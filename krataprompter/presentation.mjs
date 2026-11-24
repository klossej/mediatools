export const FONT_FAMILIES = Object.freeze({
  Arial: "Arial, Helvetica, sans-serif",
  Helvetica: "Helvetica, Arial, sans-serif",
  Verdana: "Verdana, sans-serif",
  Tahoma: "Tahoma, sans-serif",
  "System sans-serif": "system-ui, sans-serif",
  Georgia: "Georgia, serif",
  "Times New Roman": '"Times New Roman", serif',
  "Courier New": '"Courier New", monospace',
});

export const DEFAULT_SETTINGS = Object.freeze({
  fontSize: 64,
  fontFamily: "Arial",
  speed: 50,
  lineSpacing: 1.35,
  paragraphSpacing: 0,
  width: 84,
  horizontalMargin: 8,
  textAlign: "left",
  textColor: "#FFFFFF",
  backgroundColor: "#000000",
  guide: true,
  guidePosition: 33,
  guideSize: 13,
  previewMirror: false,
  previewMirrorVertical: false,
  presenterMirror: false,
  presenterMirrorVertical: false,
});

export const MIN_SPEED = 5;
export const MAX_SPEED = 240;
export const SPEED_STEP = 5;

export const SETTING_RANGES = Object.freeze({
  fontSize: [28, 200, 1],
  speed: [MIN_SPEED, MAX_SPEED, 1],
  lineSpacing: [1, 2, 0.01],
  paragraphSpacing: [0, 96, 1],
  width: [45, 96, 1],
  horizontalMargin: [0, 25, 1],
  guidePosition: [5, 95, 1],
  guideSize: [4, 96, 1],
});

export const TEXT_ALIGNMENTS = ["left", "center", "right", "justify"];

const aliases = {
  lineSpacing: "lineHeight",
  guide: "readingGuide",
  guidePosition: "readingGuidePosition",
  guideSize: "readingGuideSize",
  presenterMirror: "mirrorHorizontal",
  presenterMirrorVertical: "mirrorVertical",
};

export function validateSetting(key, value) {
  const fallback = DEFAULT_SETTINGS[key];
  const range = SETTING_RANGES[key];
  if (range) {
    const [min, max, step] = range;
    if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) {
      return fallback;
    }
    return Number((min + Math.round((value - min) / step) * step).toFixed(2));
  }
  if (typeof fallback === "boolean") return typeof value === "boolean" ? value : fallback;
  if (typeof value !== "string") return fallback;
  if (key === "fontFamily") {
    return Object.keys(FONT_FAMILIES).find((family) => family.toLowerCase() === value.toLowerCase()) ??
      fallback;
  }
  if (key === "textAlign") return TEXT_ALIGNMENTS.includes(value) ? value : fallback;
  return /^#[\da-f]{6}$/iu.test(value) ? value.toUpperCase() : fallback;
}

export function validateSettings(values) {
  return Object.fromEntries(Object.keys(DEFAULT_SETTINGS).map((key) => [
    key, validateSetting(key, values[key] ?? (aliases[key] && values[aliases[key]])),
  ]));
}

export function settingsChanged(before, after) {
  return Object.keys(DEFAULT_SETTINGS).some((key) => before[key] !== after[key]);
}

const layoutSettings = [
  "fontSize", "fontFamily", "lineSpacing", "paragraphSpacing", "width", "horizontalMargin",
  "textAlign", "guidePosition",
];

export function layoutChanged(before, after) {
  return layoutSettings.some((key) => before[key] !== after[key]);
}
