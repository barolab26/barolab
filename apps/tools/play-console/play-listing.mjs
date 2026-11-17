// Main store listing of one app in Play Console (Profile 3): reads the current name / short description and, when
// play-listing.json has "apply": true, replaces them and saves. Sending for review is done by play-send.mjs.
const fs = await import("node:fs/promises");
const { acquireProfileTab, closeProfileTab, withProfileLock } = await import("file:///C:/10_Project/BaroLab_rust/tools/browser-lease.mjs");
const T = "C:/10_Project/BaroLab/apps/tools/play-console/";
const cfg = JSON.parse(await fs.readFile(T + "play-listing.json", "utf8"));
await withProfileLock("Profile 3", async () => {
  const leased = await acquireProfileTab("Profile 3");
  const page = leased.page;
  const fields = () => page.evaluate(() => [...document.querySelectorAll("input[type=text], textarea")].filter(e => e.offsetWidth > 0)
    .map((e, i) => ({ i, tag: e.tagName, label: (e.getAttribute("aria-label") || "").slice(0, 40), max: e.maxLength, len: e.value.length, value: e.value.slice(0, 90) })));
  const put = async (index, value) => {
    await page.evaluate((index) => { const e = [...document.querySelectorAll("input[type=text], textarea")].filter(e => e.offsetWidth > 0)[index]; e.scrollIntoView({ block: "center" }); e.focus(); }, index);
    await page.waitForTimeout(300);
    await page.keyboard.press("Control+A"); await page.keyboard.press("Backspace");
    await page.keyboard.insertText(value);
    await page.waitForTimeout(500);
  };
  try {
    await page.goto(`https://play.google.com/console/u/0/developers/7752283694845461925/app/${cfg.appId}/store-listings/default/edit`, { waitUntil: "domcontentloaded", timeout: 40000 }).catch(() => {});
    for (let i = 0; i < 16; i++) { await page.waitForTimeout(2500); if ((await fields()).length >= 3) break; }
    const before = await fields();
    console.log(cfg.key, "BEFORE", JSON.stringify(before.slice(0, 3)));
    if (before.length < 3) console.log(await page.evaluate(() => JSON.stringify({ at: location.href.slice(-70), inputs: [...document.querySelectorAll("input, textarea, [contenteditable=true]")].filter(e => e.offsetWidth > 0).map(e => `${e.tagName}|${e.type || ""}|${(e.getAttribute("aria-label") || "").slice(0, 30)}|${String(e.value || e.innerText || "").slice(0, 40)}`).slice(0, 12), text: (document.querySelector("main") || document.body).innerText.replace(/\s+/g, " ").slice(0, 700) })));
    if (cfg.apply) {
      const name = before.find(f => f.max === 30 || /앱 이름/.test(f.label)) || before[0];
      const short = before.find(f => f.max === 80 || /간단한 설명/.test(f.label)) || before[1];
      if (cfg.title.length > 30 || cfg.short.length > 80) throw new Error("text too long");
      await put(name.i, cfg.title);
      await put(short.i, cfg.short);
      const after = await fields();
      console.log(cfg.key, "TYPED", JSON.stringify(after.slice(0, 2).map(f => ({ len: f.len, value: f.value }))));
      await page.keyboard.press("Tab"); // leave the field so the form registers the change
      await page.waitForTimeout(1200);
      console.log(cfg.key, "BUTTONS", JSON.stringify(await page.evaluate(() => [...document.querySelectorAll("button, [role=button]")].filter(e => e.offsetWidth > 0).map(e => `${(e.innerText || "").trim().replace(/\s+/g, " ").slice(0, 24)}${e.disabled || e.getAttribute("aria-disabled") === "true" ? "(off)" : ""}`).filter(t => /저장|게시|취소|다음|save/i.test(t)))));
      const press = async (re) => { const b = await page.evaluate((src) => { const re = new RegExp(src); const b = [...document.querySelectorAll("button, [role=button]")].filter(e => e.offsetWidth > 0 && !e.disabled && e.getAttribute("aria-disabled") !== "true" && re.test((e.innerText || "").trim().replace(/\s+/g, " "))).pop(); if (!b) return null; b.scrollIntoView({ block: "center" }); const r = b.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, t: (b.innerText || "").trim() }; }, re.source); if (b) { await page.waitForTimeout(400); await page.mouse.click(b.x, b.y); } return b; };
      // The edit page is a two-step form: "다음" shows the summary, "저장" there puts the change into the publishing overview.
      const next = await press(/^다음$/);
      await page.waitForTimeout(7000);
      console.log(cfg.key, "STEP2 BUTTONS", JSON.stringify(await page.evaluate(() => [...document.querySelectorAll("button, [role=button]")].filter(e => e.offsetWidth > 0).map(e => (e.innerText || "").trim().replace(/\s+/g, " ").slice(0, 24)).filter(t => /저장|게시|뒤로|다음|전송|제출/.test(t)))));
      const box = next ? await press(/^(저장|변경사항 저장)$/) : null;
      await page.waitForTimeout(7000);
      const note = await page.evaluate(() => (document.body.innerText.match(/[^\n]*(저장되었|저장됨|오류|변경사항이)[^\n]*/g) || []).slice(-3).join(" | "));
      console.log(cfg.key, "SAVE clicked:", Boolean(box), "|", note.slice(0, 200));
    }
  } catch (e) { console.log(cfg.key, "ERROR", String(e?.message || e).slice(0, 200)); }
  finally { await page.goto("about:blank").catch(() => {}); await closeProfileTab(leased.task, leased.pageLabel); }
});
