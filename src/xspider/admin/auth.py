"""JWT authentication and authorization for admin module."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import AdminUser, APIKey, UserRole
from xspider.storage.database import get_database


# JWT Configuration
JWT_SECRET_KEY = secrets.token_urlsafe(32)
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
JWT_REFRESH_TOKEN_EXPIRE_DAYS = 7

# API Key Configuration
API_KEY_PREFIX = "xsp_"
API_KEY_SECRET_PREFIX = "sk_"

# Security
security = HTTPBearer(auto_error=False)


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str  # user_id
    username: str
    role: str
    exp: datetime
    iat: datetime


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def generate_api_key_id() -> str:
    """Generate an 8-character API key identifier."""
    return secrets.token_hex(4)


def generate_api_key_secret() -> str:
    """Generate a 32-character API key secret."""
    return secrets.token_hex(16)


def create_full_api_key(key_id: str, secret: str) -> str:
    """Create the full API key string: xsp_<key_id>_sk_<secret>."""
    return f"{API_KEY_PREFIX}{key_id}_{API_KEY_SECRET_PREFIX}{secret}"


def parse_api_key(api_key: str) -> tuple[str, str] | None:
    """Parse an API key into (key_id, secret). Returns None if invalid format."""
    if not api_key.startswith(API_KEY_PREFIX):
        return None

    # Remove prefix: xsp_
    remaining = api_key[len(API_KEY_PREFIX) :]

    # Split by _sk_
    parts = remaining.split(f"_{API_KEY_SECRET_PREFIX}")
    if len(parts) != 2:
        return None

    key_id, secret = parts
    if len(key_id) != 8 or len(secret) != 32:
        return None

    return key_id, secret


def hash_api_key_secret(secret: str) -> str:
    """Hash an API key secret using bcrypt."""
    return hash_password(secret)


def verify_api_key_secret(plain_secret: str, hashed_secret: str) -> bool:
    """Verify an API key secret against its hash."""
    return verify_password(plain_secret, hashed_secret)


async def validate_api_key(
    api_key: str,
    db: AsyncSession,
) -> tuple[APIKey, AdminUser] | None:
    """Validate an API key and return the key and associated user.

    Returns None if the key is invalid, expired, or revoked.
    Updates last_used_at on successful validation.
    """
    parsed = parse_api_key(api_key)
    if not parsed:
        return None

    key_id, secret = parsed

    # Find the API key by key_id
    result = await db.execute(
        select(APIKey).where(APIKey.key_id == key_id, APIKey.is_active == True)  # noqa: E712
    )
    api_key_record = result.scalar_one_or_none()

    if not api_key_record:
        return None

    # Check expiration
    if api_key_record.expires_at:
        if datetime.now(timezone.utc) > api_key_record.expires_at.replace(
            tzinfo=timezone.utc
        ):
            return None

    # Verify secret
    if not verify_api_key_secret(secret, api_key_record.secret_hash):
        return None

    # Get the associated user
    result = await db.execute(
        select(AdminUser).where(AdminUser.id == api_key_record.user_id)
    )
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        return None

    # Update last_used_at
    api_key_record.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return api_key_record, user


def create_access_token(
    user_id: int,
    username: str,
    role: UserRole,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES))

    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role.value,
        "exp": expire,
        "iat": now,
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> TokenPayload | None:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return TokenPayload(
            sub=payload["sub"],
            username=payload["username"],
            role=payload["role"],
            exp=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            iat=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
        )
    except JWTError:
        return None


async def get_db_session() -> AsyncSession:
    """Get database session dependency."""
    db = get_database()
    async with db.session() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    session_token: Annotated[str | None, Cookie(alias="session_token")] = None,
    db: AsyncSession = Depends(get_db_session),
) -> AdminUser:
    """Get the current authenticated user from JWT token or API key."""
    token = None

    # Check for X-API-Key header first
    x_api_key = request.headers.get("X-API-Key")
    if x_api_key:
        result = await validate_api_key(x_api_key, db)
        if result:
            api_key_record, user = result
            request.state.api_key = api_key_record
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Try to get token from Authorization header
    if credentials:
        token = credentials.credentials
    # Fall back to session cookie
    elif session_token:
        token = session_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if it's an API key (starts with xsp_)
    if token.startswith(API_KEY_PREFIX):
        result = await validate_api_key(token, db)
        if result:
            api_key_record, user = result
            request.state.api_key = api_key_record
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Otherwise, treat as JWT token
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user from database
    user_id = int(payload.sub)
    result = await db.execute(select(AdminUser).where(AdminUser.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )

    return user


async def get_current_active_user(
    current_user: Annotated[AdminUser, Depends(get_current_user)],
) -> AdminUser:
    """Ensure user is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


async def get_current_admin(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
) -> AdminUser:
    """Ensure current user is an admin."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_admin(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
) -> AdminUser:
    """Dependency that requires admin role."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str,
) -> AdminUser | None:
    """Authenticate a user by username and password."""
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == username)
    )
    user = result.scalar_one_or_none()

    if not user:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user


async def create_default_admin(db: AsyncSession) -> AdminUser | None:
    """Create default admin user if none exists."""
    result = await db.execute(
        select(AdminUser).where(AdminUser.role == UserRole.ADMIN)
    )
    admin = result.scalar_one_or_none()

    if admin:
        return None

    # Create default admin
    admin = AdminUser(
        username="admin",
        email="admin@xspider.local",
        password_hash=hash_password("admin123"),
        role=UserRole.ADMIN,
        credits=999999,
        is_active=True,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)

    return admin
