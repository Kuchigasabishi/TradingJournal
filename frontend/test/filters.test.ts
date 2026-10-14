import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_FILTERS, parseFilters, toApiQuery, toParams } from "../src/lib/filters.ts";

test("an empty address means the default view", () => {
  assert.deepEqual(parseFilters({}), DEFAULT_FILTERS);
  assert.deepEqual(toParams(DEFAULT_FILTERS), {});
});

test("reads every filter from the address", () => {
  const filters = parseFilters({ status: "open", instrument: " eurusd ", side: "short", tag: ["a", "b"], from: "2035-03-01", to: "2035-03-31", sort: "pnl", order: "asc", page: "3" });
  assert.deepEqual(filters, { status: "open", instrument: "eurusd", side: "short", tags: ["a", "b"], from: "2035-03-01", to: "2035-03-31", sort: "pnl", order: "asc", page: 3 });
});

test("ignores values it does not understand instead of failing", () => {
  const filters = parseFilters({ status: "weird", side: "up", sort: "colour", order: "sideways", from: "yesterday", to: "2035-13-45x", page: "-2", tag: "" });
  assert.deepEqual(filters, DEFAULT_FILTERS);
  assert.equal(parseFilters({ page: "abc" }).page, 1);
  assert.equal(parseFilters({ page: "2.5" }).page, 1);
});

test("a single tag in the address is still a list", () => {
  assert.deepEqual(parseFilters({ tag: "breakout" }).tags, ["breakout"]);
});

test("two tags written as one comma-joined value, the way the router writes a list, are two tags", () => {
  assert.deepEqual(parseFilters({ tag: "breakout,news" }).tags, ["breakout", "news"]);
  assert.deepEqual(parseFilters({ tag: ["breakout,news", "range"] }).tags, ["breakout", "news", "range"]);
  assert.deepEqual(parseFilters({ tag: "a,,b," }).tags, ["a", "b"]); // stray commas leave no empty tag
});

test("writes only what differs from the defaults, and round-trips", () => {
  const filters = parseFilters({ status: "closed", tag: ["x", "y"], sort: "opened_at", page: "2" });
  assert.deepEqual(toParams(filters), { status: "closed", tag: ["x", "y"], sort: "opened_at", page: "2" });
  assert.deepEqual(parseFilters(toParams(filters)), filters);
});

test("turns a filter set into the API query for one page", () => {
  const query = toApiQuery(parseFilters({ status: "open", page: "3", tag: ["a"] }), 25);
  assert.deepEqual(query, { status: "open", instrument: undefined, side: undefined, tag: ["a"], from: undefined, to: undefined, sort: "journal_at", order: "desc", limit: 25, offset: 50 });
  assert.equal(toApiQuery(DEFAULT_FILTERS, 25).tag, undefined);
  assert.equal(toApiQuery(DEFAULT_FILTERS, 25).offset, 0);
});
