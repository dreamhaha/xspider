"""HTML page routes for admin module."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from xspider.admin.auth import decode_token, get_current_active_user
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
async def dashboard_page(request: Request) -> HTMLResponse:
    """Render admin dashboard."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "dashboard.html",
        get_template_context(request, user),
    )


@router.get("/admin/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request) -> HTMLResponse:
    """Render Twitter accounts management page."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if user.role != UserRole.ADMIN:
        return RedirectResponse(url="/admin/dashboard", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "accounts/list.html",
        get_template_context(request, user),
    )


@router.get("/admin/proxies", response_class=HTMLResponse)
async def proxies_page(request: Request) -> HTMLResponse:
    """Render proxy management page."""
    user = get_optional_user(request)
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
async def users_page(request: Request) -> HTMLResponse:
    """Render user management page."""
    user = get_optional_user(request)
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
async def search_page(request: Request) -> HTMLResponse:
    """Render search page for users."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "searches/new.html",
        get_template_context(request, user),
    )


@router.get("/searches", response_class=HTMLResponse)
async def searches_list_page(request: Request) -> HTMLResponse:
    """Render search history page."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "searches/list.html",
        get_template_context(request, user),
    )


@router.get("/searches/{search_id}", response_class=HTMLResponse)
async def search_detail_page(request: Request, search_id: int) -> HTMLResponse:
    """Render search detail page."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "searches/detail.html",
        get_template_context(request, user, search_id=search_id),
    )


@router.get("/credits", response_class=HTMLResponse)
async def credits_page(request: Request) -> HTMLResponse:
    """Render credits page."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "credits.html",
        get_template_context(request, user),
    )


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request) -> HTMLResponse:
    """Render user profile page."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "profile.html",
        get_template_context(request, user),
    )


@router.get("/admin/monitors", response_class=HTMLResponse)
async def monitors_page(request: Request) -> HTMLResponse:
    """Render influencer monitoring list page."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "monitors/list.html",
        get_template_context(request, user),
    )


@router.get("/admin/monitors/{influencer_id}", response_class=HTMLResponse)
async def monitor_detail_page(request: Request, influencer_id: int) -> HTMLResponse:
    """Render influencer monitoring detail page."""
    user = get_optional_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "monitors/detail.html",
        get_template_context(request, user, influencer_id=influencer_id),
    )
