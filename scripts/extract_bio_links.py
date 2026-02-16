#!/usr/bin/env python3
"""
Extract links from user bios and parse Linktree-style pages.

Usage:
    python scripts/extract_bio_links.py
"""

import asyncio
import sys
import csv
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel

from xspider.scraper.link_extractor import LinkExtractor, ExtractedLink

console = Console()


async def extract_links_from_rankings():
    """Extract links from the most recent rankings file."""

    # Find the most recent rankings file
    exports_dir = Path("data/exports")
    rankings_files = sorted(exports_dir.glob("rankings_*.csv"), reverse=True)

    if not rankings_files:
        console.print("[red]No rankings files found in data/exports/[/red]")
        return

    rankings_file = rankings_files[0]
    console.print(f"[cyan]Reading: {rankings_file}[/cyan]")

    # Read users from rankings
    users = []
    with open(rankings_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            users.append(row)

    console.print(f"[green]Found {len(users)} users[/green]")

    # We need to re-fetch user data to get descriptions
    # Let's read from the Twitter API
    from xspider.twitter.client import TwitterGraphQLClient
    from xspider.core import RateLimitError

    twitter = TwitterGraphQLClient.from_settings()
    extractor = LinkExtractor()

    console.print(Panel(
        "[bold]Bio Link Extraction[/bold]\n\n"
        "1. Fetch user profiles (for descriptions)\n"
        "2. Extract URLs from bios\n"
        "3. Resolve t.co shortened links\n"
        "4. Parse Linktree-style pages\n"
        "5. Export results",
        title="🔗 Link Extractor",
    ))

    # Fetch user details and extract links
    user_data = []
    all_links = {}

    # Limit to top 50 users to avoid rate limits
    users_to_process = users[:50]

    console.print(f"\n[bold blue]📡 Step 1: Fetching user profiles[/bold blue]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching...", total=len(users_to_process))

        for i, user in enumerate(users_to_process):
            screen_name = user.get("screen_name", "")
            progress.update(task, description=f"Fetching @{screen_name}...")

            try:
                profile = await twitter.get_user_by_screen_name(screen_name)
                user_info = {
                    "user_id": profile.rest_id,
                    "screen_name": profile.screen_name,
                    "name": profile.name,
                    "description": profile.description or "",
                    "followers_count": profile.followers_count,
                    "following_count": profile.following_count,
                    "url": profile.url or "",
                    "location": profile.location or "",
                    "pagerank": user.get("pagerank", ""),
                    "hidden_score": user.get("hidden_score", ""),
                }
                user_data.append(user_info)

            except RateLimitError as e:
                console.print(f"\n[yellow]Rate limited, waiting {min(e.retry_after, 60)}s...[/yellow]")
                await asyncio.sleep(min(e.retry_after, 60))
                # Retry
                try:
                    profile = await twitter.get_user_by_screen_name(screen_name)
                    user_info = {
                        "user_id": profile.rest_id,
                        "screen_name": profile.screen_name,
                        "name": profile.name,
                        "description": profile.description or "",
                        "followers_count": profile.followers_count,
                        "following_count": profile.following_count,
                        "url": profile.url or "",
                        "location": profile.location or "",
                        "pagerank": user.get("pagerank", ""),
                        "hidden_score": user.get("hidden_score", ""),
                    }
                    user_data.append(user_info)
                except Exception:
                    pass

            except Exception as e:
                console.print(f"[dim]Skipping @{screen_name}: {e}[/dim]")

            progress.update(task, completed=i + 1)
            await asyncio.sleep(0.3)

    await twitter.close()

    console.print(f"   ✅ Fetched [green]{len(user_data)}[/green] user profiles")

    # Step 2: Extract links from bios
    console.print(f"\n[bold blue]📡 Step 2: Extracting links from bios[/bold blue]")

    users_with_links = 0
    total_links = 0
    aggregator_links = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting...", total=len(user_data))

        for i, user in enumerate(user_data):
            screen_name = user.get("screen_name", "")
            description = user.get("description", "")
            profile_url = user.get("url", "")

            progress.update(task, description=f"Processing @{screen_name}...")

            links = []

            # Extract from description
            if description:
                try:
                    bio_links = await extractor.extract_links_from_bio(
                        description,
                        resolve_tco=True,
                        parse_aggregators=True,
                    )
                    links.extend(bio_links)
                except Exception as e:
                    console.print(f"[dim]Error extracting from @{screen_name}: {e}[/dim]")

            # Also check the profile URL field
            if profile_url:
                try:
                    # Resolve if it's a t.co link
                    if "t.co" in profile_url:
                        resolved = await extractor.resolve_tco_url(profile_url)
                        if resolved:
                            profile_url = resolved

                    is_agg = extractor.is_link_aggregator(profile_url)
                    links.append(ExtractedLink(
                        url=profile_url,
                        title="Profile URL",
                        source="profile",
                        is_aggregator=is_agg,
                    ))

                    # Parse if aggregator
                    if is_agg:
                        agg_links = await extractor.parse_linktree_page(profile_url)
                        links.extend(agg_links)

                except Exception as e:
                    pass

            if links:
                users_with_links += 1
                total_links += len(links)
                aggregator_links += sum(1 for l in links if l.is_aggregator)
                all_links[user["user_id"]] = {
                    "user": user,
                    "links": links,
                }

            progress.update(task, completed=i + 1)

    await extractor.close()

    console.print(f"   ✅ Users with links: [green]{users_with_links}[/green]")
    console.print(f"   ✅ Total links found: [green]{total_links}[/green]")
    console.print(f"   ✅ Aggregator pages: [green]{aggregator_links}[/green]")

    # Show sample results
    console.print("\n[bold blue]📋 Sample Results[/bold blue]")

    table = Table(title="Users with Extracted Links")
    table.add_column("Username", style="cyan")
    table.add_column("Bio", max_width=40)
    table.add_column("Links", style="yellow")

    shown = 0
    for user_id, data in all_links.items():
        if shown >= 15:
            break
        user = data["user"]
        links = data["links"]

        bio_preview = user.get("description", "")[:60] + "..." if len(user.get("description", "")) > 60 else user.get("description", "")

        link_list = []
        for link in links[:3]:
            url_short = link.url[:50] + "..." if len(link.url) > 50 else link.url
            if link.is_aggregator:
                link_list.append(f"[green]🌐 {url_short}[/green]")
            else:
                link_list.append(url_short)

        if len(links) > 3:
            link_list.append(f"[dim]+{len(links) - 3} more[/dim]")

        table.add_row(
            f"@{user.get('screen_name', '')}",
            bio_preview,
            "\n".join(link_list) if link_list else "-",
        )
        shown += 1

    console.print(table)

    # Export results
    console.print(f"\n[bold blue]📡 Step 3: Export Results[/bold blue]")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Export users with bios
    users_file = exports_dir / f"users_with_bios_{timestamp}.csv"
    with open(users_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "screen_name", "name", "description", "followers_count",
            "location", "profile_url", "pagerank", "hidden_score"
        ])
        writer.writeheader()
        for user in user_data:
            writer.writerow({
                "screen_name": user.get("screen_name", ""),
                "name": user.get("name", ""),
                "description": user.get("description", "").replace("\n", " "),
                "followers_count": user.get("followers_count", ""),
                "location": user.get("location", ""),
                "profile_url": user.get("url", ""),
                "pagerank": user.get("pagerank", ""),
                "hidden_score": user.get("hidden_score", ""),
            })

    console.print(f"   ✅ Users with bios: [cyan]{users_file}[/cyan]")

    # Export extracted links
    links_file = exports_dir / f"extracted_links_{timestamp}.csv"
    with open(links_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "screen_name", "name", "followers_count", "link_url",
            "link_title", "link_source", "is_aggregator"
        ])
        writer.writeheader()
        for user_id, data in all_links.items():
            user = data["user"]
            for link in data["links"]:
                writer.writerow({
                    "screen_name": user.get("screen_name", ""),
                    "name": user.get("name", ""),
                    "followers_count": user.get("followers_count", ""),
                    "link_url": link.url,
                    "link_title": link.title,
                    "link_source": link.source,
                    "is_aggregator": link.is_aggregator,
                })

    console.print(f"   ✅ Extracted links: [cyan]{links_file}[/cyan]")

    # Export linktree details (expanded links from aggregator pages)
    linktree_file = exports_dir / f"linktree_links_{timestamp}.csv"
    linktree_count = 0
    with open(linktree_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "screen_name", "aggregator_url", "extracted_url", "link_title"
        ])
        writer.writeheader()
        for user_id, data in all_links.items():
            user = data["user"]
            aggregator_url = None

            for link in data["links"]:
                if link.is_aggregator:
                    aggregator_url = link.url
                elif link.source not in ("bio", "profile") and aggregator_url:
                    writer.writerow({
                        "screen_name": user.get("screen_name", ""),
                        "aggregator_url": aggregator_url,
                        "extracted_url": link.url,
                        "link_title": link.title,
                    })
                    linktree_count += 1

    console.print(f"   ✅ Linktree links: [cyan]{linktree_file}[/cyan] ({linktree_count} links)")

    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold green]🎉 Link Extraction Complete![/bold green]")
    console.print("=" * 60)

    summary = Table(title="Summary", show_header=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green", justify="right")

    summary.add_row("Users Processed", str(len(user_data)))
    summary.add_row("Users with Links", str(users_with_links))
    summary.add_row("Total Links", str(total_links))
    summary.add_row("Linktree Links", str(linktree_count))

    console.print(summary)


if __name__ == "__main__":
    asyncio.run(extract_links_from_rankings())
