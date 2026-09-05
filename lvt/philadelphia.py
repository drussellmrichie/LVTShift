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

__all__ = ["TaxYear", "tax_year_params", "parcel_cache_path", "SUPPORTED_TAX_YEARS",
           "ZeroBuildingSplit", "split_zero_building_parcels"]


@dataclass(frozen=True)
class TaxYear:
    year: int
    city_rate_pct: float
    school_rate_pct: float
    city_revenue_target: int | None
    target_kind: str      # 'actual' | 'projection' | 'none'
    source: str
    homestead_exemption: int   # statutory Homestead Exemption for this tax year

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
                f"= {self.combined_rate_pct}% ({self.combined_mills} mills) | city target {tgt} "
                f"| homestead ${self.homestead_exemption:,}")


_PARAMS: dict[int, TaxYear] = {
    2024: TaxYear(
        year=2024,
        city_rate_pct=0.6317,
        school_rate_pct=0.7681,
        city_revenue_target=795_796_126,
        target_kind="actual",
        homestead_exemption=80_000,
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
        homestead_exemption=100_000,
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
        homestead_exemption=100_000,
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


@dataclass(frozen=True)
class ZeroBuildingSplit:
    """How the zeroed-building-line cohort divides. See `split_zero_building_parcels`."""
    category: "pd.Series"
    abated: "pd.Series"
    homestead_zeroed: "pd.Series"
    no_exemption: "pd.Series"
    homestead_claim_rate: float

    def describe(self) -> str:
        return (f"zero-building line: {int(self.abated.sum()):,} abated | "
                f"{int(self.homestead_zeroed.sum()):,} homestead-zeroed "
                f"({self.homestead_claim_rate:.1%} confirmed by OPA's homestead flag) | "
                f"{int(self.no_exemption.sum()):,} genuinely $0 improvement")


def split_zero_building_parcels(
    gdf,
    category,
    homestead_exemption: float,
    category_map: dict,
    *,
    genuine_vacant_codes=("6", "12", "13"),
    homestead_claim_floor: float = 0.85,
) -> ZeroBuildingSplit:
    """Split parcels whose taxable building line is $0 into their three real populations.

    `taxable_building <= 0` on a non-vacant parcel does not mean "abated". It means the
    building line nets to zero, which happens three different ways, and treating all of
    them as abated construction put ~13k modest homesteaded rowhomes in the abated bucket
    and then revoked their Homestead Exemption under the reform while every other
    homesteader in the city kept theirs.

    The discriminator is the exempt total. The Homestead Exemption is a flat statutory
    amount, so it can never explain more than `homestead_exemption` of exempted value:

    - `exempt_total >  homestead_exemption` -> an abatement is present.
    - `0 < exempt_total <= homestead_exemption` -> ordinary homesteaded property whose
      building assessment is smaller than the exemption. Restored to its OPA category;
      it keeps its exemption under the reform, so its $0 building line is correct as-is.
    - `exempt_total == 0` -> nothing is exempted and the improvement really is worth $0.
      Left as Override 1 classified it.

    Pass `homestead_exemption` from `tax_year_params(year)`, not a literal: the amount has
    moved four times ($30K -> $40K -> $45K -> $80K -> $100K) and using the wrong year's cap
    silently moves parcels across the abated/homestead boundary.

    Parameters
    ----------
    gdf : GeoDataFrame or DataFrame
        Needs `taxable_land`, `taxable_building`, `exempt_land`, `exempt_building` and
        `category_code`. `homestead_exemption` (per-parcel, from OPA) is optional but
        enables the guard.
    category : pd.Series
        The PROPERTY_CATEGORY series as of Override 1.
    homestead_exemption : float
        The tax year's statutory Homestead Exemption.
    category_map : dict
        OPA `category_code` -> category name, used to restore homestead-zeroed parcels.
    homestead_claim_floor : float
        Minimum share of homestead-zeroed parcels that must actually carry a homestead on
        OPA's own flag. Below this the split is not describing what it claims to.

    Returns
    -------
    ZeroBuildingSplit
    """
    import pandas as pd

    def _num(col):
        return pd.to_numeric(gdf[col], errors="coerce").fillna(0.0)

    codes = gdf["category_code"].astype(str)
    exempt_total = _num("exempt_land") + _num("exempt_building")
    zero_building = (
        (_num("taxable_building") <= 0)
        & (_num("taxable_land") > 0)
        & (~codes.isin(set(genuine_vacant_codes)))
    )

    abated = zero_building & (exempt_total > homestead_exemption)
    homestead_zeroed = zero_building & (exempt_total > 0) & (exempt_total <= homestead_exemption)
    no_exemption = zero_building & (exempt_total <= 0)

    out = category.copy()
    out[abated] = "Abated / Construction Exemption"
    out[homestead_zeroed] = codes[homestead_zeroed].map(category_map).fillna("Other")

    # The split is exemption arithmetic, so check it against OPA's own homestead flag --
    # the column that would move if the split were separating the wrong two populations.
    claim_rate = float("nan")
    if "homestead_exemption" in gdf.columns and homestead_zeroed.any():
        hs = pd.to_numeric(gdf["homestead_exemption"], errors="coerce").fillna(0.0)
        claim_rate = float((hs[homestead_zeroed] > 0).mean())
        if claim_rate < homestead_claim_floor:
            raise ValueError(
                f"Only {claim_rate:.1%} of parcels classified as homestead-zeroed actually "
                f"carry a Homestead Exemption on OPA's flag (floor {homestead_claim_floor:.0%}). "
                f"The ${homestead_exemption:,.0f} cap is probably wrong for this tax year -- "
                "check tax_year_params(year).homestead_exemption against the assessment vintage."
            )

    return ZeroBuildingSplit(out, abated, homestead_zeroed, no_exemption, claim_rate)


def parcel_cache_path(year: int, data_dir: str | Path = "data") -> Path:
    """Path to the year-specific shared parcel cache.

    The cache is keyed by tax year on purpose: `opa_properties_public` always carries the
    latest assessment year, so an unsuffixed cache makes it easy to model one year's
    taxable values against another year's expectations without any visible symptom.
    """
    return Path(data_dir) / f"parcels_ty{year}.gpq"
