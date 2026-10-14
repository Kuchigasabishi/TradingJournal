// Reproduces the diverging scale in src/theme.ts: the documented blue arm, plus a red arm derived at the same
// OKLCH lightness steps, with WCAG contrast for every ink-on-fill pair the app uses. Run: node tools/derive-diverging-ramp.mjs
// Derives the loss arm of the diverging scale so it has the same OKLCH lightness steps as the gain arm,
// then reports WCAG contrast for every text-on-fill pair the app will use.
const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLin = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
const hexToLin = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => toLin(v / 255));
};
const linToHex = (lin) =>
  "#" + lin.map((c) => Math.round(Math.min(1, Math.max(0, fromLin(Math.min(1, Math.max(0, c))))) * 255).toString(16).padStart(2, "0")).join("");
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
const inGamut = (lin) => lin.every((c) => c >= -1e-4 && c <= 1 + 1e-4);
const fromLch = (L, C, h) => fromOklab([L, C * Math.cos((h * Math.PI) / 180), C * Math.sin((h * Math.PI) / 180)]);
const clipChroma = (L, C, h) => {
  let c = C;
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

const surface = "#fcfcfb";
const ink = "#0b0b0b";
const secondary = "#52514e";
const muted = "#898781";
const neutral = "#f0efec";

// Gain arm: the documented sequential blue steps 100, 250, 400 and 550.
const gain = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab"];
// Loss arm: the documented red hue (categorical slot 8 and the critical status sit at hue ~25).
const redHue = (oklch("#e34948").h + oklch("#d03b3b").h) / 2;
const loss = gain.map((hex) => {
  const { L, C } = oklch(hex);
  const chroma = clipChroma(L, C, redHue);
  return linToHex(fromLch(L, chroma, redHue));
});

console.log(`red hue (avg of #e34948 and #d03b3b): ${redHue.toFixed(1)} deg`);
console.log("\narm            hex       L      C      contrast vs surface  ink      white");
for (const [name, arm] of [["gain", gain], ["loss", loss]]) {
  arm.forEach((hex, i) => {
    const { L, C } = oklch(hex);
    console.log(`${name} step ${i + 1}    ${hex}  ${L.toFixed(3)}  ${C.toFixed(3)}  ${contrast(hex, surface).toFixed(2).padStart(6)}               ${contrast(hex, ink).toFixed(2).padStart(5)}    ${contrast(hex, "#ffffff").toFixed(2).padStart(5)}`);
  });
}
console.log(`\nneutral midpoint ${neutral}: ink ${contrast(neutral, ink).toFixed(2)}`);
console.log("\ntext tokens on the chart surface (WCAG text needs 4.5:1):");
for (const [name, hex] of [["primary ink", ink], ["secondary ink", secondary], ["muted", muted]]) console.log(`  ${name.padEnd(14)} ${hex}  ${contrast(hex, surface).toFixed(2)}`);
console.log("\nstatus text on the surface: critical #d03b3b", contrast("#d03b3b", surface).toFixed(2), " good text #006300", contrast("#006300", surface).toFixed(2));
console.log("accent ink button text: white on ink", contrast("#ffffff", ink).toFixed(2));
console.log("gain 450 #2a78d6 on surface", contrast("#2a78d6", surface).toFixed(2), "  track #cde2fb on surface", contrast("#cde2fb", surface).toFixed(2));
console.log("hairlines: grid #e1e0d9", contrast("#e1e0d9", surface).toFixed(2), " baseline #c3c2b7", contrast("#c3c2b7", surface).toFixed(2));
console.log("focus ring #2a78d6 vs page #f9f9f7", contrast("#2a78d6", "#f9f9f7").toFixed(2));
