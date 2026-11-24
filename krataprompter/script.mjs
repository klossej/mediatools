export const BOLD = 1;
export const ITALIC = 2;
export const UNDERLINE = 4;

const cueMarker = "*#";
const lineText = (line) => line.map(({ text }) => text).join("");

export function appendRun(line, text, style = 0) {
  if (!text) return;
  const previous = line.at(-1);
  if (previous?.style === style) previous.text += text;
  else line.push({ text, style });
}

const tags = new Map([
  ["b", BOLD], ["strong", BOLD], ["i", ITALIC], ["em", ITALIC], ["u", UNDERLINE],
]);

function parseInline(line) {
  const frames = [{ runs: [], style: 0 }];
  const top = () => frames.at(-1);
  const add = (text) => appendRun(top().runs, text, top().style);

  function close(matched) {
    const frame = frames.pop();
    if (!matched) add(frame.literal);
    for (const { text, style } of frame.runs) {
      appendRun(top().runs, text, matched ? style : (style & ~frame.addedStyle) | top().style);
    }
  }

  function open(delimiter, literal, addedStyle) {
    frames.push({ delimiter, literal, addedStyle, style: top().style | addedStyle, runs: [] });
  }

  const tokens = /\\([\\*_<>])|<(\/?)(b|strong|i|em|u)>|(\*+|_+)/gi;
  let end = 0;
  for (const match of line.matchAll(tokens)) {
    const [token, escaped, closing, tag, emphasis] = match;
    add(line.slice(end, match.index));
    end = match.index + token.length;
    if (escaped) {
      add(escaped);
    } else if (tag) {
      const name = tag.toLowerCase();
      if (!closing) open(name, token, tags.get(name));
      else if (top().delimiter === name) close(true);
      else add(token);
    } else {
      const character = emphasis[0];
      const before = line[match.index - 1] ?? " ";
      const after = line[end] ?? " ";
      const withinWord = character === "_" && /[\p{L}\p{N}]/u.test(before) &&
        /[\p{L}\p{N}]/u.test(after);
      let count = token.length;
      if (!withinWord && count <= 3) {
        while (!/\s/u.test(before) && top().delimiter?.[0] === character &&
          top().delimiter.length <= count) {
          count -= top().delimiter.length;
          close(true);
        }
        if (count && !/\s/u.test(after)) {
          if (count >= 2) open(character.repeat(2), character.repeat(2), BOLD);
          if (count % 2) open(character, character, ITALIC);
          count = 0;
        }
      }
      add(character.repeat(count));
    }
  }
  add(line.slice(end));
  while (frames.length > 1) close(false);
  return top().runs;
}

export function readScript(source, markdown = false) {
  return source.replace(/^\uFEFF/u, "").split(/\r\n?|\n/u).map((line) => {
    if (!line) return [];
    return markdown && line.trim() !== cueMarker ? parseInline(line) : [{ text: line, style: 0 }];
  });
}

const marks = [
  { style: BOLD, start: "<strong>", end: "</strong>" },
  { style: ITALIC, start: "<em>", end: "</em>" },
  { style: UNDERLINE, start: "<u>", end: "</u>" },
];

export function writeScript(lines, markdown = false) {
  return lines.map((line) => {
    const plain = lineText(line);
    if (!markdown || plain.trim() === cueMarker) return plain;

    let result = "";
    let active = [];
    for (const { text, style } of [...line, { text: "", style: 0 }]) {
      const next = marks.filter((mark) => style & mark.style);
      let common = 0;
      while (active[common] && active[common] === next[common]) common++;
      for (const mark of active.slice(common).reverse()) result += mark.end;
      for (const mark of next.slice(common)) result += mark.start;
      result += text.replace(/[\\*_<>]/gu, "\\$&");
      active = next;
    }
    return result;
  }).join("\n");
}

export function buildScript(lines) {
  const documentLines = [];
  const cues = [];
  let position = 0;
  let needsCue = true;

  for (const [sourceIndex, runs] of lines.entries()) {
    const text = lineText(runs);
    const trimmed = text.trim();
    if (trimmed === cueMarker) {
      needsCue = true;
      continue;
    }
    if (needsCue && trimmed) {
      if (cues.length) {
        documentLines.push({ runs: [], position });
        position += 1;
      }
      cues.push(position);
      needsCue = false;
    }
    documentLines.push({ runs, position, sourceIndex });
    position += text.length + 1;
  }
  return { lines: documentLines, cues, end: position };
}
