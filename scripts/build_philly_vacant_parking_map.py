"""Build the Philadelphia vacant-land + surface-parking image for PPI's donate page.

KNOWN DEFECT — do not publish the citywide panel from this script.
`draw(..., buffer_ft=90)` inflates every parcel so it is visible at citywide
scale. The median vacant lot is 1,005 sq ft (~32 ft square); a 90 ft buffer
makes it ~212 ft square, roughly 44x its true footprint, and in dense North
Philadelphia the inflated lots merge into what reads as one continuous field of
vacancy. The real figure is a 2.0% median tract, with only 3 of 408 tracts over
20%. Use build_philly_paired_figure.py (true-scale block zoom + tract-level
intensity) for anything published. This script is kept because it computes the
headline acreage stats and is the baseline for panel 4 of
build_philly_vacant_parking_alternatives.py, which exists to show the distortion.

Every figure printed on the image is computed here from the source layers and
interpolated into the text — nothing is hand-typed (see global CLAUDE.md).

Data (all City of Philadelphia open data; no OSM, so the published image carries
no ODbL attribution requirement):
  - L&I Vacant Indicators (Land)      -> vacant lots
  - OPA opa_properties_public         -> surface parking lots (PKG LOT codes)
  - PWD_PARCELS                       -> parking lot footprints
Lot areas are OPA `total_area` (true ground sq ft), never an ArcGIS Shape__Area.

Outputs: analysis/reports/philadelphia/vacant_and_parking_<variant>.png
         analysis/reports/philadelphia/vacant_parking_headline.json
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch, ConnectionPatch

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities" / "philadelphia" / "data"
OUT_DIR = REPO_ROOT / "analysis" / "reports" / "philadelphia"

CRS_PLOT = "EPSG:2272"  # PA State Plane South (ft) — correct aspect for Philadelphia
SQFT_PER_ACRE = 43560.0
PHILLY_LAND_SQMI = 134.18

# Center City core, in WGS84: Vine St -> South St, Schuylkill -> Delaware
INSET_BBOX = (-75.184, 39.933, -75.138, 39.964)

BG = "#0d1117"
CITY_FILL = "#1b212b"
CITY_EDGE = "#39424f"
VACANT = "#FFB020"
PARKING = "#FF4D5A"
INK = "#f2f5f8"
MUTED = "#93a1b0"


def load_layers():
    vacant = gpd.read_parquet(DATA_DIR / "vacant_land_lni.gpq")
    parking = gpd.read_parquet(DATA_DIR / "surface_parking_polygons.gpq")
    parking_all = gpd.read_parquet(DATA_DIR / "surface_parking_opa.gpq")

    vacant["opa_id"] = vacant["opa_id"].astype(str).str.zfill(9)
    parking["brt_id"] = parking["brt_id"].astype(str).str.zfill(9)
    parking_all["parcel_number"] = parking_all["parcel_number"].astype(str).str.zfill(9)

    # 40 parcels appear in both layers; parking is the more specific claim, so it wins
    overlap = set(vacant["opa_id"]) & set(parking_all["parcel_number"])
    vacant = vacant[~vacant["opa_id"].isin(overlap)].copy()
    return vacant, parking, parking_all, len(overlap)


def city_boundary() -> gpd.GeoDataFrame:
    tracts = gpd.read_parquet(DATA_DIR / "census_tracts.gpq")
    if tracts.crs is None:
        tracts = tracts.set_crs("EPSG:4326")
    diss = tracts.to_crs(CRS_PLOT).dissolve()
    diss["geometry"] = diss.geometry.buffer(0)
    return diss


def compute_stats(vacant, parking_all, overlap_n) -> dict:
    park_area = parking_all["total_area"].fillna(0)
    vac_area = vacant["total_area"].fillna(0)
    city_acres = PHILLY_LAND_SQMI * 640
    stats = {
        "vacant_parcels": int(len(vacant)),
        "vacant_acres": float(vac_area.sum() / SQFT_PER_ACRE),
        "parking_parcels": int(len(parking_all)),
        "parking_acres": float(park_area.sum() / SQFT_PER_ACRE),
        "overlap_parcels_reassigned_to_parking": int(overlap_n),
        "city_land_acres": float(city_acres),
    }
    stats["total_parcels"] = stats["vacant_parcels"] + stats["parking_parcels"]
    stats["total_acres"] = stats["vacant_acres"] + stats["parking_acres"]
    stats["pct_of_city_land"] = stats["total_acres"] / city_acres * 100
    stats["central_parks"] = stats["total_acres"] / 843.0  # NYC Central Park = 843 ac
    return stats


def draw(ax, city, vacant, parking, *, buffer_ft, lw, alpha=1.0, edge=CITY_EDGE):
    city.plot(ax=ax, facecolor=CITY_FILL, edgecolor=edge, linewidth=0.8, zorder=1)
    v = vacant.geometry
    p = parking.geometry
    if buffer_ft:
        v = v.buffer(buffer_ft)
        p = p.buffer(buffer_ft * 0.5)
    gpd.GeoSeries(v, crs=CRS_PLOT).plot(
        ax=ax, facecolor=VACANT, edgecolor="none", alpha=alpha, zorder=2
    )
    gpd.GeoSeries(p, crs=CRS_PLOT).plot(
        ax=ax, facecolor=PARKING, edgecolor="none", alpha=alpha, zorder=3
    )
    ax.set_axis_off()


def build(stats, city, vacant, parking, out_path: Path, *, headline: bool):
    fig = plt.figure(figsize=(10, 11), dpi=200, facecolor=BG)

    # Main citywide panel
    ax = fig.add_axes([0.01, 0.135, 0.98, 0.745])
    ax.set_facecolor(BG)
    draw(ax, city, vacant, parking, buffer_ft=90, lw=0)

    # Center City inset
    inset_box = gpd.GeoDataFrame(
        geometry=gpd.GeoSeries.from_wkt(
            [
                "POLYGON(({x0} {y0},{x1} {y0},{x1} {y1},{x0} {y1},{x0} {y0}))".format(
                    x0=INSET_BBOX[0], y0=INSET_BBOX[1], x1=INSET_BBOX[2], y1=INSET_BBOX[3]
                )
            ]
        ),
        crs="EPSG:4326",
    ).to_crs(CRS_PLOT)
    bx0, by0, bx1, by1 = inset_box.total_bounds
    ax.add_patch(
        Rectangle(
            (bx0, by0), bx1 - bx0, by1 - by0,
            fill=False, edgecolor=INK, linewidth=1.1, zorder=6, alpha=0.85,
        )
    )

    axi = fig.add_axes([0.605, 0.155, 0.375, 0.25])
    axi.set_facecolor(CITY_FILL)
    clip = inset_box.geometry.iloc[0]
    draw(
        axi,
        gpd.GeoDataFrame(geometry=[city.geometry.iloc[0].intersection(clip)], crs=CRS_PLOT),
        vacant[vacant.intersects(clip)],
        parking[parking.intersects(clip)],
        buffer_ft=12,
        lw=0,
        edge="none",  # the city boundary would read as a stray line inside the inset
    )
    axi.set_xlim(bx0, bx1); axi.set_ylim(by0, by1)
    axi.set_axis_on(); axi.set_xticks([]); axi.set_yticks([])
    for s in axi.spines.values():
        s.set_visible(True); s.set_color(INK); s.set_linewidth(1.1); s.set_alpha(0.85)
    axi.set_title("Center City core, true scale", color=INK, fontsize=10, pad=6, loc="left")

    # Leader lines tying the callout box to the inset
    for corner_xy, inset_xy in (((bx1, by1), (0, 1)), ((bx1, by0), (0, 0))):
        fig.add_artist(
            ConnectionPatch(
                xyA=corner_xy, coordsA=ax.transData,
                xyB=inset_xy, coordsB=axi.transAxes,
                color=INK, linewidth=0.8, alpha=0.5,
            )
        )

    # Headline
    if headline:
        fig.text(
            0.03, 0.972,
            f"{stats['total_acres']:,.0f} acres of Philadelphia\nsit vacant or paved for parking.",
            color=INK, fontsize=26, fontweight="bold", va="top", linespacing=1.22,
        )
        fig.text(
            0.03, 0.878,
            f"{stats['vacant_parcels']:,} vacant lots  ·  {stats['parking_parcels']:,} surface parking lots"
            f"  ·  {stats['pct_of_city_land']:.1f}% of the city's land\n"
            f"Together they cover {stats['central_parks']:.0f} times the area of Central Park.",
            color=MUTED, fontsize=12, va="top", linespacing=1.5,
        )

    # Legend
    fig.legend(
        handles=[
            Patch(facecolor=VACANT, edgecolor="none", label=f"Vacant land — {stats['vacant_acres']:,.0f} acres"),
            Patch(facecolor=PARKING, edgecolor="none", label=f"Surface parking — {stats['parking_acres']:,.0f} acres"),
        ],
        loc="lower left", bbox_to_anchor=(0.03, 0.072), frameon=False,
        labelcolor=INK, fontsize=12.5, handlelength=1.3, handleheight=1.3,
    )

    fig.text(
        0.03, 0.030,
        "Sources: City of Philadelphia — L&I Vacant Property Indicators (land); Office of Property\n"
        "Assessment parcel records (surface parking). Lot areas are OPA recorded ground area.\n"
        "Parcels enlarged for visibility at citywide scale; the Center City inset is drawn to true scale.",
        color=MUTED, fontsize=7.4, va="bottom", linespacing=1.5,
    )
    fig.text(0.97, 0.030, "Progress and Poverty Institute", color=MUTED,
             fontsize=8.5, va="bottom", ha="right")

    fig.savefig(out_path, facecolor=BG, bbox_inches=None)
    plt.close(fig)
    print(f"wrote {out_path}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vacant, parking, parking_all, overlap_n = load_layers()
    stats = compute_stats(vacant, parking_all, overlap_n)
    print(json.dumps(stats, indent=2))

    city = city_boundary()
    vacant_p = vacant.to_crs(CRS_PLOT)
    parking_p = parking.to_crs(CRS_PLOT)

    (OUT_DIR / "vacant_parking_headline.json").write_text(json.dumps(stats, indent=2))
    build(stats, city, vacant_p, parking_p,
          OUT_DIR / "vacant_and_parking_headline.png", headline=True)
    build(stats, city, vacant_p, parking_p,
          OUT_DIR / "vacant_and_parking_plain.png", headline=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
