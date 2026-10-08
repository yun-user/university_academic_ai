import assert from "node:assert/strict";
import test from "node:test";
import { maxSemesters, resizeSemesters } from "../src/planOptions.ts";

const options = { start_year: 2027, start_term: 1, semesters: 3, credit_limit: 18,
  excluded_codes: ["EXCLUDED"], assume_in_progress_passed: false, semester_limits: [15, 0, 9] };

test("adding successive semesters preserves custom limits and break semesters", () => {
  const original = structuredClone(options);
  const next = resizeSemesters(resizeSemesters(options, 4), 5);
  assert.equal(next.semesters, 5);
  assert.deepEqual(next.semester_limits, [15, 0, 9, 18, 18]);
  assert.deepEqual(next.excluded_codes, ["EXCLUDED"]);
  assert.deepEqual(options, original);
});

test("uniform limits remain uniform and trimming retains earlier custom limits", () => {
  assert.deepEqual(resizeSemesters({ ...options, semester_limits: [] }, 4).semester_limits, []);
  assert.deepEqual(resizeSemesters(options, 2).semester_limits, [15, 0]);
});

test("semester addition respects both twelve semesters and the end of 2100", () => {
  assert.equal(maxSemesters(options), 12);
  assert.equal(maxSemesters({ ...options, start_year: 2099, start_term: 2 }), 3);
  assert.equal(maxSemesters({ ...options, start_year: 2100 }), 2);
  assert.equal(maxSemesters({ ...options, start_year: 2100, start_term: 2 }), 1);
});

test("invalid start dates cannot enable the add button", () => {
  for (const start_year of [2017, 2101, NaN, 2027.5])
    assert.equal(maxSemesters({ ...options, start_year }), 0);
  assert.equal(maxSemesters({ ...options, start_term: 3 }), 0);
});
