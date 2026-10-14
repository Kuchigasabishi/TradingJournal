import assert from "node:assert/strict";
import test from "node:test";

import * as D from "../src/lib/decimal.ts";
import { formatMoney, formatMoneyDec, formatPrice, formatPriceSet, formatQuantity, plainDecimal, pricePlaces, toneOf } from "../src/lib/money.ts";

test("currency formatting is exact and never rounds a real value away", () => {
  const cases: [string | null, string, boolean, string][] = [
    ["27.8", "USD", false, "$27.80"],
    ["27.8", "USD", true, "+$27.80"],
    ["-12.3", "USD", true, "-$12.30"],
    ["-12.3", "USD", false, "-$12.30"],
    ["0", "USD", true, "$0.00"],
    ["1234567.5", "EUR", false, "€1,234,567.50"],
    ["-0.00000001", "USD", false, "-$0.00000001"],
    ["9999999999.99999999", "USD", false, "$9,999,999,999.99999999"],
    ["1500", "JPY", false, "¥1,500"],
    ["1500.5", "JPY", false, "¥1,500.5"],
    ["12.3", "CAD", false, "C$12.30"],
    ["12.3", "XYZ", false, "XYZ 12.30"],
    [null, "USD", false, "–"],
  ];
  for (const [value, currency, signed, expected] of cases) assert.equal(formatMoney(value, currency, signed), expected, `${value} ${currency}`);
});

test("text that is not a decimal passes through untouched", () => {
  assert.equal(formatMoney("n/a", "USD"), "n/a");
  assert.equal(formatQuantity("n/a"), "n/a");
});

test("sums of formatted values stay exact", () => {
  const total = D.sum(["0.1", "0.2", "0.3"].map((text) => D.parse(text) as bigint));
  assert.equal(formatMoneyDec(total, "USD"), "$0.60");
});

test("lot sizes and prices show at least two decimals and as many as eight", () => {
  const cases: [string, string][] = [
    ["0.1", "0.10"],
    ["100000", "100,000.00"],
    ["1.08543", "1.08543"],
    ["0.00000001", "0.00000001"],
    ["150", "150.00"],
  ];
  for (const [value, expected] of cases) assert.equal(formatQuantity(value), expected, value);
  assert.equal(formatQuantity(null), "–");
});

test("derived figures round to the cent without inventing a sign", () => {
  const cases: [string, number, string][] = [
    ["7.76583333", 2, "+$7.77"],
    ["-7.765", 2, "-$7.77"], // half rounds away from zero
    ["0.004", 2, "$0.00"], // rounds to zero: no sign
    ["-0.004", 2, "$0.00"],
    ["0.005", 2, "+$0.01"],
  ];
  for (const [text, places, expected] of cases) assert.equal(formatMoneyDec(D.parse(text) as bigint, "USD", true, places), expected, text);
  assert.equal(formatMoneyDec(D.parse("1500.4") as bigint, "JPY", false, 0), "¥1,500");
});

test("prices of one trade share a decimal count and nothing is rounded", () => {
  assert.deepEqual(formatPriceSet(["1.274", "1.2728"]), ["1.2740", "1.2728"]);
  assert.deepEqual(formatPriceSet(["1.08425", "1.0871"]), ["1.08425", "1.08710"]);
  assert.deepEqual(formatPriceSet(["150.1", "149.9"]), ["150.10", "149.90"]);
  assert.deepEqual(formatPriceSet(["2650.5", null]), ["2,650.50", "–"]);
  assert.deepEqual(formatPriceSet(["0.00000001", "1"]), ["0.00000001", "1.00000000"]);
  assert.deepEqual(formatPriceSet(["1234.5", "1.25"], { grouping: false }), ["1234.50", "1.25"]);
  assert.deepEqual(formatPriceSet(["n/a", "1.5"]), ["n/a", "1.50"]);
});

test("prices of one instrument can share precision across rows", () => {
  const places = pricePlaces(["1.08425", "1.0871", "1.081", null]);
  assert.equal(places, 5);
  assert.deepEqual(["1.081", "1.0871", null].map((text) => formatPrice(text, places)), ["1.08100", "1.08710", "–"]);
  assert.equal(formatPrice("1.234567", 2), "1.234567"); // more decimals than asked for are kept
  assert.equal(pricePlaces([]), 2);
});

test("input boxes get plain padded decimals", () => {
  assert.equal(plainDecimal("28.5"), "28.50");
  assert.equal(plainDecimal("0.1"), "0.10");
  assert.equal(plainDecimal("-12"), "-12.00");
  assert.equal(plainDecimal("1234.56789"), "1234.56789");
  assert.equal(plainDecimal(null), "");
});

test("tone follows the exact sign", () => {
  assert.equal(toneOf(D.parse("0.00000001") as bigint), "gain");
  assert.equal(toneOf(D.parse("-0.00000001") as bigint), "loss");
  assert.equal(toneOf(0n), "flat");
});
