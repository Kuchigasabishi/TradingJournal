/**
 * Time conversions in the server's time zone.
 *
 * The server stores instants in UTC and buckets calendar days in APP_TIMEZONE (/api/ready tells clients
 * which). People type and read wall-clock times in that zone, so conversion has to be daylight-saving
 * aware: a fixed offset would be wrong for half the year.
 */

export type Wall = { year: number; month: number; day: number; hour: number; minute: number; second: number };

const DAY_MS = 86_400_000;
const formatters = new Map<string, Intl.DateTimeFormat>();

function formatterFor(timeZone: string): Intl.DateTimeFormat {
  let formatter = formatters.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    formatters.set(timeZone, formatter);
  }
  return formatter;
}

/** The wall-clock time in `timeZone` at the instant `ms` (milliseconds since the epoch). */
export function wallClock(ms: number, timeZone: string): Wall {
  const parts = formatterFor(timeZone).formatToParts(new Date(ms));
  const read = (type: string): number => Number(parts.find((part) => part.type === type)?.value ?? "0");
  return { year: read("year"), month: read("month"), day: read("day"), hour: read("hour") % 24, minute: read("minute"), second: read("second") };
}

function wallAsUtc(wall: Wall): number {
  return Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute, wall.second);
}

/** The zone's offset from UTC at an instant, in milliseconds (New York in winter: -18_000_000). */
export function offsetMs(ms: number, timeZone: string): number {
  return wallAsUtc(wallClock(ms, timeZone)) - Math.floor(ms / 1000) * 1000;
}

function sameWall(a: Wall, b: Wall): boolean {
  return wallAsUtc(a) === wallAsUtc(b);
}

/**
 * The instant at which `timeZone`'s clocks read `wall`, or null when that time does not exist (the hour
 * skipped when clocks spring forward). When it happens twice (clocks fall back) the earlier instant wins.
 */
export function instantFromWall(wall: Wall, timeZone: string): number | null {
  const naive = wallAsUtc(wall);
  const candidates = new Set<number>();
  // Offsets a day either side bracket any single transition, so the right candidate is among these two.
  for (const probe of [naive - DAY_MS, naive + DAY_MS]) {
    const candidate = naive - offsetMs(probe, timeZone);
    if (sameWall(wallClock(candidate, timeZone), wall)) candidates.add(candidate);
  }
  return candidates.size === 0 ? null : Math.min(...candidates);
}

const WALL_TEXT = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/;

/** Parses "2035-03-10 14:30" (or with a T, or with seconds). Null when malformed or not a real date. */
export function parseWall(text: string): Wall | null {
  const match = WALL_TEXT.exec(text.trim());
  if (!match) return null;
  const [year, month, day, hour, minute, second] = [match[1], match[2], match[3], match[4], match[5], match[6] ?? "0"].map(Number) as [number, number, number, number, number, number];
  const wall: Wall = { year, month, day, hour, minute, second };
  if (hour > 23 || minute > 59 || second > 59) return null;
  const check = new Date(Date.UTC(year, month - 1, day));
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return null;
  return wall;
}

const pad = (value: number, width = 2): string => String(value).padStart(width, "0");

export function formatWall(wall: Wall): string {
  return `${pad(wall.year, 4)}-${pad(wall.month)}-${pad(wall.day)} ${pad(wall.hour)}:${pad(wall.minute)}`;
}

export function isoFromMs(ms: number): string {
  return new Date(ms).toISOString().replace(".000Z", "Z");
}

export type InstantResult = { ok: true; iso: string; ms: number } | { ok: false; reason: "format" | "nonexistent" };

/** Reads wall-clock text typed in `timeZone` and returns the UTC instant the server expects. */
export function textToInstant(text: string, timeZone: string): InstantResult {
  const wall = parseWall(text);
  if (!wall) return { ok: false, reason: "format" };
  const ms = instantFromWall(wall, timeZone);
  return ms === null ? { ok: false, reason: "nonexistent" } : { ok: true, iso: isoFromMs(ms), ms };
}

/** An API instant ("2035-03-10T19:30:00Z") as wall-clock text in `timeZone`: "2035-03-10 14:30". */
export function instantToText(iso: string, timeZone: string): string {
  return formatWall(wallClock(Date.parse(iso), timeZone));
}

/** The wall-clock time of day ("14:30") an instant shows in `timeZone`. */
export function clockOf(iso: string, timeZone: string): string {
  const wall = wallClock(Date.parse(iso), timeZone);
  return `${pad(wall.hour)}:${pad(wall.minute)}`;
}

/** The calendar day ("2035-03-10") an instant falls on in `timeZone`. */
export function dayOf(iso: string, timeZone: string): string {
  const wall = wallClock(Date.parse(iso), timeZone);
  return `${pad(wall.year, 4)}-${pad(wall.month)}-${pad(wall.day)}`;
}

export function todayIn(timeZone: string, nowMs: number = Date.now()): string {
  const wall = wallClock(nowMs, timeZone);
  return `${pad(wall.year, 4)}-${pad(wall.month)}-${pad(wall.day)}`;
}
