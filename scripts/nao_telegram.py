#!/usr/bin/env python3
"""
Shared Telegram sender for Nao. The ONE implementation of sending.

Previously three copies existed (run-task.sh curl, watcher.py, the bridge),
each with its own truncation behavior — run-task.sh's `head -c 3500` could
slice an emoji mid-byte and Telegram rejects invalid UTF-8 with a 400,
silently killing the notification. This module chunks by characters, never
bytes, and splits long messages instead of truncating.

Usage as a module:
    from nao_telegram import send
    send("hello")                          # returns True on success
    send("pick one", keyboard=[[("Done", "w:done:0")]])

Usage from shell (run-task.sh):
    python3 nao_telegram.py "message text"
Exit 0 on success, 1 on failure or missing creds (with a line on stderr).
"""

import json
import os
import sys
import urllib.parse
import urllib.request

# Telegram's limit is 4096 UTF-16 code units. Chunking at 3500 Python
# characters leaves headroom for astral-plane emoji counting double.
CHUNK = 3500


def _load_env():
    """Best-effort: pick up ~/Nao/.env when run outside run-task.sh."""
    path = os.path.expanduser("~/Nao/.env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _api(token, method, params, timeout=20):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/%s" % (token, method), data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def send(text, keyboard=None, token=None, chat_id=None):
    """Send text, chunked. keyboard = [[(label, callback_data), ...], ...]
    and rides on the LAST chunk so buttons sit at the bottom.
    Returns True if every chunk was accepted."""
    _load_env()
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("nao_telegram: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set",
              file=sys.stderr)
        return False

    text = text if text.strip() else "(no output)"
    chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]
    for n, chunk in enumerate(chunks):
        params = {"chat_id": chat_id, "text": chunk}
        if keyboard and n == len(chunks) - 1:
            params["reply_markup"] = json.dumps({"inline_keyboard": [
                [{"text": label, "callback_data": data} for label, data in row]
                for row in keyboard
            ]})
        try:
            _api(token, "sendMessage", params)
        except Exception as e:
            print("nao_telegram: send failed: %s" % e, file=sys.stderr)
            return False
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: nao_telegram.py <message>", file=sys.stderr)
        sys.exit(1)
    sys.exit(0 if send(sys.argv[1]) else 1)
