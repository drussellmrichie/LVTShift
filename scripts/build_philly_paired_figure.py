"""Paired citywide + block-level figure for PPI's donate page.

The two panels exist to be read together. The block zoom alone invites the
misreading that all of Philadelphia looks like Fairhill; the citywide intensity
panel shows it does not (median tract 2.0%). Neither panel exaggerates any
geometry — the citywide panel aggregates to tracts, the block panel is true scale.

Reuses helpers from build_philly_block_zoom.py and
build_philly_vacant_parking_alternatives.py so the two never drift.

Output: analysis/reports/philadelphia/vacant_parking_paired.png
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle
from shapely.geometry import box

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from build_philly_block_zoom import (  # noqa: E402
    ARC, CRS_PLOT, HALF_WIN_FT, DATA_DIR, OUT_DIR,
    BG, LOT_FILL, LOT_EDGE, BUILDING, BUILDING_EDGE, VACANT, PARKING, INK, MUTED,
    fetch_bbox, load_layers, densest_cell, scale_bar,
)
from build_philly_vacant_parking_alternatives import HEAT, tracts_with_share  # noqa: E402

CACHE = DATA_DIR / "_block_zoom_window"


def cached_window_layers(win_wgs):
    """Fetch buildings + parcels for the zoom window once, then reuse."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, service, fields in (
        ("buildings", "building_footprints", "objectid"),
        ("parcels", "PWD_PARCELS", "brt_id"),
    ):
        path = CACHE / f"{name}.gpq"
        if path.exists():
            out[name] = gpd.read_parquet(path)
        else:
            print(f"fetching {name} ...")
            g = fetch_bbox(service, win_wgs.bounds, out_fields=fields)
            g.to_parquet(path)
            out[name] = g
        out[name] = out[name].to_crs(CRS_PLOT)
        print(f"  {name}: {len(out[name]):,}")
    return out["buildings"], out["parcels"]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vacant, parking = load_layers()
    park_all = gpd.read_parquet(DATA_DIR / "surface_parking_opa.gpq")
    park_all["parcel_number"] = park_all["parcel_number"].astype(str).str.zfill(9)

    cx, cy, _ = densest_cell(vacant)
    win = box(cx - HALF_WIN_FT, cy - HALF_WIN_FT, cx + HALF_WIN_FT, cy + HALF_WIN_FT)
    win_wgs = gpd.GeoSeries([win], crs=CRS_PLOT).to_crs("EPSG:4326").iloc[0]
    bldgs, parcels = cached_window_layers(win_wgs)

    t = tracts_with_share(vacant, park_all)
    city = t.dissolve()
    city["geometry"] = city.geometry.buffer(0)

    v_win = vacant[vacant.intersects(win)]
    p_win = parking[parking.intersects(win)]
    b_win = bldgs[bldgs.intersects(win)]
    par_win = parcels[parcels.intersects(win)]
    vac_area = v_win.geometry.intersection(win).area.sum()
    win_area = win.area
    median_pct = t["pct"].median()

    fig = plt.figure(figsize=(17.5, 10.2), dpi=190, facecolor=BG)

    # LEFT — citywide intensity
    axl = fig.add_axes([0.028, 0.115, 0.32, 0.665])
    axl.set_facecolor(BG)
    t.plot(ax=axl, column="pct", cmap=HEAT, vmin=0, vmax=20,
           edgecolor=BG, linewidth=0.22, zorder=2)
    city.plot(ax=axl, facecolor="none", edgecolor="#4c5665", linewidth=0.7, zorder=4)
    axl.plot([cx], [cy], marker="o", markersize=15, markerfacecolor="none",
             markeredgecolor=INK, markeredgewidth=1.8, zorder=6)
    axl.annotate("detail at right", xy=(cx, cy), xytext=(28, 34),
                 textcoords="offset points", color=INK, fontsize=9.5, zorder=7,
                 arrowprops=dict(arrowstyle="-", color=INK, alpha=0.6, linewidth=0.9))
    axl.set_axis_off()

    # Dedicated colorbar axes — fig.colorbar(ax=...) would shrink axl and drag
    # its figure-space position out from under the panel title.
    cax = fig.add_axes([0.352, 0.30, 0.010, 0.34])
    sm = plt.cm.ScalarMappable(cmap=HEAT, norm=plt.Normalize(0, 20))
    cb = fig.colorbar(sm, cax=cax)
    cb.set_ticks([0, 5, 10, 15, 20])
    cb.set_ticklabels(["0%", "5%", "10%", "15%", "20%+"])
    cb.ax.tick_params(colors=MUTED, labelsize=8.5, length=0)
    cb.outline.set_visible(False)

    # RIGHT — block zoom
    axr = fig.add_axes([0.415, 0.115, 0.56, 0.665])
    axr.set_facecolor(BG)
    par_win.plot(ax=axr, facecolor=LOT_FILL, edgecolor=LOT_EDGE, linewidth=0.3, zorder=2)
    b_win.plot(ax=axr, facecolor=BUILDING, edgecolor=BUILDING_EDGE, linewidth=0.3, zorder=3)
    v_win.plot(ax=axr, facecolor=VACANT, edgecolor="#6b4a10", linewidth=0.3, zorder=4)
    p_win.plot(ax=axr, facecolor=PARKING, edgecolor="#6e1f26", linewidth=0.3, zorder=5)
    axr.set_xlim(cx - HALF_WIN_FT, cx + HALF_WIN_FT)
    axr.set_ylim(cy - HALF_WIN_FT, cy + HALF_WIN_FT)
    axr.set_axis_off()
    scale_bar(axr, cx - HALF_WIN_FT + 110, cy - HALF_WIN_FT + 120)
    for s in ("left",):
        axr.add_patch(Rectangle((cx - HALF_WIN_FT, cy - HALF_WIN_FT),
                                HALF_WIN_FT * 2, HALF_WIN_FT * 2,
                                fill=False, edgecolor="#4c5665", linewidth=1.0, zorder=9))

    # Panel headings in FIGURE space so they cannot drift with axes resizing
    for x, title, sub in (
        (0.028, "The whole city",
         f"Share of each neighborhood's land that is vacant or surface\n"
         f"parking. Median tract: {median_pct:.1f}%."),
        (0.415, "The hardest-hit blocks",
         f"Fairhill / West Kensington, North Philadelphia — {len(v_win)} vacant lots in "
         f"{win_area/43560:.0f} acres.\n"
         f"Vacant land and parking are {vac_area/win_area:.0%} of the ground here. "
         f"Every shape is at true size."),
    ):
        fig.text(x, 0.858, title, color=INK, fontsize=16, fontweight="bold", va="top")
        fig.text(x, 0.828, sub, color=MUTED, fontsize=10.5, va="top", linespacing=1.5)

    fig.text(0.030, 0.968,
             "Philadelphia's idle land, at two scales",
             color=INK, fontsize=27, fontweight="bold", va="top")
    fig.text(0.030, 0.912,
             "Most of the city is only lightly affected. In the worst neighborhoods, "
             "nearly a fifth of the ground is empty.",
             color=MUTED, fontsize=13, va="top")

    fig.legend(
        handles=[
            Patch(facecolor=LOT_FILL, edgecolor=LOT_EDGE, label="Occupied lots"),
            Patch(facecolor=BUILDING, edgecolor=BUILDING_EDGE, label="Buildings"),
            Patch(facecolor=VACANT, edgecolor="none", label="Vacant land"),
            Patch(facecolor=PARKING, edgecolor="none", label="Surface parking"),
        ],
        loc="lower left", bbox_to_anchor=(0.415, 0.038), frameon=False,
        labelcolor=INK, fontsize=11.5, ncol=4, handlelength=1.3, handleheight=1.3)

    fig.text(0.030, 0.040,
             "Sources: City of Philadelphia — L&I Vacant Property Indicators (land);\n"
             "Office of Property Assessment parcel records; building footprints; PWD parcels.",
             color=MUTED, fontsize=8.2, va="bottom", linespacing=1.6)
    fig.text(0.970, 0.040, "Progress and Poverty Institute", color=MUTED,
             fontsize=9, ha="right", va="bottom")

    out = OUT_DIR / "vacant_parking_paired.png"
    fig.savefig(out, facecolor=BG)
    plt.close(fig)
    print(f"\nwrote {out}")
    print(f"median tract {median_pct:.2f}% | zoom window {vac_area/win_area:.1%} | "
          f"{len(v_win)} vacant lots in view")
    return 0


if __name__ == "__main__":
    sys.exit(main())
