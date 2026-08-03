#!/usr/bin/env python3
"""
Nao watcher — hourly, silent by default, stateful.

Unlike the report-generator jobs, this one remembers what it has already
said. That memory is the entire difference between proactive and
repetitive: promise-deadline-monitor re-sent the same nudge every morning
with no escalation and no way to dismiss it.

Split of responsibilities:
  - `claude -p` does RETRIEVAL (it needs MCP to reach Tana)
  - this script does BOOKKEEPING (must be exact, so no LLM in the path)

Exit codes: 0 = ran fine (silent or notified), 1 = collector failed.
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

NAO = os.path.expanduser("~/Nao")
STATE_PATH = os.path.join(NAO, "state", "watcher.json")
LAST_BATCH_PATH = os.path.join(NAO, "state", "watcher-lastbatch.json")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")
COLLECT_PROMPT = os.path.join(NAO, "prompts", "watcher-collect.md")

MAX_ITEMS_PER_MESSAGE = 3   # a wall of alerts gets ignored wholesale
DUE_SOON_DAYS = 2
ESCALATE_AFTER_HOURS = 24
MAX_NOTIFICATIONS = 3       # then auto-snooze; silence beats nagging
AUTO_SNOOZE_DAYS = 7
COLLECT_TIMEOUT = 300


def log(msg):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write("[%s] watcher: %s\n" % (stamp, msg))


def load_env():
    """run-task.sh sources .env; we are not launched through it."""
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


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (ValueError, IOError) as e:
        # A corrupt state file would otherwise re-notify everything as new.
        log("state file unreadable (%s) — starting empty" % e)
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)   # atomic: a half-written state is worse than none


def collect():
    """Run the collector prompt and parse its JSON array."""
    with open(COLLECT_PROMPT) as f:
        prompt = f.read()

    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

    proc = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--output-format", "text",
         "--dangerously-skip-permissions"],
        input=prompt, capture_output=True, text=True,
        cwd=NAO, env=env, timeout=COLLECT_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError("collector exited %d: %s"
                           % (proc.returncode, proc.stderr.strip()[:300]))

    out = proc.stdout.strip()
    # The model sometimes wraps JSON in prose or fences despite instructions.
    match = re.search(r"\[.*\]", out, re.DOTALL)
    if not match:
        raise RuntimeError("no JSON array in collector output: %r" % out[:300])
    return json.loads(match.group(0))


def evaluate(promises, today):
    """Return {key: item} for every promise currently tripping a condition."""
    active = {}
    for p in promises:
        deadline = p.get("deadline")
        if not deadline:
            continue   # no deadline means it can never be overdue
        try:
            due = datetime.strptime(deadline, "%Y-%m-%d").date()
        except ValueError:
            log("skipping %s — unparseable deadline %r" % (p.get("id"), deadline))
            continue

        days = (due - today).days
        if days < 0:
            condition, urgency = "promise_overdue", -days
        elif days <= DUE_SOON_DAYS:
            condition, urgency = "promise_due_soon", 1000 + days
        else:
            continue

        active["%s:%s" % (condition, p["id"])] = {
            "condition": condition,
            "what": p.get("what") or "(untitled promise)",
            "who": p.get("who"),
            "deadline": deadline,
            "days": days,
            "urgency": urgency,
        }
    return active


def describe(item, times_notified):
    days = item["days"]
    what = item["what"]
    # Self-commitments carry Who = "Self"; "...check it weekly for Self" reads badly.
    raw_who = (item.get("who") or "").strip()
    who = "" if raw_who.lower() in ("", "self", "ruben", "me") else " for %s" % raw_who

    if days < 0:
        n = -days
        head = "OVERDUE %d day%s: %s%s" % (n, "" if n == 1 else "s", what, who)
    elif days == 0:
        head = "Due today: %s%s" % (what, who)
    elif days == 1:
        head = "Due tomorrow: %s%s" % (what, who)
    else:
        head = "Due in %d days: %s%s" % (days, what, who)

    # The ladder: escalate rather than repeat verbatim.
    if times_notified == 1:
        return head + "\n  ↳ still open since I first flagged it"
    if times_notified >= 2:
        return head + "\n  ↳ third nudge — reply `snooze 7d`, `done`, or `drop`"
    return head


def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        log("no telegram creds — printing only")
        return False
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendMessage" % token, data=data)
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:
        log("telegram send failed: %s" % e)
        return False


def main():
    load_env()
    now = datetime.now(timezone.utc)
    today = now.date()

    try:
        promises = collect()
    except Exception as e:
        log("FAILED — %s" % e)
        return 1

    active = evaluate(promises, today)
    state = load_state()
    lines = []

    # --- Loop closing. Nothing in Nao currently notices a win. ------------
    for key in list(state):
        if key in active:
            continue
        done = state.pop(key)
        if done.get("timesNotified", 0) > 0:
            lines.append("Cleared: %s" % done.get("what", key))

    # --- New and escalating notifications --------------------------------
    due = []
    for key, item in active.items():
        entry = state.get(key)
        if entry is None:
            entry = {
                "condition": item["condition"],
                "what": item["what"],
                "firstSeen": today.isoformat(),
                "lastNotified": None,
                "timesNotified": 0,
                "snoozedUntil": None,
            }
            state[key] = entry
        entry["what"] = item["what"]   # keep the label fresh if Tana changed

        snoozed = entry.get("snoozedUntil")
        if snoozed and now < datetime.fromisoformat(snoozed):
            continue

        last = entry.get("lastNotified")
        if last:
            last_dt = datetime.fromisoformat(last)
            if last_dt.date() == today:
                continue   # never twice in one day, whatever the ladder says
            if entry["timesNotified"] >= 1 and \
               now - last_dt < timedelta(hours=ESCALATE_AFTER_HOURS):
                continue

        if entry["timesNotified"] >= MAX_NOTIFICATIONS:
            entry["snoozedUntil"] = (now + timedelta(days=AUTO_SNOOZE_DAYS)).isoformat()
            log("auto-snoozed %s after %d notifications" % (key, entry["timesNotified"]))
            continue

        due.append((item["urgency"], key, item, entry))

    due.sort(key=lambda t: t[0])   # most overdue first
    overflow = max(0, len(due) - MAX_ITEMS_PER_MESSAGE)

    sent_keys = []
    for _, key, item, entry in due[:MAX_ITEMS_PER_MESSAGE]:
        lines.append(describe(item, entry["timesNotified"]))
        entry["timesNotified"] += 1
        entry["lastNotified"] = now.isoformat()
        sent_keys.append(key)

    # The Telegram bridge resolves `snooze` / `done` / `drop` against this,
    # so a bare reply acts on whatever was most recently pushed.
    if sent_keys:
        with open(LAST_BATCH_PATH, "w") as f:
            json.dump({"keys": sent_keys, "at": now.isoformat()}, f, indent=2)

    if overflow:
        lines.append("(+%d more waiting)" % overflow)

    save_state(state)

    if not lines:
        log("quiet (%d open promises, %d active conditions)" % (len(promises), len(active)))
        return 0

    message = "\n".join(lines)
    print(message)
    send_telegram(message)
    log("notified %d item(s)" % len(due[:MAX_ITEMS_PER_MESSAGE]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
