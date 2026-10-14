import { StyleSheet, View } from "react-native";

import { type Impact, impactLabel } from "../lib/events";
import { colors, radius } from "../theme";
import { AppText } from "./text";

const FILLED: Record<Impact, number> = { low: 1, medium: 2, high: 3, holiday: 0, unknown: 0 };
const BAR_HEIGHTS = [5, 8, 11] as const;

/**
 * How much a news release can move the market, as rising bars filled up to its level: one for low, two for medium, three
 * for high. Colour (the amber ramp in theme.ts) is a third channel on top of the bars and the words. A holiday is a boxed
 * H and an impact the feed invented is a boxed question mark: neither is a level on the scale.
 */
export function ImpactGlyph({ impact, testID }: { impact: Impact; testID?: string }) {
  const label = impactLabel(impact);
  if (impact === "holiday" || impact === "unknown") {
    return (
      <View role="img" aria-label={label} testID={testID} style={styles.box}>
        <AppText variant="tiny" tone="secondary" bold style={styles.boxText}>
          {impact === "holiday" ? "H" : "?"}
        </AppText>
      </View>
    );
  }
  const filled = FILLED[impact];
  return (
    <View role="img" aria-label={label} testID={testID} style={styles.bars}>
      {BAR_HEIGHTS.map((height, index) => (
        <View key={index} testID={testID ? `${testID}-bar-${index}` : undefined} style={[styles.bar, { height, backgroundColor: index < filled ? colors.impact[impact] : colors.grid }]} />
      ))}
    </View>
  );
}

/** A glyph with the number of releases at that level, on a neutral chip: the same on a gain, a loss or an empty day. */
export function ImpactBadge({ impact, count, showCount = true, testID, countTestID }: { impact: Impact; count: number; showCount?: boolean; testID?: string; countTestID?: string }) {
  return (
    <View testID={testID} style={styles.badge}>
      <ImpactGlyph impact={impact} testID={testID ? `${testID}-glyph` : undefined} />
      {showCount ? (
        <AppText variant="tiny" numeric bold testID={countTestID}>
          {count}
        </AppText>
      ) : null}
    </View>
  );
}

/** A ring: an event from the owner's own calendar. Ink, not a data colour, so it never reads as a gain, a loss or news. */
export function PersonalMark({ size = 9, testID }: { size?: number; testID?: string }) {
  return <View role="img" aria-label="personal event" testID={testID} style={{ width: size, height: size, borderRadius: size / 2, borderWidth: 2, borderColor: colors.ink }} />;
}

/** A ring and, when there is room, the title of the day's first personal event with how many more there are, on the same neutral chip as the news. */
export function PersonalBadge({ title, more = 0, testID, titleTestID }: { title?: string; more?: number; testID?: string; titleTestID?: string }) {
  return (
    <View testID={testID} style={[styles.badge, styles.personal]}>
      <PersonalMark size={8} />
      {title ? (
        <AppText variant="tiny" numberOfLines={1} style={styles.personalTitle} testID={titleTestID}>
          {title}
        </AppText>
      ) : null}
      {title && more > 0 ? (
        <AppText variant="tiny" bold style={styles.personalMore} testID={titleTestID ? `${titleTestID}-more` : undefined}>
          +{more}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bars: { flexDirection: "row", alignItems: "flex-end", gap: 2 },
  bar: { width: 3, borderRadius: 1 },
  box: { width: 14, height: 14, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.inkSecondary, alignItems: "center", justifyContent: "center" },
  boxText: { fontSize: 9, lineHeight: 11 },
  badge: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 4, paddingVertical: 1, borderRadius: radius.sm, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.hairline },
  personal: { alignSelf: "flex-start", maxWidth: "100%" },
  personalTitle: { flexShrink: 1 },
  personalMore: { flexShrink: 0 },
});
