"""Generate all figures, tables, and headline macros for the report.

SINGLE SOURCE OF NUMERICAL CONTENT for paper/Report.tex. Re-run after any data change:

    C:/Users/druss/miniconda3/python.exe analysis/single_tax/philadelphia/paper/scripts/generate_paper_assets.py

Then rebuild the PDF. Never type a result number into Report.tex — add it here as a macro,
regenerate, and reference the macro.

Reads (all produced by cities/philadelphia/model_single_tax_ledger.ipynb, except the
tract-level LVT-UBI exports and the tract geometry, which the surface-comparison map needs):

    analysis/data/philadelphia_single_tax_ty2026_ledger.csv       the 2,880-row sweep
    analysis/data/philadelphia_single_tax_ty2026_lines.csv        the revenue ledger
    analysis/data/philadelphia_single_tax_ty2026_kappa_bounds.csv the published kappa bounds
    analysis/data/philadelphia_lvt_ubi_ty2026.csv                 tract land tax, OPA surface
    analysis/data/philadelphia_lvt_ubi_lycd_ty2026.csv            tract land tax, LYCD surface
    cities/philadelphia/data/census_tracts.gpq                    tract geometry
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
    Headlines, PPI_COLORS, latex_escape, num, usd_b, usd_m, pct, ratio, save_table, text,
)

PAPER = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[5]
DATA = REPO_ROOT / "analysis" / "data"
CITY_DATA = REPO_ROOT / "cities" / "philadelphia" / "data"
TABLES = PAPER / "tables"
FIGS = PAPER / "figures"
TABLES.mkdir(parents=True, exist_ok=True)
FIGS.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({
    "savefig.dpi": 300, "savefig.bbox": "tight",
    "font.family": "serif", "font.size": 10,
    "axes.spines.top": False, "axes.spines.right": False,
})

def share(x, decimals=2):
    """kappa and spans in kappa: dimensionless shares, so no 'x' suffix.
    (report_helpers.ratio appends 'x', which is right for LYCD/OPA multiples
    but reads as '0.5 times' when applied to a share.)"""
    return f"{x:,.{decimals}f}"


PREFIX = "Stx"
SLUG = "philadelphia_single_tax_ty2026"

# The headline operating point. Every number quoted without a qualifier is this cell.
I_STAR, PHI_STAR, H_STAR, BASIS_STAR = 0.05, 1.0, 0.0, "taxable"

# Colour-scale clip for the surface map; cited in the figure caption, so it is a macro.
MAP_CLIP_LO, MAP_CLIP_HI = 0.5, 2.5

BUNDLE_ORDER = ["B0", "B1", "B2", "B3", "B4", "B5"]
FAMILIES = ["building", "wage", "other"]

# Short axis labels; the full bundle names live in the table and the figure caption.
SHORT = {"B1": "structures", "B2": "wage", "B3": "wage +\nstructures",
         "B4": "+ BIRT,\nNPT, SIT", "B5": "+ U&O,\nRTT"}


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #
def load():
    sweep = pd.read_csv(DATA / f"{SLUG}_ledger.csv")
    lines = pd.read_csv(DATA / f"{SLUG}_lines.csv")
    bounds = pd.read_csv(DATA / f"{SLUG}_kappa_bounds.csv")
    return sweep, lines, bounds


def headline_cell(sweep, g_level="none"):
    """The sweep rows at the headline operating point."""
    return sweep[
        (sweep.rent_basis == BASIS_STAR)
        & (sweep.discount_rate == I_STAR)
        & (sweep.phi == PHI_STAR)
        & (sweep.haircut == H_STAR)
        & (sweep.g_level == g_level)
    ].copy()


def bundle_frame(sweep):
    """One row per bundle: target and the family split of what it abolishes."""
    b = sweep.drop_duplicates("bundle").set_index("bundle")
    return b.loc[[x for x in BUNDLE_ORDER if x in b.index]]


def literature_kappa(bundles, bounds):
    """Bundle-weighted kappa implied by the published bounds.

    Each family's published low/high, weighted by that family's share of the bundle's
    abolished revenue. This is the quantity that answers 'could published capitalization
    estimates carry this bundle?' -- it is compared against kappa*, never substituted for it.
    """
    lo = {r.family: r.kappa for r in bounds[bounds.edge == "low"].itertuples()}
    hi = {r.family: r.kappa for r in bounds[bounds.edge == "high"].itertuples()}
    out = {}
    for bname, row in bundles.iterrows():
        tab = row["t_abolished"]
        if tab <= 0:
            continue
        w = {f: row[f"t_{f}"] / tab for f in FAMILIES}
        out[bname] = {
            "lit_low": sum(w[f] * lo[f] for f in FAMILIES),
            "lit_high": sum(w[f] * hi[f] for f in FAMILIES),
            **{f"w_{f}": w[f] for f in FAMILIES},
        }
    return pd.DataFrame(out).T


def surface_ratio_by_tract():
    """Tract-level LYCD/OPA land-rent ratio, joined to tract geometry.

    Both exports are the same LVT-UBI model at full capture on the same parcels; the only
    difference is which published land surface prices the land. So the ratio of
    `new_land_tax` is the ratio of the two surfaces' land value in that tract.
    """
    o = pd.read_csv(DATA / "philadelphia_lvt_ubi_ty2026.csv", dtype={"tract_geoid": str})
    l = pd.read_csv(DATA / "philadelphia_lvt_ubi_lycd_ty2026.csv", dtype={"tract_geoid": str})
    m = o[["tract_geoid", "new_land_tax", "total_pop"]].merge(
        l[["tract_geoid", "new_land_tax"]], on="tract_geoid", suffixes=("_opa", "_lycd"))
    m = m[(m.new_land_tax_opa > 0) & (m.new_land_tax_lycd > 0)].copy()
    m["ratio"] = m.new_land_tax_lycd / m.new_land_tax_opa
    return m


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
CITY_HALL_LONLAT = (-75.1635, 39.9526)   # geographic constant, cited by macros


def geography_stats(tracts):
    """The computed statistics behind the map's narration — added after the paper
    audit's M-1 refuted a narration written from the rendered image. Every geographic
    sentence in section 3.1 must cite these macros, not the picture."""
    import geopandas as gpd
    from shapely.geometry import Point
    geo = gpd.read_parquet(CITY_DATA / "census_tracts.gpq")
    geo["tract_geoid"] = geo["GEOID"].astype(str)
    g = geo.merge(tracts, on="tract_geoid", how="inner").to_crs(32618)
    hall = gpd.GeoSeries([Point(*CITY_HALL_LONLAT)], crs=4326).to_crs(32618).iloc[0]
    g["km"] = g.geometry.centroid.distance(hall) / 1000.0
    g["q"] = pd.qcut(g["km"], 5, labels=False)

    out = {
        "mid_belt_median": g[g["q"].isin([1, 2])]["ratio"].median(),
        "outer_median": g[g["q"] == 4]["ratio"].median(),
        "below_one_median_km": g[g["ratio"] < 1]["km"].median(),
        "all_median_km": g["km"].median(),
    }
    # Incidence geography: share of tracts whose burden-rank moves materially.
    ro = g["new_land_tax_opa"].rank(pct=True)
    rl = g["new_land_tax_lycd"].rank(pct=True)
    out["rank_shift_share"] = 100 * ((ro - rl).abs() > 0.10).mean()
    return out


def band_fragility(sweep, bundles, lit):
    """Across every swept operating point (taxable basis), how often does some
    bundle/surface cell exit the published band on the failure side? Feeds the M-4
    disclosure sentence in section 3.3."""
    d = sweep[(sweep.rent_basis == BASIS_STAR) & (sweep.bundle != "B0")].copy()
    d["hi"] = d["bundle"].map(lit["lit_high"])
    grp = d.groupby(["discount_rate", "phi", "haircut", "g_level"])
    total = grp.ngroups
    any_above = grp.apply(lambda x: bool((x["kappa_star"] > x["hi"]).any()),
                          include_groups=False).sum()
    return total, int(any_above)


def fig_surface_map(tracts):
    """THE headline figure: where the two published land surfaces disagree."""
    try:
        import geopandas as gpd
    except ImportError:
        print("  [warn] geopandas unavailable; skipping surface map")
        return None
    geo = gpd.read_parquet(CITY_DATA / "census_tracts.gpq")
    geo["tract_geoid"] = geo["GEOID"].astype(str)
    g = geo.merge(tracts, on="tract_geoid", how="inner")

    fig, ax = plt.subplots(figsize=(6.0, 6.6))
    # Diverging scale centred on parity. Clipped: a handful of tracts with near-zero OPA
    # land run to 70x and would otherwise flatten the whole map to one colour.
    vmin, vmax = MAP_CLIP_LO, MAP_CLIP_HI
    g.plot(column=g["ratio"].clip(vmin, vmax), cmap="PuOr_r", vmin=vmin, vmax=vmax,
           linewidth=0.15, edgecolor="white", ax=ax, legend=True,
           legend_kwds={"label": "LYCD land value $\\div$ OPA land value",
                        "orientation": "horizontal", "shrink": 0.72, "pad": 0.02,
                        "extend": "both"})
    ax.set_axis_off()
    # No in-figure title: the LaTeX caption carries it, and duplicating reads as an error.
    fig.savefig(FIGS / "surface_map.pdf")
    plt.close(fig)
    return g


def fig_kappa_star(cell, lit):
    """kappa* by bundle and surface, against the band published estimates support."""
    d = cell[cell.bundle != "B0"]
    bundles = [b for b in BUNDLE_ORDER if b in set(d.bundle)]
    x = np.arange(len(bundles))
    fig, ax = plt.subplots(figsize=(6.8, 4.2))

    # The literature band, drawn behind: what published estimates could deliver.
    lo = [lit.loc[b, "lit_low"] for b in bundles]
    hi = [lit.loc[b, "lit_high"] for b in bundles]
    ax.fill_between(x, lo, hi, color=PPI_COLORS["gray"], alpha=0.45, zorder=1,
                    label="Published estimates (bundle-weighted range)")

    for surf, colour, marker in (("opa", PPI_COLORS["accent"], "o"),
                                 ("lycd", PPI_COLORS["primary"], "s")):
        y = [d[(d.bundle == b) & (d.surface == surf)]["kappa_star"].iloc[0] for b in bundles]
        ax.plot(x, y, marker=marker, color=colour, lw=1.8, ms=6, zorder=3,
                label=f"$\\kappa^*$ required ({surf.upper()} land)")

    ax.axhline(0, color=PPI_COLORS["dark"], lw=0.8, ls=":", zorder=2)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{b}\n{SHORT[b]}" for b in bundles], fontsize=8)
    ax.set_ylabel("$\\kappa$ required to break even")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.savefig(FIGS / "kappa_star.pdf")
    plt.close(fig)


def fig_ledger(lines):
    """What the program abolishes, absorbs, and leaves alone."""
    order = ["labor", "capital", "absorbed", "kept", "out_of_scope"]
    label = {"labor": "Taxes on labor\n(abolished)", "capital": "Taxes on capital\n(abolished)",
             "absorbed": "Land tax\n(absorbed)", "kept": "Kept", "out_of_scope": "Out of scope"}
    colour = {"labor": PPI_COLORS["accent"], "capital": PPI_COLORS["light"],
              "absorbed": PPI_COLORS["primary"], "kept": PPI_COLORS["gray"],
              "out_of_scope": PPI_COLORS["gray"]}
    g = lines.groupby("classification")["amount"].sum() / 1e9
    g = g.reindex([c for c in order if c in g.index])
    fig, ax = plt.subplots(figsize=(6.6, 3.4))
    ax.bar([label[c] for c in g.index], g.values,
           color=[colour[c] for c in g.index], width=0.62)
    for i, v in enumerate(g.values):
        ax.text(i, v + 0.04, f"${v:,.2f}B", ha="center", fontsize=9,
                color=PPI_COLORS["dark"])
    ax.set_ylabel("Annual revenue ($B)")
    ax.set_ylim(0, max(g.values) * 1.18)
    ax.tick_params(axis="x", labelsize=8)
    fig.savefig(FIGS / "ledger.pdf")
    plt.close(fig)


def fig_sensitivity(sweep):
    """How kappa*(B3) moves on each swept axis, one at a time, both surfaces.

    Two things this figure is built to show honestly. First, phi and h are the SAME knob:
    kappa* depends on the product phi*(1-h), so phi=0.85 and h=0.15 give an identical
    kappa*. They share one row rather than pretending to be independent axes. Second, the
    discount-rate row spans more than the land-surface row -- but its range is an analyst's
    choice, while the surface range is a disagreement between two published assessments.
    The figure labels that distinction rather than leaving the reader to infer a ranking.
    """
    b3 = sweep[(sweep.bundle == "B3") & (sweep.rent_basis == BASIS_STAR)]
    base = dict(discount_rate=I_STAR, phi=PHI_STAR, haircut=H_STAR, g_level="none")

    def span(col, surf):
        sel = b3[b3.surface == surf].copy()
        for k, v in base.items():
            if k != col:
                sel = sel[sel[k] == v]
        return sel["kappa_star"].min(), sel["kappa_star"].max()

    rows = []
    surf_vals = [b3[(b3.surface == v) & (b3.discount_rate == I_STAR) & (b3.phi == PHI_STAR)
                    & (b3.haircut == H_STAR) & (b3.g_level == "none")]["kappa_star"].iloc[0]
                 for v in ("opa", "lycd")]
    rows.append({"dim": "Land surface\n(OPA vs LYCD)", "surface": None,
                 "lo": min(surf_vals), "hi": max(surf_vals)})
    def span_product(surf):
        """kappa* over the full phi*(1-h) grid — the single knob, honestly measured.
        The paper-audit's M-3: varying phi with h pinned (or vice versa) spans half of
        what the knob spans. kappa*(x) = (T-G)/(x*T_ab) - R0/T_ab, so this span is even
        R0-independent — identical across surfaces."""
        sel = b3[(b3.surface == surf) & (b3.discount_rate == I_STAR)
                 & (b3.g_level == "none")]
        return sel["kappa_star"].min(), sel["kappa_star"].max()

    for col, lab in (("discount_rate", "Discount rate $i$\n(3–7%, chosen range)"),
                     ("phi", "Capture $\\varphi$ and haircut $h$\n(one knob: $\\varphi(1-h)$)"),
                     ("g_level", "Road rent $G$")):
        for surf in ("opa", "lycd"):
            lo, hi = span_product(surf) if col == "phi" else span(col, surf)
            rows.append({"dim": lab, "surface": surf, "lo": lo, "hi": hi})
    r = pd.DataFrame(rows)

    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    labs = list(dict.fromkeys(r["dim"]))
    for i, lab in enumerate(labs):
        sub = r[r["dim"] == lab]
        for _, row in sub.iterrows():
            off = 0.0 if row["surface"] is None else (-0.16 if row["surface"] == "opa" else 0.16)
            c = (PPI_COLORS["dark"] if row["surface"] is None else
                 PPI_COLORS["accent"] if row["surface"] == "opa" else PPI_COLORS["primary"])
            ax.plot([row["lo"], row["hi"]], [i + off] * 2, color=c, lw=5.5,
                    solid_capstyle="butt")
    ax.set_yticks(range(len(labs)))
    ax.set_yticklabels(labs, fontsize=8.5)
    ax.invert_yaxis()
    ax.set_xlabel("$\\kappa^*$ for B3 (wage tax + tax on structures)")
    ax.axvline(0, color=PPI_COLORS["gray"], lw=0.8, ls=":")
    handles = [plt.Line2D([], [], color=PPI_COLORS["accent"], lw=5, label="OPA land"),
               plt.Line2D([], [], color=PPI_COLORS["primary"], lw=5, label="LYCD land"),
               plt.Line2D([], [], color=PPI_COLORS["dark"], lw=5, label="across surfaces")]
    ax.legend(handles=handles, frameon=False, fontsize=8, ncol=3,
              loc="lower center", bbox_to_anchor=(0.5, -0.42))
    fig.savefig(FIGS / "sensitivity.pdf")
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def tab_ledger(lines):
    d = lines.copy()
    d = d[d.classification.isin(["labor", "capital", "absorbed"])]
    d = d.sort_values(["classification", "amount"], ascending=[True, False])
    out = pd.DataFrame({
        "Tax": d["name"].map(text),
        "Annual ($M)": (d["amount"] / 1e6).round(1).map(lambda v: f"{v:,.1f}"),
        "Body": d["body"].map(text),
        "Basis": d["classification"].map(text),
        "Status": d["status"].map(text),
    })
    save_table(TABLES / "ledger.tex", out, col_format="X r l l l")


def tab_bundles(bundles, cell_none, lit):
    rows = []
    for b in BUNDLE_ORDER:
        if b not in bundles.index or b == "B0":
            continue
        r = bundles.loc[b]
        ko = cell_none[(cell_none.bundle == b) & (cell_none.surface == "opa")]["kappa_star"].iloc[0]
        kl = cell_none[(cell_none.bundle == b) & (cell_none.surface == "lycd")]["kappa_star"].iloc[0]
        rows.append({
            # Headers below carry math, so this table is written with escape=False --
            # which means data cells must be escaped here. Bundle labels contain '&'.
            "Bundle": f"{b}. {latex_escape(r['bundle_label'])}",
            "Abolished (\\$B)": f"{r['t_abolished'] / 1e9:,.2f}",
            "Target (\\$B)": f"{r['target'] / 1e9:,.2f}",
            "$\\kappa^*$ (OPA)": f"{ko:,.2f}",
            "$\\kappa^*$ (LYCD)": f"{kl:,.2f}",
            "Published high": f"{lit.loc[b, 'lit_high']:,.2f}",
        })
    save_table(TABLES / "bundles.tex", pd.DataFrame(rows),
               col_format="X r r r r r", escape=False)


def _short_cite(citation: str) -> str:
    """'Coste, Jonah (2024), ...' -> 'Coste (2024)'. Keeps the table readable without
    hardcoding author names: both parts are parsed out of the exported citation."""
    import re
    surname = str(citation).split(",")[0].strip()
    m = re.search(r"\((\d{4})\)", str(citation))
    year = m.group(1) if m else ""
    return latex_escape(f"{surname} ({year})" if year else surname)


def tab_bounds(bounds):
    fam = {"building": "Tax on structures", "wage": "Wage \\& Earnings, NPT",
           "other": "BIRT, SIT, U\\&O, RTT"}
    rows = []
    for f in FAMILIES:
        lo = bounds[(bounds.family == f) & (bounds.edge == "low")].iloc[0]
        hi = bounds[(bounds.family == f) & (bounds.edge == "high")].iloc[0]
        rows.append({
            "Family": fam[f],
            "Low $\\kappa$": f"{lo['kappa']:,.3f}",
            "High $\\kappa$": f"{hi['kappa']:,.3f}",
            # A dagger marks a bound transferred from a different tax; the caption
            # explains it. A "Directness" column hyphenates badly at this width.
            "Low anchor": _short_cite(lo["citation"])
                          + ("$^\\dagger$" if lo["directness"] == "transferred" else ""),
            "High anchor": _short_cite(hi["citation"])
                           + ("$^\\dagger$" if hi["directness"] == "transferred" else ""),
        })
    save_table(TABLES / "bounds.tex", pd.DataFrame(rows),
               col_format="l r r X X", escape=False)


# --------------------------------------------------------------------------- #
# Headlines
# --------------------------------------------------------------------------- #
def headlines(sweep, lines, bounds, bundles, cell_none, cell_central, lit, tracts):
    H = Headlines(prefix=PREFIX, out_path=TABLES / "headlines.tex")

    # --- the two land surfaces ---
    r0 = cell_none.drop_duplicates("surface").set_index("surface")["r0"]
    H.add("RentOpa", r0["opa"] / 1e9, usd_b)
    H.add("RentLycd", r0["lycd"] / 1e9, usd_b)
    H.add("SurfaceGapPct", 100 * (r0["lycd"] - r0["opa"]) / r0["opa"], pct)
    H.add("SurfaceRatio", r0["lycd"] / r0["opa"], ratio)

    # --- tract-level heterogeneity behind that aggregate gap ---
    H.add("TractN", len(tracts), num)
    H.add("TractMedianRatio", tracts.ratio.median(), ratio)
    H.add("TractPFive", tracts.ratio.quantile(0.05), ratio)
    H.add("TractPNinetyFive", tracts.ratio.quantile(0.95), ratio)
    H.add("TractShareLycdHigher", 100 * (tracts.ratio > 1).mean(), pct)
    H.add("TractShareOpaHigher", 100 * (tracts.ratio < 1).mean(), pct)

    # --- what the program abolishes ---
    by_class = lines.groupby("classification")["amount"].sum()
    H.add("LaborB", by_class["labor"] / 1e9, usd_b)
    H.add("CapitalB", by_class["capital"] / 1e9, usd_b)
    H.add("LandTaxB", by_class["absorbed"] / 1e9, usd_b)
    H.add("LedgerLines", len(lines), num)

    # --- bundles (LaTeX macro names cannot contain digits, so B3 -> BThree) ---
    WORD = {"B1": "BOne", "B2": "BTwo", "B3": "BThree", "B4": "BFour", "B5": "BFive"}
    for b, w in WORD.items():
        r = bundles.loc[b]
        H.add(f"{w}TargetB", r["target"] / 1e9, usd_b)
        H.add(f"{w}AbolishedB", r["t_abolished"] / 1e9, usd_b)
        for surf in ("opa", "lycd"):
            k = cell_none[(cell_none.bundle == b) & (cell_none.surface == surf)]["kappa_star"].iloc[0]
            H.add(f"{w}Kappa{surf.capitalize()}", k, share)
            kc = cell_central[(cell_central.bundle == b)
                              & (cell_central.surface == surf)]["kappa_star"].iloc[0]
            H.add(f"{w}Kappa{surf.capitalize()}G", kc, share)
        H.add(f"{w}LitHigh", lit.loc[b, "lit_high"], share)
        H.add(f"{w}LitLow", lit.loc[b, "lit_low"], share)
    H.add("BThreeWageSharePct", 100 * lit.loc["B3", "w_wage"], pct)
    H.add("BFiveWageSharePct", 100 * lit.loc["B5", "w_wage"], pct)

    # --- the published bounds themselves ---
    for f in FAMILIES:
        lo = bounds[(bounds.family == f) & (bounds.edge == "low")].iloc[0]
        hi = bounds[(bounds.family == f) & (bounds.edge == "high")].iloc[0]
        H.add(f"Kappa{f.capitalize()}Low", lo["kappa"], share)
        H.add(f"Kappa{f.capitalize()}High", hi["kappa"], share)

    # --- the sweep's own size, and the headline operating point ---
    # Geography (M-1) and band-fragility (M-4) macros.
    gs = geography_stats(tracts)
    H.add("MidBeltMedianRatio", gs["mid_belt_median"], ratio)
    H.add("OuterMedianRatio", gs["outer_median"], ratio)
    H.add("BelowOneMedianKm", gs["below_one_median_km"], lambda x: f"{x:,.1f}")
    H.add("AllMedianKm", gs["all_median_km"], lambda x: f"{x:,.1f}")
    H.add("RankShiftSharePct", gs["rank_shift_share"], pct)
    opt, above = band_fragility(sweep, bundles, lit)
    H.add("OpPointsTotal", opt, num)
    H.add("OpPointsAnyAbove", above, num)
    vacant_study_macros(H)

    H.add("SweepRows", len(sweep), num)
    H.add("DiscountRate", 100 * I_STAR, pct)
    H.add("GCentralM", cell_central["g_amount"].iloc[0] / 1e6, usd_m)

    # Swept grid values the prose refers to by name. These are data, not illustration:
    # if the sweep grid changes, the sentences citing them must change with it.
    H.add("DiscountLowPct", 100 * sweep.discount_rate.min(), pct)
    H.add("DiscountHighPct", 100 * sweep.discount_rate.max(), pct)
    H.add("PhiLow", sweep.phi.min(), share)
    H.add("HaircutHighPct", 100 * sweep.haircut.max(), pct)
    H.add("MapClipLo", MAP_CLIP_LO, ratio)
    H.add("MapClipHi", MAP_CLIP_HI, ratio)

    # --- where does kappa* sit relative to the published band? ---
    # Three outcomes, and the distinction is the paper's central result: BELOW the band
    # means the bundle pencils more easily than even the least favourable published
    # estimate; INSIDE means published evidence is consistent with both success and
    # failure, so the literature does not discriminate; ABOVE means no published reading
    # supports it.
    below = inside = above = 0
    for b in ("B1", "B2", "B3", "B4", "B5"):
        for surf in ("opa", "lycd"):
            k = cell_none[(cell_none.bundle == b) & (cell_none.surface == surf)]["kappa_star"].iloc[0]
            if k < lit.loc[b, "lit_low"]:
                below += 1
            elif k <= lit.loc[b, "lit_high"]:
                inside += 1
            else:
                above += 1
    H.add("CellsBelowBand", below, num)
    H.add("CellsInsideBand", inside, num)
    H.add("CellsAboveBand", above, num)
    H.add("CellsTotal", below + inside + above, num)

    # --- one-at-a-time sensitivity spans for kappa*(B3), for the prose ---
    b3 = sweep[(sweep.bundle == "B3") & (sweep.rent_basis == BASIS_STAR)]
    base = dict(discount_rate=I_STAR, phi=PHI_STAR, haircut=H_STAR, g_level="none")

    def _span(col, surf):
        sel = b3[b3.surface == surf].copy()
        for k, v in base.items():
            if k != col:
                sel = sel[sel[k] == v]
        return sel["kappa_star"].max() - sel["kappa_star"].min()

    surf_span = abs(
        cell_none[(cell_none.bundle == "B3") & (cell_none.surface == "opa")]["kappa_star"].iloc[0]
        - cell_none[(cell_none.bundle == "B3") & (cell_none.surface == "lycd")]["kappa_star"].iloc[0])
    H.add("SpanSurface", surf_span, share)
    H.add("SpanDiscountOpa", _span("discount_rate", "opa"), share)
    H.add("SpanDiscountLycd", _span("discount_rate", "lycd"), share)
    # M-3 fix: SpanCapture is the PRODUCT-knob span phi*(1-h) over its swept grid,
    # not the phi-only span with h pinned (which is half of it).
    _pk = sweep[(sweep.bundle == "B3") & (sweep.rent_basis == BASIS_STAR)
                & (sweep.surface == "opa") & (sweep.discount_rate == I_STAR)
                & (sweep.g_level == "none")]["kappa_star"]
    H.add("SpanCapture", _pk.max() - _pk.min(), share)
    H.add("SpanRoadRent", _span("g_level", "opa"), share)

    H.write()
    H.to_json(PAPER / "values.json")
    return H


def vacant_study_macros(H):
    """Read the vacant-land ratio study's generated table (produced by
    scripts/vacant_land_ratio_study.py --out ...). The paper cites the study's
    aggregates rather than restating docs/VACANT_LAND_VALUATION.md by hand."""
    path = DATA / "philadelphia_vacant_land_ratio_study.csv"
    v = pd.read_csv(path)
    row = v[v["sample"].str.startswith("bare land, sale")].iloc[0]
    H.add("VacantN", int(row["n"]), num)
    H.add("VacantOpaAgg", row["OPA aggregate"], ratio)
    H.add("VacantLycdAgg", row["LYCD aggregate"], ratio)
    H.add("VacantOpaCod", int(row["OPA COD"]), num)
    H.add("VacantLycdCod", int(row["LYCD COD"]), num)


def main():
    sweep, lines, bounds = load()
    bundles = bundle_frame(sweep)
    cell_none = headline_cell(sweep, "none")
    cell_central = headline_cell(sweep, "central")
    lit = literature_kappa(bundles, bounds)
    tracts = surface_ratio_by_tract()

    fig_surface_map(tracts)
    fig_kappa_star(cell_none, lit)
    fig_ledger(lines)
    fig_sensitivity(sweep)

    tab_ledger(lines)
    tab_bundles(bundles, cell_none, lit)
    tab_bounds(bounds)

    H = headlines(sweep, lines, bounds, bundles, cell_none, cell_central, lit, tracts)
    print(f"figures -> {FIGS}")
    print(f"tables  -> {TABLES}")
    print(f"macros  -> {TABLES / 'headlines.tex'} ({len(H._vals)} macros)")


if __name__ == "__main__":
    main()
