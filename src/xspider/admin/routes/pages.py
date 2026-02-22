"""HTML page routes for admin module."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import decode_token, get_current_active_user, get_db_session
from xspider.admin.i18n import get_lang, t
from xspider.admin.i18n.translator import get_all_translations
from xspider.admin.models import AdminUser, UserRole

router = APIRouter()


def get_template_context(request: Request, user: AdminUser | None = None, **kwargs: Any) -> dict[str, Any]:
    """Build template context with i18n support."""
    lang = get_lang(request)
    context = {
        "request": request,
        "lang": lang,
        "_": lambda key, **kw: t(key, lang, **kw),
        "translations": get_all_translations(lang),
    }
    if user:
        context["user"] = user
    context.update(kwargs)
    return context


def get_optional_user(request: Request) -> AdminUser | None:
    """Get current user from session cookie, or None if not authenticated."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return None

    payload = decode_token(session_token)
    if not payload:
        return None

    # Return a minimal user object for template rendering
    # The actual user validation happens in API routes
    return AdminUser(
        id=int(payload.sub),
        username=payload.username,
        email="",  # Not needed for nav
        password_hash="",
        role=UserRole(payload.role),
        credits=0,
    )


async def get_user_from_db(request: Request, db: AsyncSession) -> AdminUser | None:
    """Get current user from database with actual credits."""
    session_token = request.cookies.get("session_token")
    if not session_token:
        return None

    payload = decode_token(session_token)
    if not payload:
        return None

    result = await db.execute(
        select(AdminUser).where(AdminUser.id == int(payload.sub))
    )
    return result.scalar_one_or_none()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render login page."""
    user = get_optional_user(request)
    if user:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "login.html",
        get_template_context(request),
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    """Render registration page."""
    user = get_optional_user(request)
    if user:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "register.html",
        get_template_context(request),
    )


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render admin dashboard."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        get_template_context(request, user),
    )


@router.get("/admin/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render Twitter accounts management page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "accounts/list.html",
        get_template_context(request, user),
    )


@router.get("/admin/accounts/stats", response_class=HTMLResponse)
async def accounts_stats_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render Twitter accounts statistics page for risk control."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "accounts/stats.html",
        get_template_context(request, user),
    )


@router.get("/admin/accounts/groups", response_class=HTMLResponse)
async def accounts_groups_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render account groups management page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "accounts/groups.html",
        get_template_context(request, user),
    )


@router.get("/admin/proxies", response_class=HTMLResponse)
async def proxies_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render proxy management page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "proxies/list.html",
        get_template_context(request, user),
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render user management page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "users/list.html",
        get_template_context(request, user),
    )


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render search page for users."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "searches/new.html",
        get_template_context(request, user),
    )


@router.get("/searches", response_class=HTMLResponse)
async def searches_list_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render search history page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "searches/list.html",
        get_template_context(request, user),
    )


@router.get("/searches/{search_id}", response_class=HTMLResponse)
async def search_detail_page(
    request: Request,
    search_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render search detail page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "searches/detail.html",
        get_template_context(request, user, search_id=search_id),
    )


@router.get("/credits", response_class=HTMLResponse)
async def credits_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render credits page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "credits.html",
        get_template_context(request, user),
    )


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render user profile page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "profile.html",
        get_template_context(request, user),
    )


@router.get("/admin/monitors", response_class=HTMLResponse)
async def monitors_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render influencer monitoring list page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "monitors/list.html",
        get_template_context(request, user),
    )


@router.get("/admin/monitors/{influencer_id}", response_class=HTMLResponse)
async def monitor_detail_page(
    request: Request,
    influencer_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render influencer monitoring detail page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "monitors/detail.html",
        get_template_context(request, user, influencer_id=influencer_id),
    )


# ============ Operating Accounts ============

@router.get("/admin/operating-accounts", response_class=HTMLResponse)
async def operating_accounts_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render operating accounts management page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "operating-accounts/list.html",
        get_template_context(request, user),
    )


@router.get("/admin/operating-accounts/{account_id}", response_class=HTMLResponse)
async def operating_account_detail_page(
    request: Request,
    account_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render operating account detail page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "operating-accounts/detail.html",
        get_template_context(request, user, account_id=account_id),
    )


# ============ CRM ============

@router.get("/admin/crm", response_class=HTMLResponse)
async def crm_kanban_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render CRM kanban page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "crm/kanban.html",
        get_template_context(request, user),
    )


@router.get("/admin/crm/leads", response_class=HTMLResponse)
async def crm_leads_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render CRM leads list page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "crm/leads.html",
        get_template_context(request, user),
    )


# ============ Analytics ============

@router.get("/admin/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render analytics overview page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "analytics/index.html",
        get_template_context(request, user),
    )


# ============ Content Rewrite ============

@router.get("/admin/content-rewrite", response_class=HTMLResponse)
async def content_rewrite_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render content rewrite page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "content-rewrite/list.html",
        get_template_context(request, user),
    )


# ============ Smart Interaction ============

@router.get("/admin/smart-interaction", response_class=HTMLResponse)
async def smart_interaction_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render smart interaction page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "smart-interaction/list.html",
        get_template_context(request, user),
    )


# ============ AI Openers ============

@router.get("/admin/openers", response_class=HTMLResponse)
async def openers_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render AI openers page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "openers/list.html",
        get_template_context(request, user),
    )


# ============ Targeted Comment ============

@router.get("/admin/targeted-comment", response_class=HTMLResponse)
async def targeted_comment_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render targeted comment page."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "targeted-comment/list.html",
        get_template_context(request, user),
    )


# ============ Packages (Admin) ============

@router.get("/admin/packages", response_class=HTMLResponse)
async def packages_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render packages management page (admin only)."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "packages/list.html",
        get_template_context(request, user),
    )


# ============ Webhooks (Admin) ============

@router.get("/admin/webhooks", response_class=HTMLResponse)
async def webhooks_page(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> HTMLResponse:
    """Render webhooks management page (admin only)."""
    user = await get_user_from_db(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "webhooks/list.html",
        get_template_context(request, user),
    )
