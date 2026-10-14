import assert from "node:assert/strict";
import test from "node:test";

import { toCanonical } from "../src/lib/decimal.ts";
import { averagePerTrade, dayStats, percentSteps } from "../src/lib/summary.ts";

const days = [
  { date: "2035-03-01", pnl: "0.1" },
  { date: "2035-03-02", pnl: "-12.5" },
  { date: "2035-03-03", pnl: "27.8" },
  { date: "2035-03-04", pnl: "0.2" },
];

test("finds the extremes and the scale of a month", () => {
  const stats = dayStats(days);
  assert.equal(stats.best?.date, "2035-03-03");
  assert.equal(toCanonical(stats.best?.pnl ?? 0n), "27.8");
  assert.equal(stats.worst?.date, "2035-03-02");
  assert.equal(toCanonical(stats.worst?.pnl ?? 0n), "-12.5");
  assert.equal(toCanonical(stats.maxGain), "27.8");
  assert.equal(toCanonical(stats.maxLoss), "12.5");
  assert.equal(toCanonical(stats.maxAbs), "27.8");
});

test("the net is an exact sum", () => {
  assert.equal(toCanonical(dayStats(days).net), "15.6"); // 0.1 - 12.5 + 27.8 + 0.2
  assert.equal(toCanonical(dayStats([{ date: "a", pnl: "0.1" }, { date: "b", pnl: "0.2" }]).net), "0.3");
});

test("a month of losses still has a best and a worst day, and no gain scale", () => {
  const stats = dayStats([{ date: "a", pnl: "-3" }, { date: "b", pnl: "-1" }]);
  assert.equal(stats.best?.date, "b");
  assert.equal(stats.worst?.date, "a");
  assert.equal(stats.maxGain, 0n);
  assert.equal(toCanonical(stats.maxAbs), "3");
});

test("an empty month has no extremes", () => {
  const stats = dayStats([]);
  assert.deepEqual([stats.best, stats.worst, stats.net, stats.maxAbs], [null, null, 0n, 0n]);
});

test("averages divide exactly and need at least one trade", () => {
  assert.equal(toCanonical(averagePerTrade(15_60_000_000n, 4) ?? 0n), "3.9"); // 15.6 / 4
  assert.equal(averagePerTrade(0n, 0), null);
  assert.equal(toCanonical(averagePerTrade(1_00_000_000n, 3) ?? 0n), "0.33333333");
});

test("percent steps round to whole numbers", () => {
  assert.equal(percentSteps(2, 3), 67);
  assert.equal(percentSteps(1, 2), 50);
  assert.equal(percentSteps(0, 5), 0);
  assert.equal(percentSteps(5, 5), 100);
  assert.equal(percentSteps(3, 0), 0);
});
