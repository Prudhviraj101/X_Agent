"""
scraper/__init__.py â€” Common utilities and the ScrapedItem dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScrapedItem:
    """Normalised content item from any source."""
    title: str
    url: str
    source: str                     # e.g. "reddit", "github", "hn", "rss", "gnews"
    summary: str = ""               # Short excerpt / description
    score: int = 0                  # Upvotes, stars, HN points, etc.
    author: str = ""
    subreddit: str = ""
    tags: list[str] = field(default_factory=list)
    fetched_at: float = 0.0         # Unix timestamp
    media: list[dict] = field(default_factory=list)  # [{type: image|video, url}]

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "summary": self.summary,
            "score": self.score,
            "author": self.author,
            "subreddit": self.subreddit,
            "tags": self.tags,
            "fetched_at": self.fetched_at,
            "media": self.media,
        }

