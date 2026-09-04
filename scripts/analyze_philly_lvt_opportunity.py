"""Rank Philadelphia's walkable neighborhoods by 'underused land where demand already exists'.

The question: where is a lot of land held at low intensity *in a place people are
demonstrably willing to build*? Idle land alone is not an LVT story — most of
Philadelphia's vacant acreage sits where nobody wants to build, and taxing it
harder mostly raises bills on land that stays empty. The interesting case is the
co-occurrence: underused land inside a market already producing new buildings on
the parcels next door.

TWO underuse measures, kept separate on purpose — they are not the same claim.

  idle_acres     Literally empty: vacant land (L&I Vacant Indicators, Land) plus
                 surface parking (OPA `%PKG LOT%` building codes), deduplicated
                 so a parcel in both counts once, as parking. This is the
                 measure behind the 2,527-acre headline figure, and it is a
                 FLOOR: it only sees parcels whose *primary* OPA use is a lot.
                 A supermarket or strip centre whose site is mostly parking
                 apron is coded by its store and is invisible here — 1400 E
                 Passyunk Ave (4.1 acres, `SUPERMKT 1 STY MASONRY`) is the
                 canonical miss.

  lowfar_acres   Held at low intensity: non-exempt, non-single-family parcels
                 whose floor area ratio (OPA `total_livable_area / total_area`)
                 is under LOWFAR_CUT. This is what catches the one-storey store,
                 the gas station, the strip centre and the supermarket apron.
                 Single-family is excluded because a detached house on a large
                 Northeast lot is low-FAR without being an infill site, and
                 exempt parcels are excluded because a city park is not a
                 development opportunity.

  underused_acres  The union of the two, deduplicated by parcel.

Demand, per window, from two independent signals — a price level and a revealed
quantity — because either alone is easy to fool:

  price_psf      median market_value / total_area over IMPROVED, non-underused
                 parcels. An underused parcel's own assessed value is the thing
                 under test, not the evidence for demand.
  new_since_2018 parcels whose 10-year construction abatement began in 2018 or
                 later, i.e. buildings that actually went up. `start_year_a` is
                 left-censored at 2015 (the assessment history begins there),
                 which is why the window starts at 2018 and not earlier.

Geometry: a quarter-mile-radius moving window (125 acres — a walkshed) centred
on every cell of a 500 ft grid. Windows overlap by construction, so reported
sites are non-maximum-suppressed at a half-mile spacing before being named.

A site must clear the citywide median on BOTH demand signals; the ranking among
those is by underused_acres. Nothing here is hand-typed: every figure in the
outputs is computed from the source layers (see global CLAUDE.md).

Outputs: analysis/data/philadelphia_lvt_opportunity_sites.csv
         analysis/reports/philadelphia/lvt_opportunity_sites.json
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "cities" / "philadelphia" / "data"
OUT_DIR = REPO_ROOT / "analysis" / "reports" / "philadelphia"
EXPORT_DIR = REPO_ROOT / "analysis" / "data"
ATTR_PATH = REPO_ROOT / "analysis" / "ownership" / "philadelphia" / "opa_attributes.parquet"

CRS_PLOT = "EPSG:2272"  # PA State Plane South, feet
SQFT_PER_ACRE = 43560.0

GRID_FT = 500.0
WINDOW_FT = 1320.0  # quarter mile
SUPPRESS_FT = 2640.0  # half mile between reported sites
NEW_BUILD_SINCE = 2018
LOWFAR_CUT = 0.40

# Windows aggregate parcels by centroid, so a parcel counts wholly into whichever
# window its centroid lands in. Uncapped, that lets a single 600-acre rail yard or
# refinery in Tacony outrank every genuine infill corridor in the city. The low-FAR
# measure is about the walkable urban fabric — a strip centre, a supermarket apron,
# a one-storey store — so parcels above this size are excluded from it. `idle` is
# deliberately NOT capped: a 65-acre stadium lot really is 65 acres of parking.
#
# 30 acres is where the cap stops changing the ranking and starts only removing
# genuine mega-sites: going 10 -> 30 admits 176 more parcels (big-box centres, the
# 25-acre office-plus-parking slab at 1301 S Columbus Blvd) while the parcels it
# still excludes are a 1,616-acre multi-family tract, an 850-acre commercial one
# and the rail/refinery land above 100 acres.
LOWFAR_MAX_ACRES = 30.0

# Categories excluded from the low-FAR measure: a detached house on a big
# Northeast lot is low-FAR without being an infill site.
LOWFAR_EXCLUDE_CATS = {"SINGLE FAMILY", "GARAGE - RESIDENTIAL"}

# Demand bar for a reported site. The median is too weak a filter — half the city
# clears it, including places whose "underuse" is simply low demand.
PRICE_PCTL = 75.0
NEW_PCTL = 60.0

# The user's own corridor, for a named comparison against the ranked list:
# Washington Ave / E Passyunk / S 8th St, South Philadelphia.
REFERENCE_POINT = (-75.1583, 39.9375)
REFERENCE_NAME = "Washington Ave / E Passyunk / S 8th"


def _norm_id(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.split(".").str[0].str.zfill(9)


def load_layers() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    parcels = gpd.read_parquet(DATA_DIR / "parcels_ty2026.gpq")
    vacant = gpd.read_parquet(DATA_DIR / "vacant_land_lni.gpq")
    parking = gpd.read_parquet(DATA_DIR / "surface_parking_opa.gpq")
    abate = pd.read_parquet(DATA_DIR / "abatement_sunsets.parquet")
    area = pd.read_parquet(DATA_DIR / "opa_building_area.parquet")
    attrs = pd.read_parquet(ATTR_PATH)

    parcels["pid"] = _norm_id(parcels["parcel_number"])

    # A parcel present in both idle layers counts once, as parking.
    park_ids = set(_norm_id(parking["parcel_number"]))
    vac_ids = set(_norm_id(vacant["opa_id"])) - park_ids - {"000000000", "00000None"}
    parcels["is_parking"] = parcels["pid"].isin(park_ids)
    parcels["is_vacant"] = parcels["pid"].isin(vac_ids)
    parcels["is_idle"] = parcels["is_parking"] | parcels["is_vacant"]

    recent = abate.loc[abate["start_year_a"] >= NEW_BUILD_SINCE, "parcel_number"]
    parcels["is_new"] = parcels["pid"].isin(set(_norm_id(recent)))

    area["pid"] = _norm_id(area["parcel_number"])
    attrs["pid"] = _norm_id(attrs["parcel_number"])
    parcels = parcels.merge(
        area[["pid", "total_livable_area"]].drop_duplicates("pid"), on="pid", how="left"
    ).merge(
        attrs[["pid", "category_code_description"]].drop_duplicates("pid"),
        on="pid", how="left",
    )

    for c in ("total_area", "market_value", "total_livable_area",
              "taxable_land", "taxable_building", "exempt_land", "exempt_building"):
        parcels[c] = pd.to_numeric(parcels[c], errors="coerce")
    parcels = parcels[parcels["total_area"].between(1, 5_000_000, inclusive="both")]

    parcels["far"] = parcels["total_livable_area"].fillna(0) / parcels["total_area"]
    exempt = (parcels["taxable_land"].fillna(0) + parcels["taxable_building"].fillna(0)) <= 0
    parcels["is_lowfar"] = (
        (parcels["far"] < LOWFAR_CUT)
        & ~exempt
        & ~parcels["category_code_description"].isin(LOWFAR_EXCLUDE_CATS)
        & (parcels["total_area"] <= LOWFAR_MAX_ACRES * SQFT_PER_ACRE)
    )
    parcels["is_underused"] = parcels["is_idle"] | parcels["is_lowfar"]

    # Price level is read off improved, fully-used parcels only.
    improved = (parcels["taxable_building"].fillna(0) > 0) & ~parcels["is_underused"]
    parcels["price_psf"] = np.where(
        improved & (parcels["market_value"] > 0),
        parcels["market_value"] / parcels["total_area"],
        np.nan,
    )

    parcels = parcels.to_crs(CRS_PLOT)
    hoods = gpd.read_parquet(DATA_DIR / "neighborhoods.gpq").to_crs(CRS_PLOT)
    return parcels, hoods


def window_stats(parcels: gpd.GeoDataFrame) -> pd.DataFrame:
    xy = np.column_stack([parcels.geometry.x.values, parcels.geometry.y.values])
    keep = np.isfinite(xy).all(axis=1)
    parcels, xy = parcels.loc[keep], xy[keep]

    minx, miny = xy.min(axis=0)
    maxx, maxy = xy.max(axis=0)
    cx, cy = np.meshgrid(np.arange(minx, maxx + GRID_FT, GRID_FT),
                         np.arange(miny, maxy + GRID_FT, GRID_FT))
    centers = np.column_stack([cx.ravel(), cy.ravel()])

    tree = cKDTree(xy)
    centers = centers[tree.query_ball_point(centers, WINDOW_FT, return_length=True) >= 25]

    area = parcels["total_area"].values
    idle = parcels["is_idle"].values
    lowfar = parcels["is_lowfar"].values
    under = parcels["is_underused"].values
    new = parcels["is_new"].values
    psf = parcels["price_psf"].values

    rows = []
    for (x, y), idx in zip(centers, tree.query_ball_point(centers, WINDOW_FT)):
        idx = np.asarray(idx)
        a = area[idx]
        p = psf[idx]
        p = p[np.isfinite(p)]
        rows.append((
            x, y,
            a[idle[idx]].sum() / SQFT_PER_ACRE,
            a[lowfar[idx]].sum() / SQFT_PER_ACRE,
            a[under[idx]].sum() / SQFT_PER_ACRE,
            a.sum() / SQFT_PER_ACRE,
            int(new[idx].sum()),
            float(np.median(p)) if p.size >= 10 else np.nan,
            int(under[idx].sum()),
        ))

    df = pd.DataFrame(rows, columns=[
        "x", "y", "idle_acres", "lowfar_acres", "underused_acres",
        "parcel_acres", "new_since_2018", "price_psf", "underused_parcels",
    ])
    df["underused_share"] = df["underused_acres"] / df["parcel_acres"]
    return df


def select_sites(df: pd.DataFrame) -> pd.DataFrame:
    price_cut = float(np.nanpercentile(df["price_psf"], PRICE_PCTL))
    new_cut = float(np.nanpercentile(df["new_since_2018"], NEW_PCTL))
    ok = (
        df["price_psf"].notna()
        & (df["price_psf"] >= price_cut)
        & (df["new_since_2018"] >= new_cut)
        & (df["underused_acres"] > 0)
    )
    cand = df.loc[ok].sort_values("underused_acres", ascending=False).reset_index(drop=True)

    kept: list[int] = []
    pts = cand[["x", "y"]].values
    for i in range(len(cand)):
        if all(np.hypot(*(pts[i] - pts[j])) >= SUPPRESS_FT for j in kept):
            kept.append(i)
        if len(kept) >= 40:
            break
    out = cand.iloc[kept].copy()
    out.attrs["price_cut"] = float(price_cut)
    out.attrs["new_cut"] = float(new_cut)
    return out


def name_sites(sites: pd.DataFrame, hoods: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites["x"], sites["y"]),
                         crs=CRS_PLOT)
    g = gpd.sjoin(g, hoods[["id", "geometry"]], how="left", predicate="within")
    g = g.drop(columns=["index_right"]).rename(columns={"id": "neighborhood"})
    ll = g.to_crs("EPSG:4326")
    g["lon"], g["lat"] = ll.geometry.x, ll.geometry.y
    return g


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parcels, hoods = load_layers()
    print(f"parcels {len(parcels):,}  idle {int(parcels['is_idle'].sum()):,}  "
          f"low-FAR {int(parcels['is_lowfar'].sum()):,}  "
          f"underused {int(parcels['is_underused'].sum()):,}  "
          f"new since {NEW_BUILD_SINCE} {int(parcels['is_new'].sum()):,}")

    cache = DATA_DIR / "_lvt_opportunity_windows.parquet"
    if cache.exists() and "--rebuild" not in sys.argv:
        df = pd.read_parquet(cache)
    else:
        df = window_stats(parcels)
        df.to_parquet(cache)
    print(f"windows {len(df):,}")

    sites = select_sites(df)
    named = name_sites(sites, hoods)

    ref = gpd.GeoSeries(gpd.points_from_xy([REFERENCE_POINT[0]], [REFERENCE_POINT[1]]),
                        crs="EPSG:4326").to_crs(CRS_PLOT)
    rx, ry = float(ref.x.iloc[0]), float(ref.y.iloc[0])
    ref_row = df.loc[np.hypot(df["x"] - rx, df["y"] - ry).idxmin()]
    metrics = ["idle_acres", "lowfar_acres", "underused_acres", "underused_share",
               "price_psf", "new_since_2018"]
    ref_pct = {c: float((df[c] <= ref_row[c]).mean() * 100) for c in metrics}

    cols = ["neighborhood", "lat", "lon", "underused_acres", "idle_acres",
            "lowfar_acres", "underused_share", "price_psf", "new_since_2018",
            "underused_parcels", "parcel_acres"]
    out_csv = EXPORT_DIR / "philadelphia_lvt_opportunity_sites.csv"
    named[cols].to_csv(out_csv, index=False)

    payload = {
        "window_radius_ft": WINDOW_FT,
        "window_acres": float(np.pi * WINDOW_FT**2 / SQFT_PER_ACRE),
        "grid_ft": GRID_FT,
        "new_build_since": NEW_BUILD_SINCE,
        "lowfar_cut": LOWFAR_CUT,
        "windows_scored": int(len(df)),
        "price_psf_cut": sites.attrs["price_cut"],
        "new_since_2018_cut": sites.attrs["new_cut"],
        "sites": named[cols].head(15).to_dict(orient="records"),
        "reference": {
            "name": REFERENCE_NAME,
            "lat": REFERENCE_POINT[1], "lon": REFERENCE_POINT[0],
            **{c: float(ref_row[c]) for c in metrics + ["parcel_acres"]},
            "citywide_percentile": ref_pct,
        },
    }
    (OUT_DIR / "lvt_opportunity_sites.json").write_text(json.dumps(payload, indent=2))

    print(f"\nwrote {out_csv}")
    print(named[cols].head(15).to_string(index=False))
    print(f"\n{REFERENCE_NAME}")
    print(json.dumps(payload["reference"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
