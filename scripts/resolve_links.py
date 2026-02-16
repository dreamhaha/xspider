#!/usr/bin/env python3
"""
Resolve t.co shortened links and parse Linktree pages.

Usage:
    python scripts/resolve_links.py
"""

import asyncio
import sys
import csv
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel

console = Console()

# Link aggregator domains
LINK_AGGREGATOR_DOMAINS = {
    "linktr.ee", "linktree.com", "bio.link", "beacons.ai", "linkbio.co",
    "tap.bio", "campsite.bio", "link.bio", "lnk.bio", "hoo.be", "stan.store",
    "allmylinks.com", "contactinbio.com", "carrd.co", "bio.site", "snipfeed.co",
    "solo.to", "withkoji.com", "msha.ke", "later.com",
}


def is_link_aggregator(url: str) -> bool:
    """Check if URL is a link aggregator page."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        return domain in LINK_AGGREGATOR_DOMAINS
    except Exception:
        return False


async def resolve_url(client: httpx.AsyncClient, url: str) -> str | None:
    """Resolve a shortened URL to its final destination."""
    try:
        # Clean URL - remove trailing )
        url = url.rstrip(")")

        response = await client.head(url, follow_redirects=True, timeout=10.0)
        final_url = str(response.url)

        # Skip if it redirected back to Twitter
        if "twitter.com" in final_url or "x.com" in final_url:
            return None

        return final_url
    except Exception as e:
        console.print(f"[dim]Failed to resolve {url}: {e}[/dim]")
        return None


async def parse_linktree_page(client: httpx.AsyncClient, url: str) -> list[dict]:
    """Parse a Linktree-style page and extract all links."""
    links = []

    try:
        response = await client.get(url, timeout=15.0)
        if response.status_code != 200:
            return links

        html = response.text

        # Pattern 1: Standard href links
        href_pattern = re.compile(
            r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>',
            re.IGNORECASE | re.DOTALL
        )

        page_domain = urlparse(url).netloc.lower()

        for match in href_pattern.finditer(html):
            href, title = match.groups()
            if href.startswith(('http://', 'https://')):
                link_domain = urlparse(href).netloc.lower()

                # Skip internal links and common CDN/tracking
                skip_domains = ['cdn.', 'static.', 'assets.', 'analytics.',
                               'facebook.com/tr', 'googleapis.com', 'gstatic.com']

                if link_domain != page_domain and not any(s in link_domain for s in skip_domains):
                    links.append({
                        "url": href,
                        "title": title.strip()[:100] if title else "",
                    })

        # Pattern 2: JSON data (React apps like Linktree)
        json_pattern = re.compile(r'"url"\s*:\s*"(https?://[^"]+)"', re.IGNORECASE)
        for match in json_pattern.finditer(html):
            href = match.group(1)
            link_domain = urlparse(href).netloc.lower()
            if link_domain != page_domain:
                if not any(l["url"] == href for l in links):
                    links.append({"url": href, "title": ""})

    except Exception as e:
        console.print(f"[dim]Failed to parse {url}: {e}[/dim]")

    return links


async def resolve_all_links():
    """Resolve all t.co links from the extracted links file."""

    exports_dir = Path("data/exports")

    # Find the most recent extracted links file
    link_files = sorted(exports_dir.glob("extracted_links_*.csv"), reverse=True)
    bio_files = sorted(exports_dir.glob("users_with_bios_*.csv"), reverse=True)

    if not link_files:
        console.print("[red]No extracted links files found[/red]")
        return

    links_file = link_files[0]
    console.print(f"[cyan]Reading: {links_file}[/cyan]")

    # Read links
    links_data = []
    with open(links_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            links_data.append(row)

    console.print(f"[green]Found {len(links_data)} links to resolve[/green]")

    console.print(Panel(
        "[bold]Link Resolution[/bold]\n\n"
        "1. Resolve t.co shortened URLs\n"
        "2. Detect Linktree-style pages\n"
        "3. Parse aggregator pages for additional links\n"
        "4. Export resolved links",
        title="🔗 Link Resolver",
    ))

    # Create HTTP client
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*",
        },
    ) as client:

        resolved_links = []
        linktree_links = []

        # Step 1: Resolve t.co links
        console.print("\n[bold blue]📡 Step 1: Resolving shortened URLs[/bold blue]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Resolving...", total=len(links_data))

            for i, link in enumerate(links_data):
                url = link["link_url"]
                screen_name = link["screen_name"]

                progress.update(task, description=f"Resolving @{screen_name}...")

                if "t.co" in url:
                    resolved = await resolve_url(client, url)
                    if resolved:
                        is_agg = is_link_aggregator(resolved)
                        resolved_links.append({
                            **link,
                            "resolved_url": resolved,
                            "is_aggregator": is_agg,
                        })
                    else:
                        resolved_links.append({
                            **link,
                            "resolved_url": url,
                            "is_aggregator": False,
                        })
                else:
                    is_agg = is_link_aggregator(url)
                    resolved_links.append({
                        **link,
                        "resolved_url": url,
                        "is_aggregator": is_agg,
                    })

                progress.update(task, completed=i + 1)
                await asyncio.sleep(0.1)  # Rate limiting

        resolved_count = sum(1 for l in resolved_links if l["resolved_url"] != l["link_url"])
        aggregator_count = sum(1 for l in resolved_links if l["is_aggregator"])

        console.print(f"   ✅ Resolved [green]{resolved_count}[/green] shortened URLs")
        console.print(f"   ✅ Found [green]{aggregator_count}[/green] link aggregator pages")

        # Step 2: Parse aggregator pages
        if aggregator_count > 0:
            console.print("\n[bold blue]📡 Step 2: Parsing link aggregator pages[/bold blue]")

            aggregator_urls = set(
                l["resolved_url"] for l in resolved_links
                if l["is_aggregator"]
            )

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Parsing...", total=len(aggregator_urls))

                for i, agg_url in enumerate(aggregator_urls):
                    # Find the user who has this aggregator
                    owner = next(
                        (l for l in resolved_links if l["resolved_url"] == agg_url),
                        None
                    )

                    progress.update(task, description=f"Parsing {urlparse(agg_url).netloc}...")

                    try:
                        page_links = await parse_linktree_page(client, agg_url)
                        for pl in page_links:
                            linktree_links.append({
                                "screen_name": owner["screen_name"] if owner else "",
                                "aggregator_url": agg_url,
                                "extracted_url": pl["url"],
                                "link_title": pl["title"],
                            })
                    except Exception as e:
                        console.print(f"[dim]Error parsing {agg_url}: {e}[/dim]")

                    progress.update(task, completed=i + 1)
                    await asyncio.sleep(0.3)

            console.print(f"   ✅ Extracted [green]{len(linktree_links)}[/green] links from aggregator pages")

    # Show sample results
    console.print("\n[bold blue]📋 Resolved Links Sample[/bold blue]")

    table = Table(title="Resolved Links")
    table.add_column("Username", style="cyan", width=15)
    table.add_column("Original", style="dim", width=25)
    table.add_column("Resolved", style="green", width=40)
    table.add_column("Type", style="yellow")

    shown = 0
    for link in resolved_links:
        if shown >= 20:
            break
        if link["resolved_url"] != link["link_url"]:
            link_type = "🌐 Aggregator" if link["is_aggregator"] else "Link"
            resolved_short = link["resolved_url"][:50] + "..." if len(link["resolved_url"]) > 50 else link["resolved_url"]
            table.add_row(
                f"@{link['screen_name'][:12]}",
                link["link_url"][:25],
                resolved_short,
                link_type,
            )
            shown += 1

    console.print(table)

    # Show Linktree links
    if linktree_links:
        console.print("\n[bold blue]📋 Links from Aggregator Pages[/bold blue]")

        table = Table(title="Extracted Linktree Links")
        table.add_column("Username", style="cyan")
        table.add_column("Aggregator", style="dim", width=25)
        table.add_column("Link", style="green", width=40)
        table.add_column("Title", style="yellow")

        for link in linktree_links[:15]:
            agg_short = urlparse(link["aggregator_url"]).netloc
            url_short = link["extracted_url"][:45] + "..." if len(link["extracted_url"]) > 45 else link["extracted_url"]
            table.add_row(
                f"@{link['screen_name']}",
                agg_short,
                url_short,
                link["link_title"][:20] if link["link_title"] else "",
            )

        console.print(table)

    # Export results
    console.print("\n[bold blue]📡 Step 3: Export Results[/bold blue]")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Export resolved links
    resolved_file = exports_dir / f"resolved_links_{timestamp}.csv"
    with open(resolved_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "screen_name", "name", "followers_count", "original_url",
            "resolved_url", "link_source", "is_aggregator"
        ])
        writer.writeheader()
        for link in resolved_links:
            writer.writerow({
                "screen_name": link["screen_name"],
                "name": link["name"],
                "followers_count": link["followers_count"],
                "original_url": link["link_url"],
                "resolved_url": link["resolved_url"],
                "link_source": link["link_source"],
                "is_aggregator": link["is_aggregator"],
            })

    console.print(f"   ✅ Resolved links: [cyan]{resolved_file}[/cyan]")

    # Export linktree links
    if linktree_links:
        linktree_file = exports_dir / f"linktree_expanded_{timestamp}.csv"
        with open(linktree_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "screen_name", "aggregator_url", "extracted_url", "link_title"
            ])
            writer.writeheader()
            for link in linktree_links:
                writer.writerow(link)

        console.print(f"   ✅ Linktree links: [cyan]{linktree_file}[/cyan]")

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold green]🎉 Link Resolution Complete![/bold green]")
    console.print("=" * 60)

    summary = Table(title="Summary", show_header=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green", justify="right")

    summary.add_row("Total Links", str(len(links_data)))
    summary.add_row("URLs Resolved", str(resolved_count))
    summary.add_row("Aggregator Pages", str(aggregator_count))
    summary.add_row("Linktree Links", str(len(linktree_links)))

    console.print(summary)


if __name__ == "__main__":
    asyncio.run(resolve_all_links())
