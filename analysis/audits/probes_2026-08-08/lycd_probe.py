"""Reconstruction of model_lycd.ipynb's LYCD land-value pipeline for audit probes.

Mirrors cells 2-18 of cities/philadelphia/model_lycd.ipynb exactly at default
parameters, so that parameters can then be varied to test sensitivity.
Run from cities/philadelphia/.
"""
import sys
import geopandas as gpd
import pandas as pd
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, '../..')
from lvt.lvt_utils import model_split_rate_tax, calculate_current_tax

MILLAGE = 13.998
VACANT_CODES = {'6', '12', '13'}


def knn_impute(values, coords, K=5):
    values = np.asarray(values, dtype=float)
    has_v = ~np.isnan(values)
    need_v = np.isnan(values)
    if need_v.sum() == 0:
        return values
    tree = cKDTree(coords[has_v])
    _, idxs = tree.query(coords[need_v], k=min(K, int(has_v.sum())), workers=-1)
    out = values.copy()
    out[need_v] = np.median(values[has_v][idxs], axis=1)
    return out


def build(land_pct_improved=0.20, land_pct_vacant=1.00, min_improved=50,
          apply_cap=True, area_priority='opa_first'):
    gdf = gpd.read_parquet('data/parcels.gpq')
    gdf['parcel_number'] = gdf['parcel_number'].astype(str).str.zfill(9)

    pin_areas = pd.read_parquet('data/parcel_areas_by_pin.parquet')
    pin_areas['pin'] = pin_areas['pin'].astype(str).str.strip()
    dor_areas = pd.read_parquet('data/parcel_areas_dor.parquet')
    dor_areas['parcel_number'] = dor_areas['parcel_number'].astype(str).str.zfill(9)
    gma = pd.read_parquet('data/parcel_gma_assignment.parquet')
    gma['key'] = gma['key'].astype(str).str.zfill(9)

    gdf['pin'] = gdf['pin'].astype(str).str.strip()
    _opa_area = pd.to_numeric(gdf['total_area'], errors='coerce').fillna(0)
    _pin_area = gdf['pin'].map(pin_areas.drop_duplicates('pin').set_index('pin')['pin_area_sqft'])
    _dor_area = gdf['parcel_number'].map(
        dor_areas.drop_duplicates('parcel_number').set_index('parcel_number')['dor_area_sqft'])

    if area_priority == 'opa_first':
        _s1 = _opa_area > 0
        _s2 = ~_s1 & _pin_area.notna() & (_pin_area > 0)
    else:  # pin_first — the ordering the markdown in Step 2 describes
        _s1 = _pin_area.notna() & (_pin_area > 0)
        _s2 = ~_s1 & (_opa_area > 0)
    if area_priority == 'opa_first':
        gdf['dor_area_sqft'] = np.where(_s1, _opa_area, np.where(_s2, _pin_area, _dor_area))
        gdf['_area_src'] = np.where(_s1, 'opa_total_area', np.where(_s2, 'pin_dor', 'dor_spatial'))
    else:
        gdf['dor_area_sqft'] = np.where(_s1, _pin_area, np.where(_s2, _opa_area, _dor_area))
        gdf['_area_src'] = np.where(_s1, 'pin_dor', np.where(_s2, 'opa_total_area', 'dor_spatial'))

    gdf = gdf.merge(gma[['key', 'gma1', 'gma2', 'gma3']],
                    left_on='parcel_number', right_on='key', how='left')

    cat_raw = gdf['category_code'].astype(str).str.strip()
    has_market = gdf['market_value'].notna() & (gdf['market_value'] > 0)
    has_area = gdf['dor_area_sqft'].notna() & (gdf['dor_area_sqft'] > 0)
    is_improved = ~cat_raw.isin(VACANT_CODES) & has_market & has_area
    is_vacant_p = cat_raw.isin(VACANT_CODES) & has_market & has_area

    gdf['_total_psf'] = np.where(is_improved | is_vacant_p,
                                 gdf['market_value'] / gdf['dor_area_sqft'], np.nan)

    imp = gdf[is_improved]
    pairs = [('gma3', imp.groupby('gma3')['_total_psf'].count().rename('_l3_n')),
             ('gma3', imp.groupby('gma3')['_total_psf'].median().rename('_l3_med')),
             ('gma2', imp.groupby('gma2')['_total_psf'].count().rename('_l2_n')),
             ('gma2', imp.groupby('gma2')['_total_psf'].median().rename('_l2_med')),
             ('gma1', imp.groupby('gma1')['_total_psf'].median().rename('_l1_med'))]
    for key, ser in pairs:
        gdf = gdf.merge(ser.reset_index(), on=key, how='left')

    gdf['_gma_med'] = np.where(
        gdf['_l3_n'].fillna(0) >= min_improved, gdf['_l3_med'],
        np.where(gdf['_l2_n'].fillna(0) >= min_improved, gdf['_l2_med'], gdf['_l1_med']))

    _land_pct = np.where(is_vacant_p, land_pct_vacant, land_pct_improved)
    _land_psf = gdf['_gma_med'] * _land_pct
    gdf['lycd_land_value'] = np.where(gdf['gma3'].notna() & has_area,
                                      (_land_psf * gdf['dor_area_sqft']).clip(lower=0), np.nan)
    gdf['gma_level'] = np.where(
        gdf['gma3'].isna(), 'knn',
        np.where(gdf['_l3_n'].fillna(0) >= min_improved, 'L3',
                 np.where(gdf['_l2_n'].fillna(0) >= min_improved, 'L2', 'L1')))

    stats = {}
    stats['n_knn_land'] = int(gdf['lycd_land_value'].isna().sum())
    stats['n_area_missing'] = int(gdf['dor_area_sqft'].isna().sum())
    # parcels that have a GMA zone but no area -> land is NaN, area is NaN
    stats['n_gma_but_no_area'] = int((gdf['gma3'].notna() & ~has_area).sum())

    gdf_m = gdf.to_crs('EPSG:3857')
    coords = np.column_stack([gdf_m.geometry.x, gdf_m.geometry.y])
    gdf['dor_area_sqft'] = knn_impute(gdf['dor_area_sqft'].values.astype(float), coords)
    gdf['lycd_land_value'] = knn_impute(gdf['lycd_land_value'].values, coords)

    _is_vac_cap = cat_raw.isin(VACANT_CODES)
    _mv_cap = pd.to_numeric(gdf['market_value'], errors='coerce').fillna(0).clip(lower=0)
    capped_mask = (gdf['lycd_land_value'] > _mv_cap) & ~_is_vac_cap
    stats['n_capped'] = int(capped_mask.sum())
    stats['land_before_cap'] = float(gdf['lycd_land_value'].sum())
    stats['land_removed_by_cap'] = float(
        (gdf['lycd_land_value'] - np.minimum(gdf['lycd_land_value'], _mv_cap))[capped_mask].sum())
    if apply_cap:
        gdf['lycd_land_value'] = np.where(
            ~_is_vac_cap, np.minimum(gdf['lycd_land_value'], _mv_cap), gdf['lycd_land_value'])
    gdf['_capped'] = capped_mask
    stats['land_after_cap'] = float(gdf['lycd_land_value'].sum())
    return gdf, stats


CAT = {'1': 'Single Family Residential', '2': 'Small Multi-Family (2-4 units)', '3': 'Mixed Use',
       '4': 'Commercial', '5': 'Industrial', '6': 'Vacant Land', '7': 'Other Commercial',
       '8': 'Other Residential', '9': 'Hotel', '10': 'Office / Commercial Condo', '11': 'Other',
       '12': 'Vacant Land', '13': 'Vacant Land', '14': 'Large Multi-Family (5+ units)',
       '15': 'Retail / General Commercial'}


def categorize(gdf):
    gdf = gdf.copy()
    gdf['category_code'] = pd.to_numeric(gdf['category_code'], errors='coerce').astype('Int64').astype(str)
    gdf['PROPERTY_CATEGORY'] = gdf['category_code'].map(CAT).fillna('Other')
    gdf.loc[gdf['taxable_building'] <= 0, 'PROPERTY_CATEGORY'] = 'Vacant Land'
    abated = ((gdf['taxable_building'] <= 0) & (gdf['taxable_land'] > 0)
              & (~gdf['category_code'].isin(VACANT_CODES)))
    gdf.loc[abated, 'PROPERTY_CATEGORY'] = 'Abated / Construction Exemption'
    iv = gdf['category_code'].isin(VACANT_CODES) & (gdf['taxable_building'] > 0)
    gdf.loc[iv, 'PROPERTY_CATEGORY'] = 'Improved Vacant Land'
    gdf['taxable_total'] = (gdf['taxable_land'] + gdf['taxable_building']).clip(lower=0)
    gdf['full_exmp'] = (gdf['taxable_total'] <= 0).astype(int)
    EX = {k: v + ' — Exempt' for k, v in CAT.items()}
    em = gdf['full_exmp'] == 1
    gdf.loc[em, 'PROPERTY_CATEGORY'] = gdf.loc[em, 'category_code'].map(EX).fillna('Other — Exempt')
    return gdf


def solve(gdf, ratio=4.0, imputed_bldg_multiplier=4.0):
    gdf = gdf.copy()
    gdf['millage_rate'] = MILLAGE
    cur, _, gdf = calculate_current_tax(df=gdf, tax_value_col='taxable_total',
                                        millage_rate_col='millage_rate',
                                        exemption_flag_col='full_exmp')
    gdf['model_land'] = gdf['lycd_land_value'].clip(lower=0)
    gdf['model_building'] = pd.to_numeric(gdf['taxable_building'], errors='coerce').fillna(0).clip(lower=0)
    ab = gdf['PROPERTY_CATEGORY'] == 'Abated / Construction Exemption'
    gdf.loc[ab, 'model_building'] = gdf.loc[ab, 'model_land'] * imputed_bldg_multiplier
    taxable = gdf[gdf['full_exmp'] == 0].copy()
    lm, im, rev, taxable = model_split_rate_tax(
        df=taxable, land_value_col='model_land', improvement_value_col='model_building',
        current_revenue=taxable['current_tax'].sum(), land_improvement_ratio=ratio)
    return lm, im, taxable, gdf


def winners(taxable):
    """Share of taxable parcels whose bill falls, and median % change."""
    tc = taxable['tax_change_pct']
    return float((tc < 0).mean()), float(tc.median())
