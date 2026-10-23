#!/usr/bin/env python3
"""
Shared filing and confirm logic for the nightly check-in.

Two entry points need this: checkin-capture.py files a finished check-in on
its own, and the Telegram bridge applies whatever Ruben picks with `add 1,3`.
One implementation so the two cannot drift — same arrangement as
calendar_log.py, and for the same reason.

The write policy is the calendar's, applied to stronger evidence. A check-in
is Ruben's own account of his day, so what he said happened gets written
without asking: interactions, tasks, promises, Last interaction. What he did
NOT say is never filled in — a Vibe is set only from stated sentiment. And
three things are proposed rather than written, because they change his long-
term memory rather than record a day: a new person entering his contacts,
durable news that belongs on a Person node, and facts about himself (the
memory protocol is propose-first).

Undo reuses calendar_log's batch. `undo` always means the most recent write,
whichever job made it — the only rule a person can reason about at 11pm.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

NAO = os.path.expanduser("~/Nao")
sys.path.insert(0, os.path.join(NAO, "scripts"))

import calendar_log  # noqa: E402
import nao_audit     # noqa: E402

PENDING_PATH = os.path.join(NAO, "state", "checkin-pending.json")
LOG_PROMPT = os.path.join(NAO, "prompts", "checkin-log.md")
CONFIRM_PROMPT = os.path.join(NAO, "prompts", "checkin-confirm.md")

CHECKIN_TAG = "sbiN1DKnMwvg"
MAX_PROPOSALS = 6   # a wall of proposals gets ignored wholesale


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


def split_output(text):
    """Return (human_text, result_dict).

    A missing or unparseable result is not fatal — the writes may already
    have happened, and saying so without an undo beats claiming failure.
    """
    empty = {"receipts": [], "proposals": []}
    if not text:
        return "", empty
    m = re.search(r"```json\s*(\{.*\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), empty
    try:
        result = json.loads(m.group(1))
    except ValueError:
        return text.strip(), empty
    if not isinstance(result, dict):
        return text.strip(), empty
    result.setdefault("receipts", [])
    result.setdefault("proposals", [])
    return (text[:m.start()] + text[m.end():]).strip(), result


def file_checkin(node, run_claude):
    """Write one check-in to Tana. Returns (human_text, result).

    node: {"id", "created", "content", "fallbackDate"}
    """
    with open(LOG_PROMPT) as f:
        prompt = f.read()
    prompt += "\n\n```json\n%s\n```\n" % json.dumps(
        {"nodeId": node["id"], "created": node.get("created"),
         "fallbackDate": node["fallbackDate"],
         "content": node["content"]}, indent=2)
    human, result = split_output(run_claude(prompt))

    for r in result["receipts"]:
        changed = {p["id"]: {"lastInteraction": [p.get("priorLastInteraction"),
                                                 result.get("date")]}
                   for p in (r.get("people") or []) if p.get("id")}
        nao_audit.record("checkin-capture", "wrote",
                         why="Ruben's own account (check-in %s)" % node["id"],
                         kind=r.get("kind"), title=r.get("title"),
                         nodeId=r.get("nodeId"),
                         appendedTo=r.get("appendedTo"), auto=True,
                         changed=changed or None)

    # Only created nodes are undoable; an append to an existing node has
    # nothing to trash, and trashing the node it went into would destroy
    # the calendar's (or Ruben's) record along with ours.
    undoable = [dict(r, eventId=None) for r in result["receipts"]
                if r.get("nodeId")]
    calendar_log.save_undo(undoable)
    return human, result


def describe(p):
    kind = p.get("kind")
    if kind == "new-person":
        line = "New contact: %s" % p.get("name", "?")
        if p.get("details"):
            line += " — %s" % p["details"]
        return line
    if kind == "person-update":
        return "%s: %s" % (p.get("name", "?"), p.get("update", ""))
    if kind == "fact":
        return "Fact: %s" % p.get("text", "")
    if kind == "new-area":
        line = "New area: %s" % p.get("name", "?")
        if p.get("why"):
            line += " — %s" % p["why"]
        return line
    return "%s: %s" % (kind, json.dumps(p)[:80])


def save_pending(proposals, date):
    """Replace the pending set. Numbering in Telegram must match exactly
    what `add 2` will act on, so there is only ever one live list."""
    items = [dict(p, date=p.get("date") or date)
             for p in proposals[:MAX_PROPOSALS]]
    write_json(PENDING_PATH, {"items": items,
                              "at": datetime.now(timezone.utc).isoformat()})
    for p in items:
        nao_audit.record("checkin-capture", "asked",
                         why="changes long-term memory; propose-first",
                         kind=p.get("kind"), title=describe(p))
    return items


def has_pending():
    return bool(read_json(PENDING_PATH, {}).get("items"))


def confirm(selection, run_claude):
    """`add all` / `add 1,3` / `add no` from the bridge."""
    sel = (selection or "").strip().lower()
    pending = read_json(PENDING_PATH, {}).get("items") or []
    if not pending:
        return "No check-in proposals waiting."
    now = datetime.now(timezone.utc).isoformat()

    if sel in ("no", "none", "skip"):
        for p in pending:
            nao_audit.record("bridge", "skipped", why="declined by Ruben",
                             kind=p.get("kind"), title=describe(p))
        write_json(PENDING_PATH, {"items": [], "at": now})
        return "Skipped %d — nothing added." % len(pending)

    if sel in ("all", "*", ""):
        chosen = list(range(len(pending)))
    else:
        chosen = []
        for part in re.split(r"[,\s]+", sel):
            if not part:
                continue
            if not part.isdigit():
                return "Couldn't read %r. Try `add 1,3`, `add all`, or `add no`." % part
            idx = int(part) - 1
            if not 0 <= idx < len(pending):
                return "No item %s — the list has %d." % (part, len(pending))
            chosen.append(idx)
    if not chosen:
        return "Nothing selected."

    picked = [pending[i] for i in sorted(set(chosen))]
    with open(CONFIRM_PROMPT) as f:
        prompt = f.read()
    prompt += "\n\n```json\n%s\n```\n" % json.dumps(picked, indent=2)
    result = run_claude(prompt)

    for p in picked:
        nao_audit.record("bridge", "wrote", why="confirmed by Ruben",
                         kind=p.get("kind"), title=describe(p))
    # Consume the whole list either way — stale numbering is how the wrong
    # thing gets written on a second `add`.
    write_json(PENDING_PATH, {"items": [], "at": now})
    return (result or "(no output)").strip()
