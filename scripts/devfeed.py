#!/usr/bin/env python3
"""Dev feed collector — polls GitHub for pushes and merges across Ruben's repos.

Deterministic, no LLM. Which repos to watch is discovered, not configured:
every non-archived, non-fork repo of the owner pushed within `active_days`,
plus any `pin`ned in config/devfeed.json (which otherwise only holds display
names, colour slots and `hide`s). Per repo it fetches recent commits and
merged PRs, plus open PRs and in-progress branches — the "what is waiting on
me" half that matters once the factory opens PRs on its own. Everything goes
through the gh CLI (keyring auth), and devfeed/feed.json is regenerated
wholesale each run — stateless, so there is no dedupe bookkeeping to corrupt.
The dashboard (devfeed/index.html) polls feed.json.

On any repo failing to fetch, the previous feed.json is left untouched rather
than overwritten with a partial view; the dashboard surfaces staleness via
generated_at, so a broken collector is visible on the page itself.
"""

import json
import os
import subprocess
import sys
import zlib
from datetime import datetime, timedelta, timezone

# The repo root this script lives in: ~/Nao in production, a worktree when testing.
NAO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH = "/opt/homebrew/bin/gh"
CONFIG_PATH = os.path.join(NAO, "config", "devfeed.json")
OUT_PATH = os.path.join(NAO, "devfeed", "feed.json")
LOG_PATH = os.path.join(NAO, "logs", "tasks.log")

MAX_ITEMS_PER_REPO = 30
SLOTS = 8                 # colour slots in index.html
BRANCH_DAYS = 7           # a branch with no commit for this long is not "in progress"
IGNORED_BRANCHES = {"review-media"}   # /ship's GIF store, not work


def log(msg):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    with open(LOG_PATH, "a") as f:
        f.write(f"[{ts}] devfeed: {msg}\n")


def gh(*args):
    r = subprocess.run(
        [GH, *args],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh {args[0]} {args[1]}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


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
    merged_titles = set()
    for pr in pulls:
        if not pr.get("merged_at"):
            continue
        ts = pr["merged_at"]
        if ts < since:
            continue
        merged_prs.add(pr["number"])
        merged_titles.add(pr["title"].strip())
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
        # Three shapes duplicate a PR's own merge entry: the merge commit
        # ("Merge pull request #N ..."), a squash commit ("... (#N)"), and —
        # for merge-commit PRs whose title is the branch commit's subject —
        # the branch commit itself. Skip all three from the item list; they
        # still count toward the sparkline via commit_ts.
        if msg.strip() in merged_titles:
            continue
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


OPEN_WORK_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { name }
    pullRequests(states: OPEN, first: 20, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number title url isDraft createdAt updatedAt headRefName reviewDecision
        commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
      }
    }
    refs(refPrefix: "refs/heads/", first: 20,
         orderBy: {field: TAG_COMMIT_DATE, direction: DESC}) {
      nodes {
        name
        associatedPullRequests(first: 1) { totalCount }
        target { ... on Commit { committedDate messageHeadline url } }
      }
    }
  }
}
"""


def fetch_open_work(repo):
    """Open PRs (what's waiting for review) and branches with recent commits
    but no PR yet (what's being built). Merged work is fetch_repo's job."""
    owner, name = repo.split("/")
    data = gh("api", "graphql", "-f", f"query={OPEN_WORK_QUERY}",
              "-F", f"owner={owner}", "-F", f"name={name}")["data"]["repository"]

    prs = []
    for pr in data["pullRequests"]["nodes"]:
        last = pr["commits"]["nodes"]
        rollup = last[0]["commit"]["statusCheckRollup"] if last else None
        prs.append({
            "title": pr["title"],
            "ref": f"#{pr['number']}",
            "url": pr["url"],
            "branch": pr["headRefName"],
            "draft": pr["isDraft"],
            "opened": pr["createdAt"],
            "ts": pr["updatedAt"],
            "review": pr["reviewDecision"],          # APPROVED / CHANGES_REQUESTED / None
            "checks": rollup["state"] if rollup else None,  # SUCCESS / FAILURE / PENDING / None
        })

    default = (data["defaultBranchRef"] or {}).get("name")
    cutoff = (datetime.now(timezone.utc) - timedelta(days=BRANCH_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    # A branch with any PR is covered elsewhere: open ones are in prs, and
    # merged/closed ones are done even if nobody deleted the branch.
    branches = []
    for ref in data["refs"]["nodes"]:
        c = ref["target"] or {}
        ts = c.get("committedDate")
        if (ref["name"] == default or ref["name"] in IGNORED_BRANCHES
                or ref["associatedPullRequests"]["totalCount"] or not ts or ts < cutoff):
            continue
        branches.append({
            "title": c["messageHeadline"],
            "branch": ref["name"],
            "ts": ts,
            "url": f"https://github.com/{repo}/tree/{ref['name']}",
        })
    return prs, branches


def discover(cfg):
    """Repos to show: recently pushed ones plus pins, minus hides, most recent first."""
    overrides = {r["repo"]: r for r in cfg.get("repos", [])}
    hidden = set(cfg.get("hide", []))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=cfg["active_days"])).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    listed = gh("repo", "list", cfg["owner"], "--limit", "200", "--no-archived", "--source",
                "--json", "nameWithOwner,pushedAt")
    pushed = {r["nameWithOwner"]: r["pushedAt"] for r in listed}
    names = {n for n, ts in pushed.items() if ts and ts >= cutoff}
    names |= {n for n, o in overrides.items() if o.get("pin")}
    names -= hidden
    return [
        {
            "repo": n,
            "display": overrides.get(n, {}).get("display") or n.split("/")[1],
            # Pinned slot if configured, else derived from the name, so a repo
            # keeps its colour however the list reorders.
            "slot": overrides.get(n, {}).get("slot") or zlib.crc32(n.encode()) % SLOTS + 1,
        }
        for n in sorted(names, key=lambda n: pushed.get(n) or "", reverse=True)
    ]


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
    for r in discover(cfg):
        items, commit_ts = fetch_repo(r["repo"], since)
        open_prs, branches = fetch_open_work(r["repo"])
        repos_out.append({
            "repo": r["repo"],
            "display": r["display"],
            "slot": r["slot"],
            "last_activity": max([i["ts"] for i in items[:1] + open_prs + branches],
                                 default=None),
            "spark": daily_counts(commit_ts, cfg["spark_days"]),
            "items": items,
            "open_prs": open_prs,
            "branches": branches,
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
    prs = sum(len(r["open_prs"]) for r in repos_out)
    log(f"feed regenerated ({len(repos_out)} repos, {total} items, {prs} open PRs)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)
