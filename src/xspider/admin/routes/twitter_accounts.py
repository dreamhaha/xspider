"""Twitter accounts management routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_admin, get_db_session
from xspider.admin.models import AccountGroup, AccountStatus, AdminUser, TwitterAccount
from xspider.admin.schemas import (
    AccountGroupAssignRequest,
    AccountStatusCheck,
    AndroidAccountImport,
    AndroidImportResult,
    TwitterAccountBatchImport,
    TwitterAccountCreate,
    TwitterAccountDetailResponse,
    TwitterAccountResponse,
    TwitterAccountUpdate,
)

router = APIRouter()


def mask_token(token: str, visible_chars: int = 8) -> str:
    """Mask a token showing only last N characters."""
    if len(token) <= visible_chars:
        return "*" * len(token)
    return "*" * (len(token) - visible_chars) + token[-visible_chars:]


@router.get("/", response_model=list[TwitterAccountResponse])
async def list_accounts(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    status_filter: AccountStatus | None = None,
    group_id: int | None = None,
    ungrouped: bool = False,
    db: AsyncSession = Depends(get_db_session),
) -> list[TwitterAccount]:
    """List all Twitter accounts.

    Args:
        status_filter: Filter by account status.
        group_id: Filter by group ID.
        ungrouped: If True, only return ungrouped accounts.
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(TwitterAccount)
        .options(selectinload(TwitterAccount.group))
        .order_by(TwitterAccount.created_at.desc())
    )

    if status_filter:
        query = query.where(TwitterAccount.status == status_filter)

    if ungrouped:
        query = query.where(TwitterAccount.group_id == None)
    elif group_id is not None:
        query = query.where(TwitterAccount.group_id == group_id)

    result = await db.execute(query)
    return list(result.scalars().all())


# ============================================================================
# Risk Summary Endpoint (must be before /{account_id} routes)
# ============================================================================


@router.get("/stats/risk-summary")
async def get_all_accounts_risk_summary(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get risk summary for all accounts.

    Returns:
        List of accounts with their risk scores and statistics.
    """
    from xspider.admin.services.account_stats_service import AccountStatsService

    stats_service = AccountStatsService(db)
    summaries = await stats_service.get_all_accounts_risk_summary()

    # Calculate overall statistics
    total_accounts = len(summaries)
    high_risk = sum(1 for s in summaries if s.get("risk_level") in ["high", "critical"])
    medium_risk = sum(1 for s in summaries if s.get("risk_level") == "medium")
    low_risk = sum(1 for s in summaries if s.get("risk_level") == "low")

    return {
        "summary": {
            "total_accounts": total_accounts,
            "high_risk": high_risk,
            "medium_risk": medium_risk,
            "low_risk": low_risk,
        },
        "accounts": summaries,
    }


@router.get("/{account_id}", response_model=TwitterAccountDetailResponse)
async def get_account(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get Twitter account details."""
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    return {
        "id": account.id,
        "name": account.name,
        "status": account.status,
        "last_used_at": account.last_used_at,
        "last_check_at": account.last_check_at,
        "request_count": account.request_count,
        "error_count": account.error_count,
        "rate_limit_reset": account.rate_limit_reset,
        "created_at": account.created_at,
        "notes": account.notes,
        "bearer_token_preview": mask_token(account.bearer_token),
        "ct0_preview": mask_token(account.ct0),
        "auth_token_preview": mask_token(account.auth_token),
    }


@router.post("/", response_model=TwitterAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    request: TwitterAccountCreate,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> TwitterAccount:
    """Create a new Twitter account."""
    account = TwitterAccount(
        name=request.name,
        bearer_token=request.bearer_token,
        ct0=request.ct0,
        auth_token=request.auth_token,
        status=AccountStatus.ACTIVE,
        created_by=current_user.id,
        notes=request.notes,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    return account


@router.put("/{account_id}", response_model=TwitterAccountResponse)
async def update_account(
    account_id: int,
    request: TwitterAccountUpdate,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> TwitterAccount:
    """Update a Twitter account."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(TwitterAccount)
        .options(selectinload(TwitterAccount.group))
        .where(TwitterAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Update fields if provided
    if request.name is not None:
        account.name = request.name
    if request.bearer_token is not None:
        account.bearer_token = request.bearer_token
    if request.ct0 is not None:
        account.ct0 = request.ct0
    if request.auth_token is not None:
        account.auth_token = request.auth_token
    if request.status is not None:
        account.status = request.status
    if request.notes is not None:
        account.notes = request.notes
    if request.group_id is not None:
        account.group_id = request.group_id

    await db.commit()
    await db.refresh(account, ["group"])

    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a Twitter account."""
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    await db.delete(account)
    await db.commit()


@router.post("/batch-import", response_model=list[TwitterAccountResponse])
async def batch_import_accounts(
    request: TwitterAccountBatchImport,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> list[TwitterAccount]:
    """Batch import Twitter accounts."""
    accounts = []

    for account_data in request.accounts:
        account = TwitterAccount(
            name=account_data.name,
            bearer_token=account_data.bearer_token,
            ct0=account_data.ct0,
            auth_token=account_data.auth_token,
            status=AccountStatus.ACTIVE,
            created_by=current_user.id,
            notes=account_data.notes,
        )
        db.add(account)
        accounts.append(account)

    await db.commit()

    # Refresh all accounts
    for account in accounts:
        await db.refresh(account)

    return accounts


@router.post("/import-android", response_model=AndroidImportResult)
async def import_android_accounts(
    request: AndroidAccountImport,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AndroidImportResult:
    """Import Twitter accounts from Android app export format.

    Accepts JSON in the format exported from Twitter Android app:
    {
        "accounts": [
            {
                "Uid": "1234567890",
                "AccountId": "username",
                "UserInfo": "{\"screen_name\": \"username\", ...}",
                "Cookies": [
                    {"name": "ct0", "value": "..."},
                    {"name": "auth_token", "value": "..."}
                ]
            }
        ]
    }
    """
    from xspider.admin.services.account_import import parse_android_accounts

    # Convert pydantic models to dicts for parsing
    accounts_data = [acc.model_dump() for acc in request.accounts]

    if not accounts_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No accounts data provided",
        )

    imported_accounts = parse_android_accounts(accounts_data)

    if not imported_accounts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse any accounts from the provided data. Check ct0 and auth_token cookies.",
        )

    # Import to database
    created_accounts = []
    skipped_accounts = []
    errors = []

    for imported in imported_accounts:
        # Check if account already exists (by auth_token to avoid duplicates)
        existing = await db.execute(
            select(TwitterAccount).where(TwitterAccount.auth_token == imported.auth_token)
        )
        if existing.scalar_one_or_none():
            skipped_accounts.append(imported.screen_name)
            continue

        try:
            account = TwitterAccount(
                name=f"@{imported.screen_name}",
                bearer_token="",  # Not available in Android format
                ct0=imported.ct0,
                auth_token=imported.auth_token,
                status=AccountStatus.ACTIVE,
                created_by=current_user.id,
                notes=f"Android import. UID: {imported.uid}, Country: {imported.country}",
            )
            db.add(account)
            created_accounts.append(imported.screen_name)
        except Exception as e:
            errors.append(f"{imported.screen_name}: {str(e)}")

    await db.commit()

    return AndroidImportResult(
        success=len(created_accounts) > 0,
        imported=len(created_accounts),
        skipped=len(skipped_accounts),
        accounts=created_accounts,
        skipped_accounts=skipped_accounts,
        errors=errors if errors else None,
    )


@router.post("/{account_id}/check", response_model=AccountStatusCheck)
async def check_account_status(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountStatusCheck:
    """Check Twitter account status by making a test request."""
    from xspider.admin.services.account_monitor import AccountMonitorService

    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Use monitor service to check account
    monitor = AccountMonitorService(db)
    check_result = await monitor.check_account(account)

    return AccountStatusCheck(
        account_id=account.id,
        status=check_result.status,
        error_message=check_result.error_message,
        rate_limit_reset=check_result.rate_limit_reset,
    )


@router.post("/check-all", response_model=list[AccountStatusCheck])
async def check_all_accounts(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> list[AccountStatusCheck]:
    """Check status of all Twitter accounts."""
    from xspider.admin.services.account_monitor import AccountMonitorService

    result = await db.execute(select(TwitterAccount))
    accounts = list(result.scalars().all())

    monitor = AccountMonitorService(db)
    results = []

    for account in accounts:
        check_result = await monitor.check_account(account)
        results.append(
            AccountStatusCheck(
                account_id=account.id,
                status=check_result.status,
                error_message=check_result.error_message,
                rate_limit_reset=check_result.rate_limit_reset,
            )
        )

    return results


@router.post("/{account_id}/reset-counters", response_model=TwitterAccountResponse)
async def reset_account_counters(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> TwitterAccount:
    """Reset account request and error counters."""
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(TwitterAccount)
        .options(selectinload(TwitterAccount.group))
        .where(TwitterAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    account.request_count = 0
    account.error_count = 0
    account.rate_limit_reset = None

    if account.status == AccountStatus.RATE_LIMITED:
        account.status = AccountStatus.ACTIVE

    await db.commit()
    await db.refresh(account, ["group"])

    return account


# ============================================================================
# Account Group Assignment Endpoints (账号分组)
# ============================================================================


@router.post("/{account_id}/assign-group")
async def assign_account_to_group(
    account_id: int,
    group_id: int | None,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Assign an account to a group or remove from group.

    Args:
        account_id: Twitter account ID.
        group_id: Group ID to assign, or None to remove from group.
    """
    from sqlalchemy import func

    # Verify account exists
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    old_group_id = account.group_id

    # Verify group exists if assigning
    if group_id is not None:
        group_result = await db.execute(
            select(AccountGroup).where(AccountGroup.id == group_id)
        )
        if not group_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found",
            )

    # Update account
    account.group_id = group_id
    await db.commit()

    # Update group counts
    async def update_group_counts(gid: int) -> None:
        total = await db.execute(
            select(func.count()).select_from(TwitterAccount).where(TwitterAccount.group_id == gid)
        )
        active = await db.execute(
            select(func.count()).select_from(TwitterAccount)
            .where(TwitterAccount.group_id == gid)
            .where(TwitterAccount.status == AccountStatus.ACTIVE)
        )
        grp_result = await db.execute(select(AccountGroup).where(AccountGroup.id == gid))
        grp = grp_result.scalar_one_or_none()
        if grp:
            grp.account_count = total.scalar() or 0
            grp.active_account_count = active.scalar() or 0

    if old_group_id:
        await update_group_counts(old_group_id)
    if group_id:
        await update_group_counts(group_id)

    await db.commit()

    return {"success": True, "account_id": account_id, "group_id": group_id}


@router.post("/batch-assign-group")
async def batch_assign_accounts_to_group(
    request: AccountGroupAssignRequest,
    group_id: int | None,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Batch assign multiple accounts to a group.

    Args:
        request: Request containing account_ids list.
        group_id: Group ID to assign, or None to remove from groups.
    """
    from sqlalchemy import func

    # Verify group exists if assigning
    if group_id is not None:
        group_result = await db.execute(
            select(AccountGroup).where(AccountGroup.id == group_id)
        )
        if not group_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Group not found",
            )

    # Get accounts and track old groups
    accounts_result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id.in_(request.account_ids))
    )
    accounts = list(accounts_result.scalars().all())

    affected_group_ids = set()
    for account in accounts:
        if account.group_id:
            affected_group_ids.add(account.group_id)
        account.group_id = group_id

    if group_id:
        affected_group_ids.add(group_id)

    await db.commit()

    # Update counts for all affected groups
    for gid in affected_group_ids:
        total = await db.execute(
            select(func.count()).select_from(TwitterAccount).where(TwitterAccount.group_id == gid)
        )
        active = await db.execute(
            select(func.count()).select_from(TwitterAccount)
            .where(TwitterAccount.group_id == gid)
            .where(TwitterAccount.status == AccountStatus.ACTIVE)
        )
        grp_result = await db.execute(select(AccountGroup).where(AccountGroup.id == gid))
        grp = grp_result.scalar_one_or_none()
        if grp:
            grp.account_count = total.scalar() or 0
            grp.active_account_count = active.scalar() or 0

    await db.commit()

    return {
        "success": True,
        "updated": len(accounts),
        "group_id": group_id,
    }


# ============================================================================
# Account Statistics Endpoints (风控统计)
# ============================================================================


@router.get("/{account_id}/stats")
async def get_account_stats(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
    days: int = 7,
) -> dict:
    """Get comprehensive statistics for an account.

    Args:
        account_id: Twitter account ID.
        days: Number of days to include (default 7).

    Returns:
        Account statistics including daily breakdown and risk analysis.
    """
    from xspider.admin.services.account_stats_service import AccountStatsService

    # Verify account exists
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    stats_service = AccountStatsService(db)
    return await stats_service.get_account_stats(account_id, days)


@router.get("/{account_id}/activities")
async def get_account_activities(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
    limit: int = 100,
) -> dict:
    """Get recent activities for an account.

    Args:
        account_id: Twitter account ID.
        limit: Maximum number of activities to return (default 100).

    Returns:
        List of recent account activities.
    """
    from xspider.admin.models import AccountActivity

    # Verify account exists
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    # Get activities
    activities_result = await db.execute(
        select(AccountActivity)
        .where(AccountActivity.account_id == account_id)
        .order_by(AccountActivity.created_at.desc())
        .limit(limit)
    )
    activities = list(activities_result.scalars().all())

    return {
        "account_id": account_id,
        "account_name": account.name,
        "total_count": len(activities),
        "activities": [
            {
                "id": a.id,
                "action_type": a.action_type.value,
                "keyword": a.keyword,
                "success": a.success,
                "response_time_ms": a.response_time_ms,
                "result_count": a.result_count,
                "error_code": a.error_code,
                "error_message": a.error_message,
                "is_rate_limited": a.is_rate_limited,
                "created_at": a.created_at.isoformat(),
            }
            for a in activities
        ],
    }


@router.post("/{account_id}/stats/refresh")
async def refresh_account_daily_stats(
    account_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Manually refresh daily statistics for an account.

    Args:
        account_id: Twitter account ID.

    Returns:
        Updated daily statistics.
    """
    from xspider.admin.services.account_stats_service import AccountStatsService

    # Verify account exists
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found",
        )

    stats_service = AccountStatsService(db)
    daily_stats = await stats_service.update_daily_stats(account_id)

    return {
        "success": True,
        "account_id": account_id,
        "date": daily_stats.stat_date.isoformat(),
        "total_requests": daily_stats.total_requests,
        "successful_requests": daily_stats.successful_requests,
        "failed_requests": daily_stats.failed_requests,
        "rate_limit_hits": daily_stats.rate_limit_hits,
        "risk_score": daily_stats.risk_score,
        "anomaly_detected": daily_stats.anomaly_detected,
        "anomaly_reason": daily_stats.anomaly_reason,
    }
