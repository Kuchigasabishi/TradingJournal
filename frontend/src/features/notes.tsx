import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, View } from "react-native";

import { ApiError, type Note } from "../api/client";
import { useDeleteNote, useNote, useUpdateNote } from "../api/queries";
import { dayLabel, isIsoDay } from "../lib/calendar";
import { instantToText } from "../lib/time";
import { LIMITS, NOTES_TOO_LONG } from "../lib/validation";
import { useFlash, useServer } from "../state/providers";
import { space } from "../theme";
import { Button, TextField } from "../ui/controls";
import { Banner, ConfirmDialog, ErrorState, LoadingState } from "../ui/feedback";
import { Card, Page } from "../ui/layout";
import { AppText } from "../ui/text";
import { BackLink, NotFoundCard, first, messageOf, useDocumentTitle } from "./common";

type Problems = { day?: string; body?: string; general?: string };

function NoteEditor({ note, timeZone }: { note: Note; timeZone: string }) {
  const [day, setDay] = useState(note.day);
  const [body, setBody] = useState(note.body);
  const [problems, setProblems] = useState<Problems>({});
  const [confirming, setConfirming] = useState(false);
  const update = useUpdateNote();
  const remove = useDeleteNote();
  const router = useRouter();
  const flash = useFlash();

  const save = async () => {
    const dayText = day.trim();
    const text = body.trim();
    const found: Problems = {};
    if (!isIsoDay(dayText)) found.day = "Use YYYY-MM-DD, for example 2035-03-10.";
    if (text === "") found.body = "Write something first.";
    else if (text.length > LIMITS.notes) found.body = NOTES_TOO_LONG;
    if (found.day || found.body) {
      setProblems(found);
      return;
    }
    // Only what changed is sent, so a PATCH never rewrites what the person left alone.
    const changes: { day?: string; body?: string } = {};
    if (dayText !== note.day) changes.day = dayText;
    if (text !== note.body) changes.body = text;
    if (Object.keys(changes).length === 0) {
      setProblems({});
      flash.show("Nothing was changed.", "info");
      return;
    }
    try {
      const saved = await update.mutateAsync({ id: note.id, body: changes });
      flash.show("Note saved.");
      router.replace(`/day/${saved.day}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422 && Array.isArray(error.detail)) {
        const fields: Problems = {};
        for (const item of error.detail as { loc?: unknown[]; msg?: string }[]) {
          const name = (item.loc ?? []).map(String).find((part) => part === "day" || part === "body");
          if (name === "day" || name === "body") fields[name] ??= item.msg ?? "Invalid value.";
        }
        setProblems(Object.keys(fields).length > 0 ? fields : { general: messageOf(error) });
      } else {
        setProblems({ general: messageOf(error) });
      }
    }
  };

  const destroy = async () => {
    try {
      await remove.mutateAsync(note.id);
      flash.show("Note deleted.");
      router.replace(`/day/${note.day}`);
    } catch (error) {
      setConfirming(false);
      setProblems({ general: messageOf(error) });
    }
  };

  return (
    <Card testID="note-editor">
      <View style={styles.form}>
        <TextField label="Day" testID="field-note-day" value={day} onChangeText={setDay} error={problems.day} hint={isIsoDay(day.trim()) ? dayLabel(day.trim()) : "YYYY-MM-DD"} />
        <TextField label="Note" testID="field-note-body" value={body} onChangeText={setBody} error={problems.body} multiline autoCapitalize="sentences" />
        {problems.general ? <Banner kind="error" message={problems.general} testID="note-error" /> : null}
        <AppText variant="tiny" tone="secondary" testID="note-saved">
          Saved {instantToText(note.created_at, timeZone)}; last changed {instantToText(note.updated_at, timeZone)}.
        </AppText>
        <View style={styles.actions}>
          <Button label="Save note" variant="primary" onPress={() => void save()} loading={update.isPending} testID="note-update" />
          <Button label="Cancel" onPress={() => router.replace(`/day/${note.day}`)} testID="note-cancel" />
          <View style={styles.spacer} />
          <Button label="Delete note" variant="danger" onPress={() => setConfirming(true)} testID="note-delete" />
        </View>
      </View>
      <ConfirmDialog
        visible={confirming}
        title="Delete this note?"
        message={`The note for ${dayLabel(note.day)} will be removed. This cannot be undone.`}
        confirmLabel="Delete note"
        busy={remove.isPending}
        onConfirm={() => void destroy()}
        onCancel={() => setConfirming(false)}
        testID="delete-note-dialog"
      />
    </Card>
  );
}

export function NoteScreen() {
  const params = useLocalSearchParams<{ id?: string }>();
  const { timezone } = useServer();
  const id = Number(first(params.id));
  const query = useNote(id);
  const validId = Number.isInteger(id) && id >= 1;
  useDocumentTitle(query.data ? `Note for ${dayLabel(query.data.day)}` : "Note");
  const missing = !validId || (query.isError && query.error instanceof ApiError && query.error.status === 404);

  return (
    <Page testID="note-detail">
      <BackLink href={query.data ? `/day/${query.data.day}` : "/calendar"} label={query.data ? "← Back to the day" : "← Calendar"} />
      <AppText variant="h1" role="heading" testID="page-title">
        {query.data ? `Note for ${dayLabel(query.data.day)}` : "Note"}
      </AppText>
      {missing ? (
        <NotFoundCard title="Note not found" hint="It may have been deleted, or the address is wrong." href="/calendar" label="Back to the calendar" />
      ) : query.isPending ? (
        <LoadingState label="Loading the note…" testID="note-loading" />
      ) : query.isError ? (
        <ErrorState title="Could not load the note" detail={messageOf(query.error)} onRetry={() => void query.refetch()} testID="note-load-error" retryTestID="note-retry" />
      ) : (
        <NoteEditor key={query.data.id} note={query.data} timeZone={timezone} />
      )}
    </Page>
  );
}

const styles = StyleSheet.create({
  form: { gap: space.lg },
  actions: { flexDirection: "row", alignItems: "center", gap: space.sm },
  spacer: { flex: 1 },
});
