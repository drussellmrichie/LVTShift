# From LYCD to an assessor-grade land model

Design note, 2026-09-04. What LYCD is, what it is not, which of its defects are tunable inside
the method, and what a land model an assessor could actually adopt would look like. Mechanism
only: every number this note leans on lives in a generated or dated artifact, cited inline,
and should be re-read there rather than here.

## What LYCD is

LYCD ("Least You Can Do") estimates a parcel's land value as

    land_value = zone_land_psf x lot_area
    zone_land_psf = median(market_value / lot_area over improved parcels in the zone) x k

with `k = 0.20` for improved parcels and `k = 1.00` for vacant ones, the zone taken from OPA's
own Geographic Market Area hierarchy (L3 if it holds enough improved parcels, else L2, else
L1), and improved-parcel land clipped at the parcel's own market value. The construction is
shared by every Philadelphia notebook through `lvt.philadelphia.compute_lycd_land_values`.

In the appraisal literature this is the **allocation** method: land as a share of total value.
IAAO's mass-appraisal standard lists allocation last among land techniques, to be used where
vacant sales are absent. That is the honest description of LYCD's role in this repo: a floor
that breaks OPA's default-ratio collapse (most improved parcels sit at exactly 0.200 land
ratio) using OPA's own geography and OPA's own totals, so that a split-rate *distribution* can
be modeled without waiting for a reassessment. It is not a land valuation, and the audit trail
says so in four places (`analysis/audits/philadelphia_four_scenario_audit_2026-08-08.md`).

Two properties of the construction matter for everything below:

- **Scale-invariant in lot area.** Because the zone rate is itself `median(value / area)`, a
  uniform area error cancels exactly. Only *mixed* area conventions and *relative* area errors
  move results, which is why the Web Mercator area defect was invisible in the headline and
  catastrophic per parcel.
- **`k` is not a land share.** It multiplies a zone-median *total* $/sqft. The realized land
  share at `k = 0.20` differs from 0.20 and varies by parcel, so calibrating `k` to an external
  land-share estimate is a category error (audit, finding 3 and the refuted-candidates list).

## What is wrong with it, in order of consequence

| Defect | Evidence | Fixable inside the method? |
|---|---|---|
| Vacant land priced at 100% of the zone-median *improved* rate | `docs/VACANT_LAND_VALUATION.md`: LYCD over-values bare land in every cut; OPA under-values it; correcting both closes most of the LYCD/OPA land-base gap | Yes, with sales |
| Flat `k = 0.20` for every improved parcel | Audit finding 3: the OPA-vs-LYCD winner comparison reverses under the FHFA-calibrated prototype | Partly (per-cell share) |
| Linear in lot area | Sibling ratio study: PRD far above 1.0 on vacant land; `philly_open_avmkit` measures a negative partial correlation of $/sqft with log area and a positive one with frontage/depth | Yes |
| KNN fallback imputes neighbours' dollar land value, not zone $/sqft times own area | Audit finding 5 | Yes, trivially |
| Records with no lot area of their own (condominium units above all) take a neighbour's whole-lot area, then hit the cap at 100% of unit value | `model_lycd_reassessment.ipynb` Step 7, the `knn` lot-area-source row | Needs a per-unit share of the building lot, not a tuning |
| Cap clips land to market value, leaving a cohort at land ratio 1.00 with positive building value | Audit finding 2 | Yes |
| Hard L3 medians step at zone boundaries | Not quantified | Yes (smoothing) |

The first row dominates. It is the one defect that is *empirically decidable*: for a bare lot
the sale price is the land price, and the city records thousands of them.

Separately, read every COD on Philadelphia vacant land against its noise floor. The sibling
`property_valuation_simulations` project measures per-sale transaction noise on Philadelphia
repeat sales large enough that a perfect assessment would still show a COD in the mid-20s to
mid-30s (`docs/VACANT_LAND_VALUATION.md`, "Not all of that dispersion is the surface's
fault"). A land model that hits IAAO's 20 on a naive ratio study is not the target; one whose
COD net of noise approaches it is.

## Stage A: tuning inside the method

Each of these keeps `zone rate x area` as the published form and is days of work. Validate every
step with `scripts/vacant_land_ratio_study.py`; success is a median ratio near 1.0 and a PRD
near 1.0, with COD read net of the noise floor.

1. **Calibrate the vacant leg to sales.** Replace `k = 1.00` with a per-zone vacant $/sqft
   fitted on scrutinized, time-adjusted vacant sales, falling back up the GMA hierarchy where
   sales are thin. `philly_open_avmkit` already has the scrutinized sales, the bulk-deed
   filter, and the structure-presence flag that removes "vacant" sales carrying a building.
2. **Derive the improved-parcel share per cell instead of assuming it.** The openavmkit LYCD
   branch derives `k` as `median vacant $/sqft / median improved $/sqft` per zone-group cell.
   Feed it the *sales-based* vacant rate from step 1, not OPA's vacant assessments, or the
   share inherits OPA's under-assessment of bare land. The FHFA tract shares used by
   `cities/philadelphia/model_lycd_refined_prototype.ipynb` remain a single-family cross-check.
3. **Add a size curve and a buildability flag.** `land = rate x area^beta` with `beta < 1`, a
   frontage-to-depth term, and a sub-minimum-lot dummy from the zoning dimensional table
   transcribed in `philly_open_avmkit` (`data/philly_zoning_dimensions.csv`). The sibling
   repo's Ridge calibration measured all three effects on vacant sales. This is what moves PRD
   toward 1.0, which is the regressivity problem.
4. **Fix the KNN and cap forms.** Impute the zone $/sqft and multiply by the parcel's own
   area. Cap land plus building at market, or better, cap land at market minus depreciated
   structure cost (the extraction method).
5. **Smooth the rate surface.** Replace hard L3 medians with a kernel-weighted rate so two
   sides of one street get one land rate. Boundary cliffs are what appeals litigate.

Stratifying the zone median by residential versus non-residential context (the prototype's
second refinement) is cheap and worth keeping, but it is an input-quality step, not a valuation
step.

## Stage B: what an assessor-grade land model looks like

Three evidence legs feeding one reconciled land-price surface, then a published schedule.

1. **Vacant-land sales model.** Direct evidence. A smoothed spatial surface plus lot size,
   shape, zoning and buildability, corner, topography, and structure presence. The sibling
   repo has the sales and most features; its generic vacant AVM currently trails OPA on COD,
   so this leg needs the land-specific features rather than the residential feature set.
2. **Extraction from improved parcels.** For residential, the Kolbe et al. semi-parametric
   decomposition already runs city-wide in `philly_open_avmkit` and is calibrated on vacant
   sales (`out/models/kolbe_eval.md`). Commercial has no Kolbe estimate; use cost-approach
   extraction (improved value minus depreciated replacement cost), which is how assessors do
   it and which OPA's building attributes support.
3. **Teardown sales.** Improved parcels sold and then demolished are land sales. Join RTT
   sales to L&I demolition permits (already downloaded by the sibling repo's commercial
   enrichment). This is the only land evidence inside built-out rowhouse fabric where vacant
   sales do not exist, which is most of the city.

Reconcile the three into a single $/sqft surface, then express every parcel as
`base rate x area x listed adjustments`. That table is the assessor-grade LYCD: the same
structure the method has now, with the base rate estimated from land evidence rather than
from a fifth of total value. A schedule with adjustments is something OPA can adopt and the
Board of Revision of Taxes can review. A gradient-boosted surface is not.

What makes it usable as the basis of an LVT, beyond accuracy:

- **A land-specific ratio study**, stratified by ward, price decile, and tract income and
  race, within IAAO tolerances. `agc_assessments` (Allegheny, not Philadelphia) is the worked
  template for the stratified form; `dc-lvt-assessment-legislation` drafts the statutory ask
  that makes such a study mandatory.
- **A stated method that decomposes each parcel's value**, so an appeal can contest a specific
  adjustment rather than a black box.
- **An annual update path** using time-adjusted sales.
- **An explicit rule, not a model, for parcels with no market**: side yards, sub-minimum lots,
  assemblage remnants. These are the population most exposed under full capture, and both
  current surfaces are worst on exactly them.

## Repo boundaries

`philly_open_avmkit` owns sales scrutiny, the AVM, the Kolbe decomposition and the ratio-study
machinery; that is where Stage B is built. LVTShift owns the choice of which land surface to
model on, the tax mechanics, and the distributional analysis. Stage A steps 4 and 5 are
LVTShift changes to `compute_lycd_land_values`; steps 1 to 3 need sales and so belong in the
sibling repo, with LVTShift consuming a per-parcel surface keyed on OPA `parcel_number`.

## What was built alongside this note

`cities/philadelphia/model_lycd_reassessment.ipynb` models the *reassessment* question that
precedes any rate change: OPA's current methodology and flat rate, with only the land component
re-valued by LYCD, rolled back to revenue neutrality. It uses the `lvt.reassessment` machinery
and the shared LYCD construction, carries every parcel's existing exemptions forward under the
rule documented in `cities/philadelphia/CLAUDE.md`, and then decomposes a stacked
reassess-then-split-rate shift into its two components. Its export is
`analysis/data/philadelphia_lycd_reassessment_ty<YEAR>.csv`.

## Open items

- Lars Doucet's write-up of the method (`openavmkit/valuing land - the simplest viable
  method.pdf`) is image-only and was not machine-readable when this note was written; check
  whether it already specifies any of the Stage A refinements before implementing them.
- No published artifact yet carries the land-share band the audit asked for (finding 6).

## Resolved

- **`model_lycd.ipynb`'s abated-parcel building imputation** (2026-09-04). The notebook had
  regressed to `model_building = 4 x model_land` for abated parcels, while `model.ipynb`,
  `model_post_abatement.ipynb` and `model_lycd_post_abatement.ipynb` all restore the observed
  `exempt_building` value. Fixed to match; re-executed. Reform improvement base moved
  $118.53B -> $126.21B (abated bldg base $8.53B -> $16.21B), land millage 23.23 -> 22.76 mills,
  improvement millage 5.81 -> 5.69 mills. The LYCD land base itself is untouched
  ($82.37B all parcels, $62.54B over taxable parcels) since the fix only touches building
  imputation. See `cities/philadelphia/CLAUDE.md` for the full account of why the earlier
  revert's rationale was wrong.
