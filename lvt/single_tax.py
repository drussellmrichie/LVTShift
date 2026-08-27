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
an estimate**. `G` is road/curb rent, a hand-set scenario input. `h` is a
collections/surrender haircut on rent.

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
    "KAPPA_SCENARIOS",
    "KAPPA_SCENARIOS_UNSOURCED",
    "DEFAULT_COLLECTION_RATE",
    "G_SCENARIOS",
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
# WARNING -- read before using any pot_/dividend_ column these produce.
# `illustrative_low` and `illustrative_mid` have NO empirical source. They are
# placeholders for a sweep, not estimates, and they are named `illustrative_*` so that
# nothing downstream can read them as findings. Do not rename them to authoritative
# labels ("conservative", "central") without attaching a citation to each value --
# an earlier version used exactly those names and an audit flagged it, because the
# exported CSV then presents an invented parameter as a result.
#
# `atcor` is different: kappa = 1 is the definition of All-Taxes-Come-Out-Of-Rents,
# not a guess. It is a defensible reference point.
#
# Note also that kappa > 1 is NOT impossible. Gaffney's EBCOR (Excess Burden Comes Out
# of Rents) holds that abolishing a *distortionary* tax raises rent by more than the
# revenue foregone, because the deadweight loss is recovered too. Treat kappa* > 1 as
# "requires super-ATCOR capitalization", never as "impossible".
KAPPA_SCENARIOS: Dict[str, Dict[str, float]] = {
    "illustrative_low": {"building": 0.50, "wage": 0.10, "other": 0.20},
    "illustrative_mid": {"building": 0.70, "wage": 0.25, "other": 0.40},
    "atcor": {"building": 1.00, "wage": 1.00, "other": 1.00},
}
KAPPA_SCENARIOS_UNSOURCED = ("illustrative_low", "illustrative_mid")

# Road/curb rents, gross of operating cost. Hand-set scenarios, NOT estimates.
G_SCENARIOS: Dict[str, float] = {
    "none": 0.0,
    "central": 150_000_000.0,   # 100M congestion + 50M curb
    "high": 400_000_000.0,      # 250M congestion + 150M curb
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
