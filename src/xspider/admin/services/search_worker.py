"""Background search task worker."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from xspider.admin.models import (
    AccountGroup,
    AccountStatus,
    CrawlMode,
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
    concurrent_get_following,
    concurrent_search,
)
from xspider.admin.services.account_stats_service import AccountStatsService, AccountActionType
from xspider.admin.services.link_extractor import extract_bio_links, serialize_links
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
    is_seed: bool = False  # Whether this user was a manually specified seed
    discovered_from: str | None = None  # Twitter user ID of the user this was discovered from
    discovery_source: str = "keyword"  # How was this user discovered: seed, keyword, following, comment
    description_urls: list[dict] | None = None  # Twitter URL entities for expanding t.co links


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
        """Execute a search task using twikit library.

        Supports three crawl modes:
        - keywords: Traditional keyword-based search
        - seeds: Start from specified influencer usernames
        - mixed: Combine both keyword search and seed users
        """
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

        # Get active proxies
        proxy_urls = await self._get_active_proxy_urls(session)

        # Create account pool for concurrent searches (with proxy support)
        pool = AccountPool.from_db_accounts(db_accounts, proxy_urls=proxy_urls)
        available_count = pool.get_available_count()

        logger.info(
            "search_worker.using_account_pool",
            total_accounts=len(pool),
            available_accounts=available_count,
            proxy_count=len(proxy_urls),
            crawl_mode=search.crawl_mode.value,
        )

        # Determine crawl mode
        crawl_mode = search.crawl_mode or CrawlMode.KEYWORDS

        # Collect all seed users from both sources
        seed_users: list[DiscoveredUser] = []
        search_stats: SearchStats | None = None

        # Stage 2a: Resolve specified seed users (for seeds or mixed mode)
        if crawl_mode in (CrawlMode.SEEDS, CrawlMode.MIXED):
            seed_usernames_json = search.seed_usernames
            if seed_usernames_json:
                try:
                    seed_usernames = json.loads(seed_usernames_json)
                    if seed_usernames:
                        await self._update_progress(
                            session, search, SearchStage.RESOLVING_SEEDS, 8,
                            f"Resolving {len(seed_usernames)} specified seed users..."
                        )

                        resolved_seeds = await self._resolve_seed_users(pool, seed_usernames)
                        seed_users.extend(resolved_seeds)

                        logger.info(
                            "search_worker.seeds_resolved",
                            requested=len(seed_usernames),
                            resolved=len(resolved_seeds),
                        )
                except json.JSONDecodeError as e:
                    logger.warning("search_worker.invalid_seed_json", error=str(e))

        # Stage 2b: Keyword search (for keywords or mixed mode)
        if crawl_mode in (CrawlMode.KEYWORDS, CrawlMode.MIXED):
            if search.keywords:
                keywords_text = search.keywords[:50] if search.keywords else ""
                await self._update_progress(
                    session, search, SearchStage.SEARCHING_SEEDS, 15,
                    f"Searching with {available_count} accounts: {keywords_text}..."
                )

                # Parse keywords
                keywords = [k.strip() for k in search.keywords.split(",") if k.strip()]

                try:
                    # Perform concurrent search using all available accounts
                    twikit_users, search_stats = await concurrent_search(
                        pool=pool,
                        keywords=keywords,
                        max_results_per_keyword=50,
                    )

                    # Convert twikit users to our DiscoveredUser dataclass
                    # Mark them as non-seeds (discovered via keyword search)
                    for user in twikit_users:
                        discovered = DiscoveredUser(
                            id=user.id,
                            username=user.screen_name,
                            name=user.name or user.screen_name,
                            description=user.description or "",
                            followers_count=user.followers_count or 0,
                            following_count=user.following_count or 0,
                            depth=0,  # Seeds are depth 0
                            is_seed=False,  # Discovered via search, not manually specified
                            discovered_from=None,
                            discovery_source="keyword",
                            description_urls=getattr(user, "description_urls", None),
                        )
                        seed_users.append(discovered)

                    # Log pool stats
                    if search_stats:
                        pool_stats = pool.get_stats()
                        logger.info(
                            "search_worker.concurrent_search_completed",
                            seeds_found=len(twikit_users),
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

        # Update seeds found count
        search.seeds_found = len(seed_users)

        # Update progress based on what we collected
        await self._update_progress(
            session, search, SearchStage.SEARCHING_SEEDS, 30,
            f"Found {len(seed_users)} seed users"
        )

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
            elif crawl_mode == CrawlMode.SEEDS:
                search.progress_message = "No seed users could be resolved"
            else:
                search.progress_message = "No users found matching keywords"
            await session.commit()
            return

        # Stage 3: Crawl following based on crawl_depth
        # Following = accounts the seed users follow (not their followers)
        all_discovered_users = list(seed_users)
        seen_ids: set[str] = {user.id for user in seed_users}
        all_relations: list[FollowerRelation] = []

        # Crawl following for each depth level
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
                f"Crawling following of {len(users_to_crawl)} users (depth {current_depth})..."
            )

            # Crawl following and get relationships
            new_users, relations = await self._crawl_following_with_relations(
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

        # Stage 3b: Crawl commenters from recent tweets (if enabled)
        if search.crawl_commenters:
            await self._update_progress(
                session, search, SearchStage.CRAWLING_COMMENTERS, 55,
                f"Crawling commenters from {len(seed_users)} users' recent tweets..."
            )

            commenter_users = await self._crawl_tweet_commenters(
                session=session,
                pool=pool,
                users=seed_users,
                seen_ids=seen_ids,
                tweets_per_user=search.tweets_per_user or 10,
                commenters_per_tweet=search.commenters_per_tweet or 50,
            )

            all_discovered_users.extend(commenter_users)

            await self._update_progress(
                session, search, SearchStage.CRAWLING_COMMENTERS, 65,
                f"Found {len(commenter_users)} users from comment sections"
            )

            logger.info(
                "search_worker.commenters_completed",
                commenter_count=len(commenter_users),
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

        # Save discovered influencers with link extraction
        # Get first proxy for link extraction (if available)
        first_proxy = proxy_urls[0] if proxy_urls else None

        for i, user in enumerate(unique_users):
            # Extract links from user bio
            extracted_links_json = None
            if user.description or user.description_urls:
                try:
                    link_result = await extract_bio_links(
                        description=user.description,
                        description_urls=user.description_urls,
                        parse_linktree=True,
                        proxy_url=first_proxy,
                    )
                    if link_result["all_links"]:
                        extracted_links_json = serialize_links(link_result["all_links"])
                except Exception as link_err:
                    logger.debug(
                        "search_worker.link_extraction_error",
                        user_id=user.id,
                        error=str(link_err),
                    )

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
                # Seed mode fields
                is_seed=user.is_seed,
                discovered_from=user.discovered_from,
                discovery_source=user.discovery_source,
                # Extracted links
                extracted_links=extracted_links_json,
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

    async def _get_active_proxy_urls(self, session: AsyncSession) -> list[str]:
        """Get URLs of all active proxies.

        Returns:
            List of proxy URLs formatted for twikit.
        """
        from xspider.admin.models import ProxyServer, ProxyStatus, ProxyProtocol

        result = await session.execute(
            select(ProxyServer)
            .where(ProxyServer.status == ProxyStatus.ACTIVE)
            .order_by(ProxyServer.response_time.asc().nulls_last())
        )
        proxies = list(result.scalars().all())

        proxy_urls = []
        for proxy in proxies:
            url = proxy.url
            # Ensure URL has protocol prefix
            if not url.startswith(("http://", "https://", "socks5://")):
                if proxy.protocol == ProxyProtocol.SOCKS5:
                    url = f"socks5://{url}"
                elif proxy.protocol == ProxyProtocol.HTTPS:
                    url = f"https://{url}"
                else:
                    url = f"http://{url}"
            proxy_urls.append(url)

        return proxy_urls

    async def _resolve_seed_users(
        self,
        pool: AccountPool,
        usernames: list[str],
        max_retries: int = 3,
    ) -> list[DiscoveredUser]:
        """Resolve usernames to full user information.

        Takes a list of Twitter usernames (without @) and retrieves their full profile.
        These users will be marked as seeds (is_seed=True, depth=0).

        If an account fails or is rate limited, the task will be retried with another account.

        Args:
            pool: Account pool for API calls.
            usernames: List of Twitter usernames to resolve.
            max_retries: Maximum retry attempts per username.

        Returns:
            List of DiscoveredUser objects for successfully resolved users.
        """
        resolved_users: list[DiscoveredUser] = []
        failed_usernames: list[str] = []

        logger.info(
            "search_worker.resolving_seed_users",
            count=len(usernames),
        )

        for username in usernames:
            resolved = False
            last_error = None

            # Try up to max_retries times with different accounts
            for attempt in range(max_retries):
                # Get an available account
                account = await pool.get_account()
                if not account:
                    # Wait for rate-limited accounts to recover
                    if attempt < max_retries - 1:
                        logger.info(
                            "search_worker.waiting_for_account",
                            username=username,
                            attempt=attempt + 1,
                        )
                        await asyncio.sleep(2)
                        continue
                    else:
                        logger.warning(
                            "search_worker.no_account_for_seed_resolution",
                            username=username,
                        )
                        break

                try:
                    client = account.get_client()
                    user = await client.get_user_by_screen_name(username)

                    if user:
                        resolved_users.append(DiscoveredUser(
                            id=user.id,
                            username=user.screen_name,
                            name=user.name or user.screen_name,
                            description=user.description or "",
                            followers_count=user.followers_count or 0,
                            following_count=user.following_count or 0,
                            depth=0,
                            is_seed=True,
                            discovered_from=None,
                            discovery_source="seed",
                            description_urls=getattr(user, "description_urls", None),
                        ))
                        logger.info(
                            "search_worker.seed_user_resolved",
                            username=user.screen_name,
                            followers=user.followers_count,
                        )
                        resolved = True
                        break  # Success, move to next username
                    else:
                        # User not found - don't retry
                        logger.warning(
                            "search_worker.seed_user_not_found",
                            username=username,
                        )
                        last_error = "User not found"
                        break  # No point retrying if user doesn't exist

                except Exception as e:
                    error_msg = str(e) or f"{type(e).__name__}"
                    last_error = error_msg

                    if "TooManyRequests" in error_msg or "rate" in error_msg.lower() or type(e).__name__ == "TooManyRequests":
                        account.mark_rate_limited()
                        logger.warning(
                            "search_worker.seed_resolution_rate_limited",
                            username=username,
                            account_id=account.account_id,
                            attempt=attempt + 1,
                        )
                        # Retry with another account
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1)
                            continue
                    elif "not found" in error_msg.lower() or "suspended" in error_msg.lower():
                        # User doesn't exist or is suspended - don't retry
                        logger.warning(
                            "search_worker.seed_user_unavailable",
                            username=username,
                            error=error_msg,
                        )
                        break
                    elif "Timeout" in type(e).__name__ or "timeout" in error_msg.lower():
                        # Network timeout - retry without marking account error
                        logger.warning(
                            "search_worker.seed_resolution_timeout",
                            username=username,
                            attempt=attempt + 1,
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2)  # Wait a bit longer for timeout
                            continue
                    elif "ClientTransaction" in error_msg or "attribute" in error_msg:
                        # Internal twikit error - likely stale cookies, mark account error
                        account.mark_error()
                        account.client = None  # Clear cached client
                        logger.warning(
                            "search_worker.account_auth_error",
                            username=username,
                            account_id=account.account_id,
                            error=error_msg,
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1)
                            continue
                    else:
                        # Other error - retry with another account
                        logger.warning(
                            "search_worker.seed_resolution_error",
                            username=username,
                            error=error_msg,
                            error_type=type(e).__name__,
                            attempt=attempt + 1,
                        )
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1)
                            continue

            if not resolved:
                failed_usernames.append(username)

            # Small delay between usernames
            await asyncio.sleep(0.3)

        if failed_usernames:
            logger.warning(
                "search_worker.seed_resolution_failures",
                failed_count=len(failed_usernames),
                failed_usernames=failed_usernames,  # Log all failed usernames
            )

        logger.info(
            "search_worker.seed_resolution_completed",
            requested=len(usernames),
            resolved=len(resolved_users),
            failed=len(failed_usernames),
        )

        return resolved_users

    async def _crawl_following(
        self,
        session: AsyncSession,
        pool: AccountPool,
        users: list[DiscoveredUser],
        seen_ids: set[str],
        max_per_user: int = 50,
    ) -> list[DiscoveredUser]:
        """Crawl following of users using account pool.

        Gets the accounts that the seed users follow (their following list).
        This helps discover influencers in the same space.

        Args:
            session: Database session.
            pool: Account pool for API calls.
            users: List of users to get following for.
            seen_ids: Set of user IDs already seen (will be updated).
            max_per_user: Maximum following per user.

        Returns:
            List of newly discovered users (not in seen_ids).
        """
        user_ids = [u.id for u in users]

        logger.info(
            "search_worker.crawl_following_start",
            user_count=len(user_ids),
            max_per_user=max_per_user,
        )

        # Get following concurrently
        twikit_following, crawl_stats = await concurrent_get_following(
            pool=pool,
            user_ids=user_ids,
            max_following_per_user=max_per_user,
        )

        # Convert to DiscoveredUser and filter out already seen
        new_users: list[DiscoveredUser] = []
        for following in twikit_following:
            if following.id not in seen_ids:
                seen_ids.add(following.id)
                discovered = DiscoveredUser(
                    id=following.id,
                    username=following.screen_name,
                    name=following.name or following.screen_name,
                    description=following.description or "",
                    followers_count=following.followers_count or 0,
                    following_count=following.following_count or 0,
                    is_seed=False,
                    discovered_from=None,  # Parent relationship not tracked in this method
                    discovery_source="following",
                    description_urls=getattr(following, "description_urls", None),
                )
                new_users.append(discovered)

        logger.info(
            "search_worker.crawl_following_completed",
            total_following=len(twikit_following),
            new_users=len(new_users),
            successful_requests=crawl_stats.successful_requests,
            rate_limited=crawl_stats.rate_limited_requests,
        )

        # Record crawl activities for statistics
        await self._record_crawl_activities(session, crawl_stats)

        return new_users

    async def _crawl_following_with_relations(
        self,
        session: AsyncSession,
        pool: AccountPool,
        users: list[DiscoveredUser],
        seen_ids: set[str],
        max_per_user: int = 50,
        depth: int = 1,
    ) -> tuple[list[DiscoveredUser], list[FollowerRelation]]:
        """Crawl following and track relationships.

        Gets the accounts that the seed users follow (their following list).
        Records relationship: source_user follows target_user.

        Args:
            session: Database session.
            pool: Account pool for API calls.
            users: List of users to get following for.
            seen_ids: Set of user IDs already seen (will be updated).
            max_per_user: Maximum following per user.
            depth: Current crawl depth level.

        Returns:
            Tuple of (new users, relationships).
        """
        from xspider.admin.services.account_pool import get_following_with_account

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

                    following_list, was_rate_limited, response_time, error = await get_following_with_account(
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
                        crawl_stats.total_followers += len(following_list)

                    crawl_stats.account_activities.append({
                        "account_id": account.account_id,
                        "user_id": target_user.id,
                        "success": not error and not was_rate_limited,
                        "result_count": len(following_list),
                        "response_time_ms": response_time,
                        "is_rate_limited": was_rate_limited,
                        "error_message": error,
                    })

                    for followed_user in following_list:
                        # Record relationship: target_user follows followed_user
                        relations.append(FollowerRelation(
                            source_id=target_user.id,
                            target_id=followed_user.id,
                        ))

                        # Add to discovered users if new
                        if followed_user.id not in seen_ids:
                            seen_ids.add(followed_user.id)
                            new_users.append(DiscoveredUser(
                                id=followed_user.id,
                                username=followed_user.screen_name,
                                name=followed_user.name or followed_user.screen_name,
                                description=followed_user.description or "",
                                followers_count=followed_user.followers_count or 0,
                                following_count=followed_user.following_count or 0,
                                depth=depth,
                                is_seed=False,
                                discovered_from=target_user.id,
                                discovery_source="following",
                                description_urls=getattr(followed_user, "description_urls", None),
                            ))
                continue

            # Create concurrent tasks for batch
            tasks = [
                get_following_with_account(account, user.id, max_per_user)
                for account, user in zip(accounts, batch_users)
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, result in enumerate(results):
                target_user = batch_users[j]
                account = accounts[j]

                if isinstance(result, Exception):
                    logger.warning(
                        "search_worker.following_error",
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

                following_list, was_rate_limited, response_time, error = result

                # Record activity stats
                crawl_stats.total_requests += 1
                if was_rate_limited:
                    crawl_stats.rate_limited_requests += 1
                elif error:
                    crawl_stats.failed_requests += 1
                else:
                    crawl_stats.successful_requests += 1
                    crawl_stats.total_followers += len(following_list)

                crawl_stats.account_activities.append({
                    "account_id": account.account_id,
                    "user_id": target_user.id,
                    "success": not error and not was_rate_limited,
                    "result_count": len(following_list),
                    "response_time_ms": response_time,
                    "is_rate_limited": was_rate_limited,
                    "error_message": error,
                })

                for followed_user in following_list:
                    # Record relationship: target_user follows followed_user
                    relations.append(FollowerRelation(
                        source_id=target_user.id,
                        target_id=followed_user.id,
                    ))

                    # Add to discovered users if new
                    if followed_user.id not in seen_ids:
                        seen_ids.add(followed_user.id)
                        new_users.append(DiscoveredUser(
                            id=followed_user.id,
                            username=followed_user.screen_name,
                            name=followed_user.name or followed_user.screen_name,
                            description=followed_user.description or "",
                            followers_count=followed_user.followers_count or 0,
                            following_count=followed_user.following_count or 0,
                            depth=depth,
                            is_seed=False,
                            discovered_from=target_user.id,
                            discovery_source="following",
                            description_urls=getattr(followed_user, "description_urls", None),
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

    async def _crawl_tweet_commenters(
        self,
        session: AsyncSession,
        pool: AccountPool,
        users: list[DiscoveredUser],
        seen_ids: set[str],
        tweets_per_user: int = 10,
        commenters_per_tweet: int = 50,
    ) -> list[DiscoveredUser]:
        """Crawl commenters from recent tweets of specified users.

        For each user, get their recent tweets and extract accounts
        that commented/replied to those tweets.

        Args:
            session: Database session.
            pool: Account pool for API calls.
            users: List of users to get tweet commenters for.
            seen_ids: Set of user IDs already seen (will be updated).
            tweets_per_user: Number of recent tweets to fetch per user.
            commenters_per_tweet: Max commenters to fetch per tweet.

        Returns:
            List of newly discovered users from comment sections.
        """
        new_users: list[DiscoveredUser] = []

        logger.info(
            "search_worker.crawl_commenters_start",
            user_count=len(users),
            tweets_per_user=tweets_per_user,
            commenters_per_tweet=commenters_per_tweet,
        )

        for target_user in users:
            # Get an available account
            account = await pool.get_account()
            if not account:
                logger.warning(
                    "search_worker.no_account_for_commenters",
                    user=target_user.username,
                )
                # Wait and retry
                await asyncio.sleep(2)
                account = await pool.get_account()
                if not account:
                    continue

            try:
                client = account.get_client()

                # Get recent tweets from this user
                tweets = []
                try:
                    # get_user_tweets returns a Result object, not an async iterator
                    result = await client.get_user_tweets(
                        target_user.id,
                        tweet_type="Tweets",
                        count=tweets_per_user,
                    )
                    if result:
                        for tweet in result[:tweets_per_user]:
                            tweets.append(tweet)
                except Exception as e:
                    error_msg = str(e)
                    if "TooManyRequests" in error_msg or "rate" in error_msg.lower():
                        account.mark_rate_limited()
                    logger.warning(
                        "search_worker.get_tweets_error",
                        user=target_user.username,
                        error=error_msg,
                    )
                    continue

                logger.info(
                    "search_worker.got_user_tweets",
                    user=target_user.username,
                    tweet_count=len(tweets),
                )

                # For each tweet, get commenters
                for tweet in tweets:
                    # Get a fresh account for each tweet to avoid rate limiting
                    reply_account = await pool.get_account()
                    if not reply_account:
                        await asyncio.sleep(1)
                        reply_account = await pool.get_account()
                        if not reply_account:
                            continue

                    try:
                        reply_client = reply_account.get_client()

                        # Get replies/comments using search with conversation_id
                        reply_count = 0
                        try:
                            # Search for tweets in this conversation thread
                            search_results = await reply_client.search_tweet(
                                f"conversation_id:{tweet.id}",
                                product="Latest",
                                count=commenters_per_tweet,
                            )

                            for reply_tweet in search_results:
                                # Skip the original tweet itself
                                if reply_tweet.id == tweet.id:
                                    continue

                                # Get user from reply tweet
                                reply_user = reply_tweet.user
                                if not reply_user:
                                    continue

                                commenter_id = reply_user.id
                                screen_name = reply_user.screen_name

                                if not commenter_id or not screen_name:
                                    continue

                                # Skip if already seen
                                if commenter_id in seen_ids:
                                    continue

                                seen_ids.add(commenter_id)
                                new_users.append(DiscoveredUser(
                                    id=commenter_id,
                                    username=screen_name,
                                    name=reply_user.name or screen_name,
                                    description=reply_user.description or "",
                                    followers_count=reply_user.followers_count or 0,
                                    following_count=reply_user.following_count or 0,
                                    depth=1,  # Commenters are considered depth 1
                                    is_seed=False,
                                    discovered_from=target_user.id,  # Discovered from seed user
                                    discovery_source="comment",
                                    description_urls=getattr(reply_user, "description_urls", None),
                                ))
                                reply_count += 1

                                if reply_count >= commenters_per_tweet:
                                    break

                        except Exception as search_err:
                            error_str = str(search_err)
                            # 404 usually means the tweet was deleted
                            if "404" in error_str:
                                logger.debug(
                                    "search_worker.tweet_deleted_or_inaccessible",
                                    tweet_id=tweet.id,
                                )
                            else:
                                logger.debug(
                                    "search_worker.search_replies_error",
                                    tweet_id=tweet.id,
                                    error=error_str,
                                )

                        logger.debug(
                            "search_worker.tweet_commenters",
                            tweet_id=tweet.id,
                            commenters=reply_count,
                        )

                    except Exception as e:
                        error_msg = str(e)
                        if "TooManyRequests" in error_msg or "rate" in error_msg.lower():
                            reply_account.mark_rate_limited()
                        logger.warning(
                            "search_worker.get_replies_error",
                            tweet_id=tweet.id,
                            error=error_msg,
                        )

                    # Small delay between tweets
                    await asyncio.sleep(0.5)

            except Exception as e:
                logger.warning(
                    "search_worker.crawl_commenters_user_error",
                    user=target_user.username,
                    error=str(e),
                )

            # Delay between users
            await asyncio.sleep(1)

        logger.info(
            "search_worker.crawl_commenters_completed",
            total_commenters=len(new_users),
        )

        return new_users


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
