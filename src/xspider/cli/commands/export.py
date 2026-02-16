"""Export commands for xspider.

导出命令 - 将数据导出为各种格式
"""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from xspider.core.config import get_settings

console = Console()
app = typer.Typer(
    name="export",
    help="Export commands / 导出命令",
    no_args_is_help=True,
)


async def _fetch_export_data(
    data_type: str,
    filters: dict,
    limit: Optional[int],
) -> list[dict]:
    """Fetch data for export.

    获取导出数据
    """
    # TODO: Implement actual data fetching from database
    # Mock data
    await asyncio.sleep(0.5)

    if data_type == "users":
        return [
            {
                "username": f"user_{i}",
                "display_name": f"User {i}",
                "followers": 1000 * (i + 1),
                "following": 100 * (i + 1),
                "pagerank": 0.1 - (i * 0.001),
                "industry": ["AI", "Web3", "Crypto"][i % 3],
                "audit_score": 0.5 + (i % 5) * 0.1,
                "crawled_at": "2024-01-15",
            }
            for i in range(limit or 100)
        ]
    elif data_type == "edges":
        return [
            {
                "source": f"user_{i}",
                "target": f"user_{(i + 1) % 100}",
                "weight": 1.0,
                "discovered_at": "2024-01-15",
            }
            for i in range(limit or 500)
        ]
    elif data_type == "audit":
        return [
            {
                "username": f"user_{i}",
                "score": 0.5 + (i % 5) * 0.1,
                "passed": (0.5 + (i % 5) * 0.1) >= 0.6,
                "industry": ["AI", "Web3", "Crypto"][i % 3],
                "reason": "Relevant content detected",
                "audited_at": "2024-01-15",
            }
            for i in range(limit or 100)
        ]
    else:
        return []


def _export_to_csv(data: list[dict], output: Path) -> None:
    """Export data to CSV format.

    导出为CSV格式
    """
    if not data:
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)


def _export_to_json(data: list[dict], output: Path) -> None:
    """Export data to JSON format.

    导出为JSON格式
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _export_to_jsonl(data: list[dict], output: Path) -> None:
    """Export data to JSON Lines format.

    导出为JSONL格式
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


@app.command("users")
def export_users(
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Export format: csv, json, jsonl / 导出格式: csv, json, jsonl",
    ),
    output: Path = typer.Option(
        Path("data/exports/users.csv"),
        "--output",
        "-o",
        help="Output file path / 输出文件路径",
    ),
    min_pagerank: Optional[float] = typer.Option(
        None,
        "--min-pagerank",
        help="Minimum PageRank filter / 最低PageRank筛选",
    ),
    min_followers: Optional[int] = typer.Option(
        None,
        "--min-followers",
        help="Minimum followers filter / 最低粉丝数筛选",
    ),
    industry: Optional[str] = typer.Option(
        None,
        "--industry",
        "-i",
        help="Filter by industry / 按行业筛选",
    ),
    audit_passed: Optional[bool] = typer.Option(
        None,
        "--audit-passed/--audit-failed",
        help="Filter by audit status / 按审核状态筛选",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of records / 最大记录数",
    ),
) -> None:
    """
    Export user data.

    导出用户数据。

    Example / 示例:
        xspider export users --format csv --output results.csv
    """
    # Update output extension based on format
    if format == "json" and output.suffix != ".json":
        output = output.with_suffix(".json")
    elif format == "jsonl" and output.suffix != ".jsonl":
        output = output.with_suffix(".jsonl")
    elif format == "csv" and output.suffix != ".csv":
        output = output.with_suffix(".csv")

    console.print(Panel(
        f"[bold]Export Configuration / 导出配置[/bold]\n\n"
        f"Format / 格式: [cyan]{format}[/cyan]\n"
        f"Output / 输出: [cyan]{output}[/cyan]\n"
        f"Min PageRank: [cyan]{min_pagerank or 'None'}[/cyan]\n"
        f"Min Followers / 最低粉丝: [cyan]{min_followers or 'None'}[/cyan]\n"
        f"Industry / 行业: [cyan]{industry or 'All'}[/cyan]\n"
        f"Limit / 限制: [cyan]{limit or 'None'}[/cyan]",
        title="Export Users / 导出用户",
    ))

    filters = {
        "min_pagerank": min_pagerank,
        "min_followers": min_followers,
        "industry": industry,
        "audit_passed": audit_passed,
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching data / 获取数据中...", total=None)
        data = asyncio.run(_fetch_export_data("users", filters, limit))
        progress.update(task, completed=100, total=100)

        task2 = progress.add_task("Exporting / 导出中...", total=None)
        if format == "csv":
            _export_to_csv(data, output)
        elif format == "json":
            _export_to_json(data, output)
        elif format == "jsonl":
            _export_to_jsonl(data, output)
        else:
            console.print(f"[red]Error: Unknown format '{format}' / 错误: 未知格式 '{format}'[/red]")
            raise typer.Exit(1)
        progress.update(task2, completed=100, total=100)

    console.print(f"\n[green]Exported {len(data)} users to {output} / 已导出 {len(data)} 个用户到 {output}[/green]")


@app.command("edges")
def export_edges(
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Export format: csv, json, jsonl / 导出格式: csv, json, jsonl",
    ),
    output: Path = typer.Option(
        Path("data/exports/edges.csv"),
        "--output",
        "-o",
        help="Output file path / 输出文件路径",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of records / 最大记录数",
    ),
) -> None:
    """
    Export edge (relationship) data.

    导出边(关系)数据。

    Example / 示例:
        xspider export edges --format csv --output edges.csv
    """
    console.print(f"[bold blue]Exporting edges to {output} / 导出边到 {output}[/bold blue]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Exporting / 导出中...", total=None)
        data = asyncio.run(_fetch_export_data("edges", {}, limit))

        if format == "csv":
            _export_to_csv(data, output)
        elif format == "json":
            _export_to_json(data, output)
        elif format == "jsonl":
            _export_to_jsonl(data, output)

    console.print(f"[green]Exported {len(data)} edges / 已导出 {len(data)} 条边[/green]")


@app.command("audit")
def export_audit(
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Export format: csv, json, jsonl / 导出格式: csv, json, jsonl",
    ),
    output: Path = typer.Option(
        Path("data/exports/audit.csv"),
        "--output",
        "-o",
        help="Output file path / 输出文件路径",
    ),
    passed_only: bool = typer.Option(
        False,
        "--passed-only",
        help="Export only passed audits / 仅导出通过的审核",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of records / 最大记录数",
    ),
) -> None:
    """
    Export audit results.

    导出审核结果。

    Example / 示例:
        xspider export audit --format json --passed-only
    """
    console.print(f"[bold blue]Exporting audit results to {output} / 导出审核结果到 {output}[/bold blue]")

    filters = {"passed_only": passed_only}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task("Exporting / 导出中...", total=None)
        data = asyncio.run(_fetch_export_data("audit", filters, limit))

        if passed_only:
            data = [d for d in data if d.get("passed")]

        if format == "csv":
            _export_to_csv(data, output)
        elif format == "json":
            _export_to_json(data, output)
        elif format == "jsonl":
            _export_to_jsonl(data, output)

    console.print(f"[green]Exported {len(data)} audit results / 已导出 {len(data)} 条审核结果[/green]")


@app.command("all")
def export_all(
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Export format: csv, json / 导出格式: csv, json",
    ),
    output_dir: Path = typer.Option(
        Path("data/exports"),
        "--output-dir",
        "-o",
        help="Output directory / 输出目录",
    ),
) -> None:
    """
    Export all data (users, edges, audit).

    导出所有数据(用户、边、审核)。

    Example / 示例:
        xspider export all --format csv --output-dir ./exports
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_dir / timestamp

    console.print(f"[bold blue]Exporting all data to {output_dir} / 导出所有数据到 {output_dir}[/bold blue]")

    output_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        # Export users
        task = progress.add_task("Exporting users / 导出用户...", total=3)
        ext = "json" if format == "json" else "csv"
        users_data = asyncio.run(_fetch_export_data("users", {}, None))
        if format == "json":
            _export_to_json(users_data, output_dir / f"users.{ext}")
        else:
            _export_to_csv(users_data, output_dir / f"users.{ext}")
        progress.update(task, advance=1)

        # Export edges
        progress.update(task, description="Exporting edges / 导出边...")
        edges_data = asyncio.run(_fetch_export_data("edges", {}, None))
        if format == "json":
            _export_to_json(edges_data, output_dir / f"edges.{ext}")
        else:
            _export_to_csv(edges_data, output_dir / f"edges.{ext}")
        progress.update(task, advance=1)

        # Export audit
        progress.update(task, description="Exporting audit / 导出审核...")
        audit_data = asyncio.run(_fetch_export_data("audit", {}, None))
        if format == "json":
            _export_to_json(audit_data, output_dir / f"audit.{ext}")
        else:
            _export_to_csv(audit_data, output_dir / f"audit.{ext}")
        progress.update(task, advance=1)

    # Summary
    table = Table(title="Export Summary / 导出摘要")
    table.add_column("Data Type / 数据类型", style="cyan")
    table.add_column("Records / 记录数", justify="right", style="green")
    table.add_column("File / 文件", style="dim")

    table.add_row("Users / 用户", f"{len(users_data):,}", f"users.{ext}")
    table.add_row("Edges / 边", f"{len(edges_data):,}", f"edges.{ext}")
    table.add_row("Audit / 审核", f"{len(audit_data):,}", f"audit.{ext}")

    console.print(table)
    console.print(f"\n[green]All data exported to {output_dir} / 所有数据已导出到 {output_dir}[/green]")


# Default behavior when running "xspider export --format csv --output results.csv"
@app.callback(invoke_without_command=True)
def export_callback(
    ctx: typer.Context,
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Export format: csv, json, jsonl / 导出格式",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path / 输出文件路径",
    ),
) -> None:
    """
    Export commands for saving data to files.

    导出命令 - 用于将数据保存到文件。

    When called with --output, exports users to the specified file.
    使用--output调用时,将用户导出到指定文件。
    """
    if ctx.invoked_subcommand is None and output:
        export_users(
            format=format,
            output=output,
            min_pagerank=None,
            min_followers=None,
            industry=None,
            audit_passed=None,
            limit=None,
        )
    elif ctx.invoked_subcommand is None:
        console.print("[yellow]Please specify --output or use a subcommand / 请指定--output或使用子命令[/yellow]")
        console.print("Use 'xspider export --help' for more information / 使用 'xspider export --help' 获取更多信息")
        raise typer.Exit(0)


if __name__ == "__main__":
    app()
