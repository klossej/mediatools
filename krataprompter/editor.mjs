import { appendRun, BOLD, ITALIC, UNDERLINE } from "./script.mjs";

const blockTags = new Set(["DIV", "P", "LI", "UL", "OL", "BLOCKQUOTE", "PRE"]);

function domPoint(spans, offset, isEnd = false) {
  for (const { node, start, end } of spans) {
    const length = end - start;
    if (offset < length || (isEnd && offset === length)) return [node, start + offset];
    offset -= length;
  }
  const { node, end } = spans.at(-1);
  return [node, end];
}

export function setEditorRange(range, spans, start, end) {
  range.setStart(...domPoint(spans, start));
  range.setEnd(...domPoint(spans, end, true));
}

export function firstTextRect(range) {
  return Array.from(range.getClientRects()).find((rect) => rect.width > 0);
}

function styleOf(element, inherited) {
  let style = inherited;
  const { tagName } = element;
  const { fontWeight, fontStyle, textDecoration, textDecorationLine } = element.style ?? {};
  if (tagName === "B" || tagName === "STRONG" || fontWeight === "bold" ||
      Number(fontWeight) >= 600) style |= BOLD;
  if (fontWeight === "normal" || (fontWeight && Number(fontWeight) < 600)) style &= ~BOLD;
  if (tagName === "I" || tagName === "EM" || fontStyle === "italic") style |= ITALIC;
  if (fontStyle === "normal") style &= ~ITALIC;
  if (tagName === "U" || textDecoration?.includes("underline") ||
      textDecorationLine?.includes("underline")) style |= UNDERLINE;
  return style;
}

export function readEditor(root, inherited = 0, sourceLines) {
  const lines = [];
  let line = [];
  let spans = sourceLines && [];
  let hasInline = false;

  function flush() {
    lines.push(line);
    sourceLines?.push(spans);
    line = [];
    spans = sourceLines && [];
    hasInline = false;
  }

  function visit(node, style, terminal) {
    if (node.nodeType === Node.TEXT_NODE) {
      let start = 0;
      function appendText(end) {
        appendRun(line, node.data.slice(start, end), style);
        if (end > start) spans?.push({ node, start, end });
        hasInline = true;
      }
      for (const newline of node.data.matchAll(/\r\n?|\n/gu)) {
        appendText(newline.index);
        flush();
        start = newline.index + newline[0].length;
      }
      appendText(node.length);
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.tagName === "BR") {
      if (!terminal) flush();
      // A final BR is the browser's placeholder for the current editable line.
      hasInline = true;
      return;
    }
    const nextStyle = styleOf(node, style);
    if (blockTags.has(node.tagName)) {
      if (hasInline) flush();
      for (const blockLine of readEditor(node, nextStyle, sourceLines)) lines.push(blockLine);
    } else {
      visitChildren(node, nextStyle, terminal);
    }
  }

  function visitChildren(parent, style, terminal) {
    for (const child of parent.childNodes) {
      visit(child, style, terminal && child === parent.lastChild);
    }
  }

  visitChildren(root, inherited, true);
  if (hasInline || !lines.length) flush();
  return lines;
}

export function appendStyledLine(element, runs) {
  const textNodes = [];
  for (const { text, style } of runs) {
    let parent = element;
    for (const [flag, tag] of [[BOLD, "strong"], [ITALIC, "em"], [UNDERLINE, "u"]]) {
      if (!(style & flag)) continue;
      const mark = document.createElement(tag);
      parent.append(mark);
      parent = mark;
    }
    const node = document.createTextNode(text);
    parent.append(node);
    textNodes.push(node);
  }
  if (!textNodes.length) element.append(document.createElement("br"));
  return textNodes;
}

export function writeEditor(root, lines) {
  const fragment = document.createDocumentFragment();
  for (const runs of lines) {
    const line = document.createElement("div");
    appendStyledLine(line, runs);
    fragment.append(line);
  }
  root.replaceChildren(fragment);
}

export function installEditor(root, toolbar, changed) {
  let selectionRange;

  function selectionChanged() {
    const selection = window.getSelection();
    if (selection.rangeCount && root.contains(selection.anchorNode) &&
        root.contains(selection.focusNode)) {
      selectionRange = selection.getRangeAt(0).cloneRange();
      for (const button of toolbar.querySelectorAll("[data-format]")) {
        button.setAttribute("aria-pressed", String(document.queryCommandState(button.dataset.format)));
      }
    }
  }

  function restoreSelection() {
    root.focus();
    const selection = window.getSelection();
    if (selectionRange && root.contains(selectionRange.commonAncestorContainer)) {
      selection.removeAllRanges();
      selection.addRange(selectionRange);
    } else {
      selection.selectAllChildren(root);
      selection.collapseToEnd();
    }
  }

  root.addEventListener("input", changed);
  document.addEventListener("selectionchange", selectionChanged);
  root.addEventListener("paste", (event) => {
    event.preventDefault();
    document.execCommand("insertText", false, event.clipboardData.getData("text/plain"));
  });
  root.addEventListener("drop", (event) => event.preventDefault());
  toolbar.addEventListener("pointerdown", (event) => {
    if (event.target.closest("button")) event.preventDefault();
  });
  toolbar.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    restoreSelection();
    if (button.dataset.format) document.execCommand(button.dataset.format);
    else {
      const before = window.getSelection().getRangeAt(0).cloneRange();
      before.setStart(root, 0);
      const previousLine = readEditor(before.cloneContents()).at(-1);
      const prefix = previousLine.some(({ text }) => text.trim()) ? "\n" : "";
      document.execCommand("insertText", false, prefix + "*#\n");
    }
    changed();
    selectionChanged();
  });
  return () => { selectionRange = undefined; };
}
