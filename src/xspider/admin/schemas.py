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


# ============================================================================
# CRM and Sales Lead Schemas (销售线索)
# ============================================================================


class SalesLeadResponse(BaseModel):
    """Sales lead response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    twitter_user_id: str
    screen_name: str
    display_name: str | None
    bio: str | None
    profile_image_url: str | None
    followers_count: int
    authenticity_score: float
    intent_score: float
    stage: str
    dm_status: str | None
    intent_label: str | None
    notes: str | None
    tags: str | None
    opener_generated: bool
    opener_text: str | None
    source_influencer: str | None
    created_at: datetime
    stage_updated_at: datetime | None


class LeadStageUpdate(BaseModel):
    """Update lead stage request."""

    new_stage: str
    notes: str | None = None


class LeadNoteUpdate(BaseModel):
    """Update lead note request."""

    note: str


class LeadTagsUpdate(BaseModel):
    """Update lead tags request."""

    tags: list[str]


class LeadActivityResponse(BaseModel):
    """Lead activity response."""

    id: int
    activity_type: str
    old_value: str | None
    new_value: str | None
    description: str | None
    created_at: datetime


class KanbanBoardResponse(BaseModel):
    """Kanban board response."""

    board: dict[str, list[SalesLeadResponse]]


class KanbanStatsResponse(BaseModel):
    """Kanban statistics response."""

    discovered: int
    ai_qualified: int
    to_contact: int
    dm_sent: int
    replied: int
    converted: int
    archived: int
    high_intent: int
    dm_available: int
    conversion_rate: float


# ============================================================================
# Intent Analysis Schemas (意图分析)
# ============================================================================


class IntentAnalysisResult(BaseModel):
    """Intent analysis result."""

    intent_label: str
    sentiment: str
    confidence: float
    keywords: list[str]
    is_high_intent: bool
    reasoning: str


class IntentSummaryResponse(BaseModel):
    """Intent summary for a tweet."""

    tweet_id: int
    total_analyzed: int
    high_intent_count: int
    high_intent_rate: float
    intent_distribution: dict[str, int]
    sentiment_distribution: dict[str, int]


class HighIntentCommenterResponse(BaseModel):
    """High intent commenter response."""

    id: int
    screen_name: str
    display_name: str | None
    comment_text: str
    intent_label: str
    sentiment: str
    intent_confidence: float
    intent_keywords: str | None
    dm_status: str | None
    followers_count: int


# ============================================================================
# Growth Monitoring Schemas (增长监控)
# ============================================================================


class FollowerSnapshotResponse(BaseModel):
    """Follower snapshot response."""

    id: int
    followers_count: int
    following_count: int
    tweet_count: int
    avg_likes: float
    avg_retweets: float
    avg_replies: float
    followers_change: int
    followers_change_pct: float
    is_anomaly: bool
    anomaly_type: str | None
    anomaly_score: float
    snapshot_at: datetime


class GrowthSummaryResponse(BaseModel):
    """Growth summary response."""

    influencer_id: int
    current_followers: int
    growth_7d: int
    growth_7d_pct: float
    growth_30d: int
    growth_30d_pct: float
    avg_likes: float
    avg_retweets: float
    anomaly_count: int
    latest_snapshot_at: datetime | None


class GrowthAnomalyResponse(BaseModel):
    """Growth anomaly response."""

    influencer_id: int
    screen_name: str
    display_name: str | None
    followers_count: int
    followers_change: int
    followers_change_pct: float
    anomaly_type: str
    anomaly_score: float
    snapshot_at: datetime


# ============================================================================
# AI Opener Schemas (AI破冰文案)
# ============================================================================


class OpenerGenerateRequest(BaseModel):
    """Generate opener request."""

    target_screen_name: str
    target_twitter_id: str
    lead_id: int | None = None
    commenter_id: int | None = None
    num_openers: int = Field(default=3, ge=1, le=5)


class OpenerResponse(BaseModel):
    """AI opener response."""

    id: int
    target_screen_name: str
    target_twitter_id: str
    openers: str  # JSON array of openers
    user_bio: str | None
    user_interests: str | None
    model_used: str
    tokens_used: int
    credits_used: int
    is_used: bool
    used_at: datetime | None
    selected_opener: int | None
    response_received: bool
    created_at: datetime


class OpenerStatsResponse(BaseModel):
    """Opener statistics response."""

    total_generated: int
    total_used: int
    total_responses: int
    response_rate: float
    credits_used: int


# ============================================================================
# Audience Overlap Schemas (受众重合)
# ============================================================================


class AudienceOverlapRequest(BaseModel):
    """Audience overlap analysis request."""

    influencer_a_id: int
    influencer_b_id: int


class AudienceOverlapResponse(BaseModel):
    """Audience overlap analysis response."""

    id: int
    influencer_a_screen_name: str
    influencer_b_screen_name: str
    followers_a_count: int
    followers_b_count: int
    overlap_count: int
    unique_a_count: int
    unique_b_count: int
    jaccard_index: float
    overlap_percentage_a: float
    overlap_percentage_b: float
    sample_overlap_users: str | None  # JSON array
    credits_used: int
    created_at: datetime


class SimilarAudienceResponse(BaseModel):
    """Similar audience response."""

    influencer_id: int
    screen_name: str
    overlap_percentage: float
    jaccard_index: float
    overlap_count: int
    analysis_id: int


# ============================================================================
# Webhook Schemas (Webhook集成)
# ============================================================================


class WebhookCreateRequest(BaseModel):
    """Create webhook request."""

    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=10)
    event_types: list[str]
    secret: str | None = None
    headers: dict[str, str] | None = None


class WebhookUpdateRequest(BaseModel):
    """Update webhook request."""

    name: str | None = None
    url: str | None = None
    event_types: list[str] | None = None
    is_active: bool | None = None
    headers: dict[str, str] | None = None


class WebhookResponse(BaseModel):
    """Webhook response."""

    id: int
    name: str
    url: str
    event_types: str  # JSON array
    is_active: bool
    last_triggered_at: datetime | None
    success_count: int
    failure_count: int
    created_at: datetime


class WebhookLogResponse(BaseModel):
    """Webhook log response."""

    id: int
    event_type: str
    success: bool
    response_status: int
    response_body: str | None
    error_message: str | None
    created_at: datetime


class WebhookStatsResponse(BaseModel):
    """Webhook statistics response."""

    total_webhooks: int
    active_webhooks: int
    total_triggers: int
    total_success: int
    total_failure: int
    success_rate: float


# ============================================================================
# Credit Package Schemas (积分套餐)
# ============================================================================


class CreditPackageCreate(BaseModel):
    """Create credit package request (admin)."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str
    credits: int = Field(..., gt=0)
    price: float = Field(..., gt=0)
    currency: str = "USD"
    bonus_credits: int = 0
    features: list[str] | None = None
    is_popular: bool = False
    sort_order: int = 0


class CreditPackageUpdate(BaseModel):
    """Update credit package request (admin)."""

    name: str | None = None
    description: str | None = None
    credits: int | None = None
    price: float | None = None
    bonus_credits: int | None = None
    features: list[str] | None = None
    is_popular: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class CreditPackageResponse(BaseModel):
    """Credit package response."""

    id: int
    name: str
    description: str
    credits: int
    bonus_credits: int
    total_credits: int
    price: float
    currency: str
    features: str | None  # JSON array
    is_popular: bool


class PackagePurchaseResponse(BaseModel):
    """Package purchase response."""

    id: int
    package_name: str
    credits_purchased: int
    bonus_credits: int
    total_credits: int
    amount_paid: float
    currency: str
    payment_method: str
    payment_id: str | None
    status: str
    created_at: datetime


class PurchaseStatsResponse(BaseModel):
    """Purchase statistics response (admin)."""

    total_revenue: float
    total_purchases: int
    credits_sold: int
    bonus_given: int
    average_order: float
    popular_packages: list[dict[str, Any]]


# ============================================================================
# Privacy and Retention Schemas (隐私与保留)
# ============================================================================


class RetentionPolicyRequest(BaseModel):
    """Set retention policy request."""

    search_results_days: int | None = None
    commenter_data_days: int | None = None
    lead_data_days: int | None = None
    analytics_days: int | None = None
    webhook_logs_days: int | None = None
    auto_delete_enabled: bool = True


class RetentionPolicyResponse(BaseModel):
    """Retention policy response."""

    id: int
    search_results_days: int
    commenter_data_days: int
    lead_data_days: int
    analytics_days: int
    webhook_logs_days: int
    auto_delete_enabled: bool
    updated_at: datetime | None


class DataStatsResponse(BaseModel):
    """Data storage statistics response."""

    searches: int
    leads: int
    ai_openers: int
    oldest_search: datetime | None
    retention_policy: dict[str, Any] | None


class DataCleanupResponse(BaseModel):
    """Data cleanup response."""

    success: bool
    cleaned_records: dict[str, int]


# ============================================================================
# Network Topology Schemas (网络拓扑)
# ============================================================================


class TopologyNodeResponse(BaseModel):
    """Topology node response."""

    id: str
    label: str
    name: str | None
    size: float
    color: str
    pagerank: float | None = None
    hidden_score: float | None = None
    followers_count: int
    relevance_score: int | None = None
    is_relevant: bool | None = None


class TopologyEdgeResponse(BaseModel):
    """Topology edge response."""

    source: str
    target: str
    type: str
    weight: float | None = None


class TopologyResponse(BaseModel):
    """Network topology response."""

    search_id: int | None = None
    keywords: str | None = None
    nodes: list[TopologyNodeResponse]
    edges: list[TopologyEdgeResponse]
    stats: dict[str, Any]
