#!/bin/bash
# Generic Nao task runner. Takes a prompt file path and a task name.
# Usage: run-task.sh <prompt-file-path> [model]
#   NAO_FORCE=1     re-run even if today's output already exists
#   NAO_TASK_TIMEOUT=<seconds>  override the 900s default

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
TIMEOUT_SECS="${NAO_TASK_TIMEOUT:-900}"

mkdir -p "$NAO_DIR/briefings" "$NAO_DIR/logs"

# Deterministic idempotency: if today's output already exists with content,
# the task already ran (launchd catch-up after sleep, or a manual re-run).
# Skipping here is free; the in-prompt Tana search stays as a second layer.
if [[ -s "$OUTPUT" && -z "${NAO_FORCE:-}" ]]; then
  echo "[$TIMESTAMP] SKIP  $TASK_NAME (already ran today: $OUTPUT; NAO_FORCE=1 to override)" >> "$LOG"
  exit 0
fi

echo "[$TIMESTAMP] START $TASK_NAME (model=$MODEL)" >> "$LOG"

# A hung MCP call would otherwise run forever — launchd never kills us.
# coreutils gtimeout if installed, else no timeout (logged so it's known).
TIMEOUT_CMD=()
if command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(gtimeout "$TIMEOUT_SECS")
elif command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD=(timeout "$TIMEOUT_SECS")
else
  echo "[$TIMESTAMP] WARN  no timeout binary (brew install coreutils) — $TASK_NAME runs unbounded" >> "$LOG"
fi

# Run claude with stdin-piped prompt. Use --dangerously-skip-permissions for autonomous run.
# CD into Nao dir so CLAUDE.md is loaded automatically.
cd "$NAO_DIR"

# ${arr[@]+...} idiom: macOS ships bash 3.2, where expanding an empty
# array under `set -u` is an unbound-variable error.
if ${TIMEOUT_CMD[@]+"${TIMEOUT_CMD[@]}"} claude -p \
  --model "$MODEL" \
  --output-format text \
  --dangerously-skip-permissions \
  < "$PROMPT_FILE" \
  > "$OUTPUT" 2>> "$LOG"; then
  END_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  SIZE=$(wc -c < "$OUTPUT" | tr -d ' ')
  echo "[$END_TIMESTAMP] END   $TASK_NAME (ok, ${SIZE} bytes written to $OUTPUT)" >> "$LOG"

  # Every prompt job ends with one line naming what it wrote and where (the
  # convention in CLAUDE.md), so the action log gets these for free. Skip a
  # run that stayed quiet — a job that changed nothing is not an action.
  SUMMARY=$(grep -v '^[[:space:]]*$' "$OUTPUT" | tail -1)
  if [[ -n "$SUMMARY" ]]; then
    python3 "$NAO_DIR/scripts/nao_audit.py" record \
      "$TASK_NAME" wrote "scheduled run" "$SUMMARY" >/dev/null 2>&1 || true
  fi

  # Send Telegram notification only if output has non-whitespace content.
  # nao_telegram.py chunks by characters — the old `head -c 3500` could
  # split an emoji mid-byte and Telegram rejects invalid UTF-8 outright.
  CONTENT=$(tr -d '[:space:]' < "$OUTPUT")
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" && -n "$CONTENT" ]]; then
    python3 "$NAO_DIR/scripts/nao_telegram.py" "🧠 ${TASK_NAME}: $(cat "$OUTPUT")" \
      >> "$LOG" 2>&1 || echo "[$END_TIMESTAMP] WARN: telegram send failed for $TASK_NAME" >> "$LOG"
  else
    echo "[$END_TIMESTAMP] $TASK_NAME: stayed quiet (no notification)" >> "$LOG"
  fi
else
  EXIT=$?
  END_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  REASON="exit=$EXIT"
  [[ $EXIT -eq 124 ]] && REASON="timed out after ${TIMEOUT_SECS}s"
  echo "[$END_TIMESTAMP] END   $TASK_NAME (FAILED, $REASON)" >> "$LOG"
  # Park partial output so the skip-check above doesn't block a retry today.
  [[ -f "$OUTPUT" ]] && mv "$OUTPUT" "${OUTPUT}.failed"
  # A silently failing job is indistinguishable from a quiet day — say so.
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    python3 "$NAO_DIR/scripts/nao_telegram.py" \
      "⚠️ ${TASK_NAME} failed (${REASON}) — check logs/tasks.log on the mini" \
      >> "$LOG" 2>&1 || true
  fi
  exit $EXIT
fi
