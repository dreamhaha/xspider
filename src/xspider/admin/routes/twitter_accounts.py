"""Twitter accounts management routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_admin, get_db_session
from xspider.admin.models import AccountStatus, AdminUser, TwitterAccount
from xspider.admin.schemas import (
    AccountStatusCheck,
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
    db: AsyncSession = Depends(get_db_session),
) -> list[TwitterAccount]:
    """List all Twitter accounts."""
    query = select(TwitterAccount).order_by(TwitterAccount.created_at.desc())

    if status_filter:
        query = query.where(TwitterAccount.status == status_filter)

    result = await db.execute(query)
    return list(result.scalars().all())


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
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
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

    await db.commit()
    await db.refresh(account)

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
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id == account_id)
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
    await db.refresh(account)

    return account
