"""Generate every figure, table, and headline macro for the report.

SINGLE SOURCE OF NUMERICAL CONTENT for paper/Report.tex. Re-run after any data change:

    C:/Users/druss/miniconda3/python.exe analysis/lycd_reassessment/philadelphia/paper/scripts/generate_paper_assets.py

Then rebuild the PDF. Never type a result number into Report.tex -- add it here as a macro,
regenerate, and reference the macro.

Reads:

    analysis/data/philadelphia_lycd_reassessment_ty2026.csv          per-parcel, both scenarios
    analysis/data/philadelphia_lycd_reassessment_ty2026_s5.csv       the same, on the certified
                                                                     sales-based surface
    analysis/data/philadelphia_vacant_land_ratio_study_ty2026.csv    sales test of both surfaces
    analysis/data/philadelphia_equity_by_surface_*.csv               land-tax equity by surface
    analysis/reports/philadelphia_lycd_reassessment_ty2026/metrics_*.csv
    cities/philadelphia/data/census_tracts.gpq                       map geometry
    <PHILLY_AVMKIT_ROOT>/.../out/land/                               land evidence and scores

The reassessment exports come from cities/philadelphia/model_lycd_reassessment.ipynb (the _s5
one with LVT_LAND_SURFACE=s5), the ratio study from scripts/vacant_land_ratio_study.py, and the
equity CSVs from scripts/philadelphia_equity_by_land_surface.py.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_helpers import (  # noqa: E402
    Headlines, PPI_COLORS, latex_escape, money, num, usd_b, usd_m, pct, ratio, save_table, text,
)

PAPER = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[5]
DATA = REPO_ROOT / "analysis" / "data"
CITY_DATA = REPO_ROOT / "cities" / "philadelphia" / "data"
TABLES = PAPER / "tables"
FIGS = PAPER / "figures"
TABLES.mkdir(parents=True, exist_ok=True)
FIGS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO_ROOT))
from lvt.philadelphia import tax_year_params      # noqa: E402
from lvt.reassessment import reassessment_equity  # noqa: E402

plt.rcParams.update({
    "savefig.dpi": 300, "savefig.bbox": "tight",
    "font.family": "serif", "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False,
})

PREFIX = "Lycd"
TAX_YEAR = 2026
SLUG = f"philadelphia_lycd_reassessment_ty{TAX_YEAR}"
TY = tax_year_params(TAX_YEAR)

# IAAO Standard on Ratio Studies (2013) Sec. 9.2.4: vacant land COD 5.0-20.0, with 25.0 allowed
# only for rural or seasonal land, which Philadelphia is not. PRB's acceptable band is +/-0.05.
IAAO_COD = 20.0
IAAO_PRB_BAND = 0.05
# LYCD's vacant multiplier and improved multiplier -- the method's own constants, needed to turn
# an observed sales ratio into the k the sales would support.
LYCD_K_VACANT, LYCD_K_IMPROVED = 1.00, 0.20
# Display clips, cited in the captions so they are macros not literals.
MAP_PCT_CLIP = 30.0
RATIO_HIST_CLIP = 0.6
SCENARIO_HIST_CLIP = 60.0

USECOLS = [
    "parcel_id", "property_category", "current_tax", "new_tax", "tax_change", "tax_change_pct",
    "taxable_land_value", "taxable_improvement_value", "std_geoid", "median_income",
    "minority_pct", "land_millage", "lycd_land_value", "opa_gross_land", "opa_gross_building",
    "gma_level", "area_source", "institutional_exempt", "reentered_base",
    "alloc_land", "alloc_building", "alloc_taxable_total", "alloc_new_tax", "alloc_tax_change",
    "alloc_tax_change_pct", "exemption_kind", "norollback_new_tax", "abated", "market_value",
    "taxable_total", "dor_area_sqft", "lycd_zone_psf", "gma3",
]

CAT_ORDER = [
    "Single Family Residential", "Small Multi-Family (2-4 units)",
    "Large Multi-Family (5+ units)", "Mixed Use", "Commercial", "Industrial",
    "Office / Commercial Condo", "Hotel", "Abated / Construction Exemption", "Vacant Land",
]


def pct0(x):
    """Whole-number percent, for the tests' tolerance parameters."""
    return f"{float(x):.0f}%"


def tex_usd(x, decimals=0):
    """Dollars for a table cell written with escape=False: the '$' must be escaped or it
    opens math mode, and a negative reads better as -$785 than $-785."""
    s = f"\\${abs(float(x)):,.{decimals}f}"
    return f"-{s}" if float(x) < 0 else s


def tex_usd_m(x, decimals=1):
    s = f"\\${abs(float(x)):,.{decimals}f}M"
    return f"-{s}" if float(x) < 0 else s


def load():
    df = pd.read_csv(DATA / f"{SLUG}.csv", usecols=USECOLS, dtype={"parcel_id": str,
                                                                   "std_geoid": str,
                                                                   "gma3": str})
    rat = pd.read_csv(DATA / f"philadelphia_vacant_land_ratio_study_ty{TAX_YEAR}.csv")
    met = pd.read_csv(REPO_ROOT / "analysis" / "reports" / SLUG / f"metrics_{SLUG}.csv").iloc[0]
    return df, rat, met


# --------------------------------------------------------------------------- #
# The sales-based surface (the second analysis)
# --------------------------------------------------------------------------- #
# philly_open_avmkit owns the land evidence, the held-out scoring and the choice of surface;
# LVTShift reads its outputs read-only (never the reverse). The tax-side export is this
# notebook re-run with LVT_LAND_SURFACE=<the certified surface>, so every tax-side number for
# it comes through the same code path as LYCD's and differs only in the land rate.
#
# Point PHILLY_AVMKIT_ROOT at that repo's checkout to build the section elsewhere; the default
# is this machine's layout. Without it the generator still runs and simply omits the section
# (load_sales warns and returns None), so a fresh clone produces a shorter report rather than a
# wrong one.
PHILLY_AVMKIT_ROOT = Path(os.environ.get("PHILLY_AVMKIT_ROOT", r"C:\projects\philly_open_avmkit"))
PHILLY_LAND = PHILLY_AVMKIT_ROOT / "notebooks" / "pipeline" / "data" / "us-pa-philadelphia" / "out" / "land"
# The surface the sibling repo's land roll certifies (asserted against land_roll_meta.json).
SALES_SURFACE = "s5"
SALES_SLUG = f"{SLUG}_{SALES_SURFACE}"
SALES_COLS = ["parcel_id", "lycd_land_value", "alloc_land", "alloc_tax_change", "alloc_tax_change_pct",
              "tax_change", "tax_change_pct", "current_tax", "land_millage", "land_surface_source",
              "land_surface_psf", "lycd_land_value_lycd", "opa_gross_land", "opa_gross_building",
              "market_value", "institutional_exempt", "property_category", "exemption_kind",
              "std_geoid", "dor_area_sqft", "abated", "area_source"]

# Candidate -> (macro key, table label, short label). Only these rows are shown; every other
# held-out candidate is counted, not tabulated.
CANDIDATES = {
    "S0 OPA assessed land": ("Szero", "OPA assessed land", "OPA"),
    "S1 LYCD zone-rate allocation": ("Sone", "LYCD zone-rate allocation", "LYCD allocation"),
    "S3 published schedule": ("Sthree", "Published rate schedule", "Schedule"),
    "S4 Kolbe extraction (fold-calibrated)": ("Sfourcv", "Extraction from improved sales", "Extraction"),
    "S8 Albouy-Shin hierarchical Bayesian (NUTS, fold-calibrated)":
        ("Seight", "Hierarchical Bayesian model", "Bayesian model"),
    "S2 kNN interpolation (k=20)": ("Stwo", "Interpolation among sales", "Interpolation"),
    "S5 paired-sales comparables (k=10)": ("Sfive", "Paired-sales comparables", "Paired sales"),
    "E-GBM openavmkit gradient-boosted trees (fold-fitted)":
        ("Egbm", "Gradient-boosted trees", "Boosted trees"),
}
# land_tests.csv / land_tests_4c_t7_summary.csv use their own short names.
TEST_KEYS = {"OPA": "Szero", "LYCD allocation": "Sone", "Interpolation (k=20)": "Stwo",
             "Schedule": "Sthree", "Paired sales": "Sfive", "Gradient-boosted trees": "Egbm"}
H2H_KEYS = {
    ("S5 paired-sales comparables (k=10)", "S0 OPA assessed land"): "SfiveVsSzero",
    ("S5 paired-sales comparables (k=10)", "S3 published schedule"): "SfiveVsSthree",
    ("S5 paired-sales comparables (k=10)", "S2 kNN interpolation (k=20)"): "SfiveVsStwo",
    ("E-GBM openavmkit gradient-boosted trees (fold-fitted)", "S5 paired-sales comparables (k=10)"): "EgbmVsSfive",
    ("S8 Albouy-Shin hierarchical Bayesian (NUTS, fold-calibrated)", "S5 paired-sales comparables (k=10)"):
        "SeightVsSfive",
    ("S3 published schedule", "S0 OPA assessed land"): "SthreeVsSzero",
    ("S4 Kolbe extraction (fold-calibrated)", "S0 OPA assessed land"): "SfourcvVsSzero",
    ("S0 OPA assessed land", "S1 LYCD zone-rate allocation"): "SzeroVsSone",
}


def load_sales():
    """The certified surface's run of the notebook plus the sibling repo's evidence and scores, or None."""
    p = DATA / f"{SALES_SLUG}.csv"
    need = ["scores.csv", "head_to_head.csv", "witnesses.csv", "land_tests.csv",
            "land_tests_4c_t7_summary.csv", "noise_floor_measured.json", "land_roll_meta.json"]
    missing = [n for n in need if not (PHILLY_LAND / n).exists()]
    if not p.exists() or missing:
        print(f"  [warn] sales-surface inputs missing ({p.name} or {missing}); section skipped")
        return None
    meta = json.loads((PHILLY_LAND / "land_roll_meta.json").read_text())
    assert meta["surface_column"] == SALES_SURFACE, (
        f"the sibling repo now certifies {meta['surface_column']!r}, not {SALES_SURFACE!r}: "
        f"re-run model_lycd_reassessment.ipynb with LVT_LAND_SURFACE={meta['surface_column']} "
        "and update SALES_SURFACE")
    return {
        "export": pd.read_csv(p, usecols=SALES_COLS, dtype={"parcel_id": str, "std_geoid": str}),
        "witnesses": pd.read_csv(PHILLY_LAND / "witnesses.csv"),
        "scores": pd.read_csv(PHILLY_LAND / "scores.csv"),
        "h2h": pd.read_csv(PHILLY_LAND / "head_to_head.csv"),
        "tests": pd.read_csv(PHILLY_LAND / "land_tests.csv"),
        "prb": pd.read_csv(PHILLY_LAND / "land_tests_4c_t7_summary.csv"),
        "noise": json.loads((PHILLY_LAND / "noise_floor_measured.json").read_text()),
        "meta": meta,
    }


def sales_section(df, s, H):
    """Macros, tables and the figure for the sales-based surface."""
    w, sc, h2h, ex = s["witnesses"], s["scores"], s["h2h"], s["export"]

    # --- the evidence ---------------------------------------------------------------
    by = w.groupby("kind")["psf_adj"].agg(["size", "median"])
    H.add("WitN", len(w), num)
    for k, nm in (("W1", "Wone"), ("W1b", "Woneb"), ("W2", "Wtwo")):
        if k in by.index:
            H.add(f"{nm}N", int(by.loc[k, "size"]), num)
            H.add(f"{nm}Psf", by.loc[k, "median"], lambda x: f"${x:,.2f}")
    if {"W1", "W1b", "W2"} <= set(by.index):
        H.add("WonebOverWone", by.loc["W1b", "median"] / by.loc["W1", "median"], ratio)
        H.add("WtwoOverWone", by.loc["W2", "median"] / by.loc["W1", "median"], ratio)
    H.add("WitSubMinPct", 100 * w["sub_minimum"].mean(), pct)
    H.add("WitGmaThreeZones", w["gma3"].nunique(), num)
    H.add("WitPerGmaThreeMedian", w.groupby("gma3").size().median(), lambda x: f"{x:.0f}")
    desc = {"W1": "Sold vacant, still vacant", "W1b": "Sold vacant, since built on",
            "W2": "Sold improved, demolished within a year"}
    tbl = pd.DataFrame({
        "Evidence": [desc[k] for k in by.index],
        "Sales": by["size"].map(num).values,
        "Median \\$/sqft": by["median"].map(lambda x: f"\\${x:,.2f}").values,
    })
    save_table(TABLES / "witness_streams.tex", tbl, col_format="X r r", escape=False)

    # --- held-out accuracy ------------------------------------------------------------
    allw = sc[sc["subset"].eq("all witnesses")].set_index("candidate")
    order = [c for c in CANDIDATES if c in allw.index]
    for cand in order:
        nm = CANDIDATES[cand][0]
        r = allw.loc[cand]
        H.add(f"{nm}TrCod", r["tr_cod"], lambda x: f"{x:.0f}")
        H.add(f"{nm}RawCod", r["cod"], lambda x: f"{x:.0f}")
        H.add(f"{nm}TrMedian", r["tr_median"], lambda x: f"{x:.2f}")
        H.add(f"{nm}TrPrd", r["tr_prd"], lambda x: f"{x:.2f}")
        H.add(f"{nm}NetLo", r["cod_net_lo"], lambda x: f"{x:.0f}")
        H.add(f"{nm}NetHi", r["cod_net_hi"], lambda x: f"{x:.0f}")
    H.add("HeldoutN", int(allw.loc["S5 paired-sales comparables (k=10)", "n"]), num)
    H.add("HeldoutCandidates", int(allw["held_out"].sum()), num)
    H.add("HeldoutUntabulated", int(allw["held_out"].sum()) - sum(allw.loc[order, "held_out"]), num)
    short = {c: CANDIDATES[c][1] for c in order}
    tbl = pd.DataFrame({
        "Surface": [short[c] for c in order],
        "Held out": ["yes" if allw.loc[c, "held_out"] else "no" for c in order],
        "n": [num(allw.loc[c, "n"]) for c in order],
        "Median": [f"{allw.loc[c, 'tr_median']:.2f}" for c in order],
        "COD, trimmed": [f"{allw.loc[c, 'tr_cod']:.0f}" for c in order],
        "COD, raw": [f"{allw.loc[c, 'cod']:.0f}" for c in order],
        "PRD": [f"{allw.loc[c, 'tr_prd']:.2f}" for c in order],
    })
    save_table(TABLES / "heldout.tex", tbl, col_format="X l r r r r r", escape=False)

    # Per-stream COD -- where does each surface do its work?
    piv = sc.pivot_table(index="candidate", columns="subset", values="tr_cod")
    subsets = [x for x in ("W1 only", "W1b only", "W2 only") if x in piv.columns]
    stream_rows = [c for c in order if c in piv.index and CANDIDATES[c][0] != "Seight"]
    tbl = pd.DataFrame({"Surface": [short[c] for c in stream_rows]})
    for sub, lab in zip(subsets, ("Still vacant", "Since built on", "Teardown")):
        tbl[lab] = [f"{piv.loc[c, sub]:.0f}" if np.isfinite(piv.loc[c, sub]) else "---" for c in stream_rows]
    save_table(TABLES / "heldout_by_stream.tex", tbl, col_format="X r r r", escape=False)
    for cand in stream_rows:
        for sub, lab in zip(subsets, ("Wone", "Woneb", "Wtwo")):
            H.add(f"{CANDIDATES[cand][0]}TrCod{lab}", piv.loc[cand, sub], lambda x: f"{x:.0f}")

    # The measured transaction-noise floor: the COD a perfect surface would score on these sales.
    band = s["noise"]["measured_perfect_surface_cod_band"]
    H.add("NoiseCodLo", band[0], lambda x: f"{x:.0f}")
    H.add("NoiseCodHi", band[1], lambda x: f"{x:.0f}")
    H.add("NoiseRepeatPairs", s["noise"]["repeat_sales"]["n_pairs"], num)
    H.add("NoiseNeighbourPairs", s["noise"]["neighbour_pairs_30m"]["n_pairs"], num)

    # --- head to head -------------------------------------------------------------------
    rows = []
    for _, r in h2h.iterrows():
        nm = H2H_KEYS.get((r["a"], r["b"]))
        if nm is None:
            continue
        H.add(f"{nm}Diff", r["cod_diff"], lambda x: f"{x:+.1f}")
        H.add(f"{nm}DiffAbs", abs(r["cod_diff"]), lambda x: f"{x:.1f}")
        H.add(f"{nm}Lo", r["lo"], lambda x: f"{x:+.1f}")
        H.add(f"{nm}Hi", r["hi"], lambda x: f"{x:+.1f}")
        H.add(f"{nm}P", r["p_a_better"], lambda x: f"{x:.3f}")
        rows.append({"order": list(H2H_KEYS.values()).index(nm),
                     "A": CANDIDATES[r["a"]][2], "B": CANDIDATES[r["b"]][2],
                     "COD difference": f"{r['cod_diff']:+.1f}",
                     "95\\% interval": f"[{r['lo']:+.1f}, {r['hi']:+.1f}]",
                     "P(A better)": f"{r['p_a_better']:.3f}"})
    assert len(rows) == len(H2H_KEYS), "a head-to-head pair the report cites is missing from head_to_head.csv"
    out = pd.DataFrame(rows).sort_values("order").drop(columns="order")
    save_table(TABLES / "head_to_head.tex", out, col_format="X X r r r", escape=False)

    # --- selection: the rule the land roll applies, and what it held out ----------------
    meta = s["meta"]
    bar = re.search(r">=\s*([0-9.]+)%", meta["selection"]["rule"])
    H.add("TOneBar", float(bar.group(1)), pct0)
    gbm = [c for c in meta["selection"]["considered"] if c["column"] == "e_gbm"][0]
    H.add("EgbmGated", "yes" if gbm["gated"] else "no")

    # --- vertical equity of each surface (IAAO PRB) ----------------------------------------
    for _, r in s["prb"].iterrows():
        nm = TEST_KEYS.get(r["candidate"])
        if nm is not None:
            H.add(f"{nm}Prb", r["prb"], lambda x: f"{x:+.3f}")
    H.add("IaaoPrbBand", IAAO_PRB_BAND, lambda x: f"{x:.2f}")

    # --- what the certified surface does to the roll ---------------------------------------
    b = ex[(ex["institutional_exempt"] == 0) & (ex["current_tax"] > 0)]
    knn = ex["land_surface_source"].eq("knn")
    H.add("SfiveKnnParcels", int(knn.sum()), num)
    H.add("SfiveKnnValuePct", 100 * ex.loc[knn, "market_value"].sum() / ex["market_value"].sum(), pct)
    H.add("SfiveLandBaseB", ex["lycd_land_value"].sum() / 1e9, usd_b)
    H.add("LycdLandBaseB", ex["lycd_land_value_lycd"].sum() / 1e9, usd_b)
    H.add("OpaLandBaseB", ex["opa_gross_land"].sum() / 1e9, usd_b)
    H.add("SfiveOverOpaLand", ex["lycd_land_value"].sum() / ex["opa_gross_land"].sum(), ratio)
    H.add("SfiveOverLycdLand", ex["lycd_land_value"].sum() / ex["lycd_land_value_lycd"].sum(), ratio)
    imp = ex[ex["opa_gross_building"] > 0].copy()
    # Sec. 3(c) on the sales-based surface: how often does land ALONE exceed OPA's total
    # assessment before the cap binds? Measured on the pre-cap value (rate x area), since the
    # exported land value is already capped. Split out the cohort whose lot area is itself
    # imputed (condominium units and other records with no lot of their own, which inherit a
    # neighbour's whole-lot area): their overshoot is the known area artifact, not evidence
    # about OPA's totals.
    imp["pre_cap"] = imp["land_surface_psf"] * imp["dor_area_sqft"]
    over = imp["pre_cap"] > imp["market_value"]
    condo_like = imp["area_source"].eq("knn")
    H.add("SfivePreCapExceeds", int(over.sum()), num)
    H.add("SfivePreCapExceedsCondo", int((over & condo_like).sum()), num)
    H.add("SfivePreCapExceedsCore", int((over & ~condo_like).sum()), num)
    H.add("SfivePreCapExceedsCorePct", 100 * (over & ~condo_like).sum() / (~condo_like).sum(), pct)
    H.add("SfiveCapRemovedB", (imp.loc[over, "pre_cap"] - imp.loc[over, "market_value"]).sum() / 1e9, usd_b)
    H.add("SfiveCapRemovedCoreB",
          (imp.loc[over & ~condo_like, "pre_cap"] - imp.loc[over & ~condo_like, "market_value"]).sum() / 1e9, usd_b)
    H.add("SfiveKnnFillPsf", ex.loc[knn, "land_surface_psf"].median(), lambda x: f"${x:,.0f}")
    H.add("SfiveJoinedPsf", ex.loc[ex["land_surface_source"].eq("surface"), "land_surface_psf"].median(),
          lambda x: f"${x:,.0f}")

    # reading C under the sales-based surface
    moved = b["alloc_tax_change"].abs() > 0.01
    H.add("SfiveCMoved", int(moved.sum()), num)
    H.add("SfiveCMovedPct", 100 * moved.mean(), pct)
    lev = b["alloc_tax_change"].sum()
    H.add("SfiveCLevyAbsM", abs(lev) / 1e6, lambda x: f"${x:,.1f}M")
    H.add("SfiveCLevySign", "falls" if lev < 0 else "rises")
    H.add("SfiveCLevyPct", 100 * lev / ex["current_tax"].sum(), lambda x: f"{x:+.2f}%")
    ab = b[moved & (b["abated"] == 1)]
    H.add("SfiveCAbatedMedianPct", ab["alloc_tax_change_pct"].median(), lambda x: f"{x:+.1f}%")
    # reading A under the sales-based surface
    vac = b[b["property_category"] == "Vacant Land"]
    H.add("SfiveAVacantMedianPct", vac["tax_change_pct"].median(), lambda x: f"{x:+,.0f}%")
    H.add("SfiveAVacantShareOfShift",
          100 * vac["tax_change"].clip(lower=0).sum() / b["tax_change"].clip(lower=0).sum(), pct)

    # --- incentive and uniformity tests -------------------------------------------------
    t = s["tests"]
    t = t[t["candidate"].isin(TEST_KEYS)]
    moran_col = [c for c in t.columns if c.startswith("T4 Moran")][0]
    # Short headers: four numeric columns with long labels starve the X column, and the
    # surface names then hyphenate. The caption carries the definitions.
    disp = pd.DataFrame({
        "Surface": t["candidate"].values,
        "T1 neutral": [f"{v:.0f}\\%" for v in t["T1 rate-neutral %"]],
        "T2 COD": [f"{v:.0f}" for v in t["T2 within-cluster COD"]],
        "T3 cross / within": [f"{a:.0f}\\% / {c:.0f}\\%" for a, c in
                              zip(t["T3 cross-cell smooth %"], t["T3 within-cell smooth %"])],
        "T4 Moran $I$": [f"{v:+.2f}" for v in t[moran_col]],
    })
    save_table(TABLES / "land_tests.tex", disp, col_format="X r r r r", escape=False)
    for _, r in t.iterrows():
        nm = TEST_KEYS[r["candidate"]]
        H.add(f"{nm}TOne", r["T1 rate-neutral %"], pct0)
        H.add(f"{nm}TTwo", r["T2 within-cluster COD"], lambda x: f"{x:.0f}")
        H.add(f"{nm}TThreeCross", r["T3 cross-cell smooth %"], pct0)
        H.add(f"{nm}TThreeWithin", r["T3 within-cell smooth %"], pct0)
        H.add(f"{nm}TFour", r[moran_col], lambda x: f"{x:+.2f}")
        H.add(f"{nm}TFourP", r["T4 p"], lambda x: f"{x:.2f}")
    H.add("TOnePairs", int(t["T1 pairs"].max()), num)
    # The tests' own parameters, carried alongside their results so the caption cites
    # generated values and cannot drift if the tests are retuned.
    r0 = t.iloc[0]
    H.add("TPairRadiusM", r0["param_pair_radius_m"], lambda x: f"{x:.0f}")
    H.add("TSizeMatchPct", r0["param_size_match_pct"], pct0)
    H.add("TNeutralityTolPct", r0["param_neutrality_tol_pct"], pct0)
    H.add("TSmoothJumpPct", r0["param_smooth_jump_pct"], pct0)

    fig_sales_surface(allw, order, short, ex)
    return ex


def fig_sales_surface(allw, order, short, ex):
    """Left: held-out dispersion by surface. Right: where the certified surface departs
    from LYCD, by tract."""
    try:
        import geopandas as gpd
    except ImportError:
        gpd = None
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 4.1), gridspec_kw={"width_ratios": [1.0, 1.15]})
    rows = allw.loc[order]
    labels = [short[c].replace(" (", "\n(") for c in rows.index]
    colours = [PPI_COLORS["accent"] if CANDIDATES[c][0] == "Sfive"
               else PPI_COLORS["light"] if CANDIDATES[c][0] == "Egbm" else PPI_COLORS["primary"]
               for c in rows.index]
    axes[0].barh(labels, rows["tr_cod"], color=colours)
    axes[0].axvline(IAAO_COD, color=PPI_COLORS["dark"], lw=1.0, ls="--")
    axes[0].annotate("IAAO", (IAAO_COD + 1, -0.25), fontsize=7, color=PPI_COLORS["dark"])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("held-out COD, trimmed (lower is better)")
    axes[0].tick_params(axis="y", labelsize=7)

    if gpd is not None:
        geo = gpd.read_parquet(CITY_DATA / "census_tracts.gpq")
        geo["tract_geoid"] = geo["GEOID"].astype(str)
        t = ex.dropna(subset=["std_geoid"]).copy()
        t["tract_geoid"] = t["std_geoid"].astype(str).str.zfill(12).str[:11]
        agg = t.groupby("tract_geoid").agg(sales=("lycd_land_value", "sum"),
                                          lycd=("lycd_land_value_lycd", "sum"))
        agg["ratio"] = agg["sales"] / agg["lycd"].replace(0, np.nan)
        g = geo.merge(agg, on="tract_geoid", how="inner")
        g.plot(column=np.log2(g["ratio"].clip(0.25, 4.0)), cmap="RdBu_r", vmin=-2, vmax=2,
               linewidth=0.1, edgecolor="white", ax=axes[1], legend=True,
               legend_kwds={"label": "sales-based ÷ LYCD land (log2)",
                            "orientation": "horizontal", "shrink": 0.8, "pad": 0.02,
                            "extend": "both"})
        axes[1].set_axis_off()
    fig.tight_layout()
    fig.savefig(FIGS / "sales_surface.pdf")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Scenario slices
# --------------------------------------------------------------------------- #
def billed(df):
    """Parcels with a real bill today -- the population every per-parcel claim is about."""
    return df[(df["institutional_exempt"] == 0) & (df["current_tax"] > 0)]


def scenario_c(df, H):
    """The ordinance's reading: land re-split inside OPA's total, statutory rate untouched."""
    b = billed(df)
    moved = b["alloc_tax_change"].abs() > 0.01
    mv = b[moved]

    H.add("Parcels", len(df), num)
    H.add("BilledParcels", len(b), num)
    H.add("Millage", TY.combined_mills, lambda x: f"{x:.4f}")
    H.add("LevyB", df["current_tax"].sum() / 1e9, usd_b, )
    H.add("CMoved", int(moved.sum()), num)
    H.add("CMovedPct", 100 * moved.mean(), pct)
    H.add("CUnmovedPct", 100 * (1 - moved.mean()), pct)
    H.add("CUp", int((b["alloc_tax_change"] > 0.01).sum()), num)
    H.add("CDown", int((b["alloc_tax_change"] < -0.01).sum()), num)
    H.add("CLevyM", b["alloc_tax_change"].sum() / 1e6, lambda x: f"-${abs(x):,.1f}M")
    # Unsigned variants for prose where the verb carries the direction ("falls by $11.6M").
    H.add("CLevyAbsM", abs(b["alloc_tax_change"].sum()) / 1e6, lambda x: f"${x:,.1f}M")
    H.add("CLevyPct", 100 * b["alloc_tax_change"].sum() / df["current_tax"].sum(),
          lambda x: f"{x:.2f}%")
    H.add("CMedianPct", mv["alloc_tax_change_pct"].median(), lambda x: f"{x:.1f}%")

    ab = mv[mv["abated"] == 1]
    H.add("CAbatedMoved", len(ab), num)
    H.add("CAbatedMedianPct", ab["alloc_tax_change_pct"].median(), lambda x: f"{x:.1f}%")
    H.add("CAbatedMedianAbsPct", abs(ab["alloc_tax_change_pct"].median()), lambda x: f"{x:.1f}%")
    H.add("CAbatedNetM", ab["alloc_tax_change"].sum() / 1e6, lambda x: f"-${abs(x):,.1f}M")
    lr = (ab["lycd_land_value"] / ab["opa_gross_land"].replace(0, np.nan)).median()
    H.add("CAbatedLandRatio", lr, ratio)

    # Everything that is NOT abatement-type relief is bit-for-bit unchanged -- the claim the
    # notebook asserts on every run.
    H.add("CUnchangedParcels", int((~moved).sum()), num)

    # The exemption rule's reconstruction of today's bill is recoverable from the export:
    # alloc_new_tax is the rule on the new land, alloc_tax_change is (rule on new land) minus
    # (rule on OPA's land), so their difference is the rule on OPA's land. Where that differs
    # from the recorded bill, the rule cannot reproduce today's exemption for that parcel.
    recon = df["alloc_new_tax"] - df["alloc_tax_change"]
    mismatch = (recon - df["current_tax"]).abs() > 0.02      # $1 of value at ~14 mills
    H.add("ReconMatchPct", 100 * (1 - mismatch.mean()), pct)
    H.add("ReconMismatchParcels", int(mismatch.sum()), num)

    up, down = mv[mv["alloc_tax_change"] > 0], mv[mv["alloc_tax_change"] < 0]
    H.add("CUpM", up["alloc_tax_change"].sum() / 1e6, lambda x: f"${x:,.1f}M")
    H.add("CDownM", down["alloc_tax_change"].sum() / 1e6, lambda x: f"-${abs(x):,.1f}M")
    H.add("CAbatedShareOfNet",
          100 * mv.loc[mv["property_category"] == "Abated / Construction Exemption",
                       "alloc_tax_change"].sum() / mv["alloc_tax_change"].sum(), pct)
    sfr = mv[mv["property_category"] == "Single Family Residential"]
    H.add("CSfrMoved", len(sfr), num)
    H.add("CSfrMedianAbs", sfr["alloc_tax_change"].abs().median(), money)
    H.add("CSfrNinetiethAbs", sfr["alloc_tax_change"].abs().quantile(0.9), money)
    return b, moved


def scenario_a(df, H):
    """The revaluation reading: LYCD land added to OPA building, flat rate rolled back."""
    b = billed(df)
    H.add("AMillage", float(df["land_millage"].iloc[0]), lambda x: f"{x:.4f}")
    H.add("AMillageCutPct", 100 * (float(df["land_millage"].iloc[0]) / TY.combined_mills - 1),
          lambda x: f"{x:.1f}%")
    H.add("AMillageCutAbsPct", abs(100 * (float(df["land_millage"].iloc[0]) / TY.combined_mills - 1)),
          lambda x: f"{x:.1f}%")
    H.add("ADownTenPct", 100 * (b["tax_change_pct"] < -10).mean(), pct)
    H.add("AUpTenPct", 100 * (b["tax_change_pct"] > 10).mean(), pct)
    H.add("AMedianPct", b["tax_change_pct"].median(), lambda x: f"{x:.1f}%")

    vac = b[b["property_category"] == "Vacant Land"]
    H.add("AVacantMedianPct", vac["tax_change_pct"].median(), lambda x: f"{x:,.0f}%")
    H.add("AVacantNetM", vac["tax_change"].sum() / 1e6, usd_m)
    H.add("AVacantShareOfShift",
          100 * vac["tax_change"].clip(lower=0).sum() / b["tax_change"].clip(lower=0).sum(), pct)
    sfr = b[b["property_category"] == "Single Family Residential"]
    H.add("ASfrMedianPct", sfr["tax_change_pct"].median(), lambda x: f"{x:.1f}%")
    H.add("ASfrMedianAbsPct", abs(sfr["tax_change_pct"].median()), lambda x: f"{x:.1f}%")

    # Scenario B: the same base with the rate NOT rolled back.
    lev_b = b["norollback_new_tax"].sum()
    H.add("BLevyRisePct", 100 * (lev_b / b["current_tax"].sum() - 1), lambda x: f"{x:.1f}%")
    H.add("BLevyB", lev_b / 1e9, usd_b)

    # The Sec. 3(c) identity this reading breaks, and by how much. Measured on GROSS values
    # (LYCD land against OPA's own recorded building), since the identity the ordinance states
    # is about the assessment itself, not about what survives an exemption.
    nv = b[b["opa_gross_building"] > 0]
    over = (nv["lycd_land_value"] + nv["opa_gross_building"]) - nv["market_value"]
    H.add("AOvershootParcels", int((over > 1).sum()), num)
    H.add("AOvershootPct", 100 * (over > 1).mean(), pct)
    H.add("AOvershootB", over.clip(lower=0).sum() / 1e9, usd_b)
    H.add("AOvershootDenom", len(nv), num)
    return b


# --------------------------------------------------------------------------- #
# The ordinance's own tests (Sec. 3(b) uniformity, Sec. 3(e), Sec. 4)
# --------------------------------------------------------------------------- #
def land_psf(df, col):
    a = df["dor_area_sqft"].replace(0, np.nan)
    return df[col] / a


def uniformity_tests(df, H):
    """Sec. 3(b): the land component must not vary among similarly situated parcels on the
    basis of the presence, absence, or value of improvements. Sec. 4(c): test for systematic
    variation associated with improvement value and with abatement status.

    'Similarly situated' is operationalised as 'in the same OPA Geographic Market Area (L3)',
    the finest geography OPA itself uses -- the ordinance's own list (location, size, zoning)
    is not all available here, so this is the weakest form of the test, not the strongest.
    """
    d = df[(df["dor_area_sqft"] > 0) & (df["gma3"].notna()) & (df["institutional_exempt"] == 0)].copy()
    d["improved"] = d["opa_gross_building"] > 0
    # Three surfaces, not two. The raw LYCD column is what the method publishes on its own;
    # `alloc_land` is what the ordinance's re-split would actually certify, and the two differ
    # exactly where it matters for Sec. 3(b): a vacant parcel's re-split land is capped at its
    # own total, i.e. OPA's own vacant value, so the raw method's vacant leg never reaches the roll.
    SURFACES = [("OPA", "opa_gross_land"), ("LYCD", "lycd_land_value"), ("Resplit", "alloc_land")]
    # The sales-based surface, when its run exists (merged onto df in main()).
    if "sales_land" in d.columns:
        SURFACES += [("Sfive", "sales_land"), ("SfiveResplit", "sales_alloc_land")]
    for name, col in SURFACES:
        d[f"psf_{name}"] = land_psf(d, col)

    rows = []
    # (1) vacant vs improved land rate, within zone. The ordinance names this exact contrast.
    z = d.groupby("gma3").filter(lambda g: g["improved"].nunique() == 2 and len(g) >= 30)
    for name, _ in SURFACES:
        med = z.groupby(["gma3", "improved"])[f"psf_{name}"].median().unstack()
        r = (med[False] / med[True]).replace([np.inf, -np.inf], np.nan).dropna()
        rows.append({"surface": name, "test": "Vacant vs improved, same zone",
                     "n": len(r), "value": r.median()})
        H.add(f"Uni{name}VacantImprovedRatio", r.median(), ratio)
        H.add(f"Uni{name}VacantImprovedZones", len(r), num)

    # (2) abated vs non-abated land rate, within zone (Sec. 4(c) names abatement status).
    da = d[d["improved"]]
    z = da.groupby("gma3").filter(lambda g: g["abated"].nunique() == 2 and (g["abated"] == 1).sum() >= 10)
    for name, _ in SURFACES:
        med = z.groupby(["gma3", "abated"])[f"psf_{name}"].median().unstack()
        r = (med[1] / med[0]).replace([np.inf, -np.inf], np.nan).dropna()
        rows.append({"surface": name, "test": "Abated vs unabated, same zone",
                     "n": len(r), "value": r.median()})
        H.add(f"Uni{name}AbatedRatio", r.median(), ratio)

    # (3) The sharpest form of Sec. 3(b): among improved parcels in the same zone AND the same
    # lot-size band -- as close to "similarly situated" as this data supports -- does the land
    # component track the value of the building standing on it? It should not.
    da = da.copy()
    da["area_band"] = da.groupby("gma3")["dor_area_sqft"].transform(
        lambda s: pd.qcut(s, 4, labels=False, duplicates="drop"))
    cells = da.groupby(["gma3", "area_band"]).filter(lambda g: len(g) >= 30)
    for name, col in SURFACES:
        rho = cells.groupby(["gma3", "area_band"]).apply(
            lambda g: g[col].corr(g["opa_gross_building"], method="spearman"),
            include_groups=False).dropna()
        rows.append({"surface": name,
                     "test": "Land--building rank corr., same zone and lot band",
                     "n": len(rho), "value": rho.median()})
        H.add(f"Uni{name}BuildingCorr", rho.median(), lambda x: f"{x:.2f}")
    H.add("UniCells", int(cells.groupby(["gma3", "area_band"]).ngroups), num)

    tbl = pd.DataFrame(rows)
    pick = lambda s: tbl[tbl.surface == s]  # noqa: E731
    out = pd.DataFrame({
        "Test": pick("OPA")["test"].values,
        "Cells": [num(v) for v in pick("OPA")["n"].values],
        "OPA": [f"{v:.2f}" for v in pick("OPA")["value"].values],
        "LYCD, raw": [f"{v:.2f}" for v in pick("LYCD")["value"].values],
        "LYCD, re-split": [f"{v:.2f}" for v in pick("Resplit")["value"].values],
    })
    fmt = "X r r r r"
    if "Sfive" in set(tbl.surface):
        out["Sales, raw"] = [f"{v:.2f}" for v in pick("Sfive")["value"].values]
        out["Sales, re-split"] = [f"{v:.2f}" for v in pick("SfiveResplit")["value"].values]
        fmt = "X r r r r r r"
    save_table(TABLES / "uniformity.tex", out, col_format=fmt, escape=False)
    return d


def default_ratio_collapse(df, H):
    """Sec. 3(e) forbids deriving the land component as a fixed percentage of total value.
    OPA's own roll shows the practice directly: a large share of improved parcels sit at
    exactly a 0.20 land-to-total ratio."""
    d = df[(df["opa_gross_building"] > 0) & (df["market_value"] > 0)]
    r_opa = (d["opa_gross_land"] / d["market_value"]).round(4)
    r_lycd = (d["alloc_land"] / d["market_value"]).round(4)
    # Abated parcels specifically: if most of them also sit at 0.20, the premium OPA gives
    # their land over their neighbours' is the 80/20 rule applied to an expensive new
    # building, not evidence about the lot.
    ab = d[d["abated"] == 1]
    H.add("AbatedAtDefaultPct",
          100 * (ab["opa_gross_land"] / ab["market_value"]).round(4).between(0.1995, 0.2005).mean(), pct)
    at20_opa = 100 * r_opa.between(0.1995, 0.2005).mean()
    at20_lycd = 100 * r_lycd.between(0.1995, 0.2005).mean()
    H.add("DefaultRatioOpaPct", at20_opa, pct)
    H.add("DefaultRatioLycdPct", at20_lycd, pct)
    if "sales_alloc_land" in d.columns:
        r_sales = (d["sales_alloc_land"] / d["market_value"]).round(4)
        H.add("DefaultRatioSfivePct", 100 * r_sales.between(0.1995, 0.2005).mean(), pct)
        H.add("SfiveResplitLandShareMedian", r_sales.median(), lambda x: f"{x:.2f}")
    H.add("DefaultRatioImprovedParcels", len(d), num)
    H.add("ImprovedSharePct", 100 * len(d) / len(df), pct)
    # The modal bin width matters for the claim: report the top mode of each surface.
    H.add("DefaultRatioOpaMode", r_opa.mode().iloc[0], lambda x: f"{x:.2f}")
    return r_opa, r_lycd


def sales_test(rat, H):
    """Sec. 3(b) accuracy and Sec. 4(b)(.1): compare each surface's land values to sales of
    vacant land. The sales-implied k inverts the aggregate ratio: LYCD's vacant leg is linear
    in k, so a surface running 1.80x aggregate is consistent with k = 1/1.80."""
    cut = rat[rat["sample"].str.startswith("bare land")].iloc[0]
    H.add("SalesN", int(cut["n"]), num)
    for s in ("OPA", "LYCD"):
        H.add(f"Sales{s}Median", cut[f"{s} median"], ratio)
        H.add(f"Sales{s}Agg", cut[f"{s} aggregate"], ratio)
        H.add(f"Sales{s}Cod", cut[f"{s} COD"], lambda x: f"{x:.0f}")
        H.add(f"Sales{s}Prd", cut[f"{s} PRD"], lambda x: f"{x:.2f}")
    H.add("IaaoCod", IAAO_COD, lambda x: f"{x:.0f}")
    H.add("SalesLycdCodVsIaao", cut["LYCD COD"] / IAAO_COD, ratio)
    H.add("SalesImpliedKAgg", LYCD_K_VACANT / cut["LYCD aggregate"], lambda x: f"{x:.2f}")
    H.add("SalesImpliedKMedian", LYCD_K_VACANT / cut["LYCD median"], lambda x: f"{x:.2f}")
    H.add("LycdKVacant", LYCD_K_VACANT, lambda x: f"{x:.2f}")
    H.add("LycdKImproved", LYCD_K_IMPROVED, lambda x: f"{x:.2f}")

    # Eight columns is the limit of what the text width takes; short labels and headers keep the
    # X column from being starved into a one-word-per-line ribbon (it was, on first render).
    labels = {"all vacant-category sales": "All vacant sales",
              "genuinely bare land": "Bare land",
              "bare land, sale >= $20k": "Bare land, sale $\\geq$ \\$20k"}
    out = pd.DataFrame({
        "Sample": rat["sample"].map(lambda s: labels.get(s, latex_escape(s))),
        "n": rat["n"].map(num),
        "OPA med.": rat["OPA median"].map(lambda x: f"{x:.2f}"),
        "OPA COD": rat["OPA COD"].map(lambda x: f"{x:.0f}"),
        "OPA agg.": rat["OPA aggregate"].map(lambda x: f"{x:.2f}"),
        "LYCD med.": rat["LYCD median"].map(lambda x: f"{x:.2f}"),
        "LYCD COD": rat["LYCD COD"].map(lambda x: f"{x:.0f}"),
        "LYCD agg.": rat["LYCD aggregate"].map(lambda x: f"{x:.2f}"),
    })
    save_table(TABLES / "vacant_ratio.tex", out, col_format="X r r r r r r r", escape=False)


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def table_scenarios(df, b, moved, H):
    """The three readings of 'LYCD land, rates alone', side by side."""
    lev = df["current_tax"].sum()
    rows = [
        {"Reading": "A. Revaluation, rate rolled back",
         "Held fixed": "OPA building; the levy",
         "Bills that move": num(len(b)) + " (all)",
         "Levy": "unchanged"},
        {"Reading": "B. Revaluation, rate unchanged",
         "Held fixed": "OPA building; the rate",
         "Bills that move": num(len(b)) + " (all)",
         "Levy": f"+{100 * (b['norollback_new_tax'].sum() / lev - 1):.1f}\\%"},
        {"Reading": "C. Re-split within total, rate unchanged",
         "Held fixed": "OPA total; the rate",
         "Bills that move": num(int(moved.sum())) + f" ({100 * moved.mean():.1f}\\%)",
         "Levy": f"{100 * b['alloc_tax_change'].sum() / lev:.2f}\\%"},
    ]
    save_table(TABLES / "scenarios.tex", pd.DataFrame(rows), col_format="X l r r", escape=False)


def table_fiscal_note(b, H):
    """Scenario C by exemption kind: the fiscal note the drafting notes ask for."""
    labels = {"none": "No exemption", "homestead": "Homestead only",
              "building_share": "Abatement (relief on the improvement)",
              "total_share": "Partial relief on total value", "full": "Fully exempt"}
    g = b.groupby("exemption_kind")
    out = pd.DataFrame({
        "Parcels": g.size(),
        "Bills moved": g["alloc_tax_change"].apply(lambda s: int((s.abs() > 0.01).sum())),
        "Net change": g["alloc_tax_change"].sum(),
        "Median change": g.apply(lambda x: x.loc[x["alloc_tax_change"].abs() > 0.01,
                                                 "alloc_tax_change"].median(), include_groups=False),
    })
    out = out.reindex([k for k in ["none", "homestead", "building_share", "total_share", "full"]
                       if k in out.index])
    disp = pd.DataFrame({
        "Exemption": [labels[i] for i in out.index],
        "Parcels": out["Parcels"].map(num),
        "Bills moved": out["Bills moved"].map(num),
        "Net change": out["Net change"].map(lambda x: tex_usd(x) if abs(x) > 0.5 else "---"),
        "Median move": out["Median change"].map(lambda x: tex_usd(x) if pd.notna(x) else "---"),
    })
    save_table(TABLES / "fiscal_note.tex", disp, col_format="X r r r r", escape=False)


def table_movers(b, moved, H):
    """Scenario C: which property types the abatement effect actually lands on."""
    mv = b[moved]
    g = mv.groupby("property_category")
    out = pd.DataFrame({
        "n": g.size(),
        "net": g["alloc_tax_change"].sum(),
        "med": g["alloc_tax_change"].median(),
        "medpct": g["alloc_tax_change_pct"].median(),
        "landratio": g.apply(lambda x: (x["lycd_land_value"] /
                                        x["opa_gross_land"].replace(0, np.nan)).median(),
                             include_groups=False),
    }).sort_values("n", ascending=False)
    out = out[out["n"] >= 10]
    disp = pd.DataFrame({
        "Property type": [latex_escape(i) for i in out.index],
        "Bills moved": out["n"].map(num),
        "Net change": out["net"].map(tex_usd),
        "Median": out["med"].map(tex_usd),
        "Median \\%": out["medpct"].map(lambda x: f"{x:.1f}\\%"),
        "LYCD/OPA land": out["landratio"].map(lambda x: f"{x:.2f}"),
    })
    save_table(TABLES / "movers_category.tex", disp, col_format="X r r r r r", escape=False)


def table_revaluation(b, H):
    """Scenario A by category -- what the revaluation reading does, for contrast."""
    g = b.groupby("property_category")
    out = pd.DataFrame({
        "n": g.size(),
        "win": g["tax_change"].apply(lambda s: 100 * (s < 0).mean()),
        "medpct": g["tax_change_pct"].median(),
        "net": g["tax_change"].sum(),
    })
    out = out.reindex([c for c in CAT_ORDER if c in out.index])
    disp = pd.DataFrame({
        "Property type": [latex_escape(i) for i in out.index],
        "Parcels": out["n"].map(num),
        "Pay less": out["win"].map(lambda x: f"{x:.0f}\\%"),
        "Median change": out["medpct"].map(lambda x: f"{x:+,.1f}\\%"),
        "Net change": out["net"].map(lambda x: tex_usd_m(x / 1e6)),
    })
    save_table(TABLES / "revaluation_category.tex", disp, col_format="X r r r r", escape=False)


def table_equity(b, H):
    """Scenario A stratified by income, value and racial composition, with bootstrap CIs."""
    eq = reassessment_equity(b, value_col="market_value", n_boot=200, random_state=0)
    frames = []
    for key, label in (("by_income_quintile", "Income quintile"),
                       ("by_minority_band", "Non-white share")):
        t = eq[key]
        if not len(t):
            continue
        grp = t.columns[0]
        frames.append(pd.DataFrame({
            # Minority bands read "0-10%": the % must be escaped or LaTeX comments out the row.
            "Stratum": [f"{label}: {latex_escape(v)}" for v in t[grp]],
            "Parcels": t["n"].map(num),
            "Pay less": t["pct_winners"].map(lambda x: f"{x:.1f}\\%"),
            "95\\% CI": [f"{lo:.1f}--{hi:.1f}" for lo, hi in
                         zip(t["pct_winners_lo"], t["pct_winners_hi"])],
            "Median change": t["median_change_pct"].map(lambda x: f"{x:+,.1f}\\%"),
        }))
    save_table(TABLES / "equity.tex", pd.concat(frames, ignore_index=True),
               col_format="X r r r r", escape=False)

    inc = eq["by_income_quintile"]
    H.add("AEquityQOneWin", inc["pct_winners"].iloc[0], pct)
    H.add("AEquityQFiveWin", inc["pct_winners"].iloc[-1], pct)
    val = eq["by_value_decile"]
    H.add("AEquityDOneWin", val["pct_winners"].iloc[0], pct)
    H.add("AEquityDOneMedian", val["median_change_pct"].iloc[0], lambda x: f"{x:,.1f}%")
    H.add("AEquityDTenWin", val["pct_winners"].iloc[-1], pct)
    return eq


# --------------------------------------------------------------------------- #
# Who a land tax would fall on, by land surface
# --------------------------------------------------------------------------- #
# Read from scripts/philadelphia_equity_by_land_surface.py's outputs. Strata are block-group
# quintiles of median household income and non-white share over taxable homes; every figure is
# an aggregate change (sum of new bills over sum of current) for the group.
EQ_SURFACES = [  # (label in the equity CSVs, macro key, display name)
    ("OPA land", "Opa", "OPA"),
    ("LYCD land", "Lycd", "LYCD allocation"),
    ("S2 kNN (k=20)", "Stwo", "Interpolation"),
    ("S5 paired-sales (certified)", "Sfive", "Paired sales"),
    ("E-GBM (most accurate)", "Egbm", "Boosted trees"),
]
EQ_TREATMENTS = [  # (label in the CSVs, macro key, display name)
    ("ends", "Ends", "Reform taxes abated buildings"),
    ("kept", "Kept", "Reform keeps the abatement"),
    ("expired", "Expired", "Abatements already expired"),
]
EQ_GROUPS = [  # (stratum, level, macro key, display name)
    ("inc_q", "Q1 (poorest)", "Poor", "Poorest"),
    ("inc_q", "Q5 (richest)", "Rich", "Richest"),
    ("min_q", "Q1 (whitest)", "White", "Whitest"),
    ("min_q", "Q5 (most non-white)", "Nonwhite", "Most non-white"),
]


def load_equity():
    names = ["strata", "summary", "bg_corr", "knn", "edges"]
    paths = {n: DATA / f"philadelphia_equity_by_surface_{n}.csv" for n in names}
    missing = [p.name for p in paths.values() if not p.exists()]
    if missing:
        print(f"  [warn] equity inputs missing ({missing}); run scripts/philadelphia_equity_by_land_surface.py")
        return None
    return {n: pd.read_csv(p) for n, p in paths.items()}


def _eq_cell(st, surface, treatment, stratum, level, col):
    r = st[(st.surface == surface) & (st.treatment == treatment) & (st.stratum == stratum) & (st.level == level)]
    assert len(r) == 1, (surface, treatment, stratum, level)
    return float(r[col].iloc[0])


def signed_pct(x):
    return f"{x:+.1f}%"


def equity_section(eq, H):
    st, corr, knn, edges = eq["strata"], eq["bg_corr"], eq["knn"], eq["edges"]

    # Quintile boundaries, for the method paragraph.
    e = edges.set_index("quantile")
    H.add("EqIncPoorTop", e.loc[0.2, "median_income"], money)
    H.add("EqIncRichBottom", e.loc[0.8, "median_income"], money)
    H.add("EqNonwhiteWhiteTop", e.loc[0.2, "nonwhite_pct"], lambda x: f"{x:.0f}%")
    H.add("EqNonwhiteMostBottom", e.loc[0.8, "nonwhite_pct"], lambda x: f"{x:.0f}%")

    # Every surface x treatment: homes and all-parcel change for the four end groups, and the
    # lowest share of homes paying less in any income, race or Black-share group.
    stable = 0
    for s_lab, s_key, _ in EQ_SURFACES:
        signs = set()
        for t_lab, t_key, _ in EQ_TREATMENTS:
            vals = {}
            for stratum, level, g_key, _ in EQ_GROUPS:
                vals[g_key] = _eq_cell(st, s_lab, t_lab, stratum, level, "homes_pct")
                H.add(f"Eq{s_key}{t_key}Homes{g_key}", vals[g_key], signed_pct)
                H.add(f"Eq{s_key}{t_key}All{g_key}", _eq_cell(st, s_lab, t_lab, stratum, level, "all_pct"), signed_pct)
            sub = st[(st.surface == s_lab) & (st.treatment == t_lab)]
            H.add(f"Eq{s_key}{t_key}MinWin", sub["homes_win_pct"].min(), lambda x: f"{x:.0f}%")
            signs.add((np.sign(vals["Rich"] - vals["Poor"]), np.sign(vals["Nonwhite"] - vals["White"])))
        stable += len(signs) == 1
    # The OPA and LYCD rows come from the split-rate notebooks, the sales-based rows from the
    # reassessment notebook's exemption rule. LYCD run through both says whether that matters.
    diffs = [abs(_eq_cell(st, "LYCD land", "ends", stratum, level, col)
                 - _eq_cell(st, "LYCD land, reassessment rules", "ends", stratum, level, col))
             for stratum, level, _, _ in EQ_GROUPS for col in ("homes_pct", "all_pct")]
    H.add("EqLycdRulesMaxDiff", max(diffs), lambda x: f"{x:.1f}")
    # Report.tex states the orderings hold on every surface under every treatment; make that
    # claim fail loudly rather than go stale.
    assert stable == len(EQ_SURFACES), (
        f"the richest-poorest or whitest-most-non-white ordering flips with the abatement treatment "
        f"on {len(EQ_SURFACES) - stable} surface(s); revise sec:equity and the abstract")
    H.add("EqSurfaces", len(EQ_SURFACES), num)

    # The certified surface's decomposition: flat-rate revaluation, then the split rate on top.
    for s_lab, s_key in (("S5 paired-sales (certified)", "Sfive"), ("E-GBM (most accurate)", "Egbm")):
        for t_lab, t_key in (("revaluation only", "Reval"), ("split-rate increment", "Split")):
            for stratum, level, g_key, _ in EQ_GROUPS:
                H.add(f"Eq{s_key}{t_key}Homes{g_key}", _eq_cell(st, s_lab, t_lab, stratum, level, "homes_pct"),
                      signed_pct)

    # What drives the all-parcel change: vacant land's contribution, in points of the group's bill.
    for s_lab, s_key in (("LYCD land", "Lycd"), ("S5 paired-sales (certified)", "Sfive")):
        for stratum, level, g_key, _ in EQ_GROUPS:
            H.add(f"Eq{s_key}Vacant{g_key}",
                  _eq_cell(st, s_lab, "ends", stratum, level, "contrib_vacant land"), lambda x: f"{x:+.0f}")

    # Block-group correlations of the homes change with income and non-white share.
    c = corr[(corr.treatment == "ends") & (corr.scope == "homes")].set_index("surface")
    for s_lab, s_key, _ in EQ_SURFACES:
        H.add(f"Eq{s_key}RInc", c.loc[s_lab, "r_log_income"], lambda x: f"{x:+.2f}")
        H.add(f"Eq{s_key}RNonwhite", c.loc[s_lab, "r_nonwhite"], lambda x: f"{x:+.2f}")
    H.add("EqBlockGroups", int(c["n_block_groups"].iloc[0]), num)

    # Parcels KNN-filled outside the AVM universe: how much of any group, and how much they move it.
    H.add("EqKnnMaxSharePct", knn["knn_share_pct"].max(), pct)
    H.add("EqKnnMaxShift", (knn["homes_pct"] - knn["homes_pct_without_knn"]).abs().max(), lambda x: f"{x:.1f}")

    # Table: the five surfaces under the standard treatment, homes and all taxable parcels.
    def panel(col):
        out = []
        for s_lab, _, s_name in EQ_SURFACES:
            cells = [f"{_eq_cell(st, s_lab, 'ends', stratum, level, col):+.1f}\\%"
                     for stratum, level, _, _ in EQ_GROUPS]
            out.append(" & ".join([s_name] + cells) + r" \\")
        return out
    head = " & ".join(["Land values"] + [g[3] for g in EQ_GROUPS]) + r" \\"
    lines = [r"\begin{tabularx}{\linewidth}{@{} X r r r r @{}}", r"\toprule",
             r" & \multicolumn{2}{c}{Income} & \multicolumn{2}{c}{Non-white share} \\",
             r"\cmidrule(lr){2-3}\cmidrule(l){4-5}", head, r"\midrule",
             r"\multicolumn{5}{@{}l}{\emph{Homes}} \\"] + panel("homes_pct") + \
            [r"\midrule", r"\multicolumn{5}{@{}l}{\emph{All taxable parcels}} \\"] + panel("all_pct") + \
            [r"\bottomrule", r"\end{tabularx}"]
    (TABLES / "equity_surfaces.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Table: every surface under every abatement treatment, homes only, plus the lowest win rate.
    head = " & ".join(["Abatement treatment"] + [g[3] for g in EQ_GROUPS] + ["Lowest share paying less"]) + r" \\"
    lines = [r"\begin{tabularx}{\linewidth}{@{} X r r r r r @{}}", r"\toprule", head]
    for s_lab, _, s_name in EQ_SURFACES:
        lines += [r"\midrule", rf"\multicolumn{{6}}{{@{{}}l}}{{\emph{{{s_name}}}}} \\"]
        for t_lab, _, t_name in EQ_TREATMENTS:
            cells = [f"{_eq_cell(st, s_lab, t_lab, stratum, level, 'homes_pct'):+.1f}\\%"
                     for stratum, level, _, _ in EQ_GROUPS]
            win = st[(st.surface == s_lab) & (st.treatment == t_lab)]["homes_win_pct"].min()
            lines.append(" & ".join([t_name] + cells + [f"{win:.0f}\\%"]) + r" \\")
    lines += [r"\bottomrule", r"\end{tabularx}"]
    (TABLES / "equity_abatement.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    fig_equity_profile(st)


def fig_equity_profile(st):
    """Homes' aggregate change across all five income and non-white-share quintiles, by surface."""
    colours = {"Opa": PPI_COLORS["primary"], "Lycd": PPI_COLORS["gray"], "Stwo": PPI_COLORS["light"],
               "Sfive": PPI_COLORS["accent"], "Egbm": PPI_COLORS["dark"]}
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3), sharey=True)
    panels = ((axes[0], "inc_q", ["Q1 (poorest)", "Q2", "Q3", "Q4", "Q5 (richest)"],
               ["poorest", "2", "3", "4", "richest"], "block-group income quintile"),
              (axes[1], "min_q", ["Q1 (whitest)", "Q2", "Q3", "Q4", "Q5 (most non-white)"],
               ["whitest", "2", "3", "4", "most\nnon-white"], "block-group non-white-share quintile"))
    for ax, stratum, levels, ticks, xlabel in panels:
        for s_lab, s_key, s_name in EQ_SURFACES:
            y = [_eq_cell(st, s_lab, "ends", stratum, lv, "homes_pct") for lv in levels]
            lw = 2.2 if s_key == "Sfive" else 1.3
            ax.plot(range(5), y, marker="o", ms=3.5, lw=lw, color=colours[s_key], label=s_name)
        ax.axhline(0, color=PPI_COLORS["dark"], lw=0.6)
        ax.set_xticks(range(5))
        ax.set_xticklabels(ticks, fontsize=8)
        ax.set_xlabel(xlabel)
    axes[0].set_ylabel("change in homes' total bill (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=8, frameon=False, loc="lower center", ncol=len(EQ_SURFACES),
               bbox_to_anchor=(0.5, -0.06))
    fig.tight_layout()
    fig.savefig(FIGS / "equity_profile.pdf")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def fig_scenario_compare(b):
    """The whole argument in one picture: how many bills each reading moves, and how far."""
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), sharey=True)
    bins = np.linspace(-SCENARIO_HIST_CLIP, SCENARIO_HIST_CLIP, 121)
    for ax, col, title, colour in (
        (axes[0], "tax_change_pct", "A. Revaluation, rate rolled back", PPI_COLORS["primary"]),
        (axes[1], "alloc_tax_change_pct", "C. Re-split within total, rate unchanged",
         PPI_COLORS["accent"]),
    ):
        ax.hist(b[col].clip(-SCENARIO_HIST_CLIP, SCENARIO_HIST_CLIP).dropna(), bins=bins, color=colour)
        ax.axvline(0, color=PPI_COLORS["dark"], lw=0.8)
        ax.set_title(title, fontsize=9)
        # matplotlib renders these labels itself -- no LaTeX backend, so "\%" would print a
        # literal backslash. Mathtext ($...$) does work.
        ax.set_xlabel("change in the annual bill (%), clipped at $\\pm$60")
    axes[0].set_ylabel("parcels")
    axes[0].set_yscale("log")
    fig.tight_layout()
    fig.savefig(FIGS / "scenario_compare.pdf")
    plt.close(fig)


def _tract_frame(b, value_cols):
    t = b.dropna(subset=["std_geoid"]).copy()
    t["tract_geoid"] = t["std_geoid"].astype(str).str.zfill(12).str[:11]
    return t.groupby("tract_geoid").agg(value_cols)


def fig_maps(b):
    """Where each reading lands. A spatial design needs a map, not only tables."""
    try:
        import geopandas as gpd
    except ImportError:
        print("  [warn] geopandas unavailable; skipping maps")
        return
    geo = gpd.read_parquet(CITY_DATA / "census_tracts.gpq")
    geo["tract_geoid"] = geo["GEOID"].astype(str)

    agg = _tract_frame(b, {"tax_change_pct": "median", "alloc_tax_change": "sum",
                           "alloc_tax_change_pct": "median"})
    g = geo.merge(agg, on="tract_geoid", how="inner")

    fig, axes = plt.subplots(1, 2, figsize=(7.4, 4.6))
    g.plot(column=g["tax_change_pct"].clip(-MAP_PCT_CLIP, MAP_PCT_CLIP), cmap="RdBu_r",
           vmin=-MAP_PCT_CLIP, vmax=MAP_PCT_CLIP, linewidth=0.1, edgecolor="white", ax=axes[0],
           legend=True, legend_kwds={"label": "median change in bill (%)",
                                     "orientation": "horizontal", "shrink": 0.8, "pad": 0.02,
                                     "extend": "both"})
    axes[0].set_title("A. Revaluation, rate rolled back", fontsize=9)

    v = g["alloc_tax_change"] / 1000.0
    lim = float(np.nanpercentile(v.abs(), 98)) or 1.0
    g.plot(column=v.clip(-lim, lim), cmap="RdBu_r", vmin=-lim, vmax=lim, linewidth=0.1,
           edgecolor="white", ax=axes[1], legend=True,
           legend_kwds={"label": "net change in tract bills (\\$000)",
                        "orientation": "horizontal", "shrink": 0.8, "pad": 0.02, "extend": "both"})
    axes[1].set_title("C. Re-split within total, rate unchanged", fontsize=9)
    for ax in axes:
        ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(FIGS / "scenario_maps.pdf")
    plt.close(fig)


def fig_uniformity(d):
    """Sec. 3(b)'s own contrast: does the land rate depend on what is built on the lot?"""
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.4), sharey=True)
    for ax, col, title in ((axes[0], "psf_OPA", "OPA land values"),
                           (axes[1], "psf_LYCD", "LYCD land values, raw")):
        parts = [d.loc[~d["improved"], col].dropna(), d.loc[d["improved"], col].dropna()]
        parts = [p[(p > 0) & (p < np.nanpercentile(p, 99))] for p in parts]
        ax.boxplot([np.log10(p) for p in parts], tick_labels=["vacant", "improved"],
                   showfliers=False,
                   medianprops={"color": PPI_COLORS["accent"], "linewidth": 1.6},
                   boxprops={"color": PPI_COLORS["dark"]},
                   whiskerprops={"color": PPI_COLORS["dark"]},
                   capprops={"color": PPI_COLORS["dark"]})
        ax.set_title(title, fontsize=9)
        ax.set_xlabel("improvements on the lot")
    axes[0].set_ylabel("land value per sq ft ($\\log_{10}$ \\$)")
    fig.tight_layout()
    fig.savefig(FIGS / "uniformity.pdf")
    plt.close(fig)


def fig_sales(rat):
    """Both surfaces against vacant-land sale prices, on the same axis as the IAAO target."""
    cuts = rat["sample"].tolist()
    x = np.arange(len(cuts))
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2))
    w = 0.36
    axes[0].bar(x - w / 2, rat["OPA aggregate"], w, label="OPA", color=PPI_COLORS["primary"])
    axes[0].bar(x + w / 2, rat["LYCD aggregate"], w, label="LYCD", color=PPI_COLORS["accent"])
    axes[0].axhline(1.0, color=PPI_COLORS["dark"], lw=1.0, ls="--")
    axes[0].set_ylabel("assessed land $\\div$ sale price (aggregate)")
    axes[0].legend(fontsize=8, frameon=False)

    axes[1].bar(x - w / 2, rat["OPA COD"], w, color=PPI_COLORS["primary"])
    axes[1].bar(x + w / 2, rat["LYCD COD"], w, color=PPI_COLORS["accent"])
    axes[1].axhline(IAAO_COD, color=PPI_COLORS["dark"], lw=1.0, ls="--")
    axes[1].annotate("IAAO limit", (len(cuts) - 0.5, IAAO_COD + 3), fontsize=7,
                     ha="right", color=PPI_COLORS["dark"])
    axes[1].set_ylabel("coefficient of dispersion")
    labels = ["all vacant\nsales", "genuinely\nbare land", "bare land\n$\\geq$\\$20k"]
    for ax in axes:
        ax.set_xticks(x)
        ax.set_xticklabels(labels[:len(cuts)], fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGS / "sales_test.pdf")
    plt.close(fig)


def fig_default_ratio(r_opa, r_lycd):
    """Sec. 3(e)'s target, visible in the roll: OPA's land-to-total ratio piles up at 0.20."""
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    bins = np.linspace(0, RATIO_HIST_CLIP, 121)
    ax.hist(r_opa.clip(0, RATIO_HIST_CLIP), bins=bins, color=PPI_COLORS["primary"], alpha=0.85,
            label="OPA land $\\div$ total")
    ax.hist(r_lycd.clip(0, RATIO_HIST_CLIP), bins=bins, color=PPI_COLORS["accent"], alpha=0.7,
            label="LYCD land $\\div$ total")
    ax.set_xlabel("land as a share of total assessed value (improved parcels)")
    ax.set_ylabel("parcels")
    # Log scale: the spike at exactly 0.20 is two orders of magnitude above everything else and
    # would otherwise flatten the rest of both distributions to the axis.
    ax.set_yscale("log")
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(FIGS / "default_ratio.pdf")
    plt.close(fig)


# --------------------------------------------------------------------------- #
def main():
    df, rat, met = load()
    H = Headlines(prefix=PREFIX, out_path=TABLES / "headlines.tex")
    sales = load_sales()
    if sales is not None:
        cols = sales["export"][["parcel_id", "lycd_land_value", "alloc_land"]].rename(
            columns={"lycd_land_value": "sales_land", "alloc_land": "sales_alloc_land"})
        df = df.merge(cols, on="parcel_id", how="left")
    eq = load_equity()

    b, moved = scenario_c(df, H)
    scenario_a(df, H)
    d = uniformity_tests(df, H)
    if sales is not None:
        sales_section(df, sales, H)
    if eq is not None:
        equity_section(eq, H)
    r_opa, r_lycd = default_ratio_collapse(df, H)
    sales_test(rat, H)

    table_scenarios(df, b, moved, H)
    table_fiscal_note(b, H)
    table_movers(b, moved, H)
    table_revaluation(b, H)
    table_equity(b, H)

    fig_scenario_compare(b)
    fig_maps(b)
    fig_uniformity(d)
    fig_sales(rat)
    fig_default_ratio(r_opa, r_lycd)

    H.add("TaxYear", TAX_YEAR, lambda x: f"{x:.0f}")
    H.add("MapPctClip", MAP_PCT_CLIP, lambda x: f"{x:.0f}")
    H.add("RatioHistClip", RATIO_HIST_CLIP, lambda x: f"{x:.1f}")
    H.add("ScenarioHistClip", SCENARIO_HIST_CLIP, lambda x: f"{x:.0f}")
    H.write()
    H.to_json(PAPER / "values.json")
    print(f"wrote {TABLES / 'headlines.tex'}")
    for p in sorted(TABLES.glob("*.tex")) + sorted(FIGS.glob("*.pdf")):
        print(f"  {p.relative_to(PAPER)}")


if __name__ == "__main__":
    main()
