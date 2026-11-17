// Checks recorded verse audio through the Gemini web chat (uploads, no API quota): the chat writes down what it
// hears and this script compares it with the verse text.
//   node check-voice-web.cjs prep <female|male> [count=8]   -> converts the next unverified files to mp3, writes the
//        question and attachment list for ~/.claude/gemini-collab/ask.mjs (run that next, in a new chat)
//   node check-voice-web.cjs grade                           -> reads the chat's answer, records the files that pass in
//        voice-verified.json and lists the ones that do not (nothing is deleted)
const fs = require("fs");
const path = require("path");
const os = require("os");
const { execFileSync } = require("child_process");
const ROOT = path.resolve(__dirname, "..");
const COLLAB = path.join(os.homedir(), ".claude", "gemini-collab");
const WORK = path.join(os.tmpdir(), "voice-web-check");
const VERIFIED = path.join(__dirname, "voice-verified.json");
const all = JSON.parse(fs.readFileSync(path.join(ROOT, "content/verses.json"), "utf8")).verses;
const spoken = (v) => `${v.reference.replace(/(\d+):(\d+)/, "$1장 $2절")}. ${v.text.replace(/^\([^)]*\)\s*/, "")}`;
const norm = (s) => s.replace(/[^가-힣0-9]/g, "");
function overlap(a, b) {
  const row = new Array(b.length + 1).fill(0);
  for (let i = 1; i <= a.length; i++) { let prev = 0; for (let j = 1; j <= b.length; j++) { const keep = row[j]; row[j] = a[i - 1] === b[j - 1] ? prev + 1 : Math.max(row[j], row[j - 1]); prev = keep; } }
  return row[b.length] / Math.max(a.length, 1);
}
const verified = fs.existsSync(VERIFIED) ? JSON.parse(fs.readFileSync(VERIFIED, "utf8")) : {};
const [mode, who, countArg] = process.argv.slice(2);
if (mode === "prep") {
  const dir = path.join(ROOT, "app/src/main/assets/voice", who);
  const todo = all.filter((v) => fs.existsSync(path.join(dir, `${v.id}.ogg`)) && !(verified[who] || []).includes(v.id)).slice(0, Number(countArg || 8));
  if (!todo.length) { console.log(`nothing left to check for ${who}`); process.exit(0); }
  fs.rmSync(WORK, { recursive: true, force: true }); fs.mkdirSync(WORK, { recursive: true });
  const files = todo.map((v, i) => { const f = path.join(WORK, `${String(i + 1).padStart(2, "0")}-${v.id}.mp3`); execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", path.join(dir, `${v.id}.ogg`), "-c:a", "libmp3lame", "-b:a", "64k", f]); return f; });
  fs.writeFileSync(path.join(WORK, "batch.json"), JSON.stringify({ who, ids: todo.map((v) => v.id) }));
  fs.writeFileSync(path.join(COLLAB, "attach.txt"), files.join("\n") + "\n", "utf8");
  fs.writeFileSync(path.join(COLLAB, "question.txt"), `/new\n첨부한 한국어 음성 파일 ${files.length}개를 파일 이름의 번호 순서(${files.map((f) => path.basename(f, ".mp3")).join(", ")})대로, 들리는 그대로 받아 적어 주세요. 고치거나 요약하지 말고 빠진 부분 없이 처음부터 끝까지 적고, 장·절 숫자는 아라비아 숫자로 적어 주세요. 답은 JSON 배열(문자열 ${files.length}개)만 주세요.`, "utf8");
  console.log(`${who}: ${todo.length} files ready (${todo.map((v) => v.id).join(" ")})`);
} else if (mode === "grade") {
  const { who: w, ids } = JSON.parse(fs.readFileSync(path.join(WORK, "batch.json"), "utf8"));
  const answer = fs.readFileSync(path.join(COLLAB, "answer.txt"), "utf8");
  // The chat may add a citation marker such as "[cite: 1, 2]" after the array: take the first bracket span that parses.
  let heard = null;
  for (let end = answer.indexOf("]"), start = answer.indexOf("["); end > start && start >= 0 && !heard; end = answer.indexOf("]", end + 1)) {
    try { const j = JSON.parse(answer.slice(start, end + 1)); if (Array.isArray(j)) heard = j; } catch { }
    if (end < 0) break;
  }
  if (!Array.isArray(heard) || heard.length !== ids.length) { console.log(`answer unusable (${heard ? heard.length : "no"} items for ${ids.length} files); nothing recorded`); process.exit(1); }
  verified[w] = verified[w] || [];
  const bad = [];
  ids.forEach((id, k) => {
    const want = norm(spoken(all.find((v) => v.id === id))), got = norm(String(heard[k]));
    const score = overlap(want, got), len = got.length / Math.max(want.length, 1);
    const ok = score >= 0.9 && len > 0.9 && len < 1.12;
    console.log(`${ok ? "ok " : "BAD"} ${w} ${id} match ${(score * 100).toFixed(0)}% length ${(len * 100).toFixed(0)}%${ok ? "" : ` | heard: ${String(heard[k]).slice(0, 110)}`}`);
    if (ok) { if (!verified[w].includes(id)) verified[w].push(id); } else bad.push(id);
  });
  fs.writeFileSync(VERIFIED, JSON.stringify(verified, null, 1) + "\n");
  console.log(`graded ${ids.length}, bad ${bad.length}${bad.length ? ": " + bad.join(",") : ""}; verified so far female ${(verified.female || []).length} male ${(verified.male || []).length}`);
} else { console.log("usage: prep <female|male> [count] | grade"); process.exit(1); }
