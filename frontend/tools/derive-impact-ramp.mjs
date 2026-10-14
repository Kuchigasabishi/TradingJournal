// Reproduces the economic-news impact ramp in src/theme.ts. Run: node tools/derive-impact-ramp.mjs
//
// Impact is ordered (low < medium < high), so it takes an ordinal ramp: one hue, steadily darker. The hue is amber because the
// calendar already spends blue and red on gains and losses; amber stays well clear of the blue arm and, because impact is always
// drawn as bars with a count on a neutral chip, never has to be told apart from the red arm by colour alone. The three steps use
// the same OKLCH lightness as the P&L shades (.764, .622, .480), so news and money carry the same visual weight, and the lightest
// one lands on the design system's documented yellow (#eda100) to within rounding.
//
// The checks are the dataviz method's ordinal ones (monotone lightness, visible gaps between steps, a pale end that still clears
// 2:1 against the surface, one hue). The distances to the P&L colours are printed for the record, in OKLab x 100 under normal
// vision and under simulated protan, deutan and tritan vision (Machado, Oliveira and Fernandes 2009, severity 1).
const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLin = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
const hexToLin = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => toLin(v / 255));
};
const linToHex = (lin) => "#" + lin.map((c) => Math.round(Math.min(1, Math.max(0, fromLin(Math.min(1, Math.max(0, c))))) * 255).toString(16).padStart(2, "0")).join("");
const toOklab = ([r, g, b]) => {
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
};
const fromOklab = ([L, a, b]) => {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
};
const oklch = (hex) => {
  const [L, a, b] = toOklab(hexToLin(hex));
  return { L, C: Math.hypot(a, b), h: ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360 };
};
const fromLch = (L, C, h) => fromOklab([L, C * Math.cos((h * Math.PI) / 180), C * Math.sin((h * Math.PI) / 180)]);
const inGamut = (lin) => lin.every((c) => c >= -1e-4 && c <= 1 + 1e-4);
const maxChroma = (L, h) => {
  let c = 0.4;
  while (c > 0 && !inGamut(fromLch(L, c, h))) c -= 0.002;
  return Math.max(c, 0);
};
const lum = (hex) => {
  const [r, g, b] = hexToLin(hex);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

const MACHADO = {
  protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
  tritan: [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.3039]],
};
const simulate = (hex, kind) => {
  const [r, g, b] = hexToLin(hex);
  return MACHADO[kind].map((row) => Math.min(1, Math.max(0, row[0] * r + row[1] * g + row[2] * b)));
};
const deltaE = (a, b) => 100 * Math.hypot(...toOklab(a).map((v, i) => v - toOklab(b)[i]));
const distances = (a, b) => ({
  normal: deltaE(hexToLin(a), hexToLin(b)),
  protan: deltaE(simulate(a, "protan"), simulate(b, "protan")),
  deutan: deltaE(simulate(a, "deutan"), simulate(b, "deutan")),
  tritan: deltaE(simulate(a, "tritan"), simulate(b, "tritan")),
});

const surface = "#fcfcfb";
const HUE = 75; // amber
const LIGHTNESS = [0.764, 0.622, 0.48]; // the P&L shades' second, third and fourth steps
const [low, medium, high] = LIGHTNESS.map((L) => linToHex(fromLch(L, maxChroma(L, HUE), HUE)));
const ramp = [low, medium, high];

console.log(`impact ramp (hue ${HUE}): low ${low}  medium ${medium}  high ${high}`);
console.log("in src/theme.ts: impact: { low, medium, high }");

const Ls = ramp.map((hex) => oklch(hex).L);
const gaps = Ls.slice(1).map((l, i) => Math.abs(l - Ls[i]));
const hues = ramp.map((hex) => oklch(hex).h);
const checks = [
  ["lightness monotone, light to dark", Ls.every((l, i) => i === 0 || l < Ls[i - 1])],
  ["every gap between steps >= 0.06 L", gaps.every((g) => g >= 0.06), gaps.map((g) => g.toFixed(3)).join(", ")],
  ["lightest step >= 2:1 on the surface", contrast(low, surface) >= 2, `${contrast(low, surface).toFixed(2)}:1`],
  ["one hue (spread <= 40 degrees)", Math.max(...hues) - Math.min(...hues) <= 40, `${(Math.max(...hues) - Math.min(...hues)).toFixed(1)} degrees`],
];
for (const [name, ok, detail] of checks) console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  (${detail})` : ""}`);
console.log(`contrast on the surface: low ${contrast(low, surface).toFixed(2)}, medium ${contrast(medium, surface).toFixed(2)}, high ${contrast(high, surface).toFixed(2)}`);

const arms = {
  gain: ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab"],
  loss: ["#fad6d2", "#ea9a93", "#d75853", "#9e3432"],
};
for (const [name, arm] of Object.entries(arms)) {
  const worst = { normal: Infinity, protan: Infinity, deutan: Infinity, tritan: Infinity };
  for (const a of ramp) for (const b of arm) for (const [kind, value] of Object.entries(distances(a, b))) worst[kind] = Math.min(worst[kind], value);
  console.log(`closest to the ${name} arm: ${Object.entries(worst).map(([kind, value]) => `${kind} ${value.toFixed(1)}`).join(", ")}`);
}
if (!checks.every(([, ok]) => ok)) process.exit(1);
