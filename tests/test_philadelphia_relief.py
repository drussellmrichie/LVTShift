"""Relief against total value is not a construction abatement.

A zero-building-line parcel whose non-homestead relief reaches the land line is relief against
total value; an abatement exempts the improvement only. These tests pin how the zero-building
split, the abatement cohort and the land re-split treat it.
"""
import numpy as np
import pandas as pd
import pytest

from lvt.philadelphia import (
    expand_abatement_cohort, reallocate_land_within_total, split_zero_building_parcels,
)

CAP = 100_000.0
CATEGORY_MAP = {"1": "Single Family Residential"}


def _zero_building_frame() -> pd.DataFrame:
    return pd.DataFrame({
        # 0 full abatement: the improvement exempt, nothing on land
        # 1 long-running relief: spent the building and reached the land, no homestead
        # 2 homestead-zeroed: the exemption is the homestead alone
        # 3 abatement plus homestead: the only land exemption is homestead spill
        "parcel_number":    ["000000001", "000000002", "000000003", "000000004"],
        "category_code":    ["1", "1", "1", "1"],
        "taxable_land":     [40_000, 34_000, 20_000, 20_000],
        "taxable_building": [0, 0, 0, 0],
        "exempt_land":      [0, 14_000, 0, 30_000],
        "exempt_building":  [300_000, 183_000, 60_000, 400_000],
        "homestead_exemption": [0, 0, CAP, CAP],
    }).assign(market_value=lambda d: d.taxable_land + d.taxable_building + d.exempt_land + d.exempt_building)


def _split(df):
    category = pd.Series("Vacant Land", index=df.index)   # what Override 1 calls a $0 building line
    return split_zero_building_parcels(df, category, CAP, CATEGORY_MAP)


def test_relief_reaching_land_is_not_abated_and_keeps_its_category():
    z = _split(_zero_building_frame())
    assert z.total_value_relief.tolist() == [False, True, False, False]
    assert z.abated.tolist() == [True, False, False, True]
    assert z.category[1] == "Single Family Residential"
    assert z.category[0] == "Abated / Construction Exemption"


def test_homestead_spill_onto_land_does_not_count_as_total_value_relief():
    """Parcel 3's $30k of exempt land is the homestead the building could not absorb once the
    abatement had taken it: still an abatement."""
    z = _split(_zero_building_frame())
    assert bool(z.abated[3]) and not bool(z.total_value_relief[3])


def _classification(tmp_path, schedule_by_parcel):
    pd.DataFrame({"parcel_number": list(schedule_by_parcel), "schedule_type": list(schedule_by_parcel.values())}
                 ).to_parquet(tmp_path / "abatement_classification_ty2026.parquet")


def test_expand_releases_classified_relief_only_when_given_a_category_map(tmp_path):
    df = _zero_building_frame()
    z = _split(df)
    _classification(tmp_path, {"000000001": "old_flat_100", "000000004": "non_abatement_relief"})
    kept = expand_abatement_cohort(df, z.category, z.abated, 2026, data_dir=tmp_path)
    assert kept.abated.tolist() == z.abated.tolist()          # default: unchanged
    assert not kept.released.any()
    rel = expand_abatement_cohort(df, z.category, z.abated, 2026, data_dir=tmp_path, category_map=CATEGORY_MAP)
    assert rel.released.tolist() == [False, False, False, True]
    assert rel.abated.tolist() == [True, False, False, False]
    assert rel.category[3] == "Single Family Residential"


def _loop_like_building_share():
    """Long-running relief that fits inside the building line with no land exempt: arithmetic alone reads it
    as building_share."""
    return pd.DataFrame({
        "taxable_land": [50_000.0], "taxable_building": [40_000.0],
        "exempt_land": [0.0], "exempt_building": [110_000.0], "homestead_exemption": [0.0],
    })


def test_total_value_relief_forces_total_share_and_keeps_opa_reconstruction():
    df = _loop_like_building_share()
    opa_land = df.taxable_land + df.exempt_land
    plain = reallocate_land_within_total(df.assign(nl=opa_land), new_land_col="nl", homestead_cap=CAP)
    forced = reallocate_land_within_total(df.assign(nl=opa_land), new_land_col="nl", homestead_cap=CAP,
                                          total_value_relief=[True])
    assert plain.exemption_kind[0] == "building_share"
    assert forced.exemption_kind[0] == "total_share"
    assert forced.diagnostics["reconstruction_match_rate"] == 1.0
    assert forced.alloc_taxable_total[0] == pytest.approx(90_000.0)


def test_value_share_relief_keeps_the_dollars_and_splits_them_pro_rata():
    df = _loop_like_building_share()                    # gross 200k: land 50k, building 150k
    new_land = pd.Series([120_000.0])                   # the land estimate rises
    kw = dict(new_land_col="nl", homestead_cap=CAP, total_value_relief=[True])
    bf = reallocate_land_within_total(df.assign(nl=new_land), **kw)
    vs = reallocate_land_within_total(df.assign(nl=new_land), relief_order="value_share", **kw)
    # Same dollars exempted either way: the taxable total is OPA's.
    assert bf.alloc_taxable_total[0] == pytest.approx(90_000.0)
    assert vs.alloc_taxable_total[0] == pytest.approx(90_000.0)
    # Building-first spends the relief on the 80k building and taxes 10k less of the land.
    assert bf.alloc_taxable_land[0] == pytest.approx(90_000.0)
    # Pro rata: the taxable lines keep the parcel's own land share, 120k / 200k.
    assert vs.alloc_taxable_land[0] / vs.alloc_taxable_total[0] == pytest.approx(0.6)


def test_relief_order_default_is_unchanged_and_is_validated():
    df = _loop_like_building_share()
    nl = pd.Series([120_000.0])
    a = reallocate_land_within_total(df.assign(nl=nl), new_land_col="nl", homestead_cap=CAP)
    b = reallocate_land_within_total(df.assign(nl=nl), new_land_col="nl", homestead_cap=CAP,
                                     relief_order="building_first")
    assert np.allclose(a.alloc_taxable_land, b.alloc_taxable_land)
    with pytest.raises(ValueError, match="relief_order"):
        reallocate_land_within_total(df.assign(nl=nl), new_land_col="nl", homestead_cap=CAP,
                                     relief_order="land_first")
