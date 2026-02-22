"""Data Privacy and Retention Routes (数据隐私与保留路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_current_admin, get_db_session
from xspider.admin.models import AdminUser
from xspider.admin.services import PrivacyService

router = APIRouter(prefix="/privacy", tags=["Privacy"])


# ==================== Retention Policy ====================


@router.get("/retention")
async def get_retention_policy(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get current data retention policy."""
    service = PrivacyService(db)
    policy = await service.get_retention_policy(current_user.id)

    if not policy:
        # Return defaults
        return {
            "policy": None,
            "defaults": service.DEFAULT_RETENTION,
            "message": "No custom retention policy set. Using defaults.",
        }

    return {
        "policy": {
            "id": policy.id,
            "search_results_days": policy.search_results_days,
            "commenter_data_days": policy.commenter_data_days,
            "lead_data_days": policy.lead_data_days,
            "analytics_days": policy.analytics_days,
            "webhook_logs_days": policy.webhook_logs_days,
            "auto_delete_enabled": policy.auto_delete_enabled,
            "updated_at": policy.updated_at.isoformat() if policy.updated_at else None,
        },
        "defaults": service.DEFAULT_RETENTION,
    }


@router.put("/retention")
async def set_retention_policy(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    retention_days: int | None = None,  # Simple single value from UI
    search_results_days: int | None = None,
    commenter_data_days: int | None = None,
    lead_data_days: int | None = None,
    analytics_days: int | None = None,
    webhook_logs_days: int | None = None,
    auto_delete_enabled: bool = True,
) -> dict[str, Any]:
    """Set data retention policy."""
    service = PrivacyService(db)

    # If simple retention_days is provided, apply to all types
    if retention_days is not None:
        search_results_days = retention_days
        commenter_data_days = retention_days
        lead_data_days = retention_days
        analytics_days = retention_days
        webhook_logs_days = retention_days

    policy = await service.set_retention_policy(
        user_id=current_user.id,
        search_results_days=search_results_days,
        commenter_data_days=commenter_data_days,
        lead_data_days=lead_data_days,
        analytics_days=analytics_days,
        webhook_logs_days=webhook_logs_days,
        auto_delete_enabled=auto_delete_enabled,
    )

    return {
        "success": True,
        "policy": {
            "id": policy.id,
            "search_results_days": policy.search_results_days,
            "commenter_data_days": policy.commenter_data_days,
            "lead_data_days": policy.lead_data_days,
            "analytics_days": policy.analytics_days,
            "webhook_logs_days": policy.webhook_logs_days,
            "auto_delete_enabled": policy.auto_delete_enabled,
        },
    }


# ==================== Data Export (GDPR) ====================


@router.get("/export")
async def export_user_data(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    """
    Export all user data (GDPR right of access).

    Returns a JSON file containing all data associated with the user.
    """
    service = PrivacyService(db)
    data = await service.export_user_data(current_user.id)

    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f"attachment; filename=xspider_data_export_{current_user.id}.json"
        },
    )


# ==================== Data Deletion (GDPR) ====================


@router.post("/export")
async def export_user_data_post(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    format: str = "json",
) -> JSONResponse:
    """Export user data (POST version for UI compatibility)."""
    service = PrivacyService(db)
    data = await service.export_user_data(current_user.id)

    if format == "csv":
        # Return a message indicating CSV is not yet supported
        return JSONResponse(
            content={"message": "Data export initiated. Check your email."},
        )

    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f"attachment; filename=xspider_data_export_{current_user.id}.json"
        },
    )


@router.delete("/delete")
async def delete_user_data_simple(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Delete all user data (simplified endpoint for UI)."""
    service = PrivacyService(db)
    stats = await service.delete_user_data(
        user_id=current_user.id,
        keep_transactions=True,
    )

    return {
        "success": True,
        "message": "Your data has been deleted",
        "deleted_records": stats,
    }


@router.delete("/delete-my-data")
async def delete_user_data(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    confirm: bool = False,
    keep_transactions: bool = True,
) -> dict[str, Any]:
    """
    Delete all user data (GDPR right to be forgotten).

    Args:
        confirm: Must be True to proceed with deletion
        keep_transactions: Keep financial transaction records (default True for audit)

    Warning: This action is irreversible!
    """
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Must set confirm=true to delete data. This action is irreversible!",
        )

    service = PrivacyService(db)
    stats = await service.delete_user_data(
        user_id=current_user.id,
        keep_transactions=keep_transactions,
    )

    return {
        "success": True,
        "message": "Your data has been deleted",
        "deleted_records": stats,
    }


# ==================== Data Statistics ====================


@router.get("/stats")
async def get_data_stats(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get data storage statistics."""
    service = PrivacyService(db)
    return await service.get_data_stats(current_user.id)


# ==================== Admin: Cleanup ====================


@router.post("/admin/cleanup")
async def admin_cleanup_expired_data(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Clean up expired data based on retention policies (admin only).

    Args:
        user_id: Optional user ID to clean up. If not provided, cleans all users.
    """
    service = PrivacyService(db)
    stats = await service.cleanup_expired_data(user_id=user_id)

    return {"success": True, "cleaned_records": stats}


@router.delete("/admin/user/{user_id}")
async def admin_delete_user_data(
    user_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    keep_transactions: bool = True,
) -> dict[str, Any]:
    """Delete all data for a specific user (admin only)."""
    service = PrivacyService(db)
    stats = await service.delete_user_data(
        user_id=user_id,
        keep_transactions=keep_transactions,
    )

    return {"success": True, "deleted_records": stats}
