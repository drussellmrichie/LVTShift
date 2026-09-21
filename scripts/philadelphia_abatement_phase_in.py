"""
Philadelphia -- abated properties' tax bills under a 10-year LVT phase-in, by abatement schedule,
and what each way of holding them harmless would cost and whom it would reach.

Question: if Philadelphia phases in a 4:1 land/building split rate over ten years on S5 land values,
and stops issuing new abatements, what happens to the bills of parcels whose abatement is still
running -- and what would it cost to protect them for the rest of their abatement?

Every scenario is revenue-neutral in every year (against today's levy by default; see the options
below) and static (TY2026 values held
fixed, no new construction, so "no new abatements" changes nothing that is on the roll today). Year
0 (TY2026) is today's bill everywhere; the reform starts in year 1, the ratio reaches 4:1 in year 10,
and years 11-15 hold it there so that deferred amounts can be repaid.

Reference scenarios:

- status_quo      OPA's own land/building split, one flat rate, abatements expire on schedule.
                  The baseline every reform bill is compared against, so a bill that rises only
                  because its abatement ran out does not count as the reform's doing.
- resplit_flat    S5 land re-split inside OPA's total (the draft Sec. 2-305 ordinance), flat rate.
                  Isolates the land-assessment change from the rate change.
- lvt_phase_in    The re-split plus a land/building millage ratio rising in equal steps to 4:1.

Hold-harmless designs. Each modifies lvt_phase_in only for parcels whose construction abatement is
still running, and each re-solves the rates so everyone else makes up exactly what they are spared:

- hh_full           pays no more than its status_quo bill.
- hh_split_rate     pays no more than its resplit_flat bill: shields the rate change, not the re-split.
- hh_owner_occupied hh_full, for owner-occupied residential parcels only. Owner occupancy cannot be
                    read off the Homestead Exemption here: a parcel with a residential abatement is
                    not eligible for it until the abatement ends, so the flag is empty for exactly
                    these parcels. The proxy is the one the ownership analysis uses -- an individual
                    (not business) owner whose mailing address is the property -- and it is checked
                    against the homestead flag on non-abated homes, where the flag is meaningful.
- hh_cap_10pct      pays no more than 110% of its status_quo bill.
- hh_cap_500        pays no more than its status_quo bill plus $500.
- hh_declining      is spared a share of its increase over status_quo that starts at 100% in year 1
                    and falls 10 points a year, so the protection fades rather than ending at expiry.
- hh_defer          hh_full while the abatement runs; the amount spared is repaid in five equal
                    annual installments starting the year it ends. No interest.
- hh_oo_income_*    hh_owner_occupied, only for households under LOOP's 2026 income limit of 120% of AMI
                    (2-person limit; 1- and 4-person as bounds). An Art. VIII §2(b)(ii) "poverty" class.
- hh_oo_senior      hh_owner_occupied, only for households meeting the Senior Citizen Tax Freeze test
                    (65+, income at most $41,500).
                    Parcel records carry no income or age, so each owner-occupied parcel gets the share
                    of comparable HMDA home buyers who meet the test (see `need_eligibility`) and is
                    shielded by that share: its bill is the expected bill across eligible and
                    ineligible households, and the costs are expected costs.

Each parcel's exemptions follow the repo's own rules (`reallocate_land_within_total`): homestead as
min(cap, value), building first; partial institutional relief in dollars; full institutional
exemption stays; abatement-type relief as a share of the building line. What changes by year is
that share, for the parcels `build_philadelphia_abatement_classification.py` identifies as
construction abatements:

- old_flat_100, old_flat_partial, new_flat_90_commercial   share held until abatement year 10
- new_graduated_residential                               share falls 10 points a year to 0
- anything else with building-share relief (the unidentified value-tracking relief and the
  unresolved parcels)                                     share held throughout

Abatement year k is exempt for k <= 10. Expiry is taken on whole tax years; OPA prorates the last
year by month, which moves one year's bill for each expiring parcel and nothing after it.

Three options put the run on the Council one-pager's basis, so the one-pager's payback figures and
its long-run front page describe one reform (`scripts/philadelphia_council_one_pager.py` checks):

- `--homestead-order`     which line the Homestead Exemption comes off (`lvt.philadelphia.
                          HOMESTEAD_ORDERS`; default building_first, 53 Pa.C.S. Sec. 8583(c)).
- `--baseline rate`       hold today's single RATE instead of today's levy: the status-quo levy then
                          grows as abatements expire, as it does under current law, and every
                          scenario raises that year's status-quo levy. Default `levy`.
- `--revalue-bare-lots`   from year 1 the re-split values bare lots at S5 whole
                          (`lvt.philadelphia.uncap_bare_land`), as the one-pager does.

A run with any non-default option writes its outputs with a suffix naming them, e.g.
`philadelphia_abatement_phase_in_value_share_rate_bare_panel.parquet`, beside a `_meta.json` that
records the options and the final-year rates. The default run's file names are unchanged.

Outputs (analysis/data/, gitignored):
    philadelphia_abatement_phase_in_rates.csv     millages and amount shifted, by scenario x year
    philadelphia_abatement_phase_in_by_year.csv   abated cohort under lvt_phase_in, schedule x year
    philadelphia_abatement_phase_in_exposure.csv  worst year while abated, by scenario x schedule
    philadelphia_abatement_phase_in_designs.csv   each design's cost, reach and residual exposure
    philadelphia_abatement_phase_in_others.csv    what everyone else pays, by scenario x year
    philadelphia_abatement_phase_in_panel.parquet per abated parcel x year, every scenario's bill

Requires:
    cities/philadelphia/data/parcels_ty2026.gpq
    cities/philadelphia/data/abatement_classification_ty2026.parquet
    analysis/data/philadelphia_lycd_reassessment_ty2026_s5.csv
        (LVT_LAND_SURFACE=s5 jupyter nbconvert --execute cities/philadelphia/model_lycd_reassessment.ipynb)
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path
from typing import Dict, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from lvt.philadelphia import (  # noqa: E402
    HOMESTEAD_ORDERS, _apply_exemptions, _decompose_exemptions, parcel_cache_path, reallocate_land_within_total,
    tax_year_params, uncap_bare_land,
)

DEFAULT_SETTINGS = dict(homestead_order="building_first", baseline="levy", revalue_bare_lots=False)


def output_tag(settings: dict) -> str:
    """'' for the default run, else a suffix naming the options, e.g. '_value_share_rate_bare'."""
    if settings == DEFAULT_SETTINGS:
        return ""
    return (f"_{settings['homestead_order']}_{settings['baseline']}"
            + ("_bare" if settings["revalue_bare_lots"] else ""))

TAX_YEAR = 2026
YEARS = 10
HORIZON = 15
FINAL_RATIO = 4.0
ABATEMENT_LIFE = 10
REPAY_YEARS = 5
MATCH_TOL = 1.0
PCT_CUTOFFS = (10, 25, 50)
USD_CUTOFFS = (500, 1000, 2500)

DATA = REPO_ROOT / "analysis/data"
CITY_DATA = REPO_ROOT / "cities/philadelphia/data"
S5_EXPORT = DATA / f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s5.csv"
CLASSIFICATION = CITY_DATA / f"abatement_classification_ty{TAX_YEAR}.parquet"
OWNERSHIP_DIR = REPO_ROOT / "analysis/ownership/philadelphia"
MAILING = OWNERSHIP_DIR / "opa_mailing.parquet"   # built by fetch_mailing.py there
OCCUPANCY_AGREEMENT_FLOOR = 0.8

# Need-based eligibility (PA Const. Art. VIII §2(b)(ii) classes), anchored on Philadelphia's own programs.
# LOOP 2026 income limits at 120% of AMI, by household size; Senior Citizen Real Estate Tax Freeze:
# 65+, income at most $41,500 for a married couple. Both from phila.gov, checked 2026-09-15.
HMDA_DIR = CITY_DATA / "hmda"
HMDA_FIRST_YEAR = 2018          # first year HMDA reports applicant age and property value
LOOP_120_AMI = {"1p": 103_050, "2p": 117_800, "4p": 147_200}
SENIOR_FREEZE_INCOME = 41_500
SENIOR_AGE = 65
HMDA_VALUE_BINS = 20
HMDA_MIN_PER_BIN = 500
AGE_BANDS = {"<25": (18, 24), "25-34": (25, 34), "35-44": (35, 44), "45-54": (45, 54),
             "55-64": (55, 64), "65-74": (65, 74), ">74": (75, 95)}

HELD_SHARE = {"old_flat_100", "old_flat_partial", "new_flat_90_commercial"}
GRADUATED = "new_graduated_residential"
ABATEMENTS = HELD_SHARE | {GRADUATED}
HOMES_CODES = {"1", "2", "8"}

REFERENCE = ["status_quo", "resplit_flat", "lvt_phase_in"]
# name -> (reference bill, owner-occupied only, kind, parameter)
DESIGNS = {
    "hh_full": ("status_quo", False, "cap", None),
    "hh_split_rate": ("resplit_flat", False, "cap", None),
    "hh_owner_occupied": ("status_quo", True, "cap", None),
    "hh_cap_10pct": ("status_quo", False, "cap_pct", 0.10),
    "hh_cap_500": ("status_quo", False, "cap_usd", 500.0),
    "hh_declining": ("status_quo", False, "declining", None),
    "hh_defer": ("status_quo", False, "cap", None),
    # Need-based: hh_owner_occupied, weighted by each parcel's probability of meeting the limit.
    "hh_oo_income_2p": ("status_quo", True, "share", "p_income_2p"),
    "hh_oo_income_1p": ("status_quo", True, "share", "p_income_1p"),
    "hh_oo_income_4p": ("status_quo", True, "share", "p_income_4p"),
    "hh_oo_senior": ("status_quo", True, "share", "p_senior"),
}
SCENARIOS = REFERENCE + list(DESIGNS)
SHARE_DESIGNS = [k for k, v in DESIGNS.items() if v[2] == "share"]


def _pid(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64").astype(str).str.zfill(9)


def load_inputs(ty, settings: dict = DEFAULT_SETTINGS) -> pd.DataFrame:
    """The parcel cache with S5 land, re-split components, exemption parts and abatement schedule."""
    gdf = gpd.read_parquet(parcel_cache_path(TAX_YEAR, data_dir=CITY_DATA))
    gdf = pd.DataFrame(gdf.drop(columns="geometry"))
    gdf["parcel_number"] = _pid(gdf["parcel_number"])
    for c in ["taxable_land", "taxable_building", "exempt_land", "exempt_building", "homestead_exemption"]:
        gdf[c] = pd.to_numeric(gdf[c], errors="coerce").fillna(0.0)

    s5 = pd.read_csv(S5_EXPORT, usecols=["parcel_id", "land_surface", "lycd_land_value", "alloc_land",
                                         "alloc_building", "alloc_taxable_total", "current_tax"],
                     encoding="utf-8", encoding_errors="replace")
    s5["parcel_number"] = _pid(s5.pop("parcel_id"))
    assert (s5["land_surface"] == "s5").all(), f"{S5_EXPORT.name} was not built on the S5 surface"
    # The cache repeats a few identical rows and the export, built from it, repeats them in the
    # same place -- so align by position (as every other export consumer does), not by a join.
    assert len(s5) == len(gdf) and (s5["parcel_number"].to_numpy() == gdf["parcel_number"].to_numpy()).all(), (
        "parcel cache and S5 export are not row-aligned")
    df = gdf.reset_index(drop=True)
    s5 = s5.reset_index(drop=True).rename(columns={"lycd_land_value": "s5_land"})
    for c in ["s5_land", "alloc_land", "alloc_building", "alloc_taxable_total", "current_tax"]:
        df[c] = s5[c]

    # Re-derive the re-split rather than trusting the export, and check the two agree: if the
    # exemption rules have moved since the export was built, this is where it shows.
    alloc = reallocate_land_within_total(df, new_land_col="s5_land", homestead_cap=ty.homestead_exemption)
    drift = (alloc.alloc_taxable_total - df["alloc_taxable_total"]).abs()
    assert (drift > MATCH_TOL).mean() < 0.001, (
        f"{int((drift > MATCH_TOL).sum()):,} parcels' re-split taxable total differs from {S5_EXPORT.name}; "
        "rebuild the S5 export before trusting this run")
    df["alloc_land"], df["alloc_building"] = alloc.alloc_land, alloc.alloc_building
    df["exemption_kind"] = alloc.exemption_kind
    df.attrs["settings"] = dict(settings)
    if settings["revalue_bare_lots"]:
        # The one-pager's rule, from the same library function, applied to the same frame.
        pays = ~((df["taxable_land"] <= 0) & (df["taxable_building"] <= 0)).to_numpy()
        land_u, _, bare = uncap_bare_land(alloc, df, pays)
        df["is_bare"] = bare
        df["bare_taxable_land"] = np.where(bare, land_u, 0.0)

    parts = _decompose_exemptions(df, "homestead_exemption", MATCH_TOL)
    df["gross_land"], df["gross_building"] = parts.gross_land, parts.gross_building
    df["other_exempt"] = parts.other_exempt
    df["share0"] = np.where(
        (df["exemption_kind"] == "building_share") & (df["gross_building"] > 0),
        df["other_exempt"] / df["gross_building"].where(df["gross_building"] > 0, 1.0), 0.0).clip(0, 1)

    cls = pd.read_parquet(CLASSIFICATION, columns=["parcel_number", "schedule_type", "abatement_year_ty"])
    cls["parcel_number"] = _pid(cls["parcel_number"])
    cls = cls.drop_duplicates("parcel_number").set_index("parcel_number")
    df["schedule_type"] = df["parcel_number"].map(cls["schedule_type"]).fillna("none")
    df["abatement_year_ty"] = df["parcel_number"].map(cls["abatement_year_ty"])
    classified = df["exemption_kind"] == "building_share"
    assert (df.loc[classified, "schedule_type"] != "none").all(), (
        "building-share parcels missing from the classification; rebuild it for this cache")
    df["is_abatement"] = df["schedule_type"].isin(ABATEMENTS)
    df["category_code"] = pd.to_numeric(df["category_code"], errors="coerce").astype("Int64").astype(str)
    df.attrs["parts"] = parts
    df["owner_occupied"] = owner_occupied(df, parts.homestead_active.to_numpy())
    need = need_eligibility(df)
    for c in need.columns:
        df[c] = need[c].to_numpy()
    return df


def owner_occupied(df: pd.DataFrame, homestead: np.ndarray) -> np.ndarray:
    """Residential parcel owned by an individual whose mailing address is the property itself."""
    sys.path.insert(0, str(OWNERSHIP_DIR))
    import owner_lib as ol

    mail = pd.read_parquet(MAILING, columns=["parcel_number", "mailing_street", "location"])
    mail["parcel_number"] = _pid(mail["parcel_number"])
    mail = mail.drop_duplicates("parcel_number").set_index("parcel_number")

    def norm(s: pd.Series) -> pd.Series:
        return ol.norm_addr(s).str.replace(r"\b0+(\d)", r"\1", regex=True)

    street = df["parcel_number"].map(mail["mailing_street"])
    location = df["parcel_number"].map(mail["location"])
    blank = norm(street) == ""
    self_mailed = (norm(street) == norm(location)) | blank
    individual = ol.classify_sector(df["owner_1"].fillna("")) == ol.SECTOR_INDIVIDUAL
    residential = df["category_code"].isin(HOMES_CODES)
    occupied = (self_mailed & individual & residential & location.notna()).to_numpy()

    # Where the homestead flag is meaningful (no abatement), the proxy should find most homesteads.
    check = residential.to_numpy() & ~df["is_abatement"].to_numpy() & homestead
    agreement = float(occupied[check].mean())
    if agreement < OCCUPANCY_AGREEMENT_FLOOR:
        raise ValueError(f"Owner-occupancy proxy marks only {agreement:.1%} of homesteaded non-abated homes "
                         f"as owner-occupied (floor {OCCUPANCY_AGREEMENT_FLOOR:.0%}); check {MAILING.name}.")
    df.attrs["occupancy_agreement"] = agreement
    return occupied


def price_to_assessment(market: np.ndarray, n_bins: int = 10) -> np.ndarray:
    """Median sale price / TY2026 assessment for residential parcels, by assessed-value band.

    HMDA records purchase prices and OPA records assessments, so a parcel must be put on the price
    scale before it is matched to comparable buyers. OPA assesses mid- and upper-priced homes below
    their sale prices; matching on the raw assessment would place them among cheaper homes' buyers and
    overstate their eligibility. Binned on the assessment (the quantity being corrected), not on the
    sale price, so the correction does not import the regression-to-the-mean of a price-binned ratio.
    """
    path = HMDA_DIR / "opa_residential_sales_2024_2025.csv"
    if not path.exists():
        q = ("SELECT parcel_number, sale_price, sale_date, category_code FROM opa_properties_public "
             "WHERE sale_date >= '2024-01-01' AND sale_date < '2026-01-01' AND sale_price >= 50000 "
             "AND category_code IN ('1', '2')")
        r = requests.get("https://phl.carto.com/api/v2/sql?q=" + urllib.parse.quote(q) + "&format=csv", timeout=600)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    sales = pd.read_csv(path, dtype={"parcel_number": str})
    sales["parcel_number"] = _pid(sales["parcel_number"])
    cache = pd.read_parquet(parcel_cache_path(TAX_YEAR, data_dir=CITY_DATA), columns=["parcel_number", "market_value"])
    cache["parcel_number"] = _pid(cache["parcel_number"])
    s = sales.merge(cache.drop_duplicates("parcel_number"), on="parcel_number")
    s["market_value"] = pd.to_numeric(s["market_value"], errors="coerce")
    s = s[(s["market_value"] > 0)]
    s["factor"] = s["sale_price"] / s["market_value"]
    s = s[(s["factor"] > 1 / 3) & (s["factor"] < 10)]      # drop nominal and bulk transfers
    edges = np.unique(s["market_value"].quantile(np.linspace(0, 1, n_bins + 1)).to_numpy())
    s["bin"] = np.clip(np.searchsorted(edges, s["market_value"], side="right") - 1, 0, len(edges) - 2)
    factor = s.groupby("bin")["factor"].median()
    bins = np.clip(np.searchsorted(edges, market, side="right") - 1, 0, len(edges) - 2)
    return factor.reindex(bins).to_numpy()


def need_eligibility(df: pd.DataFrame) -> pd.DataFrame:
    """Probability each parcel's household meets the income or senior limit, from comparable home buyers.

    Parcel records carry no owner income or age. HMDA does, for every owner-occupant who bought a
    Philadelphia home with a mortgage: income, home value, and applicant and co-applicant age band. A
    parcel's probability is the eligible share among buyers of homes of similar value (value bins in
    constant dollars), which matters because abated new construction sells well above the block-group
    averages the Census would offer.

    Incomes are restated in the latest HMDA year's dollars by the growth in HMDA's area median family
    income, then compared with the programs' dollar limits. Do not compare income with HMDA's own
    median instead: that median covers a narrower area than HUD's, and a ratio to it would put the
    two-person LOOP limit near $86K rather than $117,800. Ages are advanced by the years since purchase.

    Biases, all toward overstating eligibility except the last: incomes are indexed one year short of
    the 2026 limits; cash buyers, who skew wealthier, are absent; income at purchase stands in for
    income now. Retirement since purchase cuts the other way for the senior limit.
    """
    frames = []
    for path in sorted(HMDA_DIR.glob("hmda_purchase_*.csv")):
        frames.append(pd.read_csv(path, low_memory=False, usecols=[
            "activity_year", "occupancy_type", "business_or_commercial_purpose", "income", "property_value",
            "applicant_age", "co-applicant_age", "ffiec_msa_md_median_family_income"]))
    if not frames:
        raise FileNotFoundError(f"No HMDA files in {HMDA_DIR}; download purchase originations for county 42101, "
                                f"{HMDA_FIRST_YEAR}+, from ffiec.cfpb.gov/v2/data-browser-api")
    h = pd.concat(frames, ignore_index=True)
    h = h[(h["activity_year"] >= HMDA_FIRST_YEAR) & (h["occupancy_type"] == 1)
          & (h["business_or_commercial_purpose"] != 1)].copy()
    h["income"] = pd.to_numeric(h["income"], errors="coerce") * 1000
    h["value"] = pd.to_numeric(h["property_value"], errors="coerce")
    h = h[(h["income"] > 0) & (h["value"] > 0)]
    latest = int(h["activity_year"].max())
    mfi = h.groupby("activity_year")["ffiec_msa_md_median_family_income"].median()
    med_value = h.groupby("activity_year")["value"].median()
    h["income_now"] = h["income"] * mfi.loc[latest] / h["activity_year"].map(mfi)
    h["value_now"] = h["value"] * med_value.loc[latest] / h["activity_year"].map(med_value)

    def p_senior_age(col: str) -> pd.Series:
        lo = h[col].map(lambda a: AGE_BANDS.get(a, (np.nan, np.nan))[0])
        hi = h[col].map(lambda a: AGE_BANDS.get(a, (np.nan, np.nan))[1])
        shifted = (hi + (TAX_YEAR - h["activity_year"]) - SENIOR_AGE + 1) / (hi - lo + 1)
        return shifted.clip(0, 1).fillna(0.0)

    h["senior"] = np.maximum(p_senior_age("applicant_age"), p_senior_age("co-applicant_age"))
    for size, limit in LOOP_120_AMI.items():
        h[f"p_income_{size}"] = (h["income_now"] <= limit).astype(float)
    h["p_senior"] = h["senior"] * (h["income_now"] <= SENIOR_FREEZE_INCOME)

    edges = np.unique(h["value_now"].quantile(np.linspace(0, 1, HMDA_VALUE_BINS + 1)).to_numpy())
    h["bin"] = np.clip(np.searchsorted(edges, h["value_now"], side="right") - 1, 0, len(edges) - 2)
    cols = [f"p_income_{s}" for s in LOOP_120_AMI] + ["p_senior"]
    by_bin = h.groupby("bin")[cols].mean()
    counts = h.groupby("bin").size()
    assert counts.min() >= HMDA_MIN_PER_BIN, f"HMDA value bins too thin: {counts.min()} buyers in the smallest"

    market = pd.to_numeric(df["market_value"], errors="coerce").fillna(0.0).to_numpy()
    price = market * price_to_assessment(market)
    parcel_bin = np.clip(np.searchsorted(edges, price, side="right") - 1, 0, len(edges) - 2)
    out = pd.DataFrame(by_bin.reindex(parcel_bin).to_numpy(), columns=cols, index=df.index)
    df.attrs["hmda"] = dict(buyers=int(len(h)), years=f"{int(h['activity_year'].min())}-{latest}",
                            citywide={c: float(h[c].mean()) for c in cols})
    return out


def exempt_share(df: pd.DataFrame, t: int) -> np.ndarray:
    """Share of the building line exempt in reform year t (t = 0 is TY2026)."""
    share0 = df["share0"].to_numpy()
    if t == 0:
        # Today's billed share, including abatements in a prorated eleventh year.
        return share0.copy()
    k = df["abatement_year_ty"].to_numpy(dtype=float) + t
    running = np.nan_to_num(k, nan=np.inf) <= ABATEMENT_LIFE
    sched = df["schedule_type"].to_numpy()
    held = np.isin(sched, list(HELD_SHARE))
    grad = sched == GRADUATED
    out = share0.copy()
    out[held] = np.where(running[held], share0[held], 0.0)
    out[grad] = np.where(running[grad], np.clip(share0[grad] - 0.1 * t, 0, 1), 0.0)
    return out


def running_abatement(df: pd.DataFrame, t: int) -> np.ndarray:
    k = df["abatement_year_ty"].to_numpy(dtype=float) + t
    return df["is_abatement"].to_numpy() & (np.nan_to_num(k, nan=np.inf) <= ABATEMENT_LIFE)


def taxable(df: pd.DataFrame, land: pd.Series, building: pd.Series, t: int, cap: float,
            resplit: bool = False, ratio: float = 1.0) -> Tuple[pd.Series, pd.Series]:
    """Taxable land and building lines in year t. `resplit` marks the S5 re-split (the reform)."""
    s = df.attrs["settings"]
    share = pd.Series(exempt_share(df, t), index=df.index)
    other = pd.Series(np.where(df["exemption_kind"] == "building_share", share * building, df["other_exempt"]),
                      index=df.index).clip(lower=0)
    tl, tb = _apply_exemptions(land, building, other, df.attrs["parts"], cap,
                               homestead_order=s["homestead_order"], rate_ratio=ratio)
    if resplit and t >= 1 and s["revalue_bare_lots"]:
        bare = df["is_bare"].to_numpy()
        tl = tl.where(~bare, df["bare_taxable_land"])
        tb = tb.where(~bare, 0.0)
    return tl, tb



def ratio_for(t: int) -> float:
    return 1.0 + (FINAL_RATIO - 1.0) * min(t, YEARS) / YEARS


def solve_design(weighted: np.ndarray, revenue: float, eligible: np.ndarray, ref: np.ndarray,
                 kind: str, param: float | None) -> Tuple[np.ndarray, np.ndarray, float]:
    """Revenue-neutral building millage when eligible parcels' bills are limited by a design.

    Returns (bills actually charged, bills the same rates would charge without the design, building
    millage). Every design's bill is non-decreasing in the millage, so the millage that raises
    `revenue` is found by bisection -- one solver for caps of any shape and for the declining shield.
    """
    if kind == "cap":
        ceiling = ref
    elif kind == "cap_pct":
        ceiling = ref * (1 + param)
    elif kind == "cap_usd":
        ceiling = ref + param
    elif kind not in ("declining", "share"):
        raise ValueError(kind)

    def charge(mills: float) -> Tuple[np.ndarray, np.ndarray]:
        raw = weighted * mills / 1000
        if kind in ("declining", "share"):
            # A shield share: scalar for the declining design, per parcel for need-based ones.
            limited = raw - param * np.clip(raw - ref, 0, None)
        else:
            limited = np.minimum(raw, ceiling)
        return np.where(eligible, limited, raw), raw

    lo, hi = 0.0, revenue * 1000 / weighted.sum()
    for _ in range(60):
        if charge(hi)[0].sum() >= revenue:
            break
        hi *= 2
    else:
        raise RuntimeError("could not bracket the revenue-neutral millage")
    for _ in range(200):
        mid = (lo + hi) / 2
        if charge(mid)[0].sum() < revenue:
            lo = mid
        else:
            hi = mid
    bills, raw = charge(hi)
    assert abs(bills.sum() - revenue) < 1.0, "design solve missed the levy"
    return bills, raw, hi


def run(df: pd.DataFrame, ty) -> Tuple[Dict[str, np.ndarray], pd.DataFrame]:
    cap = ty.homestead_exemption
    parts = df.attrs["parts"]
    hold_levy = df.attrs["settings"]["baseline"] == "levy"
    revenue = float(df["current_tax"].sum())      # today's levy, held every year by the levy baseline
    abated = df["is_abatement"].to_numpy()
    owner = df["owner_occupied"].to_numpy()

    # Guards: year 0 through this module's exemption path must reproduce the repo rule exactly.
    sq_l0, sq_b0 = taxable(df, parts.gross_land, parts.gross_building, 0, cap)
    rs_l0, rs_b0 = taxable(df, df["alloc_land"], df["alloc_building"], 0, cap)
    alloc = reallocate_land_within_total(df, new_land_col="s5_land", homestead_cap=cap)
    assert ((sq_l0 + sq_b0) - alloc.reconstructed_taxable_total).abs().max() < MATCH_TOL, "status-quo year 0 drifts from the rule"
    assert ((rs_l0 + rs_b0) - alloc.alloc_taxable_total).abs().max() < MATCH_TOL, "re-split year 0 drifts from the rule"

    n = len(df)
    owed = np.zeros(n)
    installment = np.zeros(n)
    left = np.zeros(n, dtype=int)
    bills: Dict[str, np.ndarray] = {}
    rows = []
    need_share = {k: df[DESIGNS[k][3]].to_numpy() for k in SHARE_DESIGNS}
    for t in range(HORIZON + 1):
        running = running_abatement(df, t)
        bills[f"running_{t}"] = running
        sq_l, sq_b = [x.to_numpy() for x in taxable(df, parts.gross_land, parts.gross_building, t, cap)]
        sq_w = sq_l + sq_b
        # The levy every scenario raises this year: today's, or today's rate on this year's roll.
        levy = revenue if hold_levy else float(sq_w.sum()) * ty.combined_mills / 1000
        sq = sq_w * levy / sq_w.sum()
        if t == 0:
            year = {k: sq for k in SCENARIOS}
            mills = {k: (levy * 1000 / sq_w.sum(),) * 2 for k in SCENARIOS}
            bills.update({f"{k}_{t}": v for k, v in year.items()})
            for k in SCENARIOS:
                rows.append(dict(scenario=k, t=t, tax_year=TAX_YEAR, ratio=1.0, land_mills=mills[k][0],
                                 building_mills=mills[k][1], shifted_to_others=0.0, others_bill_change_pct=0.0,
                                 parcels_limited=0, repayments=0.0))
            continue

        ratio = ratio_for(t)
        rs_l, rs_b = [x.to_numpy() for x in taxable(df, df["alloc_land"], df["alloc_building"], t, cap,
                                                    resplit=True, ratio=ratio)]
        rs_w, lvt_w = rs_l + rs_b, ratio * rs_l + rs_b
        rs = rs_w * levy / rs_w.sum()
        lvt = lvt_w * levy / lvt_w.sum()
        ref_bills = {"status_quo": sq, "resplit_flat": rs}
        year = {"status_quo": sq, "resplit_flat": rs, "lvt_phase_in": lvt}
        mills = {"status_quo": (levy * 1000 / sq_w.sum(),) * 2, "resplit_flat": (levy * 1000 / rs_w.sum(),) * 2,
                 "lvt_phase_in": (ratio * levy * 1000 / lvt_w.sum(), levy * 1000 / lvt_w.sum())}
        limited, repaid = {}, {}

        # Deferral: an abatement that ended last year starts repaying what it was spared.
        ended = bills[f"running_{t - 1}"] & ~running & (owed > 0)
        installment[ended] = owed[ended] / REPAY_YEARS
        left[ended] = REPAY_YEARS
        owed[ended] = 0.0
        due = np.where(left > 0, installment, 0.0)

        for name, (ref_name, owner_only, kind, param) in DESIGNS.items():
            eligible = running & (owner if owner_only else True)
            p = (max(0.0, 1.0 - 0.1 * (t - 1)) if kind == "declining"
                 else need_share[name] if kind == "share" else param)
            target = levy - (due.sum() if name == "hh_defer" else 0.0)
            charged, raw, bm = solve_design(lvt_w, target, eligible, ref_bills[ref_name], kind, p)
            if name == "hh_defer":
                owed += np.where(eligible, raw - charged, 0.0)
                charged = charged + due
                repaid[name] = float(due.sum())
            year[name] = charged
            mills[name] = (ratio * bm, bm)
            limited[name] = int((eligible & (raw - (charged - (due if name == "hh_defer" else 0)) > 0.005)).sum())
        left[left > 0] -= 1

        for k in SCENARIOS:
            b = year[k]
            rows.append(dict(scenario=k, t=t, tax_year=TAX_YEAR + t,
                             ratio=1.0 if k in ("status_quo", "resplit_flat") else ratio,
                             land_mills=mills[k][0], building_mills=mills[k][1],
                             shifted_to_others=float((b - lvt)[~abated].sum()) if k in DESIGNS else 0.0,
                             others_bill_change_pct=100 * (b[~abated].sum() / lvt[~abated].sum() - 1) if k in DESIGNS else 0.0,
                             parcels_limited=limited.get(k, 0), repayments=repaid.get(k, 0.0)))
        bills.update({f"{k}_{t}": v for k, v in year.items()})
        for k in SCENARIOS:
            assert abs(year[k].sum() - levy) < 1.0, f"{k} year {t} is not revenue-neutral"

    assert (left == 0).all() and np.allclose(owed, 0.0), "deferred amounts not fully repaid within the horizon"
    return bills, pd.DataFrame(rows)


def by_year(df: pd.DataFrame, bills: Dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    sched = df["schedule_type"].to_numpy()
    for s in sorted(ABATEMENTS):
        in_s = sched == s
        for t in range(1, YEARS + 1):
            m = in_s & bills[f"running_{t}"]
            sq, lvt, rs = bills[f"status_quo_{t}"][m], bills[f"lvt_phase_in_{t}"][m], bills[f"resplit_flat_{t}"][m]
            d = lvt - sq
            pos = sq > 0
            pct = 100 * d[pos] / sq[pos]
            row = dict(schedule_type=s, t=t, tax_year=TAX_YEAR + t, parcels=int(in_s.sum()), running=int(m.sum()),
                       status_quo_total=sq.sum(), resplit_total=rs.sum(), lvt_total=lvt.sum(),
                       median_change_usd=np.median(d) if m.any() else np.nan,
                       p90_change_usd=np.quantile(d, .9) if m.any() else np.nan,
                       median_change_pct=np.median(pct) if pos.any() else np.nan,
                       p90_change_pct=np.quantile(pct, .9) if pos.any() else np.nan,
                       resplit_share_of_increase=(rs - sq).sum() / d.sum() if d.sum() > 0 else np.nan)
            for c in PCT_CUTOFFS:
                row[f"share_over_{c}pct"] = float((pct > c).mean()) if pos.any() else np.nan
            for c in USD_CUTOFFS:
                row[f"share_over_{c}usd"] = float((d > c).mean()) if m.any() else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def worst_years(df: pd.DataFrame, bills: Dict[str, np.ndarray], scenario: str) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per parcel: worst $ and % over status_quo while its abatement runs, and whether it ever runs in the reform."""
    n = len(df)
    usd, pct = np.full(n, -np.inf), np.full(n, -np.inf)
    ever = np.zeros(n, dtype=bool)
    for t in range(1, YEARS + 1):
        r = bills[f"running_{t}"]
        ever |= r
        sq, b = bills[f"status_quo_{t}"], bills[f"{scenario}_{t}"]
        usd = np.where(r, np.maximum(usd, b - sq), usd)
        p = np.where(sq > 0, 100 * (b - sq) / np.where(sq > 0, sq, 1), -np.inf)
        pct = np.where(r, np.maximum(pct, p), pct)
    return usd, pct, ever


def exposure(df: pd.DataFrame, bills: Dict[str, np.ndarray]) -> pd.DataFrame:
    rows = []
    sched = df["schedule_type"].to_numpy()
    # Need-based designs charge an expected bill (a probability-weighted blend), which has no worst
    # year of its own; their exposure is computed as a mixture in designs_summary instead.
    for scenario in ["resplit_flat", "lvt_phase_in"] + [k for k in DESIGNS if k not in SHARE_DESIGNS]:
        usd, pct, ever = worst_years(df, bills, scenario)
        for s in sorted(ABATEMENTS) + ["all abatements"]:
            m = (sched == s if s != "all abatements" else df["is_abatement"].to_numpy()) & ever
            p = pct[m & np.isfinite(pct)]
            row = dict(scenario=scenario, schedule_type=s, parcels=int(m.sum()),
                       median_worst_usd=np.median(usd[m]), p90_worst_usd=np.quantile(usd[m], .9),
                       median_worst_pct=np.median(p), p90_worst_pct=np.quantile(p, .9))
            for c in PCT_CUTOFFS:
                row[f"share_over_{c}pct"] = float((p > c).mean())
            for c in USD_CUTOFFS:
                row[f"share_over_{c}usd"] = float((usd[m] > c).mean())
            rows.append(row)
    return pd.DataFrame(rows)


def designs_summary(df: pd.DataFrame, bills: Dict[str, np.ndarray], rates: pd.DataFrame, exp: pd.DataFrame) -> pd.DataFrame:
    """One row per design: what it costs everyone else, whom the relief reaches, what exposure is left."""
    abated = df["is_abatement"].to_numpy()
    owner = df["owner_occupied"].to_numpy()
    homes = df["category_code"].isin(HOMES_CODES).to_numpy()
    lvt_all = exp[(exp.scenario == "lvt_phase_in") & (exp.schedule_type == "all abatements")].iloc[0]
    lvt_usd, lvt_pct, ever = worst_years(df, bills, "lvt_phase_in")
    cap_usd, cap_pct, _ = worst_years(df, bills, "hh_owner_occupied")
    capped_spared = sum(np.clip(bills[f"lvt_phase_in_{t}"] - bills[f"hh_owner_occupied_{t}"], 0, None)
                        for t in range(1, HORIZON + 1))
    in_scope = abated & ever
    rows = []
    for name in DESIGNS:
        # Gross relief: every year's reduction below the plain phase-in bill, before any repayment.
        spared = sum(np.clip(bills[f"lvt_phase_in_{t}"] - bills[f"{name}_{t}"], 0, None)
                     for t in range(1, HORIZON + 1))
        r = rates[rates.scenario == name]
        if name in SHARE_DESIGNS:
            # Mixture: an eligible household pays the owner-occupant cap, an ineligible one the phase-in.
            prob = df[DESIGNS[name][3]].to_numpy() * owner
            m = in_scope

            def mix(cap_hit: np.ndarray, lvt_hit: np.ndarray) -> float:
                return float((prob[m] * cap_hit[m] + (1 - prob[m]) * lvt_hit[m]).mean())

            e = pd.Series(dict(share_over_25pct=mix(cap_pct > 25, lvt_pct > 25),
                               share_over_1000usd=mix(cap_usd > 1000, lvt_usd > 1000),
                               median_worst_usd=np.nan, p90_worst_usd=np.nan))
            helped = float((prob * (capped_spared > 1))[abated].sum())
        else:
            e = exp[(exp.scenario == name) & (exp.schedule_type == "all abatements")].iloc[0]
            helped = int((spared[abated] > 1).sum())
        rows.append(dict(
            design=name,
            net_shifted_total=float(r.shifted_to_others.sum()),
            gross_relief_to_abated=float(spared[abated].sum()),
            peak_year_shift=float(r.shifted_to_others.max()),
            peak_year=int(r.loc[r.shifted_to_others.idxmax(), "tax_year"]),
            max_others_bill_change_pct=float(r.others_bill_change_pct.max()),
            abated_parcels_helped=helped,
            relief_share_owner_occupied=float(spared[abated & owner].sum() / spared[abated].sum()),
            relief_share_residential=float(spared[abated & homes].sum() / spared[abated].sum()),
            relief_share_top_decile_parcels=float(np.sort(spared[abated])[::-1][: max(1, int(0.1 * abated.sum()))].sum()
                                                 / spared[abated].sum()),
            share_over_25pct=e.share_over_25pct, share_over_25pct_no_hh=lvt_all.share_over_25pct,
            share_over_1000usd=e.share_over_1000usd, share_over_1000usd_no_hh=lvt_all.share_over_1000usd,
            median_worst_usd=e.median_worst_usd, p90_worst_usd=e.p90_worst_usd,
        ))
    return pd.DataFrame(rows)


def others(df: pd.DataFrame, bills: Dict[str, np.ndarray]) -> pd.DataFrame:
    """Parcels without a construction abatement: how the reform and each design lands on them."""
    homes = (df["category_code"].isin(HOMES_CODES) & ~df["is_abatement"]
             & (df["exemption_kind"] != "building_share")).to_numpy()
    rest = ~df["is_abatement"].to_numpy()
    rows = []
    for t in range(1, HORIZON + 1):
        sq = bills[f"status_quo_{t}"]
        h = homes & (sq > 0)
        for k in SCENARIOS[1:]:
            new = bills[f"{k}_{t}"]
            rows.append(dict(scenario=k, t=t, tax_year=TAX_YEAR + t,
                             all_others_change_pct=100 * (new[rest].sum() / sq[rest].sum() - 1),
                             homes_change_pct=100 * (new[h].sum() / sq[h].sum() - 1),
                             homes_median_change_usd=float(np.median(new[h] - sq[h])),
                             homes_share_paying_less=float((new[h] < sq[h]).mean())))
    return pd.DataFrame(rows)


def panel(df: pd.DataFrame, bills: Dict[str, np.ndarray]) -> pd.DataFrame:
    m = df["is_abatement"].to_numpy()
    frames = []
    for t in range(HORIZON + 1):
        f = pd.DataFrame({"parcel_number": df["parcel_number"].to_numpy()[m], "schedule_type": df["schedule_type"].to_numpy()[m],
                          "abatement_year": df["abatement_year_ty"].to_numpy()[m] + t, "t": t, "tax_year": TAX_YEAR + t,
                          "running": bills[f"running_{t}"][m], "exempt_share": exempt_share(df, t)[m]})
        for k in SCENARIOS:
            f[k] = bills[f"{k}_{t}"][m]
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Abated parcels' bills under a 10-year LVT phase-in.")
    ap.add_argument("--homestead-order", choices=HOMESTEAD_ORDERS, default=DEFAULT_SETTINGS["homestead_order"])
    ap.add_argument("--baseline", choices=("levy", "rate"), default=DEFAULT_SETTINGS["baseline"],
                    help="hold today's levy (default) or today's rate, as the one-pager does")
    ap.add_argument("--revalue-bare-lots", action="store_true",
                    help="value bare lots at S5 whole in the re-split, as the one-pager does")
    a = ap.parse_args()
    settings = dict(homestead_order=a.homestead_order, baseline=a.baseline, revalue_bare_lots=a.revalue_bare_lots)
    tag = output_tag(settings)

    ty = tax_year_params(TAX_YEAR)
    df = load_inputs(ty, settings)
    print(f"{len(df):,} parcels; {int(df['is_abatement'].sum()):,} construction abatements on S5 land; "
          f"options {settings}; today's levy ${df['current_tax'].sum()/1e9:.3f}B"
          + (" held constant" if settings["baseline"] == "levy" else ", today's rate held"))
    hm = df.attrs["hmda"]
    oo_abated = df.is_abatement & df.owner_occupied
    print(f"HMDA {hm['years']}: {hm['buyers']:,} owner-occupant buyers; eligible share citywide "
          + ", ".join(f"{k} {v:.1%}" for k, v in hm["citywide"].items())
          + "; among owner-occupied abatements "
          + ", ".join(f"{k} {df.loc[oo_abated, k].mean():.1%}" for k in hm["citywide"]))
    print(f"Owner-occupancy proxy finds {df.attrs['occupancy_agreement']:.1%} of homesteaded non-abated homes; "
          f"{df.loc[df.is_abatement, 'owner_occupied'].mean():.1%} of abatements are owner-occupied")
    bills, rates = run(df, ty)
    exp = exposure(df, bills)
    tables = {
        "rates": rates,
        "by_year": by_year(df, bills),
        "exposure": exp,
        "designs": designs_summary(df, bills, rates, exp),
        "others": others(df, bills),
    }
    stem = f"philadelphia_abatement_phase_in{tag}"
    for name, tbl in tables.items():
        tbl.to_csv(DATA / f"{stem}_{name}.csv", index=False)
    panel(df, bills).to_parquet(DATA / f"{stem}_panel.parquet", index=False)
    final = rates[(rates.scenario == "lvt_phase_in") & (rates.t == HORIZON)].iloc[0]
    (DATA / f"{stem}_meta.json").write_text(json.dumps(dict(
        settings=settings, tax_year=TAX_YEAR, horizon=HORIZON, final_ratio=FINAL_RATIO,
        parcels=int(len(df)), abatements=int(df["is_abatement"].sum()),
        final_year_lvt_land_mills=float(final.land_mills), final_year_lvt_building_mills=float(final.building_mills),
        generated=pd.Timestamp.today().strftime("%Y-%m-%d"),
    ), indent=2), encoding="utf-8")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print("\nDesigns compared")
    print(tables["designs"].round(3).T.to_string())
    print("\nAmount shifted to everyone else, $M by year")
    print((rates[rates.scenario.isin(DESIGNS)].pivot(index="tax_year", columns="scenario", values="shifted_to_others") / 1e6)
          .round(1).to_string())
    print("\nWorst year while abated, share over +25% / over +$1,000, by schedule")
    e = tables["exposure"]
    print(e.pivot(index="scenario", columns="schedule_type", values="share_over_25pct").round(2).to_string())
    print(e.pivot(index="scenario", columns="schedule_type", values="share_over_1000usd").round(2).to_string())
    print("\nHomes without abatements, aggregate % change vs status quo")
    o = tables["others"]
    print(o.pivot(index="tax_year", columns="scenario", values="homes_change_pct").round(2).to_string())
    print(f"\nWrote five CSVs, a panel and {stem}_meta.json to {DATA}")


if __name__ == "__main__":
    main()
