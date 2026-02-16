"""Pydantic schemas for admin module request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from xspider.admin.models import (
    AccountStatus,
    AuthenticityLabel,
    DMStatus,
    LLMProvider,
    MonitorStatus,
    ProxyProtocol,
    ProxyStatus,
    SearchStatus,
    TransactionType,
    UserRole,
)


# ============================================================================
# Auth Schemas
# ============================================================================


class LoginRequest(BaseModel):
    """Login request schema."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)


class RegisterRequest(BaseModel):
    """Registration request schema."""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)


class TokenResponse(BaseModel):
    """JWT token response schema."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    """User response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: UserRole
    credits: int
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


# ============================================================================
# Admin User Management Schemas
# ============================================================================


class UserCreateRequest(BaseModel):
    """Admin create user request."""

    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)
    role: UserRole = UserRole.USER
    credits: int = Field(default=0, ge=0)


class UserUpdateRequest(BaseModel):
    """Admin update user request."""

    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class CreditRechargeRequest(BaseModel):
    """Credit recharge request."""

    amount: int = Field(..., gt=0)
    description: str | None = None


class UserListResponse(BaseModel):
    """User list response with pagination."""

    users: list[UserResponse]
    total: int
    page: int
    page_size: int


# ============================================================================
# Twitter Account Schemas
# ============================================================================


class TwitterAccountCreate(BaseModel):
    """Create Twitter account request."""

    name: str | None = Field(None, max_length=100)
    bearer_token: str = Field(..., min_length=10)
    ct0: str = Field(..., min_length=10)
    auth_token: str = Field(..., min_length=10)
    notes: str | None = None


class TwitterAccountUpdate(BaseModel):
    """Update Twitter account request."""

    name: str | None = None
    bearer_token: str | None = None
    ct0: str | None = None
    auth_token: str | None = None
    status: AccountStatus | None = None
    notes: str | None = None


class TwitterAccountResponse(BaseModel):
    """Twitter account response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    status: AccountStatus
    last_used_at: datetime | None
    last_check_at: datetime | None
    request_count: int
    error_count: int
    rate_limit_reset: datetime | None
    created_at: datetime
    notes: str | None


class TwitterAccountDetailResponse(TwitterAccountResponse):
    """Twitter account detail response with tokens (masked)."""

    bearer_token_preview: str  # Show only last 8 chars
    ct0_preview: str
    auth_token_preview: str


class TwitterAccountBatchImport(BaseModel):
    """Batch import Twitter accounts."""

    accounts: list[TwitterAccountCreate]


class AccountStatusCheck(BaseModel):
    """Account status check result."""

    account_id: int
    status: AccountStatus
    error_message: str | None = None
    rate_limit_reset: datetime | None = None


# ============================================================================
# Proxy Server Schemas
# ============================================================================


class ProxyCreate(BaseModel):
    """Create proxy request."""

    name: str | None = Field(None, max_length=100)
    url: str = Field(..., min_length=10)
    protocol: ProxyProtocol = ProxyProtocol.HTTP


class ProxyUpdate(BaseModel):
    """Update proxy request."""

    name: str | None = None
    url: str | None = None
    protocol: ProxyProtocol | None = None
    status: ProxyStatus | None = None


class ProxyResponse(BaseModel):
    """Proxy response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    url: str
    protocol: ProxyProtocol
    status: ProxyStatus
    last_check_at: datetime | None
    response_time: float | None
    success_rate: float
    total_requests: int
    failed_requests: int
    created_at: datetime


class ProxyBatchImport(BaseModel):
    """Batch import proxies."""

    urls: list[str]
    protocol: ProxyProtocol = ProxyProtocol.HTTP


class ProxyHealthCheck(BaseModel):
    """Proxy health check result."""

    proxy_id: int
    status: ProxyStatus
    response_time: float | None = None
    error_message: str | None = None


# ============================================================================
# Search Task Schemas
# ============================================================================


class SearchCreate(BaseModel):
    """Create search task request."""

    keywords: str = Field(..., min_length=1, max_length=500)
    industry: str | None = Field(None, max_length=100)


class SearchResponse(BaseModel):
    """Search task response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    keywords: str
    industry: str | None
    seeds_found: int
    users_crawled: int
    credits_used: int
    status: SearchStatus
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class SearchDetailResponse(SearchResponse):
    """Search detail response with influencers."""

    influencers: list["InfluencerResponse"]


class InfluencerResponse(BaseModel):
    """Discovered influencer response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    twitter_user_id: str
    screen_name: str
    name: str | None
    followers_count: int
    pagerank_score: float
    hidden_score: float
    is_relevant: bool
    relevance_score: int


class SearchEstimate(BaseModel):
    """Search cost estimate."""

    estimated_credits: int
    breakdown: dict[str, int]


# ============================================================================
# Credit Transaction Schemas
# ============================================================================


class CreditTransactionResponse(BaseModel):
    """Credit transaction response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: int
    balance_after: int
    type: TransactionType
    description: str | None
    created_at: datetime


class CreditHistoryResponse(BaseModel):
    """Credit history response with pagination."""

    transactions: list[CreditTransactionResponse]
    current_balance: int
    total: int
    page: int
    page_size: int


# ============================================================================
# LLM Usage Schemas
# ============================================================================


class LLMUsageResponse(BaseModel):
    """LLM usage response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    provider: LLMProvider
    model: str
    tokens_input: int
    tokens_output: int
    credits_used: int
    created_at: datetime


# ============================================================================
# Dashboard Schemas
# ============================================================================


class DashboardStats(BaseModel):
    """Dashboard statistics."""

    # Account stats
    total_accounts: int
    active_accounts: int
    rate_limited_accounts: int
    error_accounts: int

    # Proxy stats
    total_proxies: int
    active_proxies: int
    error_proxies: int

    # User stats
    total_users: int
    active_users_today: int

    # Search stats
    searches_today: int
    searches_running: int

    # Credit stats
    total_credits_used_today: int


class AccountStatusDistribution(BaseModel):
    """Account status distribution for charts."""

    active: int
    rate_limited: int
    banned: int
    needs_verify: int
    error: int


class ProxyStatusDistribution(BaseModel):
    """Proxy status distribution for charts."""

    active: int
    inactive: int
    error: int


class DailySearchStats(BaseModel):
    """Daily search statistics."""

    date: str
    searches: int
    credits_used: int


class RecentActivity(BaseModel):
    """Recent activity item."""

    type: str  # "search", "login", "recharge", etc.
    description: str
    user: str
    timestamp: datetime


# ============================================================================
# Export Schemas
# ============================================================================


class ExportRequest(BaseModel):
    """Export data request."""

    search_id: int
    format: str = Field(default="csv", pattern="^(csv|json)$")
    include_irrelevant: bool = False


class ExportResponse(BaseModel):
    """Export response with download info."""

    filename: str
    url: str
    size_bytes: int
    record_count: int


# ============================================================================
# Pagination Schemas
# ============================================================================


class PaginationParams(BaseModel):
    """Pagination parameters."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    """Generic paginated response."""

    items: list[Any]
    total: int
    page: int
    page_size: int
    pages: int


# ============================================================================
# Influencer Monitoring Schemas (网红监控)
# ============================================================================


class MonitoredInfluencerCreate(BaseModel):
    """Create monitored influencer request."""

    screen_name: str = Field(..., min_length=1, max_length=50)
    monitor_since: datetime | None = None  # 监控开始时间
    monitor_until: datetime | None = None  # 监控结束时间
    check_interval_minutes: int = Field(default=60, ge=5, le=1440)  # 5分钟到24小时
    notes: str | None = None


class MonitoredInfluencerUpdate(BaseModel):
    """Update monitored influencer request."""

    status: MonitorStatus | None = None
    monitor_since: datetime | None = None
    monitor_until: datetime | None = None
    check_interval_minutes: int | None = None
    notes: str | None = None


class MonitoredInfluencerResponse(BaseModel):
    """Monitored influencer response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    twitter_user_id: str
    screen_name: str
    display_name: str | None
    bio: str | None
    followers_count: int
    following_count: int
    tweet_count: int
    verified: bool
    profile_image_url: str | None
    status: MonitorStatus
    monitor_since: datetime | None
    monitor_until: datetime | None
    check_interval_minutes: int
    last_checked_at: datetime | None
    next_check_at: datetime | None
    tweets_collected: int
    commenters_analyzed: int
    credits_used: int
    created_at: datetime
    notes: str | None


class MonitoredTweetResponse(BaseModel):
    """Monitored tweet response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tweet_id: str
    content: str
    tweet_type: str
    like_count: int
    retweet_count: int
    reply_count: int
    quote_count: int
    view_count: int | None
    bookmark_count: int
    has_media: bool
    has_links: bool
    tweeted_at: datetime
    collected_at: datetime
    commenters_scraped: bool
    commenters_analyzed: bool
    total_commenters: int


class TweetCommenterResponse(BaseModel):
    """Tweet commenter response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    twitter_user_id: str
    screen_name: str
    display_name: str | None
    bio: str | None
    profile_image_url: str | None
    followers_count: int
    following_count: int
    tweet_count: int
    verified: bool
    account_created_at: datetime | None
    comment_text: str
    commented_at: datetime
    comment_like_count: int
    dm_status: DMStatus
    is_analyzed: bool
    authenticity_score: float
    primary_label: AuthenticityLabel | None
    labels: list[str] | None
    analysis_reasoning: str | None
    is_bot: bool
    is_suspicious: bool
    is_real_user: bool
    can_dm: bool


class CommenterAnalysisResult(BaseModel):
    """Result of commenter authenticity analysis."""

    commenter_id: int
    twitter_user_id: str
    screen_name: str
    authenticity_score: float  # 0-100
    primary_label: AuthenticityLabel
    labels: list[AuthenticityLabel]
    reasoning: str
    is_bot: bool
    is_suspicious: bool
    is_real_user: bool
    can_dm: bool
    dm_status: DMStatus


class CommenterAnalysisSummary(BaseModel):
    """Summary of commenter analysis for a tweet."""

    tweet_id: int
    total_commenters: int
    analyzed_count: int
    real_users: int
    suspicious: int
    bots: int
    can_dm_count: int
    average_authenticity_score: float
    label_distribution: dict[str, int]


class MonitoringStats(BaseModel):
    """Monitoring statistics for dashboard."""

    total_monitors: int
    active_monitors: int
    paused_monitors: int
    total_tweets_collected: int
    total_commenters_analyzed: int
    real_users_found: int
    bots_detected: int
    dm_available_count: int


class ScrapeCommentersRequest(BaseModel):
    """Request to scrape commenters for a tweet."""

    tweet_id: int
    max_commenters: int = Field(default=100, ge=1, le=1000)


class AnalyzeCommentersRequest(BaseModel):
    """Request to analyze commenters for a tweet."""

    tweet_id: int
    force_reanalyze: bool = False  # Re-analyze already analyzed commenters


class MonitorTaskResponse(BaseModel):
    """Response for monitor-related async tasks."""

    task_id: str
    status: str
    message: str


class CommenterFilterParams(BaseModel):
    """Filter parameters for commenter queries."""

    is_real_user: bool | None = None
    is_bot: bool | None = None
    is_suspicious: bool | None = None
    can_dm: bool | None = None
    min_authenticity_score: float | None = None
    max_authenticity_score: float | None = None
    primary_label: AuthenticityLabel | None = None
    min_followers: int | None = None
    max_followers: int | None = None


class CommenterExportRequest(BaseModel):
    """Request to export commenters data."""

    tweet_id: int | None = None  # Export for specific tweet
    influencer_id: int | None = None  # Export for all tweets of an influencer
    format: str = Field(default="csv", pattern="^(csv|json)$")
    filters: CommenterFilterParams | None = None
    include_analysis: bool = True
