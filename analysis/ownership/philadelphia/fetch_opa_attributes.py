"""Fetch the OPA attribute columns the shared parcel cache does not carry.

The ownership-by-property-type analysis needs three things that are not in
`cities/philadelphia/data/parcels_ty<YEAR>.gpq`:

  - `building_code` / `building_code_description` — the only field that identifies surface
    parking. OPA's `category_code` puts most parking lots in code 6 ("VACANT LAND"), so the
    LVT model's "Vacant Land" category silently contains them. The `R*` building-code family
    (RA/RB/RC/RD/RE/RF) is what separates them.
  - `homestead_exemption` — the owner-occupancy signal, fetched citywide for the first time.
  - `zoning` — context for what a vacant parcel is permitted to become.

This is a sidecar rather than an addition to `scripts/build_philadelphia_parcel_cache.py` on
purpose. `building_code` belongs in the cache builder long-term, but adding it there forces a
`--force` rebuild, which would re-pull current owner names underneath already-published
TY2026 results. Fold it into the builder at the next natural cache rebuild instead.

These columns come from `opa_properties_public`, which always reflects the *latest*
assessment year — unlike the taxable values, which the cache pulls from the year-keyed
`assessments` table. Building codes and zoning are structural and drift slowly, so the
vintage mismatch is acceptable here; taxable values would not be.

Usage:
    python analysis/ownership/philadelphia/fetch_opa_attributes.py
    python analysis/ownership/philadelphia/fetch_opa_attributes.py --force
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.parse
from pathlib import Path

import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")

CARTO = "https://phl.carto.com/api/v2/sql"
HERE = Path(__file__).parent
ATTRS_OUT = HERE / "opa_attributes.parquet"
MAILING_OUT = HERE / "opa_mailing.parquet"

ATTR_QUERY = (
    "SELECT parcel_number, building_code, building_code_description, "
    "category_code_description, homestead_exemption, zoning "
    "FROM opa_properties_public"
)
MAILING_QUERY = (
    "SELECT parcel_number, mailing_street, mailing_address_1, mailing_address_2, "
    "mailing_care_of, mailing_city_state, mailing_zip, location "
    "FROM opa_properties_public"
)


def carto_csv(query: str, timeout: int = 600) -> pd.DataFrame:
    url = f"{CARTO}?q={urllib.parse.quote(query)}&format=csv"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), low_memory=False, dtype=str)


def fetch(query: str, out: Path, label: str, force: bool) -> None:
    if out.exists() and not force:
        print(f"{out.name} already exists — pass --force to refresh")
        return
    print(f"Downloading {label} from Carto...")
    df = carto_csv(query)
    print(f"  {len(df):,} rows")
    for c in df.columns:
        print(f"    {c}: {df[c].notna().mean():.1%} non-null")
    df.to_parquet(out)
    print(f"  saved to {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="refetch even if the cache exists")
    ap.add_argument("--skip-mailing", action="store_true",
                    help="leave the existing opa_mailing.parquet alone")
    args = ap.parse_args()

    fetch(ATTR_QUERY, ATTRS_OUT, "building codes / homestead / zoning", args.force)
    if not args.skip_mailing:
        # Refreshed alongside the attributes so both share one OPA vintage.
        fetch(MAILING_QUERY, MAILING_OUT, "mailing address fields", args.force)


if __name__ == "__main__":
    main()
