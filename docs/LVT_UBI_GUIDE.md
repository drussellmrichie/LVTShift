# LVT + UBI Guide — Full Land-Rent Capture with a Per-Capita Dividend

This guide documents a third modeling paradigm, alongside `docs/LVT_MODELING_GUIDE.md` (rate and
base shifts in the property tax) and `docs/WAGE_TAX_SWAP_GUIDE.md` (swapping one tax instrument for
another). This one taxes **100% of annual land rent**, leaves the building tax exactly as billed
today, holds the taxing bodies harmless on the land portion of their current revenue, and pays the
residual out as an equal per-capita dividend to residents.

Worked example: `cities/philadelphia/model_lvt_ubi.ipynb`. Module: `lvt/ubi_utils.py`. Report
function: `lvt.viz.create_lvt_ubi_report`. Unit tests: `tests/test_ubi_utils.py`.

## Why this needs a different approach

Every property-tax reform elsewhere in this repo is revenue-neutral by construction: a fixed levy
is redistributed across parcels, and the modeling question is *who pays a different share*. This
one is not, and cannot be. Raising more than today's levy **is** the reform — the surplus is what
funds the dividend — so there is no revenue target to solve a millage against. The rate is
exogenous: a capture share of an imputed rent flow.

Three things follow.

**There is no revenue-neutral solve.** `lvt/ubi_utils.py` never calls `model_split_rate_tax`. That
is deliberate; do not "fix" it by adding a solver.

**`save_standard_export` and `create_city_report` do not apply.** The standard export's revenue
drift check assumes revenue neutrality and would fail by construction, and the standard report's
charts are all framed as "share of a fixed bill". The module writes its own exports and the report
function is a separate sibling.

**The primary result is a transfer between people, not between parcels.** A parcel-level table
answers "whose bill rises", which under this reform is just a restatement of "where is land
valuable". The question that needs answering is whether a *resident* comes out ahead once the
dividend is counted, and that only exists once population is attached — so the primary deliverable
is tract-level, like the wage-tax swap's.

## The capitalization gross-up

An assessed land value is a market price, and that price already capitalizes the ad-valorem tax the
land currently bears. For a perpetual site rent `R`, net capitalization rate `i` and current rate `t`:

```
P * i = R - t * P    =>    R = P * (i + t)
```

So observed assessed land value must be grossed up by `(i + t)`, **not** merely multiplied by `i`.
At Philadelphia's `t = 0.013998` and `i = 0.05` the factor is `0.063998` — 28% more rent than a
naive `P * i`. `lvt.ubi_utils.land_rent_from_value` implements this; passing `tax_rate=0` recovers
the naive version and is available only so the difference can be shown.

**`i` is a net capitalization rate, `r − g`** — the nominal required return on land minus expected
rent growth — not a raw discount rate. Anchoring: a ~7.5% nominal required return against ~2.5%
rent growth gives ~5%. This matters for interpretation: where a site's price embeds an option or
growth premium (vacant land held speculatively), the correct denominator is larger than `i`, so
`P * (i + t)` **overstates currently realizable rent** — on precisely the parcels an LVT targets.
That is arguably the intended incentive, but it is an overstatement and is stated as one.

## The baseline, and the held-harmless credit

Because the reform is not revenue-neutral, `current_tax` is not a bookkeeping intermediate that
cancels out of the answer. It is the counterfactual bill the reform is measured against, and every
dollar of the dividend is the gap between the two. So the baseline is **the actual levy, always**:
`t × (assessed land + assessed building)`, the bill the parcel is really sent.

That matters the moment the land the rent is priced from is not the assessor's — the
`LAND_VALUE_SOURCE = 'lycd'` cross-run. `model_full_land_rent_tax` therefore takes the two land
columns for two different jobs:

| Argument | Role | Philadelphia |
| --- | --- | --- |
| `land_value_col` | the land the **current** tax is billed on — the baseline | always `taxable_land` |
| `rent_basis_col` | the land the **rent** is priced from | `model_land`, or `full_assessed_land` |
| `baseline_total_col` | the billed total the reconstruction is checked against | `taxable_total` |

**What "the land portion of current revenue" means is then forced, not chosen.** The reform
stipulates two things — the building tax is byte-identical to today's (`t·B`), and the baseline is
the real levy (`t·(L_assessed + B)`) — so the land credit the taxing bodies are held harmless on is
the residual of the second after the first, namely `t·L_assessed`. Pricing that credit off the
alternative surface instead would hold them harmless on revenue they never collected. The pot is
therefore `phi·(i+t)·L_rent − t·L_assessed`, and the two land values are genuinely different
quantities in it.

The reading this rejects is that an independent land surface is a *reassessment*, whose baseline
would be what the parcel would pay had the assessor valued land that way. It is not one: LYCD
replaces land without re-deriving buildings, so it implies no coherent parcel total, and a
revenue-neutral reassessment is a different reform served by `lvt/reassessment.py`. An independent
surface here answers "how much rent does this site throw off", never "what is this parcel billed
today" — so it belongs in the rent basis and nowhere else.

**Pass `baseline_total_col`.** It is the only guard that catches a baseline rebuilt on the wrong
land column: the city-level revenue validation runs on the assessor's own total and never sees the
model's frame, and the zero-sum check nets the reform against whatever baseline it is handed, so
both pass unchanged while every `current_tax` is wrong. That is exactly how Limitation 19 went
undetected. The check is exact arithmetic, so its tolerance is 0.01% by default.

## The three identities

Each holds exactly. Each is asserted in the notebook and unit-tested, rather than described in
prose and hoped for.

**1. `tax_change = L * (phi*(i+t) - t)`**, which at full capture collapses to **`i * L`**.
*Precondition:* the rent basis is the land the current tax is levied on. In general
`tax_change = phi*(i+t)*L_rent − t*L_assessed`, and the collapse needs the two to be the same
value. It therefore does not hold under `RENT_BASIS = 'full'`, where rent is charged on a base the
current tax does not touch, nor under `LAND_VALUE_SOURCE = 'lycd'`, where it is charged on a
different surface. `summary['rent_basis_matches_current_basis']` reports the precondition — by
value, not by column name, so an OPA run that copies `taxable_land` into its own `model_land`
column is correctly reported as matching. The notebook asserts whichever form applies.

**2. `owner_residual = (i+t)*(L+B) - new_tax = (1-phi)*(i+t)*L + i*B`**, which at full capture is
**`i * B`**. Apply the same capitalization logic to the whole property and the owner is left with a
normal return on the structure and zero on the land — exactly the Georgist target. This is the
arithmetic proof that the rent levy and the retained building tax do not double-count, and it is
the shortest answer to the objection that the combination is confiscatory: it is confiscatory of
land rent only, by construction.

**3. `land_wealth_destroyed = ubi_pot / i`**, exact for every `phi` and every rent basis, under
the held-harmless framing. Land price is capitalized rent net of the land tax actually borne:
`(R − t·L_assessed)/i` before, `(R − phi·R)/i` after. The difference is
`(phi·R − t·L_assessed)/i = ubi_pot/i`. Where the two bases agree this reduces to the familiar
`L` and `L(i+t)(1-phi)/i`; where they do not, the assessed sum is *not* the price this model's own
rent and tax figures imply — a rent surface taxed at a smaller assessed one capitalizes to more
than either — and using it would break the identity. The one-time capitalization loss to
landowners equals the present value of the dividend stream, to the dollar.

**Stock and flow are two views of one transfer and must never be added.** Current owners bear the
one-time loss. The annual levy is borne by whoever holds title — and anyone who buys land after the
reform paid ~$0 for it and bears no net burden at all. Any statement of the form "landowners lose
$X billion in wealth *and* $Y billion a year" is double counting.

## The two revenue framings

| Framing | Dividend pot | Budget effect |
| --- | --- | --- |
| `city_held_harmless` (default) | `sum(L) * (phi*(i+t) - t)` | none — the taxing bodies keep today's revenue |
| `full_redistribution` | `phi*(i+t) * sum(L)` | an unfunded hole of exactly `t * sum(L)` |

Held-harmless is the default because it is the only budget-neutral variant and because it has a
concrete institutional description: **the rent levy is collected as one charge; the first claim on
it is the City and School District's existing land-portion entitlement `t·L`, split in the
`city_mills` / `school_mills` proportion; the residual funds the dividend.** The full-redistribution
figure is always computed and reported alongside, and always prints its budget hole.

Under held-harmless the analysis is exactly **zero-sum**: every dollar of dividend is a dollar of
additional land tax, so `sum(net_gain) == 0` across tracts. The notebook asserts this. Under full
redistribution the sum equals the budget hole, which is a useful way to make the hole visible.

## The dividend

Denominator is ACS `B01003` resident population, summed over **the same tracts every other number
is keyed to** — never a hardcoded citywide figure, which drifts silently from the tract table and
breaks the adding-up check. `get_population_by_tract` fetches it alongside tenure (`B25003`) and
average household size (`B25010`), because the incidence result turns on tenure.

`child_share = 1.0` — every resident, adult or child, receives a full share — is the default
because it is a policy choice worth stating rather than assuming. Alaska's Permanent Fund Dividend
pays children a full share; many UBI designs pay a half share. `compute_ubi_dividend` takes the
parameter either way.

## Who wins

**The structural finding.** Land rent is collected from whoever holds title — commercial,
institutional and absentee owners included, many of whom live nowhere near the parcel — while the
dividend goes only to residents. Residents in aggregate therefore receive more than they pay. This
is the mirror image of the wage-tax swap's commuter transfer, running in the opposite direction,
and it is why the analysis is interesting at all. `summarize_ubi_incidence` measures it and
`who_pays.png` draws it.

**Renters.** A tax on pure land rent cannot be shifted to tenants — land supply is fixed, so the
levy falls entirely on the owner — and 100% capture is the case where shifting is *least* possible.
Renters therefore collect the dividend and owe none of the levy. This is first-order and standard,
and it is also incomplete: the second-order effect of releasing hoarded land is more supply and
*lower* rents, which would make renters larger winners still. That is unmodeled.

**Owner-occupiers** break even at

```
L* = ubi_per_capita * household_size / (phi*(i+t) - t)
```

`compute_breakeven_land_value` computes this and raises rather than returning nonsense when
`phi <= t/(i+t)` (below which no landowner loses and no threshold exists). It compares a
*parcel-level* bill against a *household-level* dividend, so **it is only meaningful for
owner-occupied single-unit parcels** — on a 40-unit apartment parcel one owner pays the land bill
while 40 households collect dividends. The notebook scopes it to OPA `category_code == 1` and uses
an occupancy-weighted tract household size, not a citywide scalar.

A single threshold in `L` also presumes identity 1. Where the rent basis is not the billed land the
bill depends on two land values at once and no threshold in either one partitions winners from
losers, so the notebook compares `tax_change` against the household dividend directly. That is
exact under either land source and gives the identical answer when the bases match — 76.5% of
single-family parcels on the TY2026 OPA run, either way. `breakeven_curve.png` still draws the
closed-form threshold, and the notebook says so when the two diverge.

## Robustness: what the answer does and does not depend on

**Lead with this.** At full capture under the held-harmless framing, a tract's net position is

```
net_j = i * (sum(L) * pop_j / P  -  L_j)
```

The sign does not involve `i`. And scaling every land value by a constant `k` scales every
`net_j` by `k`, also sign-preserving. Therefore:

> **The capitalization rate and any uniform bias in the level of assessment set the dollar
> magnitudes but cannot change who wins.** Only *non-uniform* assessment error redistributes.

Section 9 of the notebook demonstrates this rather than claiming it: it re-solves at 3%, 5% and 9%
and asserts the net-positive tract set is identical — on the `'opa'` default, where the precondition
below holds. This demotes `i` from a fatal free parameter
to a scale knob, and it is the single most important thing to say when someone objects that the
capitalization rate was picked out of the air.

**The invariance carries identity 1's precondition too.** When the rent is priced off a surface
that is not the billed land, the net position becomes

```
net_j = (i+t)*(sum(L_rent)*s_j - L_rent_j)  -  t*(sum(L_opa)*s_j - L_opa_j)
```

— two land surfaces weighted `(i+t)` and `t` — so raising `i` re-weights them and a tract can cross
the line, once, at `i* = t(B_j - A_j)/A_j`. Because `t << i` the effect is small but not zero: on
the TY2026 LYCD run, 5 of 408 tracts (0.9% of residents) move anywhere across 3–9%, and the share
of residents coming out ahead runs 75.2% → 74.3%. So the claim under a divergent surface is
*near*-invariance, and the notebook measures it instead of asserting it. The same caveat applies to
uniform assessment bias there: scaling **both** surfaces by `k` is still sign-preserving, scaling
only the rent surface is not.

**Ranked sensitivity: land share ≫ `i` ≫ `phi` ≫ `t`.**

- **Land share** dominates everything. The pot is `i × sum(land value)` — `phi·(i+t)·L_rent −
  t·L_assessed` in general — so it inherits the land assessment's bias, and the gross-up multiplies
  that bias by `(i+t)/t ≈ 4.6×`. OPA gives ~45% of improved parcels a land ratio of exactly 0.200 —
  its default formula, not a market observation.
  This is why `LAND_VALUE_SOURCE = 'lycd'` exists: the repo's independent LYCD land surface
  (`zone_psf × lot area`) has a land base roughly 46% larger ($62.6B vs $43.0B at TY2026), and two
  land surfaces bracketing the pot is far more credible than one. The gap is not mostly the
  default-ratio correction it looks like: OPA category 6 (vacant land) alone accounts for $11.6B
  of the $19.6B, where LYCD values the land at 4.9× the parcels' entire OPA assessed value, and
  10.8% of parcels end up with land worth more than their whole assessment. Under full capture
  that is Limitation 3 (assessment error becomes confiscation), so treat the LYCD run as an
  upper bracket rather than a better estimate.
- **`i`** scales the dollars over roughly a 2.3× range across the 3–7% band, and changes nothing
  about the partition.
- **`phi`** scales the dollars and, below `t/(i+t)` ≈ 0.219, flips the whole reform into a tax cut
  for landowners.
- **`t`** is nominal, while buyers capitalize an effective rate net of delinquency (~5% in
  Philadelphia), LOOP, senior freeze and assessment lag. Because `t << i`, this is genuinely
  second-order: moving `t` to 0.012 moves `R` by 1.5%.

## Limitations

Read these before quoting any number from this analysis.

1. **OPA's default land ratio.** ~45% of improved parcels carry a land ratio of exactly 0.200. The
   entire pot is `i ×` that column, grossed up 4.6×. Cross-run on LYCD land before treating any
   single figure as settled.
2. **Assessment level and uniformity.** Philadelphia nominally assesses at 100% of market. Uniform
   under-assessment scales the dividend proportionally but leaves the winner/loser partition
   untouched; non-uniform error (COD/PRD) is what actually redistributes.
3. **Assessment circularity at 100% capture.** Land value capitalizes to zero, so the ad-valorem
   base the levy would be denominated in ceases to exist. Sale prices stop being informative about
   land, the residual method returns zero everywhere, land-secured mortgage collateral goes to
   zero, and the assessor would have to publish imputed *rental* values that OPA does not produce
   today. The `implied_land_millage_equivalent` in the summary is a comparability aid against the
   repo's split-rate models, **not** an implementable rate.
4. **Assessment error becomes confiscation at full capture — and `phi` is a weak lever against
   it.** Effective capture on a parcel is `phi × (assessed / true)`. This limitation used to say
   the tail could not be quantified without a sales-ratio study; that study now exists
   (`scripts/vacant_land_ratio_study.py`, `docs/VACANT_LAND_VALUATION.md`), and on vacant land it
   is not a tail. Measured against observed sale prices, roughly **half** of bare parcels would be
   charged more than 100% of their true land rent at full capture, and the 99th percentile is
   assessed near **8× its sale price**.

   The part that changes the policy conclusion: **retreating to `phi ≈ 0.85` barely helps.** It
   moves the over-charged share by only a few points, because `phi` scales every parcel equally
   while the problem is dispersion. You would have to halve capture to get the share under a
   fifth. So the standard argument — stop near 85% *because of* assessment error — is not
   supported by this repo's own data. Lower capture is a defensible choice for other reasons
   (preserving sale prices as an assessment check, political headroom), but the fix for
   confiscation is better assessment, not less capture.

   Caveats on the measurement, both of which cut toward overstating the problem: a ratio study
   captures sale-price noise as well as assessment error, and the script's sales scrutiny is
   cruder than `philly_open_avmkit`'s, whose scrutinized study puts the dispersion materially
   lower. Vacant land is also the worst-assessed class; the improved classes are better. Treat
   the direction as established and the magnitude as provisional.
5. **Exempt-land treatment is a policy choice.** `taxable_land` is net of institutional, homestead
   and abatement relief. `RENT_BASIS = 'full'` reaches exempt land and raises the pot, but requires
   changing Pennsylvania exemption law, is fiscally circular for City- and School-owned parcels,
   and land under streets and parks is not in OPA at all.
6. **Abatements.** The building tax is unchanged, so abated parcels keep a $0 building bill while
   paying full land rent. This notebook deliberately skips `model.ipynb`'s
   `model_building = 4 × taxable_land` imputation: that exists so a revenue-neutral split-rate
   solve does not see an artificially land-only parcel, but here the reform does not touch the
   improvement base, so current law is the correct counterfactual.
7. **LOOP and Senior Freeze are not in OPA.** They are administered by Revenue, are not available
   at parcel level, and concentrate in exactly the land-rich, cash-poor, long-tenure owner-occupier
   population most exposed to full rent capture — the group whose equity cushion goes to zero at
   the same moment their bill rises.
8. **Speculative premium in vacant-land prices.** As above: `L(i+t)` overstates *realizable
   current* rent wherever price embeds a growth or option premium.
9. **ACS margins of error.** Tract population is the denominator of every per-capita figure here,
   and `B25010`/`B25003` carry their own error. `total_pop_moe` is fetched so it can be inspected.
10. **Stock versus flow.** See identity 3. Never add the one-time wealth loss to the annual levy.
11. **Incidence assumptions.** Land rent is unshiftable (first-order, standard). The model is
    silent on second-order supply effects that would lower rents, and on the retained building tax,
    whose incidence differs under a capitalization view (owner bears it) versus a replacement-cost
    view (reproducible capital, so it is passed forward to occupiers).
12. **Parcel/household mismatch.** ~583K parcels against ~590K households and ~670K units. The
    break-even threshold is meaningful only for owner-occupied single-unit parcels; everything else
    must be read at tract level.
13. **Tract-level mixed incidence.** A tract's land rent is paid by owners who may live elsewhere,
    while its dividend goes to residents. Directional, not a household-level guarantee — the same
    caveat the wage-tax guide carries.
14. **The dividend is taxable.** The Alaska PFD is federally taxable, and a dividend of this size
    interacts with SNAP, Medicaid and TANF cliffs. Everything here is gross, not net.
15. **Static.** No behavioural response in land use, development, rents, the building base or
    migration — under a reform whose entire purpose is to change them.
16. **`i` has no empirical anchor in this repo.** Defended as a net cap rate `r − g`. Report the
    dividend as a range across the sweep, never as a single number.
17. **Negative-rent land.** Contaminated and tax-delinquent sites would be surrendered to the City
    at full capture. No fiscal cost for that is modeled.
18. **Legal feasibility is not assessed.** A rent-denominated levy plus a per-capita dividend is a
    far heavier lift under Pennsylvania law than split-rate. See
    `docs/LVT_LEGAL_DECISIONING_GUIDE.md` and run `/legality-analyzer` separately rather than
    reading anything here as a feasibility claim.
19. **FIXED 2026-08-26 — the LYCD run's baseline was not the actual bill.** Under
    `LAND_VALUE_SOURCE = 'lycd'` the reform math rebuilt each parcel's *current* tax as
    `t * (model_land + taxable_building)` — LYCD land against the OPA building. LYCD replaces land
    without re-deriving buildings, so the implied parcel total was not the OPA assessment and the
    modeled baseline summed to **$2.417B against the actual TY2026 levy of $2.143B, a $274M (12.8%)
    overstatement**. Nothing caught it: Section 5's revenue validation runs on `taxable_total`
    (pure OPA) and passed at +0.00%, and the zero-sum check passed because it was internally
    consistent with the same wrong baseline. The OPA path was never affected — there `model_land`
    *is* `taxable_land`, so the baseline was the real levy by construction.
    **The fix**, per "The baseline, and the held-harmless credit" above: `land_value_col` is now
    always the assessor's land, the alternative surface goes to `rent_basis_col`, and
    `baseline_total_col='taxable_total'` makes conflating them raise instead of drift. **Measured
    effect on the corrected TY2026 LYCD run:** the baseline drops to $2.143B (0.0000% drift); the
    held-harmless credit is `t × $43.0B = $602M` rather than `t × $62.6B`; the pot rises from
    $3.131B to $3.406B and the dividend from $1,965 to $2,138 per resident; and 4 of the 391
    populated tracts cross the win/lose line (5 of 408 counting the unpopulated), with Spearman
    0.9931 between the old and new per-capita series, so the distributional conclusions published
    before the fix survive. Anything quoting a **per-parcel** `current_tax` or
    `tax_change` from an LYCD run generated before 2026-08-26 must be regenerated. Two consequences
    of the fix are documented above rather than hidden: identity 1 no longer collapses to `i·L`
    under a divergent surface, and the rate-invariance of the partition becomes *near*-invariance.

## Running it

```bash
python scripts/build_philadelphia_parcel_cache.py --year 2026
cp env.template .env    # add CENSUS_API_KEY

cd cities/philadelphia
jupyter nbconvert --to notebook --execute --inplace \
  --ExecutePreprocessor.timeout=1200 \
  --ExecutePreprocessor.kernel_name=python3 \
  model_lvt_ubi.ipynb
```

Outputs (all gitignored): `analysis/data/philadelphia_lvt_ubi_ty<YEAR>.csv` (tract-level, the
primary deliverable), `analysis/data/philadelphia_lvt_ubi_ty<YEAR>_parcels.csv`, and seven PNGs in
`analysis/reports/philadelphia_lvt_ubi_ty<YEAR>/`.

Set `LAND_VALUE_SOURCE = 'lycd'` for the cross-run — it reads
`analysis/data/philadelphia_lycd_ty<YEAR>.csv`, so run `model_lycd.ipynb` first — and it writes to
the `philadelphia_lvt_ubi_lycd_ty<YEAR>` slug rather than overwriting the OPA run. The tracked
notebook's default stays `'opa'`; flip it in a scratch copy rather than committing the flip, so the
two runs' outputs cannot be confused for one another.

The magnitude gates in Sections 6 and 7 are the acceptance test for a real run. The arithmetic is
proven separately and offline by `tests/test_ubi_utils.py`, so anything failing those gates is a
data-wiring problem — a mis-joined or wrong-vintage cache — not a formula problem.

## Functions

See docstrings in `lvt/ubi_utils.py` and `lvt.viz.create_lvt_ubi_report`. The tract-level census
helpers (`get_census_tract_data`, `get_census_tracts_shapefile`, `match_to_census_tracts`) are
shared with the wage-tax swap and documented in `lvt/census_utils.py`.
