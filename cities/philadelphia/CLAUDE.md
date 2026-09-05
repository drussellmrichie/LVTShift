# CLAUDE.md — Philadelphia

Directory-scoped guidance for `cities/philadelphia/`. Split out of the root `CLAUDE.md` on
2026-08-28: these sections are ~48% of that file and are only needed when working on
Philadelphia, so they were costing every session for every city. Nothing was rewritten in the
move — the content below is verbatim, and the root file keeps a pointer to it.

Read this alongside the root `CLAUDE.md`, which holds the repo-wide rules these sections
assume: the two recurring failure shapes, the design patterns, the module map, and the
Documentation index. Where a rule below says "see the guard-shape rule above", it means the
root file.

Philadelphia has ten notebooks. Four follow the standard export convention —
`model.ipynb`, `model_lycd.ipynb` and their `_post_abatement` variants. Five more each follow
a different paradigm with its own export slug: `model_wage_tax_swap.ipynb`,
`model_lvt_ubi.ipynb`, `model_single_tax_ledger.ipynb`, `model_ocd_land_assessment.ipynb`, and
`model_lycd_reassessment.ipynb` (a tax-*base* shift, see "LYCD-land reassessment" below).
The tenth, `model_lycd_refined_prototype.ipynb`, is a prototype and is not part of any
documented pipeline.

## Philadelphia — OPA / Carto Data Patterns

Philadelphia parcel data comes from the **OPA (Office of Property Assessment)** via Carto, not ArcGIS FeatureServer. Use `requests` + Carto SQL API directly — `get_feature_data_with_geometry` will not work here.

**Data sources:**
- OPA properties (current): `https://phl.carto.com/api/v2/sql?q=SELECT ... FROM opa_properties_public&format=csv` — geometry is WKB in `the_geom` column, parse with `gpd.GeoSeries.from_wkb()`
- Assessment history: `https://phl.carto.com/api/v2/sql?q=SELECT ... FROM assessments WHERE year=XXXX&format=csv` — use this for billing-year taxable values

**Assessment vintage matters.** The current `opa_properties_public` table always reflects the *latest* assessment year. Philadelphia reassesses annually, so current OPA values may be 1–2 assessment cycles ahead of the billing year you're modeling. For FY2024 modeling, `assessments WHERE year=2024` (not the current OPA table) reduces the city-levy cross-check gap from +21% to +5%. Always specify `year=` and join back to current OPA for geometry + category codes.

**Revenue structure:** Philadelphia is consolidated city-county. The published 1.3998% rate is **city (0.6317%) + school district (0.7681%)**. City budget documents report only the city's ~$796M share; school district is a separate budget (~$970M). When modeling the combined rate, validate the city-only portion (0.6317% × taxable base) against city actuals. A ~5% gap is normal delinquency.

**Exemptions are already in OPA taxable columns.** `taxable_land` and `taxable_building` already net out the Homestead Exemption, 10-year construction abatement, and institutional exemptions. Do not double-apply these.

**LOOP and Senior Freeze are NOT in OPA.** Philadelphia's Longtime Owner Occupant Program (LOOP) and Senior Citizen Tax Freeze are administered by Revenue, not OPA, and are not available as public parcel-level datasets. They contribute a small portion of the revenue gap (~1–3%), with assessment vintage mismatch being the dominant factor.

**OPA land/building split:** ~45% of improved parcels have a land ratio of exactly 0.200 (OPA's default formula). Multi-family and commercial are especially affected. This attenuates split-rate impact. Document this limitation in the notebook.

**Philadelphia category classification uses four stacked overrides** (in order):
1. `taxable_building <= 0` → "Vacant Land" (catch-all for zero-improvement parcels)
2. Non-vacant OPA code AND `taxable_building <= 0` AND `taxable_land > 0` → split three ways by
   `lvt.philadelphia.split_zero_building_parcels` (see below)
3. Vacant OPA code (6/12/13) AND `taxable_building > 0` → "Improved Vacant Land" (OPA calls it vacant but carries a building record; ~1,500 parcels with small structures)
4. `full_exmp = 1` (both taxable values = 0) → "[OPA category] — Exempt" (reclassifies exempt parcels out of "Vacant Land" into typed buckets)

Always apply these in this order. Override 3 before Override 4 matters: the full-exempt check must come after the improved-vacant reclassification or some parcels can end up in the wrong bucket.

**A $0 taxable building line does not mean "abated" — it has three causes, and conflating them
silently revoked ~13K homesteaders' Homestead Exemption.** Override 2 originally treated every
non-vacant parcel with `taxable_building <= 0` as an active construction abatement. About half of
that cohort is instead an ordinary homesteaded rowhome whose building assessment is *smaller than
the Homestead Exemption*, so the exemption consumes the whole building line and spills onto land.
Those parcels then got the abated treatment — `model_building` restored from `exempt_building` —
which taxed away a homestead that every other homesteader in the city kept. By dollars the error
was invisible (the genuine abatements hold ~93% of the exempt building value, so the solved
millages barely moved), which is the guard-shape failure again: the aggregate that was checked is
not the quantity that broke.

The discriminator is the exempt total against the year's statutory Homestead Exemption, which is a
flat amount and so can never explain more than its own cap:
- `exempt_total > cap` → an abatement is present.
- `0 < exempt_total <= cap` → homesteaded parcel, restored to its OPA category. It keeps its
  exemption under the reform, so its $0 building line is already correct — do not impute one.
- `exempt_total == 0` → the improvement really is worth $0; leave it as Override 1 set it.

`split_zero_building_parcels` implements this and is shared by all six classifying notebooks
rather than copy-pasted (this bug was in all six). It takes the cap from
`tax_year_params(year).homestead_exemption` — never a literal, because the amount has moved four
times ($30K → $40K → $45K → $80K → $100K, empirically confirmed against the `assessments` billing
table) and the wrong year's cap moves parcels across the boundary with no visible symptom. It
guards itself against OPA's own per-parcel `homestead_exemption` flag and raises if fewer than 85%
of the parcels it called homestead-zeroed actually carry a homestead; a wrong cap drops that rate
to 6-24%.

**The homestead-zeroed parcels still show a large *percentage* increase (small in dollars), and
that is a real result, not residue of the bug.** Their entire remaining taxable base is land, so a
land-heavy millage hits all of it. Note this depends on OPA applying the Homestead Exemption to the
building line first and the remainder to land; had it been applied land-first these parcels would
show a *decrease*. The allocation is OPA's, not a modeling choice, but it is load-bearing for this
cohort.

**Abated parcels: restore the building value from `exempt_building`, do not impute it.** A parcel with an active abatement has `taxable_building = 0`, so it enters the split-rate base at LR=1.0 and looks like pure land. The reform scenario needs its real improvement value back. OPA already records it: `exempt_building` is the assessed building value being exempted, and `market_value − (taxable_land + exempt_land)` reproduces it to the dollar. Use it, with a `market_value − taxable_land` fallback for the mid-construction parcels where `exempt_building = 0`. Keep `current_tax` as actual (land-only). This previously imputed `model_building = 4 × taxable_land`, inverting OPA's 20%-land default ratio — a reconstruction standing in for an observed quantity, and biased: it recovered a median 0.72× of the recorded value (p10 0.23) and understated the restored base by ~20%. All four standard-export notebooks (`model.ipynb`, `model_post_abatement.ipynb`, `model_lycd.ipynb`, `model_lycd_post_abatement.ipynb`) now use the observed column, so each pre/post pair varies only the abatement treatment, and the OPA/LYCD pair varies only the land source, rather than also varying how the improvement value is estimated.

**`model_lycd.ipynb` briefly regressed to a `4 × land` imputation for abated parcels, on a rationale that was wrong even when written.** A version of that notebook reverted from `exempt_building` back to `model_building = 4 × model_land`, reasoning that `exempt_building` was "the post-abatement treatment" and that using it would make the pre-abatement LYCD scenario indistinguishable from `model_lycd_post_abatement.ipynb`. Both premises were false: restoring `exempt_building` only changes the reform-scenario building value, not `current_tax` (which stays land-only under the actual abatement either way), so it is not a post-abatement treatment. And once `model.ipynb` itself moved to `exempt_building`, the reverted `model_lycd.ipynb` differed from the OPA panel by imputation method *and* land source simultaneously — the opposite of the stated design goal of isolating land values alone. Fixed by restoring the shared pattern; see `docs/LYCD_LAND_MODEL_ROADMAP.md`'s former "open items" entry for the before/after numbers.

**Fully exempt SFR parcels are low-value homesteaders, not vacant lots.** ~27K SFR parcels with `market_value <= $80K` have their entire assessed value wiped out by the Homestead Exemption. They show up as `full_exmp=1` and end up in "Vacant Land" if not reclassified. Override 4 moves them to "Single Family Residential — Exempt."

**Kernel name:** On Windows, the `cle-venv-new` kernel may not be registered. Check `jupyter kernelspec list` and use the available kernel (e.g., `python3`) for `nbconvert --execute`.

**The four standard-export Philadelphia notebooks** are `model.ipynb` (OPA), `model_lycd.ipynb` (LYCD), `model_post_abatement.ipynb` and `model_lycd_post_abatement.ipynb`. All four export to `analysis/data/philadelphia*.csv` with a `parcel_id` column (via `parcel_id_col='parcel_number'` in `save_standard_export`). The wage-tax-swap, LVT-UBI, OCD and single-tax notebooks in the same directory each follow a different paradigm and export convention — see their sections below.

**The parcel cache is keyed by tax year: `cities/philadelphia/data/parcels_ty<YEAR>.gpq`.** Build it
with `python scripts/build_philadelphia_parcel_cache.py --year 2026`; the notebooks only read it and
raise a clear error if it is missing. The year suffix is deliberate — `opa_properties_public` always
carries the *latest* assessment year, so an unsuffixed cache makes it easy to model one year's
taxable values against another year's rate and revenue target with no visible symptom. The builder
emits the full column superset every notebook needs: the assessment value columns plus `pin` +
`total_area` (LYCD lot-area chain) and `owner_1` + `owner_2` (owner-concentration analysis in
`model.ipynb`). Keep `pin` integer-typed — the LYCD notebooks stringify it as a join key, and a float
dtype would add a `.0` suffix and break the PIN match. Also note Carto's `assessments.year` column is
varchar: the filter must be `WHERE year = '2026'` (quoted); an unquoted integer comparison returns
HTTP 400.

**Tax-year rates and revenue targets live in `lvt/philadelphia.py`, not in the notebooks.** Each
notebook sets `TAX_YEAR` and derives millage, the city-only cross-check rate, the validation target
and the cache path from `tax_year_params()`. This exists because the combined rate has been 1.3998%
for years while the *City/School split moved* (0.6317/0.7681 at TY2024 → 0.6159/0.7839 from TY2025),
so a hardcoded `city_only_rate = 6.317` keeps validating against the wrong denominator while nothing
about the combined-levy model looks wrong. Rates and targets are cited per year in that module. Note
TY2027 has **no** revenue target — its bills are not due until March 2027 — so the validation cell
skips the assert and labels the run forward-looking; its City/School split is carried forward from
FY2026 and is not independently confirmed.

**Lot area: never take a pre-computed `Shape__Area` from an ArcGIS service without checking the
service CRS.** The DOR parcels FeatureServer is EPSG:3857, where area is inflated by `1/cos^2(lat)`.
`scripts/fetch_dor_parcel_areas.py` fetches PIN-keyed areas and de-distorts them per parcel; the
notebooks assert total lot area stays under 1.5x the city. See the guard-shape rule above.

Worth knowing *why that barely moved the results*: LYCD land value is `zone_psf x area` where
`zone_psf` is itself `median(market_value / area)`, so the method is **exactly scale-invariant in lot
area** — a uniform area error cancels completely. Only *mixed* conventions and *relative* area errors
matter. Do not infer from the small headline movement that the area layer is unimportant; it is
load-bearing for any per-parcel land value and for anything that is not scale-invariant.

**Neither land surface is right about vacant land, and the error runs opposite ways.** Tested
against observed vacant-land sales (`scripts/vacant_land_ratio_study.py`): LYCD over-values it,
OPA under-values it, and correcting both cuts the LYCD/OPA land-base ratio from ~1.46x to ~1.22x
— so the surface disagreement that dominates every Philadelphia result here is mostly one
correctable error in one property class. Both surfaces are also severely dispersed on vacant
land (COD far above the IAAO standard), which is the quantified form of the LVT-UBI guide's
"assessment error becomes confiscation at full capture". Findings and limits:
`docs/VACANT_LAND_VALUATION.md`.

**Surface parking is hidden inside "Vacant Land", and only `building_code` separates it.**
OPA gives most parking lots `category_code = 6`, so the model's Vacant Land category
contains them. The separator is the `R*` building-code family: `RA` (non-commercial lot),
`RB` (non-paid commercial), `RE` (paid commercial), `^R[A-F]\d$` (lot with structure), plus
`^O[AB]\d$` for commercial parking garages. Three traps: `5R` is CONDO PARKING SPACE (~4.5K
individual deeded spaces, not lots — exclude); `R30`/`R10`/`R5x` are `ROW B/GAR` rowhouses,
so never match on `R*` alone; and `DD0`/`DE0` are office buildings whose descriptions merely
mention parking. `building_code` is **not** in the parcel cache — `analysis/ownership/philadelphia/fetch_opa_attributes.py`
pulls it as a sidecar. See `analysis/ownership/philadelphia/` for the ownership-by-type
analysis built on it, and note the City's Land Use layer is *not* a usable parking source
(it identifies ~200 parking parcels citywide against the assessor's ~2,200).

**OPA owner names truncate at two widths, 25 and 40 characters** — the length histogram
spikes at both. Truncation cuts the legal suffix off (`S&S REALITY INVESTMENTS L`), so any
LLC/corporation classifier is biased downward in a known direction: entities move *out* of
the LLC bucket, never into it. Treat every LLC share as a floor.

**`parcels.gpq` row order does NOT match the CSV row order.** Do not join by index. Verified: 480K out of 579K rows differ between `taxable_land` in `parcels.gpq` and `taxable_land_value` in `philadelphia.csv`. Always join on `parcel_id` ↔ `parcel_number` (stripping leading zeros: `parcels['parcel_id'] = parcels['parcel_number'].astype(str).str.lstrip('0').astype('Int64')`).

**`parcels.gpq` geometry is Point (OPA centroids), not polygons.** Its `geometry` column holds one
point per parcel — there is no lot-outline geometry in this cache. `scripts/build_philadelphia_webmap.py --geometry polygon`
upgrades ~90% of parcels to real DOR lot outlines by joining `parcels.gpq.pin` to a *different* file:
`cities/philadelphia/data/Philadelphia_DOR_Parcels_2023.geojson` (504 MB, WGS84, integer `PIN`
field). The sibling shapefile in `cities/philadelphia/data/dor_parcels/` looks like the obvious
choice (94 MB vs. 504 MB) but **has no `PIN` field at all** — only `PARCELID` and `TENCODE`, neither
of which matches `parcels.gpq.pin` — so it cannot be used for this join.

**The two scenario CSV encoding/data quirks the webmap build works around:**
- `philadelphia_lycd.csv` and `philadelphia_lycd_post_abatement.csv` write `property_category` as
  UTF-8 re-encoded through cp1252 (`Commercial â€” Exempt` instead of `Commercial — Exempt`). The
  OPA-land CSVs (`philadelphia.csv`, `philadelphia_post_abatement.csv`) do not have this problem —
  it is specific to whatever the LYCD notebooks' CSV write path does differently. Worth fixing at
  the source; the webmap build repairs it with a cp1252→UTF-8 round-trip rather than depending on it
  being fixed upstream.
- 10 `parcel_id` values appear twice across the export (14 rows total) with genuinely different
  attributes on each occurrence — not a formatting artifact. `881000395` is one example: one row is
  fully exempt, the other is an abated parcel with `current_tax = 1140.84`. Any downstream consumer
  that dedupes on `parcel_id` needs to do so *positionally* and identically across all four exports
  (they share one row order), not independently per file, or different scenarios can end up
  describing different physical parcels under the same id.
- LYCD pre-abatement's abated-parcel improvement-value imputation bug (was copy-pasted from the
  post-abatement notebooks) is fixed — see the "`model_lycd.ipynb` needs the same abated-parcel
  imputation" note earlier in this section.

**GDAL cannot read GeoParquet in this environment on either side.** Ubuntu's `gdal-bin` (used for
the webmap's tile build in WSL) ships no Parquet/Arrow driver and no plugin package supplies one.
Separately, the Windows conda `gdal`/`pyogrio` install fails outright (`GDAL DLL could not be
found`), so no vector I/O of any format works from Windows Python. Do not assume `ogr2ogr -f Parquet`
works just because `ogr2ogr` is on PATH — check `ogr2ogr --formats` for the format you need.

## Philadelphia — LYCD-land reassessment (`model_lycd_reassessment.ipynb`)

Models OPA's current methodology and flat combined rate with **only the land component re-valued
by LYCD**, rolled back to revenue neutrality via `lvt.reassessment` — the tax-base question that
precedes any rate change. Export: `analysis/data/philadelphia_lycd_reassessment_ty<YEAR>.csv`,
`MODEL_TYPE = 'reassessment:lycd_land_ty<YEAR>'`; `new_tax` is the flat-rate reassessment, and the
stacked 4:1 split-rate lives only in the `reassess_change` / `lvt_change` / `total_change`
decomposition columns. Background and the method's limits: `docs/LYCD_LAND_MODEL_ROADMAP.md`.

Two shared functions in `lvt/philadelphia.py` carry the modeling choices, so the notebook cannot
drift from the LVT notebooks by construction:

- **`compute_lycd_land_values`** is the LYCD construction (lot-area chain, GMA-hierarchical zone
  medians, KNN fallback, improved-only market-value cap) as one function with a diagnostics dict.
  All four LYCD notebooks now call it — `model_lycd.ipynb`, `model_lycd_post_abatement.ipynb`,
  `model_lycd_refined_prototype.ipynb` (all migrated 2026-09-04) and
  `model_lycd_reassessment.ipynb`. Every migrated notebook's re-executed output was bit-for-bit
  identical to its prior inline construction, including the refined prototype's two
  refinements. `model_lycd_reassessment.ipynb` additionally asserts its land base over taxable
  parcels equals the tracked `philadelphia_lycd_ty<YEAR>.csv` export's `taxable_land_value` sum
  to 1e-6 relative — identical construction on identical inputs, so any difference means a
  stale export or a divergence.

  **The KNN fallback now imputes a rate, not a dollar value** (2026-09-05): an unmatched
  parcel takes the median $/sqft of its nearest neighbours and applies it to its OWN area,
  instead of inheriting a neighbour's dollar land value regardless of size. Re-executing all
  four notebooks with this fix moved the citywide land base from $62.54B to $66.19B over
  taxable parcels (ratio 1.44x to 1.54x of OPA's) — a real, no-downside correction, not a
  refactor, so all four notebooks' numbers moved.

  **The market-value cap has an opt-in `cap_include_building` parameter, off by default —
  do not turn it on without reading its docstring first.** It closes a real, large problem
  (24.4% of taxable parcels already have land + building above market_value under the plain
  cap, $9.31B in aggregate) but at a cost the roadmap's original "cap land plus building at
  market" framing did not anticipate: since `market_value` is OPA's own
  `taxable_land + taxable_building`, the tightened cap reduces to capping land at
  essentially OPA's own estimate for any otherwise-uncapped parcel, dropping 23.9% of
  single-family parcels to exactly OPA's ~0.20 default ratio and cutting the citywide
  LYCD/OPA ratio from 1.54x to 1.32x. Left off — not the recommended fix for this problem.

  **The recommended fix is `compute_residual_building_value` + `carry_forward_exemptions`'s
  `gross_building_override`, wired into all three split-rate LYCD notebooks**
  (`model_lycd.ipynb` 2026-09-06; `model_lycd_post_abatement.ipynb` and
  `model_lycd_refined_prototype.ipynb` 2026-09-07). Holds land at LYCD's full value and lets
  BUILDING absorb the correction instead (`market_value - land`, then exemptions
  re-applied so they net exactly once) — no collateral damage to the land finding, unlike
  the cap option. Restricted to non-abated parcels already in today's taxable base
  (`full_exmp == 0`) — deliberately not extended to homestead-wiped re-entry, which is
  `model_lycd_reassessment.ipynb`'s question, not these notebooks'; each notebook asserts
  zero re-entries as a guard that this restriction is doing its job, plus a no-overshoot
  assertion (non-vacant, ordinary-taxable) on every run. All three re-executed cleanly,
  revenue exactly neutral, reform improvement base falling from $126.21B to $121.97B in
  `model_lycd.ipynb` and `model_lycd_post_abatement.ipynb` (identical, since both build the
  reform base from the same land and the same exemption logic) and to $120.75B in the
  refined prototype (whose larger LYCD land base makes the same correction slightly
  larger). `model_lycd_reassessment.ipynb`'s drift check (which reads `model_lycd.ipynb`'s
  exported land base, untouched by any of this) still passes.

  **One sharp gotcha, worth re-reading before touching this code: abated parcels must be
  excluded from the `carry_forward_exemptions` call entirely, not passed through it with an
  override.** That function's exemption-netting always subtracts a parcel's own historical
  exempt total from whatever building value it is given; for an abated row that total IS
  `exempt_building`, so supplying it back as the override cancels it to zero instead of
  preserving it. A synthetic unit test that looked like it caught this passed anyway, because
  it was comparing two calls that were equally wrong to each other — the real cache is what
  actually caught it ($16.4B silently zeroed). Every notebook's Step 6 keeps its abated
  cohort on its existing `exempt_building` restoration (in `model_lycd_post_abatement.ipynb`,
  on whatever Step 5's post-abatement baseline already set for it), entirely separate from
  this mechanism. See `docs/LYCD_LAND_MODEL_ROADMAP.md` Stage A item 4 for the full account
  and the exact numbers.

  Two of the function's parameters exist only for the refined prototype and default to the
  base behavior for everyone else: `zone_group_col` (a column name; when given, zone medians
  are computed per (group, GMA level) cell instead of pooling every improved parcel type
  together — the prototype's Q2 refinement) and `land_pct_improved` accepting a per-parcel
  `pandas.Series` in addition to a scalar (the prototype's Q1 refinement, an FHFA tract land
  share for core-residential categories). Both refinements' Philadelphia-specific inputs — the
  FHFA join, the residential-context and core-residential category sets — stay in the
  notebook; only the zone-median and land-value math itself moved into the shared function.
- **`carry_forward_exemptions`** is the rule for "same methodology, land valued differently":
  the Homestead Exemption is re-applied as `min(cap, new total)`, building-first (so a homestead
  whose LYCD land lifts it above the cap becomes taxable again — the "re-entering" cohort);
  abatement and partial relief are carried forward in dollars (the building value is unchanged
  by a land reform, so an abatement's dollars are exactly right); a full institutional exemption
  is a rate, not an amount, and stays. The homestead keys off OPA's per-parcel
  `homestead_exemption` dollar column AND an exemption actually applied this vintage, because
  the flag is current-vintage. **Its guard is a reconstruction**: OPA's own gross land fed through
  the same rule must reproduce OPA's taxable total per parcel (the floor is 95%; the observed rate
  is printed). That is the number that would move if the rule mis-described the exemptions.
- **`reallocate_land_within_total`** (2026-09-05, notebook Step 6b) is the *other* reading of
  "LYCD land, rates unchanged" — the one the draft § 2-305 land-assessment ordinance describes.
  It holds OPA's **total** fixed instead of OPA's building: `alloc_land = min(new_land, total)`,
  `alloc_building = total − alloc_land`, statutory rate untouched. The two functions share one
  private exemption decomposition (`_decompose_exemptions` / `_apply_exemptions` /
  `_reconstruction_guard`) so they cannot disagree about what a parcel's exemptions *are*, only
  about what is held fixed. Consequence, asserted in the notebook on every run: with total and
  rate fixed, the only bills that can move are those whose exemption depends on the split —
  abatement-type relief (`exemption_kind == 'building_share'`); homestead, partial relief on
  total value, and vacant parcels are bit-for-bit unchanged. Two things the synthetic tests
  did not catch and the real cache did: (1) relief that fits inside the building line but is
  split pro-rata across land and building is a share of *total* value, not an abatement —
  classify on `exempt_land` net of homestead spill, not on fit alone; (2) read the effect off
  `.reform_change` (rule on new land minus rule on OPA's land), never against OPA's *recorded*
  taxable total, or the rule's 0.5% reconstruction residual (parcels whose recorded homestead
  disagrees with the relief applied) shows up as a tax change on parcels the reform cannot
  touch. Export columns: `alloc_*`, `exemption_kind`, `norollback_new_tax`, `abated`,
  `market_value`, `taxable_total`, `dor_area_sqft`, `lycd_zone_psf`, `gma3` — the last five
  exist so the report generator can run the ordinance's uniformity tests without the cache.

- **`paint_land_surface`** (2026-09-05, notebook Step 2b, `LVT_LAND_SURFACE=<column>`) swaps
  an externally estimated land **rate** onto this repo's parcels. The surface comes from
  `philly_open_avmkit/notebooks/pipeline/run_land_surfaces.py` (`out/land/land_surfaces_ty<YEAR>.csv`,
  keyed `parcel_number`, several candidate $/sqft columns; `s2_k20` is the sales-interpolated
  surface, `s3` the schedule). It imports a rate, never a dollar value, and multiplies by this
  repo's own `dor_area_sqft` — the two repos' areas agree within 5% on 99.9% of joined parcels,
  but a rate keeps them decoupled by construction. Coverage is why it is a function and not a
  merge: about 55k parcels (a fifth of market value) are not in the AVM universe; they take the
  median rate of their nearest matched neighbours via the same `_knn_median_fill` LYCD uses and
  are flagged `land_surface_source == 'knn'`. The improved cap is LYCD's, so a swap changes the
  rate and nothing else; `n_land_exceeds_total` counts where the surface's land alone exceeds
  OPA's total before the cap (a § 3(c) finding about the totals). The export slug and
  `MODEL_TYPE` carry the surface name so runs never overwrite the LYCD export, and every
  downstream step (both readings, the assertions, the census join) is surface-agnostic.

The PPI report on both readings and the ordinance's own tests lives in
`analysis/lycd_reassessment/philadelphia/paper/` (generator-driven; `Report.tex` carries no
literals). Its mechanism-level findings are summarized in `docs/LYCD_LAND_MODEL_ROADMAP.md`
under "Against the draft ordinance".

Two things to keep straight when reading its output. The LVT notebooks do *not* re-apply the
homestead to LYCD land (their `model_building` is post-exemption, their land is gross), so their
SFR land base is slightly larger than this notebook's — a known simplification there, not a
discrepancy. And the `knn` lot-area-source cohort (condo units and other records with no lot of
their own) is a cap artifact, not a land-value finding; the notebook says so where it prints it.

## Philadelphia — Wage Tax Swap

`cities/philadelphia/model_wage_tax_swap.ipynb` is a fifth Philadelphia notebook, but it doesn't
follow the standard 7-section template or the standard `analysis/data/philadelphia*.csv` naming —
it models eliminating the Wage & Earnings Tax (not the property tax) and replacing it with a new
land-only tax, at census tract granularity. See `docs/WAGE_TAX_SWAP_GUIDE.md` for the full
methodology. Key gotchas found while building it:

- **ACS table B19062, not B19061.** `B19062` is "Aggregate Wage or Salary Income for Households"
  (wages only); `B19061` is "Aggregate Earnings" (wages + self-employment). Philadelphia's
  self-employment income is captured by the separate Net Profits Tax, so `B19061` would overstate
  the Wage Tax base.
- **TIGERweb tract boundaries are `Tracts_Blocks/MapServer/4`** ("Census Tracts", polygon
  geometry) — the direct sibling of the block-group Layer 1 already used in
  `get_census_blockgroups_shapefile()`. Layer 8 in the same service (used elsewhere in
  `census_utils.py` for block-group chunking) returns tract *numbers* only, not polygons — don't
  reuse it for boundaries.
- **A pure land-only tax reuses `model_split_rate_tax`, not a new solver.** Passing an all-zero
  improvement-value column makes the existing closed-form solve collapse to exactly
  `land_millage = target_revenue * 1000 / total_land_value` for *any* `land_improvement_ratio` —
  an exact identity (the improvement term's revenue contribution is `0 * improvement_millage = 0`
  regardless of ratio), not an approximation. `lvt.wage_tax_utils.model_land_only_tax` wraps this.
- This notebook reads the shared `cities/philadelphia/data/parcels.gpq` cache read-only — it does
  not build or rebuild it. Run `model.ipynb` first if the cache doesn't exist yet.

## Philadelphia — LVT + UBI (full land-rent capture)

`cities/philadelphia/model_lvt_ubi.ipynb` is a sixth Philadelphia notebook and a third modeling
paradigm: tax 100% of annual land rent, leave the building tax exactly as billed, hold the City and
School District harmless on the land portion of their current revenue, and pay the residual out as
an equal per-capita dividend. Module `lvt/ubi_utils.py`, report `lvt.viz.create_lvt_ubi_report`,
tests `tests/test_ubi_utils.py`, methodology `docs/LVT_UBI_GUIDE.md`. Slug is
`philadelphia_lvt_ubi_ty<YEAR>` (plus `_lycd`), outside the `analysis/data/philadelphia*.csv`
convention. Gotchas worth knowing before touching it:

- **It is deliberately not revenue-neutral, so `save_standard_export` and `create_city_report` do
  not apply.** Raising more than today's levy is the reform. There is no revenue target to solve a
  millage against — the rate is exogenous — so `lvt/ubi_utils.py` never calls
  `model_split_rate_tax`. Do not "fix" that by adding a solver.
- **The gross-up is `(i + t)`, not `i`.** Assessed land value is a market price that already
  capitalizes today's land tax, so annual site rent is `L * (discount_rate + combined_rate)`. At
  `i = 5%` that is 28% more rent than `L * i`. `discount_rate` is a *net* cap rate (`r − g`), not a
  raw discount rate.
- **`taxable_land` is post-exemption, so the rent basis is a policy choice.** `taxable_land +
  exempt_land` is the full assessed land; `RENT_BASIS = 'full'` charges rent on it. The clean
  `tax_change = i * L` identity only holds on the taxable basis, where the rent basis and the
  current-tax basis are the same column.
- **This notebook deliberately skips `model.ipynb`'s abated-parcel imputation**
  (`model_building = 4 × taxable_land`). That exists so a revenue-neutral split-rate solve does not
  see an artificially land-only parcel; here the reform never touches the improvement base, so
  current law — a $0 building bill during the abatement — is the correct counterfactual.
- **The export sign convention inverts versus the wage-tax swap.** There `net_change > 0` means a
  tract pays more; here `net_gain > 0` means the tract's residents come out ahead, and the map uses
  `RdYlGn` rather than `RdYlGn_r`. This is why `create_lvt_ubi_report` is a separate function and
  not `create_wage_tax_swap_report` with renamed columns — a rename would silently invert the maps.
- **`net_gain` subtracts `tax_change`, not `new_land_tax`.** Held harmless, the taxing bodies keep
  the land tax the parcel already pays, so counting the whole levy against residents double-counts
  it. The correct subtrahend makes the reform exactly zero-sum: `sum(net_gain) == 0`, which the
  notebook asserts.
- **The capitalization rate sets magnitude, not the winner/loser split.** A tract's net position is
  `i * (sum(L) * pop_j / P − L_j)`, whose sign does not involve `i`; scaling every land value by a
  constant scales every net position by the same constant. So `i` and any *uniform* assessment bias
  are scale knobs — only *non-uniform* assessment error redistributes. Section 9 demonstrates this
  by asserting the net-positive tract set is identical at 3%, 5% and 9%.
- **The levy is not a millage.** At 100% capture land value capitalizes to zero, so the ad-valorem
  base vanishes and OPA would have to assess rental values it does not publish.
  `implied_land_millage_equivalent` (= `phi*(i+t)*1000`, 64.0 mills at the defaults, against 13.998
  today and 29.0 under the 4:1 split-rate) is a comparability aid, not an implementable rate.
- **Wiring-check magnitudes live in the notebook's own asserts, not here.** Section 6's magnitude
  gates and Section 8's zero-sum check are the reference; a failure there is a data-wiring problem,
  not a formula problem, because the arithmetic is proven offline by `tests/test_ubi_utils.py`.
  LYCD land runs materially larger than the OPA base — read the current ratio off the notebook, and
  see the guard-band caution above before assuming a figure for it.
- **`land_value_col` is the BASELINE, `rent_basis_col` is the rent surface — never conflate
  them.** The current tax is always rebuilt on the assessor's land; only the rent is priced off
  `model_land` (`LAND_VALUE_SOURCE = 'lycd'`) or `full_assessed_land` (`RENT_BASIS = 'full'`).
  Passing the rent surface as the baseline invents a bill nobody was sent, and nothing downstream
  notices — so **always pass `baseline_total_col='taxable_total'`**, which verifies the
  reconstruction against the billed total and raises on drift. The held-harmless credit is then
  `t * taxable_land`, forced rather than chosen: the building tax is stipulated unchanged and the
  baseline is the real levy, so the credit is the residual. Under a divergent surface identity 1
  no longer collapses to `i*L` (`summary['rent_basis_matches_current_basis']` reports which form
  applies) and the winner/loser partition is *near*- rather than exactly rate-invariant.
  Derivation and magnitudes: Limitation 19 in `docs/LVT_UBI_GUIDE.md`.
- **Rates come from `tax_year_params()`.** Never hardcode 0.013998.

## Philadelphia — Single-Tax Static Ledger

`cities/philadelphia/model_single_tax_ledger.ipynb`, module `lvt/single_tax.py`, tests
`tests/test_single_tax.py`, spec `docs/SINGLE_TAX_LEDGER_SPEC.md`, kappa evidence
`docs/KAPPA_CAPITALIZATION_EVIDENCE.md`. Tier-1 answer to "can Philadelphia land rent fund
abolishing its taxes on labor and capital?" Audited twice (self-check 2026-08-26, independent
2026-08-27); all findings applied.

- **`kappa` is a swept parameter, not an estimate.** `kappa*` is the uniform share of an
  abolished tax that must reappear as site rent for a bundle to break even, and it depends on
  no assumed `kappa`. `KAPPA_BOUNDS` brackets each family with published estimates, but those
  feed only the `pot_`/`dividend_` columns. Every scenario value traces to a citation
  (`test_every_kappa_scenario_value_traces_to_a_bound`); do not add one that does not. Current
  values ship as `analysis/data/philadelphia_single_tax_ty2026_kappa_bounds.csv` — read them
  from there, never from this file.
- **The `wage` high bound is a CEILING, not a central estimate.** Jacob & Livas (2026)'s
  Philadelphia GE counterfactual *assumes* an open city, which forces all incidence onto land;
  their flow object also includes structure quasi-rent that a land-only levy cannot reach.
  Promoting it to a central value would present an assumption as a finding, and nothing
  estimates the band's interior. Derivation and conditions: evidence doc section 4.
- **The land tax is absorbed, never abolished.** `T_land` enters Target once per bundle;
  `validate_ledger` raises if a bundle contains it. Easiest way to get a wrong answer here.
- **PICA is a separate line and it is big.** The City General Fund wage figure is *not* the
  wage tax — the full burden is City + PICA, reconciling exactly to the City's remittance
  account in QCMR Table R-4 (test-asserted). `model_wage_tax_swap.ipynb`'s figure is an
  earlier vintage; do not mix them. Stranding PICA is a legal constraint, not just an
  accounting line: that revenue services PICA bonds.
- **Use receipts for NPT and BIRT, never rate x base.** Taxpayers credit 60% of BIRT against
  NPT, so published receipts are already net; recomputing either from a base double-counts.
- **The haircut `h` applies to R0 AND to the capitalized increment**:
  `Supply = phi*(1-h)*(R0 + sum(kappa_j*T_j)) + G`. Do not "simplify" it back to `h` on R0
  alone — the only defense for that asymmetry is that abolition-increment rent accrues to
  already-compliant parcels, which nobody has evidence for. Pinned by
  `test_haircut_applies_to_r0_and_to_the_capitalized_increment`.
- **`kappa* > 1` is NOT "impossible"** — it requires super-ATCOR capitalization, which
  Gaffney's EBCOR (Excess Burden Comes Out of Rents) makes possible for exactly the
  distortionary taxes this program abolishes. But do not overread how *attainable* it is:
  it needs `theta*(1 + MEB/revenue) > 1`, which at the sourced landowner shares means `theta`
  near 0.64-0.81, i.e. essentially the perfect-mobility ceiling.
- **The ATCOR convergence needs both `kappa = 1` and `phi = 1`**, and includes `G`; at
  `phi < 1` bundles diverge. Pinned by `test_atcor_convergence_holds_only_at_full_capture`.
- **Road/curb rent `G` is net-new, status `modeled_sibling`, never `verified`.** Levels come
  from `philly-cordon-pricing` run artifacts, read from committed JSON rather than that repo's
  prose, and pinned by `test_road_rent_amounts_match_sibling_run_artifacts`. Curb is
  deliberately **zero**: Act 84 of 2012 already routes PPA on-street revenue to the City and
  School District, so counting it as new supply lets one dollar fund both today's spending and
  the abolition; only the unestimated efficient-pricing increment would be net-new.
  `road_rent_frame()` prints the excluded line so the omission stays visible.
- **Ledger vintage is FY2026 QCMR current projection**, matching the TY2026 property
  modelling; `LEDGER_VINTAGE = 'FY2025'` gives actuals as a sensitivity. School Income Tax and
  Use & Occupancy are `estimate` status and print a loud runtime warning; they appear only in
  bundles B4/B5. Amounts and sources:
  `analysis/data/philadelphia_single_tax_ty2026_lines.csv`.
- **The property split comes from the OPA run only.** The notebook reads only
  `taxable_land_value` from the LYCD export, passes `land_value_col='land_opa'` as the
  baseline for every case, and sets `baseline_total_col='taxable_total'` — see the LVT-UBI
  baseline rule above.
- **Accrual convention is billed, by decision.** Billed keeps the property lines identical to
  the LVT-UBI model, preserves the B0 wiring check, and is the conservative direction — it
  overstates `kappa*`. Pass `collection_rate=DEFAULT_COLLECTION_RATE` for the collected basis.
- **Unlike the LVT-UBI model, `i` is not a pure scale knob here** — it moves `kappa*`,
  because Target is denominated in tax dollars that do not scale with `i`.
