import assert from "node:assert/strict";
import test from "node:test";

import { dayOf, formatWall, instantToText, isoFromMs, parseWall, textToInstant, todayIn, wallClock } from "../src/lib/time.ts";

const NEW_YORK = "America/New_York";

// Expected values come from Python's zoneinfo, an independent implementation of the same tz database.
const iso = (text: string, zone: string): string => {
  const result = textToInstant(text, zone);
  return result.ok ? result.iso : `error:${result.reason}`;
};

test("converts wall-clock times to UTC across daylight saving", () => {
  const cases: [string, string, string][] = [
    ["2035-01-10 14:30", NEW_YORK, "2035-01-10T19:30:00Z"],
    ["2035-07-10 14:30", NEW_YORK, "2035-07-10T18:30:00Z"],
    ["2035-03-11 01:59", NEW_YORK, "2035-03-11T06:59:00Z"],
    ["2035-03-11 03:00", NEW_YORK, "2035-03-11T07:00:00Z"],
    ["2035-11-04 00:30", NEW_YORK, "2035-11-04T04:30:00Z"],
    ["2035-11-04 02:00", NEW_YORK, "2035-11-04T07:00:00Z"],
    ["2035-06-01 12:00", "Asia/Kolkata", "2035-06-01T06:30:00Z"],
    ["2035-06-01 12:00", "UTC", "2035-06-01T12:00:00Z"],
    ["2035-06-01 12:00", "Europe/London", "2035-06-01T11:00:00Z"],
    ["2035-12-01 12:00", "Europe/London", "2035-12-01T12:00:00Z"],
    ["2035-06-01 12:00", "Pacific/Kiritimati", "2035-05-31T22:00:00Z"],
    ["2035-06-01 12:00", "Pacific/Pago_Pago", "2035-06-01T23:00:00Z"],
    ["2035-04-01 12:00", "Australia/Lord_Howe", "2035-04-01T01:30:00Z"],
  ];
  for (const [text, zone, expected] of cases) assert.equal(iso(text, zone), expected, `${text} ${zone}`);
});

test("a time that clocks skip does not exist", () => {
  assert.equal(iso("2035-03-11 02:30", NEW_YORK), "error:nonexistent");
});

test("a time that happens twice resolves to the earlier instant", () => {
  assert.equal(iso("2035-11-04 01:30", NEW_YORK), "2035-11-04T05:30:00Z");
});

test("round-trips between instants and wall-clock text", () => {
  for (const [instant, expected] of [
    ["2035-01-10T19:30:00Z", "2035-01-10 14:30"],
    ["2035-07-10T18:30:00Z", "2035-07-10 14:30"],
    ["2035-03-10T04:59:59Z", "2035-03-09 23:59"],
    ["2035-03-10T05:00:00Z", "2035-03-10 00:00"],
  ] as const) {
    assert.equal(instantToText(instant, NEW_YORK), expected, instant);
  }
  const typed = "2035-07-10 14:30";
  const result = textToInstant(typed, NEW_YORK);
  assert.ok(result.ok);
  assert.equal(instantToText(result.iso, NEW_YORK), typed);
});

test("buckets an instant into the zone's calendar day, as the server does", () => {
  assert.equal(dayOf("2035-01-16T04:59:59Z", NEW_YORK), "2035-01-15"); // 23:59:59 in New York
  assert.equal(dayOf("2035-01-16T05:00:00Z", NEW_YORK), "2035-01-16");
  assert.equal(dayOf("2035-07-16T03:59:59Z", NEW_YORK), "2035-07-15"); // summer offset is one hour smaller
  assert.equal(dayOf("2035-07-16T04:00:00Z", NEW_YORK), "2035-07-16");
  assert.equal(todayIn(NEW_YORK, Date.parse("2035-03-10T04:59:59Z")), "2035-03-09");
});

test("parses typed wall-clock text strictly", () => {
  assert.deepEqual(parseWall("2035-03-10 14:30"), { year: 2035, month: 3, day: 10, hour: 14, minute: 30, second: 0 });
  assert.deepEqual(parseWall("2035-03-10T14:30:15"), { year: 2035, month: 3, day: 10, hour: 14, minute: 30, second: 15 });
  for (const bad of ["", "2035-03-10", "2035-3-10 14:30", "2035-02-30 10:00", "2035-13-01 10:00", "2035-03-10 24:00", "2035-03-10 14:60", "10/03/2035 14:30"]) {
    assert.equal(parseWall(bad), null, JSON.stringify(bad));
  }
  assert.equal(iso("garbage", NEW_YORK), "error:format");
});

test("formats a wall clock and an instant as ISO text", () => {
  assert.equal(formatWall({ year: 2035, month: 3, day: 9, hour: 7, minute: 5, second: 0 }), "2035-03-09 07:05");
  assert.equal(isoFromMs(Date.UTC(2035, 0, 1, 0, 0, 0)), "2035-01-01T00:00:00Z");
  assert.deepEqual(wallClock(Date.UTC(2035, 0, 1, 5, 0, 0), NEW_YORK), { year: 2035, month: 1, day: 1, hour: 0, minute: 0, second: 0 });
});
