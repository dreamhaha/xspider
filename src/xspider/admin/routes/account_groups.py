"""Account groups management routes."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_admin, get_db_session
from xspider.admin.models import AccountGroup, AccountStatus, AdminUser, TwitterAccount
from xspider.admin.schemas import (
    AccountGroupAssignRequest,
    AccountGroupCreate,
    AccountGroupListResponse,
    AccountGroupResponse,
    AccountGroupTagsResponse,
    AccountGroupUpdate,
)

router = APIRouter()


async def _update_group_counts(db: AsyncSession, group_id: int) -> None:
    """Update cached account counts for a group."""
    # Get total count
    total_result = await db.execute(
        select(func.count())
        .select_from(TwitterAccount)
        .where(TwitterAccount.group_id == group_id)
    )
    total_count = total_result.scalar() or 0

    # Get active count
    active_result = await db.execute(
        select(func.count())
        .select_from(TwitterAccount)
        .where(TwitterAccount.group_id == group_id)
        .where(TwitterAccount.status == AccountStatus.ACTIVE)
    )
    active_count = active_result.scalar() or 0

    # Update the group
    group_result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id)
    )
    group = group_result.scalar_one_or_none()
    if group:
        group.account_count = total_count
        group.active_account_count = active_count


@router.get("/", response_model=AccountGroupListResponse)
async def list_groups(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
    is_active: bool | None = None,
) -> AccountGroupListResponse:
    """List all account groups."""
    query = select(AccountGroup).order_by(AccountGroup.priority.desc(), AccountGroup.name.asc())

    if is_active is not None:
        query = query.where(AccountGroup.is_active == is_active)

    result = await db.execute(query)
    groups = list(result.scalars().all())

    return AccountGroupListResponse(
        groups=[AccountGroupResponse.model_validate(g) for g in groups],
        total=len(groups),
    )


@router.post("/", response_model=AccountGroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    request: AccountGroupCreate,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountGroup:
    """Create a new account group."""
    # Check for duplicate name
    existing = await db.execute(
        select(AccountGroup).where(AccountGroup.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group name already exists",
        )

    # Convert tags list to JSON string
    tags_json = json.dumps(request.tags) if request.tags else None

    group = AccountGroup(
        name=request.name,
        description=request.description,
        tags=tags_json,
        color=request.color,
        is_active=request.is_active,
        priority=request.priority,
        created_by=current_user.id,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)

    return group


@router.get("/tags", response_model=AccountGroupTagsResponse)
async def get_all_tags(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountGroupTagsResponse:
    """Get all unique tags from all groups."""
    result = await db.execute(
        select(AccountGroup.tags).where(AccountGroup.tags != None)
    )
    all_tags_json = [row[0] for row in result.fetchall()]

    # Extract unique tags
    unique_tags = set()
    for tags_json in all_tags_json:
        try:
            tags = json.loads(tags_json)
            if isinstance(tags, list):
                unique_tags.update(tags)
        except (json.JSONDecodeError, TypeError):
            pass

    return AccountGroupTagsResponse(tags=sorted(unique_tags))


@router.get("/{group_id}", response_model=AccountGroupResponse)
async def get_group(
    group_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountGroup:
    """Get account group details."""
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    return group


@router.put("/{group_id}", response_model=AccountGroupResponse)
async def update_group(
    group_id: int,
    request: AccountGroupUpdate,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountGroup:
    """Update an account group."""
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    # Check for duplicate name if updating name
    if request.name is not None and request.name != group.name:
        existing = await db.execute(
            select(AccountGroup).where(AccountGroup.name == request.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name already exists",
            )
        group.name = request.name

    if request.description is not None:
        group.description = request.description
    if request.tags is not None:
        group.tags = json.dumps(request.tags)
    if request.color is not None:
        group.color = request.color
    if request.is_active is not None:
        group.is_active = request.is_active
    if request.priority is not None:
        group.priority = request.priority

    await db.commit()
    await db.refresh(group)

    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete an account group.

    Accounts in this group will become ungrouped (group_id = NULL).
    """
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    # Accounts will automatically have group_id set to NULL due to ondelete="SET NULL"
    await db.delete(group)
    await db.commit()


@router.post("/{group_id}/toggle-active", response_model=AccountGroupResponse)
async def toggle_group_active(
    group_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountGroup:
    """Toggle group active status."""
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    group.is_active = not group.is_active
    await db.commit()
    await db.refresh(group)

    return group


@router.post("/{group_id}/add-accounts", response_model=AccountGroupResponse)
async def add_accounts_to_group(
    group_id: int,
    request: AccountGroupAssignRequest,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountGroup:
    """Add accounts to a group."""
    # Verify group exists
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    # Update accounts
    accounts_result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.id.in_(request.account_ids))
    )
    accounts = list(accounts_result.scalars().all())

    for account in accounts:
        account.group_id = group_id

    # Update group counts
    await _update_group_counts(db, group_id)

    await db.commit()
    await db.refresh(group)

    return group


@router.post("/{group_id}/remove-accounts", response_model=AccountGroupResponse)
async def remove_accounts_from_group(
    group_id: int,
    request: AccountGroupAssignRequest,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AccountGroup:
    """Remove accounts from a group (make them ungrouped)."""
    # Verify group exists
    result = await db.execute(
        select(AccountGroup).where(AccountGroup.id == group_id)
    )
    group = result.scalar_one_or_none()

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    # Update accounts - set group_id to NULL
    accounts_result = await db.execute(
        select(TwitterAccount)
        .where(TwitterAccount.id.in_(request.account_ids))
        .where(TwitterAccount.group_id == group_id)
    )
    accounts = list(accounts_result.scalars().all())

    for account in accounts:
        account.group_id = None

    # Update group counts
    await _update_group_counts(db, group_id)

    await db.commit()
    await db.refresh(group)

    return group
