"""PageRank ranking commands for xspider.

PageRank排名命令 - 计算和分析用户影响力排名
"""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from xspider.core.config import get_settings

console = Console()
app = typer.Typer(
    name="rank",
    help="PageRank ranking commands / PageRank排名命令",
    no_args_is_help=True,
)


async def _compute_pagerank(
    damping: float,
    iterations: int,
    convergence: float,
    progress: Progress,
    task_id: int,
) -> dict:
    """Compute PageRank scores.

    计算PageRank分数
    """
    # TODO: Implement actual PageRank computation
    progress.update(task_id, total=iterations)

    for i in range(iterations):
        await asyncio.sleep(0.05)  # Simulated computation
        progress.update(task_id, completed=i + 1)

    # Return mock results
    return {
        "total_nodes": 1234,
        "total_edges": 5678,
        "iterations_run": iterations,
        "converged": True,
    }


@app.command("compute")
def compute(
    damping: float = typer.Option(
        0.85,
        "--damping",
        "-d",
        help="Damping factor for PageRank / PageRank阻尼系数",
        min=0.0,
        max=1.0,
    ),
    iterations: int = typer.Option(
        100,
        "--iterations",
        "-i",
        help="Maximum iterations / 最大迭代次数",
        min=1,
        max=1000,
    ),
    convergence: float = typer.Option(
        1e-6,
        "--convergence",
        "-c",
        help="Convergence threshold / 收敛阈值",
    ),
) -> None:
    """
    Compute PageRank scores for all users.

    为所有用户计算PageRank分数。

    Example / 示例:
        xspider rank compute --damping 0.85 --iterations 100
    """
    console.print(Panel(
        f"[bold]PageRank Configuration / PageRank配置[/bold]\n\n"
        f"Damping Factor / 阻尼系数: [cyan]{damping}[/cyan]\n"
        f"Max Iterations / 最大迭代: [cyan]{iterations}[/cyan]\n"
        f"Convergence / 收敛阈值: [cyan]{convergence}[/cyan]",
        title="Computing PageRank / 计算PageRank",
    ))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Computing PageRank / 计算PageRank中...", total=None)

        result = asyncio.run(_compute_pagerank(
            damping=damping,
            iterations=iterations,
            convergence=convergence,
            progress=progress,
            task_id=task_id,
        ))

    # Display results
    table = Table(title="PageRank Results / PageRank结果")
    table.add_column("Metric / 指标", style="cyan")
    table.add_column("Value / 值", style="green", justify="right")

    table.add_row("Total Nodes / 总节点数", f"{result['total_nodes']:,}")
    table.add_row("Total Edges / 总边数", f"{result['total_edges']:,}")
    table.add_row("Iterations / 迭代次数", f"{result['iterations_run']:,}")
    table.add_row("Converged / 已收敛", "[green]Yes[/green]" if result["converged"] else "[red]No[/red]")

    console.print(table)
    console.print("\n[green]PageRank computation completed / PageRank计算完成[/green]")


@app.command("top")
def top(
    limit: int = typer.Option(
        100,
        "--top",
        "-t",
        help="Number of top users to show / 显示的前N名用户",
        min=1,
        max=1000,
    ),
    find_hidden: bool = typer.Option(
        False,
        "--find-hidden",
        "-h",
        help="Find hidden gems (high rank, low followers) / 发现隐藏宝石 (高排名,低粉丝)",
    ),
    min_followers: Optional[int] = typer.Option(
        None,
        "--min-followers",
        "-m",
        help="Minimum follower count filter / 最小粉丝数筛选",
    ),
    max_followers: Optional[int] = typer.Option(
        None,
        "--max-followers",
        "-M",
        help="Maximum follower count filter / 最大粉丝数筛选",
    ),
) -> None:
    """
    Show top ranked users.

    显示排名靠前的用户。

    Example / 示例:
        xspider rank top --top 100
        xspider rank top --find-hidden --top 50
    """
    if find_hidden:
        console.print("[bold magenta]Finding hidden gems... / 寻找隐藏宝石...[/bold magenta]")
        # Hidden gems have high PageRank but low followers
        max_followers = max_followers or 10000

    # TODO: Fetch from database
    # Mock data
    users = []
    for i in range(min(limit, 50)):
        score = 1.0 - (i * 0.01)
        followers = 100000 - (i * 1000) if not find_hidden else 5000 - (i * 50)
        users.append({
            "rank": i + 1,
            "username": f"top_user_{i + 1}",
            "display_name": f"Top User {i + 1}",
            "pagerank": score,
            "followers": max(followers, 100),
            "following": 500 + i * 10,
        })

    # Filter by followers
    if min_followers:
        users = [u for u in users if u["followers"] >= min_followers]
    if max_followers:
        users = [u for u in users if u["followers"] <= max_followers]

    table = Table(title="Top Ranked Users / 排名靠前的用户" + (" (Hidden Gems / 隐藏宝石)" if find_hidden else ""))
    table.add_column("Rank / 排名", justify="right", style="dim")
    table.add_column("Username / 用户名", style="cyan")
    table.add_column("Display Name / 显示名称", style="green")
    table.add_column("PageRank", justify="right", style="yellow")
    table.add_column("Followers / 粉丝", justify="right", style="magenta")
    table.add_column("Following / 关注", justify="right", style="blue")

    for user in users[:20]:  # Show first 20
        table.add_row(
            f"#{user['rank']}",
            f"@{user['username']}",
            user["display_name"],
            f"{user['pagerank']:.4f}",
            f"{user['followers']:,}",
            f"{user['following']:,}",
        )

    console.print(table)

    if len(users) > 20:
        console.print(f"[dim]... and {len(users) - 20} more / 还有 {len(users) - 20} 个用户[/dim]")

    console.print(f"\n[green]Total: {len(users)} users / 共 {len(users)} 个用户[/green]")


@app.command("analyze")
def analyze(
    username: str = typer.Argument(
        ...,
        help="Username to analyze / 要分析的用户名",
    ),
) -> None:
    """
    Analyze a specific user's rank and connections.

    分析特定用户的排名和连接。

    Example / 示例:
        xspider rank analyze elonmusk
    """
    username = username.lstrip("@")

    console.print(f"[bold blue]Analyzing user / 分析用户:[/bold blue] @{username}")

    # TODO: Fetch from database
    # Mock data
    user_data = {
        "username": username,
        "display_name": f"User {username}",
        "pagerank": 0.0123,
        "global_rank": 42,
        "followers": 12345,
        "following": 678,
        "top_connections": [
            {"username": "connection_1", "pagerank": 0.05},
            {"username": "connection_2", "pagerank": 0.04},
            {"username": "connection_3", "pagerank": 0.03},
        ],
    }

    # User info panel
    console.print(Panel(
        f"[bold]@{user_data['username']}[/bold] - {user_data['display_name']}\n\n"
        f"PageRank Score / PageRank分数: [yellow]{user_data['pagerank']:.6f}[/yellow]\n"
        f"Global Rank / 全局排名: [cyan]#{user_data['global_rank']}[/cyan]\n"
        f"Followers / 粉丝: [green]{user_data['followers']:,}[/green]\n"
        f"Following / 关注: [blue]{user_data['following']:,}[/blue]",
        title="User Analysis / 用户分析",
    ))

    # Top connections
    table = Table(title="Top Connections / 主要连接")
    table.add_column("Username / 用户名", style="cyan")
    table.add_column("PageRank", justify="right", style="yellow")

    for conn in user_data["top_connections"]:
        table.add_row(f"@{conn['username']}", f"{conn['pagerank']:.4f}")

    console.print(table)


@app.command("compare")
def compare(
    users: str = typer.Argument(
        ...,
        help="Comma-separated usernames to compare / 逗号分隔的用户名",
    ),
) -> None:
    """
    Compare rankings of multiple users.

    比较多个用户的排名。

    Example / 示例:
        xspider rank compare "user1,user2,user3"
    """
    user_list = [u.strip().lstrip("@") for u in users.split(",") if u.strip()]

    if len(user_list) < 2:
        console.print("[red]Error: Please provide at least 2 users to compare / 错误: 请提供至少2个用户进行比较[/red]")
        raise typer.Exit(1)

    console.print(f"[bold blue]Comparing users / 比较用户:[/bold blue] {', '.join(f'@{u}' for u in user_list)}")

    # TODO: Fetch from database
    # Mock data
    table = Table(title="User Comparison / 用户比较")
    table.add_column("Username / 用户名", style="cyan")
    table.add_column("PageRank", justify="right", style="yellow")
    table.add_column("Rank / 排名", justify="right", style="green")
    table.add_column("Followers / 粉丝", justify="right", style="magenta")

    for i, username in enumerate(user_list):
        table.add_row(
            f"@{username}",
            f"{0.05 - (i * 0.01):.4f}",
            f"#{10 + i * 5}",
            f"{50000 - (i * 5000):,}",
        )

    console.print(table)


# Default behavior when running "xspider rank --find-hidden --top 100"
@app.callback(invoke_without_command=True)
def rank_callback(
    ctx: typer.Context,
    find_hidden: bool = typer.Option(
        False,
        "--find-hidden",
        help="Find hidden gems (high rank, low followers) / 发现隐藏宝石",
    ),
    top_count: int = typer.Option(
        100,
        "--top",
        help="Number of top users to show / 显示的前N名用户",
        min=1,
        max=1000,
    ),
) -> None:
    """
    PageRank ranking commands for analyzing KOL influence.

    PageRank排名命令 - 用于分析KOL影响力。

    When called without a subcommand, shows top ranked users.
    不带子命令调用时,显示排名靠前的用户。
    """
    if ctx.invoked_subcommand is None:
        top(limit=top_count, find_hidden=find_hidden, min_followers=None, max_followers=None)


if __name__ == "__main__":
    app()
