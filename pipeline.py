"""
pipeline.py â€” Orchestrates one full run of the X agent:
  scrape â†’ deduplicate â†’ score/rank â†’ draft â†’ post â†’ log

Scrapers run concurrently via ThreadPoolExecutor.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

import deduplicator as dedup_mod
import drafter
import draft_queue
import poster
from scraper import ScrapedItem
from scraper import github_trending, hackernews, rss_feeds

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)


# â”€â”€ Scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_SOURCE_WEIGHTS = {
    "reddit":  1.2,
    "github":  1.5,   # Trending repos = tools people are actually using
    "hn":      1.3,
    "rss":     1.0,
    "gnews":   0.9,
    "twitter": 1.4,   # High-engagement tweets score well
}

# Guaranteed slots per source in the drafted batch (repos/tools always get in).
# ponytail: static quotas; fine for 3-5 posts/hour, could become dynamic
# (weight by source volume) if the mix ever looks wrong.
_SOURCE_QUOTA = {
    "github": 1,   # at least 1 GitHub repo when available
    "reddit": 1,   # at least 1 community-hot topic
    "hn":     1,   # at least 1 HN story
}


def _score_item(item: ScrapedItem) -> float:
    """Higher = more tweet-worthy.

    Trending = high engagement signal * source credibility weight.
    Items with a real engagement signal (stars, upvotes, points, likes)
    outrank indistinguishable RSS/gnews filler.
    """
    weight = _SOURCE_WEIGHTS.get(item.source, 1.0)
    # Convert score to log-ish scale: 1 star and 10k stars shouldn't be linear,
    # but both must outrank 0-signal items.
    sig = (item.score + 1) ** 0.5
    return sig * weight + (0.5 if len(item.title) > 40 else 0)


def _select_trending(new_items: list[ScrapedItem], limit: int) -> list[ScrapedItem]:
    """Pick the top-N most trending, guaranteeing repos/tools-source slots.

    Reserved sources (github/reddit/hn) get their best item each, then the
    remaining slots go to the globally highest-scored leftovers. This keeps a
    flood of RSS/gnews filler from crowding out actual trending repos & tools.
    """
    selected: list[ScrapedItem] = []
    used_urls: set[str] = set()

    # Pass 1: best item per reserved source (trending tools/repos always in)
    for source, quota in _SOURCE_QUOTA.items():
        pool = [i for i in new_items if i.source == source and i.url not in used_urls]
        for item in sorted(pool, key=_score_item, reverse=True)[: quota]:
            selected.append(item)
            used_urls.add(item.url)

    # Pass 2: fill remaining slots globally by blended trending score
    remaining = [i for i in new_items if i.url not in used_urls]
    for item in sorted(remaining, key=_score_item, reverse=True):
        if len(selected) >= limit:
            break
        selected.append(item)
        used_urls.add(item.url)

    return selected


# â”€â”€ Main pipeline â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_once(cfg: "Config", dedup: "dedup_mod.Deduplicator") -> dict:
    """
    Execute one full pipeline cycle and return a structured run report.
    """
    run_start = time.time()
    report: dict = {
        "run_at": run_start,
        "scrape_counts": {},
        "new_items": 0,
        "selected": [],
        "drafts": [],
        "outcomes": [],
        "posted_count": 0,
        "error": None,
    }

    # â”€â”€ 1. Scrape all sources concurrently â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    logger.info("=" * 60)
    logger.info("[pipeline] Starting run at %s", time.strftime("%Y-%m-%d %H:%M:%S"))

    scraper_fns = {
        "reddit":  lambda: reddit.scrape(cfg),
        "github":  lambda: github_trending.scrape(cfg),
        "hn":      lambda: hackernews.scrape(cfg, lookback_hours=max(cfg.scrape_interval_hours * 2, 6)),
        "rss":     lambda: rss_feeds.scrape(cfg),
        "twitter": lambda: twitter.scrape(cfg),
    }

    all_items: list[ScrapedItem] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        future_map = {pool.submit(fn): name for name, fn in scraper_fns.items()}
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                items = future.result()
                report["scrape_counts"][name] = len(items)
                all_items.extend(items)
                logger.info("[pipeline] %s: %d items", name, len(items))
            except Exception as exc:
                logger.error("[pipeline] Scraper %r failed: %s", name, exc)
                report["scrape_counts"][name] = 0

    total_scraped = len(all_items)
    logger.info("[pipeline] Total scraped: %d", total_scraped)

    # â”€â”€ 2. Deduplicate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    new_items: list[ScrapedItem] = []
    for item in all_items:
        if not item.url or not item.title:
            continue
        if not dedup.is_seen(item.url, item.title):
            new_items.append(item)

    report["new_items"] = len(new_items)
    logger.info("[pipeline] New (not seen before): %d", len(new_items))

    if not new_items:
        logger.info("[pipeline] Nothing new this cycle â€” skipping drafting.")
        _write_log(cfg, report)
        return report

    # â”€â”€ 3. Score and select top trending items â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    selected = _select_trending(new_items, cfg.max_posts_per_run)
    report["selected"] = [i.to_dict() for i in selected]
    logger.info("[pipeline] Selected %d items for drafting.", len(selected))

    # â”€â”€ 4. Draft via LLM â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    draft_results = drafter.draft(cfg, selected)
    report["drafts"] = [
        {"tweet": d["tweet"], "char_count": len(d["tweet"]), "ok": d["ok"]}
        for d in draft_results
    ]

    # â”€â”€ 5. Queue for scheduling & HITL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    for d in draft_results:
        if d.get("ok"):
            draft_queue.enqueue(cfg, d)

    report["posted_count"] = 0  # posted asynchronously by queue worker
    report["outcomes"] = [{"status": "queued"}]

    # â”€â”€ 6. Mark all selected as seen â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    dedup.mark_seen_bulk([{"url": i.url, "title": i.title} for i in selected])
    logger.info("[pipeline] Marked %d URLs as seen.", len(selected))

    # â”€â”€ 7. Log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    report["duration_s"] = round(time.time() - run_start, 2)
    _write_log(cfg, report)

    logger.info(
        "[pipeline] Run complete in %.1fs | scraped=%d new=%d selected=%d posted=%d",
        report["duration_s"], total_scraped, report["new_items"],
        len(selected), report["posted_count"],
    )
    return report


def _write_log(cfg: "Config", report: dict) -> None:
    """Append the run report to a JSONL log file."""
    try:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = cfg.logs_dir / time.strftime("%Y-%m-%d.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        logger.error("[pipeline] Failed to write log: %s", exc)


