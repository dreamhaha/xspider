# xspider 技术开发文档

## 目录

1. [系统概述](#1-系统概述)
2. [架构设计](#2-架构设计)
3. [模块详解](#3-模块详解)
4. [销售转化模块](#4-销售转化模块) *(NEW)*
5. [数据模型](#5-数据模型)
6. [核心算法](#6-核心算法)
7. [API 接口](#7-api-接口)
8. [配置指南](#8-配置指南)
9. [开发指南](#9-开发指南)
10. [部署运维](#10-部署运维)

---

## 1. 系统概述

### 1.1 项目背景

xspider 是一个基于社交网络分析（SNA）的 Twitter/X KOL 发现系统。核心理念是：**大 V 往往会关注其他同行业的大 V**，通过分析关注关系图谱，可以发现传统关键词搜索无法触及的行业意见领袖。

### 1.2 核心功能

| 功能模块 | 描述 | 技术实现 |
|---------|------|---------|
| 种子采集 | Bio 关键词搜索 + Lists 抓取 | Twitter GraphQL API |
| 网络裂变 | BFS 遍历 Following 关系 | 异步爬虫 + 深度限制 |
| 权重计算 | PageRank 影响力排名 | NetworkX 图算法 |
| 隐形大佬 | 高权重低粉丝用户发现 | 自定义 Hidden Score |
| AI 审核 | LLM 判断行业相关性 | OpenAI / Claude API |
| **CRM 销售漏斗** | 线索全流程管理 | Kanban + 状态机 |
| **AI 破冰** | 个性化 DM 话术生成 | LLM + 模板系统 |
| **意图分析** | 购买意图评分 | 正则 + LLM 混合 |
| **增长监测** | 粉丝异常检测 | 时序分析 + 阈值检测 |
| **受众重合** | KOL 粉丝对比 | Jaccard 相似度 |
| **Webhook** | 事件推送集成 | HMAC 签名 + 异步投递 |

### 1.3 技术栈

```
Python 3.11+
├── httpx          # 异步 HTTP 客户端
├── SQLAlchemy 2.0 # 异步 ORM
├── NetworkX       # 图算法库
├── Typer + Rich   # CLI 框架
├── Pydantic       # 数据验证
├── OpenAI/Claude  # LLM API
└── structlog      # 结构化日志
```

---

## 2. 架构设计

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              CLI Layer                                   │
│                     (Typer Commands + Rich UI)                          │
│         seed | crawl | rank | audit | export                            │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Service Layer                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   Scraper   │  │    Graph    │  │     AI      │  │   Storage   │    │
│  │  - Seed     │  │  - Builder  │  │  - Client   │  │  - Database │    │
│  │  - Follow   │  │  - PageRank │  │  - Auditor  │  │  - Repos    │    │
│  │  - Tweet    │  │  - Analysis │  │  - Prompts  │  │  - Models   │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Infrastructure Layer                            │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      Twitter Client                                │  │
│  │  GraphQL Client + Token Pool + Proxy Pool + Rate Limiter          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         Core                                       │  │
│  │  Config (Pydantic) + Logging (structlog) + Exceptions              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Data Layer                                     │
│         SQLite (Users, Edges, Rankings, Audits)                         │
│         NetworkX DiGraph (In-Memory Graph)                              │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Seeds   │───▶│  Crawl   │───▶│  Graph   │───▶│  Audit   │───▶│  Export  │
│ 50-100   │    │ BFS 2-3层 │    │ PageRank │    │ LLM 审核  │    │ CSV/JSON │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │               │               │               │
     ▼               ▼               ▼               ▼               ▼
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  users   │    │  edges   │    │ rankings │    │  audits  │    │  files   │
│  表      │    │  表      │    │  表      │    │  表      │    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
```

### 2.3 并发模型

```python
# 异步并发架构
┌─────────────────────────────────────────────────────────────┐
│                     asyncio Event Loop                       │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  Semaphore (max_concurrent_requests = 5)                ││
│  │  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐     ││
│  │  │Task 1 │ │Task 2 │ │Task 3 │ │Task 4 │ │Task 5 │     ││
│  │  └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘     ││
│  └──────┼─────────┼─────────┼─────────┼─────────┼──────────┘│
│         └─────────┴─────────┼─────────┴─────────┘           │
│                             ▼                                │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Token Pool (Round-Robin)                    ││
│  │  [Token1] [Token2] [Token3] ... [TokenN]                ││
│  └─────────────────────────────────────────────────────────┘│
│                             ▼                                │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Proxy Pool (Health-Aware)                   ││
│  │  [Proxy1] [Proxy2] [Proxy3] ... [ProxyM]                ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 模块详解

### 3.1 Core 模块 (`src/xspider/core/`)

#### 3.1.1 配置管理 (`config.py`)

```python
from xspider.core import Settings, get_settings

# 配置类结构
class Settings(BaseSettings):
    # Twitter 认证
    twitter_tokens: list[TwitterToken]  # Token 池
    proxy_urls: list[str]               # 代理池

    # LLM API
    openai_api_key: str
    anthropic_api_key: str

    # 爬虫参数
    max_concurrent_requests: int = 5    # 并发数
    request_delay_ms: int = 1000        # 请求间隔
    max_followings_per_user: int = 500  # 每用户最大抓取
    crawl_depth: int = 2                # 爬取深度

    # 存储
    database_url: str = "sqlite+aiosqlite:///data/xspider.db"
```

#### 3.1.2 异常体系 (`exceptions.py`)

```python
XSpiderError                    # 基类
├── RateLimitError              # 限速错误
│   └── RateLimitExhausted      # Token 池耗尽
├── AuthenticationError         # 认证失败
├── ScrapingError               # 爬取错误
├── GraphError                  # 图计算错误
├── AuditError                  # AI 审核错误
├── DatabaseError               # 数据库错误
└── ProxyError                  # 代理错误
    └── NoHealthyProxyError     # 无可用代理
```

#### 3.1.3 日志系统 (`logging.py`)

```python
from xspider.core import setup_logging, get_logger

# 初始化
setup_logging()

# 使用
logger = get_logger(__name__, user_id="12345")
logger.info("Scraping user", followers=1000)

# 输出 (JSON 格式)
# {"event": "Scraping user", "user_id": "12345", "followers": 1000,
#  "level": "info", "timestamp": "2024-01-15T10:30:00Z"}
```

### 3.2 Twitter 模块 (`src/xspider/twitter/`)

#### 3.2.1 数据模型 (`models.py`)

```python
@dataclass(frozen=True)
class TwitterUser:
    id: str
    username: str
    display_name: str
    bio: str | None
    followers_count: int
    following_count: int
    tweet_count: int
    verified: bool
    verification_type: UserVerificationType
    created_at: datetime | None

    @classmethod
    def from_graphql_response(cls, data: dict) -> "TwitterUser":
        """解析 GraphQL 响应"""
        ...

@dataclass(frozen=True)
class Tweet:
    id: str
    text: str
    created_at: datetime
    retweet_count: int
    like_count: int
    reply_count: int
    hashtags: list[str]
    mentions: list[str]
    urls: list[str]
    media: list[TweetMedia]
    is_retweet: bool
    is_reply: bool
```

#### 3.2.2 GraphQL 端点 (`endpoints.py`)

```python
class EndpointType(Enum):
    USER_BY_SCREEN_NAME = "UserByScreenName"
    USER_BY_REST_ID = "UserByRestId"
    FOLLOWING = "Following"
    FOLLOWERS = "Followers"
    USER_TWEETS = "UserTweets"
    SEARCH_TIMELINE = "SearchTimeline"

# 端点配置
ENDPOINTS = {
    EndpointType.FOLLOWING: GraphQLEndpoint(
        query_id="iLmPpKjg_EKLcm6AhdMFBQ",
        operation_name="Following",
        features={
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            ...
        }
    ),
    ...
}
```

#### 3.2.3 Token Pool (`auth.py`)

```python
class TokenPool:
    """Token 轮询池，支持限速感知"""

    async def get_token(self) -> TokenState:
        """获取可用 Token（非阻塞）"""
        async with self._lock:
            for _ in range(len(self._tokens)):
                token = self._tokens[self._index]
                self._index = (self._index + 1) % len(self._tokens)

                if token.is_available:
                    return token

            raise RateLimitExhausted(self._earliest_reset)

    async def get_token_with_wait(self) -> TokenState:
        """获取可用 Token（阻塞等待）"""
        while True:
            try:
                return await self.get_token()
            except RateLimitExhausted as e:
                wait_time = (e.reset_time - datetime.now()).total_seconds()
                await asyncio.sleep(max(0, wait_time))

    def mark_rate_limited(self, token: TokenState, reset_time: datetime):
        """标记 Token 被限速"""
        token.rate_limit_reset = reset_time
        token.remaining_calls = 0
```

#### 3.2.4 客户端 (`client.py`)

```python
class TwitterGraphQLClient:
    """整合的 GraphQL 客户端"""

    def __init__(
        self,
        token_pool: TokenPool,
        proxy_pool: ProxyPool | None = None,
        rate_limiter: AdaptiveRateLimiter | None = None,
    ):
        self._http = httpx.AsyncClient(http2=True, timeout=30)
        self._tokens = token_pool
        self._proxies = proxy_pool
        self._limiter = rate_limiter

    @retry(
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(RateLimitError),
    )
    async def _request(
        self,
        endpoint: EndpointType,
        variables: dict,
    ) -> dict:
        """发送 GraphQL 请求"""
        token = await self._tokens.get_token_with_wait()
        proxy = await self._proxies.get_proxy() if self._proxies else None

        # 构建请求
        url = self._build_url(endpoint, variables)
        headers = self._build_headers(token)

        # 执行请求
        response = await self._http.get(
            url,
            headers=headers,
            proxy=proxy.url if proxy else None,
        )

        # 处理响应
        if response.status_code == 429:
            reset_time = self._parse_rate_limit_headers(response)
            self._tokens.mark_rate_limited(token, reset_time)
            raise RateLimitError(reset_time=reset_time)

        return response.json()

    async def iter_following(
        self,
        user_id: str,
        max_results: int = 500,
    ) -> AsyncIterator[TwitterUser]:
        """迭代获取用户的 Following 列表"""
        cursor = None
        count = 0

        while count < max_results:
            page = await self._get_following_page(user_id, cursor)

            for user in page.users:
                yield user
                count += 1
                if count >= max_results:
                    break

            if not page.has_next:
                break
            cursor = page.next_cursor
```

### 3.3 Scraper 模块 (`src/xspider/scraper/`)

#### 3.3.1 种子采集器 (`seed_collector.py`)

```python
class SeedCollector:
    """种子用户采集器"""

    async def search_by_bio(
        self,
        keywords: list[str],
        max_results_per_keyword: int = 50,
    ) -> AsyncIterator[TwitterUser]:
        """Bio 关键词搜索"""
        seen: set[str] = set()

        for keyword in keywords:
            async for user in self._search_users(keyword):
                if user.id not in seen:
                    seen.add(user.id)
                    yield user

    async def scrape_lists(
        self,
        list_ids: list[str],
        max_members_per_list: int = 100,
    ) -> AsyncIterator[TwitterUser]:
        """抓取 Twitter Lists 成员"""
        seen: set[str] = set()

        for list_id in list_ids:
            async for user in self._get_list_members(list_id):
                if user.id not in seen:
                    seen.add(user.id)
                    yield user
```

#### 3.3.2 BFS 爬虫 (`following_scraper.py`)

```python
@dataclass
class BFSNode:
    user_id: str
    depth: int
    parent_id: str | None = None

class FollowingScraper:
    """BFS Following 网络爬虫"""

    async def crawl_from_seeds(
        self,
        seed_ids: list[str],
        max_depth: int = 2,
        max_followings_per_user: int = 500,
        on_progress: Callable[[BFSProgress], None] | None = None,
    ) -> AsyncIterator[BFSResult]:
        """从种子开始 BFS 遍历"""
        visited: set[str] = set()
        queue: asyncio.Queue[BFSNode] = asyncio.Queue()

        # 初始化队列
        for seed_id in seed_ids:
            await queue.put(BFSNode(user_id=seed_id, depth=0))

        while not queue.empty():
            node = await queue.get()

            if node.user_id in visited:
                continue
            if node.depth > max_depth:
                continue

            visited.add(node.user_id)

            # 抓取 Following
            async for following in self._client.iter_following(
                node.user_id,
                max_results=max_followings_per_user,
            ):
                # 保存边关系
                yield BFSResult(
                    source_id=node.user_id,
                    target_id=following.id,
                    target_user=following,
                    depth=node.depth + 1,
                )

                # 添加到队列
                if node.depth < max_depth:
                    await queue.put(BFSNode(
                        user_id=following.id,
                        depth=node.depth + 1,
                        parent_id=node.user_id,
                    ))

            # 进度回调
            if on_progress:
                on_progress(BFSProgress(
                    visited=len(visited),
                    queue_size=queue.qsize(),
                    current_depth=node.depth,
                ))
```

### 3.4 Graph 模块 (`src/xspider/graph/`)

#### 3.4.1 图构建器 (`builder.py`)

```python
class GraphBuilder:
    """从数据库构建 NetworkX 图"""

    async def build_from_database(self) -> nx.DiGraph:
        """从 SQLite 加载图数据"""
        graph = nx.DiGraph()

        async with self._db.session() as session:
            # 加载节点
            users = await session.execute(select(User))
            for user in users.scalars():
                graph.add_node(
                    user.id,
                    username=user.username,
                    followers_count=user.followers_count,
                    is_seed=user.is_seed,
                )

            # 加载边
            edges = await session.execute(select(Edge))
            for edge in edges.scalars():
                graph.add_edge(edge.source_id, edge.target_id)

        return graph

    def get_statistics(self, graph: nx.DiGraph) -> GraphStats:
        """计算图统计信息"""
        return GraphStats(
            node_count=graph.number_of_nodes(),
            edge_count=graph.number_of_edges(),
            density=nx.density(graph),
            avg_in_degree=sum(d for _, d in graph.in_degree()) / graph.number_of_nodes(),
            avg_out_degree=sum(d for _, d in graph.out_degree()) / graph.number_of_nodes(),
        )
```

#### 3.4.2 PageRank 计算 (`pagerank.py`)

```python
class PageRankCalculator:
    """PageRank 算法实现"""

    def compute(
        self,
        graph: nx.DiGraph,
        alpha: float = 0.85,
        max_iter: int = 100,
        tol: float = 1e-6,
    ) -> dict[str, PageRankResult]:
        """计算 PageRank 分数"""
        try:
            scores = nx.pagerank(
                graph,
                alpha=alpha,
                max_iter=max_iter,
                tol=tol,
            )
        except nx.PowerIterationFailedConvergence:
            # 使用更宽松的参数重试
            scores = nx.pagerank(graph, alpha=alpha, max_iter=500, tol=1e-4)

        results = {}
        for node_id, score in scores.items():
            results[node_id] = PageRankResult(
                user_id=node_id,
                pagerank_score=score,
                in_degree=graph.in_degree(node_id),
                out_degree=graph.out_degree(node_id),
            )

        return results

    def get_top_k(
        self,
        results: dict[str, PageRankResult],
        k: int = 100,
    ) -> list[PageRankResult]:
        """获取 Top K 用户"""
        sorted_results = sorted(
            results.values(),
            key=lambda x: x.pagerank_score,
            reverse=True,
        )
        return sorted_results[:k]
```

#### 3.4.3 隐形大佬分析 (`analysis.py`)

```python
@dataclass
class HiddenInfluencerResult:
    user_id: str
    username: str
    pagerank_score: float
    followers_count: int
    hidden_score: float
    seed_followers_count: int
    followed_by: list[str]  # 关注此用户的种子用户
    category: str  # hidden_gem | established | rising_star | potential

class HiddenInfluencerAnalyzer:
    """隐形大佬发现算法"""

    def analyze(
        self,
        graph: nx.DiGraph,
        pagerank_results: dict[str, PageRankResult],
        max_followers: int = 10000,
        min_pagerank_percentile: float = 90,
    ) -> list[HiddenInfluencerResult]:
        """
        发现隐形大佬：高 PageRank + 低粉丝数

        公式: hidden_score = pagerank / log(followers + 2)
        """
        results = []

        # 计算 PageRank 阈值
        all_scores = [r.pagerank_score for r in pagerank_results.values()]
        pr_threshold = np.percentile(all_scores, min_pagerank_percentile)

        for user_id, pr_result in pagerank_results.items():
            if pr_result.pagerank_score < pr_threshold:
                continue

            node_data = graph.nodes[user_id]
            followers = node_data.get("followers_count", 0)

            # 只关注低粉丝用户
            if followers > max_followers:
                continue

            # 计算 Hidden Score
            hidden_score = pr_result.pagerank_score / math.log(followers + 2)

            # 找出谁关注了这个用户
            predecessors = list(graph.predecessors(user_id))
            seed_followers = [
                p for p in predecessors
                if graph.nodes[p].get("is_seed", False)
            ]

            # 分类
            category = self._categorize(
                pr_result.pagerank_score,
                followers,
                len(seed_followers),
            )

            results.append(HiddenInfluencerResult(
                user_id=user_id,
                username=node_data.get("username", ""),
                pagerank_score=pr_result.pagerank_score,
                followers_count=followers,
                hidden_score=hidden_score,
                seed_followers_count=len(seed_followers),
                followed_by=seed_followers[:10],
                category=category,
            ))

        # 按 hidden_score 排序
        return sorted(results, key=lambda x: x.hidden_score, reverse=True)

    def _categorize(
        self,
        pagerank: float,
        followers: int,
        seed_followers: int,
    ) -> str:
        """分类用户类型"""
        if followers < 5000 and seed_followers >= 3:
            return "hidden_gem"      # 隐藏宝石
        elif followers >= 50000:
            return "established"     # 已确立的大V
        elif followers < 10000 and seed_followers >= 1:
            return "rising_star"     # 新星
        else:
            return "potential"       # 潜力股
```

### 3.5 AI 模块 (`src/xspider/ai/`)

#### 3.5.1 LLM 客户端 (`client.py`)

```python
class LLMClient(ABC):
    """LLM 客户端抽象基类"""

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.3,
    ) -> str:
        """文本补全"""
        ...

    @abstractmethod
    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        """JSON 格式输出"""
        ...

class OpenAIClient(LLMClient):
    """OpenAI GPT 客户端"""

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        data = json.loads(response.choices[0].message.content)
        return schema.model_validate(data)

class AnthropicClient(LLMClient):
    """Anthropic Claude 客户端"""

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[BaseModel],
    ) -> BaseModel:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        # 提取 JSON
        content = response.content[0].text
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        data = json.loads(json_match.group())
        return schema.model_validate(data)
```

#### 3.5.2 Prompt 模板 (`prompts.py`)

```python
SYSTEM_PROMPT = """You are an expert at identifying industry influencers on Twitter/X.

Your task is to analyze a user's profile and recent tweets to determine:
1. Whether they are genuinely active in the specified industry
2. Their specific focus areas and expertise
3. The quality and originality of their content

Respond in JSON format with the following structure:
{
    "is_relevant": boolean,
    "relevance_score": number (1-10),
    "topics": ["topic1", "topic2", ...],
    "tags": ["tag1", "tag2", ...],
    "reasoning": "string explaining your assessment"
}

Be strict in your assessment. Generic tech accounts or marketing bots should score low.
Look for original insights, technical depth, and authentic engagement."""

AUDIT_PROMPT_TEMPLATE = """Analyze this Twitter/X user for relevance to the {industry} industry.

## User Profile
- Username: @{username}
- Display Name: {display_name}
- Bio: {bio}
- Followers: {followers_count:,}
- Following: {following_count:,}
- Tweets: {tweet_count:,}

## Recent Tweets ({tweet_count} tweets)
{tweets}

## Instructions
1. Determine if this user is a genuine {industry} industry participant
2. Score their relevance from 1-10
3. Extract their main topics and appropriate tags
4. Explain your reasoning

Respond with JSON only."""
```

#### 3.5.3 内容审核器 (`auditor.py`)

```python
class ContentAuditor:
    """AI 内容审核器"""

    async def audit_user(
        self,
        user: TwitterUser,
        tweets: list[Tweet],
        industry: str,
    ) -> AuditResult:
        """审核单个用户"""
        prompt = build_audit_prompt(user, tweets, industry)

        response = await self._llm.complete_json(
            system=SYSTEM_PROMPT,
            user=prompt,
            schema=AuditResult,
        )

        return response

    async def audit_batch(
        self,
        users: list[tuple[TwitterUser, list[Tweet]]],
        industry: str,
        concurrency: int = 5,
    ) -> AsyncIterator[tuple[str, AuditResult]]:
        """批量审核"""
        semaphore = asyncio.Semaphore(concurrency)

        async def audit_one(user: TwitterUser, tweets: list[Tweet]):
            async with semaphore:
                result = await self.audit_user(user, tweets, industry)
                return user.id, result

        tasks = [
            asyncio.create_task(audit_one(user, tweets))
            for user, tweets in users
        ]

        for coro in asyncio.as_completed(tasks):
            yield await coro
```

---

## 4. 销售转化模块

### 4.1 CRM 服务 (`admin/services/crm_service.py`)

```python
class CRMService:
    """CRM 销售漏斗服务"""

    async def get_kanban_board(
        self,
        user_id: int,
    ) -> dict[str, list[SalesLead]]:
        """获取看板视图，按阶段分组"""
        leads = await self._get_user_leads(user_id)
        return self._group_by_stage(leads)

    async def update_lead_stage(
        self,
        lead_id: int,
        user_id: int,
        new_stage: LeadStage,
        notes: str | None = None,
    ) -> SalesLead:
        """更新线索阶段（支持看板拖拽）"""
        lead = await self._get_lead(lead_id, user_id)
        old_stage = lead.stage

        lead.stage = new_stage
        lead.stage_updated_at = datetime.utcnow()

        # 记录活动日志
        await self._log_activity(
            lead_id=lead_id,
            activity_type="stage_change",
            old_value=old_stage.value,
            new_value=new_stage.value,
            description=notes,
        )

        return lead

    async def bulk_convert_to_leads(
        self,
        user_id: int,
        tweet_id: int,
        min_authenticity_score: float = 50.0,
        only_real_users: bool = True,
        only_dm_available: bool = False,
    ) -> int:
        """批量将评论者转化为销售线索"""
        # 获取符合条件的评论者
        commenters = await self._get_qualified_commenters(
            tweet_id,
            min_authenticity_score,
            only_real_users,
            only_dm_available,
        )

        # 批量创建线索
        count = 0
        for commenter in commenters:
            if not await self._lead_exists(user_id, commenter.twitter_user_id):
                await self._create_lead_from_commenter(user_id, commenter)
                count += 1

        return count
```

### 4.2 意图分析器 (`admin/services/intent_analyzer.py`)

```python
class IntentAnalyzer:
    """购买意图分析器"""

    # 意图信号模式
    INTENT_PATTERNS = {
        "recommendation_seeking": {
            "patterns": [
                r"有人推荐", r"求推荐", r"有什么好用的",
                r"recommend", r"suggestions?", r"looking for",
            ],
            "weight": 25,
            "label": IntentLabel.HIGH_INTENT,
        },
        "price_inquiry": {
            "patterns": [r"多少钱", r"价格", r"how much", r"pricing"],
            "weight": 20,
            "label": IntentLabel.HIGH_INTENT,
        },
        "pain_point": {
            "patterns": [r"太麻烦", r"效率低", r"frustrated", r"struggle"],
            "weight": 15,
            "label": IntentLabel.MEDIUM_INTENT,
        },
        "competitor_mention": {
            "patterns": [r"我用的是", r"currently using", r"switched from"],
            "weight": -10,
            "label": IntentLabel.COMPETITOR_USER,
        },
    }

    async def analyze(
        self,
        text: str,
        user_context: dict | None = None,
        use_llm: bool = False,
    ) -> IntentAnalysisResult:
        """分析文本中的购买意图"""
        # 1. 正则模式匹配（快速）
        score = 50  # 基础分数
        signals = []

        for signal_type, config in self.INTENT_PATTERNS.items():
            for pattern in config["patterns"]:
                if re.search(pattern, text, re.IGNORECASE):
                    score += config["weight"]
                    signals.append({
                        "type": signal_type,
                        "pattern": pattern,
                        "weight": config["weight"],
                    })

        # 2. 可选 LLM 深度分析
        llm_analysis = None
        if use_llm and self._llm_client:
            llm_analysis = await self._llm_analyze(text, user_context)
            score = (score + llm_analysis.score) / 2

        # 3. 确定意图标签
        label = self._score_to_label(score)

        return IntentAnalysisResult(
            score=max(0, min(100, score)),
            label=label,
            signals=signals,
            llm_analysis=llm_analysis,
        )

    def _score_to_label(self, score: float) -> IntentLabel:
        if score >= 70:
            return IntentLabel.HIGH_INTENT
        elif score >= 40:
            return IntentLabel.MEDIUM_INTENT
        else:
            return IntentLabel.LOW_INTENT
```

### 4.3 AI 破冰生成器 (`admin/services/opener_generator.py`)

```python
class OpenerGenerator:
    """AI 破冰话术生成器"""

    TEMPLATES = {
        "professional": """
生成一条专业的商务私信开场白。

目标用户: @{screen_name}
用户简介: {bio}
最近互动: {recent_comment}
产品背景: {product_context}

要求:
- 专业但不生硬
- 体现对用户背景的了解
- 自然引出产品价值
- 不超过280字符
""",
        "casual": """
生成一条轻松友好的私信开场白...
""",
        "value_offer": """
生成一条价值导向的私信开场白...
""",
    }

    async def generate(
        self,
        lead: SalesLead,
        template_type: str = "professional",
        product_context: str | None = None,
        custom_instructions: str | None = None,
    ) -> OpenerResult:
        """生成个性化破冰话术"""
        # 1. 收集用户画像
        profile = await self._build_user_profile(lead)

        # 2. 构建 prompt
        prompt = self.TEMPLATES.get(template_type, self.TEMPLATES["professional"])
        prompt = prompt.format(
            screen_name=lead.screen_name,
            bio=lead.bio or "无",
            recent_comment=profile.get("recent_comment", "无"),
            product_context=product_context or "产品/服务",
        )

        if custom_instructions:
            prompt += f"\n\n额外要求: {custom_instructions}"

        # 3. 调用 LLM
        response = await self._llm_client.complete(
            system="你是一位专业的销售文案专家...",
            user=prompt,
            temperature=0.7,
        )

        # 4. 提取并验证结果
        opener = self._extract_opener(response)

        return OpenerResult(
            opener=opener,
            template_used=template_type,
            personalization_points=profile.get("personalization_points", []),
            confidence_score=self._calculate_confidence(opener, profile),
        )
```

### 4.4 增长监测器 (`admin/services/growth_monitor.py`)

```python
class GrowthMonitor:
    """粉丝增长异常监测"""

    # 异常检测阈值
    THRESHOLDS = {
        "spike_percent_24h": 20,      # 24h增长超过20%
        "spike_absolute_24h": 1000,   # 24h增长超过1000人
        "drop_percent_24h": 10,       # 24h下降超过10%
        "drop_absolute_24h": 500,     # 24h下降超过500人
    }

    async def take_snapshot(
        self,
        influencer_id: int,
    ) -> FollowerSnapshot:
        """记录粉丝快照"""
        influencer = await self._get_influencer(influencer_id)

        snapshot = FollowerSnapshot(
            influencer_id=influencer_id,
            followers_count=influencer.followers_count,
            following_count=influencer.following_count,
            tweet_count=influencer.tweet_count,
            snapshot_at=datetime.utcnow(),
        )

        await self._save_snapshot(snapshot)
        return snapshot

    async def detect_anomalies(
        self,
        influencer_id: int,
        lookback_hours: int = 24,
    ) -> list[GrowthAnomaly]:
        """检测增长异常"""
        snapshots = await self._get_recent_snapshots(
            influencer_id,
            hours=lookback_hours,
        )

        if len(snapshots) < 2:
            return []

        anomalies = []
        latest = snapshots[-1]
        earliest = snapshots[0]

        change = latest.followers_count - earliest.followers_count
        change_percent = (change / earliest.followers_count) * 100

        # 检测异常增长
        if change > 0:
            if (change_percent > self.THRESHOLDS["spike_percent_24h"]
                and change > self.THRESHOLDS["spike_absolute_24h"]):
                anomalies.append(GrowthAnomaly(
                    influencer_id=influencer_id,
                    anomaly_type="spike",
                    change_amount=change,
                    change_percent=change_percent,
                    severity=self._calculate_severity(change_percent),
                ))

        # 检测异常下降
        elif change < 0:
            if (abs(change_percent) > self.THRESHOLDS["drop_percent_24h"]
                and abs(change) > self.THRESHOLDS["drop_absolute_24h"]):
                anomalies.append(GrowthAnomaly(
                    influencer_id=influencer_id,
                    anomaly_type="drop",
                    change_amount=change,
                    change_percent=change_percent,
                    severity="medium",
                ))

        return anomalies
```

### 4.5 受众重合分析 (`admin/services/audience_overlap.py`)

```python
class AudienceOverlapService:
    """受众重合度分析"""

    async def analyze_overlap(
        self,
        influencer_ids: list[int],
        sample_size: int = 1000,
    ) -> list[OverlapResult]:
        """分析多个KOL的粉丝重合度"""
        results = []

        # 两两比较
        for i, id_a in enumerate(influencer_ids):
            for id_b in influencer_ids[i + 1:]:
                overlap = await self._calculate_overlap(id_a, id_b, sample_size)
                results.append(overlap)

        return sorted(results, key=lambda x: x.overlap_ratio, reverse=True)

    async def _calculate_overlap(
        self,
        influencer_a: int,
        influencer_b: int,
        sample_size: int,
    ) -> OverlapResult:
        """计算两个KOL的粉丝重合度"""
        # 获取粉丝样本
        followers_a = set(await self._get_follower_sample(influencer_a, sample_size))
        followers_b = set(await self._get_follower_sample(influencer_b, sample_size))

        # Jaccard 相似度
        intersection = followers_a & followers_b
        union = followers_a | followers_b

        overlap_ratio = len(intersection) / len(union) if union else 0

        return OverlapResult(
            influencer_a_id=influencer_a,
            influencer_b_id=influencer_b,
            overlap_count=len(intersection),
            overlap_ratio=overlap_ratio,
            unique_to_a=len(followers_a - followers_b),
            unique_to_b=len(followers_b - followers_a),
            sample_overlap_users=list(intersection)[:10],
        )
```

### 4.6 Webhook 服务 (`admin/services/webhook_service.py`)

```python
class WebhookService:
    """Webhook 事件推送服务"""

    async def trigger_event(
        self,
        event_type: WebhookEventType,
        payload: dict,
        user_id: int,
    ) -> list[WebhookLog]:
        """触发 Webhook 事件"""
        # 获取订阅此事件的所有 Webhook
        webhooks = await self._get_subscribed_webhooks(user_id, event_type)

        logs = []
        for webhook in webhooks:
            log = await self._deliver_webhook(webhook, event_type, payload)
            logs.append(log)

        return logs

    async def _deliver_webhook(
        self,
        webhook: WebhookConfig,
        event_type: WebhookEventType,
        payload: dict,
    ) -> WebhookLog:
        """投递单个 Webhook"""
        # 构建签名
        timestamp = int(time.time())
        signature = self._sign_payload(webhook.secret, payload)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event_type.value,
            "X-Webhook-Timestamp": str(timestamp),
            "X-Webhook-Signature": f"sha256={signature}",
            **(webhook.headers or {}),
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    webhook.url,
                    json=payload,
                    headers=headers,
                )

            success = 200 <= response.status_code < 300
            return WebhookLog(
                webhook_id=webhook.id,
                event_type=event_type,
                payload=payload,
                response_status=response.status_code,
                response_body=response.text[:1000],
                success=success,
            )

        except Exception as e:
            return WebhookLog(
                webhook_id=webhook.id,
                event_type=event_type,
                payload=payload,
                success=False,
                error_message=str(e),
            )

    def _sign_payload(self, secret: str, payload: dict) -> str:
        """HMAC-SHA256 签名"""
        return hmac.new(
            secret.encode(),
            json.dumps(payload, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()


# 便捷函数
async def notify_high_intent_lead(lead: SalesLead, db: AsyncSession):
    """通知高意图线索"""
    service = WebhookService(db)
    await service.trigger_event(
        WebhookEventType.HIGH_INTENT_LEAD,
        {
            "lead_id": lead.id,
            "screen_name": lead.screen_name,
            "intent_score": lead.intent_score,
            "intent_label": lead.intent_label.value,
        },
        lead.user_id,
    )
```

### 4.7 拓扑可视化 (`admin/services/topology_service.py`)

```python
class TopologyService:
    """网络拓扑可视化服务"""

    async def get_search_topology(
        self,
        search_id: int,
        user_id: int,
        max_nodes: int = 100,
        min_pagerank: float = 0.0,
    ) -> dict:
        """获取搜索结果的网络拓扑"""
        # 获取搜索结果中的影响者
        influencers = await self._get_search_influencers(
            search_id,
            user_id,
            max_nodes,
            min_pagerank,
        )

        # 构建 D3.js 兼容格式
        nodes = []
        for inf in influencers:
            nodes.append({
                "id": inf.twitter_user_id,
                "label": f"@{inf.screen_name}",
                "size": self._calculate_node_size(inf.pagerank_score),
                "color": self._relevance_to_color(inf.relevance_score),
                "followers": inf.followers_count,
                "pagerank": inf.pagerank_score,
            })

        # 获取边关系
        edges = await self._get_edges(
            [n["id"] for n in nodes],
            search_id,
        )

        return {
            "nodes": nodes,
            "edges": edges,
            "metadata": {
                "node_count": len(nodes),
                "edge_count": len(edges),
                "max_pagerank": max(n["pagerank"] for n in nodes) if nodes else 0,
            },
        }

    async def export_graph_data(
        self,
        search_id: int | None,
        user_id: int,
        format: str = "json",
    ) -> dict:
        """导出图数据"""
        topology = await self.get_search_topology(search_id, user_id)

        if format == "gephi":
            return self._convert_to_gephi(topology)
        elif format == "cytoscape":
            return self._convert_to_cytoscape(topology)
        else:
            return topology

    def _convert_to_cytoscape(self, topology: dict) -> dict:
        """转换为 Cytoscape.js 格式"""
        elements = []

        for node in topology["nodes"]:
            elements.append({
                "group": "nodes",
                "data": {"id": node["id"], "label": node["label"]},
            })

        for edge in topology["edges"]:
            elements.append({
                "group": "edges",
                "data": {
                    "source": edge["source"],
                    "target": edge["target"],
                },
            })

        return {"elements": elements}
```

---

## 5. 数据模型

### 5.1 数据库 Schema

```sql
-- 用户表
CREATE TABLE users (
    id              TEXT PRIMARY KEY,      -- Twitter User ID
    username        TEXT NOT NULL,         -- @username
    display_name    TEXT,                  -- 显示名称
    bio             TEXT,                  -- 个人简介
    location        TEXT,                  -- 位置
    url             TEXT,                  -- 个人网站
    followers_count INTEGER DEFAULT 0,     -- 粉丝数
    following_count INTEGER DEFAULT 0,     -- 关注数
    tweet_count     INTEGER DEFAULT 0,     -- 推文数
    verified        BOOLEAN DEFAULT FALSE, -- 是否认证
    created_at      TIMESTAMP,             -- 账号创建时间
    scraped_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- 抓取时间
    is_seed         BOOLEAN DEFAULT FALSE, -- 是否为种子用户
    depth           INTEGER DEFAULT 0,     -- 发现深度
    followings_scraped BOOLEAN DEFAULT FALSE  -- Following 是否已抓取
);

-- 关注关系边表
CREATE TABLE edges (
    source_id   TEXT NOT NULL,  -- Follower (关注者)
    target_id   TEXT NOT NULL,  -- Followed (被关注者)
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source_id, target_id),
    FOREIGN KEY (source_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES users(id) ON DELETE CASCADE
);

-- PageRank 排名结果表
CREATE TABLE rankings (
    user_id             TEXT PRIMARY KEY,
    pagerank_score      REAL DEFAULT 0.0,      -- PageRank 分数
    in_degree           INTEGER DEFAULT 0,      -- 入度（被关注数）
    out_degree          INTEGER DEFAULT 0,      -- 出度（关注数）
    hidden_score        REAL DEFAULT 0.0,       -- 隐形大佬分数
    seed_followers_count INTEGER DEFAULT 0,     -- 被多少种子用户关注
    computed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- AI 审核结果表
CREATE TABLE audits (
    user_id         TEXT PRIMARY KEY,
    industry        TEXT NOT NULL,             -- 目标行业
    is_relevant     BOOLEAN DEFAULT FALSE,     -- 是否相关
    relevance_score REAL DEFAULT 0.0,          -- 相关性分数 (1-10)
    topics          TEXT,                      -- 主题 (JSON array)
    tags            TEXT,                      -- 标签 (JSON array)
    reasoning       TEXT,                      -- AI 推理过程
    model_used      TEXT,                      -- 使用的模型
    tweets_analyzed INTEGER DEFAULT 0,         -- 分析的推文数
    audited_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 索引
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_followers ON users(followers_count DESC);
CREATE INDEX idx_users_is_seed ON users(is_seed);
CREATE INDEX idx_users_depth ON users(depth);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_rankings_pagerank ON rankings(pagerank_score DESC);
CREATE INDEX idx_rankings_hidden ON rankings(hidden_score DESC);
CREATE INDEX idx_audits_relevance ON audits(relevance_score DESC);
```

### 5.2 关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                           USERS                                  │
│  id | username | followers_count | is_seed | depth | ...        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
┌─────────────────┐ ┌─────────────┐ ┌─────────────┐
│      EDGES      │ │  RANKINGS   │ │   AUDITS    │
│ source | target │ │ pagerank    │ │ is_relevant │
│                 │ │ hidden_score│ │ score       │
└─────────────────┘ └─────────────┘ └─────────────┘
```

---

## 6. 核心算法

### 6.1 PageRank 算法

PageRank 通过链接结构计算节点重要性。在 KOL 发现场景中，被更多有影响力的用户关注的人，其权重更高。

#### 数学公式

```
PR(u) = (1-d)/N + d * Σ PR(v) / L(v)
        v∈B(u)

其中:
- PR(u): 用户 u 的 PageRank 分数
- d: 阻尼系数 (通常 0.85)
- N: 图中节点总数
- B(u): 关注用户 u 的所有用户集合
- L(v): 用户 v 的出度（关注数）
```

#### 实现

```python
import networkx as nx

def compute_pagerank(graph: nx.DiGraph) -> dict[str, float]:
    """
    计算 PageRank

    参数:
        graph: 有向图，边方向为 follower -> followed

    返回:
        {user_id: pagerank_score}
    """
    return nx.pagerank(
        graph,
        alpha=0.85,      # 阻尼系数
        max_iter=100,    # 最大迭代次数
        tol=1e-6,        # 收敛阈值
    )
```

### 6.2 隐形大佬算法

#### 核心思想

传统的 KOL 发现依赖粉丝数，但这容易被刷量操作欺骗。隐形大佬算法关注的是：

**被行业顶层大 V 关注，但粉丝数很少的用户**

这类用户通常是：
- 核心开发者
- 顶级 VC 合伙人
- 内幕消息源

#### 公式

```
Hidden Score = PageRank Score / log(Followers Count + 2)
```

为什么用 `log`？
- 当粉丝数为 0 时，分母为 `log(2) ≈ 0.69`，避免除零
- 对数函数平滑了粉丝数的影响，避免极端值

#### 分类标准

| 类别 | 条件 | 描述 |
|------|------|------|
| Hidden Gem | followers < 5K && seed_followers >= 3 | 隐藏宝石，真正的发现 |
| Rising Star | followers < 10K && seed_followers >= 1 | 上升期新星 |
| Established | followers >= 50K | 已确立的大 V |
| Potential | 其他 | 潜力股，待观察 |

### 6.3 BFS 网络遍历

```python
算法: BFS_CRAWL(seeds, max_depth)
输入: seeds (种子用户ID列表), max_depth (最大深度)
输出: 用户节点和边关系

1. 初始化:
   visited = {}
   queue = [(seed, 0) for seed in seeds]

2. 循环直到 queue 为空:
   (user_id, depth) = queue.pop()

   if user_id in visited:
       continue

   if depth > max_depth:
       continue

   visited[user_id] = True

   for following in get_followings(user_id):
       yield Edge(source=user_id, target=following.id)

       if depth < max_depth:
           queue.append((following.id, depth + 1))

3. 返回所有 edges
```

**复杂度分析:**
- 设种子数为 S，每用户平均关注数为 F，深度为 D
- 节点数: O(S * F^D)
- 边数: O(S * F^D * F) = O(S * F^(D+1))

**实际数据:**
- 50 种子，500 关注/用户，深度 2
- 预计节点: 50 * 500^2 = 12,500,000 (去重后约 50K-200K)
- 实际受限于 API 限速，通常 10K-50K 节点

---

## 7. API 接口

### 7.1 内部 API

#### TwitterGraphQLClient

```python
class TwitterGraphQLClient:
    # 用户查询
    async def get_user_by_screen_name(username: str) -> TwitterUser
    async def get_user_by_id(user_id: str) -> TwitterUser

    # Following/Followers
    async def get_following(user_id: str, cursor: str = None) -> FollowingPage
    async def get_followers(user_id: str, cursor: str = None) -> FollowingPage
    async def iter_following(user_id: str, max_results: int = 500) -> AsyncIterator[TwitterUser]
    async def iter_followers(user_id: str, max_results: int = 500) -> AsyncIterator[TwitterUser]

    # 推文
    async def get_user_tweets(user_id: str, count: int = 20) -> list[Tweet]
    async def get_tweet(tweet_id: str) -> Tweet
```

#### SeedCollector

```python
class SeedCollector:
    async def search_by_bio(keywords: list[str], max_results: int = 50) -> AsyncIterator[TwitterUser]
    async def scrape_lists(list_ids: list[str], max_members: int = 100) -> AsyncIterator[TwitterUser]
    async def collect_all(bio_keywords: list[str], list_ids: list[str]) -> AsyncIterator[TwitterUser]
```

#### FollowingScraper

```python
class FollowingScraper:
    async def crawl_from_seeds(
        seed_ids: list[str],
        max_depth: int = 2,
        max_followings_per_user: int = 500,
        on_progress: Callable[[BFSProgress], None] = None,
    ) -> AsyncIterator[BFSResult]
```

#### GraphBuilder & PageRankCalculator

```python
class GraphBuilder:
    async def build_from_database() -> nx.DiGraph
    def get_statistics(graph: nx.DiGraph) -> GraphStats

class PageRankCalculator:
    def compute(graph: nx.DiGraph, alpha: float = 0.85) -> dict[str, PageRankResult]
    def get_top_k(results: dict, k: int = 100) -> list[PageRankResult]
```

#### ContentAuditor

```python
class ContentAuditor:
    async def audit_user(user: TwitterUser, tweets: list[Tweet], industry: str) -> AuditResult
    async def audit_batch(users: list[tuple], industry: str, concurrency: int = 5) -> AsyncIterator[tuple]
    async def audit_and_save(user_id: str, industry: str) -> AuditResult
```

### 7.2 CLI 命令

```bash
# 种子采集
xspider seed search --keywords "AI,Web3" --min-followers 1000 --limit 50
xspider seed import --file seeds.json
xspider seed list --limit 100
xspider seed clear

# 网络爬取
xspider crawl --depth 2 --concurrency 5 --max-followings 500
xspider crawl status
xspider crawl reset

# PageRank 排名
xspider rank compute --alpha 0.85
xspider rank top --limit 100 --format table
xspider rank --find-hidden --top 50
xspider rank analyze --user-id 12345

# AI 审核
xspider audit --industry "AI/ML" --model gpt-4 --top 100
xspider audit status
xspider audit results --relevant-only --min-score 7

# 导出
xspider export --format csv --output results.csv
xspider export --format json --include-graph --output network.json
xspider export all --output-dir exports/
```

---

## 8. 配置指南

### 8.1 环境变量

创建 `.env` 文件:

```bash
# ==================== Twitter 认证 ====================
# Token 格式: JSON 数组，每个元素包含 bearer_token, ct0, auth_token
# 获取方式: 浏览器登录 Twitter，F12 -> Network -> 找任意 GraphQL 请求 -> Headers
TWITTER_TOKENS='[
  {
    "bearer_token": "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D...",
    "ct0": "abc123def456...",
    "auth_token": "xyz789..."
  },
  {
    "bearer_token": "...",
    "ct0": "...",
    "auth_token": "..."
  }
]'

# ==================== 代理配置 (可选) ====================
# 格式: JSON 数组，支持 http/https/socks5
PROXY_URLS='[
  "http://user:pass@proxy1.example.com:8080",
  "socks5://proxy2.example.com:1080"
]'

# ==================== LLM API ====================
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...

# ==================== 数据库 ====================
DATABASE_URL=sqlite+aiosqlite:///data/xspider.db

# ==================== 爬虫参数 ====================
MAX_CONCURRENT_REQUESTS=5      # 并发请求数
REQUEST_DELAY_MS=1000          # 请求间隔 (毫秒)
MAX_FOLLOWINGS_PER_USER=500    # 每用户最大抓取 Following 数
CRAWL_DEPTH=2                  # 默认爬取深度

# ==================== 日志 ====================
LOG_LEVEL=INFO                 # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=json                # json 或 console
```

### 8.2 获取 Twitter Token

1. **浏览器登录 Twitter**
2. **打开开发者工具 (F12)**
3. **切换到 Network 标签**
4. **刷新页面，找任意 GraphQL 请求**
5. **从 Request Headers 中提取:**

```
authorization: Bearer AAAAAAAAAAAAAAAAAAAAANRILgAA...  -> bearer_token
x-csrf-token: abc123...                                 -> ct0
cookie: auth_token=xyz789...                           -> auth_token
```

### 8.3 代理配置建议

| 爬取规模 | 推荐代理类型 | 预估成本 |
|---------|-------------|---------|
| 小规模 (< 1K 用户) | 无需代理 | $0 |
| 中规模 (1K-10K) | 数据中心代理 | $10-50/月 |
| 大规模 (> 10K) | 住宅代理 | $50-200/月 |

推荐代理服务:
- Bright Data (原 Luminati)
- Oxylabs
- SmartProxy

---

## 9. 开发指南

### 9.1 项目设置

```bash
# 克隆项目
git clone https://github.com/yourname/xspider.git
cd xspider

# 创建虚拟环境
uv venv
source .venv/bin/activate

# 安装依赖 (包含开发依赖)
uv pip install -e ".[dev]"

# 初始化数据库
python -c "import asyncio; from xspider.storage import init_database; asyncio.run(init_database())"

# 运行测试
pytest tests/ -v --cov=xspider
```

### 9.2 代码规范

```bash
# 格式化
ruff format src/ tests/

# Lint 检查
ruff check src/ tests/

# 类型检查
mypy src/
```

### 9.3 添加新的 GraphQL 端点

```python
# 1. 在 endpoints.py 中添加端点类型
class EndpointType(Enum):
    ...
    NEW_ENDPOINT = "NewEndpoint"

# 2. 定义端点配置
ENDPOINTS[EndpointType.NEW_ENDPOINT] = GraphQLEndpoint(
    query_id="xxxxxxxx",  # 从浏览器网络请求中获取
    operation_name="NewEndpoint",
    features={...},
)

# 3. 在 client.py 中添加方法
async def new_endpoint_method(self, param: str) -> Result:
    response = await self._request(
        EndpointType.NEW_ENDPOINT,
        {"param": param},
    )
    return self._parse_response(response)
```

### 9.4 添加新的 CLI 命令

```python
# 1. 创建命令文件 src/xspider/cli/commands/newcmd.py
import typer
from rich.console import Console

app = typer.Typer(help="New command description")
console = Console()

@app.command()
def subcommand(
    option: str = typer.Option(..., help="Option description"),
):
    """Subcommand description."""
    console.print(f"Running with {option}")

# 2. 在 app.py 中注册
from xspider.cli.commands import newcmd
app.add_typer(newcmd.app, name="newcmd")
```

### 9.5 测试

```python
# tests/unit/test_pagerank.py
import pytest
import networkx as nx
from xspider.graph import PageRankCalculator

def test_pagerank_simple_graph():
    """测试简单图的 PageRank 计算"""
    graph = nx.DiGraph()
    graph.add_edges_from([
        ("A", "B"),
        ("B", "C"),
        ("C", "A"),
    ])

    calculator = PageRankCalculator()
    results = calculator.compute(graph)

    # 环形图中所有节点 PageRank 应该相等
    scores = [r.pagerank_score for r in results.values()]
    assert len(set(round(s, 6) for s in scores)) == 1

@pytest.mark.asyncio
async def test_graph_builder_from_database(mock_database):
    """测试从数据库构建图"""
    builder = GraphBuilder(mock_database)
    graph = await builder.build_from_database()

    assert graph.number_of_nodes() > 0
    assert graph.number_of_edges() > 0
```

---

## 10. 部署运维

### 10.1 性能优化

#### Token 池大小

```python
# 计算所需 Token 数量
每 Token 限速: 500 requests / 15 min = 33.3 req/min
目标吞吐量: 1000 users / hour = 16.7 users/min
每用户请求: ~3 (profile + following pages)
所需请求: 16.7 * 3 = 50 req/min

所需 Token 数: ceil(50 / 33.3) = 2 个

# 推荐: 准备 5-10 个 Token，留有余量
```

#### 内存优化

```python
# 大规模图处理
# 10万节点 + 100万边 ≈ 500MB 内存

# 如果内存不足，分批处理
async def process_in_batches(user_ids: list[str], batch_size: int = 1000):
    for i in range(0, len(user_ids), batch_size):
        batch = user_ids[i:i+batch_size]
        await process_batch(batch)
        gc.collect()  # 主动回收内存
```

### 10.2 监控指标

```python
# 关键指标
metrics = {
    "scraper": {
        "users_scraped_total": Counter,
        "edges_collected_total": Counter,
        "scrape_errors_total": Counter,
        "scrape_duration_seconds": Histogram,
    },
    "twitter_api": {
        "requests_total": Counter,
        "rate_limit_hits_total": Counter,
        "token_exhaustions_total": Counter,
        "request_latency_seconds": Histogram,
    },
    "graph": {
        "nodes_count": Gauge,
        "edges_count": Gauge,
        "pagerank_computation_seconds": Histogram,
    },
    "ai_audit": {
        "audits_total": Counter,
        "audit_duration_seconds": Histogram,
        "llm_tokens_used": Counter,
    },
}
```

### 10.3 故障处理

| 故障类型 | 检测方式 | 自动恢复 |
|---------|---------|---------|
| Token 失效 | 401 响应 | 移除失效 Token，使用备用 |
| 限速 | 429 响应 | 等待 reset_time 后重试 |
| 代理封禁 | 连接超时 | 切换代理，冷却 30 分钟 |
| 数据库锁 | SQLITE_BUSY | 指数退避重试 |

### 10.4 数据备份

```bash
# 定期备份 SQLite 数据库
sqlite3 data/xspider.db ".backup data/backup/xspider_$(date +%Y%m%d).db"

# 导出关键数据
xspider export all --output-dir data/backup/

# 压缩旧备份
find data/backup -name "*.db" -mtime +7 -exec gzip {} \;
```

---

## 附录

### A. 目录结构

```
xspider/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
│
├── docs/
│   └── TECHNICAL.md          # 本文档
│
├── src/xspider/
│   ├── __init__.py
│   ├── __main__.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py          # 配置管理
│   │   ├── exceptions.py      # 异常定义
│   │   └── logging.py         # 日志配置
│   │
│   ├── twitter/
│   │   ├── __init__.py
│   │   ├── models.py          # 数据模型
│   │   ├── endpoints.py       # GraphQL 端点
│   │   ├── auth.py            # Token Pool
│   │   ├── proxy_pool.py      # 代理池
│   │   ├── rate_limiter.py    # 限速器
│   │   └── client.py          # GraphQL 客户端
│   │
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── seed_collector.py  # 种子采集
│   │   ├── following_scraper.py # BFS 爬虫
│   │   └── tweet_scraper.py   # 推文抓取
│   │
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── builder.py         # 图构建
│   │   ├── pagerank.py        # PageRank
│   │   ├── analysis.py        # 隐形大佬分析
│   │   └── storage.py         # 排名持久化
│   │
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── client.py          # LLM 客户端
│   │   ├── prompts.py         # Prompt 模板
│   │   ├── models.py          # 审核模型
│   │   └── auditor.py         # 内容审核
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py        # 数据库连接
│   │   ├── models.py          # ORM 模型
│   │   └── repositories/      # 数据仓库
│   │
│   └── cli/
│       ├── __init__.py
│       ├── app.py             # Typer 应用
│       └── commands/          # 子命令
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
│
├── scripts/
│   ├── setup_db.py
│   └── export_results.py
│
└── data/
    ├── seeds/
    ├── cache/
    └── exports/
```

### B. 依赖版本

```toml
[project.dependencies]
httpx = ">=0.27.0"
pydantic = ">=2.5.0"
pydantic-settings = ">=2.1.0"
typer = ">=0.9.0"
rich = ">=13.7.0"
sqlalchemy = ">=2.0.0"
aiosqlite = ">=0.19.0"
networkx = ">=3.2.0"
numpy = ">=1.26.0"
openai = ">=1.10.0"
anthropic = ">=0.18.0"
structlog = ">=24.1.0"
tenacity = ">=8.2.0"
python-dotenv = ">=1.0.0"
```

### C. 参考资料

- [NetworkX PageRank 文档](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.link_analysis.pagerank_alg.pagerank.html)
- [Twitter GraphQL API 逆向分析](https://github.com/zedeus/nitter)
- [社交网络分析方法论](https://en.wikipedia.org/wiki/Social_network_analysis)

---

*文档版本: 2.0.0*
*最后更新: 2024-02*

### 更新日志

| 版本 | 日期 | 更新内容 |
|-----|------|---------|
| 1.0.0 | 2024-01 | 初始版本 |
| 2.0.0 | 2024-02 | 新增销售转化模块：CRM、AI破冰、意图分析、增长监测、受众重合、Webhook、拓扑可视化 |
