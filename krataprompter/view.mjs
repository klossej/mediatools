import { appendStyledLine } from "./editor.mjs";
import { DEFAULT_SETTINGS, FONT_FAMILIES } from "./presentation.mjs";
import { BEGINNING, yAtPosition } from "./transport.mjs";

export const REFERENCE_HEIGHT = 1080;
const referenceWidth = 1920;

export function createView(stage, fitPreview = false) {
  const sheet = stage.querySelector(".sheet");
  const frame = stage.parentElement;
  const range = document.createRange();
  let blocks = [];
  let track = [];
  let previewWidth = referenceWidth;
  let guideFraction = DEFAULT_SETTINGS.guidePosition / 100;
  let yDirection = 1;

  function fit() {
    if (fitPreview) {
      const scale = Math.min(frame.clientWidth / previewWidth, frame.clientHeight / REFERENCE_HEIGHT);
      stage.style.setProperty("--preview-scale", Math.max(0.001, scale));
    }
  }

  function setPreviewAspect(width = referenceWidth, height = REFERENCE_HEIGHT) {
    const nextWidth = width * REFERENCE_HEIGHT / height;
    if (nextWidth === previewWidth) return false;
    previewWidth = nextWidth;
    stage.style.width = `${previewWidth}px`;
    fit();
    return true;
  }

  function render(script) {
    const fragment = document.createDocumentFragment();
    blocks = script.cues.length ? script.lines.map(({ runs, position }) => {
      const block = document.createElement("div");
      const nodes = appendStyledLine(block, runs);
      if (block.textContent.trim()) block.classList.add("script-line");
      fragment.append(block);
      return { block, nodes, position };
    }) : [];
    sheet.replaceChildren(fragment);
  }

  function apply(settings) {
    const scale = stage.clientHeight / REFERENCE_HEIGHT;
    const width = Math.min(settings.width, 100 - settings.horizontalMargin * 2);
    const vertical = fitPreview ? settings.previewMirrorVertical : settings.presenterMirrorVertical;
    guideFraction = settings.guidePosition / 100;
    yDirection = vertical ? -1 : 1;
    stage.style.setProperty("--font-size", `${Math.max(12, settings.fontSize * scale)}px`);
    stage.style.setProperty("--font-family", FONT_FAMILIES[settings.fontFamily]);
    stage.style.setProperty("--line-spacing", settings.lineSpacing);
    stage.style.setProperty("--paragraph-spacing", `${settings.paragraphSpacing * scale}px`);
    stage.style.setProperty("--text-width", `${width}%`);
    stage.style.setProperty("--text-align", settings.textAlign);
    stage.style.setProperty("--text-color", settings.textColor);
    stage.style.setProperty("--background-color", settings.backgroundColor);
    stage.style.setProperty("--guide-position", `${settings.guidePosition}%`);
    stage.style.setProperty("--guide-half-size", `${settings.guideSize * scale / 2}px`);
    stage.classList.toggle("show-guide", settings.guide);
    stage.classList.toggle("mirrored", fitPreview ? settings.previewMirror : settings.presenterMirror);
    stage.classList.toggle("mirrored-vertical", vertical);
  }

  function measure(end) {
    track = [];
    if (!blocks.length) return track;

    const { height } = stage.getBoundingClientRect();
    const scale = height / stage.clientHeight;
    const startY = (rect) => yDirection === 1 ? rect.top : rect.bottom;
    const sheetTop = startY(sheet.getBoundingClientRect());
    const distance = (from, to) => (to - from) * yDirection / scale;
    const lineHeight = Number.parseFloat(getComputedStyle(sheet).lineHeight);

    for (const { block, nodes, position } of blocks) {
      const blockTop = startY(block.getBoundingClientRect());
      const blockY = distance(sheetTop, blockTop) + lineHeight / 2;
      track.push([position, blockY]);
      let textOffset = position;
      let lastRow = 0;

      // A Range can identify wrapped rows inside styled text without splitting its DOM.
      // Find each new row by binary search instead of measuring every character.
      for (const node of nodes) {
        function rowAt(index) {
          range.setStart(node, index);
          range.setEnd(node, index + 1);
          const rect = range.getBoundingClientRect();
          return Math.floor(distance(blockTop, rect.top + rect.height / 2) / lineHeight);
        }

        let start = 0;
        const finalRow = rowAt(node.length - 1);
        while (lastRow < finalRow) {
          let left = start;
          let right = node.length - 1;
          while (left < right) {
            const middle = (left + right) >>> 1;
            if (rowAt(middle) <= lastRow) left = middle + 1;
            else right = middle;
          }
          lastRow = rowAt(left);
          track.push([textOffset + left, blockY + lastRow * lineHeight]);
          start = left + 1;
        }
        textOffset += node.length;
      }
    }

    const lead = Math.min(stage.clientHeight * 0.13, 2 * lineHeight);
    track.unshift([BEGINNING, track[0][1] - lead]);
    track.push([end, track.at(-1)[1] + stage.clientHeight * guideFraction + lineHeight]);
    return track;
  }

  function show(position) {
    sheet.style.setProperty("--scroll-y", `${-yAtPosition(track, position)}px`);
  }

  if (fitPreview) {
    fit();
    new ResizeObserver(fit).observe(frame);
  }
  return { render, apply, measure, show, setPreviewAspect };
}
