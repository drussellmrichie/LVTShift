import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *
import numpy as np

# At k=1.0 with the cap OFF, lycd/market_value == zone_median_psf / own_psf.
g, st = build(land_pct_improved=1.0, apply_cap=False)
cat = g['category_code'].astype(str).str.strip()
mv = pd.to_numeric(g['market_value'], errors='coerce').fillna(0)
m = ~cat.isin(VACANT_CODES) & (mv > 0)
r = (g['lycd_land_value'][m] / mv[m]).replace([np.inf,-np.inf], np.nan).dropna()
print('k=1.0, cap OFF:  median ratio = %.4f   (tautology predicts ~1.0)' % r.median())
print('  share within +/-5%% of 1.0: %.2f%%' % (100*((r>=0.95)&(r<=1.05)).mean()))
print('  => at k=0.20 this implies median %.4f and band-share %.2f%%'
      % (0.20*r.median(), 100*((r>=0.95)&(r<=1.05)).mean()))
print()
# apples-to-apples comparator on IMPROVED parcels, common denominator = market_value
g2, _ = build()
cat2 = g2['category_code'].astype(str).str.strip()
tb = pd.to_numeric(g2['taxable_building'],errors='coerce').fillna(0)
tl = pd.to_numeric(g2['taxable_land'],errors='coerce').fillna(0)
mv2 = pd.to_numeric(g2['market_value'],errors='coerce').fillna(0)
imp = (tb>0) & (mv2>0) & ~cat2.isin(VACANT_CODES)
opa_r  = (tl[imp]/mv2[imp])
lycd_r = (g2['lycd_land_value'][imp]/mv2[imp])
print('APPLES-TO-APPLES on improved parcels (n=%d), both vs market_value:' % imp.sum())
for name, s in [('OPA land/mv', opa_r), ('LYCD land/mv', lycd_r)]:
    print('  %-14s exact 0.200: %6.2f%% | band[.19,.21]: %6.2f%% | IQR %.4f'
          % (name, 100*np.isclose(s,0.20,atol=1e-6).mean(),
             100*((s>=0.19)&(s<=0.21)).mean(), s.quantile(.75)-s.quantile(.25)))
