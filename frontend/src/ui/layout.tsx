import type { ReactNode } from "react";
import { ScrollView, StyleSheet, View, type StyleProp, type ViewStyle } from "react-native";

import { colors, radius, space } from "../theme";
import { AppText } from "./text";

/** A scrolling page with a centered, width-limited column. */
export function Page({ children, testID }: { children: ReactNode; testID?: string }) {
  return (
    <ScrollView style={styles.scroll} contentContainerStyle={styles.pageContent} testID={testID}>
      <View style={styles.column}>{children}</View>
    </ScrollView>
  );
}

export function Card({ children, style, testID, padded = true }: { children: ReactNode; style?: StyleProp<ViewStyle>; testID?: string; padded?: boolean }) {
  return (
    <View style={[styles.card, padded ? styles.padded : styles.clip, style]} testID={testID}>
      {children}
    </View>
  );
}

export function SectionHeader({ title, right, testID }: { title: string; right?: ReactNode; testID?: string }) {
  return (
    <View style={styles.sectionHeader}>
      <AppText variant="h2" testID={testID} role="heading">
        {title}
      </AppText>
      {right}
    </View>
  );
}

export function Row({ children, style, wrap = false }: { children: ReactNode; style?: StyleProp<ViewStyle>; wrap?: boolean }) {
  return <View style={[styles.row, wrap && styles.wrap, style]}>{children}</View>;
}

const styles = StyleSheet.create({
  scroll: { flex: 1, backgroundColor: colors.page },
  pageContent: { alignItems: "center", paddingHorizontal: space.lg, paddingTop: space.xl, paddingBottom: space.xxl * 2 },
  column: { width: "100%", maxWidth: 1180, gap: space.xl },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.hairline },
  padded: { padding: space.lg },
  clip: { overflow: "hidden" },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.md },
  row: { flexDirection: "row", alignItems: "center", gap: space.sm },
  wrap: { flexWrap: "wrap" },
});
