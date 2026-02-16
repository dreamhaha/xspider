"""User management routes for admin module."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_admin, get_db_session, hash_password
from xspider.admin.i18n import get_lang, t
from xspider.admin.models import AdminUser, CreditTransaction, TransactionType, UserRole
from xspider.admin.schemas import (
    CreditRechargeRequest,
    CreditTransactionResponse,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)

router = APIRouter()


@router.get("/", response_model=UserListResponse)
async def list_users(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: UserRole | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> UserListResponse:
    """List all users with pagination."""
    query = select(AdminUser).order_by(AdminUser.created_at.desc())

    if role:
        query = query.where(AdminUser.role == role)

    # Count total
    count_query = select(func.count(AdminUser.id))
    if role:
        count_query = count_query.where(AdminUser.role == role)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    users = list(result.scalars().all())

    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AdminUser:
    """Get user details."""
    lang = get_lang(request)
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("common.user_not_found", lang),
        )

    return user


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    create_request: UserCreateRequest,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AdminUser:
    """Create a new user."""
    lang = get_lang(request)

    # Check if username exists
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == create_request.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("users.username_exists", lang),
        )

    # Check if email exists
    result = await db.execute(
        select(AdminUser).where(AdminUser.email == create_request.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("users.email_exists", lang),
        )

    user = AdminUser(
        username=create_request.username,
        email=create_request.email,
        password_hash=hash_password(create_request.password),
        role=create_request.role,
        credits=create_request.credits,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    update_request: UserUpdateRequest,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AdminUser:
    """Update a user."""
    lang = get_lang(request)
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("common.user_not_found", lang),
        )

    # Prevent demoting self
    if user.id == current_user.id and update_request.role and update_request.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("users.cannot_demote_self", lang),
        )

    # Check email uniqueness if updating
    if update_request.email and update_request.email != user.email:
        email_result = await db.execute(
            select(AdminUser).where(AdminUser.email == update_request.email)
        )
        if email_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("users.email_exists", lang),
            )
        user.email = update_request.email

    if update_request.role is not None:
        user.role = update_request.role
    if update_request.is_active is not None:
        user.is_active = update_request.is_active

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a user."""
    lang = get_lang(request)

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("users.cannot_delete_self", lang),
        )

    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("common.user_not_found", lang),
        )

    await db.delete(user)
    await db.commit()


@router.post("/{user_id}/recharge", response_model=CreditTransactionResponse)
async def recharge_credits(
    user_id: int,
    recharge_request: CreditRechargeRequest,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> CreditTransaction:
    """Recharge user credits."""
    lang = get_lang(request)
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("common.user_not_found", lang),
        )

    # Update user credits
    user.credits += recharge_request.amount
    new_balance = user.credits

    # Create transaction record
    transaction = CreditTransaction(
        user_id=user_id,
        amount=recharge_request.amount,
        balance_after=new_balance,
        type=TransactionType.RECHARGE,
        description=recharge_request.description or f"Admin recharge by {current_user.username}",
        created_by=current_user.id,
    )
    db.add(transaction)

    await db.commit()
    await db.refresh(transaction)

    return transaction


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: int,
    new_password: str,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Reset user password (admin only)."""
    lang = get_lang(request)
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("common.user_not_found", lang),
        )

    if len(new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("auth.password_too_short", lang),
        )

    user.password_hash = hash_password(new_password)
    await db.commit()

    return {"message": t("users.password_reset", lang, username=user.username)}


@router.get("/{user_id}/transactions", response_model=list[CreditTransactionResponse])
async def get_user_transactions(
    user_id: int,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> list[CreditTransaction]:
    """Get user's credit transaction history."""
    lang = get_lang(request)
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("common.user_not_found", lang),
        )

    tx_result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )

    return list(tx_result.scalars().all())


@router.post("/{user_id}/toggle-active", response_model=UserResponse)
async def toggle_user_active(
    user_id: int,
    request: Request,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> AdminUser:
    """Toggle user active status."""
    lang = get_lang(request)

    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("users.cannot_deactivate_self", lang),
        )

    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("common.user_not_found", lang),
        )

    user.is_active = not user.is_active
    await db.commit()
    await db.refresh(user)

    return user
