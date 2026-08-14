"""Four honest ways to visualize Philadelphia's vacant land + surface parking.

Motivated by a real defect in the first draft: buffering every parcel by 90 ft to
make it visible at citywide scale inflated the median 1,005 sq ft lot ~44x, so
dense North Philadelphia read as one continuous field of vacancy. It is not —
the median tract is ~2% vacant+parking and only 3 of 408 tracts exceed 20%.

Panels:
  1. TRUE SCALE      every parcel at its real footprint, no buffer
  2. INTENSITY       tract choropleth, % of tract land that is vacant or parking
  3. GATHERED        the same total acreage drawn as one contiguous square
  4. INFLATED        the original 90 ft-buffered version, kept for comparison
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle, Patch

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities" / "philadelphia" / "data"
OUT_DIR = REPO_ROOT / "analysis" / "reports" / "philadelphia"

CRS_PLOT = "EPSG:2272"
SQFT_PER_ACRE = 43560.0

BG = "#0d1117"
CITY_FILL = "#1b212b"
CITY_EDGE = "#39424f"
VACANT = "#FFB020"
PARKING = "#FF4D5A"
INK = "#f2f5f8"
MUTED = "#93a1b0"

HEAT = LinearSegmentedColormap.from_list(
    "heat", ["#1b212b", "#4a3520", "#8a5a1e", "#d18b1c", "#FFB020", "#ffe08a"]
)


def load():
    vacant = gpd.read_parquet(DATA_DIR / "vacant_land_lni.gpq")
    parking = gpd.read_parquet(DATA_DIR / "surface_parking_polygons.gpq")
    parking_all = gpd.read_parquet(DATA_DIR / "surface_parking_opa.gpq")
    vacant["opa_id"] = vacant["opa_id"].astype(str).str.zfill(9)
    parking["brt_id"] = parking["brt_id"].astype(str).str.zfill(9)
    parking_all["parcel_number"] = parking_all["parcel_number"].astype(str).str.zfill(9)
    vacant = vacant[~vacant["opa_id"].isin(set(parking_all["parcel_number"]))].copy()
    return vacant.to_crs(CRS_PLOT), parking.to_crs(CRS_PLOT), parking_all


def tracts_with_share(vacant, parking_all):
    t = gpd.read_parquet(DATA_DIR / "census_tracts.gpq")
    if t.crs is None:
        t = t.set_crs("EPSG:4326")
    t = t.to_crs(CRS_PLOT)
    t["land_sqft"] = t.geometry.area
    t = t[t["land_sqft"] > 0].reset_index(drop=True)
    t["tid"] = range(len(t))

    def agg(gdf):
        g = gdf.to_crs(CRS_PLOT).copy()
        g["geometry"] = g.geometry.centroid
        j = gpd.sjoin(g[["total_area", "geometry"]], t[["tid", "geometry"]],
                      how="inner", predicate="within")
        return j.groupby("tid")["total_area"].sum()

    park_pts = gpd.GeoDataFrame(
        parking_all[["total_area"]],
        geometry=gpd.points_from_xy(parking_all["lon"], parking_all["lat"]),
        crs="EPSG:4326",
    )
    t["vac"] = t["tid"].map(agg(vacant)).fillna(0)
    t["park"] = t["tid"].map(agg(park_pts)).fillna(0)
    t["pct"] = ((t["vac"] + t["park"]) / t["land_sqft"] * 100).clip(upper=100)
    return t


def city_boundary(t):
    d = t.dissolve()
    d["geometry"] = d.geometry.buffer(0)
    return d


def base(ax, city, edge=CITY_EDGE):
    city.plot(ax=ax, facecolor=CITY_FILL, edgecolor=edge, linewidth=0.7, zorder=1)
    ax.set_axis_off()


def panel_title(ax, n, title, sub):
    ax.set_title("", pad=0)
    ax.text(0.0, 1.055, f"{n}  {title}", transform=ax.transAxes, color=INK,
            fontsize=14, fontweight="bold", va="bottom")
    ax.text(0.0, 1.012, sub, transform=ax.transAxes, color=MUTED,
            fontsize=9.6, va="bottom")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vacant, parking, parking_all = load()
    t = tracts_with_share(vacant, parking_all)
    city = city_boundary(t)

    total_acres = (vacant["total_area"].fillna(0).sum()
                   + parking_all["total_area"].fillna(0).sum()) / SQFT_PER_ACRE

    fig, axes = plt.subplots(2, 2, figsize=(15, 16.5), dpi=150, facecolor=BG)
    for a in axes.ravel():
        a.set_facecolor(BG)

    # 1 — TRUE SCALE
    ax = axes[0, 0]
    base(ax, city)
    vacant.plot(ax=ax, facecolor=VACANT, edgecolor="none", zorder=2)
    parking.plot(ax=ax, facecolor=PARKING, edgecolor="none", zorder=3)
    panel_title(ax, "1", "True scale",
                "Every parcel at its actual footprint. No exaggeration.")

    # 2 — INTENSITY
    ax = axes[0, 1]
    base(ax, city, edge="none")
    t.plot(ax=ax, column="pct", cmap=HEAT, vmin=0, vmax=25,
           edgecolor=BG, linewidth=0.25, zorder=2)
    city.plot(ax=ax, facecolor="none", edgecolor=CITY_EDGE, linewidth=0.7, zorder=4)
    ax.set_axis_off()
    panel_title(ax, "2", "Intensity by neighborhood",
                "Share of each tract's land that is vacant or parking (0–25%+).")
    sm = plt.cm.ScalarMappable(cmap=HEAT, norm=plt.Normalize(0, 25))
    cb = fig.colorbar(sm, ax=ax, fraction=0.026, pad=0.005, aspect=30, shrink=0.72)
    cb.set_ticks([0, 5, 10, 15, 20, 25])
    cb.set_ticklabels(["0%", "5%", "10%", "15%", "20%", "25%+"])
    cb.ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    cb.outline.set_visible(False)

    # 3 — GATHERED
    ax = axes[1, 0]
    base(ax, city)
    side = np.sqrt(total_acres * SQFT_PER_ACRE)  # feet
    cx, cy = city.geometry.iloc[0].centroid.x, city.geometry.iloc[0].centroid.y
    ax.add_patch(Rectangle((cx - side / 2, cy - side / 2), side, side,
                           facecolor=VACANT, edgecolor=INK, linewidth=1.0,
                           alpha=0.88, zorder=5))
    # Label sits outside the square — at 2 mi on a side it is too small to hold text
    ax.annotate(
        f"{total_acres:,.0f} acres",
        xy=(cx + side / 2, cy + side / 2),
        xytext=(cx + side * 1.5, cy + side * 1.15),
        color=INK, fontsize=15, fontweight="bold", va="center", zorder=6,
        arrowprops=dict(arrowstyle="-", color=INK, alpha=0.55, linewidth=0.9),
    )
    panel_title(ax, "3", "Gathered in one place",
                f"All {total_acres:,.0f} acres as a single square — {side/5280:.1f} miles on a side.")

    # 4 — INFLATED (the misleading original)
    ax = axes[1, 1]
    base(ax, city)
    gpd.GeoSeries(vacant.geometry.buffer(90), crs=CRS_PLOT).plot(
        ax=ax, facecolor=VACANT, edgecolor="none", zorder=2)
    gpd.GeoSeries(parking.geometry.buffer(45), crs=CRS_PLOT).plot(
        ax=ax, facecolor=PARKING, edgecolor="none", zorder=3)
    panel_title(ax, "4", "Inflated  — for comparison only",
                "Parcels buffered 90 ft. Reads as continuous; overstates lots ~44x.")

    fig.legend(
        handles=[Patch(facecolor=VACANT, edgecolor="none", label="Vacant land"),
                 Patch(facecolor=PARKING, edgecolor="none", label="Surface parking")],
        loc="lower left", bbox_to_anchor=(0.035, 0.035), frameon=False,
        labelcolor=INK, fontsize=12, ncol=2, handlelength=1.3, handleheight=1.3)
    fig.text(0.035, 0.972,
             "Four ways to draw the same data", color=INK,
             fontsize=21, fontweight="bold", va="top")
    fig.text(0.035, 0.949,
             "Median tract is 2.0% vacant or parking; only 3 of 408 tracts exceed 20%.",
             color=MUTED, fontsize=11.5, va="top")
    fig.text(0.965, 0.035,
             "Sources: City of Philadelphia L&I Vacant Property Indicators; OPA parcel records.",
             color=MUTED, fontsize=8.5, ha="right", va="bottom")

    fig.subplots_adjust(left=0.02, right=0.98, top=0.905, bottom=0.075,
                        wspace=0.02, hspace=0.11)
    out = OUT_DIR / "vacant_parking_alternatives.png"
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"wrote {out}")
    print(f"total_acres={total_acres:,.1f}  square_side_mi={side/5280:.2f}")
    print(t["pct"].describe(percentiles=[.5, .9, .99]).round(1).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
