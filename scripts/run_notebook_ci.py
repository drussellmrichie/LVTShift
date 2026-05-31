#!/usr/bin/env python3
"""Execute a city notebook in CI.

Patches data_scrape=0/False → 1/True in all code cells so notebooks fetch
fresh data (CI has no local parcel cache), then runs the notebook via
nbconvert with the notebook's own directory as the kernel working directory.
The executed notebook is discarded; only the CSV written by save_standard_export
is kept.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def patch_data_scrape(nb: dict) -> tuple:
    patched = False
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        new_source = []
        for line in cell["source"]:
            new_line = re.sub(r"(\bdata_scrape\s*=\s*)0\b", r"\g<1>1", line)
            new_line = re.sub(r"(\bdata_scrape\s*=\s*)False\b", r"\g<1>True", new_line)
            if new_line != line:
                patched = True
            new_source.append(new_line)
        cell["source"] = new_source
    return nb, patched


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: run_notebook_ci.py <city>", file=sys.stderr)
        return 1

    city = sys.argv[1]
    repo_root = Path(__file__).parent.parent.resolve()
    nb_path = repo_root / "cities" / city / "model.ipynb"

    if not nb_path.exists():
        print(f"ERROR: {nb_path} not found", file=sys.stderr)
        return 1

    with nb_path.open() as f:
        nb = json.load(f)

    nb, patched = patch_data_scrape(nb)
    if patched:
        print(f"[{city}] Patched data_scrape → 1")

    # Use MPLBACKEND=Agg so matplotlib doesn't try to open a display
    env = {**os.environ, "MPLBACKEND": "Agg"}

    # Write patched notebook as a temp file in the notebook's own directory
    # so nbconvert's cwd-relative paths work correctly
    pid = os.getpid()
    tmp_in_path = nb_path.parent / f"_ci_input_{pid}.ipynb"
    tmp_out_path = nb_path.parent / f"_ci_output_{pid}.ipynb"

    with tmp_in_path.open("w") as f:
        json.dump(nb, f)

    cmd = [
        sys.executable, "-m", "jupyter", "nbconvert",
        "--to", "notebook",
        "--execute",
        f"--ExecutePreprocessor.timeout=14400",
        "--ExecutePreprocessor.kernel_name=lvtshift",
        "--output", tmp_out_path.name,  # relative filename; cwd is nb_path.parent
        tmp_in_path.name,               # relative filename; cwd is nb_path.parent
    ]
    print(f"[{city}] Running: {' '.join(cmd)}", flush=True)
    print(f"[{city}] cwd: {nb_path.parent}", flush=True)

    try:
        result = subprocess.run(
            cmd,
            cwd=nb_path.parent,  # kernel runs from cities/<city>/ so relative paths resolve
            env=env,
        )
        if result.returncode != 0:
            print(f"[{city}] nbconvert exited with code {result.returncode}", file=sys.stderr)
        return result.returncode
    finally:
        tmp_in_path.unlink(missing_ok=True)
        tmp_out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
