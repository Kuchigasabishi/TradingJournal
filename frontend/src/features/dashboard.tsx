import { useLocalSearchParams } from "expo-router";
import { StyleSheet, View } from "react-native";

import type { MonthSummary, Trade } from "../api/client";
import type { TradeListQuery } from "../api/endpoints";
import { useMonth, useTrades } from "../api/queries";
import { ACCOUNT_CURRENCY } from "../config";
import { type MonthRef, dayLabel, monthLabel, monthOf, parseMonth } from "../lib/calendar";
import { percent } from "../lib/decimal";
import { formatMoneyDec, formatPriceSet, formatQuantity } from "../lib/money";
import { averagePerTrade, dayStats, percentSteps } from "../lib/summary";
import { instantToText, todayIn } from "../lib/time";
import { useServer } from "../state/providers";
import { colors, space } from "../theme";
import { LinkButton, TextLink } from "../ui/controls";
import { Meter, StatTile } from "../ui/data";
import { EmptyState, ErrorState, LoadingState } from "../ui/feedback";
import { Card, Page, SectionHeader } from "../ui/layout";
import { AppText } from "../ui/text";
import { first, messageOf, outcomeLabel, plural, signMark, toDec, tradesLabel, useDocumentTitle } from "./common";
import { ChartViewToggle, DailyPnlChart, DailyTable, MonthNav, useChartView } from "./months";

// The two counts that answer "how many trades are active, how many are done": the totals of a one-row page.
const OPEN_TRADES: TradeListQuery = { status: "open", sort: "opened_at", order: "desc", limit: 5 };
const CLOSED_COUNT: TradeListQuery = { status: "closed", limit: 1 };

type TradesQuery = ReturnType<typeof useTrades>;

function OpenTradeRow({ trade, timeZone }: { trade: Trade; timeZone: string }) {
  const [entry = ""] = formatPriceSet([trade.entry_price]);
  return (
    <View style={styles.openRow} testID={`open-trade-${trade.id}`}>
      <View style={styles.openMain}>
        <TextLink href={`/trades/${trade.id}`} label={trade.instrument} variant="label" testID={`open-trade-link-${trade.id}`} />
        <AppText variant="small" tone="secondary">
          {trade.side === "long" ? "Long" : "Short"} · {formatQuantity(trade.lot_size)} lots at {entry}
        </AppText>
      </View>
      <AppText variant="small" tone="secondary" numeric>
        Opened {instantToText(trade.opened_at, timeZone)}
      </AppText>
    </View>
  );
}

function OpenTradesCard({ query, timeZone }: { query: TradesQuery; timeZone: string }) {
  const total = query.data?.total ?? 0;
  return (
    <Card testID="open-trades">
      <View style={styles.cardStack}>
        <SectionHeader title="Open trades" right={<LinkButton href="/trades?status=open" label="View all" small testID="open-trades-all" />} />
        {query.isPending ? (
          <LoadingState label="Loading open trades…" />
        ) : query.isError ? (
          <ErrorState title="Could not load open trades" detail={messageOf(query.error)} onRetry={() => void query.refetch()} retryTestID="open-trades-retry" />
        ) : query.data.items.length === 0 ? (
          <AppText tone="secondary" testID="open-trades-empty">
            No open trades. Everything you have logged is closed.
          </AppText>
        ) : (
          <View>
            {query.data.items.map((trade) => (
              <OpenTradeRow key={trade.id} trade={trade} timeZone={timeZone} />
            ))}
            {total > query.data.items.length ? (
              <AppText variant="small" tone="secondary" style={styles.more}>
                and {total - query.data.items.length} more
              </AppText>
            ) : null}
          </View>
        )}
      </View>
    </Card>
  );
}

type PerformanceProps = {
  month: MonthRef;
  data: MonthSummary;
  openCount: number | null;
  closedTotal: number | null;
};

/** The month at a glance: one hero figure, then supporting figures in two rows, then the day-by-day picture. */
function Performance({ month, data, openCount, closedTotal }: PerformanceProps) {
  const [view, setView] = useChartView();
  const { totals } = data;
  const net = toDec(totals.pnl);
  const closed = totals.trade_count;
  const winRate = percent(totals.wins, closed);
  const average = averagePerTrade(net, closed);
  const { best, worst } = dayStats(data.days);
  const label = monthLabel(month);
  const money = (value: bigint, maxFraction = 8) => formatMoneyDec(value, ACCOUNT_CURRENCY, true, maxFraction);
  return (
    <View style={styles.stack}>
      <View style={styles.tiles}>
        <StatTile
          hero
          testID="stat-net"
          label={`Net P&L, ${label}`}
          value={money(net)}
          mark={signMark(net)}
          caption={closed === 0 ? "No closed trades this month" : `${tradesLabel(closed)} closed`}
        />
        <StatTile testID="stat-win-rate" label="Win rate" value={winRate === null ? "–" : `${winRate}%`} caption={closed === 0 ? "No closed trades this month" : `${plural(totals.wins, "win")} of ${tradesLabel(closed)} closed`}>
          <Meter percent={percentSteps(totals.wins, closed)} label="Win rate" testID="stat-win-rate-meter" />
        </StatTile>
        <StatTile
          testID="stat-average"
          label="Average per trade"
          value={average === null ? "–" : money(average, 2)}
          mark={average === null ? undefined : signMark(average)}
          caption={average === null ? "No closed trades this month" : "net P&L divided by closed trades, to the cent"}
        />
      </View>
      <View style={styles.tiles}>
        <StatTile testID="stat-open" label="Open trades" value={openCount === null ? "–" : String(openCount)} caption={closedTotal === null ? undefined : `${closedTotal} closed in total`} />
        <StatTile testID="stat-closed" label={`Closed in ${label}`} value={String(closed)} caption={outcomeLabel(totals.wins, totals.losses, totals.breakeven)} />
        <StatTile
          testID="stat-best-day"
          label="Best day"
          value={best && best.pnl > 0n ? money(best.pnl) : "–"}
          mark={best && best.pnl > 0n ? "gain" : undefined}
          caption={best && best.pnl > 0n ? dayLabel(best.date) : "No winning days"}
        />
        <StatTile
          testID="stat-worst-day"
          label="Worst day"
          value={worst && worst.pnl < 0n ? money(worst.pnl) : "–"}
          mark={worst && worst.pnl < 0n ? "loss" : undefined}
          caption={worst && worst.pnl < 0n ? dayLabel(worst.date) : "No losing days"}
        />
      </View>
      <Card testID="daily-card">
        <View style={styles.cardStack}>
          <SectionHeader title="Daily P&L" right={<ChartViewToggle value={view} onChange={setView} />} />
          {view === "chart" ? <DailyPnlChart month={month} days={data.days} /> : <DailyTable days={data.days} />}
          <AppText variant="tiny" tone="secondary">
            Closed trades, on the day each was closed ({data.timezone}).
          </AppText>
        </View>
      </Card>
    </View>
  );
}

export function Dashboard() {
  const params = useLocalSearchParams<{ month?: string }>();
  const { timezone } = useServer();
  const current = monthOf(todayIn(timezone));
  const month = parseMonth(first(params.month)) ?? current;
  const summary = useMonth(month.year, month.month);
  const open = useTrades(OPEN_TRADES);
  const closedAll = useTrades(CLOSED_COUNT);
  useDocumentTitle("Dashboard");
  const journalEmpty = open.data?.total === 0 && closedAll.data?.total === 0;

  return (
    <Page testID="dashboard">
      <View style={styles.titleRow}>
        <AppText variant="h1" role="heading" testID="page-title">
          Dashboard
        </AppText>
        <MonthNav month={month} current={current} />
      </View>
      {journalEmpty ? (
        <Card testID="dashboard-empty">
          <EmptyState title="Your journal is empty" hint="Log a trade and the dashboard fills in: net P&L, win rate, a daily chart.">
            <LinkButton href="/trades/new" label="Log your first trade" variant="primary" testID="empty-new-trade" />
          </EmptyState>
        </Card>
      ) : summary.isPending ? (
        <LoadingState label="Loading the month…" testID="dashboard-loading" />
      ) : summary.isError ? (
        <ErrorState title="Could not load the month" detail={messageOf(summary.error)} onRetry={() => void summary.refetch()} testID="dashboard-error" retryTestID="dashboard-retry" />
      ) : (
        <View style={summary.isPlaceholderData ? styles.stale : undefined} aria-busy={summary.isPlaceholderData} testID="dashboard-content">
          <Performance month={month} data={summary.data} openCount={open.data?.total ?? null} closedTotal={closedAll.data?.total ?? null} />
        </View>
      )}
      {journalEmpty ? null : <OpenTradesCard query={open} timeZone={timezone} />}
    </Page>
  );
}

const styles = StyleSheet.create({
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: space.md },
  stack: { gap: space.lg },
  cardStack: { gap: space.md },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: space.lg },
  stale: { opacity: 0.5 },
  openRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: space.sm, paddingVertical: space.sm, borderBottomWidth: 1, borderBottomColor: colors.grid },
  openMain: { gap: 2 },
  more: { paddingTop: space.sm },
});
