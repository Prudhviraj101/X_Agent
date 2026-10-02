# X/Twitter AI & Tech Autonomous Agent

An autonomous agent that scrapes AI and Tech news and trending GitHub repos every hour, drafts engaging X/Twitter posts using an LLM, and publishes them automatically after human-in-the-loop (HITL) approval.

---

## Features

- **Multi-source scraping** every hour:
  - GitHub Trending (AI/ML repos, Python, Jupyter Notebook)
  - Hacker News top AI/ML stories (via Algolia Search API)
  - RSS feeds: ArXiv AI & ML, MIT Tech Review, TechCrunch AI, VentureBeat AI, DeepLearning.AI Blog
- **Smart deduplication** — remembers seen URLs & similar titles for 48 hours
- **SQLite queue & HITL dashboard** — review and approve drafts in a local web interface (`queue.db` on port 8080 by default) before posting
- **Safety filter** — uses LLMs to classify each draft for safety before HITL approval
- **Scheduled posting** — posts approved drafts at configured peak hours
- **LLM-drafted tweets** — configurable to use OpenAI, Google Gemini, NVIDIA (Llama 3), or a hybrid mode (researcher + writer)
- **X/Twitter API v2** posting via OAuth 1.0a
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
- `NVIDIA_API_KEY` + `MODEL_PROVIDER=nvidia`
- `MODEL_PROVIDER=hybrid` (uses `HYBRID_RESEARCHER_MODEL` and `HYBRID_WRITER_MODEL`)

To actually post to X, also fill in:
- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`
- Set `POST_TO_X=true`

### 3. Run

```bash
python main.py
```

The agent starts the background queue/dashboard, runs an immediate first scrape cycle, then repeats every hour (configurable via `SCRAPE_INTERVAL_HOURS`). The HITL dashboard is available at `http://localhost:8080`.

Stop it any time with **Ctrl-C** — the current run finishes cleanly.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `MODEL_PROVIDER` | `openai` | `openai`, `gemini`, `nvidia`, or `hybrid` |
| `OPENAI_API_KEY` | — | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model to use for drafting |
| `GEMINI_API_KEY` | — | Your Google Gemini API key |
| `GEMINI_MODEL` | `gemini-3.5-flash` | Gemini model name |
| `NVIDIA_API_KEY` | — | Your NVIDIA API key |
| `NVIDIA_MODEL` | `meta/llama3-70b-instruct` | NVIDIA model name |
| `HYBRID_RESEARCHER_MODEL`| `gemini-3.5-flash` | Researcher model for hybrid mode |
| `HYBRID_WRITER_MODEL` | `gpt-4o-mini` | Writer model for hybrid mode |
| `X_API_KEY` | — | Twitter consumer key |
| `X_API_SECRET` | — | Twitter consumer secret |
| `X_ACCESS_TOKEN` | — | Twitter access token |
| `X_ACCESS_SECRET` | — | Twitter access token secret |
| `POST_TO_X` | `false` | `true` to post, `false` to keep in queue |
| `SCRAPE_INTERVAL_HOURS` | `1` | Run cycle frequency in hours |
| `MAX_POSTS_PER_RUN` | `3` | Max tweets per cycle |
| `DEDUP_TTL_HOURS` | `48` | Hours before a URL can be re-used |
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
├── draft_queue.py         # SQLite queue, Safety filter & HITL Dashboard
├── scraper/
│   ├── github_trending.py # GitHub Trending page
│   ├── hackernews.py      # HN Algolia Search API
│   └── rss_feeds.py       # RSS/Atom feeds
├── logs/                  # Per-run JSONL logs (auto-created)
├── vendor/                # Vendor dependencies (e.g. scrapling)
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

- GitHub Trending HTML is parsed carefully; structure occasionally changes — the scraper logs a warning if parsing fails.
- All HTTP requests time out after `HTTP_TIMEOUT` seconds; failures are logged and skipped without crashing the scheduler.
