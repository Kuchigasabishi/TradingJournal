import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { Pressable, ScrollView, StyleSheet, View } from "react-native";

import type { Trade } from "../api/client";
import { useTags, useTrades } from "../api/queries";
import { PAGE_SIZE } from "../config";
import { isIsoDay } from "../lib/calendar";
import { type TradeFilters, type TradeSort, DEFAULT_FILTERS, parseFilters, toApiQuery, toParams } from "../lib/filters";
import { formatPrice, formatQuantity, pricePlaces } from "../lib/money";
import { instantToText } from "../lib/time";
import { useServer } from "../state/providers";
import { colors, radius, space } from "../theme";
import { Button, Chip, LinkButton, Segmented, TextField, TextLink, rowField } from "../ui/controls";
import { EmptyState, ErrorState, LoadingState } from "../ui/feedback";
import { Card, Page } from "../ui/layout";
import { AppText } from "../ui/text";
import { PnlAmount, journalInstant, messageOf, useDocumentTitle } from "./common";
import { DeleteTradeDialog } from "./trade-delete";

type SortState = { field: TradeSort; order: "asc" | "desc"; onSort: (field: TradeSort) => void };

const COLUMNS = {
  date: { flex: 1.2 },
  instrument: { flex: 1.1 },
  side: { flex: 0.7 },
  lots: { flex: 0.8 },
  entry: { flex: 1 },
  exit: { flex: 1 },
  pnl: { flex: 1.4 },
  tags: { flex: 1.5 },
  actions: { flex: 1.3 },
} as const;

const PLAIN_HEADERS: { label: string; column: { flex: number }; right: boolean }[] = [
  { label: "Instrument", column: COLUMNS.instrument, right: false },
  { label: "Side", column: COLUMNS.side, right: false },
  { label: "Lots", column: COLUMNS.lots, right: true },
  { label: "Entry", column: COLUMNS.entry, right: true },
  { label: "Exit", column: COLUMNS.exit, right: true },
];

function SortHeader({ label, field, sort, align }: { label: string; field: TradeSort; sort: SortState; align?: "right" }) {
  const active = sort.field === field;
  const direction = active ? (sort.order === "asc" ? "ascending" : "descending") : null;
  return (
    <Pressable
      role="button"
      aria-label={direction ? `Sort by ${label}, currently ${direction}` : `Sort by ${label}`}
      testID={`sort-${field}`}
      onPress={() => sort.onSort(field)}
      style={[styles.sortButton, align === "right" && styles.sortRight]}
    >
      <AppText variant="label" tone={active ? "primary" : "secondary"}>
        {label}
      </AppText>
      <AppText variant="label" tone="primary" testID={`sort-${field}-arrow`}>
        {active ? (sort.order === "asc" ? "↑" : "↓") : ""}
      </AppText>
    </Pressable>
  );
}

function TagCells({ tags, id }: { tags: readonly string[]; id: number }) {
  const shown = tags.slice(0, 3);
  return (
    <View style={styles.tags} testID={`trade-tags-${id}`}>
      {shown.map((tag) => (
        <Chip key={tag} label={tag} />
      ))}
      {tags.length > shown.length ? (
        <AppText variant="tiny" tone="secondary">
          +{tags.length - shown.length}
        </AppText>
      ) : null}
    </View>
  );
}

function TradeRow({ trade, timeZone, places, onDelete }: { trade: Trade; timeZone: string; places: number; onDelete: (trade: Trade) => void }) {
  const [date = "", time = ""] = instantToText(journalInstant(trade), timeZone).split(" ");
  const closed = trade.status === "closed";
  const name = `${trade.instrument} ${trade.side} trade`;
  const entry = formatPrice(trade.entry_price, places);
  const exit = formatPrice(trade.exit_price, places);
  return (
    <View role="row" style={styles.row} testID={`trade-row-${trade.id}`}>
      <View role="cell" style={[styles.cell, COLUMNS.date]}>
        <AppText numeric testID={`trade-date-${trade.id}`}>
          {date}
        </AppText>
        <AppText variant="tiny" tone="secondary" numeric>
          {time}
        </AppText>
      </View>
      <View role="cell" style={[styles.cell, COLUMNS.instrument]}>
        <TextLink href={`/trades/${trade.id}`} label={trade.instrument} variant="label" testID={`trade-link-${trade.id}`} />
      </View>
      <AppText role="cell" style={[styles.cell, COLUMNS.side]} testID={`trade-side-${trade.id}`}>
        {trade.side === "long" ? "Long" : "Short"}
      </AppText>
      <AppText role="cell" numeric style={[styles.cell, styles.rightText, COLUMNS.lots]} testID={`trade-lots-${trade.id}`}>
        {formatQuantity(trade.lot_size)}
      </AppText>
      <AppText role="cell" numeric style={[styles.cell, styles.rightText, COLUMNS.entry]} testID={`trade-entry-${trade.id}`}>
        {entry}
      </AppText>
      <AppText role="cell" numeric style={[styles.cell, styles.rightText, COLUMNS.exit]} testID={`trade-exit-${trade.id}`}>
        {exit}
      </AppText>
      <View role="cell" style={[styles.cell, styles.right, COLUMNS.pnl]}>
        {closed ? <PnlAmount value={trade.pnl} testID={`trade-pnl-${trade.id}`} /> : <Chip label="Open" testID={`trade-status-${trade.id}`} />}
      </View>
      <View role="cell" style={[styles.cell, COLUMNS.tags]}>
        <TagCells tags={trade.tags} id={trade.id} />
      </View>
      <View role="cell" style={[styles.cell, styles.actions, COLUMNS.actions]}>
        <LinkButton href={`/trades/${trade.id}?edit=1`} label="Edit" small ariaLabel={`Edit ${name}`} testID={`trade-edit-${trade.id}`} />
        <Button label="Delete" small variant="danger" ariaLabel={`Delete ${name}`} onPress={() => onDelete(trade)} testID={`trade-delete-${trade.id}`} />
      </View>
    </View>
  );
}

/** The trades as a table. Without `sort` the headers are plain; with it, Date and P&L sort. */
export function TradesTable({ trades, timeZone, sort, onDelete }: { trades: readonly Trade[]; timeZone: string; sort?: SortState; onDelete: (trade: Trade) => void }) {
  // One instrument is quoted to one precision, so its prices share a decimal count down the column (EURUSD: 5, USDJPY: 3).
  const prices = new Map<string, string[]>();
  for (const trade of trades) prices.set(trade.instrument, [...(prices.get(trade.instrument) ?? []), trade.entry_price, ...(trade.exit_price ? [trade.exit_price] : [])]);
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator contentContainerStyle={styles.scrollContent}>
      <View role="table" aria-label="Trades" style={styles.table} testID="trades-table">
        <View role="row" style={[styles.row, styles.head]}>
          <View role="columnheader" style={[styles.cell, COLUMNS.date]}>
            {sort ? <SortHeader label="Date" field="journal_at" sort={sort} /> : <AppText variant="label" tone="secondary">Date</AppText>}
          </View>
          {PLAIN_HEADERS.map((header) => (
            <AppText key={header.label} role="columnheader" variant="label" tone="secondary" style={[styles.cell, header.right && styles.rightText, header.column]}>
              {header.label}
            </AppText>
          ))}
          <View role="columnheader" style={[styles.cell, styles.right, COLUMNS.pnl]}>
            {sort ? <SortHeader label="P&L" field="pnl" sort={sort} align="right" /> : <AppText variant="label" tone="secondary">P&L</AppText>}
          </View>
          <AppText role="columnheader" variant="label" tone="secondary" style={[styles.cell, COLUMNS.tags]}>
            Tags
          </AppText>
          <View role="columnheader" style={[styles.cell, COLUMNS.actions]} />
        </View>
        {trades.map((trade) => (
          <TradeRow key={trade.id} trade={trade} timeZone={timeZone} places={pricePlaces(prices.get(trade.instrument) ?? [])} onDelete={onDelete} />
        ))}
      </View>
    </ScrollView>
  );
}

function Pager({ page, total, onPage }: { page: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const start = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const end = Math.min(page * PAGE_SIZE, total);
  return (
    <View style={styles.pager} testID="pager">
      <AppText tone="secondary" testID="pager-range">
        {total === 0 ? "No trades" : `${start}–${end} of ${total}`}
      </AppText>
      <View style={styles.pagerButtons}>
        <Button label="‹ Previous" small disabled={page <= 1} onPress={() => onPage(page - 1)} testID="pager-prev" />
        <AppText variant="small" tone="secondary" testID="pager-page">
          Page {page} of {pages}
        </AppText>
        <Button label="Next ›" small disabled={page >= pages} onPress={() => onPage(page + 1)} testID="pager-next" />
      </View>
    </View>
  );
}

type FilterBarProps = { filters: TradeFilters; tagNames: readonly string[]; onChange: (next: TradeFilters) => void };

function FilterBar({ filters, tagNames, onChange }: FilterBarProps) {
  const [instrument, setInstrument] = useState(filters.instrument ?? "");
  const [from, setFrom] = useState(filters.from ?? "");
  const [to, setTo] = useState(filters.to ?? "");

  // When the address changes from outside (Clear, a link), the typed text follows it.
  const urlText = `${filters.instrument ?? ""}|${filters.from ?? ""}|${filters.to ?? ""}`;
  const [seen, setSeen] = useState(urlText);
  if (seen !== urlText) {
    setSeen(urlText);
    setInstrument(filters.instrument ?? "");
    setFrom(filters.from ?? "");
    setTo(filters.to ?? "");
  }

  const fromError = from !== "" && !isIsoDay(from) ? "Use YYYY-MM-DD." : undefined;
  const toError = to !== "" && !isIsoDay(to) ? "Use YYYY-MM-DD." : from !== "" && to !== "" && !fromError && from > to ? "Must not be before the first day." : undefined;
  const active = filters.status || filters.side || filters.instrument || filters.from || filters.to || filters.tags.length > 0;

  const apply = () => {
    if (fromError || toError) return;
    onChange({ ...filters, instrument: instrument.trim() || undefined, from: from || undefined, to: to || undefined, page: 1 });
  };
  const toggleTag = (name: string) => {
    const has = filters.tags.includes(name);
    onChange({ ...filters, tags: has ? filters.tags.filter((tag) => tag !== name) : [...filters.tags, name], page: 1 });
  };

  return (
    <Card testID="filters">
      <View style={styles.filters}>
        <View style={styles.filterRow}>
          <View style={styles.filterGroup}>
            <AppText variant="label" tone="secondary">
              Status
            </AppText>
            <Segmented
              label="Status"
              value={filters.status ?? "all"}
              onChange={(value) => onChange({ ...filters, status: value === "all" ? undefined : value, page: 1 })}
              options={[
                { value: "all", label: "All", testID: "filter-status-all" },
                { value: "open", label: "Open", testID: "filter-status-open" },
                { value: "closed", label: "Closed", testID: "filter-status-closed" },
              ]}
            />
          </View>
          <View style={styles.filterGroup}>
            <AppText variant="label" tone="secondary">
              Side
            </AppText>
            <Segmented
              label="Side"
              value={filters.side ?? "any"}
              onChange={(value) => onChange({ ...filters, side: value === "any" ? undefined : value, page: 1 })}
              options={[
                { value: "any", label: "Any", testID: "filter-side-any" },
                { value: "long", label: "Long", testID: "filter-side-long" },
                { value: "short", label: "Short", testID: "filter-side-short" },
              ]}
            />
          </View>
        </View>
        <View style={styles.filterRow}>
          <TextField style={rowField} label="Instrument" testID="filter-instrument" value={instrument} onChangeText={setInstrument} onSubmitEditing={apply} placeholder="EURUSD" autoCapitalize="characters" />
          <TextField style={rowField} label="From day" testID="filter-from" value={from} onChangeText={setFrom} onSubmitEditing={apply} placeholder="YYYY-MM-DD" error={fromError} />
          <TextField style={rowField} label="To day" testID="filter-to" value={to} onChangeText={setTo} onSubmitEditing={apply} placeholder="YYYY-MM-DD" error={toError} />
        </View>
        {tagNames.length > 0 ? (
          <View style={styles.filterGroup}>
            <AppText variant="label" tone="secondary">
              Tags (a trade must have all selected)
            </AppText>
            <View style={styles.tagRow}>
              {tagNames.map((name) => (
                <Chip key={name} label={name} selected={filters.tags.includes(name)} onPress={() => toggleTag(name)} testID={`filter-tag-${name}`} />
              ))}
            </View>
          </View>
        ) : null}
        <View style={styles.filterActions}>
          <Button label="Apply filters" variant="primary" small onPress={apply} testID="filters-apply" />
          <Button label="Clear filters" small variant="ghost" disabled={!active && instrument === "" && from === "" && to === ""} onPress={() => onChange({ ...DEFAULT_FILTERS, sort: filters.sort, order: filters.order })} testID="filters-clear" />
        </View>
      </View>
    </Card>
  );
}

export function TradesScreen() {
  const params = useLocalSearchParams();
  const router = useRouter();
  const { timezone } = useServer();
  const filters = parseFilters(params);
  const query = useTrades(toApiQuery(filters, PAGE_SIZE));
  const tags = useTags();
  const [pendingDelete, setPendingDelete] = useState<Trade | null>(null);
  useDocumentTitle("Trades");

  const apply = (next: TradeFilters) => router.replace({ pathname: "/trades", params: toParams(next) });
  const onSort = (field: TradeSort) => apply({ ...filters, sort: field, order: filters.sort === field && filters.order === "desc" ? "asc" : "desc", page: 1 });
  const filtered = Boolean(filters.status || filters.side || filters.instrument || filters.from || filters.to || filters.tags.length > 0);
  const pages = query.data ? Math.max(1, Math.ceil(query.data.total / PAGE_SIZE)) : 1;

  return (
    <Page testID="trades">
      <View style={styles.titleRow}>
        <AppText variant="h1" role="heading" testID="page-title">
          Trades
        </AppText>
        <LinkButton href="/trades/new" label="New trade" variant="primary" testID="trades-new" />
      </View>
      <FilterBar filters={filters} tagNames={(tags.data ?? []).map((tag) => tag.name)} onChange={apply} />
      <Card padded={false} testID="trades-card">
        {query.isPending ? (
          <LoadingState label="Loading trades…" testID="trades-loading" />
        ) : query.isError ? (
          <ErrorState title="Could not load trades" detail={messageOf(query.error)} onRetry={() => void query.refetch()} testID="trades-error" retryTestID="trades-retry" />
        ) : query.data.total === 0 ? (
          filtered ? (
            <EmptyState title="No trades match these filters" hint="Loosen or clear a filter to see more." testID="trades-empty">
              <Button label="Clear filters" onPress={() => apply({ ...DEFAULT_FILTERS })} testID="trades-empty-clear" />
            </EmptyState>
          ) : (
            <EmptyState title="No trades yet" hint="Log a trade to start your journal." testID="trades-empty">
              <LinkButton href="/trades/new" label="Log your first trade" variant="primary" testID="trades-empty-new" />
            </EmptyState>
          )
        ) : query.data.items.length === 0 ? (
          <EmptyState title="That page is past the end" testID="trades-past-end">
            <Button label="Go to the last page" onPress={() => apply({ ...filters, page: pages })} testID="trades-last-page" />
          </EmptyState>
        ) : (
          <View style={query.isPlaceholderData ? styles.stale : undefined} aria-busy={query.isPlaceholderData}>
            <TradesTable trades={query.data.items} timeZone={timezone} sort={{ field: filters.sort, order: filters.order, onSort }} onDelete={setPendingDelete} />
          </View>
        )}
      </Card>
      {query.data && query.data.total > 0 ? <Pager page={filters.page} total={query.data.total} onPage={(page) => apply({ ...filters, page })} /> : null}
      <DeleteTradeDialog trade={pendingDelete} onClose={() => setPendingDelete(null)} />
    </Page>
  );
}

const styles = StyleSheet.create({
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: space.md },
  filters: { gap: space.lg },
  filterRow: { flexDirection: "row", flexWrap: "wrap", alignItems: "flex-start", gap: space.lg },
  filterGroup: { gap: space.xs },
  filterActions: { flexDirection: "row", alignItems: "center", gap: space.sm },
  tagRow: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  scrollContent: { minWidth: "100%" },
  table: { minWidth: 960, width: "100%" },
  row: { flexDirection: "row", alignItems: "center", minHeight: 52, paddingHorizontal: space.sm, borderBottomWidth: 1, borderBottomColor: colors.grid },
  head: { minHeight: 44, borderBottomColor: colors.baseline, backgroundColor: colors.sunken, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg },
  cell: { paddingHorizontal: space.sm, paddingVertical: space.sm },
  right: { alignItems: "flex-end" },
  rightText: { textAlign: "right" },
  actions: { flexDirection: "row", gap: space.sm, justifyContent: "flex-end" },
  tags: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.xs },
  sortButton: { flexDirection: "row", alignItems: "center", gap: space.xs, minHeight: 28 },
  sortRight: { justifyContent: "flex-end" },
  pager: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: space.md },
  pagerButtons: { flexDirection: "row", alignItems: "center", gap: space.md },
  stale: { opacity: 0.5 },
});
