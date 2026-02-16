"""Proxy health checking service."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import ProxyProtocol, ProxyServer, ProxyStatus
from xspider.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ProxyCheckResult:
    """Result of proxy health check."""

    status: ProxyStatus
    response_time: float | None = None
    error_message: str | None = None


class ProxyCheckerService:
    """Service for checking proxy health."""

    # URL to test proxy connectivity
    TEST_URL = "https://httpbin.org/ip"
    TIMEOUT = 30.0

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _get_proxy_url(self, proxy: ProxyServer) -> str:
        """Get properly formatted proxy URL."""
        url = proxy.url

        # Ensure URL has protocol prefix
        if not url.startswith(("http://", "https://", "socks5://")):
            if proxy.protocol == ProxyProtocol.SOCKS5:
                url = f"socks5://{url}"
            elif proxy.protocol == ProxyProtocol.HTTPS:
                url = f"https://{url}"
            else:
                url = f"http://{url}"

        return url

    async def check_proxy(self, proxy: ProxyServer) -> ProxyCheckResult:
        """Check if a proxy is working by making a test request."""
        proxy_url = self._get_proxy_url(proxy)
        now = datetime.now(timezone.utc)

        try:
            start_time = time.monotonic()

            async with httpx.AsyncClient(
                timeout=self.TIMEOUT,
                proxy=proxy_url,
            ) as client:
                response = await client.get(self.TEST_URL)

            elapsed = (time.monotonic() - start_time) * 1000  # Convert to ms

            if response.status_code == 200:
                # Proxy is working
                proxy.status = ProxyStatus.ACTIVE
                proxy.last_check_at = now
                proxy.response_time = elapsed
                proxy.total_requests += 1

                # Update success rate
                if proxy.total_requests > 0:
                    success_count = proxy.total_requests - proxy.failed_requests
                    proxy.success_rate = (success_count / proxy.total_requests) * 100

                await self.db.commit()

                return ProxyCheckResult(
                    status=ProxyStatus.ACTIVE,
                    response_time=elapsed,
                )
            else:
                # Request succeeded but got error status
                proxy.status = ProxyStatus.ERROR
                proxy.last_check_at = now
                proxy.total_requests += 1
                proxy.failed_requests += 1

                if proxy.total_requests > 0:
                    success_count = proxy.total_requests - proxy.failed_requests
                    proxy.success_rate = (success_count / proxy.total_requests) * 100

                await self.db.commit()

                return ProxyCheckResult(
                    status=ProxyStatus.ERROR,
                    error_message=f"HTTP {response.status_code}",
                )

        except httpx.TimeoutException:
            proxy.status = ProxyStatus.ERROR
            proxy.last_check_at = now
            proxy.total_requests += 1
            proxy.failed_requests += 1

            if proxy.total_requests > 0:
                success_count = proxy.total_requests - proxy.failed_requests
                proxy.success_rate = (success_count / proxy.total_requests) * 100

            await self.db.commit()

            return ProxyCheckResult(
                status=ProxyStatus.ERROR,
                error_message="Connection timed out",
            )

        except httpx.ProxyError as e:
            proxy.status = ProxyStatus.ERROR
            proxy.last_check_at = now
            proxy.total_requests += 1
            proxy.failed_requests += 1

            if proxy.total_requests > 0:
                success_count = proxy.total_requests - proxy.failed_requests
                proxy.success_rate = (success_count / proxy.total_requests) * 100

            await self.db.commit()

            return ProxyCheckResult(
                status=ProxyStatus.ERROR,
                error_message=f"Proxy error: {str(e)}",
            )

        except httpx.RequestError as e:
            proxy.status = ProxyStatus.ERROR
            proxy.last_check_at = now
            proxy.total_requests += 1
            proxy.failed_requests += 1

            if proxy.total_requests > 0:
                success_count = proxy.total_requests - proxy.failed_requests
                proxy.success_rate = (success_count / proxy.total_requests) * 100

            await self.db.commit()

            return ProxyCheckResult(
                status=ProxyStatus.ERROR,
                error_message=f"Request error: {str(e)}",
            )

        except Exception as e:
            logger.exception("Proxy check failed", proxy_id=proxy.id)

            proxy.status = ProxyStatus.ERROR
            proxy.last_check_at = now
            proxy.total_requests += 1
            proxy.failed_requests += 1

            if proxy.total_requests > 0:
                success_count = proxy.total_requests - proxy.failed_requests
                proxy.success_rate = (success_count / proxy.total_requests) * 100

            await self.db.commit()

            return ProxyCheckResult(
                status=ProxyStatus.ERROR,
                error_message=f"Unexpected error: {str(e)}",
            )

    async def check_all_proxies(self) -> list[tuple[ProxyServer, ProxyCheckResult]]:
        """Check all proxies and return results."""
        from sqlalchemy import select

        result = await self.db.execute(select(ProxyServer))
        proxies = list(result.scalars().all())

        results = []
        for proxy in proxies:
            check_result = await self.check_proxy(proxy)
            results.append((proxy, check_result))

        return results
