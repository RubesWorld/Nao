#!/usr/bin/env python3
"""Dev feed collector — polls GitHub for pushes and merges across watched repos.

Deterministic, no LLM. Reads config/devfeed.json, fetches recent commits and
merged PRs per repo via the gh CLI (keyring auth), and regenerates
devfeed/feed.json wholesale each run — stateless, so there is no dedupe
bookkeeping to corrupt. The dashboard (devfeed/index.html) polls feed.json.

On any repo failing to fetch, the previous feed.json is left untouched rather
than overwritten with a partial view; the dashboard surfaces staleness via
generated_at, so a broken collector is visible on the page itself.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

NAO = os.path.expanduser("~/Nao")
GH = "/opt/homebrew/bin/gh"
CONFIG_PATH = os.path.join(NAO, "config", "devfeed.json")
OUT_PATH = os.path.join(NAO, "devfeed", "feed.json")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")

MAX_ITEMS_PER_REPO = 30


def log(msg):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    with open(LOG_PATH, "a") as f:
        f.write(f"[{ts}] devfeed: {msg}\n")


def gh_api(path):
    r = subprocess.run(
        [GH, "api", path],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh api {path}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def fetch_repo(repo, since):
    commits = gh_api(f"repos/{repo}/commits?per_page=60")
    pulls = gh_api(f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=20")

    merges = []
    merged_prs = set()
    for pr in pulls:
        if not pr.get("merged_at"):
            continue
        ts = pr["merged_at"]
        if ts < since:
            continue
        merged_prs.add(pr["number"])
        merges.append({
            "type": "merge",
            "title": pr["title"],
            "ref": f"#{pr['number']}",
            "ts": ts,
            "url": pr["html_url"],
        })

    pushes = []
    commit_ts = []
    for c in commits:
        ts = (c.get("commit", {}).get("committer") or {}).get("date", "")
        if not ts or ts < since:
            continue
        commit_ts.append(ts)
        msg = c["commit"]["message"].split("\n")[0]
        # Merge commits ("Merge pull request #N ...") and squash commits
        # ("... (#N)") duplicate the PR's own merge entry — skip them there,
        # though they still count toward the sparkline via commit_ts.
        n = None
        if msg.startswith("Merge pull request #"):
            try:
                n = int(msg.split("#")[1].split()[0])
            except (IndexError, ValueError):
                pass
        elif msg.endswith(")") and "(#" in msg:
            try:
                n = int(msg.rsplit("(#", 1)[1][:-1])
            except ValueError:
                pass
        if n in merged_prs:
            continue
        pushes.append({
            "type": "push",
            "title": msg,
            "ref": c["sha"][:7],
            "ts": ts,
            "url": c["html_url"],
        })

    items = sorted(merges + pushes, key=lambda i: i["ts"], reverse=True)
    return items[:MAX_ITEMS_PER_REPO], commit_ts


def daily_counts(commit_ts, days):
    """Commit counts per local day for the sparkline, oldest first."""
    today = datetime.now().astimezone().date()
    buckets = {today - timedelta(days=n): 0 for n in range(days)}
    for ts in commit_ts:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
        if d in buckets:
            buckets[d] += 1
    return [buckets[d] for d in sorted(buckets)]


def main():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    since = (datetime.now(timezone.utc) - timedelta(days=cfg["days"])).strftime(
        "%Y-%m-%dT%H:%M:%SZ")

    repos_out = []
    for r in cfg["repos"]:
        items, commit_ts = fetch_repo(r["repo"], since)
        repos_out.append({
            "repo": r["repo"],
            "display": r["display"],
            "slot": r["slot"],
            "last_activity": items[0]["ts"] if items else None,
            "spark": daily_counts(commit_ts, cfg["spark_days"]),
            "items": items,
        })

    feed = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spark_days": cfg["spark_days"],
        "days": cfg["days"],
        "repos": repos_out,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(feed, f)
    os.replace(tmp, OUT_PATH)

    total = sum(len(r["items"]) for r in repos_out)
    log(f"feed regenerated ({len(repos_out)} repos, {total} items)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)
