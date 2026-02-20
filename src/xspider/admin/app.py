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
from xspider.admin.i18n import I18nMiddleware, get_all_translations, t
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

    # Start background search worker
    from xspider.admin.services.search_worker import start_search_worker, stop_search_worker

    await start_search_worker(str(db.engine.url))

    yield

    # Cleanup
    await stop_search_worker()
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

    # i18n middleware (must be after CORS)
    app.add_middleware(I18nMiddleware)

    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Setup Jinja2 templates
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    # Add i18n translation functions to Jinja2 globals
    # Note: get_template_context() in pages.py provides a language-aware _() function
    # These globals serve as fallbacks for templates without proper context
    templates.env.globals["t"] = t  # Explicit t(key, lang) for when language is known
    templates.env.globals["get_translations"] = get_all_translations

    # Store templates in app state for use in routes
    app.state.templates = templates

    # Import and include routers
    from xspider.admin.routes.account_groups import router as account_groups_router
    from xspider.admin.routes.api_keys import router as api_keys_router
    from xspider.admin.routes.auth import router as auth_router
    from xspider.admin.routes.credits import router as credits_router
    from xspider.admin.routes.dashboard import router as dashboard_router
    from xspider.admin.routes.monitors import router as monitors_router
    from xspider.admin.routes.proxies import router as proxies_router
    from xspider.admin.routes.searches import router as searches_router
    from xspider.admin.routes.twitter_accounts import router as accounts_router
    from xspider.admin.routes.users import router as users_router

    # New feature routers (升级版功能)
    from xspider.admin.routes.ai_openers import router as openers_router
    from xspider.admin.routes.analytics import router as analytics_router
    from xspider.admin.routes.crm import router as crm_router
    from xspider.admin.routes.packages import router as packages_router
    from xspider.admin.routes.privacy import router as privacy_router
    from xspider.admin.routes.topology import router as topology_router
    from xspider.admin.routes.webhooks import router as webhooks_router

    # Growth & Engagement routers (运营增长系统)
    from xspider.admin.routes.content_rewrite import router as content_rewrite_router
    from xspider.admin.routes.operating_accounts import router as operating_accounts_router
    from xspider.admin.routes.smart_interaction import router as smart_interaction_router
    from xspider.admin.routes.targeted_comment import router as targeted_comment_router

    # API routes
    app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
    app.include_router(api_keys_router, prefix="/api/auth", tags=["API Keys"])
    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(accounts_router, prefix="/api/accounts", tags=["Twitter Accounts"])
    app.include_router(account_groups_router, prefix="/api/account-groups", tags=["Account Groups"])
    app.include_router(proxies_router, prefix="/api/proxies", tags=["Proxies"])
    app.include_router(users_router, prefix="/api/users", tags=["Users"])
    app.include_router(credits_router, prefix="/api/credits", tags=["Credits"])
    app.include_router(searches_router, prefix="/api/searches", tags=["Searches"])
    app.include_router(monitors_router, prefix="/api/monitors", tags=["Monitoring"])

    # New feature routes (升级版功能)
    app.include_router(crm_router, prefix="/api", tags=["CRM"])
    app.include_router(analytics_router, prefix="/api", tags=["Analytics"])
    app.include_router(openers_router, prefix="/api", tags=["AI Openers"])
    app.include_router(webhooks_router, prefix="/api", tags=["Webhooks"])
    app.include_router(packages_router, prefix="/api", tags=["Packages"])
    app.include_router(privacy_router, prefix="/api", tags=["Privacy"])
    app.include_router(topology_router, prefix="/api", tags=["Topology"])

    # Growth & Engagement routes (运营增长系统)
    app.include_router(operating_accounts_router, prefix="/api")
    app.include_router(content_rewrite_router, prefix="/api")
    app.include_router(smart_interaction_router, prefix="/api")
    app.include_router(targeted_comment_router, prefix="/api")

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
