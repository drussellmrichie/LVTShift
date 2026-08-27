# Audit — Philadelphia Single-Tax Static Ledger (Tier 1)

**Date:** 2026-08-26 · **Target:** branch `feat/single-tax-ledger`, commit `490b645`
**Artifacts:** `lvt/single_tax.py`, `cities/philadelphia/model_single_tax_ledger.ipynb`
(executed), `tests/test_single_tax.py`, `docs/SINGLE_TAX_LEDGER_SPEC.md`
**Depth:** standard · **Dimensions:** 1–4, plus a targeted dimension-5 pass on the three
prose claims the request named.

> Numbers in this file are hand-typed on purpose. It is a frozen, dated record of what was
> observed on 2026-08-26 and is not regenerated. Do not sync it to later pipeline runs.

---

## ⚠ Independence limitation — read this first

**This audit was performed by the same agent, in the same session, that wrote the code being
audited.** The skill's own method calls for adversarial verification in fresh context by
independent subagents, precisely because self-refutation re-runs the reasoning that produced
the work and re-agrees with it. That was not available here.

Compensating measures actually taken: every ledger figure was **re-extracted from the source
PDF text by a separate parse** rather than compared against memory; every guard was **fed a
case it is supposed to catch** to confirm it fires; the two headline prose claims were tested
across a sensitivity grid rather than at their stated operating point. Those are real checks
and they found real defects — two of the four Material findings below are against claims this
same agent made hours earlier.

What this cannot substitute for: an independent reader who does not already believe the
design. Findings 3 and 4 in particular (framing and undefended parameters) are the kind a
genuinely separate auditor would be better placed to press. **Treat this as a self-check, not
as the adversarial pass the spec requires.**

---

## The argument under audit

*Claim:* For each bundle `B` of abolished Philadelphia city/school taxes on labor and capital,
there is a break-even capitalization share `κ*(B)` — the uniform fraction of abolished tax
revenue that would have to reappear as site rent for full land-rent capture (plus road and
curb rents) to fund the abolition while holding the City and School District whole on the land
tax they already collect.

*Evidence:* A revenue ledger sourced from FY2026 QCMR Table R-2 and the executed LVT-UBI
model; `R0` = Σ L·(i+t) computed on two land surfaces; a closed-form `κ*` swept over
surface × basis × φ × i × road-rent level × haircut.

*Inference:* `κ*` is exact because κ enters Supply linearly; comparing `κ*` to the plausible
range of real-world capitalization tells you whether a bundle is fundable.

---

## Coverage

| Dimension | Inventoried | Verified | Findings |
|---|---|---|---|
| 1 Question | 1 claim | 1 | 0 |
| 2 Assumptions | 11 | 9 | 3 |
| 3 Inference | 6 steps | 6 | 2 |
| 4 Implementation | 15 ledger lines, 4 guards, 6 identities | 15 / 4 / 6 | 2 |
| 5 Reporting (targeted) | 3 named claims | 3 | 2 |

**Not verified (named honestly):** (a) the two `estimate` lines — School Income Tax and Use &
Occupancy — were not traced to a primary document, because the School District's adopted
budget was not machine-readable at build or audit time; (b) whether OPA's or LYCD's land
surface is closer to true site value, which is the single largest driver of every result here
and is outside this ledger's scope; (c) the FY2025 alternative vintage was implemented but not
executed end-to-end.

---

## What held up

Stated first because an audit that lists only defects misrepresents the object.

- **Every FY2026 QCMR figure re-extracted independently matches the ledger exactly.** Wage
  City $2,047.8M, Wage PICA $731.3M, NPT City $39.1M, NPT PICA $31.4M — four for four.
- **The PICA treatment is exactly right, and provably so.** `wage_pica + npt_pica` =
  $762,688,000, which equals the *PICA City Account* line in QCMR Table R-4 to the dollar.
  That account is the City's non-tax remittance of PICA collections and is correctly **not**
  also counted as revenue. This was the spec's flagged trap (§4.3) and it is closed.
- **City-side completeness is exact.** The eight City tax lines plus QCMR's city Real Property
  total reconcile to QCMR's `TOTAL TAX REVENUE` of $4,606,964k with a **$0 residual**. No City
  tax is missing.
- **All four `validate_ledger` guards fire when fed a violating case** (absorbed-line-in-bundle,
  unknown key, out-of-scope line, kept line). They are not vacuous passes.
- **The core rent identity is sound.** `R0 = L(i+t)` contains an `L·t` component that exactly
  offsets the absorbed `T_land = L·t` in Target, leaving `L·i` as genuine new money. B0's pot
  is therefore `0.05 × $43.023B = $2.151B`, reproducing the LVT-UBI model. Verified.
- **The B1 invariance result is real** at its stated conditions: at κ_building = 1, B1's pot
  collapses onto B0's exactly.

---

## Findings

### M1 — Material · Verified (ran) · Dimension 3/5
**The ATCOR convergence result is stated without the two conditions it requires, and the
formula given in `CLAUDE.md` is wrong.**

`CLAUDE.md` (Single-Tax section) states: *"At `kappa = 1` every bundle's pot is identical
(`R0 - T_land`)."* Both halves fail.

Measured pot spread across the six bundles at κ=1:

| φ | Road rent G | Spread across bundles |
|---|---|---|
| 1.00 | $0 | $0.000B — converges |
| 1.00 | $150M | $0.000B — converges |
| **0.85** | $0 | **$0.868B — does not converge** |
| **0.85** | $150M | **$0.868B — does not converge** |

Convergence holds only at φ = 1. At φ < 1 the pot is `φR0 + G − T_land − (1−φ)ΣT`, whose last
term is bundle-dependent. Separately, the stated value `R0 − T_land` = $2.151B omits `G`; with
central road rent the actual convergence value is **$2.301B**.

*Why it matters:* φ = 0.85 is the repo's own recommended operating point for assessment
reasons (LVT-UBI guide, Limitation 4). The stated invariance is claimed exactly where the
project says the policy should not run.

*Reproduce:* `pot()` from `lvt.single_tax` over `BUNDLES` at `kappa_amounts=t_abolished`, for
φ ∈ {1.0, 0.85}.

*Not affected:* `dividend_vs_kappa.png` is drawn at φ=1.0 and is correct as plotted.

---

### M2 — Material · Verified (ran) · Dimension 5
**"B2 on LYCD land pencils outright, no ATCOR assumption required" is unqualified and false
in most of the sensitivity space.**

Stated in the build hand-off message (not in the committed notebook, which makes no such
claim). Tested across φ × h × i × G:

**B2/LYCD pencils outright in 9 of 24 cells.** It fails in *every* i = 3% cell, and is
knife-edge at φ = 0.85 (κ* = −0.011 with no road rent; −0.002 at h = 5%; **+0.206** at
h = 15%). At the pessimistic corner (φ=0.85, h=15%, i=3%) it needs κ = 0.589.

*Why it matters:* "no ATCOR assumption required" is the strongest claim made about this build,
and it survives only at i ≥ 5% with a small haircut. The correct statement is: *at the central
parameters, LYCD site rent covers the Wage & Earnings Tax with room to spare; at i = 3% or
with a material collection haircut, it does not.*

---

### M3 — Material · Verified (read) · Dimension 2
**The three named κ scenarios are invented numbers with no source, and the export presents
them as results.**

`KAPPA_SCENARIOS` sets conservative/central/ATCOR at building 0.50/0.70/1.00, wage
0.10/0.25/1.00, other 0.20/0.40/1.00. **No citation exists for any of these values**, in the
module, the spec, or the notebook. They originate in a conversational suggestion.

The sweep export then ships `pot_central`, `dividend_central`, `pot_conservative`, … as
columns, and the notebook prints a *"Dividend per resident"* table from them. A reader of
`philadelphia_single_tax_ty2026_ledger.csv` sees `dividend_central` and has nothing telling
them it is an unsourced guess. This is the failure mode the ledger's own `status:
verified|estimate` discipline exists to prevent — applied rigorously to the tax lines and not
at all to the parameter that multiplies them.

*Note:* the spec is emphatic that "κ is a swept parameter, not an estimate." Shipping named
scenarios contradicts that in the artifact even though the prose repeats it.

*Suggested disposition:* either attach sources/bounds to the three scenarios, or rename them
to non-authoritative labels (`kappa_lo/mid/hi`) and mark the columns illustrative.

---

### M4 — Material · Verified (ran) · Dimension 2/4
**Accrual conventions are mixed: property lines are billed, every other tax line is collected
(and includes prior-year collections).**

The spec (§3) anticipated exactly this — *"Choose billed where derivable, and handle the wedge
once, via the collections-haircut scenario, not by ad-hoc per-line adjustment"* — and the
build did not do it. The haircut `h` applies to `R0` on the **supply** side only; nothing
handles the wedge on the **target** side.

The property lines ($0.602B land + $1.540B building) are TY2026 *billed*. QCMR lines are
collections, and several bundle current + prior year (Wage Total includes $5.4M prior; BIRT's
footnote states it is "the aggregate total of current and prior taxes").

Effect of applying a 5% collection loss to the property lines only:

| Bundle | Target | → | κ* | → |
|---|---|---|---|---|
| B1 | $2.143B | $2.036B | −0.396 | −0.466 |
| B3 | $4.922B | $4.815B | 0.502 | **0.477** |
| B5 | $6.388B | $6.281B | 0.628 | 0.610 |

About 5% relative on κ*(B3). No headline flips; the direction is that current results
*overstate* how much capitalization is needed.

---

### M5 — Material · Verified (read) · Dimension 3
**"κ* > 1 means it cannot be funded even if every abolished dollar reappeared as rent" is
stated as a bound but is not one.**

Asserted in the spec §2, the notebook's header markdown, and the heatmap colorbar label
("`>1 impossible`"). This assumes κ ≤ 1, i.e. that ATCOR is an upper limit. The Georgist
literature's stronger claim — Gaffney's EBCOR, that abolishing a *distortionary* tax raises
rent by more than the revenue foregone because the excess burden is recovered too — implies
κ > 1 is possible for exactly the taxes this program abolishes.

*Why it matters:* the framing forecloses the most favorable case by assumption, and does so in
a chart label, which is where framing does the most work. It currently binds on only 3 of
1,440 cells (all OPA, all in the φ=0.85/h=15%/i=3% corner), so no headline changes — but the
whole point of the ledger is to be reused on more ambitious bundles, where it would.

*Suggested disposition:* relabel as "κ* > 1 requires super-ATCOR (EBCOR) capitalization"
rather than "impossible," and say so once in the spec.

---

### A1 — Advisory · Verified (ran) · Dimension 4
**Net Profits Tax is classified `labor` but receives `κ_other`, not `κ_wage`.**

κ families are keyed off `_WAGE_KEYS = {wage_city, wage_pica}` and `_BUILDING_KEYS`, not off
`classification`. Everything else — including both NPT lines — falls to `κ_other`. So the
labor/capital classification the spec spends §3 on is **computationally inert**: it drives
only `validate_ledger`'s abolishable check and the display ordering. Given NPT is the
self-employment analogue of the wage tax, κ_wage is arguably the right family. Effect is small
($70.5M) and confined to B4/B5.

### A2 — Advisory · Verified (ran) · Dimension 4
**`validate_ledger` checks structure, never substance.** It cannot detect a wrong amount, a
figure that does not match its cited source (no source is parsed), an inconsistent vintage
(`vintage_is_consistent` reports but never raises), or a tax missing from the ledger
entirely. The City-side completeness check that closes the last gap was performed by hand in
this audit and is **not** encoded as a test — so it will not protect the next vintage change.

### A3 — Advisory · Verified (read) · Dimension 4
**School District out-of-scope taxes are absent from the ledger rather than listed.** City
consumption taxes (sales, amusement, beverage, other) appear as `out_of_scope` lines; the
School District's liquor-by-the-drink, cigarette, sales share, PILOTs and rideshare fees do
not appear at all. The spec's stated purpose for the out-of-scope table — "so the scope choice
is visible" — is therefore only half met, and the printed view understates what the program
leaves standing.

### A4 — Advisory · Verified (read) · Dimension 2
**The `full` rent basis mixes land surfaces.** `full_land_lycd = land_lycd + exempt_land`,
where `exempt_land` is OPA's. A LYCD-consistent exempt-land surface does not exist, so this is
unavoidable, but the `lycd/full` column is a hybrid and is not labelled as one. (Inherited
from `model_lvt_ubi.ipynb`; not introduced here.)

### A5 — Advisory · Dimension 2
**PICA debt service is $0 in the FY2026 projection.** The ledger's `wage_pica` note warns that
"PICA revenue services PICA bonds; stranding it is a legal constraint." QCMR Table R-2's
"Less: PICA Debt Service & Expenses" line reads 0 for all FY2026 full-year columns (against
−$5,364k FY25 actual), consistent with the PICA bonds having been retired. If so the caveat is
weaker than stated — in the direction that makes abolition *easier*. Worth confirming against
PICA's own financials before repeating the caveat.

---

## Refuted candidates

Kept as evidence the audit had a filter.

- **"Supply double-counts the land tax"** — refuted. `R0`'s `L·t` term and Target's `T_land`
  are the same dollars by construction and net exactly; B0's pot reduces to `L·i`. Verified
  numerically ($2.151B).
- **"κ·T should be grossed up by (i+t) like land value is"** — refuted. `T_j` is already an
  annual flow; the gross-up converts a *stock* (assessed price) to a flow. Applying it to a
  flow would be the error.
- **"A tax is missing from the City side"** — refuted by exact reconciliation to QCMR's
  $4,606,964k total, $0 residual.
- **"BIRT and NPT are double-counted through the 60% credit"** — refuted. Both lines are
  published receipts, already net of the credit; the module's docstring and the QCMR footnote
  both confirm the basis.
- **"The haircut should apply to κ·T as well as R0"** — *not* refuted, but not filed as a
  finding either: it is spec-mandated behaviour (§7 defines h on R0), faithfully implemented
  and explicitly tested (`test_haircut_applies_to_r0_only`). It is a spec choice to revisit,
  not an implementation defect. Direction: understates the haircut's bite at high κ.

---

## Ranked work list

1. **M3** — de-authorise or source the named κ scenarios. Highest leverage: it is the one
   defect that can mislead a reader of the exported CSV who never opens the notebook.
2. **M1** — fix the `CLAUDE.md` convergence formula (add `G`, qualify φ=1).
3. **M2** — restate the B2/LYCD claim with its operating conditions wherever it was made.
4. **M5** — relabel the κ>1 region as super-ATCOR rather than impossible.
5. **M4** — decide the accrual convention deliberately and apply it once.
6. **A2** — encode the City-side completeness reconciliation as a test before any vintage change.
7. **A1, A3, A4, A5** — as convenient.

**None of these blocks the build's central result**, which is that B3 (wage + entire property
tax) needs roughly 0.18 κ on LYCD land and 0.47 on OPA land, and that the spread between the
two surfaces is larger than any other axis in the sweep. That result survived every check run
here.

## Recommended next step

The spec requires an adversarial pass before any κ* number leaves the repo, and this audit
does not satisfy that requirement — see the independence limitation above. Re-run
`/analysis-audit` with independent subagents (or a fresh session on a different model) with
findings M3 and M5 specifically nominated for refutation, since both are judgment calls made
by the same reasoning that produced the design.
