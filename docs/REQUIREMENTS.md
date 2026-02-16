# xspider 需求规格文档

> 本文档描述 xspider 系统的完整需求规格，用于指导开发和维护。

## 目录

1. [系统概述](#1-系统概述)
2. [核心功能：KOL发现](#2-核心功能kol发现)
3. [后台管理系统](#3-后台管理系统)
4. [网红监控系统](#4-网红监控系统)
5. [数据模型](#5-数据模型)
6. [API接口规范](#6-api接口规范)
7. [技术架构](#7-技术架构)

---

## 1. 系统概述

### 1.1 产品定位

xspider 是一个基于社交网络分析的 Twitter/X KOL（关键意见领袖）发现系统，帮助用户：
- 发现特定行业的隐藏影响力者
- 监控网红动态和粉丝互动
- 分析评论者真实性，筛选高质量潜在客户

### 1.2 目标用户

| 用户类型 | 使用场景 |
|---------|---------|
| 市场营销人员 | 寻找行业KOL进行合作推广 |
| 销售团队 | 从网红粉丝中筛选潜在客户 |
| 投资机构 | 发现行业核心人物和信息源 |
| 品牌方 | 监控竞品网红合作动态 |

### 1.3 系统模块

```
┌─────────────────────────────────────────────────────────┐
│                      xspider 系统                        │
├─────────────┬─────────────┬─────────────┬───────────────┤
│  KOL发现    │  后台管理    │  网红监控    │   数据导出    │
│  - 种子采集  │  - 账号管理  │  - 推文抓取  │   - CSV      │
│  - 网络爬取  │  - 代理管理  │  - 评论采集  │   - JSON     │
│  - 排名计算  │  - 用户管理  │  - 真实性分析│   - API      │
│  - AI审核   │  - 积分系统  │  - DM检测   │              │
└─────────────┴─────────────┴─────────────┴───────────────┘
```

---

## 2. 核心功能：KOL发现

### 2.1 种子用户采集

**功能描述**：通过关键词搜索和Twitter列表抓取初始种子用户

**输入参数**：
| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| keywords | string | 是 | 搜索关键词，逗号分隔 |
| industry | string | 否 | 行业分类 |
| limit | int | 否 | 最大采集数量，默认50 |

**处理流程**：
```
1. 解析关键词列表
2. 调用Twitter搜索API
3. 过滤符合条件的用户
4. 存储到种子用户表
5. 返回采集统计
```

**CLI命令**：
```bash
xspider seed search --keywords "AI,Web3,DeFi" --limit 50
```

### 2.2 关注网络爬取

**功能描述**：BFS遍历种子用户的关注关系，构建社交网络图

**输入参数**：
| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| depth | int | 否 | 爬取深度，默认2 |
| concurrency | int | 否 | 并发数，默认5 |
| max_following | int | 否 | 每用户最大关注数，默认500 |

**处理流程**：
```
1. 从种子用户队列取出用户
2. 获取该用户的关注列表
3. 将新用户加入队列（如未超过深度）
4. 记录关注边到图数据库
5. 重复直到队列为空或达到限制
```

**CLI命令**：
```bash
xspider crawl --depth 2 --concurrency 5
```

### 2.3 PageRank排名计算

**功能描述**：使用PageRank算法计算用户影响力分数

**算法公式**：
```python
# 标准PageRank
PR(u) = (1-d) + d * Σ(PR(v) / L(v))
# d = 0.85 (阻尼系数)
# L(v) = 节点v的出度

# 隐藏影响力分数
hidden_score = pagerank_score / log(followers_count + 2)
```

**输出字段**：
| 字段 | 类型 | 说明 |
|-----|------|------|
| pagerank_score | float | PageRank分数 |
| hidden_score | float | 隐藏影响力分数 |
| rank | int | 排名 |

**CLI命令**：
```bash
xspider rank --find-hidden --top 100
```

### 2.4 AI内容审核

**功能描述**：使用LLM判断用户是否与目标行业相关

**输入参数**：
| 参数 | 类型 | 必填 | 说明 |
|-----|------|-----|------|
| industry | string | 是 | 目标行业 |
| model | string | 否 | LLM模型，默认gpt-4 |
| batch_size | int | 否 | 批量处理数，默认10 |

**审核维度**：
- 用户简介相关性
- 最近推文内容
- 互动对象特征

**输出标签**：
| 标签 | 说明 |
|-----|------|
| relevant | 与行业相关 |
| irrelevant | 与行业无关 |
| uncertain | 无法确定 |

**CLI命令**：
```bash
xspider audit --industry "AI/ML" --model gpt-4
```

---

## 3. 后台管理系统

### 3.1 用户认证

#### 3.1.1 用户注册

**接口**：`POST /api/auth/register`

**请求体**：
```json
{
  "username": "string (3-50字符)",
  "email": "string (有效邮箱)",
  "password": "string (最少6字符)"
}
```

**业务规则**：
- 用户名全局唯一
- 邮箱全局唯一
- 密码使用bcrypt加密存储
- 新用户默认角色为 `user`
- 新用户默认积分为 0

#### 3.1.2 用户登录

**接口**：`POST /api/auth/login`

**请求体**：
```json
{
  "username": "string",
  "password": "string"
}
```

**响应**：
```json
{
  "access_token": "JWT token",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**业务规则**：
- JWT有效期24小时
- 登录成功更新 `last_login_at`
- 连续失败可触发账号锁定（待实现）

### 3.2 Twitter账号管理

#### 3.2.1 数据模型

```python
class TwitterAccount:
    id: int                    # 主键
    name: str | None           # 账号备注名
    bearer_token: str          # Bearer Token (加密存储)
    ct0: str                   # ct0 Cookie (加密存储)
    auth_token: str            # auth_token Cookie (加密存储)
    status: AccountStatus      # 状态枚举
    last_used_at: datetime     # 最后使用时间
    last_check_at: datetime    # 最后检测时间
    request_count: int         # 请求计数
    error_count: int           # 错误计数
    rate_limit_reset: datetime # 限流恢复时间
    created_at: datetime       # 创建时间
    created_by: int            # 创建者ID
    notes: str | None          # 备注
```

#### 3.2.2 状态枚举

| 状态 | 值 | 说明 |
|-----|-----|------|
| ACTIVE | active | 正常可用 |
| RATE_LIMITED | rate_limited | 被限流 |
| BANNED | banned | 账号被封禁 |
| NEEDS_VERIFY | needs_verify | 需要验证 |
| ERROR | error | 其他错误 |

#### 3.2.3 功能需求

| 功能 | 接口 | 说明 |
|-----|------|------|
| 添加账号 | POST /api/accounts | 添加单个账号 |
| 批量导入 | POST /api/accounts/batch | JSON格式批量导入 |
| 账号列表 | GET /api/accounts | 分页查询 |
| 更新账号 | PUT /api/accounts/{id} | 更新账号信息 |
| 删除账号 | DELETE /api/accounts/{id} | 删除账号 |
| 状态检测 | POST /api/accounts/{id}/check | 检测单个账号 |
| 批量检测 | POST /api/accounts/check-all | 检测所有账号 |

### 3.3 代理IP管理

#### 3.3.1 数据模型

```python
class ProxyServer:
    id: int                  # 主键
    name: str | None         # 代理备注名
    url: str                 # 代理URL (如 http://user:pass@host:port)
    protocol: ProxyProtocol  # 协议类型
    status: ProxyStatus      # 状态
    last_check_at: datetime  # 最后检测时间
    response_time: float     # 响应时间(ms)
    success_rate: float      # 成功率
    total_requests: int      # 总请求数
    failed_requests: int     # 失败请求数
    created_at: datetime     # 创建时间
    created_by: int          # 创建者ID
```

#### 3.3.2 协议枚举

| 协议 | 值 |
|-----|-----|
| HTTP | http |
| HTTPS | https |
| SOCKS5 | socks5 |

#### 3.3.3 功能需求

| 功能 | 接口 | 说明 |
|-----|------|------|
| 添加代理 | POST /api/proxies | 添加单个代理 |
| 批量导入 | POST /api/proxies/batch | 每行一个URL |
| 代理列表 | GET /api/proxies | 分页查询 |
| 健康检查 | POST /api/proxies/{id}/check | 检测单个代理 |
| 批量检查 | POST /api/proxies/check-all | 检测所有代理 |

### 3.4 用户管理（管理员）

#### 3.4.1 角色权限

| 角色 | 权限 |
|-----|------|
| admin | 所有功能 + 用户管理 + 账号管理 + 代理管理 |
| user | 搜索 + 监控 + 导出 + 查看积分 |

#### 3.4.2 功能需求

| 功能 | 接口 | 权限 |
|-----|------|------|
| 用户列表 | GET /api/users | admin |
| 创建用户 | POST /api/users | admin |
| 更新用户 | PUT /api/users/{id} | admin |
| 删除用户 | DELETE /api/users/{id} | admin |
| 积分充值 | POST /api/users/{id}/recharge | admin |
| 重置密码 | POST /api/users/{id}/reset-password | admin |

### 3.5 积分系统

#### 3.5.1 积分消耗规则

| 操作 | 消耗积分 | 说明 |
|-----|---------|------|
| 搜索种子用户 | 10 | 每次搜索 |
| 爬取关注网络 | 5 | 每100用户 |
| AI审核 | 2 | 每用户 |
| LLM调用 | 1 | 每1K tokens |
| 网红监控 | 5 | 每个网红/天 |
| 评论分析 | 1 | 每100条评论 |

#### 3.5.2 交易类型

| 类型 | 值 | 说明 |
|-----|-----|------|
| RECHARGE | recharge | 充值 |
| SEARCH | search | 搜索消耗 |
| LLM_CALL | llm_call | LLM调用消耗 |
| REFUND | refund | 退款 |
| MONITOR | monitor | 监控消耗 |
| COMMENTER_ANALYSIS | commenter_analysis | 评论分析消耗 |

---

## 4. 网红监控系统

### 4.1 功能概述

监控指定网红的推文动态，抓取评论者信息，分析真实性并检测私信可用性。

### 4.2 监控工作流

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  添加网红    │ ──▶ │  抓取推文    │ ──▶ │  抓取评论    │
│  (screen_name)    │  (定时任务)   │     │  (按需触发)   │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  导出数据    │ ◀── │  检测DM     │ ◀── │  分析真实性  │
│  (CSV/JSON)  │     │  (私信可用性) │     │  (贴标签)    │
└─────────────┘     └─────────────┘     └─────────────┘
```

### 4.3 监控网红 (MonitoredInfluencer)

#### 4.3.1 数据模型

```python
class MonitoredInfluencer:
    id: int                       # 主键
    user_id: int                  # 所属用户ID
    twitter_user_id: str          # Twitter用户ID
    screen_name: str              # Twitter用户名
    display_name: str | None      # 显示名称
    bio: str | None               # 简介
    followers_count: int          # 粉丝数
    following_count: int          # 关注数
    tweet_count: int              # 推文数
    verified: bool                # 是否认证
    profile_image_url: str | None # 头像URL
    status: MonitorStatus         # 监控状态
    monitor_since: datetime       # 监控开始时间
    monitor_until: datetime       # 监控结束时间
    check_interval_minutes: int   # 检查间隔(分钟)
    last_checked_at: datetime     # 最后检查时间
    next_check_at: datetime       # 下次检查时间
    tweets_collected: int         # 已采集推文数
    commenters_analyzed: int      # 已分析评论者数
    credits_used: int             # 消耗积分
    notes: str | None             # 备注
```

#### 4.3.2 监控状态

| 状态 | 值 | 说明 |
|-----|-----|------|
| ACTIVE | active | 活跃监控中 |
| PAUSED | paused | 暂停监控 |
| COMPLETED | completed | 监控完成 |
| ERROR | error | 监控出错 |

#### 4.3.3 功能需求

| 功能 | 接口 | 说明 |
|-----|------|------|
| 添加监控 | POST /api/monitors/influencers | 添加网红监控 |
| 监控列表 | GET /api/monitors/influencers | 获取监控列表 |
| 监控详情 | GET /api/monitors/influencers/{id} | 获取单个详情 |
| 更新设置 | PATCH /api/monitors/influencers/{id} | 更新监控设置 |
| 删除监控 | DELETE /api/monitors/influencers/{id} | 删除监控 |
| 抓取推文 | POST /api/monitors/influencers/{id}/fetch-tweets | 手动触发抓取 |

### 4.4 监控推文 (MonitoredTweet)

#### 4.4.1 数据模型

```python
class MonitoredTweet:
    id: int                    # 主键
    influencer_id: int         # 所属网红ID
    tweet_id: str              # Twitter推文ID
    content: str               # 推文内容
    tweet_type: str            # 推文类型
    like_count: int            # 点赞数
    retweet_count: int         # 转推数
    reply_count: int           # 回复数
    quote_count: int           # 引用数
    view_count: int | None     # 浏览数
    bookmark_count: int        # 收藏数
    has_media: bool            # 是否有媒体
    media_urls: str | None     # 媒体URL (JSON)
    has_links: bool            # 是否有链接
    links: str | None          # 链接 (JSON)
    tweeted_at: datetime       # 发布时间
    collected_at: datetime     # 采集时间
    commenters_scraped: bool   # 评论已抓取
    commenters_analyzed: bool  # 评论已分析
    total_commenters: int      # 评论者总数
```

### 4.5 推文评论者 (TweetCommenter)

#### 4.5.1 数据模型

```python
class TweetCommenter:
    id: int                       # 主键
    tweet_id: int                 # 所属推文ID
    twitter_user_id: str          # Twitter用户ID
    screen_name: str              # 用户名
    display_name: str | None      # 显示名称
    bio: str | None               # 简介
    profile_image_url: str | None # 头像
    followers_count: int          # 粉丝数
    following_count: int          # 关注数
    tweet_count: int              # 推文数
    verified: bool                # 是否认证
    account_created_at: datetime  # 账号创建时间

    # 评论信息
    comment_text: str             # 评论内容
    comment_tweet_id: str         # 评论推文ID
    commented_at: datetime        # 评论时间
    comment_like_count: int       # 评论点赞数
    comment_reply_count: int      # 评论回复数

    # DM状态
    dm_status: DMStatus           # DM可用状态
    can_dm: bool                  # 是否可私信
    dm_checked_at: datetime       # DM检测时间

    # 真实性分析
    is_analyzed: bool             # 是否已分析
    authenticity_score: float     # 真实性分数 (0-100)
    primary_label: AuthenticityLabel  # 主要标签
    labels: str                   # 所有标签 (JSON)
    analysis_reasoning: str       # 分析理由
    is_bot: bool                  # 是否机器人
    is_suspicious: bool           # 是否可疑
    is_real_user: bool            # 是否真实用户
    analyzed_at: datetime         # 分析时间
```

#### 4.5.2 真实性标签

| 标签 | 值 | 判定条件 |
|-----|-----|---------|
| REAL_USER | real_user | 分数≥50且非机器人 |
| VERIFIED | verified | Twitter认证账号 |
| INFLUENCER | influencer | 粉丝数>10,000 |
| SUSPICIOUS | suspicious | 可疑行为模式 |
| BOT | bot | 机器人特征明显 |
| NEW_ACCOUNT | new_account | 账号<30天 |
| LOW_ACTIVITY | low_activity | 推文<10条 |
| HIGH_ENGAGEMENT | high_engagement | 粉丝>1000且推文>500 |

#### 4.5.3 真实性分析算法

```python
# 初始分数
score = 50.0

# 加分项
if verified:           score += 30   # 认证账号
if account_age > 1年:  score += 10   # 老账号
if tweets > 1000:      score += 5    # 活跃账号
if followers > 10000:  score += 15   # 高粉丝
if has_bio:            score += 5    # 有简介
if comment_likes > 10: score += 5    # 评论有互动

# 减分项
if account_age < 30天: score -= 15   # 新账号
if tweets < 10:        score -= 10   # 低活跃
if follow_ratio > 100: score -= 20   # 异常关注比
if no_followers:       score -= 15   # 无粉丝
if bot_username:       score -= 25   # 机器人用户名
if bot_bio:            score -= 20   # 机器人简介
if spam_comment:       score -= 10   # 垃圾评论
if no_bio:             score -= 5    # 无简介

# 最终分数范围 0-100
score = max(0, min(100, score))
```

#### 4.5.4 DM状态

| 状态 | 值 | 说明 |
|-----|-----|------|
| OPEN | open | 所有人可私信 |
| FOLLOWERS_ONLY | followers_only | 仅关注者可私信 |
| CLOSED | closed | 关闭私信 |
| UNKNOWN | unknown | 无法确定 |

#### 4.5.5 DM检测逻辑

```python
# 1. API检测 (优先)
if user_data.can_dm:
    return DMStatus.OPEN

# 2. 特征推断
if verified:
    return DMStatus.OPEN  # 认证账号通常开放

if followers > 100000:
    return DMStatus.FOLLOWERS_ONLY  # 大V通常限制

if "dm" in bio.lower() or "business" in bio.lower():
    return DMStatus.OPEN  # 商务合作意向

if "no dm" in bio.lower():
    return DMStatus.CLOSED

return DMStatus.UNKNOWN
```

### 4.6 功能接口

| 功能 | 接口 | 说明 |
|-----|------|------|
| 抓取评论 | POST /api/monitors/tweets/{id}/scrape-commenters | 抓取推文评论者 |
| 评论列表 | GET /api/monitors/tweets/{id}/commenters | 获取评论者列表 |
| 分析真实性 | POST /api/monitors/tweets/{id}/analyze-commenters | 分析评论者真实性 |
| 分析摘要 | GET /api/monitors/tweets/{id}/analysis-summary | 获取分析统计 |
| 检测DM | POST /api/monitors/tweets/{id}/check-dm | 检测DM可用性 |
| DM摘要 | GET /api/monitors/tweets/{id}/dm-summary | 获取DM统计 |
| 导出数据 | POST /api/monitors/export-commenters | 导出评论者数据 |

---

## 5. 数据模型

### 5.1 ER图

```
┌─────────────────┐       ┌─────────────────┐
│   AdminUser     │       │  TwitterAccount │
├─────────────────┤       ├─────────────────┤
│ id              │◀──┐   │ id              │
│ username        │   │   │ bearer_token    │
│ email           │   │   │ ct0             │
│ password_hash   │   │   │ auth_token      │
│ role            │   └───│ created_by      │
│ credits         │       │ status          │
└────────┬────────┘       └─────────────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐       ┌─────────────────┐
│MonitoredInfluencer│     │   ProxyServer   │
├─────────────────┤       ├─────────────────┤
│ id              │       │ id              │
│ user_id         │       │ url             │
│ twitter_user_id │       │ protocol        │
│ screen_name     │       │ status          │
│ status          │       │ response_time   │
└────────┬────────┘       └─────────────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐
│  MonitoredTweet │
├─────────────────┤
│ id              │
│ influencer_id   │
│ tweet_id        │
│ content         │
│ like_count      │
└────────┬────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐
│ TweetCommenter  │
├─────────────────┤
│ id              │
│ tweet_id        │
│ twitter_user_id │
│ authenticity_score│
│ primary_label   │
│ dm_status       │
└─────────────────┘
```

### 5.2 索引设计

```sql
-- 高频查询索引
CREATE INDEX idx_influencer_user ON monitored_influencers(user_id);
CREATE INDEX idx_influencer_status ON monitored_influencers(status);
CREATE INDEX idx_tweet_influencer ON monitored_tweets(influencer_id);
CREATE INDEX idx_commenter_tweet ON tweet_commenters(tweet_id);
CREATE INDEX idx_commenter_real ON tweet_commenters(is_real_user);
CREATE INDEX idx_commenter_dm ON tweet_commenters(can_dm);
CREATE INDEX idx_commenter_score ON tweet_commenters(authenticity_score);
```

---

## 6. API接口规范

### 6.1 通用规范

#### 请求头
```
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

#### 响应格式
```json
// 成功
{
  "data": { ... },
  "message": "Success"
}

// 错误
{
  "detail": "Error message"
}
```

#### 分页参数
```
page: int (默认1)
page_size: int (默认20, 最大100)
```

#### 分页响应
```json
{
  "items": [...],
  "total": 100,
  "page": 1,
  "page_size": 20,
  "pages": 5
}
```

### 6.2 错误码

| HTTP状态码 | 说明 |
|-----------|------|
| 200 | 成功 |
| 201 | 创建成功 |
| 400 | 请求参数错误 |
| 401 | 未认证 |
| 403 | 无权限 |
| 404 | 资源不存在 |
| 422 | 验证错误 |
| 500 | 服务器错误 |
| 503 | 服务不可用 |

---

## 7. 技术架构

### 7.1 技术栈

| 层级 | 技术 |
|-----|------|
| Web框架 | FastAPI |
| 模板引擎 | Jinja2 |
| 前端框架 | Bootstrap 5 |
| 数据库 | SQLite / PostgreSQL |
| ORM | SQLAlchemy 2.0 (async) |
| 认证 | JWT (python-jose) |
| 密码 | bcrypt |
| HTTP客户端 | httpx (async) |
| 图计算 | NetworkX |
| CLI | Typer |

### 7.2 目录结构

```
src/xspider/
├── admin/                  # 后台管理模块
│   ├── app.py             # FastAPI应用入口
│   ├── auth.py            # JWT认证
│   ├── database.py        # 数据库会话
│   ├── models.py          # SQLAlchemy模型
│   ├── schemas.py         # Pydantic模式
│   ├── routes/            # API路由
│   │   ├── auth.py        # 认证路由
│   │   ├── dashboard.py   # 仪表板路由
│   │   ├── monitors.py    # 监控路由
│   │   ├── twitter_accounts.py
│   │   ├── proxies.py
│   │   ├── users.py
│   │   ├── credits.py
│   │   ├── searches.py
│   │   └── pages.py       # 页面路由
│   ├── services/          # 业务服务
│   │   ├── influencer_monitor.py
│   │   ├── commenter_scraper.py
│   │   ├── authenticity_analyzer.py
│   │   ├── dm_checker.py
│   │   ├── account_monitor.py
│   │   ├── proxy_checker.py
│   │   ├── credit_service.py
│   │   └── token_pool_integration.py
│   ├── templates/         # HTML模板
│   └── static/            # 静态资源
├── cli/                   # CLI命令
│   ├── app.py
│   └── commands/
├── core/                  # 核心工具
│   ├── config.py
│   └── logging.py
├── twitter/               # Twitter客户端
│   ├── client.py
│   └── auth.py
├── scraper/               # 数据抓取
├── graph/                 # 图分析
├── ai/                    # AI模块
└── storage/               # 存储层
    ├── database.py
    └── models.py
```

### 7.3 部署架构

```
┌─────────────────────────────────────────────────────────┐
│                      Nginx (反向代理)                     │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│               Uvicorn (ASGI服务器)                        │
│                   xspider.admin                          │
└─────────────────────────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ SQLite/  │  │  Redis   │  │ Twitter  │
        │PostgreSQL│  │ (可选)   │  │   API    │
        └──────────┘  └──────────┘  └──────────┘
```

### 7.4 配置项

```bash
# .env 配置文件

# 数据库
DATABASE_URL=sqlite:///./xspider.db

# JWT
SECRET_KEY=your-secret-key
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Twitter
TWITTER_TOKENS=[{"bearer_token":"...", "ct0":"...", "auth_token":"..."}]

# AI
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# 服务器
ADMIN_HOST=0.0.0.0
ADMIN_PORT=8000
```

---

## 附录

### A. 常用命令

```bash
# 启动后台服务
xspider admin serve

# 初始化数据库
xspider admin init-db

# 创建管理员
xspider admin create-admin --username admin --password secret

# KOL发现流程
xspider seed search --keywords "AI" --limit 50
xspider crawl --depth 2
xspider rank --find-hidden --top 100
xspider audit --industry "AI/ML"
xspider export --format csv --output results.csv
```

### B. 更新日志

| 版本 | 日期 | 更新内容 |
|-----|------|---------|
| 1.0.0 | 2024-01 | 初始版本：KOL发现功能 |
| 1.1.0 | 2024-02 | 新增：后台管理系统 |
| 1.2.0 | 2024-02 | 新增：网红监控系统 |
