"""Twitter GraphQL client infrastructure."""

from xspider.twitter.auth import TokenPool, TokenState
from xspider.twitter.client import ClientConfig, TwitterGraphQLClient
from xspider.twitter.endpoints import (
    EndpointType,
    GraphQLEndpoint,
    RequestBuilder,
    build_graphql_url,
    get_endpoint,
)
from xspider.twitter.models import (
    Following,
    FollowingPage,
    MediaType,
    Tweet,
    TweetMedia,
    TwitterUser,
    UserSearchResult,
    UserVerificationType,
)
from xspider.twitter.proxy_pool import ProxyPool, ProxyProtocol, ProxyState
from xspider.twitter.rate_limiter import (
    AdaptiveRateLimiter,
    EndpointRateLimiter,
    TokenBucket,
)

__all__ = [
    # Client
    "TwitterGraphQLClient",
    "ClientConfig",
    # Models
    "TwitterUser",
    "Tweet",
    "TweetMedia",
    "MediaType",
    "Following",
    "FollowingPage",
    "UserSearchResult",
    "UserVerificationType",
    # Endpoints
    "EndpointType",
    "GraphQLEndpoint",
    "RequestBuilder",
    "get_endpoint",
    "build_graphql_url",
    # Auth
    "TokenPool",
    "TokenState",
    # Proxy
    "ProxyPool",
    "ProxyState",
    "ProxyProtocol",
    # Rate Limiter
    "TokenBucket",
    "EndpointRateLimiter",
    "AdaptiveRateLimiter",
]
