"""
Philadelphia: the joint distribution of age and housing tenure, from ACS PUMS microdata.

Answers two questions the published ACS tables cannot answer on their own:
- How many older Philadelphians rent, counted as people rather than as householders?
- How common is the "cash poor, house rich" older owner: low income, a valuable home, and a
  property tax bill that is large relative to income?

Source: 2024 ACS 1-year PUMS, Census API, restricted to the 11 PUMAs named "Philadelphia City"
(listed in PHILLY_PUMAS; the county-total guard below confirms they tile the county). Every
estimate carries a 90% margin of error from the 80 successive-difference replicate weights:
SE = sqrt(4/80 * sum_r (X_r - X)^2), MOE = 1.645 * SE.

Definitions:
- Household = the reference person (RELSHIPP 20) of a housing unit (TYPEHUGQ 1). Its age is
  the householder's age, the convention of the published table B25007.
- Owner = TEN 1 (mortgage) or 2 (free and clear). Renter = TEN 3 (rented) or 4 (occupied
  without payment of rent), again as in B25007.
- Income is HINCP scaled by ADJINC to 2024 dollars. Property value (VALP) and real-estate
  tax (TAXAMT) are respondent-reported; TAXAMT is what the household says it pays, so it is
  net of any relief (Homestead, Senior Freeze, LOOP) the respondent reflects in the amount.
- "Cash poor" = household income below 200% of the poverty line (POVPIP < 200).
  "House rich" = home value at or above the median value of all owner-occupied Philadelphia
  homes (computed here, weighted). Both thresholds are constants below and are printed in the
  output, so a different cut is a one-line change.

The survey measures home value, not land value, so nothing here says whose bill rises under
a land-value tax; that depends on the parcel's land share, which only the parcel roll has.

Run from the repo root:
    C:/Users/druss/miniconda3/python.exe analysis/age_tenure/pums_age_tenure.py
Output: analysis/age_tenure/results/philadelphia_age_tenure_2024.md (generated; do not edit).
"""

import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / 'data'
OUT_DIR = HERE / 'results'
DATA_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)
load_dotenv(REPO_ROOT / '.env')

YEAR = 2024
STATE = '42'
COUNTY = '101'
# The 11 PUMAs whose 2024 ACS name begins "Philadelphia City" (queried from the ACS API,
# for=public use microdata area:*&in=state:42). check_against_published() asserts they sum
# to the county's published household and population totals.
PHILLY_PUMAS = ['03216', '03221', '03222', '03223', '03224', '03225',
                '03227', '03228', '03229', '03230', '03231']
CACHE = DATA_DIR / f'pums_{YEAR}_philadelphia.parquet'

CASH_POOR_POVPIP = 200          # household income below 200% of poverty
N_REP = 80
Z90 = 1.645

CORE_VARS = ['SERIALNO', 'SPORDER', 'PUMA', 'AGEP', 'RELSHIPP', 'TEN', 'TYPEHUGQ',
             'HHLDRAGEP', 'HINCP', 'ADJINC', 'VALP', 'TAXAMT', 'GRPIP', 'OCPIP', 'POVPIP',
             'BLD', 'NP', 'WGTP', 'PWGTP']
HREP = [f'WGTP{i}' for i in range(1, N_REP + 1)]
PREP = [f'PWGTP{i}' for i in range(1, N_REP + 1)]


def _get(url: str, params: Dict[str, str], tries: int = 12) -> list:
    """GET a Census API JSON array, retrying the API's intermittent 503s."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=300)
            if r.ok:
                return r.json()
            last = f'{r.status_code} {r.text[:120]}'
        except requests.RequestException as e:
            last = str(e)
        time.sleep(min(5 * (i + 1), 30))
    raise RuntimeError(f'Census API failed after {tries} tries: {url} ({last})')


def fetch_pums_block(variables: Sequence[str]) -> pd.DataFrame:
    """
    Fetch one block of PUMS person records for the Philadelphia PUMAs.

    Parameters
    ----------
    variables : Sequence[str]
        PUMS variable names (the API allows 50 per call); SERIALNO and SPORDER are added.

    Returns
    -------
    pd.DataFrame
        One row per person record, keyed by SERIALNO + SPORDER.
    """
    get = list(dict.fromkeys(['SERIALNO', 'SPORDER', *variables]))
    rows = _get(f'https://api.census.gov/data/{YEAR}/acs/acs1/pums', {
        'get': ','.join(get),
        'for': 'public use microdata area:' + ','.join(PHILLY_PUMAS),
        'in': f'state:{STATE}',
        'key': os.getenv('CENSUS_API_KEY', ''),
    })
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df = df.loc[:, ~df.columns.duplicated()]
    return df.drop(columns=['state', 'public use microdata area'], errors='ignore')


def load_pums(refresh: bool = False) -> pd.DataFrame:
    """
    Load the Philadelphia PUMS person file (core variables + both replicate-weight sets).

    Parameters
    ----------
    refresh : bool
        Re-fetch from the API even when the parquet cache exists.

    Returns
    -------
    pd.DataFrame
        Numeric person-level frame with derived columns (tenure, age bands, income).
    """
    if CACHE.exists() and not refresh:
        df = pd.read_parquet(CACHE)
    else:
        blocks = [fetch_pums_block(CORE_VARS)]
        for reps in (HREP[:40], HREP[40:], PREP[:40], PREP[40:]):
            blocks.append(fetch_pums_block(reps))
        df = blocks[0]
        for b in blocks[1:]:
            df = df.merge(b, on=['SERIALNO', 'SPORDER'], how='inner', validate='one_to_one')
        assert len(df) == len(blocks[0]), 'replicate-weight blocks did not align with core records'
        num = [c for c in df.columns if c not in ('SERIALNO', 'PUMA')]
        df[num] = df[num].apply(pd.to_numeric)
        df.to_parquet(CACHE, index=False)
    return derive(df)


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """Add tenure, living arrangement, age bands and 2024-dollar income."""
    df = df.copy()
    df['owner'] = df['TEN'].isin([1, 2])
    df['renter'] = df['TEN'].isin([3, 4])
    df['householder'] = (df['RELSHIPP'] == 20) & (df['TYPEHUGQ'] == 1)
    df['arrangement'] = np.select(
        [df['owner'], df['renter'], df['TYPEHUGQ'] == 2, df['TYPEHUGQ'] == 3],
        ['Owner household', 'Renter household', 'Institutional group quarters',
         'Non-institutional group quarters'], default='Other')
    # The PUMS CSV stores ADJINC with 6 implied decimals (1015250); the API returns it
    # already scaled (1.01525). Normalize either form, then insist on a plausible factor.
    adj = df['ADJINC'].where(df['ADJINC'] < 100, df['ADJINC'] / 1e6)
    assert adj.between(0.9, 1.2).all(), f'ADJINC out of range: {adj.describe()}'
    df['income'] = df['HINCP'] * adj
    df['person_age'] = age_band(df['AGEP'])
    df['hh_age'] = age_band(df['HHLDRAGEP'].where(df['HHLDRAGEP'] >= 0), adult=True)
    df['older_hh'] = df['HHLDRAGEP'] >= 65
    df['bld_group'] = df['BLD'].map({
        1: 'Mobile home / other', 10: 'Mobile home / other', 2: 'Detached house',
        3: 'Rowhouse / twin (attached)', 4: '2-4 units', 5: '2-4 units',
        6: '5-19 units', 7: '5-19 units', 8: '20+ units', 9: '20+ units'})
    return df


def age_band(age: pd.Series, adult: bool = False) -> pd.Series:
    """Band ages to the groups used throughout (householders start at 15, as in B25007)."""
    if adult:
        bins, labels = [14, 34, 64, 74, 84, 200], ['15-34', '35-64', '65-74', '75-84', '85+']
    else:
        bins = [-1, 17, 34, 64, 74, 84, 200]
        labels = ['0-17', '18-34', '35-64', '65-74', '75-84', '85+']
    return pd.cut(age, bins=bins, labels=labels)


def estimate(df: pd.DataFrame, mask: pd.Series, weight: str = 'WGTP') -> Tuple[float, float]:
    """
    Weighted count and its 90% MOE from the replicate weights.

    Parameters
    ----------
    df : pd.DataFrame
        PUMS frame.
    mask : pd.Series
        Boolean selection of records to count.
    weight : str
        'WGTP' for households (select householders), 'PWGTP' for persons.

    Returns
    -------
    Tuple[float, float]
        (estimate, 90% margin of error)
    """
    reps = HREP if weight == 'WGTP' else PREP
    w = df.loc[mask.fillna(False).astype(bool), [weight, *reps]].to_numpy(dtype=float)
    tot = w.sum(axis=0)
    se = np.sqrt(4 / N_REP * ((tot[1:] - tot[0]) ** 2).sum())
    return tot[0], Z90 * se


def share(df: pd.DataFrame, num: pd.Series, den: pd.Series,
          weight: str = 'WGTP') -> Tuple[float, float]:
    """Weighted share num/den (num a subset of den) and its 90% MOE, via replicate weights."""
    reps = HREP if weight == 'WGTP' else PREP
    cols = [weight, *reps]
    n = df.loc[(num & den).fillna(False).astype(bool), cols].to_numpy(dtype=float).sum(axis=0)
    d = df.loc[den.fillna(False).astype(bool), cols].to_numpy(dtype=float).sum(axis=0)
    r = n / d
    se = np.sqrt(4 / N_REP * ((r[1:] - r[0]) ** 2).sum())
    return r[0], Z90 * se


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    """Weighted median (point estimate only)."""
    order = np.argsort(values.to_numpy())
    v, w = values.to_numpy()[order], weights.to_numpy(dtype=float)[order]
    return float(v[np.searchsorted(np.cumsum(w), w.sum() / 2)])


def fmt_count(est: float, moe: float) -> str:
    return f'{round(est, -2):,.0f} ± {round(moe, -2):,.0f}'


def fmt_share(est: float, moe: float) -> str:
    return f'{100 * est:.0f}% ± {100 * moe:.0f}'


def md_table(rows: List[List[str]], header: List[str]) -> str:
    out = ['| ' + ' | '.join(header) + ' |', '|' + '|'.join(['---'] * len(header)) + '|']
    out += ['| ' + ' | '.join(r) + ' |' for r in rows]
    return '\n'.join(out)


def crosstab(df: pd.DataFrame, base: pd.Series, row: pd.Series, row_levels: Sequence[str],
             col: pd.Series, col_levels: Sequence[str], weight: str = 'WGTP',
             n_mask: Optional[pd.Series] = None) -> str:
    """Markdown table of counts ± MOE for row x col within `base`, with totals and sample n."""
    rows = []
    for r in row_levels:
        cells = [fmt_count(*estimate(df, base & (row == r) & (col == c), weight))
                 for c in col_levels]
        tot_mask = base & (row == r) & col.isin(col_levels)
        cells.append(fmt_count(*estimate(df, tot_mask, weight)))
        cells.append(f'{int(tot_mask.fillna(False).sum()):,}')
        rows.append([r, *cells])
    all_mask = base & row.isin(row_levels) & col.isin(col_levels)
    rows.append(['**All**', *[fmt_count(*estimate(df, all_mask & (col == c), weight))
                              for c in col_levels],
                 fmt_count(*estimate(df, all_mask, weight)),
                 f'{int(all_mask.fillna(False).sum()):,}'])
    return md_table(rows, ['', *col_levels, 'Total', 'Sample n'])


def fetch_published() -> Dict[str, float]:
    """Published county estimates and MOEs the PUMS extract must reproduce (B25007, B01003)."""
    rows = _get(f'https://api.census.gov/data/{YEAR}/acs/acs1', {
        'get': 'group(B25007),B01003_001E', 'for': f'county:{COUNTY}', 'in': f'state:{STATE}',
        'key': os.getenv('CENSUS_API_KEY', '')})
    d = dict(zip(rows[0], rows[1]))
    return {k: float(v) for k, v in d.items() if k[-1:] in ('E', 'M') and k[:1] == 'B'}


def check_against_published(df: pd.DataFrame, pub: Dict[str, float]) -> str:
    """
    Assert the PUMS extract reproduces the published county totals, and tabulate the
    age x tenure cells of B25007 side by side.
    """
    hh = df['householder']
    hh_total, _ = estimate(df, hh)
    pop_total, _ = estimate(df, pd.Series(True, index=df.index), 'PWGTP')
    assert abs(hh_total / pub['B25007_001E'] - 1) < 0.02, \
        f'PUMS households {hh_total:,.0f} vs published {pub["B25007_001E"]:,.0f}: PUMA list wrong?'
    assert abs(pop_total / pub['B01003_001E'] - 1) < 0.02, \
        f'PUMS persons {pop_total:,.0f} vs published {pub["B01003_001E"]:,.0f}: PUMA list wrong?'

    bands = [('15-24', 15, 24), ('25-34', 25, 34), ('35-44', 35, 44), ('45-54', 45, 54),
             ('55-59', 55, 59), ('60-64', 60, 64), ('65-74', 65, 74), ('75-84', 75, 84),
             ('85+', 85, 200)]
    rows = []
    for tenure, flag, first in (('Owner', 'owner', 3), ('Renter', 'renter', 13)):
        for i, (lab, lo, hi) in enumerate(bands):
            est, moe = estimate(df, hh & df[flag] & df['HHLDRAGEP'].between(lo, hi))
            published = pub[f'B25007_{first + i:03d}E']
            rows.append([tenure, lab, fmt_count(published, pub[f'B25007_{first + i:03d}M']),
                         fmt_count(est, moe),
                         f'{100 * (est / published - 1):+.1f}%'])
    # PUMS is a subsample of the full ACS sample with its own weighting, so a cell differs
    # from the published figure by sampling noise; the 65+ aggregates must agree within the
    # two estimates' combined 90% MOE (published MOE of a sum: root sum of squares).
    for label, flag, cells in (('older owners', 'owner', (9, 10, 11)),
                               ('older renters', 'renter', (19, 20, 21))):
        est, moe = estimate(df, hh & df[flag] & df['older_hh'])
        published = sum(pub[f'B25007_{i:03d}E'] for i in cells)
        pub_moe = np.sqrt(sum(pub[f'B25007_{i:03d}M'] ** 2 for i in cells))
        assert abs(est - published) <= np.hypot(moe, pub_moe),             f'PUMS {label} {est:,.0f} ± {moe:,.0f} vs B25007 {published:,.0f} ± {pub_moe:,.0f}'
    head = (f'PUMS households {hh_total:,.0f} vs B25007 total {pub["B25007_001E"]:,.0f}; '
            f'PUMS persons {pop_total:,.0f} vs B01003 {pub["B01003_001E"]:,.0f}.\n\n')
    return head + md_table(rows, ['Tenure', 'Householder age', 'Published (B25007)',
                                  'PUMS estimate', 'Difference'])


def main() -> None:
    df = load_pums()
    pub = fetch_published()
    validation = check_against_published(df, pub)

    hh = df['householder']
    everyone = pd.Series(True, index=df.index)
    older_owner = hh & df['owner'] & df['older_hh']
    older_renter = hh & df['renter'] & df['older_hh']
    young_owner = hh & df['owner'] & (df['HHLDRAGEP'] < 65)
    older_person = df['AGEP'] >= 65
    sec: List[str] = []

    # Step 1: persons by age and living arrangement
    arrangements = ['Owner household', 'Renter household', 'Institutional group quarters',
                    'Non-institutional group quarters']
    sec.append('## 1. People by age and where they live\n\nPersons, not householders; group '
               'quarters are shown separately (institutional GQ is mostly nursing homes for '
               'older people).\n\n' + crosstab(
                   df, everyone, df['person_age'], ['0-17', '18-34', '35-64', '65-74', '75-84', '85+'],
                   df['arrangement'], arrangements, 'PWGTP'))
    rent_share = share(df, df['renter'], older_person & (df['owner'] | df['renter']), 'PWGTP')
    sec.append(f'Share of people 65+ living in households who live in a renter household: '
               f'{fmt_share(*rent_share)}.')

    # Step 2: older people by their relationship to the household's head
    rel = pd.Series(np.select(
        [df['RELSHIPP'] == 20, df['RELSHIPP'].isin([21, 22, 23, 24]), df['RELSHIPP'].isin([29, 31])],
        ['Householder', 'Spouse / partner of householder', 'Parent / parent-in-law of householder'],
        default='Other relative or non-relative'), index=df.index)
    rel_levels = ['Householder', 'Spouse / partner of householder',
                  'Parent / parent-in-law of householder', 'Other relative or non-relative']
    ten = pd.Series(np.where(df['owner'], 'Owner household',
                             np.where(df['renter'], 'Renter household', 'GQ')), index=df.index)
    sec.append('## 2. People 65+ by relationship to the householder\n\nThe published tables '
               'count an older parent living in an adult child\'s home under the child\'s age; '
               'this table counts them as themselves.\n\n' + crosstab(
                   df, older_person, rel, rel_levels, ten, ['Owner household', 'Renter household'],
                   'PWGTP'))

    # Step 3: households by householder age and tenure
    ten_hh = pd.Series(np.where(df['owner'], 'Owner', np.where(df['renter'], 'Renter', '')),
                       index=df.index)
    sec.append('## 3. Households by householder age and tenure\n\n' + crosstab(
        df, hh, df['hh_age'], ['15-34', '35-64', '65-74', '75-84', '85+'],
        ten_hh, ['Owner', 'Renter']))

    # Step 4: older owners, income x home value
    owner_value = df.loc[hh & df['owner'], 'VALP']
    median_value = weighted_median(owner_value, df.loc[hh & df['owner'], 'WGTP'])
    inc_band = pd.cut(df['income'], [-np.inf, 25_000, 50_000, 75_000, np.inf],
                      labels=['Under $25k', '$25k-50k', '$50k-75k', '$75k+'], right=False)
    val_band = pd.cut(df['VALP'], [0, 150_000, 250_000, 400_000, np.inf],
                      labels=['Under $150k', '$150k-250k', '$250k-400k', '$400k+'], right=False)
    sec.append('## 4. Older-owner households (householder 65+): income by home value\n\n'
               'Household income in 2024 dollars; home value as reported by the respondent.\n\n'
               + crosstab(df, older_owner, inc_band.astype(str),
                          ['Under $25k', '$25k-50k', '$50k-75k', '$75k+'],
                          val_band.astype(str), ['Under $150k', '$150k-250k', '$250k-400k', '$400k+']))

    # Step 5: cash poor, house rich
    cash_poor = df['POVPIP'].between(0, CASH_POOR_POVPIP - 1)
    house_rich = df['VALP'] >= median_value
    rows = []
    for label, base in (('Householder 65+', older_owner), ('Householder under 65', young_owner)):
        rows.append([label,
                     fmt_count(*estimate(df, base & cash_poor & house_rich)),
                     fmt_share(*share(df, cash_poor & house_rich, base)),
                     fmt_share(*share(df, cash_poor, base)),
                     fmt_share(*share(df, df['TEN'] == 2, base))])
    sec.append(f'## 5. "Cash poor, house rich" owners\n\nCash poor = household income below '
               f'{CASH_POOR_POVPIP}% of poverty. House rich = home value at or above the '
               f'median owner-occupied value in Philadelphia, ${median_value:,.0f}.\n\n'
               + md_table(rows, ['Owner households', 'Cash poor and house rich', 'Share of group',
                                 'Share cash poor (any value)', 'Share owning free and clear']))

    # Step 6: property tax relative to income
    tax_ok = df['TAXAMT'] >= 0
    burden = df['TAXAMT'] / df['income'].where(df['income'] > 0)
    burden_band = pd.Series(np.select(
        [df['income'] <= 0, burden < 0.02, burden < 0.04, burden < 0.06, burden < 0.10],
        ['No or negative income', 'Under 2%', '2-4%', '4-6%', '6-10%'], default='10% or more'),
        index=df.index).where(tax_ok)
    levels = ['Under 2%', '2-4%', '4-6%', '6-10%', '10% or more', 'No or negative income']
    rows = []
    for lev in levels:
        rows.append([lev] + [fmt_share(*share(df, burden_band == lev, base & tax_ok))
                             for base in (older_owner, young_owner)])
    eff = df['TAXAMT'] / df['VALP'].where(df['VALP'] > 0)
    m_older = weighted_median(eff[older_owner & tax_ok & eff.notna()],
                              df.loc[older_owner & tax_ok & eff.notna(), 'WGTP'])
    m_young = weighted_median(eff[young_owner & tax_ok & eff.notna()],
                              df.loc[young_owner & tax_ok & eff.notna(), 'WGTP'])
    p10, p90 = eff[hh & df['owner'] & tax_ok].quantile([0.1, 0.9])
    sec.append('## 6. Reported property tax as a share of household income\n\n'
               'Share of each owner group; TAXAMT is the respondent\'s reported annual real-estate '
               'tax, so it reflects whatever relief the household receives.\n\n'
               + md_table(rows, ['Tax / income', 'Householder 65+', 'Householder under 65'])
               + f'\n\nMedian reported tax as a share of reported value: {100 * m_older:.2f}% '
                 f'(65+), {100 * m_young:.2f}% (under 65). Both inputs are self-reported and '
                 f'TAXAMT is published as bracket midpoints, so a single household\'s ratio is '
                 f'noisy; among sampled owners (unweighted) the 10th-90th percentile range of tax/value is '
                 f'{100 * p10:.2f}%-{100 * p90:.2f}%.')
    heavy = (burden >= 0.06) | (df['income'] <= 0)
    sec.append('Older-owner households paying 6% or more of income in property tax (or with no '
               f'income): {fmt_count(*estimate(df, older_owner & tax_ok & heavy))}.')

    # Step 7: older renters
    rent_band = pd.Series(np.select(
        [df['GRPIP'].between(1, 29), df['GRPIP'].between(30, 49), df['GRPIP'] >= 50],
        ['Under 30%', '30-49%', '50% or more'], default='Not computed'), index=df.index)
    rows = []
    for lev in ['Under 30%', '30-49%', '50% or more', 'Not computed']:
        rows.append([lev, fmt_count(*estimate(df, older_renter & (rent_band == lev))),
                     fmt_share(*share(df, rent_band == lev, older_renter))])
    sec.append('## 7. Older-renter households (householder 65+)\n\nGross rent as a share of '
               'household income. "Not computed" covers no-cash-rent and zero-income '
               'households.\n\n' + md_table(rows, ['Rent / income', 'Households', 'Share']))
    sec.append(f'Share of older-renter households below {CASH_POOR_POVPIP}% of poverty: '
               f'{fmt_share(*share(df, cash_poor, older_renter))} (older owners: '
               f'{fmt_share(*share(df, cash_poor, older_owner))}). People 65+ living in renter '
               f'households: {fmt_count(*estimate(df, older_person & df["renter"], "PWGTP"))}.')

    # Step 8: building type, which bears on land share
    blds = ['Detached house', 'Rowhouse / twin (attached)', '2-4 units', '5-19 units', '20+ units',
            'Mobile home / other']
    rows = []
    for b in blds:
        rows.append([b] + [fmt_share(*share(df, df['bld_group'] == b, base))
                           for base in (older_owner, older_renter)])
    sec.append('## 8. Building type of older households\n\nA household\'s change under a land-value '
               'tax depends on its parcel\'s land share, which the survey does not measure. '
               'Building type is the closest survey proxy: units in large buildings sit on '
               'little land per household.\n\n'
               + md_table(rows, ['Units in structure', 'Older owners', 'Older renters']))

    n_hh = int(hh.sum())
    doc = [f'# Philadelphia: age and tenure, {YEAR} ACS 1-year PUMS',
           f'<!-- Generated by analysis/age_tenure/pums_age_tenure.py. Do not edit by hand. -->',
           f'Source: Census Bureau {YEAR} ACS 1-year PUMS, the {len(PHILLY_PUMAS)} Philadelphia '
           f'PUMAs ({n_hh:,} sampled households, {len(df):,} sampled persons). Counts are weighted '
           f'and rounded to the nearest 100; ± is the 90% margin of error from the 80 replicate '
           f'weights. "Older" means 65 or over. Method and definitions: the script\'s docstring.',
           *sec,
           '## Check against the published table\n\nThe extract must reproduce B25007 '
           '(households by tenure and householder age) and B01003 (population) for Philadelphia '
           'County; the script asserts the totals within 2% and the 65+ owner and renter counts '
           'within the two estimates\' combined margin of error.\n\n' + validation]
    out = OUT_DIR / f'philadelphia_age_tenure_{YEAR}.md'
    out.write_text('\n\n'.join(doc) + '\n', encoding='utf-8')
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
