"""Search task routes for users."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_current_admin, get_db_session
from xspider.admin.models import (
    AdminUser,
    CrawlMode,
    CreditTransaction,
    DiscoveredInfluencer,
    InfluencerRelationship,
    SearchStatus,
    TransactionType,
    UserSearch,
)
from xspider.admin.schemas import (
    GraphEdgeResponse,
    GraphNodeResponse,
    InfluencerResponse,
    RecommendedSeedInfo,
    RelationshipResponse,
    SearchCreate,
    SearchDetailResponse,
    SearchEstimate,
    SearchGraphResponse,
    SearchPreview,
    SearchProgressResponse,
    SearchResponse,
    SeedRecommendationRequest,
    SeedRecommendationResponse,
    SeedUserInfo,
)

router = APIRouter()

# Credit costs
CREDIT_COST_SEARCH_SEED = 10
CREDIT_COST_CRAWL_PER_100 = 5
CREDIT_COST_AI_AUDIT = 2
CREDIT_COST_LLM_PER_1K = 1
CREDIT_COST_SEED_RECOMMENDATION = 5  # Cost for AI seed recommendation


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


# NOTE: Static routes MUST come before dynamic routes like /{search_id}
# to ensure proper route matching in FastAPI


@router.post("/resolve-users", response_model=list[SeedUserInfo])
async def resolve_seed_users(
    usernames: Annotated[list[str], Body(embed=True)],
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> list[SeedUserInfo]:
    """Resolve seed usernames to user information.

    Takes a list of Twitter usernames (without @) and returns their profile info.
    This allows the UI to preview and validate seed users before starting a search.
    """
    from xspider.admin.models import AccountStatus, TwitterAccount
    from xspider.admin.services.account_pool import AccountPool

    # Get active Twitter accounts
    result = await db.execute(
        select(TwitterAccount).where(TwitterAccount.status == AccountStatus.ACTIVE).limit(5)
    )
    db_accounts = list(result.scalars().all())

    if not db_accounts:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active Twitter accounts available",
        )

    # Create account pool
    pool = AccountPool.from_db_accounts(db_accounts)

    resolved_users: list[SeedUserInfo] = []

    for username in usernames:
        # Clean up username (remove @ if present)
        clean_username = username.strip().lstrip("@")
        if not clean_username:
            continue

        # Get an available account
        account = await pool.get_account()
        if not account:
            resolved_users.append(SeedUserInfo(
                username=clean_username,
                valid=False,
                error="No available accounts",
            ))
            continue

        try:
            client = account.get_client()
            user = await client.get_user_by_screen_name(clean_username)

            if user:
                resolved_users.append(SeedUserInfo(
                    username=user.screen_name,
                    user_id=user.id,
                    name=user.name,
                    description=user.description,
                    followers_count=user.followers_count,
                    following_count=user.following_count,
                    profile_image_url=user.profile_image_url,
                    valid=True,
                ))
            else:
                resolved_users.append(SeedUserInfo(
                    username=clean_username,
                    valid=False,
                    error="User not found",
                ))
        except Exception as e:
            error_msg = str(e)
            if "TooManyRequests" in error_msg or "rate" in error_msg.lower():
                account.mark_rate_limited()
                error_msg = "Rate limited"
            resolved_users.append(SeedUserInfo(
                username=clean_username,
                valid=False,
                error=error_msg[:100],  # Truncate long error messages
            ))

    return resolved_users


@router.post("/recommend-seeds", response_model=SeedRecommendationResponse)
async def recommend_seed_users(
    request: SeedRecommendationRequest,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> SeedRecommendationResponse:
    """Use LLM to recommend seed influencers based on user prompt.

    Takes a natural language description of the desired influencer characteristics
    and uses AI to suggest relevant Twitter accounts as seeds.

    Example prompts:
    - "Find crypto KOLs who discuss DeFi and have 10K-100K followers"
    - "Looking for AI researchers and ML engineers who are active on Twitter"
    - "推荐一些中文区的Web3投资人和项目方"
    """
    # Check credits
    if current_user.credits < CREDIT_COST_SEED_RECOMMENDATION:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient credits. Need {CREDIT_COST_SEED_RECOMMENDATION} credits for AI recommendation.",
        )

    try:
        from xspider.admin.services.seed_recommender import recommend_seeds

        # Call LLM for recommendations
        result = await recommend_seeds(
            prompt=request.prompt,
            num_recommendations=request.num_recommendations,
            language=request.language,
        )

        # Deduct credits
        current_user.credits -= CREDIT_COST_SEED_RECOMMENDATION

        # Create transaction
        transaction = CreditTransaction(
            user_id=current_user.id,
            amount=-CREDIT_COST_SEED_RECOMMENDATION,
            balance_after=current_user.credits,
            type=TransactionType.SEARCH,
            description=f"AI seed recommendation: {request.prompt[:50]}...",
        )
        db.add(transaction)
        await db.commit()

        # Convert to response
        recommendations = [
            RecommendedSeedInfo(
                username=seed.username,
                reason=seed.reason,
                estimated_followers=seed.estimated_followers,
                relevance_score=seed.relevance_score,
                category=seed.category,
                verified=None,
            )
            for seed in result.seeds
        ]

        return SeedRecommendationResponse(
            summary=result.summary,
            recommendations=recommendations,
            model_used=result.model_used,
            tokens_used=result.tokens_used,
            credits_used=CREDIT_COST_SEED_RECOMMENDATION,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate recommendations: {str(e)[:200]}",
        )


@router.post("/preview", response_model=SearchPreview)
async def preview_search(
    request: SearchCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> SearchPreview:
    """Preview search with resolved seed users and cost estimate.

    Resolves seed usernames if provided and estimates the search cost.
    """
    seed_users: list[SeedUserInfo] = []
    valid_seeds = 0
    invalid_seeds = 0

    # If seeds provided, resolve them first
    if request.seed_usernames and len(request.seed_usernames) > 0:
        from xspider.admin.models import AccountStatus, TwitterAccount
        from xspider.admin.services.account_pool import AccountPool

        # Get active Twitter accounts
        result = await db.execute(
            select(TwitterAccount).where(TwitterAccount.status == AccountStatus.ACTIVE).limit(5)
        )
        db_accounts = list(result.scalars().all())

        if db_accounts:
            pool = AccountPool.from_db_accounts(db_accounts)

            for username in request.seed_usernames:
                clean_username = username.strip().lstrip("@")
                if not clean_username:
                    continue

                account = await pool.get_account()
                if not account:
                    seed_users.append(SeedUserInfo(
                        username=clean_username,
                        valid=False,
                        error="No available accounts",
                    ))
                    invalid_seeds += 1
                    continue

                try:
                    client = account.get_client()
                    user = await client.get_user_by_screen_name(clean_username)

                    if user:
                        seed_users.append(SeedUserInfo(
                            username=user.screen_name,
                            user_id=user.id,
                            name=user.name,
                            description=user.description,
                            followers_count=user.followers_count,
                            following_count=user.following_count,
                            profile_image_url=user.profile_image_url,
                            valid=True,
                        ))
                        valid_seeds += 1
                    else:
                        seed_users.append(SeedUserInfo(
                            username=clean_username,
                            valid=False,
                            error="User not found",
                        ))
                        invalid_seeds += 1
                except Exception as e:
                    error_msg = str(e)
                    if "TooManyRequests" in error_msg or "rate" in error_msg.lower():
                        account.mark_rate_limited()
                        error_msg = "Rate limited"
                    seed_users.append(SeedUserInfo(
                        username=clean_username,
                        valid=False,
                        error=error_msg[:100],
                    ))
                    invalid_seeds += 1

    # Estimate crawl users and credits
    estimated_seeds = valid_seeds if valid_seeds > 0 else 50  # Default for keyword mode
    estimated_crawl_users = estimated_seeds * (50 if request.crawl_depth > 0 else 1) * request.crawl_depth

    estimated_credits = (
        CREDIT_COST_SEARCH_SEED +
        (estimated_crawl_users // 100) * CREDIT_COST_CRAWL_PER_100 +
        min(estimated_seeds, 100) * CREDIT_COST_AI_AUDIT
    )

    return SearchPreview(
        seed_users=seed_users,
        valid_seeds=valid_seeds,
        invalid_seeds=invalid_seeds,
        estimated_crawl_users=estimated_crawl_users,
        estimated_credits=estimated_credits,
    )


@router.post("/estimate", response_model=SearchEstimate)
async def estimate_search_cost(
    request: SearchCreate,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
) -> SearchEstimate:
    """Estimate credit cost for a search.

    Provides a rough estimate based on crawl mode and depth.
    """
    # Estimate seeds based on mode
    if request.crawl_mode == CrawlMode.SEEDS:
        estimated_seeds = len(request.seed_usernames) if request.seed_usernames else 5
    elif request.crawl_mode == CrawlMode.MIXED:
        seed_count = len(request.seed_usernames) if request.seed_usernames else 0
        estimated_seeds = seed_count + 30  # Seeds + estimated keyword results
    else:  # keywords mode
        estimated_seeds = 50  # Typical keyword search result

    # Estimate crawl users based on depth
    if request.crawl_depth == 0:
        estimated_crawl_users = 0
    else:
        # Each level multiplies by ~30-50 users per seed
        estimated_crawl_users = estimated_seeds * 40 * request.crawl_depth

    estimated_audits = min(estimated_seeds + estimated_crawl_users // 10, 200)

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
    """Create a new search task.

    Supports three crawl modes:
    - keywords: Traditional keyword-based search (requires keywords)
    - seeds: Start from specified influencer usernames (requires seed_usernames)
    - mixed: Combine both keyword search and seed users
    """
    # Check minimum credits
    if current_user.credits < CREDIT_COST_SEARCH_SEED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Insufficient credits. Need at least {CREDIT_COST_SEARCH_SEED} credits to start a search.",
        )

    # Serialize seed_usernames to JSON if provided
    seed_usernames_json = None
    if request.seed_usernames and len(request.seed_usernames) > 0:
        # Clean up usernames (remove @ if present)
        clean_usernames = [u.strip().lstrip("@") for u in request.seed_usernames if u.strip()]
        if clean_usernames:
            seed_usernames_json = json.dumps(clean_usernames)

    # Create search record
    # Use empty string for keywords if not provided (database has NOT NULL constraint)
    search = UserSearch(
        user_id=current_user.id,
        keywords=request.keywords.strip() if request.keywords else "",
        industry=request.industry,
        crawl_depth=request.crawl_depth,
        crawl_mode=request.crawl_mode,
        seed_usernames=seed_usernames_json,
        crawl_commenters=request.crawl_commenters,
        tweets_per_user=request.tweets_per_user,
        commenters_per_tweet=request.commenters_per_tweet,
        status=SearchStatus.PENDING,
    )
    db.add(search)
    await db.commit()
    await db.refresh(search)

    return search


# Dynamic routes with {search_id} parameter - these MUST come after static routes
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

    # Get relationships
    rel_result = await db.execute(
        select(InfluencerRelationship)
        .where(InfluencerRelationship.search_id == search_id)
    )
    relationships = list(rel_result.scalars().all())

    return {
        **SearchResponse.model_validate(search).model_dump(),
        "influencers": [InfluencerResponse.model_validate(i) for i in influencers],
        "relationships": [RelationshipResponse.model_validate(r) for r in relationships],
    }


@router.get("/{search_id}/progress", response_model=SearchProgressResponse)
async def get_search_progress(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
) -> UserSearch:
    """Get search task progress for polling."""
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

    return search


@router.get("/{search_id}/graph", response_model=SearchGraphResponse)
async def get_search_graph(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: AsyncSession = Depends(get_db_session),
    max_nodes: int = Query(500, ge=10, le=2000),
) -> SearchGraphResponse:
    """Get relationship graph data for visualization."""
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

    # Get top influencers (limit nodes for performance)
    inf_result = await db.execute(
        select(DiscoveredInfluencer)
        .where(DiscoveredInfluencer.search_id == search_id)
        .order_by(DiscoveredInfluencer.pagerank_score.desc())
        .limit(max_nodes)
    )
    influencers = list(inf_result.scalars().all())

    # Build set of included node IDs
    node_ids = {inf.twitter_user_id for inf in influencers}

    # Get relationships between included nodes
    rel_result = await db.execute(
        select(InfluencerRelationship)
        .where(InfluencerRelationship.search_id == search_id)
    )
    all_relationships = list(rel_result.scalars().all())

    # Filter relationships to only include edges between visible nodes
    edges = [
        GraphEdgeResponse(source=r.source_twitter_id, target=r.target_twitter_id)
        for r in all_relationships
        if r.source_twitter_id in node_ids and r.target_twitter_id in node_ids
    ]

    # Build nodes
    nodes = [
        GraphNodeResponse(
            id=inf.twitter_user_id,
            screen_name=inf.screen_name,
            name=inf.name,
            followers_count=inf.followers_count,
            depth=inf.depth,
            pagerank_score=inf.pagerank_score,
        )
        for inf in influencers
    ]

    # Calculate stats
    depth_counts = {}
    for inf in influencers:
        depth_counts[inf.depth] = depth_counts.get(inf.depth, 0) + 1

    stats = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "total_relationships": len(all_relationships),
        "max_depth": max(inf.depth for inf in influencers) if influencers else 0,
        **{f"depth_{d}_count": c for d, c in depth_counts.items()},
    }

    return SearchGraphResponse(nodes=nodes, edges=edges, stats=stats)


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

    # Create transaction description based on crawl mode
    if search.keywords:
        description = f"Search: {search.keywords[:50]}"
    elif search.seed_usernames:
        import json
        seeds = json.loads(search.seed_usernames)
        description = f"Seed search: @{', @'.join(seeds[:3])}"
        if len(seeds) > 3:
            description += f" +{len(seeds) - 3} more"
    else:
        description = f"Search #{search.id}"

    # Create transaction
    transaction = CreditTransaction(
        user_id=current_user.id,
        amount=-CREDIT_COST_SEARCH_SEED,
        balance_after=current_user.credits,
        type=TransactionType.SEARCH,
        description=description,
        search_id=search.id,
    )
    db.add(transaction)

    # Update status
    search.status = SearchStatus.RUNNING
    search.progress_updated_at = datetime.now(timezone.utc)

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
    """Cancel a running search task and refund credits."""
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

    # Refund credits if any were used
    refund_amount = search.credits_used
    if refund_amount > 0:
        # Get the search owner for refund
        owner_result = await db.execute(
            select(AdminUser).where(AdminUser.id == search.user_id)
        )
        owner = owner_result.scalar_one()
        owner.credits += refund_amount

        # Create refund transaction
        search_desc = search.keywords[:30] if search.keywords else f"#{search.id}"
        refund_transaction = CreditTransaction(
            user_id=search.user_id,
            amount=refund_amount,
            balance_after=owner.credits,
            type=TransactionType.REFUND,
            description=f"Refund for cancelled search: {search_desc}",
            search_id=search.id,
        )
        db.add(refund_transaction)

    search.status = SearchStatus.FAILED
    search.error_message = f"Cancelled by user. Refunded {refund_amount} credits."
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

    # Helper to format links for display
    def format_links(links_json: str | None) -> str:
        if not links_json:
            return ""
        try:
            links = json.loads(links_json)
            return " | ".join(links) if links else ""
        except json.JSONDecodeError:
            return ""

    if format == "json":
        data = [
            {
                "twitter_user_id": inf.twitter_user_id,
                "screen_name": inf.screen_name,
                "name": inf.name,
                "description": inf.description,
                "followers_count": inf.followers_count,
                "pagerank_score": inf.pagerank_score,
                "hidden_score": inf.hidden_score,
                "is_relevant": inf.is_relevant,
                "relevance_score": inf.relevance_score,
                "extracted_links": json.loads(inf.extracted_links) if inf.extracted_links else [],
            }
            for inf in influencers
        ]
        content = json.dumps(data, indent=2, ensure_ascii=False)
        media_type = "application/json"
        filename = f"search_{search_id}_results.json"
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "twitter_user_id",
            "screen_name",
            "name",
            "description",
            "followers_count",
            "pagerank_score",
            "hidden_score",
            "is_relevant",
            "relevance_score",
            "links",
        ])
        for inf in influencers:
            writer.writerow([
                inf.twitter_user_id,
                inf.screen_name,
                inf.name,
                inf.description or "",
                inf.followers_count,
                inf.pagerank_score,
                inf.hidden_score,
                inf.is_relevant,
                inf.relevance_score,
                format_links(inf.extracted_links),
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
