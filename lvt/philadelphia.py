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
           "ZeroBuildingSplit", "split_zero_building_parcels",
           "LycdResult", "compute_lycd_land_values",
           "ExemptionCarryForward", "carry_forward_exemptions",
           "PHILADELPHIA_LAND_SQFT", "VACANT_CATEGORY_CODES"]


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


# Philadelphia land area, 134.2 sq mi in sqft. Parcels exclude streets, rights-of-way and
# water, so a correct lot-area layer sums to *less* than this.
PHILADELPHIA_LAND_SQFT = 134.2 * 27_878_400

VACANT_CATEGORY_CODES = ("6", "12", "13")


@dataclass(frozen=True)
class LycdResult:
    """Output of `compute_lycd_land_values`: the frame with LYCD columns, plus diagnostics."""
    gdf: "pd.DataFrame"
    diagnostics: dict

    def describe(self) -> str:
        d = self.diagnostics
        lines = [
            "Lot area source: " + ", ".join(f"{k}={v:,}" for k, v in d["area_source_counts"].items()),
            f"  OPA records overridden by surveyed polygon: {d['n_pin_override']:,}",
            f"  total lot area = {d['city_area_ratio']:.2f}x the city (expect <1.0)",
            f"GMA assignment: {d['n_gma_matched']:,} matched ({d['gma_match_rate']:.1%}); "
            + ", ".join(f"{k}={v:,}" for k, v in d["gma_level_counts"].items()),
            f"Market-value cap (improved only): {d['n_capped']:,} parcels, "
            f"${d['land_base_pre_cap']/1e9:.2f}B -> ${d['land_base_post_cap']/1e9:.2f}B "
            f"({d['cap_removed_share']:.1%} removed)",
        ]
        return "\n".join(lines)


def compute_lycd_land_values(
    gdf,
    gma,
    pin_areas,
    *,
    land_pct_improved=0.20,
    land_pct_vacant: float = 1.00,
    min_improved: int = 50,
    opa_pin_disagree_factor: float = 3.0,
    vacant_codes=VACANT_CATEGORY_CODES,
    cap_improved_at_market: bool = True,
    knn_k: int = 5,
    city_area_sqft: float = PHILADELPHIA_LAND_SQFT,
    max_city_area_ratio: float = 1.5,
    zone_group_col: "str | None" = None,
) -> LycdResult:
    """GMA-hierarchical LYCD land values, the construction shared by every Philadelphia notebook.

    "Least You Can Do": a parcel's land value is a uniform local land rate times its lot area,
    where the rate is the median total value per square foot of *improved* parcels in the
    parcel's OPA Geographic Market Area, times an allocation share::

        zone_psf        = median(market_value / lot_area) over improved parcels in the zone
        lycd_land_value = zone_psf x share x lot_area
        share           = land_pct_improved for improved parcels, land_pct_vacant for vacant ones

    The zone is the finest GMA level with at least `min_improved` improved parcels (L3, else
    L2, else L1). Parcels outside GMA coverage take the median *dollar* land value of their
    `knn_k` nearest GMA-assigned neighbours (note: not zone $/sqft times their own area -- a
    known limitation, audit 2026-08-08 finding 5). Improved parcels are then clipped at their
    own `market_value`; vacant parcels are not, because OPA under-assesses bare land and the
    clip would erase the development-potential signal.

    Two refinements, off by default, layer on the base construction without changing it for
    callers that do not use them (`model_lycd_refined_prototype.ipynb` uses both):

    - `zone_group_col`: a column on `gdf` with a per-parcel group label (e.g. "Residential"
      vs "NonResidential"). When given, zone medians are computed per (group, GMA level) cell
      instead of pooling every improved parcel type together, so a rowhouse is priced against
      other residential comps, not whatever commercial parcel happens to share its zone. When
      `None` (the default), every row shares one implicit group and results are identical to
      the ungrouped construction -- verified bit-for-bit against `model_lycd.ipynb`'s prior
      inline version.
    - `land_pct_improved` as a `pandas.Series` (aligned to `gdf.index`) instead of a scalar:
      a per-parcel allocation share, e.g. an external land-share estimate for some categories
      and the flat default for others. The value at vacant rows is ignored -- `land_pct_vacant`
      always wins there, so callers need not special-case vacant parcels when building the
      Series.

    Lot area uses ONE convention, true ground square feet, with no spatial join: OPA
    `total_area` first, then the Mercator-corrected PIN-keyed DOR polygon area, then KNN from
    parcels already on that convention. A surveyed polygon overrides OPA's record when OPA is
    more than `opa_pin_disagree_factor` times larger (a handful of impossible OPA records). The
    method is exactly scale-invariant in lot area, so only *mixed* conventions and *relative*
    errors move results; the total-area guard catches the mixed-convention failure that once
    tripled the city's land area.

    Parameters
    ----------
    gdf : GeoDataFrame
        The year-keyed parcel cache. Needs `parcel_number` (zero-padded string), `pin`,
        `category_code`, `total_area`, `market_value` and point geometry.
    gma : DataFrame
        `parcel_gma_assignment.parquet`: `key` (parcel_number) + `gma1`, `gma2`, `gma3`.
    pin_areas : DataFrame
        `parcel_areas_by_pin_current.parquet`: `pin` + `pin_area_sqft`, Mercator-corrected.
        Do NOT pass the older `parcel_areas_by_pin.parquet` -- those areas are Web Mercator.
    cap_improved_at_market : bool
        Apply the improved-parcel market-value clip. Off only for diagnostics.
    land_pct_improved : float or pandas.Series
        See "Two refinements" above.
    zone_group_col : str, optional
        See "Two refinements" above.

    Returns
    -------
    LycdResult
        `.gdf` is a copy of `gdf` with `dor_area_sqft`, `area_source`, `gma1/2/3`,
        `gma_level`, `lycd_zone_psf`, `lycd_land_pct` and `lycd_land_value` added;
        `.diagnostics` holds the counts the notebooks print and assert on.
    """
    import numpy as np
    import pandas as pd
    from scipy.spatial import cKDTree

    out = gdf.copy()
    vacant = set(str(c) for c in vacant_codes)

    # --- Lot area: single convention, no spatial join ---
    out["pin"] = out["pin"].astype(str).str.strip()
    pin_lookup = pin_areas.copy()
    pin_lookup["pin"] = pin_lookup["pin"].astype(str).str.strip()
    pin_lookup = pin_lookup.drop_duplicates("pin").set_index("pin")["pin_area_sqft"]

    opa_area = pd.to_numeric(out["total_area"], errors="coerce").fillna(0.0)
    pin_area = out["pin"].map(pin_lookup)
    has_opa = opa_area > 0
    has_pin = pin_area.notna() & (pin_area > 0)
    override = has_opa & has_pin & ((opa_area / pin_area) > opa_pin_disagree_factor)

    area = pd.Series(
        np.where(override, pin_area, np.where(has_opa, opa_area, np.where(has_pin, pin_area, np.nan))),
        index=out.index, dtype=float,
    )
    area_src = pd.Series(
        np.where(override, "pin_override",
                 np.where(has_opa, "opa_total_area", np.where(has_pin, "pin_dor", "knn"))),
        index=out.index,
    )

    geom = out.geometry.to_crs("EPSG:3857")
    if (geom.geom_type != "Point").any():
        geom = geom.centroid
    coords = np.column_stack([geom.x.values, geom.y.values])

    def _knn_median(values: np.ndarray) -> np.ndarray:
        values = np.asarray(values, dtype=float)
        have = ~np.isnan(values)
        need = np.isnan(values)
        if need.sum() == 0:
            return values
        tree = cKDTree(coords[have])
        _, ix = tree.query(coords[need], k=min(knn_k, int(have.sum())), workers=-1)
        filled = values.copy()
        filled[need] = np.median(values[have][ix], axis=1)
        return filled

    n_area_knn = int(area.isna().sum())
    area = pd.Series(_knn_median(area.values), index=out.index)
    out["dor_area_sqft"] = area
    out["area_source"] = area_src

    city_area_ratio = float(area.sum() / city_area_sqft)
    if city_area_ratio >= max_city_area_ratio:
        raise ValueError(
            f"Total lot area is {city_area_ratio:.2f}x the city -- the area layer is inflated. "
            "Check that PIN areas are Mercator-corrected and that no spatial join has been "
            "reintroduced."
        )

    # --- GMA zone labels ---
    g = gma.copy()
    g["key"] = g["key"].astype(str).str.zfill(9)
    g = g.drop_duplicates("key").set_index("key")
    for lvl in ("gma1", "gma2", "gma3"):
        out[lvl] = out["parcel_number"].astype(str).str.zfill(9).map(g[lvl])
    gma_matched = out["gma3"].notna()

    # --- Zone medians of total $/sqft over improved parcels, hierarchical ---
    cat = out["category_code"].astype(str).str.strip()
    # category_code may arrive as '1.0' from a float column; normalise like the notebooks do
    cat = pd.to_numeric(cat, errors="coerce").astype("Int64").astype(str)
    market = pd.to_numeric(out["market_value"], errors="coerce")
    has_market = market.notna() & (market > 0)
    has_area = area.notna() & (area > 0)
    is_improved = ~cat.isin(vacant) & has_market & has_area
    is_vacant = cat.isin(vacant) & has_market & has_area

    # Zone-median cell key: (zone_group, gma level) when zone_group_col is given, else just
    # the gma level -- a constant group prefix on every row partitions identically to no
    # grouping at all, so this one code path serves both cases.
    if zone_group_col is not None:
        if zone_group_col not in out.columns:
            raise ValueError(f"zone_group_col {zone_group_col!r} is not a column on gdf")
        group = out[zone_group_col]
    else:
        group = pd.Series("_all", index=out.index)

    def _cell_key(level_col: str) -> pd.Series:
        return pd.Series(list(zip(group, out[level_col])), index=out.index)

    key1, key2, key3 = _cell_key("gma1"), _cell_key("gma2"), _cell_key("gma3")

    total_psf = pd.Series(np.where(is_improved | is_vacant, market / area, np.nan), index=out.index)
    imp = pd.DataFrame({"psf": total_psf[is_improved], "k1": key1[is_improved],
                        "k2": key2[is_improved], "k3": key3[is_improved]})
    l3_n = key3.map(imp.groupby("k3")["psf"].count()).fillna(0)
    l2_n = key2.map(imp.groupby("k2")["psf"].count()).fillna(0)
    l3_med = key3.map(imp.groupby("k3")["psf"].median())
    l2_med = key2.map(imp.groupby("k2")["psf"].median())
    l1_med = key1.map(imp.groupby("k1")["psf"].median())

    zone_psf = pd.Series(
        np.where(l3_n >= min_improved, l3_med, np.where(l2_n >= min_improved, l2_med, l1_med)),
        index=out.index, dtype=float,
    )
    out["gma_level"] = np.where(
        ~gma_matched, "knn",
        np.where(l3_n >= min_improved, "L3", np.where(l2_n >= min_improved, "L2", "L1")),
    )

    if isinstance(land_pct_improved, pd.Series):
        land_pct_improved_arr = land_pct_improved.reindex(out.index).astype(float).to_numpy()
    else:
        land_pct_improved_arr = float(land_pct_improved)
    land_pct = pd.Series(np.where(is_vacant, land_pct_vacant, land_pct_improved_arr), index=out.index)
    out["lycd_zone_psf"] = zone_psf
    out["lycd_land_pct"] = land_pct
    land = pd.Series(
        np.where(gma_matched & has_area, (zone_psf * land_pct * area).clip(lower=0), np.nan),
        index=out.index, dtype=float,
    )

    # --- KNN fallback for parcels outside GMA coverage (dollar values, see docstring) ---
    n_knn = int(land.isna().sum())
    land = pd.Series(_knn_median(land.values), index=out.index)

    # --- Market-value cap, improved parcels only ---
    is_vac_code = cat.isin(vacant)
    pre_cap = float(land.sum())
    n_capped = 0
    if cap_improved_at_market:
        mv_cap = market.fillna(0).clip(lower=0)
        capped = (land > mv_cap) & ~is_vac_code
        n_capped = int(capped.sum())
        land = pd.Series(np.where(~is_vac_code, np.minimum(land, mv_cap), land), index=out.index)
    post_cap = float(land.sum())
    out["lycd_land_value"] = land

    diagnostics = {
        "area_source_counts": area_src.value_counts().to_dict(),
        "n_area_knn": n_area_knn,
        "n_pin_override": int(override.sum()),
        "total_lot_area_sqft": float(area.sum()),
        "city_area_ratio": city_area_ratio,
        "n_gma_matched": int(gma_matched.sum()),
        "gma_match_rate": float(gma_matched.mean()),
        "n_land_knn": n_knn,
        "gma_level_counts": out["gma_level"].value_counts().to_dict(),
        "n_capped": n_capped,
        "land_base_pre_cap": pre_cap,
        "land_base_post_cap": post_cap,
        "cap_removed_share": (pre_cap - post_cap) / pre_cap if pre_cap > 0 else float("nan"),
        "land_pct_improved": (
            f"per-parcel Series (median {float(np.median(land_pct_improved_arr)):.4f})"
            if isinstance(land_pct_improved, pd.Series) else land_pct_improved
        ),
        "land_pct_vacant": land_pct_vacant,
        "min_improved": min_improved,
        "zone_group_col": zone_group_col,
    }
    return LycdResult(out, diagnostics)


@dataclass(frozen=True)
class ExemptionCarryForward:
    """Output of `carry_forward_exemptions`. All Series are aligned to the input index."""
    reform_taxable_land: "pd.Series"
    reform_taxable_building: "pd.Series"
    reform_taxable_total: "pd.Series"
    institutional_exempt: "pd.Series"     # stays fully exempt under the reform
    homestead_active: "pd.Series"         # a Homestead Exemption is re-applied under the reform
    other_exempt_dollars: "pd.Series"     # non-homestead exemption carried forward in dollars
    diagnostics: dict

    def describe(self) -> str:
        d = self.diagnostics
        return (
            f"exemption carry-forward: {d['n_homestead_active']:,} homestead parcels re-exempted "
            f"at min(cap, value) | {d['n_other_exempt']:,} carry non-homestead dollars "
            f"(abatement / partial) | {d['n_institutional_exempt']:,} stay fully exempt | "
            f"{d['n_homestead_wiped_reentering']:,} homestead-wiped parcels re-enter the base "
            f"| flag-without-exemption (vintage mismatch): {d['n_homestead_flag_no_exemption']:,} "
            f"| OPA-base reconstruction match: {d['reconstruction_match_rate']:.2%}"
        )


def carry_forward_exemptions(
    gdf,
    *,
    new_land_col: str,
    homestead_cap: float,
    homestead_col: str = "homestead_exemption",
    match_tolerance: float = 1.0,
    reconstruction_floor: float = 0.95,
) -> ExemptionCarryForward:
    """Re-apply each parcel's existing exemptions to a base whose LAND value has changed.

    "Same assessment methodology, land valued differently" means every relief that exists today
    still exists tomorrow, applied the way OPA applies it. Three kinds of relief show up in the
    OPA columns, and they carry forward three different ways:

    - **Homestead Exemption** -- a flat statutory amount, `homestead_cap`, applied to the
      building line first and the remainder to land (verified against OPA data: essentially
      no homestead parcel has exempt land while taxable building remains). Under the reform
      it is re-applied as `min(cap, new total)`, so a parcel whose value the new land lifts
      above the cap becomes taxable again. Active only where OPA's per-parcel flag is set
      AND an exemption was actually applied this vintage (the flag is current-vintage).
    - **Everything else that is a dollar amount** -- the 10-year construction abatement
      (building only) and partial institutional relief -- carried forward in dollars
      (`exempt_total - homestead`), applied building-first. The building value is unchanged
      by a land reform, so an abatement's dollars are exactly right.
    - **Full institutional exemption** -- a rate, not an amount. A fully exempt parcel whose
      exemption is not explained by the homestead alone stays fully exempt.

    The guard is a reconstruction: feeding OPA's own gross land back through this rule must
    reproduce OPA's taxable total per parcel. The match rate is reported and enforced
    (`reconstruction_floor`); if the rule mis-described the exemptions, this is the number that
    would move.

    Parameters
    ----------
    gdf : DataFrame
        Needs `taxable_land`, `taxable_building`, `exempt_land`, `exempt_building`,
        `market_value`, `homestead_col` and `new_land_col`.
    new_land_col : str
        The reform's gross (pre-exemption) land value, e.g. `lycd_land_value`.
    homestead_cap : float
        The tax year's statutory Homestead Exemption, from `tax_year_params(year)`.

    Returns
    -------
    ExemptionCarryForward
    """
    import numpy as np
    import pandas as pd

    if homestead_col not in gdf.columns:
        raise ValueError(
            f"{homestead_col!r} is not in the frame. Rebuild the parcel cache with "
            "scripts/build_philadelphia_parcel_cache.py --force; the carry-forward keys the "
            "Homestead Exemption off OPA's per-parcel flag."
        )

    def _num(col):
        return pd.to_numeric(gdf[col], errors="coerce").fillna(0.0).astype(float)

    tax_land, tax_bldg = _num("taxable_land"), _num("taxable_building")
    ex_land, ex_bldg = _num("exempt_land"), _num("exempt_building")
    hs_amt = _num(homestead_col).clip(lower=0)
    gross_bldg = (tax_bldg + ex_bldg).clip(lower=0)
    gross_land = (tax_land + ex_land).clip(lower=0)
    ex_total = ex_land + ex_bldg
    old_taxable = (tax_land + tax_bldg).clip(lower=0)
    full_exmp = old_taxable <= 0

    hs_active = (hs_amt > 0) & (ex_total > 0)
    other_exempt = (ex_total - np.where(hs_active, hs_amt, 0.0)).clip(lower=0)
    homestead_wiped = full_exmp & hs_active & (other_exempt <= match_tolerance)
    institutional = full_exmp & ~homestead_wiped

    def _apply(new_land: pd.Series):
        """Building-first application of the dollar exemptions, then the homestead."""
        b1 = (gross_bldg - other_exempt).clip(lower=0)
        spill = (other_exempt - gross_bldg).clip(lower=0)
        l1 = (new_land - spill).clip(lower=0)
        hs_ex = pd.Series(np.where(hs_active, np.minimum(homestead_cap, b1 + l1), 0.0), index=gdf.index)
        b2 = (b1 - hs_ex).clip(lower=0)
        spill2 = (hs_ex - b1).clip(lower=0)
        l2 = (l1 - spill2).clip(lower=0)
        b2 = b2.where(~institutional, 0.0)
        l2 = l2.where(~institutional, 0.0)
        return l2, b2

    # Guard: OPA's own land through the same rule must reproduce OPA's own taxable total.
    rec_land, rec_bldg = _apply(gross_land)
    rec_total = rec_land + rec_bldg
    match = (rec_total - old_taxable).abs() <= match_tolerance
    match_rate = float(match.mean())
    if match_rate < reconstruction_floor:
        raise ValueError(
            f"Exemption carry-forward reproduces OPA's taxable total on only {match_rate:.2%} of "
            f"parcels (floor {reconstruction_floor:.0%}). The rule does not describe how this "
            "vintage's exemptions were applied -- check homestead_cap against the assessment year "
            "and the homestead flag's vintage before trusting any reform base built on it."
        )

    new_land = pd.to_numeric(gdf[new_land_col], errors="coerce").fillna(0.0).clip(lower=0)
    ref_land, ref_bldg = _apply(new_land)

    diagnostics = {
        "n_homestead_active": int(hs_active.sum()),
        "n_homestead_flag_no_exemption": int(((hs_amt > 0) & (ex_total <= 0)).sum()),
        "n_other_exempt": int((other_exempt > match_tolerance).sum()),
        "n_institutional_exempt": int(institutional.sum()),
        "n_homestead_wiped": int(homestead_wiped.sum()),
        "n_homestead_wiped_reentering": int((homestead_wiped & ((ref_land + ref_bldg) > 0)).sum()),
        "reconstruction_match_rate": match_rate,
        "reconstruction_mismatch_dollars": float((rec_total - old_taxable)[~match].abs().sum()),
        "homestead_cap": float(homestead_cap),
    }
    return ExemptionCarryForward(
        ref_land, ref_bldg, ref_land + ref_bldg, institutional, hs_active, other_exempt, diagnostics,
    )
