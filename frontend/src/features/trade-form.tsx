import { useState } from "react";
import { StyleSheet, View } from "react-native";

import { ApiError } from "../api/client";
import { useTags } from "../api/queries";
import { ACCOUNT_CURRENCY } from "../config";
import { type FieldErrors, type TradeFormValues, type TradePayload, fieldsFromDetail, validateTrade } from "../lib/validation";
import { space } from "../theme";
import { Button, Segmented, TagEditor, TextField, Toggle, rowField } from "../ui/controls";
import { Banner } from "../ui/feedback";
import { ErrorText } from "../ui/status";
import { AppText } from "../ui/text";
import { messageOf, nowText } from "./common";

type Props = {
  initial: TradeFormValues;
  timeZone: string;
  submitLabel: string;
  /** Saves the trade. A rejected promise keeps the form open: a 422 is mapped onto the fields, anything else shows as a message. */
  onSubmit: (payload: TradePayload) => Promise<void>;
  onCancel: () => void;
};

/**
 * The trade form, for both new and existing trades. What is typed is checked here first (the same rules the
 * server applies) and sent as exact decimal strings; whatever the server still rejects lands on the same fields.
 */
export function TradeForm({ initial, timeZone, submitLabel, onSubmit, onCancel }: Props) {
  const [values, setValues] = useState<TradeFormValues>(initial);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [general, setGeneral] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const tags = useTags();

  const set = <K extends keyof TradeFormValues>(key: K, value: TradeFormValues[K]) => setValues((current) => ({ ...current, [key]: value }));
  const setClosed = (closed: boolean) => setValues((current) => ({ ...current, closed, closedAt: closed && current.closedAt === "" ? nowText(timeZone) : current.closedAt }));

  const submit = async () => {
    const result = validateTrade(values, timeZone);
    if (!result.ok) {
      setErrors(result.errors);
      setGeneral([]);
      return;
    }
    setErrors({});
    setGeneral([]);
    setSaving(true);
    try {
      await onSubmit(result.payload);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const mapped = fieldsFromDetail(error.detail);
        setErrors(mapped.fields);
        setGeneral(mapped.general);
      } else {
        setGeneral([messageOf(error)]);
      }
    } finally {
      setSaving(false);
    }
  };

  const errorCount = Object.keys(errors).length;
  const timeHint = `${timeZone}, written YYYY-MM-DD HH:mm`;

  return (
    <View style={styles.form} testID="trade-form">
      <View style={styles.row}>
        <TextField style={[rowField, styles.instrument]} label="Instrument" testID="field-instrument" value={values.instrument} onChangeText={(text) => set("instrument", text)} error={errors.instrument} placeholder="EURUSD" autoCapitalize="characters" />
        <View style={styles.sideField}>
          <AppText variant="label" tone="secondary">
            Side
          </AppText>
          <Segmented
            label="Side"
            value={values.side}
            onChange={(side) => set("side", side)}
            options={[
              { value: "long", label: "Long", testID: "side-long" },
              { value: "short", label: "Short", testID: "side-short" },
            ]}
          />
        </View>
      </View>
      <View style={styles.row}>
        <TextField style={rowField} label="Lot size" testID="field-lot-size" value={values.lotSize} onChangeText={(text) => set("lotSize", text)} error={errors.lotSize} hint="For example 0.10" inputMode="decimal" />
        <TextField style={rowField} label="Entry price" testID="field-entry-price" value={values.entryPrice} onChangeText={(text) => set("entryPrice", text)} error={errors.entryPrice} hint="For example 1.08425" inputMode="decimal" />
        <TextField style={rowField} label="Opened" testID="field-opened-at" value={values.openedAt} onChangeText={(text) => set("openedAt", text)} error={errors.openedAt} hint={timeHint} />
      </View>
      <Toggle label="This trade is closed" value={values.closed} onChange={setClosed} testID="field-closed" />
      {values.closed ? (
        <View style={styles.row}>
          <TextField style={rowField} label="Exit price" testID="field-exit-price" value={values.exitPrice} onChangeText={(text) => set("exitPrice", text)} error={errors.exitPrice} inputMode="decimal" />
          <TextField style={rowField} label="Closed" testID="field-closed-at" value={values.closedAt} onChangeText={(text) => set("closedAt", text)} error={errors.closedAt} hint={timeHint} />
          <TextField style={rowField} label="Realized P&L" testID="field-pnl" value={values.pnl} onChangeText={(text) => set("pnl", text)} error={errors.pnl} prefix={ACCOUNT_CURRENCY} hint="What the broker booked; negative for a loss" inputMode="decimal" />
        </View>
      ) : null}
      <TextField label="Notes" testID="field-notes" value={values.notes} onChangeText={(text) => set("notes", text)} error={errors.notes} multiline placeholder="Why you took it, what you saw, what you would change" autoCapitalize="sentences" />
      <TagEditor tags={values.tags} onChange={(next) => set("tags", next)} suggestions={(tags.data ?? []).map((tag) => tag.name)} error={errors.tags} />
      {errorCount > 0 ? <ErrorText testID="form-summary">{errorCount === 1 ? "One field needs attention." : `${errorCount} fields need attention.`}</ErrorText> : null}
      {general.map((message) => (
        <Banner key={message} kind="error" message={message} testID="form-error" />
      ))}
      <View style={styles.actions}>
        <Button label={submitLabel} variant="primary" onPress={() => void submit()} loading={saving} testID="form-submit" />
        <Button label="Cancel" onPress={onCancel} disabled={saving} testID="form-cancel" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  form: { gap: space.lg },
  row: { flexDirection: "row", flexWrap: "wrap", alignItems: "flex-start", gap: space.lg },
  instrument: { maxWidth: 360 },
  sideField: { gap: space.xs },
  actions: { flexDirection: "row", alignItems: "center", gap: space.sm },
});
