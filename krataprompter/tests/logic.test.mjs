import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_SETTINGS } from "../presentation.mjs";
import { formatScriptVersion, readScriptFile, writeMarkdownFile } from "../script-file.mjs";
import {
  BOLD, ITALIC, UNDERLINE, buildScript, readScript, writeScript,
} from "../script.mjs";
import {
  adjacentCue, BEGINNING, cueIndex, movingAt, PAUSE_RAMP_MS, PLAY_RAMP_MS, positionAt,
  positionAtY, rememberPosition, restorePosition, retimeMotion, transportShortcut, yAtPosition,
} from "../transport.mjs";

test("Datavideo markers handle BOM, CRLF, whitespace and empty cue intervals", () => {
  const source = "\uFEFF\t*#\r\nFörsta stycket.\r\n\r\nFortsättning.\r\n" +
    "\u00a0*# \t\r\n *# \r\nToinen kappale.\r\n*#\r\n\u00a0*#\r\n";
  const lines = readScript(source);
  const script = buildScript(lines);
  const visible = script.lines.map(({ runs }) => runs.map(({ text }) => text).join(""));
  assert.deepEqual(visible, ["Första stycket.", "", "Fortsättning.", "", "Toinen kappale.", ""]);
  assert.deepEqual(script.cues, [0, "Första stycket.\n\nFortsättning.\n\n".length]);
  assert.equal(writeScript(lines), source.slice(1).replaceAll("\r\n", "\n"));
});

test("only standalone markers are removed and whitespace alone has no cue", () => {
  const literal = "Använd *# här.\n* #\n**#\n\t";
  const document = buildScript(readScript(literal));
  assert.equal(document.lines.length, 4);
  assert.deepEqual(document.cues, [0]);
  assert.deepEqual(buildScript(readScript("*#\n\u00a0\n*#\n")).cues, []);
});

test("Markdown preserves Unicode, nested formatting and literal delimiters", () => {
  const source = "**Första** *stycket* _ja_ <u>syksy</u> ***båda*** <u>**yhtä**</u> \\* \\<u>";
  const [line] = readScript(source, true);
  assert.deepEqual(line.filter(({ style }) => style), [
    { text: "Första", style: BOLD }, { text: "stycket", style: ITALIC },
    { text: "ja", style: ITALIC }, { text: "syksy", style: UNDERLINE },
    { text: "båda", style: BOLD | ITALIC }, { text: "yhtä", style: BOLD | UNDERLINE },
  ]);
  assert.deepEqual(readScript(writeScript([line], true), true), [line]);
  assert.equal(writeScript([line]), "Första stycket ja syksy båda yhtä * <u>");
  assert.equal(writeScript(readScript("<script>alert('a')</script> *alone", true)),
    "<script>alert('a')</script> *alone");
});

test("Markdown output round-trips mixed styles, whitespace and adjacent runs", () => {
  const lines = [[
    { text: " ää ", style: 7 }, { text: "ö", style: BOLD }, { text: "ç", style: ITALIC },
    { text: " ** \\ _ ", style: 0 }, { text: "</u>", style: UNDERLINE },
  ], [], [{ text: "*#", style: 0 }]];
  assert.deepEqual(readScript(writeScript(lines, true), true), lines);
});

test("presentation front matter round-trips the entire settings model, manuscript and bookmark", () => {
  const settings = {
    fontSize: 200, fontFamily: "Times New Roman", speed: 67, lineSpacing: 1.56, paragraphSpacing: 24,
    width: 81, horizontalMargin: 12, textAlign: "center", textColor: "#FEDCBA",
    backgroundColor: "#123456", guide: false, guidePosition: 48, guideSize: 32, previewMirror: true,
    previewMirrorVertical: true, presenterMirror: true, presenterMirrorVertical: true,
  };
  const lines = readScript("\n**Första**\n\nStycket.\n *#\t\n<u>Toinen</u> *kappale*.\n*#\n", true);
  const script = buildScript(lines);
  const logical = script.cues[1] + 1.75;
  const position = rememberPosition(script, logical);
  const serialized = writeMarkdownFile(lines, settings, position);
  assert.match(serialized, /^---\nkrataprompter: 1\npresentation:\n/u);
  assert.match(serialized, /textColor: "#FEDCBA"\n/u);
  const opened = readScriptFile(serialized, true);
  assert.deepEqual(opened.lines, lines);
  assert.deepEqual(opened.settings, settings);
  assert.equal(opened.position.cue, 2);
  assert.equal(restorePosition(buildScript(opened.lines), opened.position), logical);
});

test("metadata validates individual fields and accepts the documented example names", () => {
  const source = `---
krataprompter: 1  # Schema version
presentation:  # Defaults fill omitted fields
  fontSize: 500
  fontFamily: 'Times New Roman'
  speed: 85
  lineHeight: 1.4
  paragraphSpacing: -1
  width: .inf
  horizontalMargin: 12
  textAlign: &unsupported center
  textColor: "#abCDef" # Colours are quoted YAML strings
  backgroundColor: "url(https://example.com)"
  mirrorHorizontal: true
  mirrorVertical: true
  readingGuide: false
  readingGuidePosition: 48
  previewMirror: "true"
  undefined: true
position:
  cue: 2
  progress: 2
---
Första.
*#
Toinen.`;
  const opened = readScriptFile("\uFEFF" + source.replaceAll("\n", "\r\n"), true);
  assert.deepEqual(opened.settings, {
    ...DEFAULT_SETTINGS, fontFamily: "Times New Roman", speed: 85, lineSpacing: 1.4,
    horizontalMargin: 12, textColor: "#ABCDEF", presenterMirror: true,
    presenterMirrorVertical: true, guide: false, guidePosition: 48,
  });
  const script = buildScript(opened.lines);
  assert.equal(writeScript(opened.lines), "Första.\n*#\nToinen.");
  assert.equal(restorePosition(script, opened.position), script.cues[1]);
  assert.equal(restorePosition(script, { cue: 3, progress: 0 }), BEGINNING);
});

test("script version uses local minute precision and round-trips as metadata", () => {
  const version = formatScriptVersion(new Date(2026, 0, 4, 9, 5, 47));
  assert.equal(version, "26.01.04 09:05");
  const lines = readScript("Första.\n*#\nToinen.");
  const saved = writeMarkdownFile(lines, DEFAULT_SETTINGS, { cue: 1, progress: 0 }, version, "Kvällens sändning");
  assert.match(saved, /^version: "26\.01\.04 09:05"$/mu);
  assert.equal(readScriptFile(saved, true).version, version);
  assert.equal(readScriptFile(saved, true).title, "Kvällens sändning");
  const invalid = saved.replace(version, "26.02.29 09:05");
  const opened = readScriptFile(invalid, true);
  assert.equal(opened.version, undefined);
  assert.equal(writeScript(opened.lines), "Första.\n*#\nToinen.");
});

test("legacy files, unrelated YAML and unsupported versions use default settings", () => {
  const plain = "---\nHost: An ordinary manuscript\nA second line\n---\nFörsta.";
  assert.equal(writeScript(readScriptFile(plain, true).lines), plain);
  assert.deepEqual(readScriptFile(plain, true).settings, DEFAULT_SETTINGS);
  for (const metadata of ["title: Studio", "krataprompter: 2\npresentation:\n  fontSize: 90"]) {
    const source = `---\n${metadata}\n...\nFörsta.`;
    const markdown = readScriptFile(source, true);
    assert.equal(writeScript(markdown.lines), "Första.");
    assert.deepEqual(markdown.settings, DEFAULT_SETTINGS);
    assert.equal(markdown.position, undefined);
    assert.equal(writeScript(readScriptFile(source, false).lines), source);
  }
});

test("bookmarks retain pre-roll, cue boundaries, mid-cue progress and the end", () => {
  const script = buildScript(readScript("\nFirst.\n*#\nSecond.\n*#\nThird."));
  for (const logical of [BEGINNING, -0.5, ...script.cues, script.cues[1] + 3.5, script.end]) {
    const bookmark = rememberPosition(script, logical);
    assert.equal(restorePosition(script, bookmark), logical);
  }
  const blank = buildScript([]);
  assert.deepEqual(rememberPosition(blank, BEGINNING), { cue: 0, progress: 0 });
  assert.equal(restorePosition(blank, { cue: 1, progress: 0 }), BEGINNING);
});

test("cues can be navigated before the guide, mid-cue and after the last cue", () => {
  const cues = [0, 20, 50];
  assert.equal(cueIndex([], 5), -1);
  assert.equal(cueIndex(cues, BEGINNING), 0);
  assert.equal(cueIndex(cues, 20), 1);
  assert.equal(adjacentCue(cues, BEGINNING, 1), 20);
  assert.equal(adjacentCue(cues, 5, -1), 0);
  assert.equal(adjacentCue(cues, 25, -1), 0);
  assert.equal(adjacentCue(cues, 25, 1), 50);
  assert.equal(adjacentCue(cues, BEGINNING, -1), undefined);
  assert.equal(adjacentCue(cues, 50, 1), undefined);
});

test("transport uses elapsed time and preserves the anchor across speed and wrap changes", () => {
  const reference = [[-1, -100], [0, 0], [50, 100], [100, 200], [150, 500]];
  const narrow = [[-1, -50], [0, 0], [25, 60], [50, 120], [100, 180], [150, 300]];
  const start = { moving: true, position: BEGINNING, at: 1000, speed: 50 };
  assert.equal(positionAt(start, reference, 2000), -0.5);
  assert.equal(positionAt(start, reference, 4000), 25);
  const anchor = positionAt(start, reference, 4000);
  assert.equal(positionAtY(narrow, yAtPosition(narrow, anchor)), anchor);
  const faster = { ...start, at: 4000, position: anchor, speed: 100 };
  assert.equal(positionAt(faster, reference, 4000), 25);
  assert.equal(positionAt(faster, reference, 4500), 50);
  assert.equal(positionAt(faster, reference, 1e6), 150);
  assert.equal(positionAt({ ...faster, moving: false }, reference, 1e6), 25);
});

test("play and pause ease velocity smoothly and stop moving after the pause ramp", () => {
  const track = [[0, 0], [1000, 1000]];
  const still = { position: 0, at: 0, speed: 0, moving: false };
  const ramp = retimeMotion(still, 0, 0, true, 100, PLAY_RAMP_MS);
  assert.equal(positionAt(ramp, track, 125), 2.34375);
  assert.equal(positionAt(ramp, track, 250), 12.5);
  assert.equal(positionAt(ramp, track, 400), 27.5);

  const braking = retimeMotion(ramp, 27.5, 400, true, 0, PAUSE_RAMP_MS);
  assert.equal(positionAt(braking, track, 500), 35.625);
  assert.equal(positionAt(braking, track, 600), 37.5);
  assert.equal(positionAt(braking, track, 4000), 37.5);
  assert.equal(movingAt(braking, 599), true);
  assert.equal(movingAt(braking, 600), false);
});

test("ramp reanchors without a jump across visibility changes and rapid toggling", () => {
  const track = [[0, 0], [1000, 1000]];
  const still = { position: 0, at: 0, speed: 0, moving: false };
  const ramp = retimeMotion(still, 0, 0, true, 100, PLAY_RAMP_MS);
  const atHalf = positionAt(ramp, track, 125);
  const hidden = retimeMotion(ramp, atHalf, 125, false, 100);
  assert.equal(positionAt(hidden, track, 6000), atHalf);
  const visible = retimeMotion(hidden, atHalf, 6000, true, 100);
  assert.equal(positionAt(visible, track, 6125), positionAt(ramp, track, 250));

  const braking = retimeMotion(ramp, atHalf, 125, true, 0, PAUSE_RAMP_MS);
  assert.equal(braking.ramp.from, 50);
  const atToggle = positionAt(braking, track, 175);
  const resume = retimeMotion(braking, atToggle, 175, true, 100, PLAY_RAMP_MS);
  assert.equal(resume.ramp.from, 42.1875);
  assert.equal(positionAt(resume, track, 175), atToggle);
});

test("transport shortcuts preserve editor, composition and input handling", () => {
  const event = { key: " ", target: { closest: () => null } };
  assert.equal(transportShortcut(event), "play");
  assert.equal(transportShortcut({ ...event, key: "ArrowLeft" }), "previous");
  assert.equal(transportShortcut({ ...event, key: "Escape" }), "pause");
  assert.equal(transportShortcut({ ...event, isComposing: true }), undefined);
  assert.equal(transportShortcut({ ...event, ctrlKey: true }), undefined);
  assert.equal(transportShortcut({ ...event, target: { closest: () => ({}) } }), undefined);
});
