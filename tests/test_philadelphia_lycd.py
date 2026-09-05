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
    compute_residual_building_value,
    reallocate_land_within_total,
)


def _toy_city(n_per_zone: int = 60) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    """Two L3 zones inside one L2/L1; zone A improved parcels at $100/sqft, zone B at $200/sqft."""
    rows = []
    k = 0
    for zone, psf, x0 in (("A", 100.0, 0.0), ("B", 200.0, 10_000.0)):
        for i in range(n_per_zone):
            rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                             total_area=1000.0, market_value=psf * 1000.0, taxable_building=0.0,
                             x=x0 + i, y=0.0, zone=zone))
            k += 1
        # one vacant lot per zone, OPA-valued far below the zone rate
        rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="6",
                         total_area=500.0, market_value=5_000.0, taxable_building=0.0,
                         x=x0 + 1, y=1.0, zone=zone))
        k += 1
    # an improved parcel in zone A with no OPA area but a PIN polygon
    rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                     total_area=0.0, market_value=100_000.0, taxable_building=0.0,
                     x=2.0, y=1.0, zone="A"))
    k += 1
    # an improved parcel with no GMA assignment at all, sitting in zone B's cluster
    rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                     total_area=1000.0, market_value=200_000.0, taxable_building=0.0,
                     x=10_003.0, y=1.0, zone=None))
    k += 1
    # a cheap house in the expensive zone: the market-value cap must bind
    rows.append(dict(parcel_number=f"{k:09d}", pin=str(1000 + k), category_code="1",
                     total_area=1000.0, market_value=20_000.0, taxable_building=0.0,
                     x=10_004.0, y=1.0, zone="B"))
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
    # unassigned parcel gets the median RATE of its neighbours, applied to its own area
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
                             total_area=area, market_value=psf * area, taxable_building=0.0,
                             x=float(i), y=0.0))
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


def test_lycd_knn_imputes_rate_not_dollar_value():
    """Audit 2026-08-08 finding 5: an unmatched parcel must get a RATE from its neighbours
    and apply it to its own area, not inherit a neighbour's dollar land value outright."""
    rows = []
    k = 0
    for i in range(60):
        rows.append(dict(parcel_number=f"{k:09d}", pin=str(4000 + k), category_code="1",
                         total_area=10_000.0, market_value=100.0 * 10_000.0, taxable_building=0.0,
                         x=float(i), y=0.0, zone="A"))
        k += 1
    # An unmatched SMALL parcel sitting in the middle of a cluster of LARGE (10,000 sqft) ones.
    small_pid = f"{k:09d}"
    rows.append(dict(parcel_number=small_pid, pin=str(4000 + k), category_code="1",
                     total_area=100.0, market_value=100.0 * 100.0, taxable_building=0.0,
                     x=30.0, y=0.1, zone=None))
    df = pd.DataFrame(rows)
    gdf = gpd.GeoDataFrame(df.drop(columns=["x", "y"]),
                          geometry=[Point(x, y) for x, y in zip(df.x, df.y)], crs="EPSG:3857")
    gma = pd.DataFrame({"key": df.parcel_number, "gma3": df.zone, "gma2": "L2", "gma1": "L1"})
    gma = gma[gma.gma3.notna()]
    pin_areas = pd.DataFrame({"pin": df.pin, "pin_area_sqft": df.total_area})

    res = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=10, city_area_sqft=1e9)
    out = res.gdf.set_index("parcel_number")
    small = out.loc[small_pid]
    assert small.gma_level == "knn"
    # Correct: the neighbourhood's $100/sqft rate x this parcel's OWN 100 sqft x 0.20 share.
    assert np.isclose(small.lycd_land_value, 100.0 * 0.20 * 100.0)
    # The old (wrong) behaviour inherited a neighbour's own land value outright (100 x 0.20 x
    # 10,000 = 200,000) -- two orders of magnitude off this parcel's actual size.
    assert not np.isclose(small.lycd_land_value, 100.0 * 0.20 * 10_000.0)


def test_lycd_cap_include_building_off_by_default():
    """Default behavior (`cap_include_building=False`) is the plain land-only cap, even when
    the parcel carries a building value -- see the parameter's docstring for why turning it
    on is a much bigger change than it looks (it collapses land toward OPA's own split for
    any parcel whose building already accounts for most of market_value)."""
    gdf, gma, pin_areas = _toy_city()
    cheap_idx = gdf.index[gdf["market_value"] == 20_000.0][0]
    gdf.loc[cheap_idx, "taxable_building"] = 5_000.0
    cheap_pid = gdf.loc[cheap_idx, "parcel_number"]

    res = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=50, city_area_sqft=1e9)
    out = res.gdf.set_index("parcel_number")
    assert np.isclose(out.loc[cheap_pid, "lycd_land_value"], 20_000.0)   # unchanged by building
    assert res.diagnostics["cap_include_building"] is False


def test_lycd_cap_include_building_opt_in():
    """With cap_include_building=True, land is capped at market_value - taxable_building,
    so land + building never exceeds market_value."""
    gdf, gma, pin_areas = _toy_city()
    cheap_idx = gdf.index[gdf["market_value"] == 20_000.0][0]
    gdf.loc[cheap_idx, "taxable_building"] = 5_000.0
    cheap_pid = gdf.loc[cheap_idx, "parcel_number"]

    res = compute_lycd_land_values(gdf, gma, pin_areas, min_improved=50, city_area_sqft=1e9,
                                   cap_include_building=True)
    out = res.gdf.set_index("parcel_number")
    cheap = out.loc[cheap_pid]
    # land = market_value - building = 20,000 - 5,000 = 15,000, so land + building lands
    # exactly at market_value, never above it.
    assert np.isclose(cheap.lycd_land_value, 15_000.0)
    assert np.isclose(cheap.lycd_land_value + 5_000.0, 20_000.0)


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


def test_residual_building_ordinary_parcel():
    df = pd.DataFrame({"market_value": [200_000.0, 100_000.0], "lycd_land": [90_000.0, 150_000.0]})
    out = compute_residual_building_value(df, land_col="lycd_land")
    # 200k - 90k = 110k; 100k - 150k would be negative -> floored at 0
    assert np.allclose(out.values, [110_000.0, 0.0])


def test_carry_forward_override_prevents_double_counting():
    """The actual point of this mechanism: land + building after exemptions never exceeds
    market_value on ordinary (non-abated) rows, once building is the exemption-aware residual
    -- unlike holding building at OPA's own recorded value, which overshoots on several."""
    df = _exemption_cases()
    # Row 2 (abated) is excluded from this claim entirely -- see
    # test_carry_forward_override_cannot_preserve_abated_building for why routing it through
    # this same call, even with an override, is wrong regardless of the override's value.
    non_abated = df.drop(index=2)
    # Big enough to force overshoot on most rows if unaddressed, but clipped to each row's own
    # market_value -- mirroring the land-only cap compute_lycd_land_values always applies
    # upstream by default. Without that clip, land itself could exceed market_value (row 3's
    # market_value is only $80k), which this mechanism does not and cannot fix -- it only
    # corrects BUILDING; land staying within market_value is a precondition, not a guarantee
    # this function provides.
    non_abated = non_abated.assign(new_land=np.minimum(200_000.0, non_abated.market_value.values))

    # Baseline: building held at OPA's own value (no override) -- reproduces the overshoot.
    baseline = carry_forward_exemptions(non_abated, new_land_col="new_land", homestead_cap=100_000)
    over_baseline = (baseline.reform_taxable_total - non_abated.market_value) > 1
    assert over_baseline.any(), "fixture should reproduce the overshoot without the override"

    override = compute_residual_building_value(non_abated, land_col="new_land")
    fixed = carry_forward_exemptions(non_abated, new_land_col="new_land", homestead_cap=100_000,
                                     gross_building_override=override)
    over_fixed = (fixed.reform_taxable_total - non_abated.market_value) > 1
    assert not over_fixed.any(), "no row should exceed market_value once building is the residual"

    fixed = fixed.reform_taxable_total.reset_index(drop=True)
    # Row 0 (plain): residual building = market - land = 200k - 200k = 0; total = market exactly.
    assert fixed.iloc[0] == pytest.approx(200_000.0)
    # Row 1 (homestead): total = market_value - homestead_cap exactly (relief nets once, not
    # zero or twice, regardless of which building split it's applied to).
    assert fixed.iloc[1] == pytest.approx(300_000.0 - 100_000.0)
    # Row 3 (institutional, was index 4 before dropping row 2): stays fully exempt no matter what.
    assert fixed.iloc[3] == pytest.approx(0.0)


def test_carry_forward_override_cannot_preserve_abated_building():
    """The mistake this guards against: an abated row's building CANNOT be preserved by
    supplying its own observed value (exempt_building) as gross_building_override. The
    function's other_exempt is derived from that SAME row's historical exempt total -- for an
    abated row that IS exempt_building -- so it cancels the override back to exactly zero,
    silently zeroing out the building the four LYCD notebooks currently, correctly, restore.
    Abated rows must be excluded from this call, not routed through it with an override."""
    # index reset to 0 deliberately -- .iloc[[2]] keeps the original label 2, and an override
    # Series that isn't aligned to it would silently reindex to all-NaN/0, masking the actual
    # mechanism this test exists to demonstrate.
    df = _exemption_cases().iloc[[2]].reset_index(drop=True).copy()   # abated: land 40k, exempt_building 300k
    df["new_land"] = 500_000.0   # far above OPA's own 40k -- an LYCD-sized correction

    # An override equal to the row's OWN exempt_building looks like "preserve it" but is not.
    misguided_override = pd.Series([300_000.0], index=df.index)
    result = carry_forward_exemptions(df, new_land_col="new_land", homestead_cap=100_000,
                                      gross_building_override=misguided_override)
    assert result.reform_taxable_building.iloc[0] == pytest.approx(0.0), (
        "this is the trap, not the expectation: supplying exempt_building as the override "
        "still zeroes the building, because other_exempt is derived from that same value"
    )
    assert result.reform_taxable_total.iloc[0] == pytest.approx(500_000.0)   # land only


def test_carry_forward_override_does_not_affect_reconstruction_guard():
    """The guard validates the exemption RULE against OPA's own real numbers and must not be
    fooled by a garbage override -- it always uses OPA's own gross building, never the
    override, which only applies to the real (non-guard) computation."""
    df = _exemption_cases()
    df["same_land"] = df.taxable_land + df.exempt_land
    garbage_override = pd.Series([0.0] * len(df))   # would break every reconstruction if used
    res = carry_forward_exemptions(df, new_land_col="same_land", homestead_cap=100_000,
                                   gross_building_override=garbage_override)
    assert res.diagnostics["reconstruction_match_rate"] == 1.0
    assert res.diagnostics["used_gross_building_override"] is True


# --- reallocate_land_within_total: the assessment-standards reform ------------------------
# Total assessment and rate both unchanged; only the land/building SPLIT moves. The claim
# under test throughout: a bill can only move if its exemption depends on that split.

def _realloc(df, new_land, cap=100_000, **kw):
    return reallocate_land_within_total(
        df.assign(new_land=new_land), new_land_col="new_land", homestead_cap=cap, **kw)


def test_reallocate_reconstructs_opa_base_from_opa_land():
    df = _exemption_cases()
    res = _realloc(df, (df.taxable_land + df.exempt_land).values)
    assert res.diagnostics["reconstruction_match_rate"] == 1.0
    old = (df.taxable_land + df.taxable_building).clip(lower=0)
    assert np.allclose(res.alloc_taxable_total, old)
    assert res.diagnostics["n_taxable_changed"] == 0


def test_reallocate_only_split_dependent_exemptions_move():
    """The headline claim of the reform: with the total and the rate held fixed, the only
    parcels whose bill moves are those whose exemption is a share of the BUILDING line --
    the abated ones. Plain, homestead-only, homestead-wiped and institutional rows are all
    bit-for-bit unchanged no matter how far the land component moves."""
    df = _exemption_cases()
    res = _realloc(df, 2 * (df.taxable_land + df.exempt_land).values)
    old = (df.taxable_land + df.taxable_building).clip(lower=0).values
    new = res.alloc_taxable_total.values

    moved = np.abs(new - old) > 1
    assert list(np.flatnonzero(moved)) == [2, 5], "only the two abated rows may move"
    assert res.diagnostics["n_taxable_changed"] == 2

    # Sec. 3(c): land and improvement stay complementary parts of one unchanged total.
    gross_total = (df.taxable_land + df.exempt_land + df.taxable_building + df.exempt_building)
    assert np.allclose(res.alloc_land + res.alloc_building, gross_total)

    # 0 plain: no exemption at all, so the split is invisible to the bill.
    assert new[0] == pytest.approx(200_000.0)
    # 1 homestead: min(cap, total) with the total unchanged -> unchanged, only the line it is
    #   drawn against moves.
    assert new[1] == pytest.approx(200_000.0)
    # 3 homestead-wiped: total 80k still under the 100k cap, so it stays exempt -- unlike the
    #   revaluation reading, where a bigger land value can lift it back into the base.
    assert new[3] == pytest.approx(0.0)
    # 4 institutional: fully exempt regardless.
    assert new[4] == pytest.approx(0.0)
    # 6 homestead spilling onto land: total unchanged, so unchanged.
    assert new[6] == pytest.approx(20_000.0)


def test_reallocate_fully_abated_taxable_is_land_only():
    """A 100%-abated parcel exempts whatever the improvement is now assessed at, so its
    taxable value is exactly the reallocated land component -- raise the land share and it
    pays more. This is the ordinance's fiscal question, in one row."""
    df = _exemption_cases()
    res = _realloc(df, 2 * (df.taxable_land + df.exempt_land).values)
    # row 2: gross total 340k, land doubled 40k -> 80k, so building 260k, all abated.
    assert res.alloc_land.iloc[2] == pytest.approx(80_000.0)
    assert res.alloc_building.iloc[2] == pytest.approx(260_000.0)
    assert res.alloc_taxable_building.iloc[2] == pytest.approx(0.0)
    assert res.alloc_taxable_total.iloc[2] == pytest.approx(res.alloc_land.iloc[2])
    # ...and it moves in the other direction too, which is why a fiscal note needs both.
    lower = _realloc(df, 0.5 * (df.taxable_land + df.exempt_land).values)
    assert lower.alloc_taxable_total.iloc[2] == pytest.approx(20_000.0)


def test_reallocate_partial_abatement_carries_as_a_share():
    """Row 5 is 75% abated (300k of a 400k building). The share, not the dollar amount, is
    what carries -- so the exemption tracks the new building line."""
    df = _exemption_cases()
    res = _realloc(df, 2 * (df.taxable_land + df.exempt_land).values)
    # building 340k after reallocation; 75% of it exempt = 255k, leaving 85k taxable, then the
    # 100k homestead takes all 85k and spills 15k onto the 120k land line -> 105k.
    assert res.alloc_building.iloc[5] == pytest.approx(340_000.0)
    assert res.alloc_taxable_total.iloc[5] == pytest.approx(105_000.0)
    assert res.exemption_kind.iloc[5] == "building_share"

    # Same 75% abatement without a homestead on top, so the abated dollars are directly
    # visible rather than buried under the homestead's bite.
    clean = pd.DataFrame({
        "taxable_land": [60_000.0], "taxable_building": [100_000.0],
        "exempt_land": [0.0], "exempt_building": [300_000.0], "homestead_exemption": [0.0],
    })   # gross: land 60k, building 400k, total 460k, 75% abated
    out = _realloc(clean, [120_000.0])
    assert out.alloc_building.iloc[0] == pytest.approx(340_000.0)
    exempted = out.alloc_building.iloc[0] - out.alloc_taxable_building.iloc[0]
    assert exempted == pytest.approx(0.75 * 340_000.0)
    assert out.alloc_taxable_total.iloc[0] == pytest.approx(120_000.0 + 85_000.0)


def test_reallocate_partial_institutional_carries_in_dollars():
    """Row 4's exemption (1.4M) exceeds its building line (900k), so it is relief against
    total value, not against the improvement -- it carries in dollars and, the total being
    unchanged, the parcel stays fully exempt."""
    df = _exemption_cases()
    res = _realloc(df, 2 * (df.taxable_land + df.exempt_land).values)
    assert res.exemption_kind.iloc[4] == "full"       # fully exempt today, so 'full' wins
    assert bool(res.institutional_exempt.iloc[4])
    assert res.alloc_taxable_total.iloc[4] == pytest.approx(0.0)

    # A partially-relieved (not fully exempt) version of the same shape: exemption exceeds the
    # building line, so it is total_share and the bill does not move.
    partial = pd.DataFrame({
        "taxable_land": [100_000.0], "taxable_building": [50_000.0],
        "exempt_land": [200_000.0], "exempt_building": [150_000.0],
        "homestead_exemption": [0.0],
    })
    out = _realloc(partial, [300_000.0])
    assert out.exemption_kind.iloc[0] == "total_share"
    assert out.alloc_taxable_total.iloc[0] == pytest.approx(150_000.0)   # unchanged


def test_reallocate_prorata_relief_is_not_an_abatement():
    """Relief split across BOTH lines in the parcel's own land/building ratio is a percentage
    of total value, not an exemption of the improvement -- even though the dollars fit inside
    the building line. Real TY2026 data has 345 of these; classifying them as building_share
    would make their relief track a building value that the reform deliberately moves."""
    prorata = pd.DataFrame({           # 50% relief, applied 20/80 across land and building
        "taxable_land": [35_180.0], "taxable_building": [140_720.0],
        "exempt_land": [35_180.0], "exempt_building": [140_720.0],
        "homestead_exemption": [0.0],
    })                                  # gross land 70,360 / building 281,440, total 351,800
    res = _realloc(prorata, [140_000.0])
    assert res.diagnostics["n_prorata_reclassified"] == 1
    assert res.exemption_kind.iloc[0] == "total_share"
    assert res.reform_change.iloc[0] == pytest.approx(0.0), "relief on total value cannot move"

    # The homestead spilling onto land is NOT this pattern -- it must stay building_share.
    abated_with_spill = pd.DataFrame({
        "taxable_land": [20_000.0], "taxable_building": [0.0],
        "exempt_land": [58_900.0], "exempt_building": [235_600.0],
        "homestead_exemption": [100_000.0],
    })   # abatement 194,500 of a 235,600 building; the 100k homestead takes the rest and
         # spills 58,900 onto land -- exactly the exempt_land OPA records.
    out = _realloc(abated_with_spill, [120_000.0])
    assert out.diagnostics["n_prorata_reclassified"] == 0
    assert out.exemption_kind.iloc[0] == "building_share"


def test_reallocate_reform_change_excludes_reconstruction_residual():
    """A parcel whose recorded homestead disagrees with the relief actually applied cannot be
    reproduced by the rule -- and its bill does not depend on the land/building split, so the
    reform must report zero for it. Differencing against OPA's recorded total instead would
    report the rule's own residual as a tax change (1,818 such parcels on TY2026)."""
    # homestead_exemption records the full 100k cap, but only 25,240 was actually applied.
    odd = pd.DataFrame({
        "taxable_land": [75_720.0], "taxable_building": [277_640.0],
        "exempt_land": [0.0], "exempt_building": [25_240.0],
        "homestead_exemption": [100_000.0],
    })
    # floor lifted because this one-row frame IS the mismatch case under test; on the real
    # roll these are 0.5% of parcels and the 95% floor holds comfortably.
    res = _realloc(odd, [200_000.0], reconstruction_floor=0.0)
    assert res.diagnostics["n_reconstruction_mismatch"] == 1
    # Against OPA's recorded total this looks like a change; against the rule itself it is zero.
    recorded_delta = res.alloc_taxable_total.iloc[0] - (odd.taxable_land + odd.taxable_building).iloc[0]
    assert abs(recorded_delta) > 1
    assert res.reform_change.iloc[0] == pytest.approx(0.0)
    assert res.diagnostics["n_taxable_changed"] == 0
    assert res.diagnostics["n_taxable_changed_vs_recorded"] == 1


def test_reallocate_vacant_parcel_never_moves():
    """Vacant land has no building line to reallocate away from, so the reform cannot touch
    it -- which is why LYCD's badly over-valued vacant leg is irrelevant to this scenario."""
    vacant = pd.DataFrame({
        "taxable_land": [30_000.0], "taxable_building": [0.0],
        "exempt_land": [0.0], "exempt_building": [0.0], "homestead_exemption": [0.0],
    })
    res = _realloc(vacant, [500_000.0])       # LYCD-sized over-valuation
    assert res.alloc_land.iloc[0] == pytest.approx(30_000.0)
    assert res.alloc_building.iloc[0] == pytest.approx(0.0)
    assert res.alloc_taxable_total.iloc[0] == pytest.approx(30_000.0)
    assert res.diagnostics["n_taxable_changed"] == 0


def test_reallocate_caps_land_at_the_parcel_total():
    """A land component above the parcel's own total assessment is capped there (the
    structure is then implicitly worth zero); the total, and an unexempted bill, still do
    not move."""
    df = _exemption_cases()
    res = _realloc(df, np.full(len(df), 10_000_000.0))
    gross_total = (df.taxable_land + df.exempt_land + df.taxable_building + df.exempt_building)
    assert np.allclose(res.alloc_land, gross_total)
    assert np.allclose(res.alloc_building, 0.0)
    assert res.diagnostics["n_land_capped"] == len(df)
    assert res.alloc_taxable_total.iloc[0] == pytest.approx(200_000.0)   # plain row unmoved


def test_reallocate_exemption_kinds():
    df = _exemption_cases()
    res = _realloc(df, (df.taxable_land + df.exempt_land).values)
    assert list(res.exemption_kind) == [
        "none", "homestead", "building_share", "homestead", "full", "building_share", "homestead",
    ]
    assert res.diagnostics["exemption_kind_counts"]["building_share"] == 2


def test_reallocate_reconstruction_floor_raises():
    df = _exemption_cases()
    with pytest.raises(ValueError, match="reproduces OPA's taxable total"):
        _realloc(df, (df.taxable_land + df.exempt_land).values,
                 cap=10_000, reconstruction_floor=0.99)


def test_reallocate_requires_homestead_column():
    df = _exemption_cases().drop(columns=["homestead_exemption"])
    with pytest.raises(ValueError, match="homestead_exemption"):
        _realloc(df, 1.0)
