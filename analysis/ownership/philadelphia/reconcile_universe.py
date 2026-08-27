"""Cross-check the vacant-land and parking universes against independent city sources.

The ownership shares are only as good as the parcel sets they are computed over, and
"vacant" has three different official definitions in Philadelphia that do not agree:

  - **OPA assessor building codes** (`S*` bare land, `R*` parking) — what this analysis uses,
    because it is what the tax model actually bills.
  - **L&I Vacant Indicators** — the city's blight/code-enforcement vacancy list, cached at
    `cities/philadelphia/data/vacant_land_lni.gpq`. Note this file is an orphan: no script in
    the repo builds it, so it is used here as corroboration only, never as an input.
  - **City Land Use, 2025** — `c_dig3 = 911 Vacant Parcels` and `514 Transportation Parking`
    on the public FeatureServer. Polygon geometry with no parcel key, so matching needs a
    spatial join against parcel centroids.

Disagreement between them is a finding to report, not a bug to hide. This writes
`results/universe_reconciliation.csv`.

Usage:
    python analysis/ownership/philadelphia/reconcile_universe.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from lvt.philadelphia import parcel_cache_path  # noqa: E402

RESULTS = HERE / "results"
LAND_USE = ("https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/"
            "Land_Use/FeatureServer/0/query")
LNI = REPO / "cities/philadelphia/data/vacant_land_lni.gpq"
PARKING_ORPHAN = REPO / "cities/philadelphia/data/surface_parking_opa.gpq"


def fetch_land_use(where: str) -> gpd.GeoDataFrame:
    """Page through the Land Use layer for a where clause.

    Use the 2-digit `c_dig2` for vacancy, not `c_dig3`. The 3-digit field is only sparsely
    populated: `c_dig2 = 91` returns 36,646 features while `c_dig3 = 911` returns 7,198, so
    filtering on the 3-digit code silently drops 80% of the city's vacant land.
    """
    frames, offset = [], 0
    while True:
        r = requests.get(LAND_USE, params={
            "where": where, "outFields": "c_dig2,c_dig3", "returnGeometry": "true",
            "outSR": 4326, "f": "geojson", "resultOffset": offset,
            "resultRecordCount": 2000,
        }, timeout=180)
        r.raise_for_status()
        gj = r.json()
        feats = gj.get("features", [])
        if not feats:
            break
        frames.append(gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326"))
        offset += len(feats)
        print(f"    fetched {offset:,} land-use polygons", end="\r")
        # In GeoJSON responses ArcGIS puts this flag at the TOP level, not under
        # `properties` — reading it from the wrong place silently stops paging after the
        # first page and quietly understates every downstream overlap.
        more = gj.get("exceededTransferLimit") or gj.get("properties", {}).get(
            "exceededTransferLimit")
        if not more and len(feats) < 2000:
            break
        time.sleep(0.2)
    print()
    return pd.concat(frames, ignore_index=True) if frames else gpd.GeoDataFrame()


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    rows = []

    print("Loading parcel geometry...")
    parcels = gpd.read_parquet(parcel_cache_path(2026, REPO / "cities/philadelphia/data"))
    attrs = pd.read_parquet(HERE / "opa_attributes.parquet")
    for d in (parcels, attrs):
        d["k"] = d["parcel_number"].astype(str).str.lstrip("0")
    parcels = parcels.drop_duplicates("k").merge(
        attrs.drop(columns="parcel_number").drop_duplicates("k"), on="k", how="left")
    code = parcels["building_code"].fillna("").astype(str).str.upper()

    opa_vacant = code.str.match(r"^S[A-Z]$")
    opa_parking = code.isin(["RA", "RB", "RE"]) | code.str.match(r"^R[A-F]\d$")
    print(f"  OPA vacant (S* codes):   {opa_vacant.sum():,}")
    print(f"  OPA parking (R* codes):  {opa_parking.sum():,}")

    # --- L&I vacant indicators -------------------------------------------------------
    if LNI.exists():
        lni = gpd.read_parquet(LNI)
        lni_ids = set(lni["opa_id"].astype(str).str.lstrip("0"))
        opa_ids = set(parcels.loc[opa_vacant, "k"])
        rows.append({
            "universe": "Vacant land",
            "source_a": "OPA building codes (S*)", "count_a": len(opa_ids),
            "source_b": "L&I Vacant Indicators", "count_b": len(lni_ids),
            "overlap": len(opa_ids & lni_ids),
            "a_not_b": len(opa_ids - lni_ids), "b_not_a": len(lni_ids - opa_ids),
            "jaccard": len(opa_ids & lni_ids) / len(opa_ids | lni_ids),
        })
        print(f"  L&I vacant:              {len(lni_ids):,} "
              f"(overlap {len(opa_ids & lni_ids):,})")
    else:
        print(f"  SKIP L&I — {LNI.name} not present")

    # --- orphaned OPA surface-parking extract ----------------------------------------
    if PARKING_ORPHAN.exists():
        orph = gpd.read_parquet(PARKING_ORPHAN)
        o_ids = set(orph["parcel_number"].astype(str).str.lstrip("0"))
        p_ids = set(parcels.loc[opa_parking, "k"])
        rows.append({
            "universe": "Surface parking",
            "source_a": "OPA building codes (R*)", "count_a": len(p_ids),
            "source_b": "surface_parking_opa.gpq (orphan)", "count_b": len(o_ids),
            "overlap": len(p_ids & o_ids),
            "a_not_b": len(p_ids - o_ids), "b_not_a": len(o_ids - p_ids),
            "jaccard": len(p_ids & o_ids) / len(p_ids | o_ids),
        })
        print(f"  orphan parking extract:  {len(o_ids):,} "
              f"(overlap {len(p_ids & o_ids):,})")

    # --- city Land Use 2025 ----------------------------------------------------------
    print("Fetching City Land Use 2025 (c_dig2=91 vacant, c_dig3=514 parking)...")
    lu = fetch_land_use("c_dig2 = 91 OR c_dig3 = 514")
    if len(lu):
        cent = parcels[["k", "geometry"]].copy()
        cent["geometry"] = cent.geometry.representative_point()
        joined = gpd.sjoin(cent.to_crs(4326), lu.to_crs(4326), how="left", predicate="within")
        joined = joined.drop_duplicates("k")
        parcels["lu_d2"] = parcels["k"].map(joined.set_index("k")["c_dig2"])
        parcels["lu_d3"] = parcels["k"].map(joined.set_index("k")["c_dig3"])
        checks = [
            ("Vacant land", opa_vacant, parcels["lu_d2"] == 91, "City Land Use 2025 (c_dig2=91)"),
            ("Surface parking", opa_parking, parcels["lu_d3"] == 514,
             "City Land Use 2025 (c_dig3=514)"),
        ]
        for label, mask, lu_mask, src in checks:
            a = set(parcels.loc[mask, "k"])
            b = set(parcels.loc[lu_mask.fillna(False), "k"])
            rows.append({
                "universe": label,
                "source_a": "OPA building codes", "count_a": len(a),
                "source_b": src, "count_b": len(b),
                "overlap": len(a & b), "a_not_b": len(a - b), "b_not_a": len(b - a),
                "jaccard": len(a & b) / len(a | b) if (a | b) else float("nan"),
            })
            print(f"  {src}: {len(b):,} parcels (overlap with OPA {len(a & b):,})")

    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "universe_reconciliation.csv", index=False)
    print("\n" + out.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    print(f"\nWrote {RESULTS / 'universe_reconciliation.csv'}")


if __name__ == "__main__":
    main()
