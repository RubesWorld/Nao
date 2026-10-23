#!/bin/bash
# Dev feed morning email (launchd com.nao.devfeed-digest, daily 07:30).
#
# Runs the pinned devfeed release that scripts/devfeed-run.sh keeps checked
# out in external/devfeed. `digest` refreshes the feed, mails what's waiting
# and what happened since the last email, and keeps its window in
# config/digest-state.json (gitignored). This repo is public, so the digest
# settings (address, page link) live in config/devfeed.local.json
# (gitignored) and are merged over config/devfeed.json at run time. The SMTP
# password is a Gmail app password in the login Keychain (service
# devfeed-smtp); it never touches disk or the config.
set -uo pipefail

NAO="${NAO_DIR:-$HOME/Nao}"   # NAO_DIR: test from a worktree
SRC="$HOME/Nao/external/devfeed"
LOG="$NAO/logs/tasks.log"
mkdir -p "$NAO/logs"

ts() { date +%Y-%m-%dT%H:%M:%S%z | sed 's/\(..\)$/:\1/'; }

# Merged config next to the others, so digest-state.json lands in config/.
CFG="$NAO/config/devfeed.digest.json"
if ! /usr/bin/python3 - "$NAO/config/devfeed.json" "$NAO/config/devfeed.local.json" "$CFG" <<'PY'
import json, os, sys
base, local, out = sys.argv[1:]
cfg = json.load(open(base))
cfg.update(json.load(open(local)))
fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(cfg, f, indent=2)
PY
then
  echo "[$(ts)] devfeed: ERROR digest: can't build $CFG (is config/devfeed.local.json there?)" >> "$LOG"
  exit 1
fi

# App passwords are shown with spaces; Gmail wants them without.
PW=$(security find-generic-password -s devfeed-smtp -w 2>/dev/null | tr -d ' ')
if [[ -z "$PW" ]]; then
  echo "[$(ts)] devfeed: ERROR digest: no devfeed-smtp password in the Keychain (locked?)" >> "$LOG"
  exit 1
fi

# devfeed logs "[ts] devfeed: ..." lines itself, which health-check.py reads.
DEVFEED_SMTP_PASSWORD="$PW" /usr/bin/python3 "$SRC/devfeed.py" digest \
  --config "$CFG" >> "$LOG" 2>&1
