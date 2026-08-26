#!/usr/bin/env python3
"""
`note …` — attach the detail the calendar could not know.

The calendar knows an evening happened and who was on the invite. It cannot
know how it went, what anyone said, or who actually showed up to a thing
whose title named a venue. So the auto-logger writes a skeleton, the
end-of-day digest notices the node is thin, and this is how the gap gets
filled — typed or spoken, without opening Tana.

Same split as everywhere else in Nao: **Python decides which node**, the model
decides what goes in it. Targeting is the part that must not be guessed —
attaching a note to the wrong hangout is the one failure that would make the
whole loop untrustworthy, and it is a question with a deterministic answer.
So the node is resolved here, from Tana, before the model is invoked at all.

Deliberately no undo state: this only fills empty fields and appends to full
ones, so it cannot destroy anything. Every write still lands in
logs/actions.jsonl, which is what makes it checkable after the fact.
"""

import json
import os
import re
import sys

NAO = os.path.expanduser("~/Nao")
sys.path.insert(0, os.path.join(NAO, "scripts"))

import nao_audit  # noqa: E402

NOTE_PROMPT = os.path.join(NAO, "prompts", "interaction-note.md")
INTERACTION_TAG = "1y3M8tt6ahGs"
RECENT_DAYS = 7

# Words too common to identify anyone — "note great chat" must not match a
# person called Chat.
_STOPWORDS = {"was", "with", "and", "the", "great", "good", "nice", "fun",
              "rough", "weird", "off", "really", "very", "had", "went",
              "talked", "about", "just", "note", "for", "her", "his",
              "they", "them", "him", "she", "him"}


def _client():
    from tana_client import TanaClient
    return TanaClient()


def _thin(body):
    """Thin = Nao wrote the skeleton and nobody has added the human part.

    Vibe and Their updates are the two fields only Ruben can supply, and the
    two the end-of-day digest checks when it nudges.
    """
    return not ("**Vibe**" in body or "**Their updates**" in body)


def _names_in(body):
    """Attendee names as rendered by read_node: [Name #Person](tana:id)."""
    return re.findall(r"\[([^\]#]+?)\s*#Person\]\(tana:", body)


def find_candidates(days=RECENT_DAYS, limit=15):
    """Recent interactions, newest first, each tagged with whether it's thin.

    Reads Tana rather than the action log on purpose: an interaction added by
    the /interaction skill or by hand is just as valid a target as one the
    auto-logger wrote, and only Tana knows about all of them.
    """
    client = _client()
    raw = client.search_nodes({"and": [{"hasType": INTERACTION_TAG},
                                       {"created": {"last": days}}]})
    try:
        nodes = json.loads((raw or "").strip() or "[]")
    except ValueError:
        return []

    out = []
    for node in nodes[:limit]:
        node_id = node.get("id")
        if not node_id:
            continue
        body = client.read_node(node_id) or ""
        out.append({
            "id": node_id,
            "title": node.get("name") or "",
            "created": node.get("created") or "",
            "thin": _thin(body),
            "people": _names_in(body),
        })
    out.sort(key=lambda c: c["created"], reverse=True)
    return out


def _mentions(candidate, lowered):
    """Did Ruben name this one? Matches an attendee's first name or a
    distinctive word from the title."""
    words = {w for w in re.findall(r"[a-z']+", candidate["title"].lower())
             if len(w) > 3 and w not in _STOPWORDS}
    for person in candidate["people"]:
        words.update(p.lower() for p in person.split() if len(p) > 2)
    return any(re.search(r"\b%s" % re.escape(w), lowered) for w in words)


def resolve_target(text, days=RECENT_DAYS):
    """Return (candidate, problem_message). Exactly one of the two is None."""
    candidates = find_candidates(days)
    if not candidates:
        return None, ("Nothing logged in the last %d days to add to." % days)

    lowered = text.lower()
    named = [c for c in candidates if _mentions(c, lowered)]

    if len(named) > 1:
        # He named something that matches more than one evening. Guessing
        # here is exactly the failure this function exists to avoid.
        listing = "\n".join("  • %s" % c["title"] for c in named[:4])
        return None, ("That could be more than one:\n%s\nWhich?" % listing)
    if len(named) == 1:
        return named[0], None

    # If the message opens by naming something and nothing matched, he meant
    # a specific evening that is not here — quietly attaching to whatever is
    # newest would write the right detail onto the wrong night.
    lead = re.match(r"[a-z']+", lowered)
    if lead and lead.group(0) not in _STOPWORDS:
        listing = "\n".join("  • %s" % c["title"] for c in candidates[:3])
        return None, ("No recent interaction matches \"%s\". Recent ones:\n%s"
                      % (lead.group(0), listing))

    thin = [c for c in candidates if c["thin"]]
    if not thin:
        listing = "\n".join("  • %s" % c["title"] for c in candidates[:3])
        return None, ("Nothing recent looks unfinished. Did you mean one of "
                      "these?\n%s" % listing)
    return thin[0], None


def add_note(text, run_claude, days=RECENT_DAYS):
    """Resolve the node, then let the model fill it in."""
    text = (text or "").strip()
    if not text:
        return "Say what to add — e.g. `note Chloe was great, she's moving to LA`."

    target, problem = resolve_target(text, days)
    if problem:
        return problem

    with open(NOTE_PROMPT) as f:
        prompt = f.read()
    prompt += "\n\n```json\n%s\n```\n" % json.dumps(
        {"nodeId": target["id"], "title": target["title"],
         "currentAttendees": target["people"], "text": text}, indent=2)

    out = run_claude(prompt)
    human, receipt = _split_receipt(out)

    nao_audit.record("note", "wrote",
                     why="detail added by Ruben: %s" % text[:120],
                     nodeId=target["id"], title=target["title"],
                     kind="interaction",
                     set=(receipt or {}).get("set"),
                     flags=(receipt or {}).get("flags"))
    return human or "(no output)"


def _split_receipt(text):
    if not text:
        return "", None
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not m:
        return text.strip(), None
    try:
        receipt = json.loads(m.group(1))
    except ValueError:
        return text.strip(), None
    return (text[:m.start()] + text[m.end():]).strip(), receipt


if __name__ == "__main__":
    for c in find_candidates():
        print("%s  %-40s thin=%-5s %s"
              % (c["created"][:10], c["title"][:40], c["thin"],
                 ", ".join(c["people"])))
