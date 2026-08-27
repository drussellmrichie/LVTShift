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
    DEFAULT_COLLECTION_RATE,
    CORDON_REPO_HINT,
    CORDON_RUN_ARTIFACTS,
    G_COMPONENTS,
    KAPPA_BOUNDS,
    KAPPA_SCENARIOS_UNSOURCED,
    G_SCENARIOS,
    KAPPA_SCENARIOS,
    LedgerLine,
    kappa_bounds_frame,
    road_rent_frame,
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


def test_pica_reconciles_to_the_pica_city_account(lines):
    """wage_pica + npt_pica must equal QCMR Table R-4's PICA City Account exactly.

    That account is the City's non-tax remittance of PICA collections. If the two tax
    lines did not sum to it, either a PICA component is missing or the remittance is
    being counted twice.
    """
    by = {l.key: l.amount for l in lines}
    assert by["wage_pica"] + by["npt_pica"] == pytest.approx(762_688_000.0)


def test_npt_capitalizes_through_the_wage_family(lines):
    """NPT is the self-employment analogue of the wage tax, so it shares its kappa."""
    a = bundle_amounts(lines, "B4")
    by = {l.key: l.amount for l in lines}
    assert a["t_wage"] == pytest.approx(
        by["wage_city"] + by["wage_pica"] + by["npt_city"] + by["npt_pica"])


def test_city_side_reconciles_to_the_qcmr_total(lines):
    """Completeness guard: every City tax in QCMR Table R-2 is accounted for.

    The eight City tax lines plus QCMR's own city Real Property total must equal
    Table R-2's TOTAL TAX REVENUE exactly. This is what would catch a City tax being
    dropped on a vintage change -- validate_ledger cannot, because it checks structure
    rather than substance.
    """
    by = {l.key: l.amount for l in lines}
    city_keys = ["wage_city", "npt_city", "birt", "rtt", "sales", "amusement",
                 "beverage", "other_city_tax"]
    QCMR_CITY_REAL_PROPERTY_TOTAL = 936_062_000.0   # Table R-2, FY2026 projection
    QCMR_TOTAL_TAX_REVENUE = 4_606_964_000.0
    total = sum(by[k] for k in city_keys) + QCMR_CITY_REAL_PROPERTY_TOTAL
    assert total == pytest.approx(QCMR_TOTAL_TAX_REVENUE, abs=1.0), (
        f"City lines sum to ${total:,.0f} against QCMR's "
        f"${QCMR_TOTAL_TAX_REVENUE:,.0f} -- a City tax is missing or duplicated")


def test_collection_rate_moves_only_the_property_lines(lines):
    """M4: the accrual convention is a parameter, and it touches nothing else."""
    coll = build_ledger(LAND_TAX, BUILDING_TAX,
                        collection_rate=DEFAULT_COLLECTION_RATE)
    a, b = {l.key: l.amount for l in lines}, {l.key: l.amount for l in coll}
    for k in a:
        if k in ("property_land", "property_building"):
            assert b[k] == pytest.approx(a[k] * DEFAULT_COLLECTION_RATE)
        else:
            assert b[k] == pytest.approx(a[k])
    # Direction: the billed default is the conservative one.
    r0 = 2_753_379_787.0
    ks_billed = kappa_star(bundle_amounts(lines, "B3")["target"], r0,
                           bundle_amounts(lines, "B3")["t_abolished"], phi=1.0)
    ks_coll = kappa_star(bundle_amounts(coll, "B3")["target"], r0,
                         bundle_amounts(coll, "B3")["t_abolished"], phi=1.0)
    assert ks_billed > ks_coll


def test_collection_rate_is_validated():
    for bad in (0.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="collection_rate"):
            build_ledger(LAND_TAX, BUILDING_TAX, collection_rate=bad)


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


def test_haircut_applies_to_r0_and_to_the_capitalized_increment():
    """Audit M-3 (2026-08-27): h used to apply to R0 only, so the kappa*T increment was
    collected in full even at h = 0.15. Both are site rent, both are haircut. This test
    replaces `test_haircut_applies_to_r0_only`, which pinned the old asymmetry."""
    r0, t_ab = 2.0e9, 1.0e9
    s = supply(r0, phi=1.0, h=0.10, kappa_amounts=1.0 * t_ab)
    assert s == pytest.approx(0.9 * (r0 + t_ab))
    # And the asymmetric form is now wrong by exactly h * kappa_amounts.
    assert s == pytest.approx(0.9 * r0 + t_ab - 0.10 * t_ab)


def test_haircut_raises_kappa_star():
    """Direction check: haircutting the increment makes break-even harder, not easier.

    The old asymmetry ran the other way and flattered every h > 0 cell.
    """
    r0, t_ab, target = 2.0e9, 1.0e9, 3.0e9
    k0 = kappa_star(target, r0, t_ab, phi=1.0, h=0.0)
    k15 = kappa_star(target, r0, t_ab, phi=1.0, h=0.15)
    assert k15 > k0
    # Exactly: kappa*(h) = (target - phi(1-h)r0) / (phi(1-h)T)
    assert k15 == pytest.approx((target - 0.85 * r0) / (0.85 * t_ab))


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


def test_atcor_convergence_holds_only_at_full_capture(lines):
    """M1: at kappa=1 all bundles converge to phi*R0 + G - T_land -- but ONLY at phi=1.

    An audit (2026-08-26) found this stated unconditionally in CLAUDE.md, with a formula
    that also omitted G. Both halves are pinned here.
    """
    r0, g = 2_753_379_787.0, 150_000_000.0
    pots = {phi: [pot(r0, bundle_amounts(lines, b)["target"], phi=phi, g=g,
                      kappa_amounts=bundle_amounts(lines, b)["t_abolished"])
                  for b in BUNDLES] for phi in (1.0, 0.85)}
    # phi = 1: identical across bundles, and equal to R0 + G - T_land.
    assert max(pots[1.0]) - min(pots[1.0]) == pytest.approx(0.0, abs=1.0)
    t_land = bundle_amounts(lines, "B0")["t_land"]
    assert pots[1.0][0] == pytest.approx(r0 + g - t_land)
    # phi < 1: it does NOT converge. Guard against the claim creeping back unqualified.
    assert max(pots[0.85]) - min(pots[0.85]) > 1e8


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


def test_unsourced_kappa_scenarios_keep_non_authoritative_names():
    """An audit (2026-08-26, M3) flagged 'conservative'/'central' as invented parameters
    dressed as findings in the exported CSV. The disposition taken on 2026-08-27 was to
    source them instead of renaming them, so this list should now be empty -- but the
    rule stays enforceable if a bare scenario is ever added back."""
    assert set(KAPPA_SCENARIOS_UNSOURCED) <= set(KAPPA_SCENARIOS)
    for name in KAPPA_SCENARIOS_UNSOURCED:
        assert name.startswith("illustrative_"), (
            f"{name!r} reads as authoritative; unsourced kappa scenarios must be "
            "named illustrative_* so the exported columns cannot be misread")
    # atcor is kappa = 1 by definition, not a guess, so it is allowed a plain name.
    assert "atcor" not in KAPPA_SCENARIOS_UNSOURCED
    assert all(v == 1.0 for v in kappa_vector("atcor").values())


def test_every_kappa_scenario_value_traces_to_a_bound():
    """The M3 fix: no number reaches a pot_/dividend_ column without a citation."""
    for scenario, vec in KAPPA_SCENARIOS.items():
        assert set(vec) == set(KAPPA_BOUNDS)
        for fam, v in vec.items():
            b = KAPPA_BOUNDS[fam]
            if scenario == "atcor":
                assert v == 1.0          # definitional, not an estimate
            else:
                assert v in (b.low, b.high), (
                    f"{scenario}/{fam} = {v} matches neither published bound "
                    f"({b.low}, {b.high}); every swept kappa must be traceable")


def test_every_kappa_bound_carries_a_citation_with_a_locator():
    for fam, b in KAPPA_BOUNDS.items():
        for edge, src in (("low", b.low_source), ("high", b.high_source)):
            assert len(src.citation) > 40, f"{fam}/{edge} citation is too thin"
            assert ("http" in src.citation or "doi.org" in src.citation), (
                f"{fam}/{edge} citation has no resolvable locator")
            assert src.basis in {"capitalization_rate",
                                 "landowner_incidence_share", "theory",
                                 "model_counterfactual"}
            assert src.directness in {"direct", "transferred"}
        assert b.low <= b.high


def test_published_values_match_the_evidence_doc():
    """Pin the numbers docs/KAPPA_CAPITALIZATION_EVIDENCE.md quotes from each paper, so
    the doc and the model cannot drift apart silently. Change these only alongside a
    re-read of the source."""
    b = KAPPA_BOUNDS
    # Coste (2024): 100.6% initial capitalization of Philadelphia's abatement.
    assert b["building"].high == 1.006
    assert b["building"].high_source.value == 1.006
    # Loffler & Siegloch (2021): landowners bear ~none of it in the medium run.
    assert b["building"].low == 0.0
    # Suarez Serrato & Zidar (2016): landowners 25-30%.
    assert (b["other"].low, b["other"].high) == (0.25, 0.30)
    # Jacob & Livas (2026) Table 4, col 1: Delta_Q/T_W = 12.28*0.0941/1.0941, the
    # Tier-2 anchor. Open-city GE counterfactual for this exact tax and city -- a
    # model-quantified ceiling, deliberately above the atcor scenario's 1.0 because the
    # recovered excess burden accrues partly to Philadelphia land.
    assert b["wage"].high == pytest.approx(12.28 * 0.0941 / 1.0941, abs=5e-4)
    assert b["wage"].high == 1.056
    assert b["wage"].high_source.basis == "model_counterfactual"
    # The perfect-mobility ceiling is now the anchor's conditioning assumption, kept in
    # the corroborating list rather than standing as the bound itself.
    assert any(c.basis == "theory" for c in b["wage"].corroborating)


def test_transferred_kappa_bounds_say_so():
    """The wage family has no direct estimate. That must be visible in the export, not
    buried in a comment -- it is the weakest link and the largest family."""
    df = kappa_bounds_frame()
    wage_low = df[(df.family == "wage") & (df.edge == "low")].iloc[0]
    assert wage_low["directness"] == "transferred"
    assert "NOT a wage tax" in wage_low["setting"]


def test_kappa_scenarios_are_ordered():
    lo, hi, a = (kappa_vector("lit_low"), kappa_vector("lit_high"),
                 kappa_vector("atcor"))
    for fam in ("building", "wage", "other"):
        assert lo[fam] < hi[fam]
        assert 0.0 <= lo[fam] <= 1.0 and a[fam] == 1.0
    # Deliberate: the Philadelphia capitalization estimate is 100.6%, above ATCOR.
    # kappa > 1 is EBCOR territory, not an error -- do not clamp this to 1.0.
    assert hi["building"] > a["building"]


def test_road_rent_amounts_match_sibling_run_artifacts():
    """The 2026-08-27 audit (M-4) found `high` hand-transcribed as 175_290_000.0 against
    an artifact reading 175,308,213.52 -- inside the very fix whose comment block warns
    against quoting the sibling's prose instead of its runs. Prose cannot catch that; this
    reads the JSON. Skips when the sibling repo is not checked out beside this one, so the
    suite still runs standalone -- but the skip is announced, because a check that produced
    no output has not passed."""
    import json

    repo = Path(__file__).resolve().parents[1] / CORDON_REPO_HINT
    if not repo.is_dir():
        pytest.skip(f"sibling cordon repo not present at {repo}; G amounts unverified")

    checked = 0
    for level, comps in G_COMPONENTS.items():
        for c in comps:
            scen, ts = CORDON_RUN_ARTIFACTS[c.key]
            art = repo / "runs" / scen / ts / "stage_09_revenue.json"
            if not art.is_file():
                pytest.skip(f"run artifact missing: {art}")
            p50 = json.loads(art.read_text())["net_revenue_annual_usd"]["p50"]
            assert c.amount == pytest.approx(p50, abs=0.01), (
                f"{c.key}: constant {c.amount:,.2f} != artifact p50 {p50:,.2f} -- "
                "read the run, do not retype it")
            checked += 1
    assert checked == len(CORDON_RUN_ARTIFACTS), (
        f"only {checked} of {len(CORDON_RUN_ARTIFACTS)} cordon amounts were checked")


def test_road_rent_components_sum_to_the_g_levels():
    for level, comps in G_COMPONENTS.items():
        assert G_SCENARIOS[level] == pytest.approx(sum(c.amount for c in comps))
    assert G_SCENARIOS["none"] == 0.0
    assert G_SCENARIOS["central"] < G_SCENARIOS["high"]


def test_road_rent_is_sourced_and_never_claims_to_be_verified():
    """G comes from an unaudited-for-this-purpose sibling model. It may not be dressed
    up as a verified figure, and the excluded curb line must stay visible."""
    df = road_rent_frame()
    assert set(df["status"]) <= {"modeled_sibling", "estimate", "excluded"}
    assert "verified" not in set(df["status"])
    for _, r in df.iterrows():
        assert len(r["source"]) > 40 and r["retrieved"]
    curb = df[df["key"] == "curb_pricing"]
    assert len(curb) == 1 and curb.iloc[0]["amount"] == 0.0, (
        "the curb line is carried at zero on purpose; an omission nobody can see "
        "reads as an omission nobody made")
