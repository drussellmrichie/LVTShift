"""Tests for lvt.ubi_utils — the LVT + UBI (full land-rent capture) model.

Every test runs on synthetic data with no network and no parcel cache, because
the worked notebook cannot be executed without both. These asserts are the proof
that the arithmetic is right; the notebook's magnitude gates are the separate
proof that it is wired to the right data.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lvt.ubi_utils import (  # noqa: E402
    allocate_dividend_to_tracts,
    compute_breakeven_land_value,
    compute_ubi_dividend,
    land_rent_from_value,
    model_full_land_rent_tax,
    save_ubi_parcel_export,
    save_ubi_tract_export,
    summarize_ubi_incidence,
    sweep_land_rent_parameters,
)

I = 0.05          # net capitalization rate
T = 0.013998      # Philadelphia combined city + school rate, TY2026
GROSS = I + T     # 0.063998


def _parcels():
    # Rows: ordinary improved, land-rich improved, vacant, abated (no building),
    # fully exempt (all value in the exempt columns), NaN land, negative land.
    return pd.DataFrame({
        'parcel_number':   ['001', '002', '003', '004', '005', '006', '007'],
        'taxable_land':    [50_000, 400_000, 80_000, 60_000,      0.0, np.nan, -1_000],
        'taxable_building':[150_000, 600_000,     0.0,     0.0,   0.0,  20_000,  5_000],
        'exempt_land':     [0.0, 0.0, 0.0, 0.0, 900_000, 0.0, 0.0],
        'exempt_building': [0.0, 0.0, 0.0, 300_000, 4_000_000, 0.0, 0.0],
        'full_exmp':       [0, 0, 0, 0, 1, 0, 0],
        'PROPERTY_CATEGORY': ['Single Family Residential', 'Commercial', 'Vacant Land',
                              'Abated / Construction Exemption', 'Commercial — Exempt',
                              'Single Family Residential', 'Industrial'],
    })


def _taxable_parcels():
    """Only the rows with a clean, non-exempt, non-degenerate land value."""
    return _parcels().iloc[[0, 1, 2, 3]].reset_index(drop=True)


def _dual_source_parcels():
    """Two land surfaces over one assessment: the assessor's, and an independent one.

    ``lycd_land`` stands in for Philadelphia's LYCD surface (``zone_psf x lot area``),
    which replaces land without re-deriving buildings. ``taxable_total`` is what the
    parcel is actually billed on and never moves with the alternative surface.
    """
    df = _taxable_parcels()
    df['lycd_land'] = df['taxable_land'] * [1.6, 1.2, 3.0, 0.8]
    df['taxable_total'] = df['taxable_land'] + df['taxable_building']
    return df


def _model(df=None, **kw):
    kw.setdefault('discount_rate', I)
    kw.setdefault('combined_rate', T)
    return model_full_land_rent_tax(
        _taxable_parcels() if df is None else df,
        'taxable_land', 'taxable_building', **kw,
    )


# 1. The capitalization gross-up is (i + t), not i.
def test_gross_up_is_exact():
    assert land_rent_from_value(1000.0, I, T) == pytest.approx(63.998, abs=1e-9)
    # Dropping the tax term understates rent by t/i — 28% at these rates.
    assert land_rent_from_value(1000.0, I, 0.0) == pytest.approx(50.0, abs=1e-9)
    with pytest.raises(ValueError):
        land_rent_from_value(1000.0, 0.0, T)
    with pytest.raises(ValueError):
        land_rent_from_value(1000.0, I, -0.01)


# 2. At full capture on the taxable basis, the change collapses to i * L.
def test_full_capture_change_is_i_times_land():
    _, out = _model()
    expected = I * out['taxable_land'].clip(lower=0)
    assert np.allclose(out['tax_change'], expected, rtol=1e-12)


# 3. The owner keeps a normal return on the structure and nothing on the land.
def test_owner_residual_identity():
    _, out = _model()
    assert np.allclose(out['owner_residual'], I * out['taxable_building'], rtol=1e-12)
    # Below full capture the owner also keeps (1 - phi)(i + t) L.
    _, half = _model(capture_rate=0.5)
    expected = 0.5 * GROSS * half['taxable_land'] + I * half['taxable_building']
    assert np.allclose(half['owner_residual'], expected, rtol=1e-12)


# 4. The building tax is untouched: changing it cannot move any tax_change.
def test_building_tax_is_unchanged():
    _, base = _model()
    assert np.allclose(base['building_tax'], T * base['taxable_building'], rtol=1e-12)

    tripled = _taxable_parcels()
    tripled['taxable_building'] = tripled['taxable_building'] * 3
    _, other = _model(tripled)
    assert np.allclose(base['tax_change'], other['tax_change'], rtol=1e-12)
    assert np.allclose(other['building_tax'], 3 * base['building_tax'], rtol=1e-12)


# 5. Zero capture abolishes the land tax outright and empties the pot.
def test_zero_capture_abolishes_the_land_tax(capsys):
    summary, out = _model(capture_rate=0.0)
    assert np.allclose(out['tax_change'], -T * out['taxable_land'], rtol=1e-12)
    assert summary['ubi_pot'] < 0
    assert 'WARNING' in capsys.readouterr().out


# 6. The two revenue framings differ by exactly today's land-tax revenue.
def test_revenue_framings_differ_by_current_land_tax():
    summary, _ = _model()
    land_total = _taxable_parcels()['taxable_land'].sum()
    assert summary['full_redistribution_pot'] - summary['city_held_harmless_pot'] == \
        pytest.approx(T * land_total, rel=1e-12)
    assert summary['budget_hole'] == 0.0

    full, _ = _model(revenue_framing='full_redistribution')
    assert full['budget_hole'] == pytest.approx(T * land_total, rel=1e-12)
    assert full['ubi_pot'] == pytest.approx(full['total_new_land_tax'], rel=1e-12)


# 7. Wealth closure: the stock destroyed is the NPV of the flow, for every phi.
@pytest.mark.parametrize('phi', [0.25, 0.5, 0.75, 1.0])
def test_wealth_destroyed_equals_pot_over_discount_rate(phi):
    summary, _ = _model(capture_rate=phi)
    assert summary['land_wealth_destroyed'] == pytest.approx(summary['ubi_pot'] / I, rel=1e-12)
    land_total = _taxable_parcels()['taxable_land'].sum()
    assert summary['post_reform_land_value'] == pytest.approx(
        land_total * GROSS * (1 - phi) / I, rel=1e-12)


def test_land_value_capitalizes_to_zero_at_full_capture():
    summary, _ = _model(capture_rate=1.0)
    assert summary['post_reform_land_value'] == pytest.approx(0.0, abs=1e-6)
    assert summary['land_wealth_destroyed'] == pytest.approx(
        summary['pre_reform_land_value'], rel=1e-12)


# 8. A household sitting on exactly the break-even land value nets out to zero.
def test_breakeven_land_value_round_trip():
    ubi, hh = 1_350.0, 2.3
    star = compute_breakeven_land_value(ubi, hh, discount_rate=I, combined_rate=T)
    assert star == pytest.approx(ubi * hh / I, rel=1e-12)

    df = pd.DataFrame({'taxable_land': [star - 1_000, star, star + 1_000],
                       'taxable_building': [0.0, 0.0, 0.0]})
    _, out = _model(df)
    net = ubi * hh - out['tax_change']
    assert net.iloc[1] == pytest.approx(0.0, abs=1e-6)
    assert net.iloc[0] > 0 and net.iloc[2] < 0


# 9. Below phi = t/(i+t) nobody loses, so there is no threshold to compute.
def test_breakeven_raises_when_no_landowner_loses():
    floor = T / GROSS
    compute_breakeven_land_value(1000.0, 2.0, discount_rate=I, combined_rate=T,
                                 capture_rate=floor + 1e-6)
    with pytest.raises(ValueError, match='no break-even'):
        compute_breakeven_land_value(1000.0, 2.0, discount_rate=I, combined_rate=T,
                                     capture_rate=floor - 1e-6)


# 10. The dividend adds up, with or without a reduced child share.
def test_dividend_adds_up():
    d = compute_ubi_dividend(2_000_000.0, 1_000.0)
    assert d['ubi_per_capita'] == pytest.approx(2_000.0)
    assert d['ubi_per_share'] * d['total_shares'] == pytest.approx(d['pot_total'], rel=1e-12)

    half = compute_ubi_dividend(2_000_000.0, 1_000.0, child_population=200.0, child_share=0.5)
    assert half['total_shares'] == pytest.approx(900.0)
    assert half['ubi_per_share'] * half['total_shares'] == pytest.approx(2_000_000.0, rel=1e-12)
    assert half['ubi_per_share'] > half['ubi_per_capita']

    with pytest.raises(ValueError):
        compute_ubi_dividend(1.0, 0.0)
    with pytest.raises(ValueError):
        compute_ubi_dividend(1.0, 10.0, child_share=0.5)


# 11. Dividends pushed back onto tracts sum to the pot.
def test_tract_allocation_adds_up():
    tracts = pd.DataFrame({'tract_geoid': ['a', 'b', 'c'], 'total_pop': [100.0, 250.0, 650.0]})
    pot = 1_000_000.0
    d = compute_ubi_dividend(pot, tracts['total_pop'].sum())
    out = allocate_dividend_to_tracts(tracts, d['ubi_per_capita'], pot_total=pot)
    assert out['tract_dividend'].sum() == pytest.approx(pot, rel=1e-9)
    assert np.allclose(out['tract_dividend'], tracts['total_pop'] * d['ubi_per_capita'])


def test_tract_allocation_warns_on_denominator_drift(capsys):
    tracts = pd.DataFrame({'tract_geoid': ['a'], 'total_pop': [100.0]})
    allocate_dividend_to_tracts(tracts, 10.0, pot_total=2_000.0)
    assert 'WARNING' in capsys.readouterr().out


def _tract_net(land_by_tract, pop_by_tract, discount_rate=I, scale=1.0):
    """Net gain per tract under held-harmless full capture."""
    parcels = pd.DataFrame({
        'tract_geoid': list(land_by_tract),
        'taxable_land': [v * scale for v in land_by_tract.values()],
        'taxable_building': [0.0] * len(land_by_tract),
    })
    summary, out = model_full_land_rent_tax(
        parcels, 'taxable_land', 'taxable_building',
        discount_rate=discount_rate, combined_rate=T, capture_rate=1.0,
    )
    tracts = out.groupby('tract_geoid')[['tax_change', 'new_land_tax', 'current_tax']].sum()
    tracts = tracts.reset_index()
    tracts['total_pop'] = [pop_by_tract[g] for g in tracts['tract_geoid']]
    d = compute_ubi_dividend(summary['ubi_pot'], tracts['total_pop'].sum())
    tracts = allocate_dividend_to_tracts(tracts, d['ubi_per_capita'])
    tracts['net_gain'] = tracts['tract_dividend'] - tracts['tax_change']
    return tracts.set_index('tract_geoid')['net_gain']


LAND = {'a': 10_000_000.0, 'b': 2_000_000.0, 'c': 40_000_000.0, 'd': 500_000.0}
POP = {'a': 5_000.0, 'b': 6_000.0, 'c': 3_000.0, 'd': 4_000.0}


# 12. Who wins does not depend on the capitalization rate — only the dollars do.
def test_partition_is_invariant_to_discount_rate():
    sets = []
    for rate in (0.03, 0.05, 0.09):
        net = _tract_net(LAND, POP, discount_rate=rate)
        sets.append(frozenset(net[net > 0].index))
    assert sets[0] == sets[1] == sets[2]
    assert 0 < len(sets[0]) < len(LAND)          # a real split, not all-or-nothing
    # magnitudes do scale with the rate
    assert _tract_net(LAND, POP, 0.09).abs().sum() > _tract_net(LAND, POP, 0.03).abs().sum()


# 13. Nor on a uniform assessment bias — that only rescales every net position.
def test_partition_is_invariant_to_uniform_assessment_scale():
    base = _tract_net(LAND, POP)
    scaled = _tract_net(LAND, POP, scale=0.85)
    assert frozenset(base[base > 0].index) == frozenset(scaled[scaled > 0].index)
    assert np.allclose(scaled.values, 0.85 * base.values, rtol=1e-12)


# 14. Held harmless, the whole reform is exactly zero-sum across tracts.
def test_held_harmless_is_zero_sum():
    assert _tract_net(LAND, POP).sum() == pytest.approx(0.0, abs=1e-6)


# 15. Charging rent on exempt land is a policy choice that breaks the i*L identity.
def test_full_rent_basis_breaks_the_identity():
    df = _parcels().iloc[[4]].reset_index(drop=True)   # exempt: taxable 0, exempt_land 900k
    df['full_assessed_land'] = df['taxable_land'].fillna(0) + df['exempt_land']
    summary, out = _model(df, rent_basis_col='full_assessed_land')
    assert summary['rent_basis'] == 'full'
    assert out['new_land_tax'].iloc[0] == pytest.approx(GROSS * 900_000, rel=1e-12)
    assert out['current_land_tax'].iloc[0] == pytest.approx(0.0, abs=1e-9)
    assert out['tax_change'].iloc[0] != pytest.approx(I * 900_000, rel=1e-6)

    taxable_summary, _ = _model(df)
    assert taxable_summary['rent_basis'] == 'taxable'
    assert taxable_summary['total_new_land_tax'] == pytest.approx(0.0, abs=1e-9)


# 16. Exempt parcels are zeroed on both sides when a flag is supplied.
def test_exemption_flag_zeroes_both_sides():
    summary, out = _model(_parcels(), exemption_flag_col='full_exmp')
    assert summary['n_exempt'] == 1
    exempt_row = out.loc[out['full_exmp'] == 1].iloc[0]
    for col in ('land_rent', 'new_land_tax', 'building_tax', 'current_tax', 'new_tax', 'tax_change'):
        assert exempt_row[col] == pytest.approx(0.0, abs=1e-9)


# 17. Degenerate land values are cleaned, never propagated.
def test_nan_and_negative_land_are_cleaned():
    _, out = _model(_parcels())
    for col in ('land_rent', 'new_land_tax', 'current_tax', 'new_tax', 'tax_change'):
        assert out[col].notna().all(), col
    nan_row = out.loc[out['parcel_number'] == '006'].iloc[0]
    assert nan_row['land_rent'] == pytest.approx(0.0, abs=1e-9)
    neg_row = out.loc[out['parcel_number'] == '007'].iloc[0]
    assert neg_row['land_rent'] == pytest.approx(0.0, abs=1e-9)


# 18. A zero current bill yields NaN, never inf, in the percent column.
def test_tax_change_pct_is_nan_not_inf():
    df = pd.DataFrame({'taxable_land': [0.0, 100_000.0], 'taxable_building': [0.0, 50_000.0]})
    _, out = _model(df)
    assert np.isnan(out['tax_change_pct'].iloc[0])
    assert np.isfinite(out['tax_change_pct'].iloc[1])
    assert not np.isinf(out['tax_change_pct']).any()


# 19. The sweep is monotone in both parameters and keeps a stable schema.
def test_sweep_is_monotone():
    sweep = sweep_land_rent_parameters(
        _taxable_parcels(), 'taxable_land', 'taxable_building', population=1_000.0,
        discount_rates=(0.03, 0.04, 0.05, 0.06, 0.07),
        capture_rates=(0.25, 0.5, 0.75, 1.0),
        combined_rate=T,
    )
    assert list(sweep.columns) == ['swept', 'discount_rate', 'capture_rate', 'total_land_rent',
                                   'ubi_pot', 'ubi_per_capita',
                                   'implied_land_millage_equivalent', 'land_wealth_destroyed']
    by_i = sweep[sweep['swept'] == 'discount_rate']['ubi_per_capita']
    by_phi = sweep[sweep['swept'] == 'capture_rate']['ubi_per_capita']
    assert by_i.is_monotonic_increasing and by_i.iloc[0] < by_i.iloc[-1]
    assert by_phi.is_monotonic_increasing and by_phi.iloc[0] < by_phi.iloc[-1]


# 20. The comparability millage is phi * (i + t) * 1000.
def test_implied_millage_equivalent():
    summary, _ = _model()
    assert summary['implied_land_millage_equivalent'] == pytest.approx(63.998, abs=1e-9)
    half, _ = _model(capture_rate=0.5)
    assert half['implied_land_millage_equivalent'] == pytest.approx(31.999, abs=1e-9)


# 21. Incidence summary reports who pays and how many residents come out ahead.
def test_incidence_summary():
    _, parcels = _model(_parcels(), exemption_flag_col='full_exmp')
    tracts = pd.DataFrame({
        'tract_geoid': ['a', 'b'],
        'total_pop': [1_000.0, 3_000.0],
        'owner_households': [200.0, 400.0],
        'renter_households': [200.0, 800.0],
        'avg_household_size': [2.5, 2.5],
        'net_gain': [-50_000.0, 50_000.0],
    })
    inc = summarize_ubi_incidence(parcels, tracts, ubi_per_capita=1_000.0)
    assert inc['n_tracts'] == 2
    assert inc['n_tracts_net_positive'] == 1
    assert inc['share_population_net_positive'] == pytest.approx(75.0)
    assert inc['renter_share_pct'] == pytest.approx(1_000 / 1_600 * 100)
    assert inc['dividends_to_renter_households'] == pytest.approx(
        (200 * 2.5 + 800 * 2.5) * 1_000.0)
    assert set(inc['rent_by_payer_class']) <= {
        'Residential (1-4 units)', 'Commercial / Industrial', 'Vacant land / Parking',
        'Abated construction', 'Other / Institutional'}


def test_incidence_summary_tolerates_missing_tenure_columns():
    _, parcels = _model()
    tracts = pd.DataFrame({'tract_geoid': ['a'], 'total_pop': [10.0], 'net_gain': [1.0]})
    inc = summarize_ubi_incidence(parcels, tracts)
    assert inc['n_tracts_net_positive'] == 1
    assert np.isnan(inc['renter_share_pct'])


# 22. Exports round-trip, create their parent directory, and keep the sign
#     convention that positive net_gain means residents gain.
def test_tract_export_round_trip(tmp_path):
    tracts = pd.DataFrame({
        'tract_geoid': ['a', 'b'],
        'total_pop': [1_000.0, 1_000.0],
        'current_tax': [100_000.0, 100_000.0],
        'new_land_tax': [40_000.0, 400_000.0],
        'tax_change': [30_000.0, 300_000.0],
        'tract_dividend': [150_000.0, 150_000.0],
        'median_income': [40_000.0, 90_000.0],
        'renter_share_pct': [60.0, 20.0],
    })
    path = tmp_path / 'nested' / 'dir' / 'tracts.csv'
    out = save_ubi_tract_export(tracts, 'testcity', str(path), discount_rate=I,
                                capture_rate=1.0, ubi_per_capita=150.0)
    assert path.exists()
    assert out['net_gain'].tolist() == [120_000.0, -150_000.0]
    assert out['net_gain_per_capita'].tolist() == [120.0, -150.0]
    assert out.loc[0, 'net_gain'] > 0          # dividend beats the extra bill: residents gain
    reread = pd.read_csv(path)
    assert reread['net_gain'].tolist() == out['net_gain'].tolist()
    assert 'renter_share_pct' in reread.columns

    with pytest.raises(ValueError):
        save_ubi_tract_export(tracts.drop(columns=['tax_change']), 'testcity', str(path))


def test_parcel_export_round_trip(tmp_path):
    _, parcels = _model(_parcels(), exemption_flag_col='full_exmp')
    parcels['tract_geoid'] = '42101000100'
    path = tmp_path / 'nested' / 'parcels.csv'
    out = save_ubi_parcel_export(parcels, 'testcity', str(path),
                                 parcel_id_col='parcel_number', discount_rate=I,
                                 capture_rate=1.0)
    assert path.exists()
    assert out.columns[0] == 'parcel_id'
    assert {'land_rent', 'new_land_tax', 'building_tax', 'current_tax', 'new_tax',
            'tax_change', 'tax_change_pct', 'tract_geoid'} <= set(out.columns)
    # Source columns are renamed to the repo's standard export names, so an OPA-land run
    # and an LYCD-land run share one schema.
    assert {'property_category', 'taxable_land_value',
            'taxable_improvement_value'} <= set(out.columns)
    assert 'PROPERTY_CATEGORY' not in out.columns and 'taxable_land' not in out.columns
    assert len(pd.read_csv(path)) == len(parcels)

    renamed = parcels.rename(columns={'taxable_land': 'model_land'})
    out2 = save_ubi_parcel_export(renamed, 'testcity', str(tmp_path / 'p2.csv'),
                                  land_value_col='model_land')
    assert 'taxable_land_value' in out2.columns and 'model_land' not in out2.columns

    with pytest.raises(ValueError, match='model_full_land_rent_tax'):
        save_ubi_parcel_export(_parcels(), 'testcity', str(path))


# 23. Structural guards.
def test_invalid_arguments_raise():
    with pytest.raises(ValueError, match='revenue_framing'):
        _model(revenue_framing='nope')
    with pytest.raises(ValueError, match='capture_rate'):
        _model(capture_rate=1.5)
    with pytest.raises(ValueError, match='discount_rate'):
        _model(discount_rate=0.0)
    with pytest.raises(ValueError, match='not found'):
        model_full_land_rent_tax(_taxable_parcels(), 'nope', 'taxable_building',
                                 discount_rate=I, combined_rate=T)
    with pytest.raises(ValueError, match='rent_basis_col'):
        _model(rent_basis_col='nope')


# 24. The notebook's exact call chain, end to end, minus the two blocked API calls.
def test_notebook_call_sequence_smoke(tmp_path):
    import matplotlib
    matplotlib.use('Agg')
    import geopandas as gpd
    from shapely.geometry import Point, box

    from lvt.census_utils import match_to_census_tracts
    from lvt.viz import create_lvt_ubi_report

    rng = np.random.default_rng(0)
    n = 400
    parcels = gpd.GeoDataFrame({
        'parcel_number': [f'{k:09d}' for k in range(n)],
        'taxable_land': rng.uniform(5_000, 500_000, n),
        'taxable_building': rng.uniform(0, 900_000, n),
        'full_exmp': 0,
        'PROPERTY_CATEGORY': rng.choice(
            ['Single Family Residential', 'Commercial', 'Vacant Land'], n),
        'geometry': [Point(rng.uniform(0, 4), rng.uniform(0, 2)) for _ in range(n)],
    }, crs='EPSG:4326')

    tract_gdf = gpd.GeoDataFrame({
        'tract_geoid': ['t0', 't1', 't2', 't3'],
        'total_pop': [4_000.0, 9_000.0, 6_000.0, 5_000.0],
        'median_income': [30_000.0, 55_000.0, 80_000.0, 120_000.0],
        'minority_pct': [80.0, 55.0, 35.0, 15.0],
        'owner_households': [800.0, 1_800.0, 1_400.0, 1_200.0],
        'renter_households': [900.0, 1_900.0, 900.0, 500.0],
        'avg_household_size': [2.4, 2.4, 2.3, 2.2],
        'renter_share_pct': [52.9, 51.4, 39.1, 29.4],
        'geometry': [box(x, 0, x + 1, 2) for x in range(4)],
    }, crs='EPSG:4326')

    summary, parcels = model_full_land_rent_tax(
        parcels, 'taxable_land', 'taxable_building',
        discount_rate=I, combined_rate=T, capture_rate=1.0,
        exemption_flag_col='full_exmp', verbose=True,
    )
    assert summary['ubi_pot'] > 0

    parcels = match_to_census_tracts(parcels, tract_gdf[['tract_geoid', 'geometry']])
    assert parcels['tract_geoid'].notna().mean() > 0.98

    rolled = parcels.groupby('tract_geoid')[
        ['new_land_tax', 'current_tax', 'new_tax', 'tax_change']].sum().reset_index()
    tracts = tract_gdf.merge(rolled, on='tract_geoid', how='left').fillna({
        'new_land_tax': 0.0, 'current_tax': 0.0, 'new_tax': 0.0, 'tax_change': 0.0})

    dividend = compute_ubi_dividend(summary['ubi_pot'], tracts['total_pop'].sum())
    tracts = allocate_dividend_to_tracts(tracts, dividend['ubi_per_capita'],
                                         pot_total=summary['ubi_pot'])

    export = save_ubi_tract_export(
        tracts, 'testcity', str(tmp_path / 'data' / 'testcity.csv'),
        discount_rate=I, capture_rate=1.0, ubi_per_capita=dividend['ubi_per_capita'])
    assert export['net_gain'].sum() == pytest.approx(0.0, abs=1e-6)   # zero-sum, held harmless

    save_ubi_parcel_export(parcels, 'testcity', str(tmp_path / 'data' / 'testcity_parcels.csv'),
                           parcel_id_col='parcel_number', discount_rate=I, capture_rate=1.0)

    tracts['net_gain'] = export['net_gain'].values
    tracts['net_gain_per_capita'] = export['net_gain_per_capita'].values
    tracts['net_gain_pct'] = export['net_gain_pct'].values

    incidence = summarize_ubi_incidence(parcels, tracts,
                                        ubi_per_capita=dividend['ubi_per_capita'])
    sweep = sweep_land_rent_parameters(
        parcels, 'taxable_land', 'taxable_building',
        population=tracts['total_pop'].sum(),
        discount_rates=(0.03, 0.05, 0.07), capture_rates=(0.5, 1.0), combined_rate=T)

    breakeven = compute_breakeven_land_value(dividend['ubi_per_capita'], 2.3,
                                             discount_rate=I, combined_rate=T)

    report = create_lvt_ubi_report(
        tracts, 'testcity', output_dir=str(tmp_path / 'reports'), show=False,
        parcels_df=parcels, ubi_per_capita=dividend['ubi_per_capita'],
        incidence_summary=incidence, breakeven_land_value=breakeven, sweep_df=sweep,
    )
    written = {Path(p).name for p in report['charts_saved']}
    assert {'net_per_capita_map.png', 'income_quintile.png', 'minority_quintile.png',
            'breakeven_curve.png', 'who_pays.png', 'discount_rate_sensitivity.png',
            'distribution.png'} <= written
    for path in report['charts_saved']:
        assert Path(path).stat().st_size > 0


# 25. REGRESSION — the modeled baseline is the actual levy under either land source.
#
# The defect this pins down: passing an independent land surface as land_value_col
# rebuilds every parcel's *current* bill as t * (alt_land + building), which is not the
# assessment anybody was billed on. It survived both existing guards — a city-level
# revenue check that runs on the assessor's own total and never sees this frame, and a
# zero-sum check that nets the reform against whatever baseline it is handed.
@pytest.mark.parametrize('rent_basis_col', ['taxable_land', 'lycd_land'])
def test_baseline_equals_the_actual_levy_under_either_land_source(rent_basis_col):
    df = _dual_source_parcels()
    actual_levy = T * df['taxable_total'].sum()

    summary, out = _model(df, rent_basis_col=rent_basis_col,
                          baseline_total_col='taxable_total')

    assert summary['total_current_tax'] == pytest.approx(actual_levy, rel=1e-12)
    assert out['current_tax'].sum() == pytest.approx(actual_levy, rel=1e-12)
    assert summary['baseline_drift_pct'] == pytest.approx(0.0, abs=1e-9)
    # Per parcel too, not just in total.
    assert np.allclose(out['current_tax'], T * df['taxable_total'], rtol=1e-12)
    # The rent surface moves the levy and the pot; it must not move the baseline.
    assert summary['total_new_land_tax'] == pytest.approx(
        GROSS * df[rent_basis_col].sum(), rel=1e-12)


# 26. REGRESSION — the wrong wiring is now refused instead of quietly overstating.
def test_alt_land_surface_as_baseline_raises():
    df = _dual_source_parcels()
    with pytest.raises(ValueError, match='reconstructed baseline'):
        model_full_land_rent_tax(df, 'lycd_land', 'taxable_building',
                                 discount_rate=I, combined_rate=T,
                                 baseline_total_col='taxable_total')

    # Without the guard the old behaviour still reproduces, and this is its size: the
    # baseline is overstated by t * (alt_land - assessed_land), invisibly.
    summary, _ = model_full_land_rent_tax(df, 'lycd_land', 'taxable_building',
                                          discount_rate=I, combined_rate=T)
    overstatement = T * (df['lycd_land'].sum() - df['taxable_land'].sum())
    assert summary['total_current_tax'] - T * df['taxable_total'].sum() == \
        pytest.approx(overstatement, rel=1e-12)
    assert overstatement > 0


# 27. The held-harmless credit is the assessor's land revenue, not the rent surface's.
def test_held_harmless_credit_comes_from_the_actual_levy():
    df = _dual_source_parcels()
    summary, out = _model(df, rent_basis_col='lycd_land', baseline_total_col='taxable_total')

    l_assessed = df['taxable_land'].sum()
    l_rent = df['lycd_land'].sum()

    # Forced, not chosen: baseline = t*(L+B) and building tax = t*B, so the land credit
    # is the residual. Pricing it off the rent surface would hold the taxing bodies
    # harmless on revenue they never collected.
    assert summary['total_current_land_tax'] == pytest.approx(T * l_assessed, rel=1e-12)
    assert summary['total_building_tax'] == pytest.approx(
        T * df['taxable_building'].sum(), rel=1e-12)
    assert summary['total_current_land_tax'] + summary['total_building_tax'] == \
        pytest.approx(summary['total_current_tax'], rel=1e-12)

    assert summary['ubi_pot'] == pytest.approx(GROSS * l_rent - T * l_assessed, rel=1e-12)
    # Bigger than the pot the defective wiring produced, by exactly t * (L_rent -
    # L_assessed): crediting the taxing bodies on the larger surface ate that difference.
    # This is the $3.131B -> $3.406B move in the Philadelphia TY2026 run.
    assert summary['ubi_pot'] - I * l_rent == pytest.approx(
        T * (l_rent - l_assessed), rel=1e-12)
    assert summary['ubi_pot'] > I * l_rent


# 28. Identity 3 survives a rent basis that is not the current-tax basis.
@pytest.mark.parametrize('phi', [0.25, 0.5, 1.0])
def test_wealth_closure_holds_on_a_divergent_rent_basis(phi):
    df = _dual_source_parcels()
    summary, _ = _model(df, rent_basis_col='lycd_land', capture_rate=phi,
                        baseline_total_col='taxable_total')
    assert summary['land_wealth_destroyed'] == pytest.approx(summary['ubi_pot'] / I, rel=1e-12)
    # Pre-reform price is capitalized rent net of the tax actually borne, which exceeds
    # the assessed sum here because the rent surface is taxed at the smaller one.
    assert summary['pre_reform_land_value'] == pytest.approx(
        (GROSS * df['lycd_land'].sum() - T * df['taxable_land'].sum()) / I, rel=1e-12)
    assert summary['pre_reform_land_value'] > summary['total_land_value_rent_basis']
    # The raw assessed sum is still reported, unchanged — the notebook's magnitude gate
    # is keyed to it.
    assert summary['total_land_value_rent_basis'] == pytest.approx(
        df['lycd_land'].sum(), rel=1e-12)


# 29. Identity 1's precondition is reported, and is about values rather than column names.
def test_rent_basis_match_is_value_based():
    df = _dual_source_parcels()
    df['model_land'] = df['taxable_land']          # an OPA run's own copy, different name

    opa, opa_out = _model(df, rent_basis_col='model_land', rent_basis_label='taxable',
                          baseline_total_col='taxable_total')
    assert opa['rent_basis_matches_current_basis'] is True
    assert opa['rent_basis'] == 'taxable'
    assert np.allclose(opa_out['tax_change'], I * df['taxable_land'], rtol=1e-12)

    lycd, lycd_out = _model(df, rent_basis_col='lycd_land', rent_basis_label='taxable',
                            baseline_total_col='taxable_total')
    assert lycd['rent_basis_matches_current_basis'] is False
    # The general form, of which i*L is the matching-bases special case.
    assert np.allclose(lycd_out['tax_change'],
                       GROSS * df['lycd_land'] - T * df['taxable_land'], rtol=1e-12)
    assert not np.allclose(lycd_out['tax_change'], I * df['lycd_land'], rtol=1e-6)


# 30. A parcel row stays reconcilable when the rent surface is not the billed one.
def test_parcel_export_carries_both_land_columns(tmp_path):
    df = _dual_source_parcels()
    _, parcels = _model(df, rent_basis_col='lycd_land', baseline_total_col='taxable_total')
    out = save_ubi_parcel_export(parcels, 'testcity', str(tmp_path / 'p.csv'),
                                 parcel_id_col='parcel_number', discount_rate=I,
                                 capture_rate=1.0)
    assert {'taxable_land_value', 'rent_basis_land', 'current_land_tax'} <= set(out.columns)
    assert np.allclose(out['rent_basis_land'], df['lycd_land'], rtol=1e-12)
    assert np.allclose(out['taxable_land_value'], df['taxable_land'], rtol=1e-12)
    # current_tax = t * (billed land + billed building), row by row.
    assert np.allclose(out['current_land_tax'], T * out['taxable_land_value'], rtol=1e-12)
    assert np.allclose(out['current_tax'],
                       out['current_land_tax'] + out['building_tax'], rtol=1e-12)
