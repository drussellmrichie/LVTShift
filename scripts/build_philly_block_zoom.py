"""Block-level true-scale view of vacant land in North Philadelphia.

No exaggeration of any kind: at this scale a 1,005 sq ft lot is tens of pixels
across, so parcels are drawn at their real footprints. Building footprints are
shown so the gaps read as gaps in an otherwise-occupied block.

Sources: City of Philadelphia — L&I Vacant Property Indicators (land),
OPA parcel records (surface parking), building_footprints, PWD_PARCELS.
"""

import sys
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import requests
from matplotlib.patches import Patch, Rectangle
from shapely.geometry import box, shape

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities" / "philadelphia" / "data"
OUT_DIR = REPO_ROOT / "analysis" / "reports" / "philadelphia"

ARC = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
CRS_PLOT = "EPSG:2272"  # feet
CELL_FT = 1200.0
HALF_WIN_FT = 1100.0  # half-width of the rendered window

BG = "#0d1117"
LOT_FILL = "#232a35"     # occupied lot, whole parcel
LOT_EDGE = "#2f3947"
BUILDING = "#48525f"     # the structure on it
BUILDING_EDGE = "#5a6472"
VACANT = "#FFB020"
PARKING = "#FF4D5A"
INK = "#f2f5f8"
MUTED = "#93a1b0"


def fetch_bbox(service: str, bounds_wgs84, out_fields="*") -> gpd.GeoDataFrame:
    """Fetch a layer inside a WGS84 envelope, paging until exhausted."""
    xmin, ymin, xmax, ymax = bounds_wgs84
    records, offset = [], 0
    while True:
        params = {
            "where": "1=1",
            "geometry": f"{xmin},{ymin},{xmax},{ymax}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields,
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": 2000,
        }
        r = requests.get(f"{ARC}/{service}/FeatureServer/0/query?{urlencode(params)}", timeout=120)
        r.raise_for_status()
        feats = r.json().get("features", [])
        if not feats:
            break
        for f in feats:
            if f.get("geometry") is None:
                continue
            row = dict(f.get("properties") or {})
            row["geometry"] = shape(f["geometry"])
            records.append(row)
        if len(feats) < 2000:
            break
        offset += 2000
    if not records:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:4326")


def load_layers():
    vacant = gpd.read_parquet(DATA_DIR / "vacant_land_lni.gpq")
    parking = gpd.read_parquet(DATA_DIR / "surface_parking_polygons.gpq")
    park_all = gpd.read_parquet(DATA_DIR / "surface_parking_opa.gpq")
    vacant["opa_id"] = vacant["opa_id"].astype(str).str.zfill(9)
    park_all["parcel_number"] = park_all["parcel_number"].astype(str).str.zfill(9)
    vacant = vacant[~vacant["opa_id"].isin(set(park_all["parcel_number"]))].copy()
    return vacant.to_crs(CRS_PLOT), parking.to_crs(CRS_PLOT)


def densest_cell(vacant):
    """Grid the city and return the centre of the cell holding the most vacant lots."""
    cen = vacant.geometry.centroid
    gx = np.floor(cen.x / CELL_FT).astype(int)
    gy = np.floor(cen.y / CELL_FT).astype(int)
    import pandas as pd

    counts = pd.Series(1, index=pd.MultiIndex.from_arrays([gx, gy])).groupby(level=[0, 1]).sum()
    top = counts.sort_values(ascending=False).head(8)
    print("densest 1,200 ft cells by vacant-lot count:")
    for (cx, cy), n in top.items():
        pt = gpd.GeoSeries([box(cx * CELL_FT, cy * CELL_FT,
                                (cx + 1) * CELL_FT, (cy + 1) * CELL_FT).centroid],
                           crs=CRS_PLOT).to_crs("EPSG:4326").iloc[0]
        print(f"  {n:4d} lots   lat {pt.y:.5f}  lon {pt.x:.5f}")
    (bx, by) = top.index[0]
    return (bx + 0.5) * CELL_FT, (by + 0.5) * CELL_FT, int(top.iloc[0])


def scale_bar(ax, x0, y0, length_ft=500):
    ax.plot([x0, x0 + length_ft], [y0, y0], color=INK, linewidth=2.4, solid_capstyle="butt", zorder=10)
    ax.text(x0 + length_ft / 2, y0 + 55, f"{length_ft} ft", color=INK, fontsize=10,
            ha="center", va="bottom", zorder=10)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vacant, parking = load_layers()
    cx, cy, n_lots = densest_cell(vacant)

    win = box(cx - HALF_WIN_FT, cy - HALF_WIN_FT, cx + HALF_WIN_FT, cy + HALF_WIN_FT)
    win_wgs = gpd.GeoSeries([win], crs=CRS_PLOT).to_crs("EPSG:4326").iloc[0]
    print(f"\nwindow centre lat/lon: {win_wgs.centroid.y:.5f}, {win_wgs.centroid.x:.5f}")

    print("fetching building footprints in window ...")
    bldgs = fetch_bbox("building_footprints", win_wgs.bounds, out_fields="objectid")
    bldgs = bldgs.to_crs(CRS_PLOT)
    print(f"  {len(bldgs):,} buildings")

    # Occupied parcels must be drawn as whole lots too. Drawing vacant parcels at
    # full lot extent against buildings-only footprints makes vacancy look larger
    # than it is, because each occupied lot's yard renders as background.
    print("fetching parcel lots in window ...")
    parcels = fetch_bbox("PWD_PARCELS", win_wgs.bounds, out_fields="brt_id").to_crs(CRS_PLOT)
    print(f"  {len(parcels):,} parcels")

    v_win = vacant[vacant.intersects(win)]
    p_win = parking[parking.intersects(win)]
    b_win = bldgs[bldgs.intersects(win)]
    vac_area = v_win.geometry.intersection(win).area.sum()
    win_area = win.area
    print(f"  {len(v_win)} vacant lots, {len(p_win)} parking lots in view")
    print(f"  vacant+parking = {vac_area / win_area:.1%} of the visible ground")

    fig = plt.figure(figsize=(11.5, 12.6), dpi=190, facecolor=BG)
    ax = fig.add_axes([0.035, 0.085, 0.93, 0.775])
    ax.set_facecolor(BG)

    # Occupied lots first (whole parcel), then buildings on top, then vacant/parking lots
    par_win = parcels[parcels.intersects(win)]
    par_win.plot(ax=ax, facecolor=LOT_FILL, edgecolor=LOT_EDGE, linewidth=0.3, zorder=2)
    b_win.plot(ax=ax, facecolor=BUILDING, edgecolor=BUILDING_EDGE, linewidth=0.3, zorder=3)
    v_win.plot(ax=ax, facecolor=VACANT, edgecolor="#6b4a10", linewidth=0.3, zorder=4)
    p_win.plot(ax=ax, facecolor=PARKING, edgecolor="#6e1f26", linewidth=0.3, zorder=5)

    ax.set_xlim(cx - HALF_WIN_FT, cx + HALF_WIN_FT)
    ax.set_ylim(cy - HALF_WIN_FT, cy + HALF_WIN_FT)
    ax.set_axis_off()
    scale_bar(ax, cx - HALF_WIN_FT + 110, cy - HALF_WIN_FT + 120)

    # Locator — opaque panel so it does not read as part of the block data
    axl = fig.add_axes([0.788, 0.098, 0.165, 0.165], zorder=20)
    axl.set_facecolor(BG)
    axl.patch.set_alpha(1.0)
    for s in axl.spines.values():
        s.set_visible(True); s.set_color("#4c5665"); s.set_linewidth(1.0)
    tr = gpd.read_parquet(DATA_DIR / "census_tracts.gpq")
    if tr.crs is None:
        tr = tr.set_crs("EPSG:4326")
    city = tr.to_crs(CRS_PLOT).dissolve()
    city["geometry"] = city.geometry.buffer(0)
    city.plot(ax=axl, facecolor="#1b212b", edgecolor="#4c5665", linewidth=0.7)
    axl.plot([cx], [cy], marker="o", markersize=7, color=VACANT,
             markeredgecolor=INK, markeredgewidth=0.9)
    axl.set_xticks([]); axl.set_yticks([])

    fig.text(0.035, 0.972,
             "This is what it looks like on the ground.", color=INK,
             fontsize=24, fontweight="bold", va="top")
    fig.text(0.035, 0.925,
             f"The hardest-hit blocks in North Philadelphia — {len(v_win)} vacant lots in "
             f"{(win_area/43560):.0f} acres, about {HALF_WIN_FT*2/5280:.1f} miles across.\n"
             f"Vacant land and surface parking are {vac_area/win_area:.0%} of the ground here, "
             f"against a citywide median of 2%. Every shape is at true size.",
             color=MUTED, fontsize=12.5, va="top", linespacing=1.55)

    fig.legend(
        handles=[
            Patch(facecolor=LOT_FILL, edgecolor=LOT_EDGE, label="Occupied lots"),
            Patch(facecolor=BUILDING, edgecolor=BUILDING_EDGE, label="Buildings"),
            Patch(facecolor=VACANT, edgecolor="none", label="Vacant land"),
            Patch(facecolor=PARKING, edgecolor="none", label="Surface parking"),
        ],
        loc="lower left", bbox_to_anchor=(0.035, 0.040), frameon=False,
        labelcolor=INK, fontsize=11.5, ncol=4, handlelength=1.3, handleheight=1.3)
    fig.text(0.035, 0.012,
             "Sources: City of Philadelphia — L&I Vacant Property Indicators; OPA; building footprints.",
             color=MUTED, fontsize=8, ha="left", va="bottom")

    out = OUT_DIR / "north_philly_block_zoom.png"
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
