import { firstTextRect, setEditorRange } from "./editor.mjs";
import { upperBound } from "./transport.mjs";

const lineStart = (line) => line.position;

export function createEditorFollower(editor, scrollPaused) {
  const range = document.createRange();
  const highlights = globalThis.CSS?.highlights;
  const highlight = highlights && typeof Highlight === "function" ? new Highlight() : undefined;
  if (highlight) highlights.set("krata-reading", highlight);

  let sourceLines = [];
  let visible = true;
  let start;
  let end;
  let active = false;
  let sourceIndex;
  let followParagraph = false;

  function clear() {
    if (!active) return;
    active = false;
    highlight?.clear();
    editor.classList.remove("reading-marker");
  }

  function reveal() {
    if (!active || !visible || document.hidden) return;
    const editing = document.activeElement === editor || scrollPaused();
    if (highlight && editing) return;
    const box = firstTextRect(range);
    if (!box) return;
    const viewport = editor.getBoundingClientRect();
    const top = box.top - viewport.top;
    if (!highlight) {
      editor.style.setProperty("--reading-marker-top", `${top + editor.scrollTop}px`);
      editor.style.setProperty("--reading-marker-height", `${box.height}px`);
      editor.classList.add("reading-marker");
    }
    if (editing) return;
    if (followParagraph || top < viewport.height * 0.2 || box.bottom - viewport.top > viewport.height * 0.78) {
      editor.scrollTop += top - viewport.height / 3;
    }
    followParagraph = false;
  }

  function show(script, nextStart, nextEnd) {
    if (!visible || document.hidden || !sourceLines.length) return;
    if (start === nextStart && end === nextEnd) return;
    start = nextStart;
    end = nextEnd;
    clear();
    if (start === undefined) return;

    const line = script.lines[upperBound(script.lines, start, lineStart) - 1];
    const spans = sourceLines[line?.sourceIndex];
    if (!spans?.length || !line.runs.some(({ text }) => text.trim())) return;
    if (sourceIndex !== line.sourceIndex) {
      sourceIndex = line.sourceIndex;
      followParagraph = true;
    }
    setEditorRange(range, spans, start - line.position, end - line.position);
    if (range.collapsed) return;
    highlight?.add(range);
    active = true;
    reveal();
  }

  function invalidate() {
    clear();
    start = undefined;
    end = undefined;
    sourceIndex = undefined;
    followParagraph = false;
  }

  editor.addEventListener("blur", () => queueMicrotask(reveal));
  new ResizeObserver(reveal).observe(editor);
  return {
    show,
    setSource(lines) {
      sourceLines = lines;
      invalidate();
    },
    setVisible(value) {
      visible = value;
      invalidate();
    },
  };
}
