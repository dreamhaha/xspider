"""Background search task worker."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from xspider.admin.models import (
    AccountGroup,
    AccountStatus,
    DiscoveredInfluencer,
    InfluencerRelationship,
    SearchStage,
    SearchStatus,
    TwitterAccount,
    UserSearch,
)
from xspider.admin.services.account_pool import (
    AccountPool,
    CrawlStats,
    SearchStats,
    concurrent_get_followers,
    concurrent_search,
)
from xspider.admin.services.account_stats_service import AccountStatsService, AccountActionType
from xspider.core import get_logger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = get_logger(__name__)


@dataclass
class DiscoveredUser:
    """Simple user data from search results."""

    id: str
    username: str
    name: str
    description: str
    followers_count: int
    following_count: int
    depth: int = 0  # Discovery depth: 0=seed, 1=level1, 2=level2, etc.


@dataclass
class FollowerRelation:
    """Relationship between users (source follows target)."""

    source_id: str  # Follower's ID
    target_id: str  # Followed user's ID


class SearchWorker:
    """Background worker that processes search tasks one at a time."""

    def __init__(self, database_url: str) -> None:
        """Initialize the search worker.

        Args:
            database_url: SQLAlchemy async database URL.
        """
        self._database_url = database_url
        self._engine: AsyncEngine | None = None
        self._session_factory: sessionmaker | None = None
        self._running = False
        self._current_search_id: int | None = None

    async def start(self) -> None:
        """Start the background worker."""
        self._engine = create_async_engine(self._database_url)
        self._session_factory = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        self._running = True

        logger.info("search_worker.started")

        while self._running:
            try:
                await self._process_next_search()
            except Exception as e:
                logger.error("search_worker.error", error=str(e))

            # Wait before checking for next task
            await asyncio.sleep(2)

    async def stop(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._engine:
            await self._engine.dispose()
        logger.info("search_worker.stopped")

    async def _get_session(self) -> AsyncSession:
        """Get a new database session."""
        return self._session_factory()

    async def _process_next_search(self) -> None:
        """Find and process the next pending/running search."""
        async with await self._get_session() as session:
            # Find the oldest running or pending search
            result = await session.execute(
                select(UserSearch)
                .where(UserSearch.status.in_([SearchStatus.RUNNING, SearchStatus.PENDING]))
                .order_by(UserSearch.created_at.asc())
                .limit(1)
            )
            search = result.scalar_one_or_none()

            if not search:
                return  # No tasks to process

            self._current_search_id = search.id
            logger.info(
                "search_worker.processing",
                search_id=search.id,
                keywords=search.keywords,
            )

            try:
                await self._execute_search(session, search)
            except Exception as e:
                logger.error(
                    "search_worker.search_failed",
                    search_id=search.id,
                    error=str(e),
                )
                # Mark as failed
                search.status = SearchStatus.FAILED
                search.error_message = str(e)
                search.completed_at = datetime.now(timezone.utc)
                await session.commit()
            finally:
                self._current_search_id = None

    async def _execute_search(self, session: AsyncSession, search: UserSearch) -> None:
        """Execute a search task using twikit library."""
        # Update status to running if pending
        if search.status == SearchStatus.PENDING:
            search.status = SearchStatus.RUNNING

        # Stage 1: Initializing
        await self._update_progress(
            session, search, SearchStage.INITIALIZING, 5,
            "Preparing search parameters..."
        )

        # Get active Twitter accounts
        db_accounts = await self._get_active_accounts(session)
        if not db_accounts:
            raise Exception("No active Twitter account available")

        # Create account pool for concurrent searches
        pool = AccountPool.from_db_accounts(db_accounts)
        available_count = pool.get_available_count()

        logger.info(
            "search_worker.using_account_pool",
            total_accounts=len(pool),
            available_accounts=available_count,
        )

        # Stage 2: Searching seeds
        await self._update_progress(
            session, search, SearchStage.SEARCHING_SEEDS, 10,
            f"Searching with {available_count} accounts: {search.keywords[:50]}..."
        )

        # Parse keywords
        keywords = [k.strip() for k in search.keywords.split(",") if k.strip()]

        # Use concurrent search with account pool
        seed_users: list[DiscoveredUser] = []
        search_stats: SearchStats | None = None
        try:
            # Perform concurrent search using all available accounts
            twikit_users, search_stats = await concurrent_search(
                pool=pool,
                keywords=keywords,
                max_results_per_keyword=50,
            )

            # Convert twikit users to our DiscoveredUser dataclass
            for user in twikit_users:
                discovered = DiscoveredUser(
                    id=user.id,
                    username=user.screen_name,
                    name=user.name or user.screen_name,
                    description=user.description or "",
                    followers_count=user.followers_count or 0,
                    following_count=user.following_count or 0,
                    depth=0,  # Seeds are depth 0
                )
                seed_users.append(discovered)

            search.seeds_found = len(seed_users)

            # Update progress
            await self._update_progress(
                session, search, SearchStage.SEARCHING_SEEDS, 30,
                f"Found {len(seed_users)} seed users from {len(keywords)} keywords"
            )

            # Log pool stats
            pool_stats = pool.get_stats()
            logger.info(
                "search_worker.concurrent_search_completed",
                seeds_found=len(seed_users),
                available_accounts=pool_stats["available_accounts"],
                rate_limited_accounts=pool_stats["rate_limited_accounts"],
                total_searches=search_stats.total_searches,
                successful=search_stats.successful_searches,
                rate_limited=search_stats.rate_limited_searches,
                avg_response_ms=search_stats.avg_response_time_ms,
            )

            # Record activities for risk control statistics
            await self._record_search_activities(session, search_stats)

        except Exception as e:
            logger.warning("search_worker.seed_search_error", error=str(e))
            # Continue with whatever seeds we found

        # Check if all accounts are rate limited
        stats = pool.get_stats()
        all_rate_limited = stats["available_accounts"] == 0 and stats["rate_limited_accounts"] > 0

        if not seed_users:
            # Complete with appropriate message
            search.status = SearchStatus.COMPLETED
            search.completed_at = datetime.now(timezone.utc)
            search.progress_percent = 100
            search.progress_stage = SearchStage.FINALIZING
            if all_rate_limited:
                search.progress_message = "All accounts rate limited - please try again in 15 minutes"
            else:
                search.progress_message = "No users found matching keywords"
            await session.commit()
            return

        # Stage 3: Crawl followers based on crawl_depth
        all_discovered_users = list(seed_users)
        seen_ids: set[str] = {user.id for user in seed_users}
        all_relations: list[FollowerRelation] = []

        # Crawl followers for each depth level
        current_level_users = seed_users
        for current_depth in range(1, search.crawl_depth + 1):
            if not current_level_users:
                break

            # For deeper levels, limit to top users by follower count
            if current_depth > 1:
                users_to_crawl = sorted(
                    current_level_users,
                    key=lambda u: u.followers_count,
                    reverse=True
                )[:20]  # Limit to top 20 for deeper levels
            else:
                users_to_crawl = current_level_users

            # Calculate progress percentage for this depth
            base_progress = 35 + (current_depth - 1) * 10
            await self._update_progress(
                session, search, SearchStage.BUILDING_GRAPH, base_progress,
                f"Crawling followers of {len(users_to_crawl)} users (depth {current_depth})..."
            )

            # Crawl followers and get relationships
            new_users, relations = await self._crawl_followers_with_relations(
                session, pool, users_to_crawl, seen_ids,
                max_per_user=max(50 - current_depth * 10, 20),  # Reduce per user at deeper levels
                depth=current_depth,
            )

            all_discovered_users.extend(new_users)
            all_relations.extend(relations)
            current_level_users = new_users

            await self._update_progress(
                session, search, SearchStage.BUILDING_GRAPH, base_progress + 5,
                f"Found {len(new_users)} users at depth {current_depth}"
            )

            logger.info(
                "search_worker.depth_completed",
                depth=current_depth,
                new_users=len(new_users),
                relations=len(relations),
            )

        if search.crawl_depth == 0:
            await self._update_progress(
                session, search, SearchStage.BUILDING_GRAPH, 50,
                f"Processing {len(seed_users)} seed users (depth 0, no crawling)..."
            )

        # Stage 4: Calculate scores and save results
        await self._update_progress(
            session, search, SearchStage.CALCULATING_PAGERANK, 70,
            "Calculating influence scores..."
        )

        # Deduplicate final list
        unique_users = []
        final_seen: set[str] = set()
        for user in all_discovered_users:
            if user.id not in final_seen:
                final_seen.add(user.id)
                unique_users.append(user)

        # Save discovered influencers
        for i, user in enumerate(unique_users):
            influencer = DiscoveredInfluencer(
                search_id=search.id,
                user_id=search.user_id,
                twitter_user_id=user.id,
                screen_name=user.username,
                name=user.name,
                description=user.description,
                followers_count=user.followers_count,
                following_count=user.following_count,
                depth=user.depth,
                pagerank_score=1.0 / (i + 1),
                hidden_score=0.0,
                is_relevant=True,
                relevance_score=8,
            )
            session.add(influencer)

            search.users_crawled = i + 1
            if i % 10 == 0:
                progress = 70 + min((i * 20) // max(len(unique_users), 1), 15)
                await self._update_progress(
                    session, search, SearchStage.CALCULATING_PAGERANK, progress,
                    f"Saved {i + 1}/{len(unique_users)} influencers..."
                )

        # Save relationships
        await self._update_progress(
            session, search, SearchStage.CALCULATING_PAGERANK, 88,
            f"Saving {len(all_relations)} relationships..."
        )

        for relation in all_relations:
            rel = InfluencerRelationship(
                search_id=search.id,
                source_twitter_id=relation.source_id,
                target_twitter_id=relation.target_id,
            )
            session.add(rel)

        logger.info(
            "search_worker.relationships_saved",
            count=len(all_relations),
        )

        # Stage 5: Finalizing
        await self._update_progress(
            session, search, SearchStage.FINALIZING, 95,
            "Finalizing results..."
        )

        # Complete
        search.status = SearchStatus.COMPLETED
        search.completed_at = datetime.now(timezone.utc)
        search.progress_percent = 100
        search.progress_stage = SearchStage.FINALIZING
        search.progress_message = f"Found {len(unique_users)} influencers"

        await session.commit()

        logger.info(
            "search_worker.search_completed",
            search_id=search.id,
            seeds_found=search.seeds_found,
            users_crawled=search.users_crawled,
        )

    async def _update_progress(
        self,
        session: AsyncSession,
        search: UserSearch,
        stage: SearchStage,
        percent: int,
        message: str,
    ) -> None:
        """Update search progress."""
        search.progress_stage = stage
        search.progress_percent = percent
        search.progress_message = message
        search.progress_updated_at = datetime.now(timezone.utc)
        await session.commit()

    async def _get_active_accounts(self, session: AsyncSession) -> list[TwitterAccount]:
        """Get all active Twitter accounts for API calls.

        Only returns accounts that are:
        1. Status is ACTIVE
        2. Either ungrouped (group_id is NULL) OR belong to an active group
        """
        # Get IDs of all active groups
        active_groups_result = await session.execute(
            select(AccountGroup.id).where(AccountGroup.is_active == True)
        )
        active_group_ids = set(row[0] for row in active_groups_result.fetchall())

        # Build query for active accounts in active groups or ungrouped
        from sqlalchemy import or_

        result = await session.execute(
            select(TwitterAccount)
            .where(TwitterAccount.status == AccountStatus.ACTIVE)
            .where(
                or_(
                    TwitterAccount.group_id == None,  # Ungrouped accounts
                    TwitterAccount.group_id.in_(active_group_ids) if active_group_ids else False
                )
            )
            .order_by(TwitterAccount.last_used_at.asc().nulls_first())
        )
        return list(result.scalars().all())

    async def _crawl_followers(
        self,
        session: AsyncSession,
        pool: AccountPool,
        users: list[DiscoveredUser],
        seen_ids: set[str],
        max_per_user: int = 50,
    ) -> list[DiscoveredUser]:
        """Crawl followers of users using account pool.

        Args:
            session: Database session.
            pool: Account pool for API calls.
            users: List of users to get followers for.
            seen_ids: Set of user IDs already seen (will be updated).
            max_per_user: Maximum followers per user.

        Returns:
            List of newly discovered users (not in seen_ids).
        """
        user_ids = [u.id for u in users]

        logger.info(
            "search_worker.crawl_followers_start",
            user_count=len(user_ids),
            max_per_user=max_per_user,
        )

        # Get followers concurrently
        twikit_followers, crawl_stats = await concurrent_get_followers(
            pool=pool,
            user_ids=user_ids,
            max_followers_per_user=max_per_user,
        )

        # Convert to DiscoveredUser and filter out already seen
        new_users: list[DiscoveredUser] = []
        for follower in twikit_followers:
            if follower.id not in seen_ids:
                seen_ids.add(follower.id)
                discovered = DiscoveredUser(
                    id=follower.id,
                    username=follower.screen_name,
                    name=follower.name or follower.screen_name,
                    description=follower.description or "",
                    followers_count=follower.followers_count or 0,
                    following_count=follower.following_count or 0,
                )
                new_users.append(discovered)

        logger.info(
            "search_worker.crawl_followers_completed",
            total_followers=len(twikit_followers),
            new_users=len(new_users),
            successful_requests=crawl_stats.successful_requests,
            rate_limited=crawl_stats.rate_limited_requests,
        )

        # Record crawl activities for statistics
        await self._record_crawl_activities(session, crawl_stats)

        return new_users

    async def _crawl_followers_with_relations(
        self,
        session: AsyncSession,
        pool: AccountPool,
        users: list[DiscoveredUser],
        seen_ids: set[str],
        max_per_user: int = 50,
        depth: int = 1,
    ) -> tuple[list[DiscoveredUser], list[FollowerRelation]]:
        """Crawl followers and track relationships.

        Args:
            session: Database session.
            pool: Account pool for API calls.
            users: List of users to get followers for.
            seen_ids: Set of user IDs already seen (will be updated).
            max_per_user: Maximum followers per user.
            depth: Current crawl depth level.

        Returns:
            Tuple of (new users, relationships).
        """
        from xspider.admin.services.account_pool import get_followers_with_account

        new_users: list[DiscoveredUser] = []
        relations: list[FollowerRelation] = []
        crawl_stats = CrawlStats()

        logger.info(
            "search_worker.crawl_with_relations_start",
            user_count=len(users),
            max_per_user=max_per_user,
            depth=depth,
        )

        # Process users in batches for concurrency
        batch_size = min(pool.get_available_count(), 5)
        if batch_size == 0:
            batch_size = 1

        for i in range(0, len(users), batch_size):
            batch_users = users[i:i + batch_size]
            accounts = await pool.get_multiple_accounts(len(batch_users))

            if not accounts:
                # Try one at a time
                for target_user in batch_users:
                    account = await pool.get_account()
                    if not account:
                        logger.warning("search_worker.no_accounts_available")
                        break

                    followers, was_rate_limited, response_time, error = await get_followers_with_account(
                        account, target_user.id, max_per_user
                    )

                    # Record activity stats
                    crawl_stats.total_requests += 1
                    if was_rate_limited:
                        crawl_stats.rate_limited_requests += 1
                    elif error:
                        crawl_stats.failed_requests += 1
                    else:
                        crawl_stats.successful_requests += 1
                        crawl_stats.total_followers += len(followers)

                    crawl_stats.account_activities.append({
                        "account_id": account.account_id,
                        "user_id": target_user.id,
                        "success": not error and not was_rate_limited,
                        "result_count": len(followers),
                        "response_time_ms": response_time,
                        "is_rate_limited": was_rate_limited,
                        "error_message": error,
                    })

                    for follower in followers:
                        # Record relationship: follower follows target_user
                        relations.append(FollowerRelation(
                            source_id=follower.id,
                            target_id=target_user.id,
                        ))

                        # Add to discovered users if new
                        if follower.id not in seen_ids:
                            seen_ids.add(follower.id)
                            new_users.append(DiscoveredUser(
                                id=follower.id,
                                username=follower.screen_name,
                                name=follower.name or follower.screen_name,
                                description=follower.description or "",
                                followers_count=follower.followers_count or 0,
                                following_count=follower.following_count or 0,
                                depth=depth,
                            ))
                continue

            # Create concurrent tasks for batch
            tasks = [
                get_followers_with_account(account, user.id, max_per_user)
                for account, user in zip(accounts, batch_users)
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, result in enumerate(results):
                target_user = batch_users[j]
                account = accounts[j]

                if isinstance(result, Exception):
                    logger.warning(
                        "search_worker.followers_error",
                        user_id=target_user.id,
                        error=str(result),
                    )
                    crawl_stats.total_requests += 1
                    crawl_stats.failed_requests += 1
                    crawl_stats.account_activities.append({
                        "account_id": account.account_id,
                        "user_id": target_user.id,
                        "success": False,
                        "result_count": 0,
                        "response_time_ms": 0,
                        "is_rate_limited": False,
                        "error_message": str(result),
                    })
                    continue

                followers, was_rate_limited, response_time, error = result

                # Record activity stats
                crawl_stats.total_requests += 1
                if was_rate_limited:
                    crawl_stats.rate_limited_requests += 1
                elif error:
                    crawl_stats.failed_requests += 1
                else:
                    crawl_stats.successful_requests += 1
                    crawl_stats.total_followers += len(followers)

                crawl_stats.account_activities.append({
                    "account_id": account.account_id,
                    "user_id": target_user.id,
                    "success": not error and not was_rate_limited,
                    "result_count": len(followers),
                    "response_time_ms": response_time,
                    "is_rate_limited": was_rate_limited,
                    "error_message": error,
                })

                for follower in followers:
                    # Record relationship: follower follows target_user
                    relations.append(FollowerRelation(
                        source_id=follower.id,
                        target_id=target_user.id,
                    ))

                    # Add to discovered users if new
                    if follower.id not in seen_ids:
                        seen_ids.add(follower.id)
                        new_users.append(DiscoveredUser(
                            id=follower.id,
                            username=follower.screen_name,
                            name=follower.name or follower.screen_name,
                            description=follower.description or "",
                            followers_count=follower.followers_count or 0,
                            following_count=follower.following_count or 0,
                            depth=depth,
                        ))

            # Small delay between batches
            if i + batch_size < len(users):
                await asyncio.sleep(1)

        logger.info(
            "search_worker.crawl_with_relations_completed",
            new_users=len(new_users),
            relations=len(relations),
            depth=depth,
            total_requests=crawl_stats.total_requests,
        )

        # Record activities to database for statistics
        await self._record_crawl_activities(session, crawl_stats)

        return new_users, relations

    async def _record_search_activities(
        self, session: AsyncSession, search_stats: SearchStats
    ) -> None:
        """Record search activities for risk control statistics.

        Args:
            session: Database session.
            search_stats: Statistics from concurrent search.
        """
        try:
            stats_service = AccountStatsService(session)

            for activity in search_stats.account_activities:
                await stats_service.record_activity(
                    account_id=activity["account_id"],
                    action_type=AccountActionType.SEARCH_USER,
                    success=activity["success"],
                    response_time_ms=activity["response_time_ms"],
                    result_count=activity["result_count"],
                    is_rate_limited=activity["is_rate_limited"],
                    error_message=activity["error_message"],
                    keyword=activity["keyword"],
                )

            # Update daily stats for each account
            account_ids = set(a["account_id"] for a in search_stats.account_activities)
            for account_id in account_ids:
                await stats_service.update_daily_stats(account_id)

            logger.debug(
                "search_worker.activities_recorded",
                count=len(search_stats.account_activities),
            )
        except Exception as e:
            logger.warning(
                "search_worker.record_activities_error",
                error=str(e),
            )

    async def _record_crawl_activities(
        self, session: AsyncSession, crawl_stats: CrawlStats
    ) -> None:
        """Record follower crawl activities for risk control statistics.

        Args:
            session: Database session.
            crawl_stats: Statistics from concurrent follower crawling.
        """
        try:
            stats_service = AccountStatsService(session)

            for activity in crawl_stats.account_activities:
                await stats_service.record_activity(
                    account_id=activity["account_id"],
                    action_type=AccountActionType.GET_FOLLOWERS,
                    success=activity["success"],
                    response_time_ms=activity["response_time_ms"],
                    result_count=activity["result_count"],
                    is_rate_limited=activity["is_rate_limited"],
                    error_message=activity["error_message"],
                    target_user_id=activity.get("user_id"),
                )

            # Update daily stats for each account
            account_ids = set(a["account_id"] for a in crawl_stats.account_activities)
            for account_id in account_ids:
                await stats_service.update_daily_stats(account_id)

            logger.debug(
                "search_worker.crawl_activities_recorded",
                count=len(crawl_stats.account_activities),
            )
        except Exception as e:
            logger.warning(
                "search_worker.record_crawl_activities_error",
                error=str(e),
            )


# Global worker instance
_worker: SearchWorker | None = None


async def start_search_worker(database_url: str) -> None:
    """Start the global search worker."""
    global _worker
    if _worker is None:
        _worker = SearchWorker(database_url)
        asyncio.create_task(_worker.start())


async def stop_search_worker() -> None:
    """Stop the global search worker."""
    global _worker
    if _worker:
        await _worker.stop()
        _worker = None
