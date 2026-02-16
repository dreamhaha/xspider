"""Ranking results persistence to database."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert

from xspider.core import GraphError, get_logger
from xspider.graph.analysis import HiddenInfluencerResult
from xspider.graph.pagerank import PageRankResult
from xspider.storage import Database, Ranking

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = get_logger(__name__)


class RankingStorage:
    """Persist ranking results to database."""

    def __init__(self, database: Database) -> None:
        """Initialize ranking storage.

        Args:
            database: Database instance for persistence.
        """
        self._database = database

    async def save_pagerank_results(
        self,
        results: dict[str, PageRankResult],
        batch_size: int = 1000,
    ) -> int:
        """Save PageRank results to database.

        Args:
            results: Dictionary mapping user_id to PageRankResult.
            batch_size: Number of records to insert per batch.

        Returns:
            Number of records saved.

        Raises:
            GraphError: If save operation fails.
        """
        if not results:
            logger.warning("No PageRank results to save")
            return 0

        try:
            async with self._database.session() as session:
                saved_count = 0
                result_items = list(results.items())

                for i in range(0, len(result_items), batch_size):
                    batch = result_items[i : i + batch_size]
                    values = [
                        {
                            "user_id": user_id,
                            "pagerank_score": pr_result.pagerank_score,
                            "in_degree": pr_result.in_degree,
                            "out_degree": pr_result.out_degree,
                            "hidden_score": 0.0,
                            "seed_followers_count": 0,
                            "computed_at": datetime.utcnow(),
                        }
                        for user_id, pr_result in batch
                    ]

                    stmt = insert(Ranking).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["user_id"],
                        set_={
                            "pagerank_score": stmt.excluded.pagerank_score,
                            "in_degree": stmt.excluded.in_degree,
                            "out_degree": stmt.excluded.out_degree,
                            "computed_at": stmt.excluded.computed_at,
                        },
                    )
                    await session.execute(stmt)
                    saved_count += len(batch)

                logger.info(f"Saved {saved_count} PageRank results")
                return saved_count

        except Exception as e:
            logger.error(f"Failed to save PageRank results: {e}")
            raise GraphError(f"Failed to save PageRank results: {e}") from e

    async def save_hidden_influencer_results(
        self,
        results: dict[str, HiddenInfluencerResult],
        batch_size: int = 1000,
    ) -> int:
        """Save hidden influencer results to database.

        Args:
            results: Dictionary mapping user_id to HiddenInfluencerResult.
            batch_size: Number of records to insert per batch.

        Returns:
            Number of records saved.

        Raises:
            GraphError: If save operation fails.
        """
        if not results:
            logger.warning("No hidden influencer results to save")
            return 0

        try:
            async with self._database.session() as session:
                saved_count = 0
                result_items = list(results.items())

                for i in range(0, len(result_items), batch_size):
                    batch = result_items[i : i + batch_size]
                    values = [
                        {
                            "user_id": user_id,
                            "pagerank_score": hi_result.pagerank_score,
                            "in_degree": hi_result.in_degree,
                            "out_degree": hi_result.out_degree,
                            "hidden_score": hi_result.hidden_score,
                            "seed_followers_count": hi_result.seed_followers_count,
                            "computed_at": datetime.utcnow(),
                        }
                        for user_id, hi_result in batch
                    ]

                    stmt = insert(Ranking).values(values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["user_id"],
                        set_={
                            "pagerank_score": stmt.excluded.pagerank_score,
                            "in_degree": stmt.excluded.in_degree,
                            "out_degree": stmt.excluded.out_degree,
                            "hidden_score": stmt.excluded.hidden_score,
                            "seed_followers_count": stmt.excluded.seed_followers_count,
                            "computed_at": stmt.excluded.computed_at,
                        },
                    )
                    await session.execute(stmt)
                    saved_count += len(batch)

                logger.info(f"Saved {saved_count} hidden influencer results")
                return saved_count

        except Exception as e:
            logger.error(f"Failed to save hidden influencer results: {e}")
            raise GraphError(f"Failed to save hidden influencer results: {e}") from e

    async def get_top_by_pagerank(
        self,
        limit: int = 100,
        min_in_degree: int = 0,
    ) -> Sequence[Ranking]:
        """Get top users by PageRank score.

        Args:
            limit: Maximum number of results.
            min_in_degree: Minimum in-degree filter.

        Returns:
            List of Ranking objects sorted by PageRank descending.
        """
        async with self._database.session() as session:
            stmt = (
                select(Ranking)
                .where(Ranking.in_degree >= min_in_degree)
                .order_by(Ranking.pagerank_score.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_top_by_hidden_score(
        self,
        limit: int = 100,
        max_followers: int | None = None,
    ) -> Sequence[Ranking]:
        """Get top users by hidden influencer score.

        Args:
            limit: Maximum number of results.
            max_followers: Maximum follower count filter (requires join).

        Returns:
            List of Ranking objects sorted by hidden score descending.
        """
        async with self._database.session() as session:
            stmt = (
                select(Ranking)
                .where(Ranking.hidden_score > 0)
                .order_by(Ranking.hidden_score.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_by_seed_followers(
        self,
        min_seed_followers: int = 1,
        limit: int = 100,
    ) -> Sequence[Ranking]:
        """Get users followed by multiple seed users.

        Args:
            min_seed_followers: Minimum seed follower count.
            limit: Maximum number of results.

        Returns:
            List of Ranking objects sorted by seed followers descending.
        """
        async with self._database.session() as session:
            stmt = (
                select(Ranking)
                .where(Ranking.seed_followers_count >= min_seed_followers)
                .order_by(
                    Ranking.seed_followers_count.desc(),
                    Ranking.hidden_score.desc(),
                )
                .limit(limit)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def clear_rankings(self) -> int:
        """Clear all ranking data.

        Returns:
            Number of records deleted.
        """
        async with self._database.session() as session:
            result = await session.execute(delete(Ranking))
            deleted_count = result.rowcount
            logger.info(f"Cleared {deleted_count} ranking records")
            return deleted_count

    async def get_ranking_stats(self) -> dict[str, float | int]:
        """Get statistics about stored rankings.

        Returns:
            Dictionary with ranking statistics.
        """
        async with self._database.session() as session:
            result = await session.execute(select(Ranking))
            rankings = result.scalars().all()

            if not rankings:
                return {
                    "total_count": 0,
                    "avg_pagerank": 0.0,
                    "max_pagerank": 0.0,
                    "avg_hidden_score": 0.0,
                    "max_hidden_score": 0.0,
                    "avg_in_degree": 0.0,
                    "max_in_degree": 0,
                }

            pagerank_scores = [r.pagerank_score for r in rankings]
            hidden_scores = [r.hidden_score for r in rankings]
            in_degrees = [r.in_degree for r in rankings]

            return {
                "total_count": len(rankings),
                "avg_pagerank": sum(pagerank_scores) / len(pagerank_scores),
                "max_pagerank": max(pagerank_scores),
                "avg_hidden_score": sum(hidden_scores) / len(hidden_scores),
                "max_hidden_score": max(hidden_scores),
                "avg_in_degree": sum(in_degrees) / len(in_degrees),
                "max_in_degree": max(in_degrees),
            }
