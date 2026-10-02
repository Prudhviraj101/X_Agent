"""Self-check for trending selection: RSS flood must not crowd out repo/tool sources."""
import sys, time
sys.path.insert(0, '.')
import pipeline
from scraper import ScrapedItem

def mk(title, url, source, score):
    return ScrapedItem(title=title, url=url, source=source, score=score,
                       summary="", fetched_at=time.time())

# 200 anonymous RSS filler with tiny scores
items = [mk(f"filler article {i}", f"https://rss.example/{i}", "rss", 2) for i in range(200)]
# 1 hot GitHub repo (1000 stars) — would be item #200 in a raw sort
items.append(mk("langchain just shipped Agent v2 with 10x speed",
                "https://github.com/langchain-ai/langchain", "github", 1000))
# 1 hot HN story
items.append(mk("Show HN: I built a real-time AI scraper", "https://news.ycombinator.com/i", "hn", 450))
# 1 hot Reddit topic
items.append(mk("LocalLLaMA runs 70B on a laptop now?", "https://reddit.com/r/local/1", "reddit", 800))

selected = pipeline._select_trending(items, limit=3)
sources = [i.source for i in selected]
print("selected sources:", sources)

assert "github" in sources, f"GitHub repo drowned out! {sources}"
assert len(selected) == 3, f"expected 3, got {len(selected)}"
assert selected[0].score >= max(i.score for i in items) or sources[0] == "github", "hottest item not selected"
print("PASSED: trending repo/tool sources guaranteed in the batch")

# Edge: no reserved sources -> falls back to global sort
items2 = [mk(f"a{i}", f"https://r/{i}", "rss", i) for i in range(10)]
sel2 = pipeline._select_trending(items2, limit=3)
assert [i.score for i in sel2] == [9, 8, 7], "global fallback broken"
print("PASSED: no reserved sources -> pure trending sort fallback")