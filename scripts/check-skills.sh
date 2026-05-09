#!/bin/bash
# Helper for verifying Nao skills are in sync between filesystem and Cowork.
# Cowork has no API to read its skills, so this script prints what each skill
# *should* contain so you can eyeball-compare against the version in Cowork.
#
# Usage:
#   check-skills.sh                # list all skills with line counts
#   check-skills.sh <name>         # print the contents of one skill (and copy to clipboard)
#   check-skills.sh diff <name>    # show git diff of recent changes to one skill

set -euo pipefail

SKILLS_DIR="$HOME/Nao/skills"
SUBCMD="${1:-list}"

case "$SUBCMD" in
  list|"")
    echo "Skills tracked in $SKILLS_DIR:"
    for skill in "$SKILLS_DIR"/*/SKILL.md; do
      name=$(basename "$(dirname "$skill")")
      lines=$(wc -l < "$skill" | tr -d ' ')
      modified=$(stat -f "%Sm" -t "%Y-%m-%d" "$skill")
      printf "  %-15s  %4s lines  last modified %s\n" "$name" "$lines" "$modified"
    done
    echo ""
    echo "Usage: check-skills.sh <name>            # show one skill's content"
    echo "       check-skills.sh diff <name>       # show recent git changes"
    ;;
  diff)
    NAME="${2:?skill name required}"
    SKILL_FILE="$SKILLS_DIR/$NAME/SKILL.md"
    [[ -f "$SKILL_FILE" ]] || { echo "No skill named '$NAME'"; exit 1; }
    cd "$HOME/Nao"
    git log --oneline -5 -- "skills/$NAME/SKILL.md" || echo "(not in git yet)"
    echo ""
    git diff HEAD -- "skills/$NAME/SKILL.md" 2>/dev/null || true
    ;;
  *)
    NAME="$SUBCMD"
    SKILL_FILE="$SKILLS_DIR/$NAME/SKILL.md"
    if [[ ! -f "$SKILL_FILE" ]]; then
      echo "No skill named '$NAME'. Available: $(ls "$SKILLS_DIR" | tr '\n' ' ')"
      exit 1
    fi
    cat "$SKILL_FILE"
    if command -v pbcopy >/dev/null 2>&1; then
      pbcopy < "$SKILL_FILE"
      echo ""
      echo "---"
      echo "✓ Copied to clipboard. Paste into Cowork → Customize → Skills → $NAME"
    fi
    ;;
esac
