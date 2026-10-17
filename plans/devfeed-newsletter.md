# Dev feed newsletter — a daily re-entry email

**Status:** ⏳ planned (2026-10-16). Not started.
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
- **Short by design.** Quiet repos aren't listed. No stats. If nothing needs
  you, the whole email is one line saying so.

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

- **New repo `RubesWorld/devfeed`** is the single source of truth for the
  collector, the summarizer, delivery, the dashboard and their tests. Nothing
  personal lives there: no repo lists, emails, Tana IDs or board numbers.
  Everything personal comes from a config file.
- **Nao consumes it as a pinned dependency**, for example
  `pip install git+https://github.com/RubesWorld/devfeed@v0.3.0` into a venv,
  or a pinned checkout under `external/`. Nao keeps only:
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

1. **Extract first.** Move `devfeed.py`, `index.html` and their tests into
   `RubesWorld/devfeed` with no behaviour change, and have Nao run it from the
   pinned version. The feed and dashboard must look identical afterwards.
2. **Generalise sources and config** (github core, board and PLAN.md optional).
3. **Build the digest renderer plus email sink** upstream, plain version first.
4. **Add the optional summarizer.**
5. **Nao turns on the morning email** through config and a launchd plist.
6. README, license (MIT or Apache-2.0), example config, then announce.

Steps 1 and 2 before 3 matter: building the newsletter inside Nao first would
mean porting it later, which is exactly the drift this split is meant to avoid.

## Open questions

- Email transport: personal SMTP (Gmail app password) or a sending service?
- Send time, and whether weekends get one.
- Where PLAN.md is read from: local checkouts in `~/Code`, the factory work
  dirs, or the branch on GitHub (works without local clones).
- License choice.
