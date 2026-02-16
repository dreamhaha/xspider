# xspider

Twitter/X KOL Discovery System based on Social Network Analysis.

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

### Influencer Monitoring
- **Tweet Monitoring**: Track specific influencer tweets within time ranges
- **Commenter Scraping**: Collect tweet commenters/replies
- **Authenticity Analysis**: Label commenters (real_user, bot, suspicious, etc.)
- **DM Availability**: Check if users can receive direct messages
- **Data Export**: Export to CSV/JSON formats

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

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Admin Web UI                             │
│              (FastAPI + Jinja2 + Bootstrap 5)                   │
├─────────────────────────────────────────────────────────────────┤
│   Dashboard │ Accounts │ Proxies │ Users │ Monitors │ Search   │
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
│   - Following │ ───▶ │   - Analysis  │ ───▶ │   - Labels    │
│   - Monitor   │      │   - Hidden    │      │   - Authenticity
└───────────────┘      └───────────────┘      └───────────────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SQLite + NetworkX Storage                      │
│     (Users, Accounts, Proxies, Searches, Monitors, Credits)     │
└─────────────────────────────────────────────────────────────────┘
```

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
│   ├── models.py          # Database models
│   ├── schemas.py         # Pydantic schemas
│   ├── routes/            # API endpoints
│   │   ├── auth.py
│   │   ├── dashboard.py
│   │   ├── monitors.py
│   │   ├── twitter_accounts.py
│   │   ├── proxies.py
│   │   ├── users.py
│   │   └── searches.py
│   ├── services/          # Business logic
│   │   ├── influencer_monitor.py
│   │   ├── commenter_scraper.py
│   │   ├── authenticity_analyzer.py
│   │   ├── dm_checker.py
│   │   └── ...
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
