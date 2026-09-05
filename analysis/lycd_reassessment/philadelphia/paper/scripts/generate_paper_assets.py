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
    H.add("CLevyPct", 100 * b["alloc_tax_change"].sum() / df["current_tax"].sum(),
          lambda x: f"{x:.2f}%")
    H.add("CMedianPct", mv["alloc_tax_change_pct"].median(), lambda x: f"{x:.1f}%")

    ab = mv[mv["abated"] == 1]
    H.add("CAbatedMoved", len(ab), num)
    H.add("CAbatedMedianPct", ab["alloc_tax_change_pct"].median(), lambda x: f"{x:.1f}%")
    H.add("CAbatedNetM", ab["alloc_tax_change"].sum() / 1e6, lambda x: f"-${abs(x):,.1f}M")
    lr = (ab["lycd_land_value"] / ab["opa_gross_land"].replace(0, np.nan)).median()
    H.add("CAbatedLandRatio", lr, ratio)

    # Everything that is NOT abatement-type relief is bit-for-bit unchanged -- the claim the
    # notebook asserts on every run.
    H.add("CUnchangedParcels", int((~moved).sum()), num)
    return b, moved


def scenario_a(df, H):
    """The revaluation reading: LYCD land added to OPA building, flat rate rolled back."""
    b = billed(df)
    H.add("AMillage", float(df["land_millage"].iloc[0]), lambda x: f"{x:.4f}")
    H.add("AMillageCutPct", 100 * (float(df["land_millage"].iloc[0]) / TY.combined_mills - 1),
          lambda x: f"{x:.1f}%")
    H.add("ADownTenPct", 100 * (b["tax_change_pct"] < -10).mean(), pct)
    H.add("AUpTenPct", 100 * (b["tax_change_pct"] > 10).mean(), pct)
    H.add("AMedianPct", b["tax_change_pct"].median(), lambda x: f"{x:.1f}%")

    vac = b[b["property_category"] == "Vacant Land"]
    H.add("AVacantMedianPct", vac["tax_change_pct"].median(), lambda x: f"+{x:,.0f}%")
    H.add("AVacantNetM", vac["tax_change"].sum() / 1e6, usd_m)
    H.add("AVacantShareOfShift",
          100 * vac["tax_change"].clip(lower=0).sum() / b["tax_change"].clip(lower=0).sum(), pct)
    sfr = b[b["property_category"] == "Single Family Residential"]
    H.add("ASfrMedianPct", sfr["tax_change_pct"].median(), lambda x: f"{x:.1f}%")

    # Scenario B: the same base with the rate NOT rolled back.
    lev_b = b["norollback_new_tax"].sum()
    H.add("BLevyRisePct", 100 * (lev_b / b["current_tax"].sum() - 1), lambda x: f"+{x:.1f}%")
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
    d["psf_opa"] = land_psf(d, "opa_gross_land")
    d["psf_lycd"] = land_psf(d, "lycd_land_value")

    rows = []
    # (1) vacant vs improved land rate, within zone. The ordinance names this exact contrast.
    for name, col in (("OPA", "psf_opa"), ("LYCD", "psf_lycd")):
        z = d.groupby("gma3").filter(lambda g: g["improved"].nunique() == 2 and len(g) >= 30)
        med = z.groupby(["gma3", "improved"])[col].median().unstack()
        r = (med[False] / med[True]).replace([np.inf, -np.inf], np.nan).dropna()
        rows.append({"surface": name, "test": "Vacant vs improved land \\$/sqft, same zone",
                     "n": len(r), "value": r.median()})
        H.add(f"Uni{name}VacantImprovedRatio", r.median(), ratio)
        H.add(f"Uni{name}VacantImprovedZones", len(r), num)

    # (2) abated vs non-abated land rate, within zone (Sec. 4(c) names abatement status).
    da = d[d["improved"]]
    for name, col in (("OPA", "psf_opa"), ("LYCD", "psf_lycd")):
        z = da.groupby("gma3").filter(lambda g: g["abated"].nunique() == 2 and (g["abated"] == 1).sum() >= 10)
        med = z.groupby(["gma3", "abated"])[col].median().unstack()
        r = (med[1] / med[0]).replace([np.inf, -np.inf], np.nan).dropna()
        rows.append({"surface": name, "test": "Abated vs unabated land \\$/sqft, same zone",
                     "n": len(r), "value": r.median()})
        H.add(f"Uni{name}AbatedRatio", r.median(), ratio)

    # (3) The sharpest form of Sec. 3(b): among improved parcels in the same zone AND the same
    # lot-size band -- as close to "similarly situated" as this data supports -- does the land
    # component track the value of the building standing on it? It should not.
    da = da.copy()
    da["area_band"] = da.groupby("gma3")["dor_area_sqft"].transform(
        lambda s: pd.qcut(s, 4, labels=False, duplicates="drop"))
    cells = da.groupby(["gma3", "area_band"]).filter(lambda g: len(g) >= 30)
    for name, col in (("OPA", "opa_gross_land"), ("LYCD", "lycd_land_value")):
        rho = cells.groupby(["gma3", "area_band"]).apply(
            lambda g: g[col].corr(g["opa_gross_building"], method="spearman"),
            include_groups=False).dropna()
        rows.append({"surface": name,
                     "test": "Rank corr. of land value with building value, same zone and lot-size band",
                     "n": len(rho), "value": rho.median()})
        H.add(f"Uni{name}BuildingCorr", rho.median(), lambda x: f"{x:.2f}")
    H.add("UniCells", int(cells.groupby(["gma3", "area_band"]).ngroups), num)

    tbl = pd.DataFrame(rows)
    out = pd.DataFrame({
        "Test": tbl[tbl.surface == "OPA"]["test"].values,
        "Zones": [num(v) for v in tbl[tbl.surface == "OPA"]["n"].values],
        "OPA": [f"{v:.2f}" for v in tbl[tbl.surface == "OPA"]["value"].values],
        "LYCD": [f"{v:.2f}" for v in tbl[tbl.surface == "LYCD"]["value"].values],
    })
    save_table(TABLES / "uniformity.tex", out, col_format="X r r r", escape=False)
    return d


def default_ratio_collapse(df, H):
    """Sec. 3(e) forbids deriving the land component as a fixed percentage of total value.
    OPA's own roll shows the practice directly: a large share of improved parcels sit at
    exactly a 0.20 land-to-total ratio."""
    d = df[(df["opa_gross_building"] > 0) & (df["market_value"] > 0)]
    r_opa = (d["opa_gross_land"] / d["market_value"]).round(4)
    r_lycd = (d["alloc_land"] / d["market_value"]).round(4)
    at20_opa = 100 * r_opa.between(0.1995, 0.2005).mean()
    at20_lycd = 100 * r_lycd.between(0.1995, 0.2005).mean()
    H.add("DefaultRatioOpaPct", at20_opa, pct)
    H.add("DefaultRatioLycdPct", at20_lycd, pct)
    H.add("DefaultRatioImprovedParcels", len(d), num)
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

    out = rat.rename(columns={"sample": "Sample", "n": "Sales"}).copy()
    out["Sample"] = (out["Sample"].str.replace(">=", "$\\geq$", regex=False)
                     .str.replace("$20k", "\\$20k", regex=False))
    out["Sales"] = out["Sales"].map(num)
    for c in ["OPA median", "LYCD median"]:
        out[c] = out[c].map(lambda x: f"{x:.2f}")
    for c in ["OPA COD", "LYCD COD"]:
        out[c] = out[c].map(lambda x: f"{x:.0f}")
    for c in ["OPA aggregate", "LYCD aggregate"]:
        out[c] = out[c].map(lambda x: f"{x:.2f}")
    out = out[["Sample", "Sales", "OPA median", "OPA COD", "OPA aggregate",
               "LYCD median", "LYCD COD", "LYCD aggregate"]]
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
            "Stratum": [f"{label}: {v}" for v in t[grp]],
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
    H.add("AEquityDOneMedian", val["median_change_pct"].iloc[0], lambda x: f"{x:+,.1f}%")
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
    for ax, col, title in ((axes[0], "psf_opa", "OPA land values"),
                           (axes[1], "psf_lycd", "LYCD land values")):
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

    b, moved = scenario_c(df, H)
    scenario_a(df, H)
    d = uniformity_tests(df, H)
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
