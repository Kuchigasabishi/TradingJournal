/** Calendar arithmetic on plain "YYYY-MM-DD" strings. Pure date math in UTC, so no time zone can shift a day. */

export type MonthRef = { year: number; month: number }; // month is 1 to 12

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"] as const;

const pad = (value: number, width = 2): string => String(value).padStart(width, "0");

export function isoDate(year: number, month: number, day: number): string {
  return `${pad(year, 4)}-${pad(month)}-${pad(day)}`;
}

/** "2035-03" to a month reference. Null for anything else. */
export function parseMonth(text: string | undefined): MonthRef | null {
  const match = /^(\d{4})-(\d{2})$/.exec(text ?? "");
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  return month >= 1 && month <= 12 && year >= 1970 && year <= 2200 ? { year, month } : null;
}

export function monthKey(ref: MonthRef): string {
  return `${pad(ref.year, 4)}-${pad(ref.month)}`;
}

export function monthOf(isoDay: string): MonthRef {
  return { year: Number(isoDay.slice(0, 4)), month: Number(isoDay.slice(5, 7)) };
}

export function shiftMonth(ref: MonthRef, delta: number): MonthRef {
  const index = ref.year * 12 + (ref.month - 1) + delta;
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

export function daysInMonth(ref: MonthRef): number {
  return new Date(Date.UTC(ref.year, ref.month, 0)).getUTCDate();
}

/** Monday is 0 and Sunday is 6. */
export function weekdayIndex(isoDay: string): number {
  const [year, month, day] = isoDay.split("-").map(Number) as [number, number, number];
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
}

/** Weeks of seven cells, Monday first. A cell is a "YYYY-MM-DD" string, or null where the month does not reach. */
export function monthGrid(ref: MonthRef): (string | null)[][] {
  const lead = weekdayIndex(isoDate(ref.year, ref.month, 1));
  const cells: (string | null)[] = Array.from({ length: lead }, () => null);
  for (let day = 1; day <= daysInMonth(ref); day += 1) cells.push(isoDate(ref.year, ref.month, day));
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (string | null)[][] = [];
  for (let start = 0; start < cells.length; start += 7) weeks.push(cells.slice(start, start + 7));
  return weeks;
}

export function monthBounds(ref: MonthRef): { from: string; to: string } {
  return { from: isoDate(ref.year, ref.month, 1), to: isoDate(ref.year, ref.month, daysInMonth(ref)) };
}

export function monthLabel(ref: MonthRef): string {
  return `${MONTH_NAMES[ref.month - 1]} ${ref.year}`;
}

/** "Sat, Mar 10, 2035" */
export function dayLabel(isoDay: string): string {
  const ref = monthOf(isoDay);
  const day = Number(isoDay.slice(8, 10));
  return `${WEEKDAYS[weekdayIndex(isoDay)]}, ${MONTH_NAMES[ref.month - 1]?.slice(0, 3)} ${day}, ${ref.year}`;
}

export function addDays(isoDay: string, delta: number): string {
  const [year, month, day] = isoDay.split("-").map(Number) as [number, number, number];
  const moved = new Date(Date.UTC(year, month - 1, day + delta));
  return isoDate(moved.getUTCFullYear(), moved.getUTCMonth() + 1, moved.getUTCDate());
}

export function isIsoDay(text: string | undefined): text is string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text ?? "");
  if (!match) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const check = new Date(Date.UTC(year, month - 1, day));
  return check.getUTCFullYear() === year && check.getUTCMonth() === month - 1 && check.getUTCDate() === day;
}
