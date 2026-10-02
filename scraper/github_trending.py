"""
scraper/github_trending.py — Scrapes github.com/trending for AI/ML repos.

Uses curl_cffi with Chrome TLS fingerprint impersonation (Scrapling's HTTP
engine) to avoid bot detection, falling back to plain httpx. HTML is parsed
with BeautifulSoup4 (html.parser — no lxml needed).
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from scraper import ScrapedItem

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

_TRENDING_LANGS = [
    "",                     # Any language
    "python",
    "jupyter-notebook",
]

_AI_KEYWORDS = {
    "ai", "ml", "llm", "gpt", "nlp", "machine learning", "deep learning",
    "neural", "transformer", "diffusion", "stable diffusion", "rlhf",
    "fine-tun", "rag", "retrieval", "embedding", "vector", "language model",
    "computer vision", "object detection", "classification", "inference",
    "pytorch", "tensorflow", "jax", "huggingface", "model", "dataset",
    "benchmark", "agent", "chatbot", "assistant",
}


def _is_ai_related(name: str, desc: str) -> bool:
    combined = (name + " " + desc).lower()
    return any(kw in combined for kw in _AI_KEYWORDS)


def _parse_trending_page(html: str) -> list[dict]:
    """Parse the GitHub trending page HTML and return raw repo dicts."""
    soup = BeautifulSoup(html, "html.parser")  # stdlib parser; no lxml needed
    articles = soup.select("article.Box-row")
    repos = []
    for article in articles:
        h2 = article.select_one("h2.h3 a")
        if not h2:
            continue
        href = h2.get("href", "").strip("/")
        url = f"https://github.com/{href}"
        p = article.select_one("p")
        description = p.get_text(strip=True) if p else ""
        star_el = article.select_one("a[href$='/stargazers']")
        stars_text = star_el.get_text(strip=True).replace(",", "") if star_el else "0"
        try:
            stars = int(stars_text)
        except ValueError:
            stars = 0
        lang_el = article.select_one("span[itemprop='programmingLanguage']")
        language = lang_el.get_text(strip=True) if lang_el else ""
        gained_el = article.select_one("span.d-inline-block.float-sm-right")
        gained_text = gained_el.get_text(strip=True) if gained_el else ""
        repos.append({
            "name": href,
            "url": url,
            "description": description,
            "stars": stars,
            "language": language,
            "gained": gained_text,
        })
    return repos


def _fetch_page(url: str, params: dict, timeout: int, user_agent: str) -> str | None:
    """
    Fetch using curl_cffi Chrome impersonation first (Scrapling's HTTP engine),
    falling back to plain httpx. Returns HTML text or None.
    """
    # Primary: curl_cffi with Chrome TLS fingerprint — bypasses bot detection
    try:
        from curl_cffi import requests as curl_req
        resp = curl_req.get(url, params=params, impersonate="chrome120", timeout=timeout)
        if resp.status_code == 200:
            return resp.text
        logger.debug("[github] curl_cffi HTTP %d", resp.status_code)
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("[github] curl_cffi error: %s", exc)

    # Fallback: plain httpx
    try:
        import httpx
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
        }
        resp = httpx.get(url, params=params, headers=headers,
                         timeout=timeout, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code == 429:
            logger.warning("[github] Rate-limited")
    except Exception as exc:
        logger.warning("[github] httpx error: %s", exc)

    return None


def scrape(cfg: "Config") -> list[ScrapedItem]:
    """Return ScrapedItems from GitHub Trending (AI/ML focus)."""
    items: list[ScrapedItem] = []
    seen_urls: set[str] = set()

    for lang in _TRENDING_LANGS:
        params = {"since": "daily"}
        if lang:
            params["l"] = lang
        html = _fetch_page("https://github.com/trending", params,
                           cfg.http_timeout, cfg.user_agent)
        if html is None:
            continue
        repos = _parse_trending_page(html)
        if not repos:
            logger.warning("[github] No repos parsed (lang=%r). Page structure may have changed.", lang)
            continue
        for r in repos:
            if r["url"] in seen_urls:
                continue
            if not _is_ai_related(r["name"], r["description"]):
                continue
            seen_urls.add(r["url"])
            summary = r["description"]
            if r["gained"]:
                summary += f" ({r['gained']})"
            items.append(ScrapedItem(
                title=r["name"],
                url=r["url"],
                source="github",
                summary=summary[:400],
                score=r["stars"],
                tags=[r["language"]] if r["language"] else [],
                fetched_at=time.time(),
            ))

    logger.info("[github] Fetched %d AI/ML trending repos.", len(items))
    return items
