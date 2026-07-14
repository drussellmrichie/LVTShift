#!/usr/bin/env python3
"""Run the LVTShift nightly city model.

Windows: schedule via Task Scheduler (see README or docs).
Mac/Linux: schedule via cron or launchd.
"""
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

repo_root = Path(__file__).parent.parent
os.chdir(repo_root)

# Load .env (CENSUS_API_KEY, ANTHROPIC_API_KEY, etc.)
env_file = repo_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Select next unmodeled city
result = subprocess.run(
    [sys.executable, str(repo_root / "scripts" / "select_next_city.py")],
    capture_output=True, text=True, check=True,
)
city = result.stdout.strip()
today = date.today().isoformat()
print(f"[{today}] Selected city: {city}")

# Build prompt from template (replaces ${CITY} and ${TODAY})
template = (repo_root / ".claude" / "nightly-city-prompt.md").read_text()
prompt = template.replace("${CITY}", city).replace("${TODAY}", today)

# Locate the claude CLI (handles both unix 'claude' and Windows 'claude.cmd')
claude = shutil.which("claude") or shutil.which("claude.cmd")
if not claude:
    sys.exit("ERROR: 'claude' not found in PATH. Run: npm install -g @anthropic-ai/claude-code")

print(f"[{today}] Starting Claude Code session for {city} ...")
subprocess.run([claude, "-p", prompt, "--dangerously-skip-permissions"], check=True)
print(f"[{today}] Done.")
