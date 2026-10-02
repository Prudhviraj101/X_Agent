# X/Twitter AI & Tech Autonomous Agent

An autonomous agent that scrapes AI and Tech news, trending GitHub repos, and community discussions every hour, drafts engaging X/Twitter posts using an LLM, and optionally publishes them automatically.

---

## Features

- **Multi-source scraping** every hour:
  - Reddit (`r/MachineLearning`, `r/artificial`, `r/LocalLLaMA`, `r/singularity`, `r/AItools`, `r/ChatGPT`) — no API key required
  - GitHub Trending (AI/ML repos, Python, Jupyter Notebook)
  - Hacker News top AI/ML stories (via Algolia Search API — no key required)
  - RSS feeds: ArXiv AI & ML, MIT Tech Review, TechCrunch AI, VentureBeat AI, DeepLearning.AI Blog
  - Google News RSS for AI/Tech queries
- **Smart deduplication** — remembers seen URLs & similar titles for 48 hours
- **LLM-drafted tweets** — configurable OpenAI or Google Gemini
- **X/Twitter API v2** posting via OAuth 1.0a
- **Draft-mode fallback** — saves posts to `drafts/` when X credentials are absent
- **Structured logs** per run in `logs/`
- **Graceful shutdown** on Ctrl-C

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your preferred text editor
```

Fill in at minimum one of:
- `OPENAI_API_KEY` + `MODEL_PROVIDER=openai`
- `GEMINI_API_KEY` + `MODEL_PROVIDER=gemini`

To actually post to X, also fill in:
- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`
- Set `POST_TO_X=true`

### 3. Run

```bash
python main.py
```

The agent runs an immediate first cycle, then repeats every hour (configurable via `SCRAPE_INTERVAL_HOURS`).

Stop it any time with **Ctrl-C** — the current run finishes cleanly.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `MODEL_PROVIDER` | `openai` | `openai` or `gemini` |
| `OPENAI_API_KEY` | — | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model to use for drafting |
| `GEMINI_API_KEY` | — | Your Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name |
| `X_API_KEY` | — | Twitter consumer key |
| `X_API_SECRET` | — | Twitter consumer secret |
| `X_ACCESS_TOKEN` | — | Twitter access token |
| `X_ACCESS_SECRET` | — | Twitter access token secret |
| `POST_TO_X` | `false` | `true` to post, `false` to save drafts |
| `SCRAPE_INTERVAL_HOURS` | `1` | Run cycle frequency in hours |
| `MAX_POSTS_PER_RUN` | `3` | Max tweets per cycle |
| `DEDUP_TTL_HOURS` | `48` | Hours before a URL can be re-used |
| `REDDIT_SUBREDDITS` | see `.env.example` | Comma-separated subreddits |
| `HTTP_TIMEOUT` | `15` | Request timeout in seconds |
| `USER_AGENT` | `XAgentBot/1.0` | HTTP user-agent string |

---

## Project Structure

```
X agent/
├── main.py                # Entry point
├── config.py              # Config loader
├── scheduler.py           # Hourly scheduler
├── pipeline.py            # Run orchestrator
├── deduplicator.py        # URL deduplication store
├── drafter.py             # LLM tweet generator
├── poster.py              # X API v2 poster
├── scraper/
│   ├── reddit.py          # Reddit public JSON API
│   ├── github_trending.py # GitHub Trending page
│   ├── hackernews.py      # HN Algolia Search API
│   ├── rss_feeds.py       # RSS/Atom feeds
│   └── google_news.py     # Google News RSS
├── logs/                  # Per-run JSONL logs (auto-created)
├── drafts/                # Draft queue when POST_TO_X=false (auto-created)
├── .env.example           # Config template
└── requirements.txt       # Python dependencies
```

---

## X/Twitter API Requirements

- You need a **Developer Account** at [developer.twitter.com](https://developer.x.com)
- **Basic tier** ($100/month) allows 100 posts/month; **Free tier** has write limits
- Generate keys under **Project → App → Keys and Tokens**
- The agent uses **OAuth 1.0a User Context** for posting (the only allowed method for `POST /2/tweets`)

---

## Notes

- Reddit's public JSON API (`reddit.com/r/sub/hot.json`) works without credentials; a unique user-agent is sent automatically.
- GitHub Trending HTML is parsed with BeautifulSoup4; structure occasionally changes — the scraper logs a warning if parsing fails.
- All HTTP requests time out after `HTTP_TIMEOUT` seconds; failures are logged and skipped without crashing the scheduler.
