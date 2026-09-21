"""Building-type and zoning-family groupings for Philadelphia's commercial parcels."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lvt.philadelphia import COMMERCIAL_BUILDING_TYPES, commercial_building_type, zoning_family  # noqa: E402


def _types(rows):
    desc, code = zip(*rows)
    return list(commercial_building_type(pd.Series(desc), pd.Series(code)))


def test_parking_comes_from_the_code_and_skips_its_two_traps():
    """A deeded condo space (5R) and a rowhouse with a garage (R30) are not parking lots, however
    their descriptions read; lots and garages are identified by code alone."""
    assert _types([
        ("PKG LOT NON COMMERCIAL", "RA"), ("PD PKG LOT COMMERCIAL", "RE"), ("NON PD PKG LOT COMMERCIAL", "RB"),
        ("PKG LOT COM W/BLDG MASON", "RF0"), ("GAR W/COMM AREA MASONRY", "OA0"), ("GAR NO COMM AREA MASONRY", "OB0"),
        ("CONDO PARKING SPACE", "5R"), ("ROW B/GAR 2 STY MASONRY", "R30"),
    ]) == ["Parking lots"] * 4 + ["Parking garages"] * 2 + [
        "Condominium units", "Houses and apartments in commercial categories"]


@pytest.mark.parametrize("description, expected", [
    ("OFF BLD COM NO GAR MASON", "Offices and banks"),
    ("BANK/OFF 1 STY MASONRY", "Offices and banks"),
    ("HOTEL 20+ STY MASONRY", "Hotels"),
    ("SHOP CENT STRIP MASONRY", "Shopping centres and supermarkets"),
    ("SUPERMKT 1 STY MASONRY", "Shopping centres and supermarkets"),
    ("GAS STAT PUMP+MART MAS", "Gas stations and auto businesses"),
    ("AUTO REPAIR SHOP MASONRY", "Gas stations and auto businesses"),
    ("REST'RNT FASTFOOD MASONRY", "Restaurants and bars"),
    ("TAVERN OR BAR MASONRY", "Restaurants and bars"),
    ("IND WAREHOUSE MASONRY", "Warehouses, factories, other industrial"),
    ("IND. LGHT MFG MASONRY", "Warehouses, factories, other industrial"),
    ("COLD STORAGE WHSE MASONRY", "Warehouses, factories, other industrial"),
    ("INDUS CONDO", "Condominium units"),                  # condos win over industrial
    ("COM CONDO 1 STY MASONRY", "Condominium units"),
    ("STR/OFF+APT 3 STY MASONRY", "Storefronts with offices or apartments"),
    ("ROW W/OFF STR 2 STY MASON", "Storefronts with offices or apartments"),   # before plain rowhouses
    ("STORE 1 STY MASONRY", "Stores and services"),
    ("AMUSE HALL MASONRY", "Health, schools, worship, entertainment"),
    ("AMUS REC COMPLEX MASONRY", "Health, schools, worship, entertainment"),
    ("HEALTH FAC NURSE HOME MAS", "Health, schools, worship, entertainment"),
    ("ROW 2 STY MASONRY", "Houses and apartments in commercial categories"),
    ("VACANT LAND COMMER < ACRE", "Land coded vacant, air rights"),
    ("MISC FILT/COMPLEX MASONRY", "Other"),
    ("", "Other"),
])
def test_building_type_from_description(description, expected):
    assert _types([(description, "XX0")]) == [expected]


def test_building_type_rules_have_no_capture_groups():
    """pandas warns on capture groups in str.contains, and the warning hides real ones."""
    assert all("(?:" in pattern and "(" not in pattern.replace("(?:", "") for _, pattern in COMMERCIAL_BUILDING_TYPES)


def test_zoning_family_normalises_opa_codes():
    z = pd.Series(["CMX5", "CMX-5", "CMX4", "CMX3", "CMX2.5", "CMX1", "CA1", "CA-2", "I2", "ICMX", "IRMX",
                   "SPPOA", "RSA5", "RM1", "", None])
    assert list(zoning_family(z)) == [
        "CMX-5 Center City core", "CMX-5 Center City core", "CMX-4 Center City commercial",
        "CMX-3 community commercial", "CMX-1/2/2.5 neighborhood commercial", "CMX-1/2/2.5 neighborhood commercial",
        "CA-1/2 auto-oriented commercial", "CA-1/2 auto-oriented commercial",
        "Industrial (I-1/2/3, I-P, ICMX, IRMX)", "Industrial (I-1/2/3, I-P, ICMX, IRMX)",
        "Industrial (I-1/2/3, I-P, ICMX, IRMX)", "Special purpose (SP)", "Residential zoning", "Residential zoning",
        "Unmatched", "Unmatched",
    ]
