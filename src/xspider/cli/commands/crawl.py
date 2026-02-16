"""Web crawling commands for xspider.

网络爬取命令 - 从种子用户开始爬取社交网络图谱
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

import typer
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table

from xspider.core.config import get_settings

console = Console()
app = typer.Typer(
    name="crawl",
    help="Web crawling commands / 网络爬取命令",
    no_args_is_help=True,
)


class CrawlStats:
    """Crawl statistics tracker. / 爬取统计跟踪器"""

    def __init__(self) -> None:
        self.users_crawled: int = 0
        self.edges_discovered: int = 0
        self.errors: int = 0
        self.start_time: datetime = datetime.now()

    def generate_table(self) -> Table:
        """Generate a stats table. / 生成统计表格"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        rate = self.users_crawled / elapsed if elapsed > 0 else 0

        table = Table(title="Crawl Statistics / 爬取统计", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")

        table.add_row("Users Crawled / 已爬取用户", f"{self.users_crawled:,}")
        table.add_row("Edges Discovered / 发现的边", f"{self.edges_discovered:,}")
        table.add_row("Errors / 错误", f"{self.errors:,}")
        table.add_row("Rate / 速率", f"{rate:.2f} users/sec")
        table.add_row("Elapsed / 已用时间", f"{elapsed:.1f}s")

        return table


async def _run_crawl(
    depth: int,
    concurrency: int,
    delay_ms: int,
    max_followings: int,
    stats: CrawlStats,
    progress: Progress,
    task_id: int,
) -> None:
    """Run the crawl process.

    运行爬取过程
    """
    # TODO: Implement actual crawling logic
    # 模拟爬取过程
    total_users = 100
    progress.update(task_id, total=total_users)

    for i in range(total_users):
        await asyncio.sleep(delay_ms / 1000 / 10)  # Simulated delay
        stats.users_crawled += 1
        stats.edges_discovered += 5 + (i % 10)
        if i % 20 == 19:
            stats.errors += 1
        progress.update(task_id, completed=i + 1)


@app.command("start")
def start(
    depth: int = typer.Option(
        2,
        "--depth",
        "-d",
        help="Crawl depth (levels of following) / 爬取深度 (关注层级)",
        min=1,
        max=5,
    ),
    concurrency: int = typer.Option(
        5,
        "--concurrency",
        "-c",
        help="Number of concurrent requests / 并发请求数",
        min=1,
        max=20,
    ),
    delay: int = typer.Option(
        1000,
        "--delay",
        help="Delay between requests in ms / 请求间隔 (毫秒)",
        min=100,
        max=10000,
    ),
    max_followings: int = typer.Option(
        500,
        "--max-followings",
        "-m",
        help="Max followings to fetch per user / 每用户最大关注数",
        min=10,
        max=5000,
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Resume from last checkpoint / 从上次检查点恢复",
    ),
) -> None:
    """
    Start crawling from seed users.

    从种子用户开始爬取。

    Example / 示例:
        xspider crawl start --depth 2 --concurrency 5
    """
    settings = get_settings()

    console.print(Panel(
        f"[bold]Crawl Configuration / 爬取配置[/bold]\n\n"
        f"Depth / 深度: [cyan]{depth}[/cyan]\n"
        f"Concurrency / 并发数: [cyan]{concurrency}[/cyan]\n"
        f"Delay / 间隔: [cyan]{delay}ms[/cyan]\n"
        f"Max Followings / 最大关注数: [cyan]{max_followings}[/cyan]\n"
        f"Resume / 恢复: [cyan]{resume}[/cyan]",
        title="xspider Crawl",
    ))

    stats = CrawlStats()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Crawling / 爬取中...", total=None)

        asyncio.run(_run_crawl(
            depth=depth,
            concurrency=concurrency,
            delay_ms=delay,
            max_followings=max_followings,
            stats=stats,
            progress=progress,
            task_id=task_id,
        ))

    console.print("\n")
    console.print(stats.generate_table())
    console.print("\n[green]Crawl completed successfully / 爬取成功完成[/green]")


@app.command("status")
def status() -> None:
    """
    Show current crawl status.

    显示当前爬取状态。

    Example / 示例:
        xspider crawl status
    """
    # TODO: Fetch from database/state
    table = Table(title="Crawl Status / 爬取状态")
    table.add_column("Metric / 指标", style="cyan")
    table.add_column("Value / 值", style="green", justify="right")

    table.add_row("Status / 状态", "[yellow]Idle / 空闲[/yellow]")
    table.add_row("Last Run / 上次运行", "2024-01-15 10:30:00")
    table.add_row("Total Users / 总用户数", "1,234")
    table.add_row("Total Edges / 总边数", "5,678")
    table.add_row("Pending Users / 待处理用户", "456")

    console.print(table)


@app.command("stop")
def stop(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force stop without saving checkpoint / 强制停止,不保存检查点",
    ),
) -> None:
    """
    Stop the current crawl.

    停止当前爬取。

    Example / 示例:
        xspider crawl stop
        xspider crawl stop --force
    """
    if force:
        console.print("[yellow]Force stopping crawl... / 强制停止爬取...[/yellow]")
    else:
        console.print("[yellow]Stopping crawl and saving checkpoint... / 停止爬取并保存检查点...[/yellow]")

    # TODO: Implement actual stop logic
    console.print("[green]Crawl stopped / 爬取已停止[/green]")


@app.command("reset")
def reset(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation / 跳过确认",
    ),
) -> None:
    """
    Reset crawl state and data.

    重置爬取状态和数据。

    Example / 示例:
        xspider crawl reset --force
    """
    if not force:
        confirm = typer.confirm(
            "This will delete all crawled data. Continue? / 这将删除所有爬取数据。继续吗?"
        )
        if not confirm:
            console.print("[yellow]Cancelled / 已取消[/yellow]")
            raise typer.Exit(0)

    # TODO: Implement actual reset logic
    console.print("[green]Crawl state reset / 爬取状态已重置[/green]")


# Default command - make "xspider crawl" work like "xspider crawl start"
@app.callback(invoke_without_command=True)
def crawl_callback(
    ctx: typer.Context,
    depth: int = typer.Option(
        2,
        "--depth",
        "-d",
        help="Crawl depth (levels of following) / 爬取深度 (关注层级)",
        min=1,
        max=5,
    ),
    concurrency: int = typer.Option(
        5,
        "--concurrency",
        "-c",
        help="Number of concurrent requests / 并发请求数",
        min=1,
        max=20,
    ),
) -> None:
    """
    Web crawling commands for discovering KOL networks.

    网络爬取命令 - 用于发现KOL网络。

    When called without a subcommand, starts crawling with the given options.
    不带子命令调用时,使用给定选项开始爬取。
    """
    if ctx.invoked_subcommand is None:
        # Called without subcommand - run start
        start(
            depth=depth,
            concurrency=concurrency,
            delay=1000,
            max_followings=500,
            resume=False,
        )


if __name__ == "__main__":
    app()
