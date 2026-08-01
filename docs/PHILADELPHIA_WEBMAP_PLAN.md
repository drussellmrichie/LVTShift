# Philadelphia LVT Interactive Webmap

> **Status: proposal — paused before implementation.** Nothing described in the *Design* or *Files*
> sections has been built. This document exists to be reviewed and argued with first.
>
> Open decisions blocking implementation:
> - Whether to build the custom site at all, versus leaning on CivicMapper / Put It On A Map (see
>   the section below — both domains were unreachable from the environment this was drafted in, so
>   that comparison rests on secondhand descriptions and should be checked).
> - The Progress & Poverty GitHub org handle, and repo-creation access scoped to it.
> - Whether the LYCD cached inputs (`parcel_areas_by_pin.parquet`, GMA zone assignments) still
>   exist on a local machine — see *Risks*. Worth checking before anything else.

## Context

LVTShift models four Philadelphia LVT shift scenarios — OPA vs. LYCD land values × pre- vs.
post-abatement — but they only surface as static PNGs and flat CSVs. The reference point,
[taxshiftexplorer.org](https://taxshiftexplorer.org/#/map/philadelphia), is built on years-old OPA
data and shows a single jurisdiction at a time. We want a public, parcel-level map of all four
current models, with a live land-share slider, hosted on GitHub Pages under the Progress & Poverty
org.

**Answer to "should this be a separate GitHub project": yes.** LVTShift is a Python research
toolkit whose `.gitignore` bans exactly what a Pages site must commit (`*.csv`, `*.parquet`,
`*.png`, `*.pmtiles`, `*.json`). A static site also wants its own deploy workflow, its own issue
tracker, and an owner (P&P) different from the toolkit's. So: **LVTShift gains a generator and the
viewer source; a new site repo holds the built artifact and does the hosting.**

### Why not just use CivicMapper / Put It On A Map

Both are Center for Land Economics tools, so the question is fair. (Caveat: this container's proxy
403s both domains, so this is from search results and P&P's own writeups, not the live pages.)

- **Put It On A Map** is a bring-your-own-file inspection tool — open a GeoParquet or shapefile,
  pick an attribute, render in 3D. No hosting, no persistent public URL, no custom UI, and it
  renders an attribute rather than computing one. It cannot express four named scenarios, a
  revenue-neutral re-solve, or methodology copy.
- **CivicMapper** is a hosted, curated, per-city 3D land-value product with a login. Getting the
  four Philadelphia LVT-shift scenarios in would mean asking CLE to ingest our data into their
  platform, and it visualizes land value, not modeled tax-shift outcomes.

They are complements, not replacements — so the build **also emits a clean, well-named GeoParquet
per scenario as a first-class output**, not just an intermediate. `save_parcel_map_export`
(`lvt/parcel_map.py:62`) already writes exactly this format, so it is nearly free, and it means:

1. Anyone can drop the file into Put It On A Map and explore it in 3D immediately.
2. It is the exact handoff artifact if P&P/CLE later want Philadelphia in CivicMapper.
3. The runbook links both tools so the GeoParquet is a documented, supported output rather than
   build residue.

Worth checking on the first local build: whether Put It On A Map can load a GeoParquet from a URL.
If it can, the site gets an "open this in Put It On A Map" deep link and the two tools compose
directly.

### Constraints discovered while planning

- **This container cannot build the data.** The network policy 403s `phl.carto.com` and the Census;
  `cities/philadelphia/data/`, `analysis/data/`, and `analysis/maps/` do not exist on disk. Per
  your answer, the real build runs on your machine. Everything here is developed and self-tested
  against synthetic parcels.
- **No notebook currently exports geometry.** All four call `save_standard_export` only — none call
  `save_parcel_map_export` / `create_parcel_map`. Geometry lives in the shared cache
  `cities/philadelphia/data/parcels.gpq`.
- **The browser can re-solve the model exactly.** `_solve_revenue_neutral_split_millage`
  (`lvt/lvt_utils.py:80`) uses a *closed form* whenever no percentage cap and no credit columns are
  passed — which is the case for all four Philadelphia notebooks. This is what makes a live slider
  faithful rather than an approximation.
- **GitHub hard-blocks files > 100 MB, and Pages does not resolve Git LFS.** Tile size is a
  first-class design constraint, with a documented fallback.

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

### 2. Data pipeline — one script, no notebook churn required

`scripts/build_philadelphia_webmap.py` joins the four existing CSVs to cached geometry, exactly the
way `scripts/map_philadelphia_tax_changes.py:281-285` already does:

```python
parcels['parcel_id'] = parcels['parcel_number'].astype(str).str.lstrip('0').astype('Int64')
parcels = parcels.drop_duplicates(subset='parcel_id', keep='first')
```

Inputs (all produced by re-running the four notebooks, which you must do anyway since nothing is
cached):

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
**Fallback if the assertion fails:** add an `extra_cols` parameter to
`lvt/parcel_map.py:save_parcel_map_export` and emit `model_land`/`model_building` explicitly from
the notebooks — a small, general improvement that helps every city.

Steps:

1. Load the four CSVs, take the union of `parcel_id`, join to geometry.
2. **Dedupe identical columns across scenarios.** `model_lycd.ipynb` Step 7 takes its revenue
   baseline from the same OPA taxable values as `model.ipynb`, so `current_tax` is shared between
   OPA and LYCD; only land value differs. Pre vs. post abatement changes both. The script compares
   columns and emits each distinct series once, with `manifest.json` mapping scenario → attribute
   name. Expected saving: ~40% of the numeric payload. The dedupe is discovered empirically, not
   assumed — if two columns turn out to differ, both ship.
3. Encode for size: dollars rounded to whole integers, `property_category` as a small int code with
   the lookup in the manifest, `parcel_id` as a string.
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
platform-specific install guidance: `conda install -c conda-forge tippecanoe`, WSL, Homebrew, or the
Docker one-liner. The viewer reads its source type from the manifest, so both paths use the same
`app.js`.

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
  npm at build time. The existing templates load these from unpkg; vendoring removes a third-party
  runtime dependency from a public site and is what makes a headless render test possible here
  (unpkg is blocked by this container's proxy; `registry.npmjs.org` is not).

Features:

- Four scenario tabs (OPA / LYCD × pre / post abatement). Default **OPA pre-abatement at 4:1**.
- Land-share slider with the 4:1 point marked; live millage readout; a "reset to 4:1" control.
- Legend and stat chips (parcel count, median change, % paying more/less) recomputed live. Chips are
  computed from a small precomputed histogram in the manifest plus an exact client pass over a
  sampled subset, so they stay honest without shipping a second copy of the data.
- Click inspector: parcel number, owner, category, land/building value, current vs. new tax, $ and %
  change, link to the OPA property record. The template goes through the existing
  `parcel_url_template` convention (`lvt/parcel_map.py:44`); the intended value is
  `https://property.phila.gov/?p={parcel_id}`, which I could not verify from this container
  (outbound HTTPS to non-allowlisted hosts is blocked) — confirm it on first local build.
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

### 5. Test harness (runs in this container)

- `scripts/build_philadelphia_webmap.py --synthetic 5000` fabricates a parcel set over the
  Philadelphia bbox with plausible land/building values and four scenario columns, then runs the
  *entire real pipeline*. Nothing about the build path is stubbed except the input.
- `tests/test_philadelphia_webmap.py` — asserts the manifest aggregates reproduce
  `model_split_rate_tax`'s millages at 4:1 to floating-point tolerance, and that the dedupe step is
  lossless.
- `webmap/solve.test.mjs` — Node 22 is available. Runs `solve.js` against a JSON fixture emitted by
  the Python test and asserts the JS and Python millages and per-parcel taxes agree. **This is the
  test that matters**: it is what proves the slider is the model and not a lookalike.
- Playwright + the preinstalled Chromium loads the synthetic site from a local
  `scripts/serve_maps.py` and screenshots it, confirming the viewer boots, the vendored libs
  resolve, and the scenario tabs and slider recolor.

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

**I still need the P&P org handle**, and GitHub access scoped to that org before I can create the
repo — this session is scoped to `drussellmrichie/lvtshift`. Until then the org/repo is a constant
at the top of the build script and the runbook, and everything is developed and tested in LVTShift.

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

- `lvt/parcel_map.py` — `_build_pmtiles(..., attrs=None)`; `save_parcel_map_export(..., extra_cols=None)`
  only if the taxable-column assertion fails
- `cities/philadelphia/model.ipynb`, `model_post_abatement.ipynb` — add `location` to the OPA SELECT
- `.gitignore` — ignore `analysis/webmap/`, and add negations for the two things the blanket
  `*.json` / `*.png` rules would otherwise swallow: the Node test fixture and any committed
  screenshot. (`*.json` is ignored repo-wide today, so `webmap/` fixtures need an explicit `!` rule
  rather than `git add -f`.)
- `CLAUDE.md`, `README.md` — document the webmap and the `location` cache column

**New site repo** (P&P org, name TBC) — the built `site/` contents above.

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
   check a handful of parcels against `property.phila.gov`, and serve locally before pushing.

## Risks

- **Tile size > 100 MB.** Most likely failure. Mitigation ladder above; Release-asset hosting is the
  guaranteed escape hatch.
- **`taxable_*` ≠ `model_*` for some parcel subset** (e.g. how exempt rows were merged back after the
  solve). Caught by the build script's millage assertion; fixed by the `extra_cols` fallback.
- **The four CSVs disagree on the parcel universe** (different filtering per notebook). The script
  reports per-scenario coverage and renders missing parcels as "not modeled" rather than silently
  dropping them.
- **The LYCD notebooks need cached inputs that are not in the repo.** `model_lycd.ipynb` Step 2
  reads a pre-built `parcel_areas_by_pin.parquet` (577K DOR PIN → lot area) and Step 4 needs GMA
  zone assignments. Both live under the gitignored `cities/philadelphia/data/` and are absent here.
  If they are also gone from your machine, the two LYCD scenarios cannot be regenerated and the map
  ships with two panels instead of four until they are rebuilt. Worth checking before anything else.
- **Nothing here is verifiable against real Philadelphia data in this session.** Step 5 above is
  yours to run, and the numbers are not confirmed until you do.
