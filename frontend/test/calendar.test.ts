import assert from "node:assert/strict";
import test from "node:test";

import { addDays, dayLabel, daysInMonth, isIsoDay, monthBounds, monthGrid, monthKey, monthLabel, monthOf, parseMonth, shiftMonth, weekdayIndex } from "../src/lib/calendar.ts";

// Weekdays below were checked against Python's datetime (Monday is 0).
test("knows weekdays and month lengths", () => {
  assert.equal(weekdayIndex("2035-03-01"), 3); // Thursday
  assert.equal(weekdayIndex("2035-03-10"), 5); // Saturday
  assert.equal(weekdayIndex("2035-10-01"), 0); // Monday
  assert.equal(daysInMonth({ year: 2035, month: 2 }), 28);
  assert.equal(daysInMonth({ year: 2036, month: 2 }), 29);
  assert.equal(daysInMonth({ year: 2100, month: 2 }), 28); // not a leap year
  assert.equal(daysInMonth({ year: 2035, month: 12 }), 31);
});

test("builds a Monday-first grid padded with nulls", () => {
  const weeks = monthGrid({ year: 2035, month: 3 });
  assert.ok(weeks.every((week) => week.length === 7));
  assert.deepEqual(weeks[0], [null, null, null, "2035-03-01", "2035-03-02", "2035-03-03", "2035-03-04"]);
  assert.deepEqual(weeks.at(-1), ["2035-03-26", "2035-03-27", "2035-03-28", "2035-03-29", "2035-03-30", "2035-03-31", null]);
  assert.equal(weeks.flat().filter(Boolean).length, 31);
  assert.equal(weeks.length, 5);
  // October 2035 starts on a Monday, so the first row has no padding.
  assert.equal(monthGrid({ year: 2035, month: 10 })[0]?.[0], "2035-10-01");
  // December 2035 starts on a Saturday and spills into a sixth row.
  assert.equal(monthGrid({ year: 2035, month: 12 }).length, 6);
});

test("moves between months across year boundaries", () => {
  assert.deepEqual(shiftMonth({ year: 2035, month: 12 }, 1), { year: 2036, month: 1 });
  assert.deepEqual(shiftMonth({ year: 2035, month: 1 }, -1), { year: 2034, month: 12 });
  assert.deepEqual(shiftMonth({ year: 2035, month: 6 }, 18), { year: 2036, month: 12 });
  assert.deepEqual(shiftMonth({ year: 2035, month: 6 }, -6), { year: 2034, month: 12 });
});

test("parses and prints month and day text", () => {
  assert.deepEqual(parseMonth("2035-03"), { year: 2035, month: 3 });
  for (const bad of [undefined, "", "2035-3", "2035-13", "2035-00", "1900-01", "March"]) assert.equal(parseMonth(bad), null, String(bad));
  assert.equal(monthKey({ year: 2035, month: 3 }), "2035-03");
  assert.deepEqual(monthOf("2035-03-10"), { year: 2035, month: 3 });
  assert.equal(monthLabel({ year: 2035, month: 3 }), "March 2035");
  assert.equal(dayLabel("2035-03-10"), "Sat, Mar 10, 2035");
  assert.deepEqual(monthBounds({ year: 2036, month: 2 }), { from: "2036-02-01", to: "2036-02-29" });
});

test("validates ISO days and adds days across month ends", () => {
  assert.ok(isIsoDay("2035-02-28"));
  assert.ok(!isIsoDay("2035-02-29"));
  assert.ok(!isIsoDay("2035-2-28"));
  assert.ok(!isIsoDay(undefined));
  assert.equal(addDays("2035-02-28", 1), "2035-03-01");
  assert.equal(addDays("2035-01-01", -1), "2034-12-31");
  assert.equal(addDays("2036-02-28", 1), "2036-02-29");
});
