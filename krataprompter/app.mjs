import { installEditor, readEditor, writeEditor } from "./editor.mjs";
import { createEditorFollower } from "./editor-follow.mjs";
import { createEditorSearch } from "./editor-search.mjs";
import {
  DEFAULT_SETTINGS, FONT_FAMILIES, layoutChanged, MAX_SPEED, MIN_SPEED, SETTING_RANGES,
  settingsChanged, SPEED_STEP, TEXT_ALIGNMENTS, validateSetting,
} from "./presentation.mjs";
import { formatScriptVersion, normalizeScriptTitle, readScriptFile, writeMarkdownFile } from "./script-file.mjs";
import { buildScript, writeScript } from "./script.mjs";
import {
  adjacentCue, BEGINNING, clock, cueIndex, movingAt, PAUSE_RAMP_MS, PLAY_RAMP_MS,
  positionAt, readingRowIndex, rememberPosition, restorePosition, retimeMotion, transportShortcut,
} from "./transport.mjs";
import { createView } from "./view.mjs";

const byId = (id) => document.getElementById(id);
const editor = byId("script-editor");
const searchPanel = byId("script-search");
const editorSearch = createEditorSearch(editor, searchPanel, byId("toggle-search"));
const editorFollower = createEditorFollower(editor, () => !searchPanel.hidden);
const nameInput = byId("script-name-input");
const nameButton = byId("script-name");
const library = byId("script-library");
const serverScript = byId("server-script");
const preview = createView(document.querySelector(".preview-stage"), true);
const session = Array.from(crypto.getRandomValues(new Uint32Array(4)), (n) => n.toString(36)).join("-");
const channel = typeof BroadcastChannel === "function" ? new BroadcastChannel("krata-" + session) : null;

let settings = DEFAULT_SETTINGS;
let script = buildScript([]);
let scriptRevision = 0;
let layoutRevision = 0;
let track = [];
let previewTrack = [];
let state = { position: BEGINNING, at: clock(), speed: 0, playing: false, moving: false };
let frame = 0;
let editTimer;
let editorZoom = 100;
let signature = "";
let savedManuscript = "";
let savedSettings = DEFAULT_SETTINGS;
let savedTitle;
let filename = "Untitled";
let scriptTitle;
let scriptVersion;
let dirty = false;
let popup;
let popupCheck;
let presenterId;
let presenterVisible = false;
let presenterReading;
let fileRequest = 0;
let fileBusy = false;
let serverFile;

const settingLabels = {
  fontSize: (value) => `${value} px`,
  speed: (value) => `${value} px/s`,
  lineSpacing: (value) => value.toFixed(2),
  paragraphSpacing: (value) => `${value} px`,
  width: (value) => `${value}%`,
  horizontalMargin: (value) => `${value}%`,
  guidePosition: (value) => `${value}%`,
  guideSize: (value) => `${value} px`,
};

function publish({ layout = false, documentChanged = false } = {}) {
  channel?.postMessage({
    type: "sync",
    state,
    settings,
    scriptRevision,
    layoutRevision,
    ...(layout && { track }),
    ...(documentChanged && { script }),
  });
}

function controls(position, moving) {
  const index = cueIndex(script.cues, position);
  const ended = script.cues.length > 0 && position >= script.end;
  const update = (id, value) => {
    const element = byId(id);
    if (element.textContent !== value) element.textContent = value;
  };
  update("cue-status", `Cue ${index + 1} / ${script.cues.length}`);
  update("playback-status", ended ? "End of script" : state.playing ? "Playing" :
    moving ? "Pausing" : position === BEGINNING ? "Ready" : "Paused");
  update("play", state.playing ? "Pause" : ended ? "Replay" : "Play");
  byId("play").disabled = index < 0;
  byId("reset").disabled = index < 0;
  byId("previous").disabled = index < 0 || position <= script.cues[0];
  byId("next").disabled = index < 0 || index >= script.cues.length - 1;
}

function draw() {
  const now = clock();
  const position = positionAt(state, track, now);
  if (state.moving && (position >= script.end || !movingAt(state, now))) {
    stopTransport(position, now);
    publish();
  }
  const moving = movingAt(state, now);
  preview.show(position);
  showReadingLine(position);
  controls(position, moving);
  if (moving && !document.hidden && !frame) {
    frame = requestAnimationFrame(() => {
      frame = 0;
      draw();
    });
  }
}

function showReadingLine(position) {
  if (presenterVisible && presenterReading && position < script.end) {
    editorFollower.show(script, presenterReading.start, presenterReading.end);
  } else {
    const row = readingRowIndex(previewTrack, script, position);
    editorFollower.show(script, previewTrack[row]?.[0], row >= 0 ? previewTrack[row + 1][0] : undefined);
  }
}

function stopTransport(position, at) {
  state = { position, at, speed: 0, playing: false, moving: false };
}

function setTransport(position, playing, at) {
  if (!script.cues.length || position >= script.end) {
    stopTransport(position, at);
    return;
  }
  const visible = !document.hidden || presenterVisible;
  const speed = playing ? settings.speed : 0;
  const rampMs = playing !== state.playing ? (playing ? PLAY_RAMP_MS : PAUSE_RAMP_MS) : 0;
  state = {
    ...retimeMotion(state, position, at, visible, speed, rampMs),
    playing,
  };
}

function refreshVisibility() {
  const now = clock();
  setTransport(positionAt(state, track, now), state.playing, now);
  publish();
  draw();
}

function syncSettings() {
  for (const [key, value] of Object.entries(settings)) {
    if (typeof value === "boolean") byId(key).checked = value;
    else {
      byId(key).value = value;
      if (settingLabels[key]) byId(key + "-value").value = settingLabels[key](value);
    }
  }
}

function applySettings(next) {
  if (!settingsChanged(settings, next)) return;
  flushEdit();
  const now = clock();
  const position = positionAt(state, track, now);
  const layout = layoutChanged(settings, next);
  settings = next;
  preview.apply(settings);
  if (layout) {
    layoutRevision++;
    track = previewTrack = preview.measure(script.end);
  }
  setTransport(position, state.playing, now);
  syncSettings();
  refreshDirty();
  showFile();
  publish({ layout });
  draw();
}

function changeSetting(key, value) {
  applySettings({ ...settings, [key]: validateSetting(key, value) });
}

function refreshDirty() {
  dirty = signature !== savedManuscript || scriptTitle !== savedTitle || settingsChanged(savedSettings, settings);
}

function showFile(status) {
  const display = filename + (dirty ? " *" : "");
  byId("file-name").textContent = display;
  byId("file-name").title = display;
  byId("file-status").textContent = status ?? (dirty ? "Unsaved changes" : "");
  byId("file-status").title = byId("file-status").textContent;
  nameButton.textContent = displayedName();
}

function showVersion(version) {
  scriptVersion = version;
  byId("script-version").textContent = `Version ${version ?? "—"}`;
}

function stopPendingEdit() {
  clearTimeout(editTimer);
  editTimer = undefined;
}

function syncScript(opened) {
  stopPendingEdit();
  const sourceLines = [];
  const editedLines = readEditor(editor, 0, sourceLines);
  const lines = opened?.lines ?? editedLines;
  const canonical = writeScript(lines, true);
  const changed = signature !== canonical;
  signature = canonical;
  if (opened) {
    settings = savedSettings = opened.settings;
    savedManuscript = canonical;
    syncSettings();
    preview.apply(settings);
  }
  refreshDirty();
  showFile();
  editorFollower.setSource(sourceLines);
  editorSearch.setSource(editedLines, sourceLines);
  if (!opened && !changed) {
    showReadingLine(positionAt(state, track, clock()));
    return;
  }
  const now = clock();
  const position = positionAt(state, track, now);
  script = buildScript(lines);
  scriptRevision++;
  presenterReading = undefined;
  preview.render(script);
  track = previewTrack = preview.measure(script.end);
  const nextPosition = opened ? restorePosition(script, opened.position) :
    script.cues.length ? Math.min(position, script.end) : BEGINNING;
  if (opened) stopTransport(nextPosition, now);
  else setTransport(nextPosition, state.playing, now);
  byId("empty-preview").hidden = Boolean(script.cues.length);
  publish({ layout: true, documentChanged: true });
  draw();
}

function editorChanged() {
  editorFollower.setSource([]);
  editorSearch.invalidate();
  dirty = true;
  showFile();
  stopPendingEdit();
  editTimer = setTimeout(syncScript, 100);
}

function flushEdit() {
  if (editTimer !== undefined) syncScript();
}

function downloadFile(name, contents, mimeType) {
  const url = URL.createObjectURL(new Blob([contents], { type: mimeType + ";charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

const withoutExtension = (name) => name.replace(/\.(md|markdown|txt)$/iu, "");
const displayedName = () => scriptTitle ?? withoutExtension(filename);
const filenameStem = (name) => withoutExtension(name.trim()).replace(/[<>:"/\\|?*]/gu, "_")
  .replace(/^\.+/u, "").trim();

function currentBasename() {
  if (filename !== "Untitled") return withoutExtension(filename);
  const stem = filenameStem(scriptTitle ?? "script");
  return stem && new TextEncoder().encode(stem).length <= 236 ? stem : "script";
}

function finishNameEdit(cancel = false) {
  if (nameInput.hidden) return;
  const title = normalizeScriptTitle(nameInput.value);
  nameInput.hidden = true;
  nameButton.hidden = false;
  if (cancel || !title || title === displayedName()) return;
  flushEdit();
  scriptTitle = title === withoutExtension(filename) ? undefined : title;
  refreshDirty();
  showFile();
}

nameButton.addEventListener("click", () => {
  fileRequest++;
  nameInput.value = displayedName();
  nameButton.hidden = true;
  nameInput.hidden = false;
  nameInput.focus();
  nameInput.select();
});
nameInput.addEventListener("blur", () => finishNameEdit());
nameInput.addEventListener("keydown", (event) => {
  if (event.isComposing || !["Enter", "Escape"].includes(event.key)) return;
  event.preventDefault();
  finishNameEdit(event.key === "Escape");
  nameButton.focus();
});

function markdownSnapshot(version, title = scriptTitle) {
  const bookmark = rememberPosition(script, positionAt(state, track, clock()));
  return writeMarkdownFile(readEditor(editor), settings, bookmark, version, title);
}

async function storageRequest(route, body) {
  let response;
  try {
    response = await fetch("./api/scripts" + route, {
      signal: AbortSignal.timeout(8000),
      ...(body && { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
    });
  } catch {
    throw new Error("Could not reach the script server.");
  }
  if (!response.headers.get("Content-Type")?.startsWith("application/json")) {
    throw new Error("Server storage is unavailable.");
  }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  return result;
}

function setFileBusy(busy) {
  fileBusy = busy;
  for (const id of ["open-server", "open-script", "save-markdown", "save-as", "close-library"]) {
    byId(id).disabled = busy;
  }
  byId("open-selection").disabled = busy || !serverScript.value;
}

async function saveMarkdown(saveAs) {
  if (fileBusy) return;
  finishNameEdit();
  flushEdit();
  let name = currentBasename() + ".md";
  if (saveAs) {
    const suggested = prompt("Save Markdown on the server as", name);
    if (suggested === null) return;
    const basename = filenameStem(suggested);
    if (!basename) return;
    name = basename + ".md";
  }
  const revision = !saveAs && serverFile?.name === name ? serverFile.revision : null;
  const manuscript = signature;
  const snapshotSettings = settings;
  const snapshotTitle = scriptTitle;
  const version = formatScriptVersion();
  const content = markdownSnapshot(version, snapshotTitle);
  fileRequest++;
  setFileBusy(true);
  try {
    const result = await storageRequest("/save", { name, revision, content });
    flushEdit();
    filename = result.name;
    serverFile = result;
    savedManuscript = manuscript;
    savedSettings = snapshotSettings;
    savedTitle = snapshotTitle;
    refreshDirty();
    showVersion(version);
    showFile(!result.remembered ? "Saved. Could not record the previous script." :
      dirty ? "Saved. Newer edits are unsaved." : "Saved to server");
  } catch (error) {
    showFile(error.message);
  } finally {
    setFileBusy(false);
  }
}

function exportMarkdown() {
  finishNameEdit();
  flushEdit();
  const version = dirty || !scriptVersion ? formatScriptVersion() : scriptVersion;
  downloadFile(currentBasename() + ".md", markdownSnapshot(version), "text/markdown");
  showFile("Markdown download started");
}

function exportText() {
  flushEdit();
  const lines = readEditor(editor);
  if (lines.some((line) => line.some(({ style }) => style)) &&
      !confirm("Text files contain plain text. Export a plain-text copy?")) return;
  downloadFile(currentBasename() + ".txt", writeScript(lines), "text/plain");
  showFile("Plain-text download started");
}

const clearEditorSelection = installEditor(editor, byId("format-bar"), editorChanged);

function loadFile(name, content, stored) {
  const opened = readScriptFile(content, /\.(md|markdown)$/iu.test(name));
  clearEditorSelection();
  writeEditor(editor, opened.lines);
  editor.scrollTop = 0;
  filename = name;
  scriptTitle = savedTitle = opened.title;
  serverFile = stored && { name, revision: stored.revision };
  showVersion(opened.version);
  syncScript(opened);
  showFile(!stored ? "File opened" : stored.remembered === false ?
    "Opened. Could not record the previous script." : "Opened from server");
}

function confirmDiscard() {
  finishNameEdit();
  flushEdit();
  return !dirty || confirm("Open another file and discard unsaved script or settings changes?");
}

async function openPrevious() {
  try {
    const { script: previous } = await storageRequest("/previous");
    if (previous && fileRequest === 0 && !dirty) loadFile(previous.name, previous.content, previous);
  } catch (error) {
    if (fileRequest === 0 && !dirty) showFile(error.message);
  }
}

byId("open-server").addEventListener("click", async () => {
  const request = ++fileRequest;
  serverScript.replaceChildren();
  byId("open-selection").disabled = true;
  byId("library-status").textContent = "Loading…";
  library.showModal();
  try {
    const { scripts } = await storageRequest("");
    if (request !== fileRequest || !library.open) return;
    for (const name of scripts) serverScript.add(new Option(name, name));
    if (scripts.length) serverScript.selectedIndex = 0;
    byId("open-selection").disabled = !scripts.length;
    byId("library-status").textContent = scripts.length ? "" : "No scripts saved on the server.";
  } catch (error) {
    if (request === fileRequest && library.open) byId("library-status").textContent = error.message;
  }
});

byId("close-library").addEventListener("click", () => library.close());
library.addEventListener("cancel", (event) => {
  if (fileBusy) event.preventDefault();
});
byId("library-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = serverScript.value;
  if (fileBusy || !name || !confirmDiscard()) return;
  setFileBusy(true);
  byId("library-status").textContent = "Opening…";
  try {
    const stored = await storageRequest("/open", { name });
    loadFile(stored.name, stored.content, stored);
    library.close();
  } catch (error) {
    byId("library-status").textContent = error.message;
  } finally {
    setFileBusy(false);
  }
});

byId("open-script").addEventListener("click", () => {
  fileRequest++;
  byId("script-file").click();
});
byId("script-file").addEventListener("change", async (event) => {
  const file = event.currentTarget.files[0];
  event.currentTarget.value = "";
  if (!file || fileBusy) return;
  const request = ++fileRequest;
  let contents;
  try {
    contents = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
  } catch {
    if (request === fileRequest) showFile("Could not open as UTF-8");
    return;
  }
  if (request !== fileRequest || !confirmDiscard()) return;
  loadFile(file.name, contents);
});

byId("save-markdown").addEventListener("click", () => saveMarkdown(false));
byId("save-as").addEventListener("click", () => saveMarkdown(true));
byId("download-markdown").addEventListener("click", exportMarkdown);
byId("save-text").addEventListener("click", exportText);
window.addEventListener("beforeunload", (event) => {
  const draftTitle = nameInput.hidden ? undefined : normalizeScriptTitle(nameInput.value);
  const titleChanged = scriptTitle !== savedTitle || (draftTitle && draftTitle !== displayedName());
  if ((!dirty && !titleChanged) || (!titleChanged && !settingsChanged(savedSettings, settings) &&
      writeScript(readEditor(editor), true) === savedManuscript)) return;
  event.preventDefault();
  event.returnValue = true;
});

byId("toggle-editor").addEventListener("click", (event) => {
  const button = event.currentTarget;
  const collapsed = document.querySelector(".workspace").classList.toggle("editor-collapsed");
  byId("editor-body").hidden = collapsed;
  editorFollower.setVisible(!collapsed);
  button.textContent = collapsed ? "Expand" : "Collapse";
  button.setAttribute("aria-expanded", String(!collapsed));
  if (!collapsed) showReadingLine(positionAt(state, track, clock()));
});

function setEditorZoom(percent) {
  const next = Math.max(70, Math.min(200, percent));
  if (next === editorZoom) return;
  const scroll = editor.scrollTop * next / editorZoom;
  editorZoom = next;
  editor.style.setProperty("--editor-zoom", editorZoom / 100);
  editor.scrollTop = scroll;
  byId("zoom-reset").textContent = `${editorZoom}%`;
  byId("zoom-out").disabled = editorZoom === 70;
  byId("zoom-in").disabled = editorZoom === 200;
  editorSearch.reveal();
}

byId("editor-zoom").addEventListener("pointerdown", (event) => {
  if (event.target.closest("button") && document.activeElement === editor) event.preventDefault();
});
byId("zoom-out").addEventListener("click", () => setEditorZoom(editorZoom - 10));
byId("zoom-reset").addEventListener("click", () => setEditorZoom(100));
byId("zoom-in").addEventListener("click", () => setEditorZoom(editorZoom + 10));

for (const [key, [min, max, step]] of Object.entries(SETTING_RANGES)) {
  Object.assign(byId(key), { min, max, step });
}
for (const family of Object.keys(FONT_FAMILIES)) byId("fontFamily").add(new Option(family, family));
for (const align of TEXT_ALIGNMENTS) {
  byId("textAlign").add(new Option(align[0].toUpperCase() + align.slice(1), align));
}
for (const [key, value] of Object.entries(DEFAULT_SETTINGS)) {
  byId(key).addEventListener("input", ({ target }) => {
    let next = target.value;
    if (typeof value === "boolean") next = target.checked;
    if (typeof value === "number") next = Number(target.value);
    changeSetting(key, next);
  });
}
byId("reset-presentation").addEventListener("click", () => applySettings(DEFAULT_SETTINGS));

function command(action) {
  flushEdit();
  if (action === "faster" || action === "slower") {
    const speed = settings.speed + (action === "faster" ? SPEED_STEP : -SPEED_STEP);
    changeSetting("speed", Math.max(MIN_SPEED, Math.min(MAX_SPEED, speed)));
    return;
  }
  if (!script.cues.length) return;
  const now = clock();
  let position = positionAt(state, track, now);
  let playing = state.playing && position < script.end;
  let stopImmediately = false;
  switch (action) {
    case "play":
      if (position >= script.end) {
        position = BEGINNING;
        stopTransport(position, now);
      }
      playing = !playing;
      break;
    case "pause":
      playing = false;
      break;
    case "reset":
      position = BEGINNING;
      stopImmediately = true;
      break;
    case "next":
    case "previous": {
      const cue = adjacentCue(script.cues, position, action === "next" ? 1 : -1);
      if (cue === undefined) return;
      position = cue;
      stopImmediately = !playing;
      break;
    }
    default:
      return;
  }
  if (stopImmediately) stopTransport(position, now);
  else setTransport(position, playing, now);
  publish();
  draw();
}

for (const action of ["play", "previous", "next", "reset"]) {
  byId(action).addEventListener("click", () => command(action));
}

window.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (event.detail && button && button === document.activeElement) button.blur();
});

window.addEventListener("keydown", (event) => {
  if (library.open) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f" &&
      !byId("editor-body").hidden && (document.activeElement === editor || searchPanel.contains(event.target))) {
    event.preventDefault();
    editorSearch.open();
    return;
  }
  const action = transportShortcut(event);
  if (!action) return;
  event.preventDefault();
  if (action !== "play" || !event.repeat) command(action);
});

function releasePresenter() {
  const now = clock();
  const position = positionAt(state, track, now);
  clearInterval(popupCheck);
  popup = undefined;
  presenterId = undefined;
  presenterVisible = false;
  presenterReading = undefined;
  byId("open-presenter").textContent = "Open presenter";
  byId("presenter-status").textContent = "Presenter closed";
  if (preview.setPreviewAspect()) previewTrack = preview.measure(script.end);
  track = previewTrack;
  setTransport(position, state.playing, now);
  publish({ layout: true });
  draw();
}

function usePresenterLayout({ width, height, track: measuredTrack }) {
  const now = clock();
  const position = positionAt(state, track, now);
  if (preview.setPreviewAspect(width, height)) previewTrack = preview.measure(script.end);
  // Follow the actual wrapped presenter layout so logical synchronization does not vary its speed.
  track = measuredTrack;
  setTransport(position, state.playing, now);
  publish({ layout: true });
  draw();
}

byId("open-presenter").addEventListener("click", () => {
  if (popup && !popup.closed) {
    popup.close();
    releasePresenter();
    return;
  }
  if (popup) releasePresenter();
  const url = new URL("./presenter.html", location.href);
  url.hash = session;
  popup = window.open(url, "krata-" + session, "popup,width=960,height=540");
  if (popup) {
    byId("open-presenter").textContent = "Close presenter";
    popupCheck = setInterval(() => {
      if (popup?.closed) releasePresenter();
    }, 250);
  }
  byId("presenter-status").textContent = popup ? "Connecting presenter…" : "Allow pop-ups to open presenter";
});
if (!channel) {
  byId("open-presenter").disabled = true;
  byId("presenter-status").textContent = "Presenter requires BroadcastChannel";
}

channel?.addEventListener("message", ({ data }) => {
  if (data.type === "hello") {
    if (!popup || popup.closed) return;
    flushEdit();
    if (presenterId !== data.id) presenterReading = undefined;
    presenterId = data.id;
    presenterVisible = data.visible;
    byId("presenter-status").textContent = "Presenter connected";
    const now = clock();
    setTransport(positionAt(state, track, now), state.playing, now);
    publish({ layout: true, documentChanged: true });
    draw();
    return;
  }
  if (data.id !== presenterId) return;
  if (data.type === "presence" || data.type === "closed") {
    presenterVisible = data.type === "presence" && data.visible;
    if (data.type === "closed") {
      if (popup?.closed) {
        releasePresenter();
        return;
      }
      presenterId = undefined;
      byId("presenter-status").textContent = "Presenter closed";
    }
    refreshVisibility();
  } else if (data.type === "command") {
    command(data.action);
  } else if ((data.type === "ended" || data.type === "settled") && state.moving) {
    draw();
  } else if (data.type === "presenter-layout" && data.scriptRevision === scriptRevision &&
             data.layoutRevision === layoutRevision) {
    usePresenterLayout(data);
  } else if (data.type === "reading-row" && data.scriptRevision === scriptRevision) {
    presenterReading = data;
    showReadingLine(positionAt(state, track, clock()));
  }
});

document.addEventListener("visibilitychange", refreshVisibility);
window.addEventListener("pagehide", () => channel?.postMessage({ type: "disconnect" }));
window.addEventListener("pageshow", () => {
  if (presenterId) publish({ layout: true, documentChanged: true });
});

syncSettings();
preview.apply(settings);
draw();
openPrevious();
