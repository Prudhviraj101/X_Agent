"""
scraper/rss_feeds.py â€” Fetches and parses AI/Tech RSS/Atom feeds.

Uses stdlib xml.etree.ElementTree for parsing; httpx for HTTP with
curl_cffi as a fallback for sites that block plain urllib.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

import httpx

from scraper import ScrapedItem

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

# â”€â”€ Feed registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FEEDS = [
    {"name": "ArXiv AI",        "url": "http://export.arxiv.org/rss/cs.AI"},
    {"name": "ArXiv ML",        "url": "http://export.arxiv.org/rss/cs.LG"},
    {"name": "Hugging Face",    "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "Product Hunt AI", "url": "https://www.producthunt.com/feed"},
]

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
}


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _strip_html(text: str) -> str:
    """Best-effort HTML tag removal using BeautifulSoup without lxml."""
    if "<" not in text:
        return text.strip()
    try:
        from bs4 import BeautifulSoup as _BS
        return _BS(text, "html.parser").get_text(" ", strip=True)
    except Exception:
        # Fallback: naive tag stripper
        import re
        return re.sub(r"<[^>]+>", " ", text).strip()


def _parse_rss(xml_text: str, feed_name: str) -> list[dict]:
    """Parse RSS 2.0 or RDF items."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("[rss] Parse error for %r: %s", feed_name, exc)
        return []

    # Detect namespace
    ns = root.tag.split("}")[0].lstrip("{") if "}" in root.tag else ""

    # Try RSS 2.0
    items = root.findall(".//item")
    if items:
        results = []
        for item in items:
            title = _text(item.find("title"))
            link = _text(item.find("link"))
            desc_el = item.find("description") or item.find("{%s}description" % ns if ns else "description")
            description = _text(desc_el)
            # Strip HTML tags from description using a simple regex-free approach
            description = _strip_html(description)
            results.append({"title": title, "url": link, "summary": description[:400]})
        return results

    # Try Atom
    atom_ns = "http://www.w3.org/2005/Atom"
    entries = root.findall(f"{{{atom_ns}}}entry")
    if not entries:
        entries = root.findall("entry")
    results = []
    for entry in entries:
        title_el = entry.find(f"{{{atom_ns}}}title") or entry.find("title")
        title = _text(title_el)
        # Atom link: <link href="..."/>
        link_el = entry.find(f"{{{atom_ns}}}link") or entry.find("link")
        link = ""
        if link_el is not None:
            link = link_el.get("href", "") or _text(link_el)
        summary_el = (entry.find(f"{{{atom_ns}}}summary") or
                      entry.find(f"{{{atom_ns}}}content") or
                      entry.find("summary"))
        summary = _strip_html(_text(summary_el))[:400]
        results.append({"title": title, "url": link, "summary": summary})
    return results


def _fetch_feed(url: str, timeout: int) -> str | None:
    """Fetch feed XML. Falls back to curl_cffi on failure."""
    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=timeout,
                         follow_redirects=True)
        if resp.status_code == 200:
            return resp.text
        logger.warning("[rss] HTTP %d for %s", resp.status_code, url)
    except Exception as exc:
        logger.debug("[rss] httpx failed for %s: %s; trying curl_cffi", url, exc)

    # curl_cffi fallback
    try:
        from curl_cffi import requests as curl_req
        resp2 = curl_req.get(url, impersonate="chrome120", timeout=timeout)
        if resp2.status_code == 200:
            return resp2.text
        logger.warning("[rss] curl_cffi HTTP %d for %s", resp2.status_code, url)
    except Exception as exc2:
        logger.warning("[rss] Both fetchers failed for %s: %s", url, exc2)
    return None


def scrape(cfg: "Config") -> list[ScrapedItem]:
    """Return ScrapedItems from all configured RSS feeds."""
    items: list[ScrapedItem] = []
    seen_urls: set[str] = set()

    for feed in FEEDS:
        name = feed["name"]
        url = feed["url"]
        xml_text = _fetch_feed(url, cfg.http_timeout)
        if not xml_text:
            continue

        raw = _parse_rss(xml_text, name)
        count_before = len(items)

        for r in raw:
            item_url = r.get("url", "").strip()
            item_title = r.get("title", "").strip()
            if not item_url or not item_title:
                continue
            if item_url in seen_urls:
                continue
            seen_urls.add(item_url)
            items.append(ScrapedItem(
                title=item_title,
                url=item_url,
                source="rss",
                summary=r.get("summary", ""),
                score=0,
                tags=[name],
                fetched_at=time.time(),
            ))

        logger.debug("[rss] %r â†’ %d new items", name, len(items) - count_before)

    logger.info("[rss] Fetched %d items from %d feeds.", len(items), len(FEEDS))
    return items

