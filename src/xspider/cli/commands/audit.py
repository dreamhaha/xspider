"""AI audit commands for xspider.

AI审核命令 - 使用AI对用户进行行业相关性审核和评分
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.table import Table

from xspider.core.config import get_settings

console = Console()
app = typer.Typer(
    name="audit",
    help="AI audit commands / AI审核命令",
    no_args_is_help=True,
)


class AuditStats:
    """Audit statistics tracker. / 审核统计跟踪器"""

    def __init__(self) -> None:
        self.users_audited: int = 0
        self.passed: int = 0
        self.failed: int = 0
        self.errors: int = 0
        self.tokens_used: int = 0
        self.start_time: datetime = datetime.now()

    def generate_table(self) -> Table:
        """Generate a stats table. / 生成统计表格"""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        rate = self.users_audited / elapsed if elapsed > 0 else 0
        pass_rate = (self.passed / self.users_audited * 100) if self.users_audited > 0 else 0

        table = Table(title="Audit Statistics / 审核统计", show_header=False)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")

        table.add_row("Users Audited / 已审核用户", f"{self.users_audited:,}")
        table.add_row("Passed / 通过", f"[green]{self.passed:,}[/green]")
        table.add_row("Failed / 未通过", f"[red]{self.failed:,}[/red]")
        table.add_row("Pass Rate / 通过率", f"{pass_rate:.1f}%")
        table.add_row("Errors / 错误", f"{self.errors:,}")
        table.add_row("Tokens Used / 使用的Token", f"{self.tokens_used:,}")
        table.add_row("Rate / 速率", f"{rate:.2f} users/sec")

        return table


async def _run_audit(
    industry: str,
    model: str,
    batch_size: int,
    min_score: float,
    stats: AuditStats,
    progress: Progress,
    task_id: int,
) -> list[dict]:
    """Run the audit process.

    运行审核过程
    """
    # TODO: Implement actual AI audit logic
    # 模拟审核过程
    total_users = 50
    progress.update(task_id, total=total_users)

    results = []
    for i in range(total_users):
        await asyncio.sleep(0.1)  # Simulated API call

        score = 0.3 + (i % 7) * 0.1
        passed = score >= min_score

        stats.users_audited += 1
        stats.tokens_used += 150 + (i % 50)
        if passed:
            stats.passed += 1
        else:
            stats.failed += 1

        results.append({
            "username": f"user_{i + 1}",
            "score": score,
            "passed": passed,
            "industry_match": ["AI", "Tech", "Web3"][i % 3],
            "reason": "High relevance to industry" if passed else "Low relevance",
        })

        progress.update(task_id, completed=i + 1)

    return results


@app.command("run")
def run(
    industry: str = typer.Option(
        ...,
        "--industry",
        "-i",
        help="Industry to audit for / 审核的目标行业",
    ),
    provider: str = typer.Option(
        "kimi",
        "--provider",
        "-p",
        help="LLM provider: kimi, openai, anthropic / LLM提供商",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="AI model to use (auto-selected if not specified) / 使用的AI模型",
    ),
    batch_size: int = typer.Option(
        10,
        "--batch-size",
        "-b",
        help="Batch size for API calls / API调用批次大小",
        min=1,
        max=100,
    ),
    min_score: float = typer.Option(
        0.6,
        "--min-score",
        "-s",
        help="Minimum score to pass audit / 通过审核的最低分数",
        min=0.0,
        max=1.0,
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit",
        "-l",
        help="Maximum number of users to audit / 最大审核用户数",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Resume from last checkpoint / 从上次检查点恢复",
    ),
) -> None:
    """
    Run AI audit on users.

    对用户进行AI审核。

    Example / 示例:
        xspider audit run --industry "AI" --provider kimi
        xspider audit run --industry "Web3" --provider openai --model gpt-4
    """
    settings = get_settings()

    # Set default model based on provider
    if model is None:
        model = {
            "kimi": "moonshot-v1-8k",
            "openai": "gpt-4-turbo-preview",
            "anthropic": "claude-3-5-sonnet-20241022",
        }.get(provider.lower(), "moonshot-v1-8k")

    # Validate API key
    if provider.lower() == "openai" and not settings.openai_api_key:
        console.print("[red]Error: OPENAI_API_KEY not configured / 错误: 未配置OPENAI_API_KEY[/red]")
        raise typer.Exit(1)

    if provider.lower() == "anthropic" and not settings.anthropic_api_key:
        console.print("[red]Error: ANTHROPIC_API_KEY not configured / 错误: 未配置ANTHROPIC_API_KEY[/red]")
        raise typer.Exit(1)

    if provider.lower() == "kimi" and not settings.kimi_api_key:
        console.print("[red]Error: KIMI_API_KEY not configured / 错误: 未配置KIMI_API_KEY[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]Audit Configuration / 审核配置[/bold]\n\n"
        f"Industry / 行业: [cyan]{industry}[/cyan]\n"
        f"Provider / 提供商: [cyan]{provider}[/cyan]\n"
        f"Model / 模型: [cyan]{model}[/cyan]\n"
        f"Batch Size / 批次大小: [cyan]{batch_size}[/cyan]\n"
        f"Min Score / 最低分数: [cyan]{min_score}[/cyan]\n"
        f"Limit / 限制: [cyan]{limit or 'None'}[/cyan]",
        title="AI Audit / AI审核",
    ))

    stats = AuditStats()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Auditing users / 审核用户中...", total=None)

        results = asyncio.run(_run_audit(
            industry=industry,
            model=model,
            batch_size=batch_size,
            min_score=min_score,
            stats=stats,
            progress=progress,
            task_id=task_id,
        ))

    console.print("\n")
    console.print(stats.generate_table())

    # Show sample results
    console.print("\n")
    table = Table(title="Sample Results / 示例结果 (Top 10)")
    table.add_column("Username / 用户名", style="cyan")
    table.add_column("Score / 分数", justify="right", style="yellow")
    table.add_column("Status / 状态", justify="center")
    table.add_column("Industry / 行业", style="magenta")

    for result in results[:10]:
        status = "[green]PASS[/green]" if result["passed"] else "[red]FAIL[/red]"
        table.add_row(
            f"@{result['username']}",
            f"{result['score']:.2f}",
            status,
            result["industry_match"],
        )

    console.print(table)
    console.print("\n[green]Audit completed successfully / 审核成功完成[/green]")


@app.command("status")
def status() -> None:
    """
    Show current audit status.

    显示当前审核状态。

    Example / 示例:
        xspider audit status
    """
    # TODO: Fetch from database/state
    table = Table(title="Audit Status / 审核状态")
    table.add_column("Metric / 指标", style="cyan")
    table.add_column("Value / 值", style="green", justify="right")

    table.add_row("Status / 状态", "[yellow]Idle / 空闲[/yellow]")
    table.add_row("Last Run / 上次运行", "2024-01-15 14:30:00")
    table.add_row("Total Audited / 已审核总数", "567")
    table.add_row("Passed / 通过", "423")
    table.add_row("Failed / 未通过", "144")
    table.add_row("Pending / 待审核", "789")

    console.print(table)


@app.command("results")
def results(
    status_filter: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: passed, failed / 按状态筛选: passed, failed",
    ),
    min_score: Optional[float] = typer.Option(
        None,
        "--min-score",
        help="Minimum score filter / 最低分数筛选",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-l",
        help="Maximum number of results to show / 最大显示结果数",
        min=1,
        max=100,
    ),
) -> None:
    """
    Show audit results.

    显示审核结果。

    Example / 示例:
        xspider audit results --status passed --limit 20
    """
    console.print("[bold blue]Audit Results / 审核结果[/bold blue]")

    # TODO: Fetch from database
    # Mock data
    audit_results = []
    for i in range(limit):
        score = 0.3 + (i % 8) * 0.1
        passed = score >= 0.6
        if status_filter == "passed" and not passed:
            continue
        if status_filter == "failed" and passed:
            continue
        if min_score and score < min_score:
            continue
        audit_results.append({
            "username": f"audited_user_{i + 1}",
            "score": score,
            "passed": passed,
            "industry": ["AI", "Web3", "Crypto"][i % 3],
            "audited_at": "2024-01-15",
        })

    table = Table(title="Audit Results / 审核结果")
    table.add_column("Username / 用户名", style="cyan")
    table.add_column("Score / 分数", justify="right", style="yellow")
    table.add_column("Status / 状态", justify="center")
    table.add_column("Industry / 行业", style="magenta")
    table.add_column("Date / 日期", style="dim")

    for result in audit_results[:limit]:
        status_str = "[green]PASS[/green]" if result["passed"] else "[red]FAIL[/red]"
        table.add_row(
            f"@{result['username']}",
            f"{result['score']:.2f}",
            status_str,
            result["industry"],
            result["audited_at"],
        )

    console.print(table)
    console.print(f"\n[dim]Showing {len(audit_results)} results / 显示 {len(audit_results)} 条结果[/dim]")


@app.command("retry")
def retry(
    failed_only: bool = typer.Option(
        True,
        "--failed-only/--all",
        help="Retry only failed audits / 仅重试失败的审核",
    ),
) -> None:
    """
    Retry failed audits.

    重试失败的审核。

    Example / 示例:
        xspider audit retry --failed-only
    """
    console.print(f"[bold blue]Retrying audits / 重试审核[/bold blue] (failed only: {failed_only})")

    # TODO: Implement retry logic
    console.print("[green]Retry queued / 重试已加入队列[/green]")


# Default behavior when running "xspider audit --industry AI --provider kimi"
@app.callback(invoke_without_command=True)
def audit_callback(
    ctx: typer.Context,
    industry: Optional[str] = typer.Option(
        None,
        "--industry",
        "-i",
        help="Industry to audit for / 审核的目标行业",
    ),
    provider: str = typer.Option(
        "kimi",
        "--provider",
        "-p",
        help="LLM provider: kimi, openai, anthropic / LLM提供商",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="AI model to use / 使用的AI模型",
    ),
) -> None:
    """
    AI audit commands for evaluating KOL relevance.

    AI审核命令 - 用于评估KOL相关性。

    When called with --industry, runs the audit.
    使用--industry调用时,执行审核。
    """
    if ctx.invoked_subcommand is None and industry:
        run(
            industry=industry,
            provider=provider,
            model=model,
            batch_size=10,
            min_score=0.6,
            limit=None,
            resume=False,
        )
    elif ctx.invoked_subcommand is None:
        console.print("[yellow]Please specify --industry or use a subcommand / 请指定--industry或使用子命令[/yellow]")
        console.print("Use 'xspider audit --help' for more information / 使用 'xspider audit --help' 获取更多信息")
        raise typer.Exit(0)


if __name__ == "__main__":
    app()
