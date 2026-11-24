import { DEFAULT_SETTINGS, validateSettings } from "./presentation.mjs";
import { readScript, writeScript } from "./script.mjs";

const schemaVersion = 1;
const mappingEntry = /^( *)([a-z][\w-]*):(?=[ \t]|$)[ \t]*(.*)$/iu;

export function formatScriptVersion(date = new Date()) {
  const twoDigits = (value) => String(value).padStart(2, "0");
  const day = [date.getFullYear() % 100, date.getMonth() + 1, date.getDate()].map(twoDigits).join(".");
  const time = [date.getHours(), date.getMinutes()].map(twoDigits).join(":");
  return `${day} ${time}`;
}

export function normalizeScriptTitle(value) {
  if (typeof value !== "string") return undefined;
  return value.replace(/[\u0000-\u001f\u007f]/gu, " ").trim().slice(0, 160).trim() || undefined;
}

function validVersion(value) {
  if (typeof value !== "string") return false;
  const parts = value.match(/^(\d{2})\.(0[1-9]|1[0-2])\.(0[1-9]|[12]\d|3[01]) ([01]\d|2[0-3]):[0-5]\d$/u);
  if (!parts) return false;
  const [, year, month, day] = parts;
  return new Date(Date.UTC(2000 + Number(year), Number(month) - 1, Number(day))).getUTCDate() === Number(day);
}

// The file format uses scalar values in two block mappings. Treat YAML tags,
// arrays, anchors and nested values as unsupported input rather than resolving them.
function readScalar(source) {
  if (source.startsWith('"')) {
    const quoted = source.match(/^("(?:[^"\\]|\\.)*")(?:[ \t]+#.*)?[ \t]*$/u);
    try {
      return quoted ? JSON.parse(quoted[1]) : undefined;
    } catch {
      return undefined;
    }
  }
  if (source.startsWith("'")) {
    const quoted = source.match(/^'((?:[^']|'')*)'(?:[ \t]+#.*)?[ \t]*$/u);
    return quoted?.[1].replaceAll("''", "'");
  }
  const value = source.replace(/(?:^|[ \t])#.*$/u, "").trim();
  if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/iu.test(value)) return Number(value);
  if (/^(true|false)$/iu.test(value)) return value.toLowerCase() === "true";
  if (!value || /^[!&*\[\]{}>|]/u.test(value)) return undefined;
  return value;
}

function readMetadata(lines) {
  const metadata = Object.create(null);
  let section;
  let indent;
  for (const line of lines) {
    const entry = line.match(mappingEntry);
    if (!entry) continue;
    const [, padding, key, raw] = entry;
    const value = readScalar(raw);
    if (!padding.length) {
      section = undefined;
      indent = undefined;
      if (key === "krataprompter" || key === "version" || key === "title") metadata[key] = value;
      if ((key === "presentation" || key === "position") && value === undefined &&
          (!raw || raw.startsWith("#"))) {
        section = metadata[key] = Object.create(null);
      }
    } else if (section) {
      indent ??= padding.length;
      if (indent === padding.length) section[key] = value;
    }
  }
  return metadata;
}

function isFrontMatter(lines) {
  const root = lines.filter((line) => line && !/^\s/u.test(line) && !line.startsWith("#"));
  return root.some((line) => line.match(mappingEntry)?.[2] === "krataprompter") ||
    (root.length > 0 && root.every((line) => mappingEntry.test(line)));
}

export function readScriptFile(source, markdown) {
  let manuscript = source;
  let metadata;
  if (markdown) {
    const lines = source.replace(/^\uFEFF/u, "").split(/\r\n?|\n/u);
    const end = /^---[ \t]*$/u.test(lines[0])
      ? lines.findIndex((line, index) => index > 0 && /^(?:---|\.\.\.)[ \t]*$/u.test(line)) : -1;
    if (end > 0 && isFrontMatter(lines.slice(1, end))) {
      metadata = readMetadata(lines.slice(1, end));
      manuscript = lines.slice(end + 1).join("\n");
    }
  }

  const supported = metadata?.krataprompter === schemaVersion;
  return {
    lines: readScript(manuscript, markdown),
    settings: supported ? validateSettings(metadata.presentation ?? {}) : { ...DEFAULT_SETTINGS },
    position: supported ? metadata.position : undefined,
    version: supported && validVersion(metadata.version) ? metadata.version : undefined,
    title: supported ? normalizeScriptTitle(metadata.title) : undefined,
  };
}

export function writeMarkdownFile(lines, settings, position, version, title) {
  const properties = Object.keys(DEFAULT_SETTINGS).map((key) =>
    `  ${key}: ${JSON.stringify(settings[key])}`);
  const name = normalizeScriptTitle(title);
  return [
    "---",
    `krataprompter: ${schemaVersion}`,
    ...(name ? [`title: ${JSON.stringify(name)}`] : []),
    ...(validVersion(version) ? [`version: ${JSON.stringify(version)}`] : []),
    "presentation:",
    ...properties,
    "position:",
    `  cue: ${position.cue}`,
    `  progress: ${position.progress}`,
    "---",
    writeScript(lines, true),
  ].join("\n");
}
