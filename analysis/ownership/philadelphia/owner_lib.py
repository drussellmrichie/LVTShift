"""Shared owner-classification and entity-resolution logic for Philadelphia.

Extracted from `ownership_entities.py` so the concentration passes and the
ownership-by-property-type analysis run the same code rather than drifting copies.

Two orthogonal classification axes:

  - **Sector** (`classify_sector`) — Public agency / Institutional / Business / Individual.
    A four-way regex cascade applied in order, so Public wins ties. This is the original
    July 2026 classification, unchanged.
  - **Legal form** (`classify_legal_form`) — LLC / LP-LLP / Corporation / Trust-estate /
    Other business / Individual. New, and the finer cut most political questions actually
    want: "LLC-owned" is a much narrower claim than "business-owned".

Both are heuristics over owner-name strings that OPA truncates at 40 characters, so both
are lower bounds. `validate_sample()` exists to measure that error rather than assume it.

Entity resolution (`resolve_entities`) unions owner names that share a mailing address, but
**only for business-class names**. Merging individuals by shared address chains condo towers
and management offices into mega-components — the first attempt at this produced a fake
11,009-parcel, $10.2B "owner" mixing three unrelated people. Addresses shared by more than
`MAX_NAMES_PER_ADDR` distinct business names are treated as billing servicers or registered
agents and excluded as merge hubs.
"""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

__all__ = [
    "PUBLIC_PATTERNS", "INSTITUTIONAL", "BUSINESS",
    "SECTOR_PUBLIC", "SECTOR_INSTITUTIONAL", "SECTOR_BUSINESS", "SECTOR_INDIVIDUAL",
    "FORM_LLC", "FORM_LP", "FORM_CORP", "FORM_TRUST", "FORM_OTHER_BIZ", "FORM_INDIVIDUAL",
    "BUSINESS_FORMS", "LEGAL_FORM_ORDER",
    "owner_name_series", "norm_addr", "build_mail_key",
    "classify_sector", "classify_legal_form",
    "parse_owner_geography", "GEO_ORDER",
    "resolve_entities", "MAX_NAMES_PER_ADDR",
]

# Sector labels
SECTOR_PUBLIC = "Public agency"
SECTOR_INSTITUTIONAL = "Institutional / nonprofit"
SECTOR_BUSINESS = "Business / investor entity"
SECTOR_INDIVIDUAL = "Individual"

# Legal-form labels
FORM_LLC = "LLC"
FORM_LP = "LP / LLP"
FORM_CORP = "Corporation"
FORM_TRUST = "Trust / estate"
FORM_OTHER_BIZ = "Other business"
FORM_INDIVIDUAL = "Individual / unclassified"

BUSINESS_FORMS = (FORM_LLC, FORM_LP, FORM_CORP, FORM_TRUST, FORM_OTHER_BIZ)
LEGAL_FORM_ORDER = (*BUSINESS_FORMS, FORM_INDIVIDUAL)

PUBLIC_PATTERNS = [
    'CITY OF PHILA', 'CITY OF PHILADELPHIA', 'PHILADELPHIA LAND BANK', 'LAND BANK',
    'PHILA HOUSING AUTH', 'PHILADELPHIA HOUSING', 'HOUSING AUTHORITY',
    'REDEVELOPMENT AUTH', 'PHILADELPHIA REDEVELOP', 'PHILA REDEVELOPMENT',
    'SCHOOL DISTRICT', 'SCHOOL DIST', 'BOARD OF EDUCATION',
    'COMMONWEALTH OF', 'STATE OF PENNSYLVANIA',
    'UNITED STATES', 'SECRETARY OF HOUSING',
    'SEPTA', 'SOUTHEASTERN PENN TRANS', 'SOUTHEASTERN PENNSYLVANIA',
    'DELAWARE RIVER PORT', 'PHILA MUNICIPAL AUTH', 'PHILADELPHIA MUNICIPAL',
    'PHILA PARKING AUTH', 'PHILADELPHIA PARKING', 'PARKING AUTHORITY',
    'PHILADELPHIA AUTHORITY F', 'PHILA AUTHORITY FOR IND',
    'PIDC', 'PHILADELPHIA INDUSTRIAL', 'PENNSYLVANIA ECONOMIC DEV',
    'FAIRMOUNT PARK', 'DEPT OF', 'DEPARTMENT OF', 'AMTRAK', 'NATIONAL RAILROAD',
]
INSTITUTIONAL = [
    'UNIVERSITY', 'UNIV ', 'UNIV OF', ' COLLEGE', 'COLLEGE OF', 'HOSPITAL', 'HEALTH SYSTEM',
    'CHURCH', 'BAPTIST', 'CATHOLIC', 'LUTHERAN', 'METHODIST', 'PRESBYTERIAN', 'EPISCOPAL',
    'ISLAMIC', 'MOSQUE', 'MASJID', 'SYNAGOGUE', 'CONGREGATION', 'MINISTR', 'DIOCESE',
    'ARCHDIOCESE', 'CEMETERY', 'FOUNDATION', 'CHARIT', 'ACADEMY', 'SEMINARY',
    'SALVATION ARMY', 'YMCA', 'YWCA', 'CHARTER SCHOOL', 'FRIENDS OF',
]
BUSINESS = [
    r'\bLLC\b', r'\bL L C\b', r'\bLP\b', r'\bL P\b', r'\bLTD\b', r'\bINC\b', r'\bCORP\b',
    r'\bCOMPANY\b', r'\bCO\b', r'\bPARTNERS\b', r'\bPARTNERSHIP\b', r'\bASSOCIATES\b',
    r'\bASSOC\b', r'\bPROPERTIES\b', r'\bPROPERTY\b', r'\bREALTY\b', r'\bREAL ESTATE\b',
    r'\bINVEST', r'\bHOLDINGS\b', r'\bGROUP\b', r'\bDEVELOP', r'\bTRUST\b', r'\bTR\b',
    r'\bREIT\b', r'\bVENTURES\b', r'\bCAPITAL\b', r'\bMGMT\b', r'\bMANAGEMENT\b',
    r'\bENTERPRISES\b', r'\bBANK\b', r'\bSAVINGS\b', r'\bFCU\b', r'\bHOMES\b',
    r'\bRENTALS\b', r'\bEQUITIES\b', r'\bESTATE OF\b', r'\bAPARTMENTS\b',
]

_PUB_RE = '|'.join(re.escape(p) for p in PUBLIC_PATTERNS)
_INST_RE = '|'.join(re.escape(p) for p in INSTITUTIONAL)
_BIZ_RE = '|'.join(BUSINESS)

# OPA truncates owner names at TWO widths — measured on the TY2026 cache, the length
# histogram spikes at 25 (24,583 names vs ~10k at length 24) and again at 40 (1,012 vs 271
# at 39). Both cut the legal suffix off: "CIVETTA PROPERTY GROUP LIMITED LIABILITY" loses
# "COMPANY", and "S&S REALITY INVESTMENTS L" loses "LC" entirely. So the LLC pattern needs
# `LIMITED LIABILIT` as a prefix match, and a trailing ' LL' (1,168 names, every sampled one
# an unambiguous truncated LLC — no PA entity type is "LL") counts as an LLC.
TRUNCATION_WIDTHS = (25, 40)

_FORM_PATTERNS: list[tuple[str, str]] = [
    (FORM_LLC, r'\bLLC\b|\bL\.?\s?L\.?\s?C\.?\b|LIMITED LIABILIT|\sLL$'),
    (FORM_LP, r'\bLLP\b|\bLP\b|\bL\.?\s?P\.?\b|\bPARTNERSHIP\b|\bPARTNERS\b'),
    (FORM_CORP, r'\bINC\b|\bINCORPORATED\b|\bCORP\b|\bCORPORATION\b|\bLTD\b|\bCOMPANY\b'),
    (FORM_TRUST, r'\bTRUST\b|\bTRUSTEE\b|\bTR\b|\bESTATE OF\b'),
]

GEO_ORDER = (
    "In-city (Philadelphia)",
    "Suburban PA",
    "NJ / DE metro",
    "Out-of-state",
    "Unknown",
)

# Philadelphia's own name, plus the spellings that appear in OPA's free-text city field.
_PHILLY_CITY_NAMES = {
    "PHILADELPHIA", "PHILA", "PHILADELPHIA CITY", "PHILADELPHIAA", "PHILDELPHIA",
    "PHILADELHIA", "PHILADELPIA", "PHILADELPHA", "PHLA", "PHIL", "PHILADEPHIA",
    "PHILADELPHIS", "PHILADLEPHIA", "PHILADELPHIA PA",
}
# Zip3 prefixes covering the four PA collar counties (Bucks, Chester, Delaware, Montgomery).
_COLLAR_ZIP3 = {"189", "190", "193", "194", "180", "181"}

MAX_NAMES_PER_ADDR = 50


def owner_name_series(df: pd.DataFrame, col1: str = "owner_1", col2: str = "owner_2") -> pd.Series:
    """Coalesce owner_1 → owner_2 into one uppercased, stripped name."""
    return (
        df[[col1, col2]].replace('', np.nan).bfill(axis=1).iloc[:, 0]
        .fillna('').astype(str).str.upper().str.strip()
    )


def norm_addr(s: pd.Series) -> pd.Series:
    """Uppercase, strip punctuation, collapse whitespace."""
    s = s.fillna('').astype(str).str.upper().str.strip()
    s = s.str.replace(r'[^A-Z0-9 ]', '', regex=True)
    s = s.str.replace(r'\s+', ' ', regex=True)
    return s


def build_mail_key(mailing_street: pd.Series, mailing_zip: pd.Series,
                   location: pd.Series) -> pd.Series:
    """Normalized mailing address key, falling back to the property address when blank.

    The fallback is deliberately prefixed 'SELF ' so blank-mailing parcels group with
    themselves rather than all collapsing into one empty-string mega-key.
    """
    zip5 = mailing_zip.fillna('').astype(str).str[:5]
    key = norm_addr(mailing_street) + '|' + zip5
    blank = key.str.startswith('|')
    key.loc[blank] = 'SELF ' + norm_addr(location.loc[blank]) + '|19PHL'
    return key


def classify_sector(owner_name: pd.Series) -> pd.Series:
    """Four-way owner sector, applied in order so Public wins ties."""
    out = pd.Series(SECTOR_INDIVIDUAL, index=owner_name.index, dtype=object)
    out.loc[owner_name.str.contains(_BIZ_RE, regex=True, na=False)] = SECTOR_BUSINESS
    out.loc[owner_name.str.contains(_INST_RE, regex=True, na=False)] = SECTOR_INSTITUTIONAL
    out.loc[owner_name.str.contains(_PUB_RE, regex=True, na=False)] = SECTOR_PUBLIC
    return out


def classify_legal_form(owner_name: pd.Series) -> pd.Series:
    """Legal form of the owning entity, most specific match first.

    A name matching a `BUSINESS` pattern but no explicit legal suffix (REALTY, HOLDINGS,
    GROUP, …) lands in `Other business` rather than being forced into a form it does not
    state. Names matching nothing are `Individual / unclassified` — "unclassified" because
    a truncated entity name that lost its suffix also lands here.
    """
    out = pd.Series(FORM_INDIVIDUAL, index=owner_name.index, dtype=object)
    unassigned = pd.Series(True, index=owner_name.index)
    for label, pattern in _FORM_PATTERNS:
        hit = unassigned & owner_name.str.contains(pattern, regex=True, na=False)
        out.loc[hit] = label
        unassigned &= ~hit
    residual_biz = unassigned & owner_name.str.contains(_BIZ_RE, regex=True, na=False)
    out.loc[residual_biz] = FORM_OTHER_BIZ
    return out


def is_truncated(owner_name: pd.Series) -> pd.Series:
    """Flag names sitting exactly on one of OPA's two truncation widths.

    A name cut at 25 or 40 characters has probably lost its legal suffix, so its `LLC` /
    `LP` / `Corporation` assignment is unreliable in a *known direction*: entities get
    pushed down into `Other business` or `Individual / unclassified`, never up. Used to put
    an uncertainty band on the LLC share rather than presenting a point estimate that is
    quietly biased low.
    """
    return owner_name.str.len().isin(TRUNCATION_WIDTHS)


def parse_owner_geography(mailing_city_state: pd.Series,
                          mailing_zip: pd.Series | None = None) -> pd.DataFrame:
    """Split OPA's free-text `mailing_city_state` ('CITY ST') into city, state and bucket.

    Returns a frame with `mail_city`, `mail_state`, `owner_geography`, and `is_delaware`.

    This is a *location* proxy, not beneficial ownership: an out-of-state mailing address
    may be a registered agent or accountant for a Philadelphian, and a Philadelphia address
    may front a Delaware entity. Delaware is flagged separately for exactly that reason.
    """
    raw = mailing_city_state.fillna('').astype(str).str.upper().str.strip()
    raw = raw.str.replace(r'[.,]', ' ', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()

    state = raw.str.extract(r'\b([A-Z]{2})$', expand=False)
    city = raw.str.replace(r'\s*\b[A-Z]{2}$', '', regex=True).str.strip()

    zip3 = (mailing_zip.fillna('').astype(str).str[:3] if mailing_zip is not None
            else pd.Series('', index=raw.index))

    is_philly = city.isin(_PHILLY_CITY_NAMES) & (state == 'PA')
    bucket = pd.Series("Unknown", index=raw.index, dtype=object)
    bucket.loc[state.notna()] = "Out-of-state"
    bucket.loc[state.isin(['NJ', 'DE'])] = "NJ / DE metro"
    bucket.loc[state == 'PA'] = "Suburban PA"
    bucket.loc[is_philly] = "In-city (Philadelphia)"

    return pd.DataFrame({
        'mail_city': city,
        'mail_state': state,
        'owner_geography': bucket,
        'is_delaware': state == 'DE',
        'is_collar_county': (state == 'PA') & ~is_philly & zip3.isin(_COLLAR_ZIP3),
    }, index=raw.index)


def resolve_entities(df: pd.DataFrame, sector_col: str = 'owner_sector',
                     name_col: str = 'owner_name', mail_key_col: str = 'mail_key',
                     value_col: str = 'market_value',
                     max_names_per_addr: int = MAX_NAMES_PER_ADDR,
                     verbose: bool = True) -> tuple[pd.Series, pd.Index]:
    """Union owner names sharing a mailing address, business-class names only.

    Returns `(entity_label, hub_addresses)`. `entity_label` is the highest-value constituent
    owner name for each resolved entity; individuals and institutions keep their own name as
    their entity, because merging them by address chains condo towers and management offices
    into mega-components.
    """
    is_biz = df[sector_col] == SECTOR_BUSINESS
    pairs = df.loc[is_biz, [name_col, mail_key_col]].drop_duplicates()

    names_per_addr = pairs.groupby(mail_key_col)[name_col].nunique()
    hub_addrs = names_per_addr[names_per_addr > max_names_per_addr].index
    if verbose:
        print(f"  mail addresses excluded as merge hubs "
              f"(> {max_names_per_addr} business names): {len(hub_addrs):,}")
    link_pairs = pairs[~pairs[mail_key_col].isin(hub_addrs)]

    parent: dict = {}

    def find(x):
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(x, x) != x:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for name, addr in link_pairs.itertuples(index=False):
        union(('N', name), ('A', addr))

    entity_id = df[name_col].copy()
    entity_id.loc[is_biz] = ['C:' + str(find(('N', n))[1]) for n in df.loc[is_biz, name_col]]

    # Label each component by its highest-value constituent name.
    label = (df.assign(_eid=entity_id).groupby(['_eid', name_col])[value_col].sum()
             .sort_values(ascending=False).reset_index()
             .drop_duplicates('_eid').set_index('_eid')[name_col])
    return entity_id.map(label), hub_addrs


def validate_sample(owner_name: pd.Series, predicted_form: pd.Series,
                    n_per_form: int = 25, seed: int = 0) -> pd.DataFrame:
    """Draw a stratified sample of owner names for hand-adjudication of the form classifier.

    Returns the sample with an empty `actual_form` column to be filled in. Kept here so the
    sampling is reproducible (fixed seed) rather than re-drawn on each run.
    """
    rows = []
    rng = np.random.default_rng(seed)
    for form in LEGAL_FORM_ORDER:
        pool = owner_name[predicted_form == form].drop_duplicates()
        if pool.empty:
            continue
        take = min(n_per_form, len(pool))
        idx = rng.choice(len(pool), size=take, replace=False)
        for name in pool.iloc[idx]:
            rows.append({'owner_name': name, 'predicted_form': form, 'actual_form': ''})
    return pd.DataFrame(rows)
