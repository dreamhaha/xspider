#!/usr/bin/env python3
"""
完整 KOL 发现工作流

使用方法:
    python scripts/run_full_pipeline.py --keywords "AI,LLM" --limit 100
"""

import asyncio
import sys
import json
import csv
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich.panel import Panel

console = Console()


@dataclass
class PipelineStats:
    """Pipeline statistics"""
    seeds_found: int = 0
    users_crawled: int = 0
    edges_collected: int = 0
    users_ranked: int = 0
    hidden_found: int = 0
    users_audited: int = 0
    relevant_users: int = 0
    start_time: datetime = field(default_factory=datetime.now)


async def run_pipeline(
    keywords: list[str],
    target_seeds: int = 100,
    crawl_depth: int = 2,
    max_followings: int = 100,
    industry: str = "AI/人工智能",
):
    """Run the full KOL discovery pipeline"""

    stats = PipelineStats()

    console.print(Panel(
        f"[bold]KOL Discovery Pipeline[/bold]\n\n"
        f"Keywords: [cyan]{', '.join(keywords)}[/cyan]\n"
        f"Target Seeds: [cyan]{target_seeds}[/cyan]\n"
        f"Crawl Depth: [cyan]{crawl_depth}[/cyan]\n"
        f"Industry: [cyan]{industry}[/cyan]",
        title="🚀 xspider",
    ))

    # Import modules
    from xspider.twitter.client import TwitterGraphQLClient
    from xspider.ai.client import create_llm_client
    from xspider.ai.models import LLMProvider
    from xspider.storage.database import Database, init_database
    from xspider.storage.models import User, Edge, Ranking, Audit
    from sqlalchemy import select, func
    import networkx as nx
    import math

    # Initialize
    db = await init_database()
    twitter = TwitterGraphQLClient.from_settings()

    all_users = {}  # user_id -> user_data
    all_edges = []  # (source_id, target_id)

    # =========================================
    # STEP 1: Seed Collection
    # =========================================
    console.print("\n[bold blue]📡 Step 1: Seed Collection[/bold blue]")

    seed_users = []
    seen_ids = set()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Searching for seeds...", total=target_seeds)

        for keyword in keywords:
            if len(seed_users) >= target_seeds:
                break

            progress.update(task, description=f"Searching '{keyword}'...")

            try:
                # 使用搜索或获取知名用户
                # 由于 Twitter Search API 限制，我们用已知的 AI 领域用户作为种子
                known_ai_users = [
                    "sama", "elonmusk", "ylecun", "kaborakim", "AndrewYNg",
                    "demaborges", "OpenAI", "DeepMind", "GoogleAI", "anthroploic",
                    "GaryMarcus", "fchollet", "goodfellow_ian", "hardmaru", "drfeifei",
                    "jeffdean", "iaborrakim", "ch402", "ClementDelangue", "huggingface",
                    "StabilityAI", "midaborakim", "llama_index", "LangChainAI", "pinaborakim",
                ]

                for username in known_ai_users:
                    if len(seed_users) >= target_seeds:
                        break

                    try:
                        user = await twitter.get_user_by_screen_name(username)
                        if user.rest_id not in seen_ids:
                            seen_ids.add(user.rest_id)
                            seed_users.append(user)
                            all_users[user.rest_id] = {
                                "id": user.rest_id,
                                "screen_name": user.screen_name,
                                "name": user.name,
                                "description": user.description,
                                "followers_count": user.followers_count,
                                "following_count": user.following_count,
                                "is_seed": True,
                                "depth": 0,
                            }
                            stats.seeds_found += 1
                            progress.update(task, completed=len(seed_users))

                    except Exception as e:
                        pass  # Skip invalid users

                    await asyncio.sleep(0.5)  # Rate limiting

            except Exception as e:
                console.print(f"[yellow]Warning: {e}[/yellow]")

    console.print(f"   ✅ Found [green]{stats.seeds_found}[/green] seed users")

    # Show sample seeds
    table = Table(title="Sample Seeds")
    table.add_column("Username", style="cyan")
    table.add_column("Name")
    table.add_column("Followers", justify="right")

    for user in seed_users[:10]:
        table.add_row(f"@{user.screen_name}", user.name, f"{user.followers_count:,}")
    console.print(table)

    # =========================================
    # STEP 2: Crawl Following Network
    # =========================================
    console.print("\n[bold blue]📡 Step 2: Crawl Following Network[/bold blue]")

    # BFS queue: (user_id, depth)
    queue = [(u.rest_id, 0) for u in seed_users]
    visited = set(u.rest_id for u in seed_users)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Crawling network...", total=len(queue) * 2)

        processed = 0
        while queue and processed < 50:  # Limit for demo
            user_id, depth = queue.pop(0)

            if depth >= crawl_depth:
                continue

            progress.update(task, description=f"Crawling user {user_id[:8]}... (depth={depth})")

            try:
                count = 0
                async for following in twitter.iter_following(user_id, max_users=max_followings):
                    # Add edge
                    all_edges.append((user_id, following.rest_id))
                    stats.edges_collected += 1

                    # Add user if new
                    if following.rest_id not in visited:
                        visited.add(following.rest_id)
                        all_users[following.rest_id] = {
                            "id": following.rest_id,
                            "screen_name": following.screen_name,
                            "name": following.name,
                            "description": following.description,
                            "followers_count": following.followers_count,
                            "following_count": following.following_count,
                            "is_seed": False,
                            "depth": depth + 1,
                        }

                        # Add to queue for next level
                        if depth + 1 < crawl_depth:
                            queue.append((following.rest_id, depth + 1))

                    count += 1
                    if count >= max_followings:
                        break

                stats.users_crawled += 1
                processed += 1
                progress.update(task, completed=processed, total=max(len(queue) + processed, processed))

            except Exception as e:
                console.print(f"[yellow]Warning crawling {user_id}: {e}[/yellow]")

            await asyncio.sleep(0.3)

    console.print(f"   ✅ Crawled [green]{stats.users_crawled}[/green] users")
    console.print(f"   ✅ Collected [green]{stats.edges_collected}[/green] edges")
    console.print(f"   ✅ Total users: [green]{len(all_users)}[/green]")

    # =========================================
    # STEP 3: PageRank Calculation
    # =========================================
    console.print("\n[bold blue]📡 Step 3: PageRank Calculation[/bold blue]")

    # Build graph
    G = nx.DiGraph()
    for user_id, user_data in all_users.items():
        G.add_node(user_id, **user_data)
    for source, target in all_edges:
        if source in G and target in G:
            G.add_edge(source, target)

    console.print(f"   Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    # Calculate PageRank
    if G.number_of_nodes() > 0:
        pagerank = nx.pagerank(G, alpha=0.85)
        stats.users_ranked = len(pagerank)

        # Calculate hidden score
        rankings = []
        seed_ids = set(u.rest_id for u in seed_users)

        for user_id, pr_score in pagerank.items():
            user_data = all_users.get(user_id, {})
            followers = user_data.get("followers_count", 0)

            # Count how many seeds follow this user
            seed_followers = sum(1 for s in seed_ids if G.has_edge(s, user_id))

            # Hidden score = PR / log(followers + 2)
            hidden_score = pr_score / math.log(followers + 2) if followers < 100000 else 0

            rankings.append({
                "user_id": user_id,
                "screen_name": user_data.get("screen_name", ""),
                "name": user_data.get("name", ""),
                "followers_count": followers,
                "pagerank": pr_score,
                "hidden_score": hidden_score,
                "seed_followers": seed_followers,
                "in_degree": G.in_degree(user_id),
                "is_seed": user_data.get("is_seed", False),
            })

        # Sort by PageRank
        rankings.sort(key=lambda x: x["pagerank"], reverse=True)

        # Find hidden gems
        hidden_gems = [r for r in rankings if r["hidden_score"] > 0 and not r["is_seed"]]
        hidden_gems.sort(key=lambda x: x["hidden_score"], reverse=True)
        stats.hidden_found = len(hidden_gems[:20])

        console.print(f"   ✅ Ranked [green]{stats.users_ranked}[/green] users")

        # Show top by PageRank
        table = Table(title="Top 10 by PageRank")
        table.add_column("Rank", justify="right")
        table.add_column("Username", style="cyan")
        table.add_column("Followers", justify="right")
        table.add_column("PageRank", justify="right")

        for i, r in enumerate(rankings[:10], 1):
            table.add_row(
                str(i),
                f"@{r['screen_name']}",
                f"{r['followers_count']:,}",
                f"{r['pagerank']:.6f}",
            )
        console.print(table)

        # Show hidden gems
        if hidden_gems:
            console.print(f"\n   🔍 Found [green]{len(hidden_gems)}[/green] potential hidden influencers")

            table = Table(title="Top Hidden Gems (High PageRank, Lower Followers)")
            table.add_column("Username", style="cyan")
            table.add_column("Followers", justify="right")
            table.add_column("PageRank", justify="right")
            table.add_column("Hidden Score", justify="right", style="yellow")
            table.add_column("Followed by Seeds", justify="right")

            for r in hidden_gems[:10]:
                table.add_row(
                    f"@{r['screen_name']}",
                    f"{r['followers_count']:,}",
                    f"{r['pagerank']:.6f}",
                    f"{r['hidden_score']:.6f}",
                    str(r['seed_followers']),
                )
            console.print(table)

    # =========================================
    # STEP 4: AI Audit (Top users)
    # =========================================
    console.print("\n[bold blue]📡 Step 4: AI Audit with Kimi[/bold blue]")

    kimi = create_llm_client(provider=LLMProvider.KIMI)

    # Audit top 20 users
    audit_candidates = rankings[:20] if rankings else []
    audit_results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Auditing users...", total=len(audit_candidates))

        for i, candidate in enumerate(audit_candidates):
            progress.update(task, description=f"Auditing @{candidate['screen_name']}...")

            try:
                user_data = all_users.get(candidate["user_id"], {})

                prompt = f"""判断这个Twitter用户是否是 {industry} 行业的KOL。

用户: @{candidate['screen_name']}
名称: {candidate['name']}
简介: {user_data.get('description', '')}
粉丝: {candidate['followers_count']:,}
PageRank排名: {i + 1}

返回JSON: {{"is_relevant": true/false, "relevance_score": 1-10, "topics": [], "tags": [], "reasoning": "简短理由"}}"""

                result = await kimi.complete_json(
                    prompt=prompt,
                    system_prompt="你是社交媒体分析师。用JSON回答。",
                    max_tokens=300,
                )

                audit_results.append({
                    **candidate,
                    "is_relevant": result.get("is_relevant", False),
                    "relevance_score": result.get("relevance_score", 0),
                    "topics": result.get("topics", []),
                    "tags": result.get("tags", []),
                    "reasoning": result.get("reasoning", ""),
                })

                stats.users_audited += 1
                if result.get("is_relevant"):
                    stats.relevant_users += 1

            except Exception as e:
                console.print(f"[yellow]Audit error for {candidate['screen_name']}: {e}[/yellow]")

            progress.update(task, completed=i + 1)
            await asyncio.sleep(0.5)

    await kimi.close()

    console.print(f"   ✅ Audited [green]{stats.users_audited}[/green] users")
    console.print(f"   ✅ Relevant: [green]{stats.relevant_users}[/green]")

    # Show audit results
    table = Table(title="AI Audit Results")
    table.add_column("Username", style="cyan")
    table.add_column("Score", justify="center")
    table.add_column("Relevant", justify="center")
    table.add_column("Topics")
    table.add_column("Reasoning")

    for r in audit_results[:15]:
        relevant = "[green]✓[/green]" if r.get("is_relevant") else "[red]✗[/red]"
        topics = ", ".join(r.get("topics", [])[:3])
        reasoning = r.get("reasoning", "")[:40] + "..." if len(r.get("reasoning", "")) > 40 else r.get("reasoning", "")
        table.add_row(
            f"@{r['screen_name']}",
            f"{r.get('relevance_score', 0)}/10",
            relevant,
            topics,
            reasoning,
        )
    console.print(table)

    # =========================================
    # STEP 5: Export Results
    # =========================================
    console.print("\n[bold blue]📡 Step 5: Export Results[/bold blue]")

    # Export to CSV
    export_dir = Path("data/exports")
    export_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Export rankings
    rankings_file = export_dir / f"rankings_{timestamp}.csv"
    with open(rankings_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "rank", "user_id", "screen_name", "name", "followers_count",
            "pagerank", "hidden_score", "seed_followers", "is_seed"
        ])
        writer.writeheader()
        for i, r in enumerate(rankings[:100], 1):
            writer.writerow({
                "rank": i,
                "user_id": r["user_id"],
                "screen_name": r["screen_name"],
                "name": r["name"],
                "followers_count": r["followers_count"],
                "pagerank": f"{r['pagerank']:.8f}",
                "hidden_score": f"{r['hidden_score']:.8f}",
                "seed_followers": r["seed_followers"],
                "is_seed": r["is_seed"],
            })

    console.print(f"   ✅ Rankings exported: [cyan]{rankings_file}[/cyan]")

    # Export audit results
    audit_file = export_dir / f"audit_{timestamp}.csv"
    with open(audit_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "screen_name", "name", "followers_count", "pagerank",
            "is_relevant", "relevance_score", "topics", "tags", "reasoning"
        ])
        writer.writeheader()
        for r in audit_results:
            writer.writerow({
                "screen_name": r["screen_name"],
                "name": r["name"],
                "followers_count": r["followers_count"],
                "pagerank": f"{r['pagerank']:.8f}",
                "is_relevant": r.get("is_relevant", False),
                "relevance_score": r.get("relevance_score", 0),
                "topics": "|".join(r.get("topics", [])),
                "tags": "|".join(r.get("tags", [])),
                "reasoning": r.get("reasoning", ""),
            })

    console.print(f"   ✅ Audit results exported: [cyan]{audit_file}[/cyan]")

    # Export hidden gems
    hidden_file = export_dir / f"hidden_gems_{timestamp}.csv"
    with open(hidden_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "screen_name", "name", "followers_count", "pagerank",
            "hidden_score", "seed_followers"
        ])
        writer.writeheader()
        for r in hidden_gems[:50]:
            writer.writerow({
                "screen_name": r["screen_name"],
                "name": r["name"],
                "followers_count": r["followers_count"],
                "pagerank": f"{r['pagerank']:.8f}",
                "hidden_score": f"{r['hidden_score']:.8f}",
                "seed_followers": r["seed_followers"],
            })

    console.print(f"   ✅ Hidden gems exported: [cyan]{hidden_file}[/cyan]")

    # =========================================
    # Summary
    # =========================================
    elapsed = (datetime.now() - stats.start_time).total_seconds()

    console.print("\n" + "="*60)
    console.print("[bold green]🎉 Pipeline Complete![/bold green]")
    console.print("="*60)

    summary = Table(title="Pipeline Summary", show_header=False)
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", style="green", justify="right")

    summary.add_row("Seeds Found", f"{stats.seeds_found}")
    summary.add_row("Users Crawled", f"{stats.users_crawled}")
    summary.add_row("Edges Collected", f"{stats.edges_collected}")
    summary.add_row("Total Users", f"{len(all_users)}")
    summary.add_row("Users Ranked", f"{stats.users_ranked}")
    summary.add_row("Hidden Gems Found", f"{stats.hidden_found}")
    summary.add_row("Users Audited", f"{stats.users_audited}")
    summary.add_row("Relevant Users", f"{stats.relevant_users}")
    summary.add_row("Time Elapsed", f"{elapsed:.1f}s")

    console.print(summary)

    console.print(f"\n📁 Results exported to: [cyan]data/exports/[/cyan]")

    await twitter.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run full KOL discovery pipeline")
    parser.add_argument("--keywords", default="AI,LLM", help="Comma-separated keywords")
    parser.add_argument("--limit", type=int, default=100, help="Target number of seeds")
    parser.add_argument("--depth", type=int, default=2, help="Crawl depth")
    parser.add_argument("--industry", default="AI/人工智能", help="Industry for audit")

    args = parser.parse_args()

    keywords = [k.strip() for k in args.keywords.split(",")]

    asyncio.run(run_pipeline(
        keywords=keywords,
        target_seeds=args.limit,
        crawl_depth=args.depth,
        industry=args.industry,
    ))
