# Audit — PPI white paper "What Philadelphia's Land Rent Could Replace", 2026-08-27

**Pre-publication pass.** Target: `analysis/single_tax/philadelphia/paper/` at branch
`analysis/single-tax-report` commit `0001f90` — `Report.tex`, `scripts/generate_paper_assets.py`,
the generated `tables/`, `figures/`, `values.json`, and the four `analysis/data/` CSVs they read.

Point-in-time record: the numbers below are what the artifacts said on 2026-08-27 and are
deliberately not maintained. Current values live in the generated sources
(`values.json`, `tables/headlines.tex`) and the analysis exports.

## Independence

The paper's prose and generator were written by the session that commissioned this audit.
Every finding below originates from one of seven fresh-context subagents given file paths and
claimed defects — never the author's reasoning — with dedicated refuters on each
Blocking/Material candidate; the author's role was inventory, nomination of its own weak
points, and this synthesis. Where the synthesis disagrees with an agent it says so explicitly
(one instance, noted under M-2).

## Scope

**In scope:** dimensions 1–4 for the computations the paper's generator introduced (the
tract-level surface-ratio map, the bundle-weighted literature-κ band and its
below/inside/above classification, the one-at-a-time sensitivity spans, the geographic
narration of the map); dimension 5 for the whole document.
**Out of scope:** the underlying ledger (`lvt/single_tax.py`, the sweep exports) — audited
2026-08-26 (self-check) and 2026-08-27 (independent), all findings applied; not re-audited.
**Ran:** independent reproduction of the tract join (all 583,204 parcels), the band
construction, the classification at 120 swept operating points, all sensitivity spans at all
five discount rates, geographic statistics (distance gradients, named-area medians, rank
correlations), recomputation of all 82 macros from the CSVs, the prose-number scanner, and
figure-PDF text extraction.
**Depth:** deep on the four new computations; full claim inventory (88 claims) for dimension 5.

## Verdict

The paper's machinery is sound and its generated numbers are exact — all 82 macros reproduce
from the CSVs, the band aggregation is provably the correct one, and the central map measures
precisely what it claims (the feared LYCD→OPA fallback never fires: 100.00% join,
independently reproduced). What fails is hand-written prose, in one place decisively: the
abstract's causal punchline — the surfaces "move the break-even threshold more than any other
input" — is false on the paper's own artifacts (the surface ranks third), and its fallback
defense in §3.4 is false at every swept discount rate once capture and haircut are measured as
the single knob the paper itself declares them to be. Around that sit a refuted geographic
narration written from the map image rather than the data, an unacknowledged repo artifact
that adjudicates over half the surface gap the paper calls unresolvable, and a caveats section
that contradicts the source module's own notes — including reinstating, verbatim, a sign claim
a prior audit struck. The lead result (B3's thresholds, the disagreement's unevenness,
"different neighborhoods") survives every attack, including on non-ceiling κ evidence alone.
One Blocking finding; nothing requires recomputation — every fix is prose, one figure, and one
macro.

## Coverage

| Dimension | Inventoried | Verified | Findings |
|---|---|---|---|
| 1 Question | 1 core claim + closing interpretive leap | both examined | 0 (leap flagged under A-5) |
| 2 Assumptions (new computations) | 5 map-validity checks, band aggregation, parameter parity | all, by execution | 0 defects (4 footnote-grade caveats → A-4) |
| 3 Inference | 6 steps (map→geography, band→classification, spans→ranking, gap→unresolvability, inside→"doesn't discriminate", map→"different neighborhoods") | all, by execution | **B-1, M-1, M-2, M-4** |
| 4 Implementation | 82 macros, 3 tables, 4 figures, scanner, 2 noqa whitelists | all | **M-3** (one figure/macro understates its object) |
| 5 Reporting | 88 claims | 64 verified · 6–7 mismatch · 16–17 flagged · 1 unverifiable | **M-5, M-6, M-7** + A-1..A-3, A-5 |

The centre of gravity is dimension 3, where it should be. The uniform pattern across every
mismatch: the generated number is right and the sentence around it claims one notch more.

## Findings

### [BLOCKING] B-1. The abstract's ranking claim is false on the paper's own artifacts, and its §3.4 fallback is false at every discount rate

**Confidence:** Verified (ran) — two refuters converged by independent routes.
**What's wrong:** Abstract: "holding every other assumption fixed they move the break-even
threshold more than any other input." On the one-at-a-time measure that phrase denotes, the
surface span of κ*(B3) is 0.29 — **third**, behind the discount rate (0.40 OPA / 0.58 LYCD,
which the body itself reports) and behind the capture/haircut knob honestly measured (0.44;
see M-3). The body's fallback — "Holding the discount rate fixed at any value, the land
surface is the largest single source of variation" — fails at **every** i ∈ {3..7}% against
the product knob φ(1−h) (constant span 0.4376 > surface max 0.3812), and fails even against
the understated φ-only span at i=3% (0.1997 < 0.2011). A second, independent kill: under the
repo's own vacant-land correction the surface span falls to ~0.15, below even the φ-only 0.20.
**Consequence if unfixed:** the abstract's causal punchline — the sentence an abstract-only
reader takes away — asserts a ranking the paper's own macros contradict two pages later.
**What survives:** the *qualitative* distinction the body gestures at: the surface is the only
input that is a disagreement between two published assessments rather than an analyst-chosen
sweep range. That is a defensible lead; "largest" is not.
**Reproduce:** one-at-a-time spans from `philadelphia_single_tax_ty2026_ledger.csv` at the
central cell; product-knob span via cells at φ(1−h)=0.7225.
**Cost to fix:** rewrite one abstract sentence and one body paragraph; no recomputation.

### [MATERIAL] M-1. The map's geographic narration is substantially refuted by the data it narrates

**Confidence:** Verified (ran).
**What's wrong (§3.1):** "diverge at the edges" — refuted (r(distance, log ratio)=0.057,
p=0.25; the outermost quintile is the *least* divergent, median 1.216). "Closest through the
row-house neighborhoods" — backwards: the mid-city belts (3.3–8.7 km) are the *most* divergent
(1.41–1.44). "LYCD substantially more across the Far Northeast" — its tract-median (1.27–1.29)
is *below* the citywide 1.325. "Airport periphery" rests on n=2 tracts. "Assessor relatively
more in and around Center City" survives only narrowly: the ratio<1 tracts do cluster
centrally (median distance 3.0 km vs 7.4, p=0.001) and the dollar-weighted CC ratio is lower
(1.31 vs 1.50), but the median Center City tract is still LYCD +34%.
**What survives:** the industrial river wards (median 1.557, 100% of tracts above 1) and —
the claim that matters — "falls on different neighborhoods": rank correlation 0.894, 38.7% of
tracts shift more than 10 percentile ranks of burden, 15% shift burden share by >50%.
**Root cause:** the prose was written from the rendered image, not computed — the exact
failure shape the ledger audit's M-1 named.
**Cost to fix:** replace the middle of one paragraph with the computed version: pervasive
disagreement (LYCD higher in ~90% of tracts), largest through the mid-city row-house belts and
the industrial riverfront, smallest in the outer Northeast, with the minority of
assessor-higher tracts concentrated in and near Center City.

### [MATERIAL] M-2. The paper asserts the surface gap is unadjudicable while the repo's own artifact adjudicates most of it — publish-gating, fixable in prose

**Confidence:** Verified (ran); Blocking candidate downgraded by a dedicated refuter.
**What's wrong:** "no amount of care in specifying the model will close it" / "nothing in the
analysis can adjudicate between them" / subtitle "an assessment question nobody has settled" —
while `docs/VACANT_LAND_VALUATION.md` (merged the same day, hours before the paper) shows:
$11.6B of the $19.6B gap is vacant land, where sale price *is* land price; LYCD over-values it
in every cut (aggregate 1.55–1.86×) and OPA under-values it (0.44–0.49×); two independent
corrections converge (~$6.9B vs ~$9.4B); correcting vacant land alone moves the surface ratio
1.46× → ~1.22× and κ*(B5) to 0.562/0.449. The paper cites none of it.
**Why not Blocking (refuter's grounds, adopted):** the sentences are mostly literally true as
scoped; the paper was *right* not to compute on the corrected surfaces (the study is an
unaudited aggregate rescale with acknowledged selection and scrutiny limits); and nothing
flips — corrected κ* stays inside the bands, and the closing argument *strengthens* (a named,
measured, class-specific assessment failure, with both surfaces failing IAAO dispersion
standards by 2–4.5× even after noise correction).
**Synthesis correction to the refuter's evidence:** its "ironic fossil" (a `VacantSaleRatio
3.31` docstring example in `report_helpers.py`) is the bundled skill template's example from a
different project, not evidence of author knowledge. The verdict does not depend on it; the
timeline evidence stands on its own.
**Cost to fix:** one added paragraph citing the study + rewording the three quoted sentences
to "the ledger cannot adjudicate; a companion sales study partially can — and it convicts both
surfaces." The subtitle survives.

### [MATERIAL] M-3. Figure 4 and the SpanCapture macro measure half the knob the paper declares

**Confidence:** Verified (ran).
**What's wrong:** the paper establishes that φ and h act only through φ(1−h) ("the same
knob"), then `fig_sensitivity` computes the row's span varying φ with h pinned at 0 —
span 0.2011, half the product knob's true 0.4376 (φ(1−h) ∈ [0.7225, 1]). The caption claims
the shared row exists *because* they are one knob; the prose says "together --- the same knob
--- move it by 0.20", which is arithmetically false (together = 0.44). The five Span macros
faithfully match the CSV — the defect is in what the capture one measures, not its generation.
**Consequence:** understates the knob that, honestly measured, outranks the paper's headline
input — feeding B-1.
**Cost to fix:** one line in `fig_sensitivity` (span over the product grid), regenerate, and
reword the sentence.

### [MATERIAL] M-4. The band classification's fragility is undisclosed, and the abstract compresses away the ceiling B4/B5 depend on

**Confidence:** Verified (ran).
**What's wrong:** (i) §3.3's "4 below / 6 inside / **0 above**" is a central-cell fact
presented as the section's general conclusion; on the model's own grid, 49 of 120 swept
operating points put at least one cell *above* the band — the failure direction (worst:
i=3%, φ=0.85, h=0.15 gives 5 above). Only §2's blanket qualifier keeps the text literally
true. (ii) For B4/OPA and B5/OPA, "consistent with succeeding" rests *entirely* on the
Jacob & Livas open-city ceiling: substituting any non-ceiling wage number flips both to
above-band. The body discloses the ceiling twice; the abstract's "the range that published
capitalization estimates support" does not.
**What survives (important):** the band's aggregation is exactly correct (the weighted average
is the precise break-even functional; verified numerically), the tables/figure render it
faithfully, and **B3 stays inside on non-ceiling evidence alone** (0.357×1.006 + 0.643×0.30 =
0.552 ≥ 0.502) — the paper's lead bundle is robust.
**Cost to fix:** one disclosure sentence in §3.3; one abstract qualifier ("for the largest
bundle on both surfaces, and for the full program within bounds whose upper end is a modeled
ceiling").

### [MATERIAL] M-5. "Two independent audits" mischaracterizes the audit record

**Confidence:** Verified (read).
**What's wrong:** the Reproducibility paragraph claims "two independent audits of both are in
the project repository." The 2026-08-26 audit's own header: "performed by the same agent, in
the same session, that wrote the code being audited… Treat this as a self-check." The spec
says the same. The accurate record: one self-check plus one independent pass (itself partially
independent on the κ/G material). "Of both" also has no clear antecedent after a three-item
list.
**Cost to fix:** one sentence.

### [MATERIAL] M-6. The Caveats contradict the source module's own notes — including reinstating a claim a prior audit struck

**Confidence:** Verified (read).
**What's wrong:** (i) "No behavioral response is modeled **anywhere**" — the module's G-block
note says, of exactly this: "G is the ONLY behavioural quantity in Supply… 'static, no
behavioral response' describes the tax side, not this term." The note exists to prevent this
sentence, and the sentence got written anyway. (ii) Heading "Road and **curb** rents are
**conservative**" — the module's curb note, after audit A-5: "the SIGN IS AMBIGUOUS… an
earlier version of this note claimed the omission was conservative, which it did not
establish." The paper reinstates verbatim the characterization the audit struck. This is the
same claim's **third** attempt to enter the record.
**Cost to fix:** two sentences.

### [MATERIAL] M-7. "Every estimate behind Table 3 concerns a small change to a tax that continues to exist" is false for the wage anchor

**Confidence:** Verified (read).
**What's wrong:** the Jacob & Livas bound is a counterfactual in which Philadelphia's wage tax
is abolished entirely and replaced by an LVT — neither marginal nor continuing, and chosen as
the anchor precisely for that. The error runs in the humble direction (understates the
evidence's applicability), but the sentence is false and the marginal-scale caveat that
follows it is wrong for that bound.
**Cost to fix:** "Every empirical estimate…, with one exception: the wage family's upper
anchor is itself a full-abolition counterfactual — though a modeled one."

### [ADVISORY] A-1. Undisclosed counts and scope slips

406-of-408 tracts (2 zero-pop special-use tracts silently dropped — harmless, undisclosed);
"2,880 combinations of [six named axes]" omits the bundle axis (480 × 6); the central cell
also fixes `rent_basis='taxable'`, listed as swept and never resolved in text; "15 lines" of
taxes "the program would abolish" counts absorbed/kept/out-of-scope lines (9 are abolishable;
Table 1 shows 10); "Two bundles clear on the arithmetic alone" (B2 clears only on LYCD —
the next sentence is correct, the topic sentence overcounts).

### [ADVISORY] A-2. Caption/figure mismatches

Figure 2's caption narrates a "Parking Tax" bar; the figure draws a category bar labeled
"Kept" at $0.00B — the caption describes a line the reader cannot find. Figure 1's caption
implies the clip bites only on the high side (3 tracts sit below 0.5; 23 above 2.5, so "a
small number" is strained). Abstract "$2.9B" vs Figure 2's "$2.95B" for the same quantity on
facing pages. Table 1's "the exported ledger" points at the file named `_ledger.csv`, which is
the sweep; the per-line sources live in `_lines.csv`.

### [ADVISORY] A-3. Evidence-characterization polish

"capitalization of 1.01 of its value" — numerically faithful, grammatically a decimal share
where "101%" is meant, and quoted without the CI (86.0–115.2%, spanning 1.0) that the ledger
audit's own M-1 made load-bearing; the whole-home-price→land mapping condition is unstated.
Table 3's "all others come from studies of the same instrument" over-glosses `direct` for the
`other` family (a state corporate tax is not a school income tax or a transfer tax; the
module's own note says the RTT slice points materially higher).

### [ADVISORY] A-4. Map footnotes worth adding (from the validity verification)

The ratio speaks for *taxable* land only; ~9.6% of the LYCD side is KNN-imputed; LYCD's own
construction caps 21,702 parcels at OPA total market value ($24.0B removed, 22.6% of pre-cap
base) — the surfaces are not fully independent by construction; and the notebook's ≥0.95
match assert leaves up to 5% silent OPA-fallback armed for future vintages (dead at TY2026:
100.00% match, independently reproduced) — tighten it or print the match rate.

### [ADVISORY] A-5. Small overclaims

"rebuild with a single command" (generator + LaTeX = two, no wrapper exists); the closing
"cannot assess land to a tolerance the policy question requires" is an interpretive leap the
evidence supports only via the contested B-1 framing — it reads better, not worse, once M-2's
reframe supplies the vacant-land evidence.

## Refuted candidates

- **The weighted-extremes band is invalid aggregation** — refuted: it is *exactly* the
  break-even functional (verified numerically); the interval is the exact image of the family
  box.
- **The map conflates LYCD coverage with valuation (OPA fallback)** — refuted for this run:
  100.00% join reproduced independently; the fallback is dead code at TY2026.
- **Tables/figures misrender the band** — refuted; and all five Span macros match the CSV.
- **The vacant-land omission is Blocking** — downgraded by its refuter (scope defense partial,
  study unaudited, nothing flips); recorded as M-2.
- **"Three largest bundles inside the band" false at the central cell** — refuted: verified
  true as stated; the fragility across operating points is M-4, not a central-cell error.
- **Abstract's $2.8B/$2.9B rounding wrong** — refuted: consistent with the stated formatter;
  the facing-page inconsistency with the figure's 2dp labels is A-2.

## Not checked

- The vacant-land study itself (`scripts/vacant_land_ratio_study.py`) — its figures were taken
  as the repo states them; it has no audit of its own, which is part of why M-2 is not
  Blocking. If the paper leans on it after the reframe, it should be audited first.
- The Löffler/Coste/SSZ/J&L source papers — re-verified against primary sources in the
  2026-08-27 ledger audit; not re-fetched here.
- Whether the geographic replacement sentence itself survives alternative area definitions —
  the refuter stated its definitions; a different Far-Northeast polygon could move its medians.

## The pattern, for the record

All 82 generated macros reproduce exactly; all six-to-seven mismatches are hand-written prose
asserting more than the artifact supports — and two of them (**the curb "conservative" claim,
the un-CI'd 1.006**) are sentences a prior audit had already struck from other artifacts,
reappearing in a new document. This is the third documented recurrence of the repo's "second
shape." The prose layer has no equivalent of the macro discipline; until it does, every new
document re-litigates the same claims. The nearest mechanical remedy: the generator now
computes the quantities the worst sentences got wrong (spans, rankings, band classifications
across operating points) — emit them into `values.json` and write ranking sentences only from
those fields.

## Recommended order

1. **B-1 + M-3 together** (same subject): fix `fig_sensitivity` to the product knob,
   regenerate, then rewrite the abstract sentence and §3.4 paragraph around "the only
   non-discretionary input" instead of "largest."
2. **M-2**: add the vacant-land paragraph and reword the three unresolvability sentences —
   use the refuter's corrected headline; it is stronger than the current one.
3. **M-1**: replace the geography narration with the computed version.
4. **M-4**: the §3.3 disclosure sentence + the abstract's ceiling qualifier.
5. **M-5/M-6/M-7**: four sentences in Caveats/Reproducibility.
6. **A-1..A-5** in one polish pass; regenerate; re-run linter + overfull + read the PDF.
