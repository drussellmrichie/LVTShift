"""Unit tests for the shared Philadelphia LYCD construction and exemption carry-forward.

Synthetic data only, no network or cache dependencies.
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lvt.philadelphia import (  # noqa: E402
    compute_lycd_land_values,
    carry_forward_exemptions,
)


def _toy_city(n_per_zone: int = 60) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    """Two L3 zones inside one L2/L1; zone A improved parcels at $100/sqft, zone B at $200/sqft."""
    rows = []
    k = 0
    for zone, psf, x0 in (("A", 100.0, 0.0), ("B", 200.0, 10_000.0)):
        for i in range(n_per_zone):
            rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                             total_area=1000.0, market_value=psf * 1000.0, x=x0 + i, y=0.0,
                             zone=zone))
            k += 1
        # one vacant lot per zone, OPA-valued far below the zone rate
        rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="6",
                         total_area=500.0, market_value=5_000.0, x=x0 + 1, y=1.0, zone=zone))
        k += 1
    # an improved parcel in zone A with no OPA area but a PIN polygon
    rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                     total_area=0.0, market_value=100_000.0, x=2.0, y=1.0, zone="A"))
    k += 1
    # an improved parcel with no GMA assignment at all, sitting in zone B's cluster
    rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                     total_area=1000.0, market_value=200_000.0, x=10_003.0, y=1.0, zone=None))
    k += 1
    # a cheap house in the expensive zone: the market-value cap must bind
    rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                     total_area=1000.0, market_value=20_000.0, x=10_004.0, y=1.0, zone="B"))
    df = pd.DataFrame(rows)
    gdf = gpd.GeoDataFrame(df.drop(columns=["x", "y"]),
                           geometry=[Point(x, y) for x, y in zip(df.x, df.y)], crs="EPSG:3857")
    gma = pd.DataFrame({"key": df.parcel_number, "gma3": df.zone, "gma2": "L2", "gma1": "L1"})
    gma = gma[gma.gma3.notna()]
    pin_areas = pd.DataFrame({"pin": df.pin, "pin_area_sqft": np.where(df.total_area > 0, df.total_area, 800.0)})
    return gdf, gma, pin_areas


def test_lycd_zone_rate_times_area():
    gdf, gma, pin_areas = _toy_city()
    res = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=50, city_area_sqft=1e9)
    out = res.gdf.set_index("parcel_number")
    a_imp = out[(out.gma3 == "A") & (out.category_code == "1") & (out.total_area > 0)]
    # zone A: median 100 $/sqft x 0.20 x 1000 sqft
    assert np.allclose(a_imp.lycd_land_value, 100.0 * 0.20 * 1000.0)
    assert (a_imp.gma_level == "L3").all()
    # vacant in zone A: 100 $/sqft x 1.00 x 500 sqft, uncapped even though OPA says $5k
    vac_a = out[(out.gma3 == "A") & (out.category_code == "6")]
    assert np.allclose(vac_a.lycd_land_value, 100.0 * 500.0)
    assert res.diagnostics["land_pct_vacant"] == 1.0


def test_lycd_area_chain_and_cap():
    gdf, gma, pin_areas = _toy_city()
    res = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=50, city_area_sqft=1e9)
    out = res.gdf.set_index("parcel_number")
    # OPA area missing -> PIN polygon area (800 sqft) at zone A's rate
    no_opa = out[(out.total_area == 0) & (out.category_code == "1")]
    assert (no_opa.area_source == "pin_dor").all()
    assert np.allclose(no_opa.lycd_land_value, 100.0 * 0.20 * 800.0)
    # cheap house in zone B: 200 x 0.2 x 1000 = 40,000 > market 20,000 -> capped
    cheap = out[out.market_value == 20_000.0]
    assert np.allclose(cheap.lycd_land_value, 20_000.0)
    assert res.diagnostics["n_capped"] == 1
    assert res.diagnostics["land_base_pre_cap"] > res.diagnostics["land_base_post_cap"]


def test_lycd_hierarchy_fallback_and_knn():
    gdf, gma, pin_areas = _toy_city(n_per_zone=30)
    # 30 improved per L3 < min_improved=50 -> both zones fall back to the pooled L2 median
    res = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=50, city_area_sqft=1e9)
    out = res.gdf.set_index("parcel_number")
    assigned = out[out.gma3.notna() & (out.category_code == "1") & (out.total_area > 0)]
    assert set(assigned.gma_level) == {"L2"}
    assert assigned.lycd_land_value.nunique() <= 2   # pooled rate x area (cap may bind on one)
    # unassigned parcel gets the median dollar land value of its neighbours
    knn = out[out.gma3.isna()]
    assert (knn.gma_level == "knn").all()
    assert knn.lycd_land_value.notna().all()
    assert res.diagnostics["n_land_knn"] == 1


def test_lycd_area_guard_raises():
    gdf, gma, pin_areas = _toy_city()
    with pytest.raises(ValueError, match="inflated"):
        compute_lycd_land_values(gdf, gma, pin_areas, city_area_sqft=1.0)


def test_lycd_land_pct_improved_as_series():
    """A per-parcel share, as model_lycd_refined_prototype.ipynb passes an FHFA tract share."""
    gdf, gma, pin_areas = _toy_city()
    # Zone A's improved parcels get 0.30, zone B's get 0.10; every vacant row gets a
    # deliberately wrong 0.99, to confirm land_pct_vacant overrides it regardless.
    share = pd.Series(
        np.where(gdf["category_code"] == "6", 0.99,
                 np.where(gdf["zone"] == "A", 0.30, 0.10)),
        index=gdf.index,
    )
    res = compute_lycd_land_values(gdf, gma, pin_areas, land_pct_improved=share,
                                   min_improved=50, city_area_sqft=1e9)
    out = res.gdf.set_index("parcel_number")

    a_imp = out[(out.gma3 == "A") & (out.category_code == "1") & (out.total_area > 0)]
    assert np.allclose(a_imp.lycd_land_value, 100.0 * 0.30 * 1000.0)

    b_imp = out[(out.gma3 == "B") & (out.category_code == "1") & (out.total_area > 0)]
    assert np.allclose(b_imp.lycd_land_value, 200.0 * 0.10 * 1000.0)

    # Vacant rows ignore the 0.99 in the Series -- land_pct_vacant (default 1.00) still wins.
    vac_a = out[(out.gma3 == "A") & (out.category_code == "6")]
    assert np.allclose(vac_a.lycd_land_value, 100.0 * 500.0)
    assert res.diagnostics["land_pct_improved"].startswith("per-parcel Series")


def _toy_city_two_categories(n_per_group: int = 30, area: float = 500.0):
    """One GMA zone with two co-located property types at different rates: category '1'
    ("Residential") at $100/sqft, category '4' ("NonResidential") at $300/sqft. Every parcel
    in a group shares the identical psf, so any member can serve as the read-off probe."""
    rows = []
    k = 0
    for code, psf in (("1", 100.0), ("4", 300.0)):
        for i in range(n_per_group):
            rows.append(dict(parcel_number=f"{k:09d}", pin=str(3000 + k), category_code=code,
                             total_area=area, market_value=psf * area, x=float(i), y=0.0))
            k += 1
    df = pd.DataFrame(rows)
    gdf = gpd.GeoDataFrame(df.drop(columns=["x", "y"]),
                           geometry=[Point(x, y) for x, y in zip(df.x, df.y)], crs="EPSG:3857")
    gma = pd.DataFrame({"key": df.parcel_number, "gma3": "A", "gma2": "L2", "gma1": "L1"})
    pin_areas = pd.DataFrame({"pin": df.pin, "pin_area_sqft": df.total_area})
    return gdf, gma, pin_areas


def test_lycd_zone_group_col_stratifies_zone_median():
    """model_lycd_refined_prototype.ipynb's Q2 refinement: price a rowhouse against other
    residential comps, not whichever commercial parcel happens to share its GMA zone."""
    gdf, gma, pin_areas = _toy_city_two_categories()
    gdf["_zone_group"] = np.where(gdf["category_code"] == "1", "Residential", "NonResidential")

    pooled = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=10, city_area_sqft=1e9)
    stratified = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=10, city_area_sqft=1e9,
                                          zone_group_col="_zone_group")

    pooled_out = pooled.gdf.set_index("parcel_number")
    strat_out = stratified.gdf.set_index("parcel_number")
    resid_pid = gdf.loc[gdf.category_code == "1", "parcel_number"].iloc[0]
    nonresid_pid = gdf.loc[gdf.category_code == "4", "parcel_number"].iloc[0]

    # Pooled: one blended median (100 and 300 in equal counts -> 200) applied to everyone,
    # so a residential and a non-residential parcel with the same area get the same land value.
    assert np.isclose(pooled_out.loc[resid_pid, "lycd_zone_psf"], 200.0)
    assert np.isclose(pooled_out.loc[resid_pid, "lycd_land_value"],
                      pooled_out.loc[nonresid_pid, "lycd_land_value"])
    assert np.isclose(pooled_out.loc[resid_pid, "lycd_land_value"], 200.0 * 0.20 * 500.0)

    # Stratified: each group sees its own pure rate.
    assert np.isclose(strat_out.loc[resid_pid, "lycd_zone_psf"], 100.0)
    assert np.isclose(strat_out.loc[nonresid_pid, "lycd_zone_psf"], 300.0)
    assert np.isclose(strat_out.loc[resid_pid, "lycd_land_value"], 100.0 * 0.20 * 500.0)
    assert np.isclose(strat_out.loc[nonresid_pid, "lycd_land_value"], 300.0 * 0.20 * 500.0)


def test_lycd_zone_group_col_missing_raises():
    gdf, gma, pin_areas = _toy_city()
    with pytest.raises(ValueError, match="not a column"):
        compute_lycd_land_values(gdf, gma, pin_areas, zone_group_col="nonexistent")


def _exemption_cases() -> pd.DataFrame:
    cap = 100_000.0
    return pd.DataFrame({
        # 1 plain taxable, 2 homestead (single exemption), 3 abated (building fully exempt),
        # 4 homestead-wiped (mv < cap, fully exempt), 5 institutional (fully exempt),
        # 6 homestead + abatement, 7 homestead where exemption spills onto land
        "taxable_land":     [50_000, 60_000, 40_000,      0,       0, 60_000, 20_000],
        "taxable_building": [150_000, 140_000,     0,      0,       0,      0,      0],
        "exempt_land":      [0,       0,      0, 20_000, 500_000,      0, 30_000],
        "exempt_building":  [0, 100_000, 300_000, 60_000, 900_000, 400_000, 70_000],
        "homestead_exemption": [0, cap, 0, 80_000, 0, cap, cap],
    }).assign(market_value=lambda d: d.taxable_land + d.taxable_building + d.exempt_land + d.exempt_building)


def test_carry_forward_reconstructs_opa_base_from_opa_land():
    df = _exemption_cases()
    df["same_land"] = df.taxable_land + df.exempt_land
    res = carry_forward_exemptions(df, new_land_col="same_land", homestead_cap=100_000)
    assert res.diagnostics["reconstruction_match_rate"] == 1.0
    old = (df.taxable_land + df.taxable_building).clip(lower=0)
    assert np.allclose(res.reform_taxable_total, old)


def test_carry_forward_with_doubled_land():
    df = _exemption_cases()
    df["new_land"] = 2 * (df.taxable_land + df.exempt_land)
    res = carry_forward_exemptions(df, new_land_col="new_land", homestead_cap=100_000)
    tot = res.reform_taxable_total.values
    # 1 plain: land doubles, building unchanged
    assert tot[0] == pytest.approx(100_000 + 150_000)
    # 2 homestead: 120k land + 240k building - 100k cap
    assert tot[1] == pytest.approx(120_000 + 240_000 - 100_000)
    # 3 abated: building stays fully exempt, land doubles
    assert tot[2] == pytest.approx(80_000)
    # 4 homestead-wiped: gross 80k -> land 40k + bldg 60k = 100k, minus cap -> 0; still exempt
    assert tot[3] == pytest.approx(0.0)
    assert bool(res.homestead_active.iloc[3]) and not bool(res.institutional_exempt.iloc[3])
    # 5 institutional: stays fully exempt regardless of land
    assert tot[4] == pytest.approx(0.0) and bool(res.institutional_exempt.iloc[4])
    # 6 homestead + abatement: exempt_building 400k = 300k abatement + 100k homestead, so
    #   120k land + 400k bldg - 300k abatement dollars - 100k cap = 120k (building fully shielded)
    assert tot[5] == pytest.approx(120_000 + 400_000 - 300_000 - 100_000)
    assert res.reform_taxable_building.iloc[5] == pytest.approx(0.0)
    # 7 homestead spilling onto land: gross land 50k -> 100k; bldg 70k; minus cap 100k
    assert tot[6] == pytest.approx(100_000 + 70_000 - 100_000)
    assert res.reform_taxable_building.iloc[6] == pytest.approx(0.0)   # building-first


def test_carry_forward_homestead_wiped_reenters_when_land_lifts_it():
    df = _exemption_cases().iloc[[3]].copy()
    df["new_land"] = 90_000.0          # 90k land + 60k building = 150k > cap
    res = carry_forward_exemptions(df, new_land_col="new_land", homestead_cap=100_000)
    assert res.reform_taxable_total.iloc[0] == pytest.approx(50_000.0)
    assert res.diagnostics["n_homestead_wiped_reentering"] == 1


def test_carry_forward_requires_homestead_column():
    df = _exemption_cases().drop(columns=["homestead_exemption"])
    df["new_land"] = 1.0
    with pytest.raises(ValueError, match="homestead_exemption"):
        carry_forward_exemptions(df, new_land_col="new_land", homestead_cap=100_000)


def test_carry_forward_reconstruction_floor_raises():
    df = _exemption_cases()
    df["new_land"] = 1.0
    # a wrong cap breaks the homestead reconstruction on the homestead rows
    with pytest.raises(ValueError, match="reproduces OPA's taxable total"):
        carry_forward_exemptions(df, new_land_col="new_land", homestead_cap=10_000,
                                 reconstruction_floor=0.99)
