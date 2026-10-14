import { StyleSheet, Text, type TextProps, type TextStyle } from "react-native";

import { colors } from "../theme";

export type Variant = "hero" | "h1" | "h2" | "h3" | "body" | "small" | "label" | "tiny";
export type TextTone = "primary" | "secondary" | "muted" | "critical" | "good" | "inverse";

const VARIANTS: Record<Variant, TextStyle> = {
  hero: { fontSize: 48, lineHeight: 54, fontWeight: "700" },
  h1: { fontSize: 28, lineHeight: 34, fontWeight: "700" },
  h2: { fontSize: 20, lineHeight: 26, fontWeight: "600" },
  h3: { fontSize: 16, lineHeight: 22, fontWeight: "600" },
  body: { fontSize: 15, lineHeight: 22 },
  small: { fontSize: 13, lineHeight: 18 },
  label: { fontSize: 13, lineHeight: 18, fontWeight: "600" },
  tiny: { fontSize: 12, lineHeight: 16 },
};

const TONES: Record<TextTone, string> = {
  primary: colors.ink,
  secondary: colors.inkSecondary,
  muted: colors.inkMuted,
  critical: colors.critical,
  good: colors.goodText,
  inverse: colors.white,
};

type Props = TextProps & {
  variant?: Variant;
  tone?: TextTone;
  /** Tabular figures: only for columns of numbers that must line up. Large standalone numbers stay proportional. */
  numeric?: boolean;
  bold?: boolean;
};

export function AppText({ variant = "body", tone = "primary", numeric = false, bold = false, style, ...rest }: Props) {
  return <Text {...rest} style={[VARIANTS[variant], { color: TONES[tone] }, numeric && styles.numeric, bold && styles.bold, style]} />;
}

const styles = StyleSheet.create({
  numeric: { fontVariant: ["tabular-nums"] },
  bold: { fontWeight: "700" },
});
