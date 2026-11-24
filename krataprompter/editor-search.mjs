import { firstTextRect, setEditorRange } from "./editor.mjs";
import { upperBound } from "./transport.mjs";

const firstMatch = (row) => row.first;

function literalPattern(query) {
  return new RegExp(query.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "giu");
}

export function createEditorSearch(editor, panel, button) {
  const query = panel.querySelector("input");
  const previous = panel.querySelector("#find-previous");
  const next = panel.querySelector("#find-next");
  const count = panel.querySelector("output");
  const range = document.createRange();
  const highlights = globalThis.CSS?.highlights;
  const highlight = highlights && typeof Highlight === "function" ? new Highlight() : undefined;
  if (highlight) {
    highlight.priority = 1;
    highlights.set("krata-find", highlight);
  }

  let lines = [];
  let sourceLines = [];
  let matching = [];
  let total = 0;
  let selected = 0;
  let expression;
  let timer;

  function reveal() {
    if (panel.hidden || !total) return;
    const box = firstTextRect(range);
    if (!box) return;
    const viewport = editor.getBoundingClientRect();
    if (box.top < viewport.top || box.bottom > viewport.bottom) {
      editor.scrollTop += box.top - viewport.top - viewport.height / 3;
    }
  }

  function showMatch(scroll) {
    highlight?.clear();
    previous.disabled = next.disabled = !total;
    count.value = total ? `${selected + 1} / ${total}` : query.value.trim() ? "No matches" : "";
    if (!total) return;
    const row = matching[upperBound(matching, selected, firstMatch) - 1];
    expression.lastIndex = 0;
    let match = expression.exec(row.text);
    for (let index = row.first; index < selected; index++) match = expression.exec(row.text);
    setEditorRange(range, sourceLines[row.line], match.index, match.index + match[0].length);
    highlight?.add(range);
    if (scroll) reveal();
  }

  function refresh(reset, scroll) {
    clearTimeout(timer);
    timer = undefined;
    matching = [];
    total = 0;
    if (query.value.trim()) {
      expression = literalPattern(query.value);
      for (const [line, runs] of lines.entries()) {
        const text = runs.map(({ text }) => text).join("");
        let matches = 0;
        for (const match of text.matchAll(expression)) {
          if (!matches++) matching.push({ first: total, line, text });
        }
        total += matches;
      }
    }
    selected = reset ? 0 : Math.max(0, Math.min(selected, total - 1));
    showMatch(scroll);
  }

  function move(direction) {
    if (timer !== undefined) {
      refresh(true, true);
      return;
    }
    if (!total) return;
    selected = (selected + direction + total) % total;
    showMatch(true);
  }

  function open() {
    panel.hidden = false;
    button.setAttribute("aria-expanded", "true");
    refresh(false, true);
    query.focus({ preventScroll: true });
    query.select();
  }

  function close() {
    if (timer !== undefined) refresh(true, false);
    panel.hidden = true;
    button.setAttribute("aria-expanded", "false");
    highlight?.clear();
    editor.focus({ preventScroll: true });
    if (total && editor.contains(range.commonAncestorContainer)) {
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range.cloneRange());
    }
  }

  button.addEventListener("click", () => panel.hidden ? open() : close());
  panel.querySelector("#find-close").addEventListener("click", close);
  previous.addEventListener("click", () => move(-1));
  next.addEventListener("click", () => move(1));
  query.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => refresh(true, true), 75);
  });
  panel.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.target === query && event.key === "Enter") {
      event.preventDefault();
      move(event.shiftKey ? -1 : 1);
    }
  });

  return {
    open,
    reveal,
    invalidate() {
      clearTimeout(timer);
      timer = undefined;
      lines = sourceLines = matching = [];
      total = 0;
      previous.disabled = next.disabled = true;
      highlight?.clear();
    },
    setSource(nextLines, nextSource) {
      lines = nextLines;
      sourceLines = nextSource;
      if (!panel.hidden) refresh(false, false);
    },
  };
}
