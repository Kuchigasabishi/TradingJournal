import { Slot, type ErrorBoundaryProps } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { StyleSheet, View } from "react-native";

import { AppShell } from "../features/shell";
import { FlashProvider, QueryProvider, ServerProvider } from "../state/providers";
import { colors } from "../theme";
import { ErrorState } from "../ui/feedback";

/** Anything that throws while rendering ends up here instead of a blank page. */
export function ErrorBoundary({ error, retry }: ErrorBoundaryProps) {
  return (
    <View style={styles.boundary}>
      <ErrorState title="Something broke" detail={error.message} onRetry={() => void retry()} testID="app-error" retryTestID="app-error-retry" />
    </View>
  );
}

export default function RootLayout() {
  return (
    <QueryProvider>
      <FlashProvider>
        <ServerProvider>
          <AppShell>
            <Slot />
          </AppShell>
        </ServerProvider>
      </FlashProvider>
      <StatusBar style="dark" />
    </QueryProvider>
  );
}

const styles = StyleSheet.create({
  boundary: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.page },
});
