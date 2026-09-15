"""
Philadelphia — is the 4:1 split-rate progressive by race and income, by land surface and abatement treatment?

Rebuilds every scenario from tracked TY2026 exports rather than rerunning notebooks. The exports
reconstruct exactly as `land * land_millage + building * improvement_millage` with the land millage
fixed at 4x the improvement millage, so a scenario that differs only in the abated cohort is one
rescaling away from an exported one:

- ends:    today's bill carries the abatement; the reform taxes abated buildings
           (what model.ipynb / model_lycd*.ipynb export)
- kept:    the reform carries the abatement forward (what model_lycd_reassessment.ipynb exports)
- expired: counterfactual baseline where abatements have lapsed; both bills tax the building
           (what the *_post_abatement notebooks export; asserted to match them to the cent)

For the reassessment-notebook surfaces the change is also decomposed into the flat-rate
revaluation alone (`new_tax - current_tax`) and the split-rate increment on top of it.

Strata are block-group quintiles of median household income and non-white share, cut over taxable
homes (single-family, 2-4 unit, other residential) so each holds about a fifth of them, plus bands
of Black share. Measures are aggregate % change (sum of new over sum of current), for homes and for
every taxable parcel, the share of homes paying less, and each property group's contribution to the
all-parcel change. A final check reruns the homes measure without the parcels whose land rate was
KNN-filled because they fall outside the AVM universe.

Requires the `_s5` and `_e_gbm` reassessment exports, built with
    LVT_LAND_SURFACE=s5    jupyter nbconvert --execute cities/philadelphia/model_lycd_reassessment.ipynb
    LVT_LAND_SURFACE=e_gbm jupyter nbconvert --execute cities/philadelphia/model_lycd_reassessment.ipynb

Outputs (analysis/data/, gitignored):
    philadelphia_equity_by_surface_strata.csv   one row per scenario x stratum level
    philadelphia_equity_by_surface_summary.csv  first vs last quintile per scenario
    philadelphia_equity_by_surface_bg_corr.csv  block-group correlations of the % change
    philadelphia_equity_by_surface_knn.csv      homes % change with and without KNN-filled parcels
    philadelphia_equity_by_surface_edges.csv    the quintile boundaries every stratum uses

Limits: neighbourhood-level, not household-level; parcel owners are not necessarily residents,
and nothing here models incidence on renters.
"""

import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from lvt.philadelphia import tax_year_params

TAX_YEAR = 2026
DATA = REPO_ROOT / "analysis/data"
MILLAGE = tax_year_params(TAX_YEAR).combined_mills
ABATED = "Abated / Construction Exemption"
HOMES = {"Single Family Residential", "Small Multi-Family (2-4 units)", "Other Residential"}
READ = dict(encoding="utf-8", encoding_errors="replace")

STD_SURFACES = {
    "OPA land": f"philadelphia_ty{TAX_YEAR}",
    "LYCD land": f"philadelphia_lycd_ty{TAX_YEAR}",
    "LYCD refined (FHFA shares)": f"philadelphia_lycd_refined_ty{TAX_YEAR}",
}
REASSESS_SURFACES = {
    "S2 kNN (k=20)": f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s2_k20",
    "S5 paired-sales (certified)": f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s5",
    "E-GBM (most accurate)": f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_e_gbm",
    "LYCD land, reassessment rules": f"philadelphia_lycd_reassessment_ty{TAX_YEAR}",
}
POST_ABATEMENT_CHECKS = {
    "OPA land": f"philadelphia_post_abatement_ty{TAX_YEAR}",
    "LYCD land": f"philadelphia_lycd_post_abatement_ty{TAX_YEAR}",
}
STRATA = ["inc_q", "min_q", "black_band"]
FIRST = {"inc_q": "Q1 (poorest)", "min_q": "Q1 (whitest)"}
LAST = {"inc_q": "Q5 (richest)", "min_q": "Q5 (most non-white)"}

Bills = Tuple[np.ndarray, np.ndarray]


def clean_category(s: pd.Series) -> pd.Series:
    """Repair the em dash that some exports write through cp1252."""
    return s.str.replace("�", "—", regex=False).str.replace("â€”", "—", regex=False)


def property_group(category: str) -> str:
    if category in HOMES:
        return "homes"
    if category.startswith("Vacant Land"):
        return "vacant land"
    if category == ABATED:
        return "abated"
    if category.startswith("Large Multi"):
        return "large multifamily"
    return "commercial/mixed/other"


def load_base() -> pd.DataFrame:
    cols = ["parcel_id", "property_category", "current_tax", "new_tax", "taxable_land_value",
            "taxable_improvement_value", "is_fully_exempt", "std_geoid", "median_income",
            "minority_pct", "black_pct", "land_millage", "improvement_millage"]
    return pd.read_csv(DATA / f"{STD_SURFACES['OPA land']}.csv", usecols=cols, **READ)


def treatments_from_std(d: pd.DataFrame, base: pd.DataFrame, abated: np.ndarray,
                        abated_building: np.ndarray) -> Dict[str, Bills]:
    """Three abatement treatments from a standard export, whose reform already taxes abated buildings."""
    assert (d.parcel_id.to_numpy() == base.parcel_id.to_numpy()).all(), "exports are not row-aligned"
    recon = d.taxable_land_value * d.land_millage / 1000 + d.taxable_improvement_value * d.improvement_millage / 1000
    assert np.abs(recon - d.new_tax).max() < 0.01, "export does not reconstruct as a linear split-rate bill"
    current = base.current_tax.to_numpy()
    ends = d.new_tax.to_numpy()
    im = d.improvement_millage.iloc[0]
    kept = ends - np.where(abated, d.taxable_improvement_value, 0.0) * im / 1000
    kept = kept * current.sum() / kept.sum()
    current_expired = current + abated_building * MILLAGE / 1000
    expired = ends * current_expired.sum() / ends.sum()
    return {"ends": (current, ends), "kept": (current, kept), "expired": (current_expired, expired)}


def treatments_from_reassess(f: str, base: pd.DataFrame, abated: np.ndarray,
                             abated_building: np.ndarray) -> Tuple[Dict[str, Bills], Dict[str, Bills]]:
    """Three abatement treatments plus the revaluation / split-rate decomposition from a reassessment export."""
    r = pd.read_csv(DATA / f"{f}.csv", usecols=["parcel_id", "current_tax", "new_tax", "total_change",
                                                "taxable_land_value", "taxable_improvement_value", "abated"], **READ)
    assert (r.parcel_id.to_numpy() == base.parcel_id.to_numpy()).all(), f"{f} is not row-aligned"
    assert ((r.abated.to_numpy() == 1) == abated).all(), f"{f} disagrees about which parcels are abated"
    final = (r.current_tax + r.total_change).to_numpy()
    weighted_base = 4 * r.taxable_land_value.to_numpy() + r.taxable_improvement_value.to_numpy()
    im = final.sum() / weighted_base.sum() * 1000
    assert np.abs(weighted_base * im / 1000 - final).max() < 0.01, f"{f} does not reconstruct as a 4:1 bill"
    current = r.current_tax.to_numpy()
    ends_raw = final + abated_building * im / 1000
    current_expired = current + abated_building * MILLAGE / 1000
    treatments = {
        "ends": (current, ends_raw * current.sum() / ends_raw.sum()),
        "kept": (current, final),
        "expired": (current_expired, ends_raw * current_expired.sum() / ends_raw.sum()),
    }
    decomposition = {
        "revaluation only": (current, r.new_tax.to_numpy()),
        "split-rate increment": (r.new_tax.to_numpy(), final),
    }
    return treatments, decomposition


def build_strata(base: pd.DataFrame, homes: np.ndarray) -> pd.DataFrame:
    g = base[["std_geoid", "median_income", "minority_pct", "black_pct"]].copy()
    g["group"] = clean_category(base.property_category).map(property_group)
    inc = base.median_income.where(base.median_income > 0)
    inc_edges = inc[homes].quantile([0, .2, .4, .6, .8, 1]).to_numpy()
    min_edges = base.minority_pct[homes].quantile([0, .2, .4, .6, .8, 1]).to_numpy()
    g["inc_q"] = pd.cut(inc, np.unique(inc_edges), include_lowest=True,
                        labels=["Q1 (poorest)", "Q2", "Q3", "Q4", "Q5 (richest)"])
    g["min_q"] = pd.cut(base.minority_pct, np.unique(min_edges), include_lowest=True,
                        labels=["Q1 (whitest)", "Q2", "Q3", "Q4", "Q5 (most non-white)"])
    g["black_band"] = pd.cut(base.black_pct, [-0.1, 10, 50, 80, 100.1],
                             labels=["<10% Black", "10-50%", "50-80%", ">80% Black"])
    print(f"Income quintile edges: {[int(x) for x in inc_edges]}")
    print(f"Non-white share quintile edges: {[round(float(x), 1) for x in min_edges]}")
    pd.DataFrame({"quantile": [0, .2, .4, .6, .8, 1], "median_income": inc_edges,
                  "nonwhite_pct": min_edges}).to_csv(DATA / "philadelphia_equity_by_surface_edges.csv", index=False)
    return g


def stratum_rows(g: pd.DataFrame, homes: np.ndarray, taxable: np.ndarray, surface: str, treatment: str,
                 current: np.ndarray, new: np.ndarray) -> List[dict]:
    rows = []
    df = g.assign(cur=current, new=new)
    in_scope = taxable | (new > 0) | (current > 0)
    for strat in STRATA:
        for level, s in df[in_scope].groupby(strat, observed=True):
            h = s[homes[s.index] & (s.cur > 0)]
            row = dict(surface=surface, treatment=treatment, stratum=strat, level=str(level),
                       all_pct=100 * (s.new.sum() / s.cur.sum() - 1),
                       homes_pct=100 * (h.new.sum() / h.cur.sum() - 1),
                       homes_win_pct=100 * (h.new < h.cur).mean(),
                       homes_median_usd=(h.new - h.cur).median())
            contrib = (s.new - s.cur).groupby(s.group).sum() / s.cur.sum() * 100
            row.update({f"contrib_{k}": v for k, v in contrib.items()})
            rows.append(row)
    return rows


def bg_correlations(g: pd.DataFrame, homes: np.ndarray, taxable: np.ndarray, surface: str, treatment: str,
                    current: np.ndarray, new: np.ndarray) -> List[dict]:
    rows = []
    df = g.assign(cur=current, new=new)
    for scope, mask in [("all", taxable | (new > 0)), ("homes", homes & (current > 0))]:
        bg = df[mask].groupby("std_geoid").agg(cur=("cur", "sum"), new=("new", "sum"), n=("cur", "size"),
                                               inc=("median_income", "first"), nonwhite=("minority_pct", "first"),
                                               black=("black_pct", "first"))
        bg = bg[(bg.n >= 20) & (bg.cur > 0)]
        bg["chg"] = 100 * (bg.new / bg.cur - 1)
        with_inc = bg[bg.inc > 0]
        with_race = bg.dropna(subset=["nonwhite", "black"])
        rows.append(dict(surface=surface, treatment=treatment, scope=scope, n_block_groups=len(bg),
                         r_log_income=np.corrcoef(np.log(with_inc.inc), with_inc.chg)[0, 1],
                         r_nonwhite=np.corrcoef(with_race.nonwhite, with_race.chg)[0, 1],
                         r_black=np.corrcoef(with_race.black, with_race.chg)[0, 1]))
    return rows


def knn_check(g: pd.DataFrame, homes: np.ndarray) -> pd.DataFrame:
    rows = []
    for surface in ["S5 paired-sales (certified)", "E-GBM (most accurate)"]:
        r = pd.read_csv(DATA / f"{REASSESS_SURFACES[surface]}.csv",
                        usecols=["current_tax", "total_change", "land_surface_source"], **READ)
        df = g.assign(cur=r.current_tax, new=r.current_tax + r.total_change, knn=r.land_surface_source.eq("knn"))
        df = df[homes & (df.cur > 0)]
        for strat in ["inc_q", "min_q"]:
            for level, s in df.groupby(strat, observed=True):
                without = s[~s.knn]
                rows.append(dict(surface=surface, stratum=strat, level=str(level),
                                 knn_share_pct=100 * s.knn.mean(),
                                 homes_pct=100 * (s.new.sum() / s.cur.sum() - 1),
                                 homes_pct_without_knn=100 * (without.new.sum() / without.cur.sum() - 1)))
    return pd.DataFrame(rows)


def main() -> None:
    base = load_base()
    taxable = (~base.is_fully_exempt).to_numpy()
    homes = clean_category(base.property_category).isin(HOMES).to_numpy() & taxable
    abated = (base.property_category == ABATED).to_numpy()
    # The standard exports restore OPA's exempt_building for abated parcels; reuse that one value everywhere
    abated_building = np.where(abated, base.taxable_improvement_value, 0.0)

    scenarios: Dict[str, Dict[str, Bills]] = {}
    for surface, f in STD_SURFACES.items():
        d = base if surface == "OPA land" else pd.read_csv(DATA / f"{f}.csv", usecols=base.columns, **READ)
        scenarios[surface] = treatments_from_std(d, base, abated, abated_building)
    decompositions: Dict[str, Dict[str, Bills]] = {}
    for surface, f in REASSESS_SURFACES.items():
        scenarios[surface], decompositions[surface] = treatments_from_reassess(f, base, abated, abated_building)

    # Step 1: the constructed "expired" treatment must reproduce the post-abatement notebooks
    for surface, f in POST_ABATEMENT_CHECKS.items():
        post = pd.read_csv(DATA / f"{f}.csv", usecols=["current_tax", "new_tax"], **READ)
        cur, new = scenarios[surface]["expired"]
        assert np.abs(cur - post.current_tax).max() < 0.01 and np.abs(new - post.new_tax).max() < 0.01, (
            f"constructed expired-abatement bills for {surface} do not match {f}")
    print("Constructed expired-abatement scenarios match the post-abatement exports to the cent")

    g = build_strata(base, homes)
    rows, corr_rows = [], []
    for surface, parts in list(scenarios.items()) + list(decompositions.items()):
        for treatment, (cur, new) in parts.items():
            rows += stratum_rows(g, homes, taxable, surface, treatment, cur, new)
            corr_rows += bg_correlations(g, homes, taxable, surface, treatment, cur, new)
    strata = pd.DataFrame(rows)
    corr = pd.DataFrame(corr_rows)

    summary = []
    for (surface, treatment), grp in strata.groupby(["surface", "treatment"], sort=False):
        row = dict(surface=surface, treatment=treatment)
        for strat, tag in [("inc_q", "income"), ("min_q", "race")]:
            first = grp[(grp.stratum == strat) & (grp.level == FIRST[strat])].iloc[0]
            last = grp[(grp.stratum == strat) & (grp.level == LAST[strat])].iloc[0]
            for m in ["homes_pct", "homes_win_pct", "all_pct"]:
                row[f"{tag}_{m}_first"] = first[m]
                row[f"{tag}_{m}_last"] = last[m]
        row["min_homes_win_pct_any_stratum"] = grp.homes_win_pct.min()
        summary.append(row)
    summary = pd.DataFrame(summary)
    knn = knn_check(g, homes)

    strata.to_csv(DATA / "philadelphia_equity_by_surface_strata.csv", index=False)
    summary.to_csv(DATA / "philadelphia_equity_by_surface_summary.csv", index=False)
    corr.to_csv(DATA / "philadelphia_equity_by_surface_bg_corr.csv", index=False)
    knn.to_csv(DATA / "philadelphia_equity_by_surface_knn.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 50)
    print("\nFirst vs last quintile (income: poorest vs richest; race: whitest vs most non-white)")
    print(summary.round(1).to_string(index=False))
    print("\nHomes % change with and without KNN-filled parcels")
    print(knn.round(1).to_string(index=False))
    print(f"\nWrote five CSVs to {DATA}")


if __name__ == "__main__":
    main()
