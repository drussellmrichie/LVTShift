"""
Philadelphia LVT Webmap Generator
---------------------------------
Joins the four Philadelphia scenario CSVs to cached parcel geometry and emits the
two generated artifacts the webmap site repo needs:

    <site>/philadelphia.pmtiles
    <site>/manifest.json

Everything else in the site repo (index.html, app.js, solve.js, style.css, vendor/)
is hand-authored source and is never touched by this script.

The tile toolchain (tippecanoe + ogr2ogr) has no Windows build and GDAL is broken in
the Windows conda environment, so all vector-format work is shelled out to WSL.

Usage:
    python scripts/build_philadelphia_webmap.py --stage attrs --dry-run
    python scripts/build_philadelphia_webmap.py --bbox center-city
    python scripts/build_philadelphia_webmap.py
"""

from __future__ import annotations

import os
import argparse
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The Windows console defaults to cp1252, which cannot encode the check marks and
# em dashes in this script's output or in the category labels it reports.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from lvt.parcel_map import _COLOR_STOPS, _TIPPECANOE_BASE_ARGS  # noqa: E402

DEFAULT_SITE = Path("C:/projects/philly-lvt-webmap")
DATA_DIR = REPO_ROOT / "analysis" / "data"
TAX_YEAR = int(os.environ.get("LVT_TAX_YEAR", 2026))   # override: LVT_TAX_YEAR=2027
PARCELS_GPQ = REPO_ROOT / "cities" / "philadelphia" / "data" / f"parcels_ty{TAX_YEAR}.gpq"

# DOR parcel polygons, keyed by `PIN` (matches parcels.gpq.pin). The sibling
# shapefile in this same directory has no PIN field at all (only PARCELID and
# TENCODE, neither of which matches) -- this GeoJSON is the only polygon source
# on disk with the right join key, despite being 5x the size on disk.
DOR_POLYGONS_GEOJSON = (
    REPO_ROOT / "cities" / "philadelphia" / "data" / "Philadelphia_DOR_Parcels_2023.geojson"
)
# WSL extracts just PIN + geometry (dropping ~15 unused fields) into this cache,
# which is what Windows-side Python actually reads. Gitignored via cities/*/data/.
DOR_PIN_EXTRACT = REPO_ROOT / "cities" / "philadelphia" / "data" / "_dor_pin_geom.geojsonl"

WSL_DISTRO = "Ubuntu-24.04"
WSL_STAGE_NAME = "lvt_stage"

# The Progress & Poverty GitHub org handle is not yet known. Publishing (and the
# Release-asset tile URL) is gated on it; nothing else in the build depends on it.
PP_ORG = None

LAND_IMPROVEMENT_RATIO = 4.0
TILE_LAYER = "parcels"
# 41 points is ample for the full city (0.04 pp interpolation error) but not for
# small slices, where the median steps rather than glides. 81 keeps the manifest
# well under 50 KB and holds every build mode inside the 0.5 pp tolerance.
LAND_SHARE_GRID_POINTS = 81

# Philadelphia bbox presets for cheap end-to-end slices.
BBOX_PRESETS = {
    "center-city": (-75.185, 39.937, -75.135, 39.965),
}


@dataclass(frozen=True)
class Scenario:
    key: str
    csv: str
    label: str
    short: str
    group: str
    explainer: str
    default: bool = False


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        key="opa",
        csv=f"philadelphia_ty{TAX_YEAR}.csv",
        label="OPA land values",
        short="OPA",
        group="pre_abatement",
        default=True,
        explainer=(
            "The assessor's own published land values, exactly as the Office of Property "
            "Assessment reports them. About 45% of improved parcels carry OPA's default "
            "0.200 land-to-total ratio rather than an individually assessed land value, "
            "which compresses the difference between parcels and understates how much a "
            "split-rate tax would actually shift."
        ),
    ),
    Scenario(
        key="lycd",
        csv=f"philadelphia_lycd_ty{TAX_YEAR}.csv",
        label="LYCD land values",
        short="LYCD",
        group="pre_abatement",
        explainer=(
            "\u201cLeast You Can Do\u201d land values: land rebuilt from the median dollars "
            "per square foot observed inside OPA's own Geographic Market Area zones, rather "
            "than taken from the default ratio. This is a floor on what a serious land "
            "reassessment would find, not a full reassessment. Improvement values are "
            "otherwise identical to the OPA panel, so this scenario isolates the effect of "
            "land values alone."
        ),
    ),
    Scenario(
        key="opa_post",
        csv=f"philadelphia_post_abatement_ty{TAX_YEAR}.csv",
        label="OPA, abatements expired",
        short="OPA post",
        group="post_abatement",
        explainer=(
            "OPA land values in the world after Philadelphia's 10-year construction tax "
            "abatements run out and abated improvements return to the tax roll. This raises "
            "the taxable base, so the revenue-neutral millages land lower than in the "
            "pre-abatement panel."
        ),
    ),
    Scenario(
        key="lycd_post",
        csv=f"philadelphia_lycd_post_abatement_ty{TAX_YEAR}.csv",
        label="LYCD, abatements expired",
        short="LYCD post",
        group="post_abatement",
        explainer=(
            "LYCD land values combined with expired construction abatements \u2014 the "
            "scenario in which both the land assessment is repaired and the abatement "
            "carve-out has ended."
        ),
    ),
)

SCENARIO_KEYS = tuple(s.key for s in SCENARIOS)
SCENARIO_BY_KEY = {s.key: s for s in SCENARIOS}

CSV_COLUMNS = [
    "parcel_id",
    "property_category",
    "current_tax",
    "new_tax",
    "taxable_land_value",
    "taxable_improvement_value",
    "is_fully_exempt",
    "model_type",
    "land_millage",
    "improvement_millage",
]

# Deduped series carry generated names; the manifest maps scenario -> attribute.
SERIES_ROLES = {
    "current_tax": ("cur", "Current tax"),
    "taxable_land_value": ("l", "Taxable land value"),
    "taxable_improvement_value": ("i", "Taxable improvement value"),
}

HISTOGRAM_EDGES = [stop for stop, _ in _COLOR_STOPS[:-1]]  # -30, -15, -5, 5, 15, 30


# ── WSL bridge ──────────────────────────────────────────────────────────────────


class WslRunner:
    """Runs the tile toolchain inside WSL and moves files across the boundary.

    Windows paths are translated with `wslpath` rather than string surgery, and all
    intermediate churn happens inside the WSL filesystem (ext4) rather than across
    /mnt/c, which is materially slower at parcel scale.
    """

    def __init__(self, distro: str = WSL_DISTRO, stage_name: str = WSL_STAGE_NAME) -> None:
        self.distro = distro
        self._path_cache: dict[str, str] = {}
        # Resolve $HOME rather than carrying a literal '~': every remote path gets
        # shell-quoted before use, which would suppress tilde expansion.
        home = self.run('printf %s "$HOME"').strip()
        self.stage = f"{home}/{stage_name}"
        self.run(f"mkdir -p {shlex.quote(self.stage)}")

    def run(self, command: str, check: bool = True, quiet: bool = True) -> str:
        proc = subprocess.run(
            ["wsl.exe", "-d", self.distro, "--", "bash", "-lc", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"WSL command failed ({proc.returncode}): {command}\n"
                f"{proc.stderr or proc.stdout}"
            )
        if not quiet and proc.stderr:
            print(proc.stderr.rstrip())
        return proc.stdout

    def wslpath(self, win_path: Path | str) -> str:
        key = str(win_path)
        if key not in self._path_cache:
            out = subprocess.run(
                ["wsl.exe", "-d", self.distro, "--", "wslpath", "-a", key.replace("\\", "/")],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if out.returncode != 0:
                raise RuntimeError(f"wslpath failed for {key}: {out.stderr}")
            self._path_cache[key] = out.stdout.strip()
        return self._path_cache[key]

    def push(self, local: Path, remote_name: str) -> str:
        """Copy a Windows file into the WSL stage; returns the remote path."""
        remote = f"{self.stage}/{remote_name}"
        self.run(f"cp {shlex.quote(self.wslpath(local))} {shlex.quote(remote)}")
        return remote

    def pull(self, remote: str, local: Path) -> Path:
        local.parent.mkdir(parents=True, exist_ok=True)
        self.run(f"cp {shlex.quote(remote)} {shlex.quote(self.wslpath(local.parent))}/{local.name}")
        return local

    def have_tools(self) -> bool:
        out = self.run(
            "command -v tippecanoe >/dev/null && command -v ogr2ogr >/dev/null && echo ok",
            check=False,
        )
        return out.strip() == "ok"


# ── Load and normalize ──────────────────────────────────────────────────────────


def normalize_categories(values: pd.Series) -> pd.Series:
    """Repair cp1252-mangled UTF-8 in the LYCD exports.

    The LYCD notebooks write ``Commercial \u00e2\u20ac\u201d Exempt`` where the OPA exports
    correctly carry ``Commercial \u2014 Exempt`` \u2014 a UTF-8 em dash round-tripped through
    cp1252. Left alone it both ships garbled labels to a public map and splits the
    category column into two spurious "distinct" series during dedupe.
    """

    def fix(value: object) -> object:
        if not isinstance(value, str):
            return value
        if "\u00e2\u20ac" not in value and "\u00c3" not in value:
            return value
        try:
            return value.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value

    return values.map(fix)


def load_scenarios() -> dict[str, pd.DataFrame]:
    frames: dict[str, pd.DataFrame] = {}
    for scenario in SCENARIOS:
        path = DATA_DIR / scenario.csv
        if not path.exists():
            raise FileNotFoundError(
                f"missing scenario export: {path}\n"
                f"Run cities/philadelphia/{scenario.csv.replace('.csv', '.ipynb')} first."
            )
        frame = pd.read_csv(path, usecols=CSV_COLUMNS)
        frame["property_category"] = normalize_categories(frame["property_category"])
        frames[scenario.key] = frame
    return frames


def assert_row_alignment(frames: dict[str, pd.DataFrame]) -> None:
    """All four exports must share one parcel universe in one row order.

    The dedupe and the positional duplicate keep-mask both depend on this. If a
    notebook ever changes its filtering, this is where it must fail.
    """
    reference = frames[SCENARIO_KEYS[0]]["parcel_id"].to_numpy()
    for key in SCENARIO_KEYS[1:]:
        other = frames[key]["parcel_id"].to_numpy()
        if other.shape != reference.shape or not np.array_equal(other, reference):
            raise AssertionError(
                f"scenario '{key}' does not share the parcel universe/row order of "
                f"'{SCENARIO_KEYS[0]}'; the dedupe and keep-mask are unsafe."
            )


def build_keep_mask(frame: pd.DataFrame) -> np.ndarray:
    """Positional keep-mask dropping duplicate parcel_ids, keeping the first row.

    There are 10 duplicate parcel_ids whose rows carry genuinely conflicting
    attributes (e.g. 881000395 appears both fully-exempt and abated). Because the
    four exports share a row order, the mask is computed once and applied
    identically to all of them \u2014 deduping each frame independently could pick
    different rows per scenario and silently corrupt the join.
    """
    return ~frame["parcel_id"].duplicated(keep="first").to_numpy()


def dedupe_series(
    frames: dict[str, pd.DataFrame], column: str, prefix: str
) -> tuple[dict[str, pd.Series], dict[str, str]]:
    """Emit each distinct series once; return (attr -> series, scenario -> attr).

    The partition is discovered empirically every run, never hardcoded \u2014 if two
    columns that used to match ever diverge, both ship and the manifest says so.
    """
    attr_series: dict[str, pd.Series] = {}
    scenario_attr: dict[str, str] = {}
    for key in SCENARIO_KEYS:
        series = frames[key][column].reset_index(drop=True)
        for attr, existing in attr_series.items():
            if series.equals(existing):
                scenario_attr[key] = attr
                break
        else:
            attr = f"{prefix}{len(attr_series)}"
            attr_series[attr] = series
            scenario_attr[key] = attr
    return attr_series, scenario_attr


# ── Model assertions ────────────────────────────────────────────────────────────


@dataclass
class Totals:
    sum_land: float
    sum_improvement: float
    revenue: float
    parcels_modeled: int
    land_millage: float
    improvement_millage: float
    land_share: float


def assert_millages(key: str, frame: pd.DataFrame, verbose: bool = True) -> Totals:
    """Re-derive the revenue-neutral millages from the CSV and check them.

    `_solve_revenue_neutral_split_millage` (lvt/lvt_utils.py:80) takes a closed-form
    path whenever no cap and no credit columns are passed, which all four
    Philadelphia notebooks satisfy:

        improvement_millage = revenue * 1000 / (sum_improvement + r * sum_land)

    Reproducing the CSV's own published millage from its own value columns is what
    proves `taxable_land_value` / `taxable_improvement_value` really are the solver's
    `model_land` / `model_building`, and therefore that the browser re-solve is the
    model rather than a lookalike.
    """
    solve = frame[~frame["is_fully_exempt"]]
    sum_land = float(solve["taxable_land_value"].sum())
    sum_improvement = float(solve["taxable_improvement_value"].sum())
    revenue = float(solve["current_tax"].sum())

    denominator = sum_improvement + LAND_IMPROVEMENT_RATIO * sum_land
    if denominator <= 0:
        raise AssertionError(f"{key}: taxable base is zero or negative")
    derived_improvement = revenue * 1000 / denominator
    derived_land = LAND_IMPROVEMENT_RATIO * derived_improvement

    published_improvement = float(frame["improvement_millage"].iloc[0])
    published_land = float(frame["land_millage"].iloc[0])
    for name, derived, published in (
        ("improvement", derived_improvement, published_improvement),
        ("land", derived_land, published_land),
    ):
        if not math.isclose(derived, published, rel_tol=1e-9):
            raise AssertionError(
                f"{key}: re-derived {name} millage {derived!r} does not match the "
                f"published {published!r}. taxable_* is not model_* for this export; "
                f"emit model_land/model_building explicitly from the notebook."
            )

    land_share = LAND_IMPROVEMENT_RATIO * sum_land / denominator
    if verbose:
        print(
            f"  \u2713 {key:<10} millage assertion: land {published_land:.6f} / "
            f"improvement {published_improvement:.6f}  (land share {land_share:.4f})"
        )
    return Totals(
        sum_land=sum_land,
        sum_improvement=sum_improvement,
        revenue=revenue,
        parcels_modeled=int(len(solve)),
        land_millage=published_land,
        improvement_millage=published_improvement,
        land_share=land_share,
    )


def assert_new_tax_reconstructs(key: str, frame: pd.DataFrame, totals: Totals) -> None:
    """The per-parcel tax the browser will compute must match the CSV's new_tax."""
    solve = frame[~frame["is_fully_exempt"]]
    rebuilt = np.maximum(
        0.0, solve["taxable_land_value"].to_numpy() * totals.land_millage / 1000
    ) + np.maximum(
        0.0, solve["taxable_improvement_value"].to_numpy() * totals.improvement_millage / 1000
    )
    published = solve["new_tax"].to_numpy()
    worst = float(np.max(np.abs(rebuilt - published)))
    if worst > 1e-4:
        raise AssertionError(
            f"{key}: reconstructed new_tax differs from the export by up to ${worst:,.6f}"
        )


# ── Geometry ────────────────────────────────────────────────────────────────────


def load_parcel_geometry() -> gpd.GeoDataFrame:
    """Load the shared geometry cache keyed by the CSVs' leading-zero-stripped id.

    Mirrors scripts/map_philadelphia_tax_changes.py:281-285. The cache stores OPA
    centroids (Points), not lot polygons, and its parcel_number column is itself
    inconsistently padded (8 and 9 characters both occur).
    """
    if not PARCELS_GPQ.exists():
        raise FileNotFoundError(f"missing geometry cache: {PARCELS_GPQ}")
    columns = ["parcel_number", "pin", "owner_1", "owner_2", "geometry"]
    parcels = gpd.read_parquet(PARCELS_GPQ, columns=columns).copy()
    parcels["parcel_id"] = (
        parcels["parcel_number"].astype(str).str.lstrip("0").astype("Int64")
    )
    parcels = parcels.drop_duplicates(subset="parcel_id", keep="first")
    if parcels.crs is None or parcels.crs.to_epsg() != 4326:
        parcels = parcels.to_crs("EPSG:4326")
    return parcels


def ensure_dor_pin_extract(wsl: "WslRunner") -> Path:
    """Pull a PIN+geometry-only GeoJSONSeq out of the 504 MB DOR source.

    ogr2ogr does the shrink (drop ~15 unused attribute columns, reproject to
    WGS84) inside WSL, where GDAL actually works; the result is cached on the
    Windows side so repeat builds skip re-running it.
    """
    if DOR_PIN_EXTRACT.exists():
        return DOR_PIN_EXTRACT
    if not DOR_POLYGONS_GEOJSON.exists():
        raise FileNotFoundError(f"missing DOR polygon source: {DOR_POLYGONS_GEOJSON}")
    print("  extracting PIN + geometry from the DOR source (one-time, ~504 MB in)")
    remote_src = wsl.push(DOR_POLYGONS_GEOJSON, "dor_source.geojson")
    remote_out = f"{wsl.stage}/dor_pin.geojsonl"
    wsl.run(
        f"ogr2ogr -f GeoJSONSeq -select PIN -t_srs EPSG:4326 "
        f"{shlex.quote(remote_out)} {shlex.quote(remote_src)}",
        quiet=False,
    )
    wsl.pull(remote_out, DOR_PIN_EXTRACT)
    wsl.run(f"rm -f {shlex.quote(remote_src)} {shlex.quote(remote_out)}")
    return DOR_PIN_EXTRACT


def load_dor_polygons(extract_path: Path) -> pd.DataFrame:
    """Parse the PIN+geometry extract with shapely, not GDAL.

    Windows conda's GDAL cannot load (`GDAL DLL could not be found`), so this
    avoids pyogrio/fiona entirely: each line is one GeoJSON Feature, and
    shapely.geometry.shape builds the geometry straight from the parsed dict.
    PIN 0 is DOR's placeholder for parcels it has not matched to anything and is
    dropped, along with any duplicate PIN (condo buildings share one footprint
    across many OPA accounts; the first occurrence is kept).
    """
    from shapely.geometry import shape

    pins: list[int] = []
    geoms = []
    with extract_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            feature = json.loads(line)
            pin = feature.get("properties", {}).get("PIN")
            geometry = feature.get("geometry")
            if not pin or geometry is None:
                continue
            pins.append(int(pin))
            geoms.append(shape(geometry))

    frame = pd.DataFrame({"pin": pins, "dor_geometry": geoms})
    before = len(frame)
    frame = frame.drop_duplicates(subset="pin", keep="first")
    print(f"  DOR polygons: {len(frame):,} parsed ({before - len(frame):,} duplicate PINs dropped)")
    return frame


def join_geometry(
    attrs: pd.DataFrame, mode: str, wsl: Optional["WslRunner"] = None
) -> tuple[gpd.GeoDataFrame, Optional[float]]:
    parcels = load_parcel_geometry()
    merged = attrs.merge(
        parcels[["parcel_id", "pin", "owner_1", "owner_2", "geometry"]], on="parcel_id", how="inner"
    )
    coverage = len(merged) / max(len(attrs), 1)
    print(
        f"  geometry join: {len(merged):,} / {len(attrs):,} ({coverage * 100:.1f}%) "
        f"[point centroids]"
    )
    if coverage < 0.95:
        raise AssertionError(
            f"geometry join covered only {coverage * 100:.1f}% of parcels; expected ~100%"
        )

    if mode == "point":
        gdf = gpd.GeoDataFrame(merged.drop(columns=["pin"]), geometry="geometry", crs="EPSG:4326")
        return gdf, None

    if mode != "polygon":
        raise ValueError(f"unknown geometry mode: {mode!r}")

    if wsl is None:
        wsl = WslRunner()
    extract = ensure_dor_pin_extract(wsl)
    polygons = load_dor_polygons(extract)

    with_poly = merged.merge(polygons, on="pin", how="left")
    has_polygon = with_poly["dor_geometry"].notna()
    with_poly["geometry"] = with_poly["dor_geometry"].where(has_polygon, with_poly["geometry"])
    poly_coverage = float(has_polygon.mean())
    print(
        f"  DOR polygon coverage: {int(has_polygon.sum()):,} / {len(with_poly):,} "
        f"({poly_coverage * 100:.1f}%); the rest keep their point centroid"
    )
    with_poly = with_poly.drop(columns=["pin", "dor_geometry"])
    gdf = gpd.GeoDataFrame(with_poly, geometry="geometry", crs="EPSG:4326")
    return gdf, poly_coverage


# ── Stat curve ──────────────────────────────────────────────────────────────────


def solve_millages(totals: Totals, land_share: float) -> tuple[float, float]:
    """The closed form the browser uses, in Python. Must match solve.js exactly."""
    land = (
        land_share * totals.revenue * 1000 / totals.sum_land if totals.sum_land > 0 else 0.0
    )
    improvement = (
        (1 - land_share) * totals.revenue * 1000 / totals.sum_improvement
        if totals.sum_improvement > 0
        else 0.0
    )
    return land, improvement


def compute_stat_curve(
    solve_sets: dict[str, dict[str, np.ndarray]],
    totals: dict[str, Totals],
    points: int = LAND_SHARE_GRID_POINTS,
) -> dict:
    """Per-scenario stats across the land-share range, computed over every parcel.

    The generator is constrained to two artifacts, so the viewer cannot ship a
    parcel sample to recompute chips against. Instead every grid point is an exact
    pass over the full solve set; the viewer interpolates between them. Millages
    stay exact at any share because they are closed-form.
    """
    grid = [i / (points - 1) for i in range(points)]
    by_scenario: dict[str, dict] = {}

    for key, arrays in solve_sets.items():
        land = arrays["land"]
        improvement = arrays["improvement"]
        current = arrays["current"]
        comparable = current > 0

        rows: dict[str, list] = {
            "land_millage": [],
            "improvement_millage": [],
            "median_pct": [],
            "share_up_5": [],
            "share_down_5": [],
            "histogram": [],
        }
        for share in grid:
            land_m, imp_m = solve_millages(totals[key], share)
            new_tax = np.maximum(0.0, land * land_m / 1000) + np.maximum(
                0.0, improvement * imp_m / 1000
            )
            pct = np.where(
                comparable, (new_tax - current) / np.where(comparable, current, 1) * 100, np.nan
            )
            valid = pct[comparable]
            rows["land_millage"].append(round(land_m, 9))
            rows["improvement_millage"].append(round(imp_m, 9))
            rows["median_pct"].append(round(float(np.median(valid)), 4) if valid.size else None)
            rows["share_up_5"].append(round(float((valid > 5).mean()), 6) if valid.size else None)
            rows["share_down_5"].append(
                round(float((valid < -5).mean()), 6) if valid.size else None
            )
            counts, _ = np.histogram(valid, bins=[-np.inf, *HISTOGRAM_EDGES, np.inf])
            rows["histogram"].append([int(c) for c in counts])
        by_scenario[key] = rows

    return {
        "land_share_grid": [round(g, 6) for g in grid],
        "bins": HISTOGRAM_EDGES,
        "by_scenario": by_scenario,
    }


def assert_interpolation_error(curve: dict, solve_sets, totals, tolerance_pp: float = 0.5) -> None:
    """Chips interpolate between grid points; bound the error that introduces."""
    grid = curve["land_share_grid"]
    worst = 0.0
    for key, arrays in solve_sets.items():
        current = arrays["current"]
        comparable = current > 0
        medians = curve["by_scenario"][key]["median_pct"]
        for lo, hi, m_lo, m_hi in zip(grid, grid[1:], medians, medians[1:]):
            mid = (lo + hi) / 2
            land_m, imp_m = solve_millages(totals[key], mid)
            new_tax = np.maximum(0.0, arrays["land"] * land_m / 1000) + np.maximum(
                0.0, arrays["improvement"] * imp_m / 1000
            )
            pct = (new_tax[comparable] - current[comparable]) / current[comparable] * 100
            exact = float(np.median(pct))
            worst = max(worst, abs(exact - (m_lo + m_hi) / 2))
    print(f"  stat-curve interpolation error: {worst:.4f} pp (max)")
    if worst > tolerance_pp:
        raise AssertionError(
            f"median interpolation error {worst:.3f} pp exceeds {tolerance_pp} pp; "
            f"raise LAND_SHARE_GRID_POINTS"
        )


# ── Tiles ───────────────────────────────────────────────────────────────────────


def write_geojsonseq(gdf: gpd.GeoDataFrame, path: Path, attrs: Iterable[str]) -> int:
    """Write newline-delimited GeoJSON without GDAL.

    lvt/parcel_map.py:_build_pmtiles goes GeoParquet -> ogr2ogr -> GeoJSONSeq, but
    Ubuntu's gdal-bin ships no Parquet driver and no plugin package provides one,
    while the Windows conda GDAL is broken outright. shapely.to_geojson is
    vectorized C and handles points and polygons alike, so writing the intermediate
    directly is both more portable and one process faster.
    """
    import shapely

    geometries = shapely.to_geojson(gdf.geometry.values)
    columns: dict[str, list] = {}
    for attr in attrs:
        if attr not in gdf.columns:
            continue
        series = gdf[attr]
        if series.dtype == object:
            series = series.astype(object).where(series.notna(), None)
        columns[attr] = series.tolist()
    keys = list(columns)

    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for index, geometry in enumerate(geometries):
            properties = {}
            for key in keys:
                value = columns[key][index]
                if value is not None:
                    properties[key] = value
            handle.write('{"type":"Feature","properties":')
            json.dump(properties, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write(',"geometry":')
            handle.write(geometry)
            handle.write("}\n")
            written += 1
    return written


def build_pmtiles_via_wsl(
    gdf: gpd.GeoDataFrame,
    out_pmtiles: Path,
    wsl: WslRunner,
    attrs: list[str],
    max_zoom: Optional[int] = None,
    verbose: bool = True,
    tippecanoe_args: Optional[list[str]] = None,
) -> Path:
    """GeoJSONSeq -> (WSL) tippecanoe -> PMTiles.

    tippecanoe has no Windows build, so the tiling step shells into WSL. The flags
    come from lvt.parcel_map so this path and the native one cannot drift apart.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="pmtiles_"))
    try:
        local_gj = tmpdir / "src.geojsonl"
        count = write_geojsonseq(gdf, local_gj, attrs)
        print(f"  staged {count:,} features ({local_gj.stat().st_size / 1e6:.0f} MB GeoJSONSeq)")

        remote_gj = wsl.push(local_gj, "src.geojsonl")
        remote_out = f"{wsl.stage}/out.pmtiles"
        wsl.run(f"rm -f {shlex.quote(remote_out)}")

        flags = list(_TIPPECANOE_BASE_ARGS if tippecanoe_args is None else tippecanoe_args)
        if max_zoom is not None:
            flags = [f for f in flags if f != "-zg"] + [f"-z{max_zoom}"]
        if verbose:
            flags = [f for f in flags if f != "--quiet"]
        command = " ".join(
            [
                "tippecanoe",
                "-o",
                shlex.quote(remote_out),
                "-l",
                TILE_LAYER,
                *flags,
                shlex.quote(remote_gj),
            ]
        )
        wsl.run(command, quiet=not verbose)
        wsl.pull(remote_out, out_pmtiles)
        wsl.run(f"rm -f {shlex.quote(remote_gj)}")
    finally:
        for leftover in tmpdir.glob("*"):
            leftover.unlink(missing_ok=True)
        tmpdir.rmdir()
    return out_pmtiles


def read_pmtiles_zooms(path: Path) -> tuple[Optional[int], Optional[int]]:
    """Read min/max zoom out of the PMTiles v3 header (bytes 100 and 101).

    tippecanoe's -zg guesses the max zoom, so the only honest source for what the
    archive actually contains is the archive itself.
    """
    with path.open("rb") as handle:
        header = handle.read(128)
    if len(header) < 102 or header[:7] != b"PMTiles":
        return None, None
    return header[100], header[101]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── Manifest ────────────────────────────────────────────────────────────────────


def git_sha() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
        )
        return out.stdout.strip() or None
    except OSError:
        return None


def build_manifest(
    gdf: gpd.GeoDataFrame,
    series_maps: dict[str, dict[str, str]],
    series_labels: dict[str, dict],
    categories: list[str],
    totals: dict[str, Totals],
    curve: dict,
    args: argparse.Namespace,
    tile_path: Optional[Path],
    source_rows: int,
    dropped_duplicates: int,
    polygon_coverage: Optional[float],
) -> dict:
    bounds = gdf.total_bounds
    center = [float((bounds[0] + bounds[2]) / 2), float((bounds[1] + bounds[3]) / 2)]

    if args.tiles_hosting == "release":
        tile_url = args.release_url or (
            f"https://github.com/{PP_ORG or '<PP_ORG>'}/philly-lvt-webmap/releases/"
            f"download/tiles-v1/philadelphia.pmtiles"
        )
    else:
        tile_url = "./philadelphia.pmtiles"

    has_tiles = bool(tile_path and tile_path.exists())
    min_zoom, max_zoom = read_pmtiles_zooms(tile_path) if has_tiles else (None, None)
    tiles = {
        "url": tile_url,
        "hosting": args.tiles_hosting,
        "source_layer": TILE_LAYER,
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "bytes": tile_path.stat().st_size if has_tiles else None,
        "sha256": sha256_of(tile_path) if has_tiles else None,
    }

    scenarios = []
    for scenario in SCENARIOS:
        t = totals[scenario.key]
        scenarios.append(
            {
                "key": scenario.key,
                "label": scenario.label,
                "short": scenario.short,
                "group": scenario.group,
                "default": scenario.default,
                "source_csv": f"analysis/data/{scenario.csv}",
                "attrs": {
                    "current_tax": series_maps["current_tax"][scenario.key],
                    "land_value": series_maps["taxable_land_value"][scenario.key],
                    "improvement_value": series_maps["taxable_improvement_value"][scenario.key],
                },
                "totals": {
                    "sum_land": t.sum_land,
                    "sum_improvement": t.sum_improvement,
                    "revenue": t.revenue,
                    "parcels_modeled": t.parcels_modeled,
                },
                "published": {
                    "land_improvement_ratio": LAND_IMPROVEMENT_RATIO,
                    "land_millage": t.land_millage,
                    "improvement_millage": t.improvement_millage,
                    "land_share": t.land_share,
                },
                "explainer": scenario.explainer,
            }
        )

    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": {
            "repo": "LVTShift",
            "script": "scripts/build_philadelphia_webmap.py",
            "git_sha": git_sha(),
        },
        "city": {
            "name": "Philadelphia",
            "slug": "philadelphia",
            "center": center,
            "bounds": [float(b) for b in bounds],
            "default_zoom": 11.5,
        },
        "build": {
            "mode": "bbox" if args.bbox else ("sample" if args.sample else "full"),
            "bbox": list(resolve_bbox(args.bbox)) if args.bbox else None,
            "sample_every": args.sample,
            "parcel_count": int(len(gdf)),
            "source_rows": source_rows,
            "dropped_duplicate_parcel_ids": dropped_duplicates,
            "geometry": args.geometry,
            "polygon_coverage": polygon_coverage,
            "owner_included": not args.no_owner,
            "dollar_units": "usd",
        },
        "tiles": tiles,
        "attributes": {
            "parcel_id": "pid",
            "category": "cat",
            "exempt": "ex",
            "owner": "own",
            "owner_2": "own2",
            "series": series_labels,
        },
        "categories": [{"code": i, "name": name} for i, name in enumerate(categories)],
        "scenarios": scenarios,
        "stat_curve": curve,
        "color_stops": [
            [None if math.isinf(stop) else stop, color] for stop, color in _COLOR_STOPS
        ],
        "no_data_color": "#bdbdbd",
        "links": {
            "opa_record_template": "https://property.phila.gov/?p={pid9}",
            "lvtshift": "https://github.com/drussellmrichie/LVTShift",
            "plan": (
                "https://github.com/drussellmrichie/LVTShift/blob/main/docs/"
                "PHILADELPHIA_WEBMAP_PLAN.md"
            ),
        },
    }


# ── Orchestration ───────────────────────────────────────────────────────────────


def resolve_bbox(value: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    if not value:
        return None
    if value in BBOX_PRESETS:
        return BBOX_PRESETS[value]
    parts = [float(p) for p in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox takes a preset name or W,S,E,N")
    return tuple(parts)  # type: ignore[return-value]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_SITE, help="site repo root")
    parser.add_argument("--stage", choices=["attrs", "tiles", "all"], default="all")
    parser.add_argument("--bbox", help="preset name (center-city) or W,S,E,N")
    parser.add_argument("--sample", type=int, help="keep every Nth parcel")
    parser.add_argument("--geometry", choices=["point", "polygon"], default="point")
    parser.add_argument("--no-owner", action="store_true", help="drop owner strings from tiles")
    parser.add_argument("--max-zoom", type=int, help="cap tippecanoe max zoom (default: guess)")
    parser.add_argument("--tiles-hosting", choices=["committed", "release"], default="committed")
    parser.add_argument("--release-url", help="explicit tile URL when hosting=release")
    parser.add_argument("--emit-fixture", type=Path, help="write the Python/JS agreement fixture")
    parser.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    print("Loading scenario exports")
    frames = load_scenarios()
    source_rows = len(frames[SCENARIO_KEYS[0]])
    assert_row_alignment(frames)
    print(f"  {source_rows:,} rows x {len(SCENARIOS)} scenarios, row order aligned")

    print("Checking the model reproduces from the exports")
    totals: dict[str, Totals] = {}
    for key in SCENARIO_KEYS:
        totals[key] = assert_millages(key, frames[key])
        assert_new_tax_reconstructs(key, frames[key], totals[key])

    keep = build_keep_mask(frames[SCENARIO_KEYS[0]])
    dropped = int((~keep).sum())
    frames = {k: v.loc[keep].reset_index(drop=True) for k, v in frames.items()}
    print(f"  {len(frames[SCENARIO_KEYS[0]]):,} parcels ({dropped} duplicate ids dropped)")

    print("Deduping series across scenarios")
    attrs = pd.DataFrame({"parcel_id": frames[SCENARIO_KEYS[0]]["parcel_id"].to_numpy()})
    series_maps: dict[str, dict[str, str]] = {}
    series_labels: dict[str, dict] = {}
    for column, (prefix, role_label) in SERIES_ROLES.items():
        attr_series, scenario_attr = dedupe_series(frames, column, prefix)
        series_maps[column] = scenario_attr
        for attr, series in attr_series.items():
            attrs[attr] = series.to_numpy()
            users = [k for k, a in scenario_attr.items() if a == attr]
            series_labels[attr] = {"role": column, "label": role_label, "scenarios": users}
        print(f"  {column:<28} -> {len(attr_series)} distinct ({', '.join(attr_series)})")

    exempt_attrs, exempt_map = dedupe_series(frames, "is_fully_exempt", "ex")
    if len(exempt_attrs) != 1:
        raise AssertionError("is_fully_exempt differs across scenarios; the schema assumes one")
    attrs["ex"] = exempt_attrs["ex0"].to_numpy().astype("uint8")

    category_attrs, _ = dedupe_series(frames, "property_category", "cat")
    if len(category_attrs) != 1:
        raise AssertionError(
            "property_category differs across scenarios after normalization; "
            "check normalize_categories against a fresh export"
        )
    categories = sorted(category_attrs["cat0"].dropna().unique().tolist())
    code_of = {name: i for i, name in enumerate(categories)}
    attrs["cat"] = category_attrs["cat0"].map(code_of).fillna(0).astype("uint8")
    print(f"  property_category            -> {len(categories)} codes")

    numeric = [c for c in attrs.columns if c[:-1] in ("cur", "l", "i")]
    for column in numeric:
        attrs[column] = attrs[column].round(0).astype("int32")
    if int(attrs["parcel_id"].max()) >= 2**31 - 1:
        raise AssertionError("parcel_id exceeds int32; store it as a string instead")
    attrs["pid"] = attrs["parcel_id"].astype("int32")

    wsl: Optional[WslRunner] = None
    needs_wsl = args.geometry == "polygon" or (args.stage in ("tiles", "all") and not args.dry_run)
    if needs_wsl:
        wsl = WslRunner()
        if not wsl.have_tools():
            raise RuntimeError(
                f"tippecanoe/ogr2ogr not found in WSL {WSL_DISTRO}. Install with:\n"
                f"  wsl -d {WSL_DISTRO} -- sudo apt install -y tippecanoe gdal-bin"
            )

    print("Joining geometry")
    gdf, polygon_coverage = join_geometry(attrs, args.geometry, wsl=wsl)
    gdf = gdf.rename(columns={"owner_1": "own", "owner_2": "own2"})

    bbox = resolve_bbox(args.bbox)
    if bbox:
        west, south, east, north = bbox
        # Centroid rather than raw x/y: geometry may be a mix of points and
        # polygons in --geometry polygon mode, and a point's own centroid is
        # itself, so this filters both consistently.
        center = gdf.geometry.centroid
        gdf = gdf[(center.x >= west) & (center.x <= east) & (center.y >= south) & (center.y <= north)]
        print(f"  bbox {bbox}: {len(gdf):,} parcels")
    if args.sample:
        gdf = gdf.iloc[:: args.sample]
        print(f"  sample every {args.sample}: {len(gdf):,} parcels")

    print("Computing the stat curve")
    solve_sets = {}
    for key in SCENARIO_KEYS:
        mask = gdf["ex"].to_numpy() == 0
        a = series_maps["taxable_land_value"][key]
        b = series_maps["taxable_improvement_value"][key]
        c = series_maps["current_tax"][key]
        solve_sets[key] = {
            "land": gdf[a].to_numpy()[mask].astype("float64"),
            "improvement": gdf[b].to_numpy()[mask].astype("float64"),
            "current": gdf[c].to_numpy()[mask].astype("float64"),
        }
    curve_totals = totals if not (bbox or args.sample) else recompute_totals(solve_sets, totals)
    curve = compute_stat_curve(solve_sets, curve_totals)
    assert_interpolation_error(curve, solve_sets, curve_totals)

    tile_attrs = ["pid", "cat", "ex", *numeric_attr_names(series_labels)]
    if not args.no_owner:
        tile_attrs += ["own", "own2"]

    tile_path = args.out / "philadelphia.pmtiles"
    if args.stage in ("tiles", "all") and not args.dry_run:
        print("Building tiles in WSL")
        extra_flags = None
        if args.geometry == "polygon":
            # Denser geometry than points; simplify to keep byte size sane and
            # coalesce tiny slivers (condo stacks, alley remnants) at low zoom.
            extra_flags = list(_TIPPECANOE_BASE_ARGS) + [
                "--simplification=4",
                "--coalesce-densest-as-needed",
            ]
        build_pmtiles_via_wsl(
            gdf, tile_path, wsl, tile_attrs, max_zoom=args.max_zoom, tippecanoe_args=extra_flags
        )
        size_mb = tile_path.stat().st_size / 1e6
        print(f"  {tile_path.name}: {size_mb:.1f} MB")
        report_size_budget(size_mb, args)
    else:
        tile_path = tile_path if tile_path.exists() else None

    manifest = build_manifest(
        gdf,
        series_maps,
        series_labels,
        categories,
        curve_totals,
        curve,
        args,
        tile_path,
        source_rows,
        dropped,
        polygon_coverage,
    )
    if args.dry_run:
        print("\n[dry run] manifest not written")
    else:
        args.out.mkdir(parents=True, exist_ok=True)
        manifest_path = args.out / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"  wrote {manifest_path} ({manifest_path.stat().st_size / 1024:.0f} KB)")

    if args.emit_fixture and not args.dry_run:
        print("Emitting the Python/JS agreement fixture")
        emit_fixture(args.emit_fixture, gdf, series_maps, curve_totals, categories)

    return 0


def numeric_attr_names(series_labels: dict[str, dict]) -> list[str]:
    return sorted(series_labels.keys())


def recompute_totals(solve_sets, totals: dict[str, Totals]) -> dict[str, Totals]:
    """Slices need their own revenue-neutral solve; the full-city one does not apply."""
    out: dict[str, Totals] = {}
    for key, arrays in solve_sets.items():
        sum_land = float(arrays["land"].sum())
        sum_improvement = float(arrays["improvement"].sum())
        revenue = float(arrays["current"].sum())
        denominator = sum_improvement + LAND_IMPROVEMENT_RATIO * sum_land
        improvement_millage = revenue * 1000 / denominator if denominator > 0 else 0.0
        out[key] = Totals(
            sum_land=sum_land,
            sum_improvement=sum_improvement,
            revenue=revenue,
            parcels_modeled=int(arrays["land"].size),
            land_millage=LAND_IMPROVEMENT_RATIO * improvement_millage,
            improvement_millage=improvement_millage,
            land_share=LAND_IMPROVEMENT_RATIO * sum_land / denominator if denominator else 0.0,
        )
        print(f"  {key}: slice re-solved to {out[key].land_millage:.4f} / {improvement_millage:.4f}")
    return out


def report_size_budget(size_mb: float, args: argparse.Namespace) -> None:
    if size_mb > 90:
        print(
            f"  ! {size_mb:.1f} MB exceeds the 90 MB committed budget "
            f"(GitHub hard-blocks 100 MB and does not resolve LFS on Pages).\n"
            f"    Next rungs: --max-zoom 14, then --no-owner. If it still will not fit, "
            f"rebuild with --tiles-hosting release and upload:\n"
            f"      gh release upload tiles-v1 philadelphia.pmtiles"
        )
    elif size_mb > 50:
        print(f"  note: {size_mb:.1f} MB is over GitHub's 50 MB warning threshold but committable")


def color_index(pct: Optional[float]) -> int:
    """Bucket index under MapLibre `step` semantics (pct < stop), or -1 for no data.

    solve.js follows the same convention: the GPU expression is what actually
    colors the map, so the scalar path matches it rather than Python's
    `_color_for`, which uses <= and therefore differs only on exact boundaries.
    """
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return -1
    for index, (stop, _) in enumerate(_COLOR_STOPS):
        if pct < stop:
            return index
    return len(_COLOR_STOPS) - 1


def select_fixture_parcels(gdf, series_maps, categories, count: int = 200) -> list[int]:
    """Positional indices spanning every edge case the model can produce.

    A uniform random sample would miss the rows most likely to break agreement:
    zero current bills (undefined percent change), zero land or zero improvement
    value, the fully-exempt set, and the extremes of the value distribution.
    """
    chosen: list[int] = []
    seen: set[int] = set()

    def take(mask: np.ndarray, limit: int) -> None:
        for position in np.flatnonzero(mask)[:limit]:
            if position not in seen:
                seen.add(int(position))
                chosen.append(int(position))

    for key in SCENARIO_KEYS:
        current = gdf[series_maps["current_tax"][key]].to_numpy()
        land = gdf[series_maps["taxable_land_value"][key]].to_numpy()
        improvement = gdf[series_maps["taxable_improvement_value"][key]].to_numpy()
        take(current <= 0, 4)
        take((land == 0) & (current > 0), 4)
        take((improvement == 0) & (current > 0), 4)
        take(current == current.max(), 1)
        take(land == land.max(), 1)
        take(improvement == improvement.max(), 1)

    take(gdf["ex"].to_numpy() == 1, 6)
    for code in range(len(categories)):
        take(gdf["cat"].to_numpy() == code, 2)

    remaining = count - len(chosen)
    if remaining > 0:
        rng = np.random.default_rng(0)
        pool = np.setdiff1d(np.arange(len(gdf)), np.array(sorted(seen), dtype=int))
        for position in rng.choice(pool, size=min(remaining, pool.size), replace=False):
            chosen.append(int(position))
    return chosen


def emit_fixture(
    path: Path,
    gdf: gpd.GeoDataFrame,
    series_maps: dict[str, dict[str, str]],
    totals: dict[str, Totals],
    categories: list[str],
) -> None:
    """Write the ground-truth fixture the Node agreement test checks solve.js against.

    Values are the integer-rounded tile attributes, not the raw CSV floats, because
    those integers are exactly what the browser reads out of the vector tiles.
    """
    positions = select_fixture_parcels(gdf, series_maps, categories)
    pids = gdf["pid"].to_numpy()
    cats = gdf["cat"].to_numpy()
    exempt = gdf["ex"].to_numpy()

    scenarios: dict[str, dict] = {}
    for key in SCENARIO_KEYS:
        total = totals[key]
        current = gdf[series_maps["current_tax"][key]].to_numpy()
        land = gdf[series_maps["taxable_land_value"][key]].to_numpy()
        improvement = gdf[series_maps["taxable_improvement_value"][key]].to_numpy()
        cases = [0.0, 0.25, round(total.land_share, 10), 0.75, 1.0]
        case_millages = [
            {"landShare": s, "landMillage": m[0], "impMillage": m[1]}
            for s, m in ((s, solve_millages(total, s)) for s in cases)
        ]

        parcels = []
        for position in positions:
            expected = []
            for share in cases:
                land_millage, improvement_millage = solve_millages(total, share)
                new_tax = max(0.0, float(land[position]) * land_millage / 1000) + max(
                    0.0, float(improvement[position]) * improvement_millage / 1000
                )
                pct = (
                    (new_tax - float(current[position])) / float(current[position]) * 100
                    if current[position] > 0
                    else None
                )
                # Rounded to 6 decimals: far tighter than the 1e-6 tolerance the
                # Node test asserts, and it roughly halves the committed fixture.
                expected.append(
                    {
                        "landShare": share,
                        "newTax": round(new_tax, 6),
                        "pct": None if pct is None else round(pct, 6),
                        "colorIndex": color_index(pct),
                    }
                )
            parcels.append(
                {
                    "pid": int(pids[position]),
                    "cat": int(cats[position]),
                    "ex": int(exempt[position]),
                    "cur": int(current[position]),
                    "l": int(land[position]),
                    "i": int(improvement[position]),
                    "expected": expected,
                }
            )

        scenarios[key] = {
            "attrs": {
                "current_tax": series_maps["current_tax"][key],
                "land_value": series_maps["taxable_land_value"][key],
                "improvement_value": series_maps["taxable_improvement_value"][key],
            },
            "totals": {
                "sumLand": total.sum_land,
                "sumImp": total.sum_improvement,
                "revenue": total.revenue,
            },
            "published": {
                "ratio": LAND_IMPROVEMENT_RATIO,
                "landShare": total.land_share,
                "landMillage": total.land_millage,
                "impMillage": total.improvement_millage,
            },
            "cases": case_millages,
            "parcels": parcels,
        }

    payload = {
        "schema_version": 1,
        "source": "scripts/build_philadelphia_webmap.py --emit-fixture",
        "color_stops": [
            [None if math.isinf(stop) else stop, color] for stop, color in _COLOR_STOPS
        ],
        "no_data_color": "#bdbdbd",
        "scenarios": scenarios,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(
        f"  wrote {path} ({path.stat().st_size / 1024:.0f} KB, "
        f"{len(positions)} parcels x {len(SCENARIO_KEYS)} scenarios)"
    )


if __name__ == "__main__":
    raise SystemExit(main())
