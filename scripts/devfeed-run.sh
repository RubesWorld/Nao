#!/bin/bash
# Dev feed collector (launchd com.nao.devfeed, every 5 min).
#
# The collector and the dashboard live upstream in RubesWorld/devfeed, the
# open-source version. Nao runs a pinned release of it from external/devfeed
# and keeps only its config (config/devfeed.json) and launchd wiring here.
# To upgrade: change config/devfeed.version in a PR; the next run checks the
# new tag out. Never patch external/devfeed in place: fix it upstream, tag a
# release, bump the version.
set -uo pipefail

NAO="${NAO_DIR:-$HOME/Nao}"   # NAO_DIR: test from a worktree
SRC="$HOME/Nao/external/devfeed"
LOG="$NAO/logs/tasks.log"
VERSION=$(tr -d '[:space:]' < "$NAO/config/devfeed.version")
mkdir -p "$NAO/logs"

ts() { date +%Y-%m-%dT%H:%M:%S%z | sed 's/\(..\)$/:\1/'; }

if [[ ! -d "$SRC/.git" ]]; then
  git clone --quiet https://github.com/RubesWorld/devfeed "$SRC" \
    || { echo "[$(ts)] devfeed: ERROR clone failed" >> "$LOG"; exit 1; }
fi
if [[ "$(git -C "$SRC" describe --tags --exact-match 2>/dev/null)" != "$VERSION" ]]; then
  git -C "$SRC" fetch --quiet --tags origin \
    && git -C "$SRC" -c advice.detachedHead=false checkout --quiet "$VERSION" \
    || { echo "[$(ts)] devfeed: ERROR can't check out $VERSION" >> "$LOG"; exit 1; }
  echo "[$(ts)] devfeed: now on $VERSION" >> "$LOG"
fi

# devfeed logs "[ts] devfeed: ..." lines itself, which health-check.py reads.
/usr/bin/python3 "$SRC/devfeed.py" collect --config "$NAO/config/devfeed.json" >> "$LOG" 2>&1
