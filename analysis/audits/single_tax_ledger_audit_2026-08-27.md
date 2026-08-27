# Audit — Philadelphia Single-Tax Static Ledger (Tier 1), 2026-08-27

**The independent adversarial pass owed by `docs/SINGLE_TAX_LEDGER_SPEC.md`.**
Target: `main` at commit `1816b79` (post-PR #39). Artifacts: `lvt/single_tax.py`,
`cities/philadelphia/model_single_tax_ledger.ipynb` (stored outputs; not re-executed),
`tests/test_single_tax.py`, `docs/SINGLE_TAX_LEDGER_SPEC.md`,
`docs/KAPPA_CAPITALIZATION_EVIDENCE.md`, both exports in `analysis/data/`, and the
sibling run artifacts in `C:/projects/philly-cordon-pricing/runs/`.

Point-in-time record: the numbers below are what the artifacts said on 2026-08-27 and are
deliberately not maintained. Current values live in the generated exports
(`analysis/data/philadelphia_single_tax_ty2026_*.csv`) and the executed notebook.

## Independence

The 2026-08-26 audit was a self-check by the agent that built the ledger, in the same
session. This pass:

- **Core ledger (the 2026-08-26 build): fully independent.** Audited by a different
  session with six fresh-context subagents, one of which re-extracted every revenue line
  from the cited QCMR PDF itself rather than comparing against the repo's numbers.
- **PR #39 (κ bounds, G rework, merged earlier on 2026-08-27): partially independent.**
  That PR was authored by the session running this audit. Mitigation: every PR #39 item
  was handed to fresh-context subagents given file paths and a claimed defect, never the
  author's reasoning; the two spec-nominated targets (M3 disposition, M5 framing) went to
  dedicated refuters instructed to attack; verifier verdicts are reported as returned,
  including the four findings below that are against PR #39's own prose. One finding
  (M-2) was main-loop-found; it is against the author's work, was verified mechanically
  against the export, and its surviving benign reading is recorded inside the finding.

## Scope

**Read:** the five target files, both `analysis/data` exports, the notebook's stored
outputs, the prior audit, `docs/LVT_UBI_GUIDE.md` (limitations), sibling repos
`philly-cordon-pricing` (README, advocacy brief, AUDIT.md, run JSONs) and
`philly-parking-benefit-districts` (README, research note).
**Ran:** full test suite (130 passed, 1 xfailed); 6 independent probe families
(κ\* zeroing on 20 random draws, linearity, ATCOR convergence at 3 G levels,
`validate_ledger` guard injection, both new guards' assertion injection, full-export
recomputation of `kappa_star` / `pot_lit_*` / family sums); primary-source fetches (QCMR
PDF parsed with pymupdf; Coste WP 24-01 full PDF; Brülhart et al. published pagination;
AEA/RePEc/IZA pages for all nine sources; PPA Act 84 explainer + audited FY17 financials;
Controller April 2026 SDP release); sibling run-artifact reads at full precision.
**Not examined:** see the *Not checked* section.
**Depth:** deep on PR #39 material, standard on the carried-over core.
**Dimension 5 (reporting): off** — with one deliberate exception: the evidence doc's
citations are premises of the κ bounds, so their accuracy was audited as dimension 2.

## Verdict

The core argument survives genuinely independent verification: all twenty QCMR revenue
lines (FY2026 and FY2025) re-extract exactly from the cited PDF, the $0 City-side
reconciliation re-derives from an independent parse, the κ\* algebra is exact (probes
plus a 6.7e-16 full-export recomputation), the T_land-absorption guard demonstrably
fires, and both spec-nominated dispositions were upheld under dedicated adversarial
attack — the M3 sourcing was the right branch and the M5 relabel is correct in the
model's own accounting. What did not survive is a layer of prose sitting on top of sound
machinery: an "EBCOR demonstrated" claim that holds in exactly half its own export, a
carried-over B5 headline that the project's new bounds now contradict on one surface, two
conservative-direction claims stronger than their algebra, an undefended haircut
asymmetry that flatters every h>0 cell, plus one hand-transcribed constant and one broken
DOI inside the very machinery built to prevent hand-transcription. Nothing Blocking; the
headline κ\* values (B3: 0.502 OPA / 0.212 LYCD at G=0, h=0) stand as computed.

## Coverage

| Dimension | Inventoried | Verified | Unverifiable | Not checked |
|---|---|---|---|---|
| 1 Question | 1 core claim + 8 summary statements | all (two-restatement diff + statement-by-statement vs export) | 0 | 0 |
| 2 Assumptions | 15 (6 new in PR #39) | 14 (10+10 QCMR lines re-extracted; Act 84 verified vs PPA primary sources; both κ mapping bridges worked; all 9 κ sources re-fetched) | 0 | 1 — the OPA land/building split is taken from the LVT-UBI run and was checked only via the B0 wiring assert and the ~$1.2B school-share cross-check, not re-derived from parcels |
| 3 Inference | 8 steps | 8 | 0 | 0 |
| 4 Implementation | 7 guard families, 5 hardcoded-constant blocks, 2 exports | all, by execution | 0 | 0 |
| 5 Reporting | — | out of scope (stated) | — | — |

**Findings by dimension:**

| Dimension | Findings |
|---|---|
| 1 Question | 1 (M-2, shared with 3) |
| 2 Assumptions | 2 Material (M-5, M-6) + parts of A-2/A-3/A-4/A-5 |
| 3 Inference | 3 Material (M-1, M-2, M-3) + parts of A-4/A-5 |
| 4 Implementation | 1 Material (M-4) + parts of A-1/A-3 |
| 5 Reporting | off |

The split's centre of gravity is dimensions 2–3, where it should be: this pass audited
whether the argument holds, not merely whether the project agrees with itself. The
dimension-4 sweep came back almost entirely clean, which on a project with this guard
density is close to expected and is reported as such.

## Findings

### [MATERIAL] M-1. "EBCOR in miniature, demonstrated" holds in exactly half its own export and demonstrates an assumption's arithmetic

**Confidence:** Verified (ran) — dedicated refuter, computed against the export.
**What's wrong:** The notebook summary states, unqualified, that at `lit_high` B1's
dividend exceeds B0's — "EBCOR in miniature … demonstrated rather than argued" (the spec
update block repeats "demonstrated rather than argued"; `lvt/single_tax.py` calls
Coste's 1.006 "the concrete form of that point"). In the export the claim holds in
**240 of 480** B0/B1 cell-pairs — every φ=1.0 cell and **no** φ=0.85 cell, where the
sign flips to −$140.10/capita (0.85×1.006 < 1). Three paragraphs earlier the same
summary cell states its own standard: a result that "held in fewer than half the cells"
must be stated "with its operating conditions or not at all." This one holds in exactly
half and is stated with none. Moreover the +$5.80/capita margin at φ=1 is
T_b×0.006/pop — the direct arithmetic of assuming κ_building = 1.006, a point estimate
whose 95% CI (86.0–115.2%) spans 1.0. Nothing was demonstrated that was not assumed, and
Coste's own reading is *full* capitalization, not super-ATCOR.
**Evidence:** `dividend_lit_high` B1 = 1408.51 vs B0 = 1402.71 at (opa, taxable, i=5%,
φ=1.0, central G, h=0); B1−B0 = −$140.10/capita at φ=0.85. Refuter's cell count 240/480.
Summary cell, "A useful artifact of the bounds" paragraph; spec lines ~15–24.
**Consequence if unfixed:** the audit-trail document and the notebook both present an
input echo as empirical corroboration of the κ>1 framing — the same launder-shape M3
originally named, applied to a theory claim instead of a parameter.
**Reproduce:** filter the ledger CSV on bundle ∈ {B0,B1} and compare `dividend_lit_high`
by φ.
**Cost to fix:** ~15 minutes: reword the notebook paragraph (state φ=1 condition and
"arithmetic signature of a κ above 1, not evidence for one"), strike "demonstrated
rather than argued" from the spec block, soften "concrete form of that point" in the
module comment to note the CI spans 1.

### [MATERIAL] M-2. The carried-over B5 headline is contradicted by the project's own new bounds on one surface

**Confidence:** Verified (ran) — main-loop-found; mechanically verified against the
export; benign reading constructed and recorded below.
**What's wrong:** The summary cell still asserts (from the 2026-08-26 build, before the
bounds existed): "The full program does not pencil statically. B5 requires capitalization
well above what any published estimate of ATCOR-style incidence would support, **on
either surface**." Post-PR #39, the project's own artifacts contradict the second clause:
`pot_lit_high(B5) > 0` in **406 of 480** B5 cells (240/240 at φ=1.0, 166/240 at φ=0.85),
and a B5-weighted κ built from published *point estimates only* — no theory ceilings
(wage 0.25 SSZ-transferred, building 1.006 Coste, other 0.25–0.30 SSZ) — is
**0.451–0.463**, above κ\*(B5/LYCD) = 0.411 (G=0) and 0.397 (central G). On OPA the
sentence survives (κ\* 0.628/0.614 > 0.463).
**Benign reading, recorded:** under Löffler-side building capitalization (0.0) the
weighted κ is 0.196 and the sentence holds on both surfaces. So the correct claim is
conditional — on the land surface *and* on which of the two flatly-disagreeing building
studies one believes — not "on either surface."
**Evidence:** probe on the ledger CSV: B5 weights wage 0.4925 / building 0.2662 / other
0.2412; weighted κ 0.4513–0.4633; κ\* and `pot_lit_high` values as above.
**Consequence if unfixed:** the notebook's most quotable negative conclusion overclaims
relative to the evidence base the same notebook now carries two sections earlier.
**Reproduce:** the probe in this audit's scratchpad (`t_wage/t_abolished` weights ×
KAPPA_BOUNDS point estimates vs `kappa_star`).
**Cost to fix:** ~15 minutes of rewording: "does not pencil at zero capitalization on
either surface; whether published capitalization estimates could carry it depends on the
land surface and on which building-capitalization study one believes (Coste-side: yes on
LYCD at φ=1; Löffler-side: no on either)."

### [MATERIAL] M-3. The haircut applies to R₀ but not to the κ·T increment — an undefended asymmetry that flatters every h>0 cell

**Confidence:** Verified (ran) — two independent agents converged; direction and
magnitude computed.
**What's wrong:** `supply()` computes `phi*((1-h)*r0 + kappa_amounts) + g`. The φ
treatment of the increment is justified in the docstring by "it is site rent like any
other" — but that same rationale implies delinquency/surrender (h) hits it too, and h
does not. The asymmetry is spec-pinned (§7 defines h as R₀→(1−h)R₀; a test enforces it)
but no reason is stated anywhere. Direction is anti-conservative: κ\* in h>0 cells is
understated relative to symmetric treatment — a reported 0.502 at h=0.15 would be 0.590
symmetric; at B3, κ=0.5, h=0.10 the untouched increment is ≈$215M of Supply.
**Evidence:** `lvt/single_tax.py` `supply()`; `tests/test_single_tax.py`
`test_haircut_applies_to_r0_only`; spec §7; both agents' worked magnitudes.
**Consequence if unfixed:** every h>0 row of the 2,880-row export carries a flattering
κ\*; headline values (quoted at h=0) are unaffected.
**Reproduce:** compare `kappa_star` at h=0.15 with `(target−g−phi*(1−h)*r0)/(phi*(1−h)*t_abolished)`.
**Cost to fix:** either apply (1−h) to the increment (one line + test + notebook re-run;
moves h>0 cells only) or add a stated defense (e.g., "abolition-increment rent accrues
disproportionately on already-compliant parcels") to spec §7 and the docstring. The
current silent form is the only indefensible option.

### [MATERIAL] M-4. `G_COMPONENTS['high']` is a hand-transcription that does not match its cited artifact

**Confidence:** Verified (ran) — two agents independently.
**What's wrong:** The constant is `175_290_000.0`; the cited run artifact
(`runs/high_deterrence/20260806T194632Z/stage_09_revenue.json`,
`net_revenue_annual_usd.p50`) reads **175,308,213.52**. The constant is $18,214 low
(0.0104%) and is not a rounding of the artifact (175.31M rounds to 175.29M under no
convention). This is precisely the failure mode the adjacent PROVENANCE CAVEAT block
exists to prevent, committed inside the fix that introduced the block. Direction
conservative; no conclusion moves. Related: both cited runs' `provenance.json` record
`git_sha 976c95ceeeb5…-dirty`; the module cites the sha without the `-dirty` flag,
slightly overstating reproducibility (filed under A-3).
**Evidence:** implementation probe full-precision JSON reads; `lvt/single_tax.py`
G_COMPONENTS block. The `central` constant (83,657,804.0) matches its artifact to the
dollar, and all cited p10/p90 figures match.
**Consequence if unfixed:** `G_SCENARIOS['high']` and every `g_amount` at
`g_level=high` in the export disagree with the cited source by $18K.
**Reproduce:** read the JSON; compare.
**Cost to fix:** one constant, plus (worth it) a test that reads the artifact at full
precision when the sibling path exists and skips otherwise.

### [MATERIAL] M-5. The evidence doc's "setting κ = θ understates κ, never the reverse" fails for the exported slice of the wage tax

**Confidence:** Verified (read) — worked assessment by the sources verifier.
**What's wrong:** §1(b)'s conservative-direction claim requires the landowner burden
share to manifest entirely as local land-rent change. Philadelphia's wage tax reaches
non-resident commuters (~3.44% non-resident rate); revenue collected from them is burden
borne substantially outside the local land market, and abolishing it forgoes that revenue
while local rents respond only through location margins. For that slice κ can fall below
θ-based reasoning even with burden ≥ revenue — the SSZ θ is a share of a *local* welfare
change in a model with no exported-commuter base. The doc flags the commuter issue as
making the transfer "an assumption" but not that its direction cuts *against* the
"never the reverse" sentence.
**Evidence:** `docs/KAPPA_CAPITALIZATION_EVIDENCE.md` §1(b) and §4; verifier's worked
algebra.
**Consequence if unfixed:** readers treat `lit_low` for the wage family — the largest
family in every bundle from B2 up — as a floor, when for the exported slice it is not.
**Reproduce:** read §1(b) against the wage-tax base composition.
**Cost to fix:** one qualifying paragraph in §1(b)/§4.

### [MATERIAL] M-6. The Lyu (2024) DOI is wrong — the cited locator returns 404

**Confidence:** Verified (ran).
**What's wrong:** Repo and evidence doc cite `10.1016/j.regsciurbeco.2024.104028`, which
resolves to nothing; the correct DOI is **`10.1016/j.regsciurbeco.2024.104039`** (RSUE
108, article 104039, PII S016604622400070X). All other metadata (author, journal,
volume, year) and the quoted "at least 71%" figure are correct — nine of nine other
sources verified exactly, including quotes, page references (Brülhart p. 468 confirmed
against published pagination), and the 2023 SSZ correction (26.8%).
**Evidence:** sources verifier's fetch log; RePEc record.
**Consequence if unfixed:** a broken locator in an evidence base whose entire purpose is
traceability.
**Reproduce:** resolve both DOIs.
**Cost to fix:** two-string replacement (`_LYU_2024` in `lvt/single_tax.py` + the doc).

### [ADVISORY] A-1. κ-bounds provenance is the one companion table not shipped beside the export (M3 residue)

The tax lines get `_lines.csv` with source/status per line; the κ scenarios' provenance
(`kappa_bounds_frame()`, whose docstring promises traceability "without opening this
module") reaches notebook readers only. A CSV-only consumer meets `dividend_lit_low`
cold. The M3 refuter's verdict: the laundering charge is refuted (four-layer,
test-enforced provenance; M3's own disposition offered the sourcing branch), but this
gap is real. Fix: one line writing the frame to
`analysis/data/philadelphia_single_tax_ty2026_kappa_bounds.csv`.

### [ADVISORY] A-2. A better SIT figure sat in an already-cited source; U&O vintage label is fuzzy

The Controller's April 2026 release — the same source family the ledger cites for U&O —
carries FY2025 School Income Tax actual of **$71.8M** vs the ledger's $60M FY2023 floor
(16.4% low; κ\*(B4) moves +0.0009, immaterial, and the line is loudly flagged
`estimate`). The same release attributes the $200M U&O to FY25 while the ledger's note
says FY2026; the amount stands either way. Fix: update the SIT line (status can remain
`estimate`), align the U&O vintage note.

### [ADVISORY] A-3. Citation and docstring hygiene (four instances)

(i) Module docstring: collected basis "moves kappa\*(B3) from 0.502 to about 0.477" —
the stored cell-25 output and independent recomputation both give **0.484**; the
docstring number has no derivation. (ii) The cited cordon `git_sha` omits the `-dirty`
suffix present in both runs' provenance. (iii) Löffler & Siegloch is recorded as
`basis="landowner_incidence_share", value=0.0`, but θ≈0 is an *inference* from their
pass-through and null-sales-price results, not a share the paper reports — worth a note
field saying so. (iv) Coste's WP is accepted at *Real Estate Economics* per FHFA's page;
check the published version's numbers when it appears.

### [ADVISORY] A-4. The evidence doc should carry its own missing algebra and its missing Philadelphia literature

(i) §1(a) relies on a discount-rate consistency condition it never derives: κ =
c·(i+t)/d, so κ = c holds iff the study's PV rate d equals the ledger's gross rate i+t;
for Coste's 10-year stream at d = r−g the wedge is small, and for permanent abolition
the omitted factor (i+t)/i ≈ 1.28 runs conservative — but the repo's own rule is that a
bridge needs a derivation, not "more or less directly." (ii) The κ>1 region is never
quantified: with the doc's own sourced θ = 0.25–0.30 and mainstream MEB of 12–56¢/$,
κ>1 requires θ ≥ ~0.64–0.81 — reachable only at the perfect-mobility ceiling; one line
of threshold arithmetic (θ·(1+MEB) > 1) would tell readers how demanding super-ATCOR is.
(iii) Missing literature: **Stull & Stull (1991, JUE 29(2))** — capitalization of local
income taxes in the *Philadelphia suburban* setting, the same instrument family in the
model's own metro, absent from a §4 whose corroboration is otherwise entirely
Swiss/federal (it reports capitalization, not a share, so the "no published share"
sentence stays true — but it is the highest-value addition available for the weakest
family); and **Haughwout, Inman, Craig & Luce (2004, REStat 86(2))** — Philadelphia
wage-tax base elasticities (the city near the top of its revenue hill), direct evidence
for the burden ≥ revenue premise §1(b) rests on.

### [ADVISORY] A-5. Unstated limitations around G, and one unearned sign claim

(i) The curb-exclusion note's "the direction of the omission is conservative" asserts a
sign it hasn't earned: the counted cordon suppresses Center City entries ~9–23%,
cannibalizing the Act 84 curb remittance the exclusion holds at status quo (order
$5–10M, anti-conservative), and the sibling's own efficient-pricing scenarios return
less than status quo — soften to "small and of ambiguous sign, bounded by ~$10M."
(ii) The G/R₀ equilibrium interaction (toll-induced land-value uplift deliberately
absent from frozen R₀ — conservative) is nowhere stated. (iii) G is the sole behavioral
quantity in an otherwise-static identity (the toll's own demand response is first-order
to G and correctly included) — one sentence would convert the wave into coverage.
(iv) The Act 84 $35M-floor premise verifies against PPA's audited FY17 financials
($35.35M City + $9.77M SDP), with a minor vintage nuance (PPA's explainer dates the
floor to a 2014 action, its financials to Act 84 of 2012).

## Refuted candidates

- **"The `lit_*` rename reproduces or worsens M3's laundering"** — refuted: values are
  test-pinned to cited bounds, the transferred wage bound is flagged in four places
  including a runtime banner, and M3's own disposition offered "attach sources" as a
  valid branch. Residue → A-1.
- **"κ>1 is internally inconsistent in the ledger's own accounting"** (Direction B of
  the M5 refutation) — refuted: R₀ is status-quo rent and κ·T a separately-defined
  increment; no adding-up constraint exists to violate; pot is linear through κ=1 with
  no pathology.
- **"Adding cordon revenue to φ·R₀ double-counts"** — no defect as computed: R₀ is
  frozen at toll-free assessments, and G is collections while any uplift would be
  capitalized consumer surplus — different dollars. The unstated-interaction residue →
  A-5.
- **"175,290,000 is a legitimate rounding of the artifact"** — refuted: 175,308,213.52
  rounds to 175.29M under no convention. → M-4.
- **"B5 pencils under lit_high, so the B5 headline is simply false"** — partially
  refuted: under Löffler-side building capitalization the headline holds on both
  surfaces; retained as the conditional overclaim M-2, not a flipped conclusion.

## Not checked

- **The LVT-UBI model upstream of R₀** — the parcel-level construction of both land
  surfaces was not re-derived; this pass relied on the B0 wiring assert and the
  school-share cross-check. R₀'s soundness has its own audit trail (2026-08-08) but was
  not re-verified here.
- **The sibling cordon model's internal validity.** Only transcription from its run
  artifacts was verified. The Monte Carlo behind the p50s — transferred elasticities,
  IPF-fused OD matrix — was not audited, and its README's "illustrative ranges" caveat
  stands. G's `modeled_sibling` status is load-bearing.
- **The notebook was not re-executed** (it overwrites exports); stored outputs were
  read as artifacts.
- **The FY2025 vintage path** beyond line-value matching (no FY2025 sweep was run).
- **Jacob & Livas (2026)** as a κ anchor — Tier 2, out of scope per spec §10.

## Since the last audit (2026-08-26)

| Prior finding | Status |
|---|---|
| M1 — ATCOR convergence stated without conditions; CLAUDE.md formula wrong | closed; re-verified by independent probe (converges at φ=1 only, all G levels; distinct at φ=0.85) |
| M2 — "B2 pencils on LYCD" unqualified | closed; the summary cell now carries full operating conditions — but the *same standard* is violated by the new EBCOR sentence (M-1): the failure shape regressed in a new instance |
| M3 — unsourced κ scenarios presented as results | closed by sourcing (PR #39); disposition upheld under dedicated refutation; residue A-1 |
| M4 — mixed accrual conventions | closed; cell-25 accrual sensitivity exists and its outputs verify — with a docstring drift in the fix's own text (A-3.i) |
| M5 — "κ\*>1 impossible" framing | closed; relabel upheld under two-direction attack — but the new "demonstrated rather than argued" escalation is fresh overreach (M-1) |
| A1 — NPT classified labor but received κ_other | closed; NPT is in `_WAGE_KEYS`, test-pinned |
| A2 — `validate_ledger` checks structure, never substance | closed; the QCMR reconciliation test exists and its $0 residual re-derives from an independent PDF parse |
| A3 — SDP out-of-scope taxes absent rather than listed | closed via the printed enumeration note |
| A4 — `full` basis mixes land surfaces | closed via disclosure (hybrid-surface note in Section 3) |
| A5 — PICA debt service $0 caveat | closed via the wage_pica note's confirm-before-repeating caveat |

New in this pass: M-1 through M-6, A-1 through A-5. The prior audit's three central
claims (QCMR reconciliation, B0 wiring, same-day fixes) all substantiated under
independent re-verification — the self-check was accurate about the core, which is worth
recording given how it was discounted.

## Recommended order

1. **M-4 + M-6** — fix the `high` constant (175,308,213.52) and the Lyu DOI
   (`…104039`); minutes, and they are the two hard defects. Add the artifact-reading
   test with M-4.
2. **M-1 + M-2** — reword the two overclaiming passages (three sites for M-1, one for
   M-2) before anyone quotes the notebook outward; ~30 minutes, no re-run needed for
   prose-only edits to markdown cells, though a re-execution keeps the .ipynb honest.
3. **M-3** — decide the haircut asymmetry: one-line symmetric fix + notebook re-run, or
   a written defense in spec §7. The silent form is the only wrong option.
4. **M-5 + A-4** — one editing pass over the evidence doc: qualify §1(b) for the
   exported wage slice, add the §1(a) derivation and the θ·(1+MEB) threshold line, cite
   Stull & Stull and Haughwout et al.
5. **A-2** — update SIT to $71.8M FY2025 (Controller citation), align the U&O vintage
   label; re-run the notebook once for this and step 3 together.
6. **A-1 + A-5** — ship the κ-bounds companion CSV; add the three one-sentence G
   limitations and soften the curb sign claim.
