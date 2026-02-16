"""Analytics Routes (分析路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, IntentLabel
from xspider.admin.services import (
    AudienceOverlapService,
    GrowthMonitor,
    IntentAnalyzer,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ==================== Intent Analysis ====================


@router.post("/intent/analyze/{tweet_id}")
async def analyze_tweet_intent(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    use_llm: bool = False,
    only_real_users: bool = True,
) -> dict[str, Any]:
    """Analyze intent for all commenters of a tweet."""
    analyzer = IntentAnalyzer(db)

    stats = await analyzer.analyze_tweet_commenters(
        tweet_id=tweet_id,
        use_llm=use_llm,
        only_real_users=only_real_users,
    )

    return {"success": True, "stats": stats}


@router.get("/intent/high-intent")
async def get_high_intent_commenters(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    tweet_id: int | None = None,
    influencer_id: int | None = None,
    intent_labels: str | None = None,  # Comma-separated
    min_confidence: float = 0.5,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    """Get high-intent commenters with filters."""
    analyzer = IntentAnalyzer(db)

    # Parse intent labels
    label_list = None
    if intent_labels:
        label_list = [IntentLabel(i.strip()) for i in intent_labels.split(",")]

    commenters, total = await analyzer.get_high_intent_commenters(
        tweet_id=tweet_id,
        influencer_id=influencer_id,
        intent_labels=label_list,
        min_confidence=min_confidence,
        page=page,
        page_size=page_size,
    )

    return {
        "commenters": [
            {
                "id": c.id,
                "screen_name": c.screen_name,
                "display_name": c.display_name,
                "comment_text": c.comment_text[:200] + "..." if len(c.comment_text) > 200 else c.comment_text,
                "intent_label": c.intent_label.value if c.intent_label else None,
                "sentiment": c.sentiment.value if c.sentiment else None,
                "intent_confidence": c.intent_confidence,
                "intent_keywords": c.intent_keywords,
                "dm_status": c.dm_status.value if c.dm_status else None,
                "followers_count": c.followers_count,
            }
            for c in commenters
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/intent/summary/{tweet_id}")
async def get_intent_summary(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get intent analysis summary for a tweet."""
    analyzer = IntentAnalyzer(db)
    return await analyzer.get_intent_summary(tweet_id)


# ==================== Growth Monitoring ====================


@router.post("/growth/snapshot/{influencer_id}")
async def take_growth_snapshot(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Take a growth snapshot for an influencer."""
    from xspider.admin.models import MonitoredInfluencer
    from sqlalchemy import select

    # Get influencer
    result = await db.execute(
        select(MonitoredInfluencer).where(
            MonitoredInfluencer.id == influencer_id,
            MonitoredInfluencer.user_id == current_user.id,
        )
    )
    influencer = result.scalar_one_or_none()

    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")

    monitor = GrowthMonitor(db)
    snapshot = await monitor.take_snapshot(influencer)

    return {
        "success": True,
        "snapshot": {
            "id": snapshot.id,
            "followers_count": snapshot.followers_count,
            "followers_change": snapshot.followers_change,
            "followers_change_pct": snapshot.followers_change_pct,
            "avg_likes": snapshot.avg_likes,
            "avg_retweets": snapshot.avg_retweets,
            "is_anomaly": snapshot.is_anomaly,
            "anomaly_type": snapshot.anomaly_type,
            "anomaly_score": snapshot.anomaly_score,
            "snapshot_at": snapshot.snapshot_at.isoformat() if snapshot.snapshot_at else None,
        },
    }


@router.post("/growth/batch-snapshot")
async def batch_take_snapshots(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Take snapshots for all active monitored influencers."""
    monitor = GrowthMonitor(db)
    count = await monitor.batch_take_snapshots(user_id=current_user.id)

    return {"success": True, "snapshots_taken": count}


@router.get("/growth/history/{influencer_id}")
async def get_growth_history(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    days: int = Query(30, ge=1, le=365),
) -> dict[str, Any]:
    """Get growth history for an influencer."""
    monitor = GrowthMonitor(db)
    snapshots = await monitor.get_growth_history(influencer_id, days=days)

    return {
        "history": [
            {
                "snapshot_at": s.snapshot_at.isoformat() if s.snapshot_at else None,
                "followers_count": s.followers_count,
                "followers_change": s.followers_change,
                "followers_change_pct": s.followers_change_pct,
                "avg_likes": s.avg_likes,
                "avg_retweets": s.avg_retweets,
                "is_anomaly": s.is_anomaly,
                "anomaly_type": s.anomaly_type,
                "anomaly_score": s.anomaly_score,
            }
            for s in snapshots
        ]
    }


@router.get("/growth/anomalies")
async def get_growth_anomalies(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    days: int = Query(7, ge=1, le=30),
    min_score: float = Query(30.0, ge=0, le=100),
) -> dict[str, Any]:
    """Get recent growth anomalies."""
    monitor = GrowthMonitor(db)
    anomalies = await monitor.get_anomalies(
        user_id=current_user.id,
        days=days,
        min_score=min_score,
    )

    return {"anomalies": anomalies}


@router.get("/growth/summary/{influencer_id}")
async def get_growth_summary(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get growth summary for an influencer."""
    monitor = GrowthMonitor(db)
    return await monitor.get_growth_summary(influencer_id)


# ==================== Audience Overlap ====================


@router.post("/overlap/analyze")
async def analyze_audience_overlap(
    influencer_a_id: int,
    influencer_b_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Analyze follower overlap between two influencers."""
    from xspider.admin.services import CreditService

    # Check credits
    credit_service = CreditService(db)
    if not await credit_service.check_balance(current_user.id, 5):
        raise HTTPException(status_code=402, detail="Insufficient credits")

    service = AudienceOverlapService(db)

    try:
        analysis = await service.analyze_overlap(
            user_id=current_user.id,
            influencer_a_id=influencer_a_id,
            influencer_b_id=influencer_b_id,
        )

        # Deduct credits
        await credit_service.deduct_credits(
            user_id=current_user.id,
            amount=5,
            reason="Audience overlap analysis",
        )

        return {
            "success": True,
            "analysis": {
                "id": analysis.id,
                "influencer_a": analysis.influencer_a_screen_name,
                "influencer_b": analysis.influencer_b_screen_name,
                "followers_a": analysis.followers_a_count,
                "followers_b": analysis.followers_b_count,
                "overlap_count": analysis.overlap_count,
                "unique_a": analysis.unique_a_count,
                "unique_b": analysis.unique_b_count,
                "jaccard_index": analysis.jaccard_index,
                "overlap_pct_a": analysis.overlap_percentage_a,
                "overlap_pct_b": analysis.overlap_percentage_b,
                "sample_overlap_users": analysis.sample_overlap_users,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/overlap/history")
async def get_overlap_history(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Get audience overlap analysis history."""
    service = AudienceOverlapService(db)
    analyses, total = await service.get_analysis_history(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )

    return {
        "analyses": [
            {
                "id": a.id,
                "influencer_a": a.influencer_a_screen_name,
                "influencer_b": a.influencer_b_screen_name,
                "overlap_count": a.overlap_count,
                "jaccard_index": a.jaccard_index,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in analyses
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/overlap/{analysis_id}")
async def get_overlap_analysis(
    analysis_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get a specific overlap analysis."""
    service = AudienceOverlapService(db)
    analysis = await service.get_analysis_by_id(analysis_id, current_user.id)

    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return {
        "id": analysis.id,
        "influencer_a": analysis.influencer_a_screen_name,
        "influencer_b": analysis.influencer_b_screen_name,
        "followers_a": analysis.followers_a_count,
        "followers_b": analysis.followers_b_count,
        "overlap_count": analysis.overlap_count,
        "unique_a": analysis.unique_a_count,
        "unique_b": analysis.unique_b_count,
        "jaccard_index": analysis.jaccard_index,
        "overlap_pct_a": analysis.overlap_percentage_a,
        "overlap_pct_b": analysis.overlap_percentage_b,
        "sample_overlap_users": analysis.sample_overlap_users,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.get("/overlap/similar/{influencer_id}")
async def find_similar_audiences(
    influencer_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    min_overlap_pct: float = Query(30.0, ge=0, le=100),
) -> dict[str, Any]:
    """Find influencers with similar audiences."""
    service = AudienceOverlapService(db)
    similar = await service.find_similar_audiences(
        user_id=current_user.id,
        target_influencer_id=influencer_id,
        min_overlap_pct=min_overlap_pct,
    )

    return {"similar_influencers": similar}


@router.post("/overlap/compare-multiple")
async def compare_multiple_audiences(
    influencer_ids: list[int],
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Compare audiences across multiple influencers."""
    if len(influencer_ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 influencers")

    if len(influencer_ids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 influencers allowed")

    service = AudienceOverlapService(db)

    try:
        result = await service.compare_multiple(
            user_id=current_user.id,
            influencer_ids=influencer_ids,
        )
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
