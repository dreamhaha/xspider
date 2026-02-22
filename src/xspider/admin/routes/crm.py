"""CRM and Sales Funnel Routes (销售漏斗路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession


class StageUpdateRequest(BaseModel):
    """Request body for updating lead stage."""

    stage: str

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser, LeadStage, IntentLabel
from xspider.admin.services import CRMService

router = APIRouter(prefix="/crm", tags=["CRM"])


# ==================== Lead CRUD ====================


@router.post("/leads/")
async def create_lead(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    twitter_handle: str = Query(..., description="Twitter handle"),
    source: str | None = None,
    tags: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Create a new lead manually."""
    service = CRMService(db)

    try:
        lead = await service.create_lead(
            user_id=current_user.id,
            twitter_handle=twitter_handle,
            source=source,
            tags=tags or [],
            notes=notes,
        )
        return {
            "success": True,
            "lead": {
                "id": lead.id,
                "twitter_handle": lead.screen_name,
                "stage": lead.stage.value,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/leads/")
async def list_leads(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    stage: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    """List all leads."""
    service = CRMService(db)

    stage_filter = None
    if stage:
        try:
            stage_filter = LeadStage(stage)
        except ValueError:
            pass

    leads, total = await service.get_leads_by_stage(
        user_id=current_user.id,
        stage=stage_filter,
        page=page,
        page_size=page_size,
    )

    return {
        "leads": [
            {
                "id": lead.id,
                "twitter_handle": lead.screen_name,
                "name": lead.display_name,
                "profile_image_url": lead.profile_image_url,
                "stage": lead.stage.value,
                "tags": lead.tags or [],
                "last_activity_at": lead.stage_updated_at.isoformat() if lead.stage_updated_at else None,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
            }
            for lead in leads
        ],
        "total": total,
    }


@router.get("/leads/{lead_id}")
async def get_lead_detail(
    lead_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get detailed information about a lead."""
    service = CRMService(db)

    lead = await service.get_lead_by_id(lead_id, current_user.id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    activities = await service.get_lead_activities(lead_id, limit=10)

    return {
        "id": lead.id,
        "twitter_handle": lead.screen_name,
        "name": lead.display_name,
        "profile_image_url": lead.profile_image_url,
        "bio": lead.bio,
        "followers_count": lead.followers_count,
        "stage": lead.stage.value,
        "tags": lead.tags or [],
        "notes": lead.notes,
        "activities": [
            {
                "id": a.id,
                "type": a.activity_type,
                "note": a.description,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ],
    }


@router.get("/kanban")
async def get_kanban_board(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get leads organized by stage for kanban board."""
    service = CRMService(db)
    board = await service.get_kanban_board(current_user.id)

    # Convert to serializable format
    result = {}
    for stage, leads in board.items():
        result[stage] = [
            {
                "id": lead.id,
                "screen_name": lead.screen_name,
                "display_name": lead.display_name,
                "bio": lead.bio[:100] + "..." if lead.bio and len(lead.bio) > 100 else lead.bio,
                "profile_image_url": lead.profile_image_url,
                "followers_count": lead.followers_count,
                "intent_score": lead.intent_score,
                "intent_label": lead.intent_label.value if lead.intent_label else None,
                "dm_status": lead.dm_status.value if lead.dm_status else None,
                "stage_updated_at": lead.stage_updated_at.isoformat() if lead.stage_updated_at else None,
                "opener_generated": lead.opener_generated,
                "source_influencer": lead.source_influencer,
            }
            for lead in leads
        ]

    return {"board": result}


@router.get("/kanban/stats")
async def get_kanban_stats(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Get kanban board statistics."""
    service = CRMService(db)
    return await service.get_kanban_stats(current_user.id)


@router.get("/leads")
async def get_leads(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    stage: LeadStage | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    """Get leads with optional stage filter."""
    service = CRMService(db)
    leads, total = await service.get_leads_by_stage(
        user_id=current_user.id,
        stage=stage,
        page=page,
        page_size=page_size,
    )

    return {
        "leads": [
            {
                "id": lead.id,
                "screen_name": lead.screen_name,
                "display_name": lead.display_name,
                "bio": lead.bio,
                "profile_image_url": lead.profile_image_url,
                "followers_count": lead.followers_count,
                "intent_score": lead.intent_score,
                "intent_label": lead.intent_label.value if lead.intent_label else None,
                "dm_status": lead.dm_status.value if lead.dm_status else None,
                "stage": lead.stage.value,
                "notes": lead.notes,
                "tags": lead.tags,
                "opener_generated": lead.opener_generated,
                "opener_text": lead.opener_text,
                "source_influencer": lead.source_influencer,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
            }
            for lead in leads
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/leads/search")
async def search_leads(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    query: str | None = None,
    stages: str | None = None,  # Comma-separated
    intent_labels: str | None = None,  # Comma-separated
    min_intent_score: float | None = None,
    dm_available_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> dict[str, Any]:
    """Search leads with multiple filters."""
    service = CRMService(db)

    # Parse comma-separated values
    stage_list = None
    if stages:
        stage_list = [LeadStage(s.strip()) for s in stages.split(",")]

    intent_list = None
    if intent_labels:
        intent_list = [IntentLabel(i.strip()) for i in intent_labels.split(",")]

    leads, total = await service.search_leads(
        user_id=current_user.id,
        query=query,
        stages=stage_list,
        intent_labels=intent_list,
        min_intent_score=min_intent_score,
        dm_available_only=dm_available_only,
        page=page,
        page_size=page_size,
    )

    return {
        "leads": [
            {
                "id": lead.id,
                "screen_name": lead.screen_name,
                "display_name": lead.display_name,
                "intent_score": lead.intent_score,
                "stage": lead.stage.value,
                "dm_status": lead.dm_status.value if lead.dm_status else None,
            }
            for lead in leads
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put("/leads/{lead_id}/stage")
async def update_lead_stage(
    lead_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    body: StageUpdateRequest | None = Body(None),
    new_stage: LeadStage | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update a lead's stage. Accepts stage in body or query param."""
    service = CRMService(db)

    # Get stage from body or query
    stage_str = body.stage if body else None
    if not stage_str and new_stage:
        stage_str = new_stage.value
    if not stage_str:
        raise HTTPException(status_code=400, detail="Stage is required")

    try:
        stage = LeadStage(stage_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {stage_str}")

    try:
        lead = await service.update_lead_stage(
            lead_id=lead_id,
            user_id=current_user.id,
            new_stage=stage,
            notes=notes,
        )
        return {
            "success": True,
            "lead": {
                "id": lead.id,
                "stage": lead.stage.value,
                "stage_updated_at": lead.stage_updated_at.isoformat() if lead.stage_updated_at else None,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/leads/{lead_id}/note")
async def add_lead_note(
    lead_id: int,
    note: str,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Add a note to a lead."""
    service = CRMService(db)

    try:
        lead = await service.add_lead_note(
            lead_id=lead_id,
            user_id=current_user.id,
            note=note,
        )
        return {"success": True, "notes": lead.notes}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/leads/{lead_id}/tags")
async def update_lead_tags(
    lead_id: int,
    tags: list[str],
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Update tags for a lead."""
    service = CRMService(db)

    try:
        lead = await service.update_lead_tags(
            lead_id=lead_id,
            user_id=current_user.id,
            tags=tags,
        )
        return {"success": True, "tags": lead.tags}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/leads/{lead_id}/activities")
async def get_lead_activities(
    lead_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Get activity history for a lead."""
    service = CRMService(db)
    activities = await service.get_lead_activities(lead_id, limit=limit)

    return {
        "activities": [
            {
                "id": a.id,
                "activity_type": a.activity_type,
                "old_value": a.old_value,
                "new_value": a.new_value,
                "description": a.description,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ]
    }


@router.post("/convert-commenters/{tweet_id}")
async def bulk_convert_commenters(
    tweet_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    min_authenticity_score: float = 50.0,
    only_real_users: bool = True,
    only_dm_available: bool = False,
) -> dict[str, Any]:
    """Convert qualifying commenters from a tweet to leads."""
    service = CRMService(db)

    count = await service.bulk_convert_to_leads(
        user_id=current_user.id,
        tweet_id=tweet_id,
        min_authenticity_score=min_authenticity_score,
        only_real_users=only_real_users,
        only_dm_available=only_dm_available,
    )

    return {"success": True, "leads_created": count}
