"""Credit Package Service (积分套餐服务)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AdminUser,
    CreditPackage,
    CreditTransaction,
    PackagePurchase,
    TransactionType,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class PackageService:
    """
    Service for managing credit packages and purchases.

    Handles:
    - Package CRUD (admin)
    - Package purchases (users)
    - Credit bonuses
    - Feature access control
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ==================== Package Management (Admin) ====================

    async def create_package(
        self,
        name: str,
        description: str,
        credits: int,
        price: float,
        currency: str = "USD",
        bonus_credits: int = 0,
        features: list[str] | None = None,
        is_popular: bool = False,
        sort_order: int = 0,
    ) -> CreditPackage:
        """Create a new credit package."""
        package = CreditPackage(
            name=name,
            description=description,
            credits=credits,
            bonus_credits=bonus_credits,
            price=price,
            currency=currency,
            features=json.dumps(features or []),
            is_popular=is_popular,
            is_active=True,
            sort_order=sort_order,
        )

        self.db.add(package)
        await self.db.commit()
        await self.db.refresh(package)

        logger.info(
            "Credit package created",
            package_id=package.id,
            name=name,
            credits=credits,
            price=price,
        )

        return package

    async def update_package(
        self,
        package_id: int,
        **updates: Any,
    ) -> CreditPackage:
        """Update a credit package."""
        result = await self.db.execute(
            select(CreditPackage).where(CreditPackage.id == package_id)
        )
        package = result.scalar_one_or_none()

        if not package:
            raise ValueError(f"Package {package_id} not found")

        for key, value in updates.items():
            if key == "features" and isinstance(value, list):
                value = json.dumps(value)
            if hasattr(package, key):
                setattr(package, key, value)

        await self.db.commit()
        await self.db.refresh(package)

        return package

    async def delete_package(self, package_id: int) -> bool:
        """Soft delete a package by deactivating it."""
        result = await self.db.execute(
            select(CreditPackage).where(CreditPackage.id == package_id)
        )
        package = result.scalar_one_or_none()

        if not package:
            return False

        package.is_active = False
        await self.db.commit()

        return True

    async def get_packages(
        self,
        active_only: bool = True,
    ) -> list[CreditPackage]:
        """Get all available packages."""
        query = select(CreditPackage)

        if active_only:
            query = query.where(CreditPackage.is_active == True)  # noqa: E712

        query = query.order_by(CreditPackage.sort_order, CreditPackage.price)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_package_by_id(self, package_id: int) -> CreditPackage | None:
        """Get a package by ID."""
        result = await self.db.execute(
            select(CreditPackage).where(CreditPackage.id == package_id)
        )
        return result.scalar_one_or_none()

    # ==================== Package Purchase ====================

    async def purchase_package(
        self,
        user_id: int,
        package_id: int,
        payment_method: str = "manual",
        payment_id: str | None = None,
    ) -> PackagePurchase:
        """
        Process a package purchase.

        Args:
            user_id: The user making the purchase
            package_id: The package being purchased
            payment_method: Payment method used (stripe, paypal, manual, etc.)
            payment_id: External payment reference ID

        Returns:
            PackagePurchase record
        """
        # Get package
        package = await self.get_package_by_id(package_id)
        if not package or not package.is_active:
            raise ValueError(f"Package {package_id} not found or inactive")

        # Get user
        user_result = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            raise ValueError(f"User {user_id} not found")

        # Calculate total credits
        total_credits = package.credits + (package.bonus_credits or 0)
        old_balance = user.credits

        # Create purchase record
        purchase = PackagePurchase(
            user_id=user_id,
            package_id=package_id,
            package_name=package.name,
            credits_purchased=package.credits,
            bonus_credits=package.bonus_credits or 0,
            amount_paid=package.price,
            currency=package.currency,
            payment_method=payment_method,
            payment_id=payment_id,
            status="completed",
        )

        self.db.add(purchase)

        # Add credits to user
        user.credits = old_balance + total_credits

        # Create credit transaction
        transaction = CreditTransaction(
            user_id=user_id,
            amount=total_credits,
            balance_after=user.credits,
            type=TransactionType.PACKAGE_PURCHASE,
            description=f"Purchased {package.name} (+{package.credits} credits"
            + (f" +{package.bonus_credits} bonus)" if package.bonus_credits else ")"),
        )

        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(purchase)

        logger.info(
            "Package purchased",
            purchase_id=purchase.id,
            user_id=user_id,
            package=package.name,
            credits=total_credits,
            amount=package.price,
        )

        return purchase

    async def get_user_purchases(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PackagePurchase], int]:
        """Get purchase history for a user."""
        # Count
        count_result = await self.db.execute(
            select(func.count(PackagePurchase.id)).where(
                PackagePurchase.user_id == user_id
            )
        )
        total = count_result.scalar() or 0

        # Paginate
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(PackagePurchase)
            .where(PackagePurchase.user_id == user_id)
            .order_by(PackagePurchase.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        purchases = list(result.scalars().all())

        return purchases, total

    async def get_purchase_stats(self) -> dict[str, Any]:
        """Get overall purchase statistics (admin)."""
        # Total revenue
        revenue_result = await self.db.execute(
            select(func.sum(PackagePurchase.amount_paid)).where(
                PackagePurchase.status == "completed"
            )
        )
        total_revenue = revenue_result.scalar() or 0

        # Total purchases
        count_result = await self.db.execute(
            select(func.count(PackagePurchase.id)).where(
                PackagePurchase.status == "completed"
            )
        )
        total_purchases = count_result.scalar() or 0

        # Credits sold
        credits_result = await self.db.execute(
            select(
                func.sum(PackagePurchase.credits_purchased),
                func.sum(PackagePurchase.bonus_credits),
            ).where(PackagePurchase.status == "completed")
        )
        row = credits_result.one_or_none()
        credits_sold = (row[0] or 0) if row else 0
        bonus_given = (row[1] or 0) if row else 0

        # Popular packages
        popular_result = await self.db.execute(
            select(
                PackagePurchase.package_name,
                func.count(PackagePurchase.id).label("count"),
            )
            .where(PackagePurchase.status == "completed")
            .group_by(PackagePurchase.package_name)
            .order_by(func.count(PackagePurchase.id).desc())
            .limit(5)
        )
        popular_packages = [
            {"name": row[0], "count": row[1]}
            for row in popular_result.all()
        ]

        return {
            "total_revenue": float(total_revenue),
            "total_purchases": total_purchases,
            "credits_sold": int(credits_sold),
            "bonus_given": int(bonus_given),
            "average_order": (
                float(total_revenue) / total_purchases if total_purchases > 0 else 0
            ),
            "popular_packages": popular_packages,
        }

    # ==================== Seed Data ====================

    async def seed_default_packages(self) -> int:
        """Create default credit packages if none exist."""
        existing = await self.db.execute(select(func.count(CreditPackage.id)))
        if existing.scalar() > 0:
            return 0

        default_packages = [
            {
                "name": "Starter",
                "description": "Perfect for trying out xspider",
                "credits": 100,
                "bonus_credits": 0,
                "price": 9.99,
                "features": ["Basic search", "100 credits"],
                "sort_order": 1,
            },
            {
                "name": "Growth",
                "description": "For growing businesses",
                "credits": 500,
                "bonus_credits": 50,
                "price": 39.99,
                "features": [
                    "All search features",
                    "500 + 50 bonus credits",
                    "Intent analysis",
                ],
                "is_popular": True,
                "sort_order": 2,
            },
            {
                "name": "Pro",
                "description": "For power users",
                "credits": 1500,
                "bonus_credits": 200,
                "price": 99.99,
                "features": [
                    "All features",
                    "1500 + 200 bonus credits",
                    "AI openers",
                    "Audience overlap",
                    "Priority support",
                ],
                "sort_order": 3,
            },
            {
                "name": "Enterprise",
                "description": "For large teams",
                "credits": 5000,
                "bonus_credits": 1000,
                "price": 299.99,
                "features": [
                    "Unlimited features",
                    "5000 + 1000 bonus credits",
                    "Webhook integrations",
                    "Dedicated support",
                    "Custom retention",
                ],
                "sort_order": 4,
            },
        ]

        for pkg_data in default_packages:
            await self.create_package(**pkg_data)

        logger.info("Seeded default credit packages", count=len(default_packages))
        return len(default_packages)
