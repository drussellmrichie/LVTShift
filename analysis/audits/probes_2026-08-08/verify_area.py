import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *

g, st = build()
a = g['dor_area_sqft']
PHILLY_SQMI = 134.2
PHILLY_SQFT = PHILLY_SQMI * 27_878_400
print('Philadelphia land area: %.3e sqft (%.1f sq mi)' % (PHILLY_SQFT, PHILLY_SQMI))
print('sum(dor_area_sqft)    : %.3e sqft  -> %.2fx the city' % (a.sum(), a.sum()/PHILLY_SQFT))
for q in [0.99, 0.995, 0.999]:
    thr = a.quantile(q)
    kept = a[a <= thr]
    print('  drop top %.1f%% (area > %.0f sqft): %.3e -> %.2fx'
          % (100*(1-q), thr, kept.sum(), kept.sum()/PHILLY_SQFT))
print()
print('by area source:')
for src in ['opa_total_area','dor_spatial','pin_dor']:
    m = g['_area_src']==src
    print('  %-16s n=%-7d sum %.3e (%.2fx city) median %.0f sqft'
          % (src, m.sum(), a[m].sum(), a[m].sum()/PHILLY_SQFT, a[m].median()))
print()
print('shared-polygon signature among dor_spatial:')
ds = a[g['_area_src']=='dor_spatial']
vc = ds.value_counts()
print('  %d parcels, %d distinct area values' % (len(ds), len(vc)))
print('  share of parcels whose area value is shared with >=1 other: %.1f%%'
      % (100*ds.isin(vc[vc>1].index).mean()))
print('  top shared value: %.1f sqft on %d parcels' % (vc.index[0], vc.iloc[0]))
print()
print('largest single area records:')
top = g.nlargest(3,'dor_area_sqft')[['parcel_number','dor_area_sqft','market_value','_area_src']]
for _,r in top.iterrows():
    print('  %s  %.3e sqft (%.2f sq mi)  mv=$%.0f  src=%s'
          % (r.parcel_number, r.dor_area_sqft, r.dor_area_sqft/27_878_400, r.market_value, r._area_src))
