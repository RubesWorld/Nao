# Beeper — comms search for Nao, one-time setup

Beeper Desktop ships a **built-in MCP server** at `localhost:23373`, bridging
Google Messages (SMS **and** RCS), WhatsApp, Signal, Telegram, Instagram,
Messenger, X, Google Chat, Google Voice, LinkedIn, Discord and Slack.

Why this and not Traul: roadmap item 5 in `plans/blueprint.md` has the full
reasoning. Short version — Beeper speaks MCP natively, covers Google Messages
(the actual gap), and adds no new runtime to the mini.

The architectural point that matters: `localhost:23373` is the same shape as
tana-local at `127.0.0.1:8262`. tana-local works from headless `claude -p`
under launchd, so Beeper will too — meaning the watcher and the weekly review
could eventually query messages, not just interactive sessions. **Not yet
though; see "Deliberately not wired" at the bottom.**

## State

**Done 2026-10-23.** Signed in; Google Messages, WhatsApp and Telegram
connected; API on; registered with Claude Code as `beeper` using a read-only
in-app token. Wired to `com.nao.texts-capture` (see CLAUDE.md, "Beeper —
texts count as contact"). The steps below are kept for re-setup and for the
monthly token renewal.

**Two things learned doing it:**

- **Beeper's OAuth flow ignores `scope=read`.** A PKCE login asking for
  `read` came back `read write`, so a token that could send messages as
  Ruben. It was revoked. Only an in-app token with **"Sensitive actions"
  unchecked** is read-only. Always check: `POST /oauth/introspect` must say
  `"scope": "read"`, and a send attempt must return 403 `missing: write`.
- **Tokens expire after 30 days**, with no refresh. Renew in
  Settings → Developers, then `claude mcp remove beeper -s user` and add it
  again (step 4). texts-capture warns 3 days ahead.
- `/v1/messages/search` caps `limit` at 20 (anything larger is a 400).

## Steps (on the Mac mini)

**1. Launch it and sign in.**

```bash
open -a "Beeper Desktop"
```

It still carries a browser download's quarantine flag, so the first launch
shows the Gatekeeper prompt once. Sign in to the Beeper account.

**2. Connect Google Messages.**

Settings → Chat Networks → SMS/RCS (Google Messages) → Continue. It shows a
QR code; scan it from Google Messages on the Android (Settings → Device
pairing). Requires an active SIM, and the phone stays a dependency — if it
goes offline the bridge stops syncing.

Connect anything else worth searching while there. Slack is also available
here, which is a second route to the Slack channel that currently shows
`Needs authentication` in `claude mcp list`.

**3. Enable the API.**

Settings → Developers → enable. That starts the local server on port 23373.
Verify:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:23373/v0/mcp
```

Anything other than `000` means it is listening.

**4. Register it with Claude Code.**

```bash
claude mcp add beeper http://localhost:23373/v0/mcp -t http -s user
```

Do **not** use the OAuth prompt (it grants write). Create a token in
Settings → Developers with "Sensitive actions" unchecked and append
`-H "Authorization: Bearer <TOKEN>"`.

Then confirm:

```bash
claude mcp list | grep -i beeper
```

**5. Before building anything on it**, observe one real call. The search
endpoint's reference page 404s on the public docs, so its parameters are
unverified. This repo has been bitten three times in one week by acting on
assumed tool shapes — a stale note claiming Google Calendar was unreachable
headless, `read_node` rendering `**Label**: value` instead of `Label:: value`,
and dates arriving as `Mon, Jun 1`. Make a real query, read the real response,
then write code.

## What is wired, and what is not

Wired: `com.nao.texts-capture` (daily, counts real conversations as
contact) and its health-check freshness entry. Not wired, deliberately: an
autostart plist (add one, copying `scripts/bluebubbles-autostart.sh`, if
Beeper does not survive a reboot), a watcher condition, and any scheduled
prompt. The Telegram bridge's `claude -p` does not get Beeper tools: a leaked
bot token would then read every message.

## Do not enable Remote Access

Beeper offers exposing the API to the internet. Don't. The Telegram bridge is
already the remote surface, and it has a chat-id allowlist, an audit log and a
rate limit in front of it. An unauthenticated local API reachable from
anywhere would be the single largest hole in this machine — it reads every
message on every network.
