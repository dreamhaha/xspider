"""Twitter GraphQL endpoint definitions and request builders."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import quote


class EndpointType(str, Enum):
    """GraphQL endpoint types."""

    # Query endpoints (GET)
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

    # Mutation endpoints (POST) - for Growth & Engagement System
    CREATE_TWEET = "CreateTweet"
    CREATE_REPLY = "CreateReply"  # Actually uses CreateTweet with reply params
    DELETE_TWEET = "DeleteTweet"
    FAVORITE_TWEET = "FavoriteTweet"
    UNFAVORITE_TWEET = "UnfavoriteTweet"
    CREATE_RETWEET = "CreateRetweet"
    DELETE_RETWEET = "DeleteRetweet"
    SEND_DM = "SendDM"  # Direct Message (REST API, not GraphQL)
    FOLLOW_USER = "FollowUser"
    UNFOLLOW_USER = "UnfollowUser"


@dataclass(frozen=True)
class GraphQLEndpoint:
    """GraphQL endpoint configuration."""

    endpoint_type: EndpointType
    query_id: str
    operation_name: str
    method: str = "GET"


# Twitter GraphQL query IDs (extracted from twikit library)
# These may need to be updated periodically as Twitter changes them
# Last updated: 2026-02-20 from https://github.com/d60/twikit
GRAPHQL_ENDPOINTS: dict[EndpointType, GraphQLEndpoint] = {
    EndpointType.USER_BY_SCREEN_NAME: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_BY_SCREEN_NAME,
        query_id="NimuplG1OB7Fd2btCLdBOw",
        operation_name="UserByScreenName",
    ),
    EndpointType.USER_BY_REST_ID: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_BY_REST_ID,
        query_id="tD8zKvQzwY3kdx5yz6YmOw",
        operation_name="UserByRestId",
    ),
    EndpointType.FOLLOWING: GraphQLEndpoint(
        endpoint_type=EndpointType.FOLLOWING,
        query_id="2vUj-_Ek-UmBVDNtd8OnQA",
        operation_name="Following",
    ),
    EndpointType.FOLLOWERS: GraphQLEndpoint(
        endpoint_type=EndpointType.FOLLOWERS,
        query_id="gC_lyAxZOptAMLCJX5UhWw",
        operation_name="Followers",
    ),
    EndpointType.USER_TWEETS: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_TWEETS,
        query_id="QWF3SzpHmykQHsQMixG0cg",
        operation_name="UserTweets",
    ),
    EndpointType.USER_TWEETS_AND_REPLIES: GraphQLEndpoint(
        endpoint_type=EndpointType.USER_TWEETS_AND_REPLIES,
        query_id="vMkJyzx1wdmvOeeNG0n6Wg",
        operation_name="UserTweetsAndReplies",
    ),
    EndpointType.TWEET_DETAIL: GraphQLEndpoint(
        endpoint_type=EndpointType.TWEET_DETAIL,
        query_id="U0HTv-bAWTBYylwEMT7x5A",
        operation_name="TweetDetail",
    ),
    EndpointType.SEARCH_TIMELINE: GraphQLEndpoint(
        endpoint_type=EndpointType.SEARCH_TIMELINE,
        query_id="flaR-PUMshxFWZWPNpq4zA",
        operation_name="SearchTimeline",
    ),
    EndpointType.HOME_TIMELINE: GraphQLEndpoint(
        endpoint_type=EndpointType.HOME_TIMELINE,
        query_id="-X_hcgQzmHGl29-UXxz4sw",
        operation_name="HomeTimeline",
    ),
    EndpointType.LIKES: GraphQLEndpoint(
        endpoint_type=EndpointType.LIKES,
        query_id="IohM3gxQHfvWePH5E3KuNA",
        operation_name="Likes",
    ),
    # Mutation endpoints (POST)
    EndpointType.CREATE_TWEET: GraphQLEndpoint(
        endpoint_type=EndpointType.CREATE_TWEET,
        query_id="SiM_cAu83R0wnrpmKQQSEw",
        operation_name="CreateTweet",
        method="POST",
    ),
    EndpointType.DELETE_TWEET: GraphQLEndpoint(
        endpoint_type=EndpointType.DELETE_TWEET,
        query_id="VaenaVgh5q5ih7kvyVjgtg",
        operation_name="DeleteTweet",
        method="POST",
    ),
    EndpointType.FAVORITE_TWEET: GraphQLEndpoint(
        endpoint_type=EndpointType.FAVORITE_TWEET,
        query_id="lI07N6Otwv1PhnEgXILM7A",
        operation_name="FavoriteTweet",
        method="POST",
    ),
    EndpointType.UNFAVORITE_TWEET: GraphQLEndpoint(
        endpoint_type=EndpointType.UNFAVORITE_TWEET,
        query_id="ZYKSe-w7KEslx3JhSIk5LA",
        operation_name="UnfavoriteTweet",
        method="POST",
    ),
    EndpointType.CREATE_RETWEET: GraphQLEndpoint(
        endpoint_type=EndpointType.CREATE_RETWEET,
        query_id="ojPdsZsimiJrUGLR1sjUtA",
        operation_name="CreateRetweet",
        method="POST",
    ),
    EndpointType.DELETE_RETWEET: GraphQLEndpoint(
        endpoint_type=EndpointType.DELETE_RETWEET,
        query_id="iQtK4dl5hBmXewYZuEOKVw",
        operation_name="DeleteRetweet",
        method="POST",
    ),
}


# Base features for GraphQL requests (from twikit library)
BASE_FEATURES: dict[str, bool] = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_media_download_video_enabled": False,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
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

# Timeline features - same as base features for compatibility
TIMELINE_FEATURES: dict[str, bool] = BASE_FEATURES


class RequestBuilder:
    """Builds GraphQL request parameters."""

    BASE_URL = "https://x.com/i/api/graphql"

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


# ============================================================================
# Mutation Endpoints (POST) - for Growth & Engagement System
# ============================================================================


MUTATION_FEATURES: dict[str, bool] = {
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "articles_preview_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "responsive_web_media_download_video_enabled": True,
}


class MutationRequestBuilder:
    """Builds mutation request payloads for POST endpoints."""

    @classmethod
    def build_create_tweet_payload(
        cls,
        text: str,
        reply_to_tweet_id: str | None = None,
        quote_tweet_id: str | None = None,
        media_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build payload for CreateTweet mutation.

        Args:
            text: Tweet text content
            reply_to_tweet_id: Tweet ID to reply to (optional)
            quote_tweet_id: Tweet ID to quote (optional)
            media_ids: List of media IDs to attach (optional)

        Returns:
            Dict payload for POST request body
        """
        variables: dict[str, Any] = {
            "tweet_text": text,
            "dark_request": False,
            "media": {
                "media_entities": [],
                "possibly_sensitive": False,
            },
            "semantic_annotation_ids": [],
        }

        # Add reply context if replying to a tweet
        if reply_to_tweet_id:
            variables["reply"] = {
                "in_reply_to_tweet_id": reply_to_tweet_id,
                "exclude_reply_user_ids": [],
            }

        # Add quote tweet context
        if quote_tweet_id:
            variables["attachment_url"] = f"https://twitter.com/i/web/status/{quote_tweet_id}"

        # Add media if provided
        if media_ids:
            variables["media"]["media_entities"] = [
                {"media_id": mid, "tagged_users": []} for mid in media_ids
            ]

        return {
            "variables": variables,
            "features": MUTATION_FEATURES,
            "queryId": GRAPHQL_ENDPOINTS[EndpointType.CREATE_TWEET].query_id,
        }

    @classmethod
    def build_delete_tweet_payload(cls, tweet_id: str) -> dict[str, Any]:
        """Build payload for DeleteTweet mutation."""
        return {
            "variables": {
                "tweet_id": tweet_id,
                "dark_request": False,
            },
            "queryId": GRAPHQL_ENDPOINTS[EndpointType.DELETE_TWEET].query_id,
        }

    @classmethod
    def build_favorite_tweet_payload(cls, tweet_id: str) -> dict[str, Any]:
        """Build payload for FavoriteTweet mutation."""
        return {
            "variables": {
                "tweet_id": tweet_id,
            },
            "queryId": GRAPHQL_ENDPOINTS[EndpointType.FAVORITE_TWEET].query_id,
        }

    @classmethod
    def build_unfavorite_tweet_payload(cls, tweet_id: str) -> dict[str, Any]:
        """Build payload for UnfavoriteTweet mutation."""
        return {
            "variables": {
                "tweet_id": tweet_id,
            },
            "queryId": GRAPHQL_ENDPOINTS[EndpointType.UNFAVORITE_TWEET].query_id,
        }

    @classmethod
    def build_retweet_payload(cls, tweet_id: str) -> dict[str, Any]:
        """Build payload for CreateRetweet mutation."""
        return {
            "variables": {
                "tweet_id": tweet_id,
                "dark_request": False,
            },
            "queryId": GRAPHQL_ENDPOINTS[EndpointType.CREATE_RETWEET].query_id,
        }

    @classmethod
    def build_delete_retweet_payload(cls, tweet_id: str) -> dict[str, Any]:
        """Build payload for DeleteRetweet mutation."""
        return {
            "variables": {
                "source_tweet_id": tweet_id,
                "dark_request": False,
            },
            "queryId": GRAPHQL_ENDPOINTS[EndpointType.DELETE_RETWEET].query_id,
        }


def is_mutation_endpoint(endpoint_type: EndpointType) -> bool:
    """Check if an endpoint type is a mutation (POST) endpoint."""
    endpoint = GRAPHQL_ENDPOINTS.get(endpoint_type)
    return endpoint is not None and endpoint.method == "POST"


# ============================================================================
# REST API Endpoints (non-GraphQL)
# ============================================================================

REST_API_BASE = "https://x.com/i/api"


class RestEndpoints:
    """REST API endpoint URLs (non-GraphQL)."""

    # Direct Messages
    DM_NEW = f"{REST_API_BASE}/1.1/dm/new2.json"
    DM_CONVERSATION = f"{REST_API_BASE}/1.1/dm/conversation"
    DM_INBOX = f"{REST_API_BASE}/1.1/dm/inbox_initial_state.json"

    # User Actions
    FOLLOW = f"{REST_API_BASE}/1.1/friendships/create.json"
    UNFOLLOW = f"{REST_API_BASE}/1.1/friendships/destroy.json"


class DMRequestBuilder:
    """Builds request payloads for Direct Message operations."""

    @classmethod
    def build_send_dm_payload(
        cls,
        recipient_id: str,
        text: str,
        media_id: str | None = None,
    ) -> dict[str, Any]:
        """Build payload for sending a direct message.

        Args:
            recipient_id: Twitter user ID of the recipient
            text: Message text content
            media_id: Optional media ID to attach

        Returns:
            Dict payload for POST request body
        """
        payload: dict[str, Any] = {
            "conversation_id": f"{recipient_id}-{recipient_id}",  # Will be replaced with actual user ID
            "recipient_ids": False,
            "request_id": cls._generate_request_id(),
            "text": text,
            "cards_platform": "Web-12",
            "include_cards": 1,
            "include_quote_count": True,
            "dm_users": False,
        }

        if media_id:
            payload["media_id"] = media_id

        return payload

    @classmethod
    def build_send_dm_to_user_payload(
        cls,
        recipient_id: str,
        sender_id: str,
        text: str,
        media_id: str | None = None,
    ) -> dict[str, Any]:
        """Build payload for sending a DM with sender context.

        Args:
            recipient_id: Twitter user ID of the recipient
            sender_id: Twitter user ID of the sender (current user)
            text: Message text content
            media_id: Optional media ID to attach

        Returns:
            Dict payload for POST request body
        """
        import uuid

        # Conversation ID is sorted concatenation of user IDs
        ids = sorted([recipient_id, sender_id])
        conversation_id = f"{ids[0]}-{ids[1]}"

        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "recipient_ids": recipient_id,
            "request_id": str(uuid.uuid4()),
            "text": text,
            "cards_platform": "Web-12",
            "include_cards": 1,
            "include_quote_count": True,
            "dm_users": False,
        }

        if media_id:
            payload["media_id"] = media_id

        return payload

    @staticmethod
    def _generate_request_id() -> str:
        """Generate a unique request ID."""
        import uuid
        return str(uuid.uuid4())
