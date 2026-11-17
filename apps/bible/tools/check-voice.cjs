// Checks the recorded verse audio by having a Google AI Studio model write down what it hears and comparing that
// with the text the file should contain. A file that does not match (cut at the wrong place, or the 1910 spelling
// read as something else) is listed and, with --delete, removed so make-voice.cjs renders it again.
// usage: node check-voice.cjs <female|male> [--delete] [--only id1,id2]      (key: VOICE_KEY_FILE or the company .env)
const fs = require("fs");
const path = require("path");
const ROOT = path.resolve(__dirname, "..");
// Full-size models only. On 2026-11-17 the check fell through to the lite models when these ran out of quota; the lite
// models often wrote down just the first sentence, and 20 good files were deleted on that false result.
const MODELS = ["gemini-3.8-flash", "gemini-flash-latest", "gemini-3-flash-preview", "gemini-3.7-flash", "gemini-3.6-flash"];
const VERIFIED = path.join(__dirname, "voice-verified.json");
const verified = fs.existsSync(VERIFIED) ? JSON.parse(fs.readFileSync(VERIFIED, "utf8")) : {};
const env = Object.fromEntries(fs.readFileSync("C:/10_Project/BaroLab/.env", "utf8").replace(/^\uFEFF/, "").split(/\r?\n/)
  .map((l) => l.match(/^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.*)$/)).filter(Boolean).map((m) => [m[1], m[2].trim().replace(/^["']|["']$/g, "")]));
const key = process.env.VOICE_KEY_FILE ? fs.readFileSync(process.env.VOICE_KEY_FILE, "utf8").trim() : (env.GEMINI_API_KEY_BARO || env.GEMINI_API_KEY);
const args = process.argv.slice(2), who = args[0];
const only = (args.find((a, i) => args[i - 1] === "--only") || "").split(",").filter(Boolean);
const dir = path.join(ROOT, "app/src/main/assets/voice", who);
const all = JSON.parse(fs.readFileSync(path.join(ROOT, "content/verses.json"), "utf8")).verses;
const spoken = (v) => `${v.reference.replace(/(\d+):(\d+)/, "$1장 $2절")}. ${v.text.replace(/^\([^)]*\)\s*/, "")}`;
const norm = (s) => s.replace(/[^\uAC00-\uD7A30-9]/g, "");
// Share of the expected characters that appear in order in what was heard (longest common subsequence).
function overlap(a, b) {
  const row = new Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) { let prev = 0; for (let j = 1; j <= b.length; j++) { const keep = row[j]; row[j] = a[i - 1] === b[j - 1] ? prev + 1 : Math.max(row[j], row[j - 1]); prev = keep; } }
  return row[b.length] / Math.max(a.length, 1);
}
async function hear(files) {
  const parts = [{ text: `다음 ${files.length}개의 한국어 음성을 순서대로 들리는 그대로 받아 적으세요. 고치거나 요약하지 말고, 숫자는 한글 소리대로 적지 말고 아라비아 숫자로 적으세요. JSON 배열(문자열 ${files.length}개)만 답하세요.` }];
  for (const f of files) parts.push({ inlineData: { mimeType: "audio/ogg", data: fs.readFileSync(f).toString("base64") } });
  for (const model of MODELS) {
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, { method: "POST", headers: { "x-goog-api-key": key, "Content-Type": "application/json" }, signal: AbortSignal.timeout(90000),
      body: JSON.stringify({ contents: [{ parts }], generationConfig: { responseMimeType: "application/json", temperature: 0 } }) }).catch((e) => ({ ok: false, status: `no answer (${e.name})` }));
    if (!res.ok) { console.log(`  ${model}: HTTP ${res.status}`); continue; }
    try { const out = JSON.parse((await res.json()).candidates[0].content.parts[0].text); if (Array.isArray(out) && out.length === files.length) return out.map(String); } catch { }
    console.log(`  ${model}: unusable answer`);
  }
  return null;
}
(async () => {
  verified[who] = (verified[who] || []).filter((id) => fs.existsSync(path.join(dir, `${id}.ogg`)));
  // Files that already passed are not sent again (--all re-checks everything).
  const have = all.filter((v) => fs.existsSync(path.join(dir, `${v.id}.ogg`)) && (!only.length || only.includes(v.id)) && (args.includes("--all") || !verified[who].includes(v.id)));
  const bad = [];
  for (let i = 0; i < have.length; i += 3) {
    const batch = have.slice(i, i + 3);
    if (i > 0) await new Promise((r) => setTimeout(r, 7000));
    const heard = await hear(batch.map((v) => path.join(dir, `${v.id}.ogg`)));
    if (!heard) { console.log(`could not check ${batch.map((v) => v.id).join(",")}`); bad.push(...batch.map((v) => ({ id: v.id, why: "unchecked" }))); continue; }
    batch.forEach((v, k) => {
      const want = norm(spoken(v)), got = norm(heard[k]);
      const score = overlap(want, got), extra = got.length / Math.max(want.length, 1);
      const ok = score >= 0.9 && extra > 0.9 && extra < 1.12; // tight: a piece that gained or lost a few words at a cut must not pass
      console.log(`${ok ? "ok " : "BAD"} ${v.id} match ${(score * 100).toFixed(0)}% length ${(extra * 100).toFixed(0)}%${ok ? "" : ` | heard: ${heard[k].slice(0, 90)}`}`);
      if (!ok) bad.push({ id: v.id, why: `match ${(score * 100).toFixed(0)}%` });
      else if (!verified[who].includes(v.id)) { verified[who].push(v.id); fs.writeFileSync(VERIFIED, JSON.stringify(verified, null, 1) + "\n"); }
    });
  }
  console.log(`checked ${have.length}, bad ${bad.filter((b) => b.why !== "unchecked").length}, unchecked ${bad.filter((b) => b.why === "unchecked").length}`);
  if (args.includes("--delete")) for (const b of bad.filter((b) => b.why !== "unchecked")) { fs.unlinkSync(path.join(dir, `${b.id}.ogg`)); console.log(`deleted ${b.id}`); }
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });
