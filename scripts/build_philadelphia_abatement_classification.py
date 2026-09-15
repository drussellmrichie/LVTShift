"""Classify Philadelphia's abatement-type parcels by abatement schedule, from their billed history.

OPA's parcel data records how much building value is exempt, not which program exempts it. That
matters because the 10-year construction abatement is three different schedules:

  - **old_flat_100** -- 100% of the improvement exempt for 10 years, then fully taxable. Every
    abatement applied for before 2022-01-01.
  - **new_graduated_residential** -- residential new construction applied for from 2022-01-01:
    exempt share 100%, 90%, ..., 10% in years 1-10.
  - **new_flat_90_commercial** -- commercial/industrial abatements applied for from 2022-01-01:
    90% exempt for 10 years. Most of these parcels follow an alteration permit rather than a
    new-construction one, so the 90% rule reaches commercial improvements as well as new buildings.

Residential rehabilitation abatements (which exempt only the value the improvement added) were not
changed by the reform, so they stay on the flat schedule; they show up here as `old_flat_partial`.

**Method: read the schedule off each parcel's exemption history.** Carto's `assessments` table
holds every parcel's `exempt_building` for each tax year from 2015. Because a schedule is a share
of the improvement, `exempt share = non-homestead exemption / gross building` traces it directly:
a 10-point annual step down is the graduated schedule, a held 0.90 is the commercial one, a held
1.00 is the old one. This reads the billed quantity rather than inferring it from permits, which
say only that work was authorised, not that relief was granted or on what terms.

**Not every building exemption is an abatement.** The population is the repo's own
`building_share` exemption kind (`reallocate_land_within_total`), and it includes relief that grows
with assessed value -- present since before 2015, stepping up at every reassessment, rarely 100%
exempt, and almost never preceded by a building permit. Its program is not identified (it behaves
like an assessment-increase cap), but it cannot be a construction abatement, whose share can only
hold or fall. Such parcels are labelled
`non_abatement_relief` and excluded from abatement counts:

  - relief continuously present since the first year of history (>= 12 tax years), or
  - an exempt share that rises by more than 2 points to a value below 100% after its first
    two years (a prorated first year rising to 100% is an abatement starting mid-year).

The homestead amount for each year is inferred from the data as the modal exempt total and
checked against `tax_year_params` wherever that has the year. Which parcels carry a homestead is
known only for the current vintage (see `build_philadelphia_parcel_cache.py`), so the homestead is
netted out using today's flag in every year; parcels where that leaves no active relief in the
target year are `unresolved`.

L&I permits (`permits` on phl.carto.com) are joined as an independent check, not as the
classifier: graduated parcels should mostly carry a residential new-construction permit issued
from 2021 on, and old-flat 100% parcels a new-construction permit issued before 2022.

Usage:
    python scripts/build_philadelphia_abatement_classification.py --year 2026
    python scripts/build_philadelphia_abatement_classification.py --year 2026 --force
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.parse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lvt.philadelphia import (  # noqa: E402
    SUPPORTED_TAX_YEARS, parcel_cache_path, reallocate_land_within_total, tax_year_params,
)

CARTO = "https://phl.carto.com/api/v2/sql"
DATA_DIR = Path("cities/philadelphia/data")
HISTORY_DIR = DATA_DIR / "exemption_history"
FIRST_HISTORY_YEAR = 2015
REFORM_FIRST_TAX_YEAR = 2022   # earliest tax year a post-2021 application could first be abated
ACTIVE_FLOOR = 1_000.0         # non-homestead exemption dollars that count as active relief
STEP_TOL = 0.006               # tolerance on a 10-point step / a 0.90 share
RISE_TOL = 0.02
ABATEMENT_LIFE = 10
ABATEMENT_SCHEDULES = ["old_flat_100", "old_flat_partial", "new_graduated_residential", "new_flat_90_commercial"]


def _carto_csv(query: str, timeout: int = 900) -> pd.DataFrame:
    url = f"{CARTO}?q={urllib.parse.quote(query)}&format=csv"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), low_memory=False, dtype={"parcel_number": str})


def _zfill(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64").astype(str).str.zfill(9)


def load_exemption_history(last_year: int, force: bool = False) -> pd.DataFrame:
    """Per-parcel, per-tax-year values for every parcel with a building exemption, cached by year."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for y in range(FIRST_HISTORY_YEAR, last_year + 1):
        path = HISTORY_DIR / f"exempt_building_ty{y}.parquet"
        if force or not path.exists():
            print(f"  downloading TY{y} exemptions ...")
            df = _carto_csv(
                "SELECT parcel_number, taxable_land, taxable_building, exempt_land, exempt_building "
                f"FROM assessments WHERE year = '{y}' AND exempt_building > 0"
            )
            if df.empty:
                break
            df["parcel_number"] = _zfill(df["parcel_number"])
            df["year"] = y
            df.to_parquet(path)
        frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True)


def infer_homestead_amounts(history: pd.DataFrame) -> dict[int, float]:
    """The statutory homestead for each year, as the modal exempt total, checked against known years."""
    total = (history["exempt_land"] + history["exempt_building"]).round(0)
    amounts = {int(y): float(t.mode().iloc[0]) for y, t in total.groupby(history["year"])}
    for y, amt in amounts.items():
        if y in SUPPORTED_TAX_YEARS and tax_year_params(y).homestead_exemption != amt:
            raise ValueError(
                f"Modal exempt total for TY{y} is ${amt:,.0f} but tax_year_params says the homestead "
                f"is ${tax_year_params(y).homestead_exemption:,}. Either the history pull is wrong or "
                "lvt/philadelphia.py is."
            )
    return amounts


def _trajectory_features(hist: pd.DataFrame, year: int) -> pd.DataFrame:
    h = hist.sort_values(["parcel_number", "year"]).copy()
    active = h.pivot_table(index="parcel_number", columns="year", values="active", aggfunc="max")
    active = active.reindex(columns=range(FIRST_HISTORY_YEAR, h["year"].max() + 1))
    active = active.astype("boolean").fillna(False).astype(bool)

    # First year of the unbroken run of active relief that contains the target year.
    arr = active.to_numpy()
    cols = list(active.columns)
    t = cols.index(year)
    start = np.full(len(active), np.nan)
    for i in range(len(active)):
        if not arr[i, t]:
            continue
        j = t
        while j > 0 and arr[i, j - 1]:
            j -= 1
        start[i] = cols[j]
    feats = pd.DataFrame({"start_year": start}, index=active.index)

    h = h.merge(feats, left_on="parcel_number", right_index=True)
    h = h[h["year"] >= h["start_year"]].copy()
    h["share"] = (h["other"] / h["gross_building"].where(h["gross_building"] > 0)).clip(upper=1.0)
    g = h.groupby("parcel_number")
    h["d_share"] = g["share"].diff()
    h["years_in"] = h["year"] - h["start_year"]

    rise = h[(h["d_share"] > RISE_TOL) & (h["share"] < 0.995) & (h["years_in"] >= 2) & h["active"]]
    step = h[(h["d_share"] + 0.1).abs() < STEP_TOL]
    at = h[h["year"] == year].set_index("parcel_number")

    feats["share_at_start"] = g["share"].first()
    feats["share_ty"] = at["share"]
    feats["exempt_building_ty"] = at["other"]
    feats["grad_steps"] = step.groupby("parcel_number").size()
    feats["full_years"] = h[h["share"] > 0.995].groupby("parcel_number").size()
    feats["flat90_years"] = h[(h["share"] - 0.9).abs() < STEP_TOL].groupby("parcel_number").size()
    feats["rises"] = rise.groupby("parcel_number").size()
    for c in ("grad_steps", "full_years", "flat90_years", "rises"):
        feats[c] = feats[c].fillna(0).astype(int)
    return feats


def _assign_schedule(f: pd.DataFrame) -> pd.Series:
    s = pd.Series("unresolved", index=f.index, dtype=object)
    has = f["start_year"].notna()
    post = has & (f["start_year"] >= REFORM_FIRST_TAX_YEAR)
    non_abatement = has & ((f["start_year"] <= FIRST_HISTORY_YEAR) | (f["rises"] > 0))
    grad = post & (f["grad_steps"] > 0) & ~non_abatement
    flat90 = post & (f["flat90_years"] >= 2) & (f["full_years"] == 0) & ~grad & ~non_abatement
    full = has & (f["full_years"] > 0) & ~grad & ~flat90 & ~non_abatement
    partial = has & ~non_abatement & ~grad & ~flat90 & ~full
    s[partial] = "old_flat_partial"
    s[full] = "old_flat_100"
    s[flat90] = "new_flat_90_commercial"
    s[grad] = "new_graduated_residential"
    s[non_abatement] = "non_abatement_relief"
    return s


def _permit_check(out: pd.DataFrame) -> pd.DataFrame:
    """Permit evidence from the live L&I `permits` table, for validation only.

    Use `permits`, not `li_permits`: the latter is an archive that stops in March 2020 and so
    cannot see a single post-reform abatement. L&I labels apartment buildings "Commercial" by
    construction code, so `nc_permit_comm_res` is not the abatement's residential/commercial class.
    """
    df = _carto_csv(
        "SELECT opa_account_num, permittype, typeofwork, commercialorresidential, permitissuedate "
        "FROM permits WHERE permittype IN ('BP_NEWCNST', 'BP_ALTER', 'BP_ADDITON') "
        "OR typeofwork ILIKE '%New Construction%' OR typeofwork ILIKE '%Addition%Alteration%'"
    )
    df["opa_account_num"] = _zfill(df["opa_account_num"])
    df["permitissuedate"] = pd.to_datetime(df["permitissuedate"], errors="coerce", utc=True)
    df = df.dropna(subset=["permitissuedate"]).sort_values("permitissuedate")
    tow = df["typeofwork"].fillna("")
    is_nc = (df["permittype"] == "BP_NEWCNST") | tow.str.contains("New Construction", case=False)

    latest_nc = df[is_nc].drop_duplicates("opa_account_num", keep="last").set_index("opa_account_num")
    out = out.assign(
        nc_permit_date=out.index.map(latest_nc["permitissuedate"]),
        nc_permit_comm_res=out.index.map(latest_nc["commercialorresidential"]),
    )

    # A rehab abatement follows an alteration permit; look for one in the four years before relief starts.
    alt = df.loc[~is_nc, ["opa_account_num", "permitissuedate"]].rename(columns={"opa_account_num": "parcel_number"})
    alt["permit_year"] = alt["permitissuedate"].dt.year
    alt = alt.merge(out["start_year"], left_on="parcel_number", right_index=True)
    hit = alt[(alt["permit_year"] <= alt["start_year"]) & (alt["permit_year"] >= alt["start_year"] - 4)]
    out["alt_permit_before_start"] = out.index.isin(set(hit["parcel_number"]))
    return out


def classify(year: int, force_history: bool = False, check_permits: bool = True) -> tuple[pd.DataFrame, dict]:
    cache = parcel_cache_path(year, data_dir=DATA_DIR)
    if not cache.exists():
        raise FileNotFoundError(f"{cache} missing: python scripts/build_philadelphia_parcel_cache.py --year {year}")
    gdf = gpd.read_parquet(cache)
    gdf["parcel_number"] = _zfill(gdf["parcel_number"])
    TY = tax_year_params(year)

    gdf["_gross_land"] = gdf["taxable_land"] + gdf["exempt_land"]
    kinds = reallocate_land_within_total(gdf, new_land_col="_gross_land", homestead_cap=TY.homestead_exemption)
    pop = gdf.loc[kinds.exemption_kind == "building_share", ["parcel_number", "homestead_exemption"]]
    print(f"  {len(pop):,} building-share exemption parcels in TY{year}")

    history = load_exemption_history(max(SUPPORTED_TAX_YEARS), force=force_history)
    if year not in set(history["year"]):
        raise ValueError(f"Exemption history has no TY{year}")
    homestead = infer_homestead_amounts(history)

    h = history[history["parcel_number"].isin(pop["parcel_number"])].copy()
    # Today's homestead as a fraction of today's statutory amount, so a partial homestead (shared
    # ownership) nets out at its own share of each year's statutory amount rather than the full cap.
    hs_frac = (pop.set_index("parcel_number")["homestead_exemption"] / TY.homestead_exemption).clip(0, 1)
    exempt_total = h["exempt_land"] + h["exempt_building"]
    h["other"] = (exempt_total - h["parcel_number"].map(hs_frac).fillna(0) * h["year"].map(homestead)).clip(lower=0)
    h["gross_building"] = h["taxable_building"] + h["exempt_building"]
    h["active"] = h["other"] > ACTIVE_FLOOR

    feats = _trajectory_features(h, year).reindex(pop["parcel_number"])
    feats["schedule_type"] = _assign_schedule(feats)
    feats["abatement_year_ty"] = year - feats["start_year"] + 1
    # Last tax year with relief. The first year of relief is often a partial (prorated) year, and OPA's
    # ten years run from the month relief began, so a prorated tail can reach one tax year later.
    feats["last_abated_tax_year"] = np.where(feats["schedule_type"].isin(ABATEMENT_SCHEDULES),
                                             feats["start_year"] + ABATEMENT_LIFE - 1, np.nan)
    if check_permits:
        feats = _permit_check(feats)

    abatements = feats["schedule_type"].isin(ABATEMENT_SCHEDULES)
    diagnostics = {
        "year": year,
        "homestead_by_year": homestead,
        "n_building_share": int(len(pop)),
        "schedule_counts": feats["schedule_type"].value_counts().to_dict(),
        "exempt_building_by_schedule": feats.groupby("schedule_type")["exempt_building_ty"].sum().to_dict(),
        "n_abatements": int(abatements.sum()),
        "expirations": expiration_table(feats[abatements]),
    }
    if check_permits:
        permit_year = feats["nc_permit_date"].dt.year
        grad = feats["schedule_type"] == "new_graduated_residential"
        full = feats["schedule_type"] == "old_flat_100"
        diagnostics["grad_with_nc_permit_2021_on"] = float((permit_year[grad] >= 2021).mean())
        diagnostics["grad_permit_residential_share"] = float(
            (feats.loc[grad & feats["nc_permit_date"].notna(), "nc_permit_comm_res"] == "Residential").mean())
        diagnostics["old100_with_nc_permit_before_2022"] = float((permit_year[full] < 2022).mean())
        diagnostics["old100_with_any_nc_permit"] = float(feats.loc[full, "nc_permit_date"].notna().mean())
        alt_rate = feats.groupby("schedule_type")["alt_permit_before_start"].mean()
        diagnostics["alt_permit_rate_by_schedule"] = alt_rate.to_dict()
        # The classifier never reads permits, so these are independent: if the history rules were
        # sorting the wrong populations, the permit rates are what would collapse.
        checks = {
            "graduated parcels with a 2021+ new-construction permit": (diagnostics["grad_with_nc_permit_2021_on"], 0.5),
            "old-flat-100 parcels with a new-construction permit": (diagnostics["old100_with_any_nc_permit"], 0.4),
            "partial-share parcels with a prior alteration permit": (alt_rate.get("old_flat_partial", 0.0), 0.4),
        }
        for name, (value, floor) in checks.items():
            if value < floor:
                raise ValueError(f"Permit cross-check failed: {name} = {value:.1%} (floor {floor:.0%}).")
        if alt_rate.get("non_abatement_relief", 0.0) > 0.2:
            raise ValueError("Relief classed as non-abatement carries alteration permits at "
                             f"{alt_rate['non_abatement_relief']:.1%}; it may be rehab abatements.")
    return feats.reset_index(), diagnostics


def expiration_table(abated: pd.DataFrame) -> pd.DataFrame:
    """Abatements by last abated tax year and schedule: parcel counts and exempt building value."""
    g = abated.groupby(["last_abated_tax_year", "schedule_type"])
    t = pd.DataFrame({"parcels": g.size(), "exempt_building": g["exempt_building_ty"].sum()}).reset_index()
    t["last_abated_tax_year"] = t["last_abated_tax_year"].astype(int)
    return t


def describe(d: dict) -> str:
    lines = [f"TY{d['year']}: {d['n_building_share']:,} building-share exemption parcels, "
             f"{d['n_abatements']:,} classified as construction abatements"]
    for k, v in sorted(d["schedule_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {k:28s} {v:>7,}  ${d['exempt_building_by_schedule'].get(k, 0) / 1e9:6.2f}B exempt building")
    if "grad_with_nc_permit_2021_on" in d:
        lines += [
            "Permit cross-check (new-construction permits on the live L&I table):",
            f"  graduated parcels with an NC permit issued 2021+: {d['grad_with_nc_permit_2021_on']:.1%} "
            f"(of those with a permit, residential: {d['grad_permit_residential_share']:.1%})",
            f"  old-flat-100 parcels with any NC permit: {d['old100_with_any_nc_permit']:.1%}; "
            f"issued before 2022: {d['old100_with_nc_permit_before_2022']:.1%}",
            "  alteration permit in the 4 years before relief starts: "
            + ", ".join(f"{k} {v:.1%}" for k, v in sorted(d["alt_permit_rate_by_schedule"].items())),
        ]
    e = d["expirations"]
    wide = e.pivot(index="last_abated_tax_year", columns="schedule_type", values="parcels").fillna(0).astype(int)
    wide["all"] = wide.sum(axis=1)
    wide["exempt_building_$M"] = (e.groupby("last_abated_tax_year")["exempt_building"].sum() / 1e6).round(0)
    lines += ["Abatements by last abated tax year (parcels):", wide.to_string()]
    return "\n".join(lines)


def build(year: int, force: bool = False, check_permits: bool = True) -> Path:
    out_path = DATA_DIR / f"abatement_classification_ty{year}.parquet"
    if out_path.exists() and not force:
        print(f"{out_path} already exists -- pass --force to rebuild")
        return out_path
    out, diagnostics = classify(year, check_permits=check_permits)
    out.to_parquet(out_path)
    diagnostics["expirations"].to_csv(DATA_DIR / f"abatement_expirations_ty{year}.csv", index=False)
    print(f"Wrote {out_path}")
    print(describe(diagnostics))
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-permits", action="store_true", help="skip the L&I permit cross-check")
    args = ap.parse_args()
    build(args.year, args.force, check_permits=not args.no_permits)
    return 0


if __name__ == "__main__":
    sys.exit(main())
