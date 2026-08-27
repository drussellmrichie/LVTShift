import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *

# OPA panel headline, straight from the shipped export
opa = pd.read_csv('C:/projects/LVTShift/analysis/data/philadelphia.csv',
                  usecols=['tax_change_pct', 'is_fully_exempt'])
opa_t = opa[opa.is_fully_exempt == 0]
OPA_WIN, OPA_MED = 100 * (opa_t.tax_change_pct < 0).mean(), opa_t.tax_change_pct.median()
print('OPA-pre (shipped)      : winners %.2f%%  median %+.2f%%' % (OPA_WIN, OPA_MED))
print()
print('LYCD-pre at varying LAND_PCT_IMPROVED, vs the OPA panel it is contrasted against:')
print('%-7s %-10s %-11s %-14s %-14s' % ('pct', 'winners%', 'median%', 'd_winners(pp)', 'd_median(pp)'))
for pct in [0.10, 0.15, 0.20, 0.23, 0.25, 0.27, 0.29, 0.30, 0.35, 0.40]:
    g, st = build(land_pct_improved=pct)
    gc = categorize(g)
    lm, im, taxable, full = solve(gc)
    w, med = winners(taxable)
    w *= 100
    flag = ''
    if (med - OPA_MED) > 0:
        flag = '  <-- LYCD cut now SHALLOWER than OPA'
    print('%-7.2f %-10.2f %-11.2f %-14.2f %-14.2f%s'
          % (pct, w, med, w - OPA_WIN, med - OPA_MED, flag))
