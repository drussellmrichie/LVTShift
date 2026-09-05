# Vacant land: which surface is right, and what it costs to be wrong

Finding, 2026-08-27. Reproduce with `python scripts/vacant_land_ratio_study.py`.
Numbers here are a dated snapshot; re-run the script rather than trusting them.

## Why this mattered

Every Philadelphia result in this repo bottoms out in one disagreement. The OPA (assessor)
and LYCD (`zone_psf x area`) land surfaces differ by 46% on the taxable land base, and
**$11.6B of the $19.6B gap is vacant land alone**, where LYCD values parcels at roughly 4.9x
their entire OPA assessment. That single disagreement moves `kappa*` in the single-tax ledger
more than the capitalization rate, the capture share, the road-rent scenario and the
collection haircut combined, and it flips 14 tracts across the LVT-UBI win/lose line — the
high-minority, low-income North Philadelphia tracts where vacant land concentrates.

It is also, unusually for this project, **empirically decidable**. For a bare lot the sale
price *is* the land price, so the thing that normally makes land valuation hard — separating
land from structure — does not apply. Philadelphia records thousands of vacant-land sales.

## Method

Ratio study: assessed land value / observed sale price, both surfaces, same sales.
2,065 vacant-category sales since 2023 from OPA's own table, filtered for plausible lot area
and $/sqft and for the absence of a building record.

**Structure-presence correction.** `philly_open_avmkit` flags parcels recorded vacant that
carry a real Overture building footprint; their sale prices include a structure, so they are
not land sales. 15.4% of the sample. Excluded.

## Result

| Sample | n | OPA median | OPA COD | OPA agg | LYCD median | LYCD COD | LYCD agg |
|---|---|---|---|---|---|---|---|
| all vacant-category sales | 2,065 | 0.98 | 90 | 0.49x | 4.09 | 111 | 1.86x |
| genuinely bare land | 1,747 | 0.97 | 90 | 0.48x | 4.05 | 108 | 1.77x |
| bare land, sale >= $20k | 1,143 | 0.67 | 79 | 0.44x | 2.30 | 98 | 1.55x |

**LYCD over-values vacant land in every cut.** Aggregate 1.55–1.86x, median 2.3–4.1x. There is
no subsample where its vacant-land figures are supported by sales.

**OPA under-values it too, and by more than "conservative" implies** — about 0.44–0.49x in
aggregate, consistently. OPA is right at the *median* parcel and far too low in *aggregate*,
which is a regressivity signature, not a level error.

**The two surfaces bracket the truth from opposite sides, and the two independent corrections
land close together:** scaling OPA up by its own error implies ~$6.9B of citywide vacant land;
scaling LYCD down by its own error implies ~$9.4B. Against OPA's booked $2.99B and LYCD's
$14.55B, that agreement is the most convincing part of the result.

### First-order consequence for the models

Correcting only the vacant-land component of each surface:

| | Land base | R0 | kappa*(B5) |
|---|---|---|---|
| OPA | $43.0B -> $46.7B | $2.753B -> $2.987B | 0.602 -> 0.562 |
| LYCD | $62.6B -> $56.8B | $4.008B -> $3.637B | 0.385 -> 0.449 |

**The LYCD/OPA land-base ratio falls from 1.46x to about 1.22x.** The headline uncertainty
that dominated the LVT-UBI and single-tax results is mostly one correctable error, in one
property class, pointing in opposite directions on the two surfaces. Treat this as a
back-of-envelope correction, not a new surface: it rescales an aggregate rather than
re-valuing parcels.

## The result that was not expected

**COD is 79–111 on vacant land, against an IAAO standard of 20**, with PRD 1.9–3.5 (uniformity
wants ~1.0). Both surfaces are severely dispersed *and* severely regressive: cheap and small
lots over-assessed several-fold, expensive and large lots under-assessed by half.

`philly_open_avmkit`'s own scrutinized study (294 arm's-length 2025 sales) puts OPA at median
ratio **1.03, COD 58.6** — so proper sales scrutiny cuts the dispersion substantially, and
that number should be preferred for anything depending on dispersion. But even 58.6 is nearly
three times the IAAO standard, and the two studies agree closely on the level.

### Not all of that dispersion is the surface's fault

A vacant sale price is the land price plus transaction noise, and for vacant land that noise
is large: the sibling `property_valuation_simulations` project measures it on Philadelphia
repeat sales at **σ_e = 0.30–0.42 natural log per sale** (finding F45). A ratio study cannot
see the difference, so it charges the surface for dispersion the surface did not cause. That
noise alone produces **COD 25–36 against a perfect assessment**.

Backing it out (log-normal ratios, variances adding — an estimate, not a measurement):

| series | observed COD | surface COD net of noise |
|---|---|---|
| OPA, bare land ≥ $20k | 79 | 63–71 |
| LYCD, bare land ≥ $20k | 98 | 82–90 |
| OPA, `philly_open_avmkit` scrutinized | 59 | 42–50 |

**The finding survives; it is smaller than first published, not absent.** Every corrected
figure is still between two and four and a half times the IAAO standard of 20. Note this is a *different* mechanism
from the sales-scrutiny caveat below — scrutiny removes bad sales, whereas this noise is
irreducible and remains after perfect scrutiny.

This lands directly on Limitation 4 of `docs/LVT_UBI_GUIDE.md`, "assessment error becomes
confiscation at full capture", which the module could not previously quantify. For vacant
land it now can: with surface COD in the 40s–90s, effective capture `phi x (assessed / true)`
exceeds 100% of true rent for a substantial minority of parcels. **That remains a concrete
argument for stopping short of full capture** — and it bites hardest on exactly the property
class full capture is meant to reach. It is a weaker argument than the uncorrected COD made
it look, and the honest form is a direction, not a specific stopping point: the ledger's
`phi ~ 0.85` is not derived from these numbers, and deriving one would need a parcel-level
error distribution this study does not produce.

## What "vacant sales" leaves out (2026-09-05)

Everything above scores the two surfaces against sales of lots that are vacant *today*. That is
the only sample OPA's category code can give you, and it turned out to be the wrong sample for
the question the ordinance asks. `philly_open_avmkit`'s land-surface harness
(`notebooks/pipeline/run_land_surfaces.py`; generated report in `out/land/report.md`)
recovers two further streams of land evidence under the same scrutiny — lots that sold bare
and have *since been built on* (identified from `bldg_year_built` postdating the sale), and
improved parcels bought and demolished within a year of the sale (a new L&I demolition-permit
download). The mechanism finding: the three streams disagree by a factor of about three at the
median, and in a consistent direction — land nobody built on is the cheapest land in the city,
and land somebody bought to build on runs two to three times the price per square foot. Two
independent streams agreeing at roughly the same level, well above the still-vacant one, is
the strongest part of it.

Read every number in this document with that in mind. The "OPA under-values vacant land"
finding stands on the still-vacant sample; on the buildable streams OPA's ratio is closer to
one and LYCD's flips from far too high to too low. The level a land surface should be
calibrated to is not the still-vacant median, and the sibling harness scores every candidate
on all three streams, held out. Its headline: interpolating among the sales beats both a
published rate schedule and OPA's own land values by a measured margin; the schedule is
indistinguishable from OPA.

## Limitations

- The script's sales scrutiny is crude next to openavmkit's (a price floor, $/sqft bounds, no
  building record). The finding on the *level* is robust to it — two samples and two filtering
  regimes agree — but the *dispersion* numbers are inflated by non-arm's-length sales. Prefer
  the scrutinized study for COD.
- Selection: lots that trade may not represent lots that do not, and the ones that never trade
  are disproportionately the ones with no market at all — the population most exposed to
  abandonment under full capture.
- The correction rescales aggregates. A genuinely better surface would re-value parcels, which
  is `philly_open_avmkit`'s job, not this repo's.
- Sale dates span 2023–2026 against a TY2026 valuation date, with no time adjustment. This
  was flagged as a worry and is now measured: splitting the same cut by sale year moves COD by
  about 1% either way (OPA 79 pooled vs 78.2 within-year; LYCD 98 vs 98.6), so cross-year
  pooling contributes essentially nothing to the dispersion. It does move the *level* — OPA's
  median ratio drifts 0.77 (2024) to 0.62 (2026), consistent with prices rising against a
  static surface — so read the level as a mid-period average. Worth stating because the
  sibling project found the opposite for its own validation (its F25: restricting to a single
  sale year drove almost all of a 0.32 to 0.46 R² gain), and that mechanism does not transfer
  here.
- The noise-floor correction above assumes log-normal ratios and independence between surface
  error and transaction noise. Both are approximations, and F45's σ_e rests on 127 repeat
  pairs — enough to establish that the floor is large, not enough to pin it. It corrects no
  level: transaction noise is mean-zero in logs, so every median, aggregate and `kappa*` figure
  in this document is unaffected by it.

## Repo boundary

`philly_open_avmkit` owns the AVM, the sales scrutiny and the ratio-study machinery, and it
already produces a vacant-land model group and the structure-presence flag used here.
LVTShift owns only the choice of which land surface to model on. This script reads that repo
read-only and writes nothing to it.
