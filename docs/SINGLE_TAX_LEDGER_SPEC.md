# Spec — Philadelphia Single-Tax Static Ledger (Tier 1)

Status: **BUILT 2026-08-26.** Design settled the same day (session: LVT-UBI distributional
analysis → Jacob & Livas extension discussion). Delivered:
`cities/philadelphia/model_single_tax_ledger.ipynb` (executed), `lvt/single_tax.py`,
`tests/test_single_tax.py` (39 tests). Outputs:
`analysis/data/philadelphia_single_tax_ty2026_ledger.csv` (2,880 rows),
`..._lines.csv`, three charts in `analysis/reports/philadelphia_single_tax/`.

**Still owed: the adversarial audit.** The build has not been audited. Run `/analysis-audit`
at Opus/Fable level before quoting any κ\* number outside this repo — in particular against
the ledger (Section 3) and the overlap rules (Section 4), which are where a plausible-but-wrong
number would hide.

### Deviations taken during the build

1. **Vintage is FY2026 current projection, not the FY2024 actuals this spec defaulted to.**
   Section 3's own rule is not to mix vintages, and the property lines are TY2026; FY2026 is
   therefore the consistent choice. The FY2026 Q3 QCMR's Real Property figure ($891,102k)
   reconciles exactly with `lvt/philadelphia.tax_year_params(2026)`, confirming the match.
   FY2025 actuals are implemented as a second vintage (`LEDGER_VINTAGE = 'FY2025'`); FY2024
   was dropped because the QCMR does not carry a FY2024 PICA column.
2. **PICA is materially larger than this spec assumed.** Section 4.3 guessed "roughly 1.5
   points" and asked for verification. Verified: PICA is a *separate line* from the City
   General Fund wage tax, at $731.3M wage + $31.4M NPT (FY2026). The full wage-and-earnings
   burden is **$2.779B**, not the City-only $2.048B and not the $2.4528B in the older
   wage-tax-swap notebook. Any bundle containing the wage tax is ~$730M larger than a
   City-General-Fund-only reading would suggest.
3. **Parking Tax is $0 in the City General Fund**, not the ~$100M assumed. It left the
   General Fund after FY2023 (ACFR FY2024 Schedule XIX shows $0 against FY2023's $101,941k)
   and is absent from FY2026 QCMR Table R-2. Classification ('kept') is unchanged, so this
   does not affect any κ\*.
4. **Two lines remain estimates**, flagged loudly at runtime and in `status`: School Income
   Tax ($60M, a rounded FY2023 floor from a Department of Revenue post) and Business Use &
   Occupancy ($200M, rounded to the nearest $100M in a City Controller analysis). The School
   District's own adopted budget is the primary document and was not machine-readable at
   build time. Both appear only in B4/B5.

### Predictions in Section 8 vs. what was built

| | Predicted | Actual |
|---|---|---|
| B0 pot | $2.151B / $1,350 | $2.151B / $1,350 ✓ |
| B1 at κ=1 | equals B0 | equals B0 ✓ |
| κ\*(B3, OPA) | 0.4–0.5 | **0.502** (0.467 w/ central road rent) ✓ |
| κ\*(B3, LYCD, central G) | 0.07–0.15 | **0.177** — modestly above |
| κ\*(B5, OPA) | ">0.5, likely >1 in pessimistic cells" | **0.628**; >1 in 3 of 1,440 cells, all OPA, all in the (φ=0.85, h=0.15, i=3%) corner ✓ |

The B3/LYCD miss is explained and is the ledger being *more* correct than the prediction: the
prediction used the wage-tax-swap notebook's $2.45B wage figure, while the verified FY2026
PICA-inclusive figure is $2.779B — deviation 2 above. No ledger error was found.

## 1. Question

Which bundles of abolished Philadelphia city/school taxes on **labor and capital** can be
funded from full capture of Philadelphia land rents — parcel land rent plus road/curb rents —
and how much capitalization of the abolished taxes into land rents (κ) does each bundle
require to break even? Residual, if any, is a per-capita dividend.

This is the static ledger only: no behavioral response is modeled. κ is a swept parameter,
not an estimate. GE anchoring (Jacob & Livas 2026) is Tier 2 and explicitly out of scope
(Section 10).

## 2. The math

For a bundle `B` of abolished taxes with annual receipts `T_j`:

```
Target(B)          = Σ_{j∈B} T_j  +  T_land
Supply(B, κ⃗, ...) = φ · ( R₀ + Σ_{j∈B} κ_j·T_j )  +  G
Pot                = Supply − Target
κ*(B)              = (Target − φ·R₀ − G) / (φ · Σ_{j∈B} T_j)     # uniform break-even κ
```

where:

- `R₀` = current-world annual site rent on the chosen land surface and basis:
  `Σ L·(i + t)`, with `t` = the combined property rate from `tax_year_params()` (never
  hardcoded) and `i` the net capitalization rate. Same gross-up logic and exemption
  handling as `lvt/ubi_utils.py` — reuse `model_full_land_rent_tax`, do not reimplement.
- `T_land` = the current land-portion property tax, absorbed (not abolished): the taxing
  bodies must be made whole for it out of the rent levy. It appears in Target exactly once
  and never in any abolition bundle (assert this).
- `κ_j ∈ [0,1]` = fraction of abolished tax `j` that reappears as site rent. Applied
  linearly; capture `φ` applies to the increment too (it is site rent like any other).
- `G` = road/curb rents (congestion + curb pricing), a hand-set scenario input, Section 6.
- `κ*` is exact because κ enters linearly. Headline table: rows = bundles, columns =
  (surface × rent basis × φ), cells = κ*. `κ* ≤ 0` → pencils statically; `κ* > 1` →
  impossible even at full ATCOR.

Dividend per capita = Pot / population, where population is **read from the existing tract
export** (`analysis/data/philadelphia_lvt_ubi_ty2026.csv`, sum of `total_pop`) or recomputed
via `get_population_by_tract` — never hardcoded.

Approximation to note in the notebook, not to fix: the κ·T increment is measured gross of
the existing land-tax capitalization interaction (second-order at these rates).

## 3. The revenue ledger

Implement as a small module (`lvt/single_tax.py`): a list of dataclass lines, each carrying
`name, amount, year_basis (FY/TY + year), accrual ('billed'|'collected'), body ('city'|'school'|'pica'),
classification ('labor'|'capital'|'absorbed'|'kept'|'out_of_scope'), source (document + page/URL),
retrieved (date), status ('verified'|'estimate')`. The notebook renders the ledger as a table
and **prints a loud warning block listing every `estimate` line**; κ* tables footnote them.
No line may enter any computation without a `source`.

Sourcing rules:

- Prefer one consistent vintage: **FY2024 actuals** from the City ACFR and School District
  ACFR/adopted budget, with a stated bridge to the TY2026 property-tax modeling (the repo's
  property figures are TY2026 billed). Do not mix actuals and projections silently.
- Billed vs collected: the property-tax side of this repo is billed; wage-tax receipts are
  collected. Choose **billed where derivable**, and handle the wedge once, via the
  collections-haircut scenario (Section 7), not by ad-hoc per-line adjustment.
- If a precise figure cannot be verified at build time, the line enters as `estimate` with
  the best available number — never silently hardened. (Same rule as the global
  geographic-facts memory: retrieve, don't recall.)

Lines (amounts to be sourced at build time; classifications are decided here):

| Line | Class | Body | Notes / trap |
|---|---|---|---|
| Wage & Earnings Tax | labor | city (+PICA) | See PICA rule, §4.3. Repo-modeled $2.4528B (resident $1.6238B + non-resident $0.8290B) vs published ≈$2.51B — carry both, state which drives the tables. |
| Net Profits Tax (NPT) | labor | city | Receipts only; never rate×base (§4.1). Not included in the wage-tax swap's $2.45B. |
| Real property tax — building share | capital | city+school | From the repo model: $1.540B at TY2026. Source is the executed model, not budget docs. |
| Real property tax — land share | **absorbed** | city+school | $0.602B at TY2026. In Target once; never abolished. |
| BIRT | capital | city | Receipts (credit interaction §4.1). |
| School Income Tax (SIT) | capital | school | Tax on residents' unearned income; small; belongs in the capital bundle. |
| Use & Occupancy (U&O) | capital | school | Separate levy on the same assessed base; no receipts overlap with property tax (§4.5). Abolished whole. |
| Realty Transfer Tax (city share) | capital | city | Abolished; note that "keep RTT" is not revenue-preserving anyway — under full capture the land component of its base vanishes (§4.6). |
| Parking Tax | **kept** | city | A land-use charge, part of the road-rent family. Excluded from both sides; listed for visibility. |
| Sales, Beverage, Hotel, Liquor, Amusement | **out_of_scope** | — | Consumption taxes; the program is capital-and-labor. Rendered in an excluded-taxes table so the scope choice is visible. |

## 4. Overlap and double-counting rules

1. **NPT vs BIRT:** taxpayers credit 60% of BIRT against NPT, so published NPT receipts are
   already net of the credit. Summing published receipts is correct; computing NPT as
   rate×base double-counts. Use receipts.
2. **Wage vs Earnings vs NPT:** Wage and Earnings are one instrument reported jointly — if a
   source reports them combined, do not add an Earnings line again. NPT is a separate line.
3. **PICA:** roughly 1.5 points of the resident wage-tax rate is the PICA portion. The
   ledger must state whether the wage-tax figure includes it (the published ≈$2.51B total
   should; verify). If a source excludes PICA, add it as its own line — workers pay it, so
   abolition must replace it. Caveat for the notebook's limitations cell: PICA revenue
   services PICA bonds; stranding it is a legal constraint on any real implementation.
4. **Property tax:** city+school combined, split land/building from the repo's TY2026 model
   ($2.143B ≈ $0.602B + $1.540B). Both bodies must be made whole.
5. **U&O:** separate levy, separate receipts; no overlap adjustment. (Refinement not taken:
   its land component could be absorbed rather than abolished; note and move on.)
6. **RTT:** abolished. If a scenario keeps it, its base must be haircut for the vanishing
   land-price component — simpler to abolish, so abolish.
7. **Absorbed vs abolished:** assert programmatically that no ledger line appears in both.

## 5. Rent-supply side

- **Surfaces:** OPA (`taxable_land` from `parcels_ty2026.gpq`) and LYCD (land values joined
  from `analysis/data/philadelphia_lycd_ty2026.csv` exactly as `model_lvt_ubi.ipynb`
  Section 3 does — same key normalization, same 1.25–1.65 ratio guard). **The ledger uses
  only the LYCD export's `taxable_land_value` column**, which is unaffected by the known
  LYCD-baseline defect (Limitation 19, `docs/LVT_UBI_GUIDE.md`); the defective
  `current_tax`/`tax_change` columns must not be read. Safe to build before that fix lands.
- **Bases:** `taxable` (default) and `full` (reaching exempt land) as in `ubi_utils` —
  the `full` basis is a sensitivity, flagged as requiring PA exemption-law change.
- **Rates:** `i ∈ {0.03, 0.04, 0.05, 0.06, 0.07}` (default 0.05); `φ ∈ {0.85, 1.0}`;
  `t` from `tax_year_params(2026)`.
- **Reference magnitudes for wiring checks** (from the executed TY2026 notebooks, i=0.05,
  taxable basis): `R₀(OPA) ≈ $2.753B`, `R₀(LYCD) ≈ $4.008B`, population 1,593,208. The
  notebook recomputes all of these from data and asserts agreement within 1%.

## 6. Road/curb rents (G)

Scenario inputs, not estimates — three named levels, all constants in one cited block:

- Congestion charge: LOW $0 / CENTRAL $100M / HIGH $250M gross. Anchor citation: NYC CBD
  tolling actuals (≈$500M/yr run-rate on a much larger CBD), scaled by CBD employment.
- Curb pricing: LOW $0 / CENTRAL $50M / HIGH $150M gross. Anchor: PPA on-street meter
  revenue actuals (PPA annual report) with a Shoup-style market-pricing multiple.

Label everywhere as gross of operating cost, hand-set, and outside the parcel base. Do not
let these numbers migrate into prose as findings.

## 7. Collections / surrender haircut

One scenario axis, `h ∈ {0, 5%, 10%, 15%}`, applied as `R₀ → (1−h)·R₀`. It stands in for
both ordinary delinquency (~5% is the repo's known wedge) and the negative-rent surrender
tail at full capture (Limitation 17). Grounding section in the notebook: join the parcel
export to OpenDataPhilly's real-estate tax delinquency dataset (Carto,
`real_estate_tax_delinquencies`) and the Land Bank inventory; report the count and land
value of parcels that are ≥3 years delinquent or plausibly surrender-risk, as evidence for
which `h` is realistic. Keep this bounded to one section — the full surrender analysis is
its own future notebook.

## 8. Bundles

- **B0 — none.** Wiring check: with φ=1, OPA, taxable, G=0, h=0, the pot must equal the
  as-built LVT-UBI pot **$2.151B ± 1%** and $1,350/resident. Ties the new notebook to the
  proven one.
- **B1 — building tax only.** The combined reform. Assert the invariance result: at κ_B=1
  the pot equals B0's pot (± rounding) — the executable form of "a structure tax under full
  capitalization is a land tax in disguise."
- **B2 — Wage & Earnings only.** The swap at full capture. Cross-check: its implied
  standalone land levy should reproduce the wage-tax swap notebook's 57.0 mills ≈ 89% of
  the 64.0-mill full-capture equivalent.
- **B3 — B1 + B2** (wage + entire property tax). The expected headline: κ*(B3, LYCD,
  central G) ≈ 0.07–0.15; κ*(B3, OPA) ≈ 0.4–0.5. If the built notebook lands far from
  this, suspect the ledger before suspecting the conclusion.
- **B4 — B3 + BIRT + NPT + SIT** (all city/school taxes on labor and capital income).
- **B5 — B4 + U&O + RTT** (full program). Expected: κ* well above 0.5 on OPA, likely >1 in
  pessimistic cells — report it plainly; "does not pencil" is a finding.

## 9. Outputs

- Export: `analysis/data/philadelphia_single_tax_ledger.csv` — one row per
  (bundle × surface × basis × φ × i × G-level × h): Target, R₀, Supply at κ∈{0,0.25,0.5,0.75,1},
  κ*, pot and per-capita dividend at the three named κ scenarios
  (Conservative κ_B=0.5/κ_W=0.1/others 0.2; Central 0.7/0.25/0.4; ATCOR all 1.0).
- Charts (to `analysis/reports/philadelphia_single_tax/`): κ* heatmap (bundle × scenario);
  dividend-vs-κ lines per bundle; a ledger waterfall (Target composition vs Supply).
- Tests: κ* algebra against brute force on grid points; B0 and B1 invariance asserts;
  absorbed/abolished disjointness; ledger completeness (every line has source + class).
- Docs: results referenced from generated outputs per the AUTOGEN convention — no
  hand-typed numbers in README/docs.

## 10. Out of scope (Tier 2+), recorded so nobody "helpfully" adds them

- **Anchoring κ_W to Jacob & Livas (2026).** Deliberately deferred: their Table 4 "land
  value" is the model's fixed-factor value (counterfactual value = 12.28× wage-tax revenue
  ≈ $30B, ≠ OPA's $43B assessed land), reported gross of the replacement LVT, under an
  open-city assumption. Mapping their +9.4–21.8% land-value counterfactual into this
  ledger's κ requires reconciling those objects — a Tier-2 task with their model in hand,
  not a constant to eyeball into Tier 1.
- Any behavioral response, migration, agglomeration, or the dividend-in-utility question.
- Realistic congestion/curb revenue modeling (network or occupancy data).
- Zoning counterfactuals (Gyourko–Krimmel anchoring or QSM supply elasticities).

## 11. Sequencing

1. The LYCD-baseline-fix task (spawned 2026-08-26) may land while this is being built —
   irrelevant to this notebook (Section 5), but rebase before committing if it touched
   `lvt/ubi_utils.py` signatures.
2. Notebook follows repo code style (no decorative headers, `data_scrape` conventions,
   `tax_year_params()` for all rates) and the standard headless execution command.
3. Slug: `philadelphia_single_tax_ty2026`.
