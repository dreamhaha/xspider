# xspider

Twitter/X KOL Discovery System based on Social Network Analysis.

## Features

- **Seed Collection**: Bio keyword search + Twitter Lists scraping
- **Network Crawling**: BFS traversal of following relationships (2-3 depth)
- **Authority Ranking**: PageRank algorithm for influence calculation
- **Hidden Influencer Detection**: Find high-authority users with low follower counts
- **AI Content Audit**: LLM-powered industry relevance classification

## Installation

```bash
# Clone and install
git clone https://github.com/yourname/xspider.git
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

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                           CLI Layer                              │
│  (Typer: seed, crawl, rank, audit, export)                      │
└─────────────────────────────────────────────────────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌───────────────┐      ┌───────────────┐      ┌───────────────┐
│    Scraper    │      │     Graph     │      │      AI       │
│   - Seed      │      │   - PageRank  │      │   - Auditor   │
│   - Following │ ───▶ │   - Analysis  │ ───▶ │   - Labels    │
└───────────────┘      └───────────────┘      └───────────────┘
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SQLite + NetworkX Storage                      │
└─────────────────────────────────────────────────────────────────┘
```

## Algorithm: Hidden Influencer Detection

The core algorithm identifies "hidden gems" - users with high PageRank but low follower counts:

```python
hidden_score = pagerank_score / log(followers_count + 2)
```

These users are often:
- Core developers
- VC partners
- Insider information sources

## License

MIT
