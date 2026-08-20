#!/usr/bin/env python3
"""
Nao self-health check — weekly, deterministic, no LLM.

A failed scheduled job writes FAILED to tasks.log and stops; a job that
launchd never fired (Mac asleep, plist unloaded) writes nothing at all.
Either way the silence is indistinguishable from a quiet day. This closes
that gap: once a week, read the log, compare against what the LaunchAgents
say SHOULD have run, and report — always, so the report itself proves the
heartbeat is alive.

Run it manually any time:  python3 ~/Nao/scripts/health-check.py
"""

import glob
import os
import plistlib
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nao_telegram import send as telegram_send  # noqa: E402

NAO = os.path.expanduser("~/Nao")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")
AGENTS_GLOB = os.path.expanduser("~/Library/LaunchAgents/com.nao.*.plist")
WINDOW_DAYS = 7
WATCHER_MAX_GAP_HOURS = 3   # hourly job; allow some sleep slack

# Managed outside run-task.sh; checked by their own signals below.
SPECIAL = {"com.nao.watcher", "com.nao.telegram-bridge",
           "com.nao.health-check"}


def expected_runs(plist_path, window_days):
    """How many firings the plist's schedule implies inside the window.
    Conservative: monthly jobs count only if their day-of-month occurred."""
    with open(plist_path, "rb") as f:
        data = plistlib.load(f)
    cal = data.get("StartCalendarInterval")
    if cal is None:
        return None   # KeepAlive daemon or interval job — not calendar math
    if isinstance(cal, dict):
        cal = [cal]
    today = datetime.now().date()
    days = [today - timedelta(days=i) for i in range(window_days)]
    count = 0
    for entry in cal:
        for d in days:
            if "Day" in entry and d.day != entry["Day"]:
                continue
            # launchd Weekday: 0 and 7 are Sunday; Python: Monday=0.
            if "Weekday" in entry:
                if (d.weekday() + 1) % 7 != entry["Weekday"] % 7:
                    continue
            count += 1
    return count


def task_name(plist_path):
    with open(plist_path, "rb") as f:
        data = plistlib.load(f)
    for arg in data.get("ProgramArguments", []):
        if arg.endswith(".md"):
            return os.path.basename(arg)[:-3]
    return data.get("Label", os.path.basename(plist_path))


def parse_log(window_start):
    """tasks.log → per-task {ok, failed, skipped}, plus last watcher stamp."""
    stats, watcher_last = {}, None
    if not os.path.exists(LOG_PATH):
        return stats, watcher_last
    line_re = re.compile(
        r"^\[([0-9T:+\-Z]+)\]\s+(START|END|SKIP|watcher:)\s*(.*)$")
    with open(LOG_PATH) as f:
        for line in f:
            m = line_re.match(line.strip())
            if not m:
                continue
            stamp_raw, kind, rest = m.groups()
            try:
                stamp = datetime.fromisoformat(stamp_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if stamp < window_start:
                continue
            if kind == "watcher:":
                watcher_last = stamp
                continue
            name = rest.split()[0] if rest.split() else "?"
            entry = stats.setdefault(name, {"ok": 0, "failed": 0, "skipped": 0})
            if kind == "SKIP":
                entry["skipped"] += 1
            elif kind == "END":
                if "FAILED" in rest:
                    entry["failed"] += 1
                else:
                    entry["ok"] += 1
    return stats, watcher_last


def main():
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=WINDOW_DAYS)
    stats, watcher_last = parse_log(window_start)

    problems, fine = [], []

    for plist_path in sorted(glob.glob(AGENTS_GLOB)):
        label = os.path.basename(plist_path)[:-len(".plist")]
        if label in SPECIAL:
            continue
        name = task_name(plist_path)
        expected = expected_runs(plist_path, WINDOW_DAYS)
        s = stats.get(name, {"ok": 0, "failed": 0, "skipped": 0})
        ran = s["ok"] + s["skipped"]
        if s["failed"]:
            problems.append("%s: %d failed run(s)" % (name, s["failed"]))
        if expected and ran == 0:
            problems.append("%s: never ran (expected ~%d)" % (name, expected))
        elif expected and ran < expected:
            problems.append("%s: ran %d of ~%d expected" % (name, ran, expected))
        elif ran:
            fine.append(name)

    if watcher_last is None:
        problems.append("watcher: no log lines in %d days" % WINDOW_DAYS)
    elif now - watcher_last > timedelta(hours=WATCHER_MAX_GAP_HOURS):
        problems.append("watcher: last ran %s ago"
                        % str(now - watcher_last).split(".")[0])

    lock = os.path.join(NAO, "state", "telegram-bridge.lock")
    bridge_ok = False
    if os.path.exists(lock):
        try:
            os.kill(int(open(lock).read().strip()), 0)
            bridge_ok = True
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    if not bridge_ok:
        problems.append("telegram-bridge: not running (lock missing or stale)")

    if problems:
        msg = "🩺 Nao health — %d issue(s) this week:\n" % len(problems) \
              + "\n".join("• %s" % p for p in problems)
    else:
        msg = "🩺 Nao health: all %d jobs ran clean this week. Watcher and " \
              "bridge alive." % len(fine)

    print(msg)
    telegram_send(msg)
    with open(LOG_PATH, "a") as f:
        f.write("[%s] END   health-check (ok, %d problems)\n"
                % (now.strftime("%Y-%m-%dT%H:%M:%SZ"), len(problems)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
