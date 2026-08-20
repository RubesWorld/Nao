# Google Calendar for headless jobs — one-time setup

Calendar of record: **nycrar@gmail.com**. Cowork sessions see it through the
Google Calendar MCP, but launchd jobs (morning briefing) can't — they get it
via `gcalcli`, a CLI with its own OAuth token stored on the mini.

## Setup (on the Mac mini)

1. `brew install gcalcli`
2. gcalcli needs its own OAuth client (Google shut off the shared one):
   - console.cloud.google.com → new project (e.g. "nao-calendar") →
     enable **Google Calendar API**
   - OAuth consent screen: External, add nycrar@gmail.com as a test user
   - Credentials → Create OAuth client ID → **Desktop app** → note the
     client ID and secret
3. `gcalcli init` — paste the client ID/secret, complete the browser
   consent as nycrar@gmail.com
4. Verify: `gcalcli agenda` shows real events, then
   `~/Nao/scripts/calendar-today.sh` shows today's.

The token lands in `~/.local/share/gcalcli/` (or `~/.gcalcli_oauth` on older
versions) and refreshes itself. If it ever breaks, the morning briefing
degrades gracefully — the wrapper prints nothing and the briefing just skips
the calendar section, same as before this existed.

## Notes

- The wrapper filters declined events and strips blank lines. Add
  `--calendar <name>` inside `calendar-today.sh` to scope to specific
  calendars if the account accumulates noisy shared ones.
- Don't point the scheduled prompts at gcalcli directly — always go through
  `calendar-today.sh` so the empty-when-unavailable contract holds in one
  place.
