"""Compare OPA's land/building split with three alternatives, inside OPA's own total.

Question: OPA gives most improved parcels a land share of exactly 20%. The Homestead Exemption
and the 10-year construction abatement are both booked against the building line. Does the
20% default therefore mis-state anyone's bill under today's single millage, and who?

Method. Hold every parcel's TOTAL assessment and the millage fixed, and re-split the total into
land and building using an alternative land value. The bill can then move only where an
exemption depends on the split. Two alternatives feed the dollar comparisons here, deliberately
unlike each other:

  s5    the sales-based surface `philly_open_avmkit` certifies (fit on vacant-lot and teardown
        sales, then painted onto every parcel's lot area)
  LYCD  a zone-rate allocation anchored to OPA's own 20% convention for improved parcels -- kept
        only as a mechanism check (it shows the split CAN move a bill), not as a vote on
        direction: it redistributes OPA's own 20% by lot size and cannot say anything s5 or FHFA
        haven't already said about where land is actually worth more or less.

A third, FHFA's appraisal-based single-family land share by census tract, appears only in the
share-level sections (`land_shares`, `tract_agreement_with_fhfa`) below, comparing land SHARES
by tract -- not converted to a per-parcel dollar bill effect. Both ways of doing that conversion
were tried and rejected: `share * the abated home's own (inflated, post-construction) total`
overstates land by ~65% against the 440 abated homes with their own recorded lot sale; `share *
the tract's TYPICAL house's total, scaled to this lot's area` understates it by ~34% (developers
buy the standout lots in a tract, not its median one). See `03_lot_sale_witness.py` for the
actual market check on abated homes: their own pre-construction lot sale, not an inference from
a tract aggregate.

The abatement cohort here is restricted to `schedule_type`s the repo's own classifier
(`build_philadelphia_abatement_classification.py`) confirms are construction abatements.
`non_abatement_relief` (38% of `exemption_kind == 'building_share'` parcels) is an unidentified
relief program whose exempt share RISES at reassessment -- an abatement's can only hold or fall
-- and `unresolved` is genuinely unclassified; both are excluded from every table below, not just
counted separately, because they were never abatements and a re-split cannot logically be
"correcting" a program it wasn't modeled to touch.

s5 and LYCD come from the repo's own re-split (`reallocate_land_within_total`, via the
`model_lycd_reassessment` notebook exports), read off the exported `alloc_tax_change`. That
export is also reproduced here with a closed form, `s * (L_alt - L_opa) * millage / 1000` with
`s` the exempt share of the building line -- asserted against the export before use, since
`03_lot_sale_witness.py` needs the same closed form for a land value that has no export.

Reads  analysis/data/philadelphia_lycd_reassessment_ty2026{,_s5}.csv
       cities/philadelphia/data/fhfa_land_share_by_tract.csv
       cities/philadelphia/data/abatement_classification_ty2026.parquet
Writes analysis/opa_split_equity/out/*.csv

Run from the repo root:
    python analysis/opa_split_equity/02_split_vs_alternatives.py

Importable: `03_lot_sale_witness.py` reuses `load`, `billed`, `closed_form_change` and
`ABATEMENT_SCHEDULES` from here so the two scripts share one cohort definition.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from lvt.philadelphia import tax_year_params  # noqa: E402

DATA = ROOT / "analysis" / "data"
FHFA = ROOT / "cities" / "philadelphia" / "data" / "fhfa_land_share_by_tract.csv"
ABATEMENT_CLASS = ROOT / "cities" / "philadelphia" / "data" / "abatement_classification_ty2026.parquet"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TAX_YEAR = 2026
MILLAGE = tax_year_params(TAX_YEAR).combined_mills
TOL = 0.01                   # dollars; a bill "moves" if it changes by more than a cent
SHARE_GAP = 0.05             # a land share is "off" the alternative if it differs by > 5 points
FULL_ABATEMENT = 0.99        # exempt share of the building line at or above which it is a full abatement
FHFA_CATEGORIES = ("Single Family Residential", "Abated / Construction Exemption")
ALTS = {"s5": "s5 (sales-based)", "ly": "LYCD (zone-rate)"}
# Real construction-abatement schedules, per cities/philadelphia/CLAUDE.md's classifier notes.
# Excludes `non_abatement_relief` (unidentified program, exempt share can rise -- not an
# abatement) and `unresolved`.
ABATEMENT_SCHEDULES = ("old_flat_100", "old_flat_partial", "new_graduated_residential",
                       "new_flat_90_commercial")

S5_COLS = ["parcel_id", "property_category", "current_tax", "alloc_land", "alloc_building",
           "alloc_tax_change", "opa_gross_land", "opa_gross_building", "taxable_improvement_value",
           "exemption_kind", "homestead_active", "institutional_exempt", "market_value",
           "std_geoid", "median_income", "minority_pct", "black_pct"]


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Drop repeated parcel ids, asserting the repeats are exact copies."""
    assert len(df.drop_duplicates()) == df.parcel_id.nunique(), "a repeated parcel id has differing rows"
    return df.drop_duplicates("parcel_id")


def load() -> pd.DataFrame:
    """One frame per parcel: OPA's split plus each alternative's land value and bill change."""
    s5 = pd.read_csv(DATA / f"philadelphia_lycd_reassessment_ty{TAX_YEAR}_s5.csv",
                     usecols=S5_COLS, dtype={"parcel_id": str, "std_geoid": str})
    ly = pd.read_csv(DATA / f"philadelphia_lycd_reassessment_ty{TAX_YEAR}.csv",
                     usecols=["parcel_id", "alloc_land", "alloc_tax_change", "exemption_kind"],
                     dtype={"parcel_id": str})
    # A parcel id can repeat in the OPA extract (three identical rows for one homesteaded
    # parcel in TY2026); keep one copy, and only when the copies really are identical.
    s5, ly = (_dedupe(x) for x in (s5, ly))
    ly = ly.rename(columns={"alloc_land": "ly_land", "alloc_tax_change": "ly_chg",
                            "exemption_kind": "ly_kind"})
    df = s5.rename(columns={"alloc_land": "s5_land", "alloc_tax_change": "s5_chg"})
    df = df.merge(ly, on="parcel_id", validate="one_to_one")
    assert (df.exemption_kind == df.ly_kind).all(), "the two exports classify exemptions differently"

    df["opa_land"] = df.opa_gross_land
    df["total"] = df.opa_gross_land + df.opa_gross_building
    df["tract"] = df.std_geoid.str[:11]
    fh = pd.read_csv(FHFA, dtype={"tract_geoid": str}).drop_duplicates("tract_geoid")
    df["fhfa_share"] = df.tract.map(fh.set_index("tract_geoid").fhfa_land_share)

    # FHFA speaks to houses, so its SHARE is compared only there; every other parcel is left at
    # OPA's own share for that comparison. No FHFA dollar land value is constructed here -- see
    # the module docstring for why both ways of doing that conversion were rejected.
    df["fhfa_in_scope"] = df.property_category.isin(FHFA_CATEGORIES) & df.fhfa_share.notna()

    # Exempt share of the building line, read off OPA's recorded taxable building.
    df["exempt_share"] = (1 - df.taxable_improvement_value / df.opa_gross_building.where(df.opa_gross_building > 0)).clip(0, 1)

    cls = pd.read_parquet(ABATEMENT_CLASS, columns=["parcel_number", "schedule_type"])
    cls = cls.rename(columns={"parcel_number": "parcel_id"})
    cls["parcel_id"] = cls.parcel_id.astype(str)
    df = df.merge(cls, on="parcel_id", how="left")
    return df


def billed(df: pd.DataFrame) -> pd.DataFrame:
    """Parcels with a real bill today: the population every per-parcel claim is about."""
    return df[(df.institutional_exempt == 0) & (df.current_tax > 0)]


def closed_form_change(df: pd.DataFrame, land_col: str) -> pd.Series:
    """Bill change for an abatement-type parcel when its land is re-split to `land_col`."""
    return df.exempt_share * (df[land_col] - df.opa_land) * MILLAGE / 1000


def check_closed_form(cohort: pd.DataFrame) -> None:
    """The closed form must reproduce the repo's own re-split on the parcels it will be used for."""
    for col, exported in (("s5_land", "s5_chg"), ("ly_land", "ly_chg")):
        err = (closed_form_change(cohort, col) - cohort[exported]).abs()
        assert (err < 1).all(), f"closed form disagrees with the exported {exported} on {(err >= 1).sum()} parcels"


def abatement_cohort(df: pd.DataFrame) -> pd.DataFrame:
    """Billed parcels on a REAL construction-abatement schedule, without a homestead.

    Homestead-active parcels in this class (about 5%) mix two exemptions on one line and are
    left out rather than approximated. `non_abatement_relief` and `unresolved` parcels are
    dropped here, not just flagged, per the module docstring -- restricting to real schedules
    shrinks the building-line-exemption population from 33,746 to about 20,200.
    """
    c = billed(df)
    c = c[(c.exemption_kind == "building_share") & (c.homestead_active == 0)
          & (c.schedule_type.isin(ABATEMENT_SCHEDULES))].copy()
    c["abatement"] = np.where(c.exempt_share >= FULL_ABATEMENT, "full", "partial")
    check_closed_form(c)
    return c


def who_can_move(df: pd.DataFrame) -> pd.DataFrame:
    """Bill movement by exemption kind, from the repo's own re-split: the mechanism."""
    b = billed(df)
    rows = {}
    for key in ("s5", "ly"):
        g = b.groupby("exemption_kind")[f"{key}_chg"].agg(
            n_parcels="size", n_moved=lambda s: int((s.abs() > TOL).sum()),
            net_change_usd="sum", gross_up_usd=lambda s: s.clip(lower=0).sum(),
            gross_down_usd=lambda s: s.clip(upper=0).sum())
        rows[ALTS[key]] = g
    m = pd.concat(rows, names=["alternative"])
    m["pct_moved"] = 100 * m.n_moved / m.n_parcels
    return m


def land_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Land share of total, OPA vs each alternative, on improved parcels and on houses.

    FHFA is already a share (by tract, for single-family), so it needs no total-value
    conversion here -- unlike the cohort dollar tables, which is exactly why it can appear in
    this comparison and not those.
    """
    imp = billed(df)
    imp = imp[(imp.opa_gross_building > 0) & (imp.opa_land > 0)]
    houses = imp[imp.fhfa_in_scope & (imp.property_category == "Single Family Residential")]
    rows = {}
    for scope, sub in (("all improved, billed", imp), ("single-family, FHFA tracts", houses)):
        shares = {"OPA": sub.opa_land / sub.total, "s5": sub.s5_land / sub.total,
                  "LYCD": sub.ly_land / sub.total, "FHFA": sub.fhfa_share}
        opa_share = shares["OPA"]
        for name, share in shares.items():
            weighted = (sub.opa_land if name == "OPA" else sub.s5_land if name == "s5"
                       else sub.ly_land if name == "LYCD" else share * sub.total).sum() / sub.total.sum()
            rows[(scope, name)] = {
                "n": int(share.notna().sum()), "mean_share": share.mean(),
                "value_weighted_share": weighted, "median_share": share.median(),
                "sd_share": share.std(),
                "pct_within_5pt_of_opa": 100 * ((share - opa_share).abs() <= SHARE_GAP).mean()}
    out = pd.DataFrame(rows).T
    out.index.names = ["scope", "surface"]
    return out


def tract_agreement(df: pd.DataFrame) -> pd.DataFrame:
    """Tract-median land share of houses vs FHFA: level gap and rank agreement."""
    h = billed(df)
    h = h[h.fhfa_in_scope & (h.property_category == "Single Family Residential")
          & (h.opa_gross_building > 0) & (h.opa_land > 0)]
    t = pd.DataFrame({name: (h[col] / h.total).groupby(h.tract).median()
                      for name, col in (("OPA", "opa_land"), ("s5", "s5_land"), ("LYCD", "ly_land"))})
    t["FHFA"] = h.groupby("tract").fhfa_share.first()
    rows = {n: {"tracts": len(t), "mean_gap_vs_fhfa_pt": 100 * (t[n] - t.FHFA).mean(),
                "mean_abs_gap_vs_fhfa_pt": 100 * (t[n] - t.FHFA).abs().mean(),
                "corr_with_fhfa": t[n].corr(t.FHFA)} for n in ("OPA", "s5", "LYCD")}
    return pd.DataFrame(rows).T


def cohort_totals(c: pd.DataFrame) -> pd.DataFrame:
    """Net bill change for the abatement cohort under each alternative.

    Both alternatives are measured on the SAME parcels, so the columns differ only in the land
    value they assume. No FHFA-based dollar figure appears here -- see the module docstring; the
    market-witnessed figure is `03_lot_sale_witness.py`'s `full_abatement_at_lot_price`.
    """
    scope = c
    rows = {}
    for label, sub in (("full abatement", scope[scope.abatement == "full"]),
                       ("partial abatement", scope[scope.abatement == "partial"])):
        for key in ("s5", "ly"):
            ch = sub[f"{key}_chg"]
            rows[(label, ALTS[key])] = {
                "n": len(sub), "current_tax_usd": sub.current_tax.sum(),
                "net_change_usd": ch.sum(), "net_pct_of_cohort_tax": 100 * ch.sum() / sub.current_tax.sum(),
                "gross_up_usd": ch.clip(lower=0).sum(), "gross_down_usd": ch.clip(upper=0).sum(),
                "pct_pay_more": 100 * (ch > TOL).mean(), "pct_pay_less": 100 * (ch < -TOL).mean(),
                "median_change_usd": ch.median()}
    out = pd.DataFrame(rows).T
    out.index.names = ["cohort", "alternative"]
    return out


def cohort_by_stratum(c: pd.DataFrame, allb: pd.DataFrame, by: str, q: int = 5) -> pd.DataFrame:
    """Net bill change for FULL abatements, by tract stratum.

    Quintiles are cut on ALL billed parcels, so a stratum's label describes where the tract sits
    in the city, not within the cohort. Only full abatements are stratified: they are the ones
    whose dependence on the split (exempt = the whole improvement) does not rest on how a
    partial exemption was computed.
    """
    edges = pd.qcut(allb[by].dropna(), q, retbins=True, duplicates="drop")[1]
    core = c[c.abatement == "full"].copy()
    core["stratum"] = pd.cut(core[by], edges, labels=[f"Q{i}" for i in range(1, len(edges))],
                             include_lowest=True)
    rows = {}
    for key in ("s5", "ly"):
        g = core.groupby("stratum", observed=True).agg(
            n=("current_tax", "size"), current_tax_usd=("current_tax", "sum"),
            net_change_usd=(f"{key}_chg", "sum"),
            pct_pay_more=(f"{key}_chg", lambda s: 100 * (s > TOL).mean()))
        g["net_pct_of_cohort_tax"] = 100 * g.net_change_usd / g.current_tax_usd
        rows[ALTS[key]] = g
    return pd.concat(rows, names=["alternative"])


def main() -> None:
    df = load()
    allb = billed(df)
    c = abatement_cohort(df)
    print(f"millage {MILLAGE:.4f}; closed form reproduces the repo re-split on {len(c):,} parcels\n")

    outputs = {
        "who_can_move_by_exemption_kind": who_can_move(df),
        "land_share_by_surface": land_shares(df),
        "tract_agreement_with_fhfa": tract_agreement(df),
        "abatement_cohort_totals": cohort_totals(c),
    }
    for by in ("median_income", "minority_pct"):
        outputs[f"full_abatement_by_{by}"] = cohort_by_stratum(c, allb, by)

    for name, tbl in outputs.items():
        tbl.to_csv(OUT / f"{name}.csv")
        print(f"== {name} ==\n{tbl.round(2).to_string()}\n")


if __name__ == "__main__":
    main()
