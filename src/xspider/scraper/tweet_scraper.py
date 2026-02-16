"""Tweet content scraper for user timelines."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from xspider.core import ScrapingError, get_logger
from xspider.twitter import Tweet, TwitterGraphQLClient as TwitterClient


@dataclass(frozen=True)
class TweetScrapeProgress:
    """Progress update for tweet scraping."""

    user_id: str
    username: str
    tweets_scraped: int
    users_completed: int
    total_users: int


@dataclass
class TweetBatch:
    """A batch of tweets from a single user."""

    user_id: str
    username: str
    tweets: list[Tweet] = field(default_factory=list)
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def count(self) -> int:
        """Return the number of tweets in this batch."""
        return len(self.tweets)


@dataclass
class TweetScrapeResult:
    """Result of a tweet scraping operation."""

    users_processed: int
    total_tweets: int
    errors: list[str] = field(default_factory=list)


ProgressCallback = Callable[[TweetScrapeProgress], None]


class TweetScraper:
    """Scraper for fetching tweet content from user timelines.

    Usage:
        async with TweetScraper(client) as scraper:
            async for tweet in scraper.scrape_user_tweets(
                user_id="123",
                max_tweets=100,
            ):
                print(tweet.text)

            async for batch in scraper.scrape_multiple_users(
                user_ids=["123", "456"],
                max_tweets_per_user=50,
            ):
                print(f"{batch.username}: {batch.count} tweets")
    """

    def __init__(
        self,
        client: TwitterClient,
        *,
        progress_callback: ProgressCallback | None = None,
        default_max_tweets: int = 100,
    ) -> None:
        """Initialize the tweet scraper.

        Args:
            client: Twitter API client instance.
            progress_callback: Optional callback for progress updates.
            default_max_tweets: Default max tweets per user.
        """
        self._client = client
        self._progress_callback = progress_callback
        self._default_max_tweets = default_max_tweets
        self._logger = get_logger(__name__)

    async def __aenter__(self) -> "TweetScraper":
        """Enter async context."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Exit async context."""
        self._logger.info("tweet_scraper.closed")

    def _emit_progress(
        self,
        user_id: str,
        username: str,
        tweets_scraped: int,
        users_completed: int,
        total_users: int,
    ) -> None:
        """Emit progress update if callback is set."""
        if self._progress_callback is not None:
            self._progress_callback(
                TweetScrapeProgress(
                    user_id=user_id,
                    username=username,
                    tweets_scraped=tweets_scraped,
                    users_completed=users_completed,
                    total_users=total_users,
                )
            )

    async def scrape_user_tweets(
        self,
        user_id: str,
        *,
        max_tweets: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_retweets: bool = True,
        include_replies: bool = False,
    ) -> AsyncIterator[Tweet]:
        """Scrape tweets from a single user's timeline.

        Args:
            user_id: The user ID to scrape tweets from.
            max_tweets: Maximum number of tweets to retrieve.
            since: Only retrieve tweets after this datetime.
            until: Only retrieve tweets before this datetime.
            include_retweets: Whether to include retweets.
            include_replies: Whether to include replies.

        Yields:
            Tweet objects from the user's timeline.

        Raises:
            ScrapingError: If the scraping operation fails.
        """
        max_tweets = max_tweets or self._default_max_tweets

        self._logger.info(
            "tweet_scraper.user_start",
            user_id=user_id,
            max_tweets=max_tweets,
            since=since.isoformat() if since else None,
            until=until.isoformat() if until else None,
        )

        tweet_count = 0

        try:
            async for tweet in self._client.get_user_tweets(
                user_id=user_id,
                max_results=max_tweets,
                start_time=since,
                end_time=until,
            ):
                # Filter based on options
                if not include_retweets and tweet.is_retweet:
                    continue

                if not include_replies and tweet.is_reply:
                    continue

                tweet_count += 1
                yield tweet

                if max_tweets and tweet_count >= max_tweets:
                    break

        except Exception as e:
            self._logger.error(
                "tweet_scraper.user_error",
                user_id=user_id,
                error=str(e),
            )
            raise ScrapingError(
                f"Failed to scrape tweets for user {user_id}",
                user_id=user_id,
                endpoint="get_user_tweets",
            ) from e

        self._logger.info(
            "tweet_scraper.user_complete",
            user_id=user_id,
            tweet_count=tweet_count,
        )

    async def scrape_user_tweets_batch(
        self,
        user_id: str,
        username: str,
        *,
        max_tweets: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_retweets: bool = True,
        include_replies: bool = False,
    ) -> TweetBatch:
        """Scrape tweets from a user and return as a batch.

        Args:
            user_id: The user ID to scrape tweets from.
            username: The username for reference.
            max_tweets: Maximum number of tweets to retrieve.
            since: Only retrieve tweets after this datetime.
            until: Only retrieve tweets before this datetime.
            include_retweets: Whether to include retweets.
            include_replies: Whether to include replies.

        Returns:
            TweetBatch containing all scraped tweets.

        Raises:
            ScrapingError: If the scraping operation fails.
        """
        tweets: list[Tweet] = []

        async for tweet in self.scrape_user_tweets(
            user_id=user_id,
            max_tweets=max_tweets,
            since=since,
            until=until,
            include_retweets=include_retweets,
            include_replies=include_replies,
        ):
            tweets.append(tweet)

        return TweetBatch(
            user_id=user_id,
            username=username,
            tweets=tweets,
        )

    async def scrape_multiple_users(
        self,
        user_ids: list[str],
        *,
        max_tweets_per_user: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_retweets: bool = True,
        include_replies: bool = False,
        skip_errors: bool = True,
    ) -> AsyncIterator[TweetBatch]:
        """Scrape tweets from multiple users.

        Args:
            user_ids: List of user IDs to scrape.
            max_tweets_per_user: Maximum tweets per user.
            since: Only retrieve tweets after this datetime.
            until: Only retrieve tweets before this datetime.
            include_retweets: Whether to include retweets.
            include_replies: Whether to include replies.
            skip_errors: Whether to continue on errors.

        Yields:
            TweetBatch for each successfully scraped user.

        Raises:
            ScrapingError: If skip_errors is False and an error occurs.
        """
        total_users = len(user_ids)
        users_completed = 0

        self._logger.info(
            "tweet_scraper.multiple_start",
            user_count=total_users,
            max_tweets_per_user=max_tweets_per_user,
        )

        for user_id in user_ids:
            try:
                # Get username for the batch
                user = await self._client.get_user_by_id(user_id)
                username = user.username

                tweets: list[Tweet] = []

                async for tweet in self.scrape_user_tweets(
                    user_id=user_id,
                    max_tweets=max_tweets_per_user,
                    since=since,
                    until=until,
                    include_retweets=include_retweets,
                    include_replies=include_replies,
                ):
                    tweets.append(tweet)

                batch = TweetBatch(
                    user_id=user_id,
                    username=username,
                    tweets=tweets,
                )

                users_completed += 1

                self._emit_progress(
                    user_id=user_id,
                    username=username,
                    tweets_scraped=len(tweets),
                    users_completed=users_completed,
                    total_users=total_users,
                )

                yield batch

            except Exception as e:
                self._logger.error(
                    "tweet_scraper.user_failed",
                    user_id=user_id,
                    error=str(e),
                )
                if not skip_errors:
                    raise ScrapingError(
                        f"Failed to scrape tweets for user {user_id}",
                        user_id=user_id,
                    ) from e

        self._logger.info(
            "tweet_scraper.multiple_complete",
            users_completed=users_completed,
            total_users=total_users,
        )

    async def scrape_all_tweets(
        self,
        user_ids: list[str],
        *,
        max_tweets_per_user: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_retweets: bool = True,
        include_replies: bool = False,
        skip_errors: bool = True,
    ) -> AsyncIterator[Tweet]:
        """Scrape all tweets from multiple users as a flat stream.

        Args:
            user_ids: List of user IDs to scrape.
            max_tweets_per_user: Maximum tweets per user.
            since: Only retrieve tweets after this datetime.
            until: Only retrieve tweets before this datetime.
            include_retweets: Whether to include retweets.
            include_replies: Whether to include replies.
            skip_errors: Whether to continue on errors.

        Yields:
            Individual Tweet objects from all users.
        """
        async for batch in self.scrape_multiple_users(
            user_ids=user_ids,
            max_tweets_per_user=max_tweets_per_user,
            since=since,
            until=until,
            include_retweets=include_retweets,
            include_replies=include_replies,
            skip_errors=skip_errors,
        ):
            for tweet in batch.tweets:
                yield tweet

    async def scrape_with_result(
        self,
        user_ids: list[str],
        *,
        max_tweets_per_user: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_retweets: bool = True,
        include_replies: bool = False,
    ) -> tuple[list[TweetBatch], TweetScrapeResult]:
        """Scrape tweets and return both batches and statistics.

        Args:
            user_ids: List of user IDs to scrape.
            max_tweets_per_user: Maximum tweets per user.
            since: Only retrieve tweets after this datetime.
            until: Only retrieve tweets before this datetime.
            include_retweets: Whether to include retweets.
            include_replies: Whether to include replies.

        Returns:
            Tuple of (list of TweetBatch, TweetScrapeResult).
        """
        batches: list[TweetBatch] = []
        errors: list[str] = []
        total_tweets = 0

        for user_id in user_ids:
            try:
                user = await self._client.get_user_by_id(user_id)

                batch = await self.scrape_user_tweets_batch(
                    user_id=user_id,
                    username=user.username,
                    max_tweets=max_tweets_per_user,
                    since=since,
                    until=until,
                    include_retweets=include_retweets,
                    include_replies=include_replies,
                )

                batches.append(batch)
                total_tweets += batch.count

            except Exception as e:
                error_msg = f"Failed to scrape {user_id}: {e}"
                self._logger.error(
                    "tweet_scraper.scrape_error",
                    user_id=user_id,
                    error=str(e),
                )
                errors.append(error_msg)

        result = TweetScrapeResult(
            users_processed=len(batches),
            total_tweets=total_tweets,
            errors=errors,
        )

        return batches, result

    async def get_recent_tweets(
        self,
        user_id: str,
        count: int = 10,
    ) -> list[Tweet]:
        """Get the most recent tweets from a user.

        Convenience method for quick tweet retrieval.

        Args:
            user_id: The user ID to get tweets from.
            count: Number of recent tweets to retrieve.

        Returns:
            List of the most recent tweets.
        """
        tweets: list[Tweet] = []

        async for tweet in self.scrape_user_tweets(
            user_id=user_id,
            max_tweets=count,
        ):
            tweets.append(tweet)

        return tweets
