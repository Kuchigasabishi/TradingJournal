import { useState, type ReactNode } from "react";
import { StyleSheet, View } from "react-native";

import type { Tone } from "../lib/money";
import { colors, radius, space } from "../theme";
import { AppText } from "./text";
import { Card } from "./layout";

/**
 * A triangle that carries the sign next to an amount, so a gain or loss never depends on color alone.
 * Drawn with borders: no icon font to load, and the same on every platform.
 */
export function TrendMark({ tone, size = 5, color, testID }: { tone: Tone; size?: number; color?: string; testID?: string }) {
  const label = tone === "gain" ? "gain" : tone === "loss" ? "loss" : "break-even";
  if (tone === "flat") {
    // Two short bars, "=": a single dash beside an amount reads as a minus sign.
    const bar = { height: 2, borderRadius: 1, backgroundColor: color ?? colors.inkMuted };
    return (
      <View role="img" aria-label={label} testID={testID} style={[styles.even, { width: size * 2 }]}>
        <View style={bar} />
        <View style={bar} />
      </View>
    );
  }
  const arrow = {
    width: 0,
    height: 0,
    borderLeftWidth: size,
    borderRightWidth: size,
    borderLeftColor: "transparent",
    borderRightColor: "transparent",
    ...(tone === "gain"
      ? { borderBottomWidth: size * 1.6, borderBottomColor: color ?? colors.gainMark }
      : { borderTopWidth: size * 1.6, borderTopColor: color ?? colors.lossMark }),
  };
  return <View role="img" aria-label={label} testID={testID} style={arrow} />;
}

/** A single figure with its label. `hero` is the one number a view leads with; `mark` puts a sign triangle before it. */
export function StatTile({
  label,
  value,
  caption,
  hero = false,
  mark,
  children,
  testID,
}: {
  label: string;
  value: string;
  caption?: string;
  hero?: boolean;
  mark?: Tone;
  children?: ReactNode;
  testID?: string;
}) {
  return (
    <Card style={hero ? styles.hero : styles.tile} testID={testID}>
      <AppText variant="small" tone="secondary">
        {label}
      </AppText>
      <View style={styles.valueRow}>
        {mark ? <TrendMark tone={mark} size={hero ? 10 : 6} testID={testID ? `${testID}-mark` : undefined} /> : null}
        <AppText variant={hero ? "hero" : "h1"} testID={testID ? `${testID}-value` : undefined} style={hero ? undefined : styles.tileValue}>
          {value}
        </AppText>
      </View>
      {caption ? (
        <AppText variant="tiny" tone="secondary" testID={testID ? `${testID}-caption` : undefined}>
          {caption}
        </AppText>
      ) : null}
      {children}
    </Card>
  );
}

/** A ratio against 100: the fill is blue, the track a lighter step of the same ramp. */
export function Meter({ percent, label, testID }: { percent: number; label: string; testID?: string }) {
  const clamped = Math.min(Math.max(Math.round(percent), 0), 100);
  return (
    <View role="meter" aria-label={label} aria-valuenow={clamped} aria-valuemin={0} aria-valuemax={100} testID={testID} style={styles.track}>
      <View style={[styles.fill, { width: `${clamped}%` }]} />
    </View>
  );
}

/** Hover and keyboard focus as one piece of state, so a tooltip shows for either. */
export function useHover() {
  const [active, setActive] = useState(false);
  return {
    active,
    handlers: {
      onHoverIn: () => setActive(true),
      onHoverOut: () => setActive(false),
      onFocus: () => setActive(true),
      onBlur: () => setActive(false),
    },
  };
}

/** Floats above its parent. Near the right edge of a chart or grid, `align="right"` keeps it from overflowing. */
export function Tooltip({ children, testID, align = "left" }: { children: ReactNode; testID?: string; align?: "left" | "right" }) {
  return (
    <View style={[styles.tooltip, align === "right" ? styles.tooltipRight : styles.tooltipLeft]} pointerEvents="none" testID={testID} role="tooltip">
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  even: { gap: 2, justifyContent: "center" },
  hero: { gap: space.xs, flexGrow: 2, flexBasis: 320, justifyContent: "center" },
  tile: { gap: space.xs, flexGrow: 1, flexBasis: 200 },
  valueRow: { flexDirection: "row", alignItems: "center", gap: space.sm },
  tileValue: { fontSize: 24, lineHeight: 30, fontWeight: "600" },
  track: { height: 8, borderRadius: radius.pill, backgroundColor: colors.meterTrack, overflow: "hidden", marginTop: space.xs },
  fill: { height: "100%", backgroundColor: colors.meterFill, borderRadius: radius.pill },
  tooltip: { position: "absolute", bottom: "100%", marginBottom: space.xs, minWidth: 160, paddingVertical: space.sm, paddingHorizontal: space.md, gap: 2, borderRadius: radius.md, backgroundColor: colors.ink, zIndex: 10 },
  tooltipLeft: { left: 0 },
  tooltipRight: { right: 0 },
});
