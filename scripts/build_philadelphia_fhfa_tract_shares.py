"""Put FHFA's tract land-price estimates for Philadelphia onto 2020 census tracts.

Source: the FHFA land-price dataset (Davis, Larson, Oliner & Shui, "The Price of Residential Land
for Counties, ZIP Codes, and Census Tracts in the United States", FHFA Working Paper 19-01),
June 2024 release, "Cross-Section Census Tracts" sheet: pooled 2012-2022 estimates for the land
under single-family homes, in 2015 dollars. https://www.fhfa.gov/research/papers/wp1901

**FHFA's tracts are 2010 census tracts; everything here joins on 2020 tracts.** Every
Philadelphia id in the release is a valid 2010 tract, and nine are not valid 2020 tracts, because
the 2020 census split them. Parcels carry 2020 block groups (`std_geoid`) and
`census_tracts.gpq` holds the 408 2020 tracts. Joining FHFA's ids to them directly loses the
nine split tracts. It also joins the rest on an id match, and an id Census reused in 2020 is not
always the same area.

The crosswalk is the Census Bureau's 2020-to-2010 tract relationship file, which gives the land
area of each piece where a 2020 tract and a 2010 tract overlap. A 2020 tract takes the
land-area-weighted mean of the FHFA values of the 2010 tracts it overlaps that FHFA covers. It
gets a value only when those covered tracts hold at least `MIN_COVERED_LAND_FRAC` of its land;
otherwise it is left unestimated, as FHFA left the uncovered tract. Almost every 2020 tract lies
wholly inside one 2010 tract, so for nearly all of them this is a plain copy (a split tract's
parts each take the parent's value); the weighting matters only in the few that straddle a
boundary, and `fhfa_covered_land_frac` / `fhfa_source_tracts_2010` show which.

Output: cities/philadelphia/data/fhfa_land_share_by_tract.csv, one row per 2020 tract with an
estimate. `tract_geoid` and `fhfa_land_share` are the columns every consumer reads.

Usage:
    python scripts/build_philadelphia_fhfa_tract_shares.py
    python scripts/build_philadelphia_fhfa_tract_shares.py --force   # re-download both sources
"""
from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities/philadelphia/data"

FHFA_URL = "https://www.fhfa.gov/document/land-prices_2024_20_june.xlsx"
FHFA_XLSX = DATA_DIR / "fhfa_land_prices_2024_06.xlsx"
FHFA_SHEET = "Cross-Section Census Tracts"
REL_URL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_st42.txt"
REL_TXT = DATA_DIR / "census_tract_rel_2020_2010_pa.txt"
OUTPUT = DATA_DIR / "fhfa_land_share_by_tract.csv"

COUNTY_GEOID = "42101"
ACRE_TO_SQFT = 43_560
# A 2020 tract gets an estimate only if FHFA-covered 2010 tracts hold at least this share of its
# land: past a majority, most of its single-family homes sit in a tract FHFA did not estimate.
MIN_COVERED_LAND_FRAC = 0.5

VALUE_COLS = {
    "Land Share of Property Value": "fhfa_land_share",
    "Land Value\n(Per Acre, As-Is)": "fhfa_land_value_per_acre",
    "Property Value (As-is)": "fhfa_property_value",
}


def fetch(url: str, path: Path, force: bool) -> Path:
    if force or not path.exists():
        print(f"Downloading {url}")
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return path


def load_fhfa(path: Path) -> pd.DataFrame:
    x = pd.read_excel(path, sheet_name=FHFA_SHEET, header=1)
    x = x[(x["State"] == "Pennsylvania") & (x["County"] == "Philadelphia County")]
    out = x[list(VALUE_COLS)].rename(columns=VALUE_COLS)
    out.insert(0, "tract_2010", x["Census Tract"].astype("int64").astype(str).str.zfill(11))
    if out.tract_2010.duplicated().any():
        raise ValueError("FHFA sheet repeats a Philadelphia tract")
    return out.reset_index(drop=True)


def load_relationship(path: Path) -> pd.DataFrame:
    r = pd.read_csv(path, sep="|", dtype=str, encoding="utf-8-sig")
    r = r[r.GEOID_TRACT_20.fillna("").str.startswith(COUNTY_GEOID)]
    r = r.assign(land_part=r.AREALAND_PART.astype(float))
    return r[["GEOID_TRACT_20", "GEOID_TRACT_10", "land_part"]].rename(
        columns={"GEOID_TRACT_20": "tract_geoid", "GEOID_TRACT_10": "tract_2010"})


def crosswalk(fhfa: pd.DataFrame, rel: pd.DataFrame) -> pd.DataFrame:
    tracts_2010 = set(rel.tract_2010.dropna())
    stray = sorted(set(fhfa.tract_2010) - tracts_2010)
    if stray:
        raise ValueError(f"FHFA tracts that are not 2010 Philadelphia tracts: {stray}")

    pieces = rel[rel.land_part > 0].merge(fhfa, on="tract_2010", how="left")
    covered = pieces.fhfa_land_share.notna()
    total_land = pieces.groupby("tract_geoid").land_part.sum()
    cov = pieces[covered]
    w = cov.land_part
    out = pd.DataFrame({"fhfa_covered_land_frac": cov.groupby("tract_geoid").land_part.sum() / total_land})
    for col in VALUE_COLS.values():
        out[col] = (cov[col] * w).groupby(cov.tract_geoid).sum() / w.groupby(cov.tract_geoid).sum()
    out["fhfa_source_tracts_2010"] = cov.groupby("tract_geoid").tract_2010.agg(lambda s: " ".join(sorted(s)))
    out = out.dropna(subset=["fhfa_land_share"])
    out = out[out.fhfa_covered_land_frac >= MIN_COVERED_LAND_FRAC].reset_index()

    out["fhfa_land_share"] = out.fhfa_land_share.round(4)
    out["fhfa_land_price_psf"] = (out.pop("fhfa_land_value_per_acre") / ACRE_TO_SQFT).round(2)
    out["fhfa_property_value"] = out.fhfa_property_value.round(-2)
    out["fhfa_covered_land_frac"] = out.fhfa_covered_land_frac.round(3)
    return out[["tract_geoid", "fhfa_land_share", "fhfa_land_price_psf", "fhfa_property_value",
                "fhfa_covered_land_frac", "fhfa_source_tracts_2010"]].sort_values("tract_geoid")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="re-download the FHFA and Census files")
    args = ap.parse_args()

    fhfa = load_fhfa(fetch(FHFA_URL, FHFA_XLSX, args.force))
    rel = load_relationship(fetch(REL_URL, REL_TXT, args.force))
    out = crosswalk(fhfa, rel)

    if not set(out.tract_geoid) <= set(rel.tract_geoid):
        raise AssertionError("output holds a tract that is not a 2020 Philadelphia tract")
    used = set(" ".join(out.fhfa_source_tracts_2010).split())
    # Most multi-tract rows are boundary slivers; count the ones where a second tract matters.
    land = rel[rel.land_part > 0]
    main_frac = land.groupby("tract_geoid").land_part.max() / land.groupby("tract_geoid").land_part.sum()
    mixed = out.tract_geoid.map(main_frac) < 0.95
    print(f"FHFA: {len(fhfa)} 2010 tracts -> {len(out)} of {rel.tract_geoid.nunique()} 2020 tracts "
          f"(threshold: covered tracts hold >= {MIN_COVERED_LAND_FRAC:.0%} of the 2020 tract's land)")
    print(f"  {int((~mixed).sum())} have >= 95% of their land in one 2010 tract; {int(mixed.sum())} draw "
          f"more than 5% from others ({', '.join(out.tract_geoid[mixed])})")
    unused = sorted(set(fhfa.tract_2010) - used)
    print(f"  FHFA tracts reaching no 2020 tract: {unused if unused else 'none'}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT, index=False)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
