#!/bin/bash
cd ~/Nao
DATE=$(date +%Y-%m-%d)
PROMPT="Read the NAO-INDEX node in Tana via the tana-local MCP. Generate a concise morning briefing covering: (1) Active projects and their next actions, (2) Open promises sorted by deadline with anything overdue flagged, (3) People I haven't connected with in a while based on their cadence — surface the top 3. Write it as clean markdown. Then write the same content as a child node under today's daily note in Tana, tagged #session-digest with Context = 'Morning briefing'."
claude -p "$PROMPT" --dangerously-skip-permissions > ~/Nao/briefings/${DATE}-morning.md 2>> ~/Nao/logs/morning-briefing.log
