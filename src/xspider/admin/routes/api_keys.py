"""API key management routes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import (
    create_full_api_key,
    generate_api_key_id,
    generate_api_key_secret,
    get_current_active_user,
    get_db_session,
    hash_api_key_secret,
)
from xspider.admin.models import AdminUser, APIKey
from xspider.admin.schemas import (
    APIKeyCreateRequest,
    APIKeyCreatedResponse,
    APIKeyListResponse,
    APIKeyResponse,
)

router = APIRouter()


@router.post("/keys", response_model=APIKeyCreatedResponse)
async def create_api_key(
    request: APIKeyCreateRequest,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> APIKeyCreatedResponse:
    """Create a new API key for the current user.

    The full API key is only shown once in the response.
    """
    # Generate key components
    key_id = generate_api_key_id()
    secret = generate_api_key_secret()
    secret_hash = hash_api_key_secret(secret)

    # Calculate expiration
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=request.expires_in_days)

    # Create API key record
    api_key = APIKey(
        user_id=current_user.id,
        key_id=key_id,
        secret_hash=secret_hash,
        name=request.name,
        is_active=True,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    # Create the full API key string
    full_api_key = create_full_api_key(key_id, secret)

    return APIKeyCreatedResponse(
        id=api_key.id,
        key_id=api_key.key_id,
        name=api_key.name,
        api_key=full_api_key,
        created_at=api_key.created_at,
        expires_at=api_key.expires_at,
    )


@router.get("/keys", response_model=APIKeyListResponse)
async def list_api_keys(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> APIKeyListResponse:
    """List all API keys for the current user."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.user_id == current_user.id)
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()

    return APIKeyListResponse(
        keys=[
            APIKeyResponse(
                id=key.id,
                key_id=key.key_id,
                name=key.name,
                is_active=key.is_active,
                created_at=key.created_at,
                last_used_at=key.last_used_at,
                expires_at=key.expires_at,
            )
            for key in keys
        ]
    )


@router.delete("/keys/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Revoke an API key by its key_id."""
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_id == key_id,
            APIKey.user_id == current_user.id,
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    # Deactivate the key
    api_key.is_active = False
    await db.commit()

    return {"message": "API key revoked"}


@router.get("/keys/{key_id}", response_model=APIKeyResponse)
async def get_api_key(
    key_id: str,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> APIKeyResponse:
    """Get details of a specific API key."""
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_id == key_id,
            APIKey.user_id == current_user.id,
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )

    return APIKeyResponse(
        id=api_key.id,
        key_id=api_key.key_id,
        name=api_key.name,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
    )
