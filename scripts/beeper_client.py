#!/usr/bin/env python3
"""
Direct HTTP client for Beeper Desktop's local API (127.0.0.1:23373).

Same reasoning as tana_client.py: Python can call the REST API directly,
which is deterministic and free, so nothing in the texts path needs a model.

The token is Beeper's **read-only** one (created in Beeper → Settings →
Developers with "Sensitive actions" unchecked). It is read from the `beeper`
entry in ~/.claude.json, the one place Claude Code already keeps it. A token
that can send must never be put there: Beeper's OAuth flow ignores a
`scope=read` request and hands out read+write (found 2026-10-23), so only an
in-app token is known to be read-only. Tokens expire after 30 days; a 401
surfaces as TokenExpired so the caller can say so instead of going quiet.

Probe by hand:
    python3 beeper_client.py accounts
    python3 beeper_client.py chats
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:23373"
CLAUDE_CONFIG = os.path.expanduser("~/.claude.json")
PAGE = 20   # /v1/messages/search rejects anything larger


class TokenExpired(Exception):
    pass


def _auth_header():
    override = os.environ.get("NAO_BEEPER_AUTH")
    if override:
        return override
    try:
        with open(CLAUDE_CONFIG) as f:
            servers = json.load(f).get("mcpServers", {})
    except (IOError, ValueError):
        return None
    # By URL, not name — the tana-local rename taught that one.
    for server in servers.values():
        if server.get("url", "").startswith(BASE):
            auth = server.get("headers", {}).get("Authorization")
            if auth:
                return auth
    return None


class BeeperClient:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.auth = _auth_header()

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        url = BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        headers = {"Authorization": self.auth} if self.auth else {}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=self.timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise TokenExpired("Beeper rejected the token (401)")
            raise RuntimeError("%s -> HTTP %d %s" % (path, e.code, e.read()[:200]))

    def accounts(self):
        d = self.get("/v1/accounts")
        return d if isinstance(d, list) else d.get("items", [])

    def chats_active_since(self, since_iso):
        """Chats with activity at or after since_iso, most recent first."""
        out, cursor = [], None
        while True:
            d = self.get("/v1/chats", limit=200, cursor=cursor,
                         direction="before" if cursor else None)
            items = d.get("items", [])
            fresh = [c for c in items if (c.get("lastActivity") or "") >= since_iso]
            out += fresh
            if len(fresh) < len(items) or not d.get("hasMore") or not items:
                return out
            cursor = d.get("oldestCursor")

    def messages(self, chat_id, after_iso, before_iso):
        """Every message in one chat between two instants, oldest first."""
        out, cursor = [], None
        while True:
            d = self.get("/v1/messages/search", chatIDs=chat_id,
                         dateAfter=after_iso, dateBefore=before_iso,
                         limit=PAGE, includeMuted="true",
                         excludeLowPriority="false", cursor=cursor,
                         direction="before" if cursor else None)
            out += d.get("items", [])
            if not d.get("hasMore") or not d.get("items"):
                break
            cursor = d.get("oldestCursor")
        return sorted(out, key=lambda m: m.get("timestamp", ""))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "accounts"
    c = BeeperClient()
    if cmd == "accounts":
        for a in c.accounts():
            print(a.get("accountID"), "|", a.get("network"))
    elif cmd == "chats":
        for ch in c.get("/v1/chats", limit=25).get("items", []):
            print(ch.get("type"), "|", ch.get("network"), "|", ch.get("title"),
                  "|", ch.get("lastActivity"))
    else:
        print("usage: beeper_client.py accounts | chats", file=sys.stderr)
        sys.exit(1)
