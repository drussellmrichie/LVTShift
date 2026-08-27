# κ — published capitalization evidence and the bounds it supports

Evidence base behind `KAPPA_BOUNDS` in [`lvt/single_tax.py`](../lvt/single_tax.py).
Written 2026-08-27 in response to finding **M3** of
[`analysis/audits/single_tax_ledger_audit_2026-08-26.md`](../analysis/audits/single_tax_ledger_audit_2026-08-26.md),
which flagged the three named κ scenarios as invented numbers with no citation,
exported as if they were results.

The disposition taken was to **source them**, not to rename them. Two of the three
scenarios (`illustrative_low`, `illustrative_mid`) are gone; `lit_low` and `lit_high`
replace them and every value in them is one end of a published estimate below.

> Numbers quoted from papers are hand-typed here on purpose: this is a literature
> record, not a pipeline output, and nothing regenerates it. The values that actually
> enter the model live in `KAPPA_BOUNDS` and are asserted against this file's numbers
> by `tests/test_single_tax.py`.

---

## 1. What κ actually is, and why the literature does not measure it directly

In the ledger, for an abolished tax `j`:

```
κ_j  =  (increase in annual site rent when j is abolished) / (annual revenue of j)
```

No published paper estimates that ratio. Two nearby objects are estimated often, and
each needs a stated bridge to κ.

**(a) Capitalization rate** — the share of the present value of a tax change that shows
up in the asset price. Structures are reproducible and supplied at construction cost,
so once supply has adjusted, a fully capitalized change in a tax on structures accrues
to the factor that cannot be reproduced: the site. A capitalization rate therefore maps
to κ more or less directly, *provided* the estimate is for a tax on structures and the
adjustment horizon is long enough. The weak point is that these studies measure
capitalization into the whole property price and do not decompose land from structure.

**(b) Landowner incidence share (θ)** — the share of the tax *burden* borne by
landowners. Here

```
κ  =  θ · (burden / revenue)
```

and `burden ≥ revenue` for any distortionary tax, because the burden includes the
excess burden. Setting `κ = θ` therefore **understates** κ. That is the conservative
direction for this model: it understates the pot and the dividend, never the reverse.
The gap between θ and κ is precisely Gaffney's EBCOR claim — that abolishing a
distortionary tax raises rent by more than the revenue foregone — which is why
`κ > 1` is admissible here and why one of the bounds below sits above 1.

**What none of this covers.** Every estimate below is a *marginal* one: a small change
in a tax that continues to exist. The program this ledger prices is the abolition of
several taxes at once, at full land-rent capture. Nothing in the literature speaks to
whether a marginal capitalization rate survives at that scale. Treat the bounds as
bracketing the marginal case and nothing more.

---

## 2. The bounds

| family | low | high | low anchor | high anchor |
|---|---|---|---|---|
| `building` | 0.00 | 1.006 | Löffler & Siegloch (2021) | Coste (2024) — Philadelphia |
| `wage` | 0.25 | 1.00 | Suárez Serrato & Zidar (2016), *transferred* | perfect-mobility ceiling |
| `other` | 0.25 | 0.30 | Suárez Serrato & Zidar (2016) | Suárez Serrato & Zidar (2016) |

`atcor` remains κ = 1 for every family. That is the definition of
All-Taxes-Come-Out-Of-Rents, not an estimate, and it is the only scenario in the export
that was defensible before this pass.

---

## 3. `building` — the property tax on structures

### High bound: 1.006 — Coste (2024), and it is about Philadelphia

Jonah Coste, *Capitalization of Property Tax Incentives: Evidence From Philadelphia*,
FHFA Staff Working Paper 24-01, January 2024.
<https://www.fhfa.gov/papers/wp2401.aspx>

The 10-year construction abatement is a near-ideal experiment: contemporaneous
intra-jurisdiction tax variation, of known and finite duration, with abated and
unabated properties entitled to identical city services.

- Preferred specification: **100.6% initial capitalization** into home prices.
- 95% CI **86.0%–115.2%**.
- Carrying discount-rate uncertainty (`r − g` from 1% to 5%) widens it to
  **78.6%–125.5%**.
- Benefits become *over*capitalized as abatements near expiry: at age 9 buyers pay a
  6.7% premium against a theoretical 1.8%.
- Coste reads the result as the abatement "incentiviz[ing] development by increasing
  the price builders receive for new construction" — i.e. it lands on the development
  site.

This is the single most relevant estimate available to this model: same city, same tax,
and the same abatement `model_post_abatement.ipynb` already handles. **Caveat:** it
measures capitalization into the whole home price. Attributing that premium to the site
relies on structures being supplied elastically at construction cost, which is the
standard argument but is an argument, not a measurement.

### Low bound: 0.00 — Löffler & Siegloch (2021)

Max Löffler and Sebastian Siegloch, *Welfare Effects of Property Taxation*, IZA DP No.
14195, March 2021. <https://docs.iza.org/dp14195.pdf>

5,200 German municipal property-tax reforms, rents and sale listings, event-study design.

- Gross rents rise to **full pass-through** to tenants by year three.
- Net rents dip in the short run and **revert to the pre-reform level**.
- Offered sales prices show a short-run dip and **no significant medium-run effect**.
- Pass-through is *lower* where housing supply is inelastic.
- They report the prior US literature as estimating **0–115%** shifted onto renters
  (Orr; Heinberg & Oates; Hyman & Pasour; Dusansky et al.; Carroll & Yinger).

Landowners end up bearing approximately none of it, which is θ ≈ 0.

**Caveat that cuts against taking this at face value here:** the German Grundsteuer runs
on a frozen 1964/1935 assessment base, so it is closer to a per-property lump sum than
to a US ad valorem tax on structures, and their headline outcome is the rental market
rather than the land market.

### Corroborating

Xueying Lyu (2024), *Revisiting property tax capitalization*, Regional Science and Urban
Economics 108. <https://doi.org/10.1016/j.regsciurbeco.2024.104028> — Shanghai
progressive property-tax pilot, DiD: a 0.2pp higher marginal rate produces a ~2.73%
price fall, implying **at least 71%** of expected liabilities capitalized within a year.
Reported as a floor.

Sirmans, Gatzlaff & Macpherson (2008), *The History of Property Tax Capitalization in
Real Estate*, Journal of Real Estate Literature 16(3), 327–344 — survey; the typical
finding is *partial* capitalization, varying with housing supply elasticity.

### Reading the band

0.00–1.006 spans the whole space, and that is the honest state of the evidence rather
than a failure to look: the best-identified US estimate is full capitalization and the
best-identified European one is none. What tilts the reading is that the US estimate is
Philadelphia's own abatement. This band is the largest single source of uncertainty in
any bundle containing the property tax (B1, B3, B4, B5).

---

## 4. `wage` — Wage & Earnings Tax and Net Profits Tax

**This is the weakest link in the evidence base, and it is also the largest family in
every bundle from B2 up.** No published study reports the landowner share of a local
wage or earnings tax. Both bounds are therefore weaker than the `building` ones: the low
end is transferred from a different instrument and the high end is a theoretical
ceiling.

### High bound: 1.00 — the perfect-mobility ceiling

> "With perfect mobility, the incidence of local taxes is fully borne by landowners, the
> immobile factor."

Brülhart, Danton, Parchet & Schläpfer (2025), *Who Bears the Burden of Local Taxes?*,
AEJ: Economic Policy 17(1), 464–505, at p. 468.
<https://doi.org/10.1257/pol.20220462>

Quoted for what it is — the standard benchmark, and the paper's own contribution is that
moving is costly so realised incidence falls *below* it. It coincides with `atcor` by
construction.

### Low bound: 0.25 — transferred from Suárez Serrato & Zidar (2016)

See §5. The nearest structural estimate of the landowner share of a mobile-base
subfederal tax puts landowners at 25–30%. Transferring it to a wage tax is an
assumption: a wage tax and a corporate tax reach land through different channels, and
Philadelphia's reaches non-resident commuters at 3.44% as well as residents, which has
no analogue in the corporate setting. Flagged `directness = 'transferred'` in
`KAPPA_BOUNDS` and surfaced in the exported bounds table.

### Corroborating — sign and magnitude, but no share

These establish that local income taxes *do* capitalize, with the expected sign and a
non-trivial magnitude. None of them yields a revenue share, because converting an
elasticity to a share needs the housing-value-to-tax-revenue ratio in the study's
setting, which none of them reports.

- **Brülhart et al. (2025)**: structural landlord incidence `η_p,τ*` = **−0.281**
  (s.e. 0.021); reduced-form housing-price elasticity with respect to local income tax
  rates **−0.30**. Swiss municipalities, border-pair design with instrumented rates. In
  their model this is borne entirely by absentee landlords; they note about a third of
  landlords are resident in the same municipality.
- **Basten, von Ehrlich & Lassmann (2017)**, *Income Taxes, Sorting and the Costs of
  Housing*, Economic Journal 127(601), 653–687.
  <https://doi.org/10.1111/ecoj.12489> — income tax elasticity of rents of about
  **0.26** in absolute value; the boundary-discontinuity design *halves* conventional
  estimates, and about **one third** of the effect is income sorting rather than
  capitalization. The published abstract does not state the sign convention, so it is
  used here for magnitude only.
- **Albouy (2009)**, *The Unequal Geographic Burden of Federal Taxation*, JPE 117(4),
  635–667. <https://doi.org/10.1086/605309> — simulated long-run effect of the federal
  wage-tax wedge in high-wage cities: **land prices −21%** against **housing prices
  −5%**. Direct evidence that a tax on wages lands disproportionately on land, but it is
  federal rather than local and is reported as price levels, so it pins no share.

---

## 5. `other` — BIRT, School Income Tax, Use & Occupancy, Realty Transfer Tax

### Both bounds: 0.25–0.30 — Suárez Serrato & Zidar (2016)

Juan Carlos Suárez Serrato and Owen Zidar, *Who Benefits from State Corporate Tax Cuts?
A Local Labor Markets Approach with Heterogeneous Firms*, American Economic Review
106(9), 2582–2624. <https://doi.org/10.1257/aer.20141702>

> "firm owners bear roughly 40 percent of the incidence, while workers and landowners
> bear 30-35 percent and 25-30 percent, respectively."

The 2023 corrected structural model moves the shares to firm owners 38.1%, workers
35.0%, **landowners 26.8%** — inside the original range.

These are shares of the welfare change, not of revenue, so the bridge in §1(b) applies
and κ = θ understates.

### Why the band is narrow, and why that is misleading

It is narrow because it is **one study's reported range**, not because the literature
has converged. Do not read it as a confidence interval on the family. Two things pull in
opposite directions and neither is in the band:

- **Down.** Fuest, Peichl & Siegloch (2018), *Do Higher Corporate Taxes Reduce Wages?
  Micro Evidence from Germany*, AER 108(2), 393–418.
  <https://doi.org/10.1257/aer.20130570> — workers bear about **half** the burden of a
  municipal business tax, leaving less for landowners and firm owners together. Brülhart
  et al. also note the worker share is higher in smaller jurisdictions.
- **Up, for the RTT slice specifically.** Kopczuk & Munroe (2015), *Mansion Tax: The
  Effect of Transfer Taxes on the Residential Real Estate Market*, AEJ: Economic Policy
  7(2), 214–257. <https://doi.org/10.1257/pol.20130361> — the incidence of the NY/NJ 1%
  notch "falls on sellers, may exceed the value of the tax". A transfer tax borne by the
  asset owner at θ possibly above 1 is the EBCOR pattern in miniature. It is local to a
  notch at $1M, so it does not generalise to the whole RTT base.

The RTT is $356.4M of the `other` family and appears only in B5.

---

## 6. What would actually improve this

In rough order of leverage:

1. **A landowner-share estimate for a local wage tax.** It is the largest family and the
   only one with no direct evidence at either end. The sibling repo
   `C:/projects/lvt_pass_through_test` is set up on the closest available design (PA
   split-rate adoptions and rescindments) and would speak to the `building` family
   directly if it lands.
2. **A land/structure decomposition of Coste's abatement premium.** It would convert the
   `building` high bound from an argument into a measurement.
3. **Anything on whether marginal capitalization rates survive at full capture.** Every
   bound here is marginal; the program is not.
