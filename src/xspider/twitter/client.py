"""Twitter GraphQL client with integrated token pool, proxy rotation, and rate limiting."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from xspider.core import (
    AuthenticationError,
    RateLimitError,
    ScrapingError,
    get_logger,
    get_settings,
)
from xspider.core.config import TwitterToken
from xspider.twitter.auth import TokenPool
from xspider.twitter.endpoints import (
    EndpointType,
    RequestBuilder,
    get_endpoint,
)
from xspider.twitter.models import (
    FollowingPage,
    Tweet,
    TwitterUser,
)
from xspider.twitter.proxy_pool import ProxyPool
from xspider.twitter.rate_limiter import AdaptiveRateLimiter


logger = get_logger(__name__)


# Twitter Web client headers
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Content-Type": "application/json",
    "Origin": "https://twitter.com",
    "Referer": "https://twitter.com/",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "X-Twitter-Active-User": "yes",
    "X-Twitter-Client-Language": "en",
}


@dataclass
class ClientConfig:
    """Configuration for Twitter GraphQL client."""

    timeout: float = 30.0
    max_retries: int = 3
    retry_wait_min: float = 1.0
    retry_wait_max: float = 10.0
    rate_limit_capacity: float = 50.0
    rate_limit_refill_rate: float = 1.0


@dataclass
class TwitterGraphQLClient:
    """Twitter GraphQL API client with integrated rate limiting and rotation."""

    token_pool: TokenPool
    proxy_pool: ProxyPool
    rate_limiter: AdaptiveRateLimiter = field(default_factory=AdaptiveRateLimiter)
    config: ClientConfig = field(default_factory=ClientConfig)
    _client: httpx.AsyncClient | None = field(default=None, init=False)
    _current_token: TwitterToken | None = field(default=None, init=False)
    _current_proxy: str | None = field(default=None, init=False)

    @classmethod
    def from_settings(cls) -> "TwitterGraphQLClient":
        """Create client from application settings."""
        settings = get_settings()
        token_pool = TokenPool.from_tokens(settings.twitter_tokens)
        proxy_pool = ProxyPool.from_urls(settings.proxy_urls)
        return cls(token_pool=token_pool, proxy_pool=proxy_pool)

    async def _create_client(
        self,
        token: TwitterToken,
        proxy_url: str | None = None,
    ) -> httpx.AsyncClient:
        """Create an httpx client with authentication."""
        headers = {
            **DEFAULT_HEADERS,
            "Authorization": f"Bearer {token.bearer_token}",
            "X-Csrf-Token": token.ct0,
        }
        cookies = {
            "ct0": token.ct0,
            "auth_token": token.auth_token,
        }

        transport = None
        if proxy_url:
            transport = httpx.AsyncHTTPTransport(proxy=proxy_url)

        return httpx.AsyncClient(
            headers=headers,
            cookies=cookies,
            timeout=httpx.Timeout(self.config.timeout),
            transport=transport,
            follow_redirects=True,
            http2=True,
        )

    @asynccontextmanager
    async def _get_client(self) -> AsyncIterator[httpx.AsyncClient]:
        """Get an httpx client with current token and proxy."""
        token = await self.token_pool.get_token()
        proxy = await self.proxy_pool.get_proxy()

        self._current_token = token
        self._current_proxy = proxy

        client = await self._create_client(token, proxy)
        try:
            yield client
        finally:
            await client.aclose()

    def _parse_rate_limit_headers(
        self, response: httpx.Response, endpoint: str
    ) -> None:
        """Parse and apply rate limit headers from response."""
        headers = response.headers

        limit = headers.get("x-rate-limit-limit")
        remaining = headers.get("x-rate-limit-remaining")
        reset = headers.get("x-rate-limit-reset")

        self.rate_limiter.on_rate_limit_headers(
            endpoint=endpoint,
            limit=int(limit) if limit else None,
            remaining=int(remaining) if remaining else None,
            reset=float(reset) if reset else None,
        )

    def _handle_error_response(
        self, response: httpx.Response, endpoint: str
    ) -> None:
        """Handle error responses and update pool states."""
        if response.status_code == 429:
            retry_after = response.headers.get("retry-after")
            reset_after = float(retry_after) if retry_after else 900.0

            self.rate_limiter.on_rate_limit(endpoint, reset_after)

            if self._current_token:
                self.token_pool.mark_token_rate_limited(
                    self._current_token, reset_after
                )

            raise RateLimitError(
                f"Rate limited on {endpoint}",
                retry_after=int(reset_after),
            )

        elif response.status_code == 401:
            if self._current_token:
                self.token_pool.mark_token_invalid(self._current_token)
            raise AuthenticationError("Authentication failed")

        elif response.status_code == 403:
            if self._current_token:
                self.token_pool.mark_token_error(self._current_token)
            raise AuthenticationError("Access forbidden")

        elif response.status_code >= 500:
            if self._current_proxy:
                self.proxy_pool.mark_proxy_error(self._current_proxy)
            raise ScrapingError(f"Server error: {response.status_code}")

        elif response.status_code >= 400:
            raise ScrapingError(
                f"Client error: {response.status_code} - {response.text[:200]}"
            )

    async def _request(
        self,
        endpoint_type: EndpointType,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """Make a GraphQL request with retry logic."""
        endpoint = get_endpoint(endpoint_type)
        url = RequestBuilder.build_url(endpoint)
        endpoint_name = endpoint_type.value

        await self.rate_limiter.acquire(endpoint_name)

        start_time = time.time()

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.config.max_retries),
            wait=wait_exponential(
                min=self.config.retry_wait_min,
                max=self.config.retry_wait_max,
            ),
            retry=retry_if_exception_type((ScrapingError, httpx.HTTPError)),
            reraise=True,
        ):
            with attempt:
                async with self._get_client() as client:
                    try:
                        response = await client.get(url, params=params)
                        response_time = (time.time() - start_time) * 1000

                        self._parse_rate_limit_headers(response, endpoint_name)

                        if response.status_code != 200:
                            self._handle_error_response(response, endpoint_name)

                        if self._current_token:
                            self.token_pool.mark_token_success(self._current_token)
                        if self._current_proxy:
                            self.proxy_pool.mark_proxy_success(
                                self._current_proxy, response_time
                            )
                        self.rate_limiter.on_success(endpoint_name)

                        data = response.json()
                        return self._validate_response(data)

                    except httpx.HTTPError as e:
                        if self._current_token:
                            self.token_pool.mark_token_error(self._current_token)
                        if self._current_proxy:
                            self.proxy_pool.mark_proxy_error(self._current_proxy)

                        logger.warning(
                            "HTTP error during request",
                            extra={
                                "endpoint": endpoint_name,
                                "error": str(e),
                                "attempt": attempt.retry_state.attempt_number,
                            },
                        )
                        raise

        raise ScrapingError(f"Request failed after {self.config.max_retries} attempts")

    def _validate_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate GraphQL response for errors."""
        if "errors" in data:
            errors = data["errors"]
            error_messages = [e.get("message", "Unknown error") for e in errors]
            error_str = "; ".join(error_messages)

            for error in errors:
                code = error.get("code")
                if code == 32:
                    raise AuthenticationError("Could not authenticate")
                elif code == 34:
                    raise ScrapingError("Resource not found")
                elif code == 50:
                    raise ScrapingError("User not found")
                elif code == 63:
                    raise ScrapingError("User has been suspended")
                elif code == 88:
                    raise RateLimitError("Rate limit exceeded")

            logger.warning("GraphQL errors in response", extra={"errors": error_str})

        return data

    async def get_user_by_screen_name(self, screen_name: str) -> TwitterUser:
        """Get user profile by screen name.

        Args:
            screen_name: Twitter handle without @.

        Returns:
            TwitterUser object.

        Raises:
            ScrapingError: If user not found or request fails.
        """
        params = RequestBuilder.build_user_by_screen_name_params(screen_name)
        data = await self._request(EndpointType.USER_BY_SCREEN_NAME, params)

        user_data = data.get("data", {}).get("user", {}).get("result", {})
        if not user_data:
            raise ScrapingError(f"User not found: {screen_name}")

        if user_data.get("__typename") == "UserUnavailable":
            reason = user_data.get("reason", "Unknown")
            raise ScrapingError(f"User unavailable: {screen_name} ({reason})")

        return TwitterUser.from_graphql_response(user_data)

    async def get_user_by_id(self, user_id: str) -> TwitterUser:
        """Get user profile by ID.

        Args:
            user_id: Twitter user ID.

        Returns:
            TwitterUser object.
        """
        params = RequestBuilder.build_user_by_rest_id_params(user_id)
        data = await self._request(EndpointType.USER_BY_REST_ID, params)

        user_data = data.get("data", {}).get("user", {}).get("result", {})
        if not user_data:
            raise ScrapingError(f"User not found: {user_id}")

        return TwitterUser.from_graphql_response(user_data)

    async def get_following(
        self,
        user_id: str,
        count: int = 20,
        cursor: str | None = None,
    ) -> FollowingPage:
        """Get users that a user is following.

        Args:
            user_id: Twitter user ID.
            count: Number of users per page (max 100).
            cursor: Pagination cursor.

        Returns:
            FollowingPage with users and cursors.
        """
        params = RequestBuilder.build_following_params(user_id, count, cursor)
        data = await self._request(EndpointType.FOLLOWING, params)

        return self._parse_user_timeline(data)

    async def get_followers(
        self,
        user_id: str,
        count: int = 20,
        cursor: str | None = None,
    ) -> FollowingPage:
        """Get followers of a user.

        Args:
            user_id: Twitter user ID.
            count: Number of users per page (max 100).
            cursor: Pagination cursor.

        Returns:
            FollowingPage with users and cursors.
        """
        params = RequestBuilder.build_followers_params(user_id, count, cursor)
        data = await self._request(EndpointType.FOLLOWERS, params)

        return self._parse_user_timeline(data)

    def _parse_user_timeline(self, data: dict[str, Any]) -> FollowingPage:
        """Parse user timeline response (following/followers)."""
        users = []
        next_cursor = None
        previous_cursor = None

        timeline = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline", {})
            .get("timeline", {})
        )
        instructions = timeline.get("instructions", [])

        for instruction in instructions:
            if instruction.get("type") == "TimelineAddEntries":
                entries = instruction.get("entries", [])
                for entry in entries:
                    entry_id = entry.get("entryId", "")

                    if entry_id.startswith("user-"):
                        item_content = (
                            entry.get("content", {})
                            .get("itemContent", {})
                            .get("user_results", {})
                            .get("result", {})
                        )
                        if item_content and item_content.get("__typename") == "User":
                            users.append(
                                TwitterUser.from_graphql_response(item_content)
                            )

                    elif entry_id.startswith("cursor-bottom-"):
                        next_cursor = entry.get("content", {}).get("value")

                    elif entry_id.startswith("cursor-top-"):
                        previous_cursor = entry.get("content", {}).get("value")

        return FollowingPage(
            users=users,
            next_cursor=next_cursor,
            previous_cursor=previous_cursor,
        )

    async def get_user_tweets(
        self,
        user_id: str,
        count: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[Tweet], str | None]:
        """Get tweets from a user's timeline.

        Args:
            user_id: Twitter user ID.
            count: Number of tweets per page.
            cursor: Pagination cursor.

        Returns:
            Tuple of (tweets, next_cursor).
        """
        params = RequestBuilder.build_user_tweets_params(user_id, count, cursor)
        data = await self._request(EndpointType.USER_TWEETS, params)

        return self._parse_tweet_timeline(data)

    async def get_tweet(self, tweet_id: str) -> Tweet:
        """Get a single tweet by ID.

        Args:
            tweet_id: Tweet ID.

        Returns:
            Tweet object.
        """
        params = RequestBuilder.build_tweet_detail_params(tweet_id)
        data = await self._request(EndpointType.TWEET_DETAIL, params)

        instructions = (
            data.get("data", {})
            .get("tweetResult", {})
            .get("result", {})
            .get("timeline", {})
            .get("instructions", [])
        )

        for instruction in instructions:
            if instruction.get("type") == "TimelineAddEntries":
                for entry in instruction.get("entries", []):
                    if entry.get("entryId", "").startswith("tweet-"):
                        tweet_result = (
                            entry.get("content", {})
                            .get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result", {})
                        )
                        if tweet_result:
                            return Tweet.from_graphql_response(tweet_result)

        raise ScrapingError(f"Tweet not found: {tweet_id}")

    def _parse_tweet_timeline(
        self, data: dict[str, Any]
    ) -> tuple[list[Tweet], str | None]:
        """Parse tweet timeline response."""
        tweets = []
        next_cursor = None

        timeline = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
        )
        instructions = timeline.get("instructions", [])

        for instruction in instructions:
            if instruction.get("type") == "TimelineAddEntries":
                entries = instruction.get("entries", [])
                for entry in entries:
                    entry_id = entry.get("entryId", "")

                    if entry_id.startswith("tweet-"):
                        tweet_result = (
                            entry.get("content", {})
                            .get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result", {})
                        )
                        if tweet_result and tweet_result.get("__typename") == "Tweet":
                            tweets.append(Tweet.from_graphql_response(tweet_result))

                    elif entry_id.startswith("cursor-bottom-"):
                        next_cursor = entry.get("content", {}).get("value")

        return tweets, next_cursor

    async def iter_following(
        self,
        user_id: str,
        max_users: int | None = None,
        page_size: int = 20,
    ) -> AsyncIterator[TwitterUser]:
        """Iterate over all users that a user is following.

        Args:
            user_id: Twitter user ID.
            max_users: Maximum users to retrieve (None for all).
            page_size: Users per page.

        Yields:
            TwitterUser objects.
        """
        cursor = None
        count = 0

        while True:
            page = await self.get_following(user_id, page_size, cursor)

            for user in page.users:
                yield user
                count += 1
                if max_users and count >= max_users:
                    return

            if not page.next_cursor:
                break

            cursor = page.next_cursor

    async def iter_followers(
        self,
        user_id: str,
        max_users: int | None = None,
        page_size: int = 20,
    ) -> AsyncIterator[TwitterUser]:
        """Iterate over all followers of a user.

        Args:
            user_id: Twitter user ID.
            max_users: Maximum users to retrieve (None for all).
            page_size: Users per page.

        Yields:
            TwitterUser objects.
        """
        cursor = None
        count = 0

        while True:
            page = await self.get_followers(user_id, page_size, cursor)

            for user in page.users:
                yield user
                count += 1
                if max_users and count >= max_users:
                    return

            if not page.next_cursor:
                break

            cursor = page.next_cursor

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "token_pool": self.token_pool.get_stats(),
            "proxy_pool": self.proxy_pool.get_stats(),
            "rate_limiter": self.rate_limiter.get_stats(),
        }

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
