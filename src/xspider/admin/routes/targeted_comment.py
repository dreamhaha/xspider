"""Targeted Comment Routes (指定评论路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, CommentStrategy
from xspider.admin.schemas import (
    CommentPermissionCheckResponse,
    TargetedCommentCreate,
    TargetedCommentExecuteResponse,
    TargetedCommentHistoryResponse,
    TargetedCommentResponse,
)
from xspider.admin.services.targeted_comment_service import TargetedCommentService

router = APIRouter(prefix="/targeted-comment", tags=["Targeted Comment"])


# ==================== Permission Check ====================


@router.post("/check-permission", response_model=CommentPermissionCheckResponse)
async def check_comment_permission(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    tweet_url: str = Query(..., description="URL of the tweet to check"),
) -> Any:
    """Check if we can comment on a target tweet.

    Returns:
    - can_comment: Whether replies are allowed
    - reason: Why commenting is allowed/blocked
    - tweet details if accessible
    """
    service = TargetedCommentService(db)

    result = await service.check_comment_permission(tweet_url)

    return CommentPermissionCheckResponse(
        can_comment=result.get("can_comment", False),
        reason=result.get("reason", "Unknown"),
        tweet_id=result.get("tweet_id", ""),
        author_name=result.get("author_name", ""),
        tweet_content=result.get("tweet_content"),
    )


# ==================== Comment Generation ====================


@router.post("/generate", response_model=TargetedCommentResponse)
async def create_targeted_comment(
    request: TargetedCommentCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Create a targeted comment for a specific tweet.

    This will:
    1. Check if commenting is allowed
    2. Generate a comment based on direction/strategy
    3. Generate support comments if matrix mode

    Cost: 3 credits per comment (main + each support account)

    Matrix mode: Posts 1 main comment + up to 3 support comments
    from different accounts to boost visibility.
    """
    service = TargetedCommentService(db)

    try:
        comment = await service.create_targeted_comment(
            user_id=current_user.id,
            target_tweet_url=request.target_tweet_url,
            main_account_id=request.main_account_id,
            comment_direction=request.comment_direction,
            strategy=request.strategy,
            is_matrix=request.is_matrix,
            support_account_ids=request.support_account_ids,
        )
        return comment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{comment_id}/regenerate", response_model=TargetedCommentResponse)
async def regenerate_comment(
    comment_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    new_direction: str | None = Query(None, description="New comment direction"),
    new_strategy: CommentStrategy | None = Query(None, description="New strategy"),
) -> Any:
    """Regenerate comments with new settings.

    Only works for unexecuted comments.
    """
    service = TargetedCommentService(db)

    try:
        comment = await service.regenerate_comment(
            comment_id=comment_id,
            user_id=current_user.id,
            new_direction=new_direction,
            new_strategy=new_strategy,
        )

        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")

        return comment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Execution ====================


@router.post("/{comment_id}/execute", response_model=TargetedCommentExecuteResponse)
async def execute_comment(
    comment_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Execute a targeted comment (post it to Twitter).

    For matrix mode, posts the main comment plus all support comments.
    """
    service = TargetedCommentService(db)

    try:
        result = await service.execute_comment(comment_id, current_user.id)

        return TargetedCommentExecuteResponse(
            success=result["success"],
            comment_id=comment_id,
            posted_tweet_ids=result.get("posted_tweet_ids"),
            error_message="; ".join(result["errors"]) if result.get("errors") else None,
            executed_at=result.get("executed_at"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== CRUD ====================


@router.get("/", response_model=TargetedCommentHistoryResponse)
async def list_comments(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    is_executed: bool | None = Query(None, description="Filter by execution status"),
    is_matrix: bool | None = Query(None, description="Filter by matrix mode"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Any:
    """List targeted comments."""
    service = TargetedCommentService(db)

    comments, total = await service.list_comments(
        user_id=current_user.id,
        is_executed=is_executed,
        is_matrix=is_matrix,
        limit=limit,
        offset=offset,
    )

    # Calculate stats
    executed = [c for c in comments if c.is_executed]
    matrix = [c for c in comments if c.is_matrix]

    return TargetedCommentHistoryResponse(
        comments=comments,
        total=total,
        page=(offset // limit) + 1,
        page_size=limit,
        total_executed=len(executed),
        total_matrix=len(matrix),
    )


@router.get("/{comment_id}", response_model=TargetedCommentResponse)
async def get_comment(
    comment_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get a specific targeted comment."""
    service = TargetedCommentService(db)

    comment = await service.get_comment(comment_id, current_user.id)

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    return comment


@router.delete("/{comment_id}")
async def delete_comment(
    comment_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Delete a targeted comment (unexecuted only)."""
    service = TargetedCommentService(db)

    try:
        if not await service.delete_comment(comment_id, current_user.id):
            raise HTTPException(status_code=404, detail="Comment not found")
        return {"success": True, "message": "Comment deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
