"""
queue.py â€” Draft queue with HITL, safety filter, scheduled posting.

Three responsibilities in one file:
  1. SQLite queue: enqueue drafts, track status (pending/approved/rejected/posted)
  2. Safety filter: Gemini classifies each draft before HITL approval
  3. HITL web dashboard: stdlib http.server on HITL_PORT (default 8080)
  4. Poster loop: posts approved drafts at scheduled peak hours

Peak posting hours (UTC+5:30 by default, configurable via TIMEZONE_OFFSET):
  09:00, 12:00, 17:00, 21:00  â€” distributed across the day

Usage:
  import queue as q
  q.start(cfg)          # call from main.py; starts background threads
  q.enqueue(cfg, draft) # call from pipeline.py instead of poster.publish
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import textwrap
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import TYPE_CHECKING

import poster

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

# Peak hours in 24h format (local clock, controlled by TIMEZONE_OFFSET)
# ponytail: hard-coded peak hours; pass PEAK_HOURS=9,12,17,21 to override
_DEFAULT_PEAK_HOURS = [9, 12, 17, 21]

_HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>X-Agent Dashboard</title>
<style>
  body{{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;background:#0f1117;color:#e2e8f0}}
  h1{{color:#22d3ee;border-bottom:1px solid #1e293b;padding-bottom:12px}}
  .card{{background:#1e293b;border-radius:12px;padding:20px;margin:16px 0;border-left:4px solid {border}}}
  .tweet{{font-size:1.05em;white-space:pre-wrap;margin-bottom:14px;line-height:1.5}}
  .meta{{font-size:.8em;color:#94a3b8;margin-bottom:14px}}
  .safety{{font-size:.8em;padding:6px 10px;border-radius:6px;display:inline-block;margin-bottom:12px}}
  .safe{{background:#064e3b;color:#6ee7b7}}.unsafe{{background:#450a0a;color:#fca5a5}}
  form{{display:inline;margin-right:8px}}
  button{{padding:8px 16px;border:none;border-radius:8px;cursor:pointer;font-weight:600;font-size:.9em}}
  .approve{{background:#065f46;color:#d1fae5}}.approve:hover{{background:#047857}}
  .reject{{background:#450a0a;color:#fee2e2}}.reject:hover{{background:#7f1d1d}}
  textarea{{width:100%;background:#0f1117;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:10px;font-size:.95em;resize:vertical;box-sizing:border-box}}
  .edit-save{{background:#1e3a5f;color:#93c5fd;margin-top:6px}}.edit-save:hover{{background:#1d4ed8}}
  .empty{{color:#64748b;text-align:center;padding:60px;font-size:1.1em}}
  .status-bar{{position:fixed;top:0;right:0;background:#1e293b;padding:8px 16px;border-radius:0 0 0 12px;font-size:.8em;color:#94a3b8}}
</style>
</head>
<body>
<div class="status-bar">X-Agent ðŸ¤– &nbsp; Pending: {pending_count}</div>
<h1>ðŸ¤– X-Agent â€” Draft Approval</h1>
{body}
</body>
</html>
"""

_CARD_HTML = """\
<div class="card" style="border-left-color:{border}">
  <div class="meta">#{id} &nbsp;Â·&nbsp; {source} &nbsp;Â·&nbsp; scheduled {sched} &nbsp;Â·&nbsp; {chars} chars</div>
  <div class="safety {'safe' if safe else 'unsafe'}">{safety_icon} {safety_label}</div>
  <div class="tweet">{tweet}</div>
  <form method="POST" action="/approve"><input type="hidden" name="id" value="{id}">
    <button class="approve" type="submit">âœ… Approve</button></form>
  <form method="POST" action="/reject"><input type="hidden" name="id" value="{id}">
    <button class="reject" type="submit">âŒ Reject</button></form>
  <form method="POST" action="/edit">
    <input type="hidden" name="id" value="{id}">
    <textarea name="tweet" rows="3">{tweet}</textarea>
    <button class="edit-save" type="submit">ðŸ’¾ Save & Approve</button>
  </form>
</div>
"""

_SAFETY_PROMPT = """\
You are a content safety reviewer. Given this tweet draft, respond with EXACTLY one of:
  SAFE
  UNSAFE: <brief reason>

Rules â€” reject if the draft:
- Mentions real politics, elections, religion, or ongoing armed conflicts
- Makes unverifiable health/medical claims
- Is offensive, discriminatory, or harassing
- Is pure spam or self-promotion with no informational value

Tweet draft:
{tweet}
"""


# â”€â”€ Data layer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class DraftQueue:
    """Thin SQLite wrapper. Thread-safe (sqlite3 with isolation_level=None)."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._local = threading.local()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        if not getattr(self._local, "conn", None):
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init(self):
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tweet       TEXT    NOT NULL,
                    item_json   TEXT    NOT NULL,
                    source      TEXT,
                    safe        INTEGER DEFAULT 1,
                    safety_note TEXT    DEFAULT '',
                    status      TEXT    DEFAULT 'pending',
                    scheduled   TEXT,
                    created     TEXT    DEFAULT (datetime('now'))
                )""")

    def enqueue(self, tweet: str, item_dict: dict, scheduled: str, safe: bool, safety_note: str):
        with self._conn() as c:
            c.execute(
                "INSERT INTO drafts (tweet,item_json,source,safe,safety_note,status,scheduled)"
                " VALUES (?,?,?,?,?,?,?)",
                (tweet, json.dumps(item_dict, ensure_ascii=False, default=str),
                 item_dict.get("source", ""), int(safe), safety_note,
                 "pending", scheduled),
            )

    def pending(self) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM drafts WHERE status='pending' ORDER BY scheduled"
        ).fetchall()

    def approve(self, row_id: int, new_tweet: str | None = None):
        with self._conn() as c:
            if new_tweet:
                c.execute("UPDATE drafts SET status='approved', tweet=? WHERE id=?",
                          (new_tweet.strip(), row_id))
            else:
                c.execute("UPDATE drafts SET status='approved' WHERE id=?", (row_id,))

    def reject(self, row_id: int):
        with self._conn() as c:
            c.execute("UPDATE drafts SET status='rejected' WHERE id=?", (row_id,))

    def due_approved(self) -> list[sqlite3.Row]:
        """Approved drafts whose scheduled time is now or past."""
        now = time.strftime("%Y-%m-%d %H:%M")
        return self._conn().execute(
            "SELECT * FROM drafts WHERE status='approved' AND scheduled<=? ORDER BY scheduled",
            (now,),
        ).fetchall()

    def mark_posted(self, row_id: int, tweet_url: str):
        with self._conn() as c:
            c.execute(
                "UPDATE drafts SET status='posted', item_json=json_patch(item_json,?) WHERE id=?",
                (json.dumps({"tweet_url": tweet_url}), row_id),
            )

    def mark_posted_simple(self, row_id: int):
        with self._conn() as c:
            c.execute("UPDATE drafts SET status='posted' WHERE id=?", (row_id,))

    def pending_count(self) -> int:
        return self._conn().execute(
            "SELECT COUNT(*) FROM drafts WHERE status='pending'"
        ).fetchone()[0]


# â”€â”€ Safety filter â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _safety_check(cfg: "Config", tweet: str) -> tuple[bool, str]:
    """Returns (is_safe, note). Defaults to safe on any exception."""
    if not cfg.gemini_api_key:
        return True, ""
    try:
        from google import genai
        from google.genai import types
        c = genai.Client(api_key=cfg.gemini_api_key)
        resp = c.models.generate_content(
            model=cfg.gemini_model,
            contents=_SAFETY_PROMPT.format(tweet=tweet),
            config=types.GenerateContentConfig(max_output_tokens=40, temperature=0.0),
        )
        text = (resp.text or "").strip().upper()
        if text.startswith("UNSAFE"):
            note = resp.text.strip()[7:].strip(": ").strip() if len(resp.text) > 7 else ""
            return False, note[:120]
        return True, ""
    except Exception as exc:
        logger.debug("[queue] safety check error: %s", exc)
        return True, ""    # fail open â€” let HITL decide


# â”€â”€ Peak-hour scheduler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _next_peak_slot(peak_hours: list[int]) -> str:
    """Return the next peak datetime slot as a 'YYYY-MM-DD HH:MM' string."""
    now = time.localtime()
    today = time.strftime("%Y-%m-%d")
    for h in sorted(peak_hours):
        if now.tm_hour < h:
            return f"{today} {h:02d}:00"
    # All today's peaks passed â€” first slot tomorrow
    tomorrow = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))
    return f"{tomorrow} {sorted(peak_hours)[0]:02d}:00"


# â”€â”€ Telegram HITL â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _telegram_send(token: str, chat_id: str, text: str, row_id: int):
    import urllib.request, urllib.parse, json
    # Telegram inline keyboard
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "âœ… Approve", "callback_data": f"approve_{row_id}"},
                {"text": "âŒ Reject", "callback_data": f"reject_{row_id}"}
            ]
        ]
    }
    data = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "reply_markup": keyboard,
        "parse_mode": "HTML"
    }).encode('utf-8')
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error("[queue] Telegram send failed: %s", e)

def _telegram_edit(token: str, chat_id: str, message_id: int, new_text: str):
    import urllib.request, json
    # Edit message to remove buttons after click
    data = json.dumps({
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "HTML"
    }).encode('utf-8')
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/editMessageText",
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass


def _telegram_poll(queue: DraftQueue, stop: threading.Event):
    import urllib.request, json
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        logger.info("[queue] No TELEGRAM_BOT_TOKEN, skipping Telegram polling")
        return

    logger.info("[queue] Telegram HITL polling started")
    offset = 0
    while not stop.is_set():
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/getUpdates?timeout=20&offset={offset}")
            with urllib.request.urlopen(req, timeout=30) as r:
                updates = json.loads(r.read())['result']
            for u in updates:
                offset = u['update_id'] + 1
                if 'callback_query' in u:
                    cb = u['callback_query']
                    data = cb['data']
                    msg = cb['message']
                    chat_id = str(msg['chat']['id'])
                    msg_id = msg['message_id']
                    cb_id = cb['id']

                    # Answer callback immediately
                    try:
                        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/answerCallbackQuery?callback_query_id={cb_id}", timeout=5)
                    except Exception:
                        pass

                    if data.startswith("approve_"):
                        row_id = int(data.split("_")[1])
                        queue.approve(row_id)
                        logger.info("[queue] Telegram approved draft #%d", row_id)
                        _telegram_edit(token, chat_id, msg_id, f"âœ… <b>Approved</b>\n\n{msg.get('text','')}")
                    elif data.startswith("reject_"):
                        row_id = int(data.split("_")[1])
                        queue.reject(row_id)
                        logger.info("[queue] Telegram rejected draft #%d", row_id)
                        _telegram_edit(token, chat_id, msg_id, f"âŒ <b>Rejected</b>\n\n{msg.get('text','')}")
        except Exception as e:
            if not isinstance(e, TimeoutError):
                logger.debug("[queue] Telegram poll error: %s", getattr(e, 'reason', e))
        stop.wait(1)

def _make_handler(queue: DraftQueue):

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logger.debug("[dashboard] " + fmt, *args)

        def _send(self, body: str, code: int = 200):
            encoded = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            rows = queue.pending()
            cnt = queue.pending_count()
            if not rows:
                body = '<p class="empty">ðŸŽ‰ No pending drafts. The agent is draftingâ€¦</p>'
            else:
                cards = []
                for r in rows:
                    safe = bool(r["safe"])
                    border = "#22d3ee" if safe else "#f87171"
                    safety_icon = "âœ…" if safe else "âš ï¸"
                    safety_label = ("Safe" if safe else f"Flagged: {r['safety_note']}")
                    tweet_esc = str(r["tweet"]).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
                    cards.append(_CARD_HTML.format(
                        id=r["id"], source=r["source"] or "?",
                        sched=r["scheduled"] or "â€”",
                        chars=len(r["tweet"]),
                        safe=safe, border=border,
                        safety_icon=safety_icon, safety_label=safety_label,
                        tweet=tweet_esc,
                    ).replace("{'safe' if safe else 'unsafe'}",
                              "safe" if safe else "unsafe"))
                body = "\n".join(cards)
            html = _HTML_PAGE.format(body=body, pending_count=cnt,
                                      border="#22d3ee")
            self._send(html)

        def _parse_post(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode()
            return {k: urllib.parse.unquote_plus(v)
                    for k, v in (p.split("=", 1) for p in raw.split("&") if "=" in p)}

        def do_POST(self):
            data = self._parse_post()
            row_id = int(data.get("id", 0))
            path = self.path.rstrip("/")
            if path == "/approve":
                queue.approve(row_id)
                logger.info("[dashboard] Approved draft #%d", row_id)
            elif path == "/reject":
                queue.reject(row_id)
                logger.info("[dashboard] Rejected draft #%d", row_id)
            elif path == "/edit":
                queue.approve(row_id, new_tweet=data.get("tweet", ""))
                logger.info("[dashboard] Edited+approved draft #%d", row_id)
            # Redirect back to dashboard
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

    return Handler


# â”€â”€ Poster loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _poster_loop(cfg: "Config", queue: DraftQueue, stop: threading.Event):
    """Background thread: posts approved drafts when their scheduled time is due."""
    while not stop.is_set():
        try:
            for row in queue.due_approved():
                draft = {"tweet": row["tweet"], "item": None, "ok": True}
                try:
                    item_dict = json.loads(row["item_json"])
                except Exception:
                    item_dict = {}
                media_dir = cfg.project_root / "media"
                media_files = poster._resolve_media(cfg, item_dict, row["tweet"], media_dir)
                result = poster._post_twitter_cli(row["tweet"], media_files)
                if result["success"]:
                    queue.mark_posted_simple(row["id"])
                    logger.info("[queue] Posted #%d â†’ %s", row["id"], result.get("tweet_url"))
                else:
                    logger.warning("[queue] Post failed for #%d: %s", row["id"], result.get("error"))
        except Exception as exc:
            logger.error("[queue] Poster loop error: %s", exc)
        stop.wait(60)  # check every minute


# â”€â”€ Public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

_queue: DraftQueue | None = None
_stop = threading.Event()


def start(cfg: "Config") -> DraftQueue:
    """Start the HITL dashboard + poster loop. Call once from main.py."""
    global _queue
    db_path = cfg.project_root / "queue.db"
    q = DraftQueue(db_path)
    _queue = q

    # HITL web dashboard
    hitl_enabled = os.getenv("HITL", "true").strip().lower() in ("1", "true", "yes")
    port = int(os.getenv("HITL_PORT", "8080"))
    if hitl_enabled:
        handler = _make_handler(q)
        server = HTTPServer(("0.0.0.0", port), handler)
        t = threading.Thread(target=server.serve_forever, daemon=True, name="hitl-dashboard")
        t.start()
        logger.info("[queue] local HITL dashboard â†’ http://localhost:%d", port)

    # Telegram HITL
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        t_poll = threading.Thread(target=_telegram_poll, args=(q, _stop), daemon=True, name="tg-hitl")
        t_poll.start()

    # Poster loop
    pt = threading.Thread(target=_poster_loop, args=(cfg, q, _stop),
                          daemon=True, name="queue-poster")
    pt.start()
    logger.info("[queue] Poster loop started (checks every 60s)")

    return q


def enqueue(cfg: "Config", draft: dict, peak_hours: list[int] | None = None) -> None:
    """Safety-filter a draft and add it to the queue at the next peak slot."""
    global _queue
    if _queue is None:
        raise RuntimeError("Call queue.start(cfg) before queue.enqueue()")
    tweet = draft.get("tweet", "")
    item = draft.get("item")
    item_dict = item.to_dict() if item and hasattr(item, "to_dict") else {}

    _peak = peak_hours or [int(h) for h in os.getenv("PEAK_HOURS", "9,12,17,21").split(",") if h.strip()]
    scheduled = _next_peak_slot(_peak)

    safe, safety_note = _safety_check(cfg, tweet)
    if not safe:
        logger.info("[queue] Draft flagged unsafe: %s â†’ %r", safety_note, tweet[:60])

    _queue.enqueue(tweet, item_dict, scheduled, safe, safety_note)
    logger.info("[queue] Enqueued draft for %s (safe=%s): %sâ€¦", scheduled, safe, tweet[:60])

    # Send to Telegram if configured
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat:
        # Get the row_id of the just-inserted draft:
        with _queue._conn() as c:
            row_id = c.execute("SELECT id FROM drafts ORDER BY id DESC LIMIT 1").fetchone()[0]
        safety_indicator = "âœ… Safe" if safe else f"âš ï¸ Flagged: {safety_note}"
        text = f"ðŸ¤– <b>New Draft</b> (sched: {scheduled})\n{safety_indicator}\n\n{tweet}"
        _telegram_send(tg_token, tg_chat, text, row_id)

