"""Twitter account monitoring service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from twikit import Client
from twikit.errors import TooManyRequests, Unauthorized, Forbidden

from xspider.admin.models import AccountStatus, ProxyServer, ProxyStatus, TwitterAccount
from xspider.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AccountCheckResult:
    """Result of account status check."""

    status: AccountStatus
    error_message: str | None = None
    rate_limit_reset: datetime | None = None


class AccountMonitorService:
    """Service for monitoring Twitter account status using twikit."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_active_proxy(self) -> ProxyServer | None:
        """Get an active proxy from the database."""
        result = await self.db.execute(
            select(ProxyServer)
            .where(ProxyServer.status == ProxyStatus.ACTIVE)
            .order_by(ProxyServer.last_check_at.asc().nulls_first())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _get_proxy_url(self, proxy: ProxyServer) -> str:
        """Get properly formatted proxy URL for twikit."""
        from xspider.admin.models import ProxyProtocol

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

    async def check_account(self, account: TwitterAccount) -> AccountCheckResult:
        """Check if a Twitter account is working by making a test API call using twikit."""
        # Validate required tokens (only ct0 and auth_token needed for twikit)
        if not account.ct0 or not account.auth_token:
            logger.warning("Account missing ct0 or auth_token", account_id=account.id)
            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message="Missing ct0 or auth_token - please update account credentials",
            )

        now = datetime.now(timezone.utc)

        # Get an active proxy
        proxy = await self._get_active_proxy()
        proxy_url = None
        if proxy:
            proxy_url = self._get_proxy_url(proxy)
            logger.info(
                "account_monitor.using_proxy",
                account_id=account.id,
                proxy_id=proxy.id,
            )

        try:
            # Create twikit client with proxy support
            client = Client(language="en-US", proxy=proxy_url)

            # Set cookies
            client.set_cookies({
                "ct0": account.ct0,
                "auth_token": account.auth_token,
            })

            # Try to search for a simple user to verify account works
            # Using 'twitter' as a test query - always exists
            await client.search_user("twitter", count=1)

            # Success - account is working
            account.status = AccountStatus.ACTIVE
            account.last_check_at = now
            account.error_count = 0
            account.last_error = None
            await self.db.commit()

            logger.info(
                "account_monitor.check_success",
                account_id=account.id,
                proxy_used=proxy.id if proxy else None,
            )

            return AccountCheckResult(status=AccountStatus.ACTIVE)

        except TooManyRequests:
            # Rate limited
            account.status = AccountStatus.RATE_LIMITED
            account.last_check_at = now
            account.last_error = "Rate limited by Twitter"
            await self.db.commit()

            return AccountCheckResult(
                status=AccountStatus.RATE_LIMITED,
                error_message="Rate limited by Twitter",
            )

        except Unauthorized:
            # Authentication failed
            error_msg = "Authentication failed - tokens may be expired"
            account.status = AccountStatus.ERROR
            account.last_check_at = now
            account.error_count += 1
            account.last_error = error_msg
            await self.db.commit()

            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message=error_msg,
            )

        except Forbidden as e:
            error_str = str(e).lower()
            # Check for specific error conditions
            if "326" in error_str or "verify" in error_str or "locked" in error_str:
                error_msg = "Account needs verification"
                account.status = AccountStatus.NEEDS_VERIFY
                account.last_check_at = now
                account.last_error = error_msg
                await self.db.commit()

                return AccountCheckResult(
                    status=AccountStatus.NEEDS_VERIFY,
                    error_message=error_msg,
                )

            if "63" in error_str or "suspend" in error_str:
                error_msg = "Account is suspended"
                account.status = AccountStatus.BANNED
                account.last_check_at = now
                account.last_error = error_msg
                await self.db.commit()

                return AccountCheckResult(
                    status=AccountStatus.BANNED,
                    error_message=error_msg,
                )

            error_msg = f"Access forbidden: {str(e)[:100]}"
            account.status = AccountStatus.ERROR
            account.last_check_at = now
            account.error_count += 1
            account.last_error = error_msg
            await self.db.commit()

            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message=error_msg,
            )

        except Exception as e:
            error_str = str(e) or type(e).__name__
            error_type = type(e).__name__
            logger.warning(
                "account_monitor.check_failed",
                account_id=account.id,
                error_type=error_type,
                error=error_str,
                proxy_used=proxy.id if proxy else None,
            )

            # Check for rate limit in error message
            if "429" in error_str or "rate limit" in error_str.lower():
                error_msg = "Rate limited by Twitter"
                account.status = AccountStatus.RATE_LIMITED
                account.last_check_at = now
                account.last_error = error_msg
                await self.db.commit()

                return AccountCheckResult(
                    status=AccountStatus.RATE_LIMITED,
                    error_message=error_msg,
                )

            # Check for timeout errors
            if "Timeout" in error_type or "timeout" in error_str.lower():
                error_msg = f"Connection timeout: {error_type}"
                account.status = AccountStatus.ERROR
                account.last_check_at = now
                account.last_error = error_msg
                # Don't increment error_count for timeouts
                await self.db.commit()

                return AccountCheckResult(
                    status=AccountStatus.ERROR,
                    error_message=error_msg,
                )

            # Check for internal twikit errors (likely stale cookies)
            if "ClientTransaction" in error_str or "attribute" in error_str.lower():
                error_msg = f"Auth token expired: {error_type}"
                account.status = AccountStatus.ERROR
                account.last_check_at = now
                account.error_count += 1
                account.last_error = error_msg
                await self.db.commit()

                return AccountCheckResult(
                    status=AccountStatus.ERROR,
                    error_message=error_msg,
                )

            error_msg = f"Check failed: {error_type} - {error_str[:80]}"
            account.status = AccountStatus.ERROR
            account.last_check_at = now
            account.error_count += 1
            account.last_error = error_msg
            await self.db.commit()

            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message=error_msg,
            )

    async def check_all_accounts(self) -> list[tuple[TwitterAccount, AccountCheckResult]]:
        """Check all accounts and return results."""
        result = await self.db.execute(select(TwitterAccount))
        accounts = list(result.scalars().all())

        results = []
        for account in accounts:
            check_result = await self.check_account(account)
            results.append((account, check_result))

        return results
