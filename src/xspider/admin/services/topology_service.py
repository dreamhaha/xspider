"""Social Network Topology Service (社交网络拓扑服务)."""

from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.admin.models import (
    DiscoveredInfluencer,
    MonitoredInfluencer,
    UserSearch,
)
from xspider.core.logging import get_logger

logger = get_logger(__name__)


class TopologyService:
    """
    Service for generating social network topology data.

    Creates interactive network graph data with:
    - PageRank-based node sizing
    - Community detection coloring
    - Follow relationship edges
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_search_topology(
        self,
        search_id: int,
        user_id: int,
        max_nodes: int = 100,
        min_pagerank: float = 0.0,
    ) -> dict[str, Any]:
        """
        Get network topology for a search result.

        Returns D3.js compatible graph data with nodes and edges.
        """
        # Get search
        search_result = await self.db.execute(
            select(UserSearch).where(
                UserSearch.id == search_id,
                UserSearch.user_id == user_id,
            )
        )
        search = search_result.scalar_one_or_none()

        if not search:
            raise ValueError(f"Search {search_id} not found")

        # Get influencers from this search
        query = (
            select(DiscoveredInfluencer)
            .where(DiscoveredInfluencer.search_id == search_id)
            .order_by(DiscoveredInfluencer.pagerank_score.desc())
        )

        if min_pagerank > 0:
            query = query.where(DiscoveredInfluencer.pagerank_score >= min_pagerank)

        query = query.limit(max_nodes)

        result = await self.db.execute(query)
        influencers = list(result.scalars().all())

        # Build nodes
        nodes = []
        node_map = {}  # twitter_user_id -> node index

        for i, inf in enumerate(influencers):
            node_map[inf.twitter_user_id] = i

            # Calculate node size based on PageRank
            size = self._calculate_node_size(inf.pagerank_score)

            # Determine node color based on relevance
            color = self._get_relevance_color(inf.relevance_score)

            nodes.append({
                "id": inf.twitter_user_id,
                "label": inf.screen_name,
                "name": inf.name,
                "size": size,
                "color": color,
                "pagerank": inf.pagerank_score,
                "hidden_score": inf.hidden_score,
                "followers_count": inf.followers_count,
                "relevance_score": inf.relevance_score,
                "is_relevant": inf.is_relevant,
            })

        # Build edges (from following relationships stored during crawl)
        edges = await self._build_edges(influencers, node_map)

        return {
            "search_id": search_id,
            "keywords": search.keywords,
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "max_pagerank": max(n["pagerank"] for n in nodes) if nodes else 0,
                "relevant_nodes": sum(1 for n in nodes if n.get("is_relevant")),
            },
        }

    async def get_monitored_topology(
        self,
        user_id: int,
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        """
        Get network topology for monitored influencers.

        Shows relationships between monitored accounts.
        """
        # Get monitored influencers
        result = await self.db.execute(
            select(MonitoredInfluencer)
            .where(MonitoredInfluencer.user_id == user_id)
            .order_by(MonitoredInfluencer.followers_count.desc())
            .limit(max_nodes)
        )
        influencers = list(result.scalars().all())

        if not influencers:
            return {"nodes": [], "edges": [], "stats": {}}

        nodes = []
        node_map = {}

        for i, inf in enumerate(influencers):
            node_map[inf.twitter_user_id] = i

            # Size based on followers
            size = self._calculate_follower_size(inf.followers_count)

            # Color based on status
            color = self._get_status_color(inf.status.value if inf.status else "unknown")

            nodes.append({
                "id": inf.twitter_user_id,
                "label": inf.screen_name,
                "name": inf.display_name,
                "size": size,
                "color": color,
                "followers_count": inf.followers_count,
                "status": inf.status.value if inf.status else None,
            })

        # Build edges based on audience overlap analyses
        edges = await self._build_overlap_edges(user_id, node_map)

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
            },
        }

    async def _build_edges(
        self,
        influencers: list[DiscoveredInfluencer],
        node_map: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Build edges from following relationships."""
        edges = []
        seen = set()

        for inf in influencers:
            if not inf.following_ids:
                continue

            try:
                following = json.loads(inf.following_ids)
            except json.JSONDecodeError:
                continue

            for follow_id in following:
                if follow_id in node_map and inf.twitter_user_id in node_map:
                    # Create edge key to avoid duplicates
                    edge_key = tuple(sorted([inf.twitter_user_id, follow_id]))
                    if edge_key not in seen:
                        seen.add(edge_key)
                        edges.append({
                            "source": inf.twitter_user_id,
                            "target": follow_id,
                            "type": "follows",
                        })

        return edges

    async def _build_overlap_edges(
        self,
        user_id: int,
        node_map: dict[str, int],
    ) -> list[dict[str, Any]]:
        """Build edges based on audience overlap data."""
        from xspider.admin.models import AudienceOverlapAnalysis

        result = await self.db.execute(
            select(AudienceOverlapAnalysis).where(
                AudienceOverlapAnalysis.user_id == user_id
            )
        )
        analyses = list(result.scalars().all())

        edges = []
        seen = set()

        # Get twitter_user_ids for monitored influencers
        inf_result = await self.db.execute(
            select(MonitoredInfluencer).where(
                MonitoredInfluencer.user_id == user_id
            )
        )
        influencers = {i.id: i.twitter_user_id for i in inf_result.scalars().all()}

        for analysis in analyses:
            source_id = influencers.get(analysis.influencer_a_id)
            target_id = influencers.get(analysis.influencer_b_id)

            if source_id in node_map and target_id in node_map:
                edge_key = tuple(sorted([source_id, target_id]))
                if edge_key not in seen:
                    seen.add(edge_key)

                    # Edge thickness based on Jaccard index
                    weight = min(10, max(1, analysis.jaccard_index * 20))

                    edges.append({
                        "source": source_id,
                        "target": target_id,
                        "type": "overlap",
                        "weight": weight,
                        "jaccard": analysis.jaccard_index,
                        "overlap_count": analysis.overlap_count,
                    })

        return edges

    def _calculate_node_size(self, pagerank: float) -> float:
        """Calculate node size based on PageRank score."""
        # Log scale to handle large variations
        if pagerank <= 0:
            return 5
        return min(50, max(5, 5 + math.log10(pagerank * 10000 + 1) * 10))

    def _calculate_follower_size(self, followers: int) -> float:
        """Calculate node size based on followers."""
        if followers <= 0:
            return 5
        return min(50, max(5, 5 + math.log10(followers + 1) * 5))

    def _get_relevance_color(self, relevance_score: int | None) -> str:
        """Get node color based on relevance score."""
        if relevance_score is None:
            return "#808080"  # Gray for unscored
        if relevance_score >= 80:
            return "#22c55e"  # Green for highly relevant
        if relevance_score >= 60:
            return "#84cc16"  # Lime
        if relevance_score >= 40:
            return "#eab308"  # Yellow
        if relevance_score >= 20:
            return "#f97316"  # Orange
        return "#ef4444"  # Red for low relevance

    def _get_status_color(self, status: str) -> str:
        """Get node color based on monitor status."""
        colors = {
            "active": "#22c55e",
            "paused": "#eab308",
            "error": "#ef4444",
            "completed": "#3b82f6",
        }
        return colors.get(status, "#808080")

    async def export_graph_data(
        self,
        search_id: int | None = None,
        user_id: int = 0,
        format: str = "json",
    ) -> dict[str, Any] | str:
        """
        Export graph data in various formats.

        Supports:
        - json: Standard JSON format
        - gephi: Gephi-compatible format
        - cytoscape: Cytoscape.js format
        """
        if search_id:
            data = await self.get_search_topology(search_id, user_id)
        else:
            data = await self.get_monitored_topology(user_id)

        if format == "json":
            return data

        if format == "gephi":
            return self._to_gephi_format(data)

        if format == "cytoscape":
            return self._to_cytoscape_format(data)

        return data

    def _to_gephi_format(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert to Gephi-compatible GEXF-like format."""
        return {
            "graph": {
                "mode": "static",
                "defaultedgetype": "directed",
                "nodes": [
                    {
                        "id": n["id"],
                        "label": n["label"],
                        "attvalues": {
                            "size": n.get("size", 10),
                            "pagerank": n.get("pagerank", 0),
                            "followers": n.get("followers_count", 0),
                        },
                    }
                    for n in data.get("nodes", [])
                ],
                "edges": [
                    {
                        "id": f"{e['source']}-{e['target']}",
                        "source": e["source"],
                        "target": e["target"],
                        "weight": e.get("weight", 1),
                    }
                    for e in data.get("edges", [])
                ],
            }
        }

    def _to_cytoscape_format(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert to Cytoscape.js format."""
        elements = []

        # Add nodes
        for n in data.get("nodes", []):
            elements.append({
                "group": "nodes",
                "data": {
                    "id": n["id"],
                    "label": n["label"],
                    "size": n.get("size", 10),
                    "color": n.get("color", "#808080"),
                },
            })

        # Add edges
        for e in data.get("edges", []):
            elements.append({
                "group": "edges",
                "data": {
                    "id": f"{e['source']}-{e['target']}",
                    "source": e["source"],
                    "target": e["target"],
                    "weight": e.get("weight", 1),
                },
            })

        return {"elements": elements}
