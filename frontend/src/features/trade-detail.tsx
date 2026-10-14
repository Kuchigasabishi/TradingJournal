import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";

import { ApiError, type Trade } from "../api/client";
import { useCreateTrade, useTrade, useUpdateTrade } from "../api/queries";
import { isIsoDay } from "../lib/calendar";
import { formatPriceSet, formatQuantity } from "../lib/money";
import { instantToText } from "../lib/time";
import { type TradePayload, diffPayload, validateTrade } from "../lib/validation";
import { useFlash, useServer } from "../state/providers";
import { space } from "../theme";
import { Button, Chip, Detail, LinkButton } from "../ui/controls";
import { ErrorState, LoadingState } from "../ui/feedback";
import { Card, Page } from "../ui/layout";
import { AppText } from "../ui/text";
import { BackLink, NotFoundCard, PnlAmount, first, messageOf, newTradeValues, tradeToFormValues, useDocumentTitle } from "./common";
import { DeleteTradeDialog } from "./trade-delete";
import { TradeForm } from "./trade-form";

export function NewTradeScreen() {
  const params = useLocalSearchParams<{ day?: string }>();
  const { timezone } = useServer();
  const router = useRouter();
  const flash = useFlash();
  const create = useCreateTrade();
  const dayParam = first(params.day);
  useDocumentTitle("New trade");
  // Coming from a calendar day, the trade starts on that day.
  const day = isIsoDay(dayParam) ? dayParam : undefined;

  const save = async (payload: TradePayload) => {
    const trade = await create.mutateAsync(payload);
    flash.show("Trade saved.");
    router.replace(`/trades/${trade.id}`);
  };

  return (
    <Page testID="trade-new">
      <BackLink href={day ? `/day/${day}` : "/trades"} label={day ? "← Back to the day" : "← Trades"} />
      <AppText variant="h1" role="heading" testID="page-title">
        New trade
      </AppText>
      <Card>
        <TradeForm initial={newTradeValues(timezone, day)} timeZone={timezone} submitLabel="Save trade" onSubmit={save} onCancel={() => router.replace(day ? `/day/${day}` : "/trades")} />
      </Card>
    </Page>
  );
}

function TradeView({ trade, timeZone, onDelete }: { trade: Trade; timeZone: string; onDelete: () => void }) {
  const closed = trade.status === "closed";
  const [entry = "–", exit = "–"] = formatPriceSet([trade.entry_price, trade.exit_price]);
  return (
    <Card testID="trade-view">
      <View style={styles.stack}>
        <View style={styles.head}>
          <View style={styles.headMain}>
            <AppText variant="h1" role="heading" testID="trade-title">
              {trade.instrument}
            </AppText>
            <View style={styles.chips}>
              <Chip label={trade.side === "long" ? "Long" : "Short"} testID="trade-side" />
              <Chip label={closed ? "Closed" : "Open"} testID="trade-status" />
            </View>
          </View>
          {closed ? (
            <View style={styles.pnl}>
              <AppText variant="small" tone="secondary">
                Realized P&L
              </AppText>
              <PnlAmount value={trade.pnl} variant="h1" testID="detail-pnl" />
            </View>
          ) : null}
        </View>
        <View style={styles.grid}>
          <Detail label="Lot size" testID="detail-lot-size">
            {formatQuantity(trade.lot_size)}
          </Detail>
          <Detail label="Entry price" testID="detail-entry-price">
            {entry}
          </Detail>
          <Detail label="Exit price" testID="detail-exit-price">
            {exit}
          </Detail>
          <Detail label={`Opened (${timeZone})`} testID="detail-opened">
            {instantToText(trade.opened_at, timeZone)}
          </Detail>
          <Detail label={`Closed (${timeZone})`} testID="detail-closed">
            {trade.closed_at ? instantToText(trade.closed_at, timeZone) : "–"}
          </Detail>
        </View>
        <Detail label="Notes" testID="detail-notes">
          {trade.notes ? <AppText>{trade.notes}</AppText> : "–"}
        </Detail>
        <Detail label="Tags" testID="detail-tags">
          {trade.tags.length === 0 ? (
            "–"
          ) : (
            <View style={styles.chips}>
              {trade.tags.map((tag) => (
                <Chip key={tag} label={tag} testID={`detail-tag-${tag}`} />
              ))}
            </View>
          )}
        </Detail>
        <AppText variant="tiny" tone="secondary" testID="detail-updated">
          Saved {instantToText(trade.created_at, timeZone)}; last changed {instantToText(trade.updated_at, timeZone)}.
        </AppText>
        <View style={styles.actions}>
          <LinkButton href={`/trades/${trade.id}?edit=1`} label="Edit trade" variant="primary" testID="detail-edit" />
          <Button label="Delete trade" variant="danger" onPress={onDelete} testID="detail-delete" />
        </View>
      </View>
    </Card>
  );
}

function TradeEditor({ trade, timeZone }: { trade: Trade; timeZone: string }) {
  const router = useRouter();
  const flash = useFlash();
  const update = useUpdateTrade();
  const initial = tradeToFormValues(trade, timeZone);
  // What the stored trade looks like as a form payload, so a PATCH carries only what the person changed.
  const stored = validateTrade(initial, timeZone);
  const back = `/trades/${trade.id}`;

  const save = async (payload: TradePayload) => {
    const changes = stored.ok ? diffPayload(stored.payload, payload) : payload;
    if (Object.keys(changes).length === 0) {
      flash.show("Nothing was changed.", "info");
      router.replace(back);
      return;
    }
    await update.mutateAsync({ id: trade.id, body: changes });
    flash.show("Trade updated.");
    router.replace(back);
  };

  return (
    <Card testID="trade-edit">
      <TradeForm initial={initial} timeZone={timeZone} submitLabel="Save changes" onSubmit={save} onCancel={() => router.replace(back)} />
    </Card>
  );
}

export function TradeScreen() {
  const params = useLocalSearchParams<{ id?: string; edit?: string }>();
  const { timezone } = useServer();
  const router = useRouter();
  const id = Number(first(params.id));
  const editing = first(params.edit) === "1";
  const query = useTrade(id);
  const [pendingDelete, setPendingDelete] = useState<Trade | null>(null);
  const validId = Number.isInteger(id) && id >= 1;
  useDocumentTitle(query.data ? `${query.data.instrument} trade` : "Trade");
  const missing = !validId || (query.isError && query.error instanceof ApiError && query.error.status === 404);

  return (
    <Page testID="trade-detail">
      <BackLink href="/trades" label="← Trades" />
      {missing ? (
        <NotFoundCard title="Trade not found" hint="It may have been deleted, or the address is wrong." href="/trades" label="Back to trades" />
      ) : query.isPending ? (
        <LoadingState label="Loading the trade…" testID="trade-loading" />
      ) : query.isError ? (
        <ErrorState title="Could not load the trade" detail={messageOf(query.error)} onRetry={() => void query.refetch()} testID="trade-error" retryTestID="trade-retry" />
      ) : editing ? (
        <>
          <AppText variant="h1" role="heading" testID="page-title">
            Edit {query.data.instrument}
          </AppText>
          <TradeEditor trade={query.data} timeZone={timezone} />
        </>
      ) : (
        <TradeView trade={query.data} timeZone={timezone} onDelete={() => setPendingDelete(query.data)} />
      )}
      <DeleteTradeDialog trade={pendingDelete} onClose={() => setPendingDelete(null)} onDeleted={() => router.replace("/trades")} />
    </Page>
  );
}

const styles = StyleSheet.create({
  stack: { gap: space.xl },
  head: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", flexWrap: "wrap", gap: space.lg },
  headMain: { gap: space.sm },
  chips: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.sm },
  pnl: { gap: space.xs, alignItems: "flex-end" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: space.xl },
  actions: { flexDirection: "row", alignItems: "center", gap: space.sm },
});
