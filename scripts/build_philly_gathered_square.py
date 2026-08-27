"""Standalone 'gathered in one place' image for PPI's donate page.

Takes every vacant lot and surface parking lot in Philadelphia and draws their
combined area as a single square on the city, split proportionally into the
vacant and parking shares. No geometry is exaggerated: the square's area equals
the summed OPA ground area of the parcels, and the internal split is by area.

Output: analysis/reports/philadelphia/vacant_parking_gathered.png
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from build_philly_block_zoom import (  # noqa: E402
    CRS_PLOT, DATA_DIR, OUT_DIR, BG, VACANT, PARKING, INK, MUTED,
)

SQFT_PER_ACRE = 43560.0
PHILLY_LAND_SQMI = 134.18
CENTRAL_PARK_ACRES = 843.0
CITY_FILL = "#1b212b"
CITY_EDGE = "#39424f"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    vacant = gpd.read_parquet(DATA_DIR / "vacant_land_lni.gpq")
    park_all = gpd.read_parquet(DATA_DIR / "surface_parking_opa.gpq")
    vacant["opa_id"] = vacant["opa_id"].astype(str).str.zfill(9)
    park_all["parcel_number"] = park_all["parcel_number"].astype(str).str.zfill(9)

    # 26 L&I rows carry placeholder ids ('000000000', '00000None') rather than a real
    # OPA number. They all have null total_area so they contribute nothing today, but
    # they share an id, and a future data refresh that fills the area in would
    # double-count them. Drop the placeholders and dedupe defensively.
    vacant = vacant[~vacant["opa_id"].isin({"000000000", "00000None"})]
    vacant = vacant.drop_duplicates(subset="opa_id")

    # Parcels in both layers count once, as parking
    vacant = vacant[~vacant["opa_id"].isin(set(park_all["parcel_number"]))].copy()

    vac_ac = float(vacant["total_area"].fillna(0).sum() / SQFT_PER_ACRE)
    park_ac = float(park_all["total_area"].fillna(0).sum() / SQFT_PER_ACRE)
    total_ac = vac_ac + park_ac
    vac_share = vac_ac / total_ac

    tracts = gpd.read_parquet(DATA_DIR / "census_tracts.gpq")
    if tracts.crs is None:
        tracts = tracts.set_crs("EPSG:4326")
    city = tracts.to_crs(CRS_PLOT).dissolve()
    city["geometry"] = city.geometry.buffer(0)

    side = float(np.sqrt(total_ac * SQFT_PER_ACRE))  # feet
    cx = float(city.geometry.iloc[0].centroid.x)
    cy = float(city.geometry.iloc[0].centroid.y)
    x0, y0 = cx - side / 2, cy - side / 2

    # Fill the frame with the city. Philadelphia's outline runs diagonally, so the
    # top-left and bottom-right corners are empty — the text sits in that dead space
    # rather than in a separate band, which lets the map render much larger.
    fig = plt.figure(figsize=(11.0, 11.8), dpi=200, facecolor=BG)
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_facecolor(BG)
    city.plot(ax=ax, facecolor=CITY_FILL, edgecolor=CITY_EDGE, linewidth=0.9, zorder=1)
    minx, miny, maxx, maxy = city.total_bounds
    padx = (maxx - minx) * 0.045
    pady = (maxy - miny) * 0.045
    ax.set_xlim(minx - padx, maxx + padx)
    ax.set_ylim(miny - pady, maxy + pady)

    # The square, split by area into vacant (lower) and parking (upper)
    vac_h = side * vac_share
    ax.add_patch(Rectangle((x0, y0), side, vac_h, facecolor=VACANT,
                           edgecolor="none", zorder=5))
    ax.add_patch(Rectangle((x0, y0 + vac_h), side, side - vac_h, facecolor=PARKING,
                           edgecolor="none", zorder=5))
    ax.add_patch(Rectangle((x0, y0), side, side, fill=False, edgecolor=INK,
                           linewidth=1.4, zorder=6))
    ax.set_axis_off()

    # Callouts to each band
    ax.annotate(f"Vacant land\n{vac_ac:,.0f} acres",
                xy=(x0 + side * 0.5, y0 + vac_h * 0.5),
                xytext=(x0 - side * 1.35, y0 + vac_h * 0.35),
                color=INK, fontsize=12.5, va="center", zorder=8, linespacing=1.4,
                arrowprops=dict(arrowstyle="-", color=INK, alpha=0.5, linewidth=0.9))
    ax.annotate(f"Surface parking\n{park_ac:,.0f} acres",
                xy=(x0 + side * 0.5, y0 + vac_h + (side - vac_h) * 0.5),
                xytext=(x0 + side * 1.28, y0 + side * 1.02),
                color=INK, fontsize=12.5, va="center", zorder=8, linespacing=1.4,
                arrowprops=dict(arrowstyle="-", color=INK, alpha=0.5, linewidth=0.9))

    # Scale reference along the base of the square
    ax.annotate("", xy=(x0, y0 - side * 0.11), xytext=(x0 + side, y0 - side * 0.11),
                arrowprops=dict(arrowstyle="<->", color=MUTED, linewidth=1.0), zorder=8)
    ax.text(x0 + side / 2, y0 - side * 0.155, f"{side/5280:.1f} miles",
            color=MUTED, fontsize=11, ha="center", va="top", zorder=8)

    fig.text(0.035, 0.978, f"{total_ac:,.0f} acres", color=INK,
             fontsize=44, fontweight="bold", va="top")
    fig.text(0.035, 0.912,
             "of Philadelphia sits vacant or paved for parking.",
             color=INK, fontsize=20, va="top")
    fig.text(0.035, 0.872,
             f"Gathered into one place it would cover this much of the city — "
             f"{side/5280:.1f} miles on a side,\n"
             f"about {total_ac/CENTRAL_PARK_ACRES:.0f} times the area of Central Park.",
             color=MUTED, fontsize=12.5, va="top", linespacing=1.55)

    fig.text(0.035, 0.030,
             "Sources: City of Philadelphia — L&I Vacant Property Indicators (land);\n"
             "Office of Property Assessment parcel records (surface parking).\n"
             "Square area equals the summed recorded ground area of every such parcel.",
             color=MUTED, fontsize=8.2, va="bottom", linespacing=1.6)
    fig.text(0.965, 0.030, "Progress and Poverty Institute", color=MUTED,
             fontsize=9, ha="right", va="bottom")

    out = OUT_DIR / "vacant_parking_gathered.png"
    fig.savefig(out, facecolor=BG)
    plt.close(fig)

    stats = {
        "vacant_acres": vac_ac, "parking_acres": park_ac, "total_acres": total_ac,
        "square_side_ft": side, "square_side_mi": side / 5280,
        "pct_of_city_land": total_ac / (PHILLY_LAND_SQMI * 640) * 100,
        "central_parks": total_ac / CENTRAL_PARK_ACRES,
        "vacant_share_of_total": vac_share,
    }
    (OUT_DIR / "vacant_parking_gathered.json").write_text(json.dumps(stats, indent=2))
    print(f"wrote {out}")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
