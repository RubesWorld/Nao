#!/usr/bin/env python3
"""
Nao's action log — what was written, and why.

Separate from logs/tasks.log on purpose. That file is an operational log: it
answers "is the machine running", and it is dominated by heartbeats because
that is its job (health-check.py reads the watcher's hourly line to prove the
watcher is alive). Over seven days it carried 333 watcher lines against ~31
of everything else, so a change Nao made on its own is invisible in it.

This file answers a different question: **what did Nao do to my data, and on
what grounds.** So it records only two kinds of event —

  - a WRITE: something changed in Tana or on the calendar
  - a DECISION taken without asking: what it chose, and why

and never a heartbeat, a poll, or a run that changed nothing. Volume stays at
a few lines a day, which is what makes it readable a month later.

Two properties worth keeping:

  - **Append-only.** state/*.json holds current state and is rewritten; this
    holds history and never is. An action that later turns out wrong must
    still be visible, alongside the undo that reversed it.
  - **`why` is not optional.** A list of writes tells you what happened; only
    the reason tells you whether it should have. That field is the whole
    point of the file.

JSONL so it greps and pipes to jq:

    jq -r 'select(.action=="wrote") | "\\(.at) \\(.title)"' logs/actions.jsonl
    grep '"auto":true' logs/actions.jsonl

Never put a secret in here. It is plain text, it is committed nowhere, but it
is also never pruned.
"""

import json
import os
import sys
from datetime import datetime, timezone

NAO = os.path.expanduser("~/Nao")
ACTIONS_PATH = os.path.join(NAO, "logs", "actions.jsonl")


def record(actor, action, why=None, **fields):
    """Append one action. Never raises — an audit failure must not take down
    the thing being audited, which would trade a missing line for a missing
    feature."""
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "actor": actor, "action": action}
    if why:
        entry["why"] = why
    entry.update({k: v for k, v in fields.items() if v is not None})
    try:
        os.makedirs(os.path.dirname(ACTIONS_PATH), exist_ok=True)
        with open(ACTIONS_PATH, "a") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
    except IOError:
        pass
    return entry


def read(limit=20, actor=None, action=None, since=None):
    """Most recent first. Filters are exact matches; `since` is a date prefix
    like '2026-08-24'."""
    try:
        with open(ACTIONS_PATH) as f:
            lines = f.readlines()
    except IOError:
        return []
    out = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if actor and entry.get("actor") != actor:
            continue
        if action and entry.get("action") != action:
            continue
        if since and entry.get("at", "") < since:
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def describe(entry):
    """One readable line. Used for the Telegram `actions` command, where the
    whole value is being able to scan it on a phone."""
    when = entry.get("at", "")[5:16].replace("T", " ")
    what = (entry.get("title") or entry.get("detail")
            or entry.get("nodeId") or "")
    verb = entry.get("action", "?")
    mark = {"wrote": "✍️", "undo": "↩︎", "asked": "❓",
            "skipped": "–", "failed": "⚠️"}.get(verb, "·")
    line = "%s %s %s %s" % (mark, when, verb, what)
    if entry.get("auto"):
        line += " (auto)"
    if entry.get("why"):
        line += "\n     %s" % entry["why"]
    return line.rstrip()


def main(argv):
    """CLI so shell callers (run-task.sh) can append without importing."""
    if len(argv) >= 3 and argv[1] == "record":
        actor, action = argv[2], (argv[3] if len(argv) > 3 else "wrote")
        why = argv[4] if len(argv) > 4 else None
        detail = argv[5] if len(argv) > 5 else None
        print(json.dumps(record(actor, action, why=why, detail=detail)))
        return 0
    limit = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else 20
    for entry in reversed(read(limit)):
        print(describe(entry))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
