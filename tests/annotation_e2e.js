// Drives annotation/index.html in headless Chromium:
//   node annotation_e2e.js <page> <sample> <out> <first label> <second label's key> <disallowed>
// Labels the first item by clicking, tries a label the second item's type does not allow, labels
// the second by keyboard with a quote, reloads to check the in-browser autosave, then saves and
// writes the downloaded JSONL to <out>.
const { chromium } = require("playwright");

(async () => {
  const [page_, sample, out, firstLabel, secondKey, disallowed] = process.argv.slice(2);
  const browser = await chromium.launch();
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("file://" + page_);

  await page.fill("#annotator", "ana");
  await page.setInputFiles("#sampleFile", sample);
  await page.waitForSelector("#right:not([hidden])");
  const first = await page.textContent("#itemText");

  await page.click(`#labels button[data-label="${firstLabel}"]`);
  await page.click("#next");
  const disabled = await page.isDisabled(`#labels button[data-label="${disallowed}"]`);
  await page.fill("#quote", "Disable the canary step");
  await page.click("#summary");  // leave the textarea so keys reach the page
  const keyOf = (label) => page.evaluate((l) => LABELS.findIndex(([n]) => n === l) + 1, label);
  await page.keyboard.press(String(await keyOf(disallowed)));  // refused: not for this type
  const refused = await page.textContent("#status");
  await page.keyboard.press(secondKey);
  await page.keyboard.press("ArrowLeft");
  const pressed = await page.getAttribute(`#labels button[data-label="${firstLabel}"]`, "aria-pressed");

  // Reload: labels survive in localStorage once the same sample is loaded again.
  await page.reload();
  await page.setInputFiles("#sampleFile", sample);
  await page.waitForSelector("#right:not([hidden])");
  const progress = await page.textContent("#progress");

  const [download] = await Promise.all([page.waitForEvent("download"), page.click("#save")]);
  await download.saveAs(out);
  console.log(JSON.stringify({ first, pressed, progress, errors, disabled, refused,
                               filename: download.suggestedFilename() }));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
