import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *

print('=== SENSITIVITY: LAND_PCT_IMPROVED (shipped value = 0.20) ===')
print('%-8s %-12s %-12s %-10s %-10s %-9s %-9s' %
      ('pct', 'landbase_B', 'capped_B', 'n_capped', 'landmill', 'winners%', 'medchg%'))
rows = []
for pct in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]:
    g, st = build(land_pct_improved=pct)
    gc = categorize(g)
    lm, im, taxable, full = solve(gc)
    w, med = winners(taxable)
    rows.append((pct, st['land_after_cap'] / 1e9, st['land_removed_by_cap'] / 1e9,
                 st['n_capped'], lm, 100 * w, med))
    print('%-8.2f %-12.3f %-12.3f %-10d %-10.4f %-9.2f %-9.2f'
          % rows[-1])

print()
print('=== SENSITIVITY: market_value cap ON vs OFF (at pct=0.20) ===')
for cap in [True, False]:
    g, st = build(land_pct_improved=0.20, apply_cap=cap)
    gc = categorize(g)
    lm, im, taxable, full = solve(gc)
    w, med = winners(taxable)
    print('cap=%-6s landbase %.3f B | landmill %.4f | winners %.2f%% | med %+.2f%%'
          % (cap, st['land_after_cap'] / 1e9 if cap else st['land_before_cap'] / 1e9, lm, 100 * w, med))

print()
print('=== SENSITIVITY: MIN_IMPROVED (shipped = 50) ===')
for mi in [10, 50, 200, 1000]:
    g, st = build(min_improved=mi)
    gc = categorize(g)
    lm, im, taxable, full = solve(gc)
    w, med = winners(taxable)
    lv = g.gma_level.value_counts()
    print('min_improved=%-5d L3=%-7d L2=%-6d L1=%-5d | landmill %.4f | winners %.2f%% | med %+.2f%%'
          % (mi, lv.get('L3', 0), lv.get('L2', 0), lv.get('L1', 0), lm, 100 * w, med))

print()
print('=== SENSITIVITY: lot-area priority (code=OPA-first; Step 2 markdown says PIN-first) ===')
for ap in ['opa_first', 'pin_first']:
    g, st = build(area_priority=ap)
    gc = categorize(g)
    lm, im, taxable, full = solve(gc)
    w, med = winners(taxable)
    print('%-10s landbase %.3f B | landmill %.4f | winners %.2f%% | med %+.2f%% | n_capped %d'
          % (ap, st['land_after_cap'] / 1e9, lm, 100 * w, med, st['n_capped']))
