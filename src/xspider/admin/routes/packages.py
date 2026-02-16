"""Credit Package Routes (积分套餐路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_current_admin, get_db_session
from xspider.admin.models import AdminUser
from xspider.admin.services import PackageService

router = APIRouter(prefix="/packages", tags=["Packages"])


# ==================== Public Routes ====================


@router.get("/")
async def get_packages(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get all available credit packages."""
    service = PackageService(db)
    packages = await service.get_packages(active_only=True)

    return {
        "packages": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "credits": p.credits,
                "bonus_credits": p.bonus_credits,
                "total_credits": p.credits + (p.bonus_credits or 0),
                "price": float(p.price),
                "currency": p.currency,
                "features": p.features,
                "is_popular": p.is_popular,
            }
            for p in packages
        ]
    }


@router.get("/{package_id}")
async def get_package(
    package_id: int,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get a specific package by ID."""
    service = PackageService(db)
    package = await service.get_package_by_id(package_id)

    if not package or not package.is_active:
        raise HTTPException(status_code=404, detail="Package not found")

    return {
        "id": package.id,
        "name": package.name,
        "description": package.description,
        "credits": package.credits,
        "bonus_credits": package.bonus_credits,
        "total_credits": package.credits + (package.bonus_credits or 0),
        "price": float(package.price),
        "currency": package.currency,
        "features": package.features,
        "is_popular": package.is_popular,
    }


# ==================== User Purchase Routes ====================


@router.post("/{package_id}/purchase")
async def purchase_package(
    package_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    payment_method: str = "manual",
    payment_id: str | None = None,
) -> dict[str, Any]:
    """Purchase a credit package."""
    service = PackageService(db)

    try:
        purchase = await service.purchase_package(
            user_id=current_user.id,
            package_id=package_id,
            payment_method=payment_method,
            payment_id=payment_id,
        )

        return {
            "success": True,
            "purchase": {
                "id": purchase.id,
                "package_name": purchase.package_name,
                "credits_purchased": purchase.credits_purchased,
                "bonus_credits": purchase.bonus_credits,
                "total_credits": purchase.credits_purchased + purchase.bonus_credits,
                "amount_paid": float(purchase.amount_paid),
                "currency": purchase.currency,
                "status": purchase.status,
                "created_at": purchase.created_at.isoformat() if purchase.created_at else None,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/purchases/history")
async def get_purchase_history(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Get purchase history for the current user."""
    service = PackageService(db)
    purchases, total = await service.get_user_purchases(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )

    return {
        "purchases": [
            {
                "id": p.id,
                "package_name": p.package_name,
                "credits_purchased": p.credits_purchased,
                "bonus_credits": p.bonus_credits,
                "amount_paid": float(p.amount_paid),
                "currency": p.currency,
                "payment_method": p.payment_method,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in purchases
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ==================== Admin Routes ====================


@router.post("/admin/create")
async def admin_create_package(
    name: str,
    description: str,
    credits: int,
    price: float,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    currency: str = "USD",
    bonus_credits: int = 0,
    features: list[str] | None = None,
    is_popular: bool = False,
    sort_order: int = 0,
) -> dict[str, Any]:
    """Create a new credit package (admin only)."""
    service = PackageService(db)

    package = await service.create_package(
        name=name,
        description=description,
        credits=credits,
        price=price,
        currency=currency,
        bonus_credits=bonus_credits,
        features=features,
        is_popular=is_popular,
        sort_order=sort_order,
    )

    return {
        "success": True,
        "package": {
            "id": package.id,
            "name": package.name,
            "credits": package.credits,
            "price": float(package.price),
        },
    }


@router.put("/admin/{package_id}")
async def admin_update_package(
    package_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    name: str | None = None,
    description: str | None = None,
    credits: int | None = None,
    price: float | None = None,
    bonus_credits: int | None = None,
    features: list[str] | None = None,
    is_popular: bool | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> dict[str, Any]:
    """Update a credit package (admin only)."""
    service = PackageService(db)

    updates = {}
    for key, value in [
        ("name", name),
        ("description", description),
        ("credits", credits),
        ("price", price),
        ("bonus_credits", bonus_credits),
        ("features", features),
        ("is_popular", is_popular),
        ("is_active", is_active),
        ("sort_order", sort_order),
    ]:
        if value is not None:
            updates[key] = value

    try:
        package = await service.update_package(package_id, **updates)
        return {
            "success": True,
            "package": {
                "id": package.id,
                "name": package.name,
                "credits": package.credits,
                "price": float(package.price),
                "is_active": package.is_active,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/admin/{package_id}")
async def admin_delete_package(
    package_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Deactivate a credit package (admin only)."""
    service = PackageService(db)
    deleted = await service.delete_package(package_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Package not found")

    return {"success": True}


@router.get("/admin/stats")
async def admin_get_purchase_stats(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get purchase statistics (admin only)."""
    service = PackageService(db)
    return await service.get_purchase_stats()


@router.post("/admin/seed")
async def admin_seed_packages(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Seed default credit packages (admin only)."""
    service = PackageService(db)
    count = await service.seed_default_packages()

    return {"success": True, "packages_created": count}
