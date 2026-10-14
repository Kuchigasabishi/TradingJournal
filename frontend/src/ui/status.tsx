import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";

import { colors, space } from "../theme";
import { AppText } from "./text";

/** A small "!" in a ring: status color is always paired with an icon and a label, never color alone. */
export function ErrorIcon() {
  return (
    <View style={styles.icon} aria-hidden>
      <AppText variant="tiny" tone="critical" bold>
        !
      </AppText>
    </View>
  );
}

export function ErrorText({ children, testID }: { children: ReactNode; testID?: string }) {
  return (
    <View style={styles.text} role="alert" testID={testID}>
      <ErrorIcon />
      <AppText variant="small" tone="critical" style={styles.message}>
        {children}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  icon: { width: 18, height: 18, borderRadius: 9, borderWidth: 1.5, borderColor: colors.critical, alignItems: "center", justifyContent: "center" },
  text: { flexDirection: "row", alignItems: "flex-start", gap: space.sm },
  message: { flexShrink: 1 },
});
