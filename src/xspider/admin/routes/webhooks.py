"""Webhook Integration Routes (Webhook集成路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, WebhookEventType
from xspider.admin.services import WebhookService

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/")
async def create_webhook(
    name: str,
    url: str,
    event_types: list[str],
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    secret: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a new webhook configuration."""
    try:
        event_type_enums = [WebhookEventType(e) for e in event_types]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid event type: {e}")

    service = WebhookService(db)
    webhook = await service.create_webhook(
        user_id=current_user.id,
        name=name,
        url=url,
        event_types=event_type_enums,
        secret=secret,
        headers=headers,
    )

    return {
        "success": True,
        "webhook": {
            "id": webhook.id,
            "name": webhook.name,
            "url": webhook.url,
            "event_types": webhook.event_types,
            "is_active": webhook.is_active,
            "secret": webhook.secret,  # Show once on creation
        },
    }


@router.get("/")
async def get_webhooks(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    active_only: bool = False,
) -> dict[str, Any]:
    """Get all webhooks for the current user."""
    service = WebhookService(db)
    webhooks = await service.get_webhooks(
        user_id=current_user.id,
        active_only=active_only,
    )

    return {
        "webhooks": [
            {
                "id": w.id,
                "name": w.name,
                "url": w.url,
                "event_types": w.event_types,
                "is_active": w.is_active,
                "last_triggered_at": w.last_triggered_at.isoformat() if w.last_triggered_at else None,
                "success_count": w.success_count,
                "failure_count": w.failure_count,
                "created_at": w.created_at.isoformat() if w.created_at else None,
            }
            for w in webhooks
        ]
    }


@router.put("/{webhook_id}")
async def update_webhook(
    webhook_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    name: str | None = None,
    url: str | None = None,
    event_types: list[str] | None = None,
    is_active: bool | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Update a webhook configuration."""
    service = WebhookService(db)

    updates = {}
    if name is not None:
        updates["name"] = name
    if url is not None:
        updates["url"] = url
    if event_types is not None:
        try:
            updates["event_types"] = [WebhookEventType(e) for e in event_types]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid event type: {e}")
    if is_active is not None:
        updates["is_active"] = is_active
    if headers is not None:
        updates["headers"] = headers

    try:
        webhook = await service.update_webhook(
            webhook_id=webhook_id,
            user_id=current_user.id,
            **updates,
        )
        return {
            "success": True,
            "webhook": {
                "id": webhook.id,
                "name": webhook.name,
                "url": webhook.url,
                "event_types": webhook.event_types,
                "is_active": webhook.is_active,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Delete a webhook configuration."""
    service = WebhookService(db)
    deleted = await service.delete_webhook(webhook_id, current_user.id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")

    return {"success": True}


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Send a test event to a webhook."""
    service = WebhookService(db)

    try:
        log = await service.test_webhook(webhook_id, current_user.id)
        return {
            "success": log.success,
            "response_status": log.response_status,
            "response_body": log.response_body,
            "error_message": log.error_message,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{webhook_id}/logs")
async def get_webhook_logs(
    webhook_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Get logs for a specific webhook."""
    service = WebhookService(db)

    try:
        logs, total = await service.get_webhook_logs(
            webhook_id=webhook_id,
            user_id=current_user.id,
            page=page,
            page_size=page_size,
        )

        return {
            "logs": [
                {
                    "id": log.id,
                    "event_type": log.event_type.value if log.event_type else None,
                    "success": log.success,
                    "response_status": log.response_status,
                    "error_message": log.error_message,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in logs
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/stats")
async def get_webhook_stats(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get webhook statistics."""
    service = WebhookService(db)
    return await service.get_webhook_stats(current_user.id)


@router.get("/event-types")
async def get_event_types() -> dict[str, Any]:
    """Get available webhook event types."""
    return {
        "event_types": [
            {
                "value": e.value,
                "description": {
                    WebhookEventType.HIGH_INTENT_LEAD: "Triggered when a high-intent lead is discovered",
                    WebhookEventType.HIGH_ENGAGEMENT_COMMENT: "Triggered for high-engagement comments",
                    WebhookEventType.NEW_REAL_USER: "Triggered when a real user is identified",
                    WebhookEventType.SUSPICIOUS_GROWTH: "Triggered for suspicious follower growth",
                    WebhookEventType.DM_AVAILABLE: "Triggered when a user's DM becomes available",
                }.get(e, ""),
            }
            for e in WebhookEventType
        ]
    }
