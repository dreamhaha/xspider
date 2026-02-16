"""Credit management service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    AdminUser,
    CreditTransaction,
    LLMProvider,
    LLMUsage,
    TransactionType,
    UserSearch,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


# Credit cost constants
COST_SEARCH_SEED = 10
COST_CRAWL_PER_100 = 5
COST_AI_AUDIT_PER_USER = 2
COST_LLM_PER_1K_TOKENS = 1


class CreditService:
    """Service for managing user credits."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_balance(self, user_id: int) -> int:
        """Get user's current credit balance."""
        result = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = result.scalar_one_or_none()
        return user.credits if user else 0

    async def has_sufficient_credits(self, user_id: int, amount: int) -> bool:
        """Check if user has sufficient credits."""
        balance = await self.get_balance(user_id)
        return balance >= amount

    async def deduct_credits(
        self,
        user_id: int,
        amount: int,
        transaction_type: TransactionType,
        description: str,
        search_id: int | None = None,
    ) -> CreditTransaction | None:
        """Deduct credits from user account."""
        result = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.error("User not found for credit deduction", user_id=user_id)
            return None

        if user.credits < amount:
            logger.warning(
                "Insufficient credits",
                user_id=user_id,
                balance=user.credits,
                required=amount,
            )
            return None

        user.credits -= amount
        new_balance = user.credits

        transaction = CreditTransaction(
            user_id=user_id,
            amount=-amount,  # Negative for deductions
            balance_after=new_balance,
            type=transaction_type,
            description=description,
            search_id=search_id,
        )
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)

        logger.info(
            "Credits deducted",
            user_id=user_id,
            amount=amount,
            new_balance=new_balance,
            type=transaction_type.value,
        )

        return transaction

    async def add_credits(
        self,
        user_id: int,
        amount: int,
        description: str,
        admin_id: int | None = None,
    ) -> CreditTransaction | None:
        """Add credits to user account (recharge)."""
        result = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.error("User not found for credit recharge", user_id=user_id)
            return None

        user.credits += amount
        new_balance = user.credits

        transaction = CreditTransaction(
            user_id=user_id,
            amount=amount,  # Positive for additions
            balance_after=new_balance,
            type=TransactionType.RECHARGE,
            description=description,
            created_by=admin_id,
        )
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)

        logger.info(
            "Credits added",
            user_id=user_id,
            amount=amount,
            new_balance=new_balance,
            admin_id=admin_id,
        )

        return transaction

    async def refund_credits(
        self,
        user_id: int,
        amount: int,
        description: str,
        search_id: int | None = None,
    ) -> CreditTransaction | None:
        """Refund credits to user account."""
        result = await self.db.execute(
            select(AdminUser).where(AdminUser.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            logger.error("User not found for credit refund", user_id=user_id)
            return None

        user.credits += amount
        new_balance = user.credits

        transaction = CreditTransaction(
            user_id=user_id,
            amount=amount,  # Positive for refunds
            balance_after=new_balance,
            type=TransactionType.REFUND,
            description=description,
            search_id=search_id,
        )
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)

        logger.info(
            "Credits refunded",
            user_id=user_id,
            amount=amount,
            new_balance=new_balance,
        )

        return transaction

    async def record_llm_usage(
        self,
        user_id: int,
        provider: LLMProvider,
        model: str,
        tokens_input: int,
        tokens_output: int,
        search_id: int | None = None,
    ) -> LLMUsage:
        """Record LLM API usage and deduct credits."""
        total_tokens = tokens_input + tokens_output
        credits_used = max(1, total_tokens // 1000) * COST_LLM_PER_1K_TOKENS

        # Deduct credits
        await self.deduct_credits(
            user_id=user_id,
            amount=credits_used,
            transaction_type=TransactionType.LLM_CALL,
            description=f"LLM call: {provider.value}/{model} ({total_tokens} tokens)",
            search_id=search_id,
        )

        # Record usage
        usage = LLMUsage(
            user_id=user_id,
            search_id=search_id,
            provider=provider,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            credits_used=credits_used,
        )
        self.db.add(usage)
        await self.db.commit()
        await self.db.refresh(usage)

        return usage

    async def charge_for_search_start(
        self,
        user_id: int,
        search_id: int,
        keywords: str,
    ) -> CreditTransaction | None:
        """Charge initial credits for starting a search."""
        return await self.deduct_credits(
            user_id=user_id,
            amount=COST_SEARCH_SEED,
            transaction_type=TransactionType.SEARCH,
            description=f"Search started: {keywords[:50]}",
            search_id=search_id,
        )

    async def charge_for_crawling(
        self,
        user_id: int,
        search_id: int,
        users_crawled: int,
    ) -> CreditTransaction | None:
        """Charge credits for crawling users."""
        # Charge per 100 users crawled
        batches = (users_crawled + 99) // 100
        amount = batches * COST_CRAWL_PER_100

        if amount <= 0:
            return None

        return await self.deduct_credits(
            user_id=user_id,
            amount=amount,
            transaction_type=TransactionType.SEARCH,
            description=f"Crawled {users_crawled} users",
            search_id=search_id,
        )

    async def charge_for_ai_audit(
        self,
        user_id: int,
        search_id: int,
        users_audited: int,
    ) -> CreditTransaction | None:
        """Charge credits for AI auditing users."""
        amount = users_audited * COST_AI_AUDIT_PER_USER

        if amount <= 0:
            return None

        return await self.deduct_credits(
            user_id=user_id,
            amount=amount,
            transaction_type=TransactionType.SEARCH,
            description=f"AI audited {users_audited} users",
            search_id=search_id,
        )

    @staticmethod
    def estimate_search_cost(
        estimated_seeds: int = 50,
        estimated_crawl_users: int = 500,
        estimated_audits: int = 100,
    ) -> dict[str, int]:
        """Estimate total cost for a search operation."""
        seed_cost = COST_SEARCH_SEED
        crawl_cost = ((estimated_crawl_users + 99) // 100) * COST_CRAWL_PER_100
        audit_cost = estimated_audits * COST_AI_AUDIT_PER_USER

        return {
            "seed_search": seed_cost,
            "crawling": crawl_cost,
            "ai_audit": audit_cost,
            "total": seed_cost + crawl_cost + audit_cost,
        }
