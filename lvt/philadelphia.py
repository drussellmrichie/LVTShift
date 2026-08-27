"""Philadelphia tax-year constants, in one place.

Every Philadelphia notebook needs the same three things for a given tax year: the millage,
the city-only rate for the revenue cross-check, and the collections figure to check against.
Copying those into six notebooks is how the stale `city_only_rate = 6.317` survived past the
TY2025 rate reallocation — the combined rate stayed 1.3998% so nothing looked wrong, but the
City/School split had moved and the cross-check was quietly validating against the wrong
denominator. Keep them here and import.

Rate and revenue sources are cited per year. The combined rate has been 1.3998% throughout;
what changes is how it splits, which only affects the cross-check, not the revenue-neutral
model itself (that runs on the combined levy).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ["TaxYear", "tax_year_params", "parcel_cache_path", "SUPPORTED_TAX_YEARS"]


@dataclass(frozen=True)
class TaxYear:
    year: int
    city_rate_pct: float
    school_rate_pct: float
    city_revenue_target: int | None
    target_kind: str      # 'actual' | 'projection' | 'none'
    source: str

    @property
    def combined_rate_pct(self) -> float:
        return round(self.city_rate_pct + self.school_rate_pct, 6)

    @property
    def combined_mills(self) -> float:
        """Millage per $1,000 of assessed value (rate% x 10)."""
        return round(self.combined_rate_pct * 10, 6)

    @property
    def city_mills(self) -> float:
        return round(self.city_rate_pct * 10, 6)

    def describe(self) -> str:
        tgt = (f"${self.city_revenue_target:,} ({self.target_kind})"
               if self.city_revenue_target else "no target (forward-looking year)")
        return (f"TY{self.year}: {self.city_rate_pct}% city + {self.school_rate_pct}% school "
                f"= {self.combined_rate_pct}% ({self.combined_mills} mills) | city target {tgt}")


_PARAMS: dict[int, TaxYear] = {
    2024: TaxYear(
        year=2024,
        city_rate_pct=0.6317,
        school_rate_pct=0.7681,
        city_revenue_target=795_796_126,
        target_kind="actual",
        source="FY2024 city-only current-year Real Estate Tax collections.",
    ),
    2026: TaxYear(
        year=2026,
        city_rate_pct=0.6159,
        school_rate_pct=0.7839,
        city_revenue_target=891_102_000,
        target_kind="projection",
        source=(
            "Rate: City of Philadelphia Quarterly City Managers Report, period ending "
            "2026-03-31, Summary Table R-1 ('FY 2026 Tax Rate: .6159% City plus .7839% "
            "School District Total 1.3998%'). Target: same report, Table R-2, Real Property "
            "'Current' full-year Current Projection ($891,102k). This is a Q3 projection, "
            "not a closed-out actual."
        ),
    ),
    2027: TaxYear(
        year=2027,
        city_rate_pct=0.6159,
        school_rate_pct=0.7839,
        city_revenue_target=None,
        target_kind="none",
        source=(
            "The adopted FY2027 budget holds the combined rate at 1.3998% with no property "
            "tax increase. The City/School split is CARRIED FORWARD from FY2026 and is NOT "
            "independently confirmed — the FY2027-2031 Five-Year Plan shifts more Real Estate "
            "Tax revenue to the School District, so the split may move again. No revenue "
            "target: TY2027 bills are not due until March 2027, so there are no collections "
            "to validate against. Treat TY2027 output as a forward-looking scenario."
        ),
    ),
}

SUPPORTED_TAX_YEARS = tuple(sorted(_PARAMS))


def tax_year_params(year: int) -> TaxYear:
    """Return the rate/target constants for a Philadelphia tax year."""
    try:
        return _PARAMS[year]
    except KeyError:
        raise KeyError(
            f"No Philadelphia tax-year parameters for {year}. "
            f"Known years: {list(SUPPORTED_TAX_YEARS)}. Add an entry to lvt/philadelphia.py "
            "with a cited rate and revenue source rather than assuming the previous year's."
        ) from None


def parcel_cache_path(year: int, data_dir: str | Path = "data") -> Path:
    """Path to the year-specific shared parcel cache.

    The cache is keyed by tax year on purpose: `opa_properties_public` always carries the
    latest assessment year, so an unsuffixed cache makes it easy to model one year's
    taxable values against another year's expectations without any visible symptom.
    """
    return Path(data_dir) / f"parcels_ty{year}.gpq"
