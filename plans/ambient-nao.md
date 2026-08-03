# Ambient Nao — Watcher + Telegram Bridge

Plan for making Nao notice things on its own and be reachable on demand,
without sitting at the mini.

Two components. They are useful separately and much better together: the
watcher gives Nao something worth saying, the bridge gives Ruben a way to
answer. A watcher with no reply channel is just more notifications.

---

## Why now

Every current scheduled job is a **report generator** — wake on a clock,
summarize a window, push it. None of them watch for a condition, none
escalate, none check whether Ruben acted.

The evidence is in the workspace. `relationship-review` flagged Wyatt on
Jul 12, Jul 19, and Aug 2 with near-identical text, never escalating after
two ignores, and never noticing that "grab a drink at home" stopped being
possible when Ruben moved out. `weekly-review` flagged the stale
"shares a 2-bedroom" fact on Jul 26, then dropped it. Both systems saw
something and neither followed through.

The plumbing for the fix already exists: `run-task.sh` suppresses empty
output and only sends Telegram when there is content. A job that stays
silent 95% of the time already costs nothing.

---

## Component A — The Watcher

One job, hourly, silent unless a condition trips.

### What makes it different from the existing jobs

**Threshold-triggered, not calendar-triggered.** It does not report on a
schedule; it checks on a schedule and speaks on a change.

**Stateful.** It remembers what it has already said. This is the whole
difference between proactive and repetitive.

**Escalating.** A recommendation repeated verbatim three times trains
Ruben to ignore the channel — actively worse than saying nothing.

**Loop-closing.** When a flagged thing gets resolved, the watcher clears
its own state and says so once. Nothing today ever notices a win.

### State

`~/Nao/state/watcher.json`, one entry per condition *instance*:

```json
{
  "promise:abc123": {
    "condition": "promise_overdue",
    "firstSeen": "2026-08-01",
    "lastNotified": "2026-08-03",
    "timesNotified": 2,
    "status": "active",
    "snoozedUntil": null
  }
}
```

Key is `<condition>:<nodeId>` so the same promise is tracked across runs
rather than re-detected as new. Without this file the watcher is just
another report generator.

### Escalation ladder

| Notification | Behavior |
|---|---|
| 1st | State it plainly, once. |
| 2nd (≥24h later) | Note it is still open and how long since first flagged. |
| 3rd | Escalate AND offer an out: "still open — reply `snooze 7d`, `done`, or `drop`." |
| 4th+ | Do not send. Auto-snooze 7 days. Silence beats nagging. |

Never notify twice in one day for the same instance regardless of ladder
position.

### Conditions — start with ONE

Build `promise_overdue` first and ship it. Add conditions only after the
escalation and state machinery is proven, because that machinery is the
actual risk, not the checks.

**v1 — promises**
- `promise_overdue` — Status is Open and Deadline has passed
- `promise_due_soon` — Status is Open and Deadline within 48h

**Later candidates**, in rough order of value:
- `protocol_adherence_gap` — no `#health-dose` for an on-cycle protocol in
  N days (needs Health HQ)
- `fact_contradiction` — a `#fact` whose Last confirmed is stale AND which
  is contradicted by recent activity. This is the one that would have
  caught the address.
- `spending_threshold` — a category crossing its `#budget-baseline`
  mid-month rather than waiting for the scheduled check
- `person_cadence_overdue` — replaces the current relationship-review
  repetition with something that escalates and can be dismissed

### Rules

- **Silence is the default and the success case.** A quiet week means
  nothing needed attention, not that the watcher failed.
- **Never more than 3 items in one message.** If more trip at once, send
  the top 3 by urgency and note the count. A wall of alerts is ignored.
- **Write nothing to Tana.** The watcher reads and notifies. Anything that
  mutates Tana goes through a normal job or through Ruben.
- Hourly is arbitrary but fine — Tana has no outbound webhooks, so
  everything here is polling. For promises and adherence, hourly is
  indistinguishable from instant.

### Done when

- A promise past its deadline produces exactly one Telegram message
- The next hourly run sends nothing
- 24h later it sends an escalated message referencing the first
- Marking the promise Done in Tana produces one closing message, then
  silence
- Replying `snooze 7d` suppresses it for 7 days (requires Component B)

---

## Component B — Telegram Bridge

Inbound commands. Ask Nao to do something from anywhere; the mini does it.

### Why the mini and not Cowork dispatch

Not mainly speed, though it is faster — no cloud provisioning round trip.
The real reason is **capability**. The mini has `tana-local` on localhost,
Monarch auth in its keyring, and `~/Nao/.env`. A cloud dispatch has none
of those, so the financial and Tana-write jobs simply cannot run there.
The mini is always on. Use it.

### Long polling, not webhooks

`getUpdates` with a 30s long-poll timeout, run as a persistent daemon.

- No public URL, no tunnel, no inbound port, nothing exposed to the
  internet. The mini stays behind NAT exactly as it is now.
- Latency is 1–2s, which is imperceptible for this use.
- Webhooks would be marginally faster and require exposing the mini.
  Not worth it.

### Architecture

`~/Nao/scripts/telegram-bridge.sh` (or a small Python daemon), run by
`~/Library/LaunchAgents/com.nao.telegram-bridge.plist` with
`KeepAlive=true` so launchd restarts it on crash.

Loop:
1. `getUpdates?offset=<last+1>&timeout=30`
2. For each update: **reject anything whose `chat.id` is not the allowlisted
   `TELEGRAM_CHAT_ID`** — see Security
3. Acknowledge immediately ("on it…") so the channel does not look dead
4. Run `claude -p` from `~/Nao` so CLAUDE.md loads
5. Send the reply, chunked to Telegram's 4096-char limit
6. Persist the new offset

### Details that will bite

- **Offset persistence.** Store `last_update_id` on disk. Lose it and the
  daemon reprocesses the backlog on restart — replaying commands.
- **Concurrency.** One job at a time. A lockfile; queue or reject while
  busy. Do not let five `claude` processes race on Tana.
- **Long tasks.** A real request can take minutes. Ack first, then work,
  and stream nothing in between — a silent 3-minute gap reads as broken.
- **Chunking.** 4096 chars per message. `run-task.sh` currently truncates
  at 3500 for exactly this reason; the bridge should split rather than
  truncate.
- **Session continuity.** Each `claude -p` is a fresh session by default.
  Decide deliberately: `--continue` gives conversational follow-ups
  ("do the second one") at the cost of unbounded context growth. Suggest
  starting stateless, and adding `--continue` with an idle timeout only if
  the lack of it actually hurts.
- **Watcher replies.** `snooze 7d` / `done` / `drop` should be handled by
  the bridge directly against `watcher.json`, not by spawning Claude.
  Cheap, instant, and it cannot misinterpret.

### Done when

- A message from the allowlisted chat runs and replies
- A message from any other chat id is ignored and logged
- The daemon survives a crash (launchd restarts it) without replaying
  old commands
- A 4000+ character answer arrives split, not truncated
- Replying `snooze 7d` to a watcher alert suppresses it

---

## Security — read before building Component B

This is the part of the plan that deserves real thought.

**An inbound command channel is categorically different from a scheduled
job.** Every current job runs a prompt file Ruben wrote, with
`--dangerously-skip-permissions`. That is fine: the input is fixed and
trusted. The bridge executes *arbitrary text arriving from the internet*
on a machine holding Tana, Monarch auth, `.env`, and the SSH keys.

If the bot token leaks or the Telegram account is compromised, that is
arbitrary code execution on the mini.

Non-negotiables:

1. **Hard allowlist on `chat.id`.** A bot token is a bearer credential —
   anyone who obtains it can message the bot. The chat id check is the
   only thing standing between a leaked token and a shell. Reject and log
   everything else; never reply to non-allowlisted senders, since a reply
   confirms the bot is live.
2. **Do not reuse `--dangerously-skip-permissions` reflexively.** It is
   defensible for a fixed prompt file and much less so here. Prefer an
   explicit allowlist of tools the bridge may use.
3. **Log every inbound message and every command run**, to its own file,
   not mixed into `tasks.log`. If something goes wrong this is the
   forensic record.
4. **Rate limit.** N commands per hour, then refuse. Bounds the damage
   from a compromised account.
5. **Rotate the bot token** now that it is becoming an execution path
   rather than an outbound notification token.

None of this is a reason not to build it — it is a reason to build the
allowlist first and the features second.

---

## Sequencing

1. **Watcher, one condition (`promise_overdue`), no replies.** Proves the
   state file and the escalation ladder, which is the genuinely new
   machinery. Notifications are one-way for now.
2. **Telegram bridge, allowlist and logging first**, then command
   execution. Get the security boundary right while the surface is small.
3. **Wire `snooze` / `done` / `drop`** into the bridge against
   `watcher.json`. This is the point where the two components become one
   system.
4. **Add watcher conditions one at a time**, only after living with each
   for a week. The failure mode of this whole idea is notification fatigue,
   and it arrives by accumulation.

## Open questions

- Stateless `claude -p` per message, or `--continue` for follow-ups?
  Recommend stateless first.
- Should the bridge be allowed to write to Tana, or read-only until
  trusted? Read-only is the safer start and still useful.
- Does the watcher deserve its own Telegram bot separate from the
  outbound notifier, so alerting survives a bridge compromise?
