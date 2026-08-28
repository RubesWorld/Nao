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

Beeper Desktop **4.3.73 is installed** at `/Applications/Beeper Desktop.app`
(signed by Automattic, `com.automattic.beeper.desktop`). Nothing else is done
— the remaining steps need a human because they involve logging in and
pairing a phone.

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

OAuth is handled in-app. If it asks for a token instead, create one in
Settings → Developers and append
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

## Deliberately not wired

Beeper is **public beta and self-described as experimental**, so the rule the
blueprint already applied to Tana's hosted MCP applies here: interactive use
first, autonomous jobs later.

Specifically, none of this exists yet and none of it should until Beeper has
proven itself over a few weeks:

- **No `com.nao.beeper` autostart.** BlueBubbles has one because a dead relay
  is silent and silence is indistinguishable from nobody texting. The same
  will be true here, and the same polling-script pattern applies — `open -a`
  returns immediately, so `KeepAlive` would read that as a crash and relaunch
  forever. Copy `scripts/bluebubbles-autostart.sh` when the time comes.
- **No watcher condition and no health-check entry.** Add one hourly probe of
  port 23373 at that point, and add `com.nao.beeper` to the health-check
  SPECIAL set so it is not run-counted like a prompt job.
- **Nothing in the scheduled prompts.** The weekly review and the digests do
  not know Beeper exists.

## Do not enable Remote Access

Beeper offers exposing the API to the internet. Don't. The Telegram bridge is
already the remote surface, and it has a chat-id allowlist, an audit log and a
rate limit in front of it. An unauthenticated local API reachable from
anywhere would be the single largest hole in this machine — it reads every
message on every network.
