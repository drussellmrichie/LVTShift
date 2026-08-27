import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *
opa = pd.read_csv('C:/projects/LVTShift/analysis/data/philadelphia.csv', usecols=['tax_change_pct','is_fully_exempt'])
opa_t = opa[opa.is_fully_exempt==0]
OPA_WIN = 100*(opa_t.tax_change_pct<0).mean()
print('OPA winners %.4f%%' % OPA_WIN)
for pct in [0.205, 0.21, 0.215, 0.22]:
    g, st = build(land_pct_improved=pct)
    gc = categorize(g); lm, im, t, f = solve(gc)
    w, med = winners(t); w*=100
    print('pct %.3f -> winners %.4f%%  (delta vs OPA %+.4f pp)' % (pct, w, w-OPA_WIN))
