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
with no capitalization at all; `kappa* > 1` means it cannot be funded even if every
abolished dollar reappeared as rent.

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


def build_ledger(
    land_tax: float,
    building_tax: float,
    *,
    vintage: str = "FY2026",
    property_vintage: str = "TY2026",
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
    """
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
            "'Analysis of City/PICA Wage, Earnings and Net Profits Tax' block. Workers "
            "pay it, so abolition must replace it (spec 4.3). CAVEAT: PICA revenue "
            "services PICA bonds; stranding it is a legal constraint on implementation.",
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
            float(building_tax), property_vintage, "billed", "city+school", "capital",
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
            float(land_tax), property_vintage, "billed", "city+school", "absorbed",
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

# kappa by line family: (building, wage, other). Spec section 9.
KAPPA_SCENARIOS: Dict[str, Dict[str, float]] = {
    "conservative": {"building": 0.50, "wage": 0.10, "other": 0.20},
    "central": {"building": 0.70, "wage": 0.25, "other": 0.40},
    "atcor": {"building": 1.00, "wage": 1.00, "other": 1.00},
}

# Road/curb rents, gross of operating cost. Hand-set scenarios, NOT estimates.
G_SCENARIOS: Dict[str, float] = {
    "none": 0.0,
    "central": 150_000_000.0,   # 100M congestion + 50M curb
    "high": 400_000_000.0,      # 250M congestion + 150M curb
}

_WAGE_KEYS = {"wage_city", "wage_pica"}
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
