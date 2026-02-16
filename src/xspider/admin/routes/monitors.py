"""API routes for influencer monitoring."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_user
from xspider.admin.database import get_db
from xspider.admin.models import (
    AdminUser,
    AuthenticityLabel,
    DMStatus,
    MonitoredInfluencer,
    MonitoredTweet,
    MonitorStatus,
    TweetCommenter,
)
from xspider.admin.schemas import (
    AnalyzeCommentersRequest,
    CommenterAnalysisSummary,
    CommenterExportRequest,
    CommenterFilterParams,
    MonitoredInfluencerCreate,
    MonitoredInfluencerResponse,
    MonitoredInfluencerUpdate,
    MonitoredTweetResponse,
    MonitoringStats,
    MonitorTaskResponse,
    ScrapeCommentersRequest,
    TweetCommenterResponse,
)
from xspider.admin.services.authenticity_analyzer import AuthenticityAnalyzer
from xspider.admin.services.commenter_scraper import CommenterScraperService
from xspider.admin.services.dm_checker import DMCheckerService
from xspider.admin.services.influencer_monitor import InfluencerMonitorService
from xspider.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/monitors", tags=["Monitoring"])


# =============================================================================
# Influencer Endpoints
# =============================================================================


@router.post("/influencers", response_model=MonitoredInfluencerResponse)
async def add_influencer(
    data: MonitoredInfluencerCreate,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MonitoredInfluencerResponse:
    """Add a new influencer to monitor."""
    from xspider.admin.services.token_pool_integration import create_managed_client

    service = InfluencerMonitorService(db)

    # Check if already monitoring this influencer
    existing = await service.get_influencer_by_screen_name(
        data.screen_name, current_user.id
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Already monitoring @{data.screen_name}",
        )

    # Fetch user info from Twitter
    try:
        client = await create_managed_client()
        user_data = await client.get_user_by_screen_name(data.screen_name)

        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Twitter user @{data.screen_name} not found",
            )

        legacy = user_data.get("legacy", {})
        twitter_user_id = user_data.get("rest_id", "")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to fetch Twitter user", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to fetch Twitter user info",
        )

    # Add to database
    influencer = await service.add_influencer(
        user_id=current_user.id,
        twitter_user_id=twitter_user_id,
        screen_name=data.screen_name,
        display_name=legacy.get("name"),
        bio=legacy.get("description"),
        followers_count=legacy.get("followers_count", 0),
        following_count=legacy.get("friends_count", 0),
        tweet_count=legacy.get("statuses_count", 0),
        verified=legacy.get("verified", False),
        profile_image_url=legacy.get("profile_image_url_https"),
        monitor_since=data.monitor_since,
        monitor_until=data.monitor_until,
        check_interval_minutes=data.check_interval_minutes,
        notes=data.notes,
    )

    return MonitoredInfluencerResponse.model_validate(influencer)


@router.get("/influencers", response_model=dict)
async def list_influencers(
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    status_filter: MonitorStatus | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    """List monitored influencers for current user."""
    service = InfluencerMonitorService(db)
    influencers, total = await service.list_influencers(
        user_id=current_user.id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )

    return {
        "influencers": [
            MonitoredInfluencerResponse.model_validate(i) for i in influencers
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/influencers/{influencer_id}", response_model=MonitoredInfluencerResponse)
async def get_influencer(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MonitoredInfluencerResponse:
    """Get a monitored influencer by ID."""
    service = InfluencerMonitorService(db)
    influencer = await service.get_influencer(influencer_id)

    if not influencer or influencer.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Influencer not found",
        )

    return MonitoredInfluencerResponse.model_validate(influencer)


@router.patch("/influencers/{influencer_id}", response_model=MonitoredInfluencerResponse)
async def update_influencer(
    influencer_id: int,
    data: MonitoredInfluencerUpdate,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MonitoredInfluencerResponse:
    """Update monitored influencer settings."""
    service = InfluencerMonitorService(db)
    influencer = await service.get_influencer(influencer_id)

    if not influencer or influencer.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Influencer not found",
        )

    # Update fields
    if data.status is not None:
        influencer = await service.update_influencer_status(influencer_id, data.status)
    if data.monitor_since is not None:
        influencer.monitor_since = data.monitor_since
    if data.monitor_until is not None:
        influencer.monitor_until = data.monitor_until
    if data.check_interval_minutes is not None:
        influencer.check_interval_minutes = data.check_interval_minutes
    if data.notes is not None:
        influencer.notes = data.notes

    await db.commit()
    await db.refresh(influencer)

    return MonitoredInfluencerResponse.model_validate(influencer)


@router.delete("/influencers/{influencer_id}")
async def delete_influencer(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a monitored influencer."""
    service = InfluencerMonitorService(db)
    influencer = await service.get_influencer(influencer_id)

    if not influencer or influencer.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Influencer not found",
        )

    await db.delete(influencer)
    await db.commit()

    return {"message": "Influencer deleted successfully"}


# =============================================================================
# Tweet Endpoints
# =============================================================================


@router.get("/influencers/{influencer_id}/tweets", response_model=dict)
async def list_tweets(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    since: datetime | None = None,
    until: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict:
    """List tweets for a monitored influencer."""
    service = InfluencerMonitorService(db)

    # Verify ownership
    influencer = await service.get_influencer(influencer_id)
    if not influencer or influencer.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Influencer not found",
        )

    tweets, total = await service.get_tweets(
        influencer_id=influencer_id,
        since=since,
        until=until,
        page=page,
        page_size=page_size,
    )

    return {
        "tweets": [MonitoredTweetResponse.model_validate(t) for t in tweets],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("/influencers/{influencer_id}/fetch-tweets", response_model=MonitorTaskResponse)
async def fetch_influencer_tweets(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    max_tweets: int = Query(20, ge=1, le=100),
) -> MonitorTaskResponse:
    """Fetch latest tweets from an influencer."""
    from xspider.admin.services.token_pool_integration import create_managed_client

    service = InfluencerMonitorService(db)

    # Verify ownership
    influencer = await service.get_influencer(influencer_id)
    if not influencer or influencer.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Influencer not found",
        )

    try:
        client = await create_managed_client()

        # Fetch tweets using user timeline
        added_count = 0
        async for tweet in client.iter_user_tweets(
            influencer.twitter_user_id, max_count=max_tweets
        ):
            legacy = tweet.get("legacy", {})
            tweet_id = tweet.get("rest_id", "")

            if not tweet_id:
                continue

            # Check if within monitoring period
            tweeted_at_str = legacy.get("created_at", "")
            try:
                tweeted_at = datetime.strptime(
                    tweeted_at_str, "%a %b %d %H:%M:%S %z %Y"
                )
            except (ValueError, TypeError):
                continue

            if influencer.monitor_since and tweeted_at < influencer.monitor_since:
                continue
            if influencer.monitor_until and tweeted_at > influencer.monitor_until:
                continue

            # Extract media and links
            media_urls = []
            links = []
            entities = legacy.get("entities", {})

            for media in entities.get("media", []):
                media_urls.append(media.get("media_url_https", ""))

            for url in entities.get("urls", []):
                links.append(url.get("expanded_url", ""))

            # Add tweet
            result = await service.add_tweet(
                influencer_id=influencer_id,
                tweet_id=tweet_id,
                content=legacy.get("full_text", ""),
                tweet_type="tweet",
                like_count=legacy.get("favorite_count", 0),
                retweet_count=legacy.get("retweet_count", 0),
                reply_count=legacy.get("reply_count", 0),
                quote_count=legacy.get("quote_count", 0),
                view_count=tweet.get("views", {}).get("count"),
                bookmark_count=legacy.get("bookmark_count", 0),
                has_media=len(media_urls) > 0,
                media_urls=media_urls if media_urls else None,
                has_links=len(links) > 0,
                links=links if links else None,
                tweeted_at=tweeted_at,
            )

            if result:
                added_count += 1

        # Update check time
        await service.update_influencer_check_time(influencer_id)

        return MonitorTaskResponse(
            task_id=f"fetch-{influencer_id}",
            status="completed",
            message=f"Fetched {added_count} new tweets",
        )

    except Exception as e:
        logger.error("Failed to fetch tweets", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to fetch tweets from Twitter",
        )


# =============================================================================
# Commenter Endpoints
# =============================================================================


@router.post("/tweets/{tweet_id}/scrape-commenters", response_model=MonitorTaskResponse)
async def scrape_tweet_commenters(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    max_commenters: int = Query(100, ge=1, le=1000),
) -> MonitorTaskResponse:
    """Scrape commenters (replies) for a tweet."""
    # Verify tweet ownership
    result = await db.execute(
        select(MonitoredTweet)
        .join(MonitoredInfluencer)
        .where(
            MonitoredTweet.id == tweet_id,
            MonitoredInfluencer.user_id == current_user.id,
        )
    )
    tweet = result.scalar_one_or_none()

    if not tweet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tweet not found",
        )

    service = CommenterScraperService(db)
    added_count = await service.scrape_tweet_replies(tweet, max_replies=max_commenters)

    return MonitorTaskResponse(
        task_id=f"scrape-{tweet_id}",
        status="completed",
        message=f"Scraped {added_count} new commenters",
    )


@router.get("/tweets/{tweet_id}/commenters", response_model=dict)
async def list_commenters(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    is_real_user: bool | None = None,
    is_bot: bool | None = None,
    can_dm: bool | None = None,
    min_authenticity_score: float | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict:
    """List commenters for a tweet with filters."""
    # Verify tweet ownership
    result = await db.execute(
        select(MonitoredTweet)
        .join(MonitoredInfluencer)
        .where(
            MonitoredTweet.id == tweet_id,
            MonitoredInfluencer.user_id == current_user.id,
        )
    )
    tweet = result.scalar_one_or_none()

    if not tweet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tweet not found",
        )

    service = CommenterScraperService(db)
    commenters, total = await service.get_commenters(
        tweet_id=tweet_id,
        is_real_user=is_real_user,
        is_bot=is_bot,
        can_dm=can_dm,
        min_authenticity_score=min_authenticity_score,
        page=page,
        page_size=page_size,
    )

    return {
        "commenters": [TweetCommenterResponse.model_validate(c) for c in commenters],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.post("/tweets/{tweet_id}/analyze-commenters", response_model=MonitorTaskResponse)
async def analyze_tweet_commenters(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    force_reanalyze: bool = False,
    use_llm: bool = False,
) -> MonitorTaskResponse:
    """Analyze authenticity of commenters for a tweet."""
    # Verify tweet ownership
    result = await db.execute(
        select(MonitoredTweet)
        .join(MonitoredInfluencer)
        .where(
            MonitoredTweet.id == tweet_id,
            MonitoredInfluencer.user_id == current_user.id,
        )
    )
    tweet = result.scalar_one_or_none()

    if not tweet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tweet not found",
        )

    analyzer = AuthenticityAnalyzer(db)
    analyzed_count = await analyzer.analyze_tweet_commenters(
        tweet_id=tweet_id,
        use_llm=use_llm,
        force_reanalyze=force_reanalyze,
    )

    return MonitorTaskResponse(
        task_id=f"analyze-{tweet_id}",
        status="completed",
        message=f"Analyzed {analyzed_count} commenters",
    )


@router.get("/tweets/{tweet_id}/analysis-summary", response_model=CommenterAnalysisSummary)
async def get_analysis_summary(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CommenterAnalysisSummary:
    """Get analysis summary for a tweet's commenters."""
    # Verify tweet ownership
    result = await db.execute(
        select(MonitoredTweet)
        .join(MonitoredInfluencer)
        .where(
            MonitoredTweet.id == tweet_id,
            MonitoredInfluencer.user_id == current_user.id,
        )
    )
    tweet = result.scalar_one_or_none()

    if not tweet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tweet not found",
        )

    service = CommenterScraperService(db)
    summary = await service.get_analysis_summary(tweet_id)

    return CommenterAnalysisSummary(**summary)


@router.post("/tweets/{tweet_id}/check-dm", response_model=MonitorTaskResponse)
async def check_dm_status(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    only_real_users: bool = True,
    force_recheck: bool = False,
) -> MonitorTaskResponse:
    """Check DM availability for commenters."""
    # Verify tweet ownership
    result = await db.execute(
        select(MonitoredTweet)
        .join(MonitoredInfluencer)
        .where(
            MonitoredTweet.id == tweet_id,
            MonitoredInfluencer.user_id == current_user.id,
        )
    )
    tweet = result.scalar_one_or_none()

    if not tweet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tweet not found",
        )

    checker = DMCheckerService(db)
    checked_count = await checker.check_tweet_commenters(
        tweet_id=tweet_id,
        only_real_users=only_real_users,
        force_recheck=force_recheck,
    )

    return MonitorTaskResponse(
        task_id=f"dm-check-{tweet_id}",
        status="completed",
        message=f"Checked DM status for {checked_count} users",
    )


@router.get("/tweets/{tweet_id}/dm-summary", response_model=dict)
async def get_dm_summary(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get DM availability summary for a tweet's commenters."""
    # Verify tweet ownership
    result = await db.execute(
        select(MonitoredTweet)
        .join(MonitoredInfluencer)
        .where(
            MonitoredTweet.id == tweet_id,
            MonitoredInfluencer.user_id == current_user.id,
        )
    )
    tweet = result.scalar_one_or_none()

    if not tweet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tweet not found",
        )

    checker = DMCheckerService(db)
    return await checker.get_dm_summary(tweet_id)


# =============================================================================
# Statistics Endpoints
# =============================================================================


@router.get("/stats", response_model=MonitoringStats)
async def get_monitoring_stats(
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> MonitoringStats:
    """Get monitoring statistics for current user."""
    service = InfluencerMonitorService(db)
    stats = await service.get_monitoring_stats(user_id=current_user.id)

    return MonitoringStats(**stats)


# =============================================================================
# Export Endpoints
# =============================================================================


@router.post("/export-commenters")
async def export_commenters(
    request: CommenterExportRequest,
    current_user: Annotated[AdminUser, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Export commenters data to CSV or JSON."""
    import csv
    import io
    import json
    from datetime import datetime as dt

    from fastapi.responses import StreamingResponse

    # Build query
    query = select(TweetCommenter)

    if request.tweet_id:
        # Verify tweet ownership
        result = await db.execute(
            select(MonitoredTweet)
            .join(MonitoredInfluencer)
            .where(
                MonitoredTweet.id == request.tweet_id,
                MonitoredInfluencer.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tweet not found",
            )
        query = query.where(TweetCommenter.tweet_id == request.tweet_id)

    elif request.influencer_id:
        # Verify influencer ownership
        result = await db.execute(
            select(MonitoredInfluencer).where(
                MonitoredInfluencer.id == request.influencer_id,
                MonitoredInfluencer.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Influencer not found",
            )

        # Get all tweet IDs for this influencer
        tweet_ids_result = await db.execute(
            select(MonitoredTweet.id).where(
                MonitoredTweet.influencer_id == request.influencer_id
            )
        )
        tweet_ids = [row[0] for row in tweet_ids_result.fetchall()]
        query = query.where(TweetCommenter.tweet_id.in_(tweet_ids))

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify tweet_id or influencer_id",
        )

    # Apply filters
    if request.filters:
        if request.filters.is_real_user is not None:
            query = query.where(TweetCommenter.is_real_user == request.filters.is_real_user)
        if request.filters.is_bot is not None:
            query = query.where(TweetCommenter.is_bot == request.filters.is_bot)
        if request.filters.can_dm is not None:
            query = query.where(TweetCommenter.can_dm == request.filters.can_dm)
        if request.filters.min_authenticity_score is not None:
            query = query.where(
                TweetCommenter.authenticity_score >= request.filters.min_authenticity_score
            )

    result = await db.execute(query)
    commenters = list(result.scalars().all())

    # Generate output
    if request.format == "json":
        data = []
        for c in commenters:
            item = {
                "twitter_user_id": c.twitter_user_id,
                "screen_name": c.screen_name,
                "display_name": c.display_name,
                "bio": c.bio,
                "followers_count": c.followers_count,
                "following_count": c.following_count,
                "tweet_count": c.tweet_count,
                "verified": c.verified,
                "comment_text": c.comment_text,
                "commented_at": c.commented_at.isoformat() if c.commented_at else None,
            }
            if request.include_analysis:
                item.update({
                    "authenticity_score": c.authenticity_score,
                    "primary_label": c.primary_label.value if c.primary_label else None,
                    "is_bot": c.is_bot,
                    "is_real_user": c.is_real_user,
                    "is_suspicious": c.is_suspicious,
                    "can_dm": c.can_dm,
                    "dm_status": c.dm_status.value if c.dm_status else None,
                    "analysis_reasoning": c.analysis_reasoning,
                })
            data.append(item)

        content = json.dumps(data, indent=2, ensure_ascii=False)
        filename = f"commenters_{dt.now().strftime('%Y%m%d_%H%M%S')}.json"

        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    else:  # CSV
        output = io.StringIO()
        fieldnames = [
            "twitter_user_id",
            "screen_name",
            "display_name",
            "bio",
            "followers_count",
            "following_count",
            "tweet_count",
            "verified",
            "comment_text",
            "commented_at",
        ]
        if request.include_analysis:
            fieldnames.extend([
                "authenticity_score",
                "primary_label",
                "is_bot",
                "is_real_user",
                "is_suspicious",
                "can_dm",
                "dm_status",
                "analysis_reasoning",
            ])

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for c in commenters:
            row = {
                "twitter_user_id": c.twitter_user_id,
                "screen_name": c.screen_name,
                "display_name": c.display_name or "",
                "bio": (c.bio or "").replace("\n", " "),
                "followers_count": c.followers_count,
                "following_count": c.following_count,
                "tweet_count": c.tweet_count,
                "verified": c.verified,
                "comment_text": (c.comment_text or "").replace("\n", " "),
                "commented_at": c.commented_at.isoformat() if c.commented_at else "",
            }
            if request.include_analysis:
                row.update({
                    "authenticity_score": c.authenticity_score,
                    "primary_label": c.primary_label.value if c.primary_label else "",
                    "is_bot": c.is_bot,
                    "is_real_user": c.is_real_user,
                    "is_suspicious": c.is_suspicious,
                    "can_dm": c.can_dm,
                    "dm_status": c.dm_status.value if c.dm_status else "",
                    "analysis_reasoning": (c.analysis_reasoning or "").replace("\n", " "),
                })
            writer.writerow(row)

        content = output.getvalue()
        filename = f"commenters_{dt.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            io.BytesIO(content.encode("utf-8-sig")),  # BOM for Excel
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
