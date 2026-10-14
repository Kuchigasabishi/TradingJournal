import { useLocalSearchParams } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";

import type { Note, Trade } from "../api/client";
import { useCreateNote, useNotes, useTrades } from "../api/queries";
import { ACCOUNT_CURRENCY } from "../config";
import { addDays, dayLabel, isIsoDay } from "../lib/calendar";
import { sum } from "../lib/decimal";
import { formatMoneyDec } from "../lib/money";
import { eventQuery, parseEventFilters } from "../lib/events";
import { instantToText } from "../lib/time";
import { LIMITS, NOTES_TOO_LONG } from "../lib/validation";
import { useFlash, useServer } from "../state/providers";
import { colors, space } from "../theme";
import { Button, LinkButton, TextField, TextLink } from "../ui/controls";
import { StatTile } from "../ui/data";
import { ErrorState, LoadingState } from "../ui/feedback";
import { Card, Page, SectionHeader } from "../ui/layout";
import { AppText } from "../ui/text";
import { BackLink, NotFoundCard, first, messageOf, outcomeLabel, signMark, toDec, tradesLabel, useDocumentTitle } from "./common";
import { DayEventsCard } from "./events";
import { DeleteTradeDialog } from "./trade-delete";
import { TradesTable } from "./trades";

function NoteCard({ note, timeZone }: { note: Note; timeZone: string }) {
  return (
    <View style={styles.note} testID={`note-${note.id}`}>
      <AppText testID={`note-body-${note.id}`}>{note.body}</AppText>
      <View style={styles.noteMeta}>
        <AppText variant="tiny" tone="secondary">
          Saved {instantToText(note.updated_at, timeZone)}
        </AppText>
        <TextLink href={`/notes/${note.id}`} label="Open note" variant="small" testID={`note-open-${note.id}`} />
      </View>
    </View>
  );
}

function NoteComposer({ day }: { day: string }) {
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | undefined>();
  const create = useCreateNote();
  const flash = useFlash();

  const save = async () => {
    const text = body.trim();
    if (text === "") {
      setError("Write something first.");
      return;
    }
    if (text.length > LIMITS.notes) {
      setError(NOTES_TOO_LONG);
      return;
    }
    setError(undefined);
    try {
      await create.mutateAsync({ day, body: text });
      setBody("");
      flash.show("Note saved.");
    } catch (failure) {
      setError(messageOf(failure));
    }
  };

  return (
    <View style={styles.composer}>
      <TextField label="Add a note for this day" testID="field-day-note" value={body} onChangeText={setBody} error={error} multiline placeholder="How did the day go? What would you repeat or avoid?" autoCapitalize="sentences" />
      <View style={styles.composerActions}>
        <Button label="Save note" variant="primary" small onPress={() => void save()} loading={create.isPending} testID="note-save" />
      </View>
    </View>
  );
}

function DayContent({ date }: { date: string }) {
  const { timezone } = useServer();
  const trades = useTrades({ from: date, to: date, sort: "journal_at", order: "asc", limit: 500 });
  const notes = useNotes({ from: date, to: date, limit: 100 });
  const [pendingDelete, setPendingDelete] = useState<Trade | null>(null);

  const items = trades.data?.items ?? [];
  const closed = items.filter((trade) => trade.status === "closed");
  const stillOpen = items.length - closed.length;
  const pnls = closed.map((trade) => toDec(trade.pnl));
  const net = sum(pnls);
  const wins = pnls.filter((value) => value > 0n).length;
  const losses = pnls.filter((value) => value < 0n).length;
  const month = date.slice(0, 7);
  // The calendar this day was opened from kept some event filters; going back keeps them.
  const backQuery = eventQuery(parseEventFilters(useLocalSearchParams())).replace("?", "&");

  return (
    <Page testID="day">
      <BackLink href={`/calendar?month=${month}${backQuery}`} label="← Calendar" />
      <View style={styles.titleRow}>
        <AppText variant="h1" role="heading" testID="page-title">
          {dayLabel(date)}
        </AppText>
        <View style={styles.dayNav}>
          <LinkButton href={`/day/${addDays(date, -1)}`} label="‹ Previous day" small testID="day-prev" />
          <LinkButton href={`/day/${addDays(date, 1)}`} label="Next day ›" small testID="day-next" />
        </View>
      </View>
      <View style={styles.tiles}>
        <StatTile hero testID="day-net" label="Net P&L, closed trades" value={formatMoneyDec(net, ACCOUNT_CURRENCY, true)} mark={signMark(net)} caption={closed.length === 0 ? "No trades closed this day" : `${tradesLabel(closed.length)} closed`} />
        <StatTile testID="day-closed" label="Closed" value={String(closed.length)} caption={outcomeLabel(wins, losses, closed.length - wins - losses)} />
        <StatTile testID="day-open" label="Opened, still open" value={String(stillOpen)} />
      </View>
      <DayEventsCard date={date} />
      <Card padded={false} testID="day-trades">
        <View style={styles.cardHead}>
          <SectionHeader title="Trades" right={<LinkButton href={`/trades/new?day=${date}`} label="New trade on this day" small variant="primary" testID="day-new-trade" />} />
        </View>
        {trades.isPending ? (
          <LoadingState label="Loading trades…" testID="day-trades-loading" />
        ) : trades.isError ? (
          <ErrorState title="Could not load the trades" detail={messageOf(trades.error)} onRetry={() => void trades.refetch()} testID="day-trades-error" retryTestID="day-trades-retry" />
        ) : items.length === 0 ? (
          <View style={styles.empty}>
            <AppText tone="secondary" testID="day-trades-empty">
              No trades on this day.
            </AppText>
          </View>
        ) : (
          <TradesTable trades={items} timeZone={timezone} onDelete={setPendingDelete} />
        )}
      </Card>
      <Card testID="day-notes">
        <View style={styles.notes}>
          <SectionHeader title="Notes" />
          {notes.isPending ? (
            <LoadingState label="Loading notes…" testID="day-notes-loading" />
          ) : notes.isError ? (
            <ErrorState title="Could not load the notes" detail={messageOf(notes.error)} onRetry={() => void notes.refetch()} testID="day-notes-error" retryTestID="day-notes-retry" />
          ) : notes.data.items.length === 0 ? (
            <AppText tone="secondary" testID="day-notes-empty">
              No notes for this day yet.
            </AppText>
          ) : (
            notes.data.items.map((note) => <NoteCard key={note.id} note={note} timeZone={timezone} />)
          )}
          <NoteComposer day={date} />
        </View>
      </Card>
      <DeleteTradeDialog trade={pendingDelete} onClose={() => setPendingDelete(null)} />
    </Page>
  );
}

export function DayScreen() {
  const params = useLocalSearchParams<{ date?: string }>();
  const date = first(params.date);
  useDocumentTitle(isIsoDay(date) ? dayLabel(date) : "Not a day");
  if (!isIsoDay(date)) {
    return (
      <Page testID="day">
        <BackLink href="/calendar" label="← Calendar" />
        <NotFoundCard title="That is not a day" hint="Days are written YYYY-MM-DD, for example 2035-03-10." href="/calendar" label="Back to the calendar" />
      </Page>
    );
  }
  return <DayContent date={date} />;
}

const styles = StyleSheet.create({
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: space.md },
  dayNav: { flexDirection: "row", gap: space.sm },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: space.lg },
  cardHead: { padding: space.lg, borderBottomWidth: 1, borderBottomColor: colors.grid },
  empty: { padding: space.lg },
  notes: { gap: space.lg },
  note: { gap: space.sm, paddingBottom: space.md, borderBottomWidth: 1, borderBottomColor: colors.grid },
  noteMeta: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.md },
  composer: { gap: space.sm },
  composerActions: { flexDirection: "row" },
});
