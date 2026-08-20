#!/usr/bin/env python3
"""
Direct HTTP client for the tana-local MCP (127.0.0.1:8262/mcp).

Why this exists: the watcher's collector used to shell out to `claude -p`
and regex a JSON array out of the model's prose — the flakiest link in the
most safety-critical loop, and the slowest and most expensive. tana-local
is just an MCP server speaking JSON-RPC over HTTP on localhost; Python can
call search_nodes / read_node directly. Deterministic, sub-second, free.

The watcher treats this as the primary path and falls back to `claude -p`
if anything here raises, so a Tana upgrade that changes response shapes
degrades gracefully instead of blinding the watcher.

Probe it by hand to see real response shapes:
    python3 tana_client.py tools                 # list available tools
    python3 tana_client.py search '<json query>' # raw search_nodes result
    python3 tana_client.py read <nodeId>         # raw read_node result
"""

import json
import sys
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8262/mcp"
PROTOCOL_VERSION = "2025-03-26"


class TanaClient:
    def __init__(self, url=DEFAULT_URL, timeout=30):
        self.url = url
        self.timeout = timeout
        self.session_id = None
        self._next_id = 0
        self._initialized = False

    # ---- transport -------------------------------------------------------

    def _post(self, payload, expect_response=True):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            if not expect_response:
                resp.read()
                return None
            body = resp.read().decode("utf-8", "replace")
            ctype = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ctype:
            return self._parse_sse(body, payload.get("id"))
        return json.loads(body) if body.strip() else None

    @staticmethod
    def _parse_sse(body, want_id):
        """Collect `data:` payloads; return the JSON-RPC response matching
        our request id (or the last data payload if ids are absent)."""
        last = None
        for chunk in body.split("\n\n"):
            data_lines = [l[5:].lstrip() for l in chunk.splitlines()
                          if l.startswith("data:")]
            if not data_lines:
                continue
            try:
                msg = json.loads("\n".join(data_lines))
            except ValueError:
                continue
            last = msg
            if want_id is not None and msg.get("id") == want_id:
                return msg
        if last is None:
            raise RuntimeError("no data payload in SSE response")
        return last

    def _rpc(self, method, params=None):
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        resp = self._post(payload)
        if resp is None:
            raise RuntimeError("%s: empty response" % method)
        if "error" in resp:
            raise RuntimeError("%s: %s" % (method, resp["error"]))
        return resp.get("result")

    # ---- MCP lifecycle -----------------------------------------------------

    def initialize(self):
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "nao-watcher", "version": "1.0"},
        })
        # Notification: no id, no response expected.
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                   expect_response=False)
        self._initialized = True

    def list_tools(self):
        self.initialize()
        return self._rpc("tools/list")

    def call_tool(self, name, arguments):
        """Returns the tool result's text content, concatenated."""
        self.initialize()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError("tool %s errored: %r" % (name, result))
        parts = [c.get("text", "") for c in result.get("content", [])
                 if c.get("type") == "text"]
        return "\n".join(p for p in parts if p)

    # ---- convenience -------------------------------------------------------

    def search_nodes(self, query, workspace_id="drg2JUfK3f-A"):
        return self.call_tool("search_nodes",
                              {"query": query, "workspaceIds": [workspace_id]})

    def read_node(self, node_id):
        return self.call_tool("read_node", {"nodeId": node_id})


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tools"
    c = TanaClient()
    if cmd == "tools":
        out = c.list_tools()
    elif cmd == "search":
        out = c.search_nodes(json.loads(sys.argv[2]))
    elif cmd == "read":
        out = c.read_node(sys.argv[2])
    else:
        print("usage: tana_client.py tools | search '<json>' | read <id>",
              file=sys.stderr)
        sys.exit(1)
    print(out if isinstance(out, str) else json.dumps(out, indent=2))
