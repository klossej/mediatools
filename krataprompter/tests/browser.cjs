const assert = require("node:assert/strict");
const { execFile } = require("node:child_process");
const { createHash } = require("node:crypto");
const { mkdtemp, readFile, rm } = require("node:fs/promises");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { after, before, test } = require("node:test");
const { chromium } = require("playwright");

let server;
let browser;
let baseURL;
let dataDirectory;
const promptPath = path.resolve(__dirname, "..");

before(async () => {
  dataDirectory = await mkdtemp(path.join(tmpdir(), "krata-browser-"));
  server = execFile("python3", ["serve.py", "--port", "0", "--data-dir", dataDirectory], {
    cwd: promptPath,
  });
  const port = await new Promise((resolve, reject) => {
    server.on("error", reject);
    server.on("exit", (code) => reject(new Error(`Test server exited: ${code}`)));
    server.stdout.on("data", (data) => {
      const match = data.match(/port (\d+)/u);
      if (match) resolve(match[1]);
    });
  });
  baseURL = `http://127.0.0.1:${port}`;
  browser = await chromium.launch({ headless: true });
});

after(async () => {
  await browser?.close();
  if (server && server.exitCode === null && server.signalCode === null) {
    const closed = new Promise((resolve) => server.once("exit", resolve));
    server.kill();
    await closed;
  }
  if (dataDirectory) await rm(dataDirectory, { recursive: true, force: true });
});

function importFile(page, name, text) {
  return page.locator("#script-file").setInputFiles({
    name, mimeType: "text/plain", buffer: Buffer.from(text),
  });
}

async function download(page, selector) {
  const result = page.waitForEvent("download");
  await page.locator(selector).click();
  const file = await result;
  return { name: file.suggestedFilename(), text: await readFile(await file.path(), "utf8") };
}

async function saveToServer(page, selector, name) {
  const response = page.waitForResponse((entry) => entry.url().endsWith("/api/scripts/save"));
  await page.locator(selector).click();
  const saved = await response;
  assert.equal(saved.status(), 200, await saved.text());
  await waitText(page, "#file-name", name);
  await waitText(page, "#file-status", "Saved to server");
  return { name, text: await readFile(path.join(dataDirectory, name), "utf8") };
}

async function openFromServer(page, name) {
  await page.getByRole("button", { name: "Open Script", exact: true }).click();
  await page.waitForFunction((name) => [...document.querySelector("#server-script").options]
    .some((option) => option.value === name), name);
  await page.locator("#server-script").selectOption(name);
  await page.locator("#open-selection").click();
  await waitText(page, "#file-name", name);
  await waitText(page, "#file-status", "Opened from server");
}

function waitText(page, selector, text) {
  return page.waitForFunction(({ selector, text }) =>
    document.querySelector(selector).textContent === text, { selector, text });
}

function range(page, id, value) {
  return page.locator("#" + id).evaluate((input, next) => {
    input.value = next;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, String(value));
}

function translation(page) {
  return page.locator(".sheet").evaluate((sheet) =>
    new DOMMatrixReadOnly(getComputedStyle(sheet).transform).m42);
}

function waitForMotion(page, from, distance) {
  return page.waitForFunction(({ from, distance }) => {
    const sheet = document.querySelector(".sheet");
    return new DOMMatrixReadOnly(getComputedStyle(sheet).transform).m42 < from - distance;
  }, { from, distance });
}

function centerAtGuide(page, content) {
  return page.waitForFunction((content) => {
    const block = [...document.querySelector(".sheet").children]
      .find((element) => element.textContent.startsWith(content));
    if (!block) return false;
    const text = document.createRange();
    const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    text.setStart(walker.nextNode(), 0);
    text.setEnd(walker.currentNode, 1);
    const rect = text.getBoundingClientRect();
    const guide = document.querySelector(".reading-guide").getBoundingClientRect();
    return Math.abs((rect.top + rect.bottom) / 2 - guide.top) < 3;
  }, content);
}

async function setHidden(page, hidden) {
  await page.evaluate((hidden) => {
    Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

test("operator panels use the locally bundled Inter and adapt to narrow viewports", async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    const fontResponse = page.waitForResponse((entry) => entry.url().endsWith("/inter-latin-variable.woff2"));
    await page.goto(baseURL);
    assert.equal((await fontResponse).headers()["content-type"], "font/woff2");
    assert.equal(await page.locator("#fontSize").getAttribute("max"), "200");
    const font = await page.evaluate(async () => {
      const [face] = await document.fonts.load('600 13px "Inter Variable"', "KråtaPrompter");
      return { status: face?.status, family: getComputedStyle(document.querySelector(".app-header")).fontFamily };
    });
    assert.equal(font.status, "loaded");
    assert.ok(font.family.startsWith('"Inter Variable"'));
    const editor = page.locator(".editor-panel");
    const preview = page.locator(".preview-panel");
    const settings = page.locator(".settings");
    const wide = await Promise.all([editor.boundingBox(), preview.boundingBox(), settings.boundingBox()]);
    assert.equal(wide[0].y, wide[1].y);
    assert.equal(wide[1].y, wide[2].y);
    assert.ok(wide[0].x < wide[1].x && wide[1].x < wide[2].x);
    assert.equal(await preview.evaluate((panel) => getComputedStyle(panel).borderRadius), "8px");
    assert.equal(await page.locator("#preview-heading").evaluate((heading) =>
      getComputedStyle(heading).color), "rgb(163, 230, 53)");

    await page.locator("#toggle-editor").click();
    assert.ok((await preview.boundingBox()).width > wide[1].width);
    await page.locator("#toggle-editor").click();
    await page.setViewportSize({ width: 390, height: 844 });
    const narrow = await Promise.all([editor.boundingBox(), preview.boundingBox(), settings.boundingBox()]);
    assert.equal(narrow[0].x, narrow[1].x);
    assert.equal(narrow[1].x, narrow[2].x);
    assert.ok(narrow[0].y < narrow[1].y && narrow[1].y < narrow[2].y);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 390);
    await page.locator("#guideSize").scrollIntoViewIfNeeded();
    assert.ok((await page.locator("#script-version").boundingBox()).y >= 0);
  } finally {
    await page.close();
  }
});

test("the favicon and About dialog share the same logo", async () => {
  const page = await browser.newPage({ viewport: { width: 320, height: 820 } });
  try {
    await page.goto(baseURL);
    const favicon = page.locator('link[rel="icon"]');
    const href = await favicon.getAttribute("href");
    const asset = await page.request.get(new URL(href, baseURL).href);
    assert.equal(asset.status(), 200);
    assert.equal(asset.headers()["content-type"], "image/svg+xml");
    const presenterPage = await page.request.get(baseURL + "/presenter.html");
    assert.match(await presenterPage.text(), /rel="icon" href="\.\/icon\.svg"/u);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth), 320);

    await importFile(page, "about-check.txt", "Första raden.\n\nToinen rivi.\n\nSista raden.");
    await waitText(page, "#cue-status", "Cue 1 / 1");
    await page.locator("#play").click();
    const trigger = page.getByRole("button", { name: "About", exact: true });
    await trigger.click();
    const dialog = page.getByRole("dialog", { name: "KråtaPrompter" });
    const logo = dialog.locator("img");
    assert.equal(await logo.getAttribute("src"), href);
    assert.ok((await logo.boundingBox()).width >= 96);
    assert.ok(await logo.evaluate((image) => image.complete && image.naturalWidth > 0));
    assert.equal(await dialog.getByText("Version 1.0").isVisible(), true);

    await page.keyboard.press("Escape");
    assert.equal(await dialog.isVisible(), false);
    assert.equal(await trigger.evaluate((element) => document.activeElement === element), true);
    assert.equal(await page.locator("#playback-status").textContent(), "Playing");
    await trigger.click();
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    assert.equal(await dialog.isVisible(), false);
  } finally {
    await page.close();
  }
});

test("HTTP editor handles UTF-8, formatted Markdown, text downloads, paste and cue insertion", async () => {
  const page = await browser.newPage();
  const errors = [];
  const requests = [];
  page.on("pageerror", (error) => errors.push(error));
  page.on("request", (request) => requests.push(request));
  try {
    await page.goto(baseURL);
    const source = "**Första** *stycket* <u>så här</u>.\r\n\r\n" +
      "\u00a0*# \r\n*#\r\nToinen kappale.\r\n*#";
    await importFile(page, "sv-fi.md", source);
    await waitText(page, "#cue-status", "Cue 1 / 2");
    assert.equal(await page.locator(".sheet strong").textContent(), "Första");
    assert.equal(await page.locator(".sheet em").textContent(), "stycket");
    assert.equal(await page.locator(".sheet u").textContent(), "så här");
    assert.equal(await page.locator(".sheet").textContent(), "Första stycket så här.Toinen kappale.");
    assert.deepEqual(await page.locator(".sheet > div").allTextContents(),
      ["Första stycket så här.", "", "", "Toinen kappale."]);

    const formatted = await download(page, "#download-markdown");
    assert.equal(formatted.name, "sv-fi.md");
    await importFile(page, formatted.name, formatted.text);
    await waitText(page, "#file-status", "File opened");
    assert.equal(await page.locator("#script-editor u").textContent(), "så här");
    page.once("dialog", (dialog) => dialog.accept());
    const plain = await download(page, "#save-text");
    assert.equal(plain.name, "sv-fi.txt");
    assert.equal(plain.text, "Första stycket så här.\n\n\u00a0*# \n*#\nToinen kappale.\n*#");

    const editor = page.locator("#script-editor");
    await importFile(page, plain.name, plain.text);
    await waitText(page, "#file-name", "sv-fi.txt");
    await editor.evaluate((element) => {
      element.focus();
      const selection = getSelection();
      selection.selectAllChildren(element);
      const data = new DataTransfer();
      data.setData("text/plain", "Åland\n\nHär finns ääkkösiä.\n *# \nLoppu.");
      element.dispatchEvent(new ClipboardEvent("paste", { bubbles: true, clipboardData: data }));
    });
    await waitText(page, "#cue-status", "Cue 1 / 2");
    await page.waitForFunction(() => document.querySelector(".sheet").textContent.includes("ääkkösiä"));
    assert.equal(await page.locator(".sheet").textContent(), "ÅlandHär finns ääkkösiä.Loppu.");
    assert.deepEqual(await page.locator(".sheet > div").allTextContents(),
      ["Åland", "", "Här finns ääkkösiä.", "", "Loppu."]);

    await editor.evaluate((element) => {
      const selection = getSelection();
      selection.selectAllChildren(element);
      selection.collapseToEnd();
    });
    await page.getByRole("button", { name: "Insert cue" }).click();
    await page.keyboard.insertText("Ett nytt stycke.");
    await waitText(page, "#cue-status", "Cue 1 / 3");
    assert.match((await download(page, "#download-markdown")).text, /Loppu\.\n\*#\nEtt nytt stycke\./u);

    await editor.evaluate((element) => {
      const node = document.createTreeWalker(element, NodeFilter.SHOW_TEXT).nextNode();
      const range = document.createRange();
      range.selectNodeContents(node);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
    });
    for (const name of ["Bold", "Italic", "Underline"]) {
      await page.getByRole("button", { name, exact: true }).click();
    }
    await page.waitForFunction(() => document.querySelector(".sheet strong em u")?.textContent === "Åland");
    assert.match((await download(page, "#download-markdown")).text,
      /<strong><em><u>Åland<\/u><\/em><\/strong>/u);

    await editor.focus();
    await page.keyboard.press("End");
    await page.keyboard.insertText("!");
    assert.equal(await page.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    }), true);
    const canceled = page.waitForEvent("dialog");
    const replacement = importFile(page, "replace.txt", "New file");
    await (await canceled).dismiss();
    await replacement;
    assert.equal(await page.locator("#file-name").textContent(), "sv-fi.txt *");
    const accepted = page.waitForEvent("dialog");
    const open = importFile(page, "replace.txt", "New file");
    await (await accepted).accept();
    await open;
    await waitText(page, "#file-name", "replace.txt");
    assert.equal(await page.locator(".sheet").textContent(), "New file");
    await page.locator("#toggle-editor").click();
    assert.equal(await editor.isVisible(), false);
    await page.locator("#toggle-editor").click();
    assert.equal(await editor.isVisible(), true);

    assert.deepEqual(errors, []);
    assert.ok(requests.every((request) => request.method() === "GET" &&
      request.postData() === null && request.url().startsWith(baseURL)));
  } finally {
    await page.close();
  }
});

test("operator shortcuts, playback and speed respect editor focus and stop at the end", async () => {
  const page = await browser.newPage();
  try {
    await page.goto(baseURL);
    await importFile(page, "transport.txt", "Alku.\n*#\nMellan.\n*#\nLoppu.");
    await waitText(page, "#cue-status", "Cue 1 / 3");
    await page.locator("#script-editor").focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("Space");
    assert.equal(await page.locator("#playback-status").textContent(), "Ready");
    assert.equal(await page.locator("#cue-status").textContent(), "Cue 1 / 3");
    assert.equal(await page.locator("#speed").inputValue(), "50");
    await page.locator("#script-editor").evaluate((editor) => editor.blur());
    await page.keyboard.press("ArrowRight");
    await waitText(page, "#cue-status", "Cue 2 / 3");
    await page.keyboard.press("ArrowLeft");
    await waitText(page, "#cue-status", "Cue 1 / 3");

    await page.keyboard.press("Space");
    await waitText(page, "#playback-status", "Playing");
    const start = await translation(page);
    await waitForMotion(page, start, 8);
    await page.keyboard.press("ArrowUp");
    assert.equal(await page.locator("#speed").inputValue(), "55");
    await page.keyboard.press("ArrowDown");
    assert.equal(await page.locator("#speed").inputValue(), "50");
    await page.locator("#next").click();
    await waitText(page, "#cue-status", "Cue 2 / 3");
    assert.equal(await page.locator("#playback-status").textContent(), "Playing");
    const braking = await page.evaluate(() => {
      document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
      const translate = new DOMMatrixReadOnly(getComputedStyle(document.querySelector(".sheet")).transform).m42;
      return { translate, status: document.querySelector("#playback-status").textContent };
    });
    assert.equal(braking.status, "Pausing");
    await waitText(page, "#playback-status", "Paused");
    assert.ok(await translation(page) < braking.translate - 0.5);
    await page.keyboard.press("Home");
    await waitText(page, "#playback-status", "Ready");

    await range(page, "speed", 240);
    await page.locator("#next").click();
    await page.locator("#next").click();
    await page.locator("#play").click();
    await waitText(page, "#playback-status", "End of script");
    const stopped = await translation(page);
    await page.waitForTimeout(100);
    assert.equal(await translation(page), stopped);
    assert.equal(await page.locator("#play").textContent(), "Replay");
  } finally {
    await page.close();
  }
});

test("presenter stays in sync across wrapping, focus changes, mirroring, fullscreen and reopen", async () => {
  const operator = await browser.newPage({ viewport: { width: 1600, height: 950 } });
  const errors = [];
  operator.on("pageerror", (error) => errors.push(error));
  try {
    await operator.goto(baseURL);
    const longLine = "KråtaPrompter pitää tekstin samassa lukukohdassa. ".repeat(10);
    await importFile(operator, "live.txt", `${longLine}\n*#\nAndra cue. ${longLine}\n*#\nTredje cue.`);
    await waitText(operator, "#cue-status", "Cue 1 / 3");
    async function openPresenter() {
      const opening = operator.waitForEvent("popup");
      await operator.locator("#open-presenter").click();
      const presenter = await opening;
      presenter.on("pageerror", (error) => errors.push(error));
      await waitText(operator, "#presenter-status", "Presenter connected");
      await presenter.waitForFunction(() => document.querySelector(".sheet").children.length === 5);
      assert.deepEqual(await presenter.locator(".sheet > div").allTextContents(),
        [longLine, "", "Andra cue. " + longLine, "", "Tredje cue."]);
      return presenter;
    }
    let presenter = await openPresenter();
    await presenter.setViewportSize({ width: 1280, height: 1024 });
    await operator.locator("#next").click();
    await centerAtGuide(operator, "Andra cue.");
    await centerAtGuide(presenter, "Andra cue.");
    await range(operator, "fontSize", 90);
    await range(operator, "lineSpacing", 1.6);
    await range(operator, "width", 74);
    await presenter.setViewportSize({ width: 1920, height: 1080 });
    await centerAtGuide(operator, "Andra cue.");
    await centerAtGuide(presenter, "Andra cue.");
    assert.equal(await presenter.locator(".sheet").evaluate((element) =>
      getComputedStyle(element).fontSize), "90px");

    await operator.locator("#presenterMirror").check();
    await presenter.waitForFunction(() => getComputedStyle(document.querySelector(".glass")).transform
      .startsWith("matrix(-1,"));
    assert.equal(await operator.locator(".glass").evaluate((element) =>
      getComputedStyle(element).transform), "none");
    await operator.locator("#guide").uncheck();
    await presenter.waitForFunction(() => getComputedStyle(document.querySelector(".reading-guide"))
      .visibility === "hidden");
    await presenter.locator(".stage").dblclick({ position: { x: 20, y: 20 } });
    await presenter.waitForFunction(() => Boolean(document.fullscreenElement));
    assert.equal(await presenter.locator("button").count(), 0);
    assert.equal(await presenter.locator(".stage").evaluate((element) =>
      getComputedStyle(element).backgroundColor), "rgb(0, 0, 0)");

    await operator.locator("#play").click();
    await presenter.bringToFront();
    await setHidden(operator, true);
    const start = await translation(presenter);
    await waitForMotion(presenter, start, 10);
    await presenter.keyboard.press("ArrowRight");
    await waitText(operator, "#cue-status", "Cue 3 / 3");
    const advanced = await translation(presenter);
    await waitForMotion(presenter, advanced, 5);
    await presenter.keyboard.press("Escape");
    await waitText(operator, "#playback-status", "Paused");
    await setHidden(operator, false);
    const saved = await translation(presenter);
    await waitText(operator, "#open-presenter", "Close presenter");
    const closed = presenter.waitForEvent("close");
    await operator.getByRole("button", { name: "Close presenter", exact: true }).click();
    await closed;
    await waitText(operator, "#presenter-status", "Presenter closed");
    await waitText(operator, "#open-presenter", "Open presenter");
    presenter = await openPresenter();
    await presenter.setViewportSize({ width: 1920, height: 1080 });
    await presenter.waitForFunction((saved) => {
      const sheet = document.querySelector(".sheet");
      return Math.abs(new DOMMatrixReadOnly(getComputedStyle(sheet).transform).m42 - saved) < 3;
    }, saved);
    await operator.locator("#play").click();
    await setHidden(presenter, true);
    await setHidden(operator, true);
    await operator.waitForTimeout(70);
    const suspended = await translation(operator);
    await operator.waitForTimeout(350);
    await setHidden(operator, false);
    assert.ok(Math.abs(await translation(operator) - suspended) < 8);
    assert.deepEqual(errors, []);
    await presenter.close();
    await waitText(operator, "#open-presenter", "Open presenter");
  } finally {
    await operator.context().close();
  }
});

test("Save and Save As round-trip the presentation and reading position while paused", async () => {
  const operator = await browser.newPage({ viewport: { width: 1600, height: 950 }, timezoneId: "UTC" });
  const errors = [];
  operator.on("pageerror", (error) => errors.push(error));
  try {
    await operator.clock.setFixedTime(new Date("2026-11-24T20:15:00Z"));
    await operator.goto(baseURL);
    const manuscript = "**Första stycket.**\n*#\n" + "Toinen kappale ja esimerkki. ".repeat(14) +
      "\nSeuraava rivi.\n*#\nSista stycket.";
    await importFile(operator, "studio.md", manuscript);
    await waitText(operator, "#cue-status", "Cue 1 / 3");
    await waitText(operator, "#script-name", "studio");
    assert.equal(await operator.locator("#script-name").evaluate((element) => getComputedStyle(element).fontWeight), "700");
    await operator.locator("#script-name").click();
    await operator.locator("#script-name-input").fill("Kvällens sändning");
    await operator.locator("#script-name-input").press("Enter");
    await waitText(operator, "#script-name", "Kvällens sändning");
    await waitText(operator, "#file-name", "studio.md *");
    const opening = operator.waitForEvent("popup");
    await operator.locator("#open-presenter").click();
    const presenter = await opening;
    presenter.on("pageerror", (error) => errors.push(error));
    await presenter.setViewportSize({ width: 1920, height: 1080 });
    await waitText(operator, "#presenter-status", "Presenter connected");

    const numeric = {
      fontSize: 80, speed: 87, paragraphSpacing: 24, lineSpacing: 1.4,
      width: 83, horizontalMargin: 13, guidePosition: 42, guideSize: 40,
    };
    for (const [key, value] of Object.entries(numeric)) await range(operator, key, value);
    await operator.locator("#fontFamily").selectOption("Georgia");
    await operator.locator("#textAlign").selectOption("center");
    await range(operator, "textColor", "#f4dcab");
    await range(operator, "backgroundColor", "#231740");
    await operator.locator("#guide").uncheck();
    for (const key of ["previewMirror", "previewMirrorVertical", "presenterMirror", "presenterMirrorVertical"]) {
      await operator.locator("#" + key).check();
    }
    await waitText(operator, "#file-name", "studio.md *");
    assert.equal(await operator.evaluate(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    }), true);

    await operator.locator("#next").click();
    await waitText(operator, "#cue-status", "Cue 2 / 3");
    await operator.locator("#play").click();
    await waitText(operator, "#playback-status", "Playing");
    const start = await translation(operator);
    await waitForMotion(operator, start, 18);
    await operator.locator("#play").click();
    await waitText(operator, "#playback-status", "Paused");
    await presenter.waitForFunction(() => {
      const stage = document.querySelector(".stage");
      const sheet = stage.querySelector(".sheet");
      const guide = stage.querySelector(".reading-guide");
      return getComputedStyle(stage.querySelector(".glass")).transform === "matrix(-1, 0, 0, -1, 0, 0)" &&
        getComputedStyle(stage).backgroundColor === "rgb(35, 23, 64)" &&
        getComputedStyle(sheet).color === "rgb(244, 220, 171)" &&
        getComputedStyle(sheet).fontFamily.startsWith("Georgia") &&
        getComputedStyle(sheet).textAlign === "center" &&
        getComputedStyle(sheet).fontSize === "80px" &&
        getComputedStyle(sheet).lineHeight === "112px" &&
        getComputedStyle(sheet.children[1]).marginTop === "24px" &&
        Math.abs(sheet.getBoundingClientRect().width - stage.clientWidth * 0.74) < 1 &&
        getComputedStyle(guide, "::before").borderLeftWidth === "20px" &&
        getComputedStyle(guide).visibility === "hidden" &&
        Math.abs(guide.getBoundingClientRect().top - stage.clientHeight * 0.58) < 1;
    });

    operator.once("dialog", (dialog) => dialog.accept("Studio Åä"));
    const saved = await saveToServer(operator, "#save-as", "Studio Åä.md");
    await waitText(operator, "#script-version", "Version 26.11.24 20:15");
    await operator.locator("#toggle-editor").click();
    assert.equal(await operator.locator("#script-version").isVisible(), true);
    await operator.locator("#toggle-editor").click();
    assert.deepEqual(await download(operator, "#download-markdown"), saved);
    const { readScriptFile } = await import("../script-file.mjs");
    const { writeScript } = await import("../script.mjs");
    const { DEFAULT_SETTINGS } = await import("../presentation.mjs");
    const data = readScriptFile(saved.text, true);
    assert.equal(data.version, "26.11.24 20:15");
    assert.equal(data.title, "Kvällens sändning");
    const custom = {
      ...numeric, fontFamily: "Georgia", textAlign: "center", textColor: "#F4DCAB",
      backgroundColor: "#231740", guide: false, previewMirror: true,
      previewMirrorVertical: true, presenterMirror: true, presenterMirrorVertical: true,
    };
    assert.deepEqual(data.settings, custom);
    assert.equal(data.position.cue, 2);
    assert.ok(data.position.progress > 0 && data.position.progress < 1);
    assert.equal(writeScript(data.lines, true), manuscript.replace("**Första stycket.**", "<strong>Första stycket.</strong>"));
    const before = await translation(operator);
    const beforePresenter = await translation(presenter);

    // Opening a legacy file resets inherited settings and pauses active playback.
    await operator.locator("#play").click();
    await importFile(operator, "legacy.md", "Legacy script.");
    await waitText(operator, "#playback-status", "Ready");
    await waitText(operator, "#file-name", "legacy.md");
    assert.deepEqual(readScriptFile((await saveToServer(operator, "#save-markdown", "legacy.md")).text, true).settings,
      DEFAULT_SETTINGS);

    await openFromServer(operator, saved.name);
    await waitText(operator, "#script-version", "Version 26.11.24 20:15");
    await waitText(operator, "#script-name", "Kvällens sändning");
    await operator.locator("#script-name").click();
    await operator.locator("#script-name-input").fill("Discarded title");
    await operator.locator("#script-name-input").press("Escape");
    await waitText(operator, "#script-name", "Kvällens sändning");
    assert.equal(await operator.locator("#file-name").textContent(), "Studio Åä.md");
    await waitText(operator, "#playback-status", "Paused");
    await waitText(operator, "#cue-status", "Cue 2 / 3");
    await presenter.waitForFunction((before) =>
      Math.abs(new DOMMatrixReadOnly(getComputedStyle(document.querySelector(".sheet")).transform).m42 -
        before) < 0.1, beforePresenter);
    assert.ok(Math.abs(await translation(operator) - before) < 0.1);
    await operator.waitForTimeout(120);
    assert.ok(Math.abs(await translation(operator) - before) < 0.1);
    for (const [key, value] of Object.entries(custom)) {
      const control = operator.locator("#" + key);
      if (typeof value === "boolean") assert.equal(await control.isChecked(), value);
      else assert.equal(await control.inputValue(), key.endsWith("Color") ? value.toLowerCase() : String(value));
    }
    for (const display of [operator.locator("#script-editor"), operator.locator(".sheet"), presenter.locator(".sheet")]) {
      const text = await display.textContent();
      assert.ok(text.includes("Första stycket."));
      assert.ok(!text.includes("krataprompter:"));
    }

    await operator.locator("#reset-presentation").click();
    await waitText(operator, "#file-name", "Studio Åä.md *");
    await waitText(operator, "#cue-status", "Cue 2 / 3");
    await waitText(operator, "#playback-status", "Paused");
    operator.once("dialog", (dialog) => dialog.accept());
    const exported = await download(operator, "#save-text");
    assert.equal(exported.text, writeScript(data.lines));
    assert.equal(await operator.locator("#file-name").textContent(), "Studio Åä.md *");
    await waitText(operator, "#script-version", "Version 26.11.24 20:15");

    await operator.clock.setFixedTime(new Date("2026-11-24T20:16:00Z"));
    const reset = readScriptFile((await saveToServer(operator, "#save-markdown", saved.name)).text, true);
    assert.deepEqual(reset.settings, DEFAULT_SETTINGS);
    assert.deepEqual(reset.position, data.position);
    assert.equal(reset.version, "26.11.24 20:16");
    assert.equal(reset.title, data.title);
    await waitText(operator, "#script-version", "Version 26.11.24 20:16");
    await waitText(operator, "#file-name", "Studio Åä.md");
    assert.deepEqual(errors, []);
  } finally {
    await operator.context().close();
  }
});

test("a fresh operator opens the server's previous script and protects later edits", async () => {
  const { readScript, buildScript } = await import("../script.mjs");
  const { writeMarkdownFile } = await import("../script-file.mjs");
  const { DEFAULT_SETTINGS } = await import("../presentation.mjs");
  const lines = readScript("Ensimmäinen.\n*#\nAndra cue.\nSista raden.");
  assert.equal(buildScript(lines).cues.length, 2);
  const content = writeMarkdownFile(lines, { ...DEFAULT_SETTINGS, fontSize: 76 }, { cue: 2, progress: 0.25 });
  const old = await browser.newPage();
  const fresh = await browser.newPage();
  try {
    for (const name of ["Earlier.md", "Evening Å.md"]) {
      const response = await old.request.post(baseURL + "/api/scripts/save", { data: { name, content } });
      assert.equal(response.status(), 200);
    }
    await old.goto(baseURL);
    await waitText(old, "#file-name", "Evening Å.md");
    await waitText(old, "#cue-status", "Cue 2 / 2");
    await waitText(old, "#playback-status", "Paused");
    assert.equal(await old.locator("#fontSize").inputValue(), "76");
    await openFromServer(old, "Earlier.md");

    await fresh.goto(baseURL);
    await waitText(fresh, "#file-name", "Earlier.md");
    await waitText(fresh, "#playback-status", "Paused");
    assert.equal(await fresh.locator("#fontSize").inputValue(), "76");

    await range(fresh, "fontSize", 86);
    await saveToServer(fresh, "#save-markdown", "Earlier.md");
    const oldRevision = createHash("sha256").update(content, "utf8").digest("hex") + ".md";
    assert.equal(await readFile(path.join(dataDirectory, ".revisions", "Earlier.md", oldRevision), "utf8"), content);
    await range(old, "fontSize", 96);
    await old.locator("#save-markdown").click();
    await waitText(old, "#file-status", "The server copy changed. Use Save As or reopen it.");
    assert.equal(await old.locator("#file-name").textContent(), "Earlier.md *");

    const results = await Promise.all([
      fresh.request.get(baseURL + "/.krataprompter-data/Earlier.md"),
      fresh.request.get(baseURL + "/.revisions/Earlier.md/" + oldRevision),
      fresh.request.get(baseURL + "/serve.py"),
      fresh.request.post(baseURL + "/api/scripts/save", {
        headers: { Origin: "http://example.com" }, data: { name: "Extern.md", content },
      }),
      fresh.request.post(baseURL + "/api/scripts/open", { data: { name: "../Earlier.md" } }),
    ]);
    assert.deepEqual(results.map((response) => response.status()), [404, 404, 404, 403, 400]);
    const previous = await fresh.request.get(baseURL + "/api/scripts/previous");
    assert.equal(previous.headers()["cache-control"], "no-store");
    assert.equal((await previous.json()).script.name, "Earlier.md");
    await fresh.reload();
    await waitText(fresh, "#file-name", "Earlier.md");
    assert.equal(await fresh.locator("#fontSize").inputValue(), "86");
  } finally {
    await Promise.all([old.close(), fresh.close()]);
  }
});

test("the editor highlights the presenter row and follows it without moving an active caret", async () => {
  const operator = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await operator.goto(baseURL);
    const paragraph = "Tavoite on näyttää tämä lause oikein erittäin kapeassa esitysikkunassa.";
    const long = [
      ...Array.from({ length: 48 }, (_, row) => `Rivi ${row + 1} tekstissä.`),
      "*#", paragraph,
      ...Array.from({ length: 18 }, (_, row) => `Fortsättning ${row + 1}.`),
      "*#", "Sista stycket.",
    ].join("\n");
    await importFile(operator, "follow.txt", long);
    await waitText(operator, "#cue-status", "Cue 1 / 3");

    function highlightedText() {
      return [...CSS.highlights.get("krata-reading")][0]?.toString() ?? "";
    }
    const highlight = () => operator.evaluate(highlightedText);
    await operator.locator("#next").click();
    await waitText(operator, "#cue-status", "Cue 2 / 3");
    const wideRow = await highlight();
    assert.ok(wideRow.startsWith("Tavoite"));
    const editor = operator.locator("#script-editor");
    assert.ok(await editor.evaluate((element) => element.scrollTop) > 200);

    const opening = operator.waitForEvent("popup");
    await operator.locator("#open-presenter").click();
    const presenter = await opening;
    await presenter.setViewportSize({ width: 420, height: 900 });
    await waitText(operator, "#presenter-status", "Presenter connected");
    await operator.waitForFunction((limit) => {
      const row = [...CSS.highlights.get("krata-reading")][0]?.toString();
      return row?.startsWith("Tavoite") && row.length < limit;
    }, wideRow.length);

    await editor.evaluate((element) => {
      element.focus();
      const range = document.createRange();
      range.setStart(element.firstElementChild.firstChild, 2);
      range.collapse(true);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
      element.scrollTop = 0;
    });
    await operator.locator("#next").evaluate((button) => button.click());
    await waitText(operator, "#cue-status", "Cue 3 / 3");
    await operator.waitForFunction(() => [...CSS.highlights.get("krata-reading")][0]?.toString() === "Sista stycket.");
    assert.equal(await highlight(), "Sista stycket.");
    assert.deepEqual(await editor.evaluate((element) => ({
      top: element.scrollTop,
      focused: document.activeElement === element,
      line: getSelection().anchorNode.textContent,
      offset: getSelection().anchorOffset,
    })), { top: 0, focused: true, line: "Rivi 1 tekstissä.", offset: 2 });

    await editor.evaluate((element) => element.blur());
    await operator.waitForFunction(() => document.querySelector("#script-editor").scrollTop > 200);
    assert.equal(await editor.evaluate((element) => element.textContent.includes("*#")), true);
    await presenter.close();
  } finally {
    await operator.context().close();
  }
});

test("the presenter keeps a steady pace across paragraphs with different wrapping", async () => {
  const operator = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await operator.goto(baseURL);
    const paragraphs = "Pitempi kappale rivittyy eri tavalla kapeassa esitysikkunassa. ".repeat(8);
    const lead = Array.from({ length: 45 }, (_, index) => `Start ${index + 1}.`).join("\n");
    await importFile(operator, "pace.txt", lead + "\n*#\nKort.\n\n" + [paragraphs, paragraphs].join("\n\n"));
    await waitText(operator, "#cue-status", "Cue 1 / 2");
    await range(operator, "fontSize", 64);
    await range(operator, "paragraphSpacing", 24);
    await range(operator, "speed", 180);
    const opening = operator.waitForEvent("popup");
    await operator.locator("#open-presenter").click();
    const presenter = await opening;
    await presenter.setViewportSize({ width: 600, height: 900 });
    await operator.waitForFunction(() => document.querySelector(".preview-stage").style.width === "720px");
    await operator.locator("#next").click();
    await centerAtGuide(presenter, "Kort.");
    const startingScroll = await operator.locator("#script-editor").evaluate((element) => element.scrollTop);
    const start = await translation(presenter);
    await operator.locator("#play").click();
    await waitForMotion(presenter, start, 35);
    const samples = await presenter.evaluate(() => new Promise((resolve) => {
      const sheet = document.querySelector(".sheet");
      const points = [];
      function sample(time) {
        if (!points.length || time - points.at(-1).time >= 185) {
          const y = new DOMMatrixReadOnly(getComputedStyle(sheet).transform).m42;
          points.push({ time, y });
        }
        if (points.length < 8) requestAnimationFrame(sample);
        else resolve(points);
      }
      requestAnimationFrame(sample);
    }));
    const pixelsPerSecond = 180 * 900 / 1080;
    for (let index = 1; index < samples.length; index++) {
      const a = samples[index - 1];
      const b = samples[index];
      const expectedTravel = (b.time - a.time) * pixelsPerSecond / 1000;
      assert.ok(Math.abs(a.y - b.y - expectedTravel) < 5,
        `Presenter travelled ${a.y - b.y}px, expected ${expectedTravel}px`);
    }
    await operator.waitForFunction((before) => document.querySelector("#script-editor").scrollTop > before + 20,
      startingScroll);
    await presenter.close();
  } finally {
    await operator.context().close();
  }
});

test("Find searches the manuscript literally and editor zoom preserves presentation text", async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await page.goto(baseURL);
    const editor = page.locator("#script-editor");
    const manuscript = "**Första** raden [mål].\n" +
      Array.from({ length: 60 }, (_, index) => `Mellanrad ${index + 1}.`).join("\n") +
      "\nSista raden [MÅL].";
    await importFile(page, "search.md", manuscript);
    await waitText(page, "#file-name", "search.md");
    await editor.focus();
    await page.keyboard.press("Control+f");
    const query = page.getByRole("searchbox", { name: "Find in script" });
    assert.equal(await query.isVisible(), true);
    await query.fill("fÖrsta raden");
    await waitText(page, "#find-count", "1 / 1");
    const highlighted = () => page.evaluate(() => [...CSS.highlights.get("krata-find")][0]?.toString());
    assert.equal(await highlighted(), "Första raden");

    await query.fill("[mål]");
    await waitText(page, "#find-count", "1 / 2");
    await query.press("Enter");
    await waitText(page, "#find-count", "2 / 2");
    assert.equal(await highlighted(), "[MÅL]");
    assert.ok(await editor.evaluate((element) => element.scrollTop) > 200);
    await page.getByRole("button", { name: "Previous match" }).click();
    await waitText(page, "#find-count", "1 / 2");
    assert.equal(await highlighted(), "[mål]");
    await query.fill("inga träffar");
    await waitText(page, "#find-count", "No matches");
    await query.fill("[mål]");
    await waitText(page, "#find-count", "1 / 2");
    await query.press("Escape");
    assert.equal(await query.isVisible(), false);
    assert.equal(await page.evaluate(() => getSelection().toString()), "[mål]");

    const previewSize = await page.locator(".sheet").evaluate((element) => getComputedStyle(element).fontSize);
    await page.getByRole("button", { name: "Increase editor text size" }).click();
    await waitText(page, "#zoom-reset", "110%");
    assert.equal(await editor.evaluate((element) => getComputedStyle(element).fontSize), "16.5px");
    assert.equal(await page.evaluate(() => getSelection().toString()), "[mål]");
    await page.getByRole("button", { name: "Decrease editor text size" }).click();
    await waitText(page, "#zoom-reset", "100%");
    assert.equal(await editor.evaluate((element) => getComputedStyle(element).fontSize), "15px");
    assert.equal(await page.locator(".sheet").evaluate((element) => getComputedStyle(element).fontSize), previewSize);
    assert.equal(await page.locator("#file-name").textContent(), "search.md");
  } finally {
    await page.close();
  }
});
