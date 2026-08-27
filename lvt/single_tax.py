"""Static single-tax ledger: which abolished taxes can Philadelphia land rent fund?

Implements `docs/SINGLE_TAX_LEDGER_SPEC.md` (Tier 1). For a bundle `B` of abolished
city/school taxes on labor and capital:

    Target(B)   = sum(T_j for j in B) + T_land
    Supply(B)   = phi * ((1 - h) * R0 + sum(kappa_j * T_j)) + G
    Pot         = Supply - Target
    kappa*(B)   = (Target - G - phi * (1 - h) * R0) / (phi * sum(T_j))

`T_land` is the current land-portion property tax. It is *absorbed*, not abolished:
the taxing bodies must be made whole for it out of the rent levy, so it enters Target
exactly once and never appears in an abolition bundle. `kappa_j` is the fraction of
abolished tax `j` that reappears as site rent (ATCOR); it is a **swept parameter, not
an estimate**, though `KAPPA_BOUNDS` now brackets each family with published
capitalization and incidence estimates (see `docs/KAPPA_CAPITALIZATION_EVIDENCE.md`).
`G` is net-new road/curb rent, sourced from the sibling cordon-pricing model's run
artifacts. `h` is a collections/surrender haircut on rent.

kappa* is exact because kappa enters linearly. `kappa* <= 0` means the bundle pencils
with no capitalization at all; `kappa* > 1` means it needs **super-ATCOR** capitalization
-- more rent than the abolished revenue. That is not impossible: Gaffney's EBCOR (Excess
Burden Comes Out of Rents) holds that abolishing a distortionary tax raises rent by more
than the revenue foregone, because the excess burden is recovered too. Never label the
kappa* > 1 region "impossible".

This module holds no behavioral response of any kind. GE anchoring to Jacob & Livas
(2026) is Tier 2 and deliberately out of scope -- see spec section 10 for why their
land-value object is not this ledger's kappa.

Vintage note
------------
The default vintage is **FY2026 current projection** (QCMR, period ending 2026-03-31),
chosen over the spec's FY2024 default because it matches the TY2026 vintage of the
repo's property-tax modeling -- the spec's own rule is not to mix vintages silently,
and FY2026 is the consistent choice. `FY2025` actuals are available as a sensitivity.

The two property lines are always TY2026 *billed* amounts taken from the executed
LVT-UBI model, on both vintages. Under the FY2025 vintage the non-property lines are
therefore a year behind the property lines; that mix is flagged by
`vintage_is_consistent()` and must be reported, not silently absorbed.

Accrual convention
------------------
The decision, made once and stated here: **the ledger runs on a BILLED basis by default**
(`collection_rate = 1.0`), which keeps the property lines identical to the LVT-UBI model
and preserves the B0 wiring check that ties the two notebooks together.

That convention is not free. The QCMR lines are *collections*, and several bundle current
plus prior year (Wage Total carries $5.4M prior; the BIRT figure is, per Table R-2's own
footnote, "the aggregate total of current and prior taxes"). So a default run mixes a
billed property component with collected tax lines.

The direction is known and the magnitude is small: since collections run below billings,
a billed property line overstates what abolition actually costs the taxing bodies, so the
default **overstates kappa*** -- results are conservative, not flattering. Pass
`collection_rate=DEFAULT_COLLECTION_RATE` to put the property lines on a collected basis
and see the other convention; at TY2026 that moves kappa*(B3) from 0.502 to about 0.477.
Do not "fix" the mix by grossing the QCMR lines up instead: collections are what a taxing
body actually loses when a tax is abolished, so collected is the more defensible Target
basis, and only the tie to the LVT-UBI model argues for billed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

__all__ = [
    "LedgerLine",
    "BUNDLES",
    "KappaSource",
    "KappaBound",
    "KAPPA_BOUNDS",
    "KAPPA_SCENARIOS",
    "KAPPA_SCENARIOS_UNSOURCED",
    "kappa_bounds_frame",
    "DEFAULT_COLLECTION_RATE",
    "RoadRentComponent",
    "G_COMPONENTS",
    "G_SCENARIOS",
    "road_rent_frame",
    "build_ledger",
    "ledger_frame",
    "validate_ledger",
    "vintage_is_consistent",
    "bundle_amounts",
    "kappa_star",
    "supply",
    "pot",
    "kappa_vector",
    "sweep_bundles",
    "SUPPORTED_VINTAGES",
]

# QCMR citation shared by every line drawn from Table R-2.
_QCMR_FY2026 = (
    "City of Philadelphia Quarterly City Managers Report, period ending 2026-03-31, "
    "Table R-2 'Tax Revenue Summary -- General Fund', FY2026 Full Year Current "
    "Projection column (000 omitted). "
    "https://www.phila.gov/media/20260515154446/Quarterly-City-Managers-Report-March-30-2026R.pdf"
)
_QCMR_FY2025 = (
    "City of Philadelphia Quarterly City Managers Report, period ending 2026-03-31, "
    "Table R-2 'Tax Revenue Summary -- General Fund', FY25 Actual column (000 omitted). "
    "https://www.phila.gov/media/20260515154446/Quarterly-City-Managers-Report-March-30-2026R.pdf"
)
_RETRIEVED = "2026-08-26"

SUPPORTED_VINTAGES = ("FY2026", "FY2025")

_VALID_CLASSES = {"labor", "capital", "absorbed", "kept", "out_of_scope"}
_VALID_STATUS = {"verified", "estimate"}


@dataclass(frozen=True)
class LedgerLine:
    """One tax line. No line may enter a computation without a `source`."""

    key: str
    name: str
    amount: float           # annual dollars
    vintage: str            # 'FY2026' | 'FY2025' | 'TY2026'
    accrual: str            # 'collected' | 'billed' | 'projected'
    body: str               # 'city' | 'school' | 'pica' | 'city+school'
    classification: str     # see _VALID_CLASSES
    source: str
    retrieved: str
    status: str             # 'verified' | 'estimate'
    note: str = ""

    @property
    def abolishable(self) -> bool:
        return self.classification in ("labor", "capital")


# Amounts in dollars. QCMR prints thousands; these are x1000.
_TAX_LINES: Dict[str, Dict[str, float]] = {
    # key:            FY2026 projection,   FY2025 actual
    "wage_city":      {"FY2026": 2_047_837_000.0, "FY2025": 1_937_088_000.0},
    "wage_pica":      {"FY2026":   731_305_000.0, "FY2025":   713_257_000.0},
    "npt_city":       {"FY2026":    39_074_000.0, "FY2025":    57_389_000.0},
    "npt_pica":       {"FY2026":    31_383_000.0, "FY2025":    42_519_000.0},
    "birt":           {"FY2026":   779_316_000.0, "FY2025":   751_979_000.0},
    "rtt":            {"FY2026":   356_444_000.0, "FY2025":   331_506_000.0},
    "sales":          {"FY2026":   323_170_000.0, "FY2025":   311_267_000.0},
    "amusement":      {"FY2026":    46_183_000.0, "FY2025":    43_413_000.0},
    "beverage":       {"FY2026":    70_955_000.0, "FY2025":    68_160_000.0},
    "other_city_tax": {"FY2026":     7_923_000.0, "FY2025":     8_615_000.0},
}

# School District lines are not in the City QCMR and are sourced separately.
_SIT_AMOUNT = 60_000_000.0
_UO_AMOUNT = 200_000_000.0

# Current-year property collections / billings at TY2026, from the repo's own
# cross-check: model-implied city-only billing $942,747,555 against the QCMR full-year
# current projection of $891,102,000, a +5.80% gap. 891102/942748 = 0.9452.
DEFAULT_COLLECTION_RATE = 0.9452


def build_ledger(
    land_tax: float,
    building_tax: float,
    *,
    vintage: str = "FY2026",
    property_vintage: str = "TY2026",
    collection_rate: float = 1.0,
) -> List[LedgerLine]:
    """Assemble the ledger.

    Parameters
    ----------
    land_tax, building_tax : float
        The land and building portions of the current combined city+school property
        tax, taken from the executed LVT-UBI model
        (`summary['total_current_land_tax']` and `summary['total_building_tax']`).
        Passed in rather than hardcoded so the ledger cannot drift from the model.
    vintage : {'FY2026', 'FY2025'}
        Which QCMR column the non-property tax lines come from.
    collection_rate : float, default 1.0
        Scales the two property lines from a billed to a collected basis. The default
        of 1.0 keeps them billed -- see "Accrual convention" in the module docstring for
        why, and why the default is the conservative direction. Pass
        `DEFAULT_COLLECTION_RATE` for the collected-basis run.
    """
    if not 0 < collection_rate <= 1.0:
        raise ValueError(f"collection_rate must be in (0, 1], got {collection_rate}")
    if vintage not in SUPPORTED_VINTAGES:
        raise ValueError(
            f"vintage must be one of {SUPPORTED_VINTAGES}, got {vintage!r}. "
            "Add a column to _TAX_LINES with a cited source rather than "
            "interpolating between years."
        )
    qcmr = _QCMR_FY2026 if vintage == "FY2026" else _QCMR_FY2025
    accrual = "projected" if vintage == "FY2026" else "collected"
    amt = {k: v[vintage] for k, v in _TAX_LINES.items()}

    lines = [
        # --- labor ---------------------------------------------------------------
        LedgerLine(
            "wage_city", "Wage & Earnings Tax (City)", amt["wage_city"], vintage,
            accrual, "city", "labor", qcmr, _RETRIEVED, "verified",
            "Wage and Earnings are one instrument reported jointly; no separate "
            "Earnings line (spec 4.2). Excludes the PICA portion, which is its own line.",
        ),
        LedgerLine(
            "wage_pica", "Wage & Earnings Tax (PICA)", amt["wage_pica"], vintage,
            accrual, "pica", "labor", qcmr, _RETRIEVED, "verified",
            "Confirmed separate from the City General Fund line in Table R-2's "
            "'Analysis of City/PICA Wage, Earnings and Net Profits Tax' block, and "
            "wage_pica + npt_pica reconciles to the dollar with the PICA City Account "
            "line in Table R-4 -- so the remittance is not double-counted. Workers pay "
            "it, so abolition must replace it (spec 4.3). On the bond caveat: Table R-2's "
            "'Less: PICA Debt Service & Expenses' reads $0 for every FY2026 full-year "
            "column (vs -$5,364k FY25 actual), consistent with the PICA bonds having "
            "been retired. Confirm against PICA's own financials before repeating the "
            "'stranding PICA strands its bondholders' argument.",
        ),
        LedgerLine(
            "npt_city", "Net Profits Tax (City)", amt["npt_city"], vintage,
            accrual, "city", "labor", qcmr, _RETRIEVED, "verified",
            "Receipts as published, already net of the 60% BIRT credit. Never compute "
            "as rate x base -- that double-counts against BIRT (spec 4.1).",
        ),
        LedgerLine(
            "npt_pica", "Net Profits Tax (PICA)", amt["npt_pica"], vintage,
            accrual, "pica", "labor", qcmr, _RETRIEVED, "verified",
            "Same PICA logic as the wage line.",
        ),
        # --- capital -------------------------------------------------------------
        LedgerLine(
            "property_building", "Real property tax -- building share",
            float(building_tax) * collection_rate, property_vintage,
            "billed" if collection_rate == 1.0 else "collected", "city+school", "capital",
            "Executed cities/philadelphia/model_lvt_ubi.ipynb, Section 6 "
            "(summary['total_building_tax']), TY2026 combined rate from "
            "lvt.philadelphia.tax_year_params(2026).",
            _RETRIEVED, "verified",
            "From the repo model, not budget documents (spec 4.4): the budget does not "
            "publish a land/building split.",
        ),
        LedgerLine(
            "birt", "Business Income & Receipts Tax", amt["birt"], vintage,
            accrual, "city", "capital", qcmr, _RETRIEVED, "verified",
            "Table R-2 note: the printed figure is the aggregate of current and prior "
            "year. Receipts basis, so the NPT credit interaction is already netted.",
        ),
        LedgerLine(
            "sit", "School Income Tax", _SIT_AMOUNT, "FY2023", "collected",
            "school", "capital",
            "City of Philadelphia Department of Revenue, 'Unearned income in Philly is "
            "subject to the School Income Tax' (2024-05-06): local public schools "
            "received 'more than $60 million' from the SIT in FY2023. "
            "https://www.phila.gov/2024-05-06-unearned-income-in-philly-is-subject-to-the-school-income-tax/",
            _RETRIEVED, "estimate",
            "ESTIMATE: a rounded floor ('more than $60 million'), FY2023 vintage, not "
            "the ledger vintage. SIT is <1.5% of every bundle it appears in, so the "
            "imprecision cannot move a kappa* conclusion -- but it is not verified.",
        ),
        LedgerLine(
            "uo", "Business Use & Occupancy Tax", _UO_AMOUNT, "FY2026", "projected",
            "school", "capital",
            "Office of the City Controller, 'Half of School District of Philadelphia's "
            "$4.6 Billion Budget Relies on 16 Types of Local Taxes, Fees & "
            "Contributions' (2026): '$200 million from the Business Use and Occupancy "
            "Tax' in the FY2026 adopted budget. "
            "https://controller.phila.gov/half-of-school-district-of-philadelphias-4-6-billion-budget-relies-on-16-types-of-local-taxes-fees-contributions/",
            _RETRIEVED, "estimate",
            "ESTIMATE: rounded to the nearest $100M in a secondary source; the School "
            "District adopted budget is the primary document and was not machine-"
            "readable at build time. Separate levy from the property tax, so no overlap "
            "adjustment (spec 4.5).",
        ),
        LedgerLine(
            "rtt", "Realty Transfer Tax (City)", amt["rtt"], vintage,
            accrual, "city", "capital", qcmr, _RETRIEVED, "verified",
            "Abolished rather than kept: under full capture the land component of its "
            "base vanishes, so 'keep RTT' is not revenue-preserving either (spec 4.6).",
        ),
        # --- absorbed ------------------------------------------------------------
        LedgerLine(
            "property_land", "Real property tax -- land share (ABSORBED)",
            float(land_tax) * collection_rate, property_vintage,
            "billed" if collection_rate == 1.0 else "collected", "city+school", "absorbed",
            "Executed cities/philadelphia/model_lvt_ubi.ipynb, Section 6 "
            "(summary['total_current_land_tax']).",
            _RETRIEVED, "verified",
            "Never abolished. The taxing bodies must be made whole for it out of the "
            "rent levy, so it enters Target exactly once for every bundle (spec 4.7).",
        ),
        # --- kept ----------------------------------------------------------------
        LedgerLine(
            "parking", "Parking Tax (KEPT)", 0.0, vintage, accrual, "city", "kept",
            "City of Philadelphia ACFR FY2024, Schedule XIX 'Schedule of Budgetary "
            "Actual and Estimated Revenues and Obligations -- General Fund': Parking "
            "Lot Tax FY2024 Actual $0 against FY2023 Actual $101,941k. Not a line in "
            "the FY2026 QCMR Table R-2. "
            "https://www.phila.gov/media/20250519125628/annual-comp-financial-report-FY-2024.pdf",
            _RETRIEVED, "verified",
            "A land-use charge, part of the road-rent family -- excluded from both "
            "sides and listed only for visibility. It also left the City General Fund "
            "after FY2023, so a nonzero General Fund figure would be wrong regardless.",
        ),
        # --- out of scope --------------------------------------------------------
        LedgerLine(
            "sales", "Sales Tax", amt["sales"], vintage, accrual, "city",
            "out_of_scope", qcmr, _RETRIEVED, "verified",
            "Consumption tax. The program is capital-and-labor only.",
        ),
        LedgerLine(
            "amusement", "Amusement Tax", amt["amusement"], vintage, accrual, "city",
            "out_of_scope", qcmr, _RETRIEVED, "verified", "Consumption tax.",
        ),
        LedgerLine(
            "beverage", "Beverage Tax", amt["beverage"], vintage, accrual, "city",
            "out_of_scope", qcmr, _RETRIEVED, "verified", "Consumption tax.",
        ),
        LedgerLine(
            "other_city_tax", "Other City taxes", amt["other_city_tax"], vintage,
            accrual, "city", "out_of_scope", qcmr, _RETRIEVED, "verified",
            "Table R-2 'Other'. Includes smokeless tobacco and miscellaneous.",
        ),
    ]
    return lines


BUNDLES: Dict[str, Dict[str, object]] = {
    "B0": {"label": "None (wiring check)", "keys": []},
    "B1": {"label": "Building tax only", "keys": ["property_building"]},
    "B2": {"label": "Wage & Earnings only", "keys": ["wage_city", "wage_pica"]},
    "B3": {
        "label": "Wage + entire property tax",
        "keys": ["property_building", "wage_city", "wage_pica"],
    },
    "B4": {
        "label": "B3 + BIRT + NPT + SIT",
        "keys": ["property_building", "wage_city", "wage_pica",
                 "birt", "npt_city", "npt_pica", "sit"],
    },
    "B5": {
        "label": "Full program (+ U&O + RTT)",
        "keys": ["property_building", "wage_city", "wage_pica",
                 "birt", "npt_city", "npt_pica", "sit", "uo", "rtt"],
    },
}

# kappa by line family: (building, wage, other).
#
# Every value below traces to a published estimate. This replaced two invented
# scenarios (`illustrative_low`/`illustrative_mid`) that an audit (2026-08-26, finding
# M3) flagged as unsourced parameters shipped in the export as if they were results.
# Full evidence base, mapping derivation and caveats: docs/KAPPA_CAPITALIZATION_EVIDENCE.md
#
# THE MAPPING. kappa_j is the share of abolished tax j's *revenue* that reappears as
# annual site rent. The literature measures two nearby objects:
#
#   'capitalization_rate'        -- the share of the present value of a tax change
#       that shows up in the asset price. Structures are reproducible and supplied at
#       construction cost, so once supply has adjusted a fully capitalized change to a
#       tax on structures accrues to the non-reproducible factor, the site. Maps to
#       kappa directly.
#   'landowner_incidence_share'  -- theta, the share of the tax BURDEN borne by
#       landowners. kappa = theta * (burden / revenue), and burden >= revenue whenever
#       the tax is distortionary. Setting kappa = theta therefore UNDERSTATES kappa;
#       it is the conservative direction (it understates the pot, never the reverse).
#       That gap is exactly Gaffney's EBCOR, below.
#
# kappa > 1 is NOT impossible: EBCOR (Excess Burden Comes Out of Rents) holds that
# abolishing a *distortionary* tax raises rent by more than the revenue foregone,
# because the deadweight loss is recovered too. `building`'s upper bound is a published
# point estimate slightly above 1, which is the concrete form of that point. Treat
# kappa* > 1 as "requires super-ATCOR capitalization", never as "impossible".


@dataclass(frozen=True)
class KappaSource:
    """One published estimate standing behind a kappa bound."""

    citation: str
    value: float
    basis: str          # 'capitalization_rate' | 'landowner_incidence_share' | 'theory'
    setting: str        # jurisdiction and instrument actually measured
    directness: str     # 'direct' (same instrument, comparable setting) | 'transferred'
    note: str = ""


@dataclass(frozen=True)
class KappaBound:
    """Published low/high bracket for one kappa family."""

    family: str
    low: float
    high: float
    low_source: KappaSource
    high_source: KappaSource
    corroborating: Tuple[KappaSource, ...] = ()
    note: str = ""


_COSTE_2024 = KappaSource(
    citation=("Coste, Jonah (2024), 'Capitalization of Property Tax Incentives: "
              "Evidence From Philadelphia', FHFA Staff Working Paper 24-01. "
              "https://www.fhfa.gov/papers/wp2401.aspx"),
    value=1.006,
    basis="capitalization_rate",
    setting="Philadelphia's 10-year construction abatement, residential sales 1980-2023",
    directness="direct",
    note=("Preferred specification: 100.6% initial capitalization, 95% CI 86.0-115.2%; "
          "78.6-125.5% once discount-rate uncertainty (r-g in 1%-5%) is carried. Same "
          "city, same tax, and the same abatement this repo already models. Coste "
          "measures capitalization into the whole home price, not a land/structure "
          "split; for new construction with elastic structure supply the premium "
          "accrues to the site, which is the mapping assumed here."),
)
_LOFFLER_SIEGLOCH_2021 = KappaSource(
    citation=("Loffler, Max and Sebastian Siegloch (2021), 'Welfare Effects of Property "
              "Taxation', IZA DP No. 14195. https://docs.iza.org/dp14195.pdf"),
    value=0.0,
    basis="landowner_incidence_share",
    setting="5,200 German municipal property-tax reforms, rental and sales listings",
    directness="direct",
    note=("Gross rents rise to full pass-through by year three, net rents revert to "
          "the pre-reform level, and offered sales prices show no significant "
          "medium-run effect -- i.e. landowners end up bearing ~none of it. They also "
          "report the prior US range as 0-115% shifted onto renters. Caveat: the German "
          "Grundsteuer runs on a frozen 1964/1935 base, so it is a weaker analogue of a "
          "US ad-valorem tax on structures than Coste is."),
)
_LYU_2024 = KappaSource(
    citation=("Lyu, Xueying (2024), 'Revisiting property tax capitalization', "
              "Regional Science and Urban Economics 108. "
              "https://doi.org/10.1016/j.regsciurbeco.2024.104028"),
    value=0.71,
    basis="capitalization_rate",
    setting="Shanghai progressive property-tax pilot, DiD across neighborhoods",
    directness="direct",
    note="Reported as a floor: 'at least 71% of expected property tax liabilities'.",
)
_SUAREZ_SERRATO_ZIDAR_2016 = KappaSource(
    citation=("Suarez Serrato, Juan Carlos and Owen Zidar (2016), 'Who Benefits from "
              "State Corporate Tax Cuts? A Local Labor Markets Approach with "
              "Heterogeneous Firms', American Economic Review 106(9), 2582-2624. "
              "https://doi.org/10.1257/aer.20141702"),
    value=0.25,
    basis="landowner_incidence_share",
    setting="US state corporate tax rates and apportionment rules, structural estimation",
    directness="direct",
    note=("'firm owners bear roughly 40 percent of the incidence, while workers and "
          "landowners bear 30-35 percent and 25-30 percent, respectively.' The 2023 "
          "corrected model puts landowners at 26.8%. Shares of the welfare change, not "
          "of revenue -- see the mapping note above."),
)
# Same study, but used for a tax it did not measure. Kept as its own object so the
# exported bounds table shows 'transferred' on the wage row and 'direct' on the other
# row, rather than one directness label doing duty for two different uses.
_SSZ_TRANSFERRED_TO_WAGE = KappaSource(
    citation=_SUAREZ_SERRATO_ZIDAR_2016.citation,
    value=0.25,
    basis="landowner_incidence_share",
    setting="US state corporate tax (NOT a wage tax)",
    directness="transferred",
    note=("Applied to the wage family only because it is the nearest structural "
          "estimate of the landowner share of a mobile-base subfederal tax. A wage tax "
          "and a corporate tax reach land through different channels, and Philadelphia's "
          "reaches non-resident commuters as well, so the transfer is an assumption, "
          "not a measurement. " + _SUAREZ_SERRATO_ZIDAR_2016.note),
)
_PERFECT_MOBILITY = KappaSource(
    citation=("Brulhart, Marius, Jayson Danton, Raphael Parchet and Jorg Schlapfer "
              "(2025), 'Who Bears the Burden of Local Taxes?', American Economic "
              "Journal: Economic Policy 17(1), 464-505, p. 468. "
              "https://doi.org/10.1257/pol.20220462"),
    value=1.0,
    basis="theory",
    setting="benchmark, not an estimate",
    directness="direct",
    note=("'With perfect mobility, the incidence of local taxes is fully borne by "
          "landowners, the immobile factor.' The paper's own contribution is that "
          "moving is costly, so realised incidence is below this ceiling -- it is cited "
          "here as the upper bound, which is what it is."),
)
_BRULHART_2025 = KappaSource(
    citation=("Brulhart, Danton, Parchet and Schlapfer (2025), AEJ: Economic Policy "
              "17(1), 464-505. https://doi.org/10.1257/pol.20220462"),
    value=-0.281,
    basis="capitalization_rate",
    setting="Swiss municipal income taxes, border-pair design with instrumented rates",
    directness="direct",
    note=("Structural landlord incidence eta_p,tau* = -0.281 (s.e. 0.021); reduced-form "
          "housing-price elasticity -0.30. An elasticity, NOT a revenue share -- "
          "converting it would need the housing-value-to-income-tax-revenue ratio in "
          "their setting, which the paper does not report. Cited as corroboration of "
          "sign and order of magnitude only."),
)
_BASTEN_2017 = KappaSource(
    citation=("Basten, Christoph, Maximilian von Ehrlich and Andrea Lassmann (2017), "
              "'Income Taxes, Sorting and the Costs of Housing: Evidence from Municipal "
              "Boundaries in Switzerland', The Economic Journal 127(601), 653-687. "
              "https://doi.org/10.1111/ecoj.12489"),
    value=0.26,
    basis="capitalization_rate",
    setting="Swiss municipal income taxes, apartment-level boundary discontinuity",
    directness="direct",
    note=("Income tax elasticity of rents ~0.26 in absolute value; the boundary design "
          "halves conventional estimates, and about a third of the effect is income "
          "sorting rather than capitalization. Again an elasticity, not a share."),
)
_ALBOUY_2009 = KappaSource(
    citation=("Albouy, David (2009), 'The Unequal Geographic Burden of Federal "
              "Taxation', Journal of Political Economy 117(4), 635-667. "
              "https://doi.org/10.1086/605309"),
    value=float("nan"),
    basis="capitalization_rate",
    setting="US federal taxation of nominal wages across cities, simulation",
    directness="transferred",
    note=("Simulated long-run effect of the wage-tax wedge in high-wage cities: land "
          "prices -21% against housing prices -5%. Evidence that a tax on wages lands "
          "disproportionately on land, but federal rather than local and reported as "
          "price levels, so it pins no share."),
)
_FUEST_PEICHL_SIEGLOCH_2018 = KappaSource(
    citation=("Fuest, Clemens, Andreas Peichl and Sebastian Siegloch (2018), 'Do Higher "
              "Corporate Taxes Reduce Wages? Micro Evidence from Germany', American "
              "Economic Review 108(2), 393-418. https://doi.org/10.1257/aer.20130570"),
    value=0.5,
    basis="landowner_incidence_share",
    setting="20-year panel of German municipal business tax rates",
    directness="direct",
    note=("Workers bear about half the burden of the municipal business tax; the "
          "residual is split between firm owners and landowners, so this caps the "
          "landowner share well below 1 for a local business tax. Value recorded is the "
          "WORKER share, not a landowner share."),
)
_KOPCZUK_MUNROE_2015 = KappaSource(
    citation=("Kopczuk, Wojciech and David J. Munroe (2015), 'Mansion Tax: The Effect "
              "of Transfer Taxes on the Residential Real Estate Market', American "
              "Economic Journal: Economic Policy 7(2), 214-257. "
              "https://doi.org/10.1257/pol.20130361"),
    value=float("nan"),
    basis="landowner_incidence_share",
    setting="NY/NJ 1% 'mansion tax' notch at $1M",
    directness="direct",
    note=("Incidence 'falls on sellers, may exceed the value of the tax' -- i.e. a "
          "transfer tax is borne by the asset owner and plausibly at theta > 1, the "
          "EBCOR pattern. Local to a notch, so it does not generalise to the whole RTT "
          "base; it is the reason this family's published band should be read as one "
          "study's range and not as a bound on the RTT component."),
)

KAPPA_BOUNDS: Dict[str, KappaBound] = {
    "building": KappaBound(
        family="building",
        low=0.0,
        high=1.006,
        low_source=_LOFFLER_SIEGLOCH_2021,
        high_source=_COSTE_2024,
        corroborating=(_LYU_2024,),
        note=("The widest band of the three, and the disagreement is real rather than "
              "noise: the best-identified US estimate is full capitalization and the "
              "best-identified European one is none. The Philadelphia estimate is the "
              "high end, which matters for how this band should be read here."),
    ),
    "wage": KappaBound(
        family="wage",
        low=0.25,
        high=1.0,
        low_source=_SSZ_TRANSFERRED_TO_WAGE,
        high_source=_PERFECT_MOBILITY,
        corroborating=(_BRULHART_2025, _BASTEN_2017, _ALBOUY_2009),
        note=("WEAKEST LINK IN THE EVIDENCE BASE. No published study reports the "
              "landowner share of a local wage or earnings tax. The low bound is "
              "TRANSFERRED from the corporate-tax setting -- the nearest structural "
              "estimate of a mobile-base subfederal tax -- and the high bound is the "
              "perfect-mobility ceiling, not an estimate. The corroborating entries "
              "establish that local income taxes do capitalize with the expected sign "
              "and a non-trivial magnitude; none of them pins a revenue share. This is "
              "also the largest family in every bundle from B2 up."),
    ),
    "other": KappaBound(
        family="other",
        low=0.25,
        high=0.30,
        low_source=_SUAREZ_SERRATO_ZIDAR_2016,
        high_source=_SUAREZ_SERRATO_ZIDAR_2016,
        corroborating=(_FUEST_PEICHL_SIEGLOCH_2018, _KOPCZUK_MUNROE_2015),
        note=("Narrow because it is ONE study's reported range (landowners 25-30%), not "
              "because the literature has converged. Do not read it as a confidence "
              "interval on the family: it covers BIRT, SIT, U&O and RTT together, and "
              "the transfer-tax evidence points materially higher for the RTT slice."),
    ),
}

KAPPA_SCENARIOS: Dict[str, Dict[str, float]] = {
    "lit_low": {f: b.low for f, b in KAPPA_BOUNDS.items()},
    "lit_high": {f: b.high for f, b in KAPPA_BOUNDS.items()},
    "atcor": {f: 1.0 for f in KAPPA_BOUNDS},
}
# Empty by construction: every scenario above is derived from KAPPA_BOUNDS, and every
# bound carries its citation. Kept so the audit's rule stays enforceable if a bare
# scenario is ever added back.
KAPPA_SCENARIOS_UNSOURCED: Tuple[str, ...] = ()

# Road/curb rents: NET-NEW annual revenue from pricing the public right-of-way.
#
# Replaced the original hand-set scenarios (central 150M = 100M congestion + 50M curb;
# high 400M = 250M congestion + 150M curb) on 2026-08-27. Two things were wrong with
# them, both found by checking against the sibling models:
#
#   1. The curb component double-counted. Philadelphia already prices some curb, and
#      Act 84 of 2012 directs a $35M/yr minimum PPA payment to the City General Fund
#      with the residual net on-street revenue going to the School District -- the two
#      bodies this ledger holds harmless. Gross curb revenue in Supply would let the
#      same dollar fund both today's spending and the abolition. Only the INCREMENT
#      over the current remittance is new supply, and no one has estimated it, so the
#      curb component is now zero and carries its reason.
#   2. The high congestion figure (250M) exceeded the top of the sibling model's own
#      revenue ladder -- more than its $25 high-deterrence scenario, which is already
#      past the revenue-maximizing toll.
#
# PROVENANCE CAVEAT. The congestion figures come from a sibling repo, not from a
# published source or from this repo's pipeline. That repo was audited 2026-04-22 and
# the audit's first finding was hand-estimated revenue numbers that had drifted from
# actual runs by 36-44%; the values below are read from the committed run artifacts
# (`runs/<scenario>/<ts>/stage_09_revenue.json`), not from its prose. Its own README
# calls the outputs "illustrative ranges based on transferred parameters -- not
# forecasts". Status is therefore 'modeled_sibling', never 'verified'.


@dataclass(frozen=True)
class RoadRentComponent:
    """One net-new road/curb rent line. Same source discipline as LedgerLine."""

    key: str
    name: str
    amount: float
    source: str
    retrieved: str
    status: str         # 'modeled_sibling' | 'estimate' | 'excluded'
    note: str = ""


_CORDON_RUN = (
    "philly-cordon-pricing (Progress-and-Poverty-Institute), run artifact "
    "runs/{scen}/{ts}/stage_09_revenue.json, net_revenue_annual_usd p50, "
    "steady-state (Year 5+), net of operating cost, ~7% evasion and ~12% exemption "
    "discounts; git_sha 976c95ceeeb5. Repo audit: AUDIT.md dated 2026-04-22."
)
_G_RETRIEVED = "2026-08-27"

G_COMPONENTS: Dict[str, Tuple[RoadRentComponent, ...]] = {
    "none": (),
    "central": (
        RoadRentComponent(
            key="cordon_nyc_calibrated",
            name="Center City cordon toll, $9/entry (NYC-calibrated)",
            amount=83_657_804.0,
            source=_CORDON_RUN.format(scen="nyc_calibrated", ts="20260806T194631Z"),
            retrieved=_G_RETRIEVED,
            status="modeled_sibling",
            note=("p10 $67.9M / p50 $83.7M / p90 $102.0M over 1,000 draws. Sits near the "
                  "elbow of that model's revenue curve. Philadelphia prices no cordon "
                  "today, so the whole amount is net-new rent."),
        ),
    ),
    "high": (
        RoadRentComponent(
            key="cordon_high_deterrence",
            name="Center City cordon toll, $25/entry (high deterrence)",
            amount=175_290_000.0,
            source=_CORDON_RUN.format(scen="high_deterrence", ts="20260806T194632Z"),
            retrieved=_G_RETRIEVED,
            status="modeled_sibling",
            note=("p10 $138.8M / p50 $175.3M / p90 $218.5M. Past the revenue-maximizing "
                  "toll ($15, p50 $142.6M) in that model, so it is the ceiling of the "
                  "published ladder rather than a plausible policy."),
        ),
    ),
}

_CURB_EXCLUDED = RoadRentComponent(
    key="curb_pricing",
    name="Curb parking rent (EXCLUDED, not zero)",
    amount=0.0,
    source=("philly-parking-benefit-districts (Progress-and-Poverty-Institute), README "
            "'Key calibration numbers' and research/demand-based-curb-parking-pricing-"
            "model-for-philadelphia---claude-2026-04-28.md; Act 84 of 2012."),
    retrieved=_G_RETRIEVED,
    status="excluded",
    note=("Status-quo on-street revenue is ~$40-50M/yr, but Act 84 of 2012 already "
          "routes a $35M/yr minimum to the City General Fund and the residual to the "
          "School District, so it is not net-new supply -- only the increment from "
          "efficient pricing would be, and no citywide estimate of that exists on real "
          "data. The sibling model still runs on synthetic transactions (PPA meter data "
          "pending an RTKL request) and its efficient-pricing scenarios return LESS "
          "revenue than status quo on that synthetic baseline. Excluded until there is "
          "something to cite; the direction of the omission is conservative."),
)

G_SCENARIOS: Dict[str, float] = {
    name: float(sum(c.amount for c in comps))
    for name, comps in G_COMPONENTS.items()
}

# kappa families. NPT is the self-employment analogue of the wage tax, so it
# capitalizes through the same channel and belongs in the wage family -- classification
# ('labor'/'capital') does NOT drive kappa, these key sets do.
_WAGE_KEYS = {"wage_city", "wage_pica", "npt_city", "npt_pica"}
_BUILDING_KEYS = {"property_building"}


def ledger_frame(lines: Sequence[LedgerLine]) -> pd.DataFrame:
    """Ledger as a DataFrame, sorted by classification then descending amount."""
    df = pd.DataFrame([asdict(l) for l in lines])
    order = {"labor": 0, "capital": 1, "absorbed": 2, "kept": 3, "out_of_scope": 4}
    df["_o"] = df["classification"].map(order)
    return (df.sort_values(["_o", "amount"], ascending=[True, False])
              .drop(columns="_o").reset_index(drop=True))


def validate_ledger(lines: Sequence[LedgerLine],
                    bundles: Optional[Dict] = None) -> None:
    """Structural checks. Raises AssertionError on any violation."""
    bundles = BUNDLES if bundles is None else bundles
    keys = [l.key for l in lines]
    assert len(keys) == len(set(keys)), f"duplicate ledger keys: {keys}"
    by_key = {l.key: l for l in lines}

    for l in lines:
        assert l.classification in _VALID_CLASSES, \
            f"{l.key}: bad classification {l.classification!r}"
        assert l.status in _VALID_STATUS, f"{l.key}: bad status {l.status!r}"
        assert l.source.strip(), f"{l.key}: no source -- may not enter a computation"
        assert l.retrieved.strip(), f"{l.key}: no retrieved date"
        assert l.amount >= 0, f"{l.key}: negative amount {l.amount}"

    # Spec 4.7: absorbed and abolished must be disjoint.
    absorbed = {l.key for l in lines if l.classification == "absorbed"}
    assert absorbed, "no absorbed line -- the land tax must be absorbed, not dropped"
    for name, b in bundles.items():
        bk = set(b["keys"])
        unknown = bk - set(by_key)
        assert not unknown, f"bundle {name} references unknown keys {unknown}"
        clash = bk & absorbed
        assert not clash, (
            f"bundle {name} abolishes {clash}, which is classified 'absorbed'. "
            "The land tax is absorbed into the rent levy, never abolished (spec 4.7)."
        )
        for k in bk:
            assert by_key[k].abolishable, (
                f"bundle {name} includes {k!r}, classified "
                f"{by_key[k].classification!r} -- only labor/capital lines are abolishable"
            )


def vintage_is_consistent(lines: Sequence[LedgerLine]) -> Tuple[bool, List[str]]:
    """Report vintage mixing across lines that enter computations."""
    used = [l for l in lines if l.classification in ("labor", "capital", "absorbed")]
    vintages = sorted({l.vintage for l in used})
    return len(vintages) == 1, vintages


def bundle_amounts(lines: Sequence[LedgerLine], bundle: str) -> Dict[str, float]:
    """T_abolished (total and by family) and T_land for a bundle."""
    by_key = {l.key: l for l in lines}
    keys = BUNDLES[bundle]["keys"]
    t_land = sum(l.amount for l in lines if l.classification == "absorbed")
    fam = {"building": 0.0, "wage": 0.0, "other": 0.0}
    for k in keys:
        a = by_key[k].amount
        if k in _BUILDING_KEYS:
            fam["building"] += a
        elif k in _WAGE_KEYS:
            fam["wage"] += a
        else:
            fam["other"] += a
    total = sum(fam.values())
    return {"t_abolished": total, "t_land": t_land,
            "target": total + t_land, **{f"t_{k}": v for k, v in fam.items()}}


def road_rent_frame(
    components: Optional[Dict[str, Tuple[RoadRentComponent, ...]]] = None,
    include_excluded: bool = True,
) -> pd.DataFrame:
    """Road/curb rent components behind each G level, one row per component.

    Parameters
    ----------
    components : dict of str -> tuple of RoadRentComponent, optional
        Defaults to G_COMPONENTS.
    include_excluded : bool, default True
        Append the curb line that is deliberately carried at zero. It is included by
        default because an omission nobody can see reads as an omission nobody made.

    Returns
    -------
    pandas.DataFrame
        Columns: g_level, key, name, amount, status, source, retrieved, note.
    """
    components = G_COMPONENTS if components is None else components
    rows: List[Dict[str, object]] = []
    for level, comps in components.items():
        for c in comps:
            rows.append({"g_level": level, **asdict(c)})
    if include_excluded:
        rows.append({"g_level": "(all)", **asdict(_CURB_EXCLUDED)})
    return pd.DataFrame(rows)


def kappa_bounds_frame(bounds: Optional[Dict[str, KappaBound]] = None) -> pd.DataFrame:
    """The published bracket behind each kappa family, one row per bound.

    Parameters
    ----------
    bounds : dict of str -> KappaBound, optional
        Defaults to KAPPA_BOUNDS.

    Returns
    -------
    pandas.DataFrame
        Columns: family, edge ('low'|'high'), kappa, basis, directness, setting,
        citation, note. Rendered by the notebook so the exported scenarios can be
        traced to a source without opening this module.
    """
    bounds = KAPPA_BOUNDS if bounds is None else bounds
    rows: List[Dict[str, object]] = []
    for fam, b in bounds.items():
        for edge, value, src in (("low", b.low, b.low_source),
                                 ("high", b.high, b.high_source)):
            rows.append({
                "family": fam, "edge": edge, "kappa": value,
                "basis": src.basis, "directness": src.directness,
                "setting": src.setting, "citation": src.citation,
                "note": src.note,
            })
    return pd.DataFrame(rows)


def kappa_vector(scenario: str) -> Dict[str, float]:
    if scenario not in KAPPA_SCENARIOS:
        raise ValueError(f"unknown kappa scenario {scenario!r}; "
                         f"known: {list(KAPPA_SCENARIOS)}")
    return dict(KAPPA_SCENARIOS[scenario])


def supply(r0: float, *, phi: float, g: float = 0.0, h: float = 0.0,
           kappa_amounts: float = 0.0) -> float:
    """phi * ((1-h)*R0 + sum(kappa_j * T_j)) + G.

    `kappa_amounts` is the already-weighted sum(kappa_j * T_j). Capture applies to
    the capitalized increment too: it is site rent like any other.
    """
    return phi * ((1.0 - h) * r0 + kappa_amounts) + g


def pot(r0: float, target: float, **kw) -> float:
    return supply(r0, **kw) - target


def kappa_star(target: float, r0: float, t_abolished: float, *,
               phi: float, g: float = 0.0, h: float = 0.0) -> float:
    """Uniform kappa at which Supply == Target. NaN when nothing is abolished.

    The spec's printed formula is the h = 0 case of this.
    """
    if t_abolished <= 0:
        return float("nan")
    return (target - g - phi * (1.0 - h) * r0) / (phi * t_abolished)


def sweep_bundles(
    lines: Sequence[LedgerLine],
    r0_by_case: Dict[Tuple[str, str, float], float],
    *,
    population: float,
    phis: Iterable[float] = (1.0, 0.85),
    g_levels: Optional[Dict[str, float]] = None,
    haircuts: Iterable[float] = (0.0, 0.05, 0.10, 0.15),
    kappa_grid: Iterable[float] = (0.0, 0.25, 0.5, 0.75, 1.0),
    bundles: Optional[Dict] = None,
) -> pd.DataFrame:
    """One row per (bundle x surface x basis x phi x i x G-level x h).

    `r0_by_case` maps (surface, basis, i) -> R0, the gross annual site rent at
    capture 1.0 (i.e. `summary['total_land_rent']` from `model_full_land_rent_tax`).
    """
    bundles = BUNDLES if bundles is None else bundles
    g_levels = G_SCENARIOS if g_levels is None else g_levels
    rows: List[Dict[str, object]] = []

    for bname, b in bundles.items():
        amts = bundle_amounts(lines, bname)
        target, t_ab = amts["target"], amts["t_abolished"]
        for (surface, basis, i), r0 in r0_by_case.items():
            for phi in phis:
                for gname, g in g_levels.items():
                    for h in haircuts:
                        row: Dict[str, object] = {
                            "bundle": bname, "bundle_label": b["label"],
                            "surface": surface, "rent_basis": basis,
                            "discount_rate": i, "phi": phi,
                            "g_level": gname, "g_amount": g, "haircut": h,
                            "r0": r0, "target": target,
                            "t_abolished": t_ab, "t_land": amts["t_land"],
                            "t_building": amts["t_building"],
                            "t_wage": amts["t_wage"], "t_other": amts["t_other"],
                            "kappa_star": kappa_star(target, r0, t_ab,
                                                     phi=phi, g=g, h=h),
                        }
                        for k in kappa_grid:
                            ka = k * t_ab
                            p = pot(r0, target, phi=phi, g=g, h=h, kappa_amounts=ka)
                            row[f"pot_kappa_{k:g}"] = p
                        for sname in KAPPA_SCENARIOS:
                            kv = kappa_vector(sname)
                            ka = (kv["building"] * amts["t_building"]
                                  + kv["wage"] * amts["t_wage"]
                                  + kv["other"] * amts["t_other"])
                            p = pot(r0, target, phi=phi, g=g, h=h, kappa_amounts=ka)
                            row[f"pot_{sname}"] = p
                            row[f"dividend_{sname}"] = p / population
                        rows.append(row)
    return pd.DataFrame(rows)
