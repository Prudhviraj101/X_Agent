"""
main.py â€” Entry point for the X/Twitter AI & Tech Autonomous Agent.

Usage:
    python main.py

Environment:
    Copy .env.example to .env and fill in your credentials.
    See README.md for full configuration reference.
"""
from __future__ import annotations

import logging
import signal
import sys

# â”€â”€ Logging setup (before any imports that log) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("x-agent")


def _check_dependencies() -> bool:
    """Warn about any missing optional dependencies."""
    missing = []
    try:
        import dotenv  # noqa: F401
    except ImportError:
        missing.append("python-dotenv")
    try:
        import bs4  # noqa: F401
    except ImportError:
        missing.append("beautifulsoup4")
    try:
        import httpx  # noqa: F401
    except ImportError:
        missing.append("httpx")
    try:
        import requests_oauthlib  # noqa: F401
    except ImportError:
        missing.append("requests-oauthlib")

    if missing:
        logger.warning("Missing optional packages: %s", ", ".join(missing))
        logger.warning("Install with: pip install %s", " ".join(missing))
    return True


def main() -> None:
    _check_dependencies()

    # Lazy imports after dependency check
    from config import load_config
    from deduplicator import Deduplicator
    import pipeline as pipe
    from scheduler import Scheduler

    # â”€â”€ Load config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    cfg = load_config()

    logger.info("=" * 60)
    logger.info("  X/Twitter AI & Tech Autonomous Agent")
    logger.info("=" * 60)
    logger.info("  LLM provider : %s", cfg.model_provider)
    logger.info("  LLM ready    : %s", cfg.has_llm())
    logger.info("  Post to X    : %s", cfg.posting_enabled())
    logger.info("  Interval     : %dh", cfg.scrape_interval_hours)
    logger.info("  Max posts/run: %d", cfg.max_posts_per_run)
    logger.info("  Subreddits   : %s", ", ".join(cfg.reddit_subreddits))
    logger.info("=" * 60)

    if not cfg.has_llm():
        logger.warning(
            "No LLM API key configured. Tweets will use raw titles as fallback. "
            "Set OPENAI_API_KEY or GEMINI_API_KEY in your .env file."
        )
    if not cfg.posting_enabled():
        logger.info(
            "Draft mode active (POST_TO_X=false or credentials missing). "
            "Tweets will be saved to: %s", cfg.drafts_dir
        )

    # â”€â”€ Deduplicator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    dedup = Deduplicator(cfg.dedup_store_path, ttl_hours=cfg.dedup_ttl_hours)
    logger.info("[main] Dedup store: %s seen URLs loaded.", dedup.stats()["stored_urls"])

    # â”€â”€ Queue manager & HITL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    import draft_queue as queue
    queue.start(cfg)

    # â”€â”€ Pipeline job â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def job() -> None:
        pipe.run_once(cfg, dedup)

    # â”€â”€ Scheduler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    interval_secs = cfg.scrape_interval_hours * 3600
    sched = Scheduler(job=job, interval_seconds=interval_secs)

    # Graceful shutdown on Ctrl-C / SIGTERM
    def _shutdown(signum, frame) -> None:
        logger.info("[main] Shutdown signal received (%s). Stopping ...", signum)
        sched.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    sched.start()

    try:
        sched.wait()
    except KeyboardInterrupt:
        sched.stop()

    logger.info("[main] Agent stopped. Goodbye.")


if __name__ == "__main__":
    main()
