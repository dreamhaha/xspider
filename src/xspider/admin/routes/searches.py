"""Search task routes for users."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_current_admin, get_db_session
from xspider.admin.models import (
    AdminUser,
    CreditTransaction,
    DiscoveredInfluencer,
    SearchStatus,
    TransactionType,
    UserSearch,
)
from xspider.admin.schemas import (
    InfluencerResponse,
    SearchCreate,
    SearchDetailResponse,
    SearchEstimate,
    SearchResponse,
)

router = APIRouter()

# Credit costs
CREDIT_COST_SEARCH_SEED = 10
CREDIT_COST_CRAWL_PER_100 = 5
CREDIT_COST_AI_AUDIT = 2
CREDIT_COST_LLM_PER_1K = 1


@router.get("/", response_model=list[SearchResponse])
async def list_searches(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    status_filter: SearchStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> list[UserSearch]:
    """List user's search tasks."""
    query = select(UserSearch).where(UserSearch.user_id == current_user.id)

    if status_filter:
        query = query.where(UserSearch.status == status_filter)

    query = query.order_by(UserSearch.created_at.desc())

    # Pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/all", response_model=list[SearchResponse])
async def list_all_searches(
    current_user: Annotated[AdminUser, Depends(get_current_admin)],
    status_filter: SearchStatus | None = None,
    user_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
) -> list[UserSearch]:
    """List all search tasks (admin only)."""
    query = select(UserSearch)

    if status_filter:
        query = query.where(UserSearch.status == status_filter)
    if user_id:
        query = query.where(UserSearch.user_id == user_id)

    query = query.order_by(UserSearch.created_at.desc())

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{search_id}", response_model=SearchDetailResponse)
async def get_search(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Get search task details with discovered influencers."""
    result = await db.execute(
        select(UserSearch).where(UserSearch.id == search_id)
    )
    search = result.scalar_one_or_none()

    if not search:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search not found",
        )

    # Check access
    if search.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Get influencers
    inf_result = await db.execute(
        select(DiscoveredInfluencer)
        .where(DiscoveredInfluencer.search_id == search_id)
        .order_by(DiscoveredInfluencer.pagerank_score.desc())
    )
    influencers = list(inf_result.scalars().all())

    return {
        **SearchResponse.model_validate(search).model_dump(),
        "influencers": [InfluencerResponse.model_validate(i) for i in influencers],
    }


@router.post("/estimate", response_model=SearchEstimate)
async def estimate_search_cost(
    request: SearchCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
) -> SearchEstimate:
    """Estimate credit cost for a search."""
    # Rough estimates based on typical search
    estimated_seeds = 50  # Typical seed count
    estimated_crawl_users = 500  # Typical crawl depth
    estimated_audits = 100  # Top users to audit

    breakdown = {
        "seed_search": CREDIT_COST_SEARCH_SEED,
        "crawling": (estimated_crawl_users // 100) * CREDIT_COST_CRAWL_PER_100,
        "ai_audit": estimated_audits * CREDIT_COST_AI_AUDIT,
    }

    return SearchEstimate(
        estimated_credits=sum(breakdown.values()),
        breakdown=breakdown,
    )


@router.post("/", response_model=SearchResponse, status_code=status.HTTP_201_CREATED)
async def create_search(
    request: SearchCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserSearch:
    """Create a new search task."""
    # Check minimum credits
    if current_user.credits < CREDIT_COST_SEARCH_SEED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient credits. Need at least {CREDIT_COST_SEARCH_SEED} credits to start a search.",
        )

    # Create search record
    search = UserSearch(
        user_id=current_user.id,
        keywords=request.keywords,
        industry=request.industry,
        status=SearchStatus.PENDING,
    )
    db.add(search)
    await db.commit()
    await db.refresh(search)

    return search


@router.post("/{search_id}/start", response_model=SearchResponse)
async def start_search(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserSearch:
    """Start a pending search task."""
    result = await db.execute(
        select(UserSearch).where(UserSearch.id == search_id)
    )
    search = result.scalar_one_or_none()

    if not search:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search not found",
        )

    if search.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if search.status != SearchStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Search is already {search.status.value}",
        )

    # Deduct initial credits
    if current_user.credits < CREDIT_COST_SEARCH_SEED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Insufficient credits",
        )

    current_user.credits -= CREDIT_COST_SEARCH_SEED
    search.credits_used = CREDIT_COST_SEARCH_SEED

    # Create transaction
    transaction = CreditTransaction(
        user_id=current_user.id,
        amount=-CREDIT_COST_SEARCH_SEED,
        balance_after=current_user.credits,
        type=TransactionType.SEARCH,
        description=f"Search: {search.keywords[:50]}",
        search_id=search.id,
    )
    db.add(transaction)

    # Update status
    search.status = SearchStatus.RUNNING

    await db.commit()
    await db.refresh(search)

    # TODO: Trigger actual search task in background

    return search


@router.post("/{search_id}/cancel", response_model=SearchResponse)
async def cancel_search(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserSearch:
    """Cancel a running search task."""
    result = await db.execute(
        select(UserSearch).where(UserSearch.id == search_id)
    )
    search = result.scalar_one_or_none()

    if not search:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search not found",
        )

    if search.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if search.status not in [SearchStatus.PENDING, SearchStatus.RUNNING]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel search with status: {search.status.value}",
        )

    search.status = SearchStatus.FAILED
    search.error_message = "Cancelled by user"
    search.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(search)

    return search


@router.get("/{search_id}/export")
async def export_search_results(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
    format: str = Query("csv", pattern="^(csv|json)$"),
    include_irrelevant: bool = False,
) -> StreamingResponse:
    """Export search results as CSV or JSON."""
    import csv
    import io
    import json

    result = await db.execute(
        select(UserSearch).where(UserSearch.id == search_id)
    )
    search = result.scalar_one_or_none()

    if not search:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search not found",
        )

    if search.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Get influencers
    query = select(DiscoveredInfluencer).where(
        DiscoveredInfluencer.search_id == search_id
    )
    if not include_irrelevant:
        query = query.where(DiscoveredInfluencer.is_relevant == True)  # noqa: E712

    query = query.order_by(DiscoveredInfluencer.pagerank_score.desc())

    inf_result = await db.execute(query)
    influencers = list(inf_result.scalars().all())

    if format == "json":
        data = [
            {
                "twitter_user_id": inf.twitter_user_id,
                "screen_name": inf.screen_name,
                "name": inf.name,
                "followers_count": inf.followers_count,
                "pagerank_score": inf.pagerank_score,
                "hidden_score": inf.hidden_score,
                "is_relevant": inf.is_relevant,
                "relevance_score": inf.relevance_score,
            }
            for inf in influencers
        ]
        content = json.dumps(data, indent=2)
        media_type = "application/json"
        filename = f"search_{search_id}_results.json"
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "twitter_user_id",
            "screen_name",
            "name",
            "followers_count",
            "pagerank_score",
            "hidden_score",
            "is_relevant",
            "relevance_score",
        ])
        for inf in influencers:
            writer.writerow([
                inf.twitter_user_id,
                inf.screen_name,
                inf.name,
                inf.followers_count,
                inf.pagerank_score,
                inf.hidden_score,
                inf.is_relevant,
                inf.relevance_score,
            ])
        content = output.getvalue()
        media_type = "text/csv"
        filename = f"search_{search_id}_results.csv"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """Delete a search and its results."""
    result = await db.execute(
        select(UserSearch).where(UserSearch.id == search_id)
    )
    search = result.scalar_one_or_none()

    if not search:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search not found",
        )

    if search.user_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    if search.status == SearchStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a running search. Cancel it first.",
        )

    await db.delete(search)
    await db.commit()
