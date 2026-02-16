"""BFS Following scraper with depth limiting."""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from xspider.core import ScrapingError, get_logger
from xspider.storage import Database, Edge, User
from xspider.twitter import TwitterGraphQLClient as TwitterClient, TwitterUser


class BFSState(str, Enum):
    """BFS traversal state."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BFSNode:
    """Node in the BFS queue."""

    user_id: str
    username: str
    depth: int
    state: BFSState = BFSState.PENDING


@dataclass
class BFSProgress:
    """Progress update for BFS traversal."""

    current_user_id: str
    current_username: str
    current_depth: int
    queue_size: int
    visited_count: int
    edges_found: int
    total_edges: int


@dataclass
class BFSResult:
    """Result of a BFS traversal."""

    users_visited: int
    edges_discovered: int
    max_depth_reached: int
    errors: list[str] = field(default_factory=list)


ProgressCallback = Callable[[BFSProgress], None]


class FollowingScraper:
    """BFS crawler for following relationships.

    Performs breadth-first traversal starting from seed users,
    discovering and storing follow edges up to a specified depth.

    Usage:
        async with FollowingScraper(client, db) as scraper:
            result = await scraper.crawl_from_seeds(
                seed_ids=["123", "456"],
                max_depth=2,
            )
    """

    def __init__(
        self,
        client: TwitterClient,
        database: Database,
        *,
        progress_callback: ProgressCallback | None = None,
        batch_size: int = 100,
    ) -> None:
        """Initialize the following scraper.

        Args:
            client: Twitter API client instance.
            database: Database instance for persistence.
            progress_callback: Optional callback for progress updates.
            batch_size: Number of edges to batch before committing.
        """
        self._client = client
        self._database = database
        self._progress_callback = progress_callback
        self._batch_size = batch_size
        self._logger = get_logger(__name__)

        # BFS state
        self._queue: deque[BFSNode] = deque()
        self._visited: set[str] = set()
        self._total_edges = 0

    async def __aenter__(self) -> "FollowingScraper":
        """Enter async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context."""
        self._logger.info(
            "following_scraper.closed",
            visited_count=len(self._visited),
            total_edges=self._total_edges,
        )

    def _emit_progress(self, node: BFSNode, edges_found: int) -> None:
        """Emit progress update if callback is set."""
        if self._progress_callback is not None:
            self._progress_callback(
                BFSProgress(
                    current_user_id=node.user_id,
                    current_username=node.username,
                    current_depth=node.depth,
                    queue_size=len(self._queue),
                    visited_count=len(self._visited),
                    edges_found=edges_found,
                    total_edges=self._total_edges,
                )
            )

    async def _load_visited_from_db(self) -> None:
        """Load already-scraped user IDs from database."""
        async with self._database.session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(User.id).where(User.followings_scraped == True)  # noqa: E712
            )
            self._visited = set(row[0] for row in result.fetchall())

        self._logger.info(
            "following_scraper.loaded_visited",
            count=len(self._visited),
        )

    async def _save_user(
        self,
        twitter_user: TwitterUser,
        depth: int,
        is_seed: bool = False,
    ) -> None:
        """Save or update a user in the database."""
        async with self._database.session() as session:
            from sqlalchemy import select
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            # Check if user exists
            existing = await session.execute(
                select(User).where(User.id == twitter_user.id)
            )
            user = existing.scalar_one_or_none()

            if user is None:
                user = User(
                    id=twitter_user.id,
                    username=twitter_user.username,
                    display_name=twitter_user.display_name,
                    bio=twitter_user.bio,
                    location=twitter_user.location,
                    url=twitter_user.url,
                    followers_count=twitter_user.followers_count,
                    following_count=twitter_user.following_count,
                    tweet_count=twitter_user.tweet_count,
                    verified=twitter_user.verified,
                    created_at=twitter_user.created_at,
                    is_seed=is_seed,
                    depth=depth,
                )
                session.add(user)
            else:
                # Update with new data (immutable pattern - create new values)
                user.username = twitter_user.username
                user.display_name = twitter_user.display_name
                user.bio = twitter_user.bio
                user.followers_count = twitter_user.followers_count
                user.following_count = twitter_user.following_count
                if is_seed:
                    user.is_seed = True
                if depth < user.depth:
                    user.depth = depth

            await session.commit()

    async def _save_edges(self, source_id: str, target_ids: list[str]) -> None:
        """Save follow edges to the database."""
        if not target_ids:
            return

        async with self._database.session() as session:
            edges = [
                Edge(source_id=source_id, target_id=target_id)
                for target_id in target_ids
            ]

            for edge in edges:
                await session.merge(edge)

            await session.commit()

        self._total_edges += len(target_ids)

    async def _mark_user_scraped(self, user_id: str) -> None:
        """Mark a user's followings as scraped."""
        async with self._database.session() as session:
            from sqlalchemy import select

            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user is not None:
                user.followings_scraped = True
                await session.commit()

    async def _scrape_user_followings(
        self,
        node: BFSNode,
        max_depth: int,
    ) -> AsyncIterator[BFSNode]:
        """Scrape followings for a single user and yield new nodes.

        Args:
            node: The BFS node to process.
            max_depth: Maximum depth for traversal.

        Yields:
            New BFSNode objects for discovered users.
        """
        self._logger.info(
            "following_scraper.scraping_user",
            user_id=node.user_id,
            username=node.username,
            depth=node.depth,
        )

        edges_found = 0
        target_ids: list[str] = []

        try:
            async for following in self._client.get_following(
                user_id=node.user_id
            ):
                edges_found += 1
                target_ids.append(following.id)

                # Save user to database
                await self._save_user(
                    twitter_user=following,
                    depth=node.depth + 1,
                )

                # Add to queue if not visited and within depth
                if (
                    following.id not in self._visited
                    and node.depth + 1 < max_depth
                ):
                    yield BFSNode(
                        user_id=following.id,
                        username=following.username,
                        depth=node.depth + 1,
                    )

                # Batch save edges
                if len(target_ids) >= self._batch_size:
                    await self._save_edges(node.user_id, target_ids)
                    target_ids = []

            # Save remaining edges
            if target_ids:
                await self._save_edges(node.user_id, target_ids)

            # Mark user as scraped
            await self._mark_user_scraped(node.user_id)

            self._emit_progress(node, edges_found)

            self._logger.info(
                "following_scraper.user_complete",
                user_id=node.user_id,
                edges_found=edges_found,
            )

        except Exception as e:
            self._logger.error(
                "following_scraper.user_error",
                user_id=node.user_id,
                error=str(e),
            )
            raise ScrapingError(
                f"Failed to scrape followings for user {node.user_id}",
                user_id=node.user_id,
                endpoint="get_following",
            ) from e

    async def crawl_from_seeds(
        self,
        seed_ids: list[str],
        *,
        max_depth: int = 2,
        resume: bool = True,
        skip_errors: bool = True,
    ) -> BFSResult:
        """Perform BFS crawl starting from seed users.

        Args:
            seed_ids: List of user IDs to start crawling from.
            max_depth: Maximum depth for BFS traversal (0 = seeds only).
            resume: Whether to skip already-scraped users.
            skip_errors: Whether to continue on errors.

        Returns:
            BFSResult with statistics about the crawl.
        """
        self._logger.info(
            "following_scraper.crawl_start",
            seed_count=len(seed_ids),
            max_depth=max_depth,
        )

        # Reset state
        self._queue.clear()
        self._visited.clear()
        self._total_edges = 0
        errors: list[str] = []
        max_depth_reached = 0

        # Load already-scraped users if resuming
        if resume:
            await self._load_visited_from_db()

        # Initialize queue with seeds
        for seed_id in seed_ids:
            if seed_id not in self._visited:
                # Fetch seed user info
                try:
                    seed_user = await self._client.get_user_by_id(seed_id)
                    await self._save_user(seed_user, depth=0, is_seed=True)

                    self._queue.append(
                        BFSNode(
                            user_id=seed_id,
                            username=seed_user.username,
                            depth=0,
                        )
                    )
                except Exception as e:
                    error_msg = f"Failed to fetch seed {seed_id}: {e}"
                    self._logger.error(
                        "following_scraper.seed_error",
                        seed_id=seed_id,
                        error=str(e),
                    )
                    errors.append(error_msg)
                    if not skip_errors:
                        raise ScrapingError(error_msg, user_id=seed_id)

        # BFS traversal
        while self._queue:
            node = self._queue.popleft()

            if node.user_id in self._visited:
                continue

            self._visited.add(node.user_id)
            max_depth_reached = max(max_depth_reached, node.depth)

            try:
                async for new_node in self._scrape_user_followings(
                    node, max_depth
                ):
                    if new_node.user_id not in self._visited:
                        self._queue.append(new_node)

            except ScrapingError as e:
                errors.append(str(e))
                if not skip_errors:
                    raise

        result = BFSResult(
            users_visited=len(self._visited),
            edges_discovered=self._total_edges,
            max_depth_reached=max_depth_reached,
            errors=errors,
        )

        self._logger.info(
            "following_scraper.crawl_complete",
            users_visited=result.users_visited,
            edges_discovered=result.edges_discovered,
            max_depth_reached=result.max_depth_reached,
            error_count=len(errors),
        )

        return result

    async def crawl_single_user(
        self,
        user_id: str,
        *,
        max_followings: int | None = None,
    ) -> AsyncIterator[TwitterUser]:
        """Scrape followings for a single user without BFS.

        Args:
            user_id: The user ID to scrape followings for.
            max_followings: Maximum number of followings to retrieve.

        Yields:
            TwitterUser objects representing the user's followings.
        """
        self._logger.info(
            "following_scraper.single_user_start",
            user_id=user_id,
        )

        count = 0

        try:
            async for following in self._client.get_following(
                user_id=user_id,
                max_results=max_followings,
            ):
                count += 1
                yield following

        except Exception as e:
            self._logger.error(
                "following_scraper.single_user_error",
                user_id=user_id,
                error=str(e),
            )
            raise ScrapingError(
                f"Failed to scrape followings for user {user_id}",
                user_id=user_id,
                endpoint="get_following",
            ) from e

        self._logger.info(
            "following_scraper.single_user_complete",
            user_id=user_id,
            followings_count=count,
        )

    async def get_queue_status(self) -> dict[str, Any]:
        """Get current BFS queue status.

        Returns:
            Dictionary with queue statistics.
        """
        return {
            "queue_size": len(self._queue),
            "visited_count": len(self._visited),
            "total_edges": self._total_edges,
            "next_in_queue": (
                {
                    "user_id": self._queue[0].user_id,
                    "username": self._queue[0].username,
                    "depth": self._queue[0].depth,
                }
                if self._queue
                else None
            ),
        }
