"""
Philadelphia — numbers and map for the City Council candidate one-pager on a land value tax.

Everything printed on the one-pager is emitted here from the tracked TY2026 parcel cache and the
S5 land surface, so the flyer carries no hand-typed figure.

The model, in one line: hold each parcel's OPA total assessment fixed, re-split it into a land
component taken from the S5 paired-sales surface and a residual building, then tax land at four
times the building rate, revenue-neutral. Assessments do not move; only the split, and therefore
the rate mix, does. This is `lvt.philadelphia.reallocate_land_within_total` (the draft Sec. 2-305
land-assessment reading) with a split rate stacked on top, and bare lots valued at S5 whole
(`lvt.philadelphia.uncap_bare_land`). `scripts/philadelphia_abatement_phase_in.py`, run with the
matching options, models the same reform year by year; `payback()` reads that run and checks its
final-year rates against this script's.

Contrast the revaluation reading used by the `model_lycd*.ipynb` split-rate notebooks and by
`philadelphia_equity_by_land_surface.py`, which holds OPA's BUILDING fixed and lets the total rise
with the larger land estimate. That reading needs a citywide rollback and moves every bill; this
one cannot move a bill whose exemption does not depend on the land/building split.

Horizon: the long run, after today's 10-year construction abatements have run out. Existing
abatements are honored while they last -- `philadelphia_abatement_phase_in.py` models that
transition, and this script reads its panel for the payback figures. Modeling the reform against a
baseline that still carries 14k abatements would credit the reform with revenue that current law
already collects a few years later.

The Homestead Exemption decides who among homeowners gains. At one rate its line does not matter;
under a split rate it is worth `cap x building rate` when drawn building-first, which is what 53
Pa.C.S. Sec. 8583(c) requires, so the shift that cuts rentals' bills raises most owner-occupants'.
`--homestead-order` picks the order the headline figures use (default: the statute), and
`homestead_comparison` in numbers.json reports every order side by side. The payback figures follow
the flag, from a phase-in run built at the same order:

    python scripts/philadelphia_abatement_phase_in.py --homestead-order value_share --baseline rate --revalue-bare-lots
    python scripts/philadelphia_council_one_pager.py --homestead-order value_share

Outputs (analysis/political/philadelphia_council_one_pager/, gitignored):
    numbers.json         every figure the one-pager prints
    gathered_light.png   print variant of the vacant + parking gathered-square map
"""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from lvt.philadelphia import (  # noqa: E402
    COMMERCIAL_OTHER, HOMESTEAD_ORDERS, _decompose_exemptions, commercial_building_type, expand_abatement_cohort,
    parcel_cache_path, reallocate_land_within_total, split_zero_building_parcels, tax_year_params, uncap_bare_land,
    LARGE_TRACT_TREATMENTS,
    zoning_family,
)

TAX_YEAR = 2026
RATIO = 4.0
DATA = REPO_ROOT / "analysis/data"
CACHE_DIR = REPO_ROOT / "cities/philadelphia/data"
OUT = REPO_ROOT / "analysis/political/philadelphia_council_one_pager"
SURFACE_EXPORT = DATA / f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s5.csv"
SURFACE_SUPPORT = DATA / f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s5_support.json"   # written with the export
GATHERED_JSON = REPO_ROOT / "analysis/reports/philadelphia/vacant_parking_gathered.json"
OPA_ATTRIBUTES = REPO_ROOT / "analysis/ownership/philadelphia/opa_attributes.parquet"   # fetch_opa_attributes.py
COUNCIL_DISTRICTS = CACHE_DIR / "council_districts.gpq"     # cached by scripts/map_philadelphia_tax_changes.py
COUNCIL_DISTRICTS_SOURCE = "https://opendata.arcgis.com/datasets/9298c2f3fa3241fbb176ff1e84d33360_0.geojson"
FHFA_TRACTS = CACHE_DIR / "fhfa_land_share_by_tract.csv"    # see cities/philadelphia/model_lycd_refined_prototype.ipynb
PHASE_IN_BASIS = dict(baseline="rate", revalue_bare_lots=True)   # the phase-in options that match this script
# The phase-in's final-year rates may differ from this script's only through the two abated cohorts
# (see payback()); on TY2026 that moves them by under a tenth of a percent.
MAX_PHASE_IN_RATE_GAP_PCT = 0.5
COMMERCIAL_GROUP = "commercial/mixed/other"
MAX_OTHER_TAX_SHARE = 0.05       # the building-type rules must place 95% of the sector's tax
MIN_CELL_PARCELS = 10            # zoning x type cells smaller than this are left out of the cross-table
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
HOMESTEAD_LABELS = {
    "building_first": "off the building first, remainder off land (53 Pa.C.S. Sec. 8583(c), current law)",
    "land_first": "off land first, remainder off the building",
    "value_share": "in proportion to land and building value",
    "tax_share": f"in proportion to each line's share of the tax (land weighted {RATIO:g}:1)",
}

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
                                             "land_beyond_support", "land_surface_psf", "dor_area_sqft",
                                             "std_geoid", "median_income", "minority_pct", "black_pct"], **READ)
    s["land_beyond_support"] = s.land_beyond_support.astype(str).str.lower().eq("true")
    # What the surface would say if taken whole, kept only so the range can report it.
    s["s5_land_uncarried"] = (s.pop("land_surface_psf") * s.pop("dor_area_sqft")).clip(lower=0)
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


def surface_support() -> dict:
    """The surface's own statement of where its sales stop testing it (philly_open_avmkit's
    `land_surface_support.json`, written beside the export by the reassessment notebook)."""
    return json.loads(SURFACE_SUPPORT.read_text(encoding="utf-8"))


def shift(post: pd.DataFrame, taxable: np.ndarray, params, homestead_order: str, ratio: float = RATIO,
          land_col: str = "s5_land", large_tracts: str = "carry_opa"):
    """The reform at one homestead order and one rate ratio: taxable lines, today's bill, the new bill."""
    r = reallocate_land_within_total(post, new_land_col=land_col, homestead_cap=params.homestead_exemption,
                                     homestead_order=homestead_order, homestead_rate_ratio=ratio)
    base_total = r.reconstructed_taxable_total.to_numpy()   # the same rule on OPA's own land
    # A bare lot larger than the land sales can test keeps OPA's value (`uncap_bare_land`).
    land, building, bare = uncap_bare_land(
        r, post, taxable, land_col, beyond_support=post.land_beyond_support.to_numpy(),
        large_tracts=large_tracts, uncarried_land=post.s5_land_uncarried.to_numpy(),
        opa_level=surface_support()["reference_median_ratio_beyond_edge_still_vacant"])
    current = base_total * params.combined_mills / 1000
    revenue = float(current.sum())
    land_mills, building_mills = solve_split_rate(land, building, revenue, ratio)
    new = (land * land_mills + building * building_mills) / 1000
    assert abs(new.sum() / revenue - 1) < 1e-9, "split-rate solve is not revenue-neutral"
    return SimpleNamespace(r=r, base_total=base_total, land=land, building=building, bare=bare, current=current,
                           revenue=revenue, land_mills=land_mills, building_mills=building_mills, new=new)


def sector_totals(groups: pd.Series, taxable: np.ndarray, current: np.ndarray, new: np.ndarray) -> pd.DataFrame:
    """Each property group's totals, plus the share of its billed parcels that pay less and the median
    percentage change: those two barely move with the few very large bare tracts whose land value
    carries most of the dollar totals."""
    d = pd.DataFrame(dict(g=groups, cur=current, new=new))[taxable | (new > 0) | (current > 0)]
    by_group = d.groupby("g").agg(cur=("cur", "sum"), new=("new", "sum"), parcels=("cur", "size"))
    by_group["change_pct"] = 100 * (by_group.new / by_group.cur - 1)
    by_group["change_musd"] = (by_group.new - by_group.cur) / 1e6
    billed = d[d.cur > 0]
    by_group["pay_less_pct"] = billed.groupby("g")[["cur", "new"]].apply(lambda x: 100 * (x.new < x.cur).mean())
    by_group["median_change_pct"] = billed.groupby("g")[["cur", "new"]].apply(
        lambda x: 100 * float(np.median(x.new / x.cur - 1)))
    return by_group


def neighbourhood_profile(q: pd.DataFrame, current: np.ndarray, new: np.ndarray, mask: np.ndarray) -> dict:
    """Aggregate change and share paying less, by income and non-white-share quintile of block groups."""
    profile = {}
    for col in ("inc_q", "min_q"):
        d = pd.DataFrame(dict(level=q[col], cur=current, new=new))[mask & (current > 0)]
        profile[col] = {str(k): dict(homes_pct=float(100 * (s.new.sum() / s.cur.sum() - 1)),
                                     pay_less_pct=float(100 * (s.new < s.cur).mean()),
                                     median_change_usd=float(np.median(s.new - s.cur)))
                        for k, s in d.groupby("level", observed=True)}
    return profile


def cohort_stats(cur: np.ndarray, new: np.ndarray, mask: np.ndarray) -> dict:
    s = bill_stats(cur, new, mask)
    d = (new - cur)[mask & (cur > 0)]
    s.update(pay_more_pct=float(100 * (d > 0).mean()),
             median_increase_of_those_paying_more_usd=float(np.median(d[d > 0])) if (d > 0).any() else 0.0)
    return s


def owner_occupied_proxy(g: pd.DataFrame, homestead: np.ndarray, abated: np.ndarray) -> np.ndarray:
    """The phase-in script's proxy: a 1-4-unit home whose individual owner's mailing address is the home.

    It catches owner-occupants who never claimed the Homestead Exemption (roughly 237k claim it
    against roughly 344k owner-occupied units in the ACS). Reused, not re-derived, so the two
    scripts cannot disagree about who is an owner-occupant; its own agreement guard still runs.
    """
    from philadelphia_abatement_phase_in import _pid, owner_occupied

    df = pd.DataFrame(dict(parcel_number=_pid(g.parcel_number), owner_1=g.owner_1,
                           category_code=g.category_code, is_abatement=abated))
    occupied = owner_occupied(df, homestead)
    print(f"owner-occupancy proxy: {occupied.sum():,} parcels; agrees with the homestead on "
          f"{df.attrs['occupancy_agreement']:.1%} of homesteaded non-abated homes")
    return occupied


def house_bills(land, building, homestead: bool, order: str, params, land_mills: float, building_mills: float):
    """Today's and the reformed bill for made-up parcels, through the same library rule as the roll.

    Each is recorded as OPA records a homestead today (building first), then re-split at its own
    land value, so only the homestead's line under `order` changes.
    """
    cap = params.homestead_exemption
    land, building = np.atleast_1d(np.asarray(land, float)), np.atleast_1d(np.asarray(building, float))
    ex = np.where(homestead, np.minimum(cap, land + building), 0.0)
    off_building = np.minimum(ex, building)
    df = pd.DataFrame(dict(taxable_land=land - (ex - off_building), taxable_building=building - off_building,
                           exempt_land=ex - off_building, exempt_building=off_building,
                           homestead_exemption=np.where(homestead, cap, 0.0), new_land=land))
    r = reallocate_land_within_total(df, new_land_col="new_land", homestead_cap=cap,
                                     homestead_order=order, homestead_rate_ratio=RATIO)
    today = r.reconstructed_taxable_total.to_numpy() * params.combined_mills / 1000
    after = (r.alloc_taxable_land.to_numpy() * land_mills + r.alloc_taxable_building.to_numpy() * building_mills) / 1000
    return today, after


def typical_home(land: float, building: float, order: str, params, land_mills: float, building_mills: float) -> dict:
    """One house with the Homestead Exemption and the same house without it, plus each one's break-even.

    The break-even is the land share of a house of this total value below which it pays less; the
    house without the exemption breaks even at the same share whatever the order.
    """
    out = {}
    shares = np.linspace(0, 1, 2001)
    value = land + building
    for tag, hs in (("with_homestead", True), ("without_homestead", False)):
        today, after = house_bills(land, building, hs, order, params, land_mills, building_mills)
        t_grid, a_grid = house_bills(shares * value, (1 - shares) * value, hs, order, params, land_mills, building_mills)
        pays_more = a_grid >= t_grid
        out[tag] = dict(today_usd=float(today[0]), after_usd=float(after[0]), change_usd=float(after[0] - today[0]),
                        pays_less_below_land_share_pct=float(100 * (shares[pays_more.argmax()] if pays_more.any() else 1.0)))
    return out


def homestead_comparison(post, category, taxable, homes, groups, q, params, hs, occupied) -> dict:
    """Every homestead order side by side, for homestead recipients and for owner-occupants more widely."""
    sfr = (category == "Single Family Residential").to_numpy()
    cohorts = {
        "all_homes": homes, "homestead": homes & hs, "no_homestead": homes & ~hs,
        "owner_occupied": homes & occupied, "not_owner_occupied": homes & ~occupied,
        "single_family": homes & sfr, "two_to_four_units": homes & (category == "Small Multi-Family (2-4 units)").to_numpy(),
    }
    orders = {}
    for order in HOMESTEAD_ORDERS:
        s = shift(post, taxable, params, order)
        if order == HOMESTEAD_ORDERS[0]:
            # the typical homestead home is a fact about the land split, not about the order
            m = homes & sfr & (s.r.exemption_kind == "homestead").to_numpy() & (s.current > 0)
            house_land, house_building = float(np.median(s.r.alloc_land[m])), float(np.median(s.r.alloc_building[m]))
        only = homes & (s.r.exemption_kind == "homestead").to_numpy() & (s.current > 0)
        worth_today = ((s.r.alloc_land + s.r.alloc_building).to_numpy() - s.base_total) * params.combined_mills / 1000
        worth_after = ((s.r.alloc_land.to_numpy() - s.land) * s.land_mills
                       + (s.r.alloc_building.to_numpy() - s.building) * s.building_mills) / 1000
        sectors = sector_totals(groups, taxable, s.current, s.new)
        orders[order] = dict(
            rule=HOMESTEAD_LABELS[order],
            land_rate_pct=float(s.land_mills / 10), building_rate_pct=float(s.building_mills / 10),
            exemption_worth_usd=dict(median_today=float(np.median(worth_today[only])),
                                     median_after=float(np.median(worth_after[only]))),
            homes={name: cohort_stats(s.current, s.new, mask) for name, mask in cohorts.items()},
            by_property_group={k: dict(change_musd=round(float(v.change_musd), 2), change_pct=round(float(v.change_pct), 2),
                                       pay_less_pct=round(float(v.pay_less_pct), 2))
                               for k, v in sectors.iterrows()},
            profile={name: neighbourhood_profile(q, s.current, s.new, cohorts[name])
                     for name in ("all_homes", "homestead", "owner_occupied")},
            typical_home=typical_home(house_land, house_building, order, params, s.land_mills, s.building_mills),
        )
    return dict(
        basis=dict(
            homes="taxable 1-4-unit homes with a bill today",
            homestead="OPA records a Homestead Exemption and some value is exempt in the TY2026 assessment",
            owner_occupied="homestead, or an individual owner whose mailing address is the home "
                           "(philadelphia_abatement_phase_in.owner_occupied)",
            typical_home=f"median land ${house_land:,.0f} and median building ${house_building:,.0f} (gross, before "
                         "the exemption) of homestead-only single-family homes; not the same house as the median bill",
            caveats=["formerly abated homes (the abatement bars the homestead) are not granted it once it expires",
                     "every order but building_first needs 53 Pa.C.S. Sec. 8583(c) amended",
                     "rates are re-solved revenue-neutral under each order",
                     "`transition` is computed at the headline order only"],
        ),
        orders=orders,
    )


def file_date(path: Path) -> str:
    return pd.Timestamp(path.stat().st_mtime, unit="s").strftime("%Y-%m-%d")


def council_district(g: pd.DataFrame) -> np.ndarray:
    """Each parcel's City Council district, from its OPA point and the cached district boundaries."""
    import geopandas as gpd

    if not COUNCIL_DISTRICTS.exists():
        raise FileNotFoundError(f"{COUNCIL_DISTRICTS.relative_to(REPO_ROOT)} is missing; run "
                                "scripts/map_philadelphia_tax_changes.py once to cache it")
    pts = gpd.read_parquet(parcel_cache_path(TAX_YEAR, CACHE_DIR), columns=["parcel_number", "geometry"])
    pts = pts.set_crs("EPSG:4326") if pts.crs is None else pts
    pts["parcel_id"] = pts.parcel_number.astype(str).str.lstrip("0").astype("Int64")
    pts = pts.drop_duplicates("parcel_id")
    cd = gpd.read_parquet(COUNCIL_DISTRICTS).to_crs(pts.crs)
    j = gpd.sjoin(pts, cd[["DISTRICT", "geometry"]], how="left", predicate="within")
    j = j[["parcel_id", "DISTRICT"]].drop_duplicates("parcel_id")
    return g[["parcel_id"]].merge(j, on="parcel_id", how="left", validate="many_to_one")["DISTRICT"].to_numpy()


def district_table(g: pd.DataFrame, s, homes: np.ndarray, hs: np.ndarray, occupied: np.ndarray, order: str) -> dict:
    """Homes, homestead homes and owner-occupants by Council district, at the headline order."""
    district = council_district(g)
    billed = homes & (s.current > 0)
    unmatched = float(np.mean(pd.isna(district[billed])))
    assert unmatched < 0.001, f"{unmatched:.2%} of homes fall in no Council district; check the boundary file"
    keys = ("parcels", "pay_less_pct", "aggregate_change_pct", "median_change_usd", "median_current_bill_usd")
    rows = {}
    for d in sorted(pd.unique(district[billed & ~pd.isna(district)])):
        in_d = district == d
        rows[str(int(d))] = {name: {k: v for k, v in bill_stats(s.current, s.new, mask & in_d).items() if k in keys}
                             for name, mask in (("all_homes", homes), ("homestead", homes & hs),
                                                ("owner_occupied", homes & occupied))}
    return dict(basis=dict(homestead_order=order, boundaries=f"{COUNCIL_DISTRICTS_SOURCE} (cached "
                           f"{file_date(COUNCIL_DISTRICTS)}), joined to OPA parcel points",
                           homes="taxable 1-4-unit homes with a bill today",
                           unmatched_homes_pct=100 * unmatched),
                districts=rows)


def progressivity_robustness(g, post, category, taxable, homes, q, params, order, headline_profile) -> dict:
    """The neighbourhood pattern on an independent land estimate: FHFA's tract land shares.

    Single-family homes in a tract FHFA covers take FHFA's land share of their own total; every
    other parcel keeps S5. Same shift, same rates solve, same homestead order as the headline, so
    the only thing that changes is where single-family land values come from.
    """
    f = pd.read_csv(FHFA_TRACTS, dtype={"tract_geoid": str})
    tract = g.std_geoid.astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(12).str[:11]
    share = tract.map(f.drop_duplicates("tract_geoid").set_index("tract_geoid").fhfa_land_share)
    sfr = (category == "Single Family Residential").to_numpy() & taxable
    use = sfr & share.notna().to_numpy()
    gross_total = (post.taxable_land + post.exempt_land + post.taxable_building + post.exempt_building).to_numpy()
    frame = post.assign(fhfa_land=np.where(use, share.fillna(0).to_numpy() * gross_total, post.s5_land.to_numpy()))
    s = shift(frame, taxable, params, order, land_col="fhfa_land")
    prof = neighbourhood_profile(q, s.current, s.new, homes)

    def spread(p, col, low, high):
        return float(p[col][low]["homes_pct"] - p[col][high]["homes_pct"])

    gaps = {}
    for col, low, high in (("inc_q", "poorest", "richest"), ("min_q", "most non-white", "whitest")):
        s5_gap, fhfa_gap = spread(headline_profile, col, low, high), spread(prof, col, low, high)
        gaps[col] = dict(compare=f"{low} minus {high}, aggregate % change of homes", s5=s5_gap, fhfa=fhfa_gap,
                         fhfa_over_s5=fhfa_gap / s5_gap if s5_gap else None)
    return dict(
        basis=dict(surface="FHFA tract land share of single-family property value, applied to each single-family "
                           f"home's own total; S5 everywhere else ({FHFA_TRACTS.relative_to(REPO_ROOT).as_posix()})",
                   homestead_order=order,
                   single_family_matched_pct=float(100 * use.sum() / sfr.sum())),
        rates=dict(land_rate_pct=float(s.land_mills / 10), building_rate_pct=float(s.building_mills / 10)),
        homes=bill_stats(s.current, s.new, homes),
        homes_profile=prof,
        spread=gaps,
    )


def typical_rowhouse(s, homes: np.ndarray, category: pd.Series, params, order: str) -> dict:
    """The worked example: a typical homestead rowhouse, the same house rented, and the empty lot beside it.

    The house is the median gross land and median gross building (before any exemption) of
    homestead-only single-family homes: a house with typical parts, not the house at the median
    bill. The lot has the same land and no building, so its bill is land alone.
    """
    sfr = (category == "Single Family Residential").to_numpy()
    m = homes & sfr & (s.r.exemption_kind == "homestead").to_numpy() & (s.current > 0)
    land, building = float(np.median(s.r.alloc_land[m])), float(np.median(s.r.alloc_building[m]))
    house = typical_home(land, building, order, params, s.land_mills, s.building_mills)
    for v in house.values():
        v["change_pct"] = 100 * (v["after_usd"] / v["today_usd"] - 1)
    lot_today, lot_after = land * params.combined_mills / 1000, land * s.land_mills / 1000
    return dict(
        basis=f"median gross land and median gross building of {int(m.sum()):,} homestead-only single-family homes",
        homestead_order=order, land_usd=land, building_usd=building, value_usd=land + building,
        land_share_pct=100 * land / (land + building),
        homestead_exemption_usd=float(params.homestead_exemption),
        with_homestead=house["with_homestead"], without_homestead=house["without_homestead"],
        empty_lot=dict(today_usd=lot_today, after_usd=lot_after, change_usd=lot_after - lot_today,
                       change_pct=100 * (lot_after / lot_today - 1)),
    )


def load_opa_attributes(g: pd.DataFrame) -> pd.DataFrame:
    """OPA building code, description and zoning for each parcel, aligned to `g`."""
    from philadelphia_abatement_phase_in import _pid

    if not OPA_ATTRIBUTES.exists():
        raise FileNotFoundError(f"{OPA_ATTRIBUTES.relative_to(REPO_ROOT)} is missing; run "
                                "analysis/ownership/philadelphia/fetch_opa_attributes.py")
    cols = ["building_code", "building_code_description", "zoning"]
    a = pd.read_parquet(OPA_ATTRIBUTES, columns=["parcel_number", *cols])
    a["key"] = _pid(a.parcel_number)
    a = a.drop_duplicates("key").set_index("key")
    key = _pid(g.parcel_number)
    return pd.DataFrame({c: key.map(a[c]).to_numpy() for c in cols}, index=g.index)


def commercial_breakdown(g: pd.DataFrame, groups: pd.Series, taxable: np.ndarray, s, order: str) -> dict:
    """The flyer's 'Commercial' bar taken apart: by building type, by zoning, and by both.

    With each total held fixed, a parcel pays more exactly when its land share is above the
    citywide break-even, so the breakdown reports each group's median land share beside its
    bill change: that is the mechanism, not a coincidence of neighbourhood.
    """
    attrs = load_opa_attributes(g)
    keep = (groups == COMMERCIAL_GROUP).to_numpy() & (taxable | (s.new > 0) | (s.current > 0))
    gross = (s.r.alloc_land + s.r.alloc_building).to_numpy()
    land_share = np.divide(s.r.alloc_land.to_numpy(), gross, out=np.full(len(gross), np.nan), where=gross > 0)
    d = pd.DataFrame(dict(
        building_type=commercial_building_type(attrs.building_code_description, attrs.building_code).to_numpy(),
        zoning=zoning_family(attrs.zoning).to_numpy(),
        described=attrs.building_code_description.notna().to_numpy(), zoned=attrs.zoning.notna().to_numpy(),
        cur=s.current, new=s.new, land_share=land_share))[keep]

    described, zoned = float(d.described.mean()), float(d.zoned.mean())
    other_share = float(d.cur[d.building_type == COMMERCIAL_OTHER].sum() / d.cur.sum())
    assert described >= 0.99 and zoned >= 0.98, (
        f"only {described:.1%} of the sector has an OPA building description and {zoned:.1%} a zoning code; "
        f"is {OPA_ATTRIBUTES.name} from a different vintage than the parcel cache?")
    assert other_share <= MAX_OTHER_TAX_SHARE, (
        f"{other_share:.1%} of the sector's tax is in '{COMMERCIAL_OTHER}': the rules in "
        "lvt.philadelphia.COMMERCIAL_BUILDING_TYPES have fallen behind OPA's building descriptions")

    def stats(x: pd.DataFrame) -> dict:
        return dict(parcels=int(len(x)), today_musd=float(x.cur.sum() / 1e6),
                    change_musd=float((x.new - x.cur).sum() / 1e6),
                    change_pct=float(100 * (x.new.sum() / x.cur.sum() - 1)) if x.cur.sum() > 0 else None,
                    pay_more_pct=float(100 * (x.new > x.cur).mean()), pay_less_pct=float(100 * (x.new < x.cur).mean()),
                    median_land_share_pct=float(100 * x.land_share.median()))

    def table(by) -> dict:
        rows = {(" | ".join(k) if isinstance(k, tuple) else k): stats(x)
                for k, x in d.groupby(by) if len(x) >= (MIN_CELL_PARCELS if isinstance(by, list) else 1)}
        return dict(sorted(rows.items(), key=lambda kv: -kv[1]["change_musd"]))

    by_type = table("building_type")
    total = float((d.new - d.cur).sum() / 1e6)
    assert abs(sum(v["change_musd"] for v in by_type.values()) - total) < 1e-6, "building types do not add up to the sector"
    stamp = pd.Timestamp(OPA_ATTRIBUTES.stat().st_mtime, unit="s").strftime("%Y-%m-%d")
    return dict(
        basis=dict(
            sector=f"the '{COMMERCIAL_GROUP}' property group, the flyer's 'Commercial' bar",
            homestead_order=order,
            building_type="OPA building_code_description, grouped by lvt.philadelphia.commercial_building_type "
                          "(parking by building_code)",
            zoning="OPA zoning, grouped by lvt.philadelphia.zoning_family",
            attributes=f"{OPA_ATTRIBUTES.relative_to(REPO_ROOT).as_posix()}, OPA's current properties table "
                       f"(file dated {stamp}); the cross-table omits cells under {MIN_CELL_PARCELS} parcels",
            caveat="S5 is fitted on small-lot land sales and values expensive land relatively low, so the cuts "
                   "to towers and the increases on large lots are the model's least reliable figures",
        ),
        coverage=dict(parcels=int(len(d)), change_musd=total, described_pct=100 * described, zoned_pct=100 * zoned,
                      other_tax_pct=100 * other_share),
        by_building_type=by_type,
        by_zoning=table("zoning"),
        by_zoning_and_building_type=table(["zoning", "building_type"]),
    )


def print_commercial_breakdown(c: dict) -> None:
    for key in ("by_building_type", "by_zoning"):
        t = pd.DataFrame(c[key]).T[["parcels", "today_musd", "change_musd", "change_pct", "pay_more_pct",
                                    "median_land_share_pct"]]
        print(f"\nCommercial / mixed / other, {key.replace('_', ' ')} ({c['basis']['homestead_order']}):")
        print(t.astype(float).round(1).to_string())


def payback(order: str, headline) -> dict:
    """How long an abated owner takes to recoup, from the phase-in panel's own scenarios.

    `lvt_phase_in` there is the within-total re-split with the ratio rising in equal steps to 4:1,
    against `status_quo` (today's split and rate, abatements expiring on schedule). The panel read is
    the one built on this script's basis (the headline homestead order, today's rate held, bare lots
    at S5), and its final-year rates are checked against the front page's, so the transition and the
    long-run flyer describe one reform. The abated cohorts differ slightly (the phase-in uses the
    schedule classification, this script `expand_abatement_cohort`), which is what the tolerance is for.
    """
    from philadelphia_abatement_phase_in import output_tag

    settings = dict(homestead_order=order, **PHASE_IN_BASIS)
    stem = f"philadelphia_abatement_phase_in{output_tag(settings)}"
    meta_path, panel_path = DATA / f"{stem}_meta.json", DATA / f"{stem}_panel.parquet"
    if not meta_path.exists():
        raise FileNotFoundError(
            f"{meta_path.name} is missing; run: python scripts/philadelphia_abatement_phase_in.py "
            f"--homestead-order {order} --baseline rate --revalue-bare-lots")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["settings"] == settings, f"{meta_path.name} was built with {meta['settings']}, not {settings}"
    gaps = dict(land=100 * (meta["final_year_lvt_land_mills"] / headline.land_mills - 1),
                building=100 * (meta["final_year_lvt_building_mills"] / headline.building_mills - 1))
    print(f"phase-in final-year rates vs front page: land {gaps['land']:+.2f}%, building {gaps['building']:+.2f}%")
    assert max(abs(v) for v in gaps.values()) <= MAX_PHASE_IN_RATE_GAP_PCT, (
        f"the phase-in's final-year rates differ from the front page's by {gaps}; they no longer describe one reform")
    p = pd.read_parquet(panel_path)
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
        basis=dict(panel=panel_path.name, settings=settings, generated=meta["generated"],
                   final_year_rate_gap_pct=gaps),
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


def worked_example(g, category, full_exempt, land, building, current, millage, land_mills, building_mills) -> dict:
    """A rowhouse and the empty lot beside it, at typical Philadelphia values.

    The pair is the MEDIAN LAND and MEDIAN BUILDING of taxable single-family homes, not the
    parcel at the median bill. Those are different houses and the difference is not cosmetic: the
    median-bill rowhouse carries $154k of building over $20k of land, an 11% land share, so it
    saves $943 -- five times the median saving the page reports. Printing that beside "the median
    home saves $206" would be arithmetically correct and deeply misleading.

    The empty lot is given the same land value as the house, which is the point of the comparison:
    identical ground, one built on and one not. Its bill is land alone.

    Unlike a full shift, a 4:1 split does not make the two bills equal, and the pair does not
    balance to zero between themselves -- revenue neutrality holds citywide, not within any two
    parcels. Do not reword the caption to imply otherwise.
    """
    sfr = (category == "Single Family Residential").to_numpy() & ~full_exempt & (current > 0)
    house_land = float(np.median(land[sfr]))
    house_building = float(np.median(building[sfr]))

    def bill(l, b, rate_l, rate_b):
        return (l * rate_l + b * rate_b) / 1000

    change = (new_tax := bill(house_land, house_building, land_mills, building_mills)) - (
        today := bill(house_land + house_building, 0.0, millage, 0.0))
    lot_today = bill(house_land, 0.0, millage, 0.0)
    lot_new = bill(house_land, 0.0, land_mills, 0.0)
    # A parcel pays less exactly when its land share sits below the citywide taxable land share.
    pivot = float(100 * land.sum() / (land.sum() + building.sum()))
    return dict(
        basis="median land and median building value of taxable single-family homes",
        house_land_usd=house_land, house_building_usd=house_building,
        house_land_share_pct=float(100 * house_land / (house_land + house_building)),
        house_today_usd=float(today), house_new_usd=float(new_tax), house_change_usd=float(change),
        lot_today_usd=float(lot_today), lot_new_usd=float(lot_new),
        lot_change_usd=float(lot_new - lot_today),
        median_sfr_change_usd=float(np.median(((land * land_mills + building * building_mills) / 1000 - current)[sfr])),
        pays_less_below_land_share_pct=pivot,
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
    ap = argparse.ArgumentParser(description="Numbers and map for the Council candidate LVT one-pager.")
    ap.add_argument("--homestead-order", choices=HOMESTEAD_ORDERS, default="building_first",
                    help="which line the Homestead Exemption comes off in the headline figures "
                         "(default building_first, 53 Pa.C.S. Sec. 8583(c)); homestead_comparison "
                         "reports every order regardless")
    order = ap.parse_args().homestead_order

    OUT.mkdir(parents=True, exist_ok=True)
    params = tax_year_params(TAX_YEAR)
    millage = params.combined_mills

    g = load_parcels()
    category, abated, restored_building, full_exempt = classify(g)
    post = expire_abatements(g, abated, restored_building)
    taxable = ~full_exempt

    headline = shift(post, taxable, params, order)
    r, base_total, land, building, bare = headline.r, headline.base_total, headline.land, headline.building, headline.bare
    print(r.describe())
    print(f"homestead exemption applied {HOMESTEAD_LABELS[order]}")

    # A parcel with a building on it keeps its total: the reform can only change how that total is
    # split, so the only such bills that move are the ones whose relief depends on the split.
    built = taxable & ~bare
    identical = np.isclose(land + building, base_total, atol=1.0)
    print(f"{bare.sum():,} bare lots revalued from sales; no building reassessed. "
          f"Taxable total unchanged on {identical[built].mean():.2%} of the {built.sum():,} taxable "
          f"parcels that have a building ({(~identical & built).sum():,} move, split-dependent relief)")

    current, revenue, new = headline.current, headline.revenue, headline.new
    land_mills, building_mills = headline.land_mills, headline.building_mills

    homes = category.isin(HOMES).to_numpy() & taxable
    groups = category.map(property_group)
    q, edges = strata(g, homes)

    by_group = sector_totals(groups, taxable, current, new)
    profile = neighbourhood_profile(q, current, new, homes)
    # Who holds the Homestead Exemption, and who is an owner-occupant more widely: computed once and
    # shared by every section that reports homeowners.
    hs = _decompose_exemptions(post, "homestead_exemption", 1.0).homestead_active.to_numpy()
    occupied = hs | owner_occupied_proxy(g, hs, abated)

    # The ratio is the only lever this reform has, so price it: with the total fixed, a parcel pays
    # less exactly when its land share sits below the citywide average, and the ratio sets how hard
    # that bites. Reported so the flyer's 4:1 is a choice with a stated cost, not a default. Each
    # ratio is its own solve because the tax_share homestead order weights land by the ratio.
    sweep = {}
    for ratio in (1.5, 2.0, 2.5, 3.0, 4.0, 5.0):
        alt_shift = headline if ratio == RATIO else shift(post, taxable, params, order, ratio)
        lm, bm, alt = alt_shift.land_mills, alt_shift.building_mills, alt_shift.new
        s = bill_stats(current, alt, homes)
        s.update(land_rate_pct=float(lm / 10), building_rate_pct=float(bm / 10),
                 vacant_change_pct=float(100 * (alt[(groups == "vacant land").to_numpy()].sum()
                                                / current[(groups == "vacant land").to_numpy()].sum() - 1)))
        sweep[f"{ratio:g}:1"] = s

    # Bare lots larger than the land sales can test: the headline carries them at OPA's value,
    # and the two other readings are solved whole so the sector figures can be printed as a range.
    beyond = bare & post.land_beyond_support.to_numpy()
    large_tract_range = {}
    for treatment in LARGE_TRACT_TREATMENTS:
        alt = headline if treatment == "carry_opa" else shift(post, taxable, params, order, large_tracts=treatment)
        t = sector_totals(groups, taxable, alt.current, alt.new)
        large_tract_range[treatment] = dict(
            bare_land_beyond_support_busd=float(alt.land[beyond].sum() / 1e9),
            land_rate_pct=float(alt.land_mills / 10), building_rate_pct=float(alt.building_mills / 10),
            by_property_group=t[["change_pct", "change_musd"]].round(2).to_dict("index"))
    support = surface_support()

    numbers = dict(
        as_of=pd.Timestamp.today().strftime("%Y-%m-%d"),
        source="LVTShift scripts/philadelphia_council_one_pager.py",
        model=dict(tax_year=TAX_YEAR, ratio=RATIO, land_surface="S5 paired sales",
                   construction=("OPA total held fixed where there is a building: land = min(S5, total), "
                                 "building = total - land. On bare lots the cap is lifted and land = S5, "
                                 "up to the lot size the land sales can test; a larger bare lot keeps "
                                 "OPA's value."),
                   support_edge_sqft=float(support["edge_sqft"]),
                   bare_lots_beyond_support=int(beyond.sum()),
                   opa_median_ratio_on_large_vacant_sales=float(
                       support["reference_median_ratio_beyond_edge_still_vacant"]),
                   horizon="after today's 10-year abatements have expired",
                   homestead_order=order, homestead_rule=HOMESTEAD_LABELS[order],
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
        worked_example=worked_example(g, category, full_exempt, land, building, current, millage, land_mills, building_mills),
        ratio_sweep=sweep,
        large_tract_range=large_tract_range,
        quintile_edges=edges,
        transition=payback(order, headline),
        vacant_and_parking=json.loads(GATHERED_JSON.read_text()),
        homestead_comparison=homestead_comparison(post, category, taxable, homes, groups, q, params, hs, occupied),
        commercial_breakdown=commercial_breakdown(g, groups, taxable, headline, order),
        typical_rowhouse=typical_rowhouse(headline, homes, category, params, order),
        districts=district_table(g, headline, homes, hs, occupied, order),
        progressivity_robustness=progressivity_robustness(g, post, category, taxable, homes, q, params, order, profile),
    )
    sector = numbers["by_property_group"][COMMERCIAL_GROUP]["change_musd"]
    assert abs(numbers["commercial_breakdown"]["coverage"]["change_musd"] - sector) < 0.01, \
        "commercial breakdown does not reproduce its sector's change"
    (OUT / "numbers.json").write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    render_map()
    print(json.dumps({k: numbers[k] for k in
                      ("rates", "homes", "by_property_group", "large_tract_range", "homes_profile",
                       "transition")}, indent=2))
    print_homestead_comparison(numbers["homestead_comparison"])
    print_commercial_breakdown(numbers["commercial_breakdown"])
    print_new_sections(numbers)
    print(f"wrote {OUT}")


def print_new_sections(n: dict) -> None:
    t = n["typical_rowhouse"]
    print(f"\nTypical homestead rowhouse (${t['value_usd']:,.0f}, land {t['land_share_pct']:.1f}%):")
    for k in ("with_homestead", "without_homestead", "empty_lot"):
        v = t[k]
        print(f"  {k:18s} ${v['today_usd']:,.0f} -> ${v['after_usd']:,.0f} ({v['change_pct']:+.1f}%)")
    d = pd.DataFrame({k: {f"{c}: {m}": v[c][m] for c in v for m in ("pay_less_pct", "aggregate_change_pct")}
                      for k, v in n["districts"]["districts"].items()}).T
    print("\nBy Council district:\n" + d.round(1).to_string())
    p = n["progressivity_robustness"]
    print("\nProgressivity on FHFA land shares:", {k: round(v["fhfa_over_s5"], 2) for k, v in p["spread"].items()},
          f"(single-family matched {p['basis']['single_family_matched_pct']:.1f}%)")
    print("Sector share paying less:", {k: round(v["pay_less_pct"], 1) for k, v in n["by_property_group"].items()})
    tr = n["transition"]
    print("Transition:", {k: round(v, 2) if isinstance(v, float) else v for k, v in tr.items() if k != "basis"})


def print_homestead_comparison(c: dict) -> None:
    rows = {}
    for order, o in c["orders"].items():
        row = {"land rate %": o["land_rate_pct"], "building rate %": o["building_rate_pct"],
               "exemption worth $": o["exemption_worth_usd"]["median_after"]}
        for name, s in o["homes"].items():
            row[f"{name}: pay less %"] = s["pay_less_pct"]
            row[f"{name}: $M"] = s["aggregate_change_musd"]
        for k, v in o["by_property_group"].items():
            row[f"sector {k}: $M"] = v["change_musd"]
        rows[order] = row
    print("\nHomestead order comparison (exemption worth today: "
          f"${next(iter(c['orders'].values()))['exemption_worth_usd']['median_today']:,.0f})")
    print(pd.DataFrame(rows).round(2).to_string())


if __name__ == "__main__":
    main()
