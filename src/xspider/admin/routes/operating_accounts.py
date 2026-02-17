"""Operating Account Management Routes (运营账号管理路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, InteractionMode
from xspider.admin.schemas import (
    OperatingAccountCreate,
    OperatingAccountResponse,
    OperatingAccountStats,
    OperatingAccountUpdate,
    OperatingFollowerSnapshotResponse,
    OperatingGrowthSummaryResponse,
    ShadowbanCheckResult,
)
from xspider.admin.services.operating_account_service import OperatingAccountService
from xspider.admin.services.shadowban_checker_service import ShadowbanCheckerService

router = APIRouter(prefix="/operating-accounts", tags=["Operating Accounts"])


# ==================== CRUD Operations ====================


@router.post("/", response_model=OperatingAccountResponse)
async def register_operating_account(
    request: OperatingAccountCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Register a Twitter account as an operating account.

    Operating accounts are used for:
    - Publishing tweets
    - Replying to KOL tweets
    - Sending DMs
    """
    service = OperatingAccountService(db)

    try:
        account = await service.register_operating_account(
            user_id=current_user.id,
            twitter_account_id=request.twitter_account_id,
            niche_tags=request.niche_tags,
            persona=request.persona,
            daily_tweets_limit=request.daily_tweets_limit,
            daily_replies_limit=request.daily_replies_limit,
            daily_dms_limit=request.daily_dms_limit,
            interaction_mode=request.interaction_mode,
            notes=request.notes,
        )
        return account
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=list[OperatingAccountResponse])
async def list_operating_accounts(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    include_inactive: bool = Query(False, description="Include inactive accounts"),
) -> Any:
    """List all operating accounts for the current user."""
    service = OperatingAccountService(db)
    accounts = await service.list_operating_accounts(
        user_id=current_user.id,
        include_inactive=include_inactive,
    )
    return accounts


@router.get("/{account_id}", response_model=OperatingAccountResponse)
async def get_operating_account(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get a specific operating account."""
    service = OperatingAccountService(db)
    account = await service.get_operating_account(account_id, current_user.id)

    if not account:
        raise HTTPException(status_code=404, detail="Operating account not found")

    return account


@router.put("/{account_id}", response_model=OperatingAccountResponse)
async def update_operating_account(
    account_id: int,
    request: OperatingAccountUpdate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Update an operating account's configuration."""
    service = OperatingAccountService(db)

    account = await service.update_operating_account(
        operating_account_id=account_id,
        user_id=current_user.id,
        niche_tags=request.niche_tags,
        persona=request.persona,
        daily_tweets_limit=request.daily_tweets_limit,
        daily_replies_limit=request.daily_replies_limit,
        daily_dms_limit=request.daily_dms_limit,
        auto_reply_enabled=request.auto_reply_enabled,
        interaction_mode=request.interaction_mode,
        is_active=request.is_active,
        notes=request.notes,
    )

    if not account:
        raise HTTPException(status_code=404, detail="Operating account not found")

    return account


@router.delete("/{account_id}")
async def delete_operating_account(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Delete an operating account."""
    service = OperatingAccountService(db)

    if not await service.delete_operating_account(account_id, current_user.id):
        raise HTTPException(status_code=404, detail="Operating account not found")

    return {"success": True, "message": "Operating account deleted"}


# ==================== Shadowban Check ====================


@router.post("/{account_id}/check-shadowban", response_model=ShadowbanCheckResult)
async def check_shadowban(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    full_check: bool = Query(True, description="Perform full check (costs 20 credits)"),
) -> Any:
    """Check if the operating account is shadowbanned.

    Full check includes:
    - Search ban: Tweets don't appear in search
    - Suggestion ban: Account doesn't appear in recommendations
    - Reply ban: Replies are hidden
    - Ghost ban: Tweets are invisible

    Costs 20 credits for full check.
    """
    service = ShadowbanCheckerService(db)

    try:
        if full_check:
            result = await service.full_check(account_id, current_user.id)
        else:
            result = await service.quick_check(account_id, current_user.id)

        return ShadowbanCheckResult(
            is_shadowbanned=result.is_shadowbanned,
            search_ban=result.search_ban,
            suggestion_ban=result.suggestion_ban,
            reply_ban=result.reply_ban,
            ghost_ban=result.ghost_ban,
            checked_at=result.checked_at,
            details=result.to_json() if result.details else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{account_id}/shadowban-status", response_model=ShadowbanCheckResult | None)
async def get_shadowban_status(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Get the last shadowban check result."""
    service = ShadowbanCheckerService(db)
    result = await service.get_last_check(account_id, current_user.id)

    if not result:
        return None

    return ShadowbanCheckResult(
        is_shadowbanned=result.is_shadowbanned,
        search_ban=result.search_ban,
        suggestion_ban=result.suggestion_ban,
        reply_ban=result.reply_ban,
        ghost_ban=result.ghost_ban,
        checked_at=result.checked_at,
        details=result.to_json() if result.details else None,
    )


# ==================== Statistics ====================


@router.get("/{account_id}/stats", response_model=list[OperatingAccountStats])
async def get_operating_account_stats(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    days: int = Query(7, ge=1, le=30, description="Number of days to include"),
) -> Any:
    """Get daily statistics for an operating account."""
    service = OperatingAccountService(db)

    # Verify account ownership
    account = await service.get_operating_account(account_id, current_user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Operating account not found")

    stats = await service.get_daily_stats(account_id, days)

    return [
        OperatingAccountStats(
            account_id=account_id,
            screen_name=account.screen_name,
            followers_count=s["followers_count"],
            followers_change=s["followers_change"],
            followers_change_pct=s["followers_change_pct"],
            tweets_posted=s["tweets_posted"],
            replies_posted=s["replies_posted"],
            engagement_received=s["total_engagement"],
            date=s["date"],
        )
        for s in stats
    ]


@router.post("/{account_id}/snapshot", response_model=OperatingFollowerSnapshotResponse)
async def take_follower_snapshot(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> Any:
    """Take a follower snapshot for growth tracking."""
    service = OperatingAccountService(db)

    # Verify account ownership
    account = await service.get_operating_account(account_id, current_user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Operating account not found")

    try:
        snapshot = await service.take_follower_snapshot(account_id)
        return OperatingFollowerSnapshotResponse(
            id=snapshot.id,
            operating_account_id=snapshot.operating_account_id,
            followers_count=snapshot.followers_count,
            following_count=snapshot.following_count,
            tweet_count=snapshot.tweet_count,
            followers_change=snapshot.followers_change,
            followers_change_pct=snapshot.followers_change_pct,
            tweets_posted=snapshot.tweets_posted,
            replies_posted=snapshot.replies_posted,
            total_engagement=snapshot.total_engagement,
            snapshot_at=snapshot.snapshot_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Risk Assessment ====================


@router.post("/{account_id}/evaluate-risk")
async def evaluate_risk_level(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Evaluate and update the risk level for an operating account."""
    service = OperatingAccountService(db)

    # Verify account ownership
    account = await service.get_operating_account(account_id, current_user.id)
    if not account:
        raise HTTPException(status_code=404, detail="Operating account not found")

    risk_level = await service.evaluate_risk_level(account_id)

    return {
        "account_id": account_id,
        "risk_level": risk_level.value,
        "message": f"Risk level evaluated as {risk_level.value}",
    }


# ==================== Post Capability Check ====================


@router.get("/{account_id}/can-post")
async def can_post(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    post_type: str = Query("tweet", pattern="^(tweet|reply|dm)$"),
) -> dict[str, Any]:
    """Check if the account can post (not rate limited, not banned).

    Post types:
    - tweet: New tweet
    - reply: Reply to another tweet
    - dm: Direct message
    """
    service = OperatingAccountService(db)

    can_proceed, reason = await service.can_post(account_id, post_type)

    return {
        "account_id": account_id,
        "post_type": post_type,
        "can_post": can_proceed,
        "reason": reason,
    }
