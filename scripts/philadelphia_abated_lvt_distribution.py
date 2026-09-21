"""
Philadelphia -- how an immediate 4:1 split rate on S5 land changes the bills of parcels whose
construction abatement is still running, by abatement type.

Question: while a parcel's abatement is in effect, what does the shift do to its bill?

This is the static, one-step reading: the S5 reassessment export's `total_change` (the S5 land
re-split at a flat rate, then a revenue-neutral 4:1 land/building split rate on top), with every
parcel's abatement carried in dollars, compared against its current TY2026 bill. It is not the
10-year phase-in; `philadelphia_abatement_phase_in.py` answers that one and reports each parcel's
worst year.

Cohort: parcels the abatement classification identifies as a construction abatement
(`old_flat_100`, `old_flat_partial`, `new_graduated_residential`, `new_flat_90_commercial`) whose
abatement is still running one year into the reform (abatement year <= ABATEMENT_LIFE - 1). This is
the same cohort `philadelphia_abatement_phase_in.py` reports on, and the script checks its size
against that script's exposure output. Excluded on purpose: `non_abatement_relief` (relief of
unidentified program that tracks value, not a construction abatement), `unresolved`, and parcels in
abatement year 10-11, which expire within a year.

Outputs (analysis/data/, gitignored):
    philadelphia_abated_lvt_distribution.csv   percentiles, shares and dollars, by abatement type
    philadelphia_abated_lvt_buckets.csv        share of parcels in each %-change band, by type

Requires:
    cities/philadelphia/data/abatement_classification_ty2026.parquet
    analysis/data/philadelphia_lycd_reassessment_ty2026_s5.csv
        (LVT_LAND_SURFACE=s5 jupyter nbconvert --execute cities/philadelphia/model_lycd_reassessment.ipynb)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

TAX_YEAR = 2026
ABATEMENT_LIFE = 10
ABATEMENTS = ["old_flat_100", "old_flat_partial", "new_graduated_residential", "new_flat_90_commercial"]
PCT_BANDS = [-np.inf, -25, 0, 25, 100, np.inf]
PCT_LABELS = ["down >25%", "down 0-25%", "up 0-25%", "up 25-100%", "up >100%"]
USD_CUTOFFS = (500, 1000, 2500)

DATA = REPO_ROOT / "analysis/data"
S5_EXPORT = DATA / f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s5.csv"
CLASSIFICATION = REPO_ROOT / f"cities/philadelphia/data/abatement_classification_ty{TAX_YEAR}.parquet"
PHASE_IN_EXPOSURE = DATA / "philadelphia_abatement_phase_in_exposure.csv"
OUT_SUMMARY = DATA / "philadelphia_abated_lvt_distribution.csv"
OUT_BUCKETS = DATA / "philadelphia_abated_lvt_buckets.csv"


def _pid(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64").astype(str).str.zfill(9)


def load_abated_cohort() -> pd.DataFrame:
    """The S5 export's rows for parcels with a construction abatement still running.

    Returns the export columns plus `schedule_type` and `abatement_year_ty`. Parcel ids that appear
    twice in the export describe different physical parcels (see cities/philadelphia/CLAUDE.md), so
    both rows are dropped rather than one being guessed.
    """
    d = pd.read_csv(S5_EXPORT, dtype={"parcel_id": str})
    d["pid"] = _pid(d["parcel_id"])
    d = d[~d["pid"].duplicated(keep=False)]

    cls = pd.read_parquet(CLASSIFICATION, columns=["parcel_number", "schedule_type", "abatement_year_ty"])
    cls["pid"] = _pid(cls["parcel_number"])
    cls = cls.drop_duplicates("pid")

    m = d.merge(cls[["pid", "schedule_type", "abatement_year_ty"]], on="pid", how="inner")
    in_cls = cls["pid"].isin(m["pid"]).mean()
    assert in_cls > 0.99, f"only {in_cls:.1%} of classified parcels found in the S5 export; stale export?"

    a = m[m["schedule_type"].isin(ABATEMENTS) & (m["exemption_kind"] == "building_share")]
    a = a[a["abatement_year_ty"] <= ABATEMENT_LIFE - 1]
    return a.copy()


def check_cohort(a: pd.DataFrame) -> None:
    """Guard the two things a wrong cohort or a wrong column would leave silent."""
    assert (a["current_tax"] > 0).all(), "abated parcel with no current bill; percent change undefined"
    assert (a["institutional_exempt"] == 0).all(), "institutionally exempt parcel in the abated cohort"
    resid = (a["total_change"] - (a["reassess_change"] + a["lvt_change"])).abs().max()
    assert resid < 0.01, f"total_change is not reassess_change + lvt_change (max gap ${resid:,.2f})"
    # The 4:1 bill must be a real, non-negative tax, not a reconstruction artifact.
    assert ((a["current_tax"] + a["total_change"]) >= -0.01).all(), "negative modeled bill"

    if PHASE_IN_EXPOSURE.exists():
        e = pd.read_csv(PHASE_IN_EXPOSURE)
        e = e[(e["scenario"] == "lvt_phase_in") & (e["schedule_type"] == "all abatements")]
        expected = int(e["parcels"].iloc[0])
        assert len(a) == expected, (
            f"cohort has {len(a):,} parcels but philadelphia_abatement_phase_in.py reports {expected:,}; "
            "one of the two inputs is stale, so rerun that script and this one together")
        print(f"cohort size matches the phase-in script's exposure output ({expected:,})")
    else:
        print(f"note: {PHASE_IN_EXPOSURE.name} not found; cohort size not cross-checked")


def summarize(g: pd.DataFrame) -> pd.Series:
    p, t = g["total_change_pct"], g["total_change"]
    q = p.quantile([0.10, 0.25, 0.50, 0.75, 0.90])
    row = {
        "parcels": len(g),
        "pct_p10": q[0.10], "pct_p25": q[0.25], "pct_median": q[0.50], "pct_p75": q[0.75], "pct_p90": q[0.90],
        "share_up": (t > 0).mean(), "share_down": (t < 0).mean(),
        "share_up_over_25pct": (p > 25).mean(), "share_up_over_100pct": (p > 100).mean(),
        "usd_median": t.median(), "usd_p10": t.quantile(0.10), "usd_p90": t.quantile(0.90),
    }
    for c in USD_CUTOFFS:
        row[f"share_up_over_{c}usd"] = (t > c).mean()
    row["net_change_usd_m"] = t.sum() / 1e6
    row["current_tax_usd_m"] = g["current_tax"].sum() / 1e6
    row["median_reassess_pct"] = g["reassess_change_pct"].median()
    row["median_split_rate_pct"] = g["lvt_change_pct"].median()
    return pd.Series(row)


def build(a: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    order = [s for s in ABATEMENTS if s in set(a["schedule_type"])]
    summary = pd.DataFrame({s: summarize(a[a["schedule_type"] == s]) for s in order}).T
    summary.loc["all abatements"] = summarize(a)
    summary.index.name = "schedule_type"

    band = pd.cut(a["total_change_pct"], PCT_BANDS, labels=PCT_LABELS)
    buckets = pd.crosstab(a["schedule_type"], band, normalize="index").reindex(order)
    buckets.loc["all abatements"] = band.value_counts(normalize=True).reindex(PCT_LABELS)
    buckets.index.name = "schedule_type"
    return summary, buckets


def main(argv: Optional[list] = None) -> None:
    a = load_abated_cohort()
    check_cohort(a)
    summary, buckets = build(a)
    summary.to_csv(OUT_SUMMARY)
    buckets.to_csv(OUT_BUCKETS)

    show = ["parcels", "pct_p10", "pct_p25", "pct_median", "pct_p75", "pct_p90",
            "share_up", "share_up_over_25pct", "share_up_over_100pct", "usd_median"]
    print(f"\n{len(a):,} parcels with a construction abatement still running; "
          "change in bill, immediate 4:1 on S5 land vs. today's TY2026 bill")
    print(summary[show].round(2).to_string())
    print("\nShare of parcels by size of change")
    print((buckets * 100).round(1).to_string())
    print(f"\nwrote {OUT_SUMMARY.relative_to(REPO_ROOT)} and {OUT_BUCKETS.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
