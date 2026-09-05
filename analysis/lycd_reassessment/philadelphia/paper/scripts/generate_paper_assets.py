"""Generate every figure, table, and headline macro for the report.

SINGLE SOURCE OF NUMERICAL CONTENT for paper/Report.tex. Re-run after any data change:

    C:/Users/druss/miniconda3/python.exe analysis/lycd_reassessment/philadelphia/paper/scripts/generate_paper_assets.py

Then rebuild the PDF. Never type a result number into Report.tex -- add it here as a macro,
regenerate, and reference the macro.

Reads (all produced by cities/philadelphia/model_lycd_reassessment.ipynb except the ratio
study, which scripts/vacant_land_ratio_study.py writes, and the tract geometry):

    analysis/data/philadelphia_lycd_reassessment_ty2026.csv          per-parcel, both scenarios
    analysis/data/philadelphia_vacant_land_ratio_study_ty2026.csv    sales test of both surfaces
    analysis/reports/philadelphia_lycd_reassessment_ty2026/metrics_*.csv
    cities/philadelphia/data/census_tracts.gpq                       map geometry
"""
from __future__ import annotations

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

# IAAO Standard on Ratio Studies, table 1-3: COD <= 20 for a heterogeneous class, PRD 0.98-1.03.
IAAO_COD = 20.0
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
# The sales-based surface (Phase 2 of the second analysis)
# --------------------------------------------------------------------------- #
# philly_open_avmkit owns the land evidence and the held-out scoring; LVTShift reads its
# outputs read-only (never the reverse). The S2 export is this notebook re-run with
# LVT_LAND_SURFACE=s2_k20, so every tax-side number for S2 comes through the same code path
# as LYCD's and differs only in the land rate.
PHILLY_LAND = Path(r"C:\projects\philly_open_avmkit\notebooks\pipeline\data\us-pa-philadelphia\out\land")
S2_SLUG = f"{SLUG}_s2_k20"
S2_COLS = ["parcel_id", "lycd_land_value", "alloc_land", "alloc_tax_change", "alloc_tax_change_pct",
           "tax_change", "tax_change_pct", "current_tax", "land_millage", "land_surface_source",
           "land_surface_psf", "lycd_land_value_lycd", "opa_gross_land", "opa_gross_building",
           "market_value", "institutional_exempt", "property_category", "exemption_kind",
           "std_geoid", "dor_area_sqft", "abated", "area_source"]


def load_s2():
    """The S2 run of the notebook plus the sibling repo's evidence and scores, or None."""
    p = DATA / f"{S2_SLUG}.csv"
    if not p.exists() or not (PHILLY_LAND / "scores.csv").exists():
        print(f"  [warn] S2 inputs missing ({p.name} or philly scores.csv); S2 section skipped")
        return None
    s2 = pd.read_csv(p, usecols=S2_COLS, dtype={"parcel_id": str, "std_geoid": str})
    return {
        "export": s2,
        "witnesses": pd.read_csv(PHILLY_LAND / "witnesses.csv"),
        "scores": pd.read_csv(PHILLY_LAND / "scores.csv"),
        "h2h": pd.read_csv(PHILLY_LAND / "head_to_head.csv"),
    }


def s2_section(df, s2, H):
    """Macros, tables and the figure for the sales-based surface."""
    w, sc, h2h, ex = s2["witnesses"], s2["scores"], s2["h2h"], s2["export"]

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
    keymap = {"S0 OPA assessed land": "Szero", "S1 LYCD zone-rate allocation": "Sone",
              "S2 kNN interpolation (k=20)": "Stwo", "S3 published schedule": "Sthree",
              "S4 Kolbe extraction (in-sample)": "Sfour"}
    for cand, nm in keymap.items():
        if cand in allw.index:
            r = allw.loc[cand]
            H.add(f"{nm}TrCod", r["tr_cod"], lambda x: f"{x:.0f}")
            H.add(f"{nm}RawCod", r["cod"], lambda x: f"{x:.0f}")
            H.add(f"{nm}TrMedian", r["tr_median"], lambda x: f"{x:.2f}")
            H.add(f"{nm}TrPrd", r["tr_prd"], lambda x: f"{x:.2f}")
    r2 = allw.loc["S2 kNN interpolation (k=20)"]
    H.add("StwoNetLo", r2["cod_net_lo"], lambda x: f"{x:.0f}")
    H.add("StwoNetHi", r2["cod_net_hi"], lambda x: f"{x:.0f}")
    r0 = allw.loc["S0 OPA assessed land"]
    H.add("SzeroNetLo", r0["cod_net_lo"], lambda x: f"{x:.0f}")
    H.add("SzeroNetHi", r0["cod_net_hi"], lambda x: f"{x:.0f}")
    H.add("HeldoutN", int(r2["n"]), num)
    order = ["S0 OPA assessed land", "S1 LYCD zone-rate allocation", "S2 kNN interpolation (k=20)",
             "S3 published schedule", "S4 Kolbe extraction (in-sample)"]
    short = {"S0 OPA assessed land": "OPA assessed land",
             "S1 LYCD zone-rate allocation": "LYCD zone-rate allocation",
             "S2 kNN interpolation (k=20)": "Interpolation among land sales (k=20)",
             "S3 published schedule": "Published rate schedule",
             "S4 Kolbe extraction (in-sample)": "Kolbe extraction (in-sample)"}
    brief = {"S0 OPA assessed land": "OPA", "S1 LYCD zone-rate allocation": "LYCD allocation",
             "S2 kNN interpolation (k=20)": "Interpolation", "S3 published schedule": "Schedule",
             "S4 Kolbe extraction (in-sample)": "Kolbe"}
    rows = allw.loc[[c for c in order if c in allw.index]]
    tbl = pd.DataFrame({
        "Surface": [short[c] for c in rows.index],
        "Held out": ["yes" if h else "no" for h in rows["held_out"]],
        "n": rows["n"].map(num).values,
        "Median": rows["tr_median"].map(lambda x: f"{x:.2f}").values,
        "COD, trimmed": rows["tr_cod"].map(lambda x: f"{x:.0f}").values,
        "COD, raw": rows["cod"].map(lambda x: f"{x:.0f}").values,
        "PRD": rows["tr_prd"].map(lambda x: f"{x:.2f}").values,
    })
    save_table(TABLES / "heldout.tex", tbl, col_format="X l r r r r r", escape=False)

    # Per-stream COD for the surfaces that matter -- where does each one do its work?
    piv = sc.pivot_table(index="candidate", columns="subset", values="tr_cod")
    subsets = [s for s in ("W1 only", "W1b only", "W2 only") if s in piv.columns]
    rows = piv.loc[[c for c in order if c in piv.index], subsets]
    tbl = pd.DataFrame({"Surface": [short[c] for c in rows.index]})
    for s, lab in zip(subsets, ("Still vacant", "Since built on", "Teardown")):
        tbl[lab] = rows[s].map(lambda x: f"{x:.0f}" if np.isfinite(x) else "---").values
    save_table(TABLES / "heldout_by_stream.tex", tbl, col_format="X r r r", escape=False)
    for cand, nm in keymap.items():
        if cand in piv.index:
            for s, lab in zip(subsets, ("Wone", "Woneb", "Wtwo")):
                H.add(f"{nm}TrCod{lab}", piv.loc[cand, s], lambda x: f"{x:.0f}")

    # --- head to head -------------------------------------------------------------------
    hk = {("S2 kNN interpolation (k=20)", "S3 published schedule"): "StwoVsSthree",
          ("S2 kNN interpolation (k=20)", "S0 OPA assessed land"): "StwoVsSzero",
          ("S3 published schedule", "S0 OPA assessed land"): "SthreeVsSzero",
          ("S0 OPA assessed land", "S1 LYCD zone-rate allocation"): "SzeroVsSone"}
    rows = []
    for _, r in h2h.iterrows():
        nm = hk.get((r["a"], r["b"]))
        if nm is None:
            continue
        H.add(f"{nm}Diff", r["cod_diff"], lambda x: f"{x:+.1f}")
        H.add(f"{nm}DiffAbs", abs(r["cod_diff"]), lambda x: f"{x:.1f}")
        H.add(f"{nm}Lo", r["lo"], lambda x: f"{x:+.1f}")
        H.add(f"{nm}Hi", r["hi"], lambda x: f"{x:+.1f}")
        H.add(f"{nm}P", r["p_a_better"], lambda x: f"{x:.3f}")
        rows.append({"A": brief[r["a"]], "B": brief[r["b"]],
                     "COD difference": f"{r['cod_diff']:+.1f}",
                     "95\\% interval": f"[{r['lo']:+.1f}, {r['hi']:+.1f}]",
                     "P(A better)": f"{r['p_a_better']:.3f}"})
    save_table(TABLES / "head_to_head.tex", pd.DataFrame(rows), col_format="X X r r r", escape=False)

    # --- what S2 does to the roll ---------------------------------------------------------
    b = ex[(ex["institutional_exempt"] == 0) & (ex["current_tax"] > 0)]
    H.add("StwoKnnParcels", int(ex["land_surface_source"].eq("knn").sum()), num)
    H.add("StwoKnnValuePct",
          100 * ex.loc[ex["land_surface_source"].eq("knn"), "market_value"].sum() / ex["market_value"].sum(), pct)
    H.add("StwoLandBaseB", ex["lycd_land_value"].sum() / 1e9, usd_b)
    H.add("LycdLandBaseB", ex["lycd_land_value_lycd"].sum() / 1e9, usd_b)
    H.add("OpaLandBaseB", ex["opa_gross_land"].sum() / 1e9, usd_b)
    H.add("StwoOverOpaLand", ex["lycd_land_value"].sum() / ex["opa_gross_land"].sum(), ratio)
    H.add("StwoOverLycdLand", ex["lycd_land_value"].sum() / ex["lycd_land_value_lycd"].sum(), ratio)
    imp = ex[ex["opa_gross_building"] > 0].copy()
    share = imp["lycd_land_value"] / imp["market_value"].replace(0, np.nan)
    H.add("StwoImprovedLandShareMedian", share.median(), lambda x: f"{x:.2f}")
    # Sec. 3(c) on the sales-based surface: how often does land ALONE exceed OPA's total
    # assessment before the cap binds? Measured on the pre-cap value (rate x area), since the
    # exported land value is already capped. Split out the cohort whose lot area is itself
    # imputed (condominium units and other records with no lot of their own, which inherit a
    # neighbour's whole-lot area): their overshoot is the known area artifact, not evidence
    # about OPA's totals.
    imp["pre_cap"] = imp["land_surface_psf"] * imp["dor_area_sqft"]
    over = imp["pre_cap"] > imp["market_value"]
    condo_like = imp["area_source"].eq("knn")
    H.add("StwoPreCapExceeds", int(over.sum()), num)
    H.add("StwoPreCapExceedsPct", 100 * over.mean(), pct)
    H.add("StwoPreCapExceedsCondo", int((over & condo_like).sum()), num)
    H.add("StwoPreCapExceedsCore", int((over & ~condo_like).sum()), num)
    H.add("StwoPreCapExceedsCorePct", 100 * (over & ~condo_like).sum() / (~condo_like).sum(), pct)
    H.add("StwoCapRemovedB", (imp.loc[over, "pre_cap"] - imp.loc[over, "market_value"]).sum() / 1e9, usd_b)
    H.add("StwoCapRemovedCoreB",
          (imp.loc[over & ~condo_like, "pre_cap"] - imp.loc[over & ~condo_like, "market_value"]).sum() / 1e9, usd_b)
    H.add("StwoKnnFillPsf", ex.loc[ex["land_surface_source"].eq("knn"), "land_surface_psf"].median(), lambda x: f"${x:,.0f}")
    H.add("StwoJoinedPsf", ex.loc[ex["land_surface_source"].eq("surface"), "land_surface_psf"].median(), lambda x: f"${x:,.0f}")

    # reading C under S2
    moved = b["alloc_tax_change"].abs() > 0.01
    H.add("StwoCMoved", int(moved.sum()), num)
    H.add("StwoCMovedPct", 100 * moved.mean(), pct)
    lev = b["alloc_tax_change"].sum()
    H.add("StwoCLevyAbsM", abs(lev) / 1e6, lambda x: f"${x:,.1f}M")
    H.add("StwoCLevySign", "falls" if lev < 0 else "rises")
    H.add("StwoCLevyPct", 100 * lev / ex["current_tax"].sum(), lambda x: f"{x:+.2f}%")
    ab = b[moved & (b["abated"] == 1)]
    H.add("StwoCAbatedMedianPct", ab["alloc_tax_change_pct"].median(), lambda x: f"{x:+.1f}%")
    # reading A under S2
    H.add("StwoAMillage", float(ex["land_millage"].iloc[0]), lambda x: f"{x:.4f}")
    H.add("StwoADownTenPct", 100 * (b["tax_change_pct"] < -10).mean(), pct)
    H.add("StwoAUpTenPct", 100 * (b["tax_change_pct"] > 10).mean(), pct)
    vac = b[b["property_category"] == "Vacant Land"]
    H.add("StwoAVacantMedianPct", vac["tax_change_pct"].median(), lambda x: f"{x:+,.0f}%")
    H.add("StwoAVacantShareOfShift",
          100 * vac["tax_change"].clip(lower=0).sum() / b["tax_change"].clip(lower=0).sum(), pct)

    fig_s2(allw, order, short, ex)
    return ex


def fig_s2(allw, order, short, ex):
    """Left: held-out dispersion by surface. Right: where the sales-based surface departs
    from LYCD, by tract."""
    try:
        import geopandas as gpd
    except ImportError:
        gpd = None
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.9), gridspec_kw={"width_ratios": [1.0, 1.15]})
    rows = allw.loc[[c for c in order if c in allw.index]]
    labels = [short[c].replace(" (", "\n(") for c in rows.index]
    colours = [PPI_COLORS["accent"] if "Interpolation" in short[c] else PPI_COLORS["primary"]
               for c in rows.index]
    axes[0].barh(labels, rows["tr_cod"], color=colours)
    axes[0].axvline(IAAO_COD, color=PPI_COLORS["dark"], lw=1.0, ls="--")
    axes[0].annotate("IAAO", (IAAO_COD + 1, 0.55), fontsize=7, color=PPI_COLORS["dark"])
    axes[0].invert_yaxis()
    axes[0].set_xlabel("held-out COD, trimmed (lower is better)")
    axes[0].tick_params(axis="y", labelsize=7)

    if gpd is not None:
        geo = gpd.read_parquet(CITY_DATA / "census_tracts.gpq")
        geo["tract_geoid"] = geo["GEOID"].astype(str)
        t = ex.dropna(subset=["std_geoid"]).copy()
        t["tract_geoid"] = t["std_geoid"].astype(str).str.zfill(12).str[:11]
        agg = t.groupby("tract_geoid").agg(s2=("lycd_land_value", "sum"),
                                          lycd=("lycd_land_value_lycd", "sum"))
        agg["ratio"] = agg["s2"] / agg["lycd"].replace(0, np.nan)
        g = geo.merge(agg, on="tract_geoid", how="inner")
        g.plot(column=np.log2(g["ratio"].clip(0.25, 4.0)), cmap="RdBu_r", vmin=-2, vmax=2,
               linewidth=0.1, edgecolor="white", ax=axes[1], legend=True,
               legend_kwds={"label": "sales-based ÷ LYCD land (log2)",
                            "orientation": "horizontal", "shrink": 0.8, "pad": 0.02,
                            "extend": "both"})
        axes[1].set_axis_off()
    fig.tight_layout()
    fig.savefig(FIGS / "s2_surface.pdf")
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
    if "s2_land" in d.columns:
        SURFACES += [("Stwo", "s2_land"), ("StwoResplit", "s2_alloc_land")]
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
    if "Stwo" in set(tbl.surface):
        out["Sales, raw"] = [f"{v:.2f}" for v in pick("Stwo")["value"].values]
        out["Sales, re-split"] = [f"{v:.2f}" for v in pick("StwoResplit")["value"].values]
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
    if "s2_alloc_land" in d.columns:
        r_s2 = (d["s2_alloc_land"] / d["market_value"]).round(4)
        H.add("DefaultRatioStwoPct", 100 * r_s2.between(0.1995, 0.2005).mean(), pct)
        H.add("StwoResplitLandShareMedian", r_s2.median(), lambda x: f"{x:.2f}")
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
    s2 = load_s2()
    H.add("HasStwo", "yes" if s2 is not None else "no")
    if s2 is not None:
        cols = s2["export"][["parcel_id", "lycd_land_value", "alloc_land"]].rename(
            columns={"lycd_land_value": "s2_land", "alloc_land": "s2_alloc_land"})
        df = df.merge(cols, on="parcel_id", how="left")

    b, moved = scenario_c(df, H)
    scenario_a(df, H)
    d = uniformity_tests(df, H)
    if s2 is not None:
        s2_section(df, s2, H)
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
