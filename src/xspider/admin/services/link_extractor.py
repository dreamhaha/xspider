"""Link extraction utility for bio URLs and Linktree parsing."""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx

from xspider.core.logging import get_logger

logger = get_logger(__name__)

# Common link tree domains
LINKTREE_DOMAINS = {
    "linktr.ee",
    "linktree.com",
    "linkin.bio",
    "bio.link",
    "beacons.ai",
    "lnk.bio",
    "solo.to",
    "stan.store",
    "carrd.co",
}

# URL pattern for extracting links from text
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE
)

# Twitter t.co URL pattern
TCO_PATTERN = re.compile(r'https?://t\.co/\w+', re.IGNORECASE)

# Patterns to skip (tracking, assets, etc.)
SKIP_PATTERNS = [
    "linktr.ee/", "linktree.com/", "twitter.com/intent",
    "facebook.com/sharer", "cdn.", "static.", ".css", ".js",
    "javascript:", "mailto:", "tel:", "whatsapp:",
    "fonts.googleapis.com", "fonts.gstatic.com",
    "thanks.is/", "pxf.io/", "sjv.io/",
    "kqzyfj.com", "linksynergy.com", "wk5q.net",
    "googletagmanager.com", "google-analytics.com",
    "assets.production.linktr.ee",
]


def extract_urls_from_text(text: str | None) -> list[str]:
    """Extract all URLs from text.

    Args:
        text: The text to extract URLs from (e.g., user bio)

    Returns:
        List of extracted URLs
    """
    if not text:
        return []

    urls = URL_PATTERN.findall(text)
    # Clean up URLs (remove trailing punctuation)
    cleaned = []
    for url in urls:
        # Remove common trailing punctuation
        url = url.rstrip(".,;:!?)'\"")
        if url:
            cleaned.append(url)

    return cleaned


def expand_tco_from_entities(
    description: str | None,
    description_urls: list[dict] | None,
) -> str:
    """Expand t.co URLs in description using Twitter's entity data.

    Twitter provides expanded URLs in the description_urls field.
    This is more reliable than HTTP redirects.

    Args:
        description: The original description text with t.co URLs
        description_urls: List of URL entities from Twitter API
            Each entity has: url, expanded_url, display_url, indices

    Returns:
        Description with t.co URLs replaced by expanded URLs
    """
    if not description or not description_urls:
        return description or ""

    result = description

    # Sort by indices in reverse order to replace from end to start
    # This prevents index shifting issues
    sorted_urls = sorted(
        description_urls,
        key=lambda x: x.get("indices", [0, 0])[0],
        reverse=True
    )

    for url_entity in sorted_urls:
        tco_url = url_entity.get("url", "")
        expanded_url = url_entity.get("expanded_url", "")

        if tco_url and expanded_url:
            result = result.replace(tco_url, expanded_url)

    return result


def get_expanded_urls_from_entities(
    description_urls: list[dict] | None,
) -> list[str]:
    """Get expanded URLs from Twitter's description_urls entities.

    Args:
        description_urls: List of URL entities from Twitter API

    Returns:
        List of expanded URLs
    """
    if not description_urls:
        return []

    expanded = []
    for url_entity in description_urls:
        expanded_url = url_entity.get("expanded_url", "")
        if expanded_url:
            expanded.append(expanded_url)

    return expanded


def is_linktree_url(url: str) -> bool:
    """Check if a URL is a linktree-like service.

    Args:
        url: The URL to check

    Returns:
        True if the URL is a linktree-like service
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]

        return domain in LINKTREE_DOMAINS
    except Exception:
        return False


def should_skip_url(url: str) -> bool:
    """Check if URL should be skipped (tracking, assets, etc.)."""
    url_lower = url.lower()
    return any(skip in url_lower for skip in SKIP_PATTERNS)


async def fetch_linktree_links(url: str, client: httpx.AsyncClient) -> list[str]:
    """Fetch and parse links from a linktree-like page.

    Uses __NEXT_DATA__ JSON to extract links (more reliable than HTML parsing).

    Args:
        url: The linktree URL to fetch
        client: The HTTP client to use

    Returns:
        List of extracted links from the linktree page
    """
    links = []

    try:
        response = await client.get(url, timeout=15.0, follow_redirects=True)
        if response.status_code != 200:
            logger.debug("linktree_fetch_failed", url=url, status=response.status_code)
            return links

        html = response.text

        # Method 1: Parse __NEXT_DATA__ JSON (preferred for linktr.ee)
        next_data_match = re.search(
            r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.+?)</script>',
            html,
            re.DOTALL
        )

        if next_data_match:
            try:
                json_str = next_data_match.group(1)
                data = json.loads(json_str)

                # Navigate to links array
                props = data.get("props", {}).get("pageProps", {})
                link_list = props.get("links", [])

                for link_item in link_list:
                    link_url = link_item.get("url", "")
                    if link_url and link_url.startswith("http"):
                        if not should_skip_url(link_url):
                            links.append(link_url)

                if links:
                    logger.debug("linktree_parsed_nextdata", url=url, link_count=len(links))
                    return links

            except (json.JSONDecodeError, KeyError) as e:
                logger.debug("linktree_nextdata_parse_error", url=url, error=str(e))

        # Method 2: Fallback to href pattern matching
        href_pattern = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
        hrefs = href_pattern.findall(html)

        for href in hrefs:
            if href.startswith("#") or href.startswith("/"):
                continue
            if href.startswith("http") and not should_skip_url(href):
                links.append(href)

        # Method 3: Look for JSON url fields
        json_pattern = re.compile(r'"url"\s*:\s*"(https?://[^"]+)"', re.IGNORECASE)
        json_urls = json_pattern.findall(html)

        for json_url in json_urls:
            # Unescape JSON strings
            json_url = json_url.replace("\\u002F", "/").replace("\\/", "/")
            if json_url not in links and not should_skip_url(json_url):
                links.append(json_url)

        # Deduplicate while preserving order
        seen = set()
        unique_links = []
        for link in links:
            if link not in seen:
                seen.add(link)
                unique_links.append(link)

        logger.debug("linktree_parsed", url=url, link_count=len(unique_links))
        return unique_links

    except Exception as e:
        logger.debug("linktree_parse_error", url=url, error=str(e))
        return links


async def extract_bio_links(
    description: str | None,
    description_urls: list[dict] | None = None,
    url: str | None = None,
    parse_linktree: bool = True,
    proxy_url: str | None = None,
) -> dict:
    """Extract all links from a user's bio/description.

    This function:
    1. Uses Twitter's description_urls to get expanded URLs (preferred)
    2. Falls back to extracting URLs from description text
    3. Parses linktree-like pages to get internal links

    Args:
        description: User's bio/description text
        description_urls: Twitter's URL entities with expanded URLs
        url: User's profile URL (from Twitter user object)
        parse_linktree: Whether to parse linktree pages for internal links
        proxy_url: Optional proxy URL for HTTP requests

    Returns:
        Dict with:
        - direct_links: List of direct links found
        - linktree_links: List of links extracted from linktree pages
        - all_links: Combined list of all unique links
    """
    result = {
        "direct_links": [],
        "linktree_links": [],
        "all_links": [],
    }

    # Get expanded URLs from Twitter entities (preferred method)
    expanded_urls = get_expanded_urls_from_entities(description_urls)

    # If no entities, fall back to extracting from text
    if not expanded_urls:
        expanded_urls = extract_urls_from_text(description)

    # Add profile URL if provided
    if url:
        expanded_urls.append(url)

    if not expanded_urls:
        return result

    # Separate linktree URLs from direct links
    linktree_urls = []
    for link_url in expanded_urls:
        if is_linktree_url(link_url):
            linktree_urls.append(link_url)
        elif not should_skip_url(link_url):
            result["direct_links"].append(link_url)

    # Parse linktree pages
    if parse_linktree and linktree_urls:
        # Create HTTP client with optional proxy
        transport = None
        if proxy_url:
            transport = httpx.AsyncHTTPTransport(proxy=proxy_url)

        async with httpx.AsyncClient(
            transport=transport,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            },
        ) as client:
            for lt_url in linktree_urls:
                lt_links = await fetch_linktree_links(lt_url, client)
                result["linktree_links"].extend(lt_links)
                # Also add the linktree URL itself as a direct link
                result["direct_links"].append(lt_url)

    # Build all_links (deduplicated)
    seen = set()
    for link in result["direct_links"] + result["linktree_links"]:
        if link not in seen:
            seen.add(link)
            result["all_links"].append(link)

    return result


def serialize_links(links: list[str] | None) -> str | None:
    """Serialize links to JSON string for storage.

    Args:
        links: List of links to serialize

    Returns:
        JSON string or None if empty
    """
    if not links:
        return None
    return json.dumps(links, ensure_ascii=False)


def deserialize_links(json_str: str | None) -> list[str]:
    """Deserialize links from JSON string.

    Args:
        json_str: JSON string to deserialize

    Returns:
        List of links
    """
    if not json_str:
        return []
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return []
