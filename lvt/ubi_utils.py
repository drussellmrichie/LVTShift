"""
Full land-rent capture with a per-capita dividend ("LVT + UBI") for LVTShift.

This is a third modeling paradigm. ``lvt_utils`` and ``reassessment`` change the
*rate* or the *base* of an existing property tax. ``wage_tax_utils`` swaps a
different instrument (a payroll tax) out and a land-only levy in. This module
does neither: it taxes the **annual rent** a site throws off, leaves the building
tax exactly as billed today, holds the taxing bodies harmless on the land portion
of their current revenue, and pays the residual out as an equal per-capita
dividend to residents.

Two consequences follow from that and shape every function here.

First, **there is no revenue-neutral solve**. The rate is exogenous: it is a
capture share of an imputed rent flow, not a millage backed out of a revenue
target. Nothing in this module calls ``model_split_rate_tax``, and that is
deliberate — do not "fix" it by adding a solver.

Second, at full capture the levy **is not expressible as a millage on assessed
value**. Taxing 100% of land rent drives the market price of land to zero, so the
ad-valorem base the levy would be denominated in ceases to exist. A real
implementation would have to charge an assessed *rental* value that OPA does not
publish today. ``implied_land_millage_equivalent`` in the summary is a
comparability aid against the repo's split-rate models, not an implementable rate.

The capitalization gross-up
---------------------------
An assessed land value is a market price, and that price already capitalizes the
existing land tax. For a perpetual site rent ``R``, net capitalization rate ``i``
and current ad-valorem rate ``t``::

    P * i = R - t * P    =>    R = P * (i + t)

so the observed assessed land value must be grossed up by ``(i + t)``, not merely
multiplied by ``i``. At Philadelphia's ``t = 0.013998`` and ``i = 0.05`` the
gross-up factor is ``0.063998`` — 28% more rent than a naive ``P * i``.

``i`` is a **net** capitalization rate, ``r - g``: the nominal required return on
land minus expected rent growth. It is not a raw discount rate. Where a site's
price embeds an option or growth premium (vacant land held speculatively), the
correct denominator is larger than ``i`` and ``P * (i + t)`` therefore overstates
*currently realizable* rent — on precisely the parcels an LVT targets.

Three identities
----------------
Each holds exactly, and each is asserted in the worked notebook and unit-tested:

1. ``tax_change = L * (phi*(i+t) - t)``, which at ``phi = 1`` collapses to
   ``i * L``. Precondition: the rent basis is the same column the current land
   tax is levied on.
2. ``owner_residual = (i+t)*(L+B) - new_tax = (1-phi)*(i+t)*L + i*B``, which at
   ``phi = 1`` is ``i * B``. The owner keeps a normal return on the structure and
   zero on the land. This is the arithmetic proof that the rent levy and the
   retained building tax do not double-count.
3. ``land_wealth_destroyed = ubi_pot / i``, exact for every ``phi``. The one-time
   capitalization loss to landowners equals the present value of the dividend
   stream. Stock and flow are two views of one transfer — never add them.

What the answer does and does not depend on
-------------------------------------------
At ``phi = 1`` under the held-harmless framing, a geography's net position is
``i * (sum(L) * pop_j / P - L_j)``. The sign of that does not involve ``i``, and
scaling every land value by a constant scales every net position by the same
constant. So the capitalization rate and any *uniform* assessment bias set the
dollar magnitudes but cannot change who wins. Only non-uniform assessment error
redistributes. Sensitivity ranks: land share >> i >> phi >> t.

Functions
---------
land_rent_from_value
    The capitalization gross-up, ``L * (i + t)``.
model_full_land_rent_tax
    The core model: per-parcel rent, new bill, unchanged building tax, and a
    summary carrying both revenue framings and the wealth account.
get_population_by_tract
    Tract population, tenure and household size from ACS, for the dividend
    denominator and the incidence analysis.
compute_ubi_dividend
    Split a dividend pot into per-resident shares.
allocate_dividend_to_tracts
    Push the per-capita dividend back onto tracts.
compute_breakeven_land_value
    The land value at which an owner-occupier household breaks even.
summarize_ubi_incidence
    Who pays the rent levy vs. who collects the dividend.
sweep_land_rent_parameters
    Sensitivity across capitalization rates and capture rates.
save_ubi_tract_export
    Primary deliverable: tract-level dividend vs. rent bill, winners and losers.
save_ubi_parcel_export
    Secondary parcel-level detail.
"""

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from lvt.census_utils import get_census_tract_data

DEFAULT_DISCOUNT_RATE = 0.05

# Property categories grouped into who actually writes the cheque. Owner-occupancy
# is NOT observable in the OPA parcel cache, so residential cannot be split into
# owner-occupied and rented here — the grouping stops where the data stops.
PAYER_CLASS_MAP: Dict[str, str] = {
    'Single Family Residential':      'Residential (1-4 units)',
    'Small Multi-Family (2-4 units)': 'Residential (1-4 units)',
    'Large Multi-Family (5+ units)':  'Multi-family (5+ units)',
    'Other Residential':              'Residential (1-4 units)',
    'Commercial':                     'Commercial / Industrial',
    'Other Commercial':               'Commercial / Industrial',
    'Retail / General Commercial':    'Commercial / Industrial',
    'Office / Commercial Condo':      'Commercial / Industrial',
    'Hotel':                          'Commercial / Industrial',
    'Mixed Use':                      'Commercial / Industrial',
    'Industrial':                     'Commercial / Industrial',
    'Transportation - Parking':       'Vacant land / Parking',
    'Vacant Land':                    'Vacant land / Parking',
    'Improved Vacant Land':           'Vacant land / Parking',
    'Agricultural':                   'Vacant land / Parking',
    'Abated / Construction Exemption': 'Abated construction',
}
PAYER_CLASS_FALLBACK = 'Other / Institutional'


def _clip_numeric(series: pd.Series) -> pd.Series:
    """Coerce to numeric, fill NaN with 0, clip negatives to 0."""
    return pd.to_numeric(series, errors='coerce').fillna(0.0).clip(lower=0.0)


def _optional_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric view of an optional column; all-NaN when the column is absent."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors='coerce')
    return pd.Series(np.nan, index=df.index, dtype='float64')


def land_rent_from_value(
    land_value: Union[float, pd.Series, np.ndarray],
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    tax_rate: float = 0.0,
) -> Union[float, pd.Series, np.ndarray]:
    """
    Convert an assessed land value into the annual site rent it implies.

    An assessed land value is a market price, and that price already capitalizes
    the ad-valorem tax the land currently bears. For a perpetual rent ``R``::

        P * i = R - t * P    =>    R = P * (i + t)

    so the gross-up factor is ``(i + t)``, not ``i``. Passing ``tax_rate=0``
    recovers the naive ``P * i`` and understates rent by ``t / i`` — roughly 28%
    at Philadelphia's combined rate and a 5% capitalization rate.

    Parameters
    ----------
    land_value : float, pd.Series or np.ndarray
        Assessed land value(s).
    discount_rate : float, default 0.05
        Net capitalization rate ``r - g`` (required return minus rent growth).
        Not a raw discount rate: where a site price embeds a growth or option
        premium, the true denominator is larger and this overstates currently
        realizable rent.
    tax_rate : float, default 0.0
        Current ad-valorem rate the land already bears, as a fraction (e.g.
        0.013998 for Philadelphia's combined city + school rate).

    Returns
    -------
    float, pd.Series or np.ndarray
        Annual land rent, same type as the input.

    Raises
    ------
    ValueError
        If ``discount_rate`` is not strictly positive, or ``tax_rate`` is negative.
    """
    if discount_rate <= 0:
        raise ValueError(
            f"discount_rate must be > 0, got {discount_rate}. A zero or negative "
            "capitalization rate implies infinite or negative land value."
        )
    if tax_rate < 0:
        raise ValueError(f"tax_rate must be >= 0, got {tax_rate}")
    return land_value * (discount_rate + tax_rate)


def model_full_land_rent_tax(
    df: pd.DataFrame,
    land_value_col: str,
    improvement_value_col: str,
    *,
    rent_basis_col: Optional[str] = None,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    combined_rate: float = 0.013998,
    capture_rate: float = 1.0,
    revenue_framing: str = 'city_held_harmless',
    exemption_flag_col: Optional[str] = None,
    verbose: bool = False,
) -> Tuple[Dict[str, float], pd.DataFrame]:
    """
    Model a land-rent levy with the building tax left unchanged.

    Each parcel's imputed annual site rent is ``land * (discount_rate +
    combined_rate)``. ``capture_rate`` of that is charged as the new land bill.
    The improvement side keeps paying exactly today's ad-valorem building tax,
    untouched. The taxing bodies' existing land-tax revenue is the first claim on
    the rent levy; what is left over is the dividend pot.

    There is no revenue-neutral solve here — the rate is exogenous. See the module
    docstring for why that is deliberate, and for why at ``capture_rate = 1.0``
    the levy cannot actually be denominated as a millage on assessed value.

    Parameters
    ----------
    df : pd.DataFrame
        Parcel data.
    land_value_col : str
        Land value the *current* tax is levied on (Philadelphia: ``taxable_land``,
        which is net of homestead, abatement and institutional relief).
    improvement_value_col : str
        Improvement value the *current* building tax is levied on.
    rent_basis_col : str, optional
        Land value the *rent* is imputed from. Defaults to ``land_value_col``.
        Pass a full-assessed-land column (e.g. ``taxable_land + exempt_land``) to
        model a levy that reaches currently-exempt land — an explicit policy
        choice that breaks the ``tax_change = i * L`` identity, since rent is then
        charged on a base the current tax does not touch.
    discount_rate : float, default 0.05
        Net capitalization rate.
    combined_rate : float, default 0.013998
        Current combined ad-valorem rate as a fraction. Pass
        ``tax_year_params(year).combined_rate_pct / 100`` rather than a literal.
    capture_rate : float, default 1.0
        Share of imputed land rent taken by the levy. 1.0 is full capture.
    revenue_framing : {'city_held_harmless', 'full_redistribution'}
        ``city_held_harmless`` (default) leaves today's land-tax revenue with the
        taxing bodies and puts only the surplus in the dividend pot.
        ``full_redistribution`` pays out the entire rent levy and reports the
        resulting unfunded budget hole.
    exemption_flag_col : str, optional
        Column flagging fully-exempt parcels (1 = exempt). Flagged parcels are
        zeroed on both the current and the new side.
    verbose : bool, default False
        Print the summary.

    Returns
    -------
    tuple
        ``(summary, result_df)``. ``result_df`` is a copy of ``df`` with
        ``land_rent``, ``new_land_tax``, ``building_tax``, ``current_land_tax``,
        ``current_tax``, ``new_tax``, ``tax_change``, ``tax_change_pct`` (NaN,
        never inf, where ``current_tax`` is 0) and ``owner_residual``.
        ``summary`` carries both revenue framings, the wealth account, and every
        parameter echoed back.

    Raises
    ------
    ValueError
        On an unknown ``revenue_framing``, a non-positive ``discount_rate``, a
        ``capture_rate`` outside [0, 1], or a missing column.
    """
    if revenue_framing not in ('city_held_harmless', 'full_redistribution'):
        raise ValueError(
            f"revenue_framing must be 'city_held_harmless' or 'full_redistribution', "
            f"got {revenue_framing!r}"
        )
    if discount_rate <= 0:
        raise ValueError(f"discount_rate must be > 0, got {discount_rate}")
    if not 0.0 <= capture_rate <= 1.0:
        raise ValueError(f"capture_rate must be in [0, 1], got {capture_rate}")
    for col in (land_value_col, improvement_value_col):
        if col not in df.columns:
            raise ValueError(f"column {col!r} not found in df")
    basis_col = rent_basis_col or land_value_col
    if basis_col not in df.columns:
        raise ValueError(f"rent_basis_col {basis_col!r} not found in df")

    out = df.copy()
    land_current = _clip_numeric(out[land_value_col])
    land_basis = _clip_numeric(out[basis_col])
    improvement = _clip_numeric(out[improvement_value_col])

    if exemption_flag_col is not None:
        if exemption_flag_col not in out.columns:
            raise ValueError(f"exemption_flag_col {exemption_flag_col!r} not found in df")
        keep = pd.to_numeric(out[exemption_flag_col], errors='coerce').fillna(0) != 1
        land_current = land_current.where(keep, 0.0)
        land_basis = land_basis.where(keep, 0.0)
        improvement = improvement.where(keep, 0.0)
        n_exempt = int((~keep).sum())
    else:
        n_exempt = 0

    gross_up = discount_rate + combined_rate

    out['land_rent'] = land_basis * gross_up
    out['new_land_tax'] = capture_rate * out['land_rent']
    out['building_tax'] = combined_rate * improvement
    out['current_land_tax'] = combined_rate * land_current
    out['current_tax'] = out['current_land_tax'] + out['building_tax']
    out['new_tax'] = out['new_land_tax'] + out['building_tax']
    out['tax_change'] = out['new_tax'] - out['current_tax']
    positive_current = out['current_tax'] > 0
    out['tax_change_pct'] = np.where(
        positive_current,
        out['tax_change'] / out['current_tax'].where(positive_current) * 100,
        np.nan,
    )
    out['owner_residual'] = gross_up * (land_basis + improvement) - out['new_tax']

    total_new_land_tax = float(out['new_land_tax'].sum())
    total_current_land_tax = float(out['current_land_tax'].sum())
    held_harmless_pot = total_new_land_tax - total_current_land_tax
    full_redistribution_pot = total_new_land_tax

    if revenue_framing == 'city_held_harmless':
        ubi_pot = held_harmless_pot
        budget_hole = 0.0
    else:
        ubi_pot = full_redistribution_pot
        budget_hole = total_current_land_tax

    pre_reform_land_value = float(land_basis.sum())
    post_reform_land_value = pre_reform_land_value * gross_up * (1.0 - capture_rate) / discount_rate

    summary: Dict[str, float] = {
        'n_parcels': int(len(out)),
        'n_exempt': n_exempt,
        'rent_basis': 'full' if basis_col != land_value_col else 'taxable',
        'rent_basis_col': basis_col,
        'revenue_framing': revenue_framing,
        'discount_rate': float(discount_rate),
        'combined_rate': float(combined_rate),
        'capture_rate': float(capture_rate),
        'gross_up_factor': float(gross_up),
        'total_land_value_current_basis': float(land_current.sum()),
        'total_land_value_rent_basis': pre_reform_land_value,
        'total_improvement_value': float(improvement.sum()),
        'total_land_rent': float(out['land_rent'].sum()),
        'total_new_land_tax': total_new_land_tax,
        'total_current_land_tax': total_current_land_tax,
        'total_building_tax': float(out['building_tax'].sum()),
        'total_current_tax': float(out['current_tax'].sum()),
        'total_new_tax': float(out['new_tax'].sum()),
        'city_held_harmless_pot': held_harmless_pot,
        'full_redistribution_pot': full_redistribution_pot,
        'full_redistribution_budget_hole': total_current_land_tax,
        'ubi_pot': ubi_pot,
        'budget_hole': budget_hole,
        'implied_land_millage_equivalent': float(capture_rate * gross_up * 1000.0),
        'pre_reform_land_value': pre_reform_land_value,
        'post_reform_land_value': post_reform_land_value,
        'land_wealth_destroyed': pre_reform_land_value - post_reform_land_value,
    }

    breakeven_capture = combined_rate / gross_up
    if capture_rate <= breakeven_capture:
        print(
            f"WARNING: capture_rate {capture_rate:.4f} is at or below "
            f"{breakeven_capture:.4f} = t/(i+t), so the rent levy raises no more than "
            "today's land tax and the dividend pot is not positive."
        )

    if verbose:
        print(f"Rent basis:                {summary['rent_basis']} ({basis_col})")
        print(f"Land value (rent basis):   ${pre_reform_land_value:,.0f}")
        print(f"Imputed annual land rent:  ${summary['total_land_rent']:,.0f}")
        print(f"New land levy:             ${total_new_land_tax:,.0f}")
        print(f"Current land tax:          ${total_current_land_tax:,.0f}")
        print(f"Building tax (unchanged):  ${summary['total_building_tax']:,.0f}")
        print(f"Dividend pot ({revenue_framing}): ${ubi_pot:,.0f}")
        if budget_hole:
            print(f"Unfunded budget hole:      ${budget_hole:,.0f}")
        print(f"Implied land millage equiv:{summary['implied_land_millage_equivalent']:9.4f}")
        print(f"Land wealth destroyed:     ${summary['land_wealth_destroyed']:,.0f}")

    return summary, out


def get_population_by_tract(
    fips_code: str,
    year: int = 2022,
    api_key: str = None,
) -> pd.DataFrame:
    """
    Fetch tract population, tenure and household size for the dividend analysis.

    The dividend denominator is resident population, so it must come from the same
    tracts every other number in the analysis is keyed to — never a hardcoded
    citywide figure. Tenure is fetched alongside it because the incidence result
    turns on it: a tax on pure land rent cannot be shifted to tenants, so renter
    households collect the dividend with no direct liability.

    Wraps ``lvt.census_utils.get_census_tract_data``, which already returns
    ``total_pop`` (B01003_001E) plus the standard demographic set.

    Parameters
    ----------
    fips_code : str
        5-digit state + county FIPS, e.g. "42101" for Philadelphia County.
    year : int, default 2022
        ACS 5-year vintage.
    api_key : str, optional
        Census API key; falls back to the CENSUS_API_KEY environment variable.

    Returns
    -------
    pd.DataFrame
        One row per tract keyed on ``tract_geoid``, with ``total_pop``,
        ``total_pop_moe``, ``occupied_households``, ``owner_households``,
        ``renter_households``, ``avg_household_size``, ``renter_share_pct`` and
        the default ``median_income`` / ``minority_pct`` / ``black_pct`` columns.
    """
    df = get_census_tract_data(
        fips_code,
        year=year,
        api_key=api_key,
        extra_variables=[
            'B01003_001M',   # total population, margin of error
            'B25003_001E',   # occupied housing units
            'B25003_002E',   # owner occupied
            'B25003_003E',   # renter occupied
            'B25010_001E',   # average household size of occupied units
        ],
        column_aliases={
            'B01003_001M': 'total_pop_moe',
            'B25003_001E': 'occupied_households',
            'B25003_002E': 'owner_households',
            'B25003_003E': 'renter_households',
            'B25010_001E': 'avg_household_size',
        },
    )
    df['renter_share_pct'] = np.where(
        df['occupied_households'] > 0,
        df['renter_households'] / df['occupied_households'] * 100,
        np.nan,
    )
    return df


def compute_ubi_dividend(
    pot_total: float,
    population: float,
    *,
    child_population: Optional[float] = None,
    child_share: float = 1.0,
) -> Dict[str, float]:
    """
    Split a dividend pot into per-resident shares.

    ``child_share = 1.0`` — every resident, adult or child, receives a full share
    — is the default because it is a policy choice worth stating rather than
    assuming. Alaska's Permanent Fund Dividend pays children a full share; many
    UBI designs pay a half share.

    Parameters
    ----------
    pot_total : float
        Dollars available to distribute.
    population : float
        Total resident population.
    child_population : float, optional
        Residents under 18. Required only when ``child_share != 1.0``.
    child_share : float, default 1.0
        Fraction of a full share paid per child.

    Returns
    -------
    dict
        ``pot_total``, ``population``, ``child_population``, ``child_share``,
        ``total_shares``, ``ubi_per_share``, ``ubi_per_capita``. By construction
        ``ubi_per_share * total_shares == pot_total``.

    Raises
    ------
    ValueError
        If ``population`` is not positive, ``child_share`` is outside [0, 1], or
        ``child_share != 1.0`` without a ``child_population``.
    """
    if population <= 0:
        raise ValueError(f"population must be > 0, got {population}")
    if not 0.0 <= child_share <= 1.0:
        raise ValueError(f"child_share must be in [0, 1], got {child_share}")
    if child_share != 1.0 and child_population is None:
        raise ValueError("child_share != 1.0 requires child_population")

    if child_population is None:
        total_shares = float(population)
    else:
        if child_population < 0 or child_population > population:
            raise ValueError(
                f"child_population {child_population} must be in [0, population={population}]"
            )
        total_shares = float(population - child_population) + child_share * float(child_population)
    if total_shares <= 0:
        raise ValueError("total_shares resolved to 0; nothing to distribute")

    return {
        'pot_total': float(pot_total),
        'population': float(population),
        'child_population': None if child_population is None else float(child_population),
        'child_share': float(child_share),
        'total_shares': total_shares,
        'ubi_per_share': float(pot_total) / total_shares,
        'ubi_per_capita': float(pot_total) / float(population),
    }


def allocate_dividend_to_tracts(
    tract_df: pd.DataFrame,
    ubi_per_capita: float,
    pop_col: str = 'total_pop',
    out_col: str = 'tract_dividend',
    pot_total: Optional[float] = None,
    tolerance_pct: float = 0.5,
) -> pd.DataFrame:
    """
    Push the per-capita dividend back onto tracts.

    Parameters
    ----------
    tract_df : pd.DataFrame
        Tract-level frame containing ``pop_col``.
    ubi_per_capita : float
        Dividend per resident, from ``compute_ubi_dividend``.
    pop_col : str, default 'total_pop'
        Tract population column.
    out_col : str, default 'tract_dividend'
        Name of the total-dollars column to write.
    pot_total : float, optional
        When given, the tract total is checked against it and a warning is printed
        if they drift. ACS tract populations can sum slightly away from a citywide
        denominator when tracts are suppressed or when the two use different
        vintages.
    tolerance_pct : float, default 0.5
        Drift tolerance for that check, in percent.

    Returns
    -------
    pd.DataFrame
        Copy of ``tract_df`` with ``out_col`` and ``dividend_per_capita`` added.
    """
    if pop_col not in tract_df.columns:
        raise ValueError(f"pop_col {pop_col!r} not found in tract_df")

    out = tract_df.copy()
    pop = pd.to_numeric(out[pop_col], errors='coerce').fillna(0.0)
    out[out_col] = pop * float(ubi_per_capita)
    out['dividend_per_capita'] = float(ubi_per_capita)

    if pot_total:
        allocated = float(out[out_col].sum())
        drift_pct = (allocated / float(pot_total) - 1) * 100
        if abs(drift_pct) > tolerance_pct:
            print(
                f"WARNING: allocated dividends ${allocated:,.0f} differ from the pot "
                f"${pot_total:,.0f} by {drift_pct:+.2f}% (tolerance {tolerance_pct}%). "
                "Check that the population denominator is the sum of these same tracts."
            )
    return out


def compute_breakeven_land_value(
    ubi_per_capita: float,
    household_size: float,
    *,
    discount_rate: float = DEFAULT_DISCOUNT_RATE,
    combined_rate: float = 0.013998,
    capture_rate: float = 1.0,
) -> float:
    """
    Land value at which an owner-occupier household exactly breaks even.

    A household on a parcel with land value ``L`` pays ``L * (phi*(i+t) - t)``
    more than today and collects ``ubi_per_capita * household_size``. Setting
    those equal gives the threshold; below it the household comes out ahead.

    This compares a *parcel-level* bill against a *household-level* dividend, so
    it is only meaningful for owner-occupied single-unit parcels. On a 40-unit
    apartment parcel one owner pays the land bill while 40 households collect
    dividends, and the comparison is meaningless. Scope callers accordingly.

    Parameters
    ----------
    ubi_per_capita : float
        Dividend per resident.
    household_size : float
        Residents per household. Prefer a local (tract) average over a citywide one.
    discount_rate, combined_rate, capture_rate : float
        As in ``model_full_land_rent_tax``.

    Returns
    -------
    float
        Break-even land value in dollars.

    Raises
    ------
    ValueError
        When ``capture_rate <= combined_rate / (discount_rate + combined_rate)``,
        i.e. when the levy raises no more than today's land tax so that every
        landowner is a winner and no threshold exists.
    """
    denominator = capture_rate * (discount_rate + combined_rate) - combined_rate
    if denominator <= 0:
        breakeven_capture = combined_rate / (discount_rate + combined_rate)
        raise ValueError(
            f"capture_rate {capture_rate} is at or below t/(i+t) = {breakeven_capture:.4f}, "
            "so the rent levy costs landowners nothing relative to today and there is no "
            "break-even land value."
        )
    return float(ubi_per_capita) * float(household_size) / denominator


def summarize_ubi_incidence(
    parcels_df: pd.DataFrame,
    tract_df: pd.DataFrame,
    *,
    category_col: str = 'PROPERTY_CATEGORY',
    new_land_tax_col: str = 'new_land_tax',
    tax_change_col: str = 'tax_change',
    net_gain_col: str = 'net_gain',
    population_col: str = 'total_pop',
    owner_households_col: str = 'owner_households',
    renter_households_col: str = 'renter_households',
    avg_household_size_col: str = 'avg_household_size',
    ubi_per_capita: Optional[float] = None,
) -> Dict[str, object]:
    """
    Who pays the rent levy and who collects the dividend.

    The structural finding this exists to measure: land rent is collected from
    whoever holds title — including absentee, commercial and institutional owners
    who live nowhere near the parcel — while the dividend goes only to residents.
    That mismatch is the mirror image of the commuter transfer in the wage-tax
    swap, running the other way.

    Owner-occupancy is not observable in the OPA parcel cache, so the payer
    classes stop at property type; ``PAYER_CLASS_MAP`` documents the grouping.

    Parameters
    ----------
    parcels_df : pd.DataFrame
        Parcel-level output of ``model_full_land_rent_tax``, with ``category_col``.
    tract_df : pd.DataFrame
        Tract-level frame with population, tenure and ``net_gain_col``.
    category_col, new_land_tax_col, tax_change_col, net_gain_col : str
        Column names.
    population_col, owner_households_col, renter_households_col,
    avg_household_size_col : str
        Tract columns. Missing tenure columns degrade gracefully to NaN.
    ubi_per_capita : float, optional
        Used to split dividends between owner and renter households.

    Returns
    -------
    dict
        Totals, ``rent_by_payer_class`` (a dict), tract and population net-positive
        shares, tenure counts and the owner/renter dividend split.
    """
    result: Dict[str, object] = {}

    result['total_new_land_tax'] = float(parcels_df[new_land_tax_col].sum())
    result['total_tax_change'] = float(parcels_df[tax_change_col].sum())

    if category_col in parcels_df.columns:
        payer = parcels_df[category_col].astype(str).map(PAYER_CLASS_MAP)
        payer = payer.fillna(PAYER_CLASS_FALLBACK)
        by_class = parcels_df.groupby(payer)[new_land_tax_col].sum().sort_values(ascending=False)
        result['rent_by_payer_class'] = {str(k): float(v) for k, v in by_class.items()}
        change_by_class = parcels_df.groupby(payer)[tax_change_col].sum().sort_values(ascending=False)
        result['tax_change_by_payer_class'] = {str(k): float(v) for k, v in change_by_class.items()}
    else:
        result['rent_by_payer_class'] = {}
        result['tax_change_by_payer_class'] = {}

    pop = _optional_numeric(tract_df, population_col).fillna(0.0)
    result['total_population'] = float(pop.sum())

    if net_gain_col in tract_df.columns:
        net = pd.to_numeric(tract_df[net_gain_col], errors='coerce')
        positive = net > 0
        result['n_tracts'] = int(len(tract_df))
        result['n_tracts_net_positive'] = int(positive.sum())
        result['share_tracts_net_positive'] = (
            float(positive.sum()) / len(tract_df) * 100 if len(tract_df) else np.nan
        )
        pop_positive = float(pop.where(positive, 0.0).sum())
        result['population_net_positive'] = pop_positive
        result['share_population_net_positive'] = (
            pop_positive / float(pop.sum()) * 100 if pop.sum() else np.nan
        )
    else:
        result['n_tracts'] = int(len(tract_df))
        result['n_tracts_net_positive'] = None
        result['share_tracts_net_positive'] = np.nan
        result['population_net_positive'] = np.nan
        result['share_population_net_positive'] = np.nan

    owners = _optional_numeric(tract_df, owner_households_col)
    renters = _optional_numeric(tract_df, renter_households_col)
    hh_size = _optional_numeric(tract_df, avg_household_size_col)
    result['owner_households'] = float(owners.sum())
    result['renter_households'] = float(renters.sum())
    total_hh = result['owner_households'] + result['renter_households']
    result['renter_share_pct'] = (
        result['renter_households'] / total_hh * 100 if total_hh else np.nan
    )

    if ubi_per_capita is not None:
        result['dividends_to_renter_households'] = float(
            (renters * hh_size * ubi_per_capita).sum()
        )
        result['dividends_to_owner_households'] = float(
            (owners * hh_size * ubi_per_capita).sum()
        )
    else:
        result['dividends_to_renter_households'] = np.nan
        result['dividends_to_owner_households'] = np.nan

    return result


def sweep_land_rent_parameters(
    df: pd.DataFrame,
    land_value_col: str,
    improvement_value_col: str,
    population: float,
    *,
    discount_rates: Optional[Sequence[float]] = None,
    capture_rates: Optional[Sequence[float]] = None,
    base_discount_rate: float = DEFAULT_DISCOUNT_RATE,
    base_capture_rate: float = 1.0,
    **model_kwargs,
) -> pd.DataFrame:
    """
    Sensitivity of the dividend to the capitalization rate and the capture rate.

    Sweeps one parameter at a time, holding the other at its base value. The
    partition of winners and losers is invariant to ``discount_rate`` under the
    held-harmless framing at full capture — only the dollar magnitudes move — so
    this table is about scale, not about who wins.

    Parameters
    ----------
    df : pd.DataFrame
        Parcel data, as passed to ``model_full_land_rent_tax``.
    land_value_col, improvement_value_col : str
        Column names.
    population : float
        Denominator for ``ubi_per_capita``.
    discount_rates, capture_rates : sequence of float, optional
        Values to sweep. Either may be omitted.
    base_discount_rate, base_capture_rate : float
        Held fixed while the other parameter is swept.
    **model_kwargs
        Passed through to ``model_full_land_rent_tax`` (e.g. ``combined_rate``,
        ``revenue_framing``, ``rent_basis_col``, ``exemption_flag_col``).

    Returns
    -------
    pd.DataFrame
        One row per parameter point with ``swept``, ``discount_rate``,
        ``capture_rate``, ``total_land_rent``, ``ubi_pot``, ``ubi_per_capita``,
        ``implied_land_millage_equivalent`` and ``land_wealth_destroyed``.
    """
    if population <= 0:
        raise ValueError(f"population must be > 0, got {population}")

    rows: List[Dict[str, float]] = []

    def _run(swept: str, discount: float, capture: float) -> None:
        summary, _ = model_full_land_rent_tax(
            df,
            land_value_col,
            improvement_value_col,
            discount_rate=discount,
            capture_rate=capture,
            **model_kwargs,
        )
        rows.append({
            'swept': swept,
            'discount_rate': summary['discount_rate'],
            'capture_rate': summary['capture_rate'],
            'total_land_rent': summary['total_land_rent'],
            'ubi_pot': summary['ubi_pot'],
            'ubi_per_capita': summary['ubi_pot'] / float(population),
            'implied_land_millage_equivalent': summary['implied_land_millage_equivalent'],
            'land_wealth_destroyed': summary['land_wealth_destroyed'],
        })

    for rate in (discount_rates or []):
        _run('discount_rate', rate, base_capture_rate)
    for rate in (capture_rates or []):
        _run('capture_rate', base_discount_rate, rate)

    return pd.DataFrame(rows)


def save_ubi_tract_export(
    tract_df: pd.DataFrame,
    city: str,
    output_path: str,
    *,
    tract_geoid_col: str = 'tract_geoid',
    dividend_col: str = 'tract_dividend',
    tax_change_col: str = 'tax_change',
    new_land_tax_col: str = 'new_land_tax',
    current_tax_col: str = 'current_tax',
    population_col: str = 'total_pop',
    income_col: str = 'median_income',
    minority_col: str = 'minority_pct',
    black_col: str = 'black_pct',
    renter_share_col: str = 'renter_share_pct',
    model_type: str = 'lvt_ubi:full_land_rent_capture',
    discount_rate: Optional[float] = None,
    capture_rate: Optional[float] = None,
    ubi_per_capita: Optional[float] = None,
) -> pd.DataFrame:
    """
    Build and save the tract-level LVT + UBI export. The primary deliverable.

    **Sign convention — this inverts relative to the wage-tax swap export.** There
    ``net_change > 0`` means a tract pays more. Here::

        net_gain = tract_dividend - tax_change

    so **positive means the tract's residents come out ahead**. Getting this
    backwards silently flips every map and quintile chart, so the column is named
    ``net_gain`` rather than ``net_change`` to make the difference visible at the
    call site.

    Note the subtrahend is ``tax_change``, the *additional* levy relative to
    today's bill — not ``new_land_tax``, which includes the land tax the parcel
    already pays and which the taxing bodies keep under the held-harmless framing.
    Using ``new_land_tax`` here would double-count that portion. Under
    ``city_held_harmless`` this makes the analysis exactly zero-sum:
    ``sum(net_gain) == 0``. Under ``full_redistribution`` the sum equals the
    unfunded budget hole.

    Tract-level results mix two incidence populations — a tract's land rent is
    paid by owners who may live elsewhere, while its dividend goes to residents —
    so this is a directional result, not a household-level guarantee.

    Parameters
    ----------
    tract_df : pd.DataFrame
        Tract-level frame with the dividend and the aggregated parcel columns.
    city : str
        Lowercase slug, e.g. "philadelphia_lvt_ubi".
    output_path : str
        Destination CSV path; parent directories are created.
    tract_geoid_col, dividend_col, tax_change_col, new_land_tax_col,
    current_tax_col, population_col : str
        Column names in ``tract_df``.
    income_col, minority_col, black_col, renter_share_col : str
        Optional columns carried through when present.
    model_type : str
        Encoded model description recorded as a constant column.
    discount_rate, capture_rate, ubi_per_capita : float, optional
        Recorded as constant columns for reference.

    Returns
    -------
    pd.DataFrame
        The exported frame, also written to ``output_path``.
    """
    for col in (tract_geoid_col, dividend_col, tax_change_col):
        if col not in tract_df.columns:
            raise ValueError(f"required column {col!r} not found in tract_df")

    out = tract_df.copy()
    out['net_gain'] = out[dividend_col] - out[tax_change_col]

    pop = _optional_numeric(out, population_col)
    out['net_gain_per_capita'] = np.where(
        pop > 0, out['net_gain'] / pop.where(pop > 0), np.nan
    )
    cur = _optional_numeric(out, current_tax_col)
    out['net_gain_pct'] = np.where(
        cur > 0, out['net_gain'] / cur.where(cur > 0) * 100, np.nan
    )

    out['city'] = city
    out['model_type'] = model_type
    out['discount_rate'] = discount_rate
    out['capture_rate'] = capture_rate
    out['ubi_per_capita'] = ubi_per_capita

    cols = [tract_geoid_col, 'city', population_col, current_tax_col, new_land_tax_col,
            tax_change_col, dividend_col, 'net_gain', 'net_gain_per_capita', 'net_gain_pct',
            'model_type', 'discount_rate', 'capture_rate', 'ubi_per_capita']
    cols = [c for c in cols if c in out.columns]
    for col in (income_col, minority_col, black_col, renter_share_col):
        if col in out.columns:
            cols.append(col)

    out = out[cols]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    return out


def save_ubi_parcel_export(
    parcels_df: pd.DataFrame,
    city: str,
    output_path: str,
    *,
    parcel_id_col: Optional[str] = None,
    category_col: str = 'PROPERTY_CATEGORY',
    land_value_col: str = 'taxable_land',
    improvement_value_col: str = 'taxable_building',
    tract_geoid_col: str = 'tract_geoid',
    model_type: str = 'lvt_ubi:full_land_rent_capture',
    discount_rate: Optional[float] = None,
    capture_rate: Optional[float] = None,
) -> pd.DataFrame:
    """
    Build and save the parcel-level detail export.

    Secondary to ``save_ubi_tract_export``: the dividend side of the reform has no
    parcel-level meaning, so this covers the levy side only. Unlike the wage-tax
    parcel export, ``current_tax`` is real here — parcels genuinely pay today's
    property tax — so ``tax_change`` and ``tax_change_pct`` are meaningful.

    This does not reuse ``lvt.lvt_utils.save_standard_export``, whose revenue
    drift check assumes the reform is revenue-neutral. This one is deliberately
    not: raising more than today's levy is the entire point, since the surplus is
    what funds the dividend.

    Parameters
    ----------
    parcels_df : pd.DataFrame
        Parcel-level output of ``model_full_land_rent_tax``.
    city : str
        Lowercase slug.
    output_path : str
        Destination CSV path; parent directories are created.
    parcel_id_col : str, optional
        Renamed to ``parcel_id`` and placed first when present.
    category_col, land_value_col, improvement_value_col, tract_geoid_col : str
        Optional source columns carried through when present. The first three are renamed
        on the way out to ``property_category`` / ``taxable_land_value`` /
        ``taxable_improvement_value``, so an OPA-land run and an LYCD-land run share one
        schema regardless of which source column each read from.
    model_type : str
        Encoded model description recorded as a constant column.
    discount_rate, capture_rate : float, optional
        Recorded as constant columns.

    Returns
    -------
    pd.DataFrame
        The exported frame, also written to ``output_path``.
    """
    required = ['land_rent', 'new_land_tax', 'building_tax', 'current_tax', 'new_tax',
                'tax_change', 'tax_change_pct']
    missing = [c for c in required if c not in parcels_df.columns]
    if missing:
        raise ValueError(
            f"parcels_df is missing {missing}; pass the output of model_full_land_rent_tax()"
        )

    out = parcels_df.copy()
    out['city'] = city
    out['model_type'] = model_type
    out['discount_rate'] = discount_rate
    out['capture_rate'] = capture_rate

    cols: List[str] = ['city']
    if parcel_id_col and parcel_id_col in out.columns:
        out = out.rename(columns={parcel_id_col: 'parcel_id'})
        cols = ['parcel_id'] + cols
    # Rename the passed-through source columns to the repo's standard export names, so a
    # run on OPA land and a run on LYCD land produce byte-comparable schemas.
    renames = {category_col: 'property_category',
               land_value_col: 'taxable_land_value',
               improvement_value_col: 'taxable_improvement_value'}
    for src, dest in renames.items():
        if src in out.columns and src != dest:
            out = out.rename(columns={src: dest})
        if dest in out.columns:
            cols.append(dest)
    cols += required
    if tract_geoid_col in out.columns:
        cols.append(tract_geoid_col)
    cols += ['model_type', 'discount_rate', 'capture_rate']

    out = out[cols]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output_path, index=False)
    return out
