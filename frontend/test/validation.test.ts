import assert from "node:assert/strict";
import test from "node:test";

import { type TradeFormValues, checkDecimal, dedupeTags, diffPayload, fieldsFromDetail, validateTrade } from "../src/lib/validation.ts";

const NEW_YORK = "America/New_York";

const closed: TradeFormValues = {
  instrument: " eurusd ",
  side: "long",
  lotSize: "0.10",
  entryPrice: "1.08543",
  openedAt: "2035-01-10 09:00",
  closed: true,
  exitPrice: "1.08821",
  closedAt: "2035-01-10 13:30",
  pnl: "27.8",
  notes: "  retest  ",
  tags: ["Breakout", "breakout", " london  open "],
};

function errorsOf(overrides: Partial<TradeFormValues>) {
  const result = validateTrade({ ...closed, ...overrides }, NEW_YORK);
  assert.equal(result.ok, false);
  return result.ok ? {} : result.errors;
}

test("builds a payload of exact strings", () => {
  const result = validateTrade(closed, NEW_YORK);
  assert.ok(result.ok);
  assert.deepEqual(result.payload, {
    instrument: "EURUSD",
    side: "long",
    lot_size: "0.10", // typed text is sent as typed, never through a number
    entry_price: "1.08543",
    opened_at: "2035-01-10T14:00:00Z",
    exit_price: "1.08821",
    closed_at: "2035-01-10T18:30:00Z",
    pnl: "27.8",
    notes: "retest",
    tags: ["Breakout", "london open"],
  });
});

test("an open trade sends null closing fields whatever is left in the closing inputs", () => {
  const result = validateTrade({ ...closed, closed: false }, NEW_YORK);
  assert.ok(result.ok);
  assert.deepEqual([result.payload.exit_price, result.payload.closed_at, result.payload.pnl], [null, null, null]);
  assert.equal(validateTrade({ ...closed, closed: false, notes: "   " }, NEW_YORK).ok && true, true);
});

test("decimals keep eight places and ten whole digits, exactly", () => {
  const edge = validateTrade({ ...closed, entryPrice: "9999999999.99999999", pnl: "-0.00000001" }, NEW_YORK);
  assert.ok(edge.ok);
  assert.deepEqual([edge.payload.entry_price, edge.payload.pnl], ["9999999999.99999999", "-0.00000001"]);
});

test("checkDecimal normalizes what is typed and explains what is not allowed", () => {
  const ok = (raw: string, options = { label: "x", positive: true as boolean | undefined, allowNegative: false as boolean | undefined }) => {
    const result = checkDecimal(raw, options);
    return result.ok ? result.text : `error: ${result.error}`;
  };
  assert.equal(ok(" 1.50 "), "1.50");
  assert.equal(ok("+2"), "2");
  assert.equal(ok("007.5"), "7.5");
  assert.equal(ok(".5"), "0.5");
  assert.equal(ok("5."), "5");
  assert.equal(ok("-3", { label: "x", positive: false, allowNegative: true }), "-3");
  assert.equal(ok("-0", { label: "x", positive: false, allowNegative: true }), "0");
  assert.match(ok(""), /^error: Enter x\.$/);
  assert.match(ok("1,5"), /Use digits and one decimal point/);
  assert.match(ok("1e3"), /Use digits and one decimal point/);
  assert.match(ok("0"), /greater than zero/);
  assert.match(ok("-1"), /positive number/);
  assert.match(ok("0.123456789"), /At most 8 decimal places/);
  assert.match(ok("12345678901"), /At most 10 digits/);
});

test("reports each mistake on its own field", () => {
  assert.match(errorsOf({ instrument: "" }).instrument ?? "", /Enter the instrument/);
  assert.match(errorsOf({ instrument: "bad name!" }).instrument ?? "", /letters, digits/);
  assert.match(errorsOf({ lotSize: "0" }).lotSize ?? "", /greater than zero/);
  assert.match(errorsOf({ entryPrice: "1.123456789" }).entryPrice ?? "", /8 decimal places/);
  assert.match(errorsOf({ openedAt: "10/01/2035" }).openedAt ?? "", /YYYY-MM-DD HH:mm \(America\/New_York\)/);
  assert.match(errorsOf({ openedAt: "2035-03-11 02:30" }).openedAt ?? "", /does not exist/);
  assert.match(errorsOf({ exitPrice: "" }).exitPrice ?? "", /Enter the exit price/);
  assert.match(errorsOf({ closedAt: "2035-01-10 08:00" }).closedAt ?? "", /not be before the open/);
  assert.match(errorsOf({ pnl: "" }).pnl ?? "", /Enter the realized P&L/);
  assert.match(errorsOf({ notes: "x".repeat(10_001) }).notes ?? "", /At most 10,000/);
  assert.match(errorsOf({ tags: ["fine", "no;semicolons"] }).tags ?? "", /Tags use letters/);
  assert.match(errorsOf({ tags: Array.from({ length: 21 }, (_, i) => `t${i}`) }).tags ?? "", /At most 20 tags/);
});

test("dedupes tags ignoring case and keeps the first spelling", () => {
  assert.deepEqual(dedupeTags(["Breakout", "breakout", "  London   open ", "", "LONDON OPEN"]), ["Breakout", "London open"]);
});

test("a patch carries only what changed, comparing decimals by value", () => {
  const base = validateTrade(closed, NEW_YORK);
  assert.ok(base.ok);
  const same = validateTrade({ ...closed, lotSize: "0.1", pnl: "27.80" }, NEW_YORK); // typed differently, same value
  assert.ok(same.ok);
  assert.deepEqual(diffPayload(base.payload, same.payload), {});
  const edited = validateTrade({ ...closed, pnl: "-3.25", notes: "", tags: ["a"] }, NEW_YORK);
  assert.ok(edited.ok);
  assert.deepEqual(diffPayload(base.payload, edited.payload), { pnl: "-3.25", notes: null, tags: ["a"] });
  const reopened = validateTrade({ ...closed, closed: false }, NEW_YORK);
  assert.ok(reopened.ok);
  assert.deepEqual(diffPayload(base.payload, reopened.payload), { exit_price: null, closed_at: null, pnl: null });
});

test("maps a server 422 onto form fields", () => {
  const { fields, general } = fieldsFromDetail([
    { loc: ["body", "pnl"], msg: "pnl is required when closed_at is set", type: "closure.required" },
    { loc: ["body", "lot_size"], msg: "Input should be greater than 0", type: "greater_than" },
    { loc: ["body", "lot_size"], msg: "second message is ignored", type: "x" },
    { loc: ["body"], msg: "Something about the whole body", type: "x" },
  ]);
  assert.deepEqual(fields, { pnl: "pnl is required when closed_at is set", lotSize: "Input should be greater than 0" });
  assert.deepEqual(general, ["Something about the whole body"]);
  assert.deepEqual(fieldsFromDetail("Trade 5 not found"), { fields: {}, general: ["Trade 5 not found"] });
  assert.equal(fieldsFromDetail({ unexpected: true }).general.length, 1);
});
