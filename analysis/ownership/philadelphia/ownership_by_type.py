"""Who owns each Philadelphia property type, and where do they live?

Answers, for every property category the LVT model reports: what share of parcels and of
land value is LLC-owned, how many distinct LLC entities that is, and whether those entities
receive their mail in Philadelphia, the PA suburbs, the NJ/DE metro, or out of state.

Vacant land and surface parking are the headline cut — they are the categories a land value
tax hits hardest, so who owns them determines whether the reform's losers are absentee
capital or constituents. Every category is covered so those two have a baseline.

Two structural decisions worth knowing before reading the output:

  - **Surface parking is carved out of the model's categories.** OPA gives most parking lots
    `category_code = 6`, so they currently sit inside "Vacant Land". The `R*` building-code
    family separates them. A re-carve table reports exactly what moved.
  - **Public agencies are reported separately and excluded from the "private" denominator.**
    The City, Land Bank, Redevelopment Authority, PHA, SEPTA and the Commonwealth are the
    largest vacant-land holders by parcel count; leaving them in the denominator would
    understate every private-ownership share.

Usage:
    python analysis/ownership/philadelphia/ownership_by_type.py --tax-year 2026
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

import owner_lib as ol  # noqa: E402
from lvt.philadelphia import parcel_cache_path  # noqa: E402

RESULTS = HERE / 'results'
FIGS = HERE / 'figs'

# Surface parking, from OPA building codes. '5R' (CONDO PARKING SPACE) is deliberately NOT
# here: those are individual deeded spaces inside garages, not lots, and folding ~4,500 of
# them in would swamp the parcel counts with condo owners.
PARK_COMMERCIAL = 'Surface Parking — commercial'
PARK_NONCOMMERCIAL = 'Surface Parking — non-commercial'
PARK_STRUCTURE = 'Surface Parking — with structure'
PARK_GARAGE = 'Parking Garage (structured)'
PARKING_CATEGORIES = (PARK_COMMERCIAL, PARK_NONCOMMERCIAL, PARK_STRUCTURE, PARK_GARAGE)
VACANT_CATEGORY = 'Vacant Land'
HEADLINE_CATEGORIES = (VACANT_CATEGORY, *PARKING_CATEGORIES)

_PARKING_EXACT = {'RA': PARK_NONCOMMERCIAL, 'RB': PARK_COMMERCIAL, 'RE': PARK_COMMERCIAL}
_PARKING_STRUCTURED_RE = re.compile(r'^R[A-F]\d$')   # RC0, RD6, RE6, RF0, …
# Commercial parking garages ('GAR W/COMM AREA' / 'GAR NO COMM AREA'). Kept separate from the
# surface lots because a garage is a building — a land value tax treats the two very
# differently, and conflating them would blunt the headline. 'V*' (PRIV GAR) is excluded:
# those are detached residential garages, not commercial parking.
_GARAGE_RE = re.compile(r'^O[AB]\d$')
# How many top mailing addresses the brief's mail-drop concentration test reports.
OOS_TOP_N = 10
# 'R30' etc. are ROW B/GAR rowhouses, not parking — only warn about genuinely parking-named
# codes that the mapping missed.
_PARKING_DESC_RE = re.compile(r'PKG|PARKING')


def _strip_key(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lstrip('0')


def load_universe(tax_year: int) -> pd.DataFrame:
    """Join the parcel cache, both model exports, and the OPA sidecars on parcel number."""
    cache = parcel_cache_path(tax_year, REPO / 'cities/philadelphia/data')
    if not cache.exists():
        raise FileNotFoundError(
            f"{cache} not found. Build it with:\n"
            f"  python scripts/build_philadelphia_parcel_cache.py --year {tax_year}")

    parcels = gpd.read_parquet(cache)
    parcels = pd.DataFrame(parcels.drop(columns='geometry'))
    parcels['join_key'] = _strip_key(parcels['parcel_number'])
    print(f"parcel cache:        {len(parcels):,} rows")

    opa = pd.read_csv(REPO / f'analysis/data/philadelphia_ty{tax_year}.csv', low_memory=False)
    lycd = pd.read_csv(REPO / f'analysis/data/philadelphia_lycd_ty{tax_year}.csv', low_memory=False)
    print(f"OPA export:          {len(opa):,} rows")
    print(f"LYCD export:         {len(lycd):,} rows")

    # The four Philadelphia exports share one row order, and ~10 parcel_ids appear twice with
    # genuinely different attributes. Align the two scenarios POSITIONALLY before deduping, so
    # both describe the same physical parcel; deduping each file independently can pair row 1
    # of one scenario with row 2 of the other under the same id.
    if len(opa) != len(lycd) or not (opa['parcel_id'].values == lycd['parcel_id'].values).all():
        raise ValueError("OPA and LYCD exports are not positionally aligned — "
                         "cannot dedupe safely. Re-run both notebooks from the same cache.")

    keep = ['property_category', 'current_tax', 'new_tax', 'tax_change', 'tax_change_pct',
            'taxable_land_value', 'taxable_improvement_value', 'is_fully_exempt']
    merged = opa[['parcel_id'] + keep].copy()
    for c in keep:
        merged[f'lycd_{c}'] = lycd[c].values
    # The LYCD notebooks write property_category as UTF-8 re-encoded through cp1252
    # ('Commercial â€” Exempt'); repair rather than depending on an upstream fix.
    merged['lycd_property_category'] = (
        merged['lycd_property_category'].astype(str)
        .apply(lambda s: s.encode('cp1252', 'ignore').decode('utf-8', 'ignore') or s))

    merged['join_key'] = _strip_key(merged['parcel_id'])
    dup = merged['join_key'].duplicated().sum()
    print(f"duplicate parcel ids dropped (positionally, from both scenarios): {dup}")
    merged = merged.drop_duplicates('join_key')
    parcels = parcels.drop_duplicates('join_key')

    df = parcels.merge(merged, on='join_key', how='inner')

    for name, cols in [('opa_mailing.parquet', None), ('opa_attributes.parquet', None)]:
        side = pd.read_parquet(HERE / name)
        side['join_key'] = _strip_key(side['parcel_number'])
        side = side.drop_duplicates('join_key').drop(columns='parcel_number')
        df = df.merge(side, on='join_key', how='left')

    print(f"joined universe:     {len(df):,} parcels")
    return df


def assign_analysis_category(df: pd.DataFrame) -> pd.DataFrame:
    """Model category, with surface parking carved out of whatever bucket it was hiding in."""
    df['analysis_category'] = df['property_category'].astype(str)
    code = df['building_code'].fillna('').astype(str).str.strip().str.upper()

    park = pd.Series(pd.NA, index=df.index, dtype=object)
    for exact, label in _PARKING_EXACT.items():
        park.loc[code == exact] = label
    park.loc[code.str.match(_PARKING_STRUCTURED_RE) & park.isna()] = PARK_STRUCTURE
    park.loc[code.str.match(_GARAGE_RE) & park.isna()] = PARK_GARAGE

    desc = df['building_code_description'].fillna('').astype(str).str.upper()
    missed = desc.str.contains(_PARKING_DESC_RE) & park.isna() & (code != '5R')
    if missed.any():
        print("  NOTE: parking-named building codes not mapped: "
              f"{sorted(set(zip(code[missed], desc[missed])))}")

    df['is_parking'] = park.notna()
    df['source_category'] = df['analysis_category']
    df.loc[park.notna(), 'analysis_category'] = park[park.notna()]
    return df


def recarve_table(df: pd.DataFrame) -> pd.DataFrame:
    """What moved out of which model category into which parking category."""
    moved = df[df['is_parking']]
    tab = (moved.groupby(['source_category', 'analysis_category'])
           .agg(parcels=('join_key', 'size'),
                land_value=('taxable_land_value', 'sum'),
                market_value=('market_value', 'sum'))
           .reset_index().sort_values('parcels', ascending=False))
    return tab


def classify_owners(df: pd.DataFrame) -> pd.DataFrame:
    df['owner_name'] = ol.owner_name_series(df)
    before = len(df)
    df = df[df['owner_name'] != ''].copy()
    if before != len(df):
        print(f"  dropped {before - len(df):,} parcels with no owner name")

    df['owner_sector'] = ol.classify_sector(df['owner_name'])
    df['legal_form'] = ol.classify_legal_form(df['owner_name'])
    df['name_truncated'] = ol.is_truncated(df['owner_name'])
    # Public and institutional owners are not "LLCs" no matter what their name matches
    # (e.g. 'PHILADELPHIA HOUSING DEVELOPMENT CORP' is a public body, not an investor).
    non_private = df['owner_sector'].isin([ol.SECTOR_PUBLIC, ol.SECTOR_INSTITUTIONAL])
    df.loc[non_private, 'legal_form'] = df.loc[non_private, 'owner_sector']

    geo = ol.parse_owner_geography(df['mailing_city_state'], df['mailing_zip'])
    df = pd.concat([df, geo], axis=1)

    df['mail_key'] = ol.build_mail_key(df['mailing_street'], df['mailing_zip'], df['location'])
    df['self_mailed'] = (
        ol.norm_addr(df['mailing_street']) == ol.norm_addr(df['location'])
    ) | df['mail_key'].str.startswith('SELF ')
    df['has_care_of'] = df['mailing_care_of'].notna() & (df['mailing_care_of'].astype(str) != '')
    df['homestead'] = pd.to_numeric(df['homestead_exemption'], errors='coerce').fillna(0) > 0
    return df


def sector_table(df: pd.DataFrame) -> pd.DataFrame:
    g = (df.groupby(['analysis_category', 'owner_sector'])
         .agg(parcels=('join_key', 'size'),
              land_value=('taxable_land_value', 'sum'),
              market_value=('market_value', 'sum'),
              lot_area_sqft=('total_area', 'sum'),
              current_tax=('current_tax', 'sum'),
              new_tax=('new_tax', 'sum'))
         .reset_index())
    tot = g.groupby('analysis_category')[['parcels', 'land_value']].transform('sum')
    g['parcel_share'] = g['parcels'] / tot['parcels']
    g['land_value_share'] = g['land_value'] / tot['land_value'].replace(0, np.nan)
    g['tax_change'] = g['new_tax'] - g['current_tax']
    g['tax_change_pct'] = g['tax_change'] / g['current_tax'].replace(0, np.nan)
    return g.sort_values(['analysis_category', 'owner_sector'])


def _share_block(sub: pd.DataFrame, prefix: str) -> dict:
    """LLC / +LP / all-business shares of parcels and land value within one frame.

    Also emits an upper bound on the LLC land share. Truncated names lose their legal suffix
    in one direction only — an entity falls *out* of the LLC bucket, never into it — so the
    measured share is biased low. The upper bound reallocates truncated business-sector
    parcels at the LLC rate observed among untruncated business names in the same frame.
    """
    n, lv = len(sub), sub['taxable_land_value'].sum()
    out = {f'{prefix}_parcels': n, f'{prefix}_land_value': lv}
    rings = {
        'llc': [ol.FORM_LLC],
        'llc_lp': [ol.FORM_LLC, ol.FORM_LP],
        'business': list(ol.BUSINESS_FORMS),
    }
    for ring, forms in rings.items():
        m = sub['legal_form'].isin(forms)
        out[f'{prefix}_{ring}_parcel_share'] = m.sum() / n if n else np.nan
        out[f'{prefix}_{ring}_land_share'] = (
            sub.loc[m, 'taxable_land_value'].sum() / lv if lv else np.nan)

    biz = sub[sub['owner_sector'] == ol.SECTOR_BUSINESS]
    clean = biz[~biz['name_truncated']]
    obscured = biz[biz['name_truncated'] & (biz['legal_form'] != ol.FORM_LLC)]
    clean_lv = clean['taxable_land_value'].sum()
    llc_rate = (clean.loc[clean['legal_form'] == ol.FORM_LLC, 'taxable_land_value'].sum()
                / clean_lv) if clean_lv else np.nan
    measured_llc_lv = sub.loc[sub['legal_form'] == ol.FORM_LLC, 'taxable_land_value'].sum()
    out[f'{prefix}_truncated_business_land_value'] = obscured['taxable_land_value'].sum()
    out[f'{prefix}_llc_land_share_upper'] = (
        (measured_llc_lv + llc_rate * obscured['taxable_land_value'].sum()) / lv
        if lv and not np.isnan(llc_rate) else np.nan)
    return out


def llc_share_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cat, sub in df.groupby('analysis_category'):
        priv = sub[sub['owner_sector'] != ol.SECTOR_PUBLIC]
        row = {'analysis_category': cat}
        row.update(_share_block(sub, 'all'))
        row.update(_share_block(priv, 'private'))
        rows.append(row)
    return pd.DataFrame(rows).sort_values('private_llc_land_share', ascending=False)


def llc_geography_table(df: pd.DataFrame) -> pd.DataFrame:
    llc = df[df['legal_form'] == ol.FORM_LLC]
    g = (llc.groupby(['analysis_category', 'owner_geography'])
         .agg(parcels=('join_key', 'size'),
              land_value=('taxable_land_value', 'sum'),
              entities=('entity_label', 'nunique'),
              delaware_parcels=('is_delaware', 'sum'),
              care_of_parcels=('has_care_of', 'sum'))
         .reset_index())
    tot = g.groupby('analysis_category')[['parcels', 'land_value', 'entities']].transform('sum')
    g['parcel_share'] = g['parcels'] / tot['parcels']
    g['land_value_share'] = g['land_value'] / tot['land_value'].replace(0, np.nan)
    g['entity_share'] = g['entities'] / tot['entities']
    return g.sort_values(['analysis_category', 'owner_geography'])


def owner_geography_table(df: pd.DataFrame) -> pd.DataFrame:
    """Where every private owner mails, by property type — not just LLCs.

    The LLC-only cut answers "where are the LLCs", but it cannot say whether LLCs are more
    absentee than the owners around them. This table is the denominator for that comparison:
    it covers all private owners (public agencies excluded) in every category, so an LLC
    out-of-state share can be read against the category's own baseline rather than against
    nothing.
    """
    priv = df[df['owner_sector'] != ol.SECTOR_PUBLIC]
    g = (priv.groupby(['analysis_category', 'owner_geography'])
         .agg(parcels=('join_key', 'size'),
              land_value=('taxable_land_value', 'sum'),
              owners=('entity_label', 'nunique'),
              llc_parcels=('legal_form', lambda s: (s == ol.FORM_LLC).sum()))
         .reset_index())
    tot = g.groupby('analysis_category')[['parcels', 'land_value', 'owners']].transform('sum')
    g['parcel_share'] = g['parcels'] / tot['parcels']
    g['land_value_share'] = g['land_value'] / tot['land_value'].replace(0, np.nan)
    g['owner_share'] = g['owners'] / tot['owners']
    return g.sort_values(['analysis_category', 'owner_geography'])


def entity_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per resolved LLC entity, with a land-value-weighted primary geography."""
    llc = df[df['legal_form'] == ol.FORM_LLC].copy()
    geo_rank = (llc.groupby(['entity_label', 'owner_geography'])['taxable_land_value'].sum()
                .sort_values(ascending=False).reset_index()
                .drop_duplicates('entity_label').set_index('entity_label')['owner_geography'])
    ent = (llc.groupby('entity_label')
           .agg(parcels=('join_key', 'size'),
                constituent_names=('owner_name', 'nunique'),
                land_value=('taxable_land_value', 'sum'),
                market_value=('market_value', 'sum'),
                lot_area_sqft=('total_area', 'sum'),
                current_tax=('current_tax', 'sum'),
                new_tax=('new_tax', 'sum'),
                categories=('analysis_category',
                            lambda s: ' | '.join(pd.Series(s).value_counts().head(3).index)))
           .reset_index())
    ent['primary_geography'] = ent['entity_label'].map(geo_rank)
    ent['tax_change'] = ent['new_tax'] - ent['current_tax']
    return ent.sort_values('land_value', ascending=False)


def _geo_share(tab: pd.DataFrame, bucket: str, category: str | None = None) -> float:
    """Land-value share sitting in one geography bucket, citywide or within a category."""
    sub = tab if category is None else tab[tab['analysis_category'] == category]
    total = sub['land_value'].sum()
    if not total:
        return float('nan')
    return float(sub.loc[sub['owner_geography'] == bucket, 'land_value'].sum() / total)


def mail_hub_table(df: pd.DataFrame, categories: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Out-of-state mailing addresses behind LLC-owned property, across all types.

    The test this answers: is "out-of-state ownership" real, or an artifact of a handful of
    registered-agent offices and PO boxes? An address holding many parcels under many
    different LLC names is a mail drop; one holding a single large parcel under one name is
    a genuine corporate owner.

    Pass `categories` to restrict to a subset; the default spans every property type so the
    mail-drop test is not answered only for vacant land and parking.
    """
    sub = df[(df['legal_form'] == ol.FORM_LLC) &
             (df['owner_geography'] == 'Out-of-state')]
    if categories is not None:
        sub = sub[sub['analysis_category'].isin(categories)]
    tab = (sub.groupby(['mail_key', 'mailing_city_state'])
           .agg(parcels=('join_key', 'size'),
                land_value=('taxable_land_value', 'sum'),
                distinct_names=('owner_name', 'nunique'),
                has_care_of=('has_care_of', 'sum'),
                categories=('analysis_category',
                            lambda s: ' | '.join(pd.Series(s).value_counts().head(2).index)))
           .reset_index().sort_values('land_value', ascending=False))
    total = tab['land_value'].sum()
    tab['land_value_share'] = tab['land_value'] / total if total else np.nan
    return tab


def headline_stats(df: pd.DataFrame, shares: pd.DataFrame, geo: pd.DataFrame,
                   hubs: pd.DataFrame, all_geo: pd.DataFrame,
                   vp_hubs: pd.DataFrame) -> dict:
    """The scalars the written brief quotes, so no number is ever hand-typed into prose."""
    vp = df[df['analysis_category'].isin(HEADLINE_CATEGORIES)]
    vp_priv = vp[vp['owner_sector'] != ol.SECTOR_PUBLIC]
    llc = vp_priv[vp_priv['legal_form'] == ol.FORM_LLC]
    oos = llc[llc['owner_geography'] == 'Out-of-state']
    incity = llc[llc['owner_geography'] == 'In-city (Philadelphia)']

    def cat(name, col):
        r = shares.loc[shares['analysis_category'] == name, col]
        return float(r.iat[0]) if len(r) else float('nan')

    def _top_n_share(tab: pd.DataFrame) -> float:
        tot = tab['land_value'].sum() if len(tab) else 0
        return float(tab['land_value'].head(OOS_TOP_N).sum() / tot) if tot else float('nan')

    hub_top10 = _top_n_share(vp_hubs)
    return {
        'tax_year': 2026,
        'oos_top_n': OOS_TOP_N,
        'truncation_widths': list(ol.TRUNCATION_WIDTHS),
        'total_parcels': int(len(df)),
        'vacant_parking_parcels': int(len(vp)),
        'vacant_parking_private_parcels': int(len(vp_priv)),
        'vacant_parking_public_parcels': int((vp['owner_sector'] == ol.SECTOR_PUBLIC).sum()),
        'vacant_parking_public_parcel_share': float(
            (vp['owner_sector'] == ol.SECTOR_PUBLIC).mean()),
        'vacant_llc_land_share': cat(VACANT_CATEGORY, 'private_llc_land_share'),
        'vacant_llc_land_share_upper': cat(VACANT_CATEGORY, 'private_llc_land_share_upper'),
        'vacant_llc_parcel_share': cat(VACANT_CATEGORY, 'private_llc_parcel_share'),
        'vacant_business_land_share': cat(VACANT_CATEGORY, 'private_business_land_share'),
        'parking_comm_llc_land_share': cat(PARK_COMMERCIAL, 'private_llc_land_share'),
        'parking_noncomm_llc_land_share': cat(PARK_NONCOMMERCIAL, 'private_llc_land_share'),
        'garage_llc_land_share': cat(PARK_GARAGE, 'private_llc_land_share'),
        'sfr_llc_land_share': cat('Single Family Residential', 'private_llc_land_share'),
        'sfr_llc_parcel_share': cat('Single Family Residential', 'private_llc_parcel_share'),
        'industrial_llc_land_share': cat('Industrial', 'private_llc_land_share'),
        'large_mf_llc_land_share': cat('Large Multi-Family (5+ units)', 'private_llc_land_share'),
        'vacant_vs_sfr_ratio': (cat(VACANT_CATEGORY, 'private_llc_land_share')
                                / cat('Single Family Residential', 'private_llc_land_share')),
        'llc_vp_parcels': int(len(llc)),
        'llc_vp_entities': int(llc['entity_label'].nunique()),
        'llc_vp_land_value': float(llc['taxable_land_value'].sum()),
        'llc_vp_tax_change': float((llc['new_tax'] - llc['current_tax']).sum()),
        'oos_parcels': int(len(oos)),
        'oos_entities': int(oos['entity_label'].nunique()),
        'oos_land_value': float(oos['taxable_land_value'].sum()),
        'oos_parcel_share_of_llc': float(len(oos) / len(llc)) if len(llc) else float('nan'),
        'oos_land_share_of_llc': float(
            oos['taxable_land_value'].sum() / llc['taxable_land_value'].sum())
        if llc['taxable_land_value'].sum() else float('nan'),
        'incity_land_share_of_llc': float(
            incity['taxable_land_value'].sum() / llc['taxable_land_value'].sum())
        if llc['taxable_land_value'].sum() else float('nan'),
        'incity_entities': int(incity['entity_label'].nunique()),
        'delaware_parcels': int(oos['is_delaware'].sum()),
        'oos_distinct_addresses': int(len(vp_hubs)),
        'oos_top10_address_land_share': float(hub_top10),
        'oos_max_names_at_one_address': (int(vp_hubs['distinct_names'].max())
                                         if len(vp_hubs) else 0),
        'city_oos_distinct_addresses': int(len(hubs)),
        'city_oos_top10_address_land_share': _top_n_share(hubs),
        'city_oos_max_names_at_one_address': (int(hubs['distinct_names'].max())
                                              if len(hubs) else 0),
        # Citywide baselines, all property types — the denominator the LLC geography
        # numbers should be read against.
        'city_llc_oos_land_share': _geo_share(geo, 'Out-of-state'),
        'city_llc_incity_land_share': _geo_share(geo, 'In-city (Philadelphia)'),
        'city_all_oos_land_share': _geo_share(all_geo, 'Out-of-state'),
        'city_all_incity_land_share': _geo_share(all_geo, 'In-city (Philadelphia)'),
        'sfr_llc_oos_land_share': _geo_share(geo, 'Out-of-state',
                                             'Single Family Residential'),
        'vacant_llc_oos_land_share': _geo_share(geo, 'Out-of-state', VACANT_CATEGORY),
        'commercial_llc_oos_land_share': _geo_share(geo, 'Out-of-state', 'Commercial'),
        'geography_categories_covered': int(all_geo['analysis_category'].nunique()),
    }


def robustness_table(df: pd.DataFrame) -> pd.DataFrame:
    """Headline LLC land-value share under OPA vs LYCD land values."""
    rows = []
    for cat, sub in df.groupby('analysis_category'):
        priv = sub[sub['owner_sector'] != ol.SECTOR_PUBLIC]
        m = priv['legal_form'] == ol.FORM_LLC
        opa_lv, lycd_lv = priv['taxable_land_value'].sum(), priv['lycd_taxable_land_value'].sum()
        rows.append({
            'analysis_category': cat,
            'private_parcels': len(priv),
            'opa_llc_land_share': priv.loc[m, 'taxable_land_value'].sum() / opa_lv if opa_lv else np.nan,
            'lycd_llc_land_share': priv.loc[m, 'lycd_taxable_land_value'].sum() / lycd_lv if lycd_lv else np.nan,
            'opa_land_value': opa_lv,
            'lycd_land_value': lycd_lv,
        })
    out = pd.DataFrame(rows)
    out['abs_diff_pp'] = (out['lycd_llc_land_share'] - out['opa_llc_land_share']).abs() * 100
    return out.sort_values('abs_diff_pp', ascending=False)


def run_checks(df: pd.DataFrame, shares: pd.DataFrame, ent: pd.DataFrame) -> list[str]:
    """Guardrails. Returns a list of failure messages (empty = all passed)."""
    fails = []

    biggest = ent['parcels'].max() if len(ent) else 0
    if biggest > 10_000:
        fails.append(f"entity resolution produced a {biggest:,}-parcel entity (>10,000) — "
                     "the documented signature of individuals merged by shared address")

    bad = shares[(shares['private_llc_land_share'] > shares['private_llc_lp_land_share'] + 1e-9) |
                 (shares['private_llc_lp_land_share'] > shares['private_business_land_share'] + 1e-9)]
    if len(bad):
        fails.append(f"{len(bad)} categories violate LLC <= LLC+LP <= business land share")

    sec = df.groupby('analysis_category')['owner_sector'].value_counts(normalize=True).groupby(
        level=0).sum()
    if not np.allclose(sec.values, 1.0, atol=1e-6):
        fails.append("owner-sector shares do not sum to 1 within every category")

    for col in ['all_llc_land_share', 'private_llc_land_share']:
        if (shares[col].dropna() > 1.0).any() or (shares[col].dropna() < 0).any():
            fails.append(f"{col} outside [0, 1]")

    return fails


def _short_money(x: float) -> str:
    """Compact money for chart annotations: $2.6B, $441M, $9.1M."""
    if pd.isna(x):
        return 'n/a'
    for div, suf in ((1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if abs(x) >= div:
            return f'${x / div:,.1f}{suf}'
    return f'${x:,.0f}'


def make_figures(shares: pd.DataFrame, sectors: pd.DataFrame, geo: pd.DataFrame,
                 df: pd.DataFrame) -> None:
    FIGS.mkdir(exist_ok=True)
    plt.rcParams.update({'figure.dpi': 130, 'axes.grid': True, 'grid.alpha': 0.3})
    MIN_PARCELS = 200
    MIN_LLC_PARCELS = 20

    # 1. Headline — LLC land-value share by category. Fully-exempt categories carry no
    # taxable land value, so their share is undefined rather than zero — drop them instead
    # of drawing an empty bar. Headline categories are always shown even when small.
    d = shares[(shares['private_parcels'] >= MIN_PARCELS) |
               shares['analysis_category'].isin(HEADLINE_CATEGORIES)]
    d = d[d['private_llc_land_share'].notna()].sort_values('private_llc_land_share')
    fig, ax = plt.subplots(figsize=(11, max(4, 0.34 * len(d))))
    colors = ['#e76f51' if c in HEADLINE_CATEGORIES else '#4878cf'
              for c in d['analysis_category']]
    ax.barh(d['analysis_category'], d['private_llc_land_share'], color=colors)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0))
    ax.set_xlabel('LLC share of privately-owned land value')
    ax.set_title('LLC ownership by property type (public agencies excluded)')
    ax.tick_params(axis='y', labelsize=8)
    # A share means little without knowing how much property it is a share OF — a 36% bar
    # over nine parcels should not read like a 32% bar over 28,000.
    for y, (share, n, lv) in enumerate(zip(d['private_llc_land_share'],
                                           d['private_parcels'], d['private_land_value'])):
        ax.text(share + 0.006, y, f'{n:,} parcels · {_short_money(lv)} land',
                va='center', fontsize=7, color='#444')
    ax.set_xlim(0, max(d['private_llc_land_share']) * 1.55)
    fig.tight_layout()
    fig.savefig(FIGS / 'llc_share_by_category.png', bbox_inches='tight')
    plt.close(fig)

    # 2. Owner sector composition, parking now visible as its own rows
    sizes = sectors.groupby('analysis_category')['parcels'].sum()
    cats = set(sizes[sizes >= MIN_PARCELS].index) | set(HEADLINE_CATEGORIES)
    piv = (sectors[sectors['analysis_category'].isin(cats)]
           .pivot(index='analysis_category', columns='owner_sector', values='land_value_share')
           .dropna(how='all').fillna(0)
           .sort_values(ol.SECTOR_BUSINESS, ascending=False))
    piv = piv[piv.sum(axis=1) > 0]
    fig, ax = plt.subplots(figsize=(11.5, 6))
    piv.plot(kind='barh', stacked=True, ax=ax,
             color=['#6acc65', '#4878cf', '#d65f5f', '#956cb4'])
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0))
    ax.set_xlabel('Share of land value')
    ax.set_ylabel('')
    ax.set_title('Who owns each property type, by land value')
    ax.tick_params(axis='y', labelsize=8)
    ax.legend(fontsize=8, loc='center left', bbox_to_anchor=(1.01, 0.5), frameon=False)
    fig.tight_layout()
    fig.savefig(FIGS / 'owner_sector_by_category.png')
    plt.close(fig)

    # 3. Where LLC owners mail, for every property type
    size = geo.groupby('analysis_category')[['parcels', 'land_value']].sum()
    # A 100%-stacked bar over two parcels looks as authoritative as one over eight thousand.
    # Keep the headline categories regardless (their counts are annotated), but drop other
    # categories too small to read anything from.
    keep = size[(size['land_value'] > 0) &
                ((size['parcels'] >= MIN_LLC_PARCELS) |
                 size.index.isin(HEADLINE_CATEGORIES))].index
    g = geo[geo['analysis_category'].isin(keep)]
    piv = (g.pivot(index='analysis_category', columns='owner_geography',
                   values='land_value_share')
           .reindex(columns=[c for c in ol.GEO_ORDER]).fillna(0))
    piv = piv.loc[piv['Out-of-state'].sort_values().index]
    fig, ax = plt.subplots(figsize=(12, max(4, 0.36 * len(piv))))
    piv.plot(kind='barh', stacked=True, ax=ax,
             color=['#2a9d8f', '#8ab17d', '#e9c46a', '#e76f51', '#adb5bd'])
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1.0))
    ax.set_xlabel('Share of LLC-owned land value')
    ax.set_ylabel('')
    ax.set_title('Where LLC owners receive their mail, by property type')
    ax.tick_params(axis='y', labelsize=8)
    for y, cat in enumerate(piv.index):
        n, lv = size.loc[cat, 'parcels'], size.loc[cat, 'land_value']
        ax.text(1.02, y, f'{n:,.0f} LLC parcels · {_short_money(lv)}',
                va='center', fontsize=7, color='#444')
    ax.set_xlim(0, 1.0)
    ax.legend(fontsize=8, loc='upper center', bbox_to_anchor=(0.5, -0.12),
              ncol=len(ol.GEO_ORDER), frameon=False)
    fig.tight_layout()
    fig.savefig(FIGS / 'llc_geography_by_category.png', bbox_inches='tight')
    plt.close(fig)

    # 4. Dollar tax shift by sector, headline categories
    head = sectors[sectors['analysis_category'].isin(HEADLINE_CATEGORIES)]
    piv = (head.pivot(index='analysis_category', columns='owner_sector', values='tax_change')
           .fillna(0) / 1e6)
    fig, ax = plt.subplots(figsize=(11, 3.8))
    piv.plot(kind='barh', ax=ax, color=['#6acc65', '#4878cf', '#d65f5f', '#956cb4'])
    ax.set_xlabel('Tax change under the reform ($M / year)')
    ax.set_ylabel('')
    ax.axvline(0, color='k', lw=0.8)
    ax.set_title('Who pays more on vacant land and parking')
    ax.legend(fontsize=8, loc='center left', bbox_to_anchor=(1.01, 0.5), frameon=False)
    fig.tight_layout()
    fig.savefig(FIGS / 'tax_shift_by_sector_category.png')
    plt.close(fig)

    # 5. Concentration among LLC holders of vacant + parking land
    sub = df[df['analysis_category'].isin(HEADLINE_CATEGORIES) &
             (df['legal_form'] == ol.FORM_LLC)]
    vals = np.sort(sub.groupby('entity_label')['taxable_land_value'].sum().to_numpy())
    if len(vals) and vals.sum() > 0:
        cum = np.cumsum(vals) / vals.sum()
        x = np.arange(1, len(vals) + 1) / len(vals)
        fig, ax = plt.subplots(figsize=(5.5, 5.5))
        ax.plot(x, cum, color='#e76f51', lw=2)
        ax.plot([0, 1], [0, 1], color='k', lw=0.8, ls='--')
        ax.set_xlabel('Cumulative share of LLC entities (poorest first)')
        ax.set_ylabel('Cumulative share of land value')
        ax.set_title('Concentration among LLC owners of\nvacant land and surface parking')
        fig.tight_layout()
        fig.savefig(FIGS / 'entity_concentration_vacant_parking.png')
        plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tax-year', type=int, default=2026)
    args = ap.parse_args()

    RESULTS.mkdir(exist_ok=True)

    print(f"\n== Loading TY{args.tax_year} universe ==")
    df = load_universe(args.tax_year)

    print("\n== Categories ==")
    df = assign_analysis_category(df)
    recarve = recarve_table(df)
    print(f"  surface parking carved out: {int(recarve['parcels'].sum()):,} parcels")
    print(recarve.to_string(index=False, float_format=lambda x: f'{x:,.0f}'))

    print("\n== Owner classification ==")
    df = classify_owners(df)
    print(df['owner_sector'].value_counts().to_string())
    print(df['legal_form'].value_counts().to_string())

    print("\n== Entity resolution ==")
    df['entity_label'], hubs = ol.resolve_entities(df)
    n_names = df.loc[df['owner_sector'] == ol.SECTOR_BUSINESS, 'owner_name'].nunique()
    n_ents = df.loc[df['owner_sector'] == ol.SECTOR_BUSINESS, 'entity_label'].nunique()
    print(f"  business names {n_names:,} -> resolved entities {n_ents:,}")

    print("\n== Tables ==")
    sectors = sector_table(df)
    shares = llc_share_table(df)
    geo = llc_geography_table(df)
    all_geo = owner_geography_table(df)
    ent = entity_table(df)
    robust = robustness_table(df)
    hubs = mail_hub_table(df)
    vp_hubs = mail_hub_table(df, HEADLINE_CATEGORIES)
    stats = headline_stats(df, shares, geo, hubs, all_geo, vp_hubs)

    hubs.to_csv(RESULTS / 'out_of_state_mail_addresses.csv', index=False)
    with open(RESULTS / 'headline_stats.json', 'w', encoding='utf-8') as fh:
        json.dump(stats, fh, indent=2)
    recarve.to_csv(RESULTS / 'parking_recarve.csv', index=False)
    sectors.to_csv(RESULTS / 'ownership_by_category.csv', index=False)
    shares.to_csv(RESULTS / 'llc_share_by_category.csv', index=False)
    geo.to_csv(RESULTS / 'llc_geography_by_category.csv', index=False)
    all_geo.to_csv(RESULTS / 'owner_geography_by_category.csv', index=False)
    ent.to_csv(RESULTS / 'llc_entities.csv', index=False)
    robust.to_csv(RESULTS / 'robustness_opa_vs_lycd.csv', index=False)

    sample = ol.validate_sample(df['owner_name'], df['legal_form'], n_per_form=35)
    sample.to_csv(RESULTS / 'classifier_sample.csv', index=False)
    print(f"  wrote {len(sample)} owner names for hand-adjudication -> classifier_sample.csv")

    print("\n== Headline categories ==")
    cols = ['analysis_category', 'private_parcels', 'private_llc_parcel_share',
            'private_llc_land_share', 'private_llc_land_share_upper',
            'private_business_land_share']
    print(shares[shares['analysis_category'].isin(HEADLINE_CATEGORIES)][cols]
          .to_string(index=False, float_format=lambda x: f'{x:,.3f}'))

    print("\n== Guardrails ==")
    fails = run_checks(df, shares, ent)
    for f in fails:
        print(f"  FAIL: {f}")
    if not fails:
        print("  all passed")

    make_figures(shares, sectors, geo, df)
    print(f"\nResults -> {RESULTS}\nFigures -> {FIGS}")

    if fails:
        sys.exit(1)


if __name__ == '__main__':
    main()
