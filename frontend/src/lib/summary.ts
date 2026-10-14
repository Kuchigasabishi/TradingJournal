/** Statistics over the server's per-day P&L, in exact decimals. The server already did the summing; this finds extremes and ratios. */
import { type Dec, divideRound, parse } from "./decimal.ts";

export type DayLike = { date: string; pnl: string };
export type Extreme = { date: string; pnl: Dec };

export type DayStats = {
  net: Dec;
  best: Extreme | null;
  worst: Extreme | null;
  /** The largest gain on any one day, or 0. */
  maxGain: Dec;
  /** The largest loss on any one day as a positive number, or 0. */
  maxLoss: Dec;
  /** The larger of the two: the scale a heat map or bar chart is drawn against. */
  maxAbs: Dec;
};

export function dayStats(days: readonly DayLike[]): DayStats {
  let net = 0n;
  let best: Extreme | null = null;
  let worst: Extreme | null = null;
  let maxGain = 0n;
  let maxLoss = 0n;
  for (const day of days) {
    const pnl = parse(day.pnl);
    if (pnl === null) continue;
    net += pnl;
    if (best === null || pnl > best.pnl) best = { date: day.date, pnl };
    if (worst === null || pnl < worst.pnl) worst = { date: day.date, pnl };
    if (pnl > maxGain) maxGain = pnl;
    if (pnl < 0n && -pnl > maxLoss) maxLoss = -pnl;
  }
  return { net, best, worst, maxGain, maxLoss, maxAbs: maxGain > maxLoss ? maxGain : maxLoss };
}

/** The mean P&L per trade, rounded half away from zero at the eighth decimal; null when there are no trades. */
export function averagePerTrade(net: Dec, trades: number): Dec | null {
  return trades > 0 ? divideRound(net, BigInt(trades)) : null;
}

/** part / total as a whole percentage (0 to 100), for sizing a meter. */
export function percentSteps(part: number, total: number): number {
  if (total <= 0) return 0;
  return Number((BigInt(part) * 200n + BigInt(total)) / (BigInt(total) * 2n));
}
