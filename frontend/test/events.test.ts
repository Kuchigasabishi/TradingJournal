import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_EVENT_FILTERS,
  type EventLike,
  applyEventFilters,
  compareWithinDay,
  currenciesOf,
  dayEventsPhrases,
  daysCovered,
  eventQuery,
  eventTimeText,
  groupByDay,
  impactLabel,
  isFiltered,
  newsBreakdown,
  parseEventFilters,
  safeHttpUrl,
  summarizeDay,
  toEventParams,
} from "../src/lib/events.ts";

const NEW_YORK = "America/New_York";

let nextId = 1;
const news = (title: string, impact: EventLike["impact"], currency: string, startAt: string, day: string): EventLike => ({
  id: nextId++, source: "forexfactory", title, all_day: false, start_at: startAt, end_at: null, start_day: day, end_day: day, impact, currency,
});
const personal = (title: string, startAt: string | null, endAt: string | null, startDay: string, endDay = startDay): EventLike => ({
  id: nextId++, source: "gcal", title, all_day: startAt === null, start_at: startAt, end_at: endAt, start_day: startDay, end_day: endDay, impact: null, currency: null,
});

// Times below were worked out with Python's zoneinfo (an independent implementation of the tz database).
const CPI = news("CPI m/m", "high", "USD", "2044-05-11T12:30:00Z", "2044-05-11"); // 08:30 in New York
const EMPLOYMENT = news("Employment Change", "high", "AUD", "2044-05-12T00:30:00Z", "2044-05-11"); // 20:30 on the 11th
const BAILEY = news("BOE Gov Bailey Speaks", "medium", "GBP", "2044-05-12T07:30:00Z", "2044-05-12");
const BREEDEN = news("MPC Member Breeden Speaks", "low", "GBP", "2044-05-09T09:30:00Z", "2044-05-09");
const IMF = news("IMF Meetings", "low", "ALL", "2044-05-09T14:15:00Z", "2044-05-09");
const HOLIDAY = news("Bank Holiday", "holiday", "USD", "2044-05-09T11:00:00Z", "2044-05-09");
const ASIA = personal("Asia session review", "2044-05-13T02:00:00Z", "2044-05-13T06:00:00Z", "2044-05-12", "2044-05-13"); // 22:00 to 02:00
const COURSE = personal("Trading course", null, null, "2044-05-18", "2044-05-20");
const DAY_OFF = personal("Bank day off", null, null, "2044-05-12");
const DINNER = personal("Floating dinner", "2044-05-12T22:00:00Z", "2044-05-12T23:00:00Z", "2044-05-12");
const ALL_EVENTS = [CPI, EMPLOYMENT, BAILEY, BREEDEN, IMF, HOLIDAY, ASIA, COURSE, DAY_OFF, DINNER];

test("an event covers each of its days, clipped to the range asked about", () => {
  assert.deepEqual(daysCovered(CPI, "2044-05-01", "2044-05-31"), ["2044-05-11"]);
  assert.deepEqual(daysCovered(COURSE, "2044-05-01", "2044-05-31"), ["2044-05-18", "2044-05-19", "2044-05-20"]);
  assert.deepEqual(daysCovered(COURSE, "2044-05-19", "2044-05-31"), ["2044-05-19", "2044-05-20"]);
  assert.deepEqual(daysCovered(COURSE, "2044-05-01", "2044-05-18"), ["2044-05-18"]);
  assert.deepEqual(daysCovered(COURSE, "2044-06-01", "2044-06-30"), []);
  assert.deepEqual(daysCovered(COURSE, "2044-04-01", "2044-04-30"), []);
  assert.deepEqual(daysCovered(ASIA, "2044-05-12", "2044-05-13"), ["2044-05-12", "2044-05-13"]);
});

test("groups events by day, a multi-day event under every day, each day in reading order", () => {
  const byDay = groupByDay(ALL_EVENTS, "2044-05-01", "2044-05-31");
  assert.deepEqual([...byDay.keys()].sort(), ["2044-05-09", "2044-05-11", "2044-05-12", "2044-05-13", "2044-05-18", "2044-05-19", "2044-05-20"]);
  // The 12th: the all-day event first, then by time: Bailey at 03:30 (07:30 UTC), the dinner at 18:00, the review at 22:00.
  assert.deepEqual(byDay.get("2044-05-12")?.map((event) => event.title), ["Bank day off", "BOE Gov Bailey Speaks", "Floating dinner", "Asia session review"]);
  assert.deepEqual(byDay.get("2044-05-13")?.map((event) => event.title), ["Asia session review"]);
  assert.deepEqual(byDay.get("2044-05-19")?.map((event) => event.title), ["Trading course"]);
  assert.equal(byDay.get("2044-05-11")?.length, 2); // CPI, and the AUD release that is 00:30 UTC on the 12th but 20:30 on the 11th in New York
  assert.deepEqual(groupByDay(ALL_EVENTS, "2044-06-01", "2044-06-30").size, 0);
});

test("at the same moment a personal event comes before news, and ties fall back to the title", () => {
  const a = news("A", "low", "USD", "2044-05-12T12:00:00Z", "2044-05-12");
  const b = personal("B", "2044-05-12T12:00:00Z", null, "2044-05-12");
  const c = news("C", "low", "USD", "2044-05-12T12:00:00Z", "2044-05-12");
  assert.deepEqual([c, a, b].sort(compareWithinDay).map((event) => event.title), ["B", "A", "C"]);
});

test("adds a day's events up by impact and keeps the personal titles", () => {
  const day = summarizeDay([CPI, EMPLOYMENT, BAILEY, IMF, HOLIDAY, DAY_OFF, DINNER]);
  assert.deepEqual(day.news, { high: 2, medium: 1, low: 1, holiday: 1, unknown: 0, total: 5 });
  assert.equal(day.personal, 2);
  assert.deepEqual(day.titles, ["Bank day off", "Floating dinner"]);
  assert.equal(day.top, "high");
  assert.deepEqual(summarizeDay([]), { news: { high: 0, medium: 0, low: 0, holiday: 0, unknown: 0, total: 0 }, personal: 0, titles: [], top: null });
});

test("the top impact ignores holidays unless they are all there is, and counts impacts nobody knows", () => {
  assert.equal(summarizeDay([HOLIDAY]).top, "holiday");
  assert.equal(summarizeDay([HOLIDAY, BREEDEN]).top, "low");
  const odd = news("Odd", null, "USD", "2044-05-12T12:00:00Z", "2044-05-12");
  assert.equal(summarizeDay([odd, HOLIDAY]).top, "unknown");
  assert.equal(summarizeDay([odd]).news.unknown, 1);
});

test("describes a day in words", () => {
  const day = summarizeDay([CPI, EMPLOYMENT, BAILEY, IMF, HOLIDAY, DAY_OFF, DINNER]);
  assert.equal(newsBreakdown(day.news), "2 high, 1 medium, 1 low, 1 holiday");
  assert.deepEqual(dayEventsPhrases(day), ["5 news events (2 high, 1 medium, 1 low, 1 holiday)", "2 personal events"]);
  assert.deepEqual(dayEventsPhrases(summarizeDay([BAILEY])), ["1 news event (1 medium)"]);
  assert.deepEqual(dayEventsPhrases(summarizeDay([DAY_OFF])), ["1 personal event"]);
  assert.deepEqual(dayEventsPhrases(summarizeDay([])), []);
  assert.equal(impactLabel("high"), "High impact");
  assert.equal(impactLabel("holiday"), "Holiday");
  assert.equal(impactLabel("unknown"), "Impact unknown");
});

test("filters live in the address and unset ones are left out", () => {
  assert.deepEqual(parseEventFilters({}), DEFAULT_EVENT_FILTERS);
  assert.deepEqual(toEventParams(DEFAULT_EVENT_FILTERS), {});
  const filters = parseEventFilters({ show: "news", impact: ["low", "high"], currency: " usd " });
  assert.deepEqual(filters, { show: "news", impacts: ["high", "low"], currency: "USD" }); // levels come back in their usual order
  assert.deepEqual(toEventParams(filters), { show: "news", impact: ["high", "low"], currency: "USD" });
  assert.deepEqual(parseEventFilters(toEventParams(filters)), filters);
  assert.equal(parseEventFilters({ impact: "medium" }).impacts[0], "medium"); // a single value is still a list
  assert.equal(isFiltered(DEFAULT_EVENT_FILTERS), false);
  assert.equal(isFiltered(filters), true);
});

test("levels written as one comma-joined value, the way the router writes a list, are several levels", () => {
  assert.deepEqual(parseEventFilters({ impact: "medium,high" }).impacts, ["high", "medium"]);
  assert.deepEqual(parseEventFilters({ impact: ["low,holiday", "high"] }).impacts, ["high", "low", "holiday"]);
  assert.equal(eventQuery({ show: "news", impacts: ["high", "medium"], currency: "USD" }), "?show=news&impact=high&impact=medium&currency=USD");
  assert.equal(eventQuery(DEFAULT_EVENT_FILTERS), "");
});

test("only http and https addresses from a feed are ever opened", () => {
  assert.equal(safeHttpUrl("https://www.forexfactory.com/calendar/1-us-cpi"), "https://www.forexfactory.com/calendar/1-us-cpi");
  assert.equal(safeHttpUrl("  http://example.com/a  "), "http://example.com/a");
  for (const bad of ["javascript:alert(1)", "JAVASCRIPT:alert(1)", "data:text/html,hi", "file:///etc/passwd", "ftp://example.com", "not an address", "https://", "http://exa mple.com", 'https://example.com/"><script>', "", "   ", null, undefined]) assert.equal(safeHttpUrl(bad), null, String(bad));
  assert.equal(safeHttpUrl("HTTPS://Example.com/Path?a=1&b=2#top"), "HTTPS://Example.com/Path?a=1&b=2#top"); // kept as written: only the scheme matters here
});

test("ignores what it does not understand instead of failing", () => {
  assert.deepEqual(parseEventFilters({ show: "everything", impact: ["urgent", "unknown", ""], currency: "U$D" }), DEFAULT_EVENT_FILTERS);
  assert.equal(parseEventFilters({ currency: "" }).currency, undefined);
  assert.equal(parseEventFilters({ currency: "A" }).currency, undefined);
});

test("show narrows to news or to personal events", () => {
  assert.equal(applyEventFilters(ALL_EVENTS, { show: "news", impacts: [] }).every((event) => event.source === "forexfactory"), true);
  assert.equal(applyEventFilters(ALL_EVENTS, { show: "personal", impacts: [] }).every((event) => event.source === "gcal"), true);
  assert.equal(applyEventFilters(ALL_EVENTS, DEFAULT_EVENT_FILTERS).length, ALL_EVENTS.length);
});

test("impact and currency narrow the news and leave personal events alone", () => {
  const high = applyEventFilters(ALL_EVENTS, { show: "all", impacts: ["high"] });
  assert.deepEqual(high.map((event) => event.title).sort(), ["Asia session review", "Bank day off", "CPI m/m", "Employment Change", "Floating dinner", "Trading course"]);
  const two = applyEventFilters(ALL_EVENTS, { show: "news", impacts: ["medium", "holiday"] });
  assert.deepEqual(two.map((event) => event.title).sort(), ["BOE Gov Bailey Speaks", "Bank Holiday"]);
  // News for every currency (ALL) concerns every currency.
  const gbp = applyEventFilters(ALL_EVENTS, { show: "news", impacts: [], currency: "GBP" });
  assert.deepEqual(gbp.map((event) => event.title).sort(), ["BOE Gov Bailey Speaks", "IMF Meetings", "MPC Member Breeden Speaks"]);
  const odd = news("Odd", null, "USD", "2044-05-12T12:00:00Z", "2044-05-12");
  assert.equal(applyEventFilters([odd], { show: "all", impacts: ["high"] }).length, 0);
  assert.equal(applyEventFilters([odd], DEFAULT_EVENT_FILTERS).length, 1);
});

test("lists the currencies the news mentions, without ALL", () => {
  assert.deepEqual(currenciesOf(ALL_EVENTS), ["AUD", "GBP", "USD"]);
  assert.deepEqual(currenciesOf([DAY_OFF]), []);
});

test("writes times in the server's zone", () => {
  assert.equal(eventTimeText(CPI, NEW_YORK), "08:30");
  assert.equal(eventTimeText(EMPLOYMENT, NEW_YORK), "20:30"); // the 11th, though 00:30 UTC is already the 12th
  assert.equal(eventTimeText(DINNER, NEW_YORK), "18:00–19:00");
  assert.equal(eventTimeText(ASIA, NEW_YORK), "May 12 22:00 → May 13 02:00");
  assert.equal(eventTimeText(DAY_OFF, NEW_YORK), "All day");
  assert.equal(eventTimeText(COURSE, NEW_YORK), "All day · May 18 to May 20");
  // the same instant in another zone, and either side of the clocks going back in New York (2044-11-06)
  assert.equal(eventTimeText({ ...BAILEY, start_at: "2044-05-11T08:00:00Z" }, "Europe/London"), "09:00");
  assert.equal(eventTimeText({ ...CPI, start_at: "2044-11-07T15:00:00Z" }, NEW_YORK), "10:00");
  assert.equal(eventTimeText({ ...CPI, start_at: "2044-11-05T14:00:00Z" }, NEW_YORK), "10:00");
});
