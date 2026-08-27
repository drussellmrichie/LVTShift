"""Fetch current DOR parcel lot areas, keyed by PIN, in true ground square feet.

Replaces `cities/philadelphia/data/parcel_areas_by_pin.parquet`, which was built from the
2023 DOR GeoJSON and has two defects:

1. **Web Mercator area distortion.** The stored `Shape__Area` is computed in EPSG:3857,
   which inflates area by 1/cos^2(latitude) — about 1.704x at Philadelphia's latitude.
   OPA's `total_area` is true ground area, so mixing the two sources in one pipeline puts
   ~5% of parcels on an area scale 1.7x larger than the rest.
2. **Vintage gap.** It covers 577,909 PINs; 30,649 parcels in the 2024 OPA pull have PINs
   absent from it, and those fall through to a spatial join that assigns one shared
   polygon's area to every parcel inside it.

The live DOR_Parcel FeatureServer carries 607,919 features, so it closes most of the gap.
Areas are converted from Mercator to true ground area with a per-parcel cos^2(latitude)
correction; the correction varies only between 1.696 and 1.712 across the city.

Usage:
    python scripts/fetch_dor_parcel_areas.py
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pandas as pd
import requests

SERVICE = (
    "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
    "/DOR_Parcel/FeatureServer/0"
)
PAGE = 2000
OUT = Path("cities/philadelphia/data/parcel_areas_by_pin_current.parquet")
SQM_PER_SQFT = 10.763910416709722
# Web Mercator y -> latitude, for the per-parcel area de-distortion.
R_EARTH = 6378137.0


def mercator_y_to_lat(y: float) -> float:
    return math.degrees(2.0 * math.atan(math.exp(y / R_EARTH)) - math.pi / 2.0)


def fetch() -> pd.DataFrame:
    session = requests.Session()
    rows: list[dict] = []
    offset = 0
    t0 = time.time()
    while True:
        params = {
            "where": "1=1",
            "outFields": "pin,Shape__Area",
            "returnGeometry": "true",
            "geometryPrecision": "0",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
            "f": "json",
        }
        for attempt in range(4):
            try:
                r = session.get(SERVICE + "/query", params=params, timeout=120)
                r.raise_for_status()
                payload = r.json()
                break
            except Exception as exc:  # noqa: BLE001 - retry any transport/parse failure
                if attempt == 3:
                    raise RuntimeError(f"failed at offset {offset}: {exc}") from exc
                time.sleep(2 * (attempt + 1))

        feats = payload.get("features", [])
        if not feats:
            break

        for f in feats:
            attrs = f.get("attributes", {})
            pin = attrs.get("pin")
            area_merc_sqm = attrs.get("Shape__Area")
            if pin is None or not area_merc_sqm:
                continue
            geom = f.get("geometry") or {}
            rings = geom.get("rings") or []
            if rings and rings[0]:
                ys = [pt[1] for pt in rings[0]]
                lat = mercator_y_to_lat(sum(ys) / len(ys))
            else:
                lat = 39.997  # citywide median, used only if geometry is absent
            true_sqm = area_merc_sqm * (math.cos(math.radians(lat)) ** 2)
            rows.append(
                {
                    "pin": str(pin).strip(),
                    "pin_area_sqft": round(true_sqm * SQM_PER_SQFT, 1),
                }
            )

        offset += len(feats)
        if offset % 50_000 < PAGE:
            print(f"  {offset:,} features ({time.time() - t0:.0f}s)", flush=True)
        if len(feats) < PAGE:
            break

    return pd.DataFrame(rows)


def main() -> int:
    print(f"Fetching {SERVICE}")
    df = fetch()
    print(f"Fetched {len(df):,} rows, {df['pin'].nunique():,} distinct PINs")

    # One row per PIN. Duplicated PINs (multi-part lots) sum to the full lot area.
    df = df.groupby("pin", as_index=False)["pin_area_sqft"].sum()
    df = df[df["pin_area_sqft"] > 0].reset_index(drop=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    total = df["pin_area_sqft"].sum()
    philly = 134.2 * 27_878_400
    print(f"Wrote {OUT} — {len(df):,} PINs")
    print(f"  total area {total:.3e} sqft = {total / philly:.2f}x Philadelphia's land area")
    print(f"  median lot {df['pin_area_sqft'].median():,.0f} sqft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
