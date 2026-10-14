/**
 * Design tokens. The data colors follow the dataviz method: gains and losses are a blue-red diverging
 * pair with a neutral midpoint, so they stay distinguishable without red/green vision. The loss arm was
 * derived to match the gain arm's OKLCH lightness steps; tools/derive-diverging-ramp.mjs reproduces it
 * and prints the contrast of every pair. Text never wears a data color: amounts stay in ink and are
 * accompanied by a sign and a triangle, so color is never the only channel.
 */
import { useWindowDimensions } from "react-native";

export const colors = {
  page: "#f9f9f7",
  surface: "#fcfcfb",
  sunken: "#f0efec", // the diverging midpoint, also used for tracks and chips
  ink: "#0b0b0b",
  inkSecondary: "#52514e", // 7.7:1 on the surface: the safe choice for meaningful text
  inkMuted: "#898781", // 3.5:1: tick labels and decoration only
  hairline: "rgba(11, 11, 11, 0.10)",
  grid: "#e1e0d9",
  baseline: "#c3c2b7",
  white: "#ffffff",

  // Diverging scale, four equal steps per arm (OKLCH lightness .905 / .764 / .622 / .480).
  gain: ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab"] as const,
  loss: ["#fad6d2", "#ea9a93", "#d75853", "#9e3432"] as const,
  // Ink on each fill, chosen by contrast: dark ink on the three lighter steps, white on the darkest.
  fillInk: ["#0b0b0b", "#0b0b0b", "#0b0b0b", "#ffffff"] as const,
  gainMark: "#3987e5", // 3.5:1 on the surface
  lossMark: "#d75853", // 3.8:1 on the surface

  // Economic-news impact: an ordinal amber ramp at the P&L shades' lightness steps (.764 / .622 / .480), so news never
  // borrows the blue or red of a gain or a loss. It is always drawn as bars with a count, on a neutral chip, and named in
  // words: colour is the third channel, not the first. tools/derive-impact-ramp.mjs reproduces and checks it.
  impact: { low: "#eda107", medium: "#b47905", high: "#7e5403" } as const,

  meterFill: "#2a78d6",
  meterTrack: "#cde2fb",

  critical: "#d03b3b", // status color: 4.7:1 as text, always with an icon and a label
  criticalWash: "#fdf0ef",
  goodText: "#006300",
  focus: "#2a78d6",
} as const;

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 4, md: 8, lg: 12, pill: 999 } as const;

/** Heat-map and bar shades by step (0 is the lightest). */
export function shade(tone: "gain" | "loss", step: number): { fill: string; ink: string } {
  const index = Math.min(Math.max(step, 0), 3);
  return { fill: colors[tone][index] as string, ink: colors.fillInk[index] as string };
}

export function useLayout() {
  const { width } = useWindowDimensions();
  return { width, narrow: width < 720, wide: width >= 1100 };
}
