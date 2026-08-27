"""Generate all figures, tables, and headline macros for the ownership report.

SINGLE SOURCE OF NUMERICAL CONTENT for paper/Report.tex. Re-run after any data change:

    C:/Users/druss/miniconda3/python.exe paper/scripts/generate_paper_assets.py

Reads only the tracked outputs of `ownership_by_type.py` (../results/*.csv and
headline_stats.json) — never the parcel pipeline directly, so the report rebuilds in
seconds and cannot drift from the analysis it cites.

Never type a result number into Report.tex; add it here as a macro, regenerate, and
reference the macro.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_helpers import (  # noqa: E402
    Headlines, PPI_COLORS, num, usd_m, usd_b, pct, ratio, text, save_table,
)

# Justified tabularx X columns hyphenate label text badly ("Surface parking, com-mercial").
# Ragged-right avoids the hyphenation and the stretched interword spacing.
RX = r">{\raggedright\arraybackslash}X"

PAPER = Path(__file__).resolve().parents[1]
RESULTS = PAPER.parent / "results"
TABLES = PAPER / "tables"
FIGS = PAPER / "figures"
TABLES.mkdir(parents=True, exist_ok=True)
FIGS.mkdir(parents=True, exist_ok=True)

PREFIX = "PhilOwn"

plt.rcParams.update({
    "savefig.dpi": 300, "savefig.bbox": "tight",
    "font.family": "serif", "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.25, "grid.linewidth": 0.5,
})

# PPI palette, plus a geography ramp that reads local -> distant.
C_PRIMARY, C_ACCENT = PPI_COLORS["primary"], PPI_COLORS["accent"]
C_DARK, C_LIGHT, C_GRAY = PPI_COLORS["dark"], PPI_COLORS["light"], PPI_COLORS["gray"]
GEO_ORDER = ["In-city (Philadelphia)", "Suburban PA", "NJ / DE metro",
             "Out-of-state", "Unknown"]
GEO_COLORS = [C_DARK, C_PRIMARY, C_LIGHT, C_ACCENT, C_GRAY]
SECTOR_COLORS = {"Individual": C_PRIMARY, "Business / investor entity": C_ACCENT,
                 "Institutional / nonprofit": C_LIGHT, "Public agency": C_GRAY}

VACANT = "Vacant Land"
PARKING = ["Surface Parking — commercial", "Surface Parking — non-commercial",
           "Surface Parking — with structure", "Parking Garage (structured)"]
HEADLINE = [VACANT] + PARKING
# Categories with no taxable land value carry no ownership *share*; drop them from every
# share-based figure and table rather than drawing them as zero.
MIN_PARCELS = 200


def _load():
    S = json.loads((RESULTS / "headline_stats.json").read_text(encoding="utf-8"))
    d = {p.stem: pd.read_csv(p, encoding="utf-8") for p in RESULTS.glob("*.csv")}
    return S, d


_LABELS = {
    "Surface Parking — commercial": "Surface parking, commercial",
    "Surface Parking — non-commercial": "Surface parking, non-commercial",
    "Surface Parking — with structure": "Surface parking, with structure",
    "Parking Garage (structured)": "Parking garage",
    "Large Multi-Family (5+ units)": "Large multi-family (5+)",
    "Small Multi-Family (2-4 units)": "Small multi-family (2–4)",
    "Abated / Construction Exemption": "Abated / construction",
    "Single Family Residential": "Single-family residential",
    "Office / Commercial Condo": "Office / commercial condo",
    "Retail / General Commercial": "Retail / general commercial",
    "Improved Vacant Land": "Improved vacant land",
    "Vacant Land": "Vacant land",
    "Other Residential": "Other residential",
    "Other Commercial": "Other commercial",
    "Mixed Use": "Mixed use",
}


def _short(cat: str) -> str:
    """Shorten a category label for axis ticks, table rows, and figure annotations."""
    return _LABELS.get(str(cat), str(cat))


def _tex(s) -> str:
    """Category labels for LaTeX cells: em/en dashes are not reliable in all encodings."""
    return _short(s).replace("—", "--").replace("–", "--")


def _taxable(shares: pd.DataFrame) -> pd.DataFrame:
    """Categories that actually carry taxable land value (drops the '— Exempt' buckets)."""
    d = shares[shares["private_llc_land_share"].notna() &
               (shares["private_land_value"] > 0)]
    return d[(d["private_parcels"] >= MIN_PARCELS) |
             d["analysis_category"].isin(HEADLINE)]


def _geo_wide(geo: pd.DataFrame) -> pd.DataFrame:
    """Category x geography land-value shares, ordered local -> distant."""
    return (geo.pivot(index="analysis_category", columns="owner_geography",
                      values="land_value_share")
            .reindex(columns=GEO_ORDER).fillna(0.0))


def _geo_share(geo: pd.DataFrame, cat: str, bucket: str) -> float:
    row = geo[(geo["analysis_category"] == cat) & (geo["owner_geography"] == bucket)]
    tot = geo.loc[geo["analysis_category"] == cat, "land_value"].sum()
    return float(row["land_value"].sum() / tot) if tot else float("nan")


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def _place_labels(fig, ax, xs, ys, labels, fontsize=6.2) -> None:
    """Annotate each point, greedily picking an offset that collides least.

    Matplotlib has no built-in label placer, and at this density fixed offsets overlap
    badly (the category cluster around 26–36% LLC share is unreadable with a single
    offset). Candidates are tried in order of preference; the first collision-free one
    wins, otherwise the least-bad.
    """
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    ax.margins(x=0.14, y=0.14)          # room so edge labels aren't clipped
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    cands = [(0, 8), (0, -9), (34, 0), (-34, 0), (26, 8), (-26, 8),
             (26, -8), (-26, -8), (0, 16), (0, -17), (44, 9), (-44, 9),
             (44, -9), (-44, -9), (0, 24), (0, -25), (56, 0), (-56, 0)]
    # Seed the occupied set with the markers themselves so labels don't sit on a dot,
    # plus anything already drawn (legend, the citywide-average annotation).
    occupied = []
    for art in list(ax.texts) + ([ax.get_legend()] if ax.get_legend() else []):
        try:
            occupied.append(art.get_window_extent(renderer=rend))
        except Exception:
            pass
    for x, y in zip(xs, ys):
        px, py = ax.transData.transform((x, y))
        occupied.append(matplotlib.transforms.Bbox.from_bounds(px - 4, py - 4, 8, 8))
    axbb = ax.get_window_extent()

    for i in np.argsort(-ys):           # place top-down; upper labels are the crowded ones
        best, best_score = None, None
        for dx, dy in cands:
            t = ax.annotate(labels[i], (xs[i], ys[i]), textcoords="offset points",
                            xytext=(dx, dy), ha="center", va="center",
                            fontsize=fontsize, color="#333")
            bb = t.get_window_extent(renderer=rend).expanded(1.04, 1.25)
            score = sum(bb.overlaps(o) for o in occupied)
            if not (axbb.x0 <= bb.x0 and bb.x1 <= axbb.x1
                    and axbb.y0 <= bb.y0 and bb.y1 <= axbb.y1):
                score += 5              # never prefer a clipped label over an overlap
            if best_score is None or score < best_score:
                if best is not None:
                    best.remove()
                best, best_score = t, score
            else:
                t.remove()
            if best_score == 0:
                break
        occupied.append(best.get_window_extent(renderer=rend).expanded(1.04, 1.25))


def fig_llc_share(shares: pd.DataFrame) -> None:
    d = _taxable(shares).sort_values("private_llc_land_share")
    fig, ax = plt.subplots(figsize=(6.5, 0.26 * len(d) + 1.0))
    colors = [C_ACCENT if c in HEADLINE else C_PRIMARY for c in d["analysis_category"]]
    ax.barh([_short(c) for c in d["analysis_category"]],
            d["private_llc_land_share"] * 100, color=colors, height=0.72)
    # A share means little without the base it is a share of.
    for y, (s, n) in enumerate(zip(d["private_llc_land_share"], d["private_parcels"])):
        ax.text(s * 100 + 0.7, y, f"{n:,.0f}", va="center", fontsize=6.5, color="#555")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlim(0, d["private_llc_land_share"].max() * 100 * 1.22)
    ax.set_xlabel("LLC share of privately owned land value")
    ax.tick_params(axis="y", labelsize=7.5)
    ax.grid(axis="y", visible=False)
    fig.savefig(FIGS / "llc_share.pdf")
    plt.close(fig)


def fig_absentee_scatter(shares: pd.DataFrame, geo: pd.DataFrame,
                         city_llc_oos: float) -> None:
    """The report's central figure: LLC-heavy does not mean absentee."""
    d = _taxable(shares).copy()
    d["oos"] = [_geo_share(geo, c, "Out-of-state") for c in d["analysis_category"]]
    d = d[d["oos"].notna()]
    fig, ax = plt.subplots(figsize=(6.5, 4.4))
    size = 14 + 46 * (np.log10(d["private_land_value"].clip(lower=1)) -
                      np.log10(d["private_land_value"].clip(lower=1)).min())
    head = d["analysis_category"].isin(HEADLINE)
    ax.scatter(d.loc[~head, "private_llc_land_share"] * 100, d.loc[~head, "oos"] * 100,
               s=size[~head], color=C_PRIMARY, alpha=0.75, edgecolor="white", linewidth=0.6,
               label="Other property types", zorder=3)
    ax.scatter(d.loc[head, "private_llc_land_share"] * 100, d.loc[head, "oos"] * 100,
               s=size[head], color=C_ACCENT, alpha=0.9, edgecolor="white", linewidth=0.6,
               label="Vacant land and parking", zorder=4)
    ax.axhline(city_llc_oos * 100, color=C_DARK, lw=0.9, ls="--", zorder=2)
    ax.text(0.985, city_llc_oos * 100 + 1.2, "citywide LLC average", transform=
            ax.get_yaxis_transform(), ha="right", fontsize=7, color=C_DARK)
    _place_labels(fig, ax, d["private_llc_land_share"] * 100, d["oos"] * 100,
                  [_short(c) for c in d["analysis_category"]])
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("LLC share of privately owned land value")
    ax.set_ylabel("Out-of-state share of LLC-owned land value")
    ax.legend(fontsize=7.5, frameon=False, loc="upper left")
    fig.savefig(FIGS / "absentee_scatter.pdf")
    plt.close(fig)


def fig_llc_geography(geo: pd.DataFrame) -> None:
    size = geo.groupby("analysis_category")[["parcels", "land_value"]].sum()
    keep = size[(size["land_value"] > 0) &
                ((size["parcels"] >= 20) | size.index.isin(HEADLINE))].index
    piv = _geo_wide(geo[geo["analysis_category"].isin(keep)])
    piv = piv.loc[piv["Out-of-state"].sort_values().index]
    fig, ax = plt.subplots(figsize=(6.5, 0.26 * len(piv) + 1.3))
    left = np.zeros(len(piv))
    for col, color in zip(GEO_ORDER, GEO_COLORS):
        ax.barh([_short(c) for c in piv.index], piv[col] * 100, left=left,
                color=color, height=0.72, label=col)
        left += piv[col].to_numpy() * 100
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("Share of LLC-owned land value, by owner's mailing address")
    ax.tick_params(axis="y", labelsize=7.5)
    ax.grid(axis="y", visible=False)
    ax.legend(fontsize=7, frameon=False, ncol=5, loc="upper center",
              bbox_to_anchor=(0.5, -0.13 - 0.5 / len(piv)))
    fig.savefig(FIGS / "llc_geography.pdf")
    plt.close(fig)


def fig_owner_sector(sectors: pd.DataFrame) -> None:
    sizes = sectors.groupby("analysis_category")["parcels"].sum()
    cats = set(sizes[sizes >= MIN_PARCELS].index) | set(HEADLINE)
    piv = (sectors[sectors["analysis_category"].isin(cats)]
           .pivot(index="analysis_category", columns="owner_sector",
                  values="land_value_share").fillna(0.0))
    piv = piv[piv.sum(axis=1) > 0].sort_values("Business / investor entity")
    fig, ax = plt.subplots(figsize=(6.5, 0.26 * len(piv) + 1.3))
    left = np.zeros(len(piv))
    for col in ["Individual", "Business / investor entity",
                "Institutional / nonprofit", "Public agency"]:
        if col not in piv:
            continue
        ax.barh([_short(c) for c in piv.index], piv[col] * 100, left=left,
                color=SECTOR_COLORS[col], height=0.72, label=col)
        left += piv[col].to_numpy() * 100
    ax.set_xlim(0, 100)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_xlabel("Share of land value")
    ax.tick_params(axis="y", labelsize=7.5)
    ax.grid(axis="y", visible=False)
    ax.legend(fontsize=7, frameon=False, ncol=4, loc="upper center",
              bbox_to_anchor=(0.5, -0.13 - 0.5 / len(piv)))
    fig.savefig(FIGS / "owner_sector.pdf")
    plt.close(fig)


def fig_vacant_concentration(ent: pd.DataFrame) -> pd.DataFrame:
    """Portfolio-size distribution and Lorenz curve for vacant-land LLC entities."""
    bins = [0, 1, 2, 5, 10, 25, 50, 10 ** 9]
    labels = ["1", "2", "3–5", "6–10", "11–25", "26–50", "50+"]
    tier = pd.cut(ent["parcels"], bins, labels=labels)
    t = (ent.groupby(tier, observed=True)
         .agg(entities=("parcels", "size"), parcels=("parcels", "sum"),
              land_value=("land_value", "sum")))
    t["entity_share"] = t["entities"] / t["entities"].sum()
    t["land_share"] = t["land_value"] / t["land_value"].sum()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.5, 2.9))
    x = np.arange(len(t))
    ax1.bar(x - 0.19, t["entity_share"] * 100, width=0.38, color=C_PRIMARY,
            label="Share of entities")
    ax1.bar(x + 0.19, t["land_share"] * 100, width=0.38, color=C_ACCENT,
            label="Share of land value")
    ax1.set_xticks(x, t.index, fontsize=7.5)
    ax1.set_xlabel("Vacant parcels held by the entity")
    ax1.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax1.legend(fontsize=7, frameon=False)
    ax1.grid(axis="x", visible=False)

    v = np.sort(ent["land_value"].to_numpy())
    ax2.plot(np.arange(1, len(v) + 1) / len(v), np.cumsum(v) / v.sum(),
             color=C_ACCENT, lw=1.6)
    ax2.plot([0, 1], [0, 1], color=C_DARK, lw=0.8, ls="--")
    ax2.set_xlabel("Cumulative share of LLC entities")
    ax2.set_ylabel("Cumulative share of land value")
    ax2.xaxis.set_major_formatter(mtick.PercentFormatter(1.0))
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(1.0))
    fig.tight_layout()
    fig.savefig(FIGS / "vacant_concentration.pdf")
    plt.close(fig)
    return t


def fig_tax_shift(sectors: pd.DataFrame) -> None:
    head = sectors[sectors["analysis_category"].isin(HEADLINE)]
    piv = (head.pivot(index="analysis_category", columns="owner_sector",
                      values="tax_change").fillna(0.0) / 1e6)
    piv = piv.reindex([c for c in HEADLINE if c in piv.index][::-1])
    fig, ax = plt.subplots(figsize=(6.5, 2.9))
    cols = [c for c in ["Individual", "Business / investor entity",
                        "Institutional / nonprofit", "Public agency"] if c in piv]
    y = np.arange(len(piv))
    h = 0.8 / len(cols)
    for i, col in enumerate(cols):
        ax.barh(y + (i - (len(cols) - 1) / 2) * h, piv[col], height=h,
                color=SECTOR_COLORS[col], label=col)
    ax.set_yticks(y, [_short(c) for c in piv.index], fontsize=7.5)
    ax.axvline(0, color="k", lw=0.8)
    ax.set_xlabel("Change in annual tax bill under the reform (\\$M)")
    ax.grid(axis="y", visible=False)
    ax.legend(fontsize=7, frameon=False, ncol=2, loc="lower right")
    fig.savefig(FIGS / "tax_shift.pdf")
    plt.close(fig)


def _add_basemap(ax) -> None:
    """Light web-tile basemap under the current lon/lat axes.

    Network-dependent: degrades to no basemap with a warning rather than failing the
    build, so the report still rebuilds offline.
    """
    try:
        import contextily as cx
        cx.add_basemap(ax, crs="EPSG:4326", source=cx.providers.CartoDB.PositronNoLabels,
                       attribution_size=4, zorder=0)
    except Exception as e:                                    # pragma: no cover
        print(f"  [warn] basemap skipped ({type(e).__name__}: {e})")


def fig_map(pts: pd.DataFrame) -> None:
    """Where LLC-owned vacant land and parking actually sit, by owner's mailing address."""
    llc = pts[pts["legal_form"] == "LLC"]
    fig, axes = plt.subplots(1, 2, figsize=(6.5, 4.2), sharex=True, sharey=True)
    for ax, (title, d) in zip(axes, [("All private owners", pts),
                                     ("LLC owners only", llc)]):
        if title.startswith("LLC"):
            # Local and out-of-state are drawn at near-equal marker size on purpose:
            # enlarging the 16.5% minority would visually overstate it.
            oos = d[d["owner_geography"] == "Out-of-state"]
            loc = d[d["owner_geography"] != "Out-of-state"]
            ax.scatter(loc["lon"], loc["lat"], s=1.3, color=C_PRIMARY, alpha=0.55,
                       linewidths=0, zorder=2, label="Local / regional")
            ax.scatter(oos["lon"], oos["lat"], s=2.0, color=C_ACCENT, alpha=0.95,
                       linewidths=0, zorder=3, label="Out-of-state")
            ax.legend(fontsize=6.5, frameon=False, loc="upper left", markerscale=4)
        else:
            ax.scatter(d["lon"], d["lat"], s=1.1, color=C_PRIMARY, alpha=0.5,
                       linewidths=0, zorder=2)
        ax.set_title(title, fontsize=8.5)
        ax.set_xticks([]); ax.set_yticks([])
        ax.grid(visible=False)
        for sp in ax.spines.values():
            sp.set_visible(False)
    for ax in axes:   # aspect + basemap last, so tile extent matches the final limits
        ax.set_aspect(1.0 / np.cos(np.deg2rad(float(pts["lat"].mean()))))
        _add_basemap(ax)
    fig.tight_layout()
    fig.savefig(FIGS / "map.pdf")
    plt.close(fig)


def _compact_usd(x: float) -> str:
    """$2.59B / $27.6M / $410K — keeps a column of mixed magnitudes readable."""
    x = float(x)
    if abs(x) >= 1e9:
        return f"${x / 1e9:,.2f}B"
    return f"${x / 1e6:,.1f}M" if abs(x) >= 1e6 else f"${x / 1e3:,.0f}K"


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
def tab_llc_share(shares: pd.DataFrame, geo: pd.DataFrame) -> None:
    d = _taxable(shares).sort_values("private_llc_land_share", ascending=False)
    out = pd.DataFrame({
        "Property type": [_tex(c) for c in d["analysis_category"]],
        "Parcels": [num(x) for x in d["private_parcels"]],
        "Land value": [_compact_usd(x) for x in d["private_land_value"]],
        "LLC": [pct(x * 100) for x in d["private_llc_land_share"]],
        "LLC (upper)": [pct(x * 100) for x in d["private_llc_land_share_upper"]],
        "Any business": [pct(x * 100) for x in d["private_business_land_share"]],
        "LLC out-of-state": [pct(_geo_share(geo, c, "Out-of-state") * 100)
                             for c in d["analysis_category"]],
    })
    save_table(TABLES / "llc_share.tex", out, col_format=f"{RX} r r r r r r")


def tab_geography(geo_all: pd.DataFrame, geo_llc: pd.DataFrame,
                  shares: pd.DataFrame) -> None:
    cats = _taxable(shares)["analysis_category"]
    a, l = _geo_wide(geo_all), _geo_wide(geo_llc)
    keep = [c for c in a.index if c in set(cats) and c in l.index]
    a, l = a.loc[keep], l.loc[keep]
    order = a["Out-of-state"].sort_values(ascending=False).index
    out = pd.DataFrame({
        "Property type": [_tex(c) for c in order],
        "All: in-city": [pct(a.loc[c, "In-city (Philadelphia)"] * 100) for c in order],
        "All: out-of-state": [pct(a.loc[c, "Out-of-state"] * 100) for c in order],
        "LLC: in-city": [pct(l.loc[c, "In-city (Philadelphia)"] * 100) for c in order],
        "LLC: out-of-state": [pct(l.loc[c, "Out-of-state"] * 100) for c in order],
    })
    save_table(TABLES / "geography.tex", out, col_format=f"{RX} r r r r")


def tab_vacant_sector(sectors: pd.DataFrame) -> None:
    d = sectors[sectors["analysis_category"] == VACANT].copy()
    d = d.sort_values("land_value", ascending=False)
    out = pd.DataFrame({
        "Owner type": [text(s) for s in d["owner_sector"]],
        "Parcels": [num(x) for x in d["parcels"]],
        "Land value": [_compact_usd(x) for x in d["land_value"]],
        "Share of land value": [pct(x * 100) for x in d["land_value_share"]],
        "Tax change": [_compact_usd(x) for x in d["tax_change"]],
    })
    save_table(TABLES / "vacant_sector.tex", out, col_format=f"{RX} r r r r")


def tab_top_entities(ent: pd.DataFrame, n: int = 15) -> None:
    d = ent.head(n)
    out = pd.DataFrame({
        # Owner strings are reproduced exactly as the assessor records them (uppercase);
        # title-casing invents capitalisation the source does not have ("Ols", "Bw").
        "LLC entity": [text(s) for s in d["entity_label"]],
        "Vacant parcels": [num(x) for x in d["parcels"]],
        "Names": [num(x) for x in d["constituent_names"]],
        "Land value": [_compact_usd(x) for x in d["land_value"]],
        "Tax change": [_compact_usd(x) for x in d["tax_change"]],
        "Mails from": [text(s).replace(" (Philadelphia)", "") for s in d["primary_geography"]],
    })
    save_table(TABLES / "top_entities.tex", out, col_format=f"{RX} r r r r l")


def tab_universe(rec: pd.DataFrame) -> None:
    out = pd.DataFrame({
        "Universe": [text(s) for s in rec["universe"]],
        "Comparison source": [text(s) for s in rec["source_b"]],
        "This study": [num(x) for x in rec["count_a"]],
        "Comparison": [num(x) for x in rec["count_b"]],
        "Overlap": [num(x) for x in rec["overlap"]],
        "Jaccard": [f"{x:.2f}" for x in rec["jaccard"]],
    })
    save_table(TABLES / "universe.tex", out, col_format=f"l {RX} r r r r")


def tab_precision(prec: pd.DataFrame) -> None:
    d = prec.sort_values("precision", ascending=False)
    out = pd.DataFrame({
        "Predicted owner form": [text(s) for s in d["predicted_form"]],
        "Sampled": [num(x) for x in d["sampled"]],
        "Correct": [num(x) for x in d["correct"]],
        "Precision": [pct(x * 100) for x in d["precision"]],
    })
    save_table(TABLES / "precision.tex", out, col_format=f"{RX} r r r")


# --------------------------------------------------------------------------- #
def main() -> None:
    S, D = _load()
    shares, sectors = D["llc_share_by_category"], D["ownership_by_category"]
    geo_llc, geo_all = D["llc_geography_by_category"], D["owner_geography_by_category"]
    ent_v, rec, prec = D["llc_entities_vacant"], D["universe_reconciliation"], D["classifier_precision"]
    robust, oos_addr = D["robustness_opa_vs_lycd"], D["out_of_state_mail_addresses"]
    pts = D["headline_parcel_points"]

    fig_llc_share(shares)
    fig_absentee_scatter(shares, geo_llc, S["city_llc_oos_land_share"])
    fig_llc_geography(geo_llc)
    fig_owner_sector(sectors)
    tiers = fig_vacant_concentration(ent_v)
    fig_tax_shift(sectors)
    fig_map(pts)

    tab_llc_share(shares, geo_llc)
    tab_geography(geo_all, geo_llc, shares)
    tab_vacant_sector(sectors)
    tab_top_entities(ent_v)
    tab_universe(rec)
    tab_precision(prec)

    vac_sec = sectors[sectors["analysis_category"] == VACANT].set_index("owner_sector")
    park = shares[shares["analysis_category"].isin(PARKING)]
    tax = _taxable(shares)
    rank = tax.sort_values("private_llc_land_share", ascending=False)["analysis_category"].tolist()
    single = ent_v[ent_v["parcels"] == 1]
    big = ent_v[ent_v["parcels"] >= 50]

    H = Headlines(prefix=PREFIX, out_path=TABLES / "headlines.tex")
    # Scope
    H.add("TaxYear", S["tax_year"], lambda x: str(int(x)))
    H.add("TotalParcels", S["total_parcels"], num)
    H.add("Categories", S["geography_categories_covered"], num)
    # Headline ownership
    H.add("VacantLlcShare", S["vacant_llc_land_share"] * 100, pct)
    H.add("VacantLlcShareUpper", S["vacant_llc_land_share_upper"] * 100, pct)
    H.add("VacantLlcParcelShare", S["vacant_llc_parcel_share"] * 100, pct)
    H.add("VacantBusinessShare", S["vacant_business_land_share"] * 100, pct)
    H.add("SfrLlcShare", S["sfr_llc_land_share"] * 100, pct)
    H.add("VacantVsSfrRatio", S["vacant_vs_sfr_ratio"], ratio)
    H.add("IndustrialLlcShare", S["industrial_llc_land_share"] * 100, pct)
    H.add("CommercialLlcShare",
          float(shares.loc[shares["analysis_category"] == "Commercial",
                           "private_llc_land_share"].iloc[0]) * 100, pct)
    H.add("LargeMfLlcShare", S["large_mf_llc_land_share"] * 100, pct)
    H.add("ParkingCommLlcShare", S["parking_comm_llc_land_share"] * 100, pct)
    H.add("ParkingNoncommLlcShare", S["parking_noncomm_llc_land_share"] * 100, pct)
    H.add("GarageLlcShare", S["garage_llc_land_share"] * 100, pct)
    H.add("VacantLlcRank", rank.index(VACANT) + 1, lambda x: f"{int(x)}")
    H.add("TaxableCategories", len(tax), num)
    # Vacant land: individuals vs entities
    H.add("VacantIndividualParcels", vac_sec.loc["Individual", "parcels"], num)
    H.add("VacantBusinessParcels", vac_sec.loc["Business / investor entity", "parcels"], num)
    H.add("VacantIndividualLandShare", vac_sec.loc["Individual", "land_value_share"] * 100, pct)
    H.add("VacantBusinessLandShare",
          vac_sec.loc["Business / investor entity", "land_value_share"] * 100, pct)
    # Universe / public holdings
    H.add("VpParcels", S["vacant_parking_parcels"], num)
    H.add("VpPrivateParcels", S["vacant_parking_private_parcels"], num)
    H.add("VpPublicParcels", S["vacant_parking_public_parcels"], num)
    H.add("VpPublicShare", S["vacant_parking_public_parcel_share"] * 100, pct)
    H.add("ParkingCategories", len(park), num)
    # Geography
    H.add("CityAllIncity", S["city_all_incity_land_share"] * 100, pct)
    H.add("CityAllOos", S["city_all_oos_land_share"] * 100, pct)
    H.add("CityLlcIncity", S["city_llc_incity_land_share"] * 100, pct)
    H.add("CityLlcOos", S["city_llc_oos_land_share"] * 100, pct)
    H.add("VacantLlcOos", S["vacant_llc_oos_land_share"] * 100, pct)
    H.add("SfrLlcOos", S["sfr_llc_oos_land_share"] * 100, pct)
    H.add("CommercialLlcOos", S["commercial_llc_oos_land_share"] * 100, pct)
    H.add("VpLlcIncityShare", S["incity_land_share_of_llc"] * 100, pct)
    H.add("VpLlcOosShare", S["oos_land_share_of_llc"] * 100, pct)
    H.add("VpLlcEntities", S["llc_vp_entities"], num)
    H.add("VpLlcIncityEntities", S["incity_entities"], num)
    H.add("VpLlcOosEntities", S["oos_entities"], num)
    H.add("VpLlcParcels", S["llc_vp_parcels"], num)
    H.add("VpLlcTaxChangeM", S["llc_vp_tax_change"] / 1e6, lambda x: usd_m(x, 1))
    # Mail-drop test
    H.add("DelawareParcels", S["delaware_parcels"], num)
    H.add("OosAddresses", S["oos_distinct_addresses"], num)
    H.add("OosMaxNames", S["oos_max_names_at_one_address"], num)
    H.add("OosTopTenShare", S["oos_top10_address_land_share"] * 100, pct)
    H.add("OosTopN", S["oos_top_n"], num)
    H.add("CityOosAddresses", S["city_oos_distinct_addresses"], num)
    H.add("CityOosMaxNames", S["city_oos_max_names_at_one_address"], num)
    # "NEW YORK NY" -> "New York, NY" (title-casing alone gives "New York Ny").
    _c = str(oos_addr.iloc[0]["mailing_city_state"]).rsplit(" ", 1)
    H.add("TopOosCity", f"{_c[0].title()}, {_c[1].upper()}" if len(_c) == 2 else _c[0], text)
    # Vacant-land entities
    H.add("VacantEntities", len(ent_v), num)
    H.add("VacantEntityParcels", ent_v["parcels"].sum(), num)
    H.add("VacantEntityLandM", ent_v["land_value"].sum() / 1e6, lambda x: usd_m(x, 0))
    H.add("VacantSingleParcelEntityShare", len(single) / len(ent_v) * 100, pct)
    H.add("VacantSingleParcelLandShare",
          single["land_value"].sum() / ent_v["land_value"].sum() * 100, pct)
    H.add("VacantBigEntities", len(big), num)
    H.add("VacantBigLandShare", big["land_value"].sum() / ent_v["land_value"].sum() * 100, pct)
    H.add("VacantTopEntityShown", 15, num)
    # Quality
    H.add("ClassifierSample", prec["sampled"].sum(), num)
    H.add("LlcPrecision", float(prec.loc[prec["predicted_form"] == "LLC", "precision"].iloc[0]) * 100, pct)
    H.add("OtherBusinessPrecision",
          float(prec.loc[prec["predicted_form"] == "Other business", "precision"].iloc[0]) * 100, pct)
    H.add("TruncationWidthOne", S["truncation_widths"][0], num)
    H.add("TruncationWidthTwo", S["truncation_widths"][1], num)
    for label, key in [("VacantLandUse", ("Vacant land", "City Land Use 2025 (c_dig2=91)")),
                       ("VacantLandI", ("Vacant land", "L&I Vacant Indicators")),
                       ("ParkingLandUse", ("Surface parking", "City Land Use 2025 (c_dig3=514)")),
                       ("ParkingOpa", ("Surface parking", "surface_parking_opa.gpq (orphan)"))]:
        r = rec[(rec["universe"] == key[0]) & (rec["source_b"] == key[1])].iloc[0]
        H.add(f"Jaccard{label}", r["jaccard"], lambda x: f"{float(x):.2f}")
        H.add(f"Count{label}", r["count_b"], num)
    H.add("ParkingOpaCount", int(rec[(rec["universe"] == "Surface parking")]["count_a"].iloc[0]), num)
    H.add("VacantOpaCount", int(rec[(rec["universe"] == "Vacant land")]["count_a"].iloc[0]), num)
    vr = robust[robust["analysis_category"] == VACANT].iloc[0]
    H.add("RobustVacantDiffPp", vr["abs_diff_pp"], lambda x: f"{float(x):.1f} points")
    H.add("RobustMaxDiffPp", robust["abs_diff_pp"].max(), lambda x: f"{float(x):.1f} points")
    H.add("RobustMaxCategory", _short(robust.iloc[0]["analysis_category"]), text)
    H.write()
    H.to_json(PAPER / "values.json")

    print(f"  figures -> {FIGS}")
    print(f"  tables  -> {TABLES}")
    print(f"  {len(H._vals)} headline macros -> {H.out_path}")
    print("\nPortfolio tiers (vacant-land LLC entities):")
    print(tiers[["entities", "parcels", "entity_share", "land_share"]].to_string())


if __name__ == "__main__":
    main()
