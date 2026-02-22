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
    DMRequestBuilder,
    EndpointType,
    MutationRequestBuilder,
    RequestBuilder,
    RestEndpoints,
    get_endpoint,
    is_mutation_endpoint,
)
from xspider.twitter.models import (
    FollowingPage,
    Tweet,
    TwitterUser,
)
from xspider.twitter.proxy_pool import ProxyPool
from xspider.twitter.rate_limiter import AdaptiveRateLimiter


logger = get_logger(__name__)


# Twitter/X Web client headers
DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "Origin": "https://x.com",
    "Referer": "https://x.com/",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
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

    async def search_users(
        self,
        query: str,
        *,
        max_results: int = 50,
    ) -> AsyncIterator[TwitterUser]:
        """Search for users by keyword in their bio/profile.

        Args:
            query: Search query string.
            max_results: Maximum number of users to return.

        Yields:
            TwitterUser objects matching the search.
        """
        cursor = None
        count = 0

        while count < max_results:
            # Build params using RequestBuilder
            params = RequestBuilder.build_search_params(
                query=query,
                count=min(20, max_results - count),
                cursor=cursor,
                product="People",  # Search for people/users
            )

            try:
                data = await self._request(EndpointType.SEARCH_TIMELINE, params)
            except Exception as e:
                logger.warning(
                    "search_users.request_failed",
                    query=query,
                    error=str(e),
                )
                break

            # Parse search results
            try:
                instructions = (
                    data.get("data", {})
                    .get("search_by_raw_query", {})
                    .get("search_timeline", {})
                    .get("timeline", {})
                    .get("instructions", [])
                )

                users_found = False
                next_cursor = None

                for instruction in instructions:
                    if instruction.get("type") == "TimelineAddEntries":
                        entries = instruction.get("entries", [])
                        for entry in entries:
                            content = entry.get("content", {})
                            item_content = content.get("itemContent", {})

                            if item_content.get("itemType") == "TimelineUser":
                                user_result = item_content.get("user_results", {}).get("result", {})
                                if user_result and user_result.get("__typename") == "User":
                                    legacy = user_result.get("legacy", {})
                                    user = TwitterUser(
                                        id=user_result.get("rest_id", ""),
                                        username=legacy.get("screen_name", ""),
                                        name=legacy.get("name", ""),
                                        description=legacy.get("description", ""),
                                        followers_count=legacy.get("followers_count", 0),
                                        following_count=legacy.get("friends_count", 0),
                                        tweet_count=legacy.get("statuses_count", 0),
                                        verified=legacy.get("verified", False),
                                        profile_image_url=legacy.get("profile_image_url_https", ""),
                                        created_at=legacy.get("created_at"),
                                    )
                                    yield user
                                    users_found = True
                                    count += 1
                                    if count >= max_results:
                                        return

                            # Check for cursor
                            if content.get("cursorType") == "Bottom":
                                next_cursor = content.get("value")

                cursor = next_cursor
                if not users_found or not cursor:
                    break

            except Exception as e:
                logger.warning(
                    "search_users.parse_failed",
                    query=query,
                    error=str(e),
                )
                break

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "token_pool": self.token_pool.get_stats(),
            "proxy_pool": self.proxy_pool.get_stats(),
            "rate_limiter": self.rate_limiter.get_stats(),
        }

    # =========================================================================
    # Mutation Methods (POST) - Growth & Engagement System
    # =========================================================================

    async def _post_request(
        self,
        endpoint_type: EndpointType,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Make a GraphQL POST mutation request with retry logic.

        Args:
            endpoint_type: The mutation endpoint type.
            payload: The request payload (variables, features, queryId).

        Returns:
            The response data dictionary.

        Raises:
            ScrapingError: If the request fails after retries.
            RateLimitError: If rate limited.
            AuthenticationError: If authentication fails.
        """
        if not is_mutation_endpoint(endpoint_type):
            raise ScrapingError(f"Endpoint {endpoint_type.value} is not a mutation endpoint")

        endpoint = get_endpoint(endpoint_type)
        url = RequestBuilder.build_url(endpoint)
        endpoint_name = f"mutation_{endpoint_type.value}"

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
                        response = await client.post(url, json=payload)
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
                        return self._validate_mutation_response(data)

                    except httpx.HTTPError as e:
                        if self._current_token:
                            self.token_pool.mark_token_error(self._current_token)
                        if self._current_proxy:
                            self.proxy_pool.mark_proxy_error(self._current_proxy)

                        logger.warning(
                            "HTTP error during mutation request",
                            extra={
                                "endpoint": endpoint_name,
                                "error": str(e),
                                "attempt": attempt.retry_state.attempt_number,
                            },
                        )
                        raise

        raise ScrapingError(f"Mutation failed after {self.config.max_retries} attempts")

    def _validate_mutation_response(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate mutation response for errors."""
        if "errors" in data:
            errors = data["errors"]
            error_messages = [e.get("message", "Unknown error") for e in errors]
            error_str = "; ".join(error_messages)

            for error in errors:
                code = error.get("code")
                message = error.get("message", "")

                if code == 32:
                    raise AuthenticationError("Could not authenticate")
                elif code == 88:
                    raise RateLimitError("Rate limit exceeded")
                elif code == 187:
                    raise ScrapingError("Status is a duplicate")
                elif code == 226:
                    raise ScrapingError("Tweet looks like spam")
                elif code == 385:
                    raise ScrapingError("Cannot reply to this tweet")
                elif "suspended" in message.lower():
                    raise ScrapingError("Account is suspended")

            logger.warning("GraphQL mutation errors", extra={"errors": error_str})
            raise ScrapingError(f"Mutation failed: {error_str}")

        return data

    async def post_tweet(
        self,
        text: str,
        media_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Post a new tweet.

        Args:
            text: Tweet text content (max 280 characters).
            media_ids: Optional list of media IDs to attach.

        Returns:
            Dictionary with tweet data including tweet_id.

        Raises:
            ScrapingError: If posting fails.
        """
        payload = MutationRequestBuilder.build_create_tweet_payload(
            text=text,
            media_ids=media_ids,
        )
        data = await self._post_request(EndpointType.CREATE_TWEET, payload)

        tweet_result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )

        return {
            "tweet_id": tweet_result.get("rest_id"),
            "text": text,
            "raw_response": tweet_result,
        }

    async def reply_to_tweet(
        self,
        tweet_id: str,
        text: str,
        media_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Reply to an existing tweet.

        Args:
            tweet_id: ID of the tweet to reply to.
            text: Reply text content.
            media_ids: Optional list of media IDs to attach.

        Returns:
            Dictionary with reply tweet data.

        Raises:
            ScrapingError: If replying fails.
        """
        payload = MutationRequestBuilder.build_create_tweet_payload(
            text=text,
            reply_to_tweet_id=tweet_id,
            media_ids=media_ids,
        )
        data = await self._post_request(EndpointType.CREATE_TWEET, payload)

        tweet_result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )

        return {
            "tweet_id": tweet_result.get("rest_id"),
            "reply_to_tweet_id": tweet_id,
            "text": text,
            "raw_response": tweet_result,
        }

    async def quote_tweet(
        self,
        tweet_id: str,
        text: str,
    ) -> dict[str, Any]:
        """Quote an existing tweet.

        Args:
            tweet_id: ID of the tweet to quote.
            text: Quote text content.

        Returns:
            Dictionary with quote tweet data.
        """
        payload = MutationRequestBuilder.build_create_tweet_payload(
            text=text,
            quote_tweet_id=tweet_id,
        )
        data = await self._post_request(EndpointType.CREATE_TWEET, payload)

        tweet_result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )

        return {
            "tweet_id": tweet_result.get("rest_id"),
            "quoted_tweet_id": tweet_id,
            "text": text,
            "raw_response": tweet_result,
        }

    async def delete_tweet(self, tweet_id: str) -> bool:
        """Delete a tweet.

        Args:
            tweet_id: ID of the tweet to delete.

        Returns:
            True if deletion was successful.
        """
        payload = MutationRequestBuilder.build_delete_tweet_payload(tweet_id)
        data = await self._post_request(EndpointType.DELETE_TWEET, payload)

        # Check if deletion was successful
        result = data.get("data", {}).get("delete_tweet", {})
        return result.get("tweet_results") is not None or "delete_tweet" in data.get("data", {})

    async def like_tweet(self, tweet_id: str) -> bool:
        """Like a tweet.

        Args:
            tweet_id: ID of the tweet to like.

        Returns:
            True if like was successful.
        """
        payload = MutationRequestBuilder.build_favorite_tweet_payload(tweet_id)
        data = await self._post_request(EndpointType.FAVORITE_TWEET, payload)

        result = data.get("data", {}).get("favorite_tweet")
        return result == "Done" or result is not None

    async def unlike_tweet(self, tweet_id: str) -> bool:
        """Unlike a tweet.

        Args:
            tweet_id: ID of the tweet to unlike.

        Returns:
            True if unlike was successful.
        """
        payload = MutationRequestBuilder.build_unfavorite_tweet_payload(tweet_id)
        data = await self._post_request(EndpointType.UNFAVORITE_TWEET, payload)

        result = data.get("data", {}).get("unfavorite_tweet")
        return result == "Done" or result is not None

    async def retweet(self, tweet_id: str) -> dict[str, Any]:
        """Retweet a tweet.

        Args:
            tweet_id: ID of the tweet to retweet.

        Returns:
            Dictionary with retweet data.
        """
        payload = MutationRequestBuilder.build_retweet_payload(tweet_id)
        data = await self._post_request(EndpointType.CREATE_RETWEET, payload)

        retweet_result = (
            data.get("data", {})
            .get("create_retweet", {})
            .get("retweet_results", {})
            .get("result", {})
        )

        return {
            "retweet_id": retweet_result.get("rest_id"),
            "source_tweet_id": tweet_id,
            "raw_response": retweet_result,
        }

    async def unretweet(self, tweet_id: str) -> bool:
        """Remove a retweet.

        Args:
            tweet_id: ID of the original tweet to unretweet.

        Returns:
            True if unretweet was successful.
        """
        payload = MutationRequestBuilder.build_delete_retweet_payload(tweet_id)
        data = await self._post_request(EndpointType.DELETE_RETWEET, payload)

        result = data.get("data", {}).get("unretweet", {})
        return "source_tweet_results" in result or result is not None

    async def check_can_reply(self, tweet_id: str) -> dict[str, Any]:
        """Check if the current user can reply to a tweet.

        Args:
            tweet_id: ID of the tweet to check.

        Returns:
            Dictionary with reply permissions.
        """
        try:
            tweet = await self.get_tweet(tweet_id)
            return {
                "can_reply": True,
                "tweet_id": tweet_id,
                "author_id": tweet.author.id,
                "author_screen_name": tweet.author.screen_name,
            }
        except ScrapingError as e:
            return {
                "can_reply": False,
                "tweet_id": tweet_id,
                "reason": str(e),
            }

    # ========================================================================
    # Direct Message Operations
    # ========================================================================

    async def send_dm(
        self,
        recipient_id: str,
        text: str,
        media_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a direct message to a user.

        Args:
            recipient_id: Twitter user ID of the recipient.
            text: Message text content.
            media_id: Optional media ID to attach.

        Returns:
            Dictionary with DM data including message_id.

        Raises:
            ScrapingError: If the request fails.
            AuthenticationError: If authentication fails.
        """
        # Get current user ID for conversation ID
        current_user_id = await self._get_current_user_id()

        payload = DMRequestBuilder.build_send_dm_to_user_payload(
            recipient_id=recipient_id,
            sender_id=current_user_id,
            text=text,
            media_id=media_id,
        )

        await self.rate_limiter.acquire("dm_send")

        async with self._get_client() as client:
            try:
                response = await client.post(
                    RestEndpoints.DM_NEW,
                    data=payload,  # REST API uses form data, not JSON
                    headers={
                        **DEFAULT_HEADERS,
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )

                if response.status_code == 403:
                    raise AuthenticationError(
                        "Cannot send DM: user may have DMs disabled or you are blocked"
                    )

                if response.status_code == 429:
                    raise RateLimitError("DM rate limit exceeded")

                if response.status_code != 200:
                    raise ScrapingError(
                        f"DM send failed with status {response.status_code}: {response.text}"
                    )

                data = response.json()

                # Extract message details from response
                entries = data.get("entries", [])
                message_data = {}

                for entry in entries:
                    message = entry.get("message", {})
                    if message:
                        message_data = message.get("message_data", {})
                        break

                logger.info(
                    "dm.sent",
                    recipient_id=recipient_id,
                    text_length=len(text),
                )

                return {
                    "success": True,
                    "recipient_id": recipient_id,
                    "message_id": message_data.get("id"),
                    "text": text,
                    "created_at": message_data.get("time"),
                    "raw_response": data,
                }

            except httpx.HTTPError as e:
                logger.error("dm.send_failed", error=str(e))
                raise ScrapingError(f"Failed to send DM: {e}") from e

    async def _get_current_user_id(self) -> str:
        """Get the current authenticated user's ID.

        Returns:
            The user ID string.

        Raises:
            AuthenticationError: If unable to get current user.
        """
        if not self._current_token:
            await self._rotate_token()

        if not self._current_token:
            raise AuthenticationError("No valid token available")

        # If we have the user ID cached in the token, use it
        if hasattr(self._current_token, "user_id") and self._current_token.user_id:
            return self._current_token.user_id

        # Otherwise, we need to make a request to get the current user
        # This uses the viewer endpoint
        async with self._get_client() as client:
            try:
                response = await client.get(
                    "https://x.com/i/api/1.1/account/verify_credentials.json",
                    params={"skip_status": "true"},
                )

                if response.status_code != 200:
                    raise AuthenticationError("Failed to get current user info")

                data = response.json()
                return str(data.get("id_str", data.get("id")))

            except httpx.HTTPError as e:
                raise AuthenticationError(f"Failed to get current user: {e}") from e

    async def check_dm_availability(self, user_id: str) -> dict[str, Any]:
        """Check if a user can receive DMs.

        Args:
            user_id: Twitter user ID to check.

        Returns:
            Dictionary with DM availability info.
        """
        try:
            user_data = await self.get_user_by_id(user_id)
            if not user_data:
                return {
                    "user_id": user_id,
                    "can_dm": False,
                    "reason": "User not found",
                }

            legacy = user_data.get("legacy", {})

            # Check various DM-related fields
            can_dm = legacy.get("can_dm", False)
            protected = legacy.get("protected", False)

            return {
                "user_id": user_id,
                "can_dm": can_dm,
                "protected": protected,
                "following": legacy.get("following", False),
                "followed_by": legacy.get("followed_by", False),
                "reason": None if can_dm else "DMs may be restricted",
            }

        except Exception as e:
            return {
                "user_id": user_id,
                "can_dm": False,
                "reason": str(e),
            }

    async def close(self) -> None:
        """Close the client and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
