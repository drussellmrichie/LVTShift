"""Condo units on the S5 reassessment export hold their share of the building's lot, not all of it.

Real data, not a fixture: the defect was a data shape (a unit with no lot of its own inheriting
the building's), so only the export can show it. Skipped when the gitignored export is absent.
Rebuild it with
    LVT_LAND_SURFACE=s5 jupyter nbconvert --to notebook --execute --output _executed_s5.ipynb \
        cities/philadelphia/model_lycd_reassessment.ipynb
"""
from pathlib import Path

import pandas as pd
import pytest

EXPORT = Path(__file__).resolve().parents[1] / "analysis" / "data" / "philadelphia_lycd_reassessment_ty2026_s5.csv"

# One Riverside, 210-20 S 25th St: a condo unit on a ~28,000 sqft building lot, and two of its
# sibling units. Before the fix each carried the whole lot, so land was capped at 100% of value.
UNITS = [888089760, 888089758, 888089642]


@pytest.fixture(scope="module")
def units() -> pd.DataFrame:
    if not EXPORT.exists():
        pytest.skip(f"{EXPORT.name} not built")
    rows = []
    for chunk in pd.read_csv(EXPORT, chunksize=200_000, encoding="utf-8", encoding_errors="replace",
                             usecols=["parcel_id", "dor_area_sqft", "area_source", "lycd_land_value",
                                      "land_surface_psf", "market_value"]):
        rows.append(chunk[pd.to_numeric(chunk["parcel_id"], errors="coerce").isin(UNITS)])
    df = pd.concat(rows)
    df["parcel_id"] = pd.to_numeric(df["parcel_id"]).astype(int)
    return df.set_index("parcel_id")


def test_one_riverside_unit_holds_its_share_of_the_lot(units):
    u = units.loc[888089760]
    assert u["area_source"] == "condo_share"
    # ~3.0% livable-area share of a ~28,000 sqft lot is ~844 sqft; the whole lot is ~28,000.
    assert 750 < u["dor_area_sqft"] < 950
    assert u["lycd_land_value"] == pytest.approx(u["land_surface_psf"] * u["dor_area_sqft"], rel=1e-6)
    assert u["lycd_land_value"] < 0.10 * u["market_value"]


def test_sibling_units_share_one_lot_rather_than_each_holding_it(units):
    assert units["area_source"].eq("condo_share").all()
    # Three units of a ~28,000 sqft lot together hold a small fraction of it.
    assert units["dor_area_sqft"].sum() < 0.10 * 28_000
