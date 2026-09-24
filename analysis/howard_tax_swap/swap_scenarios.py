"""
Howard County, MD: which county tax could a land-value levy replace, and who wins?

For each candidate tax T with revenue R_T, the swap abolishes T and adds a land-only levy
sized to R_T on the county's billed taxable land base (phase-in, exemptions and Homestead
credit carried from the Howard model export). A parcel's net change is

    land_levy_i - T_i,   land_levy_i = R_T * L_i / sum(L)

where T_i is the parcel's (or its occupying household's) annual share of the abolished tax.
Both terms are linear in R_T, so which parcels win or lose does not depend on the size of
the swap; only the dollar amounts do. Results are reported per $10M swapped and at each
tax's budgeted revenue.

Allocation of each abolished tax to parcels (documented assumptions, not measurements):
- Fire & Rescue tax: exact, 0.206% of each parcel's billed base (real-property share only).
- Transfer + recordation: in proportion to full market value with uniform turnover. The
  roll carries no sale dates, so category-specific turnover is not modeled.
- Local income tax: in proportion to household income. Owner-occupied homes get their
  tract's mean owner-household income (ACS B25120 / B25003); renters' share is reported
  in aggregate only.
- Hotel/motel tax: paid by guests; no resident parcel carries any of it.
- Admissions & amusement: allocated like the income tax, i.e. as if residents paid all of
  it in proportion to income. This is the most favorable case for the swap.
- School facilities surcharge + road excise tax: paid on new construction; no existing
  home carries any of it.

Run from the repo root:
    C:/Users/druss/miniconda3/python.exe analysis/howard_tax_swap/swap_scenarios.py
"""

import os
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent / 'results'
OUT_DIR.mkdir(exist_ok=True)
load_dotenv(REPO_ROOT / '.env')

EXPORT = REPO_ROOT / 'analysis' / 'data' / 'howard_county.csv'
ROLL = REPO_ROOT / 'cities' / 'howard_county' / 'data' / 'sdat_howa_2026-09-23.csv'
FIRE_MILLAGE = 2.06            # $0.206 per $100
COMBINED_MILLAGE = 12.50       # county 1.044 + fire 0.206, per $100 -> per $1,000
ACS_YEAR = 2024

# Revenue each swap replaces, $. Page numbers are the printed pages of the Howard County FY 2027
# Approved Operating Budget (howardcountymd.gov, HCCBudgetbuild_Approved2027_06102026_Bookmarked.pdf).
# Inputs, not results: they are kept here because the repo ignores *.csv.
REVENUES = pd.Series({
    # The model export's own current-tax total (county general + fire real-property levies)
    'property_split_4to1': 923_500_536,
    # Fire share (0.206 / 1.250) of the modeled current tax; the fund's $153.7M (p. 380) also
    # includes business personal property
    'fire_tax': 152_187_000,
    # Local transfer tax, its five earmarked funds 9.8 + 9.8 + 7.8 + 5.9 + 5.9 = $39.2M
    # (capital-fund pages), plus recordation tax $19.0M (p. 39)
    'transfer_recordation': 58_200_000,
    # Income tax $739.2M (p. 39) x (3.20 - 2.25) / 3.20: the largest cut the 2.25% floor in
    # Tax-General 10-106 allows
    'income_tax': 219_443_000,
    # 'Other Local Taxes' (p. 39) combines hotel/motel and admissions & amusement; the split is
    # not published, so each scenario uses the combined line
    'admissions_amusement': 9_700_000,
    'hotel_tax': 9_700_000,
    # School facilities surcharge $6.0M (p. 367) + road excise tax $2.6M (p. 370)
    'surcharge_excise': 8_600_000,
})

HOME_CATS = ['Single Family Residential', 'Townhome / Rowhouse', 'Condominium']


def load_parcels() -> pd.DataFrame:
    e = pd.read_csv(EXPORT, dtype={'parcel_id': str, 'std_geoid': str})
    roll = pd.read_csv(ROLL, dtype=str, usecols=['acctid', 'owner_occ', 'cycle_year', 'cur_land', 'cur_impr'])
    roll = roll[roll['cycle_year'] == '2027'].drop_duplicates('acctid')
    df = e.merge(roll[['acctid', 'owner_occ', 'cur_land', 'cur_impr']], left_on='parcel_id',
                 right_on='acctid', how='left')
    assert len(df) == len(e)
    df = df[~df['is_fully_exempt']].copy()
    df['market_value'] = pd.to_numeric(df['cur_land'], errors='coerce').fillna(0) + \
        pd.to_numeric(df['cur_impr'], errors='coerce').fillna(0)
    df['billed_base'] = df['taxable_land_value'] + df['taxable_improvement_value']
    # Guard: the export's current tax is the billed base at the combined rate
    resid = (df['billed_base'] * COMBINED_MILLAGE / 1000 - df['current_tax']).abs().max()
    assert resid < 1.0, f"billed base does not reproduce current_tax (max resid ${resid:,.2f})"
    df['owner_home'] = (df['owner_occ'] == 'H') & df['property_category'].isin(HOME_CATS)
    df['tract'] = df['std_geoid'].str[:11]
    return df


def load_owner_income() -> pd.DataFrame:
    """Tract mean owner-household income and county aggregate household income (ACS 5-year)."""
    key = os.getenv('CENSUS_API_KEY')
    url = f'https://api.census.gov/data/{ACS_YEAR}/acs/acs5'
    j = requests.get(url, params={'get': 'B25120_001E,B25120_002E,B25003_002E', 'for': 'tract:*',
                                  'in': 'state:24 county:027', 'key': key}, timeout=60).json()
    t = pd.DataFrame(j[1:], columns=j[0])
    for c in ['B25120_001E', 'B25120_002E', 'B25003_002E']:
        t[c] = pd.to_numeric(t[c], errors='coerce')
    t['tract'] = t['state'] + t['county'] + t['tract']
    t['owner_mean_income'] = t['B25120_002E'] / t['B25003_002E']
    return t[['tract', 'B25120_001E', 'B25120_002E', 'owner_mean_income']]


OWNER_BRACKETS = [(0, 5e3), (5e3, 1e4), (1e4, 1.5e4), (1.5e4, 2e4), (2e4, 2.5e4), (2.5e4, 3.5e4),
                  (3.5e4, 5e4), (5e4, 7.5e4), (7.5e4, 1e5), (1e5, 1.5e5), (1.5e5, None)]


def owner_income_draws(df: pd.DataFrame, inc: pd.DataFrame, pairing: str, seed: int = 0) -> pd.Series:
    """
    Give each owner-occupied home a household income from its tract's owner income distribution
    (ACS B25118), rather than the tract mean. The roll does not link parcels to incomes, so two
    pairings bracket the truth: 'rank' pairs the priciest land with the highest incomes within each
    tract (perfect positive correlation), 'random' pairs them independently. The open top bracket
    takes the value that makes the bracket mean equal the tract's B25120/B25003 owner mean.
    """
    key = os.getenv('CENSUS_API_KEY')
    cols = [f'B25118_{i:03d}E' for i in range(3, 14)]
    j = requests.get(f'https://api.census.gov/data/{ACS_YEAR}/acs/acs5',
                     params={'get': ','.join(cols), 'for': 'tract:*', 'in': 'state:24 county:027',
                             'key': key}, timeout=60).json()
    b = pd.DataFrame(j[1:], columns=j[0])
    b['tract'] = b['state'] + b['county'] + b['tract']
    b = b.set_index('tract')[cols].apply(pd.to_numeric).clip(lower=0)
    mids = np.array([(lo + hi) / 2 for lo, hi in OWNER_BRACKETS[:-1]])
    means = inc.set_index('tract')['owner_mean_income']
    rng = np.random.default_rng(seed)
    out = pd.Series(np.nan, index=df.index)
    h = df['owner_home']
    for tract, idx in df[h].groupby('tract').groups.items():
        if tract not in b.index or b.loc[tract].sum() == 0:
            continue
        counts = b.loc[tract].to_numpy(dtype=float)
        n_top = counts[-1]
        lower_sum = (counts[:-1] * mids).sum()
        top_mean = max((means[tract] * counts.sum() - lower_sum) / n_top, 1.5e5) if n_top else 1.5e5
        values = np.append(mids, top_mean)
        probs = counts / counts.sum()
        n = len(idx)
        # Quantile draws from the bracket distribution, each bracket spread uniformly
        u = (np.arange(n) + 0.5) / n
        cum = np.cumsum(probs)
        k = np.searchsorted(cum, u)
        lo = np.array([lo for lo, _ in OWNER_BRACKETS])[k]
        hi = np.array([hi if hi else 2 * top_mean - 1.5e5 for _, hi in OWNER_BRACKETS])[k]
        within = (u - np.append(0, cum)[k]) / np.where(probs[k] > 0, probs[k], 1)
        draws = np.where(k == len(values) - 1, lo + within * (hi - lo), lo + within * (hi - lo))
        order = df.loc[idx, 'market_value'].rank(method='first').to_numpy().astype(int) - 1
        if pairing == 'rank':
            out.loc[idx] = draws[order]
        else:
            out.loc[idx] = rng.permutation(draws)
    return out


def allocate(df: pd.DataFrame, inc: pd.DataFrame) -> Dict[str, pd.Series]:
    """Each parcel's share (summing to <= 1) of each abolished tax."""
    county_income = inc['B25120_001E'].sum()
    owner_inc = df['tract'].map(inc.set_index('tract')['owner_mean_income'])
    owner_inc = owner_inc.fillna(inc['B25120_002E'].sum() / df['owner_home'].sum())
    income_share = (owner_inc / county_income).where(df['owner_home'], 0.0)
    zero = pd.Series(0.0, index=df.index)
    bounds = {}
    for pairing in ('rank', 'random'):
        draw = owner_income_draws(df, inc, pairing).fillna(owner_inc)
        bounds[f'income_tax_{pairing}_paired'] = (draw / county_income).where(df['owner_home'], 0.0)
    return {
        'property_split_4to1': None,   # handled from the export's own new_tax
        'fire_tax': df['billed_base'] / df['billed_base'].sum(),
        'transfer_recordation': df['market_value'] / df['market_value'].sum(),
        'income_tax': income_share,
        **bounds,
        'admissions_amusement': income_share,
        'hotel_tax': zero,
        'surcharge_excise': zero,
    }


def summarize(df: pd.DataFrame, delta: pd.Series, removed_share_owner: float, land_share_owner: float,
              name: str, revenue: float) -> dict:
    h = df['owner_home']
    d = delta[h]
    q = pd.qcut(df.loc[h, 'median_income'], 5, labels=['Q1', 'Q2', 'Q3', 'Q4', 'Q5'])
    by_q = d.groupby(q, observed=True).median()
    return {
        'scenario': name,
        'revenue_usd': revenue,
        'owner_homes': int(h.sum()),
        'pct_owner_homes_win': round(100 * (d < 0).mean(), 1),
        'median_owner_home_change_usd': round(d.median(), 0),
        'owner_share_of_removed_tax_pct': round(100 * removed_share_owner, 1),
        'owner_share_of_land_levy_pct': round(100 * land_share_owner, 1),
        'net_to_owner_homes_usd_m': round((land_share_owner - removed_share_owner) * revenue / 1e6, 1),
        **{f'median_change_{k}_usd': round(v, 0) for k, v in by_q.items()},
    }


def main() -> None:
    df = load_parcels()
    inc = load_owner_income()
    shares = allocate(df, inc)
    land_share = df['taxable_land_value'] / df['taxable_land_value'].sum()
    land_share_owner = land_share[df['owner_home']].sum()

    rows = []
    for tax, share in shares.items():
        revenue = float(REVENUES[tax.replace('_rank_paired', '').replace('_random_paired', '')])
        if tax == 'property_split_4to1':
            delta = df['new_tax'] - df['current_tax']
            removed_owner = df.loc[df['owner_home'], 'current_tax'].sum() / df['current_tax'].sum()
            new_owner = df.loc[df['owner_home'], 'new_tax'].sum() / df['new_tax'].sum()
            rows.append(summarize(df, delta, removed_owner, new_owner, tax, revenue))
            continue
        delta = revenue * (land_share - share)
        rows.append(summarize(df, delta, share[df['owner_home']].sum(), land_share_owner, tax, revenue))

    out = pd.DataFrame(rows)
    # The land base the levy falls on, by who holds it
    holders = (df.assign(group=np.where(df['owner_home'], 'Owner-occupied homes',
                                        np.where(df['property_category'].isin(HOME_CATS), 'Rented homes',
                                                 df['property_category'])))
                 .groupby('group')['taxable_land_value'].sum().div(df['taxable_land_value'].sum()).mul(100)
                 .round(1).sort_values(ascending=False))
    renter_income_share = inc['B25120_001E'].sum() - inc['B25120_002E'].sum()
    print(f"Land-only levy per $10M swapped: {1e7 * 1000 / df['taxable_land_value'].sum():.3f} mills")
    print(f"Renter households' share of county household income: "
          f"{100 * renter_income_share / inc['B25120_001E'].sum():.1f}%")
    print("\nWho holds the taxable land base (%):")
    print(holders.to_string())
    print()
    print(out.T.to_string())
    out.to_csv(OUT_DIR / 'swap_scenarios.csv', index=False)
    holders.rename('pct_of_taxable_land').to_csv(OUT_DIR / 'land_base_holders.csv')


if __name__ == '__main__':
    main()
