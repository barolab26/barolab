// Sends the saved changes of one app for review from Play Console's publishing overview (Profile 3).
// usage: PLAY_APP=<app id> ... ; prints what the page says before and after.
const { acquireProfileTab, closeProfileTab, withProfileLock } = await import("file:///C:/10_Project/BaroLab_rust/tools/browser-lease.mjs");
const fs = await import("node:fs/promises");
const APP = (await fs.readFile("C:/10_Project/BaroLab/apps/tools/play-console/play-send.txt", "utf8")).trim();
await withProfileLock("Profile 3", async () => {
  const leased = await acquireProfileTab("Profile 3");
  const page = leased.page;
  const click = async (re, scope = "button, a, [role=button]") => {
    const box = await page.evaluate(({ src, scope }) => {
      const re = new RegExp(src);
      const dlg = [...document.querySelectorAll("[role=dialog], material-dialog")].filter(e => e.offsetWidth > 0).pop();
      const pool = [...(dlg || document).querySelectorAll(scope)].filter(e => e.offsetWidth > 0 && !e.disabled && re.test((e.innerText || "").trim().replace(/\s+/g, " ")));
      const el = pool.pop(); if (!el) return null;
      el.scrollIntoView({ block: "center" }); const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, text: (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 40), inDialog: Boolean(dlg) };
    }, { src: re.source, scope });
    if (!box) return null;
    await page.waitForTimeout(400); await page.mouse.click(box.x, box.y); return box;
  };
  const text = async (n = 900) => page.evaluate((n) => { const t = (document.body.innerText || "").replace(/[ \t]+/g, " ").replace(/\n{2,}/g, "\n"); const i = t.indexOf("게시 개요"); return t.slice(Math.max(0, i), i + n); }, n);
  try {
    await page.goto(`https://play.google.com/console/u/0/developers/7752283694845461925/app/${APP}/publishing`, { waitUntil: "domcontentloaded", timeout: 40000 }).catch(() => {});
    await page.waitForTimeout(10000);
    console.log("BEFORE:", (await text(600)).replace(/\n/g, " | "));
    const first = await click(/^검토를 위해 변경사항 \d+개 (제출|전송)$/);
    console.log("clicked", JSON.stringify(first));
    await page.waitForTimeout(4000);
    const dialog = await page.evaluate(() => { const d = [...document.querySelectorAll("[role=dialog], material-dialog")].filter(e => e.offsetWidth > 0).pop(); return d ? { text: (d.innerText || "").replace(/\s+/g, " ").slice(0, 500), buttons: [...d.querySelectorAll("button")].map(b => (b.innerText || "").trim()).filter(Boolean) } : null; });
    console.log("dialog", JSON.stringify(dialog));
    // "검토 다시 시작": an earlier submission of the same day is still in review and is resent together with the new change.
    if (dialog) { const second = await click(/(제출|전송|검토 다시 시작)/, "button"); console.log("confirmed", JSON.stringify(second)); }
    await page.waitForTimeout(10000);
    console.log("AFTER:", (await text(900)).replace(/\n/g, " | "));
  } finally { await page.goto("about:blank").catch(() => {}); await closeProfileTab(leased.task, leased.pageLabel); }
});
