"""Fetch the two extra Philadelphia layers the underused-land site ranking needs.

`scripts/analyze_philly_lvt_opportunity.py` needs two inputs that no other part
of the repo builds:

  opa_building_area.parquet  OPA `total_livable_area` per parcel. This is the
                             numerator of the floor-area ratio that separates a
                             one-storey store on a parking apron from a
                             rowhouse, and it is the only reason the ranking can
                             see underuse that the vacant/parking layers cannot.
                             Coverage is 97-100% on every improved category and
                             ~0% on vacant land, which is correct rather than
                             missing: a vacant parcel has no floor area.

  neighborhoods.gpq          Neighborhood polygons, used only to give each
                             ranked site a human-readable name. Nothing
                             numerical depends on it.

Both come from City of Philadelphia open data and are gitignored like every
other cached layer, so this script is how they get rebuilt from scratch. It is
idempotent — re-running overwrites in place. Pass --force to refetch a layer
that already exists.

Note the Azavea `geo-data` neighborhood GeoJSON that older write-ups point at is
gone (404); the City's own FeatureServer below is the live source.

Outputs (gitignored, under cities/philadelphia/data/):
  opa_building_area.parquet
  neighborhoods.gpq
"""

import io
import sys
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities" / "philadelphia" / "data"

CARTO_SQL = "https://phl.carto.com/api/v2/sql"
NEIGHBORHOODS = (
    "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
    "/Philadelphia_Neighborhoods/FeatureServer/0/query"
)

# opa_properties_public is ~583K rows. A four-column pull of the whole table is
# heavy enough that Carto can time out on a single request, so it is paged. The
# ORDER BY is required, not cosmetic: LIMIT/OFFSET paging over an unordered
# result set can repeat or drop rows between pages.
PAGE_SIZE = 100_000


def fetch_building_area() -> pd.DataFrame:
    frames, offset = [], 0
    while True:
        query = (
            "SELECT parcel_number, total_livable_area, total_area, number_stories "
            "FROM opa_properties_public "
            f"ORDER BY parcel_number LIMIT {PAGE_SIZE} OFFSET {offset}"
        )
        resp = requests.get(
            CARTO_SQL, params={"q": query, "format": "csv"}, timeout=300
        )
        resp.raise_for_status()
        page = pd.read_csv(io.StringIO(resp.text))
        if page.empty:
            break
        frames.append(page)
        offset += PAGE_SIZE
        print(f"  fetched {offset:,}", flush=True)
        if len(page) < PAGE_SIZE:
            break
        time.sleep(0.3)
    return pd.concat(frames, ignore_index=True)


def fetch_neighborhoods() -> gpd.GeoDataFrame:
    resp = requests.get(
        NEIGHBORHOODS,
        params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson"},
        timeout=120,
    )
    resp.raise_for_status()
    return gpd.read_file(io.StringIO(resp.text))


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    force = "--force" in sys.argv

    area_path = DATA_DIR / "opa_building_area.parquet"
    if area_path.exists() and not force:
        print(f"skip {area_path.name} (exists; --force to refetch)")
    else:
        print("Fetching OPA building area ...")
        area = fetch_building_area()
        area.to_parquet(area_path)
        covered = area["total_livable_area"].gt(0).sum()
        print(f"  {len(area):,} parcels, {covered:,} with floor area "
              f"({covered/len(area):.1%})")
        print(f"  wrote {area_path}")

    hood_path = DATA_DIR / "neighborhoods.gpq"
    if hood_path.exists() and not force:
        print(f"skip {hood_path.name} (exists; --force to refetch)")
    else:
        print("Fetching Philadelphia neighborhoods ...")
        hoods = fetch_neighborhoods()
        hoods.to_parquet(hood_path)
        print(f"  {len(hoods):,} neighborhood polygons, {hoods.crs}")
        print(f"  wrote {hood_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
