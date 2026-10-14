import { type Href } from "expo-router";
import { useEffect } from "react";
import { StyleSheet, View } from "react-native";

import { ApiError, NetworkError, type Trade } from "../api/client";
import { ACCOUNT_CURRENCY } from "../config";
import { parse } from "../lib/decimal";
import { type Tone, formatMoneyDec, formatPriceSet, plainDecimal, toneOf } from "../lib/money";
import { formatWall, instantToText, wallClock } from "../lib/time";
import { type TradeFormValues } from "../lib/validation";
import { space } from "../theme";
import { LinkButton, TextLink } from "../ui/controls";
import { TrendMark } from "../ui/data";
import { EmptyState } from "../ui/feedback";
import { AppText, type Variant } from "../ui/text";

export const first = (value: string | string[] | undefined): string | undefined => (Array.isArray(value) ? value[0] : value);

/** A decimal string from the API as an exact value. A missing amount counts as zero. */
export const toDec = (text: string | null | undefined): bigint => (text === null || text === undefined ? 0n : (parse(text) ?? 0n));

export const plural = (count: number, one: string, many = `${one}s`): string => `${count} ${count === 1 ? one : many}`;

export const tradesLabel = (count: number): string => plural(count, "trade");

/** "7 wins · 4 losses · 1 breakeven" */
export const outcomeLabel = (wins: number, losses: number, breakeven: number): string => `${plural(wins, "win")} · ${plural(losses, "loss", "losses")} · ${breakeven} breakeven`;

/** The triangle for a figure, or nothing for exactly zero: a zero total has no direction to point in. */
export const signMark = (value: bigint): Tone | undefined => (value === 0n ? undefined : toneOf(value));

/** Names the browser tab, so a tab, a history entry and a screenshot all say which screen they show. */
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    if (typeof document !== "undefined") document.title = `${title} · Trading Journal`;
  }, [title]);
}

/** One sentence for the person using the app, whatever went wrong. */
export function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    if (Array.isArray(error.detail)) return error.detail.map((item) => (item as { msg?: string }).msg ?? "Invalid value.").join(" ");
    return error.message;
  }
  if (error instanceof NetworkError) return "Cannot reach the server. Check that it is running, then try again.";
  return "Something went wrong. Try again.";
}

/** A signed amount with its triangle. The number is exact text from the server, formatted without ever becoming a float. */
export function PnlAmount({ value, testID, variant = "body", color }: { value: string | null | undefined; testID?: string; variant?: Variant; color?: string }) {
  const amount = value === null || value === undefined ? null : parse(value);
  if (amount === null) {
    return (
      <AppText tone="muted" variant={variant} testID={testID}>
        –
      </AppText>
    );
  }
  return (
    <View style={styles.amount}>
      <TrendMark tone={toneOf(amount)} color={color} />
      <AppText numeric bold variant={variant} testID={testID} style={color ? { color } : undefined}>
        {formatMoneyDec(amount, ACCOUNT_CURRENCY, true)}
      </AppText>
    </View>
  );
}

export function BackLink({ href, label }: { href: Href; label: string }) {
  return <TextLink href={href} label={label} variant="small" testID="back-link" />;
}

/** What a screen shows for an address that names nothing: a deleted trade, a malformed id. */
export function NotFoundCard({ title, hint, href, label }: { title: string; hint: string; href: Href; label: string }) {
  return (
    <EmptyState title={title} hint={hint} testID="not-found">
      <LinkButton href={href} label={label} testID="not-found-link" />
    </EmptyState>
  );
}

/** When a trade belongs on the calendar: the day it closed, or opened while it is still open. */
export function journalInstant(trade: Trade): string {
  return trade.closed_at ?? trade.opened_at;
}

/** A stored trade as form text. The server keeps the shortest exact form (0.1, 28.5); the form pads it (0.10, 28.50) without changing the value. */
export function tradeToFormValues(trade: Trade, timeZone: string): TradeFormValues {
  const prices = formatPriceSet([trade.entry_price, trade.exit_price], { grouping: false });
  return {
    instrument: trade.instrument,
    side: trade.side,
    lotSize: plainDecimal(trade.lot_size, 2),
    entryPrice: prices[0] ?? "",
    openedAt: instantToText(trade.opened_at, timeZone),
    closed: trade.status === "closed",
    exitPrice: trade.exit_price === null ? "" : (prices[1] ?? ""),
    closedAt: trade.closed_at ? instantToText(trade.closed_at, timeZone) : "",
    pnl: plainDecimal(trade.pnl, 2),
    notes: trade.notes ?? "",
    tags: [...trade.tags],
  };
}

export function nowText(timeZone: string): string {
  return formatWall(wallClock(Date.now(), timeZone));
}

/** A blank form. Coming from a calendar day, the open time starts at 09:00 on that day. */
export function newTradeValues(timeZone: string, day?: string): TradeFormValues {
  return {
    instrument: "",
    side: "long",
    lotSize: "",
    entryPrice: "",
    openedAt: day ? `${day} 09:00` : nowText(timeZone),
    closed: false,
    exitPrice: "",
    closedAt: "",
    pnl: "",
    notes: "",
    tags: [],
  };
}

const styles = StyleSheet.create({
  amount: { flexDirection: "row", alignItems: "center", gap: space.sm },
});
