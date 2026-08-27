import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *
import numpy as np

def variant(mult=None, fallback_only=False, winsor_area=None):
    """Rebuild with an alternative cap form."""
    g, st = build(apply_cap=False)          # get uncapped land
    cat = g['category_code'].astype(str).str.strip()
    mv = pd.to_numeric(g['market_value'], errors='coerce').fillna(0).clip(lower=0)
    isvac = cat.isin(VACANT_CODES)
    land = g['lycd_land_value'].copy()
    if winsor_area is not None:
        # re-derive land with area winsorized at a percentile, then apply the shipped 1x cap
        thr = g['dor_area_sqft'].quantile(winsor_area)
        scale = np.minimum(g['dor_area_sqft'], thr) / g['dor_area_sqft'].replace(0, np.nan)
        land = land * scale.fillna(1.0)
        land = np.where(~isvac, np.minimum(land, mv), land)
    elif fallback_only:
        m = ~isvac & g['_area_src'].isin(['dor_spatial'])
        land = np.where(m, np.minimum(land, mv), land)
    elif mult is not None:
        land = np.where(~isvac, np.minimum(land, mv * mult), land)
    g['lycd_land_value'] = land
    gc = categorize(g)
    lm, im, t, f = solve(gc)
    w, med = winners(t)
    return lm, 100*w, med, float(np.asarray(land).sum()/1e9)

rows = [('shipped 1x cap', dict(mult=1.0)),
        ('2x market value', dict(mult=2.0)),
        ('5x market value', dict(mult=5.0)),
        ('fallback-only (dor_spatial)', dict(fallback_only=True)),
        ('winsorize area at p99 + 1x cap', dict(winsor_area=0.99)),
        ('no cap', dict(mult=None))]
print('%-32s %-10s %-10s %-10s %-10s' % ('variant','landmill','winners%','median%','landbase_B'))
for name, kw in rows:
    if name == 'no cap':
        g, st = build(apply_cap=False); gc = categorize(g); lm, im, t, f = solve(gc)
        w, med = winners(t); lb = g.lycd_land_value.sum()/1e9
        print('%-32s %-10.4f %-10.2f %-10.2f %-10.3f' % (name, lm, 100*w, med, lb)); continue
    lm, w, med, lb = variant(**kw)
    print('%-32s %-10.4f %-10.2f %-10.2f %-10.3f' % (name, lm, w, med, lb))
