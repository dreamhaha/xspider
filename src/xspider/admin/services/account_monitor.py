"""Twitter account monitoring service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import AccountStatus, TwitterAccount
from xspider.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AccountCheckResult:
    """Result of account status check."""

    status: AccountStatus
    error_message: str | None = None
    rate_limit_reset: datetime | None = None


class AccountMonitorService:
    """Service for monitoring Twitter account status."""

    # Twitter GraphQL endpoint for simple user lookup
    CHECK_URL = "https://twitter.com/i/api/graphql/G3KGOASz96M-Qu0nwmGXNg/UserByScreenName"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def check_account(self, account: TwitterAccount) -> AccountCheckResult:
        """Check if a Twitter account is working by making a test API call."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                headers = {
                    "Authorization": f"Bearer {account.bearer_token}",
                    "X-Csrf-Token": account.ct0,
                    "Cookie": f"auth_token={account.auth_token}; ct0={account.ct0}",
                    "Content-Type": "application/json",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "X-Twitter-Active-User": "yes",
                    "X-Twitter-Auth-Type": "OAuth2Session",
                }

                # Simple query to check if account is valid
                params = {
                    "variables": '{"screen_name":"twitter","withSafetyModeUserFields":true}',
                    "features": (
                        '{"hidden_profile_subscriptions_enabled":true,'
                        '"rweb_tipjar_consumption_enabled":true,'
                        '"responsive_web_graphql_exclude_directive_enabled":true,'
                        '"verified_phone_label_enabled":false,'
                        '"subscriptions_verification_info_is_identity_verified_enabled":true,'
                        '"subscriptions_verification_info_verified_since_enabled":true,'
                        '"highlights_tweets_tab_ui_enabled":true,'
                        '"responsive_web_twitter_article_notes_tab_enabled":true,'
                        '"subscriptions_feature_can_gift_premium":true,'
                        '"creator_subscriptions_tweet_preview_api_enabled":true,'
                        '"responsive_web_graphql_skip_user_profile_image_extensions_enabled":false,'
                        '"responsive_web_graphql_timeline_navigation_enabled":true}'
                    ),
                    "fieldToggles": '{"withAuxiliaryUserLabels":false}',
                }

                response = await client.get(
                    self.CHECK_URL,
                    headers=headers,
                    params=params,
                )

                result = await self._process_response(response, account)
                return result

        except httpx.TimeoutException:
            logger.warning("Account check timed out", account_id=account.id)
            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message="Request timed out",
            )
        except httpx.RequestError as e:
            logger.error("Account check request failed", account_id=account.id, error=str(e))
            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message=f"Request error: {str(e)}",
            )
        except Exception as e:
            logger.exception("Account check failed", account_id=account.id)
            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message=f"Unexpected error: {str(e)}",
            )

    async def _process_response(
        self,
        response: httpx.Response,
        account: TwitterAccount,
    ) -> AccountCheckResult:
        """Process the API response and determine account status."""
        now = datetime.now(timezone.utc)

        if response.status_code == 200:
            # Account is working
            account.status = AccountStatus.ACTIVE
            account.last_check_at = now
            account.error_count = 0
            await self.db.commit()

            return AccountCheckResult(status=AccountStatus.ACTIVE)

        if response.status_code == 429:
            # Rate limited
            rate_limit_reset = None
            reset_header = response.headers.get("x-rate-limit-reset")
            if reset_header:
                try:
                    rate_limit_reset = datetime.fromtimestamp(
                        int(reset_header), tz=timezone.utc
                    )
                except (ValueError, TypeError):
                    pass

            account.status = AccountStatus.RATE_LIMITED
            account.last_check_at = now
            account.rate_limit_reset = rate_limit_reset
            await self.db.commit()

            return AccountCheckResult(
                status=AccountStatus.RATE_LIMITED,
                error_message="Rate limited by Twitter",
                rate_limit_reset=rate_limit_reset,
            )

        if response.status_code == 401:
            # Authentication failed - token expired or invalid
            account.status = AccountStatus.ERROR
            account.last_check_at = now
            account.error_count += 1
            await self.db.commit()

            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message="Authentication failed - token may be expired",
            )

        if response.status_code == 403:
            # Check if account needs verification or is suspended
            try:
                data = response.json()
                errors = data.get("errors", [])
                for error in errors:
                    code = error.get("code")
                    if code == 326:  # Account locked/needs verification
                        account.status = AccountStatus.NEEDS_VERIFY
                        account.last_check_at = now
                        await self.db.commit()

                        return AccountCheckResult(
                            status=AccountStatus.NEEDS_VERIFY,
                            error_message="Account needs verification",
                        )
                    if code == 63:  # Account suspended
                        account.status = AccountStatus.BANNED
                        account.last_check_at = now
                        await self.db.commit()

                        return AccountCheckResult(
                            status=AccountStatus.BANNED,
                            error_message="Account is suspended",
                        )
            except Exception:
                pass

            account.status = AccountStatus.ERROR
            account.last_check_at = now
            account.error_count += 1
            await self.db.commit()

            return AccountCheckResult(
                status=AccountStatus.ERROR,
                error_message=f"Access forbidden (HTTP 403)",
            )

        # Other error status codes
        account.status = AccountStatus.ERROR
        account.last_check_at = now
        account.error_count += 1
        await self.db.commit()

        return AccountCheckResult(
            status=AccountStatus.ERROR,
            error_message=f"HTTP {response.status_code}",
        )

    async def check_all_accounts(self) -> list[tuple[TwitterAccount, AccountCheckResult]]:
        """Check all accounts and return results."""
        from sqlalchemy import select

        result = await self.db.execute(select(TwitterAccount))
        accounts = list(result.scalars().all())

        results = []
        for account in accounts:
            check_result = await self.check_account(account)
            results.append((account, check_result))

        return results
