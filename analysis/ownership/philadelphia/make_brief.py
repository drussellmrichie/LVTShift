"""Render OWNERSHIP_BRIEF.md from the generated result tables.

Every number in the brief comes from `results/` — the template holds only `{{placeholder}}`
tokens and prose. This is the repo convention: a hand-typed figure in a document goes stale
the moment the pipeline is re-run, silently, and nobody notices until someone quotes it.

`--check` re-renders into memory and fails if the committed brief is out of date, so a stale
brief can be caught before it is published rather than after.

Usage:
    python analysis/ownership/philadelphia/make_brief.py
    python analysis/ownership/philadelphia/make_brief.py --check
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent
RESULTS = HERE / "results"
TMPL = HERE / "OWNERSHIP_BRIEF.md.tmpl"
OUT = HERE / "OWNERSHIP_BRIEF.md"

VACANT = "Vacant Land"
PARKING_PREFIX = "Surface Parking"


def pct(x: float, dp: int = 1) -> str:
    return "n/a" if pd.isna(x) else f"{x * 100:.{dp}f}%"


def money(x: float) -> str:
    if pd.isna(x):
        return "n/a"
    if abs(x) >= 1e9:
        return f"${x / 1e9:,.2f} billion"
    if abs(x) >= 1e6:
        return f"${x / 1e6:,.1f} million"
    return f"${x:,.0f}"


def num(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x:,.0f}"


def build_context() -> dict[str, str]:
    stats = json.loads((RESULTS / "headline_stats.json").read_text(encoding="utf-8"))
    sectors = pd.read_csv(RESULTS / "ownership_by_category.csv")
    recon = pd.read_csv(RESULTS / "universe_reconciliation.csv")
    robust = pd.read_csv(RESULTS / "robustness_opa_vs_lycd.csv")
    prec = pd.read_csv(RESULTS / "classifier_precision.csv")
    valid = pd.read_csv(RESULTS / "classifier_validation.csv")

    vac = sectors[sectors["analysis_category"] == VACANT].set_index("owner_sector")["parcels"]

    def recon_j(universe: str, source_frag: str) -> float:
        m = recon[(recon["universe"] == universe) &
                  recon["source_b"].str.contains(source_frag, regex=False)]
        return float(m["jaccard"].iat[0]) if len(m) else float("nan")

    def recon_count(universe: str, source_frag: str, col: str) -> float:
        m = recon[(recon["universe"] == universe) &
                  recon["source_b"].str.contains(source_frag, regex=False)]
        return float(m[col].iat[0]) if len(m) else float("nan")

    vac_rob = robust[robust["analysis_category"] == VACANT]
    named = robust[robust["private_parcels"] >= 100]
    llc_prec = prec.loc[prec["predicted_form"] == "LLC", "precision"]
    obscured = (valid["actual_form"].astype(str)
                .str.startswith("Business — form obscured")).sum()
    other_biz = (valid["predicted_form"] == "Other business").sum()

    ctx = {
        "tax_year": str(stats["tax_year"]),
        "model_label": "revenue-neutral 4:1 split-rate, OPA land values",
        "total_parcels": num(stats["total_parcels"]),
        "vacant_llc_land_share": pct(stats["vacant_llc_land_share"]),
        "vacant_llc_land_share_upper": pct(stats["vacant_llc_land_share_upper"]),
        "vacant_llc_parcel_share": pct(stats["vacant_llc_parcel_share"]),
        "sfr_llc_land_share": pct(stats["sfr_llc_land_share"]),
        "vacant_vs_sfr_ratio": f"{stats['vacant_vs_sfr_ratio']:.1f}",
        "parking_comm_llc_land_share": pct(stats["parking_comm_llc_land_share"]),
        "parking_noncomm_llc_land_share": pct(stats["parking_noncomm_llc_land_share"]),
        "garage_llc_land_share": pct(stats["garage_llc_land_share"]),
        "industrial_llc_land_share": pct(stats["industrial_llc_land_share"]),
        "large_mf_llc_land_share": pct(stats["large_mf_llc_land_share"]),
        "incity_land_share_of_llc": pct(stats["incity_land_share_of_llc"]),
        "oos_land_share_of_llc": pct(stats["oos_land_share_of_llc"]),
        "llc_vp_entities": num(stats["llc_vp_entities"]),
        "incity_entities": num(stats["incity_entities"]),
        "oos_entities": num(stats["oos_entities"]),
        "llc_vp_parcels": num(stats["llc_vp_parcels"]),
        "llc_vp_tax_change": money(stats["llc_vp_tax_change"]),
        "vacant_parking_parcels": num(stats["vacant_parking_parcels"]),
        "vacant_parking_public_parcels": num(stats["vacant_parking_public_parcels"]),
        "vacant_parking_public_parcel_share": pct(stats["vacant_parking_public_parcel_share"]),
        "delaware_parcels": num(stats["delaware_parcels"]),
        "oos_distinct_addresses": num(stats["oos_distinct_addresses"]),
        "oos_max_names_at_one_address": num(stats["oos_max_names_at_one_address"]),
        "oos_top10_address_land_share": pct(stats["oos_top10_address_land_share"]),
        "oos_top_n": num(stats["oos_top_n"]),
        "city_llc_oos_land_share": pct(stats["city_llc_oos_land_share"]),
        "city_llc_incity_land_share": pct(stats["city_llc_incity_land_share"]),
        "city_all_oos_land_share": pct(stats["city_all_oos_land_share"]),
        "city_all_incity_land_share": pct(stats["city_all_incity_land_share"]),
        "sfr_llc_oos_land_share": pct(stats["sfr_llc_oos_land_share"]),
        "vacant_llc_oos_land_share": pct(stats["vacant_llc_oos_land_share"]),
        "commercial_llc_oos_land_share": pct(stats["commercial_llc_oos_land_share"]),
        "geography_categories_covered": num(stats["geography_categories_covered"]),
        "city_oos_distinct_addresses": num(stats["city_oos_distinct_addresses"]),
        "city_oos_max_names_at_one_address": num(stats["city_oos_max_names_at_one_address"]),
        "truncation_widths": " and ".join(str(w) for w in stats["truncation_widths"]),
        "vacant_individual_parcels": num(vac.get("Individual", float("nan"))),
        "vacant_business_parcels": num(vac.get("Business / investor entity", float("nan"))),
        "validation_n": num(len(valid)),
        "llc_precision": pct(llc_prec.iat[0]) if len(llc_prec) else "n/a",
        "obscured_share": pct(obscured / other_biz) if other_biz else "n/a",
        "vacant_jaccard_landuse": f"{recon_j('Vacant land', 'Land Use'):.2f}",
        "vacant_jaccard_lni": f"{recon_j('Vacant land', 'L&I'):.2f}",
        "parking_jaccard_landuse": f"{recon_j('Surface parking', 'Land Use'):.2f}",
        "parking_jaccard_orphan": f"{recon_j('Surface parking', 'orphan'):.3f}",
        "landuse_parking_count": num(recon_count("Surface parking", "Land Use", "count_b")),
        "opa_parking_count": num(recon_count("Surface parking", "Land Use", "count_a")),
        "vacant_lycd_diff_pp": f"{vac_rob['abs_diff_pp'].iat[0]:.1f}" if len(vac_rob) else "n/a",
        "max_lycd_diff_pp": f"{named['abs_diff_pp'].max():.1f}" if len(named) else "n/a",
    }
    return ctx


def render() -> str:
    ctx = build_context()
    text = TMPL.read_text(encoding="utf-8")
    missing = [k for k in re.findall(r"\{\{(\w+)\}\}", text) if k not in ctx]
    if missing:
        raise SystemExit(f"template references unknown placeholders: {sorted(set(missing))}")
    for k, v in ctx.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed brief differs from a fresh render")
    args = ap.parse_args()

    text = render()
    if args.check:
        if not OUT.exists():
            raise SystemExit(f"{OUT.name} has not been generated yet")
        if OUT.read_text(encoding="utf-8") != text:
            raise SystemExit(f"{OUT.name} is STALE — re-run make_brief.py")
        print(f"{OUT.name} is up to date")
        return

    OUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
