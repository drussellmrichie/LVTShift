"""Fetch Philadelphia vacant-land and surface-parking layers for the PPI donate-page map.

Sources (all City of Philadelphia open data — no OSM, so no ODbL attribution burden
on the published image):
  - L&I Vacant_Indicators_Land (ArcGIS)  -> vacant lots, polygon geometry, opa_id key
  - OPA opa_properties_public (Carto)    -> surface parking lots via building_code_description

Lot areas come from OPA `total_area` (true ground square feet), NEVER from an ArcGIS
`Shape__Area`. The DOR/PHL services are served in EPSG:3857, where area is inflated by
1/cos^2(latitude) ~= 1.704x at Philadelphia's latitude. See CLAUDE.md.

Outputs (gitignored, under cities/philadelphia/data/):
  vacant_land_lni.gpq      polygons, WGS84
  surface_parking_opa.gpq  polygons where DOR geometry resolves, else OPA centroid
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import shape

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities" / "philadelphia" / "data"

LNI_VACANT_LAND = (
    "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
    "/Vacant_Indicators_Land/FeatureServer/0"
)
CARTO_SQL = "https://phl.carto.com/api/v2/sql"

# Only 'PKG LOT' codes. Matching on 'GAR' would catch 100,450 ROW B/GAR rowhouses,
# and category_code 7/8 garages are structures, not surface lots.
PARKING_LIKE = "%PKG LOT%"


def fetch_arcgis_layer(url: str, out_fields: str = "*", page_size: int = 2000) -> gpd.GeoDataFrame:
    """Page through an ArcGIS FeatureServer layer, returning WGS84 geometry."""
    offset = 0
    records = []
    while True:
        params = {
            "where": "1=1",
            "outFields": out_fields,
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        resp = requests.get(f"{url}/query?{urlencode(params)}", timeout=120)
        resp.raise_for_status()
        payload = resp.json()
        feats = payload.get("features", [])
        if not feats:
            break
        for feat in feats:
            if feat.get("geometry") is None:
                continue
            row = dict(feat.get("properties") or {})
            row["geometry"] = shape(feat["geometry"])
            records.append(row)
        print(f"  fetched {len(records):,}", flush=True)
        if len(feats) < page_size:
            break
        offset += page_size
        time.sleep(0.2)
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def carto_sql(query: str) -> pd.DataFrame:
    """Run a Carto SQL query, returning a DataFrame."""
    resp = requests.get(
        CARTO_SQL, params={"q": query, "format": "csv"}, timeout=180
    )
    resp.raise_for_status()
    from io import StringIO

    return pd.read_csv(StringIO(resp.text))


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Vacant land: L&I's own determination, polygon geometry
    print("Fetching L&I Vacant_Indicators_Land ...")
    vacant = fetch_arcgis_layer(
        LNI_VACANT_LAND,
        out_fields="opa_id,address,owner1,bldg_desc,zoningbasedistrict,councildistrict",
    )
    vacant["opa_id"] = vacant["opa_id"].astype(str).str.strip().str.zfill(9)
    print(f"  {len(vacant):,} vacant-land polygons")

    # Attach true-ground lot area from OPA (not Shape__Area — CRS distortion)
    print("Fetching OPA total_area for vacant parcels ...")
    areas = carto_sql(
        "SELECT parcel_number, total_area FROM opa_properties_public "
        "WHERE total_area IS NOT NULL"
    )
    areas["parcel_number"] = areas["parcel_number"].astype(str).str.strip().str.zfill(9)
    area_map = areas.set_index("parcel_number")["total_area"]
    vacant["total_area"] = vacant["opa_id"].map(area_map)
    matched = vacant["total_area"].notna().sum()
    print(f"  area matched for {matched:,} / {len(vacant):,} ({matched/len(vacant):.1%})")

    vacant.to_parquet(DATA_DIR / "vacant_land_lni.gpq")
    print(f"  wrote {DATA_DIR / 'vacant_land_lni.gpq'}")

    # Surface parking: OPA building codes
    print("Fetching OPA surface parking lots ...")
    parking = carto_sql(
        "SELECT parcel_number, building_code_description, total_area, pin, "
        "ST_Y(the_geom) AS lat, ST_X(the_geom) AS lon "
        "FROM opa_properties_public "
        f"WHERE building_code_description LIKE '{PARKING_LIKE}'"
    )
    parking["parcel_number"] = (
        parking["parcel_number"].astype(str).str.strip().str.zfill(9)
    )
    print(f"  {len(parking):,} surface parking parcels")
    print(parking["building_code_description"].value_counts().to_string())

    parking = parking.dropna(subset=["lat", "lon"])
    parking_gdf = gpd.GeoDataFrame(
        parking,
        geometry=gpd.points_from_xy(parking["lon"], parking["lat"]),
        crs="EPSG:4326",
    )
    parking_gdf.to_parquet(DATA_DIR / "surface_parking_opa.gpq")
    print(f"  wrote {DATA_DIR / 'surface_parking_opa.gpq'}")

    # Headline figures, generated — never hand-typed into the image
    stats = {
        "vacant_parcels": int(len(vacant)),
        "vacant_acres": float(vacant["total_area"].sum() / 43560.0),
        "vacant_area_match_rate": float(matched / len(vacant)),
        "parking_parcels": int(len(parking)),
        "parking_acres": float(parking["total_area"].sum() / 43560.0),
        "source_vacant": "City of Philadelphia L&I, Vacant Indicators (Land)",
        "source_parking": "City of Philadelphia OPA, opa_properties_public",
    }
    stats["combined_acres"] = stats["vacant_acres"] + stats["parking_acres"]
    out = DATA_DIR / "vacant_parking_stats.json"
    out.write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
