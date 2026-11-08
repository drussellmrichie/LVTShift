"""The Philadelphia tax-year table: every year since TY2016 bills at a combined 1.3998%, and the
Homestead Exemption steps $45,000 -> $80,000 -> $100,000 at TY2023 and TY2025 (Phila. Code
§§ 19-1301, 19-1801, 19-1301.2 and the bills cited beside `_PARAMS`)."""
import pytest

from lvt.philadelphia import SUPPORTED_TAX_YEARS, tax_year_params

HOMESTEAD = {2022: 45_000, 2023: 80_000, 2024: 80_000, 2025: 100_000, 2026: 100_000, 2027: 100_000}


def test_years_are_contiguous_from_2022():
    assert SUPPORTED_TAX_YEARS == tuple(range(2022, 2028))


@pytest.mark.parametrize("year", SUPPORTED_TAX_YEARS)
def test_combined_rate_is_unchanged_since_2016(year):
    assert tax_year_params(year).combined_rate_pct == pytest.approx(1.3998)


@pytest.mark.parametrize("year,amount", HOMESTEAD.items())
def test_homestead_steps(year, amount):
    assert tax_year_params(year).homestead_exemption == amount


def test_split_moved_in_2025():
    assert tax_year_params(2024).city_rate_pct == 0.6317
    assert tax_year_params(2025).city_rate_pct == 0.6159
    assert tax_year_params(2025).school_rate_pct == 0.7839


def test_unknown_year_names_the_fix():
    with pytest.raises(KeyError, match="cited rate"):
        tax_year_params(2019)
