import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *
import geopandas as gpd

g = gpd.read_parquet('data/parcels.gpq')
g['category_code'] = pd.to_numeric(g['category_code'], errors='coerce').astype('Int64').astype(str)
tl = pd.to_numeric(g['taxable_land'], errors='coerce').fillna(0)
tb = pd.to_numeric(g['taxable_building'], errors='coerce').fillna(0)
mv = pd.to_numeric(g['market_value'], errors='coerce').fillna(0)
eb = pd.to_numeric(g['exempt_building'], errors='coerce').fillna(0)

abated = (tb <= 0) & (tl > 0) & (~g['category_code'].isin(VACANT_CODES))
print('abated parcels: %d' % abated.sum())

pre = tl * 4.0                       # model.ipynb pre-abatement imputation
implied = (mv - tl).clip(lower=0)
post = eb.where(eb > 0, implied)     # model_post_abatement.ipynb

same = np.isclose(pre[abated], post[abated], rtol=1e-9, atol=1e-6)
print('  identical pre vs post improvement: %d (%.1f%%)' % (same.sum(), 100 * same.mean()))
print('  using exempt_building (eb>0): %d' % int((abated & (eb > 0)).sum()))
print('  using market_value fallback : %d' % int((abated & (eb <= 0)).sum()))
fb = abated & (eb <= 0)
print('  of the fallback group, identical to pre: %d (%.1f%%)'
      % (np.isclose(pre[fb], post[fb], rtol=1e-9, atol=1e-6).sum(),
         100 * np.isclose(pre[fb], post[fb], rtol=1e-9, atol=1e-6).mean()))
ebg = abated & (eb > 0)
print('  of the exempt_building group, identical to pre: %d (%.1f%%)'
      % (np.isclose(pre[ebg], post[ebg], rtol=1e-9, atol=1e-6).sum(),
         100 * np.isclose(pre[ebg], post[ebg], rtol=1e-9, atol=1e-6).mean()))
print()
print('  market_value == 5 x taxable_land exactly, among abated: %d (%.1f%%)'
      % (np.isclose(mv[abated], 5 * tl[abated], rtol=1e-9, atol=1e-6).sum(),
         100 * np.isclose(mv[abated], 5 * tl[abated], rtol=1e-9, atol=1e-6).mean()))

print()
print('=== revenue cross-check (the assert in Step 7 / Section 4) ===')
tt = (tl + tb).clip(lower=0)
city_rev = tt.mul(6.317 / 1000).sum()
gap = (city_rev / 795_796_126 - 1) * 100
print('modeled combined levy : $%,.0f'.replace('%,', '%') % (tt.mul(13.998 / 1000).sum()))
print('implied city-only     : $%.0f' % city_rev)
print('FY2024 city actual    : $795796126')
print('gap                   : %+.2f%%   (prose target ±5%%, assert allows ±10%%)' % gap)
