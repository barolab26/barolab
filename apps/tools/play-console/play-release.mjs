// Uploads a signed bundle to the app's closed-testing (Alpha) track in Play Console (Profile 3) and, in "publish"
// mode, sends the release for review. In "probe" mode it stops on the review page and only reports what it sees.
// Config: play-release.json { key, appId, aab, notes, mode }.
const fs = await import("node:fs/promises");
const { acquireProfileTab, closeProfileTab, withProfileLock } = await import("file:///C:/10_Project/BaroLab_rust/tools/browser-lease.mjs");
const T = "C:/10_Project/BaroLab/apps/tools/play-console/";
const cfg = JSON.parse(await fs.readFile(T + "play-release.json", "utf8"));
const BASE = `https://play.google.com/console/u/0/developers/7752283694845461925/app/${cfg.appId}`;
const log = [];
await withProfileLock("Profile 3", async () => {
  const leased = await acquireProfileTab("Profile 3");
  const page = leased.page;
  const state = async (n = 1600) => page.evaluate((n) => {
    const main = document.querySelector("main") || document.body;
    return { at: location.href.replace(/.*\/app\/\d+/, "").slice(0, 110),
      buttons: [...document.querySelectorAll("button, a[role=button]")].filter(e => e.offsetWidth > 0 && !e.disabled).map(e => (e.innerText || "").trim().replace(/\s+/g, " ").slice(0, 36)).filter(t => t && t.length > 1 && !/^(home|badge|dashboard|bar_chart|overview|shield|rocket_launch|vital_signs|finance_mode|sell|more_vert|close|help)$/.test(t)).filter((v, i, a) => a.indexOf(v) === i).slice(0, 30),
      text: (main.innerText || "").replace(/[ \t]+/g, " ").replace(/\n{2,}/g, "\n").slice(0, n) };
  }, n);
  const clickText = async (text, exact = true) => {
    const box = await page.evaluate(({ text, exact }) => {
      const el = [...document.querySelectorAll("button, a, [role=button]")].filter(e => e.offsetWidth > 0 && !e.disabled).filter(e => { const t = (e.innerText || "").trim().replace(/\s+/g, " "); return exact ? t === text : t.includes(text); }).pop();
      if (!el) return null;
      el.scrollIntoView({ block: "center" });
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }, { text, exact });
    if (!box) return false;
    await page.waitForTimeout(400);
    await page.mouse.click(box.x, box.y);
    return true;
  };
  try {
    await page.goto(`${BASE}/closed-testing`, { waitUntil: "domcontentloaded", timeout: 40000 }).catch(() => {});
    await page.waitForTimeout(9000);
    const track = await page.evaluate(() => [...document.querySelectorAll("a[href*='/tracks/']")].map(a => a.getAttribute("href")).find(h => /\/tracks\/\d+/.test(h)));
    if (!track) throw new Error("closed-testing track link not found");
    await page.goto("https://play.google.com" + track, { waitUntil: "domcontentloaded", timeout: 40000 }).catch(() => {});
    await page.waitForTimeout(9000);
    log.push({ step: "track", ...(await state(700)) });
    const opened = (await clickText("새 버전 만들기")) || (await clickText("버전 수정")) || (await clickText("새 버전 만들기", false));
    for (let i = 0; i < 20; i++) { await page.waitForTimeout(2500); if (await page.evaluate(() => [...document.querySelectorAll("button, a, [role=button]")].some(e => e.offsetWidth > 0 && /업로드/.test(e.innerText || "")))) break; }
    log.push({ step: "new release", opened, ...(await state(900)) });
    // upload the bundle
    // A draft from an earlier run already holds the bundle: do not upload the same version code twice.
    let uploaded = await page.evaluate((version) => { const t = document.body.innerText; const i = t.indexOf(version), j = t.indexOf("이전 버전의 앱 버전 포함"); return i >= 0 && (j < 0 || i < j); }, cfg.version);
    if (!uploaded) {
      const chooser = page.waitForFileChooser({ timeout: 20000 });
      chooser.catch(() => null);
      const up = (await clickText("업로드")) || (await clickText("업로드", false));
      try { await (await chooser).setFiles([cfg.aab]); uploaded = true; } catch (e) { log.push({ step: "chooser", error: String(e.message).slice(0, 120), up }); }
    } else log.push({ step: "bundle already in the draft" });
    if (uploaded) {
      for (let i = 0; i < 40; i++) { await page.waitForTimeout(3000); const t = await page.evaluate(() => document.body.innerText); if (/\b4 \(0\.4\.0\)|\b6 \(0\.6\.0\)|버전 코드\s*\n?\s*[46]\b/.test(t) && !/업로드 중|처리 중/.test(t)) break; }
      log.push({ step: "uploaded", ...(await state(1400)) });
      const notesOk = await page.evaluate((notes) => {
        const ta = [...document.querySelectorAll("textarea")].filter(e => e.offsetWidth > 0).pop();
        if (!ta) return false;
        ta.scrollIntoView({ block: "center" }); ta.focus(); return true;
      }, cfg.notes);
      if (notesOk) { await page.keyboard.press("Control+A"); await page.keyboard.press("Backspace"); await page.keyboard.insertText(cfg.notes); await page.waitForTimeout(600); }
      log.push({ step: "notes", notesOk });
      log.push({ step: "next", ok: (await clickText("다음")) });
      await page.waitForTimeout(9000);
      await clickText("더보기", false);
      await page.waitForTimeout(1500);
      const rv = await state(2600);
      const w = rv.text.indexOf("오류, 경고 및 메시지");
      log.push({ step: "review", at: rv.at, buttons: rv.buttons, warnings: rv.text.slice(w, w + 700) });
      if (cfg.mode === "publish") {
        const saved = await clickText("저장");
        await page.waitForTimeout(8000);
        log.push({ step: "save", saved, ...(await state(500)) });
        await page.goto(`${BASE}/publishing`, { waitUntil: "domcontentloaded", timeout: 40000 }).catch(() => {});
        await page.waitForTimeout(10000);
        const ov = await state(1800);
        log.push({ step: "overview", ...ov });
        if (cfg.send) {
          const sent = await clickText("검토를 위해 변경사항", false);
          await page.waitForTimeout(4000);
          const confirm = (await clickText("검토를 위해 변경사항 전송")) || (await clickText("변경사항 전송", false)) || (await clickText("전송", false));
          await page.waitForTimeout(9000);
          log.push({ step: "sent", sent, confirm, ...(await state(1500)) });
        }
      }
    }
    await page.screenshot({ path: `${T}play-release-${cfg.key}.png` }).catch(() => {});
  } catch (e) { log.push({ error: String(e?.message || e).slice(0, 300) }); }
  finally { await page.goto("about:blank").catch(() => {}); await closeProfileTab(leased.task, leased.pageLabel); }
});
await fs.writeFile(`${T}play-release-${cfg.key}.json`, JSON.stringify(log, null, 1), "utf8");
for (const l of log) console.log(JSON.stringify(l).slice(0, 2300));
console.log("ownership", (await listTaskSpaces()).find(s => /soultin/.test(s.name))?.ownership);
