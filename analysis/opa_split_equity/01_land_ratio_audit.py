"""Audit: how many improved Philadelphia parcels carry OPA's default 20% land share?

OPA reports a land value and a building value per parcel. This script measures how often the
land share (land / (land + building), both counting exempt dollars) sits at exactly 0.200,
by tax-year vintage, property category and value band. Every number lands in `out/`; nothing
is typed by hand.

Run from the repo root:
    python analysis/opa_split_equity/01_land_ratio_audit.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "cities" / "philadelphia" / "data"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

YEARS = (2024, 2026, 2027)
COLS = ["parcel_number", "taxable_land", "taxable_building", "exempt_land", "exempt_building",
        "market_value", "category_code", "homestead_exemption"]

# OPA category codes. Same map `scripts/philadelphia_council_one_pager.py` uses (the repo's
# canonical one) -- codes 7-11 and 14-15 are NOT vacant land; only 6/12/13 are
# (`lvt.philadelphia.VACANT_CATEGORY_CODES`). An earlier draft of this script bucketed 7-16 as
# vacant land wholesale, which misclassified large multi-family (14) and every commercial/hotel
# code among them.
CATEGORY = {"1": "Single Family Residential", "2": "Small Multi-Family (2-4 units)",
            "3": "Mixed Use", "4": "Commercial", "5": "Industrial", "6": "Vacant Land",
            "7": "Other Commercial", "8": "Other Residential", "9": "Hotel",
            "10": "Office / Commercial Condo", "11": "Other", "12": "Vacant Land",
            "13": "Vacant Land", "14": "Large Multi-Family (5+ units)",
            "15": "Retail / General Commercial", "16": "Other"}


def load(year: int) -> pd.DataFrame:
    df = pd.read_parquet(DATA / f"parcels_ty{year}.gpq", columns=COLS)
    for c in COLS[1:6]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["land"] = df.taxable_land + df.exempt_land
    df["bldg"] = df.taxable_building + df.exempt_building
    df["total"] = df.land + df.bldg
    df["category_code"] = df.category_code.astype(str)
    return df


def improved(df: pd.DataFrame) -> pd.DataFrame:
    """Parcels with both a positive land and a positive building value."""
    imp = df[(df.land > 0) & (df.bldg > 0)].copy()
    imp["share"] = imp.land / imp.total
    # OPA values are whole dollars, so an assessor who applied 20% to a total leaves
    # |5*land - total| of at most a few dollars; the tolerances below bracket that.
    gap = (5 * imp.land - imp.total).abs()
    imp["exact20"] = gap == 0
    imp["within5"] = gap <= 5
    imp["within_half_pt"] = (imp.share - 0.2).abs() <= 0.0005
    return imp


def rates(imp: pd.DataFrame) -> pd.Series:
    return pd.Series({
        "n_improved": len(imp),
        "pct_exactly_0.200": 100 * imp.exact20.mean(),
        "pct_within_$5": 100 * imp.within5.mean(),
        "pct_within_0.05pt": 100 * imp.within_half_pt.mean(),
        "pct_of_value_within_0.05pt": 100 * imp.total[imp.within_half_pt].sum() / imp.total.sum(),
        "median_share": imp.share.median(),
    })


def main() -> None:
    by_year, frames = {}, {}
    for y in YEARS:
        imp = improved(load(y))
        frames[y] = imp
        by_year[y] = rates(imp)
    by_year = pd.DataFrame(by_year).T
    by_year.index.name = "tax_year"
    by_year.to_csv(OUT / "land_ratio_by_year.csv")
    print("== by tax-year vintage ==\n", by_year.round(2).to_string(), "\n")

    # Measurement basis. The taxable columns already net out the Homestead Exemption, which is a
    # flat amount off the building line, so a homesteaded parcel's taxable land share is pushed
    # off 0.200 even though OPA assigned it 0.200. Only the full-value share (taxable + exempt)
    # reads the assessor's own split.
    basis = {}
    for y in YEARS:
        df = load(y)
        both = df[(df.taxable_land > 0) & (df.taxable_building > 0)]
        share_taxable = both.taxable_land / (both.taxable_land + both.taxable_building)
        basis[y] = {"pct_at_0.200_full_value": by_year.loc[y, "pct_within_0.05pt"],
                    "pct_at_0.200_taxable_only": 100 * ((share_taxable - 0.2).abs() <= 0.0005).mean(),
                    "pct_improved_with_any_exemption":
                        100 * ((frames[y].exempt_land + frames[y].exempt_building) > 0).mean()}
    basis = pd.DataFrame(basis).T
    basis.index.name = "tax_year"
    basis.to_csv(OUT / "land_ratio_measurement_basis.csv")
    print("== measurement basis ==\n", basis.round(1).to_string(), "\n")

    imp = frames[2026]
    imp["category"] = imp.category_code.map(CATEGORY).fillna("Other")
    by_cat = imp.groupby("category").apply(rates, include_groups=False)
    by_cat.to_csv(OUT / "land_ratio_by_category_ty2026.csv")
    print("== by category, ty2026 ==\n", by_cat.round(2).to_string(), "\n")

    imp["value_band"] = pd.qcut(imp.total, 10, labels=[f"D{i}" for i in range(1, 11)])
    by_band = imp.groupby("value_band", observed=True).apply(rates, include_groups=False)
    by_band.to_csv(OUT / "land_ratio_by_value_decile_ty2026.csv")
    print("== by total-value decile, ty2026 ==\n", by_band.round(2).to_string(), "\n")

    off = imp[~imp.within_half_pt]
    top = off.share.round(3).value_counts().head(12).rename("n_parcels").to_frame()
    top.index.name = "share_rounded"
    top.to_csv(OUT / "off_default_share_modes_ty2026.csv")
    print("== most common shares among parcels NOT at 0.200, ty2026 ==\n", top.to_string())


if __name__ == "__main__":
    main()
