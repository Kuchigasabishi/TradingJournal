/**
 * Exact decimal arithmetic for money, prices and lot sizes.
 *
 * A value is an integer count of 1e-8 units held in a bigint, the same scale the server stores. Nothing
 * here touches `number`, so a value cannot pick up floating-point error between the API and the screen.
 *
 * Files in src/lib import each other with explicit .ts extensions so that Node's built-in test runner can
 * load them directly, without a build step or a test framework.
 */

export type Dec = bigint;

export const SCALE = 8;
export const UNIT: Dec = 10n ** 8n;

const DECIMAL_TEXT = /^([+-]?)(\d*)(?:\.(\d*))?$/;

/** Parses a plain decimal string exactly. Returns null for anything else, including more than 8 decimals. */
export function parse(text: string): Dec | null {
  const match = DECIMAL_TEXT.exec(text.trim());
  if (!match) return null;
  const negative = match[1] === "-";
  const whole = match[2] ?? "";
  const fraction = match[3] ?? "";
  if (whole === "" && fraction === "") return null;
  if (fraction.length > SCALE) return null;
  const units = BigInt(whole === "" ? "0" : whole) * UNIT + BigInt(fraction.padEnd(SCALE, "0"));
  return negative ? -units : units;
}

/** The shortest plain-notation form, as the server writes it: 1.10000000 is "1.1", 100 is "100". */
export function toCanonical(value: Dec): string {
  const magnitude = abs(value);
  const whole = magnitude / UNIT;
  const fraction = (magnitude % UNIT).toString().padStart(SCALE, "0").replace(/0+$/, "");
  return `${value < 0n ? "-" : ""}${whole}${fraction === "" ? "" : "." + fraction}`;
}

export type FormatOptions = {
  /** Fraction digits always shown. */
  minFraction?: number;
  /** Fraction digits kept before rounding half away from zero. Default 8: nothing is ever rounded. */
  maxFraction?: number;
  grouping?: boolean;
};

/** Formats for display. Rounding is exact decimal rounding, half away from zero. Locale-independent: "," groups, "." separates. */
export function format(value: Dec, options: FormatOptions = {}): string {
  const maxFraction = Math.min(Math.max(options.maxFraction ?? SCALE, 0), SCALE);
  const minFraction = Math.min(Math.max(options.minFraction ?? 0, 0), maxFraction);
  const rounded = roundMagnitude(abs(value), maxFraction);
  const whole = (rounded / UNIT).toString();
  let fraction = (rounded % UNIT).toString().padStart(SCALE, "0").slice(0, maxFraction);
  while (fraction.length > minFraction && fraction.endsWith("0")) fraction = fraction.slice(0, -1);
  fraction = fraction.padEnd(minFraction, "0");
  const grouped = options.grouping ? whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",") : whole;
  const negative = value < 0n && rounded !== 0n; // a value that rounds to zero carries no sign
  return `${negative ? "-" : ""}${grouped}${fraction === "" ? "" : "." + fraction}`;
}

function roundMagnitude(magnitude: Dec, places: number): Dec {
  const drop = SCALE - places;
  if (drop <= 0) return magnitude;
  const step = 10n ** BigInt(drop);
  const remainder = magnitude % step;
  const floor = magnitude - remainder;
  return remainder * 2n >= step ? floor + step : floor;
}

/** A whole number with thousands separators ("10,000"), independent of the locale. */
export function groupDigits(count: number): string {
  return format(BigInt(Math.trunc(count)) * UNIT, { grouping: true });
}

export function abs(value: Dec): Dec {
  return value < 0n ? -value : value;
}

export function sign(value: Dec): -1 | 0 | 1 {
  return value < 0n ? -1 : value > 0n ? 1 : 0;
}

export function compare(a: Dec, b: Dec): -1 | 0 | 1 {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function sum(values: readonly Dec[]): Dec {
  return values.reduce((total, value) => total + value, 0n);
}

/** value / divisor, rounded half away from zero. The divisor is a plain integer such as a trade count. */
export function divideRound(value: Dec, divisor: bigint): Dec {
  if (divisor === 0n) throw new RangeError("division by zero");
  const negative = value < 0n !== divisor < 0n;
  const numerator = abs(value);
  const denominator = divisor < 0n ? -divisor : divisor;
  const quotient = (numerator * 2n + denominator) / (denominator * 2n);
  return negative ? -quotient : quotient;
}

/** part / total as a percentage with `places` decimals ("66.7"), or null when there is no total. */
export function percent(part: number, total: number, places = 1): string | null {
  if (total <= 0) return null;
  const decimals = Math.min(Math.max(places, 0), SCALE);
  const factor = 10n ** BigInt(decimals);
  const scaled = (BigInt(part) * 100n * factor * 2n + BigInt(total)) / (BigInt(total) * 2n);
  return format(scaled * 10n ** BigInt(SCALE - decimals), { minFraction: decimals, maxFraction: decimals });
}

/** |value| as a whole number of steps out of `steps`, relative to `max`. Used to size bars and pick heat-map shades. */
export function toSteps(value: Dec, max: Dec, steps: number): number {
  if (max <= 0n) return 0;
  const size = BigInt(steps);
  return Number((abs(value) * size * 2n + max) / (max * 2n));
}
