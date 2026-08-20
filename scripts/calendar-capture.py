#!/usr/bin/env python3
"""
Nao calendar capture — nightly, silent by default, stateful.

The calendar is the most honest record of who Ruben actually saw and where he
actually went: written down before the fact, not reconstructed after it. This
turns that into Tana's episodic memory, which the Sunday relationship review
then reads.

It proposes; it never writes to Tana on its own. A calendar entry is a plan,
and plans get cancelled — logging a dinner that never happened is worse than
logging nothing, because the relationship review believes it. Confirmation
comes back through the Telegram bridge (`log 1,3` / `log all` / `no`), which
owns the write half via prompts/calendar-log.md.

Same split as watcher.py:
  - `claude -p` does RETRIEVAL and CLASSIFICATION (it needs MCP for Calendar
    and Tana)
  - this script does BOOKKEEPING (must be exact, so no LLM in that path)

State lives in state/calendar-seen.json, keyed by Google Calendar event id.
That is what stops the same hangout being proposed every night forever. An
event proposed MAX_PROPOSALS times with no answer is retired rather than
re-sent — notification fatigue is the failure mode of this whole idea, and it
arrives by accumulation.

Exit codes: 0 = ran fine (silent or proposed), 1 = collector failed.
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
SEEN_PATH = os.path.join(NAO, "state", "calendar-seen.json")
PENDING_PATH = os.path.join(NAO, "state", "calendar-pending.json")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")
PROPOSE_PROMPT = os.path.join(NAO, "prompts", "calendar-propose.md")

MAX_ITEMS = 6          # a wall of proposals gets ignored wholesale
MAX_PROPOSALS = 2      # then retire it unanswered; silence beats nagging
SEEN_RETENTION_DAYS = 180
COLLECT_TIMEOUT = 600
MODEL = os.environ.get("NAO_CALENDAR_MODEL", "sonnet")


def log(msg):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write("[%s] calendar-capture: %s\n" % (stamp, msg))


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


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, ValueError) as e:
        if os.path.exists(path):
            # A corrupt seen-file would otherwise re-propose months of events.
            log("%s unreadable (%s) — treating as empty" % (path, e))
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def prune(seen):
    """Keep the seen-file bounded without ever forgetting a live proposal."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_RETENTION_DAYS)
    kept = {}
    for k, v in seen.items():
        at = v.get("at")
        if not at:
            kept[k] = v
            continue
        try:
            if datetime.fromisoformat(at) >= cutoff:
                kept[k] = v
        except ValueError:
            kept[k] = v
    return kept


def collect():
    """Run the proposer. Returns a list, or None if the run failed."""
    with open(PROPOSE_PROMPT) as f:
        prompt = f.read()

    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", MODEL, "--output-format", "text",
             "--dangerously-skip-permissions"],
            input=prompt, capture_output=True, text=True,
            cwd=NAO, env=env, timeout=COLLECT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log("collector timed out after %ds" % COLLECT_TIMEOUT)
        return None
    if proc.returncode != 0:
        log("collector failed (exit %d): %s"
            % (proc.returncode, proc.stderr.strip()[:300]))
        return None

    out = proc.stdout.strip()
    match = re.search(r"\[.*\]", out, re.DOTALL)
    if not match:
        log("collector returned no JSON array: %r" % out[:300])
        return None
    try:
        items = json.loads(match.group(0))
    except ValueError as e:
        log("collector JSON invalid (%s): %r" % (e, out[:300]))
        return None
    if not isinstance(items, list):
        log("collector returned %s, not a list" % type(items).__name__)
        return None
    return items


def describe(item):
    """One line per proposal. Says exactly what confirming would create."""
    if item.get("kind") == "trip":
        span = item.get("start", "?")
        if item.get("end") and item["end"] != item.get("start"):
            span += " → %s" % item["end"]
        bits = [b for b in (item.get("destination"), span) if b]
        return "%s — trip (%s)" % (item.get("title", "?"), ", ".join(bits))

    people = item.get("people") or []
    if not people:
        who = "no one named — who was there?"
    else:
        who = ", ".join(
            "%s%s" % (p.get("name", "?"), "" if p.get("id") else " (new)")
            for p in people)
    return "%s — %s, %s" % (item.get("title", "?"),
                            item.get("date", "?"), who)


def send(text, markup=None):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("no telegram credentials — printing instead")
        print(text)
        return
    params = {"chat_id": chat_id, "text": text}
    if markup:
        params["reply_markup"] = markup
    data = urllib.parse.urlencode(params).encode()
    url = "https://api.telegram.org/bot%s/sendMessage" % token
    try:
        urllib.request.urlopen(url, data=data, timeout=20).read()
    except Exception as e:
        log("telegram send failed: %s" % e)


def main():
    load_env()

    items = collect()
    if items is None:
        return 1

    seen = prune(read_json(SEEN_PATH, {}))
    now = datetime.now(timezone.utc).isoformat()

    fresh = []
    for item in items:
        eid = item.get("eventId")
        if not eid:
            # No id means no dedupe key, which means it would come back every
            # night. Dropping it is the only safe move.
            log("skipping proposal with no eventId: %r" % item.get("title"))
            continue
        record = seen.get(eid)
        if record and record.get("outcome") in ("logged", "skipped", "retired"):
            continue
        if record and record.get("proposals", 0) >= MAX_PROPOSALS:
            record["outcome"] = "retired"
            record["at"] = now
            log("retiring unanswered proposal: %s" % item.get("title"))
            continue
        fresh.append(item)

    if not fresh:
        write_json(SEEN_PATH, seen)
        log("nothing new to propose (%d candidate(s) already handled)"
            % len(items))
        return 0

    fresh = fresh[:MAX_ITEMS]

    for item in fresh:
        eid = item["eventId"]
        record = seen.get(eid, {"proposals": 0})
        record["proposals"] = record.get("proposals", 0) + 1
        record["at"] = now
        record["title"] = item.get("title", "")
        record["outcome"] = "pending"
        seen[eid] = record

    write_json(PENDING_PATH, {"items": fresh, "at": now})
    write_json(SEEN_PATH, seen)

    lines = ["📅 From your calendar (nothing written yet):"]
    for i, item in enumerate(fresh, 1):
        lines.append("%d. %s" % (i, describe(item)))
        if item.get("reason"):
            lines.append("     %s" % item["reason"])
    lines.append("")
    lines.append("`log all` / `log 1,3` / `no`")

    markup = json.dumps({"inline_keyboard": [[
        {"text": "Log all", "callback_data": "cal:all"},
        {"text": "Skip", "callback_data": "cal:no"},
    ]]})

    send("\n".join(lines), markup)
    log("proposed %d item(s): %s"
        % (len(fresh), ", ".join(i.get("title", "?") for i in fresh)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
