"""SQLAlchemy ORM models for admin module."""

from __future__ import annotations

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from xspider.storage.models import Base


class UserRole(str, PyEnum):
    """User role enumeration."""

    ADMIN = "admin"
    USER = "user"


class AccountStatus(str, PyEnum):
    """Twitter account status enumeration."""

    ACTIVE = "active"
    RATE_LIMITED = "rate_limited"
    BANNED = "banned"
    NEEDS_VERIFY = "needs_verify"
    ERROR = "error"


class ProxyProtocol(str, PyEnum):
    """Proxy protocol enumeration."""

    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class ProxyStatus(str, PyEnum):
    """Proxy status enumeration."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class SearchStatus(str, PyEnum):
    """Search task status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TransactionType(str, PyEnum):
    """Credit transaction type enumeration."""

    RECHARGE = "recharge"
    SEARCH = "search"
    LLM_CALL = "llm_call"
    REFUND = "refund"
    MONITOR = "monitor"  # 网红监控
    COMMENTER_ANALYSIS = "commenter_analysis"  # 评论者分析


class LLMProvider(str, PyEnum):
    """LLM provider enumeration."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    KIMI = "kimi"


class AdminUser(Base):
    """Admin/user account model."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.USER, nullable=False
    )
    credits: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    searches: Mapped[list["UserSearch"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    credit_transactions: Mapped[list["CreditTransaction"]] = relationship(
        back_populates="user",
        foreign_keys="CreditTransaction.user_id",
        cascade="all, delete-orphan",
    )
    created_accounts: Mapped[list["TwitterAccount"]] = relationship(
        back_populates="created_by_user", foreign_keys="TwitterAccount.created_by"
    )
    created_proxies: Mapped[list["ProxyServer"]] = relationship(
        back_populates="created_by_user", foreign_keys="ProxyServer.created_by"
    )

    __table_args__ = (
        Index("idx_admin_users_username", "username"),
        Index("idx_admin_users_email", "email"),
    )

    @property
    def is_admin(self) -> bool:
        """Check if user is an admin."""
        return self.role == UserRole.ADMIN


class TwitterAccount(Base):
    """Twitter account for scraping."""

    __tablename__ = "twitter_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(100))
    bearer_token: Mapped[str] = mapped_column(Text, nullable=False)
    ct0: Mapped[str] = mapped_column(Text, nullable=False)
    auth_token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus), default=AccountStatus.ACTIVE, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    rate_limit_reset: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    created_by_user: Mapped["AdminUser | None"] = relationship(
        back_populates="created_accounts", foreign_keys=[created_by]
    )

    __table_args__ = (
        Index("idx_twitter_accounts_status", "status"),
        Index("idx_twitter_accounts_created_by", "created_by"),
    )


class ProxyServer(Base):
    """Proxy server for scraping."""

    __tablename__ = "proxy_servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[ProxyProtocol] = mapped_column(
        Enum(ProxyProtocol), default=ProxyProtocol.HTTP, nullable=False
    )
    status: Mapped[ProxyStatus] = mapped_column(
        Enum(ProxyStatus), default=ProxyStatus.ACTIVE, nullable=False
    )
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_time: Mapped[float | None] = mapped_column(Float)
    success_rate: Mapped[float] = mapped_column(Float, default=100.0)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    failed_requests: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )

    # Relationships
    created_by_user: Mapped["AdminUser | None"] = relationship(
        back_populates="created_proxies", foreign_keys=[created_by]
    )

    __table_args__ = (
        Index("idx_proxy_servers_status", "status"),
        Index("idx_proxy_servers_created_by", "created_by"),
    )


class UserSearch(Base):
    """User search task record."""

    __tablename__ = "user_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    keywords: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100))
    seeds_found: Mapped[int] = mapped_column(Integer, default=0)
    users_crawled: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[SearchStatus] = mapped_column(
        Enum(SearchStatus), default=SearchStatus.PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    user: Mapped["AdminUser"] = relationship(back_populates="searches")
    discovered_influencers: Mapped[list["DiscoveredInfluencer"]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )
    llm_usages: Mapped[list["LLMUsage"]] = relationship(
        back_populates="search", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_user_searches_user_id", "user_id"),
        Index("idx_user_searches_status", "status"),
        Index("idx_user_searches_created_at", "created_at"),
    )


class DiscoveredInfluencer(Base):
    """Discovered influencer from search."""

    __tablename__ = "discovered_influencers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user_searches.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    twitter_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    screen_name: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    pagerank_score: Mapped[float] = mapped_column(Float, default=0.0)
    hidden_score: Mapped[float] = mapped_column(Float, default=0.0)
    is_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance_score: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    search: Mapped["UserSearch"] = relationship(back_populates="discovered_influencers")
    owner: Mapped["AdminUser"] = relationship()

    __table_args__ = (
        Index("idx_discovered_influencers_search_id", "search_id"),
        Index("idx_discovered_influencers_pagerank", "pagerank_score"),
        Index("idx_discovered_influencers_hidden", "hidden_score"),
    )


class CreditTransaction(Base):
    """Credit transaction record."""

    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text)
    search_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_searches.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )

    # Relationships
    user: Mapped["AdminUser"] = relationship(
        back_populates="credit_transactions", foreign_keys=[user_id]
    )
    admin: Mapped["AdminUser | None"] = relationship(foreign_keys=[created_by])
    search: Mapped["UserSearch | None"] = relationship()

    __table_args__ = (
        Index("idx_credit_transactions_user_id", "user_id"),
        Index("idx_credit_transactions_type", "type"),
        Index("idx_credit_transactions_created_at", "created_at"),
    )


class LLMUsage(Base):
    """LLM API usage record."""

    __tablename__ = "llm_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    search_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_searches.id", ondelete="SET NULL")
    )
    provider: Mapped[LLMProvider] = mapped_column(Enum(LLMProvider), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    user: Mapped["AdminUser"] = relationship()
    search: Mapped["UserSearch | None"] = relationship(back_populates="llm_usages")

    __table_args__ = (
        Index("idx_llm_usages_user_id", "user_id"),
        Index("idx_llm_usages_search_id", "search_id"),
        Index("idx_llm_usages_created_at", "created_at"),
    )


# ============================================================================
# Influencer Monitoring Models (网红监控模型)
# ============================================================================


class MonitorStatus(str, PyEnum):
    """Monitor task status enumeration."""

    ACTIVE = "active"  # 监控中
    PAUSED = "paused"  # 已暂停
    COMPLETED = "completed"  # 已完成
    ERROR = "error"  # 错误


class AuthenticityLabel(str, PyEnum):
    """Commenter authenticity labels (评论者真实性标签)."""

    REAL_USER = "real_user"  # 真实用户
    SUSPICIOUS = "suspicious"  # 可疑账户
    BOT = "bot"  # 机器人
    NEW_ACCOUNT = "new_account"  # 新账号
    LOW_ACTIVITY = "low_activity"  # 低活跃度
    HIGH_ENGAGEMENT = "high_engagement"  # 高互动
    VERIFIED = "verified"  # 已认证
    INFLUENCER = "influencer"  # 网红/KOL


class DMStatus(str, PyEnum):
    """DM (Direct Message) ability status."""

    OPEN = "open"  # 可以私信
    FOLLOWERS_ONLY = "followers_only"  # 仅粉丝可私信
    CLOSED = "closed"  # 不可私信
    UNKNOWN = "unknown"  # 未知


class MonitoredInfluencer(Base):
    """Monitored influencer for tweet tracking (监控的网红)."""

    __tablename__ = "monitored_influencers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    twitter_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    screen_name: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(Text)
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    tweet_count: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    profile_image_url: Mapped[str | None] = mapped_column(String(512))

    # Monitoring settings
    status: Mapped[MonitorStatus] = mapped_column(
        Enum(MonitorStatus), default=MonitorStatus.ACTIVE, nullable=False
    )
    monitor_since: Mapped[datetime | None] = mapped_column(DateTime)  # 监控开始时间
    monitor_until: Mapped[datetime | None] = mapped_column(DateTime)  # 监控结束时间
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)  # 检查间隔(分钟)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Statistics
    tweets_collected: Mapped[int] = mapped_column(Integer, default=0)
    commenters_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)

    # Relationships
    owner: Mapped["AdminUser"] = relationship()
    tweets: Mapped[list["MonitoredTweet"]] = relationship(
        back_populates="influencer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_monitored_influencers_user_id", "user_id"),
        Index("idx_monitored_influencers_twitter_user_id", "twitter_user_id"),
        Index("idx_monitored_influencers_status", "status"),
        Index("idx_monitored_influencers_next_check", "next_check_at"),
    )


class MonitoredTweet(Base):
    """Tweets from monitored influencers (被监控网红的推文)."""

    __tablename__ = "monitored_tweets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    influencer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitored_influencers.id", ondelete="CASCADE"), nullable=False
    )
    tweet_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tweet_type: Mapped[str] = mapped_column(String(20), default="tweet")  # tweet, reply, retweet, quote

    # Engagement metrics
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    retweet_count: Mapped[int] = mapped_column(Integer, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, default=0)
    quote_count: Mapped[int] = mapped_column(Integer, default=0)
    view_count: Mapped[int | None] = mapped_column(Integer)
    bookmark_count: Mapped[int] = mapped_column(Integer, default=0)

    # Media
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    media_urls: Mapped[str | None] = mapped_column(Text)  # JSON array
    has_links: Mapped[bool] = mapped_column(Boolean, default=False)
    links: Mapped[str | None] = mapped_column(Text)  # JSON array

    # Timestamps
    tweeted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Analysis status
    commenters_scraped: Mapped[bool] = mapped_column(Boolean, default=False)
    commenters_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    total_commenters: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    influencer: Mapped["MonitoredInfluencer"] = relationship(back_populates="tweets")
    commenters: Mapped[list["TweetCommenter"]] = relationship(
        back_populates="tweet", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_monitored_tweets_influencer_id", "influencer_id"),
        Index("idx_monitored_tweets_tweet_id", "tweet_id"),
        Index("idx_monitored_tweets_tweeted_at", "tweeted_at"),
    )


class TweetCommenter(Base):
    """Users who commented on monitored tweets (推文评论者)."""

    __tablename__ = "tweet_commenters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tweet_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitored_tweets.id", ondelete="CASCADE"), nullable=False
    )
    twitter_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    screen_name: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(Text)
    profile_image_url: Mapped[str | None] = mapped_column(String(512))

    # User metrics
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    tweet_count: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    account_created_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Comment info
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    comment_tweet_id: Mapped[str] = mapped_column(String(50), nullable=False)
    commented_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    comment_like_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_reply_count: Mapped[int] = mapped_column(Integer, default=0)

    # DM ability (私信能力)
    dm_status: Mapped[DMStatus] = mapped_column(
        Enum(DMStatus), default=DMStatus.UNKNOWN, nullable=False
    )
    dm_checked_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Authenticity analysis (真实性分析)
    is_analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    authenticity_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    labels: Mapped[str | None] = mapped_column(Text)  # JSON array of AuthenticityLabel values
    primary_label: Mapped[AuthenticityLabel | None] = mapped_column(Enum(AuthenticityLabel))
    analysis_reasoning: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Flags for easy filtering
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False)
    is_real_user: Mapped[bool] = mapped_column(Boolean, default=False)
    can_dm: Mapped[bool] = mapped_column(Boolean, default=False)

    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    tweet: Mapped["MonitoredTweet"] = relationship(back_populates="commenters")

    __table_args__ = (
        Index("idx_tweet_commenters_tweet_id", "tweet_id"),
        Index("idx_tweet_commenters_twitter_user_id", "twitter_user_id"),
        Index("idx_tweet_commenters_primary_label", "primary_label"),
        Index("idx_tweet_commenters_is_real_user", "is_real_user"),
        Index("idx_tweet_commenters_can_dm", "can_dm"),
        Index("idx_tweet_commenters_authenticity_score", "authenticity_score"),
    )
