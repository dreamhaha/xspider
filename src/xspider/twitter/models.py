"""Twitter data models using Pydantic."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class UserVerificationType(str, Enum):
    """Twitter user verification types."""

    NONE = "none"
    BLUE = "blue"
    BUSINESS = "business"
    GOVERNMENT = "government"


class TwitterUser(BaseModel):
    """Twitter user profile data."""

    id: str = Field(..., description="User's unique Twitter ID")
    rest_id: str = Field(default="", description="REST API ID")
    screen_name: str = Field(..., description="Twitter handle without @")
    name: str = Field(default="", description="Display name")
    description: str = Field(default="", description="User bio")
    location: str = Field(default="", description="User location")
    url: str = Field(default="", description="User website URL")
    profile_image_url: str = Field(default="", description="Profile image URL")
    profile_banner_url: str = Field(default="", description="Profile banner URL")
    followers_count: int = Field(default=0, ge=0)
    following_count: int = Field(default=0, ge=0)
    tweet_count: int = Field(default=0, ge=0)
    listed_count: int = Field(default=0, ge=0)
    created_at: datetime | None = Field(default=None)
    verified: bool = Field(default=False)
    verification_type: UserVerificationType = Field(default=UserVerificationType.NONE)
    is_protected: bool = Field(default=False)
    is_blue_verified: bool = Field(default=False)
    professional: dict[str, Any] = Field(default_factory=dict)

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_created_at(cls, v: Any) -> datetime | None:
        """Parse Twitter date format."""
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.strptime(v, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                return None
        return None

    @classmethod
    def from_graphql_response(cls, data: dict[str, Any]) -> TwitterUser:
        """Parse user from GraphQL response."""
        legacy = data.get("legacy", {})
        return cls(
            id=data.get("id", ""),
            rest_id=data.get("rest_id", ""),
            screen_name=legacy.get("screen_name", ""),
            name=legacy.get("name", ""),
            description=legacy.get("description", ""),
            location=legacy.get("location", ""),
            url=legacy.get("url", ""),
            profile_image_url=legacy.get(
                "profile_image_url_https", ""
            ).replace("_normal", "_400x400"),
            profile_banner_url=legacy.get("profile_banner_url", ""),
            followers_count=legacy.get("followers_count", 0),
            following_count=legacy.get("friends_count", 0),
            tweet_count=legacy.get("statuses_count", 0),
            listed_count=legacy.get("listed_count", 0),
            created_at=legacy.get("created_at"),
            verified=legacy.get("verified", False),
            is_protected=legacy.get("protected", False),
            is_blue_verified=data.get("is_blue_verified", False),
            verification_type=cls._parse_verification_type(data),
            professional=data.get("professional", {}),
        )

    @staticmethod
    def _parse_verification_type(data: dict[str, Any]) -> UserVerificationType:
        """Parse verification type from GraphQL response."""
        if data.get("is_blue_verified"):
            return UserVerificationType.BLUE
        affiliates = data.get("affiliates_highlighted_label", {})
        if affiliates.get("label", {}).get("badge", {}).get("url", ""):
            return UserVerificationType.BUSINESS
        if data.get("legacy", {}).get("verified"):
            return UserVerificationType.GOVERNMENT
        return UserVerificationType.NONE


class MediaType(str, Enum):
    """Tweet media types."""

    PHOTO = "photo"
    VIDEO = "video"
    GIF = "animated_gif"


class TweetMedia(BaseModel):
    """Tweet media attachment."""

    id: str
    media_type: MediaType
    url: str
    preview_url: str = ""
    width: int = 0
    height: int = 0
    duration_ms: int = 0


class Tweet(BaseModel):
    """Tweet data model."""

    id: str = Field(..., description="Tweet ID")
    rest_id: str = Field(default="", description="REST API ID")
    text: str = Field(default="", description="Tweet text content")
    full_text: str = Field(default="", description="Full tweet text")
    created_at: datetime | None = Field(default=None)
    user_id: str = Field(default="", description="Author user ID")
    user: TwitterUser | None = Field(default=None)
    reply_count: int = Field(default=0, ge=0)
    retweet_count: int = Field(default=0, ge=0)
    like_count: int = Field(default=0, ge=0)
    quote_count: int = Field(default=0, ge=0)
    view_count: int = Field(default=0, ge=0)
    bookmark_count: int = Field(default=0, ge=0)
    is_retweet: bool = Field(default=False)
    is_quote: bool = Field(default=False)
    is_reply: bool = Field(default=False)
    in_reply_to_tweet_id: str | None = Field(default=None)
    in_reply_to_user_id: str | None = Field(default=None)
    quoted_tweet_id: str | None = Field(default=None)
    retweeted_tweet_id: str | None = Field(default=None)
    language: str = Field(default="")
    source: str = Field(default="")
    media: list[TweetMedia] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    conversation_id: str = Field(default="")

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_created_at(cls, v: Any) -> datetime | None:
        """Parse Twitter date format."""
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            try:
                return datetime.strptime(v, "%a %b %d %H:%M:%S %z %Y")
            except ValueError:
                return None
        return None

    @classmethod
    def from_graphql_response(
        cls, data: dict[str, Any], user: TwitterUser | None = None
    ) -> Tweet:
        """Parse tweet from GraphQL response."""
        legacy = data.get("legacy", {})
        core = data.get("core", {})
        user_results = core.get("user_results", {}).get("result", {})

        parsed_user = user
        if user_results and not user:
            parsed_user = TwitterUser.from_graphql_response(user_results)

        return cls(
            id=data.get("id", ""),
            rest_id=data.get("rest_id", ""),
            text=legacy.get("text", legacy.get("full_text", "")),
            full_text=legacy.get("full_text", legacy.get("text", "")),
            created_at=legacy.get("created_at"),
            user_id=legacy.get("user_id_str", ""),
            user=parsed_user,
            reply_count=legacy.get("reply_count", 0),
            retweet_count=legacy.get("retweet_count", 0),
            like_count=legacy.get("favorite_count", 0),
            quote_count=legacy.get("quote_count", 0),
            view_count=cls._parse_view_count(data),
            bookmark_count=legacy.get("bookmark_count", 0),
            is_retweet=legacy.get("retweeted_status_result") is not None,
            is_quote=data.get("quoted_status_result") is not None,
            is_reply=legacy.get("in_reply_to_status_id_str") is not None,
            in_reply_to_tweet_id=legacy.get("in_reply_to_status_id_str"),
            in_reply_to_user_id=legacy.get("in_reply_to_user_id_str"),
            quoted_tweet_id=cls._extract_quoted_tweet_id(data),
            retweeted_tweet_id=cls._extract_retweeted_tweet_id(legacy),
            language=legacy.get("lang", ""),
            source=cls._parse_source(data),
            media=cls._parse_media(legacy),
            urls=cls._parse_urls(legacy),
            hashtags=cls._parse_hashtags(legacy),
            mentions=cls._parse_mentions(legacy),
            conversation_id=legacy.get("conversation_id_str", ""),
        )

    @staticmethod
    def _parse_view_count(data: dict[str, Any]) -> int:
        """Parse view count from GraphQL response."""
        views = data.get("views", {})
        count = views.get("count", "0")
        try:
            return int(count)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_source(data: dict[str, Any]) -> str:
        """Parse tweet source."""
        source = data.get("source", "")
        if "<a" in source:
            import re

            match = re.search(r">(.+?)</a>", source)
            return match.group(1) if match else source
        return source

    @staticmethod
    def _parse_media(legacy: dict[str, Any]) -> list[TweetMedia]:
        """Parse media from tweet legacy data."""
        media_list = []
        entities = legacy.get("extended_entities", legacy.get("entities", {}))
        for media in entities.get("media", []):
            media_type = MediaType(media.get("type", "photo"))
            url = media.get("media_url_https", "")
            if media_type == MediaType.VIDEO:
                variants = media.get("video_info", {}).get("variants", [])
                video_variants = [
                    v for v in variants if v.get("content_type") == "video/mp4"
                ]
                if video_variants:
                    best = max(video_variants, key=lambda x: x.get("bitrate", 0))
                    url = best.get("url", url)
            media_list.append(
                TweetMedia(
                    id=media.get("id_str", ""),
                    media_type=media_type,
                    url=url,
                    preview_url=media.get("media_url_https", ""),
                    width=media.get("original_info", {}).get("width", 0),
                    height=media.get("original_info", {}).get("height", 0),
                    duration_ms=media.get("video_info", {}).get("duration_millis", 0),
                )
            )
        return media_list

    @staticmethod
    def _parse_urls(legacy: dict[str, Any]) -> list[str]:
        """Parse URLs from tweet entities."""
        urls = []
        for url_entity in legacy.get("entities", {}).get("urls", []):
            expanded = url_entity.get("expanded_url", url_entity.get("url", ""))
            if expanded:
                urls.append(expanded)
        return urls

    @staticmethod
    def _parse_hashtags(legacy: dict[str, Any]) -> list[str]:
        """Parse hashtags from tweet entities."""
        return [
            h.get("text", "")
            for h in legacy.get("entities", {}).get("hashtags", [])
            if h.get("text")
        ]

    @staticmethod
    def _parse_mentions(legacy: dict[str, Any]) -> list[str]:
        """Parse mentions from tweet entities."""
        return [
            m.get("screen_name", "")
            for m in legacy.get("entities", {}).get("user_mentions", [])
            if m.get("screen_name")
        ]

    @staticmethod
    def _extract_quoted_tweet_id(data: dict[str, Any]) -> str | None:
        """Extract quoted tweet ID."""
        quoted = data.get("quoted_status_result", {}).get("result", {})
        return quoted.get("rest_id") if quoted else None

    @staticmethod
    def _extract_retweeted_tweet_id(legacy: dict[str, Any]) -> str | None:
        """Extract retweeted tweet ID."""
        retweeted = legacy.get("retweeted_status_result", {}).get("result", {})
        return retweeted.get("rest_id") if retweeted else None


class Following(BaseModel):
    """Represents a following relationship."""

    source_user_id: str = Field(..., description="User who follows")
    target_user_id: str = Field(..., description="User being followed")
    target_user: TwitterUser | None = Field(default=None)
    cursor: str = Field(default="", description="Pagination cursor")
    collected_at: datetime = Field(default_factory=datetime.utcnow)


class FollowingPage(BaseModel):
    """Page of following results with cursor."""

    users: list[TwitterUser] = Field(default_factory=list)
    next_cursor: str | None = Field(default=None)
    previous_cursor: str | None = Field(default=None)
    total_count: int | None = Field(default=None)


class UserSearchResult(BaseModel):
    """User search result."""

    users: list[TwitterUser] = Field(default_factory=list)
    next_cursor: str | None = Field(default=None)
