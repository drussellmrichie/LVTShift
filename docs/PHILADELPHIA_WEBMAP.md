# Philadelphia webmap — build runbook

Companion to [`PHILADELPHIA_WEBMAP_PLAN.md`](PHILADELPHIA_WEBMAP_PLAN.md), which has the design
rationale. This is the operational how-to: set up the toolchain, run the build, read its output,
work the size ladder if you need to, and publish.

The generator lives in this repo at `scripts/build_philadelphia_webmap.py`. The viewer it feeds
(`index.html`, `app.js`, `solve.js`, `style.css`, `vendor/`) lives in the sibling site repo,
`philly-lvt-webmap`, as permanent hand-authored source — the generator writes exactly two files
there (`manifest.json`, `philadelphia.pmtiles`) and touches nothing else.

## One-time setup: the tile toolchain (WSL)

`tippecanoe` has no Windows build, and Windows conda's GDAL install does not load
(`GDAL DLL could not be found`), so the tiling step always shells out to WSL.

```bash
wsl -d Ubuntu-24.04 -- bash -lc "sudo apt update && sudo apt install -y tippecanoe gdal-bin"
wsl -d Ubuntu-24.04 -- tippecanoe --version
wsl -d Ubuntu-24.04 -- ogr2ogr --version
```

If you use a different distro name, the generator's `WSL_DISTRO` constant needs to match.

Ubuntu's `gdal-bin` has no Parquet/Arrow driver (`ogr2ogr --formats` will not list one, and no
plugin package supplies it either), so the generator never asks it to read or write GeoParquet. All
Windows-side geometry I/O goes through GeoParquet (pyarrow + shapely, no GDAL needed); all WSL-side
work is GeoJSONSeq in, PMTiles out.

## Prerequisites the build expects on disk

All gitignored, all produced by running the four Philadelphia notebooks at least once:

- `analysis/data/philadelphia.csv`, `philadelphia_lycd.csv`, `philadelphia_post_abatement.csv`,
  `philadelphia_lycd_post_abatement.csv`
- `cities/philadelphia/data/parcels.gpq` (geometry cache — OPA centroids)
- For `--geometry polygon`: `cities/philadelphia/data/Philadelphia_DOR_Parcels_2023.geojson`. **Not**
  the shapefile in `cities/philadelphia/data/dor_parcels/` — that file has no `PIN` field and cannot
  be joined to `parcels.gpq`. See `CLAUDE.md`'s Philadelphia section for why.

## Commands

Cheapest sanity check — no data read beyond the CSVs and geometry cache, no WSL, no output written:

```bash
python scripts/build_philadelphia_webmap.py --stage attrs --dry-run
```

Prints the millage assertions, the empirically-discovered column dedupe, and the geometry join
coverage. This is the fastest way to know the model still reproduces itself after any upstream
change to the notebooks or the cache.

First real tiles, in seconds, over a Center City slice:

```bash
python scripts/build_philadelphia_webmap.py --bbox center-city
```

The full city, point geometry (fast, small — this is the default):

```bash
python scripts/build_philadelphia_webmap.py
```

The full city with real lot outlines for the ~90% of parcels that join to one (slower — reads the
504 MB DOR GeoJSON once and caches the extract; bigger tiles):

```bash
python scripts/build_philadelphia_webmap.py --geometry polygon
```

Useful flags:

| Flag | Effect |
|---|---|
| `--out PATH` | site repo root (default `C:/projects/philly-lvt-webmap`) |
| `--stage {attrs,tiles,all}` | stop after the attribute/assertion stage, or run everything |
| `--bbox center-city` or `W,S,E,N` | geographic slice, for fast iteration |
| `--sample N` | keep every Nth parcel — a thin citywide slice |
| `--geometry {point,polygon}` | default `point` |
| `--no-owner` | drop `own`/`own2` from the tiles (size ladder rung 5) |
| `--max-zoom N` | cap tippecanoe's max zoom instead of letting `-zg` guess |
| `--tiles-hosting {committed,release}` `--release-url URL` | point the manifest at a GitHub Release asset instead of the committed file |
| `--emit-fixture PATH` | write the Python↔JS agreement fixture (see below) |
| `--dry-run` | compute and print, write nothing |

## Reading the output

The build prints, in order: the four millage assertions (each must reproduce the notebook's own
published millage from the CSV's own value columns), the dedupe partition (12 numeric series → 9,
rediscovered every run rather than hardcoded), geometry join coverage, the stat-curve interpolation
error (must stay under 0.5 percentage points — if it doesn't, raise
`LAND_SHARE_GRID_POINTS`), and finally the tile size.

## The size ladder

GitHub hard-blocks commits over 100 MB and does not resolve Git LFS on Pages; the build targets
90 MB committed and warns above 50 MB. As built, the **point** geometry full-city tile is 53.4 MB —
over the 50 MB warning threshold (it grew from an earlier 50.5 MB measurement once the abated-parcel
imputation fix made `taxable_improvement_value`/`taxable_land_value` split into 3 series instead of
2, per `CLAUDE.md`), but still comfortably under the 90 MB target with no ladder rungs needed yet.
Points already get, unconditionally: integer dollars, the 12→9 series dedupe, and `uint8` category
codes. If a future rebuild needs to shed more:

1. `--max-zoom 14` (or lower) instead of letting `-zg` guess
2. `--no-owner`
3. If still over 90 MB: rebuild with `--tiles-hosting release`, then
   `gh release upload tiles-v1 philadelphia.pmtiles` — the manifest's `tiles.hosting` field is the
   only thing that changes; `app.js` reads it and behaves identically either way.

**Polygon geometry is where this ladder actually gets exercised** — real lot boundaries are denser
than a coordinate pair per parcel. The polygon build adds `--simplification=4
--coalesce-densest-as-needed` automatically; if that's not enough, `--max-zoom` and `--no-owner` are
the next rungs before falling back to a Release asset.

## The Python↔JS agreement test

This is the test that matters: it is what proves the browser's slider *is* the model rather than an
approximation of it.

```bash
python scripts/build_philadelphia_webmap.py --stage attrs --emit-fixture tests/fixtures/solve_fixture.json --out <any throwaway dir>
python -m pytest tests/test_philadelphia_webmap.py -q
node --test tests/solve.test.mjs
```

The fixture is committed (`tests/fixtures/solve_fixture.json`, ignored-by-default `*.json` pattern
negated explicitly in `.gitignore`). Regenerate it whenever the notebooks, the CSVs, or `solve.js`'s
math change; `pytest`'s `test_the_committed_fixture_matches_the_current_exports` will fail loudly if
it goes stale relative to the exports. The Node test imports `solve.js` straight from the site repo
(override the path with `WEBMAP_SRC` if you've checked it out somewhere other than
`../philly-lvt-webmap`), so there is exactly one copy of the math and it's the one the browser runs
— including a small MapLibre expression interpreter that evaluates the actual GPU paint expression
against the scalar path, not just the scalar path against itself.

## Serving it locally

PMTiles need HTTP range requests; `python -m http.server` returns the whole file with a 200 and
breaks. From the site repo root:

```bash
python ../LVTShift/scripts/serve_maps.py 8000
```

Then open `http://localhost:8000/`.

## Verifying against the live OPA site

`manifest.links.opa_record_template` is `https://property.phila.gov/?p={pid9}`, and the parcel id
**must** be zero-padded to 9 digits — `?p=011000022` resolves to a real record, `?p=11000022`
returns a plausible-looking "No account found" page rather than an error. `solve.js`'s
`opaRecordUrl` does the padding and the Node test asserts it.

Do not expect the assessed values on the live page to match the model's numbers — the notebooks
model `assessments WHERE year = '2024'`, while `property.phila.gov` shows the current assessment
cycle, which is routinely a different (higher) figure for the same parcel. Confirm identity (address,
owner, parcel id resolves) against the live page; confirm dollar figures against a Carto
`assessments WHERE year='2024'` query instead.

## Publishing

Gated on the Progress & Poverty GitHub org handle, which is not yet known — everything through a
full local build and test run is independent of it.

```bash
gh repo create <PP_ORG>/philly-lvt-webmap --public --source . --push
```

Then enable Pages on that repo with **Source: GitHub Actions** — `.github/workflows/pages.yml` is
already committed and needs no changes; it uploads the repo root with no build step, since the tiles
are committed directly.
