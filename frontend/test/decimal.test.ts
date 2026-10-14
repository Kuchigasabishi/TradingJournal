import assert from "node:assert/strict";
import test from "node:test";

import * as D from "../src/lib/decimal.ts";

const d = (text: string): bigint => {
  const value = D.parse(text);
  assert.notEqual(value, null, `parse(${JSON.stringify(text)})`);
  return value as bigint;
};

test("whole numbers are grouped without a locale", () => {
  assert.equal(D.groupDigits(10_000), "10,000");
  assert.equal(D.groupDigits(999), "999");
  assert.equal(D.groupDigits(1_234_567), "1,234,567");
  assert.equal(D.groupDigits(0), "0");
});

test("parses and prints canonical decimals exactly", () => {
  const cases: [string, string][] = [
    ["1.10", "1.1"],
    ["0.00000001", "0.00000001"],
    ["-0.00000001", "-0.00000001"],
    ["100", "100"],
    ["+5.", "5"],
    [".5", "0.5"],
    ["0", "0"],
    ["-0", "0"],
    ["9999999999.99999999", "9999999999.99999999"],
    ["007.500", "7.5"],
  ];
  for (const [text, canonical] of cases) assert.equal(D.toCanonical(d(text)), canonical, text);
});

test("rejects anything that is not an exact decimal with at most 8 places", () => {
  for (const bad of ["", ".", "abc", "1e3", "1,5", "--1", "1.123456789", "1 2", "NaN"]) assert.equal(D.parse(bad), null, JSON.stringify(bad));
});

test("sums are exact where floating point is not", () => {
  assert.notEqual(0.1 + 0.2, 0.3); // the reason this module exists
  assert.equal(D.toCanonical(D.sum([d("0.1"), d("0.2")])), "0.3");
  assert.equal(D.toCanonical(D.sum(Array.from({ length: 10 }, () => d("0.1")))), "1");
  assert.equal(D.toCanonical(D.sum([d("9999999999.99999999"), d("0.00000001")])), "10000000000");
  assert.equal(D.sum([]), 0n);
});

test("formats with grouping, minimum and maximum fraction digits", () => {
  const cases: [string, D.FormatOptions, string][] = [
    ["1234567.891", { minFraction: 2, grouping: true }, "1,234,567.891"],
    ["27.8", { minFraction: 2, maxFraction: 8, grouping: true }, "27.80"],
    ["-0.00000001", { minFraction: 2, maxFraction: 8 }, "-0.00000001"],
    ["9999999999.99999999", { minFraction: 2, grouping: true }, "9,999,999,999.99999999"],
    ["0", { minFraction: 2 }, "0.00"],
    ["1000", { grouping: true }, "1,000"],
    ["999", { grouping: true }, "999"],
    ["1234.5", { minFraction: 0, grouping: false }, "1234.5"],
  ];
  for (const [text, options, expected] of cases) assert.equal(D.format(d(text), options), expected, `${text} ${JSON.stringify(options)}`);
});

test("rounds exactly, half away from zero, and a value that rounds to zero carries no sign", () => {
  const two = { minFraction: 2, maxFraction: 2 };
  assert.equal(D.format(d("1.005"), two), "1.01"); // 1.005 is not exactly representable as a float; here it is
  assert.equal(D.format(d("-1.005"), two), "-1.01");
  assert.equal(D.format(d("0.994"), two), "0.99");
  assert.equal(D.format(d("2.5"), { maxFraction: 0 }), "3");
  assert.equal(D.format(d("-2.5"), { maxFraction: 0 }), "-3");
  assert.equal(D.format(d("-0.004"), two), "0.00");
});

test("divides with exact rounding", () => {
  assert.equal(D.toCanonical(D.divideRound(d("10"), 3n)), "3.33333333");
  assert.equal(D.toCanonical(D.divideRound(d("-10"), 3n)), "-3.33333333");
  assert.equal(D.toCanonical(D.divideRound(d("0.00000005"), 2n)), "0.00000003"); // 2.5 units, half away from zero
  assert.equal(D.toCanonical(D.divideRound(d("1.5"), 2n)), "0.75");
  assert.throws(() => D.divideRound(d("1"), 0n), RangeError);
});

test("percentages are integer arithmetic", () => {
  assert.equal(D.percent(2, 3), "66.7");
  assert.equal(D.percent(1, 8), "12.5");
  assert.equal(D.percent(5, 5), "100.0");
  assert.equal(D.percent(0, 4), "0.0");
  assert.equal(D.percent(1, 3, 0), "33");
  assert.equal(D.percent(2, 3, 2), "66.67");
  assert.equal(D.percent(0, 0), null);
});

test("sizes bars and shades in whole steps relative to the maximum", () => {
  assert.equal(D.toSteps(d("-50"), d("100"), 4), 2);
  assert.equal(D.toSteps(d("1"), d("100"), 4), 0);
  assert.equal(D.toSteps(d("13"), d("100"), 4), 1);
  assert.equal(D.toSteps(d("100"), d("100"), 4), 4);
  assert.equal(D.toSteps(d("5"), 0n, 4), 0);
});

test("sign, abs and compare", () => {
  assert.deepEqual([D.sign(d("-1")), D.sign(d("0")), D.sign(d("0.00000001"))], [-1, 0, 1]);
  assert.equal(D.abs(d("-3.5")), d("3.5"));
  assert.deepEqual([D.compare(d("1"), d("2")), D.compare(d("2"), d("2")), D.compare(d("3"), d("2"))], [-1, 0, 1]);
});
