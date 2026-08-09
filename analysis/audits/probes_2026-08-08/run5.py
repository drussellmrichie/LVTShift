import pandas as pd, numpy as np

b = 'C:/projects/LVTShift/analysis/data/'
files = {'OPA-pre': 'philadelphia.csv', 'LYCD-pre': 'philadelphia_lycd.csv',
         'OPA-post': 'philadelphia_post_abatement.csv',
         'LYCD-post': 'philadelphia_lycd_post_abatement.csv'}
cols = ['parcel_id', 'property_category', 'current_tax', 'new_tax', 'tax_change_pct',
        'is_fully_exempt', 'std_geoid', 'median_income', 'minority_pct', 'black_pct',
        'model_type', 'land_millage', 'improvement_millage']

print('=== Census join: did it silently fall through to NaN? ===')
d = {}
for k, f in files.items():
    df = pd.read_csv(b + f, usecols=cols)
    d[k] = df
    print('%-10s std_geoid non-null %6.2f%% | median_income non-null %6.2f%% | model_type=%s'
          % (k, 100 * df.std_geoid.notna().mean(), 100 * df.median_income.notna().mean(),
             df.model_type.iloc[0]))

print()
print('=== headline: winners and median change (taxable parcels only) ===')
for k, df in d.items():
    t = df[df.is_fully_exempt == 0]
    print('%-10s n=%d | winners %.2f%% | median %+.2f%% | land mill %.4f'
          % (k, len(t), 100 * (t.tax_change_pct < 0).mean(), t.tax_change_pct.median(),
             df.land_millage.iloc[0]))

print()
print('=== revenue neutrality actually achieved? ===')
for k, df in d.items():
    t = df[df.is_fully_exempt == 0]
    cur, new = t.current_tax.sum(), t.new_tax.sum()
    print('%-10s current $%.4fB  new $%.4fB  gap %+.6f%%' % (k, cur/1e9, new/1e9, 100*(new/cur-1)))

print()
print('=== exempt parcels: are they really zeroed out? ===')
for k, df in d.items():
    e = df[df.is_fully_exempt == 1]
    print('%-10s exempt n=%d | current_tax sum $%.2f | new_tax sum $%.2f'
          % (k, len(e), e.current_tax.sum(), e.new_tax.sum()))

print()
print('=== mojibake check on property_category ===')
for k, df in d.items():
    bad = df.property_category.astype(str).str.contains('â€', na=False).sum()
    print('%-10s rows with cp1252 mojibake: %d' % (k, bad))
