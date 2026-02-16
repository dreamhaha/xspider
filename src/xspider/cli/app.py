"""Typer main application for xspider CLI.

xspider CLI主应用程序 - 使用Typer框架构建的命令行界面
"""

from __future__ import annotations

import typer
from rich.console import Console

from xspider import __version__
from xspider.cli.commands import admin, audit, crawl, export, rank, seed

console = Console()

app = typer.Typer(
    name="xspider",
    help="Twitter/X KOL Discovery System - 发现和分析Twitter/X上的关键意见领袖",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# Register sub-commands / 注册子命令
app.add_typer(seed.app, name="seed", help="Seed collection commands / 种子采集命令")
app.add_typer(crawl.app, name="crawl", help="Web crawling commands / 网络爬取命令")
app.add_typer(rank.app, name="rank", help="PageRank ranking commands / PageRank排名命令")
app.add_typer(audit.app, name="audit", help="AI audit commands / AI审核命令")
app.add_typer(export.app, name="export", help="Export commands / 导出命令")
app.add_typer(admin.app, name="admin", help="Admin server commands / 后台管理命令")


def version_callback(value: bool) -> None:
    """Display version and exit. / 显示版本并退出"""
    if value:
        console.print(f"[bold blue]xspider[/bold blue] version [green]{__version__}[/green]")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit. / 显示版本并退出",
    ),
) -> None:
    """
    xspider - Twitter/X KOL Discovery System

    A powerful tool for discovering and analyzing Key Opinion Leaders on Twitter/X.

    xspider - Twitter/X KOL发现系统

    用于发现和分析Twitter/X上关键意见领袖的强大工具。
    """
    pass


def main() -> None:
    """Entry point for the CLI. / CLI入口点"""
    app()


if __name__ == "__main__":
    main()
