"""PageRank calculation for influence scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx

from xspider.core import GraphError, get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass(frozen=True)
class PageRankResult:
    """PageRank computation result for a single node."""

    user_id: str
    pagerank_score: float
    in_degree: int
    out_degree: int


class PageRankCalculator:
    """Calculate PageRank scores for graph nodes."""

    DEFAULT_ALPHA = 0.85
    DEFAULT_MAX_ITER = 100
    DEFAULT_TOL = 1e-06

    def __init__(
        self,
        alpha: float = DEFAULT_ALPHA,
        max_iter: int = DEFAULT_MAX_ITER,
        tol: float = DEFAULT_TOL,
    ) -> None:
        """Initialize PageRank calculator.

        Args:
            alpha: Damping parameter (probability of following link).
            max_iter: Maximum number of iterations.
            tol: Convergence tolerance.
        """
        self._alpha = alpha
        self._max_iter = max_iter
        self._tol = tol

    def compute(self, graph: nx.DiGraph) -> dict[str, PageRankResult]:
        """Compute PageRank for all nodes in the graph.

        Args:
            graph: NetworkX directed graph.

        Returns:
            Dictionary mapping user_id to PageRankResult.

        Raises:
            GraphError: If PageRank computation fails.
        """
        if graph.number_of_nodes() == 0:
            logger.warning("Empty graph provided for PageRank computation")
            return {}

        try:
            pagerank_scores = nx.pagerank(
                graph,
                alpha=self._alpha,
                max_iter=self._max_iter,
                tol=self._tol,
            )

            results = {}
            for node_id, score in pagerank_scores.items():
                results[node_id] = PageRankResult(
                    user_id=node_id,
                    pagerank_score=score,
                    in_degree=graph.in_degree(node_id),
                    out_degree=graph.out_degree(node_id),
                )

            logger.info(f"Computed PageRank for {len(results)} nodes")
            return results

        except nx.PowerIterationFailedConvergence as e:
            logger.error(f"PageRank failed to converge: {e}")
            raise GraphError(
                f"PageRank failed to converge after {self._max_iter} iterations",
                node_count=graph.number_of_nodes(),
                edge_count=graph.number_of_edges(),
            ) from e
        except Exception as e:
            logger.error(f"PageRank computation failed: {e}")
            raise GraphError(
                f"PageRank computation failed: {e}",
                node_count=graph.number_of_nodes(),
                edge_count=graph.number_of_edges(),
            ) from e

    def get_top_k(
        self,
        results: dict[str, PageRankResult],
        k: int = 10,
    ) -> list[PageRankResult]:
        """Get top k nodes by PageRank score.

        Args:
            results: PageRank results dictionary.
            k: Number of top nodes to return.

        Returns:
            List of top k PageRankResult sorted by score descending.
        """
        sorted_results = sorted(
            results.values(),
            key=lambda r: r.pagerank_score,
            reverse=True,
        )
        return sorted_results[:k]

    def normalize_scores(
        self,
        results: dict[str, PageRankResult],
    ) -> dict[str, PageRankResult]:
        """Normalize PageRank scores to range [0, 1].

        Args:
            results: PageRank results dictionary.

        Returns:
            New dictionary with normalized scores.
        """
        if not results:
            return {}

        max_score = max(r.pagerank_score for r in results.values())
        min_score = min(r.pagerank_score for r in results.values())
        score_range = max_score - min_score

        if score_range == 0:
            return {
                user_id: PageRankResult(
                    user_id=r.user_id,
                    pagerank_score=1.0,
                    in_degree=r.in_degree,
                    out_degree=r.out_degree,
                )
                for user_id, r in results.items()
            }

        return {
            user_id: PageRankResult(
                user_id=r.user_id,
                pagerank_score=(r.pagerank_score - min_score) / score_range,
                in_degree=r.in_degree,
                out_degree=r.out_degree,
            )
            for user_id, r in results.items()
        }
