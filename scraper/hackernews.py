"""
scraper/hackernews.py â€” Fetches AI/ML stories from Hacker News via the
Algolia HN Search API (https://hn.algolia.com/api). No API key required.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import httpx

from scraper import ScrapedItem

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

_HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"

_QUERIES = [
    "Show HN AI",
    "Show HN LLM",
    "AI agent github",
    "open source LLM",
]

_MIN_POINTS = 5   # Skip very low-engagement stories


def _fetch_query(query: str, since_hours: int, timeout: int,
                 user_agent: str) -> list[dict]:
    cutoff = int(time.time()) - since_hours * 3600
    params = {
        "query": query,
        "tags": "story",
        # Note: HN Algolia uses 'points' as the field name; include created_at filter
        # but separate the two constraints (some older API versions don't support combined)
        "numericFilters": f"created_at_i>{cutoff}",
        "hitsPerPage": "25",
    }
    headers = {"User-Agent": user_agent}
    try:
        resp = httpx.get(_HN_SEARCH_URL, params=params,
                         headers=headers, timeout=timeout)
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
        # Client-side filter for minimum points
        return [h for h in hits if (h.get("points") or 0) >= _MIN_POINTS]
    except httpx.TimeoutException:
        logger.warning("[hn] Timeout for query %r", query)
    except Exception as exc:
        logger.warning("[hn] Error for query %r: %s", query, exc)
    return []


def scrape(cfg: "Config", lookback_hours: int = 24) -> list[ScrapedItem]:
    """Return ScrapedItems from Hacker News for AI/ML queries."""
    items: list[ScrapedItem] = []
    seen_ids: set[str] = set()

    for query in _QUERIES:
        hits = _fetch_query(query, lookback_hours, cfg.http_timeout, cfg.user_agent)
        for hit in hits:
            obj_id = hit.get("objectID", "")
            if obj_id in seen_ids:
                continue
            seen_ids.add(obj_id)

            title = hit.get("title", "").strip()
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={obj_id}"
            points = hit.get("points", 0) or 0
            num_comments = hit.get("num_comments", 0) or 0
            author = hit.get("author", "")

            if not title:
                continue

            items.append(ScrapedItem(
                title=title,
                url=url,
                source="hn",
                summary=f"{points} points, {num_comments} comments on HN",
                score=points,
                author=author,
                tags=["HackerNews"],
                fetched_at=time.time(),
            ))

    logger.info("[hn] Fetched %d stories.", len(items))
    return items

