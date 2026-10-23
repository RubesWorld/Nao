#!/usr/bin/env python3
"""
Nao nightly check-in — file the day Ruben talked through.

Ruben talks through his day in Tana mobile, as a voice memo or a voice chat
on a #nightly-checkin node (tag sbiN1DKnMwvg). It is his update, not an
interview: the voice chat only listens. Tana transcribes and fills the
node's fields as plain text. This files them: interactions, tasks, promises and
Last interaction are written straight away, because the evidence is his own
account; new contacts, Person news and facts are proposed on Telegram
(`add 1,3` / `add all` / `add no`). Policy in checkin_log.py.

Two modes:
  checkin-capture.py          every 15 min — file any finished check-in
  checkin-capture.py nudge    21:00 — remind him, unless he already did one

He can check in whenever he likes; the nudge is a reminder, not the trigger.

Same split as calendar-capture: Python decides WHICH node and WHEN, the model
decides what goes where. A check-in is filed only once its content has been
identical on two consecutive runs — Tana fills the fields when the chat ends,
and filing a half-written node would log half a day and then mark it done.
The node is moved under that day's daily note afterwards, which also takes it
out of the Inbox before triage can propose routing it.

State: state/checkin-seen.json, keyed by node id.
Exit codes: 0 = ran fine, 1 = Tana unreachable.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

NAO = os.path.expanduser("~/Nao")
sys.path.insert(0, os.path.join(NAO, "scripts"))

import checkin_log    # noqa: E402
from nao_telegram import send  # noqa: E402

SEEN_PATH = os.path.join(NAO, "state", "checkin-seen.json")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")
WORKSPACE = "drg2JUfK3f-A"

LOOKBACK_DAYS = 2
DAY_ROLLOVER_HOUR = 4    # a check-in at 00:30 is about the day before
EMPTY_GIVE_UP_HOURS = 6  # an empty node this old was abandoned, not pending
FILE_TIMEOUT = 900
MODEL = os.environ.get("NAO_CHECKIN_MODEL", "sonnet")


def log(msg):
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write("[%s] checkin-capture: %s\n" % (stamp, msg))


def run_claude(prompt):
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    proc = subprocess.run(
        ["claude", "-p", "--model", MODEL, "--output-format", "text",
         "--dangerously-skip-permissions"],
        input=prompt, capture_output=True, text=True,
        cwd=NAO, env=env, timeout=FILE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError("claude exited %d: %s"
                           % (proc.returncode, proc.stderr.strip()[:300]))
    return proc.stdout


def client():
    from tana_client import TanaClient
    return TanaClient()


def checkin_day(created_iso):
    """The day a check-in is about, from when it was recorded."""
    local = datetime.fromisoformat(
        created_iso.replace("Z", "+00:00")).astimezone()
    if local.hour < DAY_ROLLOVER_HOUR:
        local -= timedelta(days=1)
    return local.date().isoformat()


def recent_checkins(c, days=LOOKBACK_DAYS):
    raw = c.search_nodes({"and": [{"hasType": checkin_log.CHECKIN_TAG},
                                  {"created": {"last": days}}]})
    nodes = json.loads((raw or "").strip() or "[]")
    return [n for n in nodes if n.get("id") and not n.get("inTrash")]


def has_content(body):
    """Anything Ruben said, beyond the node title and empty field labels.

    read_node renders fields as `**Label**: value <!-- node-id -->`. Date is
    excluded: Tana may set it before the conversation has produced anything.
    """
    for line in body.splitlines()[1:]:
        text = re.sub(r"<!--.*?-->", "", line).strip().lstrip("- ").strip()
        m = re.match(r"\*\*([^*]+)\*\*:\s*(.*)$", text)
        if m:
            if m.group(1).strip().lower() != "date" and m.group(2).strip():
                return True
        elif text:
            return True
    return False


def run():
    c = client()
    try:
        nodes = recent_checkins(c)
    except Exception as e:
        log("tana unreachable (%s)" % e)
        return 1

    seen = checkin_log.read_json(SEEN_PATH, {})
    now = datetime.now(timezone.utc)
    filed, waiting = [], 0

    for node in nodes:
        nid = node["id"]
        rec = seen.get(nid, {})
        if rec.get("outcome") in ("filed", "empty"):
            continue

        body = c.call_tool("read_node", {"nodeId": nid, "maxDepth": 3}) or ""
        digest = hashlib.sha256(body.encode()).hexdigest()[:16]

        if not has_content(body):
            created = datetime.fromisoformat(
                node["created"].replace("Z", "+00:00"))
            if now - created > timedelta(hours=EMPTY_GIVE_UP_HOURS):
                rec.update({"outcome": "empty", "at": now.isoformat()})
                log("gave up on empty check-in %s" % nid)
            seen[nid] = rec
            continue

        # Settled = unchanged since the last run. The first sighting only
        # records the fingerprint; filing waits one more cycle.
        if rec.get("hash") != digest:
            rec.update({"hash": digest, "at": now.isoformat()})
            seen[nid] = rec
            waiting += 1
            continue

        day = checkin_day(node["created"])
        try:
            human, result = checkin_log.file_checkin(
                {"id": nid, "created": node["created"],
                 "fallbackDate": day, "content": body}, run_claude)
        except Exception as e:
            # Not marked filed, so the next run retries it.
            log("filing %s failed (%s)" % (nid, e))
            send("⚠️ Couldn't file tonight's check-in (%s). "
                 "I'll retry in 15 minutes." % str(e)[:120])
            continue

        day = result.get("date") or day
        try:
            day_node = json.loads(c.call_tool(
                "get_or_create_calendar_node",
                {"workspaceId": WORKSPACE, "date": day,
                 "granularity": "day"}))["nodeId"]
            c.call_tool("move_node", {"nodeId": nid, "targetNodeId": day_node})
        except Exception as e:
            # Filed is what matters; a check-in left in the Inbox is untidy,
            # not lost.
            log("filed %s but could not move it to %s (%s)" % (nid, day, e))

        rec.update({"outcome": "filed", "at": now.isoformat(), "day": day,
                    "receipts": len(result["receipts"])})
        seen[nid] = rec
        filed.append((human, result, day))

    checkin_log.write_json(SEEN_PATH, seen)

    if not filed:
        log("quiet (%d check-in(s) settling)" % waiting if waiting
            else "quiet")
        return 0

    for human, result, day in filed:
        report(human, result, day)
    log("filed %d check-in(s)" % len(filed))
    return 0


def report(human, result, day):
    lines = ["🌙 Filed your check-in for %s:" % day]
    lines.append(human or "Nothing to file — it was all on the node already.")
    rows = []
    if any(r.get("nodeId") for r in result["receipts"]):
        rows.append([("↩︎ Undo all", "cal:undo")])

    items = checkin_log.save_pending(result["proposals"], day) \
        if result["proposals"] else []
    if items:
        lines.append("")
        lines.append("Want me to add these? (nothing written yet)")
        for i, p in enumerate(items, 1):
            lines.append("%d. %s" % (i, checkin_log.describe(p)))
        lines.append("")
        lines.append("`add all` / `add 1,3` / `add no`")
        rows.append([("Add all", "ci:all"), ("Skip", "ci:no")])
    send("\n".join(lines), rows or None)


def nudge():
    """21:00 reminder — silent if today's check-in already exists."""
    today = checkin_day(datetime.now(timezone.utc).isoformat())
    try:
        nodes = recent_checkins(client(), days=1)
    except Exception as e:
        log("nudge: tana unreachable (%s) — skipping the reminder" % e)
        return 1
    if any(checkin_day(n["created"]) == today for n in nodes):
        log("nudge: already checked in today")
        return 0
    send("🌙 Check-in time. Tell Tana about your day: a voice memo or "
         "voice chat on nightly-checkin. Just talk; I'll file the rest.")
    log("nudge: sent")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    try:
        sys.exit(nudge() if mode == "nudge" else run())
    except KeyboardInterrupt:
        sys.exit(130)
