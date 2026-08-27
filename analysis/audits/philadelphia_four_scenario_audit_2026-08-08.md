# Audit — Philadelphia four-scenario LVT models (OPA vs LYCD land values × pre- vs post-abatement), 2026-08-08

Point-in-time record: the numbers below are what the artifacts said on 2026-08-08 and are
deliberately not maintained. Current values live in `analysis/data/philadelphia*.csv` and the
notebooks under `cities/philadelphia/`.

> **Verification history.** A first draft of this report was written before the adversarial
> verification pass (workflow step 3) had been run. Eight independent refuters were then given each
> Blocking/Material finding — file paths and the claim only, no reasoning, no severity, no author —
> and instructed to refute it. **Four of the eight original findings did not survive**, including one
> whose recommended fix pointed in the wrong direction. Those are recorded in *Refuted candidates*
> below rather than deleted, and the surviving findings are restated in corrected form. Two new
> findings came out of the verification. This note exists so the reader can see that the filter ran
> and what it caught.
>
> **Post-audit correction (same day), from actually fixing finding 1.** Finding 1's *mechanism*
> claim below — that the area over-count "propagates 1:1 into the land base" — is **false**, and
> the fix proved it. LYCD land value is `zone_psf × area` where `zone_psf` is itself
> `median(market_value / area)`, so the method is **exactly scale-invariant in lot area**:
> multiplying every parcel's area by 2, or by 0.584, changes the land base, the solved millages,
> the winner share and the median tax change by *literally nothing* (verified by re-solving).
> What the pipeline was not invariant to is **mixing two area conventions**, which is the real
> defect: DOR-sourced areas came from a Web Mercator `Shape__Area` (inflated 1/cos²(lat) ≈ 1.704×
> at this latitude) while OPA `total_area` is true ground area, so ~5% of parcels sat on a scale
> 1.7× larger than the rest — compounded by a point-in-polygon join giving every parcel inside a
> polygon its full area. Correcting it moved total lot area from 3.06× to 0.80× the city, but
> moved the headline only from 68.26% to 68.10% winners and −18.97% to −18.65% median (2,139
> parcels flip winner/loser). **Finding 1 should have been Material, not Blocking** — the defect
> was real and worth fixing, but the market-value cap was already absorbing most of it. This
> record is left unedited below so the error is visible rather than quietly repaired.

## Scope

**The argument under audit.** Four revenue-neutral 4:1 split-rate LVT models of Philadelphia share
one parcel universe (579,814 rows from `data/parcels.gpq`, 2024 assessment vintage) and vary two
things: the **land-value source** (OPA's `taxable_land` vs. a GMA-zone LYCD estimate) and the
**abatement treatment** (10-year construction abatements active vs. expired). The evidence offered
is the per-parcel distribution of tax change in each cell; the inferential step is that comparing
cells isolates the effect of each axis on who wins and who loses under LVT.

**Read:** the four notebooks in `cities/philadelphia/`; `lvt/lvt_utils.py`; the four exports plus
`philadelphia_lycd_refined_prototype.csv`; `analysis/explainers/philadelphia_lycd.md`; `CLAUDE.md`;
the prior audit `analysis/political/philadelphia_mayor_exposure_audit.md` (2026-07-18);
`analysis/political/philadelphia_lvt_deck/` and `scripts/build_philadelphia_webmap.py` as downstream
consumers.

**Ran:** A reconstruction of `model_lycd.ipynb` (`analysis/audits/probes_2026-08-08/lycd_probe.py`)
reproducing the shipped land millage to 10 significant figures, re-solved ~40 times under varied
parameters. One refuter additionally **re-executed the shipped notebook itself** with a one-token
edit and reproduced the sweep to every printed digit. Plus direct probes of all five exports for row
alignment, revenue neutrality, census coverage, encoding, and exempt-parcel handling.

**Not examined:** dimension 5 (reporting/prose) as a systematic pass — though verification forced
partial coverage of the deck and explainers, which is where two findings came from. Not audited:
`model_ocd_land_assessment.ipynb`, `model_wage_tax_swap.ipynb`, the political briefs' internal
numbers, the webmap viewer, the upstream Carto fetch.

**Depth:** standard, deepened to `deep` on the LYCD land-value construction, with adversarial
verification on all Blocking/Material items except finding 5.

## Verdict

**The models compute what they claim to compute; the defect is in an input layer none of them
inspect.** Revenue neutrality is exact, the 2×2 is correctly wired, `current_tax` is genuinely held
constant across the land-value axis, and there is no arithmetic error in any solve path — a
conclusion that survived eight independent attempts to break it.

The real problem is upstream. **The lot-area field that LYCD land value is directly proportional to
sums to 3.08× Philadelphia's actual land area.** The market-value cap in `model_lycd.ipynb` is
silently absorbing that error — removing $26.5B, of which ~94% sits on parcels whose lot area is
itself broken — and neither the area defect nor the size of the compensation appears in any notebook
output, explainer, or doc. Because LYCD land is linear in area, this propagates 1:1 into the land
base of both LYCD cells. The two OPA cells are unaffected; they never use lot area.

Second, the LYCD-vs-OPA comparison is not robust to a defensible land-share calibration, and the
repo already contains the proof: its own FHFA-calibrated prototype puts LYCD *below* the OPA panel
on winner share (65.65% vs 66.92%) where the shipped flat-20% version puts it *above* (68.26%). No
published artifact currently states that comparison, which limits the damage — but the deck's
headline numbers come from that untracked prototype while the tracked pipeline says something else.

## Coverage

| Dimension | Inventoried | Verified | Unverifiable | Not checked |
|---|---|---|---|---|
| 1 Question | 4 gaps tested | 3 | 1 (author intent) | — |
| 2 Assumptions | 13 load-bearing | 11 (8 by re-running) | 1 (LOOP/Senior Freeze) | 1 (upstream Carto pull) |
| 3 Inference | 6 steps | 6 (5 by re-solve) | — | — |
| 4 Implementation | ~12 paths traced | 10 | — | 2 (viz path, census internals) |
| 5 Reporting | not a systematic pass | 2 incidental | — | most |

**Findings by dimension** (after verification)

| Dimension | Findings |
|---|---|
| 1 Question | 1 |
| 2 Assumptions | 3 |
| 3 Inference | 2 |
| 4 Implementation | 4 |
| 5 Reporting | 1 (incidental) |

Soundness (2+3 = 5) against consistency (4 = 4) is a thinner soundness margin than the first draft
claimed, and honestly so: three of the original soundness findings turned out to be rhetorical
rather than real. The strongest surviving item (finding 1) reads as dimension 2 only because it
silently falsifies an assumption every LYCD number depends on.

## Findings

### [BLOCKING] 1. The lot-area layer over-counts Philadelphia's land area by 3.08×, and LYCD land value is linear in it

**Confidence:** Verified (ran) — independently derived by three separate agents and by direct probe.

**What's wrong:** `dor_area_sqft`, built in `model_lycd.ipynb` cells 4/6, is the multiplicand for
every LYCD land value (`lycd_land_value = zone_psf × dor_area_sqft`). Measured:

| | value |
|---|---|
| Philadelphia actual land area | 3.741e9 sqft (134.2 sq mi) |
| `sum(dor_area_sqft)` | **1.153e10 sqft — 3.08× the city** |
| `dor_spatial` slice alone (30,649 parcels) | 8.650e9 sqft — 2.31× the city |
| distinct area values among those 30,649 parcels | **1,932** (98.7% share a value with ≥1 other) |
| most-shared single value | 236,475.4 sqft on **785 parcels** |
| largest single record (`783766600`, from `opa_total_area`) | 2.077e8 sqft = **7.45 sq mi = 5.6% of the city** |
| drop top 1% by area | 4.024e9 sqft — **1.08× the city, i.e. about right** |

Two distinct mechanisms. The DOR spatial join assigns one shared campus/block polygon's area to
every point inside it. Separately, a small number of OPA `total_area` records are simply wrong — the
7.45 sq mi parcel comes from the *primary*, supposedly reliable source, so this is not confined to
the fallback.

**Consequence if unfixed:** Every LYCD land value inherits this. It is why the market-value cap has
to remove $26.5B (finding 2), it inflates the pre-cap land base roughly threefold, and it means
LYCD land estimates for large-lot parcels are unreliable in a way no diagnostic in the pipeline
reports. Both LYCD cells of the 2×2 are affected; the two OPA cells are not.

**Reproduce:**
```bash
cd cities/philadelphia && C:/Users/druss/miniconda3/python.exe ../../analysis/audits/probes_2026-08-08/verify_area.py
```

**Cost to fix:** Moderate. Winsorising area at p99 before the cap already brings the total to 1.08×
the city; a real fix de-duplicates shared DOR polygons across the parcels inside them and adds a
plausibility ceiling on OPA `total_area`.

---

### [MATERIAL] 2. The market-value cap silently compensates for finding 1, removing $26.5B; its form was never swept

**Confidence:** Verified (ran)

**What's wrong:** The cap at `model_lycd.ipynb` cell 8 clips `lycd_land_value` to `market_value` for
non-vacant parcels. Pre-cap base $95.78B → post-cap $69.30B: **$26.48B (27.6%) removed**, 22,173
parcels. The notebook's executed output reports only `22,173`. Grepping the notebook JSON (source
*and* stored outputs) for `95.7`, `26.4`, or `pre-cap` returns nothing.

**Corrected from the first draft:** ~94% of the removed dollars sit on parcels whose lot area is
itself broken (62.4% shared DOR polygons, 24.8% implausible >5-acre OPA records). The cap is mostly
*bad-input repair*, not a discretionary valuation knob, and **"no cap" is not a defensible
alternative arm** — it admits the 3.08× over-count into the tax base. The first draft's headline
18-point swing (68.26% → 79.04% winners) would have been misleading published as a sensitivity band.

What is genuinely discretionary is the cap's **form**, which was never swept:

| variant | land millage | winners | median |
|---|---|---|---|
| shipped 1× market value | 24.06 | 68.26% | −18.97% |
| 2× market value | 22.72 | 71.43% | −23.48% |
| fallback-only (`dor_spatial`) | 22.51 | 71.93% | −24.19% |
| winsorize area at p99, then 1× | 24.59 | 67.04% | −17.30% |
| no cap *(not defensible — shown for completeness)* | 18.66 | 79.04% | −37.17% |

Roughly 3–4 points of winner share across the defensible forms.

Two further costs the notebook does not disclose: the cap leaves 21,761 improved parcels at a land
ratio of **exactly 1.00** (structure implicitly worth zero), and 19,514 of those still carry positive
`taxable_building` in the reform base, so modelled land+building exceeds market value by **$4.47B** —
the cap's own stated rationale ("land value cannot exceed total property value") is not actually
enforced on the modelled total.

**Reproduce:** `probes_2026-08-08/verify_capforms.py`, `probes_2026-08-08/run1.py`.

**Cost to fix:** An hour to report the magnitude and one alternative form; the substantive fix is
finding 1.

---

### [MATERIAL] 3. The LYCD-vs-OPA comparison reverses under a defensible land-share calibration — demonstrated by the repo's own prototype

**Confidence:** Verified (ran)

**What's wrong:** `LAND_PCT_IMPROVED = 0.20` is load-bearing. A refuter re-executed the shipped
notebook with only that literal changed:

| `LAND_PCT_IMPROVED` | winners | median change |
|---|---|---|
| 0.10 | 78.67% | −26.25% |
| **0.20 (shipped)** | **68.26%** | **−18.97%** |
| 0.40 | 56.28% | −7.54% |

**Corrected from the first draft in two ways.** (a) The range 0.10–0.40 is indefensibly wide; FHFA's
329 Philadelphia tracts put the plausible citywide band at roughly **0.20–0.28** (p25 0.203, median
0.228, p75 0.261). (b) The first draft proposed setting the constant to FHFA's 0.2328 — a category
error. The constant multiplies zone-median $/sqft; it is not a land share. The model at 0.20 already
*realises* a 0.2540 single-family land share against FHFA's 0.2328, so matching FHFA on that basis
means **lowering** the constant to ≈0.18, not raising it.

The finding survives by a better route than the one first argued. The repo's own FHFA-calibrated
prototype — which replaces the flat constant with tract-level FHFA shares for core residential, the
correct way to use that benchmark — lands on the other side of the comparison:

| export | winners | median |
|---|---|---|
| `philadelphia.csv` (OPA) | **66.92%** | −11.80% |
| `philadelphia_lycd.csv` (shipped, flat 0.20) | **68.26%** | −18.97% |
| `philadelphia_lycd_refined_prototype.csv` (FHFA-calibrated) | **65.65%** | −16.28% |

LYCD sits above OPA under the shipped constant and below it under the repo's own calibration. The
sign of the comparison is a function of the land-share treatment, not a finding about land value.

**Consequence if unfixed:** No published artifact currently states a citywide OPA-vs-LYCD winner
comparison — verified across the political briefs and the deck generator — so nothing in print is
falsified. But the comparison cannot be made informally either, and its direction is not what the
shipped numbers suggest. Category *directions* are robust (no category median flips sign within
0.20–0.28); magnitudes are not (SFR median −27.6% to −11.6% across 0.10–0.40).

**Reproduce:** `probes_2026-08-08/run6.py`, plus the three-export comparison above.

**Cost to fix:** The calibrated variant already exists as a built export; promoting it from prototype
to tracked pipeline is the substantive fix — see finding 4.

---

### [MATERIAL] 4. The deck's headline numbers come from an untracked prototype that disagrees with the tracked pipeline

**Confidence:** Verified (read)

**What's wrong:** `analysis/political/philadelphia_lvt_deck/deck/scripts/generate_deck_assets.py:51`
loads `philadelphia_lycd_refined_prototype.csv`, and `Deck.tex:197` states the public headline —
"`\PhlSfrWinRateRefined` of Philadelphia homeowners see a tax cut citywide" — from it. The deck never
loads `philadelphia.csv` at all. The source notebook describes itself in cell 0 as "PROTOTYPE: two
refinements over model_lycd.ipynb, **not a tracked pipeline notebook**."

So the four notebooks under audit are the tracked pipeline, while the published headline comes from a
fifth, untracked one — and per finding 3 the two disagree on the direction of the LYCD-vs-OPA
comparison.

**Consequence if unfixed:** The audited pipeline is not the published pipeline. Re-running the
tracked notebooks will not reproduce a deck number, and a reader comparing the deck against
`analysis/data/philadelphia_lycd.csv` gets a different answer.

**Reproduce:**
```bash
grep -n "refined" analysis/political/philadelphia_lvt_deck/deck/scripts/generate_deck_assets.py
```

**Cost to fix:** Either promote the refined variant to a tracked notebook with its own export, or
re-point the deck at the tracked pipeline. A decision, not an engineering job.

---

### [MATERIAL] 5. 9.4% of parcels get land values from spatial KNN, not from the LYCD method

**Confidence:** Verified (ran) — **not** independently refuted; no lens was assigned to this item.

**What's wrong:** `gma_level`: L3 524,536 / L2 906 / L1 102 / **knn 54,270**.
`parcel_gma_assignment.parquet` covers 528,204 of 579,814 parcels; the remainder receive the median
`lycd_land_value` of their 5 nearest neighbours. Because the KNN operates on neighbours' *dollar land
values* rather than zone price-per-sqft × the parcel's own area, a small parcel adjacent to large
ones inherits their land value irrespective of its own lot size — the variable the method is supposed
to key on.

**Consequence if unfixed:** Nearly one in ten "LYCD land values" is a spatial smooth rather than an
LYCD estimate, and results are reported as if the method applied uniformly.

**Reproduce:** `probes_2026-08-08/run1.py`, `gma_level` distribution.

**Cost to fix:** Low to report; moderate to fix properly (impute zone PSF, then multiply by the
parcel's own area).

---

### [MATERIAL] 6. No uncertainty is attached to any of the four headline results

**Confidence:** Verified (read)

**What's wrong:** All four cells report point estimates with no interval. Findings 1–3 establish that
the dominant variation is specification and input quality, not sampling: the area defect, the cap
form, and the land-share treatment each move the result by more than the between-cell contrast the
design reports.

**Cost to fix:** Low — the sensitivity grids in `probes_2026-08-08/` are most of the work.

---

### [ADVISORY] 7. The cap comment names one of two mechanisms

**Confidence:** Verified (ran)

*(Downgraded from Material — the first draft's version of this finding was refuted; see Refuted
candidates.)* The comment attributes the cap to DOR-spatial-join area inflation, which is correct and
accounts for 60.4% of capped parcels and 62.5% of clipped dollars. It omits a second real mechanism:
7,915 capped parcels ($8.5B) come from `opa_total_area` and are LYCD zone-median overshoot on
low-value homes — capped parcels' median market value is **$84,000** vs **$184,000** for uncapped
ones. The cap therefore binds disproportionately on cheap houses, a distributional consequence the
comment does not flag.

---

### [ADVISORY] 8. Step 2's documented lot-area chain contradicts the code

**Confidence:** Verified (ran)

Step 2 markdown says "PIN-keyed area → OPA `total_area` → …"; the code does OPA-first. Tested and
immaterial to results (68.26% vs 68.54% winners), but it misleads a reader about which chain ran.

---

### [ADVISORY] 9. The revenue guard is looser than the tolerance it prints

**Confidence:** Verified (ran)

Both notebooks print "target: within ±5%" then `assert abs(gap_pct) < 10.0`. Actual gap **+4.97%** —
inside the stated target by 0.03 points, and the guard would keep passing to double it.

---

### [ADVISORY] 10. The KNN lot-area imputation is dead work

**Confidence:** Verified (ran)

Cell 8 KNN-imputes `dor_area_sqft` for 907 parcels, but `n_gma_but_no_area = 0`, so every parcel
receiving an imputed area also receives an imputed land value directly and the imputed area is never
used. Fixing this properly interacts with finding 5.

---

### [ADVISORY] 11. `CLAUDE.md`'s mojibake note is stale, and the first draft mis-stated FHFA usage

**Confidence:** Verified (ran)

All four current exports contain **0** rows with the cp1252 marker; commit `d638f02` fixed the source
literals, and the downstream repair at `build_philadelphia_webmap.py:268` is correctly gated and is
now a no-op. Separately, the first draft of this audit claimed the FHFA benchmark was unused — it is
used by the prototype notebook, two mapping scripts, `analysis/cross_city.ipynb`, and the deck
generator. Correct statement: unused **by the four tracked notebooks**.

## Refuted candidates

Findings that did not survive adversarial verification. Retained because they show the filter ran.

- **"LYCD's central tendency is pinned to the inherited 0.20 constant, so it only half-fixes OPA's
  default." REFUTED, and backwards.** Two of the four numbers offered were arithmetic identities: at
  `k=1.0` with the cap off, the median LYCD/market ratio is **1.0117** and the ±5% band share is
  **17.28%** — both by construction, since half of any zone lies on each side of its own median. So
  "median 0.2026" and "17.26% in band" were restatements of `k`, measuring nothing about the level.
  The 39.00% comparator was also apples-to-oranges (exact equality on OPA's *taxable* ratio vs a ±5%
  band on LYCD's *market* ratio). Apples-to-apples on improved parcels against a common denominator:
  OPA is exactly 0.200 for **80.72%** of parcels with an interquartile range of **exactly 0.0000**;
  LYCD is 0.60% and IQR 0.0855. The original finding understated LYCD's achievement by more than
  half. It also attacked a caveat the repo states in four places, including
  `analysis/explainers/philadelphia_lycd.md` Limitation 3's heading and the public webmap copy
  calling LYCD "a floor … not a full reassessment." Separately verified: at a *fixed* land share with
  identical millages, LYCD vs OPA still reallocates 24.4% of the levy and flips 27.3% of parcels
  between winner and loser — the redistribution the finding dismissed as cosmetic is the method's
  substance.
- **"The cap's stated rationale does not describe what the cap does." REFUTED — base-rate error.**
  The composition figures were right (77.7% code 1, 4.5% code 8, 35.7% `opa_total_area`) but do not
  contradict the comment, which says the cap handles parcels *like* most code-8 ones — an
  exemplification, not a composition claim. By rate: code 8 caps at **89.18%** (highest in the city,
  23× lift) vs code 1 at 3.73% (*below* the 4.12% average); `dor_spatial` caps at **44.73%** vs
  `opa_total_area` at **1.44%**. The "35.7% from the primary source" offered as damning is a 0.38×
  *under*-representation — evidence for the comment, not against it. Survives only as finding 7.
- **"For 25.2% of abated parcels the post-abatement scenario is not a different scenario." REFUTED.**
  The arithmetic is right (7,599 of 30,111, driven by a genuine OPA formula — the rounding hypothesis
  was tested four ways and failed). But `current_tax`, `new_tax`, and `tax_change_pct` differ for
  **100%** of those parcels (median +315.5% pre vs −8.4% post; 0% vs 100% winners), because the
  post-abatement scenario changes the baseline revenue target and the solved millages, not just one
  input. The claim checked an input and never checked the outputs. Its premise was also wrong for
  `model_lycd.ipynb`, which imputes 4 × *LYCD* land (only 23 of 7,599 identical).
- **"`LAND_PCT_IMPROVED` should be calibrated to FHFA's 0.2328." REFUTED as stated** — category
  error; the constant is not a land share, and matching FHFA means ≈0.18, not 0.2328. The underlying
  concern survives as finding 3, via the repo's own prototype.
- **"No shipped notebook uses the FHFA benchmark, so it is unvalidated." REFUTED** — used by the
  prototype, two scripts, `cross_city.ipynb`, and the deck. Restated as finding 11.
- **"The market-value cap is a discretionary knob worth an 18-point sensitivity band." REFUTED** —
  cap-off admits a 3.08× area over-count and is not a defensible arm. Restated as finding 2.
- **"The reconstruction may have manufactured the sensitivity." REFUTED** — a refuter re-executed the
  shipped notebook itself with a one-token edit and reproduced the sweep to every printed digit.
- **"The revenue-neutral solve may self-cancel under a uniform land rescale, making the parameter
  irrelevant." REFUTED** — the closed form at `lvt/lvt_utils.py:122` makes a rescale by `c` exactly
  equivalent to changing the split ratio to `4c`; it cancels only when the improvement base is
  identically zero. Verified numerically.
- **"`philadelphia_lycd.csv` predates the abated-parcel imputation fix." REFUTED** — improvement/land
  is exactly 4.0 for all 30,111 abated parcels; the commit timestamp merely postdates the run.
- **"The webmap's cp1252 repair will corrupt clean labels." REFUTED** — gated on the marker.
- **"`MIN_IMPROVED = 50` is unexamined and load-bearing." REFUTED** — winners move only
  66.76%–68.89% across 10/50/200/1000.
- **"The GMA and area merges may duplicate parcels." REFUTED** — 528,204 rows, 528,204 unique keys.
- **"The census join silently fell through to NaN." REFUTED** — `std_geoid` 100% non-null in all four
  exports.

## Not checked

- The upstream Carto fetch; `parcels.gpq` taken as given.
- Whether OPA's `category_code`, `exempt_building`, and `total_area` match OPA's published spec —
  checked for internal consistency and plausibility only. Finding 1 means `total_area` now deserves a
  spec-level check.
- LOOP and Senior Freeze.
- Dimension 5 as a systematic pass: the political briefs' internal numbers, the deck's other macros,
  the webmap viewer.
- **Finding 5 received no adversarial lens** — treat it with less confidence than the others.
- `model_ocd_land_assessment.ipynb`, `model_wage_tax_swap.ipynb`.

## Since the last audit

Prior audit: `analysis/political/philadelphia_mayor_exposure_audit.md`, 2026-07-18, scoped to the
mayor's electoral exposure rather than the models' own soundness.

| Prior finding | Status |
|---|---|
| Item 2: "LYCD's flat 20% land share — ROBUST (relative) / WEAKENED (absolute)"; band-tested 15–30%; FHFA at 25–29% | **Still open — and more careful than this audit's first draft.** It band-tested the parameter and correctly identified FHFA as the benchmark. Nothing in the four tracked notebooks changed in response. Finding 3 adds that the repo's own FHFA-calibrated prototype now demonstrates the reversal empirically. |
| Item 2: "Market-value-cap ambiguity immaterial (bounds nearly identical)" | **Correct as scoped; do not generalise.** True for the mayor's-base relative correlation. For the citywide absolute headline the cap's *form* is worth ~3–4 points of winner share (finding 2). |
| Item 3: "Lot-area chain (DOR → LYCD) — VERIFIED, 90.4% PIN-level DOR coverage" | **Superseded, and the verification did not catch finding 1.** The current OPA-first chain sources 547,945 parcels from OPA `total_area` and 1,220 from the PIN lookup. More to the point, "VERIFIED" was recorded for a layer that over-counts the city's land area by 3.08×. |

New in this pass: findings 1, 4, 5, 6, 7, 8, 9, 10, 11.

## Recommended order

1. **Fix the lot-area layer** (finding 1). Everything else in the LYCD arm is downstream of it, and
   it is the only item that makes existing LYCD land values wrong rather than merely uncalibrated.
   De-duplicate shared DOR polygons across the parcels inside them; add a plausibility ceiling on OPA
   `total_area`.
2. **Decide which pipeline is canonical** (finding 4). The deck publishes from an untracked prototype
   that disagrees with the tracked notebooks on the sign of a headline comparison. Cheap, and it
   blocks any coherent restatement of results.
3. **Re-run, then report the cap's magnitude and one alternative form** (finding 2) — after 1, since
   the numbers will change.
4. **Report the land-share band alongside LYCD results** (findings 3 and 6), using the FHFA-informed
   0.20–0.28 range rather than an arbitrary sweep.
5. **Fix or disclose the KNN land-value imputation** (findings 5 and 10) — and get an independent
   check on finding 5, which this audit did not adversarially verify.
6. **Documentation cleanups** (findings 7, 8, 9, 11).
