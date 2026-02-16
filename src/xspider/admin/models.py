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
    GENERATE_OPENER = "generate_opener"  # AI破冰文案生成
    INTENT_ANALYSIS = "intent_analysis"  # 意图分析
    AUDIENCE_OVERLAP = "audience_overlap"  # 受众重合度分析
    PACKAGE_PURCHASE = "package_purchase"  # 套餐购买
    # Growth & Engagement System (运营增长系统)
    AI_TWEET_REWRITE = "ai_tweet_rewrite"  # AI推文改写 (5积分)
    SMART_INTERACTION_AUTO = "smart_interaction_auto"  # 智能互动-自动模式 (10积分)
    SMART_INTERACTION_REVIEW = "smart_interaction_review"  # 智能互动-审核模式 (5积分)
    TARGETED_COMMENT = "targeted_comment"  # 指定评论 (3积分)
    ACCOUNT_HEALTH_CHECK = "account_health_check"  # 账号健康检测 (20积分)


class LeadStage(str, PyEnum):
    """CRM Lead stage enumeration (销售漏斗阶段)."""

    DISCOVERED = "discovered"  # 新发现
    AI_QUALIFIED = "ai_qualified"  # 已AI筛选
    TO_CONTACT = "to_contact"  # 待触达
    DM_SENT = "dm_sent"  # 已发送DM
    REPLIED = "replied"  # 已回复
    CONVERTED = "converted"  # 已转化
    ARCHIVED = "archived"  # 已归档


class IntentLabel(str, PyEnum):
    """Comment intent labels (评论意图标签)."""

    LOOKING_FOR_SOLUTION = "looking_for_solution"  # 寻找方案
    COMPLAINING = "complaining"  # 抱怨竞品
    ASKING_PRICE = "asking_price"  # 询问价格
    INTERESTED = "interested"  # 表示兴趣
    RECOMMENDING = "recommending"  # 推荐产品
    NEUTRAL = "neutral"  # 中性评论
    SPAM = "spam"  # 垃圾评论


class SentimentType(str, PyEnum):
    """Sentiment type enumeration (情感类型)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class WebhookEventType(str, PyEnum):
    """Webhook event types."""

    HIGH_INTENT_LEAD = "high_intent_lead"  # 高意向线索
    HIGH_ENGAGEMENT_COMMENT = "high_engagement_comment"  # 高互动评论
    NEW_REAL_USER = "new_real_user"  # 新真实用户
    SUSPICIOUS_GROWTH = "suspicious_growth"  # 异常增长
    DM_AVAILABLE = "dm_available"  # DM可用


class LLMProvider(str, PyEnum):
    """LLM provider enumeration."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    KIMI = "kimi"


# ============================================================================
# Growth & Engagement System Enums (运营增长系统枚举)
# ============================================================================


class RiskLevel(str, PyEnum):
    """Account risk level enumeration (账号风险等级)."""

    LOW = "low"  # 低风险
    MEDIUM = "medium"  # 中风险
    HIGH = "high"  # 高风险
    CRITICAL = "critical"  # 严重风险


class RewriteTone(str, PyEnum):
    """Content rewrite tone enumeration (内容改写语气)."""

    PROFESSIONAL = "professional"  # 专业权威
    HUMOROUS = "humorous"  # 幽默风趣
    CONTROVERSIAL = "controversial"  # 争议性观点
    THREAD_STYLE = "thread_style"  # 推文串形式


class ContentStatus(str, PyEnum):
    """Content status enumeration (内容状态)."""

    DRAFT = "draft"  # 草稿
    SCHEDULED = "scheduled"  # 已排期
    PUBLISHED = "published"  # 已发布
    FAILED = "failed"  # 发布失败


class InteractionMode(str, PyEnum):
    """Smart interaction mode enumeration (智能互动模式)."""

    AUTO = "auto"  # 自动发送
    REVIEW = "review"  # 人工审核


class CommentStrategy(str, PyEnum):
    """Comment strategy enumeration (评论策略)."""

    SUPPLEMENT = "supplement"  # 补充观点
    QUESTION = "question"  # 提问引流
    HUMOR_MEME = "humor_meme"  # 幽默Meme


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
    api_keys: Mapped[list["APIKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_admin_users_username", "username"),
        Index("idx_admin_users_email", "email"),
    )

    @property
    def is_admin(self) -> bool:
        """Check if user is an admin."""
        return self.role == UserRole.ADMIN


class APIKey(Base):
    """API key for programmatic access."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    key_id: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scopes: Mapped[str | None] = mapped_column(Text)  # JSON array of allowed scopes
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    user: Mapped["AdminUser"] = relationship(back_populates="api_keys")

    __table_args__ = (
        Index("idx_api_keys_user_id", "user_id"),
        Index("idx_api_keys_key_id", "key_id"),
        Index("idx_api_keys_is_active", "is_active"),
    )


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

    # Intent & Sentiment Analysis (意图与情感分析)
    intent_label: Mapped[IntentLabel | None] = mapped_column(Enum(IntentLabel))
    sentiment: Mapped[SentimentType | None] = mapped_column(Enum(SentimentType))
    intent_confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 意图置信度 0-1
    intent_keywords: Mapped[str | None] = mapped_column(Text)  # 触发关键词 JSON array
    is_high_intent: Mapped[bool] = mapped_column(Boolean, default=False)  # 高购买意向

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
        Index("idx_tweet_commenters_intent_label", "intent_label"),
        Index("idx_tweet_commenters_is_high_intent", "is_high_intent"),
    )


# ============================================================================
# CRM & Sales Funnel Models (CRM与销售漏斗模型)
# ============================================================================


class SalesLead(Base):
    """Sales lead for CRM Kanban board (销售线索看板)."""

    __tablename__ = "sales_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    commenter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tweet_commenters.id", ondelete="SET NULL")
    )

    # Twitter user info (冗余存储，方便查询)
    twitter_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    screen_name: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(Text)
    profile_image_url: Mapped[str | None] = mapped_column(String(512))
    followers_count: Mapped[int] = mapped_column(Integer, default=0)

    # Scores
    pagerank_score: Mapped[float] = mapped_column(Float, default=0.0)
    authenticity_score: Mapped[float] = mapped_column(Float, default=0.0)
    intent_score: Mapped[float] = mapped_column(Float, default=0.0)  # 综合意向分数

    # Lead stage
    stage: Mapped[LeadStage] = mapped_column(
        Enum(LeadStage), default=LeadStage.DISCOVERED, nullable=False
    )
    stage_updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Contact info
    dm_status: Mapped[DMStatus] = mapped_column(
        Enum(DMStatus), default=DMStatus.UNKNOWN, nullable=False
    )
    intent_label: Mapped[IntentLabel | None] = mapped_column(Enum(IntentLabel))

    # Activity tracking
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_tweet_id: Mapped[str | None] = mapped_column(String(50))  # 来源推文
    source_influencer: Mapped[str | None] = mapped_column(String(50))  # 来源网红

    # AI generated content
    opener_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    opener_text: Mapped[str | None] = mapped_column(Text)

    # Notes and tags
    notes: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(Text)  # JSON array

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["AdminUser"] = relationship()
    commenter: Mapped["TweetCommenter | None"] = relationship()

    __table_args__ = (
        Index("idx_sales_leads_user_id", "user_id"),
        Index("idx_sales_leads_stage", "stage"),
        Index("idx_sales_leads_twitter_user_id", "twitter_user_id"),
        Index("idx_sales_leads_intent_score", "intent_score"),
    )


class LeadActivity(Base):
    """Activity log for sales leads (线索活动记录)."""

    __tablename__ = "lead_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_leads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )

    activity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: stage_change, note_added, opener_generated, dm_sent, replied
    old_value: Mapped[str | None] = mapped_column(String(100))
    new_value: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    lead: Mapped["SalesLead"] = relationship()
    user: Mapped["AdminUser"] = relationship()

    __table_args__ = (
        Index("idx_lead_activities_lead_id", "lead_id"),
        Index("idx_lead_activities_created_at", "created_at"),
    )


# ============================================================================
# Growth Anomaly Detection Models (增长异常检测模型)
# ============================================================================


class FollowerSnapshot(Base):
    """Historical follower count snapshots for growth tracking (粉丝历史快照)."""

    __tablename__ = "follower_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    influencer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitored_influencers.id", ondelete="CASCADE"), nullable=False
    )

    followers_count: Mapped[int] = mapped_column(Integer, nullable=False)
    following_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tweet_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Daily engagement metrics
    avg_likes: Mapped[float] = mapped_column(Float, default=0.0)
    avg_retweets: Mapped[float] = mapped_column(Float, default=0.0)
    avg_replies: Mapped[float] = mapped_column(Float, default=0.0)

    # Growth metrics (compared to previous snapshot)
    followers_change: Mapped[int] = mapped_column(Integer, default=0)
    followers_change_pct: Mapped[float] = mapped_column(Float, default=0.0)

    # Anomaly detection
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_type: Mapped[str | None] = mapped_column(String(50))  # suspicious_growth, sudden_drop
    anomaly_score: Mapped[float] = mapped_column(Float, default=0.0)

    snapshot_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    influencer: Mapped["MonitoredInfluencer"] = relationship()

    __table_args__ = (
        Index("idx_follower_snapshots_influencer_id", "influencer_id"),
        Index("idx_follower_snapshots_snapshot_at", "snapshot_at"),
        Index("idx_follower_snapshots_is_anomaly", "is_anomaly"),
    )


# ============================================================================
# Webhook Integration Models (Webhook集成模型)
# ============================================================================


class WebhookConfig(Base):
    """Webhook configuration for external integrations (Webhook配置)."""

    __tablename__ = "webhook_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255))  # For signature verification

    # Event subscriptions (JSON array of WebhookEventType values)
    events: Mapped[str] = mapped_column(Text, nullable=False)

    # Filters
    min_intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    min_authenticity_score: Mapped[float] = mapped_column(Float, default=0.0)
    intent_labels: Mapped[str | None] = mapped_column(Text)  # JSON array

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["AdminUser"] = relationship()

    __table_args__ = (
        Index("idx_webhook_configs_user_id", "user_id"),
        Index("idx_webhook_configs_is_active", "is_active"),
    )


class WebhookLog(Base):
    """Webhook delivery logs (Webhook发送记录)."""

    __tablename__ = "webhook_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    webhook_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("webhook_configs.id", ondelete="CASCADE"), nullable=False
    )

    event_type: Mapped[WebhookEventType] = mapped_column(
        Enum(WebhookEventType), nullable=False
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON payload

    # Response
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Timing
    sent_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    response_time_ms: Mapped[int | None] = mapped_column(Integer)

    # Relationships
    webhook: Mapped["WebhookConfig"] = relationship()

    __table_args__ = (
        Index("idx_webhook_logs_webhook_id", "webhook_id"),
        Index("idx_webhook_logs_sent_at", "sent_at"),
        Index("idx_webhook_logs_success", "success"),
    )


# ============================================================================
# Credit Package Models (积分套餐模型)
# ============================================================================


class CreditPackage(Base):
    """Credit packages for combo pricing (积分套餐)."""

    __tablename__ = "credit_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Pricing
    credits_included: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)  # 价格（分）
    discount_pct: Mapped[float] = mapped_column(Float, default=0.0)  # 折扣百分比

    # Features included (JSON array)
    features: Mapped[str | None] = mapped_column(Text)
    # e.g., ["crawl", "ai_audit", "commenter_analysis", "opener_generate"]

    # Limits
    max_searches: Mapped[int | None] = mapped_column(Integer)
    max_monitors: Mapped[int | None] = mapped_column(Integer)
    max_openers: Mapped[int | None] = mapped_column(Integer)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_credit_packages_is_active", "is_active"),
    )


class PackagePurchase(Base):
    """User package purchases (用户套餐购买记录)."""

    __tablename__ = "package_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("credit_packages.id", ondelete="SET NULL")
    )

    package_name: Mapped[str] = mapped_column(String(100), nullable=False)
    credits_purchased: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_paid_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    # Usage tracking
    credits_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    searches_used: Mapped[int] = mapped_column(Integer, default=0)
    monitors_used: Mapped[int] = mapped_column(Integer, default=0)
    openers_used: Mapped[int] = mapped_column(Integer, default=0)

    purchased_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Relationships
    user: Mapped["AdminUser"] = relationship()
    package: Mapped["CreditPackage | None"] = relationship()

    __table_args__ = (
        Index("idx_package_purchases_user_id", "user_id"),
        Index("idx_package_purchases_purchased_at", "purchased_at"),
    )


# ============================================================================
# AI Opener Models (AI破冰文案模型)
# ============================================================================


class AIOpener(Base):
    """AI generated conversation openers (AI生成的破冰文案)."""

    __tablename__ = "ai_openers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sales_leads.id", ondelete="SET NULL")
    )
    commenter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tweet_commenters.id", ondelete="SET NULL")
    )

    # Target user info
    target_screen_name: Mapped[str] = mapped_column(String(50), nullable=False)
    target_twitter_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # Context used for generation
    recent_tweets: Mapped[str | None] = mapped_column(Text)  # JSON array of tweets
    user_bio: Mapped[str | None] = mapped_column(Text)
    user_interests: Mapped[str | None] = mapped_column(Text)  # Inferred interests

    # Generated openers (usually 3 options)
    openers: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    selected_opener: Mapped[int | None] = mapped_column(Integer)  # Index of selected

    # Generation metadata
    model_used: Mapped[str] = mapped_column(String(50), nullable=False)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)

    # Usage tracking
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    response_received: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    owner: Mapped["AdminUser"] = relationship()
    lead: Mapped["SalesLead | None"] = relationship()
    commenter: Mapped["TweetCommenter | None"] = relationship()

    __table_args__ = (
        Index("idx_ai_openers_user_id", "user_id"),
        Index("idx_ai_openers_target_screen_name", "target_screen_name"),
        Index("idx_ai_openers_created_at", "created_at"),
    )


# ============================================================================
# Audience Overlap Analysis Models (受众重合度分析模型)
# ============================================================================


class AudienceOverlapAnalysis(Base):
    """Audience overlap analysis between influencers (受众重合度分析)."""

    __tablename__ = "audience_overlap_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )

    # Compared influencers
    influencer_a_id: Mapped[str] = mapped_column(String(50), nullable=False)
    influencer_a_name: Mapped[str] = mapped_column(String(50), nullable=False)
    influencer_a_followers: Mapped[int] = mapped_column(Integer, default=0)

    influencer_b_id: Mapped[str] = mapped_column(String(50), nullable=False)
    influencer_b_name: Mapped[str] = mapped_column(String(50), nullable=False)
    influencer_b_followers: Mapped[int] = mapped_column(Integer, default=0)

    # Results
    overlap_count: Mapped[int] = mapped_column(Integer, default=0)  # 重合用户数
    overlap_pct_a: Mapped[float] = mapped_column(Float, default=0.0)  # A粉丝中的重合比例
    overlap_pct_b: Mapped[float] = mapped_column(Float, default=0.0)  # B粉丝中的重合比例
    jaccard_index: Mapped[float] = mapped_column(Float, default=0.0)  # Jaccard相似系数

    # Sample overlap users (JSON array of user IDs)
    sample_overlap_users: Mapped[str | None] = mapped_column(Text)

    # Analysis metadata
    sample_size: Mapped[int] = mapped_column(Integer, default=0)  # 采样大小
    credits_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    owner: Mapped["AdminUser"] = relationship()

    __table_args__ = (
        Index("idx_audience_overlap_user_id", "user_id"),
        Index("idx_audience_overlap_created_at", "created_at"),
    )


# ============================================================================
# Data Retention Policy Models (数据保留策略模型)
# ============================================================================


class DataRetentionPolicy(Base):
    """Data retention policy configuration (数据保留策略)."""

    __tablename__ = "data_retention_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Retention periods (days)
    raw_data_retention_days: Mapped[int] = mapped_column(Integer, default=30)
    anonymized_retention_days: Mapped[int] = mapped_column(Integer, default=365)

    # What to retain after anonymization
    retain_user_id: Mapped[bool] = mapped_column(Boolean, default=True)
    retain_labels: Mapped[bool] = mapped_column(Boolean, default=True)
    retain_scores: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_bio: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_tweets: Mapped[bool] = mapped_column(Boolean, default=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ============================================================================
# Growth & Engagement System Models (运营增长系统模型)
# ============================================================================


class OperatingAccount(Base):
    """Operating account for content posting and engagement (运营账号).

    Unlike scraping accounts, operating accounts are used for:
    - Publishing tweets
    - Replying to KOL tweets
    - Sending DMs
    """

    __tablename__ = "operating_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    twitter_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("twitter_accounts.id", ondelete="CASCADE"), nullable=False
    )

    # Twitter profile info (cached from account)
    twitter_user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    screen_name: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(Text)
    followers_count: Mapped[int] = mapped_column(Integer, default=0)
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    tweet_count: Mapped[int] = mapped_column(Integer, default=0)
    profile_image_url: Mapped[str | None] = mapped_column(String(512))

    # Operating settings (运营配置)
    niche_tags: Mapped[str | None] = mapped_column(Text)  # JSON array: ["AI", "Web3", "DeFi"]
    persona: Mapped[str | None] = mapped_column(Text)  # 账号人设描述
    auto_reply_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interaction_mode: Mapped[InteractionMode] = mapped_column(
        Enum(InteractionMode), default=InteractionMode.REVIEW, nullable=False
    )

    # Daily limits (每日限额)
    daily_tweets_limit: Mapped[int] = mapped_column(Integer, default=5)
    daily_replies_limit: Mapped[int] = mapped_column(Integer, default=20)
    daily_dms_limit: Mapped[int] = mapped_column(Integer, default=50)

    # Today's usage (今日使用量)
    tweets_today: Mapped[int] = mapped_column(Integer, default=0)
    replies_today: Mapped[int] = mapped_column(Integer, default=0)
    dms_today: Mapped[int] = mapped_column(Integer, default=0)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Risk assessment (风险评估)
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel), default=RiskLevel.LOW, nullable=False
    )
    is_shadowbanned: Mapped[bool] = mapped_column(Boolean, default=False)
    shadowban_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    shadowban_details: Mapped[str | None] = mapped_column(Text)  # JSON: {search: bool, recommend: bool, reply: bool}

    # Statistics (统计)
    total_tweets_posted: Mapped[int] = mapped_column(Integer, default=0)
    total_replies_posted: Mapped[int] = mapped_column(Integer, default=0)
    total_dms_sent: Mapped[int] = mapped_column(Integer, default=0)
    total_engagement_received: Mapped[int] = mapped_column(Integer, default=0)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["AdminUser"] = relationship()
    twitter_account: Mapped["TwitterAccount"] = relationship()
    content_rewrites: Mapped[list["ContentRewrite"]] = relationship(
        back_populates="operating_account", cascade="all, delete-orphan"
    )
    smart_interactions: Mapped[list["SmartInteraction"]] = relationship(
        back_populates="operating_account", cascade="all, delete-orphan"
    )
    kol_watchlist: Mapped[list["KOLWatchlist"]] = relationship(
        back_populates="operating_account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_operating_accounts_user_id", "user_id"),
        Index("idx_operating_accounts_twitter_account_id", "twitter_account_id"),
        Index("idx_operating_accounts_risk_level", "risk_level"),
        Index("idx_operating_accounts_is_active", "is_active"),
    )


class ContentRewrite(Base):
    """AI-rewritten content for publishing (AI改写内容)."""

    __tablename__ = "content_rewrites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    operating_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("operating_accounts.id", ondelete="CASCADE"), nullable=False
    )

    # Source content (源内容)
    source_tweet_id: Mapped[str | None] = mapped_column(String(50))  # 原推文ID
    source_tweet_url: Mapped[str | None] = mapped_column(String(255))
    source_content: Mapped[str] = mapped_column(Text, nullable=False)
    source_author: Mapped[str | None] = mapped_column(String(50))

    # Rewrite settings (改写设置)
    tone: Mapped[RewriteTone] = mapped_column(
        Enum(RewriteTone), default=RewriteTone.PROFESSIONAL, nullable=False
    )
    custom_instructions: Mapped[str | None] = mapped_column(Text)  # 自定义改写指令

    # Generated content (生成内容)
    rewritten_content: Mapped[str | None] = mapped_column(Text)
    generated_hashtags: Mapped[str | None] = mapped_column(Text)  # JSON array
    thread_parts: Mapped[str | None] = mapped_column(Text)  # JSON array (for thread style)

    # Status (状态)
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus), default=ContentStatus.DRAFT, nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_tweet_id: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)

    # Engagement tracking (after publishing)
    likes_count: Mapped[int] = mapped_column(Integer, default=0)
    retweets_count: Mapped[int] = mapped_column(Integer, default=0)
    replies_count: Mapped[int] = mapped_column(Integer, default=0)
    last_engagement_check: Mapped[datetime | None] = mapped_column(DateTime)

    # LLM metadata
    model_used: Mapped[str | None] = mapped_column(String(50))
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["AdminUser"] = relationship()
    operating_account: Mapped["OperatingAccount"] = relationship(back_populates="content_rewrites")

    __table_args__ = (
        Index("idx_content_rewrites_user_id", "user_id"),
        Index("idx_content_rewrites_operating_account_id", "operating_account_id"),
        Index("idx_content_rewrites_status", "status"),
        Index("idx_content_rewrites_scheduled_at", "scheduled_at"),
    )


class KOLWatchlist(Base):
    """KOL watchlist for smart interaction monitoring (KOL监控列表)."""

    __tablename__ = "kol_watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    operating_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("operating_accounts.id", ondelete="CASCADE"), nullable=False
    )

    # KOL info
    kol_twitter_id: Mapped[str] = mapped_column(String(50), nullable=False)
    kol_screen_name: Mapped[str] = mapped_column(String(50), nullable=False)
    kol_display_name: Mapped[str | None] = mapped_column(String(100))
    kol_followers_count: Mapped[int] = mapped_column(Integer, default=0)
    kol_bio: Mapped[str | None] = mapped_column(Text)

    # Interaction settings (互动设置)
    interaction_mode: Mapped[InteractionMode] = mapped_column(
        Enum(InteractionMode), default=InteractionMode.REVIEW, nullable=False
    )
    relevance_threshold: Mapped[float] = mapped_column(Float, default=0.8)  # 相关性阈值
    preferred_strategies: Mapped[str | None] = mapped_column(Text)  # JSON array of CommentStrategy

    # Monitoring status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_interacted_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Statistics
    tweets_checked: Mapped[int] = mapped_column(Integer, default=0)
    interactions_generated: Mapped[int] = mapped_column(Integer, default=0)
    interactions_approved: Mapped[int] = mapped_column(Integer, default=0)
    interactions_executed: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["AdminUser"] = relationship()
    operating_account: Mapped["OperatingAccount"] = relationship(back_populates="kol_watchlist")

    __table_args__ = (
        Index("idx_kol_watchlists_user_id", "user_id"),
        Index("idx_kol_watchlists_operating_account_id", "operating_account_id"),
        Index("idx_kol_watchlists_kol_twitter_id", "kol_twitter_id"),
        Index("idx_kol_watchlists_is_active", "is_active"),
    )


class SmartInteraction(Base):
    """Smart interaction record for KOL engagement (智能互动记录)."""

    __tablename__ = "smart_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )
    operating_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("operating_accounts.id", ondelete="CASCADE"), nullable=False
    )
    kol_watchlist_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("kol_watchlists.id", ondelete="SET NULL")
    )

    # Target tweet info (目标推文)
    target_tweet_id: Mapped[str] = mapped_column(String(50), nullable=False)
    target_tweet_url: Mapped[str] = mapped_column(String(255), nullable=False)
    target_tweet_content: Mapped[str] = mapped_column(Text, nullable=False)
    target_author_id: Mapped[str] = mapped_column(String(50), nullable=False)
    target_author_name: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relevance analysis (相关性分析)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    relevance_reasoning: Mapped[str | None] = mapped_column(Text)

    # Generated comments (生成的评论 - 3种策略)
    generated_comments: Mapped[str | None] = mapped_column(Text)  # JSON: {supplement: str, question: str, humor_meme: str}
    selected_strategy: Mapped[CommentStrategy | None] = mapped_column(Enum(CommentStrategy))
    selected_comment: Mapped[str | None] = mapped_column(Text)

    # Execution mode (执行模式)
    mode: Mapped[InteractionMode] = mapped_column(
        Enum(InteractionMode), default=InteractionMode.REVIEW, nullable=False
    )
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    approved_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="SET NULL")
    )

    # Execution status (执行状态)
    is_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    posted_tweet_id: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)

    # Engagement tracking (after posting)
    likes_received: Mapped[int] = mapped_column(Integer, default=0)
    replies_received: Mapped[int] = mapped_column(Integer, default=0)
    last_engagement_check: Mapped[datetime | None] = mapped_column(DateTime)

    # LLM metadata
    model_used: Mapped[str | None] = mapped_column(String(50))
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["AdminUser"] = relationship(foreign_keys=[user_id])
    operating_account: Mapped["OperatingAccount"] = relationship(back_populates="smart_interactions")
    kol_watchlist: Mapped["KOLWatchlist | None"] = relationship()
    approver: Mapped["AdminUser | None"] = relationship(foreign_keys=[approved_by])

    __table_args__ = (
        Index("idx_smart_interactions_user_id", "user_id"),
        Index("idx_smart_interactions_operating_account_id", "operating_account_id"),
        Index("idx_smart_interactions_target_tweet_id", "target_tweet_id"),
        Index("idx_smart_interactions_is_approved", "is_approved"),
        Index("idx_smart_interactions_is_executed", "is_executed"),
    )


class TargetedComment(Base):
    """Targeted comment on specific tweets (指定评论)."""

    __tablename__ = "targeted_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False
    )

    # Target tweet (目标推文)
    target_tweet_url: Mapped[str] = mapped_column(String(255), nullable=False)
    target_tweet_id: Mapped[str] = mapped_column(String(50), nullable=False)
    target_tweet_content: Mapped[str | None] = mapped_column(Text)
    target_author_id: Mapped[str] = mapped_column(String(50), nullable=False)
    target_author_name: Mapped[str] = mapped_column(String(50), nullable=False)

    # Comment settings (评论设置)
    comment_direction: Mapped[str | None] = mapped_column(Text)  # 评论方向/指令
    strategy: Mapped[CommentStrategy | None] = mapped_column(Enum(CommentStrategy))

    # Matrix commenting (矩阵评论)
    is_matrix: Mapped[bool] = mapped_column(Boolean, default=False)
    main_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("operating_accounts.id", ondelete="SET NULL")
    )
    support_account_ids: Mapped[str | None] = mapped_column(Text)  # JSON array of account IDs

    # Permission check (权限检查)
    can_comment: Mapped[bool] = mapped_column(Boolean, default=False)
    permission_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    permission_reason: Mapped[str | None] = mapped_column(String(255))

    # Generated comment (生成的评论)
    generated_comment: Mapped[str | None] = mapped_column(Text)
    support_comments: Mapped[str | None] = mapped_column(Text)  # JSON array for matrix mode

    # Execution status
    is_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    posted_tweet_ids: Mapped[str | None] = mapped_column(Text)  # JSON array of posted reply IDs
    error_message: Mapped[str | None] = mapped_column(Text)

    # Engagement tracking
    total_likes: Mapped[int] = mapped_column(Integer, default=0)
    total_replies: Mapped[int] = mapped_column(Integer, default=0)
    last_engagement_check: Mapped[datetime | None] = mapped_column(DateTime)

    # LLM metadata
    model_used: Mapped[str | None] = mapped_column(String(50))
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["AdminUser"] = relationship()
    main_account: Mapped["OperatingAccount | None"] = relationship()

    __table_args__ = (
        Index("idx_targeted_comments_user_id", "user_id"),
        Index("idx_targeted_comments_target_tweet_id", "target_tweet_id"),
        Index("idx_targeted_comments_is_executed", "is_executed"),
        Index("idx_targeted_comments_is_matrix", "is_matrix"),
    )


class OperatingFollowerSnapshot(Base):
    """Follower snapshots for operating accounts (运营账号粉丝快照)."""

    __tablename__ = "operating_follower_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operating_account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("operating_accounts.id", ondelete="CASCADE"), nullable=False
    )

    # Metrics snapshot
    followers_count: Mapped[int] = mapped_column(Integer, nullable=False)
    following_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tweet_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Growth metrics (compared to previous snapshot)
    followers_change: Mapped[int] = mapped_column(Integer, default=0)
    followers_change_pct: Mapped[float] = mapped_column(Float, default=0.0)

    # Engagement metrics (past 24h)
    tweets_posted: Mapped[int] = mapped_column(Integer, default=0)
    replies_posted: Mapped[int] = mapped_column(Integer, default=0)
    total_engagement: Mapped[int] = mapped_column(Integer, default=0)  # likes + retweets + replies received

    snapshot_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    operating_account: Mapped["OperatingAccount"] = relationship()

    __table_args__ = (
        Index("idx_op_follower_snapshots_account_id", "operating_account_id"),
        Index("idx_op_follower_snapshots_snapshot_at", "snapshot_at"),
    )
