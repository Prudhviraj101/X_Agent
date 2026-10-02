"""
poster.py — Posts tweets via twitter-cli (free, uses logged-in browser session).

Primary:  `twitter post "..."` — FREE route using TWITTER_AUTH_TOKEN/TWITTER_CT0
          from .env (same session that already reads the feed). No paid API.
Fallback: Twitter API v2 OAuth when X_API_* credentials are set.
Draft:    If neither is available, tweets are saved to drafts/.

Set POST_TO_X=true to enable posting. It uses twitter-cli if its creds are set,
otherwise the OAuth path.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

_USER_SCRIPTS = r"C:\Users\Asus\AppData\Roaming\Python\Python314\Scripts"

# Twitter API v2 OAuth fallback
_TWEETS_URL = "https://api.twitter.com/2/tweets"


def _find_exe(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for ext in (".exe", ""):
        candidate = os.path.join(_USER_SCRIPTS, name + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


# ── Primary: twitter-cli post (free, browser-session auth) ─────────────────────

def _download_media(media: list[dict], dest: Path) -> list[str]:
    """Download image/video media to local files. Returns list of file paths."""
    import urllib.request
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for i, m in enumerate(media):
        url = m.get("url") if isinstance(m, dict) else None
        if not url:
            continue
        ext = ".mp4" if m.get("type") == "video" else ".jpg"
        path = dest / f"media_{int(time.time())}_{i}{ext}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r, open(path, "wb") as f:
                f.write(r.read())
            if path.stat().st_size > 0:
                files.append(str(path))
        except Exception as exc:
            logger.debug("[poster] media download failed: %s", exc)
    return files


def _gen_nanobanana(cfg: "Config", tweet_text: str, dest: Path) -> str | None:
    """Generate a post image with Nano Banana (Gemini 2.5 Flash Image).
    Returns a local file path, or None if generation fails / quota is hit."""
    if not cfg.gemini_api_key:
        return None
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=cfg.gemini_api_key)
        dest.mkdir(parents=True, exist_ok=True)
        resp = client.models.generate_content(
            model="gemini-2.5-flash-image",  # Nano Banana
            contents=f"Minimalist tech news illustration for an X post. No text, no words. Theme: {tweet_text[:120]}",
        )
        if resp.candidates and resp.candidates[0].content:
            for part in resp.candidates[0].content.parts:
                if getattr(part, "inline_data", None) and part.inline_data.data:
                    path = dest / f"nanobanana_{int(time.time())}.png"
                    path.write_bytes(part.inline_data.data)
                    logger.info("[poster] Nano Banana image saved: %s", path.name)
                    return str(path)
    except Exception as exc:
        logger.debug("[poster] Nano Banana generation failed: %s", exc)
    return None


def _post_twitter_cli(tweet_text: str, media_files: list[str] | None = None) -> dict:
    """Post via `twitter post` using TWITTER_AUTH_TOKEN/TWITTER_CT0 from env."""
    twitter_exe = _find_exe("twitter")
    if not twitter_exe:
        return {"success": False, "tweet_id": None, "tweet_url": None, "error": "twitter-cli not found"}
    auth_token = os.getenv("TWITTER_AUTH_TOKEN", "").strip()
    ct0 = os.getenv("TWITTER_CT0", "").strip()
    if not auth_token or not ct0:
        return {"success": False, "tweet_id": None, "tweet_url": None, "error": "no twitter creds"}

    cmd = [twitter_exe, "post", tweet_text]
    for f in (media_files or [])[:4]:  # twitter post supports up to 4 images
        cmd += ["-i", f]
    cmd.append("--json")

    try:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["TWITTER_AUTH_TOKEN"] = auth_token
        env["TWITTER_CT0"] = ct0
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=30,
            env=env, encoding="utf-8", errors="replace",
        )
        output = result.stdout.strip()
        data = json.loads(output) if output else {}
        if result.returncode == 0 and isinstance(data, dict) and data.get("ok"):
            tweet = data.get("data", {}) if isinstance(data.get("data"), dict) else data
            tweet_id = str(tweet.get("id") or data.get("id") or "")
            if not tweet_id:
                return {"success": True, "tweet_id": None, "tweet_url": None, "error": None}
            return {"success": True, "tweet_id": tweet_id,
                    "tweet_url": f"https://x.com/i/web/status/{tweet_id}", "error": None}
        error = data.get("error") if isinstance(data, dict) else None
        msg = (error.get("message") if isinstance(error, dict) else "") or result.stderr[:200]
        logger.warning("[poster] twitter-cli post failed: %s", msg)
        return {"success": False, "tweet_id": None, "tweet_url": None, "error": str(msg)}
    except subprocess.TimeoutExpired:
        return {"success": False, "tweet_id": None, "tweet_url": None, "error": "timeout"}
    except (json.JSONDecodeError, Exception) as exc:
        return {"success": False, "tweet_id": None, "tweet_url": None, "error": str(exc)}


# ── Fallback: Twitter API v2 OAuth (paid tier) ─────────────────────────────────

def _make_auth(cfg: "Config"):
    from requests_oauthlib import OAuth1
    return OAuth1(
        client_key=cfg.x_api_key,
        client_secret=cfg.x_api_secret,
        resource_owner_key=cfg.x_access_token,
        resource_owner_secret=cfg.x_access_secret,
    )


def _post_oauth(cfg: "Config", tweet_text: str) -> dict:
    import requests
    auth = _make_auth(cfg)
    try:
        resp = requests.post(_TWEETS_URL, auth=auth, json={"text": tweet_text}, timeout=20)
        if resp.status_code == 201:
            tweet_id = resp.json().get("data", {}).get("id", "")
            return {"success": True, "tweet_id": tweet_id,
                    "tweet_url": f"https://twitter.com/i/web/status/{tweet_id}", "error": None}
        if resp.status_code == 429:
            return {"success": False, "tweet_id": None, "tweet_url": None, "error": "rate_limited"}
        logger.error("[poster] OAuth HTTP %d: %s", resp.status_code, resp.text[:200])
        return {"success": False, "tweet_id": None, "tweet_url": None,
                "error": f"http_{resp.status_code}"}
    except Exception as exc:
        logger.error("[poster] OAuth error: %s", exc)
        return {"success": False, "tweet_id": None, "tweet_url": None, "error": str(exc)}


# ── Draft fallback ─────────────────────────────────────────────────────────────

def save_draft(cfg: "Config", tweet_text: str, item_dict: dict) -> Path:
    cfg.drafts_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    path = cfg.drafts_dir / f"{ts}_{hash(tweet_text) & 0xFFFF:04x}.json"
    payload = {"tweet": tweet_text, "char_count": len(tweet_text),
               "item": item_dict, "saved_at": time.time()}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("[poster] Draft saved: %s", path.name)
    return path


def _post_enabled(cfg: "Config") -> bool:
    # FREE twitter-cli route — just needs the session creds already in .env
    if os.getenv("TWITTER_AUTH_TOKEN") and os.getenv("TWITTER_CT0") and _find_exe("twitter"):
        return True
    # Paid OAuth fallback
    if cfg.x_api_key and cfg.x_api_secret and cfg.x_access_token and cfg.x_access_secret:
        return True
    return False


def _resolve_media(cfg: "Config", item_dict: dict, tweet: str, media_dir: Path) -> list[str]:
    """Get local media files for a post: downloaded from item media, or generated
    via Nano Banana when the post has none and generation is enabled."""
    files: list[str] = []

    # 1. Real scraped media (image/video from the source)
    for m in item_dict.get("media") or []:
        if m.get("type") == "image":
            files = _download_media([m], media_dir)
            if files:
                break

    # 2. If no usable image, generate one with Nano Banana (Gemini 2.5 Flash Image)
    if not files and os.getenv("NANOBANANA", "").strip().lower() in ("1", "true", "yes"):
        gen = _gen_nanobanana(cfg, tweet, media_dir)
        if gen:
            files = [gen]

    return files


def publish(cfg: "Config", drafts: list[dict]) -> list[dict]:
    """Post each draft via twitter-cli (free) or OAuth; else save draft."""
    use_twitter_cli = bool(
        os.getenv("TWITTER_AUTH_TOKEN") and os.getenv("TWITTER_CT0") and _find_exe("twitter")
    )
    use_oauth = bool(cfg.x_api_key and cfg.x_api_secret and cfg.x_access_token and cfg.x_access_secret)
    enabled = cfg.post_to_x and (use_twitter_cli or use_oauth)
    media_dir = cfg.project_root / "media"

    outcomes = []
    for d in drafts:
        tweet = d.get("tweet", "")
        item = d.get("item")
        item_dict = item.to_dict() if item else {}

        if not tweet:
            outcomes.append({**d, "posted": False, "reason": "empty_tweet"})
            continue

        if enabled:
            media_files = _resolve_media(cfg, item_dict, tweet, media_dir)
            result = _post_twitter_cli(tweet, media_files) if use_twitter_cli else _post_oauth(cfg, tweet)
            outcomes.append({
                **d,
                "posted": result["success"],
                "tweet_id": result.get("tweet_id"),
                "tweet_url": result.get("tweet_url"),
                "error": result.get("error"),
                "media": media_files,
            })
            if result["success"]:
                logger.info("[poster] Posted: %s (%d media)", result.get("tweet_url"), len(media_files))
            else:
                save_draft(cfg, tweet, item_dict)
        else:
            save_draft(cfg, tweet, item_dict)
            outcomes.append({**d, "posted": False, "reason": "draft_mode"})

    return outcomes