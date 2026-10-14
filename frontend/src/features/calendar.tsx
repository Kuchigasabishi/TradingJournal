import { useLocalSearchParams } from "expo-router";
import { StyleSheet, View } from "react-native";

import type { DaySummary } from "../api/client";
import { useEvents, useMonth, useNotes, useRefreshEventsOnSync } from "../api/queries";
import { ACCOUNT_CURRENCY } from "../config";
import { type MonthRef, WEEKDAYS, dayLabel, monthBounds, monthGrid, monthLabel, monthOf, parseMonth } from "../lib/calendar";
import { toSteps } from "../lib/decimal";
import { type DayEvents, IMPACT_NAME, applyEventFilters, currenciesOf, dayEventsPhrases, eventQuery, groupByDay, isFiltered, isNews, newsBreakdown, summarizeDay } from "../lib/events";
import { formatMoneyDec, toneOf } from "../lib/money";
import { dayStats } from "../lib/summary";
import { todayIn } from "../lib/time";
import { useServer } from "../state/providers";
import { colors, radius, shade, space, useLayout } from "../theme";
import { PressableLink } from "../ui/controls";
import { Tooltip, TrendMark } from "../ui/data";
import { ErrorState, LoadingState } from "../ui/feedback";
import { ImpactBadge, ImpactGlyph, PersonalBadge, PersonalMark } from "../ui/impact";
import { Card, Page } from "../ui/layout";
import { AppText } from "../ui/text";
import { first, messageOf, plural, toDec, tradesLabel, useDocumentTitle } from "./common";
import { EventFilterBar, useEventFilters } from "./events";
import { ChartViewToggle, DailyTable, MonthNav, useChartView } from "./months";
import { SourcesCard } from "./sources";

/** A small diamond that marks a day with a note. Shape, not color, carries the meaning. */
function NoteMark({ color, testID }: { color: string; testID?: string }) {
  return <View role="img" aria-label="has a note" testID={testID} style={[styles.noteMark, { backgroundColor: color }]} />;
}

/** The shade step (0 lightest to 3 darkest) for an amount, against the month's largest day: one scale for gains and losses. */
function shadeStep(pnl: bigint, maxAbs: bigint): number {
  return Math.min(Math.max(toSteps(pnl, maxAbs, 4) - 1, 0), 3);
}

const NEWS_LEVELS = ["high", "medium", "low", "holiday", "unknown"] as const;

type CellProps = {
  date: string;
  isToday: boolean;
  day: DaySummary | undefined;
  noteCount: number;
  maxAbs: bigint;
  compact: boolean;
  align: "left" | "right";
  /** What the day holds from outside the journal: economic news and events from the personal calendar. */
  events: DayEvents | undefined;
  /** The event filters as a query string, so the day opens with the same view. */
  query: string;
};

function DayCell({ date, isToday, day, noteCount, maxAbs, compact, align, events, query }: CellProps) {
  const pnl = day ? toDec(day.pnl) : null;
  const tone = pnl === null ? "flat" : toneOf(pnl);
  const fill = pnl === null || tone === "flat" ? { fill: pnl === null ? colors.surface : colors.sunken, ink: colors.ink } : shade(tone, shadeStep(pnl, maxAbs));
  const parts = [isToday ? `${dayLabel(date)} (today)` : dayLabel(date)];
  if (day && pnl !== null) parts.push(`${formatMoneyDec(pnl, ACCOUNT_CURRENCY, true)}, ${tradesLabel(day.trade_count)}`);
  else parts.push("no closed trades");
  if (noteCount > 0) parts.push(`${noteCount} ${noteCount === 1 ? "note" : "notes"}`);
  if (events) parts.push(...dayEventsPhrases(events));
  const label = parts.join(", ");
  const hasNews = events !== undefined && events.news.total > 0;
  const hasPersonal = events !== undefined && events.personal > 0;
  return (
    <View role="cell" style={styles.cellWrap}>
      <PressableLink
        href={`/day/${date}${query}`}
        testID={`day-${date}`}
        role="link"
        aria-label={label}
        aria-current={isToday ? "date" : undefined}
        style={({ focused }) => [styles.cell, compact && styles.cellCompact, { backgroundColor: fill.fill }, isToday && styles.cellToday, focused && styles.cellFocused]}
      >
        {({ hovered, focused }) => (
          <>
            <View style={styles.cellTop}>
              <AppText variant="small" bold numeric style={{ color: fill.ink }}>
                {Number(date.slice(8, 10))}
              </AppText>
              {noteCount > 0 ? <NoteMark color={fill.ink} testID={`note-mark-${date}`} /> : null}
            </View>
            {day && pnl !== null ? (
              <View style={styles.cellBody}>
                <View style={styles.amountRow}>
                  <TrendMark tone={tone} size={4} color={fill.ink} />
                  {compact ? null : (
                    <AppText variant="small" bold numeric style={{ color: fill.ink }} testID={`day-pnl-${date}`}>
                      {formatMoneyDec(pnl, ACCOUNT_CURRENCY, true)}
                    </AppText>
                  )}
                </View>
                {compact ? null : (
                  <AppText variant="tiny" style={{ color: fill.ink }}>
                    {tradesLabel(day.trade_count)}
                  </AppText>
                )}
              </View>
            ) : null}
            {events && (hasNews || hasPersonal) ? (
              <View style={styles.cellEvents}>
                {hasNews ? (
                  <View style={styles.badges}>
                    {compact && events.top ? (
                      <ImpactBadge impact={events.top} count={events.news[events.top]} showCount={false} testID={`news-badge-${date}-${events.top}`} />
                    ) : (
                      NEWS_LEVELS.filter((level) => events.news[level] > 0).map((level) => (
                        <ImpactBadge key={level} impact={level} count={events.news[level]} testID={`news-badge-${date}-${level}`} countTestID={`news-count-${date}-${level}`} />
                      ))
                    )}
                  </View>
                ) : null}
                {hasPersonal ? <PersonalBadge title={compact ? undefined : events.titles[0]} more={events.personal - 1} testID={`personal-badge-${date}`} titleTestID={`personal-title-${date}`} /> : null}
              </View>
            ) : null}
            {hovered || focused ? (
              <Tooltip testID={`day-tooltip-${date}`} align={align}>
                <AppText variant="tiny" tone="inverse">
                  {dayLabel(date)}
                </AppText>
                <AppText variant="label" tone="inverse">
                  {day && pnl !== null ? formatMoneyDec(pnl, ACCOUNT_CURRENCY, true) : "No closed trades"}
                </AppText>
                {day ? (
                  <AppText variant="tiny" tone="inverse">
                    {tradesLabel(day.trade_count)} · {day.wins}W {day.losses}L {day.breakeven}BE
                  </AppText>
                ) : null}
                {noteCount > 0 ? (
                  <AppText variant="tiny" tone="inverse">
                    {noteCount} {noteCount === 1 ? "note" : "notes"}
                  </AppText>
                ) : null}
                {events && hasNews ? (
                  <AppText variant="tiny" tone="inverse">
                    {plural(events.news.total, "news event")}: {newsBreakdown(events.news)}
                  </AppText>
                ) : null}
                {events?.titles.slice(0, 3).map((title, index) => (
                  <AppText key={index} variant="tiny" tone="inverse" numberOfLines={1}>
                    {title}
                  </AppText>
                ))}
                {events && events.titles.length > 3 ? (
                  <AppText variant="tiny" tone="inverse">
                    +{events.titles.length - 3} more
                  </AppText>
                ) : null}
              </Tooltip>
            ) : null}
          </>
        )}
      </PressableLink>
    </View>
  );
}

function Swatch({ fill, testID }: { fill: string; testID?: string }) {
  return <View testID={testID} style={[styles.swatch, { backgroundColor: fill }]} />;
}

/** The scale the grid is shaded with: losses darken leftward, gains rightward, the midpoint is neutral. */
function Legend({ maxAbs }: { maxAbs: bigint }) {
  return (
    <View style={styles.legend} testID="calendar-legend">
      <AppText variant="tiny" tone="secondary">
        Loss
      </AppText>
      <View style={styles.swatches}>
        {[3, 2, 1, 0].map((step) => (
          <Swatch key={`loss-${step}`} fill={shade("loss", step).fill} testID={`legend-loss-${step}`} />
        ))}
        <Swatch fill={colors.sunken} testID="legend-even" />
        {[0, 1, 2, 3].map((step) => (
          <Swatch key={`gain-${step}`} fill={shade("gain", step).fill} testID={`legend-gain-${step}`} />
        ))}
      </View>
      <AppText variant="tiny" tone="secondary">
        Gain
      </AppText>
      <AppText variant="tiny" tone="secondary" testID="legend-scale">
        {maxAbs > 0n ? `Darkest shade: ${formatMoneyDec(maxAbs, ACCOUNT_CURRENCY)} in a day, the largest this month.` : "Shades scale to the month's largest day."}
      </AppText>
      <View style={styles.noteLegend}>
        <NoteMark color={colors.ink} />
        <AppText variant="tiny" tone="secondary">
          Day has a note
        </AppText>
      </View>
    </View>
  );
}

/** What the marks from outside the journal mean. Only what the month actually contains is explained. */
function EventsLegend({ hasNews, hasHoliday, hasPersonal }: { hasNews: boolean; hasHoliday: boolean; hasPersonal: boolean }) {
  return (
    <View style={styles.legend} testID="calendar-events-legend">
      {hasNews ? (
        <>
          <AppText variant="tiny" tone="secondary">
            News impact
          </AppText>
          {(["low", "medium", "high"] as const).map((level) => (
            <View key={level} style={styles.legendItem}>
              <ImpactGlyph impact={level} testID={`legend-impact-${level}`} />
              <AppText variant="tiny" tone="secondary">
                {IMPACT_NAME[level]}
              </AppText>
            </View>
          ))}
          {hasHoliday ? (
            <View style={styles.legendItem}>
              <ImpactGlyph impact="holiday" testID="legend-impact-holiday" />
              <AppText variant="tiny" tone="secondary">
                Holiday
              </AppText>
            </View>
          ) : null}
          <AppText variant="tiny" tone="secondary">
            The number is how many releases.
          </AppText>
        </>
      ) : null}
      {hasPersonal ? (
        <View style={[styles.legendItem, hasNews && styles.noteLegend]}>
          <PersonalMark testID="legend-personal" />
          <AppText variant="tiny" tone="secondary">
            Personal calendar event
          </AppText>
        </View>
      ) : null}
    </View>
  );
}

type GridProps = {
  month: MonthRef;
  today: string;
  days: readonly DaySummary[];
  noteCounts: ReadonlyMap<string, number>;
  maxAbs: bigint;
  events: ReadonlyMap<string, DayEvents>;
  query: string;
};

function CalendarGrid({ month, today, days, noteCounts, maxAbs, events, query }: GridProps) {
  const { narrow } = useLayout();
  const byDate = new Map(days.map((day) => [day.date, day]));
  const weeks = monthGrid(month);
  return (
    <View role="table" aria-label={`Calendar, ${monthLabel(month)}`} testID="calendar-grid" style={styles.grid}>
      <View role="row" style={styles.weekRow}>
        {WEEKDAYS.map((name) => (
          <AppText key={name} role="columnheader" variant="label" tone="secondary" style={styles.weekday}>
            {name}
          </AppText>
        ))}
      </View>
      {weeks.map((week, row) => (
        <View key={row} role="row" style={styles.weekRow}>
          {week.map((date, column) =>
            date === null ? (
              <View key={`blank-${row}-${column}`} style={styles.cellWrap} />
            ) : (
              <DayCell
                key={date}
                date={date}
                isToday={date === today}
                day={byDate.get(date)}
                noteCount={noteCounts.get(date) ?? 0}
                maxAbs={maxAbs}
                compact={narrow}
                align={column >= 4 ? "right" : "left"}
                events={events.get(date)}
                query={query}
              />
            )
          )}
        </View>
      ))}
    </View>
  );
}

export function CalendarScreen() {
  const params = useLocalSearchParams<{ month?: string }>();
  const { timezone } = useServer();
  const today = todayIn(timezone);
  const current = monthOf(today);
  const month = parseMonth(first(params.month)) ?? current;
  const { from, to } = monthBounds(month);
  useDocumentTitle("Calendar");
  const summary = useMonth(month.year, month.month);
  const notes = useNotes({ from, to, limit: 500 });
  const events = useEvents({ from, to });
  useRefreshEventsOnSync();
  const { filters, apply } = useEventFilters();
  const [view, setView] = useChartView();
  const maxAbs = dayStats(summary.data?.days ?? []).maxAbs;

  const noteCounts = new Map<string, number>();
  for (const note of notes.data?.items ?? []) noteCounts.set(note.day, (noteCounts.get(note.day) ?? 0) + 1);

  // Filters narrow what is drawn; what the month holds decides which controls and legend entries exist at all.
  const monthEvents = events.data?.items ?? [];
  const shown = applyEventFilters(monthEvents, filters);
  const eventDays = new Map<string, DayEvents>([...groupByDay(shown, from, to)].map(([day, list]) => [day, summarizeDay(list)] as const));
  const newsCount = monthEvents.filter(isNews).length;
  const hasHoliday = monthEvents.some((event) => event.impact === "holiday");
  const query = eventQuery(filters);

  return (
    <Page testID="calendar">
      <View style={styles.titleRow}>
        <AppText variant="h1" role="heading" testID="page-title">
          Calendar
        </AppText>
        <MonthNav month={month} current={current} />
      </View>
      {summary.isPending ? (
        <LoadingState label="Loading the month…" testID="calendar-loading" />
      ) : summary.isError ? (
        <ErrorState title="Could not load the month" detail={messageOf(summary.error)} onRetry={() => void summary.refetch()} testID="calendar-error" retryTestID="calendar-retry" />
      ) : (
        <View style={summary.isPlaceholderData ? styles.stale : undefined} aria-busy={summary.isPlaceholderData} testID="calendar-content">
          <Card>
            <View style={styles.cardStack}>
              <View style={styles.cardHeader}>
                <View style={styles.cardTitle}>
                  <AppText variant="h2" testID="calendar-heading">
                    {monthLabel(month)}
                  </AppText>
                  <AppText tone="secondary" testID="calendar-summary">
                    {summary.data.totals.trade_count === 0
                      ? "No closed trades this month."
                      : `${formatMoneyDec(toDec(summary.data.totals.pnl), ACCOUNT_CURRENCY, true)} net from ${tradesLabel(summary.data.totals.trade_count)}.`}
                  </AppText>
                  {monthEvents.length > 0 ? (
                    <AppText variant="small" tone="secondary" testID="calendar-events-summary">
                      {isFiltered(filters)
                        ? `Showing ${shown.length} of ${plural(monthEvents.length, "event")} this month.`
                        : `${plural(monthEvents.length, "event")} this month: ${newsCount} news, ${monthEvents.length - newsCount} personal.`}
                    </AppText>
                  ) : null}
                </View>
                <ChartViewToggle value={view} onChange={setView} chartLabel="Grid" />
              </View>
              {monthEvents.length > 0 ? <EventFilterBar filters={filters} onChange={apply} currencies={currenciesOf(monthEvents)} hasNews={newsCount > 0} /> : null}
              {view === "chart" ? (
                <>
                  <Legend maxAbs={maxAbs} />
                  {monthEvents.length > 0 ? <EventsLegend hasNews={newsCount > 0} hasHoliday={hasHoliday} hasPersonal={monthEvents.length > newsCount} /> : null}
                  <CalendarGrid month={month} today={today} days={summary.data.days} noteCounts={noteCounts} maxAbs={maxAbs} events={eventDays} query={query} />
                </>
              ) : (
                <DailyTable days={summary.data.days} noteDays={new Set(noteCounts.keys())} eventDays={monthEvents.length > 0 ? eventDays : undefined} />
              )}
              {notes.isError ? (
                <AppText variant="small" tone="critical" testID="calendar-notes-error">
                  Notes could not be loaded, so days with notes are not marked.
                </AppText>
              ) : null}
              {events.isError ? (
                <AppText variant="small" tone="critical" testID="calendar-events-error">
                  Events could not be loaded, so news and calendar events are not shown.
                </AppText>
              ) : null}
              <AppText variant="tiny" tone="secondary">
                Press a day to open it; today has a dark outline. Days are in {summary.data.timezone}, and a trade counts on the day it was closed.
                {monthEvents.length > 0 ? ` News and calendar events are shown on the day they fall in ${summary.data.timezone}.` : ""}
              </AppText>
            </View>
          </Card>
        </View>
      )}
      <SourcesCard />
    </Page>
  );
}

const styles = StyleSheet.create({
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: space.md },
  cardStack: { gap: space.lg },
  cardHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: space.md },
  cardTitle: { gap: 2 },
  stale: { opacity: 0.5 },
  grid: { gap: space.xs },
  weekRow: { flexDirection: "row", gap: space.xs },
  weekday: { flex: 1, textAlign: "center", paddingVertical: space.xs },
  cellWrap: { flex: 1, minWidth: 0 },
  cell: { minHeight: 88, padding: space.sm, borderRadius: radius.md, borderWidth: 1, borderColor: colors.hairline, justifyContent: "space-between", gap: space.xs, position: "relative" },
  cellCompact: { minHeight: 56, padding: space.xs },
  cellToday: { borderColor: colors.ink, borderWidth: 2 },
  cellFocused: { outlineColor: colors.focus, outlineWidth: 2, outlineStyle: "solid", outlineOffset: 1 },
  cellTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  cellBody: { gap: 2 },
  cellEvents: { gap: 2, alignItems: "flex-start" },
  badges: { flexDirection: "row", flexWrap: "wrap", gap: 2 },
  amountRow: { flexDirection: "row", alignItems: "center", gap: space.xs },
  noteMark: { width: 8, height: 8, transform: [{ rotate: "45deg" }] },
  legend: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: space.sm },
  legendItem: { flexDirection: "row", alignItems: "center", gap: space.xs },
  swatches: { flexDirection: "row", gap: 2 },
  swatch: { width: 20, height: 12, borderRadius: 2, borderWidth: 1, borderColor: colors.hairline },
  noteLegend: { flexDirection: "row", alignItems: "center", gap: space.sm, marginLeft: space.md },
});
