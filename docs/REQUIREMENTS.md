# xspider 需求规格文档

> 本文档描述 xspider 系统的完整需求规格，用于指导开发和维护。

## 目录

1. [系统概述](#1-系统概述)
2. [核心功能：KOL发现](#2-核心功能kol发现)
3. [后台管理系统](#3-后台管理系统)
4. [网红监控系统](#4-网红监控系统)
5. [销售转化平台](#5-销售转化平台) *(NEW)*
6. [企业集成功能](#6-企业集成功能) *(NEW)*
7. [数据模型](#7-数据模型)
8. [API接口规范](#8-api接口规范)
9. [技术架构](#9-技术架构)

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

## 5. 销售转化平台

### 5.1 CRM看板系统

#### 5.1.1 销售漏斗阶段

| 阶段 | 值 | 说明 |
|-----|-----|------|
| DISCOVERED | discovered | 从评论中发现 |
| AI_QUALIFIED | ai_qualified | 通过AI审核 |
| TO_CONTACT | to_contact | 待联系，已生成破冰话术 |
| DM_SENT | dm_sent | 已发送私信 |
| REPLIED | replied | 已回复 |
| CONVERTED | converted | 转化成功 |
| NOT_INTERESTED | not_interested | 不感兴趣/无响应 |

#### 5.1.2 销售线索数据模型

```python
class SalesLead:
    id: int                       # 主键
    user_id: int                  # 所属用户ID
    twitter_user_id: str          # Twitter用户ID
    screen_name: str              # 用户名
    display_name: str             # 显示名称
    bio: str                      # 简介
    profile_image_url: str        # 头像
    followers_count: int          # 粉丝数

    # 意图分析
    intent_score: float           # 购买意图分数 (0-100)
    intent_label: IntentLabel     # high_intent | medium_intent | low_intent
    intent_signals: JSON          # 意图信号详情

    # 销售状态
    stage: LeadStage              # 销售漏斗阶段
    stage_updated_at: datetime    # 阶段更新时间
    dm_status: DMStatus           # DM可用性

    # AI破冰
    opener_generated: bool        # 是否已生成破冰话术
    opener_text: str              # 破冰话术内容
    opener_template: str          # 使用的模板类型

    # 来源追踪
    source_tweet_id: int          # 来源推文ID
    source_influencer: str        # 来源网红

    # 管理
    notes: str                    # 备注
    tags: JSON                    # 标签数组
    created_at: datetime
    updated_at: datetime
```

#### 5.1.3 功能需求

| 功能 | 接口 | 说明 |
|-----|------|------|
| 看板视图 | GET /api/crm/kanban | 按阶段分组的线索列表 |
| 看板统计 | GET /api/crm/kanban/stats | 各阶段数量和转化率 |
| 线索列表 | GET /api/crm/leads | 分页查询线索 |
| 搜索线索 | GET /api/crm/leads/search | 多条件搜索 |
| 更新阶段 | PUT /api/crm/leads/{id}/stage | 拖拽移动阶段 |
| 添加备注 | PUT /api/crm/leads/{id}/note | 添加跟进备注 |
| 更新标签 | PUT /api/crm/leads/{id}/tags | 打标签 |
| 活动历史 | GET /api/crm/leads/{id}/activities | 查看操作记录 |
| 批量转化 | POST /api/crm/convert-commenters/{tweet_id} | 评论者转线索 |

### 5.2 AI破冰文案生成

#### 5.2.1 功能描述

使用LLM根据用户画像生成个性化的DM破冰话术。

#### 5.2.2 模板类型

| 模板 | 场景 | 示例 |
|-----|------|------|
| professional | 专业商务 | 注意到您在{领域}的专业见解... |
| casual | 轻松友好 | 嘿！看到您关于{话题}的评论... |
| value_offer | 价值导向 | 我们帮助像您这样的{角色}解决{痛点}... |
| question | 问题引导 | 好奇您对{趋势}怎么看？ |

#### 5.2.3 接口规范

```python
# 生成破冰话术
POST /api/ai-openers/generate/{lead_id}
Request:
{
  "template_type": "professional",  # 可选
  "product_context": "AI数据分析工具",
  "custom_instructions": "强调ROI"
}
Response:
{
  "opener": "Hi [Name], 注意到您在数据分析领域的专业见解...",
  "template_used": "professional",
  "personalization_points": ["bio关键词", "最近互动"],
  "confidence_score": 0.85
}

# 批量生成
POST /api/ai-openers/generate-batch
Request:
{
  "lead_ids": [1, 2, 3],
  "template_type": "value_offer"
}
```

### 5.3 购买意图分析

#### 5.3.1 意图信号

| 信号类型 | 权重 | 示例模式 |
|---------|------|---------|
| 求推荐 | +25 | "有人推荐", "求推荐", "有什么好用的" |
| 价格咨询 | +20 | "多少钱", "价格", "怎么收费" |
| 痛点表达 | +15 | "太麻烦了", "效率太低", "有没有更好的" |
| 竞品比较 | +10 | "A和B哪个好", "有没有替代" |
| 使用竞品 | -10 | "我用的是X", "X挺好用" |

#### 5.3.2 分析流程

```
1. 正则模式匹配 (快速)
   - 匹配预定义的意图关键词
   - 快速判断明显的高/低意图

2. LLM深度分析 (可选)
   - 分析评论上下文
   - 理解隐含需求
   - 生成详细意图报告
```

#### 5.3.3 意图标签

| 标签 | 分数范围 | 说明 |
|-----|---------|------|
| HIGH_INTENT | 70-100 | 强烈购买信号 |
| MEDIUM_INTENT | 40-69 | 中等兴趣 |
| LOW_INTENT | 0-39 | 一般互动 |
| COMPETITOR_USER | N/A | 使用竞品 |

### 5.4 粉丝增长异常监测

#### 5.4.1 功能描述

监测网红粉丝数变化，检测异常增长（可能是刷粉）或异常下降（可能被封号）。

#### 5.4.2 数据模型

```python
class FollowerSnapshot:
    id: int
    influencer_id: int
    followers_count: int
    following_count: int
    tweet_count: int
    snapshot_at: datetime

class GrowthAnomaly:
    id: int
    influencer_id: int
    anomaly_type: str        # spike | drop | suspicious
    change_amount: int       # 变化量
    change_percent: float    # 变化百分比
    period_hours: int        # 时间窗口
    severity: str            # low | medium | high | critical
    detected_at: datetime
    is_resolved: bool
```

#### 5.4.3 异常检测规则

| 类型 | 条件 | 严重程度 |
|-----|------|---------|
| spike | 24h内增长>20% 且 >1000人 | high |
| spike | 24h内增长>50% 且 >500人 | critical |
| drop | 24h内下降>10% 且 >500人 | medium |
| suspicious | 增长率远超历史平均 | low-high |

### 5.5 竞品受众重合度分析

#### 5.5.1 功能描述

比较多个KOL的粉丝重合度，用于：
- 选择合作KOL时避免重复覆盖
- 发现竞品关注的核心用户群

#### 5.5.2 算法

```python
# Jaccard相似度
overlap_ratio = len(followers_A ∩ followers_B) / len(followers_A ∪ followers_B)

# 输出
{
  "influencer_a": "@user_a",
  "influencer_b": "@user_b",
  "overlap_count": 1234,
  "overlap_ratio": 0.15,  # 15%重合
  "unique_to_a": 5000,
  "unique_to_b": 6000,
  "sample_overlap_users": ["@common1", "@common2", ...]
}
```

### 5.6 网络拓扑可视化

#### 5.6.1 功能描述

生成D3.js兼容的社交网络图数据，支持：
- 搜索结果网络图
- 监控网红关系图
- 导出为Gephi/Cytoscape格式

#### 5.6.2 数据格式

```json
{
  "nodes": [
    {
      "id": "12345",
      "label": "@username",
      "size": 50,         // 基于PageRank
      "color": "#ff6600", // 基于相关性
      "x": 100,
      "y": 200
    }
  ],
  "edges": [
    {
      "source": "12345",
      "target": "67890",
      "weight": 1.0
    }
  ],
  "metadata": {
    "node_count": 100,
    "edge_count": 500,
    "density": 0.05
  }
}
```

---

## 6. 企业集成功能

### 6.1 Webhook集成

#### 6.1.1 事件类型

| 事件 | 值 | 触发条件 |
|-----|-----|---------|
| 高意图线索 | high_intent_lead | 意图分数>80 |
| 高互动评论 | high_engagement_comment | 评论点赞>10 |
| 新真实用户 | new_real_user | 真实性分数>70 |
| 异常增长 | suspicious_growth | 检测到粉丝异常 |
| DM可用 | dm_available | 用户开放DM |

#### 6.1.2 Webhook数据模型

```python
class WebhookConfig:
    id: int
    user_id: int
    name: str                  # 配置名称
    url: str                   # 回调URL
    event_types: list[str]     # 订阅的事件类型
    secret: str                # HMAC签名密钥
    headers: dict              # 自定义请求头
    is_active: bool
    last_triggered_at: datetime
    success_count: int
    failure_count: int

class WebhookLog:
    id: int
    webhook_id: int
    event_type: str
    payload: JSON
    response_status: int
    response_body: str
    success: bool
    error_message: str
    created_at: datetime
```

#### 6.1.3 请求签名

```python
# HMAC-SHA256签名
signature = hmac.new(
    secret.encode(),
    json.dumps(payload).encode(),
    hashlib.sha256
).hexdigest()

# 请求头
X-Webhook-Signature: sha256={signature}
X-Webhook-Event: high_intent_lead
X-Webhook-Timestamp: 1234567890
```

### 6.2 数据隐私与GDPR合规

#### 6.2.1 数据保留策略

```python
class RetentionPolicy:
    id: int
    user_id: int
    search_results_days: int     # 搜索结果保留天数
    commenter_data_days: int     # 评论者数据保留天数
    lead_data_days: int          # 线索数据保留天数
    analytics_days: int          # 分析数据保留天数
    webhook_logs_days: int       # Webhook日志保留天数
    auto_delete_enabled: bool    # 是否自动删除
```

#### 6.2.2 GDPR功能

| 功能 | 接口 | 说明 |
|-----|------|------|
| 数据导出 | GET /api/privacy/export | 导出用户所有数据 |
| 数据删除 | DELETE /api/privacy/delete-my-data | 删除用户所有数据 |
| 保留策略 | PUT /api/privacy/retention | 设置数据保留策略 |
| 数据统计 | GET /api/privacy/stats | 查看数据存储统计 |

### 6.3 积分套餐系统

#### 6.3.1 套餐配置

```python
class CreditPackage:
    id: int
    name: str                  # 套餐名称
    description: str           # 描述
    credits: int               # 基础积分
    bonus_credits: int         # 赠送积分
    price: Decimal             # 价格
    currency: str              # 货币 (USD/CNY)
    features: list[str]        # 特性列表
    is_popular: bool           # 是否热门
    is_active: bool
    sort_order: int
```

#### 6.3.2 默认套餐

| 套餐 | 积分 | 赠送 | 价格 | 特性 |
|-----|------|-----|------|------|
| Starter | 1000 | 0 | $9.99 | 基础功能 |
| Growth | 5000 | 500 | $39.99 | 优先支持 |
| Pro | 15000 | 3000 | $99.99 | API访问 |
| Enterprise | 50000 | 15000 | $299.99 | 专属客服 |

#### 6.3.3 购买记录

```python
class CreditPurchase:
    id: int
    user_id: int
    package_id: int
    package_name: str
    credits_purchased: int
    bonus_credits: int
    amount_paid: Decimal
    currency: str
    payment_method: str
    payment_id: str
    status: str               # pending | completed | refunded
    created_at: datetime
```

---

## 7. 数据模型

### 7.1 ER图

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

### 7.2 索引设计

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

## 8. API接口规范

### 8.1 通用规范

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

### 8.2 错误码

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

## 9. 技术架构

### 9.1 技术栈

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

### 9.2 目录结构

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

### 9.3 部署架构

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

### 9.4 配置项

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
| 2.0.0 | 2024-02 | 重大升级：销售转化平台 |
|       |        | - CRM看板系统（销售漏斗管理）|
|       |        | - AI破冰文案生成器 |
|       |        | - 购买意图分析 |
|       |        | - 粉丝增长异常监测 |
|       |        | - 竞品受众重合度分析 |
|       |        | - 网络拓扑可视化 |
|       |        | - Webhook集成（Slack/Zapier）|
|       |        | - GDPR数据隐私合规 |
|       |        | - 积分套餐系统 |
