"""Aerial imagery of Philadelphia sites where LVT would bite: underused land inside a hot market.

Draws each site on Esri World Imagery with the parcel layer overlaid, so the
argument is visible rather than asserted: the empty and half-empty parcels are
outlined against the new buildings that went up next door to them.

Sites come from analysis/reports/philadelphia/lvt_opportunity_sites.json, which
scores every quarter-mile walkshed in the city — see
scripts/analyze_philly_lvt_opportunity.py for the method and for what the two
underuse measures do and do not claim.

Parcel outlines are DOR lot polygons, joined to OPA attributes on PIN. The
overlay classes:

  IDLE   vacant land (L&I) or a parcel whose OPA use IS a parking lot
  LOWFAR built, but floor area under LOWFAR_CUT of the lot — the one-storey
         store, the strip centre, the supermarket apron
  NEW    a building whose 10-year abatement started in 2018 or later

Every figure in the caption is read from the analysis JSON, never hand-typed
(see global CLAUDE.md).

Output: analysis/reports/philadelphia/lvt_site_aerial_<slug>.png
"""

import json
import sys
from pathlib import Path

import contextily as cx
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from shapely.geometry import shape

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from analyze_philly_lvt_opportunity import (  # noqa: E402
    DATA_DIR, OUT_DIR, SQFT_PER_ACRE, load_layers,
)

CRS_WEB = "EPSG:3857"
PIN_GEOM = DATA_DIR / "_dor_pin_geom.geojsonl"

BG = "#0d1117"
INK = "#f2f5f8"
MUTED = "#93a1b0"
IDLE = "#FFB020"     # vacant / surface parking
LOWFAR = "#FF4D5A"   # built but held at low intensity
NEW = "#4ADE80"      # built since 2018

SITES = [
    {
        "slug": "columbus_pennsport",
        "title": "Columbus Boulevard at Pennsport",
        "sub": "Washington Ave to Reed St, along the Delaware",
        "lat": 39.929905, "lon": -75.145873, "radius_ft": 1800,
    },
    {
        # Framed on the corridor itself, not on a point: the window is centred so
        # that the Washington Ave / Passyunk / 8th junction sits near the top and
        # the Acme at 1400 E Passyunk (4.1 acres, FAR 0.30) near the bottom, with
        # enough margin south to reach the East Passyunk shopping blocks.
        "slug": "washington_passyunk",
        "title": "E Passyunk, Washington Ave to the Acme",
        "sub": "The slack stretch between the two busy ends of Passyunk",
        "lat": 39.9335, "lon": -75.1600, "radius_ft": 1900,
        "marks": [
            {"lat": 39.93630, "lon": -75.15670,
             "label": "Washington Ave × Passyunk × 8th", "dx": -46, "dy": 42},
            {"lat": 39.93209, "lon": -75.16215,
             "label": "Acme, 1400 E Passyunk — 4.1 acres", "dx": -40, "dy": -40},
        ],
    },
]


def load_pin_polygons(bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Stream the DOR PIN geometry file, keeping features intersecting bbox.

    GDAL cannot read this repo's vector formats on Windows (see CLAUDE.md), so the
    line-delimited GeoJSON is filtered in pure Python rather than via pyogrio.
    """
    try:
        import orjson as _json

        loads = _json.loads
    except ImportError:
        loads = json.loads

    minx, miny, maxx, maxy = bbox
    rows = []
    with open(PIN_GEOM, "rb") as fh:
        for line in fh:
            line = line.strip().rstrip(b",")
            if not line.startswith(b"{"):
                continue
            feat = loads(line)
            geom = feat.get("geometry")
            if not geom:
                continue
            xs, ys = [], []
            for ring in geom["coordinates"]:
                for part in (ring if geom["type"] == "MultiPolygon" else [ring]):
                    arr = np.asarray(part, dtype=float)
                    if arr.ndim != 2:
                        continue
                    xs.append(arr[:, 0])
                    ys.append(arr[:, 1])
            if not xs:
                continue
            x = np.concatenate(xs)
            y = np.concatenate(ys)
            if x.max() < minx or x.min() > maxx or y.max() < miny or y.min() > maxy:
                continue
            rows.append({"pin": feat["properties"]["PIN"], "geometry": shape(geom)})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def site_frame(parcels_ll: gpd.GeoDataFrame, site: dict) -> gpd.GeoDataFrame:
    """Parcel polygons within the site's square window, carrying the underuse flags."""
    deg_lat = site["radius_ft"] / 364_000.0
    deg_lon = deg_lat / np.cos(np.radians(site["lat"]))
    bbox = (site["lon"] - deg_lon, site["lat"] - deg_lat,
            site["lon"] + deg_lon, site["lat"] + deg_lat)

    cache = DATA_DIR / f"_site_polys_{site['slug']}.gpq"
    if cache.exists():
        poly = gpd.read_parquet(cache)
    else:
        poly = load_pin_polygons(bbox)
        poly.to_parquet(cache)

    attrs = parcels_ll[["pin", "is_idle", "is_lowfar", "is_new", "total_area"]].copy()
    attrs["pin"] = pd.to_numeric(attrs["pin"], errors="coerce").astype("Int64")
    poly["pin"] = pd.to_numeric(poly["pin"], errors="coerce").astype("Int64")
    g = poly.merge(attrs.drop_duplicates("pin"), on="pin", how="left")
    for c in ("is_idle", "is_lowfar", "is_new"):
        g[c] = g[c].fillna(False).astype(bool)
    g.attrs["bbox"] = bbox
    return g


def draw(ax, g: gpd.GeoDataFrame, site: dict) -> dict:
    gm = g.to_crs(CRS_WEB)
    cen = gpd.GeoSeries(
        gpd.points_from_xy([site["lon"]], [site["lat"]]), crs="EPSG:4326"
    ).to_crs(CRS_WEB)
    half = site["radius_ft"] * 0.3048 / np.cos(np.radians(site["lat"]))
    cx0, cy0 = float(cen.x.iloc[0]), float(cen.y.iloc[0])
    ax.set_xlim(cx0 - half, cx0 + half)
    ax.set_ylim(cy0 - half, cy0 + half)

    cx.add_basemap(ax, source=cx.providers.Esri.WorldImagery, crs=CRS_WEB,
                   attribution=False, zoom=17)

    # All parcel lines, faint, so the fabric reads.
    gm.boundary.plot(ax=ax, color="#ffffff", linewidth=0.25, alpha=0.22, zorder=2)

    layers = [
        (gm[gm["is_idle"]], IDLE, 0.55),
        (gm[gm["is_lowfar"] & ~gm["is_idle"]], LOWFAR, 0.45),
    ]
    for sub, color, alpha in layers:
        if len(sub):
            sub.plot(ax=ax, facecolor=color, edgecolor=color, linewidth=1.2,
                     alpha=alpha, zorder=3)
            sub.boundary.plot(ax=ax, color=color, linewidth=1.3, zorder=4)
    new = gm[gm["is_new"] & ~gm["is_idle"] & ~gm["is_lowfar"]]
    if len(new):
        new.boundary.plot(ax=ax, color=NEW, linewidth=1.4, zorder=5)

    for mark in site.get("marks", []):
        mp = gpd.GeoSeries(
            gpd.points_from_xy([mark["lon"]], [mark["lat"]]), crs="EPSG:4326"
        ).to_crs(CRS_WEB)
        mx, my = float(mp.x.iloc[0]), float(mp.y.iloc[0])
        ax.annotate(
            mark["label"], xy=(mx, my),
            xytext=(mark["dx"], mark["dy"]), textcoords="offset points",
            color=INK, fontsize=11.5, fontweight="bold", zorder=9,
            ha="left" if mark["dx"] >= 0 else "right",
            va="bottom" if mark["dy"] >= 0 else "top",
            bbox=dict(facecolor=BG, edgecolor="#39424f", alpha=0.85,
                      boxstyle="round,pad=0.42"),
            arrowprops=dict(arrowstyle="-", color=INK, linewidth=1.1, alpha=0.9),
        )

    ax.set_axis_off()

    # In-frame counts, computed from what is actually drawn.
    inframe = gm.cx[cx0 - half:cx0 + half, cy0 - half:cy0 + half]
    return {
        "idle_acres": float(inframe.loc[inframe["is_idle"], "total_area"].sum() / SQFT_PER_ACRE),
        "lowfar_acres": float(
            inframe.loc[inframe["is_lowfar"] & ~inframe["is_idle"], "total_area"].sum()
            / SQFT_PER_ACRE
        ),
        "new_parcels": int(inframe["is_new"].sum()),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    scores = json.loads((OUT_DIR / "lvt_opportunity_sites.json").read_text())
    parcels, _ = load_layers()
    parcels_ll = parcels.to_crs("EPSG:4326")

    for site in SITES:
        g = site_frame(parcels_ll, site)
        fig = plt.figure(figsize=(11.0, 12.8), dpi=200, facecolor=BG)
        ax = fig.add_axes([0.0, 0.135, 1.0, 0.775])
        ax.set_facecolor(BG)
        counts = draw(ax, g, site)

        fig.text(0.035, 0.975, site["title"], color=INK, fontsize=27,
                 fontweight="bold", va="top")
        fig.text(0.035, 0.938, site["sub"], color=MUTED, fontsize=13.5, va="top")

        acres = counts["idle_acres"] + counts["lowfar_acres"]
        fig.text(0.035, 0.115,
                 f"{acres:,.0f} acres in frame are empty or built to less than "
                 f"{scores['lowfar_cut']:.0%} of the lot,\n"
                 f"beside {counts['new_parcels']:,} parcels that put up a new building "
                 f"since {scores['new_build_since']}.",
                 color=INK, fontsize=13.5, va="top", linespacing=1.6)

        handles = [
            Line2D([], [], marker="s", linestyle="none", markersize=11,
                   markerfacecolor=IDLE, markeredgecolor=IDLE,
                   label="Vacant land or surface parking"),
            Line2D([], [], marker="s", linestyle="none", markersize=11,
                   markerfacecolor=LOWFAR, markeredgecolor=LOWFAR,
                   label=f"Built below {scores['lowfar_cut']:.0%} floor-area ratio"),
            Line2D([], [], marker="s", linestyle="none", markersize=11,
                   markerfacecolor="none", markeredgecolor=NEW, markeredgewidth=2.0,
                   label=f"New building since {scores['new_build_since']}"),
        ]
        leg = ax.legend(handles=handles, loc="lower left", frameon=True,
                        facecolor=BG, edgecolor="#39424f", fontsize=11.5,
                        labelcolor=INK, borderpad=0.9, labelspacing=0.85)
        leg.get_frame().set_alpha(0.86)

        fig.text(0.035, 0.020,
                 "Imagery: Esri World Imagery. Parcels: City of Philadelphia DOR lot "
                 "polygons joined to Office of Property\nAssessment records; vacant land "
                 "from L&I Vacant Property Indicators. Floor-area ratio is OPA "
                 "total_livable_area / total_area.",
                 color=MUTED, fontsize=8.2, va="bottom", linespacing=1.6)
        fig.text(0.965, 0.020, "Progress and Poverty Institute", color=MUTED,
                 fontsize=9, ha="right", va="bottom")

        out = OUT_DIR / f"lvt_site_aerial_{site['slug']}.png"
        fig.savefig(out, facecolor=BG)
        plt.close(fig)
        print(f"wrote {out}  {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
