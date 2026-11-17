// Adds verses to content/verses.json and content/source-manifest.json from the eBible KOROLD (Korean 1910) VPL text.
// usage: node add-verses.cjs <path to kor_vpl.txt> [--write]      (without --write it only prints what it would add)
// Every text is copied byte for byte from the VPL file; a verse is added only if the provider's chapter page
// contains the same words (whitespace aside). Nothing is modernised, shortened or reconstructed.
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const ROOT = path.resolve(__dirname, "..");
const sha = (s) => crypto.createHash("sha256").update(s).digest("hex");
const [vplPath, flag] = process.argv.slice(2);
const BOOKS = { // VPL code: [Korean name, provider page code, chapter digits]
  GEN: ["창세기", "GEN", 2], DEU: ["신명기", "DEU", 2], JOS: ["여호수아", "JOS", 2], PSA: ["시편", "PSA", 3], PRO: ["잠언", "PRO", 2], ECC: ["전도서", "ECC", 2],
  ISA: ["이사야", "ISA", 2], JER: ["예레미야", "JER", 2], ZEP: ["스바냐", "ZEP", 2], MAT: ["마태복음", "MAT", 2], MAR: ["마가복음", "MRK", 2], LUK: ["누가복음", "LUK", 2],
  JOH: ["요한복음", "JHN", 2], "1CO": ["고린도전서", "1CO", 2], "2CO": ["고린도후서", "2CO", 2], PHI: ["빌립보서", "PHP", 2], "2TI": ["디모데후서", "2TI", 2],
  HEB: ["히브리서", "HEB", 2], JAM: ["야고보서", "JAS", 2], "1JO": ["요한일서", "1JN", 2], REV: ["요한계시록", "REV", 2],
};
// Well-known verses of comfort and hope, chosen for daily reading by the head on 2026-11-17 (first 30 that pass are used).
const WANT = ["GEN 1:1", "DEU 31:6", "JOS 1:9", "PSA 27:1", "PSA 28:7", "PSA 30:5", "PSA 37:4", "PSA 46:1", "PSA 55:22", "PSA 91:2", "PSA 103:2", "PSA 118:24", "PSA 145:18",
  "PRO 4:23", "PRO 17:22", "ECC 3:1", "ISA 26:3", "ISA 40:8", "JER 29:11", "JER 33:3", "ZEP 3:17", "MAT 7:7", "MAT 28:20", "MAR 9:23", "LUK 1:37", "JOH 3:16", "JOH 14:6",
  "1CO 16:14", "2CO 12:9", "HEB 11:1", "1JO 4:19", "PHI 1:6", "2TI 1:7", "JAM 1:5", "REV 21:4", "PSA 16:8", "PSA 34:18", "PSA 62:1", "PSA 121:1", "PRO 3:6",
  "ISA 43:1", "PSA 119:11", "PSA 100:5", "MAT 5:16", "JOH 8:12", "JOH 16:33", "1JO 4:8"];
// No longer than the longest verse already shipped, so every card still fits.
const TARGET = 60, MAX_CHARS = 95;
// The 1910 text marks speech with ` and ' that are often left open inside a single verse, and some psalms open with a
// long musical heading; such verses read badly alone on a card, so they are left out rather than edited.
const awkward = (t) => /[`'‘’"]/.test(t) || /^\([^)]{13,}\)/.test(t) || /(하고|하니|하시니|하리니|것이니|있나니|증거니)$/.test(t.trim());

(async () => {
  const vpl = new Map(fs.readFileSync(vplPath, "utf8").split(/\r?\n/).filter(Boolean).map((l) => { const m = l.match(/^(\S+ \d+:\d+) (.*)$/); return m ? [m[1], m[2]] : ["", ""]; }));
  const versesPath = path.join(ROOT, "content/verses.json"), manifestPath = path.join(ROOT, "content/source-manifest.json");
  const verses = JSON.parse(fs.readFileSync(versesPath, "utf8")), manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (sha(fs.readFileSync(vplPath)) !== manifest.sourceTextSha256) throw new Error("VPL file differs from the recorded source text hash");
  const have = new Set(verses.verses.map((v) => v.id));
  const pages = new Map();
  for (const ref of WANT) {
    if (verses.verses.length >= TARGET) break;
    const [code, cv] = ref.split(" "), [chapter, verse] = cv.split(":");
    const [name, page, digits] = BOOKS[code] || [];
    const id = `${code.toLowerCase()}-${chapter}-${verse}`;
    const text = vpl.get(ref);
    if (!name || !text || have.has(id)) { console.log(`skip ${ref}: ${!name ? "unknown book" : !text ? "not in VPL" : "already present"}`); continue; }
    if (text.length > MAX_CHARS) { console.log(`skip ${ref}: ${text.length} chars is too long for a card`); continue; }
    if (awkward(text)) { console.log(`skip ${ref}: open quotation, long heading or unfinished sentence`); continue; }
    const url = `https://ebible.org/kor/${page}${String(chapter).padStart(digits, "0")}.htm`;
    if (!pages.has(url)) { const res = await fetch(url); pages.set(url, res.ok ? Buffer.from(await res.arrayBuffer()) : null); }
    const html = pages.get(url);
    const norm = (s) => s.replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ").replace(/\s+/g, "");
    const matches = Boolean(html) && norm(html.toString("utf8")).includes(norm(text));
    if (!matches) { console.log(`skip ${ref}: provider page does not show the same words`); continue; }
    console.log(`add ${id} | ${name} ${chapter}:${verse} | ${text}`);
    verses.verses.push({ id, day: verses.verses.length + 1, reference: `${name} ${chapter}:${verse}`, text, sourceUrl: `${url}#V${verse}` });
    manifest.entries.push({ id, vplReference: ref, textSha256: sha(text), sourceUrl: `${url}#V${verse}`, chapterHtmlSha256: sha(html), vplMatchesChapterHtml: true });
    have.add(id);
  }
  manifest.selectionCount = verses.verses.length;
  console.log(`total ${verses.verses.length}`);
  if (flag === "--write") {
    fs.writeFileSync(versesPath, JSON.stringify(verses, null, 2) + "\n", "utf8");
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");
    console.log("written");
  }
})().catch((e) => { console.error("ERR", e.message); process.exit(1); });
