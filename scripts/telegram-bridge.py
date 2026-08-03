#!/usr/bin/env python3
"""
Nao Telegram bridge — inbound commands from anywhere, executed on the mini.

Why the mini rather than a cloud dispatch: capability, not just latency.
This machine has tana-local on localhost, Monarch auth in its keyring, and
~/Nao/.env. A remote agent has none of those.

Why long polling rather than webhooks: no public URL, no tunnel, no inbound
port. The mini stays behind NAT exactly as it is today.

SECURITY — read before changing anything here.
    This executes text arriving from the internet on a machine holding
    Tana, financial credentials, and SSH keys. A bot token is a bearer
    credential: anyone who obtains it can message the bot. The chat-id
    allowlist below is the only thing between a leaked token and a shell.
    Do not weaken it, and do not reply to non-allowlisted senders — a
    reply confirms the bot is live.
"""

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

NAO = os.path.expanduser("~/Nao")
STATE_DIR = os.path.join(NAO, "state")
OFFSET_PATH = os.path.join(STATE_DIR, "telegram-offset.json")
WATCHER_STATE = os.path.join(STATE_DIR, "watcher.json")
LAST_BATCH = os.path.join(STATE_DIR, "watcher-lastbatch.json")
LOCK_PATH = os.path.join(STATE_DIR, "telegram-bridge.lock")
AUDIT_LOG = os.path.join(NAO, "logs", "telegram-bridge.log")

POLL_TIMEOUT = 30
CLAUDE_TIMEOUT = 600
TELEGRAM_LIMIT = 4096
RATE_LIMIT_PER_HOUR = 30
MODEL = os.environ.get("NAO_BRIDGE_MODEL", "sonnet")

_recent = []   # command timestamps, for rate limiting


def audit(msg):
    """Separate from tasks.log on purpose: this is the forensic record."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    line = "[%s] %s" % (stamp, msg)
    with open(AUDIT_LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_env():
    path = os.path.join(NAO, ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api(token, method, params=None, timeout=40):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def send(token, chat_id, text):
    """Split rather than truncate — a cut-off answer is worse than two messages."""
    if not text.strip():
        text = "(no output)"
    for i in range(0, len(text), TELEGRAM_LIMIT):
        try:
            api(token, "sendMessage",
                {"chat_id": chat_id, "text": text[i:i + TELEGRAM_LIMIT]})
        except Exception as e:
            audit("send failed: %s" % e)
            return


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Built-in commands. Handled directly, never through Claude — replying to an
# alert should be instant, free, and impossible to misinterpret.
# --------------------------------------------------------------------------

def builtin(text):
    cmd = text.strip().lower()

    if cmd in ("help", "/help", "?"):
        return ("Nao bridge\n"
                "  snooze 7d  — mute the last alert for N days\n"
                "  done       — clear it (mark handled)\n"
                "  drop       — clear it and stop tracking\n"
                "  status     — what the watcher is tracking\n"
                "anything else is passed to Nao")

    if cmd == "status":
        state = read_json(WATCHER_STATE, {})
        if not state:
            return "Watcher is tracking nothing. All clear."
        out = ["Watcher is tracking %d item(s):" % len(state)]
        for k, v in sorted(state.items()):
            bits = ["  • %s" % v.get("what", k)]
            bits.append("notified %dx" % v.get("timesNotified", 0))
            if v.get("snoozedUntil"):
                bits.append("snoozed until %s" % v["snoozedUntil"][:10])
            out.append(", ".join(bits))
        return "\n".join(out)

    keys = read_json(LAST_BATCH, {}).get("keys") or []

    if cmd.startswith("snooze"):
        parts = cmd.split()
        days = 7
        if len(parts) > 1:
            try:
                days = int(parts[1].rstrip("d"))
            except ValueError:
                return "Couldn't read that duration. Try `snooze 7d`."
        if not keys:
            return "Nothing recent to snooze."
        state = read_json(WATCHER_STATE, {})
        until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
        n = 0
        for k in keys:
            if k in state:
                state[k]["snoozedUntil"] = until
                n += 1
        write_json(WATCHER_STATE, state)
        return "Snoozed %d item(s) for %d days." % (n, days)

    if cmd in ("done", "drop", "/done", "/drop"):
        if not keys:
            return "Nothing recent to clear."
        state = read_json(WATCHER_STATE, {})
        n = 0
        for k in keys:
            if state.pop(k, None) is not None:
                n += 1
        write_json(WATCHER_STATE, state)
        # 'done' only clears the watcher's memory. The promise itself still
        # says Open in Tana — say so rather than implying otherwise.
        note = ("\nNote: this clears the reminder, not the Tana node. "
                "Ask me to mark it Done if you want that too.")
        return "Cleared %d item(s).%s" % (n, note if cmd.endswith("done") else "")

    return None


def run_claude(text):
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", MODEL, "--output-format", "text",
             "--dangerously-skip-permissions"],
            input=text, capture_output=True, text=True,
            cwd=NAO, env=env, timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "Timed out after %d minutes." % (CLAUDE_TIMEOUT // 60)
    if proc.returncode != 0:
        return "Failed (exit %d): %s" % (proc.returncode, proc.stderr.strip()[:500])
    return proc.stdout.strip()


def rate_limited():
    now = time.time()
    _recent[:] = [t for t in _recent if now - t < 3600]
    if len(_recent) >= RATE_LIMIT_PER_HOUR:
        return True
    _recent.append(now)
    return False


def acquire_lock():
    """launchd KeepAlive plus a stale-tolerant lock: never two bridges."""
    if os.path.exists(LOCK_PATH):
        try:
            pid = int(open(LOCK_PATH).read().strip())
            os.kill(pid, 0)
            return False          # a live bridge already owns it
        except (ValueError, ProcessLookupError, PermissionError):
            pass                  # stale lock from a crash
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))
    return True


def main():
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    allowed = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()

    if not token or not allowed:
        audit("FATAL: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set")
        return 1
    if not acquire_lock():
        audit("another bridge instance is running — exiting")
        return 0

    offset = read_json(OFFSET_PATH, {}).get("offset", 0)
    audit("bridge started (model=%s, allowed_chat=%s, offset=%d)"
          % (MODEL, allowed, offset))

    while True:
        try:
            resp = api(token, "getUpdates",
                       {"offset": offset, "timeout": POLL_TIMEOUT},
                       timeout=POLL_TIMEOUT + 15)
        except Exception as e:
            audit("poll error: %s" % e)
            time.sleep(5)
            continue

        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            # Persist BEFORE executing. A crash mid-command loses it rather
            # than replaying it on restart — for commands with side effects,
            # losing is the safer failure.
            write_json(OFFSET_PATH, {"offset": offset})

            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip()

            # ---- the security boundary --------------------------------
            if chat_id != allowed:
                audit("REJECTED chat_id=%s from=%r text=%r"
                      % (chat_id, msg.get("from", {}).get("username"), text[:80]))
                continue          # deliberately no reply
            if not text:
                continue
            if rate_limited():
                audit("RATE LIMITED: %r" % text[:80])
                send(token, chat_id, "Rate limit hit (%d/hr). Try again shortly."
                     % RATE_LIMIT_PER_HOUR)
                continue

            audit("CMD %r" % text[:300])

            reply = builtin(text)
            if reply is not None:
                send(token, chat_id, reply)
                continue

            # A silent multi-minute gap reads as broken.
            send(token, chat_id, "on it…")
            started = time.time()
            reply = run_claude(text)
            audit("done in %.1fs, %d chars" % (time.time() - started, len(reply)))
            send(token, chat_id, reply)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
