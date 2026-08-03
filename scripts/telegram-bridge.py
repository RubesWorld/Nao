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
import re
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

NAO = os.path.expanduser("~/Nao")
STATE_DIR = os.path.join(NAO, "state")
OFFSET_PATH = os.path.join(STATE_DIR, "telegram-offset.json")
WATCHER_STATE = os.path.join(STATE_DIR, "watcher.json")
LAST_BATCH = os.path.join(STATE_DIR, "watcher-lastbatch.json")
PENDING = os.path.join(STATE_DIR, "cleanup-pending.json")
PROPOSE_PROMPT = os.path.join(NAO, "prompts", "cleanup-propose.md")
EXECUTE_PROMPT = os.path.join(NAO, "prompts", "cleanup-execute.md")
LOCK_PATH = os.path.join(STATE_DIR, "telegram-bridge.lock")
AUDIT_LOG = os.path.join(NAO, "logs", "telegram-bridge.log")

POLL_TIMEOUT = 30
CLAUDE_TIMEOUT = 600
TELEGRAM_LIMIT = 4096
RATE_LIMIT_PER_HOUR = 30
MAX_CONSECUTIVE_ERRORS = 20   # then exit and let launchd restart us
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


def keyboard(rows):
    """Inline keyboard. rows = [[(label, callback_data), ...], ...]

    callback_data is capped at 64 bytes by Telegram, so keep it terse —
    it maps to a text command below rather than carrying state itself.
    """
    return json.dumps({"inline_keyboard": [
        [{"text": label, "callback_data": data} for label, data in row]
        for row in rows
    ]})


def send(token, chat_id, text, markup=None):
    """Split rather than truncate — a cut-off answer is worse than two messages."""
    if not text.strip():
        text = "(no output)"
    chunks = [text[i:i + TELEGRAM_LIMIT] for i in range(0, len(text), TELEGRAM_LIMIT)]
    for n, chunk in enumerate(chunks):
        params = {"chat_id": chat_id, "text": chunk}
        # Buttons ride on the LAST chunk so they sit at the bottom.
        if markup and n == len(chunks) - 1:
            params["reply_markup"] = markup
        try:
            api(token, "sendMessage", params)
        except Exception as e:
            audit("send failed: %s" % e)
            return


# A tap resolves to the same string a typed command would produce, so there
# is exactly one implementation of every action.
def callback_to_command(data):
    if data == "w:snooze":
        return "snooze 7d"
    if data == "w:done":
        return "done"
    if data == "w:drop":
        return "drop"
    if data == "c:all":
        return "do all"
    if data == "c:no":
        return "no"
    if data.startswith("c:"):
        n = data[2:]
        return "do %s" % n if n.isdigit() else None
    return None


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

def propose_cleanup(scope):
    """Read-only scan. Writes the numbered list Python owns, not the model."""
    with open(PROPOSE_PROMPT) as f:
        prompt = f.read()
    prompt += "\n\n# Scope for this run\n\n%s\n" % (scope or "all")

    out = run_claude(prompt, model="sonnet")
    match = re.search(r"\[.*\]", out, re.DOTALL)
    if not match:
        return "Couldn't read a proposal list. Nothing changed.\n\n%s" % out[:500]
    try:
        items = json.loads(match.group(0))
    except ValueError as e:
        return "Proposal wasn't valid JSON (%s). Nothing changed." % e

    if not items:
        write_json(PENDING, {"items": [], "at": datetime.now(timezone.utc).isoformat()})
        return "Nothing to clean up in that scope."

    items = items[:12]
    write_json(PENDING, {"items": items,
                         "at": datetime.now(timezone.utc).isoformat()})

    verb = {"trash": "trash", "mark_outdated": "mark outdated", "mark_done": "mark done"}
    lines = ["Proposed (nothing changed yet):"]
    for i, it in enumerate(items, 1):
        lines.append("%d. %s — %s" % (i, it.get("title", "?"),
                                      verb.get(it.get("action"), it.get("action"))))
        if it.get("reason"):
            lines.append("     %s" % it["reason"])
    lines.append("")
    lines.append("or type `do 1,3` to pick specific ones")

    # Deliberately only bulk actions as buttons. Per-item buttons would need
    # stable numbering across partial applies AND a keyboard that survives a
    # tap — editMessageText strips it. Typing `do 1,3` handles the rarer
    # granular case without that complexity.
    return "\n".join(lines), keyboard([[("Apply all", "c:all"),
                                        ("Cancel", "c:no")]])


def execute_cleanup(selection):
    pending = read_json(PENDING, {}).get("items") or []
    if not pending:
        return "No pending proposal. Send `cleanup` first."

    if selection.strip() in ("all", "*"):
        chosen = list(range(len(pending)))
    else:
        chosen = []
        for part in re.split(r"[,\s]+", selection.strip()):
            if not part:
                continue
            if not part.isdigit():
                return "Couldn't read %r. Try `do 1,3` or `do all`." % part
            idx = int(part) - 1
            if not 0 <= idx < len(pending):
                return "No item %s — the list has %d." % (part, len(pending))
            chosen.append(idx)
    if not chosen:
        return "Nothing selected."

    picked = [pending[i] for i in sorted(set(chosen))]
    with open(EXECUTE_PROMPT) as f:
        prompt = f.read()
    prompt += "\n\n```json\n%s\n```\n" % json.dumps(picked, indent=2)

    audit("CLEANUP EXECUTE %d item(s): %s"
          % (len(picked), ", ".join(p.get("id", "?") for p in picked)))
    result = run_claude(prompt, model="sonnet")

    # Consume the proposal either way — stale numbering is how the wrong
    # thing gets deleted on a second `do`.
    write_json(PENDING, {"items": [], "at": datetime.now(timezone.utc).isoformat()})
    return result or "(no output)"


def builtin(text):
    cmd = text.strip().lower()

    if cmd in ("help", "/help", "?"):
        return ("Nao bridge\n"
                "  snooze 7d  — mute the last alert for N days\n"
                "  done       — clear it (mark handled)\n"
                "  drop       — clear it and stop tracking\n"
                "  status     — what the watcher is tracking\n"
                "  cleanup [facts|promises|schema|all]\n"
                "             — propose tidy-ups, changes nothing\n"
                "  do 1,3 / do all / no\n"
                "             — act on the last proposal\n"
                "anything else is passed to Nao")

    if cmd == "cleanup" or cmd.startswith("cleanup "):
        return propose_cleanup(cmd[len("cleanup"):].strip())

    if cmd == "do" or cmd.startswith("do "):
        return execute_cleanup(cmd[len("do"):].strip())

    if cmd in ("no", "cancel", "nevermind", "never mind"):
        if read_json(PENDING, {}).get("items"):
            write_json(PENDING, {"items": []})
            return "Discarded. Nothing changed."
        return None   # not answering a proposal — let Claude handle it

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
            return ("Nothing recent to clear — no alert has been sent yet, "
                    "or it was already handled.")

        batch = read_json(LAST_BATCH, {})
        at = batch.get("at")
        if at:
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(at)
                if age > timedelta(days=2):
                    return ("The last alert was %d days ago — too old to act on "
                            "blind. Send `status` to see what's tracked."
                            % age.days)
            except ValueError:
                pass

        state = read_json(WATCHER_STATE, {})
        cleared = [state.pop(k) for k in keys if k in state]
        write_json(WATCHER_STATE, state)
        if not cleared:
            return "Already cleared."

        if cmd.endswith("drop"):
            # Drop = "not doing this". Stop nagging, leave Tana untouched.
            return ("Dropped %d item(s) — I'll stop tracking them.\n"
                    "Tana is unchanged; they still read Open there."
                    % len(cleared))

        # Done = "I did it". Close the loop properly rather than just
        # forgetting, which is the whole point of Status + Closed existing.
        node_ids = [k.split(":", 1)[1] for k in keys if ":" in k]
        instruction = (
            "Mark these #promise nodes complete in Tana workspace drg2JUfK3f-A.\n"
            "For EACH node id below: set Status (R4CiFnM0eZgx) to Done, and set "
            "Closed (tfAT2tfpG0gi) to today's date in YYYY-MM-DD (get it with "
            "`date +%Y-%m-%d`).\n"
            "Touch nothing else. Reply with one short line per node, nothing more.\n\n"
            + "\n".join("- %s" % n for n in node_ids))
        audit("DONE -> closing promises in Tana: %s" % ", ".join(node_ids))
        result = run_claude(instruction, model="sonnet")
        return "Cleared %d item(s) and closed in Tana:\n%s" % (len(cleared), result)

    return None


def run_claude(text, model=None):
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", model or MODEL, "--output-format", "text",
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
    consecutive_errors = 0

    while True:
        try:
            resp = api(token, "getUpdates",
                       {"offset": offset, "timeout": POLL_TIMEOUT},
                       timeout=POLL_TIMEOUT + 15)
            consecutive_errors = 0
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                # Not transient — the token was revoked or rotated. Exiting
                # lets launchd KeepAlive restart us, which re-reads .env and
                # picks up the new token. Retrying in-process would spin
                # forever on a stale credential, which is exactly what it did.
                audit("FATAL: auth rejected (HTTP %d) — exiting so launchd "
                      "restarts with fresh .env" % e.code)
                return 1
            consecutive_errors += 1
            audit("poll error: %s" % e)
        except Exception as e:
            consecutive_errors += 1
            audit("poll error: %s" % e)

        if consecutive_errors:
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                audit("FATAL: %d consecutive poll failures — exiting for restart"
                      % consecutive_errors)
                return 1
            time.sleep(min(5 * consecutive_errors, 60))   # back off, don't hammer
            continue

        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            # Persist BEFORE executing. A crash mid-command loses it rather
            # than replaying it on restart — for commands with side effects,
            # losing is the safer failure.
            write_json(OFFSET_PATH, {"offset": offset})

            # ---- button taps ------------------------------------------
            cq = update.get("callback_query")
            if cq:
                cq_msg = cq.get("message") or {}
                chat_id = str(cq_msg.get("chat", {}).get("id", ""))
                if chat_id != allowed:
                    audit("REJECTED callback chat_id=%s" % chat_id)
                    continue
                data = cq.get("data") or ""
                cmd = callback_to_command(data)
                audit("TAP %r -> %r" % (data, cmd))

                # Always answer, or the button spins forever on his phone.
                try:
                    api(token, "answerCallbackQuery",
                        {"callback_query_id": cq["id"],
                         "text": "working…" if cmd else "unknown button"})
                except Exception as e:
                    audit("answerCallbackQuery failed: %s" % e)
                if not cmd:
                    continue

                result = builtin(cmd)
                if isinstance(result, tuple):
                    result = result[0]
                result = result or "(nothing to do)"

                # Strip the buttons so the same tap can't be replayed, and
                # record the outcome on the original message.
                try:
                    api(token, "editMessageText", {
                        "chat_id": chat_id,
                        "message_id": cq_msg.get("message_id"),
                        "text": ((cq_msg.get("text") or "")[:3500]
                                 + "\n\n— " + result[:500]),
                    })
                except Exception as e:
                    audit("editMessageText failed: %s" % e)
                    send(token, chat_id, result)
                continue

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

            # Most builtins are instant, but cleanup/do call Claude and can
            # take a minute. A silent gap reads as broken, so ack those too.
            lowered = text.strip().lower()
            if lowered.startswith(("cleanup", "do ")) or lowered == "do":
                send(token, chat_id, "on it…")

            reply = builtin(text)
            if reply is not None:
                # builtins may return plain text or (text, inline keyboard)
                if isinstance(reply, tuple):
                    send(token, chat_id, reply[0], markup=reply[1])
                else:
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
