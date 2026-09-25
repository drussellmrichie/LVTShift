"""Lots whose OPA area the sibling repo rejected carry its corrected area on the S5 export.

Real data, not a fixture: the defect was a data shape (an OPA record 2-3x the lot, under a rate
fitted on the true size), so only the export can show it. The expected areas are read from the
sibling repo's land roll, not retyped here. Skipped when either gitignored file is absent.
Rebuild the export with
    LVT_LAND_SURFACE=s5 jupyter nbconvert --to notebook --execute --output _executed_s5.ipynb \
        cities/philadelphia/model_lycd_reassessment.ipynb
"""
import os
from pathlib import Path

import pandas as pd
import pytest

EXPORT = Path(__file__).resolve().parents[1] / "analysis" / "data" / "philadelphia_lycd_reassessment_ty2026_s5.csv"
ROLL = (Path(os.environ.get("PHILLY_AVMKIT_ROOT", "C:/projects/philly_open_avmkit"))
        / "notebooks" / "pipeline" / "data" / "us-pa-philadelphia" / "out" / "land" / "land_roll_ty2026.csv")

# 3102 Mechanicsville Rd: OPA records ~3x the lot and the DOR match is a borrowed polygon, so
# neither of this repo's own area sources could correct it.
PINNED = "786322300"


@pytest.fixture(scope="module")
def flagged() -> pd.DataFrame:
    if not EXPORT.exists() or not ROLL.exists():
        pytest.skip("S5 export or sibling land roll not built")
    roll = pd.read_csv(ROLL, usecols=["parcel_number", "land_area_sqft", "land_area_source"],
                       dtype={"parcel_number": str})
    if "pwd_dor" not in set(roll["land_area_source"]):
        pytest.skip("sibling land roll predates its lot-area rule")
    roll = roll[roll["land_area_source"].eq("pwd_dor")].copy()
    roll["key"] = roll["parcel_number"].str.strip().str.zfill(9)
    rows = []
    for chunk in pd.read_csv(EXPORT, chunksize=200_000, encoding="utf-8", encoding_errors="replace",
                             usecols=["parcel_id", "dor_area_sqft", "area_source"], dtype={"parcel_id": str}):
        chunk["key"] = chunk["parcel_id"].str.strip().str.zfill(9)
        rows.append(chunk[chunk["key"].isin(roll["key"])])
    return pd.concat(rows).merge(roll[["key", "land_area_sqft"]], on="key").set_index("key")


def test_no_flagged_lot_keeps_an_inflated_area(flagged):
    assert len(flagged) > 0
    assert (flagged["dor_area_sqft"] <= 2 * flagged["land_area_sqft"]).all()
    assert not flagged["area_source"].eq("opa_total_area").any()


def test_the_borrowed_polygon_lot_takes_the_sibling_repos_area(flagged):
    lot = flagged.loc[PINNED]
    assert lot["area_source"] == "pwd_dor"
    assert lot["dor_area_sqft"] == pytest.approx(lot["land_area_sqft"], rel=1e-9)
