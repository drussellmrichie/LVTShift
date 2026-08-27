/**
 * Python <-> JavaScript agreement test for the Philadelphia webmap.
 *
 * This is the test that matters: it is what proves the map's slider *is* the
 * model rather than a lookalike. solve.js lives in the site repo
 * (philly-lvt-webmap); the fixture is emitted here by the Python build via
 *
 *     python scripts/build_philadelphia_webmap.py --stage attrs \
 *         --emit-fixture tests/fixtures/solve_fixture.json --out <scratch>
 *
 * Run:  node --test tests/solve.test.mjs
 *       WEBMAP_SRC=../elsewhere node --test tests/solve.test.mjs
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEBMAP_SRC = resolve(HERE, process.env.WEBMAP_SRC ?? '../../philly-lvt-webmap');
const FIXTURE = resolve(HERE, 'fixtures/solve_fixture.json');

const solve = await import(pathToFileURL(resolve(WEBMAP_SRC, 'solve.js')).href);
const fixture = JSON.parse(readFileSync(FIXTURE, 'utf8'));
const SCENARIOS = Object.keys(fixture.scenarios);

/**
 * A minimal interpreter for the MapLibre expression subset fillColorExpression
 * emits. The GPU evaluates the expression, not the scalar helpers, so without
 * this the map could be colored by subtly different math than everything else
 * here verifies.
 */
function evalExpr(expr, props) {
  if (!Array.isArray(expr)) return expr;
  const [op, ...args] = expr;
  const ev = (e) => evalExpr(e, props);

  switch (op) {
    case 'literal':
      return args[0];
    case 'get':
      return props[ev(args[0])];
    case 'has':
      return Object.prototype.hasOwnProperty.call(props, ev(args[0]));
    case 'to-number': {
      for (const arg of args) {
        const value = ev(arg);
        if (value === null || value === undefined) continue;
        const n = typeof value === 'boolean' ? Number(value) : Number(value);
        if (!Number.isNaN(n)) return n;
      }
      throw new Error('to-number: no convertible argument');
    }
    case '+':
      return args.reduce((total, a) => total + ev(a), 0);
    case '-':
      return args.length === 1 ? -ev(args[0]) : ev(args[0]) - ev(args[1]);
    case '*':
      return args.reduce((total, a) => total * ev(a), 1);
    case '/':
      return ev(args[0]) / ev(args[1]);
    case 'max':
      return Math.max(...args.map(ev));
    case 'min':
      return Math.min(...args.map(ev));
    case '<':
      return ev(args[0]) < ev(args[1]);
    case '<=':
      return ev(args[0]) <= ev(args[1]);
    case '>':
      return ev(args[0]) > ev(args[1]);
    case '>=':
      return ev(args[0]) >= ev(args[1]);
    case '==':
      return ev(args[0]) === ev(args[1]);
    case '!':
      return !ev(args[0]);
    case 'case': {
      for (let i = 0; i + 1 < args.length; i += 2) {
        if (ev(args[i])) return ev(args[i + 1]);
      }
      return ev(args[args.length - 1]);
    }
    case 'step': {
      const input = ev(args[0]);
      let output = ev(args[1]);
      for (let i = 2; i + 1 < args.length; i += 2) {
        if (input >= ev(args[i])) output = ev(args[i + 1]);
        else break;
      }
      return output;
    }
    default:
      throw new Error(`unsupported expression operator: ${op}`);
  }
}

test('the fixture covers all four scenarios and real edge cases', () => {
  assert.equal(fixture.schema_version, 1);
  assert.deepEqual(SCENARIOS.sort(), ['lycd', 'lycd_post', 'opa', 'opa_post']);
  for (const key of SCENARIOS) {
    const parcels = fixture.scenarios[key].parcels;
    assert.ok(parcels.length >= 150, `${key}: only ${parcels.length} fixture parcels`);
    assert.ok(parcels.some((p) => p.cur === 0), `${key}: no zero-current-bill parcel`);
    assert.ok(parcels.some((p) => p.ex === 1), `${key}: no exempt parcel`);
    assert.ok(parcels.some((p) => p.i === 0), `${key}: no zero-improvement parcel`);
  }
});

test('the color stops match the Python model', () => {
  const expected = fixture.color_stops.map(([stop, color]) => [stop ?? Infinity, color]);
  assert.deepEqual(solve.COLOR_STOPS, expected);
  assert.equal(solve.NO_DATA_COLOR, fixture.no_data_color);
});

test('solveMillages reproduces the published millages', () => {
  for (const key of SCENARIOS) {
    const { totals, published } = fixture.scenarios[key];
    const got = solve.solveMillages(totals, published.landShare);
    assertClose(got.landMillage, published.landMillage, 1e-12, `${key} land millage`);
    assertClose(got.impMillage, published.impMillage, 1e-12, `${key} improvement millage`);
  }
});

test('publishedLandShare inverts the 4:1 ratio', () => {
  for (const key of SCENARIOS) {
    const { totals, published } = fixture.scenarios[key];
    const share = solve.publishedLandShare(totals, published.ratio);
    assertClose(share, published.landShare, 1e-12, `${key} land share`);
    const ratio = solve.ratioFromLandShare(totals, share);
    assertClose(ratio, published.ratio, 1e-9, `${key} ratio round-trip`);
  }
});

test('solveMillages matches Python at every land share in the fixture', () => {
  for (const key of SCENARIOS) {
    const { totals, cases } = fixture.scenarios[key];
    for (const c of cases) {
      const got = solve.solveMillages(totals, c.landShare);
      assertClose(got.landMillage, c.landMillage, 1e-12, `${key} @${c.landShare} land`);
      assertClose(got.impMillage, c.impMillage, 1e-12, `${key} @${c.landShare} improvement`);
      assert.ok(Number.isFinite(got.landMillage) && Number.isFinite(got.impMillage),
        `${key} @${c.landShare}: non-finite millage`);
    }
  }
});

test('per-parcel tax, percent change and color match Python', () => {
  let checked = 0;
  for (const key of SCENARIOS) {
    const { totals, parcels } = fixture.scenarios[key];
    for (const parcel of parcels) {
      for (const want of parcel.expected) {
        const m = solve.solveMillages(totals, want.landShare);
        const newTax = solve.parcelTax(parcel.l, parcel.i, m.landMillage, m.impMillage);
        const pct = solve.taxChangePct(newTax, parcel.cur);

        assertClose(newTax, want.newTax, 1e-6, `${key} pid ${parcel.pid} @${want.landShare} tax`);
        if (want.pct === null) {
          assert.equal(pct, null, `${key} pid ${parcel.pid}: expected no percent change`);
        } else {
          assertClose(pct, want.pct, 1e-6, `${key} pid ${parcel.pid} @${want.landShare} pct`);
        }
        assert.equal(solve.colorIndex(pct), want.colorIndex,
          `${key} pid ${parcel.pid} @${want.landShare} color bucket`);
        checked += 1;
      }
    }
  }
  assert.ok(checked > 3000, `only ${checked} parcel-cases checked`);
});

test('the paint expression agrees with the scalar path for every parcel', () => {
  for (const key of SCENARIOS) {
    const { totals, attrs, parcels } = fixture.scenarios[key];
    for (const parcel of parcels) {
      for (const want of parcel.expected) {
        const millages = solve.solveMillages(totals, want.landShare);
        const expression = solve.fillColorExpression(attrs, millages);
        const props = {
          [attrs.current_tax]: parcel.cur,
          [attrs.land_value]: parcel.l,
          [attrs.improvement_value]: parcel.i,
        };
        const painted = evalExpr(expression, props);
        const scalar = solve.colorFor(want.pct);
        assert.equal(painted, scalar,
          `${key} pid ${parcel.pid} @${want.landShare}: GPU expression painted ${painted} ` +
          `but the scalar path says ${scalar}`);
      }
    }
  }
});

test('the endpoints are a pure land tax and a pure building tax', () => {
  for (const key of SCENARIOS) {
    const { totals, parcels } = fixture.scenarios[key];
    const landOnly = solve.solveMillages(totals, 1);
    const buildingOnly = solve.solveMillages(totals, 0);
    assert.equal(landOnly.impMillage, 0, `${key}: land-only leaves a building millage`);
    assert.equal(buildingOnly.landMillage, 0, `${key}: building-only leaves a land millage`);

    for (const parcel of parcels) {
      for (const m of [landOnly, buildingOnly]) {
        const tax = solve.parcelTax(parcel.l, parcel.i, m.landMillage, m.impMillage);
        assert.ok(Number.isFinite(tax) && tax >= 0,
          `${key} pid ${parcel.pid}: endpoint tax was ${tax}`);
      }
    }
  }
});

test('revenue neutrality holds across the whole slider', () => {
  // Rates are solved against the scenario totals, so summing the two legs back
  // over those totals must return the revenue target at any land share.
  for (const key of SCENARIOS) {
    const { totals } = fixture.scenarios[key];
    for (const share of [0, 0.25, 0.5, 0.75, 1]) {
      const m = solve.solveMillages(totals, share);
      const raised =
        (totals.sumLand * m.landMillage) / 1000 + (totals.sumImp * m.impMillage) / 1000;
      assertClose(raised, totals.revenue, 1e-9, `${key} @${share} revenue neutrality`);
    }
  }
});

test('OPA record links are zero-padded to nine digits', () => {
  const template = 'https://property.phila.gov/?p={pid9}';
  // ?p=011001000 resolves; ?p=11001000 returns a plausible-looking "No account
  // found" page rather than an error, so an unpadded link ships broken silently.
  assert.equal(solve.opaRecordUrl(template, 11001000), 'https://property.phila.gov/?p=011001000');
  assert.equal(solve.opaRecordUrl(template, 881000395), 'https://property.phila.gov/?p=881000395');

  for (const key of SCENARIOS) {
    for (const parcel of fixture.scenarios[key].parcels) {
      const url = solve.opaRecordUrl(template, parcel.pid);
      assert.match(url, /\?p=\d{9}$/, `pid ${parcel.pid} produced ${url}`);
    }
  }
});

test('statsAt is exact on the grid knots', () => {
  const curvePath = resolve(WEBMAP_SRC, 'manifest.json');
  let manifest;
  try {
    manifest = JSON.parse(readFileSync(curvePath, 'utf8'));
  } catch {
    return; // manifest is a build artifact; skip when the site has not been built
  }
  const curve = manifest.stat_curve;
  for (const key of Object.keys(curve.by_scenario)) {
    const rows = curve.by_scenario[key];
    curve.land_share_grid.forEach((share, index) => {
      const stats = solve.statsAt(curve, key, share);
      if (rows.median_pct[index] === null) return;
      assertClose(stats.medianPct, rows.median_pct[index], 1e-9, `${key} knot ${share} median`);
    });
  }
});

function assertClose(actual, expected, tolerance, label) {
  assert.ok(
    Number.isFinite(actual) === Number.isFinite(expected),
    `${label}: finiteness differs (${actual} vs ${expected})`,
  );
  const scale = Math.max(1, Math.abs(expected));
  const diff = Math.abs(actual - expected);
  assert.ok(
    diff / scale <= tolerance,
    `${label}: ${actual} != ${expected} (relative diff ${diff / scale}, tolerance ${tolerance})`,
  );
}
