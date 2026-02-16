"""Proxy management routes."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_admin, get_db_session
from xspider.admin.models import AdminUser, ProxyProtocol, ProxyServer, ProxyStatus
from xspider.admin.schemas import (
    ProxyBatchImport,
    ProxyCreate,
    ProxyHealthCheck,
    ProxyResponse,
    ProxyUpdate,
)

router = APIRouter()


def detect_protocol(url: str) -> ProxyProtocol:
    """Detect proxy protocol from URL."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme in ("socks5", "socks5h"):
        return ProxyProtocol.SOCKS5
    elif scheme == "https":
        return ProxyProtocol.HTTPS
    else:
        return ProxyProtocol.HTTP


@router.get("/", response_model=list[ProxyResponse])
async def list_proxies(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    status_filter: ProxyStatus | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> list[ProxyServer]:
    """List all proxies."""
    query = select(ProxyServer).order_by(ProxyServer.created_at.desc())

    if status_filter:
        query = query.where(ProxyServer.status == status_filter)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{proxy_id}", response_model=ProxyResponse)
async def get_proxy(
    proxy_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> ProxyServer:
    """Get proxy details."""
    result = await db.execute(
        select(ProxyServer).where(ProxyServer.id == proxy_id)
    )
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy not found",
        )

    return proxy


@router.post("/", response_model=ProxyResponse, status_code=status.HTTP_201_CREATED)
async def create_proxy(
    request: ProxyCreate,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> ProxyServer:
    """Create a new proxy."""
    proxy = ProxyServer(
        name=request.name,
        url=request.url,
        protocol=request.protocol,
        status=ProxyStatus.ACTIVE,
        created_by=current_user.id,
    )
    db.add(proxy)
    await db.commit()
    await db.refresh(proxy)

    return proxy


@router.put("/{proxy_id}", response_model=ProxyResponse)
async def update_proxy(
    proxy_id: int,
    request: ProxyUpdate,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> ProxyServer:
    """Update a proxy."""
    result = await db.execute(
        select(ProxyServer).where(ProxyServer.id == proxy_id)
    )
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy not found",
        )

    if request.name is not None:
        proxy.name = request.name
    if request.url is not None:
        proxy.url = request.url
    if request.protocol is not None:
        proxy.protocol = request.protocol
    if request.status is not None:
        proxy.status = request.status

    await db.commit()
    await db.refresh(proxy)

    return proxy


@router.delete("/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a proxy."""
    result = await db.execute(
        select(ProxyServer).where(ProxyServer.id == proxy_id)
    )
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy not found",
        )

    await db.delete(proxy)
    await db.commit()


@router.post("/batch-import", response_model=list[ProxyResponse])
async def batch_import_proxies(
    request: ProxyBatchImport,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> list[ProxyServer]:
    """Batch import proxies from URL list."""
    proxies = []

    for url in request.urls:
        url = url.strip()
        if not url:
            continue

        # Detect protocol from URL if not specified
        protocol = request.protocol
        if protocol == ProxyProtocol.HTTP:
            protocol = detect_protocol(url)

        proxy = ProxyServer(
            url=url,
            protocol=protocol,
            status=ProxyStatus.ACTIVE,
            created_by=current_user.id,
        )
        db.add(proxy)
        proxies.append(proxy)

    await db.commit()

    for proxy in proxies:
        await db.refresh(proxy)

    return proxies


@router.post("/{proxy_id}/check", response_model=ProxyHealthCheck)
async def check_proxy_health(
    proxy_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> ProxyHealthCheck:
    """Check proxy health by making a test request."""
    from xspider.admin.services.proxy_checker import ProxyCheckerService

    result = await db.execute(
        select(ProxyServer).where(ProxyServer.id == proxy_id)
    )
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy not found",
        )

    checker = ProxyCheckerService(db)
    check_result = await checker.check_proxy(proxy)

    return ProxyHealthCheck(
        proxy_id=proxy.id,
        status=check_result.status,
        response_time=check_result.response_time,
        error_message=check_result.error_message,
    )


@router.post("/check-all", response_model=list[ProxyHealthCheck])
async def check_all_proxies(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> list[ProxyHealthCheck]:
    """Check health of all proxies."""
    from xspider.admin.services.proxy_checker import ProxyCheckerService

    result = await db.execute(select(ProxyServer))
    proxies = list(result.scalars().all())

    checker = ProxyCheckerService(db)
    results = []

    for proxy in proxies:
        check_result = await checker.check_proxy(proxy)
        results.append(
            ProxyHealthCheck(
                proxy_id=proxy.id,
                status=check_result.status,
                response_time=check_result.response_time,
                error_message=check_result.error_message,
            )
        )

    return results


@router.post("/{proxy_id}/reset-stats", response_model=ProxyResponse)
async def reset_proxy_stats(
    proxy_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: AsyncSession = Depends(get_db_session),
) -> ProxyServer:
    """Reset proxy statistics."""
    result = await db.execute(
        select(ProxyServer).where(ProxyServer.id == proxy_id)
    )
    proxy = result.scalar_one_or_none()

    if not proxy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proxy not found",
        )

    proxy.total_requests = 0
    proxy.failed_requests = 0
    proxy.success_rate = 100.0
    proxy.response_time = None

    if proxy.status == ProxyStatus.ERROR:
        proxy.status = ProxyStatus.ACTIVE

    await db.commit()
    await db.refresh(proxy)

    return proxy
