"""Link extraction from user bios and Linktree-style pages."""

from __future__ import annotations

import re
import asyncio
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from xspider.core import get_logger

logger = get_logger(__name__)

# Common link aggregator domains
LINK_AGGREGATOR_DOMAINS = {
    "linktr.ee",
    "linktree.com",
    "bio.link",
    "beacons.ai",
    "linkbio.co",
    "tap.bio",
    "campsite.bio",
    "link.bio",
    "lnk.bio",
    "hoo.be",
    "stan.store",
    "allmylinks.com",
    "contactinbio.com",
    "carrd.co",
    "bio.site",
    "snipfeed.co",
    "solo.to",
    "withkoji.com",
    "msha.ke",
    "later.com",
}

# URL regex pattern
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE
)

# Twitter t.co URL pattern
TCO_PATTERN = re.compile(r'https?://t\.co/\w+', re.IGNORECASE)


@dataclass
class ExtractedLink:
    """A link extracted from bio or link aggregator page."""
    url: str
    title: str = ""
    source: str = ""  # "bio" or "linktree" etc.
    is_aggregator: bool = False


@dataclass
class LinkExtractor:
    """Extract and resolve links from user bios."""

    timeout: float = 10.0
    max_redirects: int = 5
    _client: httpx.AsyncClient | None = field(default=None, init=False)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def extract_urls_from_text(self, text: str) -> list[str]:
        """Extract all URLs from text."""
        if not text:
            return []
        return URL_PATTERN.findall(text)

    def is_link_aggregator(self, url: str) -> bool:
        """Check if URL is a link aggregator page."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain in LINK_AGGREGATOR_DOMAINS
        except Exception:
            return False

    async def resolve_tco_url(self, tco_url: str) -> str | None:
        """Resolve a t.co shortened URL to its destination."""
        try:
            client = await self._get_client()
            response = await client.head(tco_url, follow_redirects=True)
            return str(response.url)
        except Exception as e:
            logger.debug(f"Failed to resolve t.co URL {tco_url}: {e}")
            return None

    async def parse_linktree_page(self, url: str) -> list[ExtractedLink]:
        """Parse a Linktree-style page and extract all links."""
        links = []

        try:
            client = await self._get_client()
            response = await client.get(url)

            if response.status_code != 200:
                return links

            html = response.text

            # Extract links from common patterns
            # Pattern 1: href="..." with link text
            href_pattern = re.compile(
                r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>',
                re.IGNORECASE | re.DOTALL
            )

            for match in href_pattern.finditer(html):
                href, title = match.groups()
                # Filter out internal/navigation links
                if href.startswith(('http://', 'https://')) and not self._is_internal_link(href, url):
                    links.append(ExtractedLink(
                        url=href,
                        title=title.strip()[:100] if title else "",
                        source=urlparse(url).netloc,
                        is_aggregator=False,
                    ))

            # Pattern 2: JSON data in script tags (common in React apps)
            json_url_pattern = re.compile(r'"url"\s*:\s*"(https?://[^"]+)"', re.IGNORECASE)
            for match in json_url_pattern.finditer(html):
                href = match.group(1)
                if not self._is_internal_link(href, url):
                    # Avoid duplicates
                    if not any(l.url == href for l in links):
                        links.append(ExtractedLink(
                            url=href,
                            title="",
                            source=urlparse(url).netloc,
                            is_aggregator=False,
                        ))

            # Pattern 3: data-url or data-href attributes
            data_url_pattern = re.compile(
                r'data-(?:url|href)=["\']([^"\']+)["\']',
                re.IGNORECASE
            )
            for match in data_url_pattern.finditer(html):
                href = match.group(1)
                if href.startswith(('http://', 'https://')) and not self._is_internal_link(href, url):
                    if not any(l.url == href for l in links):
                        links.append(ExtractedLink(
                            url=href,
                            title="",
                            source=urlparse(url).netloc,
                            is_aggregator=False,
                        ))

        except Exception as e:
            logger.warning(f"Failed to parse linktree page {url}: {e}")

        return links

    def _is_internal_link(self, href: str, page_url: str) -> bool:
        """Check if a link is internal to the page."""
        try:
            href_domain = urlparse(href).netloc.lower()
            page_domain = urlparse(page_url).netloc.lower()

            # Same domain
            if href_domain == page_domain:
                return True

            # Common CDN/tracking domains to skip
            skip_domains = {
                'cdn.', 'static.', 'assets.', 'img.', 'images.',
                'analytics.', 'track.', 'pixel.', 'fonts.',
                'googleapis.com', 'gstatic.com', 'cloudflare.com',
                'facebook.com/tr', 'connect.facebook',
            }

            for skip in skip_domains:
                if skip in href_domain or skip in href:
                    return True

            return False
        except Exception:
            return True

    async def extract_links_from_bio(
        self,
        bio: str,
        resolve_tco: bool = True,
        parse_aggregators: bool = True,
    ) -> list[ExtractedLink]:
        """Extract all links from a user bio, resolving shortened URLs and parsing aggregators."""

        results = []
        urls = self.extract_urls_from_text(bio)

        for url in urls:
            # Resolve t.co URLs
            if TCO_PATTERN.match(url) and resolve_tco:
                resolved = await self.resolve_tco_url(url)
                if resolved:
                    url = resolved
                else:
                    continue

            # Check if it's a link aggregator
            is_aggregator = self.is_link_aggregator(url)

            results.append(ExtractedLink(
                url=url,
                title="",
                source="bio",
                is_aggregator=is_aggregator,
            ))

            # Parse link aggregator pages
            if is_aggregator and parse_aggregators:
                aggregator_links = await self.parse_linktree_page(url)
                results.extend(aggregator_links)

        return results

    async def extract_links_batch(
        self,
        users: list[dict],
        bio_field: str = "description",
        resolve_tco: bool = True,
        parse_aggregators: bool = True,
        max_concurrent: int = 5,
    ) -> dict[str, list[ExtractedLink]]:
        """Extract links from multiple user bios concurrently."""

        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}

        async def process_user(user: dict) -> tuple[str, list[ExtractedLink]]:
            user_id = user.get("id", user.get("user_id", ""))
            bio = user.get(bio_field, "")

            async with semaphore:
                links = await self.extract_links_from_bio(
                    bio,
                    resolve_tco=resolve_tco,
                    parse_aggregators=parse_aggregators,
                )
                return user_id, links

        tasks = [process_user(user) for user in users if user.get(bio_field)]

        for coro in asyncio.as_completed(tasks):
            try:
                user_id, links = await coro
                if links:
                    results[user_id] = links
            except Exception as e:
                logger.warning(f"Error extracting links: {e}")

        return results
