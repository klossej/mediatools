# Testing and verification

Run the deterministic parser and transport tests from `krataprompter/` with Node.js 22 or later.

```bash
node --test tests/logic.test.mjs
python3 -m unittest discover -s tests
```

The browser suite uses Playwright and Chromium as test-only tools. It starts the supplied Python server on a free loopback port with a temporary script folder and stops it when the tests finish. Use `python3 serve.py --dev` for manual testing with a separate library.

```bash
npm install --prefix /tmp/krataprompter-qa playwright@1.63.0
/tmp/krataprompter-qa/node_modules/.bin/playwright install chromium
NODE_PATH=/tmp/krataprompter-qa/node_modules node --test tests/browser.cjs
```

## Results, 2026-11-25

All 14 logic tests, 10 storage tests and 10 browser scenarios passed. Browser verification used Playwright 1.63.0 with headless Chromium. The default launcher returned HTTP 200 for the operator, presenter, JavaScript and library on loopback port 25252 in the prototype verification, when the existing AAF Audio Extractor suite also passed all 108 tests.

| Area | Verified |
|---|---|
| Script | UTF-8 Swedish and Finnish text, BOM and CRLF, non-breaking space around Datavideo markers, trailing and consecutive markers, cue spacing in both displays, paragraphs, cue insertion and plain-text paste |
| Local files and formatting | Markdown import and round-trip of bold, italic and underline, UTF-8 text downloads, selected-text formatting, unsaved-change warnings, and local operations without manuscript uploads |
| Server library | UTF-8 Markdown on disk, save and open, previous-script restoration, duplicate names, stale or concurrent saves, exact revision archival before replacement, original preservation on archive failure and isolated development storage |
| Presentation metadata | Save and Save As, visible last-save stamp, full settings including guide arrow size, bookmark round-trip, invalid or missing values, settings-only unsaved changes, default reset, paused reopen, and manuscript-only text export |
| Operator interface | Locally served Inter, MediaBrowser panel styling, bold inline script name and persistence, 200 px text-size limit, preview expansion on collapse, and stacked panels without horizontal overflow at 390 px |
| App identity | Shared favicon and About logo, visual checks at 16–48 px, About keyboard dismissal and focus return, and header fit at 320 px |
| Transport | Play and pause ramps, steady speed across paragraph breaks and uneven wrapping, quick toggles, cue jumps, shortcuts, live speed changes, reset and automatic stop |
| Presenter | Cue placement at 1280×1024 and 1920×1080, resize and font changes, independent mirroring, adjustable guide arrows, fullscreen, companion shortcuts, hidden-operator playback, Close presenter, paused reopen and no catch-up jump after both views are hidden |
| Editor follow | Highlight matches the current wrapped presenter line at a different viewport width, scrollbar follows paragraph and cue changes, and keyboard focus preserves the caret and scroll position |
| Editor tools | Literal case-insensitive search across styled spans, match navigation and selection, and editor-only zoom with caret preservation |

The browser tests simulate visibility transitions and use virtual viewports. Physical monitor placement, teleprompter glass and playback with the production workstation's browser and display settings remain part of the on-site rehearsal. See the [operator guide](OPERATOR_GUIDE.md).
