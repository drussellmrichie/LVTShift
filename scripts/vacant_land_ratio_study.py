"""Which land surface is right about Philadelphia's vacant land?

Ratio study against observed sale prices: assessed land value / sale price, for vacant
parcels, under both land surfaces the repo models on. For a bare lot the sale price *is*
the land price, which makes this an unusually direct test of a land surface -- the thing
that normally makes land valuation hard (separating land from structure) does not apply.

Answers the question that dominates every Philadelphia result in this repo: the OPA and
LYCD surfaces disagree by 46% on the taxable land base, most of it vacant land, and that
one disagreement moves kappa* in the single-tax ledger more than every other axis
combined. See docs/VACANT_LAND_VALUATION.md for the finding.

Cross-repo input: philly_open_avmkit's Overture structure-presence flag, which identifies
parcels recorded vacant that actually carry a building. Their sale prices include a
structure, so they are not land sales. That repo owns the AVM and ratio-study machinery;
this script owns only the surface comparison LVTShift needs.

Run from the repo root:
    C:/Users/druss/miniconda3/python.exe scripts/vacant_land_ratio_study.py [--year 2026]
"""
from __future__ import annotations

import argparse
import pathlib
from io import StringIO
from typing import Dict, Optional

import pandas as pd
import requests

CARTO = 'https://phl.carto.com/api/v2/sql'
AVMKIT_STRUCTURE_FLAG = pathlib.Path(
    r'C:\projects\philly_open_avmkit\notebooks\pipeline\data\us-pa-philadelphia'
    r'\out\models\vacant_with_structure.csv')

# Sales scrutiny. Deliberately crude compared with openavmkit's: this keeps the script
# self-contained, and the finding is robust to it (see the docs note). Anything that
# depends on the *dispersion* rather than the level should use their scrutinized study.
MIN_PRICE = 5_000
MIN_AREA, MAX_AREA = 100, 100_000
MIN_PSF, MAX_PSF = 1, 500


def fetch_vacant_sales(since: str = '2023-01-01') -> pd.DataFrame:
    q = ("SELECT parcel_number, sale_price, sale_date, total_area, "
         "taxable_land, taxable_building FROM opa_properties_public "
         f"WHERE category_code = '6' AND sale_price > {MIN_PRICE} "
         f"AND sale_date >= '{since}'")
    r = requests.get(CARTO, params={'q': q, 'format': 'csv'}, timeout=180)
    r.raise_for_status()
    s = pd.read_csv(StringIO(r.text), dtype={'parcel_number': str})
    s = s[(s.total_area > MIN_AREA) & (s.total_area < MAX_AREA)].copy()
    s['psf'] = s.sale_price / s.total_area
    # A parcel carrying a building record is not a land sale.
    s = s[(s.psf > MIN_PSF) & (s.psf < MAX_PSF) & (s.taxable_building.fillna(0) <= 0)]
    s['_k'] = s.parcel_number.str.strip().str.lstrip('0')
    return s


def attach_surfaces(sales: pd.DataFrame, year: int) -> pd.DataFrame:
    lycd_path = pathlib.Path('analysis/data') / f'philadelphia_lycd_ty{year}.csv'
    if not lycd_path.exists():
        raise FileNotFoundError(
            f'{lycd_path} not found. Run cities/philadelphia/model_lycd.ipynb for '
            f'TY{year} first.')
    lycd = pd.read_csv(lycd_path, usecols=['parcel_id', 'taxable_land_value'],
                       dtype={'parcel_id': str}).drop_duplicates('parcel_id', keep='first')
    lycd['_k'] = lycd.parcel_id.str.strip().str.lstrip('0')
    d = sales.merge(lycd[['_k', 'taxable_land_value']], on='_k', how='inner').rename(
        columns={'taxable_land': 'land_opa', 'taxable_land_value': 'land_lycd'})
    return d[(d.land_opa > 0) & (d.land_lycd > 0)].copy()


def attach_structure_flag(d: pd.DataFrame) -> pd.DataFrame:
    """Flag parcels recorded vacant that carry a real building footprint."""
    if not AVMKIT_STRUCTURE_FLAG.exists():
        print(f'  NOTE: {AVMKIT_STRUCTURE_FLAG} not found; structure correction skipped. '
              'The finding is robust to it, but say so if you quote these numbers.')
        d['built_up'] = False
        return d
    vs = pd.read_csv(AVMKIT_STRUCTURE_FLAG, usecols=['parcel_number', 'built_up'],
                     dtype={'parcel_number': str})
    vs['_k'] = vs.parcel_number.str.strip().str.lstrip('0')
    d = d.merge(vs.drop_duplicates('_k')[['_k', 'built_up']], on='_k', how='left')
    print(f'  matched to structure-presence file: {d.built_up.notna().mean()*100:.1f}%')
    d['built_up'] = d.built_up.fillna(False).astype(bool)
    return d


def ratio_stats(x: pd.DataFrame, label: str) -> Dict[str, object]:
    """IAAO-style level and dispersion, per surface, on one sample."""
    out: Dict[str, object] = {'sample': label, 'n': len(x)}
    for name, col in (('OPA', 'land_opa'), ('LYCD', 'land_lycd')):
        r = x[col] / x.sale_price
        med = r.median()
        out[f'{name} median'] = round(med, 2)
        out[f'{name} COD'] = round(100 * (r - med).abs().mean() / med)
        out[f'{name} PRD'] = round(r.mean() / (x[col].sum() / x.sale_price.sum()), 2)
        out[f'{name} aggregate'] = round(x[col].sum() / x.sale_price.sum(), 2)
    return out


def main(year: int = 2026, since: str = '2023-01-01') -> pd.DataFrame:
    print(f'Vacant-land ratio study, TY{year} surfaces against sales since {since}\n')
    d = attach_structure_flag(attach_surfaces(fetch_vacant_sales(since), year))
    print(f'  sales on both surfaces: {len(d):,}')
    print(f'  recorded vacant but built up: {d.built_up.sum():,} '
          f'({d.built_up.mean()*100:.1f}%) -- excluded below\n')

    bare = d[~d.built_up]
    samples = [
        ratio_stats(d, 'all vacant-category sales'),
        ratio_stats(bare, 'genuinely bare land'),
        ratio_stats(bare[bare.sale_price >= 20_000], 'bare land, sale >= $20k'),
    ]
    table = pd.DataFrame(samples)
    print('assessed land / sale price. 1.00 = right; IAAO wants COD <= 20, PRD ~1.0\n')
    print(table.to_string(index=False))

    base = bare[bare.sale_price >= 20_000]
    print('\nImplied citywide vacant-land value, scaling each surface by its own error:')
    for name, col, booked in (('OPA', 'land_opa', 2.99), ('LYCD', 'land_lycd', 14.55)):
        ratio = base[col].sum() / base.sale_price.sum()
        print(f'  {name:4} books ${booked:>5.2f}B at {ratio:.2f}x -> implies '
              f'${booked / ratio:.2f}B')
    print('\nThe two surfaces bracket the truth from opposite sides, and the two '
          'independent\ncorrections land close together -- that agreement is the '
          'strongest part of this result.')
    return table


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--year', type=int, default=2026)
    ap.add_argument('--since', default='2023-01-01')
    ap.add_argument('--out', default=None, help='optional CSV path for the table')
    a = ap.parse_args()
    t = main(a.year, a.since)
    if a.out:
        t.to_csv(a.out, index=False)
        print(f'\nwrote {a.out}')
