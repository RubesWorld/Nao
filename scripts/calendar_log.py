#!/usr/bin/env python3
"""
Shared apply/undo for calendar proposals.

Both entry points need this: calendar-capture.py writes booking-backed items
on its own at 21:30, and the Telegram bridge writes whatever Ruben picks with
`log 1,3`. One implementation so the two cannot drift.

The asymmetry is deliberate. Writing needs judgement — resolving people,
composing a Context line, picking a trip Status — so it runs through
prompts/calendar-log.md. Undoing needs none: it is a list of node ids and
prior values, so it goes straight to tana-local over HTTP. Same split as the
watcher, and for the same reason: the reversal path is the one that has to
be exact, and an LLM in it is a liability rather than a help.

The receipt is what makes undo possible. calendar-log.md reports what it
actually wrote — node ids, and each Person's Last interaction *before* the
overwrite. Restoring means putting that date back, not clearing the field:
clearing would read as "never seen", which is a worse lie than the one being
reversed.
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

NAO = os.path.expanduser("~/Nao")
sys.path.insert(0, os.path.join(NAO, "scripts"))

import nao_audit  # noqa: E402

UNDO_PATH = os.path.join(NAO, "state", "calendar-undo.json")
SEEN_PATH = os.path.join(NAO, "state", "calendar-seen.json")
LOG_PROMPT = os.path.join(NAO, "prompts", "calendar-log.md")

# Past this, `undo` refuses rather than acting blind — same guard the bridge
# already applies to done/drop on a stale watcher alert.
UNDO_MAX_AGE_HOURS = 48

LAST_INTERACTION_FIELD = "q5wo_UUohjlq"


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


def split_receipt(text):
    """Return (human_text, receipts).

    The model prints readable lines and then a fenced JSON receipt. A missing
    or unparseable receipt is not fatal — the write already happened, and
    saying so without an undo beats claiming the whole thing failed.
    """
    if not text:
        return "", []
    m = re.search(r"```json\s*(\[.*?\])\s*```", text, re.DOTALL)
    if not m:
        m = re.search(r"(\[\s*\{.*\}\s*\])\s*$", text, re.DOTALL)
    if not m:
        return text.strip(), []
    try:
        receipts = json.loads(m.group(1))
    except ValueError:
        return text.strip(), []
    if not isinstance(receipts, list):
        return text.strip(), []
    human = (text[:m.start()] + text[m.end():]).strip()
    return human, receipts


def _why(item):
    """The grounds for writing this one, in a phrase — the field that makes
    the action log worth keeping."""
    bits = ["%s-backed" % (item.get("evidence") or "unrated")]
    people = [p for p in (item.get("people") or []) if p.get("id")]
    if people:
        bits.append("%s resolved" % ", ".join(p.get("name", "?") for p in people))
    elif item.get("kind") == "interaction":
        bits.append("nobody resolved")
    if item.get("reason"):
        bits.append(item["reason"])
    return "; ".join(bits)


def apply_items(items, run_claude, actor="bridge", auto=False):
    """Write items to Tana via calendar-log.md. Returns (human_text, receipts).

    Every write is recorded to the action log with the grounds for it, so a
    change made without asking can be checked afterwards rather than taken on
    trust.
    """
    with open(LOG_PROMPT) as f:
        prompt = f.read()
    prompt += "\n\n```json\n%s\n```\n" % json.dumps(items, indent=2)
    human, receipts = split_receipt(run_claude(prompt))

    by_event = {i.get("eventId"): i for i in items}
    written = set()
    for r in receipts:
        eid = r.get("eventId")
        src = by_event.get(eid, {})
        written.add(eid)
        changed = {p["id"]: {"lastInteraction": [p.get("priorLastInteraction"),
                                                 src.get("date")]}
                   for p in (r.get("people") or []) if p.get("id")}
        nao_audit.record(actor, "wrote", why=_why(src),
                         kind=r.get("kind"), nodeId=r.get("nodeId"),
                         title=src.get("title") or r.get("title"),
                         eventId=eid, auto=auto or None,
                         changed=changed or None)

    # Silence about a failure is the one thing an audit log cannot afford.
    for item in items:
        if item.get("eventId") not in written:
            nao_audit.record(actor, "failed", why=_why(item),
                             title=item.get("title"),
                             eventId=item.get("eventId"), auto=auto or None)
    return human, receipts


def save_undo(receipts, titles=None):
    """Replace the undo batch. Only ever one batch: `undo` always means the
    most recent write, which is the only one a person can reason about."""
    if not receipts:
        return
    titles = titles or {}
    for r in receipts:
        r.setdefault("title", titles.get(r.get("eventId"), r.get("eventId", "?")))
    write_json(UNDO_PATH, {"at": datetime.now(timezone.utc).isoformat(),
                           "items": receipts})


def load_undo():
    """Return (items, stale) — stale means older than the guard window."""
    data = read_json(UNDO_PATH, {})
    items = data.get("items") or []
    at = data.get("at")
    stale = False
    if at:
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(at)
            stale = age > timedelta(hours=UNDO_MAX_AGE_HOURS)
        except ValueError:
            pass
    return items, stale


def _restore_person(client, person, lines):
    prior = person.get("priorLastInteraction")
    pid = person.get("id")
    if not pid:
        return
    if person.get("createdByThisLog"):
        client.call_tool("trash_node", {"nodeId": pid})
        lines.append("   removed the Person node it created")
        return
    # Put the old date back. Clearing instead would read as "never seen",
    # which is further from the truth than the value being reversed.
    client.call_tool("set_field_content", {
        "nodeId": pid,
        "attributeId": LAST_INTERACTION_FIELD,
        "content": prior or "",
    })
    lines.append("   Last interaction restored to %s" % (prior or "empty"))


def undo(selection="all"):
    """Reverse the last write. Deterministic — no model in this path."""
    from tana_client import TanaClient

    items, stale = load_undo()
    if not items:
        return "Nothing to undo."
    if stale:
        return ("The last calendar write was over %d hours ago — too old to "
                "reverse blind. Remove it in Tana if it is wrong."
                % UNDO_MAX_AGE_HOURS)

    sel = (selection or "all").strip().lower()
    if sel in ("", "all", "*"):
        chosen = list(range(len(items)))
    else:
        chosen = []
        for part in re.split(r"[,\s]+", sel):
            if not part:
                continue
            if not part.isdigit():
                return "Couldn't read %r. Try `undo 1` or `undo all`." % part
            idx = int(part) - 1
            if not 0 <= idx < len(items):
                return "No item %s — the last write had %d." % (part, len(items))
            chosen.append(idx)

    client = TanaClient()
    seen = read_json(SEEN_PATH, {})
    now = datetime.now(timezone.utc).isoformat()
    lines, removed = [], []

    for idx in sorted(set(chosen)):
        item = items[idx]
        title = item.get("title") or item.get("eventId", "?")
        node_id = item.get("nodeId")
        try:
            if node_id:
                client.call_tool("trash_node", {"nodeId": node_id})
            entry_lines = []
            for person in item.get("people") or []:
                _restore_person(client, person, entry_lines)
            lines.append("↩︎ %s" % title)
            lines.extend(entry_lines)
            nao_audit.record("bridge", "undo",
                             why="reversed by Ruben",
                             title=title, nodeId=node_id,
                             eventId=item.get("eventId"),
                             restored={p.get("id"): p.get("priorLastInteraction")
                                       for p in (item.get("people") or [])
                                       if p.get("id")} or None)
        except Exception as e:
            lines.append("⚠️ %s — undo failed: %s" % (title, str(e)[:120]))
            continue

        # Declining after the fact is still declining: don't re-propose it.
        eid = item.get("eventId")
        if eid:
            rec = seen.get(eid, {})
            rec.update({"outcome": "skipped", "at": now, "title": title})
            seen[eid] = rec
        removed.append(idx)

    write_json(SEEN_PATH, seen)
    kept = [it for i, it in enumerate(items) if i not in removed]
    write_json(UNDO_PATH, {"at": now, "items": kept})

    if not lines:
        return "Nothing undone."
    return "\n".join(lines)
