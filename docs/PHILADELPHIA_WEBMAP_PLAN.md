# Philadelphia LVT Interactive Webmap

> **Status: reviewed and unblocked; implementation not started.** Nothing in the *Design* section
> has been built — no generator, no viewer, no tiles. What has happened (2026-08-01) is that every
> open decision was resolved, every data assumption was checked against the real inputs, and the
> sibling publishing project was scaffolded. This document remains the spec to argue with.
>
> All three original open decisions are now closed:
> - ~~Whether to build the custom site at all, versus leaning on CivicMapper / Put It On A Map.~~
>   **Resolved 2026-08-01** — the prior-art review below was redone against the live tools rather
>   than secondhand descriptions. Build-custom holds; see *Prior art* for what changed.
> - ~~The Progress & Poverty GitHub org handle, and repo-creation access scoped to it.~~
>   **Resolved 2026-08-01** — org is `Progress-and-Poverty-Institute`, user is an admin. The sibling
>   project is scaffolded at `C:\projects\philly-lvt-webmap`; the GitHub repo awaits only a
>   public-vs-private call. **No decisions now block implementation.** Remaining work is tasks:
>   install `tippecanoe` + `ogr2ogr` via WSL, then write the generator and viewer.
> - ~~Whether the LYCD cached inputs still exist on a local machine.~~ **Resolved 2026-08-01** —
>   they do, along with all four built CSVs. See *Inputs verified*, which closes every data risk
>   this plan listed. Tile size remains unmeasured, and the tile toolchain is not yet installed.

## Context

LVTShift models four Philadelphia LVT shift scenarios — OPA vs. LYCD land values × pre- vs.
post-abatement — but they only surface as static PNGs and flat CSVs. The reference point,
[taxshiftexplorer.org](https://taxshiftexplorer.org/#/map/philadelphia), already maps Philadelphia
parcels against the same 1.3998% combined levy, but on April-2020 data, with one scenario axis and
a slider that steps in fixed 10-point increments (see *Prior art*). We want a public, parcel-level
map of all four current models, with a live continuous land-share slider, hosted on GitHub Pages
under the Progress & Poverty org.

Stated honestly, the thing being proposed is **Tax Shift Explorer with current data, four scenario
dimensions, and a continuous rather than 10-point slider** — not a first-of-its-kind tool.

**Answer to "should this be a separate GitHub project": yes.** LVTShift is a Python research
toolkit whose `.gitignore` bans exactly what a Pages site must commit (`*.csv`, `*.parquet`,
`*.png`, `*.pmtiles`, `*.json`). A static site also wants its own deploy workflow, its own issue
tracker, and an owner (P&P) different from the toolkit's. So: **LVTShift gains a generator and the
viewer source; a new site repo holds the built artifact and does the hosting.**

### Prior art

Reviewed 2026-08-01 against the live tools and their source, replacing an earlier draft written
from secondhand descriptions. Two claims in that draft were wrong and are corrected below.

**No existing tool covers all four of:** parcel-level Philadelphia, multiple named scenarios,
continuous revenue-neutral re-solve, free public hosting. The closest gets two of four.

#### Tax Shift Explorer — closest by purpose

[taxshiftexplorer.org](https://taxshiftexplorer.org/) (Robert Schalkenbach Foundation / Center for
Property Tax Reform). React + Mapbox GL; 14 cities including Philadelphia; parcel vector tiles
(`.pbf` z/x/y) plus per-council-district GeoJSON choropleths. Characterized by reading its JS
bundle and data catalog, not its marketing copy:

- **Its slider is 11 precomputed discrete steps, not a live re-solve.** Steps are
  `[0, 10, 20, …, 100]` percent of revenue from land, backed by a static per-city table of 21
  numbers (`lt_100 = 0.05369`, `lt_90 = 0.048321`, … plus the `bt_*` improvement rates) and
  per-parcel `lt_<pct>_dif` fields baked into the tiles.
- Its `actual_tax_rate` is `0.013998` — Philadelphia's combined city + school rate, so it models
  the same levy this plan does.
- **Data vintage is in the hostname:** everything is served from the S3 bucket
  `rsf-2020-04-11`, i.e. April 2020.
- One scenario axis only — no OPA-vs-LYCD, no pre-vs-post-abatement.
- No public source repository found.

This is the most useful finding in the review, and it bears directly on the plan's top risk — see
*Size budget*, where the payload comparison now favors the closed-form approach.

#### Detroit LVT maps — validates the stack

[pjsier/detroit-land-value-tax-maps](https://github.com/pjsier/detroit-land-value-tax-maps) (MIT)
is the closest open-source US parcel-level precedent, and it independently arrives at this plan's
architecture: **MapLibre GL + tippecanoe vector tiles**, a Makefile pipeline, served as static
files from object storage. Still live. But it is a single fixed scenario with no slider,
residential-focused, Detroit-only, and untouched since January 2024.

#### Tax Policy Associates' England model — validates the live re-solve

[DanNeidle/lvt_model_2026](https://github.com/DanNeidle/lvt_model_2026) (MIT, 2026) is the one tool
found that genuinely re-solves revenue-neutrally in the browser: users set a marginal rate schedule
and see what it raises and who pays. Proof the pattern works in production. Not reusable code —
England-only, aggregated to local authority × council-tax band rather than parcel, and built around
council tax and stamp duty.

#### Also checked, not competitors

Detroit's [official city estimator](https://detroitmi.gov/departments/office-chief-financial-officer/land-value-tax-plan)
is an address lookup — no map, residential only, one scenario. Felt, Regrid, and UrbanFootprint
offer hosting, parcel data, and land-use scenario modeling, but none compute a revenue-neutral tax
re-solve, and all are commercial.

#### CivicMapper and Put It On A Map — two corrections

Both are Center for Land Economics tools, so the question was fair. Correcting the earlier draft:

- **CivicMapper has no login and no paywall** — the earlier "hosted product with a login" claim was
  wrong; the per-city viewers open directly. It covers **32 cities** (including many LVTShift
  already models: Baltimore, Rochester, St. Paul, Spokane, Albuquerque, Newport News,
  Bryan/College Station, Fort Collins), but **not Philadelphia**. It renders assessor land /
  improvement / market values as 3D extrusions with Value / Underused / Parking modes; its own
  methodology note confirms straight assessor data divided by lot area. No tax-shift modeling, no
  scenarios, no slider. "Want to add your city?" routes to **greg@landeconomics.org** — Greg, the
  upstream collaborator on this repo — so getting Philadelphia *land values* into CivicMapper is
  plausibly one email rather than a platform negotiation.
- **Put It On A Map cannot load a GeoParquet from a URL** — the earlier draft left this as an open
  question hoping for an "open this in PIOAM" deep link. It is answered: no. The viewer's only
  entry point is a local "Browse GeoParquet…" file picker, and its source
  ([larsiusprime/geovizwiz](https://github.com/larsiusprime/geovizwiz), MIT, actively developed)
  has no `URLSearchParams` or `location.search` handling anywhere. Remote fetching exists only in
  its separate ArcGIS Fetcher utility. The earlier draft also undersold it slightly: it is now a
  four-tool suite (3D Parcel Explorer, Data Fetcher, Format Converter, Construct) that does compute
  some derived metrics. Still nothing resembling a revenue-neutral re-solve or named scenarios.

These remain complements, not replacements — so the build **also emits a clean, well-named
GeoParquet per scenario as a first-class output**, not just an intermediate. `save_parcel_map_export`
(`lvt/parcel_map.py:62`) already writes exactly this format, so it is nearly free, and it means:

1. Anyone can download the file and open it in Put It On A Map's 3D viewer (download-and-open; a
   deep link is not possible).
2. It is the exact handoff artifact if P&P/CLE later want Philadelphia in CivicMapper.
3. The runbook links both tools so the GeoParquet is a documented, supported output rather than
   build residue.

### Constraints discovered while planning

- ~~**This container cannot build the data.**~~ **Superseded 2026-08-01.** That was true of the
  cloud container this plan was drafted in. Re-checked from the local Windows machine: `phl.carto.com`
  answers (`SELECT count(*) FROM opa_properties_public` → 583,706) and TIGERweb answers. More
  importantly, **the inputs are already on disk and do not need rebuilding** — see *Inputs verified*
  below. The synthetic-parcel test path is still worth keeping for CI and for anyone without the
  caches, but it is no longer the only option.
- **No notebook currently exports geometry.** All four call `save_standard_export` only — none call
  `save_parcel_map_export` / `create_parcel_map`. Geometry lives in the shared cache
  `cities/philadelphia/data/parcels.gpq`.
- **The browser can re-solve the model exactly.** `_solve_revenue_neutral_split_millage`
  (`lvt/lvt_utils.py:80`) uses a *closed form* whenever no percentage cap and no credit columns are
  passed — which is the case for all four Philadelphia notebooks. This is what makes a live slider
  faithful rather than an approximation.
- **GitHub hard-blocks files > 100 MB, and Pages does not resolve Git LFS.** Tile size is a
  first-class design constraint, with a documented fallback.

### Inputs verified (2026-08-01, local machine)

Checked directly rather than assumed. **Every data input this plan needs already exists, and the
three data risks it listed are resolved.** What is still missing is the *tile toolchain*, not the
data — see the end of *Data pipeline*.

- **The LYCD cached inputs are present** — this was the plan's "check before anything else."
  `parcel_areas_by_pin.parquet` (5.2 MB), `parcel_gma_assignment.parquet` (2.6 MB) and
  `parcels.gpq` (28 MB) are all in `cities/philadelphia/data/`. The map ships with four panels, not
  two.
- **All four CSVs already exist** (built 2026-07-18) with exactly the expected 17-column schema,
  including `parcel_id`, `taxable_land_value`, `taxable_improvement_value` and the published
  `land_millage` / `improvement_millage`. The claim in *Data pipeline* that the notebooks must be
  re-run "since nothing is cached" is **wrong** — re-running is a data-freshness decision, not a
  prerequisite.
- **The parcel universes are identical across all four scenarios** — 579,814 rows each, 44,116
  fully-exempt each, same `parcel_id` set. The "four CSVs disagree on the parcel universe" risk does
  not materialize (the build script should still report coverage, cheaply, in case that changes).
- **The `taxable_* == model_*` assertion passes exactly.** Re-deriving the 4:1 millages from the
  CSVs' own `current_tax` / `taxable_land_value` / `taxable_improvement_value` reproduces each
  file's published millages to **0.00%** in all four scenarios (OPA 29.08217 / 7.27054; LYCD
  23.64154 / 5.91038; OPA-post 32.06624 / 8.01656; LYCD-post 26.32383 / 6.58096), on both the
  all-parcel and non-exempt subsets. **The `extra_cols` fallback in *Data pipeline* is therefore not
  needed.** Keep the assertion in the build script as a regression guard; drop the fallback work.

**Column dedupe measured — the saving is larger than estimated.** The plan guessed ~40% of the
numeric payload from reasoning about which notebook shares which baseline. Measured pairwise across
the four CSVs:

| Column | Distinct series | Which collapse |
|---|---|---|
| `current_tax` | 2 of 4 | `opa == lycd`, `opa_post == lycd_post` |
| `taxable_land_value` | 2 of 4 | `opa == opa_post`, `lycd == lycd_post` |
| `taxable_improvement_value` | 2 of 4 | `lycd == opa_post == lycd_post`; `opa` differs |
| `property_category` | 2 of 4 | `opa == opa_post`, `lycd == lycd_post` |

So 6 distinct numeric series instead of 12 — **a 50% saving, not 40%**, and the dedupe step stays
as designed (discovered empirically, both shipped if two columns ever differ). The one result worth
a second look before trusting it: `taxable_improvement_value` collapsing three-ways with only `opa`
standing apart is plausible (the abated-building imputation) but was not predicted, so confirm it
is a real modelling consequence and not a notebook bug.

**One inconsistency found.** These CSVs carry `model_type = split_rate_4to1` (underscore), while
`CLAUDE.md` declares `split_rate:4.0` (colon) canonical and explicitly says "use colon format, not
underscore." The build script must not assume either spelling — read `model_type` as an opaque
label and take the scenario key from the filename. Worth fixing at the source separately; out of
scope here.

---

## Design

### 1. Client-side re-solve (the slider)

For a land share of revenue `s` over the solved (non-exempt) set with totals `ΣL`, `ΣI`, `R`:

```
land_millage = s * R * 1000 / ΣL
imp_millage  = (1 - s) * R * 1000 / ΣI
new_tax_i    = max(0, L_i * land_millage / 1000) + max(0, I_i * imp_millage / 1000)
pct_i        = current_i > 0 ? (new_i - current_i) / current_i * 100 : null
```

This is algebraically identical to the repo's ratio form
(`imp = R*1000/(ΣI + r*ΣL)`, `land = r*imp`) with `r = s*ΣI / ((1-s)*ΣL)`, and it handles the
land-only endpoint cleanly — the same identity `lvt/wage_tax_utils.py` relies on. The slider is
labelled by land share, with the current 4:1 point marked and the equivalent ratio shown as a
readout.

**Why it recolors instantly at 580K parcels:** MapLibre paint properties are expressions evaluated
on the GPU-side feature data. `fill-color` is a `step` over an inline arithmetic expression reading
each parcel's `L`, `I`, `cur` attributes with the two millages injected as literals. Moving the
slider or switching scenario is a single `setPaintProperty` call — no data reprocessing, no
re-fetch of tiles.

Those three attributes are the *entire* per-parcel cost of the slider. Tax Shift Explorer reaches
coarser 10-point granularity by baking ~11 precomputed difference columns per parcel into its tiles
instead; the closed form is both finer-grained and lighter. See *Size budget*.

### 2. Data pipeline — one script, no notebook churn required

`scripts/build_philadelphia_webmap.py` joins the four existing CSVs to cached geometry, exactly the
way `scripts/map_philadelphia_tax_changes.py:281-285` already does:

```python
parcels['parcel_id'] = parcels['parcel_number'].astype(str).str.lstrip('0').astype('Int64')
parcels = parcels.drop_duplicates(subset='parcel_id', keep='first')
```

Inputs — **all four already exist on disk** (built 2026-07-18; see *Inputs verified*). Re-running
the notebooks is a freshness decision, not a prerequisite, so the first build can happen
immediately:

| Scenario key | CSV | Notebook |
|---|---|---|
| `opa` | `analysis/data/philadelphia.csv` | `model.ipynb` |
| `lycd` | `analysis/data/philadelphia_lycd.csv` | `model_lycd.ipynb` |
| `opa_post` | `analysis/data/philadelphia_post_abatement.csv` | `model_post_abatement.ipynb` |
| `lycd_post` | `analysis/data/philadelphia_lycd_post_abatement.csv` | `model_lycd_post_abatement.ipynb` |

Geometry + owner from `cities/philadelphia/data/parcels.gpq` (`owner_1`, `owner_2`, `the_geom`).

The CSV's `taxable_land_value` / `taxable_improvement_value` **are** the solver's `model_land` /
`model_building` for every parcel in the solve — `model_split_rate_tax` writes
`adj_land_value`/`adj_improvement_value` into those names (`lvt/lvt_utils.py:639-640`), and with no
exemption columns passed those are the input columns unchanged. The build script asserts this by
re-deriving the published `land_millage`/`improvement_millage` from the CSV and comparing to the
values in the CSV's own `land_millage`/`improvement_millage` columns; it fails loudly on mismatch.

**This assertion has now been run against the real CSVs and passes at 0.00% in all four scenarios**
(see *Inputs verified*), so it ships as a regression guard rather than an open question. The
previously-planned fallback — adding `extra_cols` to `save_parcel_map_export` to emit
`model_land`/`model_building` explicitly — is **not needed and should not be built**. It remains a
reasonable general improvement to `lvt/parcel_map.py` on its own merits, but it is no longer on this
plan's critical path.

Steps:

1. Load the four CSVs, take the union of `parcel_id`, join to geometry.
2. **Dedupe identical columns across scenarios.** The script compares columns and emits each
   distinct series once, with `manifest.json` mapping scenario → attribute name. **Measured against
   the real CSVs: 6 distinct numeric series instead of 12, a 50% saving** (the collapse table is in
   *Inputs verified*; the original ~40% guess was conservative). The dedupe stays discovered
   empirically, not hardcoded to that table — if two columns ever differ, both ship.
3. Encode for size: dollars rounded to whole integers, `property_category` as a small int code with
   the lookup in the manifest, `parcel_id` as a **zero-padded 9-digit string** (required by the OPA
   record link — see the inspector bullet in *Viewer*).
4. Compute per-scenario aggregates over the non-exempt solve set: `ΣL`, `ΣI`, `R`, plus the 4:1
   millages, median change, and share paying more/less. These go in `manifest.json`.
5. Build tiles. Reuse `lvt/parcel_map.py:_build_pmtiles` (line 712 — ogr2ogr → GeoJSONSeq →
   tippecanoe), extended with an `attrs` parameter so it can carry the multi-scenario schema
   instead of the hardcoded `_TILE_ATTRS` (line 705). Backward compatible.
6. Write one GeoParquet per scenario to `analysis/maps/philadelphia*.parquet` via
   `save_parcel_map_export` — a supported output for Put It On A Map / CivicMapper, not just a
   build intermediate.
7. Assemble `analysis/webmap/site/` — viewer files + `philadelphia.pmtiles` + `manifest.json` —
   and print a size report plus the publish command.

**No tippecanoe?** `_have_tippecanoe()` (line 700) already checks for tippecanoe *and* ogr2ogr. The
script degrades to a GeoJSON source (fine for the synthetic test, unusable at 580K) and prints
platform-specific install guidance. The viewer reads its source type from the manifest, so both
paths use the same `app.js`.

**Toolchain checked on the target machine, 2026-08-01 — this is a real prerequisite gap.** Neither
`tippecanoe` nor `ogr2ogr` is installed on the Windows host, so a full-scale build cannot run today.
Present and fine: Node v24.14.1, geopandas 1.1.3, pyarrow 22.0.0, shapely 2.1.2, pandas 2.3.3.

The plan previously suggested `conda install -c conda-forge tippecanoe` first. **That will not work
here** — conda-forge publishes tippecanoe for `linux-64`, `linux-aarch64`, `linux-ppc64le`, `osx-64`
and `osx-arm64` only, with no Windows build. Docker is also not installed.

**The viable path on this machine is WSL**, which is already set up (Ubuntu-24.04), and where both
tools are one command away from Ubuntu's own repos (tippecanoe 2.49.0, GDAL 3.8.4):

```bash
wsl -e bash -lc "sudo apt update && sudo apt install -y tippecanoe gdal-bin"
```

Two consequences for the runbook. The tile step has to be invoked through WSL rather than assuming
tools on `PATH`, and reading 580K parcels across `/mnt/c/...` is materially slower than a native
path — stage the intermediate GeoJSONSeq inside the WSL filesystem and copy the finished `.pmtiles`
back out, rather than letting tippecanoe stream over the mount.

### 3. Viewer

Real source files under `webmap/` in LVTShift, not Python string templates — this one is too large
and will be iterated on in the browser. It is a deliberate fork of the existing
`_PMTILES_HTML_TEMPLATE` (`lvt/parcel_map.py:813`), keeping its visual language (stat chips,
road/satellite toggle, legend, sticky inspector panel, CLE eyebrow) and adding:

- `webmap/index.html` — shell
- `webmap/style.css` — lifted from the existing template's `<style>` block
- `webmap/solve.js` — pure math, no DOM: millages, per-parcel tax, color stops. Imported by both
  the app and the Node test.
- `webmap/app.js` — map, scenario tabs, slider, inspector, search, filter, URL hash
- `webmap/vendor/` — **vendored** `maplibre-gl` (4.7.1) and `pmtiles` (3.2.0) dist files pulled from
  npm at build time. The existing templates load these from unpkg at runtime; vendoring removes a
  third-party runtime dependency from a public site, which is the durable reason to do it — a P&P-
  hosted map should not break or leak referrers because a CDN changed. (The original draft also
  cited unpkg being proxy-blocked in its container. Both unpkg and `registry.npmjs.org` are
  reachable from the local machine, so that particular argument no longer applies; the
  supply-chain one still does.)

Features:

- Four scenario tabs (OPA / LYCD × pre / post abatement). Default **OPA pre-abatement at 4:1**.
- Land-share slider with the 4:1 point marked; live millage readout; a "reset to 4:1" control.
- Legend and stat chips (parcel count, median change, % paying more/less) recomputed live. Chips are
  computed from a small precomputed histogram in the manifest plus an exact client pass over a
  sampled subset, so they stay honest without shipping a second copy of the data.
- Click inspector: parcel number, owner, category, land/building value, current vs. new tax, $ and %
  change, link to the OPA property record. The template goes through the existing
  `parcel_url_template` convention (`lvt/parcel_map.py:44`). **Verified 2026-08-01:**
  `https://property.phila.gov/?p={parcel_id}` resolves correctly — **but the parcel ID must be
  zero-padded to 9 digits.** `?p=011001000` returns the right record; `?p=11001000` returns "No
  account found matching that address." This is a live trap for this pipeline specifically, because
  the geometry join strips leading zeros (`.str.lstrip('0').astype('Int64')`, per `CLAUDE.md`), so
  the stored `parcel_id` is exactly the form that fails. The build script must emit a zero-padded
  string for the link (`f"{pid:09d}"`), independently of the integer join key.
- Property-category filter (MapLibre `filter`, no re-render cost).
- Address / parcel-number search. Requires the OPA `location` column, which the current cache fetch
  does not select — see the one notebook edit below.
- URL hash carries scenario + land share (`#/opa/0.62`) so any view is linkable. Reading the hash on
  load also gives you the option of changing the landing view later without a rebuild.
- **Plain-language scenario copy.** A public map has to explain what it is showing. Each tab carries
  a one-paragraph explainer drawn from the notebooks: OPA = the assessor's published land values,
  where ~45% of improved parcels sit at a default 0.200 land ratio; LYCD = "Least You Can Do" land
  values rebuilt from median $/sqft in OPA's own GMA zones; post-abatement = the world after the
  10-year construction abatements expire. Plus a standing methodology note and a link back to
  LVTShift. This is written from the notebooks' own markdown, not invented.

### 4. Notebook edits — one, optional

Add `location` to the OPA `SELECT` in `cities/philadelphia/model.ipynb` (and the matching fallback
in `model_post_abatement.ipynb`) so the cache carries a street address for the inspector and search.
Per `CLAUDE.md`, **any rebuild of `parcels.gpq` must emit the full column superset** —
`pin`, `total_area`, `owner_1`, `owner_2` — so the edit adds to the list, never replaces it, and
`pin` stays integer-typed. Also update the `CLAUDE.md` cache-superset paragraph to include
`location`.

If you would rather not touch the notebooks, the map still works — search degrades to
parcel-number-only. The build script detects the missing column and says so.

### 5. Test harness (no real data required)

Written so the whole pipeline is testable without the Philadelphia caches — useful for CI, and for
anyone who does not have the gitignored inputs. Now that the real inputs are confirmed present, this
is a convenience rather than the only option, but it stays: it is what keeps the JS/Python agreement
under test.

- `scripts/build_philadelphia_webmap.py --synthetic 5000` fabricates a parcel set over the
  Philadelphia bbox with plausible land/building values and four scenario columns, then runs the
  *entire real pipeline*. Nothing about the build path is stubbed except the input.
- `tests/test_philadelphia_webmap.py` — asserts the manifest aggregates reproduce
  `model_split_rate_tax`'s millages at 4:1 to floating-point tolerance, and that the dedupe step is
  lossless.
- `webmap/solve.test.mjs` — runs `solve.js` against a JSON fixture emitted by the Python test and
  asserts the JS and Python millages and per-parcel taxes agree. **This is the test that matters**:
  it is what proves the slider is the model and not a lookalike. (Node v24.14.1 confirmed present
  locally; the plan was drafted against Node 22, and nothing here depends on the difference.)
- Playwright loads the synthetic site from a local `scripts/serve_maps.py` and screenshots it,
  confirming the viewer boots, the vendored libs resolve, and the scenario tabs and slider recolor.
  **Confirmed available on the Windows host** — the `playwright` module is installed and
  `%LOCALAPPDATA%\ms-playwright` already holds `chromium-1223` and `chromium_headless_shell-1223`,
  so this step needs no setup.

### 6. Publishing

Build output `analysis/webmap/site/` (gitignored in LVTShift) is the site repo's entire content:

```
index.html  app.js  solve.js  style.css  vendor/  manifest.json
philadelphia.pmtiles  .nojekyll  README.md  LICENSE
.github/workflows/pages.yml
```

`pages.yml` is a plain `actions/deploy-pages` publish — no build step in CI, since the tiles are
committed. LVTShift also gets `docs/PHILADELPHIA_WEBMAP.md`: the runbook for re-running the four
notebooks, building, and pushing.

**Size budget.** 580K parcels is the real risk. Mitigations, applied in order until it fits under
100 MB: integer dollar encoding, column dedupe, category codes, capping tippecanoe max zoom, and
dropping owner strings (a `--no-owner` flag; the OPA record link already carries that information).
**If it still does not fit:** publish `philadelphia.pmtiles` as a **GitHub Release asset** instead of
a committed file — 2 GB limit, CORS and byte-range both supported — and point `manifest.json` at
that URL. The site repo then stays under a megabyte. The build script reports the size and tells you
which path you are on.

**The closed-form re-solve is also the cheaper option, which is the argument for it that matters
here.** Tax Shift Explorer buys its 10-point granularity by baking ~11 per-parcel `lt_<pct>_dif`
columns into its tiles. The closed form ships **3 columns per parcel** (`L`, `I`, `cur`) and
evaluates the rest in a GPU paint expression, for *continuous* granularity. So the live slider is
not a feature paid for with payload — it is the lighter design, which matters directly against the
100 MB ceiling.

**Fallback of last resort.** If the closed form ever proves infeasible, Tax Shift Explorer
demonstrates that precomputing a discrete step table works in production. It costs granularity and
payload rather than saving either, so it ranks below every mitigation above — but it is a known-good
escape hatch, not a theory.

~~**I still need the P&P org handle**, and GitHub access scoped to that org.~~ **Resolved
2026-08-01.** The org is **`Progress-and-Poverty-Institute`** and the authenticated user is an
**admin** of it, so repo creation is available on request (org policy permits both public and
private member-created repos; most existing repos there are private, a few public).

The sibling project now exists locally at **`C:\projects\philly-lvt-webmap`** — git-initialised,
scaffolded with the Pages workflow, `.nojekyll`, licence and docs, one commit. Its `CLAUDE.md`
carries the mechanics and the gotchas from this plan.

**The GitHub repo has deliberately not been created yet**, for two reasons: there is nothing to
publish until a build runs, and the public-vs-private choice is the user's to make (the site is
intended to be public, which makes repo creation an outward-facing act). Creating it is one command
once that call is made.

---

## Files

**New in LVTShift**

- `scripts/build_philadelphia_webmap.py` — generator, `--synthetic N`, `--no-owner`, `--out`
- `webmap/index.html`, `webmap/style.css`, `webmap/app.js`, `webmap/solve.js`
- `webmap/solve.test.mjs`
- `tests/test_philadelphia_webmap.py`
- `docs/PHILADELPHIA_WEBMAP.md`
- `site-template/.github/workflows/pages.yml`, `site-template/README.md`, `site-template/.nojekyll`

**Modified in LVTShift**

- `lvt/parcel_map.py` — `_build_pmtiles(..., attrs=None)`. (The conditional
  `save_parcel_map_export(..., extra_cols=None)` change is **no longer needed** — the taxable-column
  assertion passes; see *Inputs verified*.)
- `cities/philadelphia/model.ipynb`, `model_post_abatement.ipynb` — add `location` to the OPA SELECT
- `.gitignore` — ignore `analysis/webmap/`, and add negations for the two things the blanket
  `*.json` / `*.png` rules would otherwise swallow: the Node test fixture and any committed
  screenshot. (`*.json` is ignored repo-wide today, so `webmap/` fixtures need an explicit `!` rule
  rather than `git add -f`.)
- `CLAUDE.md`, `README.md` — document the webmap and the `location` cache column

**Sibling site project** — `C:\projects\philly-lvt-webmap`, destined for
`Progress-and-Poverty-Institute/philly-lvt-webmap`. Created and scaffolded 2026-08-01; receives the
built `site/` contents above. Note the build must copy only the *generated* files into it, not
overwrite its root wholesale, or it will clobber that repo's permanent `README.md`, `LICENSE`,
`CLAUDE.md`, `.gitignore` and `.github/`.

---

## Verification

1. `python3 scripts/build_philadelphia_webmap.py --synthetic 5000` — completes, writes
   `analysis/webmap/site/`, prints the size report.
2. `python3 -m pytest tests/test_philadelphia_webmap.py -q` — manifest aggregates reproduce
   `model_split_rate_tax` at 4:1.
3. `node webmap/solve.test.mjs` — JS re-solve matches the Python fixture parcel-for-parcel.
4. `python3 scripts/serve_maps.py` + Playwright screenshot — viewer boots, tabs switch, slider
   recolors, inspector populates on click.
5. **On your machine, with real data:** re-run the four notebooks, run the build without
   `--synthetic`, confirm the manifest's 4:1 millages match each notebook's printed millages, spot-
   check a handful of parcels against `property.phila.gov`, and serve locally before pushing. When
   spot-checking, click the inspector's OPA link rather than pasting the parcel ID by hand — that is
   what exercises the 9-digit zero-padding, and an unpadded ID fails silently with "No account
   found" rather than erroring.

## Risks

The 2026-08-01 verification pass closed every *data* risk listed here. What is left is a missing
toolchain (cheap, known fix) and tile size (still genuinely unmeasured, because the toolchain gap
means no full-scale build has run).

- **tippecanoe / ogr2ogr are not installed on the target machine.** Cheap to fix (one `apt` command
  inside the already-present WSL Ubuntu-24.04), but it does mean no full-scale build has been
  attempted, which is why tile size remains unmeasured. Note the conda route does not exist on
  Windows — see *Data pipeline*.
- **Tile size > 100 MB.** Still open, and the likeliest substantive failure. Mitigation ladder above;
  Release-asset hosting is the guaranteed escape hatch. The measured 50% dedupe saving and the
  3-columns-per-parcel slider design both cut in the right direction, but nothing is confirmed until
  tippecanoe has actually run over 580K real parcels.
- ~~**`taxable_*` ≠ `model_*` for some parcel subset.**~~ **Resolved** — the millage re-derivation
  matches at 0.00% across all four scenarios. Assertion stays as a regression guard; the `extra_cols`
  fallback is not needed.
- ~~**The four CSVs disagree on the parcel universe.**~~ **Resolved** — identical `parcel_id` sets,
  579,814 rows and 44,116 exempt in each. Keep the cheap coverage report in case that changes.
- ~~**The LYCD notebooks need cached inputs that are not in the repo.**~~ **Resolved** —
  `parcel_areas_by_pin.parquet` and `parcel_gma_assignment.parquet` are both present locally, as are
  all four built CSVs. Four panels, not two. (The underlying fragility stands: these files are
  gitignored and exist on exactly one machine. Worth a backup independent of this project.)
- ~~**Nothing here is verifiable against real Philadelphia data in this session.**~~ **Partly
  resolved** — the input schema, parcel universes, millage assertion, dedupe saving and OPA link
  format have all now been checked against the real data. What remains unverified is everything
  downstream of a build that has not been run: tile size, viewer behaviour at full scale, and
  parcel-level spot checks. Verification step 5 is still yours to run.

**New risk, small:** the OPA record link needs a **9-digit zero-padded** `parcel_id`, while the
geometry join strips leading zeros. An unpadded ID does not error — it renders a plausible-looking
"No account found" page. Easy to ship broken and not notice; covered in *Verification* step 5.
