"""Credit management routes for users."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, CreditTransaction, LLMUsage
from xspider.admin.schemas import (
    CreditHistoryResponse,
    CreditTransactionResponse,
    LLMUsageResponse,
)

router = APIRouter()


@router.get("/balance")
async def get_credit_balance(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
) -> dict[str, int]:
    """Get current credit balance."""
    return {"balance": current_user.credits}


@router.get("/history", response_model=CreditHistoryResponse)
async def get_credit_history(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> CreditHistoryResponse:
    """Get credit transaction history for current user."""
    # Count total transactions
    count_result = await db.execute(
        select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_id == current_user.id
        )
    )
    total = count_result.scalar() or 0

    # Get paginated transactions
    offset = (page - 1) * page_size
    tx_result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    transactions = list(tx_result.scalars().all())

    return CreditHistoryResponse(
        transactions=[CreditTransactionResponse.model_validate(t) for t in transactions],
        current_balance=current_user.credits,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/llm-usage", response_model=list[LLMUsageResponse])
async def get_llm_usage(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> list[LLMUsage]:
    """Get LLM usage history for current user."""
    result = await db.execute(
        select(LLMUsage)
        .where(LLMUsage.user_id == current_user.id)
        .order_by(LLMUsage.created_at.desc())
        .limit(limit)
    )

    return list(result.scalars().all())


@router.get("/summary")
async def get_credit_summary(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get credit usage summary for current user."""
    from xspider.admin.models import TransactionType

    # Total recharged
    recharge_result = await db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.user_id == current_user.id,
            CreditTransaction.type == TransactionType.RECHARGE,
        )
    )
    total_recharged = recharge_result.scalar() or 0

    # Total spent on searches
    search_result = await db.execute(
        select(func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0)).where(
            CreditTransaction.user_id == current_user.id,
            CreditTransaction.type == TransactionType.SEARCH,
        )
    )
    total_search_spent = search_result.scalar() or 0

    # Total spent on LLM
    llm_result = await db.execute(
        select(func.coalesce(func.sum(func.abs(CreditTransaction.amount)), 0)).where(
            CreditTransaction.user_id == current_user.id,
            CreditTransaction.type == TransactionType.LLM_CALL,
        )
    )
    total_llm_spent = llm_result.scalar() or 0

    # Total refunds
    refund_result = await db.execute(
        select(func.coalesce(func.sum(CreditTransaction.amount), 0)).where(
            CreditTransaction.user_id == current_user.id,
            CreditTransaction.type == TransactionType.REFUND,
        )
    )
    total_refunds = refund_result.scalar() or 0

    # LLM token usage
    tokens_result = await db.execute(
        select(
            func.coalesce(func.sum(LLMUsage.tokens_input), 0).label("input"),
            func.coalesce(func.sum(LLMUsage.tokens_output), 0).label("output"),
        ).where(LLMUsage.user_id == current_user.id)
    )
    tokens = tokens_result.one()

    return {
        "current_balance": current_user.credits,
        "total_recharged": total_recharged,
        "total_spent": {
            "search": total_search_spent,
            "llm": total_llm_spent,
            "total": total_search_spent + total_llm_spent,
        },
        "total_refunds": total_refunds,
        "llm_tokens": {
            "input": tokens.input,
            "output": tokens.output,
            "total": tokens.input + tokens.output,
        },
    }
