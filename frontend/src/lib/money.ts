/** Display formatting for the server's decimal strings. Every path goes through exact bigint decimals, never `number`. */
import { type Dec, abs, format, parse, toCanonical } from "./decimal.ts";

const SYMBOLS: Record<string, string> = {
  USD: "$",
  EUR: "€",
  GBP: "£",
  JPY: "¥",
  CHF: "CHF ",
  AUD: "A$",
  CAD: "C$",
  NZD: "NZ$",
  SGD: "S$",
  HKD: "HK$",
};

// Currencies quoted in whole units show no decimals unless the value has some.
const WHOLE_UNIT_CURRENCIES = new Set(["JPY", "KRW", "VND", "CLP", "ISK"]);

export type Tone = "gain" | "loss" | "flat";

export function toneOf(value: Dec): Tone {
  return value > 0n ? "gain" : value < 0n ? "loss" : "flat";
}

/**
 * "$1,234.50", "-$12.30", and with `signed` "+$27.80". Two decimals at least. A stored amount keeps every
 * decimal it has (up to eight), so 0.00000001 is shown as such and never silently becomes "$0.00". A figure
 * the app derives, such as an average, passes `maxFraction: 2` to round to the cent instead. An amount that
 * rounds to zero carries no sign.
 */
export function formatMoneyDec(value: Dec, currency: string, signed = false, maxFraction = 8): string {
  const minFraction = Math.min(WHOLE_UNIT_CURRENCIES.has(currency) ? 0 : 2, maxFraction);
  const body = format(abs(value), { minFraction, maxFraction, grouping: true });
  const isZero = /^[0.,]*$/.test(body);
  const prefix = isZero ? "" : value < 0n ? "-" : signed ? "+" : "";
  const symbol = SYMBOLS[currency] ?? `${currency} `;
  return `${prefix}${symbol}${body}`;
}

/** Formats a decimal string from the API. A missing value is an en dash. Text that is not a decimal is returned as is. */
export function formatMoney(text: string | null | undefined, currency: string, signed = false): string {
  if (text === null || text === undefined) return "–";
  const value = parse(text);
  return value === null ? text : formatMoneyDec(value, currency, signed);
}

/** Lot sizes: at least two decimals, as many as 8 when the value has them. */
export function formatQuantity(text: string | null | undefined): string {
  if (text === null || text === undefined) return "–";
  const value = parse(text);
  return value === null ? text : format(value, { minFraction: 2, maxFraction: 8, grouping: true });
}

function decimalsOf(value: Dec): number {
  return toCanonical(value).split(".")[1]?.length ?? 0;
}

/** The decimals needed to show every price exactly: the most any of them has, and at least two. */
export function pricePlaces(texts: readonly (string | null | undefined)[]): number {
  return texts.reduce<number>((most, text) => {
    const value = text === null || text === undefined ? null : parse(text);
    return value === null ? most : Math.max(most, decimalsOf(value));
  }, 2);
}

/** A price padded to `places` decimals. Never rounded: a price with more decimals than `places` keeps them. A missing price is an en dash. */
export function formatPrice(text: string | null | undefined, places: number, grouping = true): string {
  if (text === null || text === undefined) return "–";
  const value = parse(text);
  return value === null ? text : format(value, { minFraction: places, maxFraction: 8, grouping });
}

/**
 * Prices that belong together, such as a trade's entry and exit, shown with the same number of decimals so
 * they line up and compare at a glance: 1.2740 and 1.2728, not 1.274 and 1.2728. The server stores the
 * shortest exact form and drops trailing zeros, so this puts back the precision a person reads prices in.
 */
export function formatPriceSet(texts: readonly (string | null | undefined)[], options: { grouping?: boolean } = {}): string[] {
  const places = pricePlaces(texts);
  return texts.map((text) => formatPrice(text, places, options.grouping ?? true));
}

/** A decimal string padded to at least `minFraction` decimals, with no grouping: for the value of an input box. */
export function plainDecimal(text: string | null | undefined, minFraction = 2): string {
  if (text === null || text === undefined) return "";
  const value = parse(text);
  return value === null ? text : format(value, { minFraction, maxFraction: 8 });
}
