// Pre-renders the read-aloud audio of the bundled verses with Google AI Studio voices.
// usage: node make-voice.cjs <female|male> <max requests> [verses per request = 5]
// Output: app/src/main/assets/voice/<female|male>/<verse id>.ogg  (mono Opus, 32 kbps). Existing files are skipped.
// The free tier allows 10 requests a day per model (30 with the three models) and the company's Shorts need about 10
// of them each morning, so the caller passes a request budget. Several verses go into one request, each as its own
// paragraph, and the answer is cut at the longest pauses; a cut is kept only if every piece is about as long as its
// text predicts. Only the words to be read are sent, because an instruction line can be read aloud.
// The API key is read from the company .env and never printed.
const fs = require("fs");
const path = require("path");
const { execFileSync, spawnSync } = require("child_process");
const ROOT = path.resolve(__dirname, "..");
const VOICES = { female: "Sulafat", male: "Algieba" }; // warm low female / smooth low male; change here to re-cast
const MODELS = ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts"];
const TEMPO = 0.92; // a little slower than conversation for older listeners
const env = Object.fromEntries(fs.readFileSync("C:/10_Project/BaroLab/.env", "utf8").replace(/^\uFEFF/, "").split(/\r?\n/)
  .map((l) => l.match(/^\s*(?:export\s+)?([A-Za-z0-9_]+)\s*=\s*(.*)$/)).filter(Boolean).map((m) => [m[1], m[2].trim().replace(/^["']|["']$/g, "")]));
// VOICE_KEY_FILE points at another AI Studio key file (the CEO offered the yoon_master account's project on
// 2026-11-17; it has its own daily quota, so the Shorts' quota is left alone).
const key = process.env.VOICE_KEY_FILE ? fs.readFileSync(process.env.VOICE_KEY_FILE, "utf8").trim() : (env.GEMINI_API_KEY_BARO || env.GEMINI_API_KEY);
if (!key) throw new Error("no API key configured");
const [who, budgetArg, sizeArg] = process.argv.slice(2);
const budget = Number(budgetArg), size = Number(sizeArg || 5);
if (!VOICES[who] || !(budget > 0) || !(size > 0)) throw new Error("usage: node make-voice.cjs <female|male> <max requests> [verses per request]");
const all = JSON.parse(fs.readFileSync(path.join(ROOT, "content/verses.json"), "utf8")).verses;
const outDir = path.join(ROOT, "app/src/main/assets/voice", who);
fs.mkdirSync(outDir, { recursive: true });
// "(다윗의 시)" style headings are shown on screen but are not read.
const spoken = (v) => `${v.reference.replace(/(\d+):(\d+)/, "$1장 $2절")}. ${v.text.replace(/^\([^)]*\)\s*/, "")}`;
const weight = (v) => spoken(v).replace(/[\s.,!?]/g, "").length;

let exhausted = new Set();
async function tts(text) {
  for (const model of MODELS.filter((m) => !exhausted.has(m))) {
    const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
      method: "POST", headers: { "x-goog-api-key": key, "Content-Type": "application/json" },
      body: JSON.stringify({ contents: [{ parts: [{ text }] }], generationConfig: { responseModalities: ["AUDIO"], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: VOICES[who] } } } } }),
    });
    if (res.status === 429) { if (/PerDay/.test(await res.text())) exhausted.add(model); console.log(`  ${model}: 429`); continue; }
    if (!res.ok) { console.log(`  ${model}: HTTP ${res.status}`); continue; }
    const part = (await res.json()).candidates?.[0]?.content?.parts?.[0]?.inlineData;
    if (!part?.data) { console.log(`  ${model}: no audio`); continue; }
    return { model, rate: Number((part.mimeType.match(/rate=(\d+)/) || [])[1] || 24000), pcm: Buffer.from(part.data, "base64") };
  }
  return null;
}

// Pauses inside the recording, as [start, end] seconds.
function pauses(raw, rate) {
  const err = spawnSync("ffmpeg", ["-hide_banner", "-f", "s16le", "-ar", String(rate), "-ac", "1", "-i", raw, "-af", "silencedetect=noise=-38dB:d=0.25", "-f", "null", "-"], { encoding: "utf8" }).stderr || "";
  const starts = [...err.matchAll(/silence_start: ([\d.]+)/g)].map((m) => Number(m[1]));
  const ends = [...err.matchAll(/silence_end: ([\d.]+)/g)].map((m) => Number(m[1]));
  return starts.map((s, i) => [s, ends[i]]).filter(([s, e]) => e !== undefined && e > s);
}

function encode(raw, rate, from, to, out) {
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "s16le", "-ar", String(rate), "-ac", "1", "-ss", from.toFixed(3), "-to", to.toFixed(3), "-i", raw,
    "-af", `atempo=${TEMPO},loudnorm=I=-18:TP=-2`, "-c:a", "libopus", "-b:a", "32k", "-ac", "1", out]);
}

(async () => {
  const todo = all.filter((v) => !fs.existsSync(path.join(outDir, `${v.id}.ogg`)));
  let requests = 0, made = 0;
  for (let i = 0; i < todo.length && requests < budget; i += size) {
    const batch = todo.slice(i, i + size);
    if (requests > 0) await new Promise((r) => setTimeout(r, 21000)); // about three requests a minute
    // VOICE_REUSE_PCM replays a saved recording (24 kHz) for the first batch, to tune the cutting without a request.
    const audio = process.env.VOICE_REUSE_PCM && i === 0 ? { model: "saved", rate: 24000, pcm: fs.readFileSync(process.env.VOICE_REUSE_PCM) } : await tts(batch.map(spoken).join("\n\n\n"));
    requests++;
    if (!audio) { console.log(`stopped at ${batch[0].id}: no model answered (quota or error)`); break; }
    const total = audio.pcm.length / 2 / audio.rate;
    const raw = path.join(outDir, `_batch.pcm`);
    fs.writeFileSync(raw, audio.pcm);
    // The voice pauses about as long inside a verse as between verses, so the longest pauses are not the borders.
    // Among all ways to choose the borders, take the one whose pieces best match the lengths the texts predict.
    const inner = pauses(raw, audio.rate).filter(([s, e]) => s > 0.4 && e < total - 0.2);
    const weights = batch.map(weight), sum = weights.reduce((a, b) => a + b, 0);
    let best = null;
    const choose = (from, chosen) => {
      if (chosen.length === batch.length - 1) {
        const e = [0, ...chosen.flatMap(([s, t]) => [s, t]), total], lens = batch.map((_, k) => e[2 * k + 1] - e[2 * k]), speech = lens.reduce((a, b) => a + b, 0);
        const ratios = lens.map((len, k) => len / (speech * weights[k] / sum)), cost = ratios.reduce((a, r) => a + Math.log(r) ** 2, 0);
        if (!best || cost < best.cost) best = { cost, edges: e, lens, ratios };
        return;
      }
      for (let j = from; j < inner.length; j++) choose(j + 1, [...chosen, inner[j]]);
    };
    choose(0, []);
    const edges = best ? best.edges : [0, total], lengths = best ? best.lens : [total]; // piece k runs edges[2k] .. edges[2k+1]
    const fits = Boolean(best) && best.ratios.every((r) => r > 0.72 && r < 1.4);
    if (best) console.log(`  cut ratios ${best.ratios.map((r) => r.toFixed(2)).join(" ")}`);
    if (!fits) {
      console.log(`batch ${batch.map((v) => v.id).join(",")} (${audio.model}): pauses did not match the text, nothing kept`);
      console.log(`  total ${total.toFixed(1)}s; expected ends ${weights.map((w, k) => (total * weights.slice(0, k + 1).reduce((a, b) => a + b, 0) / sum).toFixed(1)).join(" ")}`);
      console.log(`  pauses (start-end): ${pauses(raw, audio.rate).map(([s, e]) => `${s.toFixed(1)}-${e.toFixed(1)}`).join(" ")}`);
      if (process.env.VOICE_KEEP_FAILED) fs.copyFileSync(raw, path.join(require("os").tmpdir(), "voice-failed.pcm"));
      fs.unlinkSync(raw); continue;
    }
    batch.forEach((v, k) => {
      const out = path.join(outDir, `${v.id}.ogg`);
      encode(raw, audio.rate, Math.max(0, edges[2 * k] - 0.08), Math.min(total, edges[2 * k + 1] + 0.15), out);
      // A new recording is unverified until check-voice.cjs has heard it.
      const vf = path.join(__dirname, "voice-verified.json");
      if (fs.existsSync(vf)) { const ver = JSON.parse(fs.readFileSync(vf, "utf8")); if ((ver[who] || []).includes(v.id)) { ver[who] = ver[who].filter((id) => id !== v.id); fs.writeFileSync(vf, JSON.stringify(ver, null, 1) + "\n"); } }
      console.log(`${v.id} ${audio.model} ${(lengths[k] / TEMPO).toFixed(1)}s ${fs.statSync(out).size}B`);
      made++;
    });
    fs.unlinkSync(raw);
  }
  console.log(`requests ${requests}, made ${made}, files ${fs.readdirSync(outDir).filter((f) => f.endsWith(".ogg")).length}/${all.length}`);
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });
