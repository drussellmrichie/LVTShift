"""
Philadelphia — FHFA land price per square foot by census tract
-----------------------------------------------------------------
Choropleth of single-family residential land value ($/sqft), from the FHFA's
land-price dataset (Davis, Larson, Oliner & Shui WP 19-01, June 2024 update),
Cross-Section Census Tracts sheet, converted from $/acre to $/sqft and moved from
FHFA's 2010 census tracts onto 2020 tracts.

This is the external benchmark used in the mayor-exposure deep audit
(analysis/political/philadelphia_mayor_exposure_audit.md, Link 2b) to
sanity-check the LYCD model's flat 20% land-share assumption — this map is
the spatial picture behind that number: land price is not uniform across
the city, it's concentrated in Center City / high-demand tracts.

Data sources:
  - cities/philadelphia/data/fhfa_land_share_by_tract.csv, written by
    scripts/build_philadelphia_fhfa_tract_shares.py (FHFA's tract estimates on
    2020 tracts; see that script for the crosswalk).
  - Census tract boundaries via lvt.census_utils.get_census_tracts_shapefile,
    cached at cities/philadelphia/data/census_tracts.gpq.

Output: analysis/reports/philadelphia/fhfa_land_price_per_sqft.png
"""

import sys
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FHFA_TRACTS = REPO_ROOT / "cities/philadelphia/data/fhfa_land_share_by_tract.csv"
TRACTS_PATH = REPO_ROOT / "cities/philadelphia/data/census_tracts.gpq"
OUTPUT_PATH = REPO_ROOT / "analysis/reports/philadelphia/fhfa_land_price_per_sqft.png"

def load_fhfa_land_price() -> pd.DataFrame:
    f = pd.read_csv(FHFA_TRACTS, dtype={"tract_geoid": str})
    return f.rename(columns={"fhfa_land_price_psf": "land_price_psf", "fhfa_land_share": "land_share",
                             "fhfa_property_value": "property_value"})


def main():
    print("Loading FHFA land-price data...")
    fhfa = load_fhfa_land_price()
    print(f"  {len(fhfa)} Philadelphia tracts with FHFA single-family land-price estimates")

    print("Loading census tract boundaries...")
    tracts = gpd.read_parquet(TRACTS_PATH)
    gdf = tracts.merge(fhfa, on="tract_geoid", how="left")
    matched = gdf["land_price_psf"].notna().sum()
    print(f"  {matched} of {len(gdf)} tracts matched (FHFA covers single-family-dominant tracts only)")

    gdf_plot = gdf.to_crs("EPSG:3857")

    cmap = matplotlib.colormaps.get_cmap("YlOrRd")
    vals = gdf_plot["land_price_psf"].dropna()
    vmin, vmax = vals.quantile(0.02), vals.quantile(0.98)
    norm = mcolors.Normalize(vmin=vmin, vmax=vmax)

    fig, ax = plt.subplots(figsize=(10, 11))

    gdf_plot.plot(
        column="land_price_psf",
        cmap=cmap,
        norm=norm,
        linewidth=0.3,
        edgecolor="white",
        ax=ax,
        missing_kwds={"color": "#e5e5e5", "hatch": "///", "edgecolor": "#bbbbbb", "linewidth": 0.3},
    )

    ax.set_axis_off()

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cbar = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02, shrink=0.7)
    cbar.set_label("Single-family land price ($/sqft)\nFHFA WP 19-01, 2024 update", fontsize=9)

    ax.set_title(
        "Philadelphia — residential land price per square foot\n(FHFA tract-level land-price estimates)",
        fontsize=13,
        fontweight="bold",
    )

    n_missing = gdf["land_price_psf"].isna().sum()
    fig.text(
        0.5, 0.02,
        f"Median ${vals.median():.0f}/sqft (p10 ${vals.quantile(.1):.0f}, p90 ${vals.quantile(.9):.0f}) "
        f"across {matched} tracts. Hatched = no FHFA estimate ({n_missing} tracts, "
        f"typically too few qualifying single-family appraisals).",
        fontsize=8.5,
        va="bottom",
        ha="center",
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT_PATH, dpi=150, bbox_inches="tight")
    print(f"Saved: {OUTPUT_PATH}")
    print(f"  $/sqft: min ${vals.min():.0f}, p25 ${vals.quantile(.25):.0f}, median ${vals.median():.0f}, "
          f"p75 ${vals.quantile(.75):.0f}, max ${vals.max():.0f}")


if __name__ == "__main__":
    main()
