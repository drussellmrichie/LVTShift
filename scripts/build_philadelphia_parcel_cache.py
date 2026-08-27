"""Build the shared Philadelphia parcel cache for a given assessment (tax) year.

`cities/philadelphia/data/parcels_ty<YEAR>.gpq` is read by every Philadelphia notebook.
It joins the year-specific taxable values from Carto's `assessments` history table to the
current `opa_properties_public` table for geometry, category codes, owner names, PIN and
lot area.

**Assessment vintage is load-bearing.** `opa_properties_public` always carries the *latest*
assessment year, so taking taxable values from it silently models the wrong billing year.
Always pull taxable values from `assessments WHERE year = '<YEAR>'`. Note the column is
varchar — the year must be quoted or Carto returns HTTP 400.

The cache must always emit the full column superset, because different notebooks need
different parts of it:
  - taxable_land / taxable_building / market_value / exempt_land / exempt_building — all models
  - pin + total_area — the LYCD notebooks' lot-area chain
  - owner_1 + owner_2 — the owner-concentration analysis in model.ipynb
`pin` is kept integer-typed: the LYCD notebooks stringify it as a join key, and a float
dtype would append '.0' and break the match against the DOR PIN areas.

Usage:
    python scripts/build_philadelphia_parcel_cache.py --year 2026
    python scripts/build_philadelphia_parcel_cache.py --year 2027 --force
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.parse
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

CARTO = "https://phl.carto.com/api/v2/sql"
OUT_DIR = Path("cities/philadelphia/data")

VALUE_COLS = [
    "taxable_land",
    "taxable_building",
    "market_value",
    "exempt_land",
    "exempt_building",
]


def _carto_csv(query: str, timeout: int = 600) -> pd.DataFrame:
    url = f"{CARTO}?q={urllib.parse.quote(query)}&format=csv"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), low_memory=False)


def build(year: int, force: bool = False) -> Path:
    out = OUT_DIR / f"parcels_ty{year}.gpq"
    if out.exists() and not force:
        print(f"{out} already exists — pass --force to rebuild")
        return out

    print(f"Downloading assessments for tax year {year} ...")
    assessments = _carto_csv(
        "SELECT parcel_number, " + ", ".join(VALUE_COLS) +
        f" FROM assessments WHERE year = '{year}'"     # quoted: the column is varchar
    )
    assessments["parcel_number"] = assessments["parcel_number"].astype(str)
    print(f"  {len(assessments):,} parcels in assessment year {year}")

    print("Downloading current OPA properties (geometry, class, owner, PIN, lot area) ...")
    opa = _carto_csv(
        "SELECT parcel_number, pin, category_code, total_area, owner_1, owner_2, the_geom "
        "FROM opa_properties_public"
    )
    opa["parcel_number"] = opa["parcel_number"].astype(str)
    print(f"  {len(opa):,} parcels in current OPA")

    merged = assessments.merge(opa, on="parcel_number", how="inner")
    print(f"  {len(merged):,} parcels after join")

    gdf = gpd.GeoDataFrame(
        merged,
        geometry=gpd.GeoSeries.from_wkb(merged["the_geom"], crs="EPSG:4326"),
        crs="EPSG:4326",
    ).drop(columns=["the_geom"], errors="ignore")
    gdf = gdf[gdf["geometry"].notna()].copy()
    print(f"  {len(gdf):,} parcels with geometry")

    for col in VALUE_COLS + ["total_area"]:
        gdf[col] = pd.to_numeric(gdf[col], errors="coerce").fillna(0.0)
    gdf["pin"] = pd.to_numeric(gdf["pin"], errors="coerce").astype("Int64")

    missing = {"parcel_number", "pin", "category_code", "total_area", "owner_1", "owner_2",
               *VALUE_COLS} - set(gdf.columns)
    if missing:
        raise RuntimeError(f"cache is missing required columns: {sorted(missing)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out)
    base = gdf["taxable_land"].sum() + gdf["taxable_building"].sum()
    print(f"Wrote {out}")
    print(f"  taxable base ${base/1e9:.3f}B "
          f"(land ${gdf['taxable_land'].sum()/1e9:.2f}B + bldg ${gdf['taxable_building'].sum()/1e9:.2f}B)")
    print(f"  fully exempt parcels: {int(((gdf['taxable_land'] + gdf['taxable_building']) <= 0).sum()):,}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, help="assessment/tax year, e.g. 2026")
    ap.add_argument("--force", action="store_true", help="rebuild even if the cache exists")
    args = ap.parse_args()
    build(args.year, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
