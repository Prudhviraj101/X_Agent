"""
drafter.py Ã¢â‚¬â€ Generates Twitter/X posts from scraped items using an LLM.

Supports OpenAI and Google Gemini; provider is chosen via config.model_provider.
Each generated tweet:
  - Is Ã¢â€°Â¤ 280 characters
  - Includes the source URL
  - Uses 2Ã¢â‚¬â€œ3 relevant hashtags
  - Is engaging, punchy, and informative
  - Varies in tone across the batch (not formulaic)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Config
    from scraper import ScrapedItem

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a social media manager specialized in AI and technology content for X (formerly Twitter).
Your job: turn a content item (title, URL, brief summary) into a single engaging tweet.

Rules (STRICT):
1. Total tweet length MUST be Ã¢â€°Â¤ 280 characters, INCLUDING the URL.
2. Include the URL exactly as provided Ã¢â‚¬â€ do not shorten or modify it.
3. Use exactly 2Ã¢â‚¬â€œ3 relevant hashtags from: #AI #MachineLearning #LLM #OpenSource \
#DeepLearning #GenAI #MLOps #GPT #NLP #ComputerVision #AIResearch #Tech #GitHub \
#DataScience. Choose only those that fit the content.
4. Do NOT use generic openers like "Ã°Å¸Â¤â€“ Exciting news!" or "Just dropped:".
5. Vary tone: sometimes informative, sometimes provocative, sometimes analytical.
6. No clickbait. No emojis unless they genuinely add value (max 1).
7. Respond with the tweet text ONLY Ã¢â‚¬â€ no quotes, no explanation, no prefix.
"""

# Stage 1: Researcher Ã¢â‚¬â€ Gemini cleans raw scraped data into core facts
_HYBRID_RESEARCH_PROMPT = """\
You are a fast, precise research extractor. From the raw content below, extract the
CORE facts that matter into a clean, dense 3-5 bullet summary. Remove filler, marketing
fluff, and redundancy. Keep numbers, names, and the actual substance.

Raw content:
{raw}

Return ONLY the clean bullet-point facts. No preamble.
"""

# Stage 2: Writer Ã¢â‚¬â€ GPT writes the tweet from the clean facts
# Few-shot examples sampled from the real X for-you feed (high-engagement tweets):
# they teach the writer the punchy, specific, question-led style that actually
# gets replies and retweets.
_FEED_TEMPLATES = [
    "WeÃ¢â‚¬â„¢re introducing Claude Fable 5.1 and Claude Mythos 5.1. They're the worldÃ¢â‚¬â„¢s most advanced models for coding and knowledge work. https://t.co/8P9PSrWPi3",
    "Advertisers are using (and loving) the new X Ads Manager - no secret why - the results speak for themselves.",
    "Ã°Å¸Å¡Â¨#IMPORTANTSTATEMENTÃ°Å¸Å¡Â¨  A MAJOR VICTORY FOR THE YOUNG GENERATION ONCE AGAIN.  The Government of India and other BJP/NDA ruled states requested the Supreme Court to use its extraordi",
    "Pitch me your company in 1 word",
    "Role: Web Developer Intern\nSalary: $2,000 - $4,000 per month\nLocation: Remote\n\n- HTML, CSS, and JavaScript.\n- You want to work on software real people use\n\nLet us know if you are Interested Ã°Å¸â€˜â€¡",
    "WeÃ¢â‚¬â„¢re introducing Claude Fable 5.1 and Claude Mythos 5.1.\n\nThey're the worldÃ¢â‚¬â„¢s most advanced models for coding and knowledge work. https://t.co/8P9PSrWPi3",
]

# Module-level cache Ã¢â‚¬â€ refreshed once per pipeline run; lazy: one fetch per hour.
_TEMPLATES_CACHE: list[str] = _FEED_TEMPLATES
_TEMPLATES_CACHE_TS = 0.0
_TEMPLATES_CACHE_TTL = 3600.0  # 1 hour


def _fetch_viral_templates(max_n: int = 5) -> list[str]:
    """Pull the best-engagement tweets from X for-you feed (cached once/hour)."""
    global _TEMPLATES_CACHE, _TEMPLATES_CACHE_TS
    import shutil, subprocess, json

    if _TEMPLATES_CACHE and time.time() - _TEMPLATES_CACHE_TS < _TEMPLATES_CACHE_TTL:
        return _TEMPLATES_CACHE

    twitter_exe = shutil.which("twitter") or os.path.join(
        r"C:\Users\Asus\AppData\Roaming\Python\Python314\Scripts", "twitter.exe"
    )
    if not twitter_exe or not os.getenv("TWITTER_AUTH_TOKEN") or not os.getenv("TWITTER_CT0"):
        return _FEED_TEMPLATES  # no twitter creds Ã¢â€ â€™ use built-in seed

    try:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["TWITTER_AUTH_TOKEN"] = os.getenv("TWITTER_AUTH_TOKEN", "")
        env["TWITTER_CT0"] = os.getenv("TWITTER_CT0", "")
        result = subprocess.run(
            [twitter_exe, "feed", "--type", "for-you", "--max", "30", "--json"],
            capture_output=True, text=True, timeout=30,
            env=env, encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not result.stdout.strip():
            return _FEED_TEMPLATES

        data = json.loads(result.stdout.strip())
        tweets = data.get("data", []) if isinstance(data, dict) else []
        # score by engagement: likes + retweets*3 + replies*2
        scored = sorted(
            [t for t in tweets if isinstance(t, dict)],
            key=lambda t: (
                (t.get("metrics") or {}).get("likes", 0)
                + (t.get("metrics") or {}).get("retweets", 0) * 3
            ),
            reverse=True,
        )
        viral = [t["text"].strip() for t in scored[:max_n] if t.get("text")]
        if viral:
            _TEMPLATES_CACHE = viral
            _TEMPLATES_CACHE_TS = time.time()
            logger.debug("[drafter] Updated feed templates: %d tweets", len(viral))
            return viral
    except Exception as exc:
        logger.debug("[drafter] feed template fetch failed: %s", exc)

    return _FEED_TEMPLATES  # fallback to built-in seed

# Stage 2: Writer â€” GPT writes the tweet from the clean facts
_HYBRID_WRITE_PROMPT = """\
Write a highly detailed, 10-20 line deep-dive X/Twitter post from these clean facts, following the specific style guide below.

Facts:
{facts}

URL (include it verbatim in the tweet): {url}

HIGH-ENGAGEMENT STYLE REFERENCE:
{templates}

Rules:
- Write a long, deeply detailed thread/post consisting of 10-20 lines. Use #AI #ML #LLM #OpenSource where relevant.
- NO generic openers like "Exciting news!" or "Just dropped:".
- CODE FORMATTING: Use single backticks (code) for inline code or terminal commands. Strictly NO large multi-line code blocks (`).
- HYPE FILTER: If facts contain excessive buzzwords ("revolutionary", "mind-blowing", etc.) without concrete benchmarks or repository links, DISCARD the post by returning EXACTLY: [DISCARD_VAPORWARE]
- LINK PLACEMENT: The very last line of your output MUST be the URL: ðŸ”— {url}
- Format based on content type:

1. IF IT'S A NEW REPO:
Start with the direct problem it solves.
[Emoji] This new repo replaces [Old Tool Name]. It lets you [Benefit 1] and [Benefit 2] entirely locally.
ðŸ”— {url}

2. IF IT'S AN AI TOOL LAUNCH:
Focus on speed/cost/efficiency.
[Emoji] Build [Output] in under 60 seconds.
[Tool Name] just launched.
â€¢ Feature A
â€¢ Feature B
Thoughts on this? ðŸ‘‡
ðŸ”— {url}

3. IF IT'S TECH/AI NEWS:
Start with a bold, factual headline.
[Emoji] [Subject] just dropped [Model/Feature].
Here is what you need to know:
1. [Major change]
2. [Performance metric]
Why this matters: [Brief insight].
ðŸ”— {url}

- Return ONLY the tweet text (or [DISCARD_VAPORWARE]).
"""


def _build_prompt(item: "ScrapedItem") -> str:
    lines = [
        f"Title: {item.title}",
        f"URL: {item.url}",
    ]
    if item.summary:
        lines.append(f"Summary: {item.summary[:300]}")
    if item.source == "reddit" and item.subreddit:
        lines.append(f"Source: r/{item.subreddit} ({item.score} upvotes)")
    elif item.source == "github":
        lines.append(f"Source: GitHub Trending ({item.score:,} Ã¢Â­Â)")
    elif item.source == "hn":
        lines.append(f"Source: Hacker News ({item.score} points)")
    elif item.source == "rss" and item.tags:
        lines.append(f"Source: {item.tags[0]}")
    return "\n".join(lines)


def _draft_openai(cfg: "Config", prompts: list[str]) -> list[str]:
    from openai import OpenAI, RateLimitError, APIError

    client = OpenAI(api_key=cfg.openai_api_key)
    results = []
    for prompt in prompts:
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=cfg.openai_model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=800,
                    temperature=0.85,
                )
                tweet = resp.choices[0].message.content.strip()
                results.append(tweet)
                break
            except RateLimitError:
                wait = 2 ** attempt * 5
                logger.warning("[drafter] OpenAI rate limit; retrying in %ds", wait)
                time.sleep(wait)
            except APIError as exc:
                logger.error("[drafter] OpenAI API error: %s", exc)
                results.append("")
                break
        else:
            results.append("")
    return results



def _draft_nvidia(cfg: "Config", prompts: list[str]) -> list[str]:
    from openai import OpenAI
    client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=cfg.nvidia_api_key, timeout=30.0, max_retries=1)
    results = []
    for prompt in prompts:
        try:
            resp = client.chat.completions.create(
                model=cfg.nvidia_model,
                messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                max_tokens=800, temperature=0.85
            )
            results.append(resp.choices[0].message.content.strip())
        except Exception as exc:
            logger.error("[drafter] NVIDIA error: %s", exc)
            results.append("")
    return results

def _draft_gemini(cfg: "Config", prompts: list[str]) -> list[str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=cfg.gemini_api_key)
    results = []
    for prompt in prompts:
        for attempt in range(3):
            try:
                resp = client.models.generate_content(
                    model=cfg.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=_SYSTEM_PROMPT,
                        max_output_tokens=800,
                        temperature=0.85,
                    ),
                )
                tweet = resp.text.strip()
                results.append(tweet)
                break
            except Exception as exc:
                if "quota" in str(exc).lower() or "rate" in str(exc).lower() or "429" in str(exc):
                    wait = 2 ** attempt * 5
                    logger.warning("[drafter] Gemini rate limit; retrying in %ds", wait)
                    time.sleep(wait)
                else:
                    logger.error("[drafter] Gemini error: %s", exc)
                    results.append("")
                    break
        else:
            results.append("")
    return results


def _enforce_length(tweet: str, url: str, max_len: int = 280) -> str:
    """
    Ensure tweet Ã¢â€°Â¤ max_len chars.
    Twitter counts all URLs as 23 chars regardless of length, but we keep
    the full URL in the text so the API can process it.
    If still over budget, truncate the text before the URL.
    """
    if len(tweet) <= max_len:
        return tweet
    # If URL is embedded, split at URL and truncate text portion
    if url in tweet:
        before_url = tweet[: tweet.index(url)].rstrip()
        after_url = tweet[tweet.index(url) + len(url):]
        budget = max_len - len(url) - len(after_url) - 1  # account for space
        if budget > 20:
            return before_url[:budget].rstrip(".,;:") + " " + url + after_url
    # Fallback: hard truncate
    return tweet[: max_len - 1] + "Ã¢â‚¬Â¦"


# Hybrid writer failover state (module-level, persists across runs in-process)
# ponytail: single process flag; fine for one hourly scheduler thread.
_WRITER_MODE = "openai"   # "openai" | "gemini"
_OPENAI_BLOCKED_UNTIL = 0.0
_OPENAI_COOLDOWN = 300.0  # reselect OpenAI 5 min after it 429s


def _write_with_openai(writer, cfg, facts, url, templates=None) -> str:
    from openai import RateLimitError, APIError
    for attempt in range(2):
        try:
            wresp = writer.chat.completions.create(
                model=cfg.hybrid_writer_model,
                messages=[{"role": "user", "content": _HYBRID_WRITE_PROMPT.format(facts=facts, url=url, templates=_fmt_templates(templates))}],
                max_tokens=800, temperature=0.85,
            )
            return wresp.choices[0].message.content.strip()
        except RateLimitError:
            logger.warning("[drafter] writer (OpenAI) rate limited")
        except APIError as exc:
            logger.error("[drafter] writer (OpenAI) error: %s", exc)
            return ""
    return None  # rate-limited / quota exhausted


def _write_with_gemini(gemini_client, cfg, facts, url, templates=None) -> str:
    from google.genai import types
    try:
        resp = gemini_client.models.generate_content(
            model=cfg.gemini_model,
            contents=_HYBRID_WRITE_PROMPT.format(facts=facts, url=url, templates=_fmt_templates(templates)),
            config=types.GenerateContentConfig(max_output_tokens=800, temperature=0.85),
        )
        return resp.text.strip()
    except Exception as exc:
        logger.error("[drafter] writer (Gemini) error: %s", exc)
        return ""


def _fmt_templates(templates: list[str] | None) -> str:
    if not templates:
        return "(no reference available)"
    return "\n".join(f"{i+1}. {t}" for i, t in enumerate(templates[:5]))


def _draft_hybrid(cfg: "Config", items: list["ScrapedItem"]) -> list[str]:
    """Two-stage: Gemini (researcher) cleans facts Ã¢â€ â€™ OpenAI writer, failing over to
    Gemini when OpenAI is quota-limited, then back to OpenAI after its cooldown."""
    from google import genai
    from google.genai import types
    from openai import OpenAI

    global _WRITER_MODE, _OPENAI_BLOCKED_UNTIL

    # Stage 0: fetch high-engagement tweet templates from X feed (cached 1h)
    templates = _fetch_viral_templates(5)

    gemini_client = genai.Client(api_key=cfg.gemini_api_key)
    writer = OpenAI(api_key=cfg.openai_api_key)

    tweets: list[str] = []
    for item in items:
        raw = _build_prompt(item)

        # Stage 1: Gemini extracts clean facts
        try:
            resp = gemini_client.models.generate_content(
                model=cfg.hybrid_researcher_model,
                contents=_HYBRID_RESEARCH_PROMPT.format(raw=raw),
                config=types.GenerateContentConfig(max_output_tokens=300, temperature=0.3),
            )
            facts = resp.text.strip()
        except Exception as exc:
            logger.error("[drafter] hybrid researcher (Gemini) error: %s", exc)
            facts = raw  # fall back to raw data

        # Stage 2: write the tweet, failing over between providers
        tweet = ""
        if _WRITER_MODE == "openai":
            tweet = _write_with_openai(writer, cfg, facts, item.url, templates)
            if tweet is None:  # OpenAI quota exhausted -> flip to Gemini on cooldown
                _WRITER_MODE = "gemini"
                _OPENAI_BLOCKED_UNTIL = time.time() + _OPENAI_COOLDOWN
                logger.info("[drafter] OpenAI writer quota exhausted -> using Gemini writer")
                tweet = _write_with_gemini(gemini_client, cfg, facts, item.url, templates)
        else:  # gemini mode
            if time.time() >= _OPENAI_BLOCKED_UNTIL:  # cooldown over, probe OpenAI again
                tweet = _write_with_openai(writer, cfg, facts, item.url, templates)
                if tweet is not None:
                    _WRITER_MODE = "openai"
                    logger.info("[drafter] OpenAI writer quota reset -> switched back")
                else:
                    _OPENAI_BLOCKED_UNTIL = time.time() + _OPENAI_COOLDOWN
            if not tweet:
                tweet = _write_with_gemini(gemini_client, cfg, facts, item.url, templates)

        tweets.append(tweet)

    return tweets


def draft(cfg: "Config", items: list["ScrapedItem"]) -> list[dict]:
    """
    Generate tweet drafts for a list of items.
    Returns a list of dicts: {"item": ScrapedItem, "tweet": str, "ok": bool}
    """
    if not items:
        return []

    if not cfg.has_llm():
        logger.warning("[drafter] No LLM credentials configured; returning raw titles as drafts.")
        return [
            {
                "item": item,
                "tweet": f"{item.title[:200]} {item.url}",
                "ok": False,
                "fallback": True,
            }
            for item in items
        ]

    prompts = [_build_prompt(item) for item in items]

    if cfg.model_provider == "gemini":
        tweets = _draft_gemini(cfg, prompts)
    elif cfg.model_provider == "nvidia":
        tweets = _draft_nvidia(cfg, prompts)
    elif cfg.model_provider == "hybrid":
        tweets = _draft_hybrid(cfg, items)
    else:
        tweets = _draft_openai(cfg, prompts)

    results = []
    for item, tweet in zip(items, tweets):
        if not tweet:
            tweet = f"{item.title[:220]} {item.url}"
        tweet = tweet  # Length enforcement disabled for deep-dive posts
        results.append({"item": item, "tweet": tweet, "ok": bool(tweet)})
        logger.debug("[drafter] Draft (%d chars): %s", len(tweet), tweet[:80])

    return results







