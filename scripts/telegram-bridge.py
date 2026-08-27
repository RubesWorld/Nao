#!/usr/bin/env python3
"""
Nao Telegram bridge — inbound commands from anywhere, executed on the mini.

Why the mini rather than a cloud dispatch: capability, not just latency.
This machine has tana-local on localhost, Monarch auth in its keyring, and
~/Nao/.env. A remote agent has none of those.

Why long polling rather than webhooks: no public URL, no tunnel, no inbound
port. The mini stays behind NAT exactly as it is today.

SECURITY — read before changing anything here.
    This executes text arriving from the internet on a machine holding
    Tana, financial credentials, and SSH keys. A bot token is a bearer
    credential: anyone who obtains it can message the bot. The chat-id
    allowlist below is the only thing between a leaked token and a shell.
    Do not weaken it, and do not reply to non-allowlisted senders — a
    reply confirms the bot is live.
"""

import json
import re
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nao_telegram import send as tg_send  # noqa: E402
import calendar_log                              # noqa: E402
import nao_audit                                 # noqa: E402
import interaction_note                          # noqa: E402

NAO = os.path.expanduser("~/Nao")
STATE_DIR = os.path.join(NAO, "state")
OFFSET_PATH = os.path.join(STATE_DIR, "telegram-offset.json")
TRANSCRIPT_PATH = os.path.join(STATE_DIR, "bridge-transcript.json")
WATCHER_STATE = os.path.join(STATE_DIR, "watcher.json")
LAST_BATCH = os.path.join(STATE_DIR, "watcher-lastbatch.json")
PENDING = os.path.join(STATE_DIR, "cleanup-pending.json")
PROPOSE_PROMPT = os.path.join(NAO, "prompts", "cleanup-propose.md")
EXECUTE_PROMPT = os.path.join(NAO, "prompts", "cleanup-execute.md")
CAL_PENDING = os.path.join(STATE_DIR, "calendar-pending.json")
CAL_SEEN = os.path.join(STATE_DIR, "calendar-seen.json")
CAL_LOG_PROMPT = os.path.join(NAO, "prompts", "calendar-log.md")
TRIAGE_PROPOSE = os.path.join(NAO, "prompts", "triage-propose.md")
TRIAGE_EXECUTE = os.path.join(NAO, "prompts", "triage-execute.md")
LOCK_PATH = os.path.join(STATE_DIR, "telegram-bridge.lock")
AUDIT_LOG = os.path.join(NAO, "logs", "telegram-bridge.log")

POLL_TIMEOUT = 30
CLAUDE_TIMEOUT = 600
RATE_LIMIT_PER_HOUR = 30
MAX_CONSECUTIVE_ERRORS = 20   # then exit and let launchd restart us
POLL_ERROR_AUDIT_AT = 3       # a dropped long poll is routine; three is a fault
MODEL = os.environ.get("NAO_BRIDGE_MODEL", "sonnet")

# Conversation continuity: freeform exchanges are remembered for follow-ups
# ("actually make it Friday") but reset after a quiet gap, so context stays
# bounded and stale threads don't leak into new topics.
TRANSCRIPT_IDLE_MINUTES = 30
TRANSCRIPT_MAX_EXCHANGES = 8
TRANSCRIPT_REPLY_CHARS = 1500   # stored reply excerpt; full reply still sent

# The plan doc's non-negotiable #2, finally honored: freeform text from the
# internet no longer runs with --dangerously-skip-permissions. Everything
# the bridge legitimately does goes through these tools. Override with
# NAO_BRIDGE_TOOLS (comma-separated) in .env; set it to * to restore the
# old skip-permissions behavior if the allowlist ever blocks something.
# The invariant this list defends: a leaked bot token must never equal a
# shell on the mini. No arbitrary Bash, no Write/Edit (Nao never modifies
# its own code over an internet channel), nothing that reads .env or keys.
# Within that line, capability is negotiable — widened 2026-08-20 by
# Ruben's call so the deployed allowlist never feels tight.
DEFAULT_ALLOWED_TOOLS = [
    "mcp__tana-local",      # all Tana tools — read AND write, Nao's memory
    "mcp__monarch-money",   # finance questions
    "Read",
    "Bash(date:*)",         # prompts need today's date
    "WebSearch",            # "look up X" from the phone
    "WebFetch",             # read a link Ruben sends
    # Nao's own repo-authored scripts, by explicit command — both the
    # cwd-relative and ~ forms, since Bash rules match the literal text:
    "Bash(python3 scripts/watcher.py:*)",
    "Bash(python3 ~/Nao/scripts/watcher.py:*)",
    "Bash(python3 scripts/health-check.py:*)",
    "Bash(python3 ~/Nao/scripts/health-check.py:*)",
]

# Model routing: explicit prefixes only — deterministic, no surprise bills.
# "!deep why is my savings rate flat" escalates; "!fast next payday" is a
# cheap quick answer. Everything else uses NAO_BRIDGE_MODEL (sonnet).
DEEP_MODEL = os.environ.get("NAO_BRIDGE_DEEP_MODEL", "opus")
FAST_MODEL = os.environ.get("NAO_BRIDGE_FAST_MODEL", "haiku")

# Voice notes: transcribed locally on the mini (see docs/voice-setup.md),
# then handled exactly like typed text. Caps keep a stray 40-minute memo
# from pinning the CPU.
VOICE_MAX_SECONDS = int(os.environ.get("NAO_VOICE_MAX_SECONDS", "300"))
WHISPER_MODEL = os.environ.get(
    "NAO_WHISPER_MODEL",
    os.path.join(NAO, "models", "ggml-base.en.bin"))

_recent = []   # command timestamps, for rate limiting


def audit(msg):
    """Separate from tasks.log on purpose: this is the forensic record."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    line = "[%s] %s" % (stamp, msg)
    with open(AUDIT_LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def load_env():
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


def api(token, method, params=None, timeout=40):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def send(token, chat_id, text, markup=None):
    """Delegates to the shared sender (correct chunking, buttons on the
    last chunk). markup = [[(label, callback_data), ...], ...]."""
    if not tg_send(text, keyboard=markup, token=token, chat_id=chat_id):
        audit("send failed (see stderr)")


class Typing:
    """Shows 'typing…' in the chat while work runs. Telegram's indicator
    expires after ~5 seconds, so a daemon thread refreshes it until the
    work finishes. Failures are swallowed — liveness UX must never break
    the command itself."""

    def __init__(self, token, chat_id):
        self.token, self.chat_id = token, chat_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self._stop.is_set():
            try:
                api(self.token, "sendChatAction",
                    {"chat_id": self.chat_id, "action": "typing"}, timeout=10)
            except Exception:
                pass
            self._stop.wait(4)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()


def route_model(text):
    """Explicit model prefixes. Returns (model_or_None, stripped_text) —
    None means the default NAO_BRIDGE_MODEL."""
    m = re.match(r"^!(deep|think)\b\s*", text, re.IGNORECASE)
    if m:
        return DEEP_MODEL, text[m.end():].strip()
    m = re.match(r"^!(fast|quick)\b\s*", text, re.IGNORECASE)
    if m:
        return FAST_MODEL, text[m.end():].strip()
    return None, text


# --------------------------------------------------------------------------
# Voice notes. Telegram delivers them as OGG/Opus; we transcribe LOCALLY on
# the mini (whisper.cpp) so audio never leaves the machine, then treat the
# text exactly like a typed message. Setup: docs/voice-setup.md. Until the
# tools are installed this degrades to a polite "not set up yet" reply.
# --------------------------------------------------------------------------

def download_voice(token, file_id, dest):
    resp = api(token, "getFile", {"file_id": file_id})
    file_path = (resp.get("result") or {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram getFile returned no path")
    url = "https://api.telegram.org/file/bot%s/%s" % (token, file_path)
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def transcribe(audio_path):
    """OGG in, text out. NAO_TRANSCRIBE_CMD ({file} placeholder) overrides
    the default ffmpeg + whisper-cli pipeline."""
    custom = os.environ.get("NAO_TRANSCRIBE_CMD")
    if custom:
        proc = subprocess.run(custom.replace("{file}", audio_path),
                              shell=True, capture_output=True, text=True,
                              timeout=300)
        if proc.returncode != 0:
            raise RuntimeError("transcribe command failed: %s"
                               % proc.stderr.strip()[:200])
        return proc.stdout.strip()

    ffmpeg = shutil.which("ffmpeg")
    whisper = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
    if not (ffmpeg and whisper and os.path.exists(WHISPER_MODEL)):
        raise RuntimeError("transcription isn't set up on the mini yet — "
                           "see docs/voice-setup.md")

    wav = audio_path + ".wav"
    try:
        subprocess.run([ffmpeg, "-y", "-i", audio_path,
                        "-ar", "16000", "-ac", "1", wav],
                       capture_output=True, timeout=60, check=True)
        proc = subprocess.run([whisper, "-m", WHISPER_MODEL, "-f", wav,
                               "-np", "-nt"],
                              capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise RuntimeError("whisper failed: %s" % proc.stderr.strip()[:200])
        return proc.stdout.strip()
    finally:
        if os.path.exists(wav):
            os.remove(wav)


def voice_to_text(token, voice):
    duration = voice.get("duration", 0)
    if duration > VOICE_MAX_SECONDS:
        raise RuntimeError("that's %ds of audio — cap is %ds. Send a "
                           "shorter note." % (duration, VOICE_MAX_SECONDS))
    ogg = os.path.join(STATE_DIR, "voice-inbox.ogg")
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        download_voice(token, voice["file_id"], ogg)
        text = transcribe(ogg)
    finally:
        if os.path.exists(ogg):
            os.remove(ogg)
    if not text:
        raise RuntimeError("transcription came back empty")
    return text


# A tap resolves to the same string a typed command would produce, so there
# is exactly one implementation of every action.
def callback_to_command(data):
    # Watcher buttons: numbered per alert item (w:done:0 = "done 1") so a
    # tap can never clear a whole multi-item batch by accident. The bare
    # legacy forms map to the un-numbered commands, which act only when the
    # batch is unambiguous.
    m = re.match(r"^w:(done|drop|snooze):(\d+)$", data)
    if m:
        verb, idx = m.group(1), int(m.group(2)) + 1
        return "snooze 7d %d" % idx if verb == "snooze" else "%s %d" % (verb, idx)
    if data == "w:snooze":
        return "snooze 7d"
    if data == "w:done":
        return "done"
    if data == "w:drop":
        return "drop"
    if data == "c:all":
        return "do all"
    if data == "c:no":
        return "no"
    if data.startswith("c:"):
        n = data[2:]
        return "do %s" % n if n.isdigit() else None
    if data == "cal:all":
        return "log all"
    if data == "cal:undo":
        return "undo"
    if data == "cal:no":
        # Deliberately not the bare `no` command: tapping Skip on a calendar
        # proposal must not also discard an unrelated pending cleanup.
        return "log no"
    return None


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


# --------------------------------------------------------------------------
# Built-in commands. Handled directly, never through Claude — replying to an
# alert should be instant, free, and impossible to misinterpret.
# --------------------------------------------------------------------------

# Cleanup and triage share one propose/confirm mechanism: a proposer prompt
# emits a JSON list, Python owns the numbering and the pending file, and the
# same `do 1,3` / buttons apply whichever proposal is currently pending.
PROPOSAL_KINDS = {
    "cleanup": {
        "execute_prompt": EXECUTE_PROMPT,
        "verbs": {"trash": "trash", "mark_outdated": "mark outdated",
                  "mark_done": "mark done", "amend": "amend"},
        "extra_tools": None,
        "empty": "Nothing to clean up in that scope.",
    },
    "triage": {
        "execute_prompt": TRIAGE_EXECUTE,
        "verbs": {"resource": "→ #resource", "idea": "→ #idea (Raw)",
                  "task": "→ #Task", "trash": "trash",
                  "keep": "leave in inbox"},
        # The execute prompt fetches saved articles to fill Key takeaways.
        # WebFetch is granted ONLY here — the fixed repo-authored prompt —
        # never to freeform internet-supplied text, which would open an
        # exfiltration channel.
        "extra_tools": ["WebFetch"],
        "empty": "Inbox is empty. Nothing to triage.",
    },
}


def propose(kind, prompt_path, prompt_suffix=""):
    """Read-only scan. Writes the numbered list Python owns, not the model."""
    with open(prompt_path) as f:
        prompt = f.read()
    prompt += prompt_suffix

    out = run_claude(prompt, model="sonnet")
    match = re.search(r"\[.*\]", out, re.DOTALL)
    if not match:
        return "Couldn't read a proposal list. Nothing changed.\n\n%s" % out[:500]
    try:
        items = json.loads(match.group(0))
    except ValueError as e:
        return "Proposal wasn't valid JSON (%s). Nothing changed." % e

    if not items:
        write_json(PENDING, {"kind": kind, "items": [],
                             "at": datetime.now(timezone.utc).isoformat()})
        return PROPOSAL_KINDS[kind]["empty"]

    items = items[:12]
    write_json(PENDING, {"kind": kind, "items": items,
                         "at": datetime.now(timezone.utc).isoformat()})

    verbs = PROPOSAL_KINDS[kind]["verbs"]
    lines = ["Proposed (nothing changed yet):"]
    for i, it in enumerate(items, 1):
        lines.append("%d. %s — %s" % (i, it.get("title", "?"),
                                      verbs.get(it.get("action"), it.get("action"))))
        note = it.get("reason") or it.get("note")
        if note:
            lines.append("     %s" % note)
        # An amend rewrites text Ruben has to live with, so show what it
        # would become. Approving a deletion blind loses a node; approving
        # an edit blind silently rewrites what Nao believes about him.
        if it.get("newText"):
            preview = it["newText"]
            if len(preview) > 220:
                preview = preview[:217] + "…"
            lines.append("     → %s" % preview)
    lines.append("")
    lines.append("or type `do 1,3` to pick specific ones")

    # Deliberately only bulk actions as buttons. Per-item buttons would need
    # stable numbering across partial applies AND a keyboard that survives a
    # tap — editMessageText strips it. Typing `do 1,3` handles the rarer
    # granular case without that complexity.
    return "\n".join(lines), [[("Apply all", "c:all"), ("Cancel", "c:no")]]


def propose_cleanup(scope):
    return propose("cleanup", PROPOSE_PROMPT,
                   "\n\n# Scope for this run\n\n%s\n" % (scope or "all"))


def propose_triage():
    return propose("triage", TRIAGE_PROPOSE)


def execute_cleanup(selection):
    stored = read_json(PENDING, {})
    pending = stored.get("items") or []
    # Pre-triage pending files carry no kind; they were always cleanup.
    kind = PROPOSAL_KINDS.get(stored.get("kind", "cleanup")) \
        or PROPOSAL_KINDS["cleanup"]
    if not pending:
        return "No pending proposal. Send `cleanup` or `triage` first."

    if selection.strip() in ("all", "*"):
        chosen = list(range(len(pending)))
    else:
        chosen = []
        for part in re.split(r"[,\s]+", selection.strip()):
            if not part:
                continue
            if not part.isdigit():
                return "Couldn't read %r. Try `do 1,3` or `do all`." % part
            idx = int(part) - 1
            if not 0 <= idx < len(pending):
                return "No item %s — the list has %d." % (part, len(pending))
            chosen.append(idx)
    if not chosen:
        return "Nothing selected."

    picked = [pending[i] for i in sorted(set(chosen))]
    with open(kind["execute_prompt"]) as f:
        prompt = f.read()
    prompt += "\n\n```json\n%s\n```\n" % json.dumps(picked, indent=2)

    audit("%s EXECUTE %d item(s): %s"
          % (stored.get("kind", "cleanup").upper(), len(picked),
             ", ".join(p.get("id", "?") for p in picked)))
    result = run_claude(prompt, model="sonnet",
                        extra_tools=kind["extra_tools"])

    # Consume the proposal either way — stale numbering is how the wrong
    # thing gets deleted on a second `do`.
    write_json(PENDING, {"items": [], "at": datetime.now(timezone.utc).isoformat()})
    return result or "(no output)"


def execute_calendar(selection):
    """Confirm calendar proposals from scripts/calendar-capture.py.

    The proposer writes; this applies. Nothing reaches Tana until Ruben has
    picked, which is the whole point — a calendar entry is a plan, and plans
    get cancelled.
    """
    sel = selection.strip().lower()
    pending = read_json(CAL_PENDING, {}).get("items") or []
    if not pending:
        return "No calendar proposals waiting."

    seen = read_json(CAL_SEEN, {})
    now = datetime.now(timezone.utc).isoformat()

    if sel in ("no", "none", "skip"):
        # Declining is not the same as ignoring: mark these so they never
        # come back, rather than letting the nightly run re-air them.
        for item in pending:
            eid = item.get("eventId")
            if eid:
                rec = seen.get(eid, {})
                rec.update({"outcome": "skipped", "at": now,
                            "title": item.get("title", "")})
                seen[eid] = rec
        write_json(CAL_SEEN, seen)
        write_json(CAL_PENDING, {"items": [], "at": now})
        return "Skipped %d — I won't raise them again." % len(pending)

    if sel in ("all", "*", ""):
        chosen = list(range(len(pending)))
    else:
        chosen = []
        for part in re.split(r"[,\s]+", sel):
            if not part:
                continue
            if not part.isdigit():
                return "Couldn't read %r. Try `log 1,3`, `log all`, or `no`." % part
            idx = int(part) - 1
            if not 0 <= idx < len(pending):
                return "No item %s — the list has %d." % (part, len(pending))
            chosen.append(idx)
    if not chosen:
        return "Nothing selected."

    picked = [pending[i] for i in sorted(set(chosen))]
    audit("CALENDAR LOG %d item(s): %s"
          % (len(picked), ", ".join(p.get("title", "?") for p in picked)))

    result, receipts = calendar_log.apply_items(
        picked, lambda text: run_claude(text, model="sonnet"))
    if receipts:
        calendar_log.save_undo(
            receipts, {i.get("eventId"): i.get("title", "") for i in picked})
        result = (result + "\n\nSend `undo` if any of that is wrong.").strip()

    # Only what the receipt actually reports is finished; anything the write
    # dropped stays pending so the next run can offer it again.
    written = {r.get("eventId") for r in receipts if r.get("nodeId")}
    for item in picked:
        eid = item.get("eventId")
        if eid and eid in written:
            rec = seen.get(eid, {})
            rec.update({"outcome": "logged", "at": now,
                        "title": item.get("title", "")})
            seen[eid] = rec
    write_json(CAL_SEEN, seen)

    # Consume the proposal either way — stale numbering is how the wrong
    # thing gets written on a second `log`. Anything not picked keeps its
    # "pending" record, so the nightly run gives it one more airing before
    # calendar-capture.py retires it.
    write_json(CAL_PENDING, {"items": [], "at": now})
    return result or "(no output)"


def load_batch():
    """The last watcher alert. Older lastbatch files carried only keys;
    synthesize items so both formats work."""
    batch = read_json(LAST_BATCH, {})
    items = batch.get("items")
    if not items:
        items = [{"key": k, "condition": "promise", "what": k}
                 for k in (batch.get("keys") or [])]
    return batch, items


def numbered(items):
    return "\n".join("%d. %s" % (i + 1, it.get("what", it["key"]))
                     for i, it in enumerate(items))


def pick(items, n):
    """n = 1-based item number, or None for 'the whole alert'. A bare
    command only resolves when the alert had exactly one item — `done` on
    a 3-item alert used to close all three in Tana."""
    if n is None:
        return items if len(items) == 1 else None
    return [items[n - 1]] if 1 <= n <= len(items) else []


def builtin(text):
    cmd = text.strip().lower()

    if cmd in ("help", "/help", "?"):
        return ("Nao bridge\n"
                "  snooze 7d [n] — mute alert (or just item n) for N days\n"
                "  done [n]      — mark handled; closes it in Tana\n"
                "  drop [n]      — stop tracking (Tana untouched)\n"
                "  status        — what the watcher is tracking\n"
                "  reset         — forget the current conversation thread\n"
                "  cleanup [facts|promises|schema|all]\n"
                "                — propose tidy-ups, changes nothing\n"
                "  triage        — propose routing for capture-inbox items\n"
                "                  (articles → #resource w/ takeaways, ideas,\n"
                "                  tasks); changes nothing until you confirm\n"
                "  do 1,3 / do all / no\n"
                "                — act on the last proposal\n"
                "  log 1,3 / log all / no\n"
                "                — log the calendar hangouts/trips proposed\n"
                "  undo / undo 1 — reverse the last calendar write\n"
                "  actions [n]   — what Nao wrote lately, and why\n"
                "  note …        — add detail to a logged hangout\n"
                "anything else is passed to Nao:\n"
                "  !deep …       — harder question, bigger model\n"
                "  !fast …       — quick lookup, cheap model\n"
                "  🎤 voice note  — transcribed on the mini, then handled "
                "as text")

    if cmd in ("reset", "/reset", "new topic"):
        write_json(TRANSCRIPT_PATH, {"exchanges": []})
        return "Fresh context — I've dropped the running conversation."

    if cmd == "cleanup" or cmd.startswith("cleanup "):
        return propose_cleanup(cmd[len("cleanup"):].strip())

    if cmd in ("triage", "/triage", "inbox"):
        return propose_triage()

    if cmd == "do" or cmd.startswith("do "):
        return execute_cleanup(cmd[len("do"):].strip())

    # Only claim `log` when what follows actually looks like a selection.
    # "log my workout" is a request for Nao, not an answer to a proposal.
    # Same guard as `log`: only claim `undo` when what follows is a
    # selector. "undo my last email" is a request for Nao, not for this.
    if cmd == "note" or cmd.startswith("note "):
        return interaction_note.add_note(
            text.strip()[len("note"):].strip(),
            lambda t: run_claude(t, model="sonnet"))

    # Same guard as log/undo: "actions on my calendar" is a question for Nao.
    if cmd == "actions" or (cmd.startswith("actions ")
                            and cmd[len("actions"):].strip().isdigit()):
        n = cmd[len("actions"):].strip()
        entries = nao_audit.read(int(n) if n.isdigit() else 8)
        if not entries:
            return "Nothing written yet."
        return "\n".join(nao_audit.describe(e) for e in reversed(entries))

    if cmd == "undo" or cmd.startswith("undo "):
        arg = cmd[len("undo"):].strip()
        if re.fullmatch(r"(all|\*|[\d,\s]*)", arg):
            return calendar_log.undo(arg)

    if cmd == "log" or cmd.startswith("log "):
        arg = cmd[len("log"):].strip()
        if re.fullmatch(r"(all|\*|no|none|skip|[\d,\s]*)", arg):
            return execute_calendar(arg)

    if cmd in ("no", "cancel", "nevermind", "never mind"):
        # A bare "no" may be answering either proposal, so clear both rather
        # than guess. Declining everything pending is never the wrong reading
        # of "no", and nothing here writes to Tana.
        replies = []
        stored = read_json(PENDING, {})
        if stored.get("items"):
            # PENDING is shared by cleanup and triage — name the right one.
            kind = stored.get("kind", "cleanup")
            write_json(PENDING, {"items": []})
            replies.append("Discarded the %s proposal. Nothing changed." % kind)
        if read_json(CAL_PENDING, {}).get("items"):
            replies.append(execute_calendar("no"))
        if replies:
            return "\n".join(replies)
        return None   # not answering a proposal — let Claude handle it

    if cmd == "status":
        state = read_json(WATCHER_STATE, {})
        tracked = {k: v for k, v in state.items() if not k.startswith("_")}
        if not tracked:
            return "Watcher is tracking nothing. All clear."
        out = ["Watcher is tracking %d item(s):" % len(tracked)]
        for k, v in sorted(tracked.items()):
            bits = ["  • %s" % v.get("what", k)]
            bits.append("notified %dx" % v.get("timesNotified", 0))
            if v.get("dropped"):
                bits.append("dropped")
            if v.get("snoozedUntil"):
                bits.append("snoozed until %s" % v["snoozedUntil"][:10])
            out.append(", ".join(bits))
        return "\n".join(out)

    # ---- watcher-alert replies: snooze / done / drop ----------------------

    m = re.match(r"^/?(snooze|done|drop)\b\s*(.*)$", cmd)
    if m:
        verb, rest = m.group(1), m.group(2).strip()
        batch, items = load_batch()
        if not items:
            return ("Nothing recent to act on — no alert has been sent yet, "
                    "or it was already handled.")

        at = batch.get("at")
        if at:
            try:
                age = datetime.now(timezone.utc) - \
                    datetime.fromisoformat(at).astimezone(timezone.utc)
                if age > timedelta(days=2):
                    return ("The last alert was %d days ago — too old to act "
                            "on blind. Send `status` to see what's tracked."
                            % age.days)
            except ValueError:
                pass

        # Parse "[7d] [n]" — duration first (snooze only), item number last.
        days, item_no = 7, None
        for part in rest.split():
            if re.fullmatch(r"\d+d", part):
                days = int(part[:-1])
            elif part.isdigit():
                if verb == "snooze" and "d" not in rest.split()[0] \
                        and part == rest.split()[0]:
                    days = int(part)          # legacy "snooze 7"
                else:
                    item_no = int(part)
            else:
                return "Couldn't read %r. Try `%s 1` or `snooze 7d 1`." \
                    % (part, verb)

        if verb == "snooze":
            chosen = items if item_no is None else pick(items, item_no)
            if not chosen:
                return "No item %d — the alert had %d." % (item_no, len(items))
            state = read_json(WATCHER_STATE, {})
            until = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            n = 0
            for it in chosen:
                if it["key"] in state:
                    state[it["key"]]["snoozedUntil"] = until
                    n += 1
            write_json(WATCHER_STATE, state)
            return "Snoozed %d item(s) for %d days." % (n, days)

        chosen = pick(items, item_no)
        if chosen is None:
            return ("That alert had %d items — which one?\n%s\n"
                    "Reply `%s 1` (or tap its button)."
                    % (len(items), numbered(items), verb))
        if not chosen:
            return "No item %d — the alert had %d." % (item_no, len(items))

        state = read_json(WATCHER_STATE, {})

        if verb == "drop":
            # Drop = "not doing this". Stop nagging, leave Tana untouched.
            # The flag must PERSIST: popping the entry just let the next
            # hourly run re-detect the same condition as brand new.
            n = 0
            for it in chosen:
                if it["key"] in state:
                    state[it["key"]]["dropped"] = True
                    n += 1
            write_json(WATCHER_STATE, state)
            return ("Dropped %d item(s) — I'll stay quiet about them until "
                    "they resolve.\nTana is unchanged; promises still read "
                    "Open there." % n)

        # Done = "I did it". Close the loop properly rather than just
        # forgetting, which is the whole point of Status + Closed existing.
        for it in chosen:
            state.pop(it["key"], None)
        write_json(WATCHER_STATE, state)

        promise_ids = [it["key"] for it in chosen
                       if it.get("condition", "").startswith("promise")]
        person_items = [it for it in chosen
                        if it.get("condition") == "person_cadence_overdue"]

        replies = []
        if promise_ids:
            instruction = (
                "Mark these #promise nodes complete in Tana workspace "
                "drg2JUfK3f-A.\n"
                "For EACH node id below: set Status (R4CiFnM0eZgx) to Done, "
                "and set Closed (tfAT2tfpG0gi) to today's date in YYYY-MM-DD "
                "(get it with `date +%Y-%m-%d`).\n"
                "Touch nothing else. Reply with one short line per node, "
                "nothing more.\n\n"
                + "\n".join("- %s" % n for n in promise_ids))
            audit("DONE -> closing promises in Tana: %s" % ", ".join(promise_ids))
            replies.append(run_claude(instruction, model="sonnet"))
        if person_items:
            instruction = (
                "In Tana workspace drg2JUfK3f-A, set the Last interaction "
                "field (q5wo_UUohjlq) to today's date in YYYY-MM-DD (get it "
                "with `date +%Y-%m-%d`) on EACH of these #Person nodes.\n"
                "Touch nothing else. Reply with one short line per node.\n\n"
                + "\n".join("- %s (%s)" % (it["key"], it.get("what", ""))
                            for it in person_items))
            audit("DONE -> updating Last interaction: %s"
                  % ", ".join(it["key"] for it in person_items))
            replies.append(run_claude(instruction, model="sonnet"))
            replies.append("Tip: `/interaction` in Cowork captures the "
                           "detail too, if there's any worth keeping.")

        return "Cleared %d item(s).\n%s" % (len(chosen), "\n".join(replies)) \
            if replies else "Cleared %d item(s)." % len(chosen)

    return None


def allowed_tools():
    raw = os.environ.get("NAO_BRIDGE_TOOLS", "").strip()
    if raw == "*":
        return None   # explicit escape hatch: old skip-permissions behavior
    if raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    return DEFAULT_ALLOWED_TOOLS


def run_claude(text, model=None, extra_tools=None):
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
    cmd = ["claude", "-p", "--model", model or MODEL, "--output-format", "text"]
    tools = allowed_tools()
    if tools is None:
        cmd.append("--dangerously-skip-permissions")
    else:
        cmd.append("--allowedTools")
        # extra_tools widen ONE fixed-prompt invocation (e.g. WebFetch for
        # triage enrichment) — never the freeform path.
        cmd.extend(tools + (extra_tools or []))
    try:
        proc = subprocess.run(
            cmd, input=text, capture_output=True, text=True,
            cwd=NAO, env=env, timeout=CLAUDE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return "Timed out after %d minutes." % (CLAUDE_TIMEOUT // 60)
    if proc.returncode != 0:
        return "Failed (exit %d): %s" % (proc.returncode, proc.stderr.strip()[:500])
    return proc.stdout.strip()


# --------------------------------------------------------------------------
# Conversation continuity. Each `claude -p` is stateless, so "actually make
# it Friday" used to land in a fresh session with no idea what "it" was.
# A rolling on-disk transcript gives freeform messages short-term memory,
# bounded by count and reset after an idle gap (or an explicit `reset`).
# --------------------------------------------------------------------------

def transcript_context():
    ex = read_json(TRANSCRIPT_PATH, {}).get("exchanges") or []
    if not ex:
        return None
    try:
        last_at = datetime.fromisoformat(ex[-1]["at"])
        if datetime.now(timezone.utc) - last_at > \
                timedelta(minutes=TRANSCRIPT_IDLE_MINUTES):
            return None
    except (KeyError, ValueError):
        return None
    lines = []
    for e in ex[-TRANSCRIPT_MAX_EXCHANGES:]:
        lines.append("Ruben: %s" % e.get("user", ""))
        lines.append("Nao: %s" % e.get("nao", ""))
    return "\n".join(lines)


def transcript_append(user_text, reply):
    ex = read_json(TRANSCRIPT_PATH, {}).get("exchanges") or []
    now = datetime.now(timezone.utc)
    if ex:
        try:
            if now - datetime.fromisoformat(ex[-1]["at"]) > \
                    timedelta(minutes=TRANSCRIPT_IDLE_MINUTES):
                ex = []   # stale thread: start fresh rather than mix topics
        except (KeyError, ValueError):
            ex = []
    ex.append({"at": now.isoformat(), "user": user_text[:1000],
               "nao": (reply or "")[:TRANSCRIPT_REPLY_CHARS]})
    write_json(TRANSCRIPT_PATH, {"exchanges": ex[-TRANSCRIPT_MAX_EXCHANGES:]})


def rate_limited():
    now = time.time()
    _recent[:] = [t for t in _recent if now - t < 3600]
    if len(_recent) >= RATE_LIMIT_PER_HOUR:
        return True
    _recent.append(now)
    return False


def acquire_lock():
    """launchd KeepAlive plus a stale-tolerant lock: never two bridges."""
    if os.path.exists(LOCK_PATH):
        try:
            pid = int(open(LOCK_PATH).read().strip())
            os.kill(pid, 0)
            return False          # a live bridge already owns it
        except (ValueError, ProcessLookupError, PermissionError):
            pass                  # stale lock from a crash
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOCK_PATH, "w") as f:
        f.write(str(os.getpid()))
    return True


def main():
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    allowed = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()

    if not token or not allowed:
        audit("FATAL: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set")
        return 1
    if not acquire_lock():
        audit("another bridge instance is running — exiting")
        return 0

    offset = read_json(OFFSET_PATH, {}).get("offset", 0)
    tools = allowed_tools()
    audit("bridge started (model=%s, allowed_chat=%s, offset=%d, tools=%s)"
          % (MODEL, allowed, offset,
             "SKIP-PERMISSIONS" if tools is None else ",".join(tools)))
    consecutive_errors = 0
    poll_error_reported = False
    last_poll_error = ""

    while True:
        try:
            resp = api(token, "getUpdates",
                       {"offset": offset, "timeout": POLL_TIMEOUT},
                       timeout=POLL_TIMEOUT + 15)
            consecutive_errors = 0
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                # Not transient — the token was revoked or rotated. Exiting
                # lets launchd KeepAlive restart us, which re-reads .env and
                # picks up the new token. Retrying in-process would spin
                # forever on a stale credential, which is exactly what it did.
                audit("FATAL: auth rejected (HTTP %d) — exiting so launchd "
                      "restarts with fresh .env" % e.code)
                return 1
            consecutive_errors += 1
            last_poll_error = str(e)
        except Exception as e:
            consecutive_errors += 1
            last_poll_error = str(e)

        # A single failed long poll is weather, not news — Telegram drops the
        # connection routinely. Logging each one buried the command audit
        # trail under 673 lines of "read operation timed out" against 47 real
        # entries, which is the opposite of what an audit log is for. Same
        # ladder the relay check uses: speak once it persists, once on
        # recovery, silence in between.
        if consecutive_errors == POLL_ERROR_AUDIT_AT:
            audit("poll failing (%d in a row): %s"
                  % (consecutive_errors, last_poll_error))
            poll_error_reported = True
        elif not consecutive_errors and poll_error_reported:
            audit("polling recovered")
            poll_error_reported = False

        if consecutive_errors:
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                audit("FATAL: %d consecutive poll failures — exiting for restart"
                      % consecutive_errors)
                return 1
            time.sleep(min(5 * consecutive_errors, 60))   # back off, don't hammer
            continue

        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            # Persist BEFORE executing. A crash mid-command loses it rather
            # than replaying it on restart — for commands with side effects,
            # losing is the safer failure.
            write_json(OFFSET_PATH, {"offset": offset})

            # ---- button taps ------------------------------------------
            cq = update.get("callback_query")
            if cq:
                cq_msg = cq.get("message") or {}
                chat_id = str(cq_msg.get("chat", {}).get("id", ""))
                if chat_id != allowed:
                    audit("REJECTED callback chat_id=%s" % chat_id)
                    continue
                data = cq.get("data") or ""
                cmd = callback_to_command(data)
                audit("TAP %r -> %r" % (data, cmd))

                # Always answer, or the button spins forever on his phone.
                try:
                    api(token, "answerCallbackQuery",
                        {"callback_query_id": cq["id"],
                         "text": "working…" if cmd else "unknown button"})
                except Exception as e:
                    audit("answerCallbackQuery failed: %s" % e)
                if not cmd:
                    continue

                with Typing(token, chat_id):
                    result = builtin(cmd)
                if isinstance(result, tuple):
                    result = result[0]
                result = result or "(nothing to do)"

                # Strip the buttons so the same tap can't be replayed, and
                # record the outcome on the original message.
                try:
                    api(token, "editMessageText", {
                        "chat_id": chat_id,
                        "message_id": cq_msg.get("message_id"),
                        "text": ((cq_msg.get("text") or "")[:3500]
                                 + "\n\n— " + result[:500]),
                    })
                except Exception as e:
                    audit("editMessageText failed: %s" % e)
                    send(token, chat_id, result)
                continue

            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip()

            # ---- the security boundary --------------------------------
            if chat_id != allowed:
                audit("REJECTED chat_id=%s from=%r text=%r"
                      % (chat_id, msg.get("from", {}).get("username"), text[:80]))
                continue          # deliberately no reply

            # ---- voice notes: transcribe, then treat as typed ----------
            if not text and msg.get("voice"):
                try:
                    with Typing(token, chat_id):
                        text = voice_to_text(token, msg["voice"])
                    audit("VOICE %ds -> %r"
                          % (msg["voice"].get("duration", 0), text[:200]))
                    # Echo the transcript so a mishearing is obvious before
                    # the reply arrives.
                    send(token, chat_id, "🎤 %s" % text)
                except Exception as e:
                    audit("VOICE failed: %s" % e)
                    send(token, chat_id, "Couldn't transcribe that — %s" % e)
                    continue

            if not text:
                continue
            if rate_limited():
                audit("RATE LIMITED: %r" % text[:80])
                send(token, chat_id, "Rate limit hit (%d/hr). Try again shortly."
                     % RATE_LIMIT_PER_HOUR)
                continue

            audit("CMD %r" % text[:300])

            # Most builtins are instant, but cleanup/do call Claude and can
            # take a minute. A silent gap reads as broken, so ack those too.
            lowered = text.strip().lower()
            if (lowered.startswith(("cleanup", "triage", "do ", "log "))
                    or lowered.startswith("note ")
                    or lowered in ("do", "log", "undo", "note")):
                send(token, chat_id, "on it…")

            with Typing(token, chat_id):
                reply = builtin(text)
            if reply is not None:
                # builtins may return plain text or (text, inline keyboard)
                if isinstance(reply, tuple):
                    send(token, chat_id, reply[0], markup=reply[1])
                else:
                    send(token, chat_id, reply)
                continue

            # A silent multi-minute gap reads as broken; typing covers the
            # in-app view, "on it…" covers the lock screen.
            send(token, chat_id, "on it…")
            started = time.time()
            model_override, clean = route_model(text)
            context = transcript_context()
            prompt = clean if not context else (
                "Recent Telegram exchanges with Ruben (continue this "
                "conversation naturally — 'it'/'that' likely refer to it):\n"
                "%s\n\nRuben's new message:\n%s" % (context, clean))
            with Typing(token, chat_id):
                reply = run_claude(prompt, model=model_override)
            transcript_append(clean, reply)
            audit("done in %.1fs, %d chars%s%s"
                  % (time.time() - started, len(reply),
                     ", with context" if context else "",
                     ", model=%s" % model_override if model_override else ""))
            send(token, chat_id, reply)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
