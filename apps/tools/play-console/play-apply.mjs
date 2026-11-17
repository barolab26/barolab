// Production-access application in Play Console (Profile 3). CEO instruction 2026-11-17: apply today.
// Every answer comes from answers.json and is what was actually recorded or what the CEO relayed; nothing is invented.
// MODE "probe": fill the pages given in answers and stop BEFORE the final submit, dumping the page that follows.
// MODE "submit": the same, then press the final submit button.
const fs = await import("node:fs/promises");
const { acquireProfileTab, closeProfileTab, withProfileLock } = await import("file:///C:/10_Project/BaroLab_rust/tools/browser-lease.mjs");
const cfg = JSON.parse(await fs.readFile("C:/10_Project/BaroLab/apps/tools/play-console/play-answers.json", "utf8"));
const DEV = "7752283694845461925";
const log = [];
await withProfileLock("Profile 3", async () => {
  const leased = await acquireProfileTab("Profile 3");
  const page = leased.page;
  const dump = () => page.evaluate(() => {
    const dlg = [...document.querySelectorAll("[role=dialog], material-dialog, .mdc-dialog, console-dialog")].filter(e => e.offsetWidth > 0).pop() || document.body;
    return {
      text: (dlg.innerText || "").replace(/[ \t]+/g, " ").replace(/\n{2,}/g, "\n").slice(0, 3500),
      fields: [...dlg.querySelectorAll("textarea, input[type=text], input[type=number], [role=radio], input[type=radio], [role=checkbox], input[type=checkbox], [role=combobox], [role=listbox], material-dropdown-select")].filter(e => e.offsetWidth > 0)
        .map(e => `${e.tagName}|${e.getAttribute("role") || e.type || ""}|${(e.getAttribute("aria-label") || "").slice(0, 60)}|val=${String(e.value || e.getAttribute("aria-checked") || "").slice(0, 40)}`),
      buttons: [...dlg.querySelectorAll("button")].filter(e => e.offsetWidth > 0).map(e => (e.innerText || "").trim().replace(/\s+/g, " ")).filter(Boolean),
    };
  });
  const clickText = async (text, tags = "button, a, label, [role=radio], [role=option], material-radio, mat-radio-button") => {
    const box = await page.evaluate(({ text, tags }) => {
      const el = [...document.querySelectorAll(tags)].filter(e => e.offsetWidth > 0 && (e.innerText || "").trim().replace(/\s+/g, " ") === text).pop();
      if (!el) return null;
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      return { x: r.left + Math.min(r.width / 2, 24), y: r.top + r.height / 2 };
    }, { text, tags });
    if (!box) return false;
    await page.waitForTimeout(300);
    await page.mouse.click(box.x, box.y);
    await page.waitForTimeout(500);
    return true;
  };
  const fill = async (labelStart, value) => {
    const ok = await page.evaluate((labelStart) => {
      const el = [...document.querySelectorAll("textarea, input[type=text]")].find(e => e.offsetWidth > 0 && (e.getAttribute("aria-label") || "").startsWith(labelStart));
      if (!el) return false;
      el.scrollIntoView({ block: "center" }); el.focus(); el.select?.();
      return true;
    }, labelStart);
    if (!ok) return false;
    await page.waitForTimeout(250);
    await page.keyboard.press("Control+A");
    await page.keyboard.press("Backspace");
    await page.keyboard.insertText(value);
    await page.waitForTimeout(400);
    return page.evaluate((labelStart) => [...document.querySelectorAll("textarea, input[type=text]")].find(e => (e.getAttribute("aria-label") || "").startsWith(labelStart))?.value.length, labelStart);
  };
  try {
    await page.goto(`https://play.google.com/console/u/0/developers/${DEV}/app/${cfg.appId}/app-dashboard`, { waitUntil: "domcontentloaded", timeout: 40000 }).catch(() => {});
    await page.waitForTimeout(9000);
    log.push({ open: await clickText("프로덕션 신청") });
    await page.waitForTimeout(6000);
    for (const [i, pg] of cfg.pages.entries()) {
      const before = await dump();
      log.push({ page: i + 1, heading: before.text.slice(0, 80), fieldsBefore: before.fields });
      for (const [label, value] of Object.entries(pg.text || {})) log.push({ fill: label.slice(0, 30), chars: await fill(label, value) });
      for (const choice of pg.choose || []) log.push({ choose: choice, ok: await clickText(choice) });
      const after = await dump();
      log.push({ counters: (after.text.match(/\d+\/\d+/g) || []).join(" "), errors: (after.text.match(/[^\n]*(필수|오류|초과|입력하세요)[^\n]*/g) || []).slice(0, 5) });
      if (i < cfg.pages.length - 1 || cfg.next) { log.push({ next: await clickText("다음") }); await page.waitForTimeout(3500); }
    }
    const last = await dump();
    log.push({ nowShowing: last });
    if (cfg.mode === "submit") {
      const done = await clickText(cfg.submitLabel || "신청");
      await page.waitForTimeout(8000);
      log.push({ submitted: done, after: (await page.evaluate(() => (document.body?.innerText || "").replace(/[ \t]+/g, " ").replace(/\n{2,}/g, "\n"))).slice(0, 3000) });
    }
    await page.screenshot({ path: `C:/10_Project/BaroLab/apps/tools/play-console/play-${cfg.key}-${cfg.mode}.png` }).catch(() => {});
  } catch (e) { log.push({ error: String(e?.message || e).slice(0, 300) }); }
  finally { await page.goto("about:blank").catch(() => {}); await closeProfileTab(leased.task, leased.pageLabel); }
});
await fs.writeFile(`C:/10_Project/BaroLab/apps/tools/play-console/play-${cfg.key}-${cfg.mode}.json`, JSON.stringify(log, null, 1), "utf8");
console.log(JSON.stringify(log, null, 1).slice(0, 7000));
console.log("ownership", (await listTaskSpaces()).find(s => s.id === 2219)?.ownership);
