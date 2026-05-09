#!/bin/bash
# Generic Nao task runner. Takes a prompt file path and a task name.
# Usage: run-task.sh <prompt-file-path> [model]

set -euo pipefail

# Explicit PATH so launchd finds claude and node
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export HOME="${HOME:-/Users/rubenmacmini}"

# Load secrets (Telegram bot token, etc)
if [[ -f "$HOME/Nao/.env" ]]; then
  set -a
  source "$HOME/Nao/.env"
  set +a
fi

PROMPT_FILE="${1:?prompt file path required}"
MODEL="${2:-haiku}"

if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ERROR: prompt file not found: $PROMPT_FILE" >> "$HOME/Nao/logs/tasks.log"
  exit 1
fi

TASK_NAME=$(basename "$PROMPT_FILE" .md)
DATE=$(date +%Y-%m-%d)
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
NAO_DIR="$HOME/Nao"
LOG="$NAO_DIR/logs/tasks.log"
OUTPUT="$NAO_DIR/briefings/${DATE}-${TASK_NAME}.md"

mkdir -p "$NAO_DIR/briefings" "$NAO_DIR/logs"

echo "[$TIMESTAMP] START $TASK_NAME (model=$MODEL)" >> "$LOG"

# Run claude with stdin-piped prompt. Use --dangerously-skip-permissions for autonomous run.
# CD into Nao dir so CLAUDE.md is loaded automatically.
cd "$NAO_DIR"

if cat "$PROMPT_FILE" | claude -p \
  --model "$MODEL" \
  --output-format text \
  --dangerously-skip-permissions \
  > "$OUTPUT" 2>> "$LOG"; then
  END_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  SIZE=$(wc -c < "$OUTPUT" | tr -d ' ')
  echo "[$END_TIMESTAMP] END   $TASK_NAME (ok, ${SIZE} bytes written to $OUTPUT)" >> "$LOG"

  # Send Telegram notification only if output has non-whitespace content
  CONTENT=$(tr -d '[:space:]' < "$OUTPUT")
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" && -n "$CONTENT" ]]; then
    SUMMARY=$(head -c 3500 "$OUTPUT")
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=🧠 ${TASK_NAME}: ${SUMMARY}" \
      > /dev/null 2>> "$LOG" || echo "[$END_TIMESTAMP] WARN: telegram send failed for $TASK_NAME" >> "$LOG"
  else
    echo "[$END_TIMESTAMP] $TASK_NAME: stayed quiet (no notification)" >> "$LOG"
  fi
else
  EXIT=$?
  END_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "[$END_TIMESTAMP] END   $TASK_NAME (FAILED, exit=$EXIT)" >> "$LOG"
  exit $EXIT
fi
