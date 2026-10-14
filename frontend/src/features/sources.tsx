import { useEffect, useState } from "react";
import { ActivityIndicator, StyleSheet, View } from "react-native";

import { ApiError, type SourceName, type SourceStatus, type SyncResponse, type SyncResult } from "../api/client";
import { useSources, useSync } from "../api/queries";
import { instantToText } from "../lib/time";
import { useServer } from "../state/providers";
import { colors, space } from "../theme";
import { Button } from "../ui/controls";
import { ErrorState, LoadingState } from "../ui/feedback";
import { Card, SectionHeader } from "../ui/layout";
import { ErrorIcon } from "../ui/status";
import { AppText } from "../ui/text";
import { messageOf, plural } from "./common";

type Tone = "good" | "bad" | "busy" | "idle";

/** How a feed stands, in one word and a tone: what its last attempt did, or that it is working on one now. */
function standing(source: SourceStatus): { label: string; tone: Tone } {
  if (!source.enabled) return { label: "Off", tone: "idle" };
  if (source.state !== "idle") return { label: "Syncing…", tone: "busy" };
  switch (source.status) {
    case "ok":
      return { label: "Up to date", tone: "good" };
    case "never":
      return { label: "Not synced yet", tone: "idle" };
    case "throttled":
      return { label: "Rate limited", tone: "bad" };
    case "bad_content":
      return { label: "Unusable answer", tone: "bad" };
    default:
      return { label: "Failed", tone: "bad" };
  }
}

/** A status with a mark that is never colour alone: a spinner, a dot, a "!" in a ring, or a dash. */
function StatusPill({ label, tone, testID }: { label: string; tone: Tone; testID: string }) {
  return (
    <View style={styles.pill}>
      {tone === "busy" ? <ActivityIndicator size="small" color={colors.inkSecondary} /> : tone === "bad" ? <ErrorIcon /> : <View style={[styles.dot, tone === "good" ? styles.dotGood : styles.dotIdle]} />}
      <AppText variant="small" tone={tone === "bad" ? "critical" : "primary"} testID={testID}>
        {label}
      </AppText>
    </View>
  );
}

function SourceRow({ source, timeZone }: { source: SourceStatus; timeZone: string }) {
  const { label, tone } = standing(source);
  const name = source.source;
  const next = source.next_due_at ? instantToText(source.next_due_at, timeZone) : null;
  return (
    <View style={styles.source} testID={`source-${name}`}>
      <View style={styles.sourceHead}>
        <AppText variant="h3">{source.label}</AppText>
        <StatusPill label={label} tone={tone} testID={`source-status-${name}`} />
        <AppText variant="small" tone="secondary" testID={`source-count-${name}`}>
          {plural(source.event_count, "event")}
        </AppText>
      </View>
      {!source.enabled ? (
        <AppText variant="small" tone="secondary" testID={`source-off-${name}`}>
          {source.disabled_reason ?? "This feed is switched off."}
        </AppText>
      ) : (
        <>
          <AppText variant="small" tone="secondary" testID={`source-last-${name}`}>
            {source.last_success_at ? `Last synced ${instantToText(source.last_success_at, timeZone)}` : "Never synced"}
            {next ? ` · next automatic sync ${next}` : ""}
          </AppText>
          {source.status !== "ok" && source.status !== "never" && source.message ? (
            <AppText variant="small" tone="critical" testID={`source-message-${name}`}>
              {`Last attempt failed: ${source.message}. The ${plural(source.event_count, "event")} already stored are kept.${next ? ` Trying again ${next}.` : ""}`}
            </AppText>
          ) : null}
        </>
      )}
    </View>
  );
}

const REASON: Record<Exclude<SyncResult["outcome"], "queued">, (result: SyncResult) => string> = {
  cooldown: (result) => `it was synced a moment ago (try again in ${result.retry_after_seconds ?? 1} s)`,
  running: () => "it is already syncing",
  disabled: () => "it is switched off",
};

/** What a request that was accepted left out: a feed still inside its cooldown, already busy or switched off. */
function leftOut(response: SyncResponse, labels: ReadonlyMap<SourceName, string>): string {
  return response.sources
    .filter((result) => result.outcome !== "queued")
    .map((result) => ` ${labels.get(result.source) ?? result.source} was not synced: ${REASON[result.outcome as Exclude<SyncResult["outcome"], "queued">](result)}.`)
    .join("");
}

/** The server's refusal (429 inside the cooldown, 409 when nothing could be queued) as a sentence, and how long to wait. */
function refusal(error: unknown): { text: string; wait: number } {
  if (error instanceof ApiError && (error.status === 429 || error.status === 409)) {
    const results = (error.detail as Partial<SyncResponse> | undefined)?.sources ?? [];
    if (error.status === 429) {
      const wait = Math.max(1, ...results.map((result) => (result.outcome === "cooldown" ? (result.retry_after_seconds ?? 0) : 0)));
      return { text: `That was synced a moment ago. You can sync again in ${wait} s.`, wait };
    }
    const allOff = results.length > 0 && results.every((result) => result.outcome === "disabled");
    return { text: allOff ? "No feed is switched on, so there is nothing to sync." : "A sync is already running.", wait: 0 };
  }
  return { text: messageOf(error), wait: 0 };
}

type Note = { kind: "info" | "error"; text: string };

/**
 * The feeds behind the calendar: where each stands, and a button to refresh them now. A refresh is a request the server
 * answers at once and carries out on its own time, so this follows the feed status until the feeds are done, and the
 * events reload by themselves (see useRefreshEventsOnSync).
 */
export function SourcesCard() {
  const { timezone } = useServer();
  const sources = useSources();
  const sync = useSync();
  const [note, setNote] = useState<Note | null>(null);
  const [cooling, setCooling] = useState(0);
  // Which feeds this card asked for, and when each last tried before that: a feed that has tried since has finished.
  // State, not a ref: the request's own refresh may already have seen the end of a quick sync, and setting this must re-run the check below.
  const [asked, setAsked] = useState<Record<string, string | null> | null>(null);

  const rows = sources.data ?? [];
  const busy = rows.some((source) => source.state !== "idle");
  const anyEnabled = rows.some((source) => source.enabled);
  const labels = new Map(rows.map((source) => [source.source, source.label] as const));

  useEffect(() => {
    if (cooling === 0) return;
    const timer = setTimeout(() => {
      setCooling(0);
      setNote(null);
    }, cooling * 1000);
    return () => clearTimeout(timer);
  }, [cooling]);

  useEffect(() => {
    if (asked === null) return;
    const finished = Object.entries(asked).every(([name, before]) => {
      const row = rows.find((source) => source.source === name);
      return row !== undefined && row.state === "idle" && row.last_attempt_at !== before;
    });
    if (finished) {
      setAsked(null);
      setNote({ kind: "info", text: "Sync finished." });
    }
  }, [rows, asked]);

  const press = () => {
    setNote(null);
    const before = Object.fromEntries(rows.map((source) => [source.source, source.last_attempt_at]));
    sync.mutate(undefined, {
      onSuccess: (response) => {
        setAsked(Object.fromEntries(response.sources.filter((result) => result.outcome === "queued").map((result) => [result.source, before[result.source] ?? null])));
        setNote({ kind: "info", text: `Sync started.${leftOut(response, labels)}` });
      },
      onError: (error) => {
        const { text, wait } = refusal(error);
        setNote({ kind: "error", text });
        setCooling(wait);
      },
    });
  };

  return (
    <Card testID="sources-card">
      <View style={styles.card}>
        <SectionHeader title="Sources" right={<Button label="Sync now" variant="primary" small onPress={press} loading={sync.isPending || busy} disabled={!anyEnabled || cooling > 0} testID="sync-now" />} />
        {note ? (
          <AppText variant="small" tone={note.kind === "error" ? "critical" : "secondary"} role={note.kind === "error" ? "alert" : "status"} testID="sync-message">
            {note.text}
          </AppText>
        ) : null}
        {sources.isPending ? (
          <LoadingState label="Loading the feeds…" testID="sources-loading" />
        ) : sources.isError ? (
          <ErrorState title="Could not load the feeds" detail={messageOf(sources.error)} onRetry={() => void sources.refetch()} testID="sources-error" retryTestID="sources-retry" />
        ) : (
          rows.map((source) => <SourceRow key={source.source} source={source} timeZone={timezone} />)
        )}
        <AppText variant="tiny" tone="secondary">
          Times are in {timezone}. News is read from the public weekly calendar. The personal calendar is read through its secret iCal address, which stays on the server and is never shown here.
        </AppText>
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { gap: space.md },
  source: { gap: space.xs, paddingTop: space.sm, borderTopWidth: 1, borderTopColor: colors.grid },
  sourceHead: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.md },
  pill: { flexDirection: "row", alignItems: "center", gap: space.xs },
  dot: { width: 10, height: 10, borderRadius: 5 },
  dotGood: { backgroundColor: colors.goodText },
  dotIdle: { backgroundColor: colors.baseline },
});
