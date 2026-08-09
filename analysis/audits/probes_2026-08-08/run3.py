import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *

g, st = build()
gc = categorize(g)

cat_raw = g['category_code'].astype(str).str.strip()
mv = pd.to_numeric(g['market_value'], errors='coerce').fillna(0)
improved = ~cat_raw.isin(VACANT_CODES) & (mv > 0)

print('=== Does LYCD escape OPA\'s 20%% land-ratio convention? ===')
lycd_share = g.loc[improved, 'lycd_land_value'].sum() / mv[improved].sum()
print('AGGREGATE LYCD land / market_value, improved parcels: %.4f' % lycd_share)

# OPA's own aggregate for the same parcels
opa_land = pd.to_numeric(g['taxable_land'], errors='coerce').fillna(0)
opa_bld = pd.to_numeric(g['taxable_building'], errors='coerce').fillna(0)
opa_tot = opa_land + opa_bld
m2 = improved & (opa_tot > 0)
print('AGGREGATE OPA  taxable_land / taxable_total, same parcels: %.4f'
      % (opa_land[m2].sum() / opa_tot[m2].sum()))

# per-parcel ratio distribution
r = (g.loc[improved, 'lycd_land_value'] / mv[improved]).replace([np.inf, -np.inf], np.nan).dropna()
print()
print('per-parcel LYCD land/market ratio, improved parcels:')
for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
    print('   p%-3d %.4f' % (p, r.quantile(p / 100)))
print('   share exactly at cap (ratio==1.0 within 1e-9): %.3f%%' % (100 * np.isclose(r, 1.0, atol=1e-9).mean()))
print('   share within 0.19-0.21: %.2f%%' % (100 * ((r >= 0.19) & (r <= 0.21)).mean()))

# OPA's own default-ratio artifact, for comparison
ro = (opa_land[m2] / opa_tot[m2])
print()
print('per-parcel OPA land/total ratio, same parcels:')
print('   share exactly 0.200 (within 1e-6): %.2f%%' % (100 * np.isclose(ro, 0.20, atol=1e-6).mean()))

print()
print('=== Is there an external land-value benchmark in the repo, and is LYCD validated against it? ===')
import pathlib
p = pathlib.Path('data/fhfa_land_share_by_tract.csv')
if p.exists():
    f = pd.read_csv(p)
    print('fhfa_land_share_by_tract.csv EXISTS: %d rows, cols=%s' % (len(f), list(f.columns)))
    sc = [c for c in f.columns if 'share' in c.lower() or 'land' in c.lower()]
    for c in sc:
        print('   %s: mean %.4f  median %.4f' % (c, f[c].mean(), f[c].median()))
else:
    print('no FHFA file')
