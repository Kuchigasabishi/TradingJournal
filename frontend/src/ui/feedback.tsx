import type { ReactNode } from "react";
import { ActivityIndicator, Modal, Pressable, StyleSheet, View } from "react-native";

import { colors, radius, space } from "../theme";
import { Button } from "./controls";
import { ErrorIcon } from "./status";
import { AppText } from "./text";

export function LoadingState({ label = "Loading…", testID }: { label?: string; testID?: string }) {
  return (
    <View style={styles.center} testID={testID} role="status">
      <ActivityIndicator color={colors.inkSecondary} />
      <AppText tone="secondary">{label}</AppText>
    </View>
  );
}

export function ErrorState({
  title = "Something went wrong",
  detail,
  onRetry,
  testID,
  retryTestID,
}: {
  title?: string;
  detail?: string;
  onRetry?: () => void;
  testID?: string;
  retryTestID?: string;
}) {
  return (
    <View style={[styles.center, styles.errorBox]} testID={testID} role="alert">
      <View style={styles.errorTitle}>
        <ErrorIcon />
        <AppText variant="h3">{title}</AppText>
      </View>
      {detail ? <AppText tone="secondary">{detail}</AppText> : null}
      {onRetry ? <Button label="Retry" onPress={onRetry} testID={retryTestID} /> : null}
    </View>
  );
}

export function EmptyState({ title, hint, children, testID }: { title: string; hint?: string; children?: ReactNode; testID?: string }) {
  return (
    <View style={styles.center} testID={testID}>
      <AppText variant="h3">{title}</AppText>
      {hint ? <AppText tone="secondary">{hint}</AppText> : null}
      {children}
    </View>
  );
}

export type BannerKind = "success" | "error" | "info";

export function Banner({ kind, message, testID, onDismiss }: { kind: BannerKind; message: string; testID?: string; onDismiss?: () => void }) {
  return (
    <View style={[styles.banner, kind === "error" && styles.bannerError, kind === "success" && styles.bannerSuccess]} testID={testID} role={kind === "error" ? "alert" : "status"}>
      {kind === "error" ? <ErrorIcon /> : null}
      <AppText variant="small" style={styles.bannerMessage} tone={kind === "error" ? "critical" : "primary"}>
        {message}
      </AppText>
      {onDismiss ? (
        <Pressable onPress={onDismiss} role="button" aria-label="Dismiss" testID={testID ? `${testID}-dismiss` : undefined} style={styles.dismiss}>
          <AppText variant="small" tone="secondary">
            Dismiss
          </AppText>
        </Pressable>
      ) : null}
    </View>
  );
}

/** A modal confirmation. Alert.alert does nothing on the web, so destructive actions use this. */
export function ConfirmDialog({
  visible,
  title,
  message,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
  testID = "confirm-dialog",
}: {
  visible: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  testID?: string;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.overlay}>
        <View style={styles.dialog} testID={testID} role="alertdialog" aria-label={title}>
          <AppText variant="h2">{title}</AppText>
          <AppText tone="secondary">{message}</AppText>
          <View style={styles.dialogActions}>
            <Button label="Cancel" onPress={onCancel} testID={`${testID}-cancel`} />
            <Button label={confirmLabel} variant="danger" onPress={onConfirm} loading={busy} testID={`${testID}-confirm`} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  center: { alignItems: "center", justifyContent: "center", gap: space.md, padding: space.xl },
  errorBox: { backgroundColor: colors.criticalWash, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.hairline },
  errorTitle: { flexDirection: "row", alignItems: "center", gap: space.sm },
  banner: { flexDirection: "row", alignItems: "center", gap: space.sm, paddingVertical: space.sm, paddingHorizontal: space.md, borderRadius: radius.md, backgroundColor: colors.sunken },
  bannerSuccess: { borderLeftWidth: 4, borderLeftColor: colors.goodText },
  bannerError: { backgroundColor: colors.criticalWash, borderLeftWidth: 4, borderLeftColor: colors.critical },
  bannerMessage: { flex: 1 },
  dismiss: { paddingHorizontal: space.sm, paddingVertical: space.xs },
  overlay: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(11, 11, 11, 0.45)", padding: space.lg },
  dialog: { width: "100%", maxWidth: 440, gap: space.md, padding: space.xl, borderRadius: radius.lg, backgroundColor: colors.surface },
  dialogActions: { flexDirection: "row", justifyContent: "flex-end", gap: space.sm, marginTop: space.sm },
});
