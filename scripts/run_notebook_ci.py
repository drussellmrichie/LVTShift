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

    with tempfile.NamedTemporaryFile(
        suffix=".ipynb", mode="w", delete=False, dir=nb_path.parent
    ) as tmp_in:
        json.dump(nb, tmp_in)
        tmp_in_path = Path(tmp_in.name)

    tmp_out_path = Path(tempfile.mktemp(suffix="_executed.ipynb"))

    try:
        result = subprocess.run(
            [
                "jupyter", "nbconvert",
                "--to", "notebook",
                "--execute",
                "--ExecutePreprocessor.timeout=14400",  # 4 hours
                "--output", str(tmp_out_path),
                str(tmp_in_path),
            ],
            cwd=nb_path.parent,  # kernel runs from cities/<city>/ so relative paths resolve
            env=env,
        )
        return result.returncode
    finally:
        tmp_in_path.unlink(missing_ok=True)
        tmp_out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
