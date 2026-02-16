"""Admin server CLI commands for xspider."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()

app = typer.Typer(
    name="admin",
    help="Admin server commands / 后台管理服务命令",
    no_args_is_help=True,
)


@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload for development"),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of worker processes"),
) -> None:
    """
    Start the admin web server.

    启动后台管理Web服务器。

    Example:
        xspider admin serve
        xspider admin serve --port 8080 --reload
    """
    import uvicorn

    console.print("[bold blue]Starting xspider admin server...[/bold blue]")
    console.print(f"[dim]Host: {host}[/dim]")
    console.print(f"[dim]Port: {port}[/dim]")
    console.print(f"[dim]Reload: {reload}[/dim]")
    console.print(f"[dim]Workers: {workers}[/dim]")
    console.print()
    console.print(f"[green]Admin panel: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/admin/dashboard[/green]")
    console.print(f"[green]API docs: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/api/docs[/green]")
    console.print()
    console.print("[yellow]Default admin credentials: admin / admin123[/yellow]")
    console.print()

    uvicorn.run(
        "xspider.admin.app:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        log_level="info",
    )


@app.command("init-db")
def init_db() -> None:
    """
    Initialize the admin database tables.

    初始化后台管理数据库表。
    """
    import asyncio

    from xspider.admin.auth import create_default_admin
    from xspider.storage.database import get_database
    from xspider.storage.models import Base

    async def _init():
        db = get_database()
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with db.session() as session:
            admin = await create_default_admin(session)
            if admin:
                console.print(f"[green]Created default admin user: {admin.username}[/green]")
                console.print("[yellow]Password: admin123[/yellow]")
            else:
                console.print("[dim]Default admin already exists[/dim]")

        console.print("[green]Database initialized successfully![/green]")

    asyncio.run(_init())


@app.command("create-admin")
def create_admin(
    username: str = typer.Argument(..., help="Admin username"),
    email: str = typer.Argument(..., help="Admin email"),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True, help="Admin password"),
) -> None:
    """
    Create a new admin user.

    创建新的管理员用户。

    Example:
        xspider admin create-admin myuser myemail@example.com -p mypassword
    """
    import asyncio

    from sqlalchemy import select

    from xspider.admin.auth import hash_password
    from xspider.admin.models import AdminUser, UserRole
    from xspider.storage.database import get_database

    async def _create():
        db = get_database()

        async with db.session() as session:
            # Check if username exists
            result = await session.execute(
                select(AdminUser).where(AdminUser.username == username)
            )
            if result.scalar_one_or_none():
                console.print(f"[red]Error: Username '{username}' already exists[/red]")
                raise typer.Exit(1)

            # Check if email exists
            result = await session.execute(
                select(AdminUser).where(AdminUser.email == email)
            )
            if result.scalar_one_or_none():
                console.print(f"[red]Error: Email '{email}' already exists[/red]")
                raise typer.Exit(1)

            # Create admin user
            admin = AdminUser(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=UserRole.ADMIN,
                credits=999999,
                is_active=True,
            )
            session.add(admin)
            await session.commit()

            console.print(f"[green]Admin user '{username}' created successfully![/green]")

    asyncio.run(_create())


@app.command("list-users")
def list_users() -> None:
    """
    List all admin users.

    列出所有用户。
    """
    import asyncio

    from rich.table import Table
    from sqlalchemy import select

    from xspider.admin.models import AdminUser
    from xspider.storage.database import get_database

    async def _list():
        db = get_database()

        async with db.session() as session:
            result = await session.execute(
                select(AdminUser).order_by(AdminUser.created_at)
            )
            users = result.scalars().all()

            if not users:
                console.print("[dim]No users found[/dim]")
                return

            table = Table(title="Admin Users")
            table.add_column("ID", style="cyan")
            table.add_column("Username", style="green")
            table.add_column("Email")
            table.add_column("Role")
            table.add_column("Credits")
            table.add_column("Active")

            for user in users:
                role_style = "red" if user.role.value == "admin" else "blue"
                table.add_row(
                    str(user.id),
                    user.username,
                    user.email,
                    f"[{role_style}]{user.role.value}[/{role_style}]",
                    str(user.credits),
                    "[green]Yes[/green]" if user.is_active else "[red]No[/red]",
                )

            console.print(table)

    asyncio.run(_list())
