# xspider

Twitter/X KOL Discovery & Sales Conversion Platform based on Social Network Analysis.

## Features

### Core Discovery
- **Seed Collection**: Bio keyword search + Twitter Lists scraping
- **Network Crawling**: BFS traversal of following relationships (2-3 depth)
- **Authority Ranking**: PageRank algorithm for influence calculation
- **Hidden Influencer Detection**: Find high-authority users with low follower counts
- **AI Content Audit**: LLM-powered industry relevance classification

### Admin Management System
- **Twitter Account Pool**: Manage multiple accounts with status monitoring
- **Proxy IP Pool**: Manage proxies with health checking
- **User Management**: Role-based access (admin/user) with credit system
- **Search Tasks**: Track and manage discovery tasks
- **Multi-Language Support (i18n)**: Chinese, English, Japanese with auto-detection

### Influencer Monitoring
- **Tweet Monitoring**: Track specific influencer tweets within time ranges
- **Commenter Scraping**: Collect tweet commenters/replies
- **Authenticity Analysis**: Label commenters (real_user, bot, suspicious, etc.)
- **DM Availability**: Check if users can receive direct messages
- **Data Export**: Export to CSV/JSON formats

### Sales Conversion Platform (NEW)
- **CRM Kanban System**: Sales funnel with stages (Discovered → AI Qualified → To Contact → DM Sent → Replied → Converted)
- **AI Opener Generator**: LLM-powered personalized DM icebreaker messages
- **Sentiment & Intent Analysis**: Purchase intent scoring with pattern matching + LLM fallback
- **Network Topology Visualization**: D3.js compatible social graph with PageRank-based node sizing
- **Growth Anomaly Detection**: Follower spike monitoring with suspicious activity alerts
- **Audience Overlap Analysis**: Jaccard index calculation for comparing KOL audiences

### Enterprise Integration
- **Webhook Integration**: HMAC-SHA256 signed payloads for Slack/Zapier/custom endpoints
- **GDPR Compliance**: Data retention policies, export, and deletion (right to be forgotten)
- **Credit Package System**: Starter/Growth/Pro/Enterprise tiers with bonus credits

## Installation

```bash
# Clone and install
git clone https://github.com/dreamhaha/xspider.git
cd xspider
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required:
- `TWITTER_TOKENS`: JSON array of Twitter auth tokens
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`: For AI audit

## Usage

### CLI Commands

```bash
# 1. Collect seeds by keywords
xspider seed search --keywords "AI,Web3,DeFi" --limit 50

# 2. Crawl following network
xspider crawl --depth 2 --concurrency 5

# 3. Compute PageRank
xspider rank --find-hidden --top 100

# 4. AI audit for industry relevance
xspider audit --industry "AI/ML" --model gpt-4

# 5. Export results
xspider export --format csv --output results.csv
```

### Admin Web Interface

```bash
# Initialize database and create admin user
xspider admin init-db
xspider admin create-admin --username admin --password your_password

# Start admin server
xspider admin serve --host 0.0.0.0 --port 8000

# Or run directly
python -m xspider.admin
```

Access the admin panel at `http://localhost:8000/admin/dashboard`

Default credentials (first run):
- Username: `admin`
- Password: `admin123`

## Multi-Language Support (i18n)

The admin interface supports automatic language detection based on browser settings:

| Language | Code | Status |
|----------|------|--------|
| English | `en` | Default |
| Chinese (Simplified) | `zh` | Supported |
| Japanese | `ja` | Supported |

**How it works:**
1. Browser sends `Accept-Language` header (e.g., `zh-CN,zh;q=0.9,en;q=0.8`)
2. i18n middleware extracts primary language
3. All API responses and UI elements display in detected language
4. Falls back to English if language not supported

**Testing language detection:**
```bash
# Test Chinese
curl -H "Accept-Language: zh-CN" http://localhost:8000/api/auth/login \
  -d '{"username":"x","password":"x"}' -H "Content-Type: application/json"
# Returns: {"detail": "用户名或密码错误"}

# Test Japanese
curl -H "Accept-Language: ja" http://localhost:8000/api/auth/login \
  -d '{"username":"x","password":"x"}' -H "Content-Type: application/json"
# Returns: {"detail": "ユーザー名またはパスワードが正しくありません"}
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Admin Web UI                             │
│              (FastAPI + Jinja2 + Bootstrap 5)                   │
├─────────────────────────────────────────────────────────────────┤
│ Dashboard │ Monitors │ CRM │ Analytics │ Webhooks │ Settings   │
└─────────────────────────────────────────────────────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                           CLI Layer                              │
│  (Typer: seed, crawl, rank, audit, export, admin)               │
└─────────────────────────────────────────────────────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│    Scraper    │      │     Graph     │      │      AI       │
│   - Seed      │      │   - PageRank  │      │   - Auditor   │
│   - Following │ ───▶ │   - Analysis  │ ───▶ │   - Intent    │
│   - Monitor   │      │   - Topology  │      │   - Opener    │
└───────────────┘      └───────────────┘      └───────────────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Data Layer                               │
│     SQLite + NetworkX (Users, Leads, Packages, Webhooks, etc.)  │
└─────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│   Webhooks    │      │    Privacy    │      │   Packages    │
│ - Slack       │      │ - GDPR Export │      │ - Credits     │
│ - Zapier      │      │ - Retention   │      │ - Purchases   │
│ - Custom      │      │ - Deletion    │      │ - Bonuses     │
└───────────────┘      └───────────────┘      └───────────────┘
```

## Sales Funnel Stages

| Stage | Description |
|-------|-------------|
| `discovered` | Initial discovery from commenter scraping |
| `ai_qualified` | Passed AI authenticity and intent analysis |
| `to_contact` | Ready for outreach, AI opener generated |
| `dm_sent` | DM has been sent |
| `replied` | Lead has replied to DM |
| `converted` | Successfully converted to customer |
| `not_interested` | Lead declined or unresponsive |

## Webhook Event Types

| Event | Trigger |
|-------|---------|
| `high_intent_lead` | Lead with intent score > 80 discovered |
| `high_engagement_comment` | Comment with >10 likes detected |
| `new_real_user` | Real user (authenticity > 70) identified |
| `suspicious_growth` | Follower growth anomaly detected |
| `dm_available` | User's DM becomes available |

## Intent Labels

| Label | Score Range | Description |
|-------|-------------|-------------|
| `high_intent` | 70-100 | Strong buying signals |
| `medium_intent` | 40-69 | Moderate interest |
| `low_intent` | 0-39 | General engagement |
| `competitor_user` | N/A | Uses competitor products |

## Admin System Features

### Twitter Account Management
- Add/remove Twitter accounts with auth tokens
- Monitor account status (active, rate_limited, banned, needs_verify)
- Automatic status detection
- Request count and error tracking

### Proxy Management
- Support HTTP/HTTPS/SOCKS5 proxies
- Health checking with response time
- Success rate tracking
- Batch import support

### User & Credit System
- Role-based access control (admin/user)
- Credit-based usage tracking
- Recharge and transaction history
- LLM usage tracking

### Influencer Monitoring

```python
# Workflow
1. Add influencer to monitor (by @username)
2. Fetch tweets within specified time range
3. Scrape commenters for each tweet
4. Analyze commenter authenticity
5. Check DM availability
6. Export qualified leads
```

#### Authenticity Labels
| Label | Description |
|-------|-------------|
| `real_user` | Genuine user with normal activity |
| `verified` | Twitter verified account |
| `influencer` | High follower count (>10K) |
| `suspicious` | Unusual patterns detected |
| `bot` | Bot-like behavior indicators |
| `new_account` | Account less than 30 days old |
| `low_activity` | Less than 10 tweets |
| `high_engagement` | High follower + activity |

#### DM Status
| Status | Description |
|--------|-------------|
| `open` | Anyone can send DM |
| `followers_only` | Only followers can DM |
| `closed` | DMs are disabled |
| `unknown` | Could not determine |

## API Endpoints

### Authentication
- `POST /api/auth/login` - User login
- `POST /api/auth/register` - User registration
- `GET /api/auth/me` - Get current user

### Dashboard
- `GET /api/dashboard/stats` - System statistics
- `GET /api/dashboard/monitoring-stats` - Monitoring statistics

### Monitoring
- `POST /api/monitors/influencers` - Add influencer
- `GET /api/monitors/influencers` - List influencers
- `POST /api/monitors/influencers/{id}/fetch-tweets` - Fetch tweets
- `POST /api/monitors/tweets/{id}/scrape-commenters` - Scrape commenters
- `POST /api/monitors/tweets/{id}/analyze-commenters` - Analyze authenticity
- `POST /api/monitors/tweets/{id}/check-dm` - Check DM status
- `POST /api/monitors/export-commenters` - Export data

### CRM & Sales Funnel
- `GET /api/crm/kanban` - Get kanban board with leads by stage
- `GET /api/crm/kanban/stats` - Kanban statistics
- `GET /api/crm/leads` - List leads with filters
- `GET /api/crm/leads/search` - Search leads
- `PUT /api/crm/leads/{id}/stage` - Update lead stage
- `PUT /api/crm/leads/{id}/note` - Add note to lead
- `PUT /api/crm/leads/{id}/tags` - Update lead tags
- `GET /api/crm/leads/{id}/activities` - Get lead activity history
- `POST /api/crm/convert-commenters/{tweet_id}` - Convert commenters to leads

### Analytics & AI
- `POST /api/analytics/intent/{user_id}` - Analyze purchase intent
- `GET /api/analytics/growth/{influencer_id}` - Get growth history
- `GET /api/analytics/growth/{influencer_id}/anomalies` - Detect growth anomalies
- `POST /api/analytics/audience-overlap` - Compare audience overlap between KOLs
- `POST /api/ai-openers/generate/{lead_id}` - Generate AI opener message
- `POST /api/ai-openers/generate-batch` - Batch generate openers
- `GET /api/ai-openers/templates` - List opener templates

### Network Topology
- `GET /api/topology/search/{search_id}` - Get search result topology (D3.js format)
- `GET /api/topology/monitored` - Get monitored influencer topology
- `GET /api/topology/export/{search_id}` - Export topology (json/gephi/cytoscape)

### Webhooks
- `POST /api/webhooks/` - Create webhook
- `GET /api/webhooks/` - List webhooks
- `PUT /api/webhooks/{id}` - Update webhook
- `DELETE /api/webhooks/{id}` - Delete webhook
- `POST /api/webhooks/{id}/test` - Test webhook
- `GET /api/webhooks/{id}/logs` - Get webhook logs
- `GET /api/webhooks/event-types` - List available event types

### Credit Packages
- `GET /api/packages/` - List available packages
- `GET /api/packages/{id}` - Get package details
- `POST /api/packages/{id}/purchase` - Purchase package
- `GET /api/packages/purchases/history` - Purchase history
- `POST /api/packages/admin/create` - Create package (admin)
- `POST /api/packages/admin/seed` - Seed default packages (admin)

### Privacy & GDPR
- `GET /api/privacy/retention` - Get retention policy
- `PUT /api/privacy/retention` - Set retention policy
- `GET /api/privacy/export` - Export user data (GDPR)
- `DELETE /api/privacy/delete-my-data` - Delete user data (GDPR)
- `GET /api/privacy/stats` - Data storage statistics
- `POST /api/privacy/admin/cleanup` - Cleanup expired data (admin)

## Algorithm: Hidden Influencer Detection

The core algorithm identifies "hidden gems" - users with high PageRank but low follower counts:

```python
hidden_score = pagerank_score / log(followers_count + 2)
```

These users are often:
- Core developers
- VC partners
- Insider information sources

## Algorithm: Authenticity Analysis

Heuristic scoring based on:
- Account age and activity level
- Follower/following ratio
- Profile completeness (bio, avatar)
- Username patterns (bot-like)
- Comment quality and engagement
- Optional LLM deep analysis

## Project Structure

```
src/xspider/
├── admin/                  # Admin management system
│   ├── app.py             # FastAPI application
│   ├── auth.py            # JWT authentication
│   ├── models.py          # Database models (50+ tables)
│   ├── schemas.py         # Pydantic schemas (100+ schemas)
│   ├── i18n/              # Internationalization
│   │   ├── middleware.py  # Accept-Language parsing
│   │   ├── translator.py  # Translation lookup
│   │   └── locales/       # Translation files (en, zh, ja)
│   ├── routes/            # API endpoints
│   │   ├── auth.py        # Authentication
│   │   ├── dashboard.py   # Dashboard stats
│   │   ├── monitors.py    # Influencer monitoring
│   │   ├── twitter_accounts.py
│   │   ├── proxies.py
│   │   ├── users.py
│   │   ├── searches.py
│   │   ├── crm.py         # CRM & sales funnel (NEW)
│   │   ├── analytics.py   # Intent & growth analysis (NEW)
│   │   ├── ai_openers.py  # AI opener generator (NEW)
│   │   ├── webhooks.py    # Webhook integration (NEW)
│   │   ├── packages.py    # Credit packages (NEW)
│   │   ├── privacy.py     # GDPR compliance (NEW)
│   │   └── topology.py    # Network visualization (NEW)
│   ├── services/          # Business logic
│   │   ├── influencer_monitor.py
│   │   ├── commenter_scraper.py
│   │   ├── authenticity_analyzer.py
│   │   ├── dm_checker.py
│   │   ├── crm_service.py         # CRM operations (NEW)
│   │   ├── intent_analyzer.py     # Purchase intent (NEW)
│   │   ├── growth_monitor.py      # Growth anomalies (NEW)
│   │   ├── opener_generator.py    # AI DM openers (NEW)
│   │   ├── audience_overlap.py    # KOL comparison (NEW)
│   │   ├── webhook_service.py     # Webhook delivery (NEW)
│   │   ├── package_service.py     # Credit packages (NEW)
│   │   ├── privacy_service.py     # GDPR operations (NEW)
│   │   └── topology_service.py    # Graph visualization (NEW)
│   ├── templates/         # Jinja2 HTML templates
│   └── static/            # CSS/JS assets
├── cli/                   # CLI commands
├── core/                  # Core utilities
├── twitter/               # Twitter API client
├── scraper/               # Data collection
├── graph/                 # Network analysis
├── ai/                    # AI/LLM integration
└── storage/               # Database layer
```

## Dependencies

Core:
- `typer` - CLI framework
- `httpx` - Async HTTP client
- `sqlalchemy` - Database ORM
- `networkx` - Graph analysis

Admin:
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `jinja2` - Template engine
- `python-jose` - JWT tokens
- `bcrypt` - Password hashing

## License

MIT
