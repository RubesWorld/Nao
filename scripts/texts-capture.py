#!/usr/bin/env python3
"""
Nao texts capture — real text conversations, as communication.

Daily at 08:15, for the day before (04:00 → 04:00, like the check-in). Reads
one-on-one chats from Beeper, keeps only real conversations, and moves the
linked Person's **Last texted** forward (never Last interaction, which is for
seeing people). A chat not linked to anyone is proposed once on Telegram
(`link 1,3` / `link all` / `link no` / `link 2 Full Name`).

On Sundays it also sends the week: who he texted, on how many days, and
everyone he really texted who still isn't in Tana, as a fresh `link` list.

Policy and the conversation test live in texts_log.py. Deterministic Python
end to end: no model reads or classifies messages.

Catches up on missed days (mini asleep) up to CATCH_UP_DAYS back.
Exit codes: 0 = ran fine, 1 = Beeper or Tana unreachable.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

NAO = os.path.expanduser("~/Nao")
sys.path.insert(0, os.path.join(NAO, "scripts"))

import texts_log  # noqa: E402
from beeper_client import BeeperClient, TokenExpired, BASE  # noqa: E402
from nao_telegram import send  # noqa: E402

STATE_PATH = os.path.join(NAO, "state", "texts-capture.json")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")
CATCH_UP_DAYS = int(os.environ.get("NAO_TEXTS_CATCH_UP", "3"))  # 7 to seed a week
WARN_EXPIRY_DAYS = 3


def log(msg):
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with open(LOG_PATH, "a") as f:
        f.write("[%s] texts-capture: %s\n" % (stamp, msg))


def yesterday():
    now = datetime.now()
    if now.hour < texts_log.DAY_ROLLOVER_HOUR:
        now -= timedelta(days=1)
    return now.date() - timedelta(days=1)


def token_expiry(beeper):
    """Expiry date of the token, or None if Beeper won't say."""
    try:
        req = urllib.request.Request(
            BASE + "/oauth/introspect",
            data=urllib.parse.urlencode(
                {"token": beeper.auth.replace("Bearer ", "")}).encode(),
            headers={"Authorization": beeper.auth})
        with urllib.request.urlopen(req, timeout=10) as r:
            exp = json.load(r).get("exp")
        return date.fromtimestamp(exp) if exp else None
    except Exception:
        return None


def warn_expiry(beeper, state):
    exp = token_expiry(beeper)
    if not exp or (exp - date.today()).days > WARN_EXPIRY_DAYS:
        return
    if state.get("warnedExpiry") == exp.isoformat():
        return
    send("🔑 Beeper's token expires %s. Make a new one in Beeper → Settings → "
         "Developers with \"Sensitive actions\" unchecked, then replace it: "
         "`claude mcp remove beeper -s user` and `claude mcp add beeper "
         "http://localhost:23373/v0/mcp -t http -s user -H \"Authorization: "
         "Bearer <token>\"`." % exp.strftime("%b %-d"))
    state["warnedExpiry"] = exp.isoformat()


def run():
    from tana_client import TanaClient
    state = texts_log.read_json(STATE_PATH, {})
    beeper = BeeperClient()

    target = yesterday()
    last = state.get("lastDay")
    earliest = target - timedelta(days=CATCH_UP_DAYS - 1)
    first = max(date.fromisoformat(last) + timedelta(days=1), earliest) \
        if last else earliest
    days = [first + timedelta(days=i) for i in range((target - first).days + 1)]
    if not days:
        log("quiet (already did %s)" % last)
        return 0

    try:
        found = [(d, texts_log.conversations(beeper, d)) for d in days]
    except TokenExpired:
        log("beeper token rejected")
        send("🔑 Beeper rejected Nao's token, so texts aren't counting as "
             "contact. It has probably expired: make a new one in Beeper → "
             "Settings → Developers (\"Sensitive actions\" unchecked) and add "
             "it again.")
        return 1
    except Exception as e:
        log("beeper unreachable (%s)" % e)
        send("⚠️ Couldn't reach Beeper on the mini (%s), so yesterday's texts "
             "weren't counted. Is Beeper Desktop running?" % str(e)[:100])
        return 1

    try:
        tana = TanaClient()
        people = texts_log.load_people(tana)
    except Exception as e:
        log("tana unreachable (%s)" % e)
        return 1

    links = texts_log.read_json(texts_log.PEOPLE_PATH, {})
    pending = texts_log.read_json(texts_log.PENDING_PATH, {}).get("items") or []
    by_id = {p["id"]: p for p in people}
    by_title = {v["title"]: v for v in links.values() if v.get("personId")}
    moved, proposals, convo_count = [], [], 0

    for day, convos in found:
        day_iso = day.isoformat()
        history = []
        for chat, stats in convos:
            convo_count += 1
            network = texts_log.NETWORKS.get(chat.get("accountID", "").split(".")[0],
                                             chat.get("network") or "texts")
            link = links.get(chat["id"]) or {}
            if not link.get("personId") and chat["title"] in by_title:
                # Same contact on another network ("RayRay" on SMS and WhatsApp).
                link = dict(by_title[chat["title"]])
                links[chat["id"]] = link
            if not link.get("personId"):
                exact, likely = texts_log.candidate(chat["title"], people)
                if exact:
                    link = {"personId": exact["id"], "name": exact["name"],
                            "title": chat["title"]}
                    links[chat["id"]] = link
                elif not link.get("asked"):
                    # Asked once, daily. After that only Sunday brings it back.
                    links[chat["id"]] = {"asked": day_iso, "title": chat["title"]}
                    proposals.append({
                        "chatID": chat["id"], "title": chat["title"],
                        "network": network, "date": day_iso,
                        "personId": likely and likely["id"],
                        "personName": likely and likely["name"]})
            history.append({"chatID": chat["id"], "title": chat["title"],
                            "network": network})
            person = by_id.get(link.get("personId"))
            if not person:
                continue
            why = "real text conversation on %s (%d/%d msgs, %d turns)" % (
                network, stats["mine"], stats["theirs"], stats["turns"])
            try:
                if texts_log.move_last_texted(tana, person, day_iso, why,
                                              "texts-capture"):
                    moved.append(person["name"])
            except Exception as e:
                log("skipped %s (%s)" % (person["name"], e))
        texts_log.record_history(day_iso, history)

    texts_log.write_json(texts_log.PEOPLE_PATH, links)
    state["lastDay"] = target.isoformat()
    warn_expiry(beeper, state)
    texts_log.write_json(STATE_PATH, state)

    sunday = datetime.now().weekday() == 6
    new = []
    if sunday:
        new = weekly(target, links, by_id)
    elif proposals and not pending:
        # One live list at a time, so `link 2` always means what he saw.
        # Anything found while a list is unanswered waits for Sunday.
        new = texts_log.save_pending(proposals)
        lines = ["💬 Real text conversations with people I can't place yet:"]
        lines += ["%d. %s" % (i, texts_log.describe(p)) for i, p in enumerate(new, 1)]
        lines += ["", "`link all` / `link 1,3` / `link no` / `link 2 Full Name`"]
        send("\n".join(lines), [[("Link all", "tx:all"), ("Not now", "tx:no")]])

    log("%s: %d conversation(s), %d Last texted moved%s%s%s" % (
        ",".join(d.isoformat() for d in days), convo_count, len(moved),
        " (%s)" % ", ".join(moved) if moved else "",
        ", %d proposed" % len(new) if new else "",
        ", weekly sent" if sunday else ""))
    return 0


def weekly(end_day, links, by_id):
    """Sunday: who he texted this week, and who still isn't in Tana.

    The unknowns become the live `link` list, replacing any stale one, so the
    numbers match this message. Always sends: a week of texting with nobody
    is itself worth seeing, and it doubles as proof the job is alive.
    """
    texted, unknown = texts_log.week_summary(end_day, links)
    lines = ["💬 Texting this week"]
    if texted:
        lines += ["%s — %d day%s" % (n, d, "" if d == 1 else "s")
                  for n, d in texted[:12]]
    else:
        lines.append("No real conversations with anyone in Tana.")
    items = []
    if unknown:
        people = list(by_id.values())
        for u in unknown:
            _, likely = texts_log.candidate(u["title"], people)
            items.append(dict(u, personId=likely and likely["id"],
                              personName=likely and likely["name"]))
        items = texts_log.save_pending(items)
        lines += ["", "Texted this week, not linked to anyone in Tana yet:"]
        lines += ["%d. %s" % (i, texts_log.describe(p)) for i, p in enumerate(items, 1)]
        if len(unknown) > len(items):
            lines.append("…and %d more." % (len(unknown) - len(items)))
        lines += ["", "`link all` / `link 1,3` / `link 2 Full Name` / `link no`"]
        send("\n".join(lines), [[("Link all", "tx:all"), ("Not now", "tx:no")]])
    else:
        texts_log.write_json(texts_log.PENDING_PATH, {"items": []})
        send("\n".join(lines))
    return items


if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        sys.exit(130)
