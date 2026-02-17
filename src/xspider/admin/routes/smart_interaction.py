"""Smart Interaction Routes (智能互动路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, CommentStrategy, InteractionMode
from xspider.admin.schemas import (
    InteractionHistoryResponse,
    KOLWatchlistCreate,
    KOLWatchlistResponse,
    KOLWatchlistUpdate,
    PendingInteractionsResponse,
    SmartInteractionApproveRequest,
    SmartInteractionExecuteResponse,
    SmartInteractionGenerateRequest,
    SmartInteractionResponse,
)
from xspider.admin.services.smart_interaction_service import SmartInteractionService

router = APIRouter(prefix="/smart-interaction", tags=["Smart Interaction"])


# ==================== KOL Watchlist ====================


@router.post("/watchlist", response_model=KOLWatchlistResponse)
async def add_to_watchlist(
    request: KOLWatchlistCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Add a KOL to the watchlist for smart interaction monitoring.

    When active, the system will:
    1. Monitor the KOL's new tweets
    2. Evaluate relevance against your niche
    3. Generate comments using 3 strategies
    4. Wait for approval (REVIEW mode) or auto-post (AUTO mode)
    """
    service = SmartInteractionService(db)

    try:
        watchlist = await service.add_to_watchlist(
            user_id=current_user.id,
            operating_account_id=request.operating_account_id,
            kol_screen_name=request.kol_screen_name,
            interaction_mode=request.interaction_mode,
            relevance_threshold=request.relevance_threshold,
            preferred_strategies=request.preferred_strategies,
        )
        return watchlist
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/watchlist", response_model=list[KOLWatchlistResponse])
async def list_watchlist(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    operating_account_id: int | None = Query(None, description="Filter by account"),
    include_inactive: bool = Query(False, description="Include inactive entries"),
) -> Any:
    """List KOLs in the watchlist."""
    service = SmartInteractionService(db)

    watchlist = await service.list_watchlist(
        user_id=current_user.id,
        operating_account_id=operating_account_id,
        include_inactive=include_inactive,
    )
    return watchlist


@router.get("/watchlist/{watchlist_id}", response_model=KOLWatchlistResponse)
async def get_watchlist_entry(
    watchlist_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get a specific watchlist entry."""
    service = SmartInteractionService(db)

    watchlist = await service.list_watchlist(current_user.id)
    entry = next((w for w in watchlist if w.id == watchlist_id), None)

    if not entry:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    return entry


@router.put("/watchlist/{watchlist_id}", response_model=KOLWatchlistResponse)
async def update_watchlist_entry(
    watchlist_id: int,
    request: KOLWatchlistUpdate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Update watchlist entry settings."""
    service = SmartInteractionService(db)

    watchlist = await service.update_watchlist(
        watchlist_id=watchlist_id,
        user_id=current_user.id,
        interaction_mode=request.interaction_mode,
        relevance_threshold=request.relevance_threshold,
        preferred_strategies=request.preferred_strategies,
        is_active=request.is_active,
    )

    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    return watchlist


@router.delete("/watchlist/{watchlist_id}")
async def remove_from_watchlist(
    watchlist_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Remove a KOL from the watchlist."""
    service = SmartInteractionService(db)

    if not await service.remove_from_watchlist(watchlist_id, current_user.id):
        raise HTTPException(status_code=404, detail="Watchlist entry not found")

    return {"success": True, "message": "Removed from watchlist"}


# ==================== Interaction Generation ====================


@router.post("/generate", response_model=SmartInteractionResponse)
async def generate_interaction(
    request: SmartInteractionGenerateRequest,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Generate a smart interaction for a target tweet.

    This will:
    1. Fetch the tweet content
    2. Evaluate relevance to your account's niche
    3. Generate 3 comment strategies:
       - SUPPLEMENT: Add valuable insight
       - QUESTION: Engage with a question
       - HUMOR_MEME: Witty/humorous response

    Credit costs:
    - AUTO mode: 10 credits
    - REVIEW mode: 5 credits
    """
    service = SmartInteractionService(db)

    try:
        interaction = await service.generate_interaction(
            user_id=current_user.id,
            operating_account_id=request.operating_account_id,
            target_tweet_url=request.target_tweet_url,
            mode=request.mode,
        )
        return interaction
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Pending Interactions (Review Mode) ====================


@router.get("/pending", response_model=PendingInteractionsResponse)
async def get_pending_interactions(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    operating_account_id: int | None = Query(None, description="Filter by account"),
) -> Any:
    """Get interactions pending approval (REVIEW mode)."""
    service = SmartInteractionService(db)

    interactions = await service.get_pending_interactions(
        user_id=current_user.id,
        operating_account_id=operating_account_id,
    )

    return PendingInteractionsResponse(
        interactions=interactions,
        total=len(interactions),
    )


@router.post("/{interaction_id}/approve", response_model=SmartInteractionResponse)
async def approve_interaction(
    interaction_id: int,
    request: SmartInteractionApproveRequest,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Approve an interaction with a selected comment strategy.

    Choose one of the 3 generated strategies or provide a custom comment.
    """
    service = SmartInteractionService(db)

    try:
        interaction = await service.approve_interaction(
            interaction_id=interaction_id,
            user_id=current_user.id,
            selected_strategy=request.selected_strategy,
            custom_comment=request.custom_comment,
        )

        if not interaction:
            raise HTTPException(status_code=404, detail="Interaction not found")

        return interaction
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{interaction_id}/reject")
async def reject_interaction(
    interaction_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Reject and delete a pending interaction."""
    service = SmartInteractionService(db)

    if not await service.reject_interaction(interaction_id, current_user.id):
        raise HTTPException(status_code=404, detail="Interaction not found")

    return {"success": True, "message": "Interaction rejected"}


# ==================== Execution ====================


@router.post("/{interaction_id}/execute", response_model=SmartInteractionExecuteResponse)
async def execute_interaction(
    interaction_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Execute an approved interaction (post the comment).

    This posts the selected comment as a reply to the target tweet.
    """
    service = SmartInteractionService(db)

    try:
        result = await service.execute_interaction(interaction_id, current_user.id)

        return SmartInteractionExecuteResponse(
            success=result["success"],
            interaction_id=interaction_id,
            posted_tweet_id=result.get("posted_tweet_id"),
            error_message=result.get("error"),
            executed_at=result.get("executed_at"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== History ====================


@router.get("/history", response_model=InteractionHistoryResponse)
async def get_interaction_history(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    operating_account_id: int | None = Query(None, description="Filter by account"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Any:
    """Get interaction history."""
    service = SmartInteractionService(db)

    interactions, total = await service.get_interaction_history(
        user_id=current_user.id,
        operating_account_id=operating_account_id,
        limit=limit,
        offset=offset,
    )

    # Calculate stats
    executed = [i for i in interactions if i.is_executed]
    approved = [i for i in interactions if i.is_approved]
    success_rate = len(executed) / total if total > 0 else 0.0

    return InteractionHistoryResponse(
        interactions=interactions,
        total=total,
        page=(offset // limit) + 1,
        page_size=limit,
        total_executed=len(executed),
        total_approved=len(approved),
        success_rate=success_rate,
    )


@router.get("/{interaction_id}", response_model=SmartInteractionResponse)
async def get_interaction(
    interaction_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get a specific interaction."""
    service = SmartInteractionService(db)

    interactions, _ = await service.get_interaction_history(
        user_id=current_user.id,
        limit=1000,
        offset=0,
    )

    interaction = next((i for i in interactions if i.id == interaction_id), None)

    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction not found")

    return interaction
