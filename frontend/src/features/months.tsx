import { useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import type { DaySummary } from "../api/client";
import { ACCOUNT_CURRENCY } from "../config";
import { type MonthRef, dayLabel, daysInMonth, isoDate, monthKey, monthLabel, shiftMonth } from "../lib/calendar";
import { abs, parse, toSteps } from "../lib/decimal";
import { type DayEvents, newsBreakdown } from "../lib/events";
import { formatMoneyDec, toneOf } from "../lib/money";
import { dayStats } from "../lib/summary";
import { colors, space, useLayout } from "../theme";
import { Button, Segmented, TextLink } from "../ui/controls";
import { Tooltip, useHover } from "../ui/data";
import { AppText } from "../ui/text";
import { PnlAmount, tradesLabel } from "./common";

/** The month switcher shared by the dashboard and the calendar. The month lives in the address (?month=2035-03). */
export function MonthNav({ month, current }: { month: MonthRef; current: MonthRef }) {
  const router = useRouter();
  const go = (target: MonthRef) => router.setParams({ month: monthKey(target) });
  const isCurrent = monthKey(month) === monthKey(current);
  return (
    <View style={styles.nav}>
      <Button label="‹ Prev" small onPress={() => go(shiftMonth(month, -1))} testID="month-prev" />
      <AppText variant="h3" style={styles.monthLabel} testID="month-label" role="heading">
        {monthLabel(month)}
      </AppText>
      <Button label="Next ›" small onPress={() => go(shiftMonth(month, 1))} testID="month-next" />
      <Button label="This month" small variant="ghost" disabled={isCurrent} onPress={() => go(current)} testID="month-today" />
    </View>
  );
}

export type ChartView = "chart" | "table";

/** Switches between a visual and its table. The first option's label changes with the visual ("Chart", "Grid"). */
export function ChartViewToggle({ value, onChange, chartLabel = "Chart" }: { value: ChartView; onChange: (value: ChartView) => void; chartLabel?: string }) {
  return (
    <Segmented
      label="View"
      value={value}
      onChange={onChange}
      testID="view-toggle"
      options={[
        { value: "chart", label: chartLabel, testID: "view-chart" },
        { value: "table", label: "Table", testID: "view-table" },
      ]}
    />
  );
}

/** The two toggled views of one data set share this state shape on the dashboard and the calendar. */
export function useChartView(initial: ChartView = "chart") {
  return useState<ChartView>(initial);
}

const PLOT_HEIGHT = 128;
const AXIS_WIDTH = 84;

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

type SlotProps = {
  date: string;
  day: DaySummary | undefined;
  upPx: number;
  downPx: number;
  upMax: bigint;
  downMax: bigint;
  align: "left" | "right";
  showLabel: boolean;
};

function Slot({ date, day, upPx, downPx, upMax, downMax, align, showLabel }: SlotProps) {
  const hover = useHover();
  const pnl = day ? parse(day.pnl) : null;
  const tone = pnl === null ? "flat" : toneOf(pnl);
  const label = day && pnl !== null ? `${dayLabel(date)}: ${formatMoneyDec(pnl, ACCOUNT_CURRENCY, true)}, ${tradesLabel(day.trade_count)}` : `${dayLabel(date)}: no closed trades`;
  const scale = tone === "gain" ? upMax : downMax;
  const room = tone === "gain" ? upPx : downPx;
  // A day with any P&L at all keeps a 2px sliver, so it never vanishes next to a large day.
  const barHeight = pnl === null || pnl === 0n ? 0 : Math.max(2, toSteps(abs(pnl), scale, room));
  return (
    <Pressable testID={`bar-${date}`} role="img" aria-label={label} focusable={day !== undefined} {...hover.handlers} style={styles.slot}>
      <View style={[styles.half, { height: upPx, justifyContent: "flex-end" }]}>
        {tone === "gain" && barHeight > 0 ? <View testID={`bar-mark-${date}`} style={[styles.bar, styles.barUp, { height: barHeight, backgroundColor: colors.gainMark }, hover.active && styles.barLift]} /> : null}
      </View>
      <View style={[styles.half, { height: downPx, justifyContent: "flex-start" }]}>
        {tone === "loss" && barHeight > 0 ? <View testID={`bar-mark-${date}`} style={[styles.bar, styles.barDown, { height: barHeight, backgroundColor: colors.lossMark }, hover.active && styles.barLift]} /> : null}
      </View>
      <AppText variant="tiny" tone="muted" style={styles.tick} numeric>
        {showLabel ? Number(date.slice(8, 10)) : " "}
      </AppText>
      {hover.active && day && pnl !== null ? (
        <Tooltip testID={`bar-tooltip-${date}`} align={align}>
          <AppText variant="tiny" tone="inverse">
            {dayLabel(date)}
          </AppText>
          <AppText variant="label" tone="inverse">
            {formatMoneyDec(pnl, ACCOUNT_CURRENCY, true)}
          </AppText>
          <AppText variant="tiny" tone="inverse">
            {tradesLabel(day.trade_count)} · {day.wins}W {day.losses}L {day.breakeven}BE
          </AppText>
        </Tooltip>
      ) : null}
    </Pressable>
  );
}

/**
 * Daily net P&L as thin bars around a zero line: gains rise in blue, losses fall in red. One scale, one
 * axis. Heights come from exact decimal ratios. Every value is also in the table view and each bar's
 * label, and the tooltip is a convenience on top of those, never the only way to read a value.
 */
export function DailyPnlChart({ month, days }: { month: MonthRef; days: readonly DaySummary[] }) {
  const { narrow } = useLayout();
  const byDate = new Map(days.map((day) => [day.date, day]));
  const { maxGain: upMax, maxLoss: downMax } = dayStats(days);
  const total = upMax + downMax;
  // The zero line sits where the gain and loss ranges meet, so equal heights mean equal amounts above and below it.
  const upPx = total === 0n ? PLOT_HEIGHT / 2 : clamp(toSteps(upMax, total, PLOT_HEIGHT), upMax > 0n ? 24 : 10, PLOT_HEIGHT - (downMax > 0n ? 24 : 10));
  const downPx = PLOT_HEIGHT - upPx;
  const count = daysInMonth(month);
  return (
    <View testID="daily-chart" style={styles.chart}>
      <View style={[styles.axis, { height: PLOT_HEIGHT }]}>
        {upMax > 0n ? (
          <AppText variant="tiny" tone="muted" style={[styles.axisLabel, { top: 0 }]} numeric testID="axis-max">
            {formatMoneyDec(upMax, ACCOUNT_CURRENCY, true)}
          </AppText>
        ) : null}
        <AppText variant="tiny" tone="muted" style={[styles.axisLabel, { top: upPx - 8 }]} numeric>
          {formatMoneyDec(0n, ACCOUNT_CURRENCY)}
        </AppText>
        {downMax > 0n ? (
          <AppText variant="tiny" tone="muted" style={[styles.axisLabel, { bottom: 0 }]} numeric testID="axis-min">
            {formatMoneyDec(-downMax, ACCOUNT_CURRENCY)}
          </AppText>
        ) : null}
      </View>
      <View style={styles.plot}>
        <View style={[styles.baseline, { top: upPx }]} />
        {days.length === 0 ? (
          <AppText variant="small" tone="secondary" style={[styles.emptyHint, { top: Math.max(upPx - 30, 0) }]} testID="daily-chart-empty">
            No closed trades this month
          </AppText>
        ) : null}
        <View style={styles.slots}>
          {Array.from({ length: count }, (_, index) => {
            const day = index + 1;
            const date = isoDate(month.year, month.month, day);
            return (
              <Slot
                key={date}
                date={date}
                day={byDate.get(date)}
                upPx={upPx}
                downPx={downPx}
                upMax={upMax}
                downMax={downMax}
                align={index > count / 2 ? "right" : "left"}
                showLabel={!narrow || day === 1 || day % 5 === 0}
              />
            );
          })}
        </View>
      </View>
    </View>
  );
}

/**
 * The table twin of the chart and the calendar: one row per day that has closed trades, with exact
 * amounts. Given `noteDays`, days that only have a note get a row too and a Notes column appears. Given
 * `eventDays`, so do days that only have news or calendar events, with News and Events columns.
 */
export function DailyTable({ days, noteDays, eventDays }: { days: readonly DaySummary[]; noteDays?: ReadonlySet<string>; eventDays?: ReadonlyMap<string, DayEvents> }) {
  const byDate = new Map(days.map((day) => [day.date, day]));
  const dates = [...new Set([...byDate.keys(), ...(noteDays ?? []), ...(eventDays?.keys() ?? [])])].sort();
  if (dates.length === 0) {
    return (
      <AppText tone="secondary" testID="daily-table-empty">
        {eventDays ? "No closed trades, notes or events this month." : noteDays ? "No closed trades or notes this month." : "No closed trades this month."}
      </AppText>
    );
  }
  const headings = ["Day", "Trades", "Wins / losses / even", "Net P&L", ...(noteDays ? ["Notes"] : []), ...(eventDays ? ["News", "Calendar"] : [])];
  const table = (
    <View role="table" aria-label="Daily P&L" testID="daily-table" style={eventDays ? styles.wideTable : undefined}>
      <View role="row" style={[styles.tableRow, styles.tableHead]}>
        {headings.map((heading) => (
          <AppText key={heading} role="columnheader" variant="label" tone="secondary" style={[styles.cell, heading === "Net P&L" && styles.rightText]}>
            {heading}
          </AppText>
        ))}
      </View>
      {dates.map((date) => {
        const day = byDate.get(date);
        return (
          <View key={date} role="row" style={styles.tableRow} testID={`daily-row-${date}`}>
            <View role="cell" style={styles.cell}>
              <TextLink href={`/day/${date}`} label={dayLabel(date)} testID={`daily-link-${date}`} />
            </View>
            <AppText role="cell" numeric style={styles.cell} tone={day ? "primary" : "muted"}>
              {day ? day.trade_count : "–"}
            </AppText>
            <AppText role="cell" numeric style={styles.cell} tone={day ? "primary" : "muted"}>
              {day ? `${day.wins} / ${day.losses} / ${day.breakeven}` : "–"}
            </AppText>
            <View role="cell" style={[styles.cell, styles.right]}>
              <PnlAmount value={day?.pnl} testID={`daily-pnl-${date}`} />
            </View>
            {noteDays ? (
              <AppText role="cell" style={styles.cell} tone={noteDays.has(date) ? "primary" : "muted"} testID={`daily-note-${date}`}>
                {noteDays.has(date) ? "Has a note" : "–"}
              </AppText>
            ) : null}
            {eventDays ? <EventCells events={eventDays.get(date)} date={date} /> : null}
          </View>
        );
      })}
    </View>
  );
  // Seven columns do not fit a phone: like the trades table, this one scrolls sideways there instead of crushing its columns.
  return eventDays ? (
    <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={styles.scrollContent}>
      {table}
    </ScrollView>
  ) : (
    table
  );
}

/** The News and Calendar cells of a table row: news by impact ("2 high, 1 low") and the titles of the personal events. */
function EventCells({ events, date }: { events: DayEvents | undefined; date: string }) {
  const news = events && events.news.total > 0 ? newsBreakdown(events.news) : null;
  const titles = events && events.personal > 0 ? events.titles.join(", ") : null;
  return (
    <>
      <AppText role="cell" style={styles.cell} tone={news ? "primary" : "muted"} testID={`daily-news-${date}`}>
        {news ?? "–"}
      </AppText>
      <AppText role="cell" style={styles.cell} tone={titles ? "primary" : "muted"} testID={`daily-events-${date}`}>
        {titles ?? "–"}
      </AppText>
    </>
  );
}

const styles = StyleSheet.create({
  nav: { flexDirection: "row", alignItems: "center", gap: space.sm, flexWrap: "wrap" },
  monthLabel: { minWidth: 140, textAlign: "center" },
  chart: { flexDirection: "row", gap: space.sm },
  axis: { width: AXIS_WIDTH, position: "relative" },
  axisLabel: { position: "absolute", right: space.sm, textAlign: "right" },
  plot: { flex: 1, position: "relative" },
  emptyHint: { position: "absolute", left: 0, right: 0, textAlign: "center" },
  baseline: { position: "absolute", left: 0, right: 0, height: 1, backgroundColor: colors.baseline },
  slots: { flexDirection: "row" },
  slot: { flex: 1, paddingHorizontal: 1, position: "relative" },
  half: { width: "100%", alignItems: "center" },
  bar: { width: "100%", maxWidth: 20 },
  barUp: { borderTopLeftRadius: 4, borderTopRightRadius: 4 },
  barDown: { borderBottomLeftRadius: 4, borderBottomRightRadius: 4 },
  barLift: { opacity: 0.8 },
  tick: { textAlign: "center", marginTop: space.xs, fontSize: 11 },
  scrollContent: { minWidth: "100%" },
  wideTable: { minWidth: 900, width: "100%" },
  tableRow: { flexDirection: "row", alignItems: "center", paddingVertical: space.sm, borderBottomWidth: 1, borderBottomColor: colors.grid },
  tableHead: { borderBottomColor: colors.baseline },
  cell: { flex: 1, paddingHorizontal: space.sm },
  right: { alignItems: "flex-end" },
  rightText: { textAlign: "right" },
});
