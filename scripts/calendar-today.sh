#!/bin/bash
# Today's Google Calendar agenda for headless jobs (nycrar@gmail.com).
#
# The Google Calendar MCP only exists in Cowork sessions; launchd jobs were
# blind to the calendar. gcalcli fills the gap with a one-time OAuth on the
# mini — see docs/calendar-setup.md.
#
# Contract: prints today's agenda as plain text, one event per line.
# Prints NOTHING (exit 0) when gcalcli is missing, unauthenticated, or the
# day is empty — callers must treat empty output as "no calendar data",
# never as an error. That keeps the morning briefing working before setup.

set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

command -v gcalcli >/dev/null 2>&1 || exit 0

TODAY=$(date +%Y-%m-%d)
TOMORROW=$(date -v+1d +%Y-%m-%d 2>/dev/null || date -d '+1 day' +%Y-%m-%d)

gcalcli --nocolor agenda "$TODAY" "$TOMORROW" --nodeclined --details location 2>/dev/null \
  | sed '/^$/d' \
  | grep -v '^No Events Found' || true
