#!/usr/bin/env bash
# Run the LVTShift nightly city model locally.
# Schedule with cron or launchd to run each morning.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env (CENSUS_API_KEY, etc.)
if [ -f .env ]; then
  set -a; source .env; set +a
fi

# Activate virtualenv if present at the standard project location
VENV="$HOME/packaging-test/pkg-test/bin/activate"
if [ -f "$VENV" ]; then
  source "$VENV"
fi

# Select the next unmodeled city
CITY=$(python scripts/select_next_city.py)
TODAY=$(date +%Y-%m-%d)
echo "[$(date)] Starting nightly run for: $CITY"

# Build the session prompt from the template
PROMPT=$(CITY="$CITY" TODAY="$TODAY" envsubst < .claude/nightly-city-prompt.md)

# Run the Claude Code session
claude -p "$PROMPT" --dangerously-skip-permissions

echo "[$(date)] Nightly run complete for: $CITY"
