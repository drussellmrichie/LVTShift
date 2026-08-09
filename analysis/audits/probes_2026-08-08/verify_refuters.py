import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lycd_probe import *

g, st = build()
gc = categorize(g)
cat = pd.to_numeric(g['category_code'], errors='coerce').astype('Int64').astype(str)
mv = pd.to_numeric(g['market_value'], errors='coerce').fillna(0)
land = g['lycd_land_value']
exempt = gc['full_exmp'] == 1

print('=== R1 CLAIM: realized SFR land share is ABOVE FHFA, so raising the constant moves AWAY ===')
for label, mask in [
    ('all improved, ALL parcels',      ~cat.isin(VACANT_CODES) & (mv > 0)),
    ('all improved, NON-EXEMPT only',  ~cat.isin(VACANT_CODES) & (mv > 0) & ~exempt),
    ('SFR (code 1), ALL parcels',      (cat == '1') & (mv > 0)),
    ('SFR (code 1), NON-EXEMPT only',  (cat == '1') & (mv > 0) & ~exempt),
]:
    agg = land[mask].sum() / mv[mask].sum()
    med = (land[mask] / mv[mask]).median()
    print('  %-32s aggregate %.4f | parcel median %.4f | n=%d' % (label, agg, med, mask.sum()))

fh = pd.read_csv('data/fhfa_land_share_by_tract.csv')
print('  FHFA benchmark (single-family): mean %.4f | median %.4f' % (fh.fhfa_land_share.mean(), fh.fhfa_land_share.median()))

print()
print('=== does RAISING the constant move SFR share toward or away from FHFA? ===')
for pct in [0.15, 0.20, 0.25]:
    g2, _ = build(land_pct_improved=pct)
    gc2 = categorize(g2)
    c2 = pd.to_numeric(g2['category_code'], errors='coerce').astype('Int64').astype(str)
    mv2 = pd.to_numeric(g2['market_value'], errors='coerce').fillna(0)
    m2 = (c2 == '1') & (mv2 > 0) & (gc2['full_exmp'] == 0)
    print('  pct=%.2f -> realized SFR land share %.4f (FHFA %.4f)'
          % (pct, g2['lycd_land_value'][m2].sum() / mv2[m2].sum(), fh.fhfa_land_share.mean()))

print()
print('=== R2 CLAIM: capping RATES (base-rate check) ===')
capped = g['_capped']
elig = ~cat.isin(VACANT_CODES)
print('  overall cap rate (cap-eligible): %.2f%%' % (100 * capped[elig].mean()))
for c in ['1', '8', '5', '4']:
    m = (cat == c)
    print('    code %-3s n=%-7d cap rate %6.2f%%  | share of all caps %5.2f%%'
          % (c, m.sum(), 100 * capped[m].mean(), 100 * (capped & m).sum() / capped.sum()))
print('  by area source:')
for src in ['opa_total_area', 'dor_spatial', 'pin_dor']:
    m = (g['_area_src'] == src)
    print('    %-16s n=%-7d cap rate %6.2f%% | share of parcels %5.2f%% | share of caps %5.2f%%'
          % (src, m.sum(), 100 * capped[m].mean(), 100 * m.mean(), 100 * (capped & m).sum() / capped.sum()))

print()
print('=== R2 residual: dollar-weighted clip by source and category ===')
_mv_cap = mv.clip(lower=0)
over = (land - np.minimum(land, _mv_cap))
over = over.where(capped, 0.0)
tot = over.sum()
print('  total clipped $%.2fB' % (tot / 1e9))
for src in ['opa_total_area', 'dor_spatial', 'pin_dor']:
    m = (g['_area_src'] == src)
    print('    %-16s $%.2fB (%.1f%%)' % (src, over[m].sum() / 1e9, 100 * over[m].sum() / tot))
for c in ['1', '8']:
    m = (cat == c)
    print('    code %-3s        $%.2fB (%.1f%%)' % (c, over[m].sum() / 1e9, 100 * over[m].sum() / tot))
print()
m_opa_capped = capped & (g['_area_src'] == 'opa_total_area')
m_opa_unc = ~capped & (g['_area_src'] == 'opa_total_area') & elig
print('  capped opa_total_area parcels: median market_value $%.0f (n=%d)' % (mv[m_opa_capped].median(), m_opa_capped.sum()))
print('  uncapped opa_total_area parcels: median market_value $%.0f (n=%d)' % (mv[m_opa_unc].median(), m_opa_unc.sum()))
