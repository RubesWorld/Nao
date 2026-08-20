# Nao Blueprint — living document

**Origin:** the March 2026 build plan ("NAO — Persistent AI Assistant").
**Last audited:** 2026-08-20, against the repo, git history, and CLAUDE.md.

How to use this file:
- When something ships, changes, or gets rejected, update its **Status** line
  and add a row to the Decision Log at the bottom. Don't rewrite history —
  the point of a living document is that you can see what was planned, what
  was built, and why they differ.
- Schema details (supertag fields, IDs) live in **CLAUDE.md and Tana
  itself** — deliberately not duplicated here. A second copy would drift.
- Detailed sub-plans get their own file in `plans/` (see `ambient-nao.md`)
  and a pointer from here.

Status legend: ✅ done · 🔶 partial · ⏳ open · 🔁 superseded (built differently,
on purpose) · 🚫 rejected (considered, decided against)

---

## 1. What Nao is

Nao is a persistent AI assistant that uses Tana as its long-term memory
substrate, Claude as the acting brain, and scheduled tasks as its autonomous
heartbeat. It reads and writes its own structured memory, tracks promises
and decisions across sessions, and proactively surfaces context before it's
needed.

Not a chatbot with memory bolted on — an assistant with continuity, habits,
and environmental awareness.

*(Unchanged since March. Still the test every addition has to pass.)*

## 2. The stack — planned vs. as built

| Layer | Plan said | As built (Aug 2026) |
|---|---|---|
| Memory substrate | Tana | ✅ Tana, workspace `drg2JUfK3f-A` |
| Read/write bridge | Tana Local MCP | ✅ tana-local at 127.0.0.1:8262 — plus `scripts/tana_client.py` for deterministic no-LLM reads |
| Acting brain | Claude Code / Cowork | ✅ Cowork interactive; `claude -p` headless |
| Autonomous heartbeat | Cowork Scheduled Tasks | 🔁 **launchd on the Mac mini** — Cowork/cloud schedulers can't reach localhost Tana; the mini is the sole authoritative host |
| Mobile command layer | Claude Dispatch | 🔁 **Telegram bridge** (`scripts/telegram-bridge.py`) — the plan said Dispatch would replace the custom Telegram bot; the bot won because it pairs with watcher alerts, works from a watch, and runs on the always-on mini |
| Alerting | (optional Telegram) | ✅ Telegram is the primary channel; one sender, `scripts/nao_telegram.py` |
| Ambient conditions | (not in plan) | ✅ **the watcher** — stateful, escalating, dismissable; see `plans/ambient-nao.md` |
| Computer use | Cowork Computer Use | ✅ available; last-resort per CLAUDE.md decision rule; never for banking |
| Remote dev | Claude Code CLI + Channels + VPS | 🔁 Claude Code on the web + the bridge; no VPS (see Phase 6) |
| Communication search | Traul | ⏳ never installed (see Open items) |
| Calendar of record | (implicit) | ✅ Google Calendar (nycrar@gmail.com); headless access via `scripts/calendar-today.sh` (gcalcli) |
| Self-monitoring | (not in plan) | ✅ `scripts/health-check.py`, weekly |

## 3. Memory model

Unchanged and still accurate:

| Memory type | Tana implementation |
|---|---|
| Working | Claude's context window + current session |
| Episodic | #session-digest in daily notes |
| Semantic | #fact, #preference |
| Procedural | CLAUDE.md + Cowork global instructions |
| Prospective | #promise with deadlines (+ the watcher as the alarm) |
| Financial | #budget-pulse, #financial-goal, #card-strategy, #budget-baseline, #financial-account + Monarch MCP |
| Relational *(post-plan addition)* | #Person, #interaction, cadence tracking |
| Identity | NAO-INDEX + #fact Category=Personal |
| Retrieval | search_nodes + dashboard searches (UI-built only — see CLAUDE.md "Tana search nodes") |

## 4. Build phases — scorecard

### Phase 1 — Foundation ✅
Tana Local API + MCP + Claude integration. Done, load-bearing daily.

### Phase 2 — Schema ✅ (and outgrown)
All 11 planned supertags exist, plus seven the plan didn't have: #Person,
#interaction, #Task, #resource, #idea, #budget-baseline, #financial-account.
The relationship layer was entirely post-plan. NAO-INDEX exists; the plan's
faith in "live search nodes just work" did not survive contact — the rules
learned the hard way are in CLAUDE.md, and real overdue detection lives in
the watcher because Tana filters can't express "before today".

### Phase 3 — Instructions + MCP servers ✅ / 🚫
CLAUDE.md and Cowork globals: done and evolved well past the plan (memory
protocol, capture standards). Monarch MCP: done, authenticated on the mini.
The three utility MCPs — **Sequential Thinking, Markdownify, Context7 — were
never installed and are now formally rejected** (2026-08-20): native
extended thinking made the first redundant; built-in web fetch and the
already-installed Playwright MCP cover the second; the third is a dev-tool
with no assistant-stack role. Also: every attached MCP pays context-token
rent on every scheduled haiku run, and widens the bridge's attack surface.
Five months without them, never missed. Don't re-litigate without a
specific pain.

### Phase 4 — Heartbeat + Financial ✅ (architecture pivoted)
All scheduled tasks exist and run: morning-briefing, end-of-day-digest,
weekly-review, relationship-review, mid-week-budget-check,
payday-allocation-check, weekly-spending-digest, monthly-financial-closeout,
health-check. The pivot: launchd on the mini instead of Cowork scheduled
tasks (localhost Tana requirement). Dispatch → Telegram bridge (above).
Note: payday check runs the 1st/15th; the plan wanted the 2nd/16th (day
after payday, so the deposit has settled). Open question, low stakes.

### Phase 5 — Expand 🔶
- Promise Deadline Monitor: ✅ built, then 🔁 superseded by the watcher
  (stateful + escalating beats fire-every-2-hours).
- Weekly Review: ✅.
- **Pre-Meeting Context Prep: ⏳ never built** — was blocked on real
  calendar data, which `calendar-today.sh` finally provides (pending gcalcli
  OAuth). Build it as one morning pass over today's agenda, not the plan's
  every-30-minutes poll.
- **Traul (+ SMS Backup+): ⏳ never installed.** Unified comms search is
  still the gap the plan said it was. Re-scope before building: Cowork now
  has Gmail / Google Calendar / Krisp MCPs, which cover part of the promise.
- Claude Code Channels: 🔁 covered by the bridge (chat commands) + Claude
  Code on the web (remote dev).

### Phase 6 — VPS 🚫 (obsoleted, correctly)
Never provisioned. The plan's own Future Extensions predicted the better
answer: a dedicated always-on Mac mini — which is exactly what happened.
Claude Code on the web covers remote coding. A VPS today buys nothing.

## 5. Known open problems — where they stand

| Problem (from the plan) | Status |
|---|---|
| Contradiction tracking | 🔶 Weekly review does it retroactively; CLAUDE.md instructs in-session checks. Real-time `fact_contradiction` watching still open — the case that would have caught the stale address. Judgment-based, so it doesn't fit the no-LLM watcher; likely home is a sharper weekly-review step. |
| Stale memory | ✅ Last confirmed + 90-day scans + auto-update-on-reference rule in CLAUDE.md. |
| Token cost | ✅ Managed: haiku default, quiet-by-default prompts, people-cache in the watcher, no speculative MCPs. |
| Retrieval quality | ⏳ Structured-only search, no vector layer. The plan said evaluate after 2–3 weeks; it's been ~5 months. Verdict needed: does fuzzy recall ("that restaurant from last month") actually fail often enough to justify a semantic layer? If not, close this. |
| Session digest quality | ✅ Capture standards in CLAUDE.md; digests enumerate rather than summarize. |
| Monarch API stability | 🔶 Accepted risk, unofficial API. health-check + failure pings now make breakage visible instead of silent. |
| Budget category mapping | 🔶 #budget-baseline nodes must match Monarch category names; still convention-enforced only. |
| Financial data latency | ✅ Accepted; monthly close-out is the settled-truth snapshot. |

## 6. Deliberately skipped or superseded

- **Sequential Thinking / Markdownify / Context7 MCPs** — rejected 2026-08-20
  (see Phase 3).
- **VPS layer** — obsoleted by the mini + Claude Code on the web.
- **Claude Dispatch as mobile layer** — superseded by the Telegram bridge.
- **Slack MCP** — dropped deliberately (2026-06, "drop Slack MCP
  dependency" hardening commit); scheduled tasks must not depend on it.
- **Every-30-min pre-meeting polling** — rejected cadence; the feature
  itself is still wanted (Phase 5), just as a morning pass.
- **OpenClaw-class agent frameworks** for the messaging layer — rejected on
  security grounds: they want broad, always-on permissions on the machine
  that holds Tana, Monarch auth, and SSH keys. The bridge exists precisely
  to offer a narrow, audited, allowlisted surface instead. Convenience
  features get added to the bridge, not imported wholesale.

## 7. Open items — the actual roadmap

Rough priority order:

1. **Pre-Meeting Context Prep** (Phase 5 remnant, newly unblocked by
   calendar access). One morning task: read today's agenda, cross-reference
   #Person / #promise / #session-digest / #interaction, write prep briefs
   under the daily note. Quiet when the calendar is empty.
2. **Richer conversational access to Nao** (bridge UX): 🔶 mostly shipped
   2026-08-20 — typing indicator, voice-note transcription (local
   whisper.cpp, `docs/voice-setup.md`), `!deep`/`!fast` model routing.
   Remaining: deeper continuity via `--resume` sessions, only if the
   8-exchange transcript proves shallow in practice. Incremental bridge
   upgrades — not a framework swap (see Section 6).
3. **fact_contradiction detection** — sharpen the weekly review's
   contradiction step (compare recent #session-digest content against
   #fact/#preference nodes; propose `mark_outdated` via the existing
   cleanup flow rather than acting silently).
4. **Retrieval-quality verdict** (close it or add a semantic layer — decide
   from 5 months of lived experience, not speculation).
5. **Comms search** (Traul or MCP-based equivalent) — re-scope first.
6. **Notification feedback loop** — weekly-review reads watcher state:
   alerts sent vs done/snoozed/dropped; chronic snoozes mean a miscalibrated
   condition.
7. **Passive interaction capture** — propose #interaction nodes from
   calendar events with attendees (needs #1's calendar habit first);
   propose-confirm via the cleanup-style flow, never silent writes.
8. **Adopt Tana's hosted MCP (beta)** — confirmed 2026-08-20 from the docs:
   `https://app.tana.inc/mcp`, HTTP + OAuth, no desktop app required,
   **same toolset as the local server including reads** (search_nodes,
   read_node, get_children, schemas, plus all mutations). Beta, paid plan.
   This ends the localhost constraint *for interactive surfaces*:
   - **Do now (paid plan confirmed 2026-08-20):** add it as a claude.ai
     custom connector (Settings → Connectors → Add custom connector →
     `https://app.tana.inc/mcp`, complete OAuth) → the Claude mobile app,
     Cowork cloud sessions, and Claude Code web sessions can all reach
     Nao's memory. This is the real "talk to Nao from anywhere" surface;
     the Telegram bridge stays for watcher alerts, buttons, and push.
   - **Don't do yet: migrate the heartbeat.** The launchd jobs stay on the
     local server — it's free, fast, private, and the mini is still bound
     there anyway by Monarch keyring auth, whisper, and launchd itself.
     Also: OAuth grants in headless cron contexts are fragile, and a beta
     endpoint is the wrong foundation for the autonomous layer. Revisit
     when the hosted server leaves beta.
   - **Security:** the graph is now reachable from the internet through any
     OAuth-granted client. Review and prune grants periodically; a
     compromised connected account = graph access.
   (The write-only Input API remains relevant only for tokened, non-OAuth
   automation; the hosted MCP supersedes it for everything interactive.)
9. **Nao HQ — artifact front end** (planned 2026-08-20; the long-standing
   "no front end" gap). A claude.ai Artifact page declaring the `mcp`
   runtime capability calls the viewer's connectors with their credentials
   — so once the Tana hosted-MCP connector (item 8) is added, a private
   dashboard page can read the graph LIVE: open promises sorted by
   deadline with overdue flags, today's briefing, active projects + next
   actions, latest #budget-pulse (the scheduled jobs are already the ETL —
   no Monarch access needed from the page), people due for reach-out.
   Build order:
   1. Tana connector added on claude.ai (prerequisite, item 8)
   2. Fresh Claude Code web session with the connector attached — observe
      one real search_nodes/read_node round-trip (never ship guessed tool
      shapes), then build + publish
   3. v1 is READ-ONLY, deliberately — keeps sunk cost low while the
      commit-to-Tana question is open; the rendering layer is
      substrate-agnostic and only the thin data layer speaks Tana
   4. v2 (only after living with v1): action buttons — mark promise Done,
      snooze, quick capture via import_tana_paste
   Constraint: a page declaring `mcp` cannot be shared publicly (it is a
   viewer-consented credential grant) — correct for a personal cockpit.
10. Future extensions still parked: Gmail triage in the morning briefing,
    GitHub Actions cloud layer for non-Tana tasks, Govee signals, voice
    memo pipeline, #prospect BD layer.

## 8. Decision log

| Date | Decision |
|---|---|
| 2026-03 | Original blueprint written (Tana + Cowork + Dispatch + VPS + Traul). |
| 2026-04 | Scheduled tasks moved to launchd on the Mac mini; Cowork/cloud schedulers can't reach localhost Tana. Mini becomes the authoritative heartbeat host. |
| 2026-06 | Slack MCP dependency dropped from scheduled tasks. |
| 2026-07 | listing-monitor retired (move complete). promise-deadline-monitor retired in favor of the watcher. |
| 2026-08 | Ambient layer shipped: stateful watcher + Telegram bridge (`plans/ambient-nao.md`). Tana search-node rules documented after the TODAY HQ rebuild. |
| 2026-08-20 | Hardening PR (#1): watcher state keyed by node id, per-item alert actions, persistent drop, local-time deadlines, deterministic HTTP retrieval with LLM fallback, bridge tool allowlist + transcript continuity, one Telegram sender, run-task timeout/skip/failure pings, weekly health-check, calendar wrapper (Google Calendar = calendar of record). |
| 2026-08-20 | Sequential Thinking / Markdownify / Context7 MCPs formally rejected. VPS layer formally closed as obsoleted. Blueprint converted to this living document. |
| 2026-08-20 | Bridge conversational upgrades shipped: typing indicator, local voice-note transcription, explicit model routing. OpenClaw-class framework swap reconfirmed as rejected — features get added to the bridge instead. |
| 2026-08-20 | Tana's **hosted MCP server (beta)** confirmed from docs: `https://app.tana.inc/mcp`, OAuth, full local toolset **including reads**, no desktop app needed (beta, paid plan). Localhost constraint falls for interactive surfaces. Decision: adopt for claude.ai/mobile/Cowork as a connector; heartbeat stays on the local server until hosted leaves beta (see roadmap item 8). |
| 2026-08-20 | **Nao HQ front end planned** (roadmap item 9): a claude.ai Artifact with the `mcp` runtime capability as a live dashboard over the hosted Tana connector. v1 read-only by design while the commit-to-Tana question stays open; scheduled jobs double as the ETL layer, so no Monarch access is needed from the page. |
| 2026-08-20 | **Substrate question reopened, decision deferred.** Past Tana frustration largely = access friction (desktop-only, search-node pain), which the hosted MCP + connector + Nao HQ may remove. Experiment: live with the new access for 2–4 weeks, then decide. Keep-Tana signals: memory retrieval works through the new surfaces and direct-Tana visits stop feeling necessary. Leave-Tana signals: still fighting the tool with full access, or paying for features Nao alone uses. Every access path already goes through a thin tool layer (MCP tools, tana_client), so a future migration is tractable either way — no need to decide from old frustration. |
