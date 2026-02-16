"""Webhook Integration Service (Webhook集成服务)."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    WebhookConfig,
    WebhookEventType,
    WebhookLog,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class WebhookService:
    """
    Service for managing and triggering webhooks.

    Supports:
    - Slack webhooks
    - Zapier webhooks
    - Custom HTTP endpoints
    """

    MAX_RETRIES = 3
    TIMEOUT_SECONDS = 10

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_webhook(
        self,
        user_id: int,
        name: str,
        url: str,
        event_types: list[WebhookEventType],
        secret: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebhookConfig:
        """Create a new webhook configuration."""
        # Generate secret if not provided
        if not secret:
            import secrets
            secret = secrets.token_urlsafe(32)

        webhook = WebhookConfig(
            user_id=user_id,
            name=name,
            url=url,
            secret=secret,
            event_types=json.dumps([e.value for e in event_types]),
            headers=json.dumps(headers or {}),
            is_active=True,
        )

        self.db.add(webhook)
        await self.db.commit()
        await self.db.refresh(webhook)

        logger.info(
            "Webhook created",
            webhook_id=webhook.id,
            name=name,
            event_types=[e.value for e in event_types],
        )

        return webhook

    async def update_webhook(
        self,
        webhook_id: int,
        user_id: int,
        **updates: Any,
    ) -> WebhookConfig:
        """Update a webhook configuration."""
        result = await self.db.execute(
            select(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.user_id == user_id,
            )
        )
        webhook = result.scalar_one_or_none()

        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")

        for key, value in updates.items():
            if key == "event_types" and isinstance(value, list):
                value = json.dumps([
                    e.value if isinstance(e, WebhookEventType) else e
                    for e in value
                ])
            elif key == "headers" and isinstance(value, dict):
                value = json.dumps(value)

            if hasattr(webhook, key):
                setattr(webhook, key, value)

        await self.db.commit()
        await self.db.refresh(webhook)

        return webhook

    async def delete_webhook(
        self,
        webhook_id: int,
        user_id: int,
    ) -> bool:
        """Delete a webhook configuration."""
        result = await self.db.execute(
            select(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.user_id == user_id,
            )
        )
        webhook = result.scalar_one_or_none()

        if not webhook:
            return False

        await self.db.delete(webhook)
        await self.db.commit()

        return True

    async def get_webhooks(
        self,
        user_id: int,
        active_only: bool = False,
    ) -> list[WebhookConfig]:
        """Get all webhooks for a user."""
        query = select(WebhookConfig).where(WebhookConfig.user_id == user_id)

        if active_only:
            query = query.where(WebhookConfig.is_active == True)  # noqa: E712

        result = await self.db.execute(query.order_by(WebhookConfig.created_at.desc()))
        return list(result.scalars().all())

    async def trigger_webhook(
        self,
        webhook: WebhookConfig,
        event_type: WebhookEventType,
        payload: dict[str, Any],
    ) -> WebhookLog:
        """Trigger a single webhook."""
        # Build request
        timestamp = datetime.now(timezone.utc).isoformat()
        full_payload = {
            "event_type": event_type.value,
            "timestamp": timestamp,
            "data": payload,
        }

        # Sign payload
        signature = self._sign_payload(full_payload, webhook.secret)

        # Build headers
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Event": event_type.value,
            "X-Webhook-Timestamp": timestamp,
        }

        # Add custom headers
        try:
            custom_headers = json.loads(webhook.headers or "{}")
            headers.update(custom_headers)
        except json.JSONDecodeError:
            pass

        # Send request
        response_status = 0
        response_body = ""
        success = False
        error_message = None

        async with httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
            for attempt in range(self.MAX_RETRIES):
                try:
                    response = await client.post(
                        webhook.url,
                        json=full_payload,
                        headers=headers,
                    )
                    response_status = response.status_code
                    response_body = response.text[:1000]  # Limit response body
                    success = 200 <= response_status < 300

                    if success:
                        break

                except httpx.TimeoutException:
                    error_message = "Request timeout"
                except httpx.RequestError as e:
                    error_message = str(e)
                except Exception as e:
                    error_message = f"Unexpected error: {str(e)}"

                if attempt < self.MAX_RETRIES - 1:
                    # Wait before retry (exponential backoff)
                    import asyncio
                    await asyncio.sleep(2 ** attempt)

        # Log the attempt
        log = WebhookLog(
            webhook_id=webhook.id,
            event_type=event_type,
            payload=json.dumps(payload),
            response_status=response_status,
            response_body=response_body,
            success=success,
            error_message=error_message,
        )

        self.db.add(log)

        # Update webhook stats
        webhook.last_triggered_at = datetime.now(timezone.utc)
        if success:
            webhook.success_count = (webhook.success_count or 0) + 1
        else:
            webhook.failure_count = (webhook.failure_count or 0) + 1

        await self.db.commit()
        await self.db.refresh(log)

        if success:
            logger.info(
                "Webhook triggered successfully",
                webhook_id=webhook.id,
                event_type=event_type.value,
            )
        else:
            logger.warning(
                "Webhook trigger failed",
                webhook_id=webhook.id,
                event_type=event_type.value,
                error=error_message,
            )

        return log

    async def trigger_event(
        self,
        user_id: int,
        event_type: WebhookEventType,
        payload: dict[str, Any],
    ) -> list[WebhookLog]:
        """Trigger all webhooks subscribed to an event type."""
        # Find all active webhooks for this event type
        result = await self.db.execute(
            select(WebhookConfig).where(
                WebhookConfig.user_id == user_id,
                WebhookConfig.is_active == True,  # noqa: E712
            )
        )
        webhooks = list(result.scalars().all())

        logs = []
        for webhook in webhooks:
            # Check if webhook is subscribed to this event
            try:
                event_types = json.loads(webhook.event_types or "[]")
                if event_type.value in event_types:
                    log = await self.trigger_webhook(webhook, event_type, payload)
                    logs.append(log)
            except json.JSONDecodeError:
                continue

        return logs

    def _sign_payload(
        self,
        payload: dict[str, Any],
        secret: str,
    ) -> str:
        """Generate HMAC-SHA256 signature for payload."""
        message = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        signature = hmac.new(
            secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"sha256={signature}"

    async def test_webhook(
        self,
        webhook_id: int,
        user_id: int,
    ) -> WebhookLog:
        """Send a test event to a webhook."""
        result = await self.db.execute(
            select(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.user_id == user_id,
            )
        )
        webhook = result.scalar_one_or_none()

        if not webhook:
            raise ValueError(f"Webhook {webhook_id} not found")

        test_payload = {
            "test": True,
            "message": "This is a test webhook from xspider",
            "webhook_name": webhook.name,
        }

        # Use a generic event type for testing
        return await self.trigger_webhook(
            webhook,
            WebhookEventType.HIGH_INTENT_LEAD,
            test_payload,
        )

    async def get_webhook_logs(
        self,
        webhook_id: int,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[WebhookLog], int]:
        """Get logs for a specific webhook."""
        # Verify ownership
        webhook_result = await self.db.execute(
            select(WebhookConfig).where(
                WebhookConfig.id == webhook_id,
                WebhookConfig.user_id == user_id,
            )
        )
        if not webhook_result.scalar_one_or_none():
            raise ValueError(f"Webhook {webhook_id} not found")

        # Count
        count_result = await self.db.execute(
            select(func.count(WebhookLog.id)).where(
                WebhookLog.webhook_id == webhook_id
            )
        )
        total = count_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(WebhookLog)
            .where(WebhookLog.webhook_id == webhook_id)
            .order_by(WebhookLog.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        logs = list(result.scalars().all())

        return logs, total

    async def get_webhook_stats(self, user_id: int) -> dict[str, Any]:
        """Get webhook statistics for a user."""
        result = await self.db.execute(
            select(WebhookConfig).where(WebhookConfig.user_id == user_id)
        )
        webhooks = list(result.scalars().all())

        total_success = sum(w.success_count or 0 for w in webhooks)
        total_failure = sum(w.failure_count or 0 for w in webhooks)
        total_triggers = total_success + total_failure

        return {
            "total_webhooks": len(webhooks),
            "active_webhooks": sum(1 for w in webhooks if w.is_active),
            "total_triggers": total_triggers,
            "total_success": total_success,
            "total_failure": total_failure,
            "success_rate": (
                total_success / total_triggers * 100 if total_triggers > 0 else 0
            ),
        }


# Event trigger helper functions
async def notify_high_intent_lead(
    db: AsyncSession,
    user_id: int,
    lead_data: dict[str, Any],
) -> None:
    """Notify about a new high-intent lead."""
    service = WebhookService(db)
    await service.trigger_event(
        user_id=user_id,
        event_type=WebhookEventType.HIGH_INTENT_LEAD,
        payload={
            "lead_screen_name": lead_data.get("screen_name"),
            "lead_display_name": lead_data.get("display_name"),
            "intent_label": lead_data.get("intent_label"),
            "intent_score": lead_data.get("intent_score"),
            "dm_available": lead_data.get("dm_available", False),
            "source_influencer": lead_data.get("source_influencer"),
        },
    )


async def notify_suspicious_growth(
    db: AsyncSession,
    user_id: int,
    influencer_data: dict[str, Any],
) -> None:
    """Notify about suspicious follower growth."""
    service = WebhookService(db)
    await service.trigger_event(
        user_id=user_id,
        event_type=WebhookEventType.SUSPICIOUS_GROWTH,
        payload={
            "influencer_screen_name": influencer_data.get("screen_name"),
            "followers_change": influencer_data.get("followers_change"),
            "followers_change_pct": influencer_data.get("followers_change_pct"),
            "anomaly_type": influencer_data.get("anomaly_type"),
            "anomaly_score": influencer_data.get("anomaly_score"),
        },
    )


async def notify_dm_available(
    db: AsyncSession,
    user_id: int,
    user_data: dict[str, Any],
) -> None:
    """Notify when a user's DM becomes available."""
    service = WebhookService(db)
    await service.trigger_event(
        user_id=user_id,
        event_type=WebhookEventType.DM_AVAILABLE,
        payload={
            "screen_name": user_data.get("screen_name"),
            "display_name": user_data.get("display_name"),
            "followers_count": user_data.get("followers_count"),
            "intent_label": user_data.get("intent_label"),
        },
    )
