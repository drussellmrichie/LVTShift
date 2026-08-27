"""Tests for lvt.single_tax — the static single-tax ledger (Tier 1).

Everything here runs on synthetic amounts with no network and no parcel cache.
These asserts are the proof that the kappa algebra is right; the notebook's
magnitude gates are the separate proof that it is wired to the right data.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lvt.single_tax import (  # noqa: E402
    BUNDLES,
    G_SCENARIOS,
    KAPPA_SCENARIOS,
    LedgerLine,
    build_ledger,
    bundle_amounts,
    kappa_star,
    kappa_vector,
    ledger_frame,
    pot,
    supply,
    sweep_bundles,
    validate_ledger,
    vintage_is_consistent,
)

LAND_TAX = 602_234_605.0        # TY2026, from the executed LVT-UBI model
BUILDING_TAX = 1_540_415_221.0
POP = 1_593_208.0


@pytest.fixture
def lines():
    return build_ledger(LAND_TAX, BUILDING_TAX)


# --- ledger structure -----------------------------------------------------------

def test_ledger_validates(lines):
    validate_ledger(lines)


def test_every_line_has_a_source_and_class(lines):
    for l in lines:
        assert l.source.strip(), f"{l.key} has no source"
        assert l.classification in {
            "labor", "capital", "absorbed", "kept", "out_of_scope"}


def test_absorbed_and_abolished_are_disjoint(lines):
    absorbed = {l.key for l in lines if l.classification == "absorbed"}
    assert absorbed == {"property_land"}
    for name, b in BUNDLES.items():
        assert not (set(b["keys"]) & absorbed), f"{name} abolishes the absorbed land tax"


def test_land_tax_enters_target_exactly_once(lines):
    for name in BUNDLES:
        a = bundle_amounts(lines, name)
        assert a["t_land"] == pytest.approx(LAND_TAX)
        assert a["target"] == pytest.approx(a["t_abolished"] + LAND_TAX)


def test_bundle_nesting_is_monotone(lines):
    """B0 subset B1,B2 subset B3 subset B4 subset B5 -- targets must be non-decreasing."""
    for a, b in [("B1", "B3"), ("B2", "B3"), ("B3", "B4"), ("B4", "B5")]:
        assert set(BUNDLES[a]["keys"]) <= set(BUNDLES[b]["keys"])
        assert bundle_amounts(lines, a)["target"] <= bundle_amounts(lines, b)["target"]


def test_no_double_counting_of_wage_and_pica(lines):
    """The PICA line is separate from the City line and both are in the wage family."""
    a = bundle_amounts(lines, "B2")
    by = {l.key: l.amount for l in lines}
    assert a["t_wage"] == pytest.approx(by["wage_city"] + by["wage_pica"])
    assert by["wage_pica"] > 0, "PICA must not be folded into the City wage line"


def test_estimate_lines_are_flagged_not_silent(lines):
    est = {l.key for l in lines if l.status == "estimate"}
    assert est == {"sit", "uo"}, (
        "the set of unverified lines changed -- update the notebook's warning block")
    for l in lines:
        if l.status == "estimate":
            assert "ESTIMATE" in l.note


def test_fy2025_vintage_is_flagged_as_mixed(lines):
    ok, vintages = vintage_is_consistent(lines)
    assert not ok  # FY2026 lines + TY2026 property + FY2023 SIT
    assert "TY2026" in vintages


def test_unknown_vintage_rejected():
    with pytest.raises(ValueError, match="vintage must be one of"):
        build_ledger(LAND_TAX, BUILDING_TAX, vintage="FY2019")


def test_validate_catches_an_absorbed_line_in_a_bundle(lines):
    bad = {"BX": {"label": "bad", "keys": ["property_land"]}}
    with pytest.raises(AssertionError, match="absorbed"):
        validate_ledger(lines, bad)


def test_validate_catches_a_missing_source(lines):
    broken = list(lines)
    broken[0] = LedgerLine(
        "x", "x", 1.0, "FY2026", "projected", "city", "labor", "  ", "2026-01-01",
        "verified")
    with pytest.raises(AssertionError, match="no source"):
        validate_ledger(broken)


def test_ledger_frame_is_sorted_by_class(lines):
    df = ledger_frame(lines)
    order = {"labor": 0, "capital": 1, "absorbed": 2, "kept": 3, "out_of_scope": 4}
    seq = [order[c] for c in df["classification"]]
    assert seq == sorted(seq)


# --- kappa algebra --------------------------------------------------------------

@pytest.mark.parametrize("phi", [1.0, 0.85, 0.5])
@pytest.mark.parametrize("g", [0.0, 150e6])
@pytest.mark.parametrize("h", [0.0, 0.10])
def test_kappa_star_zeroes_the_pot(phi, g, h):
    """The definition: at kappa*, Supply == Target exactly."""
    r0, target, t_ab = 2.75e9, 4.5e9, 3.0e9
    ks = kappa_star(target, r0, t_ab, phi=phi, g=g, h=h)
    p = pot(r0, target, phi=phi, g=g, h=h, kappa_amounts=ks * t_ab)
    assert p == pytest.approx(0.0, abs=1e-6)


def test_kappa_star_matches_brute_force_root():
    """Independent check: bisect the pot rather than trusting the closed form."""
    r0, target, t_ab, phi, g, h = 4.0e9, 6.1e9, 4.6e9, 0.85, 150e6, 0.05

    def f(k):
        return pot(r0, target, phi=phi, g=g, h=h, kappa_amounts=k * t_ab)

    lo, hi = -5.0, 5.0
    assert f(lo) < 0 < f(hi)
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) < 0:
            lo = mid
        else:
            hi = mid
    assert kappa_star(target, r0, t_ab, phi=phi, g=g, h=h) == pytest.approx(
        (lo + hi) / 2, rel=1e-9)


def test_pot_is_linear_in_kappa():
    r0, target, t_ab, phi = 2.75e9, 4.5e9, 3.0e9, 1.0
    ks = [0.0, 0.25, 0.5, 0.75, 1.0]
    ps = [pot(r0, target, phi=phi, kappa_amounts=k * t_ab) for k in ks]
    d = np.diff(ps)
    assert np.allclose(d, d[0])


def test_kappa_star_is_nan_when_nothing_is_abolished():
    assert np.isnan(kappa_star(1e9, 2e9, 0.0, phi=1.0))


def test_capture_applies_to_the_capitalized_increment():
    """phi multiplies the kappa*T term too -- it is site rent like any other."""
    r0, t_ab, k = 2.0e9, 1.0e9, 0.5
    s1 = supply(r0, phi=1.0, kappa_amounts=k * t_ab)
    s085 = supply(r0, phi=0.85, kappa_amounts=k * t_ab)
    assert s085 == pytest.approx(0.85 * s1)


def test_haircut_applies_to_r0_only():
    """Spec section 7 defines h on R0. Guard against it silently spreading."""
    r0, t_ab = 2.0e9, 1.0e9
    s = supply(r0, phi=1.0, h=0.10, kappa_amounts=1.0 * t_ab)
    assert s == pytest.approx(0.9 * r0 + t_ab)


def test_g_enters_outside_capture():
    """Road rent is collected directly, not through the parcel levy."""
    assert supply(0.0, phi=0.5, g=100e6) == pytest.approx(100e6)


# --- the two invariance results the spec asks for -------------------------------

def test_b0_pot_reproduces_the_ubi_model(lines):
    """B0, phi=1, no G, no haircut: the pot must be the LVT-UBI dividend pot."""
    r0 = 2_753_379_787.0          # OPA, taxable basis, i=5%, TY2026
    a = bundle_amounts(lines, "B0")
    assert a["t_abolished"] == 0.0
    p = pot(r0, a["target"], phi=1.0)
    assert p == pytest.approx(2_151_145_182.0, rel=1e-6)
    assert p / POP == pytest.approx(1350.0, abs=1.0)


def test_b1_at_full_capitalization_equals_b0(lines):
    """A structure tax under full capitalization is a land tax in disguise.

    At kappa_building = 1 the building tax's abolition is exactly self-funding, so
    B1's pot collapses onto B0's.
    """
    r0 = 2_753_379_787.0
    p0 = pot(r0, bundle_amounts(lines, "B0")["target"], phi=1.0)
    a1 = bundle_amounts(lines, "B1")
    p1 = pot(r0, a1["target"], phi=1.0, kappa_amounts=1.0 * a1["t_abolished"])
    assert p1 == pytest.approx(p0, rel=1e-9)


def test_b1_breaks_even_below_full_capitalization(lines):
    """B0's pot is already positive, so B1 breaks even strictly below kappa = 1."""
    r0 = 2_753_379_787.0
    a = bundle_amounts(lines, "B1")
    ks = kappa_star(a["target"], r0, a["t_abolished"], phi=1.0)
    assert ks < 1.0
    p_at_1 = pot(r0, a["target"], phi=1.0, kappa_amounts=a["t_abolished"])
    assert p_at_1 > 0


# --- sweep ----------------------------------------------------------------------

@pytest.fixture
def r0_cases():
    t = 0.013998
    return {("opa", "taxable", i): 43_022_903_638.0 * (i + t)
            for i in (0.03, 0.05, 0.07)}


def test_sweep_shape_and_columns(lines, r0_cases):
    df = sweep_bundles(lines, r0_cases, population=POP,
                       phis=(1.0, 0.85), haircuts=(0.0, 0.10))
    expected = len(BUNDLES) * len(r0_cases) * 2 * len(G_SCENARIOS) * 2
    assert len(df) == expected
    for s in KAPPA_SCENARIOS:
        assert f"pot_{s}" in df.columns and f"dividend_{s}" in df.columns
    assert df["kappa_star"].notna().sum() == len(df) - (
        len(df) // len(BUNDLES))  # only B0 is NaN


def test_sweep_kappa_star_agrees_with_pot_columns(lines, r0_cases):
    df = sweep_bundles(lines, r0_cases, population=POP, phis=(1.0,),
                       haircuts=(0.0,), kappa_grid=(0.0, 1.0))
    d = df[df["bundle"] != "B0"]
    # pot at kappa=0 is negative iff kappa* > 0
    assert ((d["pot_kappa_0"] < 0) == (d["kappa_star"] > 0)).all()
    # linear interpolation between the two grid points must land on kappa*
    implied = -d["pot_kappa_0"] / (d["pot_kappa_1"] - d["pot_kappa_0"])
    assert np.allclose(implied, d["kappa_star"])


def test_bigger_bundles_need_more_capitalization(lines, r0_cases):
    """Monotonicity sanity: B3 subset B4 subset B5 with rising kappa*."""
    df = sweep_bundles(lines, r0_cases, population=POP, phis=(1.0,),
                       haircuts=(0.0,), g_levels={"none": 0.0})
    d = df[df["discount_rate"] == 0.05].set_index("bundle")
    assert d.loc["B3", "kappa_star"] < d.loc["B4", "kappa_star"]
    assert d.loc["B4", "kappa_star"] < d.loc["B5", "kappa_star"]


def test_haircut_and_capture_raise_kappa_star(lines, r0_cases):
    df = sweep_bundles(lines, r0_cases, population=POP, phis=(1.0, 0.85),
                       haircuts=(0.0, 0.15), g_levels={"none": 0.0})
    d = df[(df["bundle"] == "B3") & (df["discount_rate"] == 0.05)]
    base = d[(d["phi"] == 1.0) & (d["haircut"] == 0.0)]["kappa_star"].iloc[0]
    cut = d[(d["phi"] == 1.0) & (d["haircut"] == 0.15)]["kappa_star"].iloc[0]
    cap = d[(d["phi"] == 0.85) & (d["haircut"] == 0.0)]["kappa_star"].iloc[0]
    assert cut > base and cap > base


def test_road_rent_lowers_kappa_star(lines, r0_cases):
    df = sweep_bundles(lines, r0_cases, population=POP, phis=(1.0,),
                       haircuts=(0.0,))
    d = df[(df["bundle"] == "B5") & (df["discount_rate"] == 0.05)]
    ks = d.set_index("g_level")["kappa_star"]
    assert ks["none"] > ks["central"] > ks["high"]


def test_kappa_scenarios_are_ordered():
    c, m, a = (kappa_vector("conservative"), kappa_vector("central"),
               kappa_vector("atcor"))
    for fam in ("building", "wage", "other"):
        assert c[fam] < m[fam] < a[fam]
        assert 0.0 <= c[fam] <= 1.0 and a[fam] == 1.0
