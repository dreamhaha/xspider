"""Authentication routes for admin module."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_user,
    create_access_token,
    get_current_active_user,
    get_db_session,
    hash_password,
)
from xspider.admin.models import AdminUser, UserRole
from xspider.admin.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    """Authenticate user and return JWT token."""
    user = await authenticate_user(db, request.username, request.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    # Update last login time
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    # Create access token
    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )

    # Set cookie for web UI
    response.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True,
        max_age=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db_session),
) -> AdminUser:
    """Register a new user account."""
    # Check if username exists
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == request.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    # Check if email exists
    result = await db.execute(
        select(AdminUser).where(AdminUser.email == request.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user
    user = AdminUser(
        username=request.username,
        email=request.email,
        password_hash=hash_password(request.password),
        role=UserRole.USER,
        credits=0,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    """Logout user by clearing session cookie."""
    response.delete_cookie(key="session_token")
    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
) -> AdminUser:
    """Get current authenticated user info."""
    return current_user


@router.post("/change-password")
async def change_password(
    current_password: str,
    new_password: str,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Change current user's password."""
    from xspider.admin.auth import verify_password

    if not verify_password(current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    if len(new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 6 characters",
        )

    current_user.password_hash = hash_password(new_password)
    await db.commit()

    return {"message": "Password changed successfully"}
