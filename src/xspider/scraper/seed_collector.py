"""Seed collector for initial user discovery via Bio search and Lists."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from xspider.core import ScrapingError, get_logger
from xspider.twitter import TwitterGraphQLClient as TwitterClient, TwitterUser


@dataclass(frozen=True)
class SeedProgress:
    """Progress update for seed collection."""

    source: str  # "bio_search" or "list"
    query_or_list_id: str
    users_found: int
    total_so_far: int


ProgressCallback = Callable[[SeedProgress], None]


class SeedCollector:
    """Collects seed users via Bio keyword search and Twitter Lists.

    Usage:
        async with SeedCollector(client) as collector:
            async for user in collector.search_by_bio(keywords=["AI", "ML"]):
                print(user.username)

            async for user in collector.scrape_list(list_id="123456"):
                print(user.username)
    """

    def __init__(
        self,
        client: TwitterClient,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Initialize the seed collector.

        Args:
            client: Twitter API client instance.
            progress_callback: Optional callback for progress updates.
        """
        self._client = client
        self._progress_callback = progress_callback
        self._logger = get_logger(__name__)
        self._total_collected = 0

    async def __aenter__(self) -> "SeedCollector":
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
            "seed_collector.closed",
            total_collected=self._total_collected,
        )

    def _emit_progress(self, progress: SeedProgress) -> None:
        """Emit progress update if callback is set."""
        if self._progress_callback is not None:
            self._progress_callback(progress)

    async def search_by_bio(
        self,
        keywords: list[str],
        *,
        max_results_per_keyword: int = 100,
        deduplicate: bool = True,
    ) -> AsyncIterator[TwitterUser]:
        """Search for users with keywords in their bio.

        Args:
            keywords: List of keywords to search for in user bios.
            max_results_per_keyword: Maximum results per keyword search.
            deduplicate: Whether to skip already-seen user IDs.

        Yields:
            TwitterUser objects matching the search criteria.

        Raises:
            ScrapingError: If the search operation fails.
        """
        seen_ids: set[str] = set()

        for keyword in keywords:
            self._logger.info(
                "seed_collector.bio_search.start",
                keyword=keyword,
                max_results=max_results_per_keyword,
            )

            users_found = 0

            try:
                async for user in self._client.search_users(
                    query=keyword,
                    max_results=max_results_per_keyword,
                ):
                    if deduplicate and user.id in seen_ids:
                        continue

                    seen_ids.add(user.id)
                    users_found += 1
                    self._total_collected += 1

                    self._logger.debug(
                        "seed_collector.bio_search.user_found",
                        user_id=user.id,
                        username=user.username,
                        keyword=keyword,
                    )

                    yield user

                self._emit_progress(
                    SeedProgress(
                        source="bio_search",
                        query_or_list_id=keyword,
                        users_found=users_found,
                        total_so_far=self._total_collected,
                    )
                )

            except Exception as e:
                self._logger.error(
                    "seed_collector.bio_search.error",
                    keyword=keyword,
                    error=str(e),
                )
                raise ScrapingError(
                    f"Bio search failed for keyword '{keyword}'",
                    endpoint="search_users",
                ) from e

        self._logger.info(
            "seed_collector.bio_search.complete",
            keywords_count=len(keywords),
            unique_users=len(seen_ids),
        )

    async def scrape_list(
        self,
        list_id: str,
        *,
        max_members: int | None = None,
    ) -> AsyncIterator[TwitterUser]:
        """Scrape members from a Twitter List.

        Args:
            list_id: The ID of the Twitter List to scrape.
            max_members: Maximum number of members to retrieve (None for all).

        Yields:
            TwitterUser objects that are members of the list.

        Raises:
            ScrapingError: If the list scraping operation fails.
        """
        self._logger.info(
            "seed_collector.list_scrape.start",
            list_id=list_id,
            max_members=max_members,
        )

        users_found = 0

        try:
            async for user in self._client.get_list_members(
                list_id=list_id,
                max_results=max_members,
            ):
                users_found += 1
                self._total_collected += 1

                self._logger.debug(
                    "seed_collector.list_scrape.user_found",
                    user_id=user.id,
                    username=user.username,
                    list_id=list_id,
                )

                yield user

            self._emit_progress(
                SeedProgress(
                    source="list",
                    query_or_list_id=list_id,
                    users_found=users_found,
                    total_so_far=self._total_collected,
                )
            )

        except Exception as e:
            self._logger.error(
                "seed_collector.list_scrape.error",
                list_id=list_id,
                error=str(e),
            )
            raise ScrapingError(
                f"List scraping failed for list '{list_id}'",
                endpoint="get_list_members",
            ) from e

        self._logger.info(
            "seed_collector.list_scrape.complete",
            list_id=list_id,
            users_found=users_found,
        )

    async def scrape_lists(
        self,
        list_ids: list[str],
        *,
        max_members_per_list: int | None = None,
        deduplicate: bool = True,
    ) -> AsyncIterator[TwitterUser]:
        """Scrape members from multiple Twitter Lists.

        Args:
            list_ids: List of Twitter List IDs to scrape.
            max_members_per_list: Maximum members per list (None for all).
            deduplicate: Whether to skip already-seen user IDs.

        Yields:
            TwitterUser objects from all lists.

        Raises:
            ScrapingError: If any list scraping operation fails.
        """
        seen_ids: set[str] = set()

        for list_id in list_ids:
            async for user in self.scrape_list(
                list_id=list_id,
                max_members=max_members_per_list,
            ):
                if deduplicate and user.id in seen_ids:
                    continue

                seen_ids.add(user.id)
                yield user

        self._logger.info(
            "seed_collector.lists_scrape.complete",
            lists_count=len(list_ids),
            unique_users=len(seen_ids),
        )

    async def collect_all(
        self,
        *,
        bio_keywords: list[str] | None = None,
        list_ids: list[str] | None = None,
        max_results_per_keyword: int = 100,
        max_members_per_list: int | None = None,
        deduplicate: bool = True,
    ) -> AsyncIterator[TwitterUser]:
        """Collect seeds from multiple sources in a single pass.

        Args:
            bio_keywords: Keywords for bio search.
            list_ids: Twitter List IDs to scrape.
            max_results_per_keyword: Max results per keyword search.
            max_members_per_list: Max members per list.
            deduplicate: Whether to skip duplicates across all sources.

        Yields:
            TwitterUser objects from all sources.
        """
        seen_ids: set[str] = set()

        if bio_keywords:
            async for user in self.search_by_bio(
                keywords=bio_keywords,
                max_results_per_keyword=max_results_per_keyword,
                deduplicate=False,  # We handle dedup here
            ):
                if deduplicate and user.id in seen_ids:
                    continue
                seen_ids.add(user.id)
                yield user

        if list_ids:
            async for user in self.scrape_lists(
                list_ids=list_ids,
                max_members_per_list=max_members_per_list,
                deduplicate=False,  # We handle dedup here
            ):
                if deduplicate and user.id in seen_ids:
                    continue
                seen_ids.add(user.id)
                yield user

        self._logger.info(
            "seed_collector.collect_all.complete",
            unique_users=len(seen_ids),
        )
