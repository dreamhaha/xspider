"""Build NetworkX graph from database."""

from __future__ import annotations

from typing import TYPE_CHECKING

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from xspider.core import GraphError, get_logger
from xspider.storage import Database, Edge, User

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger(__name__)


class GraphBuilder:
    """Build directed graph from database edges."""

    def __init__(self, database: Database) -> None:
        """Initialize graph builder.

        Args:
            database: Database instance for loading edges.
        """
        self._database = database

    async def build_graph(self) -> nx.DiGraph:
        """Build a directed graph from all edges in the database.

        Returns:
            NetworkX DiGraph with users as nodes and follows as edges.

        Raises:
            GraphError: If graph construction fails.
        """
        try:
            async with self._database.session() as session:
                return await self._build_from_session(session)
        except Exception as e:
            logger.error(f"Failed to build graph: {e}")
            raise GraphError(f"Failed to build graph: {e}") from e

    async def _build_from_session(self, session: AsyncSession) -> nx.DiGraph:
        """Build graph from an active session.

        Args:
            session: Active database session.

        Returns:
            NetworkX DiGraph.
        """
        graph = nx.DiGraph()

        users = await self._load_users(session)
        edges = await self._load_edges(session)

        for user in users:
            graph.add_node(
                user.id,
                username=user.username,
                display_name=user.display_name,
                followers_count=user.followers_count,
                following_count=user.following_count,
                is_seed=user.is_seed,
                depth=user.depth,
            )

        for edge in edges:
            graph.add_edge(edge.source_id, edge.target_id)

        logger.info(
            f"Built graph with {graph.number_of_nodes()} nodes "
            f"and {graph.number_of_edges()} edges"
        )

        return graph

    async def _load_users(self, session: AsyncSession) -> Sequence[User]:
        """Load all users from database.

        Args:
            session: Active database session.

        Returns:
            List of User objects.
        """
        result = await session.execute(select(User))
        return result.scalars().all()

    async def _load_edges(self, session: AsyncSession) -> Sequence[Edge]:
        """Load all edges from database.

        Args:
            session: Active database session.

        Returns:
            List of Edge objects.
        """
        result = await session.execute(select(Edge))
        return result.scalars().all()

    async def build_subgraph(
        self,
        user_ids: list[str],
        include_neighbors: bool = True,
    ) -> nx.DiGraph:
        """Build a subgraph containing only specified users.

        Args:
            user_ids: List of user IDs to include.
            include_neighbors: Whether to include direct neighbors.

        Returns:
            NetworkX DiGraph subgraph.

        Raises:
            GraphError: If subgraph construction fails.
        """
        try:
            full_graph = await self.build_graph()

            if not include_neighbors:
                return full_graph.subgraph(user_ids).copy()

            neighbor_ids: set[str] = set(user_ids)
            for user_id in user_ids:
                if user_id in full_graph:
                    neighbor_ids.update(full_graph.predecessors(user_id))
                    neighbor_ids.update(full_graph.successors(user_id))

            return full_graph.subgraph(neighbor_ids).copy()

        except GraphError:
            raise
        except Exception as e:
            logger.error(f"Failed to build subgraph: {e}")
            raise GraphError(f"Failed to build subgraph: {e}") from e

    async def get_graph_stats(self) -> dict[str, int | float]:
        """Get basic statistics about the graph.

        Returns:
            Dictionary with graph statistics.
        """
        graph = await self.build_graph()

        stats = {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "density": nx.density(graph) if graph.number_of_nodes() > 0 else 0.0,
        }

        if graph.number_of_nodes() > 0:
            in_degrees = [d for _, d in graph.in_degree()]
            out_degrees = [d for _, d in graph.out_degree()]

            stats["avg_in_degree"] = sum(in_degrees) / len(in_degrees)
            stats["avg_out_degree"] = sum(out_degrees) / len(out_degrees)
            stats["max_in_degree"] = max(in_degrees)
            stats["max_out_degree"] = max(out_degrees)

        return stats
