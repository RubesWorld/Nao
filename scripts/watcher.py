#!/usr/bin/env python3
"""
Nao watcher — hourly, silent by default, stateful.

Unlike the report-generator jobs, this one remembers what it has already
said. That memory is the entire difference between proactive and
repetitive: promise-deadline-monitor re-sent the same nudge every morning
with no escalation and no way to dismiss it.

Split of responsibilities:
  - retrieval is deterministic where possible (tana_client over HTTP to
    the local MCP), with `claude -p` as the fallback when parsing fails
  - this script does BOOKKEEPING (must be exact, so no LLM in the path)

State keys are bare node ids (the condition lives inside the entry).
Keying by condition:nodeId was a bug: a promise crossing from due-soon to
overdue changed key, which announced "Cleared" while starting a fresh
escalation ladder on the very day it became MORE urgent.

Exit codes: 0 = ran fine (silent or notified), 1 = collector failed.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nao_telegram import send as telegram_send  # noqa: E402
from tana_client import TanaClient              # noqa: E402

NAO = os.path.expanduser("~/Nao")
STATE_PATH = os.path.join(NAO, "state", "watcher.json")
LAST_BATCH_PATH = os.path.join(NAO, "state", "watcher-lastbatch.json")
PEOPLE_CACHE_PATH = os.path.join(NAO, "state", "watcher-people-cache.json")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")
COLLECT_PROMPT = os.path.join(NAO, "prompts", "watcher-collect.md")

MAX_ITEMS_PER_MESSAGE = 3   # a wall of alerts gets ignored wholesale
DUE_SOON_DAYS = 2
ESCALATE_AFTER_HOURS = 24
MAX_NOTIFICATIONS = 3       # then auto-snooze; silence beats nagging
AUTO_SNOOZE_DAYS = 7
COLLECT_TIMEOUT = 300
PEOPLE_REFRESH_HOURS = 20   # cadence data changes slowly; don't scan hourly
COLLECT_FAIL_PING_AT = 3    # consecutive failures before telling Ruben

KNOWN_CONDITIONS = ("promise_overdue", "promise_due_soon",
                    "person_cadence_overdue")

# Same mapping the relationship-review prompt documents.
CADENCE_DAYS = {
    "weekly": 7, "biweekly": 14, "bi-weekly": 14, "monthly": 30,
    "quarterly": 90, "twice a year": 180, "yearly": 365, "annually": 365,
}

# Field ids on #promise and #Person, from CLAUDE.md.
PROMISE_FIELDS = {"what": "gyC8IAnhSkk0", "who": "4je8YrsC3pgW",
                  "deadline": "nDVo67NvPODe", "status": "R4CiFnM0eZgx"}
PERSON_FIELDS = {"last interaction": "q5wo_UUohjlq", "cadence": "wVnOpgqJYQJT"}


def log(msg):
    # isoformat with colon offset — health-check.py parses these stamps
    # with fromisoformat, which pre-3.11 can't read a bare %z offset.
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
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
            state = json.load(f)
    except (ValueError, IOError) as e:
        # A corrupt state file would otherwise re-notify everything as new.
        log("state file unreadable (%s) — starting empty" % e)
        return {}
    return migrate_state(state)


def migrate_state(state):
    """Old keys were '<condition>:<nodeId>'; new keys are bare node ids."""
    for key in list(state):
        if key.startswith("_") or ":" not in key:
            continue
        cond, node_id = key.split(":", 1)
        if cond not in KNOWN_CONDITIONS:
            continue
        entry = state.pop(key)
        entry.setdefault("condition", cond)
        old = state.get(node_id)
        if old:
            # Same node tracked under two old keys — keep the longer history.
            entry["firstSeen"] = min(entry.get("firstSeen") or "9999",
                                     old.get("firstSeen") or "9999")
            entry["timesNotified"] = max(entry.get("timesNotified", 0),
                                         old.get("timesNotified", 0))
        state[node_id] = entry
    return state


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)   # atomic: a half-written state is worse than none


# ---------------------------------------------------------------------------
# Collection — HTTP first, claude -p fallback
# ---------------------------------------------------------------------------

def _first_date(value):
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return m.group(0) if m else None


def _walk_ids(obj, found):
    """Collect {id, name} pairs from arbitrarily shaped parsed JSON."""
    if isinstance(obj, dict):
        node_id = obj.get("id") or obj.get("nodeId")
        if isinstance(node_id, str) and node_id:
            found[node_id] = obj.get("name") or obj.get("title") or ""
        for v in obj.values():
            _walk_ids(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_ids(v, found)


def _search_ids(client, query):
    """search_nodes → {nodeId: name}. Raises if the result is not JSON we
    can trust — the caller falls back to the claude collector."""
    text = client.search_nodes(query)
    stripped = (text or "").strip()
    if not stripped or stripped in ("[]", "{}", "No results", "No results found."):
        return {}
    parsed = json.loads(stripped)   # ValueError → fallback, deliberately
    found = {}
    _walk_ids(parsed, found)
    if not found:
        raise RuntimeError("search returned content but no node ids parsed")
    return found


_VALUE_KEYS = ("value", "stringValue", "dateValue", "content", "text")


def _field_from_json(obj, label, field_id):
    """Walk parsed read_node JSON for an object identified by the field id
    (or exactly the field's display name) and return its value-ish key."""
    if isinstance(obj, dict):
        ident_id = str(obj.get("fieldId") or obj.get("attributeId") or "")
        ident_name = str(obj.get("name") or obj.get("label") or "").strip()
        if ident_id == field_id or ident_name.lower() == label.lower():
            for vk in _VALUE_KEYS:
                v = obj.get(vk)
                if isinstance(v, (str, int, float)) and str(v).strip():
                    return str(v).strip()
                if isinstance(v, list) and v and isinstance(v[0], str):
                    return v[0].strip()
        for v in obj.values():
            r = _field_from_json(v, label, field_id)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _field_from_json(v, label, field_id)
            if r is not None:
                return r
    return None


def _extract_fields(text, wanted):
    """Pull field values out of a read_node result.

    wanted = {output_key: (field_label, field_id)}. Tries JSON first, then
    'Label:: value' outline lines. Raises if nothing matches at all so the
    caller can fall back rather than silently returning empties.
    """
    out = {k: None for k in wanted}
    matched_any = False
    stripped = (text or "").strip()

    parsed = None
    if stripped.startswith(("{", "[")):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            parsed = None

    if parsed is not None:
        for key, (label, field_id) in wanted.items():
            value = _field_from_json(parsed, label, field_id)
            if value:
                out[key] = value
                matched_any = True
    else:
        for key, (label, field_id) in wanted.items():
            m = re.search(r"^\s*-?\s*%s\s*::\s*(.+)$" % re.escape(label),
                          text or "", re.IGNORECASE | re.MULTILINE)
            if m:
                out[key] = m.group(1).strip()
                matched_any = True

    if not matched_any:
        raise RuntimeError("no fields recognised in read_node output")
    return out


def collect_http(include_people):
    client = TanaClient()
    promises = []
    for status in ("Open", "In Progress"):
        query = {"and": [
            {"hasType": "CPJBjsqaUr6F"},
            {"field": {"fieldId": PROMISE_FIELDS["status"],
                       "stringValue": status}},
        ]}
        for node_id, name in _search_ids(client, query).items():
            fields = _extract_fields(client.read_node(node_id), {
                "what": ("What", PROMISE_FIELDS["what"]),
                "who": ("Who", PROMISE_FIELDS["who"]),
                "deadline": ("Deadline", PROMISE_FIELDS["deadline"]),
            })
            promises.append({
                "id": node_id,
                "what": fields["what"] or name or "(untitled promise)",
                "who": fields["who"],
                "deadline": _first_date(fields["deadline"]),
                "status": status,
            })

    people = []
    if include_people:
        for node_id, name in _search_ids(
                client, {"hasType": "cQ7tTJTcfs72"}).items():
            fields = _extract_fields(client.read_node(node_id), {
                "lastInteraction":
                    ("Last interaction", PERSON_FIELDS["last interaction"]),
                "cadence": ("Cadence", PERSON_FIELDS["cadence"]),
            })
            people.append({
                "id": node_id,
                "name": name or "(unnamed person)",
                "lastInteraction": _first_date(fields["lastInteraction"]),
                "cadence": fields["cadence"],
            })
    return {"promises": promises, "people": people}


def collect_claude(include_people):
    """Fallback: the original `claude -p` collector."""
    with open(COLLECT_PROMPT) as f:
        prompt = f.read()
    prompt += "\n\nINCLUDE_PEOPLE=%s\n" % ("yes" if include_people else "no")

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
    match = re.search(r"[\[{].*[\]}]", out, re.DOTALL)
    if not match:
        raise RuntimeError("no JSON in collector output: %r" % out[:300])
    data = json.loads(match.group(0))
    if isinstance(data, list):   # pre-people prompt shape
        data = {"promises": data, "people": []}
    data.setdefault("promises", [])
    data.setdefault("people", [])
    return data


def collect(include_people):
    try:
        data = collect_http(include_people)
        log("collector: http path ok (%d promises%s)" % (
            len(data["promises"]),
            ", %d people" % len(data["people"]) if include_people else ""))
        return data
    except Exception as e:
        log("collector: http path failed (%s) — falling back to claude" % e)
        return collect_claude(include_people)


def load_people_cache():
    try:
        with open(PEOPLE_CACHE_PATH) as f:
            return json.load(f)
    except (IOError, ValueError):
        return None


def save_people_cache(people, now):
    os.makedirs(os.path.dirname(PEOPLE_CACHE_PATH), exist_ok=True)
    tmp = PEOPLE_CACHE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"at": now.isoformat(), "people": people}, f, indent=2)
    os.replace(tmp, PEOPLE_CACHE_PATH)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(promises, people, today):
    """Return {nodeId: item} for everything currently tripping a condition."""
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
            # most overdue = most negative urgency = sorts first
            condition, urgency = "promise_overdue", days
        elif days <= DUE_SOON_DAYS:
            condition, urgency = "promise_due_soon", 1000 + days
        else:
            continue

        active[p["id"]] = {
            "condition": condition,
            "what": p.get("what") or "(untitled promise)",
            "who": p.get("who"),
            "deadline": deadline,
            "days": days,
            "urgency": urgency,
        }

    for person in people:
        cadence = (person.get("cadence") or "").strip().lower()
        days_allowed = CADENCE_DAYS.get(cadence)
        if not days_allowed:
            continue   # As-needed or unset: never auto-flag
        last = person.get("lastInteraction")
        if not last:
            continue   # no baseline to measure from
        try:
            last_date = datetime.strptime(last, "%Y-%m-%d").date()
        except ValueError:
            continue
        over = (today - last_date).days - days_allowed
        if over < 1:
            continue
        active[person["id"]] = {
            "condition": "person_cadence_overdue",
            "what": person.get("name") or "(unnamed person)",
            "who": None,
            "deadline": None,
            "days": over,
            "cadence": cadence,
            # People sort after all promise conditions; most overdue first.
            "urgency": 3000 - min(over, 900),
        }
    return active


def describe(item, times_notified):
    days = item["days"]
    what = item["what"]

    if item["condition"] == "person_cadence_overdue":
        head = ("Reach out: %s — %d day%s past %s cadence"
                % (what, days, "" if days == 1 else "s", item.get("cadence")))
    else:
        # Self-commitments carry Who = "Self"; "... for Self" reads badly.
        raw_who = (item.get("who") or "").strip()
        who = "" if raw_who.lower() in ("", "self", "ruben", "me") \
            else " for %s" % raw_who
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
        return head + "\n  ↳ third nudge — tap a button or reply `snooze 7d`, `done`, or `drop`"
    return head


def build_keyboard(n_items):
    """One row of buttons per alert item; numbered when there are several,
    so `done` can't accidentally clear the whole batch."""
    if n_items == 1:
        return [[("Snooze 7d", "w:snooze:0"), ("Done", "w:done:0"),
                 ("Drop", "w:drop:0")]]
    rows = []
    for i in range(n_items):
        rows.append([("✓ Done %d" % (i + 1), "w:done:%d" % i),
                     ("💤 %d" % (i + 1), "w:snooze:%d" % i),
                     ("✕ %d" % (i + 1), "w:drop:%d" % i)])
    return rows


def note_collect_failure(state):
    meta = state.setdefault("_meta", {})
    meta["collectFailures"] = meta.get("collectFailures", 0) + 1
    if meta["collectFailures"] >= COLLECT_FAIL_PING_AT \
            and not meta.get("failurePinged"):
        telegram_send("⚠️ Watcher: collector failed %d runs in a row — "
                      "promise tracking is blind. Check logs/tasks.log on "
                      "the mini." % meta["collectFailures"])
        meta["failurePinged"] = True
    save_state(state)


def main():
    load_env()
    now = datetime.now().astimezone()   # LOCAL time: deadlines are lived in
    today = now.date()                  # Ruben's timezone, not UTC's

    state = load_state()

    include_people = True
    cache = load_people_cache()
    if cache and cache.get("at"):
        try:
            age = now - datetime.fromisoformat(cache["at"])
            include_people = age > timedelta(hours=PEOPLE_REFRESH_HOURS)
        except ValueError:
            pass

    try:
        data = collect(include_people)
    except Exception as e:
        log("FAILED — %s" % e)
        note_collect_failure(state)
        return 1

    meta = state.setdefault("_meta", {})
    if meta.get("collectFailures"):
        meta["collectFailures"] = 0
        meta["failurePinged"] = False

    if include_people:
        save_people_cache(data["people"], now)
        people = data["people"]
    else:
        people = (cache or {}).get("people", [])

    active = evaluate(data["promises"], people, today)
    lines = []

    # --- Loop closing. Nothing in Nao used to notice a win. ---------------
    for key in list(state):
        if key.startswith("_") or key in active:
            continue
        done = state.pop(key)
        if done.get("timesNotified", 0) > 0 and not done.get("dropped"):
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
        # due-soon → overdue keeps the same key and ladder position now;
        # just record the new severity.
        entry["condition"] = item["condition"]

        if entry.get("dropped"):
            continue   # Ruben said stop tracking; stay stopped until resolved

        snoozed = entry.get("snoozedUntil")
        if snoozed and now < datetime.fromisoformat(snoozed).astimezone():
            continue

        last = entry.get("lastNotified")
        if last:
            last_dt = datetime.fromisoformat(last).astimezone()
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

    due.sort(key=lambda t: t[0])   # most urgent first
    overflow = max(0, len(due) - MAX_ITEMS_PER_MESSAGE)

    sent = []
    batch = due[:MAX_ITEMS_PER_MESSAGE]
    for i, (_, key, item, entry) in enumerate(batch):
        text = describe(item, entry["timesNotified"])
        if len(batch) > 1:
            text = "%d) %s" % (i + 1, text)
        lines.append(text)
        entry["timesNotified"] += 1
        entry["lastNotified"] = now.isoformat()
        sent.append({"key": key, "condition": item["condition"],
                     "what": item["what"]})

    # The Telegram bridge resolves `snooze` / `done` / `drop` (typed or
    # button) against this, so replies act on what was actually pushed.
    if sent:
        with open(LAST_BATCH_PATH, "w") as f:
            json.dump({"keys": [s["key"] for s in sent], "items": sent,
                       "at": now.isoformat()}, f, indent=2)

    if overflow:
        lines.append("(+%d more waiting)" % overflow)

    save_state(state)

    if not lines:
        log("quiet (%d open promises, %d active conditions)"
            % (len(data["promises"]), len(active)))
        return 0

    message = "\n".join(lines)
    print(message)
    # Only offer buttons when there is something they could act on — a
    # message that is purely "Cleared: x" has nothing to snooze.
    telegram_send(message, keyboard=build_keyboard(len(sent)) if sent else None)
    log("notified %d item(s)" % len(sent))
    return 0


if __name__ == "__main__":
    sys.exit(main())
