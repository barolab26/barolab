// Monthly Naver search volume for candidate store-search words (a proxy for what Korean seniors type; Google Play
// does not publish its own volumes). usage: node search-demand.cjs word1,word2,...   (five hint words per request)
// Credentials are read from the company .env and never printed.
const fs = require("fs");
const crypto = require("crypto");
const env = Object.fromEntries(fs.readFileSync("C:/10_Project/BaroLab/.env", "utf8").replace(/^\uFEFF/, "").split(/\r?\n/)
  .map((l) => l.match(/^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.*)$/)).filter(Boolean).map((m) => [m[1], m[2].trim().replace(/\s+#.*$/, "").replace(/^["']|["']$/g, "")]));
const words = (process.argv[2] || "").split(",").map((w) => w.trim().replace(/\s+/g, "")).filter(Boolean);
(async () => {
  const seen = new Map();
  for (let i = 0; i < words.length; i += 5) {
    const hints = words.slice(i, i + 5);
    const stamp = String(Date.now());
    const sig = crypto.createHmac("sha256", env.NAVER_SEARCHAD_SECRET_KEY).update(`${stamp}.GET./keywordstool`).digest("base64");
    const res = await fetch(`https://api.searchad.naver.com/keywordstool?hintKeywords=${encodeURIComponent(hints.join(","))}&showDetail=1`,
      { headers: { "X-Timestamp": stamp, "X-API-KEY": env.NAVER_SEARCHAD_ACCESS_LICENSE, "X-Customer": env.NAVER_SEARCHAD_CUSTOMER_ID, "X-Signature": sig } });
    if (!res.ok) { console.log(`HTTP ${res.status} for ${hints.join(",")}`); continue; }
    for (const r of (await res.json()).keywordList || []) {
      const n = (v) => (typeof v === "number" ? v : 0); // "< 10" is treated as unknown-small
      if (!seen.has(r.relKeyword)) seen.set(r.relKeyword, { pc: n(r.monthlyPcQcCnt), mobile: n(r.monthlyMobileQcCnt), hint: hints.includes(r.relKeyword) });
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  const rows = [...seen.entries()].map(([k, v]) => ({ k, total: v.pc + v.mobile, mobile: v.mobile, hint: v.hint }));
  console.log("== 물어본 낱말 ==");
  for (const r of rows.filter((r) => r.hint).sort((a, b) => b.total - a.total)) console.log(`${r.k}\t월 ${r.total}\t(모바일 ${r.mobile})`);
  const topic = /(인사말|안부|좋은글|좋은아침|성경|말씀|큐티|돋보기|확대경|큰글씨|글자확대|장보기|쇼핑리스트|메모장|음성메모)/;
  console.log("== 연관 낱말 상위 ==");
  for (const r of rows.filter((r) => !r.hint && topic.test(r.k)).sort((a, b) => b.total - a.total).slice(0, 45)) console.log(`${r.k}\t월 ${r.total}`);
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });
