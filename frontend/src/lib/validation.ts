/**
 * Trade form validation. It mirrors the server's rules, so most mistakes are caught before a request is
 * sent, and builds the payload from exact decimal strings: a value typed as "0.10" is sent as "0.10",
 * never through a `number`. The server stays the authority: whatever it rejects is mapped back onto the
 * same fields (see fieldsFromDetail).
 */
import { type Dec, groupDigits, parse } from "./decimal.ts";
import { textToInstant } from "./time.ts";

export type Side = "long" | "short";

export type TradeFormValues = {
  instrument: string;
  side: Side;
  lotSize: string;
  entryPrice: string;
  openedAt: string; // wall-clock text in the server's zone: "2035-03-10 14:30"
  closed: boolean;
  exitPrice: string;
  closedAt: string;
  pnl: string;
  notes: string;
  tags: string[];
};

export type TradeField = "instrument" | "side" | "lotSize" | "entryPrice" | "openedAt" | "exitPrice" | "closedAt" | "pnl" | "notes" | "tags";
export type FieldErrors = Partial<Record<TradeField, string>>;

/** What the API receives. Decimals are strings, instants are UTC, and the closing fields are null on an open trade. */
export type TradePayload = {
  instrument: string;
  side: Side;
  lot_size: string;
  entry_price: string;
  opened_at: string;
  exit_price: string | null;
  closed_at: string | null;
  pnl: string | null;
  notes: string | null;
  tags: string[];
};

export const LIMITS = { wholeDigits: 10, fractionDigits: 8, notes: 10_000, tags: 20, tagLength: 40 } as const;

export const NOTES_TOO_LONG = `At most ${groupDigits(LIMITS.notes)} characters.`;

export type DecimalCheck = { ok: true; text: string; value: Dec } | { ok: false; error: string };

/** Validates and normalizes a typed decimal: trimmed, no "+", no dangling "." and no leading zeros. */
export function checkDecimal(raw: string, options: { label: string; allowNegative?: boolean; positive?: boolean }): DecimalCheck {
  const typed = raw.trim();
  if (typed === "") return { ok: false, error: `Enter ${options.label}.` };
  if (!/^[+-]?(\d+\.?\d*|\.\d+)$/.test(typed)) return { ok: false, error: "Use digits and one decimal point, for example 0.10." };
  const negative = typed.startsWith("-");
  if (negative && !options.allowNegative) return { ok: false, error: "Enter a positive number." };
  const [wholeRaw = "", fraction = ""] = typed.replace(/^[+-]/, "").split(".");
  const whole = wholeRaw.replace(/^0+(?=\d)/, "") || "0";
  if (whole.length > LIMITS.wholeDigits) return { ok: false, error: `At most ${LIMITS.wholeDigits} digits before the decimal point.` };
  if (fraction.length > LIMITS.fractionDigits) return { ok: false, error: `At most ${LIMITS.fractionDigits} decimal places.` };
  const unsigned = fraction === "" ? whole : `${whole}.${fraction}`;
  const value = parse(unsigned) ?? 0n;
  if (options.positive && value <= 0n) return { ok: false, error: "Must be greater than zero." };
  return { ok: true, text: negative && value !== 0n ? `-${unsigned}` : unsigned, value: negative ? -value : value };
}

const INSTRUMENT = /^[A-Z0-9][A-Z0-9/._-]{0,19}$/;
const TAG = /^[\wÀ-￿][\wÀ-￿ \-/.#+]{0,39}$/;

export function normalizeInstrument(raw: string): string {
  return raw.trim().toUpperCase();
}

export function normalizeTag(raw: string): string {
  return raw.trim().split(/\s+/).join(" ");
}

export function isValidTag(tag: string): boolean {
  return TAG.test(tag);
}

/** Normalized tags with case-insensitive duplicates dropped; the first spelling wins. */
export function dedupeTags(tags: readonly string[]): string[] {
  const seen = new Map<string, string>();
  for (const tag of tags.map(normalizeTag).filter(Boolean)) if (!seen.has(tag.toLowerCase())) seen.set(tag.toLowerCase(), tag);
  return [...seen.values()];
}

export type Validation = { ok: true; payload: TradePayload } | { ok: false; errors: FieldErrors };

export function validateTrade(values: TradeFormValues, timeZone: string): Validation {
  const errors: FieldErrors = {};

  const instrument = normalizeInstrument(values.instrument);
  if (instrument === "") errors.instrument = "Enter the instrument, for example EURUSD.";
  else if (!INSTRUMENT.test(instrument)) errors.instrument = "Use letters, digits and / . _ - (up to 20 characters).";

  const lots = checkDecimal(values.lotSize, { label: "the lot size", positive: true });
  if (!lots.ok) errors.lotSize = lots.error;
  const entry = checkDecimal(values.entryPrice, { label: "the entry price", positive: true });
  if (!entry.ok) errors.entryPrice = entry.error;

  const opened = textToInstant(values.openedAt, timeZone);
  if (!opened.ok) errors.openedAt = instantError(opened.reason, timeZone);

  let exitText: string | null = null;
  let closedIso: string | null = null;
  let pnlText: string | null = null;
  if (values.closed) {
    const exit = checkDecimal(values.exitPrice, { label: "the exit price", positive: true });
    if (exit.ok) exitText = exit.text;
    else errors.exitPrice = exit.error;

    const closed = textToInstant(values.closedAt, timeZone);
    if (!closed.ok) errors.closedAt = instantError(closed.reason, timeZone);
    else if (opened.ok && closed.ms < opened.ms) errors.closedAt = "The close must not be before the open.";
    else closedIso = closed.iso;

    const pnl = checkDecimal(values.pnl, { label: "the realized P&L", allowNegative: true });
    if (pnl.ok) pnlText = pnl.text;
    else errors.pnl = pnl.error;
  }

  const notes = values.notes.trim();
  if (notes.length > LIMITS.notes) errors.notes = NOTES_TOO_LONG;

  const tags = dedupeTags(values.tags);
  if (tags.length > LIMITS.tags) errors.tags = `At most ${LIMITS.tags} tags.`;
  else if (tags.some((tag) => !isValidTag(tag))) errors.tags = "Tags use letters, digits, spaces and - / . # + _ (up to 40 characters).";

  if (Object.keys(errors).length > 0 || !lots.ok || !entry.ok || !opened.ok) return { ok: false, errors };
  return {
    ok: true,
    payload: {
      instrument,
      side: values.side,
      lot_size: lots.text,
      entry_price: entry.text,
      opened_at: opened.iso,
      exit_price: exitText,
      closed_at: closedIso,
      pnl: pnlText,
      notes: notes === "" ? null : notes,
      tags,
    },
  };
}

function instantError(reason: "format" | "nonexistent", timeZone: string): string {
  return reason === "format"
    ? `Use YYYY-MM-DD HH:mm (${timeZone}), for example 2035-03-10 14:30.`
    : `That time does not exist in ${timeZone}: clocks skip it when they spring forward.`;
}

function sameDecimal(a: string | null, b: string | null): boolean {
  if (a === null || b === null) return a === b;
  const left = parse(a);
  const right = parse(b);
  return left !== null && right !== null && left === right;
}

const DECIMAL_KEYS = new Set<keyof TradePayload>(["lot_size", "entry_price", "exit_price", "pnl"]);

/** Only the fields that differ from the stored trade, so a PATCH says exactly what changed. */
export function diffPayload(original: TradePayload, next: TradePayload): Partial<TradePayload> {
  const changes: Record<string, unknown> = {};
  for (const key of Object.keys(next) as (keyof TradePayload)[]) {
    const before = original[key];
    const after = next[key];
    const same = DECIMAL_KEYS.has(key)
      ? sameDecimal(before as string | null, after as string | null)
      : key === "tags"
        ? JSON.stringify(before) === JSON.stringify(after)
        : before === after;
    if (!same) changes[key] = after;
  }
  return changes as Partial<TradePayload>;
}

const API_FIELD: Record<string, TradeField> = {
  instrument: "instrument",
  side: "side",
  lot_size: "lotSize",
  entry_price: "entryPrice",
  opened_at: "openedAt",
  exit_price: "exitPrice",
  closed_at: "closedAt",
  pnl: "pnl",
  notes: "notes",
  tags: "tags",
};

/** Maps a FastAPI 422 `detail` onto form fields. Anything that names no field becomes a general message. */
export function fieldsFromDetail(detail: unknown): { fields: FieldErrors; general: string[] } {
  const fields: FieldErrors = {};
  const general: string[] = [];
  if (typeof detail === "string") return { fields, general: [detail] };
  if (!Array.isArray(detail)) return { fields, general: ["The server rejected the request."] };
  for (const item of detail) {
    const entry = item as { loc?: unknown[]; msg?: string };
    const name = (entry.loc ?? []).map(String).find((part) => part in API_FIELD);
    const field = name === undefined ? undefined : API_FIELD[name];
    const message = entry.msg ?? "Invalid value.";
    if (field && fields[field] === undefined) fields[field] = message;
    else if (!field) general.push(message);
  }
  return { fields, general };
}
