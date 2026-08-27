"""Fetch real parcel footprints for Philadelphia's surface parking lots.

Joins on PWD_PARCELS.brt_id == OPA parcel_number. Geometry is requested in WGS84
(outSR=4326); the service's Shape__Area is deliberately ignored (EPSG:3857 area
distortion — see CLAUDE.md), lot area comes from OPA total_area instead.
"""

import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
import requests
from shapely.geometry import shape

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities" / "philadelphia" / "data"
PWD_PARCELS = (
    "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
    "/PWD_PARCELS/FeatureServer/0"
)
CHUNK = 120


def main() -> int:
    parking = gpd.read_parquet(DATA_DIR / "surface_parking_opa.gpq")
    brt_ids = sorted(parking["parcel_number"].astype(str).str.zfill(9).unique())
    print(f"looking up footprints for {len(brt_ids):,} parking parcels")

    records = []
    for i in range(0, len(brt_ids), CHUNK):
        chunk = brt_ids[i : i + CHUNK]
        in_list = ",".join(f"'{b}'" for b in chunk)
        params = {
            "where": f"brt_id IN ({in_list})",
            "outFields": "brt_id,address,bldg_desc,gross_area",
            "outSR": 4326,
            "f": "geojson",
        }
        # POST, not GET: a 120-id IN clause overruns the server's URL length limit
        resp = requests.post(f"{PWD_PARCELS}/query", data=params, timeout=120)
        resp.raise_for_status()
        for feat in resp.json().get("features", []):
            if feat.get("geometry") is None:
                continue
            row = dict(feat.get("properties") or {})
            row["geometry"] = shape(feat["geometry"])
            records.append(row)
        print(f"  {i + len(chunk):,}/{len(brt_ids):,} -> {len(records):,} polygons", flush=True)
        time.sleep(0.15)

    gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")
    gdf["brt_id"] = gdf["brt_id"].astype(str).str.strip().str.zfill(9)
    gdf = gdf.drop_duplicates(subset="brt_id")

    # Carry OPA true-ground area across
    area = parking.set_index(
        parking["parcel_number"].astype(str).str.zfill(9)
    )["total_area"]
    gdf["total_area"] = gdf["brt_id"].map(area)

    hit = len(gdf) / len(brt_ids)
    print(f"matched {len(gdf):,} / {len(brt_ids):,} ({hit:.1%})")
    gdf.to_parquet(DATA_DIR / "surface_parking_polygons.gpq")
    print(f"wrote {DATA_DIR / 'surface_parking_polygons.gpq'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
