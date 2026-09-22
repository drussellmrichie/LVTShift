"""The market check on abated homes: their own pre-construction lot sale.

`02_split_vs_alternatives.py` compares OPA's 20% default against two modeled surfaces (s5,
LYCD) and, separately, against FHFA's tract-level land SHARE. Neither converts cleanly to a
dollar land value for an abated home specifically: `share * the home's own (post-construction,
abatement-inflated) total` overstates land, `share * the tract's typical house scaled to this
lot's area` understates it (module docstring there has the numbers). This script sidesteps the
conversion problem entirely for the subset of abated homes where it isn't needed: `philly_open_
avmkit`'s W1b (sold vacant, later built on) and W2 (bought and torn down) witness streams are
exactly these parcels' own lots, sold at close to arm's length, time-adjusted to the TY2026
valuation date by the pipeline's own residential_sf index. That is the "market value of the
land as if vacant" the draft ordinance asks for, on the parcel itself rather than inferred from
a neighborhood aggregate.

Coverage is 440 of ~12,000 full abatements (3.7%) -- enough to characterize the mechanism and
its direction, not to bill an individual parcel. Two things follow from that:

1. The witnessed subset is NOT a random sample of abated homes -- it skews toward cheaper,
   more-recently-built parcels in lower-income tracts (a developer who assembled land a decade
   ago is less likely to show up as a recent arm's-length sale). `reweighted_lot_ratio` corrects
   the headline ratio to the full cohort's (income tercile x OPA category code) composition;
   the unweighted numbers are reported alongside it so the correction is visible, not hidden.
2. Painted s5 values are IN-SAMPLE for a witness parcel (the paired-sales estimator can use the
   parcel's own sale as its nearest comparable) and were shown circular in
   `philly_open_avmkit`'s own scoring (`holdout_predictions.csv`). `out_of_fold_check` compares
   the painted value against the fold-held-out one on this exact subset, so the s5 numbers used
   for comparison in `02_split_vs_alternatives.py` carry a stated, measured degree of optimism.

Reads  analysis/data/philadelphia_lycd_reassessment_ty2026_s5.csv (via 02's `load`)
       cities/philadelphia/data/abatement_classification_ty2026.parquet (via 02's `load`)
       <PHILLY_AVMKIT_ROOT>/.../out/land/witnesses.csv
       <PHILLY_AVMKIT_ROOT>/.../out/land/holdout_predictions.csv
Writes analysis/opa_split_equity/out/*.csv

Run from the repo root:
    python analysis/opa_split_equity/03_lot_sale_witness.py
"""
import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

# 02's module number makes it unimportable by name; load it by path instead, so both scripts
# share one cohort definition rather than drifting apart from copy-paste.
_spec = importlib.util.spec_from_file_location(
    "opa_split_equity_02", Path(__file__).resolve().parent / "02_split_vs_alternatives.py")
S02 = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = S02
_spec.loader.exec_module(S02)

PHILLY_AVMKIT_ROOT = Path(os.environ.get("PHILLY_AVMKIT_ROOT", r"C:\projects\philly_open_avmkit"))
LAND_DIR = PHILLY_AVMKIT_ROOT / "notebooks" / "pipeline" / "data" / "us-pa-philadelphia" / "out" / "land"
WITNESS_KINDS = ("W1b", "W2")   # sold-vacant-since-built and teardown: a lot sale under this parcel
INCOME_TERCILES = 3            # small n (~440) -- terciles, not the quintiles 02 uses on the full cohort


def load_witnesses() -> pd.DataFrame:
    p = LAND_DIR / "witnesses.csv"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. This script needs philly_open_avmkit's land pipeline outputs; "
            "set PHILLY_AVMKIT_ROOT or run notebooks/pipeline/run_land_surfaces.py there.")
    w = pd.read_csv(p, usecols=["key", "kind", "sale_date", "sale_price", "time_factor",
                                "land_area_sqft"])
    w["key"] = w.key.astype(str)
    return w[w.kind.isin(WITNESS_KINDS)]


def build_witnessed_cohort() -> pd.DataFrame:
    """Full abatements (real schedules only) with their own recorded pre-construction lot sale."""
    df = S02.load()
    cohort = S02.abatement_cohort(df)
    full = cohort[cohort.abatement == "full"].copy()

    w = load_witnesses()
    j = full.merge(w, left_on="parcel_id", right_on="key", how="inner")
    # A parcel could in principle show up twice (e.g. sold vacant, then a later teardown sale
    # record for the same key); keep the most recent, which is the developer's actual purchase.
    j = j.sort_values("sale_date").drop_duplicates("parcel_id", keep="last")

    j["lot_value"] = j.sale_price * j.time_factor
    j["lot_share_of_total"] = j.lot_value / j.total
    j["opa_over_lot"] = j.opa_land / j.lot_value
    j["s5_over_lot"] = j.s5_land / j.lot_value
    assert j.time_factor.between(0.5, 2.0).all(), "a time-adjustment factor is out of the plausible range"
    return full, j


def representativeness(full: pd.DataFrame, j: pd.DataFrame) -> pd.DataFrame:
    """How the witnessed subset differs from the full-abatement cohort it's drawn from."""
    rows = {}
    for name, frame in (("full abatement cohort", full), ("witnessed subset", j)):
        rows[name] = {"n": len(frame), "median_income_usd": frame.median_income.median(),
                     "median_minority_pct": frame.minority_pct.median(),
                     "median_total_assessment_usd": frame.total.median()}
    return pd.DataFrame(rows).T


def stratum_edges(full: pd.DataFrame, by: str, q: int) -> np.ndarray:
    return pd.qcut(full[by].dropna(), q, retbins=True, duplicates="drop")[1]


def lot_ratio_by_stratum(j: pd.DataFrame, edges: np.ndarray, by: str, labels: list) -> pd.DataFrame:
    d = j.copy()
    d["stratum"] = pd.cut(d[by], edges, labels=labels, include_lowest=True)
    g = d.groupby("stratum", observed=True).agg(
        n=("opa_over_lot", "size"),
        opa_over_lot_median=("opa_over_lot", "median"),
        s5_over_lot_median=("s5_over_lot", "median"),
        lot_share_of_total_median=("lot_share_of_total", "median"))
    return g


def _weighted_median(values: pd.Series, weights: np.ndarray) -> float:
    order = np.argsort(values.to_numpy())
    v, w = values.to_numpy()[order], weights[order]
    cum = np.cumsum(w)
    if cum[-1] <= 0:
        return float("nan")
    return float(v[np.searchsorted(cum, cum[-1] / 2)])


def reweighted_lot_ratio(full: pd.DataFrame, j: pd.DataFrame, income_edges: np.ndarray) -> pd.DataFrame:
    """Reweight the witnessed subset to the full cohort's (income tercile x category) mix.

    Each witnessed parcel gets weight = (its cell's share of the full cohort) / (its cell's
    share of the witnessed subset), so cells the witnessed subset over-represents count for
    less and cells it under-represents count for more. Cells with zero witnessed coverage
    can't be corrected for and are reported as a coverage gap, not silently dropped.
    """
    full = full.copy()
    j = j.copy()
    full["inc"] = pd.cut(full.median_income, income_edges, labels=[f"T{i}" for i in range(1, len(income_edges))],
                         include_lowest=True)
    j["inc"] = pd.cut(j.median_income, income_edges, labels=[f"T{i}" for i in range(1, len(income_edges))],
                      include_lowest=True)
    full["cell"] = full.inc.astype(str) + "|" + full.property_category.astype(str)
    j["cell"] = j.inc.astype(str) + "|" + j.property_category.astype(str)

    cohort_mix = full.cell.value_counts(normalize=True)
    witness_mix = j.cell.value_counts(normalize=True)
    weight = (cohort_mix / witness_mix).reindex(j.cell).fillna(0.0).to_numpy()

    covered_share = full.cell.isin(j.cell.unique()).mean()
    return pd.DataFrame([{
        "n_witnessed": len(j),
        "unweighted_opa_over_lot_median": j.opa_over_lot.median(),
        "reweighted_opa_over_lot_median": _weighted_median(j.opa_over_lot, weight),
        "unweighted_s5_over_lot_median": j.s5_over_lot.median(),
        "reweighted_s5_over_lot_median": _weighted_median(j.s5_over_lot, weight),
        "unweighted_lot_share_median": j.lot_share_of_total.median(),
        "reweighted_lot_share_median": _weighted_median(j.lot_share_of_total, weight),
        "cells_witnessed": j.cell.nunique(), "cells_in_cohort": full.cell.nunique(),
        "cohort_share_in_witnessed_cells": covered_share,
    }])


def bill_at_lot_price(j: pd.DataFrame) -> pd.DataFrame:
    """What the abatement cohort would pay if land were priced at its own recorded lot sale.

    Capped at the parcel's own total, the same cap `reallocate_land_within_total` applies --
    the re-split can never assess a parcel above what OPA already says its whole property is
    worth.
    """
    land = np.minimum(j.lot_value, j.total)
    ch = (land - j.opa_land) * S02.MILLAGE / 1000
    return pd.DataFrame([{
        "n": len(j), "current_tax_usd": j.current_tax.sum(), "net_change_usd": ch.sum(),
        "net_pct_of_cohort_tax": 100 * ch.sum() / j.current_tax.sum(),
        "pct_pay_more": 100 * (ch > S02.TOL).mean(), "pct_pay_less": 100 * (ch < -S02.TOL).mean(),
        "median_change_usd": ch.median(),
    }]), ch


def effective_rate_dispersion(j: pd.DataFrame, ch: pd.Series) -> pd.DataFrame:
    """Mills of total assessed value actually collected, today vs at the parcel's own lot price.

    OPA's flat 20% gives every fully abated home close to the same effective rate on its total
    regardless of what its land is worth; pricing land at what it actually sold for spreads
    that out. The p90/p10 ratio is the simplest single number for how much spread the default
    default erases.
    """
    today = 1000 * j.current_tax / j.total
    at_lot = 1000 * (j.current_tax + ch) / j.total
    rows = {}
    for name, s in (("today (OPA 20% default)", today), ("at own recorded lot price", at_lot)):
        rows[name] = {"p10_mills": s.quantile(0.10), "p50_mills": s.quantile(0.50),
                     "p90_mills": s.quantile(0.90), "p90_over_p10": s.quantile(0.90) / s.quantile(0.10)}
    return pd.DataFrame(rows).T


def out_of_fold_check(j: pd.DataFrame) -> pd.DataFrame:
    """Painted (in-sample) vs fold-held-out s5, on the same witnessed parcels, against the lot price.

    `land_surfaces.py`'s own construction note: a comp-based estimator like s5 can take the
    subject's own sale as its nearest comparable, so its in-sample value is very largely a
    function of the price it's about to be judged against. `holdout_predictions.csv` is each
    witness scored with its OWN fold's model, which never saw that witness during fitting.
    """
    p = LAND_DIR / "holdout_predictions.csv"
    if not p.exists():
        raise FileNotFoundError(f"{p} not found (see load_witnesses' message).")
    h = pd.read_csv(p, usecols=["key", "s5"])
    h["key"] = h.key.astype(str)
    m = j.merge(h, left_on="parcel_id", right_on="key", how="inner", suffixes=("", "_h"))
    m["s5_oof_land"] = m.s5 * m.land_area_sqft
    m["s5_oof_over_lot"] = m.s5_oof_land / m.lot_value

    def cod(ratio: pd.Series) -> float:
        r = ratio.dropna()
        return 100 * (r / r.median() - 1).abs().mean()

    rows = {"OPA / lot": m.opa_over_lot, "s5 painted (in-sample) / lot": m.s5_over_lot,
            "s5 out-of-fold / lot": m.s5_oof_over_lot}
    return pd.DataFrame({name: {"n": int(s.notna().sum()), "median": s.median(), "cod_pct": cod(s)}
                         for name, s in rows.items()}).T


def main() -> None:
    full, j = build_witnessed_cohort()
    print(f"full abatements (real schedules): {len(full):,}; with a recorded pre-construction "
          f"lot sale: {len(j):,} ({100 * len(j) / len(full):.1f}%)\n")

    rep = representativeness(full, j)
    rep.to_csv(OUT / "witness_representativeness.csv")
    print("== witness_representativeness ==\n", rep.round(1).to_string(), "\n")

    inc_edges = stratum_edges(full, "median_income", INCOME_TERCILES)
    min_edges = stratum_edges(full, "minority_pct", INCOME_TERCILES)
    by_inc = lot_ratio_by_stratum(j, inc_edges, "median_income", ["low_income", "mid_income", "high_income"])
    by_min = lot_ratio_by_stratum(j, min_edges, "minority_pct", ["whitest", "mid", "most_nonwhite"])
    by_inc.to_csv(OUT / "lot_ratio_by_income_tercile.csv")
    by_min.to_csv(OUT / "lot_ratio_by_minority_tercile.csv")
    print("== lot_ratio_by_income_tercile ==\n", by_inc.round(2).to_string(), "\n")
    print("== lot_ratio_by_minority_tercile ==\n", by_min.round(2).to_string(), "\n")

    rw = reweighted_lot_ratio(full, j, inc_edges)
    rw.to_csv(OUT / "reweighted_lot_ratio.csv", index=False)
    print("== reweighted_lot_ratio ==\n", rw.round(3).T.to_string(), "\n")

    bill, ch = bill_at_lot_price(j)
    bill.to_csv(OUT / "full_abatement_at_lot_price.csv", index=False)
    print("== full_abatement_at_lot_price ==\n", bill.round(2).T.to_string(), "\n")

    disp = effective_rate_dispersion(j, ch)
    disp.to_csv(OUT / "effective_rate_dispersion.csv")
    print("== effective_rate_dispersion ==\n", disp.round(2).to_string(), "\n")

    oof = out_of_fold_check(j)
    oof.to_csv(OUT / "s5_out_of_fold_check.csv")
    print("== s5_out_of_fold_check ==\n", oof.round(2).to_string())


if __name__ == "__main__":
    main()
