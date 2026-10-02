"""
deduplicator.py — TTL-based URL deduplication store backed by a JSON file.

Thread-safe: all reads and writes go through a threading.Lock.
Atomic write: we write to a temp file then rename it to avoid corruption.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _url_key(url: str) -> str:
    """Stable key for a URL. Normalises GitHub URLs to owner/repo."""
    url = url.strip().rstrip("/").lower()
    # github.com/owner/repo[/...] -> github.com/owner/repo
    if "github.com/" in url:
        parts = url.split("github.com/")[1].split("/")
        if len(parts) >= 2:
            url = f"github.com/{parts[0]}/{parts[1]}"
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _title_tokens(title: str) -> set[str]:
    """Simple word set from a title (lowercase, strip short words)."""
    stop = {"a", "an", "the", "is", "in", "on", "of", "to", "and", "or",
            "for", "with", "this", "that", "are", "was", "has", "how",
            "new", "ai", "ml"}
    return {w for w in title.lower().split() if len(w) > 2 and w not in stop}


def _title_overlap(a: str, b: str) -> float:
    """Jaccard overlap between title token sets. Returns 0.0–1.0."""
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


class Deduplicator:
    """Remembers seen URLs and similar titles for `ttl_hours` hours."""

    def __init__(self, store_path: Path, ttl_hours: int = 48):
        self._path = store_path
        self._ttl = ttl_hours * 3600  # seconds
        self._lock = threading.Lock()
        # {url_key: {"url": str, "title": str, "seen_at": float}}
        self._store: dict[str, dict] = {}
        self._load()

    # ── Public API ────────────────────────────────────────────────────────

    def is_seen(self, url: str, title: str = "", similarity_threshold: float = 0.80) -> bool:
        """
        Return True if the URL or a very similar title was already seen
        within the TTL window.
        """
        with self._lock:
            self._prune()
            key = _url_key(url)
            if key in self._store:
                return True
            # Title similarity check
            if title:
                for entry in self._store.values():
                    if _title_overlap(title, entry.get("title", "")) >= similarity_threshold:
                        return True
            return False

    def mark_seen(self, url: str, title: str = "") -> None:
        """Record a URL as seen."""
        with self._lock:
            self._prune()
            self._store[_url_key(url)] = {
                "url": url,
                "title": title,
                "seen_at": time.time(),
            }
            self._save()

    def mark_seen_bulk(self, items: list[dict]) -> None:
        """Mark multiple items (each with 'url' and optional 'title') as seen."""
        with self._lock:
            self._prune()
            now = time.time()
            for item in items:
                url = item.get("url", "")
                if url:
                    self._store[_url_key(url)] = {
                        "url": url,
                        "title": item.get("title", ""),
                        "seen_at": now,
                    }
            self._save()

    def stats(self) -> dict:
        with self._lock:
            self._prune()
            return {"stored_urls": len(self._store)}

    # ── Internal ──────────────────────────────────────────────────────────

    def _prune(self) -> None:
        """Remove entries older than TTL. Call while holding self._lock."""
        cutoff = time.time() - self._ttl
        expired = [k for k, v in self._store.items() if v.get("seen_at", 0) < cutoff]
        for k in expired:
            del self._store[k]

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._store = data
            else:
                logger.warning("[dedup] Unexpected store format; starting fresh.")
                self._store = {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[dedup] Could not load store (%s); starting fresh.", exc)
            self._store = {}

    def _save(self) -> None:
        """Atomic write: temp-file → rename."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=self._path.parent, suffix=".tmp", prefix="dedup_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._store, f, indent=2)
                os.replace(tmp_path, self._path)
            except Exception:
                os.unlink(tmp_path)
                raise
        except OSError as exc:
            logger.error("[dedup] Failed to save store: %s", exc)
