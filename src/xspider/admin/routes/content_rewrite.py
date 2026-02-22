"""Content Rewrite Routes (AI内容改写路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, ContentStatus
from xspider.admin.schemas import (
    ContentPublishResponse,
    ContentRewriteCreate,
    ContentRewriteResponse,
    ContentScheduleRequest,
)
from xspider.admin.services.content_rewrite_service import ContentRewriteService

router = APIRouter(prefix="/content-rewrite", tags=["Content Rewrite"])


# ==================== Rewrite Operations ====================


@router.post("/generate")
async def generate_rewrite(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    content: str = Query(None, description="Content to rewrite"),
) -> dict[str, Any]:
    """Generate a quick rewrite of content (simple endpoint).

    This is a simplified endpoint for the UI that takes raw content
    and returns the rewritten version.
    """
    from pydantic import BaseModel

    service = ContentRewriteService(db)

    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    try:
        rewritten = await service.generate_quick_rewrite(
            user_id=current_user.id,
            content=content,
        )
        return {"rewritten_content": rewritten}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/", response_model=ContentRewriteResponse)
async def create_rewrite(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    original_content: str = Query(..., description="Original content"),
    rewritten_content: str | None = Query(None, description="Rewritten content"),
    scheduled_at: str | None = Query(None, description="Scheduled publish time"),
    operating_account_id: int | None = Query(None, description="Operating account ID"),
) -> Any:
    """Create a content rewrite entry."""
    from datetime import datetime

    service = ContentRewriteService(db)

    scheduled = None
    if scheduled_at:
        try:
            scheduled = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid scheduled_at format")

    try:
        rewrite = await service.create_rewrite(
            user_id=current_user.id,
            original_content=original_content,
            rewritten_content=rewritten_content,
            scheduled_at=scheduled,
            operating_account_id=operating_account_id,
        )
        return rewrite
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rewrite", response_model=ContentRewriteResponse)
async def rewrite_content(
    request: ContentRewriteCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Rewrite content using AI.

    Rewrites the provided content according to the specified tone:
    - PROFESSIONAL: Authoritative, data-driven, expert tone
    - HUMOROUS: Witty, fun, shareable content
    - CONTROVERSIAL: Bold, thought-provoking viewpoints
    - THREAD_STYLE: Convert to a Twitter thread (3-5 tweets)

    Costs 5 credits per rewrite.
    """
    service = ContentRewriteService(db)

    try:
        rewrite = await service.rewrite_content(
            user_id=current_user.id,
            operating_account_id=request.operating_account_id,
            source_content=request.source_content,
            tone=request.tone,
            source_tweet_id=request.source_tweet_id,
            source_tweet_url=request.source_tweet_url,
            source_author=request.source_author,
            custom_instructions=request.custom_instructions,
        )
        return rewrite
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=list[ContentRewriteResponse])
async def list_rewrites(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    operating_account_id: int | None = Query(None, description="Filter by account"),
    status: ContentStatus | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Any:
    """List content rewrites."""
    service = ContentRewriteService(db)

    rewrites = await service.list_rewrites(
        user_id=current_user.id,
        operating_account_id=operating_account_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return rewrites


@router.get("/{rewrite_id}", response_model=ContentRewriteResponse)
async def get_rewrite(
    rewrite_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get a specific content rewrite."""
    service = ContentRewriteService(db)

    rewrite = await service.get_rewrite(rewrite_id, current_user.id)
    if not rewrite:
        raise HTTPException(status_code=404, detail="Content rewrite not found")

    return rewrite


@router.delete("/{rewrite_id}")
async def delete_rewrite(
    rewrite_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Delete a content rewrite (drafts only)."""
    service = ContentRewriteService(db)

    try:
        if not await service.delete_rewrite(rewrite_id, current_user.id):
            raise HTTPException(status_code=404, detail="Content rewrite not found")
        return {"success": True, "message": "Content rewrite deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Publishing Operations ====================


@router.post("/{rewrite_id}/schedule", response_model=ContentRewriteResponse)
async def schedule_publish(
    rewrite_id: int,
    request: ContentScheduleRequest,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Schedule content for future publishing."""
    service = ContentRewriteService(db)

    try:
        rewrite = await service.schedule_publish(
            rewrite_id=rewrite_id,
            user_id=current_user.id,
            scheduled_at=request.scheduled_at,
        )
        if not rewrite:
            raise HTTPException(status_code=404, detail="Content rewrite not found")
        return rewrite
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{rewrite_id}/publish", response_model=ContentPublishResponse)
async def publish_now(
    rewrite_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Publish content immediately.

    Posts the rewritten content to Twitter using the associated operating account.
    For thread-style content, posts a thread.
    """
    service = ContentRewriteService(db)

    try:
        result = await service.publish_now(rewrite_id, current_user.id)

        return ContentPublishResponse(
            success=result["success"],
            content_id=rewrite_id,
            published_tweet_id=result.get("published_tweet_id"),
            error_message=result.get("error"),
            published_at=result.get("published_at"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{rewrite_id}/cancel-schedule", response_model=ContentRewriteResponse)
async def cancel_schedule(
    rewrite_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Cancel a scheduled publish and return to draft status."""
    service = ContentRewriteService(db)

    rewrite = await service.get_rewrite(rewrite_id, current_user.id)
    if not rewrite:
        raise HTTPException(status_code=404, detail="Content rewrite not found")

    if rewrite.status != ContentStatus.SCHEDULED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel: content status is {rewrite.status.value}",
        )

    rewrite.status = ContentStatus.DRAFT
    rewrite.scheduled_at = None

    await db.commit()
    await db.refresh(rewrite)

    return rewrite


# ==================== Engagement Tracking ====================


@router.post("/{rewrite_id}/refresh-engagement")
async def refresh_engagement(
    rewrite_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Refresh engagement stats for published content."""
    service = ContentRewriteService(db)

    stats = await service.update_engagement_stats(rewrite_id, current_user.id)

    if stats is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot refresh: content not published or tweet not found",
        )

    return {
        "rewrite_id": rewrite_id,
        "engagement": stats,
    }
