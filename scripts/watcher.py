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
RELAY_STATE_PATH = os.path.join(NAO, "state", "relay.json")

MAX_ITEMS_PER_MESSAGE = 3   # a wall of alerts gets ignored wholesale
DUE_SOON_DAYS = 2
ESCALATE_AFTER_HOURS = 24
MAX_NOTIFICATIONS = 3       # then auto-snooze; silence beats nagging
AUTO_SNOOZE_DAYS = 7
COLLECT_TIMEOUT = 300
RELAY_FAIL_THRESHOLD = 2    # hourly checks, so one blip is noise and two is an outage
RELAY_TIMEOUT = 10


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


def check_relay():
    """Poll the BlueBubbles iMessage relay. Returns (ok, detail).

    Probed over Tailscale rather than localhost on purpose: that is the path
    the phone actually uses, so a healthy server behind a dead tailnet is
    still down as far as Ruben is concerned. Only once that fails do we probe
    localhost, and purely to name which layer broke — the two have different
    fixes.

    Caveat worth remembering: this proves the HTTP API answers, not that the
    chat listener is still following the database. Checking for recent
    messages instead would fire every quiet evening, so it is deliberately
    not attempted.
    """
    host = os.environ.get("BLUEBUBBLES_HOST", "127.0.0.1")
    port = os.environ.get("BLUEBUBBLES_PORT", "1234")
    password = os.environ.get("BLUEBUBBLES_PASSWORD", "")
    if not password:
        return True, "no relay password configured — check skipped"

    def probe(target):
        url = "http://%s:%s/api/v1/server/info?password=%s" % (
            target, port, urllib.parse.quote(password))
        with urllib.request.urlopen(url, timeout=RELAY_TIMEOUT) as resp:
            return json.loads(resp.read().decode())

    try:
        probe(host)
        return True, "reachable at %s:%s" % (host, port)
    except Exception as e:
        reason = str(e)[:120]

    try:
        probe("127.0.0.1")
        return False, "server is up locally but unreachable over Tailscale (%s)" % reason
    except Exception:
        return False, "server not responding (%s)" % reason


def relay_watch(now):
    """Return lines to report about the relay — usually none.

    Kept entirely separate from the promise state machine. The snooze/done/drop
    ladder is promise-shaped and reads wrong for an outage, and sharing that
    dict would let a relay bug corrupt promise bookkeeping.
    """
    ok, detail = check_relay()

    try:
        with open(RELAY_STATE_PATH) as f:
            rs = json.load(f)
    except (IOError, ValueError):
        rs = {}

    fails = 0 if ok else rs.get("consecutiveFailures", 0) + 1
    rs["consecutiveFailures"] = fails
    rs["lastCheck"] = now.isoformat()
    rs["lastDetail"] = detail
    if ok:
        rs["lastOk"] = now.isoformat()

    lines = []
    notified = rs.get("notified", False)

    if not ok and fails >= RELAY_FAIL_THRESHOLD:
        last = rs.get("lastNotified")
        stale = (not last or
                 now - datetime.fromisoformat(last) >= timedelta(hours=ESCALATE_AFTER_HOURS))
        if not notified or stale:
            lines.append("iMessage relay is DOWN — %s\n"
                         "  ↳ messages are still arriving on the Mac; "
                         "you just will not see them on your phone" % detail)
            rs["notified"] = True
            rs["lastNotified"] = now.isoformat()
    elif ok and notified:
        # Closing the loop matters as much as opening it.
        lines.append("iMessage relay is back up.")
        rs["notified"] = False
        rs["lastNotified"] = None

    if not ok and fails < RELAY_FAIL_THRESHOLD:
        log("relay check failed (%d/%d) — %s" % (fails, RELAY_FAIL_THRESHOLD, detail))

    os.makedirs(os.path.dirname(RELAY_STATE_PATH), exist_ok=True)
    tmp = RELAY_STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rs, f, indent=2, sort_keys=True)
    os.replace(tmp, RELAY_STATE_PATH)

    return lines


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


def send_telegram(text, with_actions=False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        log("no telegram creds — printing only")
        return False
    params = {"chat_id": chat_id, "text": text}
    if with_actions:
        # The bridge maps these to the same commands typing them would produce.
        params["reply_markup"] = json.dumps({"inline_keyboard": [[
            {"text": "Snooze 7d", "callback_data": "w:snooze"},
            {"text": "Done", "callback_data": "w:done"},
            {"text": "Drop", "callback_data": "w:drop"},
        ]]})
    data = urllib.parse.urlencode(params).encode()
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

    # Runs before the collector so a Tana/MCP outage cannot also silence the
    # relay alarm — the two fail for entirely unrelated reasons.
    relay_lines = relay_watch(now)

    try:
        promises = collect()
    except Exception as e:
        log("FAILED — %s" % e)
        if relay_lines:
            message = "\n".join(relay_lines)
            print(message)
            send_telegram(message)
        return 1

    active = evaluate(promises, today)
    state = load_state()
    lines = list(relay_lines)   # an outage outranks any promise

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
    # Only offer buttons when there is something they could act on — a
    # message that is purely "Cleared: x" has nothing to snooze.
    send_telegram(message, with_actions=bool(sent_keys))
    log("notified %d item(s)" % len(due[:MAX_ITEMS_PER_MESSAGE]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
