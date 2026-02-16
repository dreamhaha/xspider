"""Network Topology Routes (网络拓扑路由)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.auth import get_current_active_user, get_db_session
from xspider.admin.models import AdminUser
from xspider.admin.services.topology_service import TopologyService

router = APIRouter(prefix="/topology", tags=["Topology"])


@router.get("/search/{search_id}")
async def get_search_topology(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    max_nodes: int = Query(100, ge=10, le=500),
    min_pagerank: float = Query(0.0, ge=0.0),
) -> dict[str, Any]:
    """
    Get network topology for a search result.

    Returns D3.js compatible graph data with nodes and edges.
    Nodes are sized by PageRank and colored by relevance.
    """
    service = TopologyService(db)

    try:
        return await service.get_search_topology(
            search_id=search_id,
            user_id=current_user.id,
            max_nodes=max_nodes,
            min_pagerank=min_pagerank,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/monitored")
async def get_monitored_topology(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    max_nodes: int = Query(50, ge=10, le=200),
) -> dict[str, Any]:
    """
    Get network topology for monitored influencers.

    Shows relationships between monitored accounts based on
    audience overlap analysis.
    """
    service = TopologyService(db)

    return await service.get_monitored_topology(
        user_id=current_user.id,
        max_nodes=max_nodes,
    )


@router.get("/export/{search_id}")
async def export_topology(
    search_id: int,
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    format: str = Query("json", pattern="^(json|gephi|cytoscape)$"),
) -> JSONResponse:
    """
    Export topology data in various formats.

    Supported formats:
    - json: Standard JSON (D3.js compatible)
    - gephi: Gephi-compatible GEXF-like format
    - cytoscape: Cytoscape.js elements format
    """
    service = TopologyService(db)

    try:
        data = await service.export_graph_data(
            search_id=search_id,
            user_id=current_user.id,
            format=format,
        )

        filename = f"topology_{search_id}.{format}.json"

        return JSONResponse(
            content=data,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/export/monitored")
async def export_monitored_topology(
    current_user: Annotated[AdminUser, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    format: str = Query("json", pattern="^(json|gephi|cytoscape)$"),
) -> JSONResponse:
    """Export monitored influencer topology."""
    service = TopologyService(db)

    data = await service.export_graph_data(
        search_id=None,
        user_id=current_user.id,
        format=format,
    )

    filename = f"monitored_topology.{format}.json"

    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        },
    )
