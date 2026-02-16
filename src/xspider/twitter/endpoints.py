"""Twitter GraphQL endpoint definitions and request builders."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import quote


class EndpointType(str, Enum):
    """GraphQL endpoint types."""

    USER_BY_SCREEN_NAME = "UserByScreenName"
    USER_BY_REST_ID = "UserByRestId"
    FOLLOWING = "Following"
    FOLLOWERS = "Followers"
    USER_TWEETS = "UserTweets"
    USER_TWEETS_AND_REPLIES = "UserTweetsAndReplies"
    TWEET_DETAIL = "TweetDetail"
    SEARCH_TIMELINE = "SearchTimeline"
    HOME_TIMELINE = "HomeTimeline"
    LIKES = "Likes"


@dataclass(frozen=True)
class GraphQLEndpoint:
    """GraphQL endpoint configuration."""

    endpoint_type: EndpointType
    query_id: str
    operation_name: str
    method: str = "GET"


# Twitter GraphQL query IDs (extracted from Twitter Web client)
# These may need to be updated periodically as Twitter changes them
GRAPHQL_ENDPOINTS: dict[EndpointType, GraphQLEndpoint] = {
    EndpointType.USER_BY_SCREEN_NAME: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_BY_SCREEN_NAME,
        query_id="G3KGOASz96M-Qu0nwmGXNg",
        operation_name="UserByScreenName",
    ),
    EndpointType.USER_BY_REST_ID: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_BY_REST_ID,
        query_id="QdS5LJDl99iL_KUzckdfNQ",
        operation_name="UserByRestId",
    ),
    EndpointType.FOLLOWING: GraphQLEndpoint(
        endpoint_type=EndpointType.FOLLOWING,
        query_id="iSicc7LrzWGBgDPL0tM_TQ",
        operation_name="Following",
    ),
    EndpointType.FOLLOWERS: GraphQLEndpoint(
        endpoint_type=EndpointType.FOLLOWERS,
        query_id="rRXFSG5vR6drKr5M37YOTw",
        operation_name="Followers",
    ),
    EndpointType.USER_TWEETS: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_TWEETS,
        query_id="V1ze5q3ijDS1VeLwLY0m7g",
        operation_name="UserTweets",
    ),
    EndpointType.USER_TWEETS_AND_REPLIES: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_TWEETS_AND_REPLIES,
        query_id="E4wA5vo2sjVyvpliUffSCw",
        operation_name="UserTweetsAndReplies",
    ),
    EndpointType.TWEET_DETAIL: GraphQLEndpoint(
        endpoint_type=EndpointType.TWEET_DETAIL,
        query_id="VWFGPVAGkZMGRKGe3GFFnA",
        operation_name="TweetDetail",
    ),
    EndpointType.SEARCH_TIMELINE: GraphQLEndpoint(
        endpoint_type=EndpointType.SEARCH_TIMELINE,
        query_id="gkjsKepM6gl_HmFWoWKfgg",
        operation_name="SearchTimeline",
    ),
    EndpointType.HOME_TIMELINE: GraphQLEndpoint(
        endpoint_type=EndpointType.HOME_TIMELINE,
        query_id="HZmNLvTusg0cHcgSn1oBbA",
        operation_name="HomeTimeline",
    ),
    EndpointType.LIKES: GraphQLEndpoint(
        endpoint_type=EndpointType.LIKES,
        query_id="eSSNbhECHHWWALkkQq-YTA",
        operation_name="Likes",
    ),
}


# Base features for GraphQL requests
BASE_FEATURES: dict[str, bool] = {
    "responsive_web_media_download_video_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

USER_FEATURES: dict[str, bool] = {
    "hidden_profile_likes_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

TIMELINE_FEATURES: dict[str, bool] = {
    **BASE_FEATURES,
    "interactive_text_enabled": True,
    "responsive_web_text_conversations_enabled": False,
    "responsive_web_home_pinned_timelines_enabled": True,
}


class RequestBuilder:
    """Builds GraphQL request parameters."""

    BASE_URL = "https://twitter.com/i/api/graphql"

    @classmethod
    def build_url(cls, endpoint: GraphQLEndpoint) -> str:
        """Build the full GraphQL URL."""
        return f"{cls.BASE_URL}/{endpoint.query_id}/{endpoint.operation_name}"

    @classmethod
    def build_user_by_screen_name_params(
        cls, screen_name: str
    ) -> dict[str, str]:
        """Build parameters for UserByScreenName query."""
        variables = {
            "screen_name": screen_name,
            "withSafetyModeUserFields": True,
        }
        field_toggles = {
            "withAuxiliaryUserLabels": False,
        }
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(USER_FEATURES, separators=(",", ":")),
            "fieldToggles": json.dumps(field_toggles, separators=(",", ":")),
        }

    @classmethod
    def build_user_by_rest_id_params(cls, user_id: str) -> dict[str, str]:
        """Build parameters for UserByRestId query."""
        variables = {
            "userId": user_id,
            "withSafetyModeUserFields": True,
        }
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(USER_FEATURES, separators=(",", ":")),
        }

    @classmethod
    def build_following_params(
        cls,
        user_id: str,
        count: int = 20,
        cursor: str | None = None,
    ) -> dict[str, str]:
        """Build parameters for Following query."""
        variables: dict[str, Any] = {
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
        }
        if cursor:
            variables["cursor"] = cursor
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(BASE_FEATURES, separators=(",", ":")),
        }

    @classmethod
    def build_followers_params(
        cls,
        user_id: str,
        count: int = 20,
        cursor: str | None = None,
    ) -> dict[str, str]:
        """Build parameters for Followers query."""
        variables: dict[str, Any] = {
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
        }
        if cursor:
            variables["cursor"] = cursor
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(BASE_FEATURES, separators=(",", ":")),
        }

    @classmethod
    def build_user_tweets_params(
        cls,
        user_id: str,
        count: int = 20,
        cursor: str | None = None,
        include_replies: bool = False,
    ) -> dict[str, str]:
        """Build parameters for UserTweets query."""
        variables: dict[str, Any] = {
            "userId": user_id,
            "count": count,
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(TIMELINE_FEATURES, separators=(",", ":")),
        }

    @classmethod
    def build_tweet_detail_params(cls, tweet_id: str) -> dict[str, str]:
        """Build parameters for TweetDetail query."""
        variables = {
            "focalTweetId": tweet_id,
            "with_rux_injections": False,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(TIMELINE_FEATURES, separators=(",", ":")),
            "fieldToggles": json.dumps(
                {"withArticleRichContentState": True, "withArticlePlainText": False},
                separators=(",", ":"),
            ),
        }

    @classmethod
    def build_search_params(
        cls,
        query: str,
        count: int = 20,
        cursor: str | None = None,
        product: str = "Top",
    ) -> dict[str, str]:
        """Build parameters for SearchTimeline query."""
        variables: dict[str, Any] = {
            "rawQuery": query,
            "count": count,
            "querySource": "typed_query",
            "product": product,
        }
        if cursor:
            variables["cursor"] = cursor
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(TIMELINE_FEATURES, separators=(",", ":")),
        }

    @classmethod
    def build_likes_params(
        cls,
        user_id: str,
        count: int = 20,
        cursor: str | None = None,
    ) -> dict[str, str]:
        """Build parameters for Likes query."""
        variables: dict[str, Any] = {
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": False,
            "withVoice": True,
            "withV2Timeline": True,
        }
        if cursor:
            variables["cursor"] = cursor
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(TIMELINE_FEATURES, separators=(",", ":")),
        }


def get_endpoint(endpoint_type: EndpointType) -> GraphQLEndpoint:
    """Get GraphQL endpoint configuration."""
    return GRAPHQL_ENDPOINTS[endpoint_type]


def build_graphql_url(endpoint_type: EndpointType) -> str:
    """Build full GraphQL URL for an endpoint type."""
    endpoint = get_endpoint(endpoint_type)
    return RequestBuilder.build_url(endpoint)
