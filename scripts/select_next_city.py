#!/usr/bin/env python3
"""Print the slug of the highest-ranked candidate city that hasn't been modeled yet.

A city is considered modeled if cities/<slug>/model.ipynb exists.
A city is considered blocked (skip) if cities/<slug>/BLOCKED.md exists.
"""
import json
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent
candidates_file = repo_root / "cities" / "candidates.json"
cities_dir = repo_root / "cities"

with open(candidates_file) as f:
    data = json.load(f)

modeled = {
    d.name for d in cities_dir.iterdir()
    if d.is_dir() and (d / "model.ipynb").exists()
}
blocked = {
    d.name for d in cities_dir.iterdir()
    if d.is_dir() and (d / "BLOCKED.md").exists()
}

candidates = sorted(data["candidates"], key=lambda x: x["rank"])
for c in candidates:
    slug = c["slug"]
    if slug not in modeled and slug not in blocked:
        print(slug)
        sys.exit(0)

print("ERROR: all candidates are modeled or blocked", file=sys.stderr)
sys.exit(1)
