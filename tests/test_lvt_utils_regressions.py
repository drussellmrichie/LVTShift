"""
Regression tests for lvt/lvt_utils.py: exemption order, tax credits, the revenue-neutral
split-millage solver, building abatement, and the category summary.

Ported from the retired philly_lvt_shift repo, where they pinned a copy of this module; they
pass against the live one.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from lvt.lvt_utils import (
    _apply_tax_credits,
    _compute_adjusted_tax_components,
    _solve_revenue_neutral_split_millage,
    calculate_category_tax_summary,
    calculate_current_tax,
    model_full_building_abatement,
    model_split_rate_tax,
)


@pytest.fixture
def simple_lvt_frame() -> pd.DataFrame:
    """
    Hand-built 5-parcel frame for testing the LVT solver in isolation.
    Total taxable land = $1,000,000; total improvement = $4,000,000.
    Current revenue at 13.998 mills on (land + impr) = $69,990.
    """
    return pd.DataFrame({
        "key": ["A", "B", "C", "D", "E"],
        "land_value": [200_000, 100_000, 300_000, 150_000, 250_000],
        "improvement_value": [800_000, 400_000, 1_200_000, 600_000, 1_000_000],
        "exempt_flag": [0, 0, 0, 0, 0],
        "current_tax": [13_998, 6_999, 20_997, 10_499, 17_498],  # 13.998 mills
    })


# ── _compute_adjusted_tax_components ────────────────────────────────────────

class TestComputeAdjustedTaxComponents:
    """Exemption application order and full-exempt zeroing."""

    def test_no_exemption_returns_inputs_unchanged(self):
        df = pd.DataFrame({"land": [100.0, 200.0], "impr": [300.0, 400.0]})
        land, impr = _compute_adjusted_tax_components(
            df, land_value_col="land", improvement_value_col="impr"
        )
        assert list(land) == [100.0, 200.0]
        assert list(impr) == [300.0, 400.0]

    def test_partial_exemption_eats_improvements_first(self):
        df = pd.DataFrame({
            "land": [100.0],
            "impr": [300.0],
            "exempt": [200.0],  # less than improvement
        })
        land, impr = _compute_adjusted_tax_components(
            df, land_value_col="land", improvement_value_col="impr",
            exemption_col="exempt",
        )
        assert land.iloc[0] == 100.0          # land untouched
        assert impr.iloc[0] == 100.0          # 300 - 200

    def test_exemption_overflows_to_land_when_improvement_exhausted(self):
        df = pd.DataFrame({
            "land": [500.0],
            "impr": [200.0],
            "exempt": [350.0],  # 200 to impr, 150 overflow to land
        })
        land, impr = _compute_adjusted_tax_components(
            df, land_value_col="land", improvement_value_col="impr",
            exemption_col="exempt",
        )
        assert impr.iloc[0] == 0.0
        assert land.iloc[0] == 350.0          # 500 - 150

    def test_fully_exempt_flag_zeroes_both_components(self):
        df = pd.DataFrame({
            "land": [500.0, 500.0],
            "impr": [200.0, 200.0],
            "flag": [1, 0],
        })
        land, impr = _compute_adjusted_tax_components(
            df, land_value_col="land", improvement_value_col="impr",
            exemption_flag_col="flag",
        )
        assert land.iloc[0] == 0.0 and impr.iloc[0] == 0.0
        assert land.iloc[1] == 500.0 and impr.iloc[1] == 200.0

    def test_negative_exemption_clipped_to_zero(self):
        df = pd.DataFrame({
            "land": [100.0],
            "impr": [200.0],
            "exempt": [-50.0],
        })
        land, impr = _compute_adjusted_tax_components(
            df, land_value_col="land", improvement_value_col="impr",
            exemption_col="exempt",
        )
        # negative exemption must not increase tax
        assert impr.iloc[0] == 200.0
        assert land.iloc[0] == 100.0


# ── _apply_tax_credits ──────────────────────────────────────────────────────

class TestApplyTaxCredits:
    def test_no_credits_returns_clipped_input(self):
        df = pd.DataFrame({"_": [None, None]})
        net, realized = _apply_tax_credits(pd.Series([1000.0, -50.0]), df)
        assert list(net) == [1000.0, 0.0]
        assert list(realized) == [0.0, 0.0]

    def test_fixed_credit_clips_at_zero(self):
        df = pd.DataFrame({"credit": [200.0, 5000.0]})
        net, realized = _apply_tax_credits(
            pd.Series([1000.0, 1000.0]), df, credit_col="credit"
        )
        assert list(net) == [800.0, 0.0]
        assert list(realized) == [200.0, 1000.0]   # realized capped by base

    def test_credit_rate_clipped_to_unit_interval(self):
        df = pd.DataFrame({"rate": [-0.5, 0.25, 1.5]})
        net, _ = _apply_tax_credits(
            pd.Series([1000.0, 1000.0, 1000.0]), df, credit_rate_col="rate"
        )
        # rate -0.5 clipped to 0; 0.25 → 25% off; 1.5 clipped to 1 → tax 0
        assert list(net) == [1000.0, 750.0, 0.0]

    def test_rate_and_fixed_stack_additively(self):
        df = pd.DataFrame({"rate": [0.10], "credit": [50.0]})
        net, _ = _apply_tax_credits(
            pd.Series([1000.0]), df, credit_col="credit", credit_rate_col="rate"
        )
        # 1000 - (1000 * 0.10) - 50 = 850
        assert net.iloc[0] == pytest.approx(850.0)


# ── _solve_revenue_neutral_split_millage ────────────────────────────────────

class TestSolveRevenueNeutralSplitMillage:
    def test_closed_form_no_caps_or_credits(self):
        # 4:1 split rate. Land=$100k, impr=$400k. Target=$10,000.
        # denominator = 400k + 4*100k = 800k; impr_mill * 800 = 10,000 → 12.5
        adj_land = pd.Series([100_000.0])
        adj_impr = pd.Series([400_000.0])
        df = pd.DataFrame({"land": [100_000.0], "impr": [400_000.0]})
        land_m, impr_m = _solve_revenue_neutral_split_millage(
            adj_land_value=adj_land,
            adj_improvement_value=adj_impr,
            result_df=df,
            current_revenue=10_000.0,
            land_improvement_ratio=4.0,
            land_value_col="land",
            improvement_value_col="impr",
        )
        assert impr_m == pytest.approx(12.5, rel=1e-9)
        assert land_m == pytest.approx(50.0, rel=1e-9)

    def test_zero_total_value_raises(self):
        adj = pd.Series([0.0, 0.0])
        df = pd.DataFrame({"land": [0.0, 0.0], "impr": [0.0, 0.0]})
        with pytest.raises(ValueError, match="zero or negative"):
            _solve_revenue_neutral_split_millage(
                adj_land_value=adj, adj_improvement_value=adj,
                result_df=df, current_revenue=1000.0,
                land_improvement_ratio=3.0,
                land_value_col="land", improvement_value_col="impr",
            )

    def test_solver_converges_when_cap_binds(self):
        # Two parcels. The big one gets capped; solver must push millage up
        # on the rest to hit revenue.
        adj_land = pd.Series([50_000.0, 1_000_000.0])
        adj_impr = pd.Series([150_000.0, 4_000_000.0])
        df = pd.DataFrame({
            "land": [50_000.0, 1_000_000.0],
            "impr": [150_000.0, 4_000_000.0],
            # cap: 0.5% of total value — binds on parcel 2
            "cap": [0.50, 0.005],
        })
        land_m, impr_m = _solve_revenue_neutral_split_millage(
            adj_land_value=adj_land, adj_improvement_value=adj_impr,
            result_df=df, current_revenue=50_000.0,
            land_improvement_ratio=3.0,
            land_value_col="land", improvement_value_col="impr",
            percentage_cap_col="cap",
        )
        # Reconstruct revenue from the returned millages and verify ≈ target
        land_tax = adj_land * land_m / 1000
        impr_tax = adj_impr * impr_m / 1000
        gross = (land_tax + impr_tax).clip(lower=0)
        max_tax = (df["land"] + df["impr"]) * df["cap"]
        capped = np.minimum(gross, max_tax)
        assert capped.sum() == pytest.approx(50_000.0, rel=1e-4)


# ── calculate_current_tax ───────────────────────────────────────────────────

class TestCalculateCurrentTax:

    def test_missing_required_column_raises(self):
        df = pd.DataFrame({"x": [1, 2]})
        with pytest.raises(ValueError, match="not found"):
            calculate_current_tax(df, "missing", "x")


# ── model_full_building_abatement ───────────────────────────────────────────

class TestModelFullBuildingAbatement:
    """Pure LVT (100% building abatement) must be revenue-neutral."""

    def test_revenue_neutral_pure_lvt(self, simple_lvt_frame):
        df = simple_lvt_frame.copy()
        current_rev = float(df["current_tax"].sum())
        millage, new_rev, out = model_full_building_abatement(
            df=df,
            land_value_col="land_value",
            improvement_value_col="improvement_value",
            current_revenue=current_rev,
            abatement_percentage=1.0,
        )
        assert new_rev == pytest.approx(current_rev, rel=1e-6)
        # 100% abatement → tax driven entirely by land
        # Reconstruct: every parcel's new_tax = land_value * millage / 1000
        expected = df["land_value"] * millage / 1000
        np.testing.assert_allclose(out["new_tax"].values, expected.values, rtol=1e-9)

    def test_buildings_pay_zero_under_pure_lvt(self, simple_lvt_frame):
        df = simple_lvt_frame.copy()
        current_rev = float(df["current_tax"].sum())
        _, _, out = model_full_building_abatement(
            df=df,
            land_value_col="land_value",
            improvement_value_col="improvement_value",
            current_revenue=current_rev,
            abatement_percentage=1.0,
        )
        # taxable_value column should equal land_value (improvements abated to 0)
        assert (out["taxable_value"] == out["land_value"]).all()

    def test_abatement_outside_unit_interval_raises(self, simple_lvt_frame):
        with pytest.raises(ValueError, match="between 0 and 1"):
            model_full_building_abatement(
                df=simple_lvt_frame,
                land_value_col="land_value",
                improvement_value_col="improvement_value",
                current_revenue=1000,
                abatement_percentage=1.5,
            )


# ── model_split_rate_tax ────────────────────────────────────────────────────

class TestModelSplitRateTax:
    """A 4:1 split rate must be revenue-neutral."""

    def test_revenue_neutral_4_to_1(self, simple_lvt_frame):
        df = simple_lvt_frame.copy()
        current_rev = float(df["current_tax"].sum())
        land_m, impr_m, new_rev, out = model_split_rate_tax(
            df=df,
            land_value_col="land_value",
            improvement_value_col="improvement_value",
            current_revenue=current_rev,
            land_improvement_ratio=4.0,
        )
        assert land_m == pytest.approx(4 * impr_m, rel=1e-9)
        assert new_rev == pytest.approx(current_rev, rel=1e-6)

    def test_writes_tax_change_when_current_tax_present(self, simple_lvt_frame):
        # Pre-existing current_tax column triggers tax_change write.
        # Important: this is exactly the path that produces the stale-column
        # bug downstream — the test below pins that side effect.
        _, _, _, out = model_split_rate_tax(
            df=simple_lvt_frame.copy(),
            land_value_col="land_value",
            improvement_value_col="improvement_value",
            current_revenue=float(simple_lvt_frame["current_tax"].sum()),
            land_improvement_ratio=4.0,
        )
        assert "tax_change" in out.columns
        assert "tax_change_pct" in out.columns


# ── calculate_category_tax_summary ──────────────────────────────────────────

class TestCalculateCategoryTaxSummary:
    """
    `tax_change` is always recomputed from the two tax columns, and a zero current bill has
    an undefined percent change that stays out of the percentage statistics.
    """

    def test_stale_tax_change_is_recomputed(self):
        df = pd.DataFrame({
            "PROPERTY_CATEGORY": ["A", "A", "B"],
            "current_tax": [100.0, 200.0, 300.0],
            "new_tax": [150.0, 250.0, 350.0],   # +50 each
            "tax_change": [9_999.0, 9_999.0, 9_999.0],  # stale
        })
        summary = calculate_category_tax_summary(
            df, category_col="PROPERTY_CATEGORY",
            current_tax_col="current_tax", new_tax_col="new_tax",
        )
        a = summary[summary["PROPERTY_CATEGORY"] == "A"].iloc[0]
        assert a["total_tax_change_dollars"] == pytest.approx(100.0)  # 50+50

    def test_zero_baseline_pct_is_undefined(self):
        df = pd.DataFrame({
            "PROPERTY_CATEGORY": ["A"],
            "current_tax": [0.0],
            "new_tax": [500.0],
        })
        summary = calculate_category_tax_summary(
            df, category_col="PROPERTY_CATEGORY",
            current_tax_col="current_tax", new_tax_col="new_tax",
        )
        assert np.isnan(summary.iloc[0]["mean_tax_change_pct"])

    def test_zero_baseline_parcel_counts_in_dollars_not_percentages(self):
        # Real exports hold effectively-exempt parcels (0 -> 0) and parcels entering the
        # roll (0 -> positive) inside ordinary categories; neither may read as a 0% change
        df = pd.DataFrame({
            "PROPERTY_CATEGORY": ["A", "A", "A", "A"],
            "current_tax": [100.0, 100.0, 0.0, 0.0],
            "new_tax": [150.0, 50.0, 0.0, 400.0],   # +50%, -50%, 0 -> 0, 0 -> 400
        })
        a = calculate_category_tax_summary(
            df, category_col="PROPERTY_CATEGORY",
            current_tax_col="current_tax", new_tax_col="new_tax",
        ).iloc[0]
        assert a["property_count"] == 4
        assert a["pct_defined_count"] == 2
        assert a["total_tax_change_dollars"] == pytest.approx(400.0)
        assert a["mean_tax_change_pct"] == pytest.approx(0.0)
        assert a["pct_increase_gt_threshold"] == pytest.approx(50.0)
        assert a["pct_decrease_gt_threshold"] == pytest.approx(50.0)

    def test_missing_category_column_returns_empty(self):
        df = pd.DataFrame({"current_tax": [1.0], "new_tax": [2.0]})
        summary = calculate_category_tax_summary(
            df, category_col="NONEXISTENT",
            current_tax_col="current_tax", new_tax_col="new_tax",
        )
        assert summary.empty
