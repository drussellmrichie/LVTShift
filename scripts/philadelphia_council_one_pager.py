"""
Philadelphia — numbers and map for the City Council candidate one-pager on a land value tax.

Everything printed on the one-pager is emitted here from the tracked TY2026 parcel cache and the
S5 land surface, so the flyer carries no hand-typed figure.

The model, in one line: hold each parcel's OPA total assessment fixed, re-split it into a land
component taken from the S5 paired-sales surface and a residual building, then tax land at four
times the building rate, revenue-neutral. Assessments do not move; only the split, and therefore
the rate mix, does. This is `lvt.philadelphia.reallocate_land_within_total` (the draft Sec. 2-305
land-assessment reading) with a split rate stacked on top -- the same construction as
`scripts/philadelphia_abatement_phase_in.py`'s `lvt_phase_in` scenario at its final year, so the
flyer and the transition analysis describe one reform.

Contrast the revaluation reading used by the `model_lycd*.ipynb` split-rate notebooks and by
`philadelphia_equity_by_land_surface.py`, which holds OPA's BUILDING fixed and lets the total rise
with the larger land estimate. That reading needs a citywide rollback and moves every bill; this
one cannot move a bill whose exemption does not depend on the land/building split.

Horizon: the long run, after today's 10-year construction abatements have run out. Existing
abatements are honored while they last -- `philadelphia_abatement_phase_in.py` models that
transition, and this script reads its panel for the payback figures. Modeling the reform against a
baseline that still carries 14k abatements would credit the reform with revenue that current law
already collects a few years later.

Outputs (analysis/political/philadelphia_council_one_pager/, gitignored):
    numbers.json         every figure the one-pager prints
    gathered_light.png   print variant of the vacant + parking gathered-square map
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lvt.philadelphia import (  # noqa: E402
    expand_abatement_cohort, parcel_cache_path, reallocate_land_within_total, split_zero_building_parcels,
    tax_year_params,
)

TAX_YEAR = 2026
RATIO = 4.0
DATA = REPO_ROOT / "analysis/data"
CACHE_DIR = REPO_ROOT / "cities/philadelphia/data"
OUT = REPO_ROOT / "analysis/political/philadelphia_council_one_pager"
SURFACE_EXPORT = DATA / f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s5.csv"
PHASE_IN_PANEL = DATA / "philadelphia_abatement_phase_in_panel.parquet"
GATHERED_JSON = REPO_ROOT / "analysis/reports/philadelphia/vacant_parking_gathered.json"
READ = dict(encoding="utf-8", encoding_errors="replace")

CATEGORY_MAP = {
    "1": "Single Family Residential", "2": "Small Multi-Family (2-4 units)", "3": "Mixed Use",
    "4": "Commercial", "5": "Industrial", "6": "Vacant Land", "7": "Other Commercial",
    "8": "Other Residential", "9": "Hotel", "10": "Office / Commercial Condo", "11": "Other",
    "12": "Vacant Land", "13": "Vacant Land", "14": "Large Multi-Family (5+ units)",
    "15": "Retail / General Commercial",
}
GENUINE_VACANT_CODES = {"6", "12", "13"}
HOMES = {"Single Family Residential", "Small Multi-Family (2-4 units)", "Other Residential"}

PAPER_CITY_FILL = "#E4E0D4"
PAPER_CITY_EDGE = "#1F3A68"
PAPER_VACANT = "#F2B01E"
PAPER_PARKING = "#D8432F"
PAPER_INK = "#15202E"


def property_group(category: str) -> str:
    if category in HOMES:
        return "homes"
    if category.startswith("Vacant Land"):
        return "vacant land"
    if category.startswith("Large Multi"):
        return "large multifamily"
    return "commercial/mixed/other"


def load_parcels() -> pd.DataFrame:
    """Parcel cache with the S5 land value and block-group demographics joined on."""
    import geopandas as gpd

    g = gpd.read_parquet(parcel_cache_path(TAX_YEAR, CACHE_DIR)).drop(columns="geometry")
    g["category_code"] = pd.to_numeric(g.category_code, errors="coerce").astype("Int64").astype(str)
    g["parcel_id"] = g.parcel_number.astype(str).str.lstrip("0").astype("Int64")

    s = pd.read_csv(SURFACE_EXPORT, usecols=["parcel_id", "lycd_land_value", "land_surface_source",
                                             "std_geoid", "median_income", "minority_pct", "black_pct"], **READ)
    # A handful of parcel_ids name more than one physical parcel with genuinely different
    # attributes (cities/philadelphia/CLAUDE.md). The cache and the export cannot be joined by row
    # order either, so those ids are dropped from both sides rather than matched arbitrarily.
    n = len(g)
    ambiguous = set(s.parcel_id[s.parcel_id.duplicated(keep=False)]) | set(g.parcel_id[g.parcel_id.duplicated(keep=False)])
    dropped = int(g.parcel_id.isin(ambiguous).sum())
    assert dropped <= 50, f"{dropped:,} parcels share an ambiguous parcel_id; too many to drop silently"
    g = g[~g.parcel_id.isin(ambiguous)]
    g = g.merge(s[~s.parcel_id.isin(ambiguous)].rename(columns={"lycd_land_value": "s5_land"}),
                on="parcel_id", how="inner", validate="one_to_one")
    assert len(g) >= 0.999 * n, f"S5 land values cover only {len(g):,} of {n:,} cached parcels"
    print(f"{len(g):,} parcels ({dropped} dropped for an ambiguous parcel_id)")
    return g.reset_index(drop=True)


def classify(g: pd.DataFrame):
    """PROPERTY_CATEGORY and the abated cohort, following cities/philadelphia/CLAUDE.md's overrides."""
    cap = tax_year_params(TAX_YEAR).homestead_exemption
    category = g.category_code.map(CATEGORY_MAP).fillna("Other")
    category[g.taxable_building <= 0] = "Vacant Land"                                  # Override 1
    z = split_zero_building_parcels(g, category, cap, CATEGORY_MAP,                     # Override 2
                                    genuine_vacant_codes=GENUINE_VACANT_CODES)
    category = z.category
    vacant_code = g.category_code.isin(GENUINE_VACANT_CODES)
    category[vacant_code & (g.taxable_building > 0)] = "Improved Vacant Land"          # Override 3
    full_exempt = (g.taxable_land <= 0) & (g.taxable_building <= 0)
    category[full_exempt] = category[full_exempt].str.replace(r"( — Exempt)?$", " — Exempt", n=1, regex=True)

    ex = expand_abatement_cohort(g, category, z.abated, TAX_YEAR, data_dir=CACHE_DIR)   # Override 3.5
    print(ex.describe())
    # The long-run world has no abatement, so an abated parcel wears its own OPA category again.
    category = g.category_code.map(CATEGORY_MAP).fillna("Other").where(
        ex.abated, ex.category.where(~ex.abated, other=None))
    category = category.fillna(ex.category)
    return category, ex.abated.to_numpy(), ex.restored_building, full_exempt.to_numpy()


def expire_abatements(g: pd.DataFrame, abated: np.ndarray, restored_building: pd.Series) -> pd.DataFrame:
    """The post-abatement world: the improvement is back on the taxable roll and the relief is gone.

    Only the abatement's own dollars are removed. A parcel's other relief -- homestead, partial
    institutional -- is untouched, and every non-abated parcel is returned unchanged. Abated
    parcels carry no Homestead Exemption today (they are ineligible until the abatement ends), and
    this does not grant them one, so their post-abatement bill is if anything overstated.
    """
    out = g.copy()
    b = restored_building.to_numpy()
    out.loc[abated, "taxable_building"] = b[abated]
    out.loc[abated, "exempt_building"] = 0.0
    return out


def solve_split_rate(land: np.ndarray, building: np.ndarray, revenue: float, ratio: float):
    """Revenue-neutral millages with land at `ratio` times the building rate."""
    building_mills = revenue / (ratio * land.sum() + building.sum()) * 1000
    return ratio * building_mills, building_mills


def uncap_bare_land(alloc, post: pd.DataFrame, taxable: np.ndarray):
    """Take the sales-based land value whole on parcels that carry no building.

    `reallocate_land_within_total` caps land at the parcel's own total, which for a bare lot IS
    its land: the re-split can then never assess such a lot above what OPA already says, and where
    the sales estimate is LOWER it books the shortfall as `alloc_building` -- a building line on a
    lot with no building. Under the flat rate that function models this is harmless (the two lines
    sum to the same total, so the bill is identical, which is the sense in which its docstring says
    vacant parcels never move). Stacking a split rate on top is what makes it bite: measured on
    TY2026, 14,831 of 30,564 taxable vacant lots would have a phantom $0.82B taxed at the building
    rate, and the other half would have their under-assessment frozen in place.

    So the cap is lifted exactly where there is no improvement to hold a total fixed against. For a
    bare lot "hold the total fixed" and "value the land at what it sells for" are the same
    instruction, and a total that disagrees with the sales evidence is an assessment error, not a
    constraint. Nothing with a building on it is touched, and no building is ever revalued.

    The parcel's own exemption is carried in dollars (144 bare parcels have one, nearly all partial
    institutional relief, which is relief against total value and so does not follow the split).
    """
    land = alloc.alloc_taxable_land.to_numpy().copy()
    building = alloc.alloc_taxable_building.to_numpy().copy()
    gross_total = (post.taxable_land + post.exempt_land + post.taxable_building + post.exempt_building).to_numpy()
    bare = taxable & ((post.taxable_building + post.exempt_building).to_numpy() <= 1.0)
    exempt_dollars = (gross_total - alloc.reconstructed_taxable_total.to_numpy()).clip(min=0)
    land[bare] = (post.s5_land.to_numpy()[bare] - exempt_dollars[bare]).clip(min=0)
    building[bare] = 0.0
    return land, building, bare


def strata(g: pd.DataFrame, homes: np.ndarray) -> pd.DataFrame:
    """Block-group quintiles of income and non-white share, cut over taxable homes."""
    inc = g.median_income.where(g.median_income > 0)
    e_inc = np.unique(inc[homes].quantile([0, .2, .4, .6, .8, 1]).to_numpy())
    e_min = np.unique(g.minority_pct[homes].quantile([0, .2, .4, .6, .8, 1]).to_numpy())
    return pd.DataFrame({
        "inc_q": pd.cut(inc, e_inc, include_lowest=True, labels=["poorest", "Q2", "Q3", "Q4", "richest"]),
        "min_q": pd.cut(g.minority_pct, e_min, include_lowest=True,
                        labels=["whitest", "Q2", "Q3", "Q4", "most non-white"]),
    }), dict(income_poorest_top=float(e_inc[1]), income_richest_bottom=float(e_inc[4]),
             nonwhite_whitest_top=float(e_min[1]), nonwhite_most_bottom=float(e_min[4]))


def bill_stats(cur: np.ndarray, new: np.ndarray, mask: np.ndarray) -> dict:
    k = mask & (cur > 0)
    c, n = cur[k], new[k]
    return dict(parcels=int(k.sum()), pay_less_pct=float(100 * (n < c).mean()),
                aggregate_change_pct=float(100 * (n.sum() / c.sum() - 1)),
                aggregate_change_musd=float((n.sum() - c.sum()) / 1e6),
                median_change_usd=float(np.median(n - c)), median_current_bill_usd=float(np.median(c)))


def payback() -> dict:
    """How long an abated owner takes to recoup, from the phase-in panel's own scenarios.

    `lvt_phase_in` there is this same within-total re-split with the ratio rising in equal steps to
    4:1, against `status_quo` (today's split and flat rate, abatements expiring on schedule), so
    the transition and the long-run flyer describe one reform.
    """
    p = pd.read_parquet(PHASE_IN_PANEL)
    schedules = ["old_flat_100", "old_flat_partial", "new_graduated_residential", "new_flat_90_commercial"]
    p = p[p.schedule_type.isin(schedules)].sort_values(["parcel_number", "t"])
    p["diff"] = p.lvt_phase_in - p.status_quo

    def one(g):
        t, d, run = g.t.to_numpy(), g["diff"].to_numpy(), g.running.to_numpy()
        cum = np.cumsum(d)                                        # cumulative dollars vs status quo
        expiry = int(t[run].max()) + 1 if run.any() else 0        # first tax year with no abatement
        steady = float(d[-1])                                     # annual difference at 4:1, unabated
        if cum.max() <= 1.0:
            return pd.Series(dict(expiry_t=expiry, steady_diff=steady, behind=False,
                                  peak_shortfall=0.0, extra_while_abated=0.0, years_after_expiry=np.nan))
        crossings = np.where((cum <= 0) & (t > int(cum.argmax())))[0]
        if len(crossings):                                        # interpolate within the year it crosses
            i = crossings[0]
            be = float(t[i - 1] + cum[i - 1] / (cum[i - 1] - cum[i]))
        elif steady < -1.0:                                       # still behind at t=15, extrapolate
            be = float(t[-1] + cum[-1] / -steady)
        else:
            be = np.inf                                           # pays more every year; never recoups
        return pd.Series(dict(expiry_t=expiry, steady_diff=steady, behind=True,
                              peak_shortfall=float(cum.max()),
                              extra_while_abated=float(d[run & (t >= 1)].sum()),
                              years_after_expiry=be - expiry))

    r = p.groupby("parcel_number").apply(one, include_groups=False)
    behind = r[r.behind.astype(bool)]
    recoups = behind[np.isfinite(behind.years_after_expiry)]
    return dict(
        abated_parcels=int(len(r)), phase_in_years=10, reform_starts_tax_year=2027,
        never_behind_pct=float(100 * (~r.behind.astype(bool)).mean()),
        behind_then_recoups_pct=float(100 * len(recoups) / len(r)),
        never_recoups_pct=float(100 * np.isinf(behind.years_after_expiry).sum() / len(r)),
        after_expiry_pay_less_pct=float(100 * (r.steady_diff < 0).mean()),
        after_expiry_median_annual_usd=float(r.steady_diff.median()),
        recoup_extra_while_abated_median_usd=float(recoups.extra_while_abated.median()),
        recoup_extra_while_abated_p90_usd=float(recoups.extra_while_abated.quantile(.9)),
        # Negative = whole before the abatement even ends; the phase-in is slower than the expiries.
        recoup_years_after_expiry_median=float(recoups.years_after_expiry.median()),
        recoup_years_after_expiry_p75=float(recoups.years_after_expiry.quantile(.75)),
        recoup_years_after_expiry_p90=float(recoups.years_after_expiry.quantile(.9)),
        recoup_whole_before_expiry_pct=float(100 * (recoups.years_after_expiry <= 0).sum() / len(r)),
        abatements_ended_by_2031_pct=float(100 * (r.expiry_t <= 5).mean()),
        last_expiry_tax_year=int(2026 + r.expiry_t.max()),
    )


def render_map() -> None:
    import geopandas as gpd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    g = json.loads(GATHERED_JSON.read_text())
    side, vac_share = g["square_side_ft"], g["vacant_share_of_total"]
    tracts = gpd.read_parquet(CACHE_DIR / "census_tracts.gpq")
    if tracts.crs is None:
        tracts = tracts.set_crs("EPSG:4326")
    city = tracts.to_crs("EPSG:2272").dissolve()
    city["geometry"] = city.geometry.buffer(0)
    cx, cy = float(city.geometry.iloc[0].centroid.x), float(city.geometry.iloc[0].centroid.y)
    x0, y0 = cx - side / 2, cy - side / 2

    minx, miny, maxx, maxy = city.total_bounds
    pad = (maxx - minx) * 0.01
    w, h = (maxx - minx) + 2 * pad, (maxy - miny) + 2 * pad
    fig = plt.figure(figsize=(8, 8 * h / w), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    city.plot(ax=ax, facecolor=PAPER_CITY_FILL, edgecolor=PAPER_CITY_EDGE, linewidth=1.6, zorder=1)
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_axis_off()
    vac_h = side * vac_share
    ax.add_patch(Rectangle((x0, y0), side, vac_h, facecolor=PAPER_VACANT, edgecolor="none", zorder=5))
    ax.add_patch(Rectangle((x0, y0 + vac_h), side, side - vac_h, facecolor=PAPER_PARKING, edgecolor="none", zorder=5))
    ax.add_patch(Rectangle((x0, y0), side, side, fill=False, edgecolor=PAPER_INK, linewidth=2.0, zorder=6))
    fig.savefig(OUT / "gathered_light.png", transparent=True)
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    params = tax_year_params(TAX_YEAR)
    millage = params.combined_mills

    g = load_parcels()
    category, abated, restored_building, full_exempt = classify(g)
    post = expire_abatements(g, abated, restored_building)

    r = reallocate_land_within_total(post, new_land_col="s5_land", homestead_cap=params.homestead_exemption)
    print(r.describe())

    base_total = r.reconstructed_taxable_total.to_numpy()   # the same rule on OPA's own land
    taxable = ~full_exempt
    land, building, bare = uncap_bare_land(r, post, taxable)

    # A parcel with a building on it keeps its total: the reform can only change how that total is
    # split, so the only such bills that move are the ones whose relief depends on the split.
    built = taxable & ~bare
    identical = np.isclose(land + building, base_total, atol=1.0)
    print(f"{bare.sum():,} bare lots revalued from sales; no building reassessed. "
          f"Taxable total unchanged on {identical[built].mean():.2%} of the {built.sum():,} taxable "
          f"parcels that have a building ({(~identical & built).sum():,} move, split-dependent relief)")

    current = base_total * millage / 1000
    revenue = float(current.sum())
    land_mills, building_mills = solve_split_rate(land, building, revenue, RATIO)
    new = (land * land_mills + building * building_mills) / 1000
    assert abs(new.sum() / revenue - 1) < 1e-9, "split-rate solve is not revenue-neutral"

    homes = category.isin(HOMES).to_numpy() & taxable
    groups = category.map(property_group)
    q, edges = strata(g, homes)

    by_group = (pd.DataFrame(dict(g=groups, cur=current, new=new))[taxable | (new > 0) | (current > 0)]
                .groupby("g").agg(cur=("cur", "sum"), new=("new", "sum"), parcels=("cur", "size")))
    by_group["change_pct"] = 100 * (by_group.new / by_group.cur - 1)
    by_group["change_musd"] = (by_group.new - by_group.cur) / 1e6

    profile = {}
    for col in ("inc_q", "min_q"):
        d = pd.DataFrame(dict(level=q[col], cur=current, new=new))[homes & (current > 0)]
        profile[col] = {str(k): dict(homes_pct=float(100 * (s.new.sum() / s.cur.sum() - 1)),
                                     pay_less_pct=float(100 * (s.new < s.cur).mean()),
                                     median_change_usd=float(np.median(s.new - s.cur)))
                        for k, s in d.groupby("level", observed=True)}

    # The ratio is the only lever this reform has, so price it: with the total fixed, a parcel pays
    # less exactly when its land share sits below the citywide average, and the ratio sets how hard
    # that bites. Reported so the flyer's 4:1 is a choice with a stated cost, not a default.
    sweep = {}
    for ratio in (1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
        lm, bm = solve_split_rate(land, building, revenue, ratio)
        alt = (land * lm + building * bm) / 1000
        s = bill_stats(current, alt, homes)
        s.update(land_rate_pct=float(lm / 10), building_rate_pct=float(bm / 10),
                 vacant_change_pct=float(100 * (alt[(groups == "vacant land").to_numpy()].sum()
                                                / current[(groups == "vacant land").to_numpy()].sum() - 1)))
        sweep[f"{ratio:g}:1"] = s

    numbers = dict(
        as_of=pd.Timestamp.today().strftime("%Y-%m-%d"),
        source="LVTShift scripts/philadelphia_council_one_pager.py",
        model=dict(tax_year=TAX_YEAR, ratio=RATIO, land_surface="S5 paired sales",
                   construction=("OPA total held fixed where there is a building: land = min(S5, total), "
                                 "building = total - land. On bare lots the cap is lifted and land = S5."),
                   horizon="after today's 10-year abatements have expired",
                   bare_lots_revalued=int(bare.sum()),
                   built_parcels=int(built.sum()),
                   built_total_unchanged_pct=float(100 * identical[built].mean())),
        rates=dict(current_rate_pct=float(millage / 10), land_rate_pct=float(land_mills / 10),
                   building_rate_pct=float(building_mills / 10),
                   building_rate_cut_pct=float(100 * (building_mills / millage - 1)),
                   levy_busd=float(revenue / 1e9)),
        homes=bill_stats(current, new, homes),
        all_taxable=bill_stats(current, new, taxable),
        by_property_group=by_group.round(2).to_dict("index"),
        homes_profile=profile,
        ratio_sweep=sweep,
        quintile_edges=edges,
        transition=payback(),
        vacant_and_parking=json.loads(GATHERED_JSON.read_text()),
    )
    (OUT / "numbers.json").write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    render_map()
    print(json.dumps({k: numbers[k] for k in
                      ("rates", "homes", "by_property_group", "homes_profile", "transition")}, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
