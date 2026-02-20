"""Import Twitter/X accounts from various formats."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from xspider.core import get_logger

logger = get_logger(__name__)


@dataclass
class ImportedAccount:
    """Parsed account data ready for database import."""

    uid: str
    screen_name: str
    name: str
    ct0: str
    auth_token: str
    language: str | None = None
    timezone: str | None = None
    country: str | None = None
    followers_count: int = 0
    following_count: int = 0
    statuses_count: int = 0
    is_protected: bool = False
    is_suspended: bool = False
    is_blue_verified: bool = False
    profile_image_url: str | None = None


def parse_android_account(account_data: dict[str, Any]) -> ImportedAccount | None:
    """Parse account from Android app export format.

    Expected format:
    {
        "Uid": "1811759512107515906",
        "Language": "th",
        "TimeZone": "Asia/Bangkok",
        "AccountId": "khwchnk30592380",
        "Country": "TH",
        "UserInfo": "{...json string...}",
        "Cookies": [
            {"name": "ct0", "value": "..."},
            {"name": "auth_token", "value": "..."},
            ...
        ]
    }

    Args:
        account_data: Raw account data from Android export.

    Returns:
        ImportedAccount if parsing succeeds, None otherwise.
    """
    try:
        # Extract cookies
        cookies = account_data.get("Cookies", [])
        cookie_map = {c["name"]: c["value"] for c in cookies}

        ct0 = cookie_map.get("ct0")
        auth_token = cookie_map.get("auth_token")

        if not ct0 or not auth_token:
            logger.warning(
                "account_import.missing_cookies",
                uid=account_data.get("Uid"),
                has_ct0=bool(ct0),
                has_auth_token=bool(auth_token),
            )
            return None

        # Parse UserInfo JSON string
        user_info_str = account_data.get("UserInfo", "{}")
        user_info = json.loads(user_info_str) if isinstance(user_info_str, str) else user_info_str

        return ImportedAccount(
            uid=str(account_data.get("Uid", "")),
            screen_name=user_info.get("screen_name", account_data.get("AccountId", "")),
            name=user_info.get("name", ""),
            ct0=ct0,
            auth_token=auth_token,
            language=account_data.get("Language"),
            timezone=account_data.get("TimeZone"),
            country=account_data.get("Country"),
            followers_count=user_info.get("followers_count", 0),
            following_count=user_info.get("friends_count", 0),
            statuses_count=user_info.get("statuses_count", 0),
            is_protected=user_info.get("protected", False),
            is_suspended=user_info.get("suspended", False),
            is_blue_verified=user_info.get("blue_verified", False),
            profile_image_url=user_info.get("profile_image_url_https"),
        )

    except Exception as e:
        logger.error(
            "account_import.parse_error",
            uid=account_data.get("Uid"),
            error=str(e),
        )
        return None


def parse_android_accounts(accounts_json: str | list) -> list[ImportedAccount]:
    """Parse multiple accounts from Android app export format.

    Args:
        accounts_json: JSON string or list of account data.

    Returns:
        List of successfully parsed ImportedAccount objects.
    """
    if isinstance(accounts_json, str):
        accounts_data = json.loads(accounts_json)
    else:
        accounts_data = accounts_json

    if not isinstance(accounts_data, list):
        accounts_data = [accounts_data]

    imported = []
    for account_data in accounts_data:
        account = parse_android_account(account_data)
        if account:
            imported.append(account)
            logger.info(
                "account_import.parsed",
                uid=account.uid,
                screen_name=account.screen_name,
            )

    logger.info(
        "account_import.batch_complete",
        total=len(accounts_data),
        imported=len(imported),
        failed=len(accounts_data) - len(imported),
    )

    return imported


def to_db_format(account: ImportedAccount) -> dict[str, Any]:
    """Convert ImportedAccount to database insert format.

    Args:
        account: Parsed account data.

    Returns:
        Dictionary suitable for TwitterAccount model creation.
    """
    return {
        "twitter_user_id": account.uid,
        "screen_name": account.screen_name,
        "display_name": account.name,
        "ct0": account.ct0,
        "auth_token": account.auth_token,
        "followers_count": account.followers_count,
        "following_count": account.following_count,
        "tweet_count": account.statuses_count,
        "is_protected": account.is_protected,
        "profile_image_url": account.profile_image_url,
        "status": "ACTIVE",
    }


def format_for_display(accounts: list[ImportedAccount]) -> str:
    """Format accounts for display/verification.

    Args:
        accounts: List of parsed accounts.

    Returns:
        Formatted string for display.
    """
    lines = ["Parsed Accounts:", "=" * 60]

    for i, acc in enumerate(accounts, 1):
        lines.append(f"\n{i}. @{acc.screen_name} ({acc.name})")
        lines.append(f"   UID: {acc.uid}")
        lines.append(f"   Followers: {acc.followers_count:,} | Following: {acc.following_count:,}")
        lines.append(f"   Country: {acc.country} | Language: {acc.language}")
        lines.append(f"   Protected: {acc.is_protected} | Suspended: {acc.is_suspended}")
        lines.append(f"   ct0: {acc.ct0[:20]}...")
        lines.append(f"   auth_token: {acc.auth_token[:20]}...")

    lines.append("\n" + "=" * 60)
    lines.append(f"Total: {len(accounts)} accounts ready for import")

    return "\n".join(lines)
