"""FastAPI application for xspider admin module."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from xspider.admin.auth import create_default_admin
from xspider.admin.models import (
    AdminUser,
    CreditTransaction,
    DiscoveredInfluencer,
    LLMUsage,
    ProxyServer,
    TwitterAccount,
    UserSearch,
)
from xspider.core.logging import get_logger
from xspider.storage.database import get_database
from xspider.storage.models import Base

# Module paths
MODULE_DIR = Path(__file__).parent
TEMPLATES_DIR = MODULE_DIR / "templates"
STATIC_DIR = MODULE_DIR / "static"

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup/shutdown."""
    logger.info("Starting xspider admin server")

    # Initialize database
    db = get_database()
    async with db.engine.begin() as conn:
        # Create all tables (including admin models)
        await conn.run_sync(Base.metadata.create_all)

    # Create default admin user
    async with db.session() as session:
        admin = await create_default_admin(session)
        if admin:
            logger.info(
                "Created default admin user",
                username=admin.username,
                password="admin123",
            )

    yield

    # Cleanup
    await db.close()
    logger.info("Stopped xspider admin server")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="xspider Admin",
        description="Backend management system for xspider Twitter influencer discovery",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Setup Jinja2 templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Store templates in app state for use in routes
    app.state.templates = templates

    # Import and include routers
    from xspider.admin.routes.auth import router as auth_router
    from xspider.admin.routes.credits import router as credits_router
    from xspider.admin.routes.dashboard import router as dashboard_router
    from xspider.admin.routes.monitors import router as monitors_router
    from xspider.admin.routes.proxies import router as proxies_router
    from xspider.admin.routes.searches import router as searches_router
    from xspider.admin.routes.twitter_accounts import router as accounts_router
    from xspider.admin.routes.users import router as users_router

    # API routes
    app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(accounts_router, prefix="/api/accounts", tags=["Twitter Accounts"])
    app.include_router(proxies_router, prefix="/api/proxies", tags=["Proxies"])
    app.include_router(users_router, prefix="/api/users", tags=["Users"])
    app.include_router(credits_router, prefix="/api/credits", tags=["Credits"])
    app.include_router(searches_router, prefix="/api/searches", tags=["Searches"])
    app.include_router(monitors_router, prefix="/api/monitors", tags=["Monitoring"])

    # Page routes (HTML)
    from xspider.admin.routes.pages import router as pages_router

    app.include_router(pages_router)

    # Root redirect
    @app.get("/", include_in_schema=False)
    async def root():
        """Redirect root to admin dashboard."""
        return RedirectResponse(url="/admin/dashboard")

    return app


def get_templates(request: Request) -> Jinja2Templates:
    """Get templates from app state."""
    return request.app.state.templates


# Create application instance
app = create_app()
