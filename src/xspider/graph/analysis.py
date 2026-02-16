"""Hidden influencer discovery algorithm."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import networkx as nx

from xspider.core import get_logger
from xspider.graph.pagerank import PageRankCalculator, PageRankResult

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


@dataclass(frozen=True)
class HiddenInfluencerResult:
    """Hidden influencer analysis result for a single node."""

    user_id: str
    username: str
    pagerank_score: float
    followers_count: int
    hidden_score: float
    in_degree: int
    out_degree: int
    seed_followers_count: int


class HiddenInfluencerAnalyzer:
    """Discover hidden influencers with high influence but low follower count.

    The hidden score formula: hidden_score = pagerank / log(followers + 2)

    This identifies users who have disproportionate influence relative to
    their public follower count - the "hidden gems" of the network.
    """

    def __init__(
        self,
        pagerank_calculator: PageRankCalculator | None = None,
    ) -> None:
        """Initialize hidden influencer analyzer.

        Args:
            pagerank_calculator: Optional PageRank calculator instance.
        """
        self._pagerank_calculator = pagerank_calculator or PageRankCalculator()

    def analyze(
        self,
        graph: nx.DiGraph,
        pagerank_results: dict[str, PageRankResult] | None = None,
    ) -> dict[str, HiddenInfluencerResult]:
        """Analyze graph to find hidden influencers.

        Args:
            graph: NetworkX directed graph with node attributes.
            pagerank_results: Optional pre-computed PageRank results.

        Returns:
            Dictionary mapping user_id to HiddenInfluencerResult.
        """
        if graph.number_of_nodes() == 0:
            logger.warning("Empty graph provided for hidden influencer analysis")
            return {}

        if pagerank_results is None:
            pagerank_results = self._pagerank_calculator.compute(graph)

        seed_followers = self._count_seed_followers(graph)

        results = {}
        for node_id, pr_result in pagerank_results.items():
            node_data = graph.nodes.get(node_id, {})

            followers_count = node_data.get("followers_count", 0)
            username = node_data.get("username", "")

            hidden_score = self._compute_hidden_score(
                pagerank_score=pr_result.pagerank_score,
                followers_count=followers_count,
            )

            results[node_id] = HiddenInfluencerResult(
                user_id=node_id,
                username=username,
                pagerank_score=pr_result.pagerank_score,
                followers_count=followers_count,
                hidden_score=hidden_score,
                in_degree=pr_result.in_degree,
                out_degree=pr_result.out_degree,
                seed_followers_count=seed_followers.get(node_id, 0),
            )

        logger.info(f"Analyzed {len(results)} nodes for hidden influencers")
        return results

    def _compute_hidden_score(
        self,
        pagerank_score: float,
        followers_count: int,
    ) -> float:
        """Compute hidden influencer score.

        Formula: hidden_score = pagerank / log(followers + 2)

        The +2 ensures:
        - Denominator is always > 0 (log(2) > 0)
        - Users with 0 followers still get a meaningful score
        - Natural logarithm provides smooth scaling

        Args:
            pagerank_score: PageRank score for the user.
            followers_count: Public follower count.

        Returns:
            Hidden influencer score.
        """
        denominator = math.log(followers_count + 2)
        return pagerank_score / denominator

    def _count_seed_followers(self, graph: nx.DiGraph) -> dict[str, int]:
        """Count how many seed users follow each node.

        Args:
            graph: NetworkX directed graph.

        Returns:
            Dictionary mapping user_id to seed follower count.
        """
        seed_ids = {
            node_id
            for node_id, data in graph.nodes(data=True)
            if data.get("is_seed", False)
        }

        counts: dict[str, int] = {}
        for node_id in graph.nodes():
            seed_follower_count = sum(
                1 for pred in graph.predecessors(node_id) if pred in seed_ids
            )
            counts[node_id] = seed_follower_count

        return counts

    def get_top_hidden(
        self,
        results: dict[str, HiddenInfluencerResult],
        k: int = 10,
        min_pagerank: float = 0.0,
        max_followers: int | None = None,
    ) -> list[HiddenInfluencerResult]:
        """Get top k hidden influencers.

        Args:
            results: Hidden influencer results dictionary.
            k: Number of top nodes to return.
            min_pagerank: Minimum PageRank score threshold.
            max_followers: Maximum follower count threshold.

        Returns:
            List of top k HiddenInfluencerResult sorted by hidden_score descending.
        """
        filtered = [
            r
            for r in results.values()
            if r.pagerank_score >= min_pagerank
            and (max_followers is None or r.followers_count <= max_followers)
        ]

        sorted_results = sorted(
            filtered,
            key=lambda r: r.hidden_score,
            reverse=True,
        )

        return sorted_results[:k]

    def get_by_seed_followers(
        self,
        results: dict[str, HiddenInfluencerResult],
        min_seed_followers: int = 1,
        k: int = 10,
    ) -> list[HiddenInfluencerResult]:
        """Get top hidden influencers followed by multiple seeds.

        Args:
            results: Hidden influencer results dictionary.
            min_seed_followers: Minimum number of seed followers.
            k: Number of top nodes to return.

        Returns:
            List of top k HiddenInfluencerResult filtered and sorted.
        """
        filtered = [
            r for r in results.values() if r.seed_followers_count >= min_seed_followers
        ]

        sorted_results = sorted(
            filtered,
            key=lambda r: (r.seed_followers_count, r.hidden_score),
            reverse=True,
        )

        return sorted_results[:k]

    def categorize_influencers(
        self,
        results: dict[str, HiddenInfluencerResult],
        hidden_threshold_percentile: float = 90,
        pagerank_threshold_percentile: float = 90,
    ) -> dict[str, list[HiddenInfluencerResult]]:
        """Categorize influencers into different types.

        Categories:
        - hidden_gems: High hidden score, low followers
        - established: High PageRank, high followers
        - rising_stars: High PageRank, moderate followers
        - potential: Moderate scores, worth watching

        Args:
            results: Hidden influencer results dictionary.
            hidden_threshold_percentile: Percentile for hidden score threshold.
            pagerank_threshold_percentile: Percentile for PageRank threshold.

        Returns:
            Dictionary mapping category name to list of results.
        """
        if not results:
            return {
                "hidden_gems": [],
                "established": [],
                "rising_stars": [],
                "potential": [],
            }

        hidden_scores = sorted(r.hidden_score for r in results.values())
        pagerank_scores = sorted(r.pagerank_score for r in results.values())

        hidden_idx = int(len(hidden_scores) * hidden_threshold_percentile / 100)
        pagerank_idx = int(len(pagerank_scores) * pagerank_threshold_percentile / 100)

        hidden_threshold = hidden_scores[min(hidden_idx, len(hidden_scores) - 1)]
        pagerank_threshold = pagerank_scores[min(pagerank_idx, len(pagerank_scores) - 1)]

        median_followers = sorted(r.followers_count for r in results.values())[
            len(results) // 2
        ]

        categories: dict[str, list[HiddenInfluencerResult]] = {
            "hidden_gems": [],
            "established": [],
            "rising_stars": [],
            "potential": [],
        }

        for result in results.values():
            if result.hidden_score >= hidden_threshold and result.followers_count < median_followers:
                categories["hidden_gems"].append(result)
            elif result.pagerank_score >= pagerank_threshold and result.followers_count >= median_followers:
                categories["established"].append(result)
            elif result.pagerank_score >= pagerank_threshold:
                categories["rising_stars"].append(result)
            elif result.hidden_score >= hidden_threshold * 0.5:
                categories["potential"].append(result)

        for category in categories:
            categories[category].sort(key=lambda r: r.hidden_score, reverse=True)

        return categories
