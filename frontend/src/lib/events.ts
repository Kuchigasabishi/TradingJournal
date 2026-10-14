/**
 * Events from outside calendars: economic news (ForexFactory) and the owner's personal calendar (Google). Pure
 * functions over the API's event shape: which days an event covers, how a day's events add up, how they are filtered
 * (the address bar holds the filters, like the trade list) and how their times read in the server's zone.
 */
import { MONTH_NAMES, addDays } from "./calendar.ts";
import { clockOf } from "./time.ts";

export type EventSource = "forexfactory" | "gcal";
export type Impact = "low" | "medium" | "high" | "holiday" | "unknown";

/** The part of an event this module reads, so tests do not need the generated API types. */
export type EventLike = {
  id: number;
  source: EventSource;
  title: string;
  all_day: boolean;
  start_at: string | null;
  end_at: string | null;
  start_day: string;
  end_day: string;
  impact: Impact | null;
  currency: string | null;
};

/** The levels a person can filter by, most important first. `unknown` is a level the feed invented: it is shown, never chosen. */
export const IMPACT_LEVELS = ["high", "medium", "low", "holiday"] as const;
export type FilterImpact = (typeof IMPACT_LEVELS)[number];

export const isNews = (event: Pick<EventLike, "source">): boolean => event.source === "forexfactory";

const count = (n: number, one: string, many = `${one}s`): string => `${n} ${n === 1 ? one : many}`;
const compare = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

// --- days ----------------------------------------------------------------------------------------------------

/** The days of [from, to] an event covers, as "YYYY-MM-DD" text. A multi-day event covers each of its days. */
export function daysCovered(event: Pick<EventLike, "start_day" | "end_day">, from: string, to: string): string[] {
  const days: string[] = [];
  const last = event.end_day < to ? event.end_day : to;
  for (let day = event.start_day > from ? event.start_day : from; day <= last; day = addDays(day, 1)) days.push(day);
  return days;
}

/** Within a day: all-day events first, then by start time, then news after personal, then by title. */
export function compareWithinDay(a: EventLike, b: EventLike): number {
  if (a.all_day !== b.all_day) return a.all_day ? -1 : 1;
  return compare(a.start_at ?? "", b.start_at ?? "") || compare(a.source, b.source) * -1 || compare(a.title, b.title) || a.id - b.id;
}

/** Events by the day they fall on, each list in reading order. An event that spans days appears under every day it covers. */
export function groupByDay<T extends EventLike>(events: readonly T[], from: string, to: string): Map<string, T[]> {
  const groups = new Map<string, T[]>();
  for (const event of events) {
    for (const day of daysCovered(event, from, to)) {
      const list = groups.get(day);
      if (list) list.push(event);
      else groups.set(day, [event]);
    }
  }
  for (const list of groups.values()) list.sort(compareWithinDay);
  return groups;
}

// --- one day's worth -----------------------------------------------------------------------------------------

export type NewsCounts = Record<Impact, number> & { total: number };
export type DayEvents = {
  news: NewsCounts;
  personal: number;
  /** Titles of the personal events, in reading order. */
  titles: string[];
  /** The most important impact among the day's news, or null when it has none. A holiday never outranks a real release. */
  top: Impact | null;
};

const RANK: Record<Impact, number> = { holiday: 0, unknown: 1, low: 2, medium: 3, high: 4 };

export function summarizeDay(events: readonly EventLike[]): DayEvents {
  const news: NewsCounts = { high: 0, medium: 0, low: 0, holiday: 0, unknown: 0, total: 0 };
  const titles: string[] = [];
  let top: Impact | null = null;
  for (const event of events) {
    if (isNews(event)) {
      const level: Impact = event.impact ?? "unknown";
      news[level] += 1;
      news.total += 1;
      if (top === null || RANK[level] > RANK[top]) top = level;
    } else {
      titles.push(event.title);
    }
  }
  return { news, personal: titles.length, titles, top };
}

export const IMPACT_NAME: Record<Impact, string> = { high: "High", medium: "Medium", low: "Low", holiday: "Holiday", unknown: "Unknown" };

/** "High impact", or just "Holiday": the words that go with a glyph or a colour. */
export const impactLabel = (impact: Impact): string => (impact === "holiday" ? "Holiday" : impact === "unknown" ? "Impact unknown" : `${IMPACT_NAME[impact]} impact`);

/** "6 high, 3 medium, 13 low": the parts of a day's news, most important first. */
export function newsBreakdown(counts: NewsCounts): string {
  const parts: string[] = [];
  for (const level of ["high", "medium", "low"] as const) if (counts[level] > 0) parts.push(`${counts[level]} ${level}`);
  if (counts.holiday > 0) parts.push(count(counts.holiday, "holiday"));
  if (counts.unknown > 0) parts.push(`${counts.unknown} unknown`);
  return parts.join(", ");
}

/** "22 news events (6 high, 3 medium, 13 low)" and "2 personal events", for a cell's accessible name; empty text when there is nothing. */
export function dayEventsPhrases(day: DayEvents): string[] {
  const phrases: string[] = [];
  if (day.news.total > 0) phrases.push(`${count(day.news.total, "news event")} (${newsBreakdown(day.news)})`);
  if (day.personal > 0) phrases.push(count(day.personal, "personal event"));
  return phrases;
}

// --- filters, kept in the address ------------------------------------------------------------------------------

export type EventShow = "all" | "news" | "personal";
export type EventFilters = { show: EventShow; impacts: FilterImpact[]; currency?: string };
export const DEFAULT_EVENT_FILTERS: EventFilters = { show: "all", impacts: [] };

type Params = Record<string, string | string[] | undefined>;
const first = (value: string | string[] | undefined): string | undefined => (Array.isArray(value) ? value[0] : value);
// The router writes several values of one parameter as a single comma-joined value (impact=high%2Cmedium), and a link written
// by hand or by eventQuery() repeats the name: a list parameter is split on commas whichever way it arrived.
const list = (value: string | string[] | undefined): string[] => (Array.isArray(value) ? value : value === undefined ? [] : [value]).flatMap((item) => item.split(","));

export function parseEventFilters(params: Params): EventFilters {
  const show = first(params.show);
  const chosen = new Set(list(params.impact));
  const currency = first(params.currency)?.trim().toUpperCase();
  const filters: EventFilters = {
    show: show === "news" || show === "personal" ? show : "all",
    impacts: IMPACT_LEVELS.filter((level) => chosen.has(level)),
  };
  if (currency && /^[A-Z]{2,12}$/.test(currency)) filters.currency = currency;
  return filters;
}

/** The address parameters for a filter set. Defaults are left out, so an unfiltered address stays clean. */
export function toEventParams(filters: EventFilters): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  if (filters.show !== "all") params.show = filters.show;
  if (filters.impacts.length > 0) params.impact = [...filters.impacts];
  if (filters.currency) params.currency = filters.currency;
  return params;
}

export const isFiltered = (filters: EventFilters): boolean => filters.show !== "all" || filters.impacts.length > 0 || filters.currency !== undefined;

/** Impact and currency narrow news only: a personal event has neither. A news event with an impact nobody can choose is hidden once a level is. */
export function applyEventFilters<T extends EventLike>(events: readonly T[], filters: EventFilters): T[] {
  return events.filter((event) => {
    const news = isNews(event);
    if (filters.show === "news" && !news) return false;
    if (filters.show === "personal" && news) return false;
    if (!news) return true;
    if (filters.impacts.length > 0 && !(event.impact !== null && (filters.impacts as readonly string[]).includes(event.impact))) return false;
    if (filters.currency && event.currency !== filters.currency && event.currency !== "ALL") return false; // news for every currency concerns this one too
    return true;
  });
}

/** The currencies the news mentions, sorted. "ALL" is not one of them: it is news for every currency. */
export function currenciesOf(events: readonly EventLike[]): string[] {
  const found = new Set<string>();
  for (const event of events) if (isNews(event) && event.currency && event.currency !== "ALL") found.add(event.currency);
  return [...found].sort(compare);
}

// --- times ---------------------------------------------------------------------------------------------------

const shortDay = (isoDay: string): string => `${MONTH_NAMES[Number(isoDay.slice(5, 7)) - 1]?.slice(0, 3)} ${Number(isoDay.slice(8, 10))}`;

/** When an event happens, in the server's zone: "08:30", "22:00–23:00", "May 12 22:00 → May 13 02:00", "All day", "All day · May 18 to May 20". */
export function eventTimeText(event: Pick<EventLike, "all_day" | "start_at" | "end_at" | "start_day" | "end_day">, timeZone: string): string {
  if (event.all_day) return event.start_day === event.end_day ? "All day" : `All day · ${shortDay(event.start_day)} to ${shortDay(event.end_day)}`;
  if (event.start_at === null) return "";
  const start = clockOf(event.start_at, timeZone);
  if (event.end_at === null) return start;
  const end = clockOf(event.end_at, timeZone);
  return event.start_day === event.end_day ? `${start}–${end}` : `${shortDay(event.start_day)} ${start} → ${shortDay(event.end_day)} ${end}`;
}

// --- addresses -----------------------------------------------------------------------------------------------

/** "?show=news&impact=high&impact=medium" for a filter set, or "" when nothing is filtered: what a link to a day carries along. */
export function eventQuery(filters: EventFilters): string {
  // Written by hand: React Native's own URLSearchParams is a partial polyfill, and this runs on every platform.
  const pairs: string[] = [];
  for (const [name, value] of Object.entries(toEventParams(filters))) for (const item of Array.isArray(value) ? value : [value]) pairs.push(`${encodeURIComponent(name)}=${encodeURIComponent(item)}`);
  return pairs.length === 0 ? "" : `?${pairs.join("&")}`;
}

const HTTP_ADDRESS = /^https?:\/\/[^\s<>"'`]+$/i;

/**
 * An address from a feed that is safe to open: http or https and nothing else. A calendar can hold any text in its URL
 * field, including a script, and a news feed is somebody else's server. (A pattern, not `new URL`, whose getters React
 * Native's polyfill has not always implemented.)
 */
export function safeHttpUrl(text: string | null | undefined): string | null {
  const value = text?.trim();
  return value && HTTP_ADDRESS.test(value) ? value : null;
}
