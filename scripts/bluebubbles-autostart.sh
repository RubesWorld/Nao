#!/bin/bash
#
# Keep the BlueBubbles iMessage relay running.
#
# Why this is a polling script and not KeepAlive in the plist: `open -a`
# returns as soon as the app is handed to LaunchServices, so launchd would
# read that immediate exit as a crash and relaunch forever on the throttle
# interval. Checking for the process is the only honest test of "is it up".
#
# Why it re-checks rather than firing once at login: a dead relay is silent,
# and silence is indistinguishable from nobody texting. The watcher notices
# too, but only after two hourly probes — this closes the gap to ~5 minutes
# and fixes it without waking anyone.
#
# To stop it taking the app back over:
#   launchctl unload ~/Library/LaunchAgents/com.nao.bluebubbles.plist

APP="/Applications/BlueBubbles.app"
PROC="BlueBubbles.app/Contents/MacOS/BlueBubbles"
LOG="$HOME/Nao/logs/bluebubbles-autostart.log"

stamp() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

mkdir -p "$(dirname "$LOG")"

if [ ! -d "$APP" ]; then
    echo "[$(stamp)] ERROR: $APP not found — relay cannot start" >> "$LOG"
    exit 1
fi

# Match the main binary specifically. A bare "BlueBubbles" also matches the
# Electron helper processes, which outlive the app briefly on quit and would
# make a dead relay look alive.
if pgrep -f "$PROC" > /dev/null 2>&1; then
    exit 0   # already up — stay quiet, like the rest of the ambient layer
fi

echo "[$(stamp)] relay not running — starting" >> "$LOG"
open -a "$APP"
