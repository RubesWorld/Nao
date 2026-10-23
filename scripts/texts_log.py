#!/usr/bin/env python3
"""
Texts as contact — a real text conversation moves a Person's Last interaction.

Beeper (beeper_client.py) bridges Google Messages, WhatsApp and Telegram. Once
a day, texts-capture.py looks at yesterday's one-on-one chats and decides which
were a **real conversation**, not a one-liner, a verification code or a
broadcast. Only those count. The test is deterministic, on counts alone, and no
message text is read or stored:

    Ruben sent >= 3, they sent >= 3, and the thread changed hands >= 4 times

Calibrated on 2026-10-22's real traffic: it kept seven back-and-forths
(Chloe, Wyatt, Ashleigh, ...) and dropped one-way texts, short codes, bots and
a two-message "running late".

Who a chat belongs to is the risky part, so it is never guessed:
- a chat title that equals a Person's name exactly (normalised) is linked
  automatically;
- anything else is **proposed once** on Telegram (`link 1,3` / `link all` /
  `link no`): link to a likely Person ("Chris Wilson" → Christopher Wilson), or
  add as a new contact. Whatever he doesn't pick is remembered as ignored and
  never asked about again. Notification fatigue arrives by accumulation.

What gets written: Last interaction, moved forward only. No #interaction
node — a node per text thread would bury the real hangouts, and an empty one
is exactly what the end-of-day digest flags as thin. Every move is in
logs/actions.jsonl with both dates, which is the record.

Group chats are skipped for now: who in a group was actually talking to Ruben
is a harder question than it looks.

State:
  state/texts-people.json   chat id → {personId, name} or {ignore: true}
  state/texts-pending.json  the live proposal list (one at a time)
  state/texts-capture.json  last day processed, token-expiry warning
"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher

NAO = os.path.expanduser("~/Nao")
sys.path.insert(0, os.path.join(NAO, "scripts"))

import nao_audit  # noqa: E402

STATE = os.path.join(NAO, "state")
PEOPLE_PATH = os.path.join(STATE, "texts-people.json")
PENDING_PATH = os.path.join(STATE, "texts-pending.json")

PERSON_TAG = "cQ7tTJTcfs72"
LAST_INTERACTION = "q5wo_UUohjlq"
CONTEXT_FIELD = "G0JyrqEiSl3q"
HOME = "xAJR7-Msy1YZ"
WORKSPACE = "drg2JUfK3f-A"

MIN_EACH_SIDE = 3
MIN_TURNS = 4
MAX_PROPOSALS = 5
DAY_ROLLOVER_HOUR = 4   # same as the check-in: 1am texts belong to the day before

NETWORKS = {"gmessages": "Google Messages", "whatsapp": "WhatsApp",
            "telegram": "Telegram", "signal": "Signal"}
# Words that say how Ruben saved a contact, not who they are.
FILLER = {"my", "big", "lil", "little", "sister", "brother", "mom", "dad",
          "friend", "friends", "work", "the", "dr", "doctor", "s"}


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


# ---- conversations ----------------------------------------------------------

def day_window(day):
    """[04:00 local on day, 04:00 the next day) as UTC ISO strings."""
    start = datetime(day.year, day.month, day.day, DAY_ROLLOVER_HOUR).astimezone()
    end = start + timedelta(days=1)
    fmt = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt(start), fmt(end)


def is_conversation(msgs):
    msgs = [m for m in msgs if m.get("type") not in ("REACTION", "NOTICE")]
    mine = sum(1 for m in msgs if m.get("isSender"))
    theirs = len(msgs) - mine
    turns = sum(1 for a, b in zip(msgs, msgs[1:])
                if bool(a.get("isSender")) != bool(b.get("isSender")))
    stats = {"mine": mine, "theirs": theirs, "turns": turns}
    return (mine >= MIN_EACH_SIDE and theirs >= MIN_EACH_SIDE
            and turns >= MIN_TURNS), stats


def looks_like_a_name(title):
    """Phone numbers and short codes are never people worth asking about."""
    return bool(title) and not re.search(r"\d", title)


def conversations(beeper, day):
    """[(chat, stats)] for the real one-on-one conversations on `day`."""
    start, end = day_window(day)
    out = []
    for chat in beeper.chats_active_since(start):
        if chat.get("type") != "single":
            continue
        others = [p for p in chat.get("participants", {}).get("items", [])
                  if not p.get("isSelf")]
        if len(others) != 1 or not looks_like_a_name(chat.get("title")):
            continue
        ok, stats = is_conversation(beeper.messages(chat["id"], start, end))
        if ok:
            out.append((chat, stats))
    return out


# ---- matching chats to people -------------------------------------------------

def _tokens(name):
    words = re.findall(r"[a-z]+", (name or "").lower().replace("-", " "))
    return [w for w in words if w not in FILLER]


def _norm(name):
    return " ".join(re.findall(r"[a-z]+", (name or "").lower()))


def _token_score(a, b):
    if a == b:
        return 1.0
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
        return 0.9                                   # Chris / Christopher
    r = SequenceMatcher(None, a, b).ratio()
    return r if r >= 0.85 else 0.0                   # Gonzales / Gonzalez


def candidate(title, people):
    """(exact_person, likely_person) for a chat title. Never both.

    Exact means the whole normalised name matches one Person. Likely needs a
    first-name-ish match plus nothing contradicting it, and must be unique:
    two plausible Chrises is a question, not an answer.
    """
    norm = _norm(title)
    exact = [p for p in people if _norm(p["name"]) == norm]
    if len(exact) == 1:
        return exact[0], None
    tt = _tokens(title)
    if not tt:
        return None, None
    scored = []
    for p in people:
        pt = _tokens(p["name"])
        if not pt:
            continue
        first = _token_score(tt[0], pt[0])
        if len(tt) > 1 and len(pt) > 1:
            # First and last name must both agree; middle names are free
            # ("Chloe Lee Gonzales-Gray" is Chloe Gonzalez-Gray).
            last = max(_token_score(tt[-1], pt[-1]),
                       _token_score(tt[-2], pt[-2]) if len(tt) > 2 and len(pt) > 2 else 0)
            if first and last:
                scored.append((first + last, p))
        elif len(tt) == 1 and any(_token_score(tt[0], u) == 1.0 for u in pt):
            scored.append((0.5, p))                  # "Big Sister Ericah"
    scored.sort(key=lambda x: -x[0])
    if not scored or (len(scored) > 1 and scored[0][0] == scored[1][0]):
        return None, None
    return None, scored[0][1]


# ---- Tana ---------------------------------------------------------------------

def load_people(tana):
    raw = tana.search_nodes({"hasType": PERSON_TAG})
    nodes = json.loads((raw or "").strip() or "[]")
    return [{"id": n["id"], "name": n.get("name", "")} for n in nodes
            if n.get("id") and not n.get("inTrash")
            and len(n.get("name", "")) < 60]     # skips the FDA speaker-list note


def last_interaction(tana, person_id):
    """(raw, YYYY-MM-DD or None). Tana renders dates for people ("Yesterday",
    "Mon, Jun 1"), so the raw value is kept to tell unset from unparseable."""
    from watcher import _extract_fields, _first_date
    fields = _extract_fields(tana.read_node(person_id), {
        "li": ("Last interaction", LAST_INTERACTION)})
    return fields["li"], _first_date(fields["li"])


def move_last_interaction(tana, person, day_iso, why, actor):
    """Set Last interaction to day_iso if that is later. Returns True if moved.

    An existing date that can't be parsed is left alone: overwriting it could
    move the field backwards, which is the one direction it must never go.
    """
    raw, prior = last_interaction(tana, person["id"])
    if raw and not prior:
        raise RuntimeError("can't read Last interaction %r on %s"
                           % (raw, person["name"]))
    if prior and prior >= day_iso:
        return False
    tana.call_tool("set_field_content", {
        "nodeId": person["id"], "attributeId": LAST_INTERACTION,
        "content": day_iso})
    nao_audit.record(actor, "wrote", why=why, kind="last-interaction",
                     title=person["name"], nodeId=person["id"], auto=True,
                     changed={person["id"]: {"lastInteraction": [prior, day_iso]}})
    return True


def create_person(tana, name, network, day_iso):
    paste = ("- %s #[[^%s]]\n  - [[^%s]]:: Texts with Ruben on %s.\n"
             "  - [[^%s]]:: %s\n" % (name, PERSON_TAG, CONTEXT_FIELD, network,
                                     LAST_INTERACTION, day_iso))
    out = tana.call_tool("import_tana_paste",
                         {"parentNodeId": HOME, "content": paste})
    # Reply lists "Created nodes:\n- <id> ("<name>")"; the first is the Person.
    m = re.search(r"Created nodes:\s*\n-\s*([A-Za-z0-9_-]{8,})", out or "")
    return m.group(1) if m else None


# ---- proposals ------------------------------------------------------------------

def describe(p):
    where = p.get("network", "texts")
    if p.get("personId"):
        return "%s (%s) → %s?" % (p["title"], where, p["personName"])
    return "%s (%s) → add as a new contact?" % (p["title"], where)


def save_pending(items):
    write_json(PENDING_PATH, {"items": items[:MAX_PROPOSALS],
                              "at": datetime.now(timezone.utc).isoformat()})
    for p in items[:MAX_PROPOSALS]:
        nao_audit.record("texts-capture", "asked",
                         why="who a chat belongs to is never guessed",
                         kind="text-link", title=describe(p))
    return items[:MAX_PROPOSALS]


def has_pending():
    return bool(read_json(PENDING_PATH, {}).get("items"))


def confirm(selection, tana=None):
    """`link all` / `link 1,3` / `link no` from the bridge. No model involved:
    linking is bookkeeping, and the one write is a date."""
    sel = (selection or "").strip().lower()
    pending = read_json(PENDING_PATH, {}).get("items") or []
    if not pending:
        return "No text contacts waiting."
    if sel in ("no", "none", "skip"):
        chosen = []
    elif sel in ("all", "*", ""):
        chosen = list(range(len(pending)))
    else:
        chosen = []
        for part in re.split(r"[,\s]+", sel):
            if not part:
                continue
            if not part.isdigit():
                return "Couldn't read %r. Try `link 1,3`, `link all`, or `link no`." % part
            idx = int(part) - 1
            if not 0 <= idx < len(pending):
                return "No item %s — the list has %d." % (part, len(pending))
            chosen.append(idx)

    if chosen and tana is None:
        from tana_client import TanaClient
        tana = TanaClient()

    people = read_json(PEOPLE_PATH, {})
    lines, failed = [], []
    for i, p in enumerate(pending):
        key = p["chatID"]
        if i not in chosen:
            people[key] = {"ignore": True, "title": p["title"]}
            nao_audit.record("bridge", "skipped", why="not picked; won't ask again",
                             kind="text-link", title=describe(p))
            continue
        try:
            if p.get("personId"):
                person = {"id": p["personId"], "name": p["personName"]}
                moved = move_last_interaction(
                    tana, person, p["date"], "texted %s (confirmed link)" % p["title"],
                    "bridge")
                lines.append("✅ %s is %s%s" % (p["title"], person["name"],
                             " — Last interaction → %s" % p["date"] if moved else ""))
            else:
                pid = create_person(tana, p["title"], p.get("network", "texts"), p["date"])
                if not pid:
                    # Possibly created with an unreadable reply; retrying could
                    # duplicate them, so this one is not offered again.
                    lines.append("⚠️ Couldn't confirm %s was created — check Tana" % p["title"])
                    continue
                person = {"id": pid, "name": p["title"]}
                nao_audit.record("bridge", "wrote", why="new contact from texts, confirmed",
                                 kind="new-person", title=p["title"], nodeId=pid)
                lines.append("✅ Added %s (Last interaction %s)" % (p["title"], p["date"]))
            people[key] = {"personId": person["id"], "name": person["name"],
                           "title": p["title"]}
        except Exception as e:
            failed.append(p)
            lines.append("⚠️ %s failed (%s) — `link %d` to retry"
                         % (p["title"], str(e)[:80], len(failed)))
    write_json(PEOPLE_PATH, people)
    # Only failures stay pending, renumbered in the reply above.
    write_json(PENDING_PATH, {"items": failed,
                              "at": datetime.now(timezone.utc).isoformat()})
    skipped = len(pending) - len(chosen)
    if skipped:
        lines.append("Won't ask about %d other%s again." % (skipped, "" if skipped == 1 else "s"))
    return "\n".join(lines)
