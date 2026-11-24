import { layoutChanged } from "./presentation.mjs";
import { BEGINNING, clock, movingAt, positionAt, readingRowIndex, transportShortcut } from "./transport.mjs";
import { createView, REFERENCE_HEIGHT } from "./view.mjs";

const stage = document.querySelector(".presenter-stage");
const view = createView(stage);
const session = location.hash.slice(1);
const id = Array.from(crypto.getRandomValues(new Uint32Array(2)), (n) => n.toString(36)).join("-");
const channel = session && typeof BroadcastChannel === "function"
  ? new BroadcastChannel("krata-" + session) : null;

let script;
let settings;
let track = [];
let localTrack = [];
let scriptRevision = 0;
let layoutRevision = 0;
let state = { position: BEGINNING, moving: false };
let frame = 0;
let reportedStop = false;
let reportedReading;

function send(type, data = {}) {
  channel?.postMessage({ type, id, ...data });
}

function draw() {
  if (document.hidden || !script) return;
  const now = clock();
  const position = positionAt(state, track, now);
  const moving = movingAt(state, now);
  const ended = position >= script.end;
  view.show(position);
  const row = readingRowIndex(localTrack, script, position);
  const start = localTrack[row]?.[0];
  const end = row >= 0 ? localTrack[row + 1][0] : undefined;
  if (!reportedReading || start !== reportedReading.start || end !== reportedReading.end) {
    reportedReading = { start, end };
    send("reading-row", { scriptRevision, start, end });
  }
  if (state.moving && (ended || !moving) && !reportedStop) {
    reportedStop = true;
    send(ended ? "ended" : "settled");
  }
  if (moving && !ended && !frame) {
    frame = requestAnimationFrame(() => {
      frame = 0;
      draw();
    });
  }
}

function resize() {
  if (!script) return;
  view.apply(settings);
  measureLayout();
  draw();
}

function measureLayout() {
  const { clientWidth: width, clientHeight: height } = stage;
  if (!width || !height) return;
  localTrack = view.measure(script.end);
  const scale = REFERENCE_HEIGHT / height;
  const reference = localTrack.map(([position, y]) => [position, y * scale]);
  send("presenter-layout", { scriptRevision, layoutRevision, width, height, track: reference });
}

channel?.addEventListener("message", ({ data }) => {
  if (data.type === "disconnect") {
    state = { position: positionAt(state, track, clock()), moving: false };
    draw();
    return;
  }
  if (data.type !== "sync") return;
  if (scriptRevision !== data.scriptRevision) reportedReading = undefined;
  scriptRevision = data.scriptRevision;
  layoutRevision = data.layoutRevision;
  state = data.state;
  if (data.track) track = data.track;
  const relayout = data.script || !settings || layoutChanged(settings, data.settings);
  settings = data.settings;
  if (data.script) {
    script = data.script;
    view.render(script);
  }
  if (script) {
    view.apply(settings);
    if (relayout) measureLayout();
  }
  reportedStop = false;
  draw();
});

new ResizeObserver(resize).observe(stage);
document.addEventListener("visibilitychange", () => {
  send("presence", { visible: !document.hidden });
  // Wait for the authority to confirm how far playback advanced while hidden.
});
window.addEventListener("pageshow", () => send("hello", { visible: !document.hidden }));
window.addEventListener("pagehide", () => send("closed"));

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  else document.documentElement.requestFullscreen?.().catch(() => {});
}

stage.addEventListener("dblclick", toggleFullscreen);
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement) send("command", { action: "pause" });
});
window.addEventListener("keydown", (event) => {
  if (!event.repeat && !event.altKey && !event.ctrlKey && !event.metaKey &&
      event.key.toLowerCase() === "f") {
    event.preventDefault();
    toggleFullscreen();
    return;
  }
  const action = transportShortcut(event);
  if (!action) return;
  event.preventDefault();
  if (action !== "play" || !event.repeat) send("command", { action });
});

send("hello", { visible: !document.hidden });
