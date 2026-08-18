# Who owns Philadelphia's vacant land and parking lots?

*Generated from `results/` by `make_brief.py` — do not edit numbers in this file by hand.
Tax year 2026, 583,167 parcels, revenue-neutral 4:1 split-rate, OPA land values.*

## The short version

Vacant land and surface parking are far more LLC-owned than housing, but the LLCs are
mostly **local**, not out-of-state. Both halves of that sentence matter politically, and the
second half cuts against the framing an LVT campaign might reach for first.

- **31.9% of privately-owned vacant land value is held by LLCs**
  (upper bound 35.8%; see *Truncation* below), against
  **5.0% for single-family homes** — a **6.3×** gap.
- Surface parking runs 25.9% (commercial lots) to
  27.1% (non-commercial); structured garages
  27.0%.
- But LLC owners of vacant land and parking are **49.1% in-city by
  land value** and only **23.6% out-of-state**. Of
  2,733 distinct LLC entities in these categories, 1,689 mail to
  a Philadelphia address and 261 mail out of state.
- Under the modelled reform, LLC-owned vacant land and parking pay
  **$20.0 million more per year** across 8,625 parcels.

## Vacant land is not the most LLC-owned category

It ranks behind two others. Industrial land is 47.2% LLC-owned and
large multi-family 40.5%, both above vacant land's
31.9%. A campaign that claims vacant land is uniquely investor-held is
overstating a real but narrower fact: what is distinctive about vacant land is the gap
against *housing*, not against commercial property generally.

The full ranking is in `results/llc_share_by_category.csv`.

## Individuals still own most vacant parcels

Within taxable vacant land, individuals hold 16,722 parcels against
10,950 held by business entities — individuals own more *parcels*,
businesses slightly more *value*. "Vacant lots are owned by speculators" is true of the
dollars and false of the parcel count, and any messaging that implies otherwise will not
survive contact with a reporter pulling ten addresses at random.

Note also that most *publicly* owned vacant land — the City, Land Bank, Redevelopment
Authority, PHA — is fully exempt and therefore sits outside this taxable universe entirely.
Only 550 of the 30,633 parcels in the
headline categories are publicly owned (1.8%). Any claim
about "who owns the vacant land" that includes exempt public holdings is answering a
different question than the one about who pays the tax.

## Across all property types, LLCs really are more absentee — but vacant land least of all

Owner mailing address is resolved for every private owner in all
32 categories (`results/owner_geography_by_category.csv`), which
gives the LLC figures a denominator:

| Group, citywide | In-city | Out-of-state |
|---|---|---|
| All private owners | 72.7% | 11.3% |
| LLC owners only | 41.8% | 25.7% |

So LLCs *are* markedly more out-of-town than owners generally. But the categories a land
value tax targets sit at the local end of that range: vacant-land LLCs are
16.5% out-of-state, well below the 25.7% LLC
citywide average — though still above single-family's 11.7%. The most
absentee LLC category by a wide margin is commercial property at
36.8%.

The uncomfortable implication for messaging: "out-of-state speculators are sitting on our
vacant lots" is the one version of the claim the data does not support. "Absentee owners hold
our commercial land" is much better supported — but that is a different reform argument.

## The out-of-state story is real but small

Out-of-state LLC ownership is genuine rather than a mail-drop artifact, and it is
concentrated:

- **0 parcels** in the whole set mail to Delaware — the registered-agent
  confound that usually contaminates this analysis is essentially absent here.
- The out-of-state vacant/parking parcels spread across 287 distinct
  mailing addresses, with at most 9 different LLC names sharing
  any one address. Citywide across all property types it is
  3,163 addresses, at most
  22 names at any one. Registered-agent hubs look like
  dozens of names at one address; neither scope does.
- But the top 10 addresses hold 49.0% of out-of-state
  LLC land value — a handful of large institutional owners (see
  `results/out_of_state_mail_addresses.csv`), not a broad absentee class.

So the honest formulation is: **a small number of large out-of-town corporate owners, and a
much larger number of local LLCs.**

## How much to trust these numbers

**Classifier accuracy (hand-adjudicated, n=210).** LLC precision is
100.0% — no false positives in the sample — so the LLC share is a clean *lower*
bound. Per-form precision is in `results/classifier_precision.csv`.

**Truncation.** OPA truncates owner names at two widths, 25 and 40 characters, cutting the
legal suffix off. 25.7% of sampled `Other business` names are entities whose
form the string cannot resolve (`NOAH REALTY INVESTMENTS L`). Truncation only ever moves
entities *out* of the LLC bucket, so every LLC figure here is a floor; the reported upper
bound reallocates those parcels at the LLC rate observed among untruncated names.

**Mailing address is a location proxy, not beneficial ownership.** An out-of-state address
may be an accountant for a Philadelphian; a Philadelphia address may front an entity owned
elsewhere. True beneficial ownership is not obtainable at scale by any route: the FinCEN
beneficial-ownership database is not public and is exempt from FOIA, and its reporting
requirement for domestic companies was narrowed in 2025. Tracing individual owners through
PA Department of State filings and deeds is feasible by hand for the largest holders only.

**Universe definition.** Vacant land here is the assessor's own building codes, which is what
the tax actually bills. It agrees reasonably with the City's 2025 Land Use layer
(Jaccard 0.76) and with L&I's Vacant Indicators
(Jaccard 0.59). The parking universe does **not** agree with the Land Use
layer (Jaccard 0.03) — that layer identifies only
209 parking parcels citywide against the assessor's
2,208, so it under-identifies surface parking badly and is not usable as a
parking source. The assessor codes are corroborated instead by an independent OPA extract at
Jaccard 0.996. Full comparison in `results/universe_reconciliation.csv`.

**Land values.** Headline figures use OPA taxable land values. Re-running on the LYCD
location-value model moves the vacant-land LLC share by
2.2 percentage points, and the largest divergence in any category is
15.2 points — see `results/robustness_opa_vs_lycd.csv`.

**Concentration figures are lower bounds.** Entity resolution unions LLC names that share a
mailing address, but only for business-class names — merging individuals by address chains
condo towers and management offices into fictitious mega-owners. Shell networks registered
at different addresses under unrelated names remain unresolved.

## Files

| File | Contents |
|---|---|
| `results/llc_share_by_category.csv` | LLC / +LP / all-business shares per category, all-parcel and private-only |
| `results/ownership_by_category.csv` | Parcels, land value, lot area and tax change by category × owner sector |
| `results/llc_geography_by_category.csv` | Where LLC owners mail, per category, with distinct entity counts |
| `results/owner_geography_by_category.csv` | Where **all** private owners mail, per category — the baseline |
| `results/llc_entities.csv` | One row per resolved LLC entity |
| `results/out_of_state_mail_addresses.csv` | Out-of-state mailing addresses, all property types, for the mail-drop test |
| `results/universe_reconciliation.csv` | OPA vs L&I vs City Land Use agreement |
| `results/robustness_opa_vs_lycd.csv` | Headline shares under both land-value models |
| `results/classifier_validation.csv` | The adjudicated name sample |
| `results/parking_recarve.csv` | What moved out of which category into surface parking |
| `figs/` | Five charts |
