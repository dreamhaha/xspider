"""Seed collection commands for xspider.

种子采集命令 - 通过关键词搜索、用户导入等方式收集初始种子用户
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from xspider.core.config import get_settings

console = Console()
app = typer.Typer(
    name="seed",
    help="Seed collection commands / 种子采集命令",
    no_args_is_help=True,
)


async def _search_seeds(
    keywords: list[str],
    limit: int,
    min_followers: int,
    verified_only: bool,
) -> list[dict]:
    """Search for seed users by keywords.

    通过关键词搜索种子用户
    """
    # TODO: Implement actual Twitter search logic
    # 模拟搜索结果
    results = []
    for i, keyword in enumerate(keywords):
        for j in range(min(limit // len(keywords), 10)):
            results.append({
                "username": f"user_{keyword.lower().replace(' ', '_')}_{j}",
                "display_name": f"User {keyword} {j}",
                "followers": min_followers + (j * 1000),
                "verified": verified_only or (j % 3 == 0),
                "keyword": keyword,
            })
    return results[:limit]


@app.command("search")
def search(
    keywords: str = typer.Option(
        ...,
        "--keywords",
        "-k",
        help="Comma-separated keywords to search / 逗号分隔的搜索关键词",
    ),
    limit: int = typer.Option(
        50,
        "--limit",
        "-l",
        help="Maximum number of seeds to collect / 最大采集数量",
        min=1,
        max=1000,
    ),
    min_followers: int = typer.Option(
        1000,
        "--min-followers",
        "-m",
        help="Minimum follower count / 最小粉丝数",
        min=0,
    ),
    verified_only: bool = typer.Option(
        False,
        "--verified-only",
        "-v",
        help="Only collect verified accounts / 仅采集认证账号",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (JSON) / 输出文件路径 (JSON格式)",
    ),
) -> None:
    """
    Search for seed users by keywords.

    通过关键词搜索种子用户。

    Example / 示例:
        xspider seed search --keywords "AI,Web3" --limit 50
    """
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

    if not keyword_list:
        console.print("[red]Error: No valid keywords provided / 错误: 未提供有效关键词[/red]")
        raise typer.Exit(1)

    console.print(f"[bold blue]Searching seeds with keywords / 使用关键词搜索种子:[/bold blue] {', '.join(keyword_list)}")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Searching / 搜索中...", total=len(keyword_list))

        results = asyncio.run(_search_seeds(
            keywords=keyword_list,
            limit=limit,
            min_followers=min_followers,
            verified_only=verified_only,
        ))

        progress.update(task, completed=len(keyword_list))

    # Display results in table
    table = Table(title="Seed Users Found / 发现的种子用户")
    table.add_column("Username / 用户名", style="cyan")
    table.add_column("Display Name / 显示名称", style="green")
    table.add_column("Followers / 粉丝数", justify="right", style="yellow")
    table.add_column("Verified / 认证", justify="center")
    table.add_column("Keyword / 关键词", style="magenta")

    for user in results[:20]:  # Show first 20
        table.add_row(
            f"@{user['username']}",
            user["display_name"],
            f"{user['followers']:,}",
            "[green]Yes[/green]" if user["verified"] else "[red]No[/red]",
            user["keyword"],
        )

    console.print(table)

    if len(results) > 20:
        console.print(f"[dim]... and {len(results) - 20} more / 还有 {len(results) - 20} 个结果[/dim]")

    console.print(f"\n[green]Found {len(results)} seed users / 找到 {len(results)} 个种子用户[/green]")

    if output:
        import json
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        console.print(f"[green]Results saved to / 结果已保存至: {output}[/green]")


@app.command("import")
def import_seeds(
    file: Path = typer.Argument(
        ...,
        help="Input file path (JSON/CSV) / 输入文件路径 (JSON/CSV格式)",
        exists=True,
        readable=True,
    ),
    format: str = typer.Option(
        "auto",
        "--format",
        "-f",
        help="File format: auto, json, csv / 文件格式: auto, json, csv",
    ),
) -> None:
    """
    Import seed users from file.

    从文件导入种子用户。

    Example / 示例:
        xspider seed import seeds.json
        xspider seed import seeds.csv --format csv
    """
    console.print(f"[bold blue]Importing seeds from / 从文件导入种子:[/bold blue] {file}")

    # Detect format
    if format == "auto":
        format = file.suffix.lstrip(".").lower()

    if format not in ("json", "csv"):
        console.print(f"[red]Error: Unsupported format '{format}' / 错误: 不支持的格式 '{format}'[/red]")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Importing / 导入中...", total=None)

        # TODO: Implement actual import logic
        if format == "json":
            import json
            with open(file, encoding="utf-8") as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else 1
        else:
            import csv
            with open(file, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                count = sum(1 for _ in reader)

    console.print(f"[green]Successfully imported {count} seeds / 成功导入 {count} 个种子[/green]")


@app.command("list")
def list_seeds(
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Maximum number of seeds to show / 最大显示数量",
        min=1,
        max=100,
    ),
    keyword: Optional[str] = typer.Option(
        None,
        "--keyword",
        "-k",
        help="Filter by keyword / 按关键词筛选",
    ),
) -> None:
    """
    List collected seed users.

    列出已采集的种子用户。

    Example / 示例:
        xspider seed list --limit 20
        xspider seed list --keyword "AI"
    """
    console.print("[bold blue]Listing seed users / 列出种子用户[/bold blue]")

    # TODO: Fetch from database
    # 模拟数据
    seeds = [
        {"username": f"seed_user_{i}", "followers": 1000 * (i + 1), "keyword": "AI" if i % 2 == 0 else "Web3"}
        for i in range(limit)
    ]

    if keyword:
        seeds = [s for s in seeds if keyword.lower() in s["keyword"].lower()]

    table = Table(title="Seed Users / 种子用户")
    table.add_column("#", justify="right", style="dim")
    table.add_column("Username / 用户名", style="cyan")
    table.add_column("Followers / 粉丝数", justify="right", style="yellow")
    table.add_column("Keyword / 关键词", style="magenta")

    for i, seed in enumerate(seeds, 1):
        table.add_row(
            str(i),
            f"@{seed['username']}",
            f"{seed['followers']:,}",
            seed["keyword"],
        )

    console.print(table)
    console.print(f"\n[dim]Total: {len(seeds)} seeds / 共 {len(seeds)} 个种子[/dim]")


@app.command("clear")
def clear_seeds(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation / 跳过确认",
    ),
) -> None:
    """
    Clear all collected seeds.

    清除所有已采集的种子。

    Example / 示例:
        xspider seed clear --force
    """
    if not force:
        confirm = typer.confirm("Are you sure you want to clear all seeds? / 确定要清除所有种子吗?")
        if not confirm:
            console.print("[yellow]Cancelled / 已取消[/yellow]")
            raise typer.Exit(0)

    # TODO: Clear from database
    console.print("[green]All seeds cleared / 所有种子已清除[/green]")


if __name__ == "__main__":
    app()
