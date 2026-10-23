# Dev feed newsletter — a daily re-entry email

**Status:** 🔨 in progress. Step 1 done 2026-10-17; step 4 (next up) next.
**Pointer from:** `blueprint.md`, roadmap item 11.

## Why

Context switching is the expensive part of running several projects, and with
ADHD it is the part most likely to stop work entirely. A list of what happened
doesn't help much. What helps is a **re-entry point**: where you were, and the
one next thing. The dev feed already collects almost everything needed; what's
missing is turning it into something a person reads, and delivering it.

## What exists today

- `scripts/devfeed.py` (launchd `com.nao.devfeed`, every 5 min): deterministic,
  no LLM, no secrets. Writes `devfeed/feed.json` with commits, merged PRs, open
  PRs, in-progress branches and the AI-Factory board, for every active repo.
- `devfeed/index.html`, served on Tailscale port 8300 (`com.nao.devfeed-server`).
- `end-of-day-digest` (6 PM): Tana-focused memory keeping. A different job;
  this plan doesn't replace it.

## Shape of the email

- **Morning, not evening.** The pain point is restarting, so it lands before
  the first sit-down (default 08:00 local). The evening digest stays as memory.
- **One card per active project** (pushed to, or with open work, in the last
  7 days):
  - **Where you left off:** the last commit, or the PLAN.md slice in progress
  - **Next action:** one line, the first unticked slice or the PR waiting on you
  - **Waiting on you:** PRs to review, spec questions (`spec:needs-answers`),
    `needs-human` cards
- **While you were away:** what the factory did since the last email (specs
  drafted, PRs opened, jobs stopped and why).
- **Next up (building blocks):** per repo, which card to build next and why,
  judged by what it unblocks rather than how appealing the feature is. See
  the section below.
- **Short by design.** Quiet repos aren't listed. No stats. If nothing needs
  you, the whole email is one line saying so.

## Next up: building-block recommendations

Feature value is the owner's call, and the Ready column order already
expresses it. What's hard to see from the board is **structure**: which card
is a foundation others stand on, and which cards will collide. The digest
answers "what should go next so the rest gets easier", per repo.

**Inputs** (all already on the board since 2026-10-17, when the spec runner
started writing them into every spec):
- `## Depends on`: explicit edges between cards
- `## Touches`: the files and directories each spec changes
- status, `size:*`, `risk:*`, `needs-human`, open questions
- open PRs and in-progress branches, from the existing collector

**How it ranks** (deterministic, no LLM needed):
1. **Unblocks the most.** Count the cards that depend on it, directly or
   through a chain. A card that three others wait on beats a standalone one.
2. **Foundation-ness.** Shared paths that many specs touch (schema and
   migrations, auth, shared components, the data layer) mark a card as
   groundwork. Building it first means the others rebase onto it once,
   instead of colliding with each other.
3. **Ready to go.** Its dependencies are merged, there are no open questions
   and no `needs-human`. A blocked card is listed by what it's waiting on,
   never recommended.
4. **Cheap first on ties.** Size s before m. `risk:*` cards are never
   auto-recommended to the factory; they show as "needs you".

**Output, per repo, three lines at most:**
- **Build next:** #N, with the reason (for example "unblocks #12 and #15;
  lays the `connections` table they both read")
- **Don't run together:** pairs in Ready or In Progress whose Touches
  overlap, so they shouldn't be built in parallel
- **Backlog cluster:** when several backlog ideas sit on the same missing
  foundation, name it as the one to promote and spec first. Backlog cards
  have no Touches yet, so this part is an optional LLM pass (layer 2) that
  groups backlog titles by the code they'd need.

**Where it's used:**
- the morning email and the dashboard
- the factory, later and optionally: the build runner takes Ready cards in
  board order, so the recommendation stays advice. The owner drags the card
  up. An "auto-order Ready by building blocks" mode can come once the
  recommendations have proven sensible for a few weeks.

**Open source:** generic, as long as the field names are configurable
(`depends_on_heading`, `touches_heading`). The ranking belongs upstream in
`devfeed` as part of the GitHub Projects board source.

## Architecture (three layers, so it can be open sourced)

1. **Collector**: today's `devfeed.py`, generalised. Sources are pluggable:
   `github` (commits, PRs, branches) is core; `ai-factory-board` and `plan-md`
   (read PLAN.md from local checkouts) are optional sources.
2. **Summarizer (optional)**: one LLM pass over the feed plus PLAN.md files,
   writing the "where you left off / next action" lines. Without an API key it
   falls back to a plain, non-AI version built from the same data.
3. **Delivery**: email first (SMTP, or a service like Resend, via config),
   Telegram second, and the existing dashboard. Each is a sink with the same
   input: the rendered digest.

## Nao vs the open-source version

Nao is already a public repo, so the split isn't public versus private. It's
**a generic tool** versus **Ruben's wiring**. The rule: **upstream-first, never
fork-and-patch.**

- **`RubesWorld/devfeed`** (public, MIT, created 2026-10-15) is the single source of truth for the
  collector, the summarizer, delivery, the dashboard and their tests. Nothing
  personal lives there: no repo lists, emails, Tana IDs or board numbers.
  Everything personal comes from a config file.
- **Nao consumes it as a pinned dependency**: a checkout of a release tag in
  `external/devfeed`, version in `config/devfeed.version`, kept in step by
  `scripts/devfeed-run.sh`. Nao keeps only:
  - its config (`config/devfeed.json`: which repos, display names, colours,
    the email address, schedule)
  - its launchd plists
  - personal plugins that make no sense for anyone else (anything touching
    Tana or Nao's memory)
- **Where a change goes:**
  - It would help anyone → change `devfeed`, tag a release, bump Nao's pin.
  - Only Ruben wants it → Nao config, or a Nao plugin through devfeed's
    plugin hook. If the hook can't express it, extend the hook upstream
    rather than patching around it.
  - Bug found while using it in Nao → fix upstream, then bump. Never fix it
    only in Nao.
- **Why pin instead of tracking main:** Nao's heartbeat must not break because
  of an unreleased change. Bumping the pin is a deliberate one-line PR.
- **The AI-Factory board source** can live upstream as an optional source
  ("GitHub Projects board"), since it only needs an owner and project number.
  That keeps Nao's side to config.

## Order of work

1. ✅ **Extract first** (2026-10-17). The repo already existed and was ahead of
   Nao's copy, so this was a switch: Nao runs `v0.1.0` from `external/devfeed`,
   and its own `scripts/devfeed.py` and `devfeed/index.html` are gone. The
   upstream collector produced the same repos, items, PRs and cards from Nao's
   config before switching.
2. **Generalise sources and config** (github core, board and PLAN.md optional).
3. **Build the digest renderer plus email sink** upstream, plain version first.
4. **Next-up ranking** (deterministic) in the digest and the dashboard.
5. **Add the optional summarizer**, including backlog clustering.
6. ✅ **Nao turns on the morning email** through config and a launchd plist (2026-10-22, devfeed v0.3.0).
7. README updates for the new parts, then announce. (MIT license, README and
   example config already exist upstream.)

Steps 1 and 2 before 3 matter: building the newsletter inside Nao first would
mean porting it later, which is exactly the drift this split is meant to avoid.

## Open questions

- Email transport: personal SMTP (Gmail app password) or a sending service?
- Send time, and whether weekends get one.
- Where PLAN.md is read from: local checkouts in `~/Code`, the factory work
  dirs, or the branch on GitHub (works without local clones).
