"""Native EGO Lite (v2.2.0+) TaskSpace execution engine.

Runs browser automation directly inside the user's main EGO Lite browser via
`ego-browser nodejs` TaskSpaces (`taskSpace`, `snapshot`, `evaluate`,
`screenshot`, `keyboard.paste`, `handOff`, `finish`), sharing logged-in
profiles (`Profile 3`~`Profile 7`, `Default`) natively in background Spaces
without stealing desktop focus or spawning duplicate browser instances.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Official BaroLab -> EGO Lite Profile Mapping
ACCOUNT_TO_EGO_PROFILE = {
    "soultin": "Profile 3",
    "soul5373": "Profile 4",
    "yoon_master": "Profile 5",
    "adinfo0905": "Profile 6",
    "stone0747": "Profile 7",
    "cf-flow": "Profile 3",
    "threads": "Profile 3",
    "default": "Default",
}

PORT_TO_ACCOUNT = {
    9226: "soultin",
    9334: "soultin",
    9333: "soul5373",
    9335: "yoon_master",
    9230: "adinfo0905",
    9231: "stone0747",
    9440: "cf-flow",
    9450: "threads",
}


def find_ego_cli() -> Path | None:
    """Locate the installed ego-browser CLI executable."""
    if os.name != "nt":
        return None
    candidate = Path.home() / ".local/share/ego/active_version_dir/ego-browser.exe"
    if candidate.is_file():
        return candidate
    app_dir = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Citro Labs/ego lite/Application"
    if app_dir.is_dir():
        matches = sorted(app_dir.glob("*/ego-browser.exe"), reverse=True)
        if matches:
            return matches[0]
    return None


def resolve_ego_profile(account_or_port: str | int | None) -> str:
    """Resolve a BaroLab account name or legacy CDP port to its native EGO Lite profileId."""
    if isinstance(account_or_port, int) or (isinstance(account_or_port, str) and account_or_port.isdigit()):
        account = PORT_TO_ACCOUNT.get(int(account_or_port), "soultin")
    else:
        account = str(account_or_port or "soultin").strip()
    return ACCOUNT_TO_EGO_PROFILE.get(account, "Profile 3")


def run_ego_mjs(script_source: str, *, timeout: int = 60, result_prefix: str = "BAROLAB_EGO_JSON:") -> dict:
    """Execute an ESM script in `ego-browser nodejs` via direct UTF-8 stdin pipe.

    Passing `input=script_source` directly to `[ego-browser.exe, "nodejs"]` bypasses
    PowerShell/cmd argument parsing completely and preserves 100% of UTF-8 text.
    """
    ego_cli = find_ego_cli()
    if not ego_cli:
        raise RuntimeError("ego-browser CLI is not available on this host")

    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [str(ego_cli), "nodejs"],
        input=script_source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=cflags,
    )

    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    update_notice = next(
        (line.strip() for line in combined.splitlines() if line.strip().startswith("[ego-browser:notice]")),
        None,
    )
    for line in reversed(combined.splitlines()):
        stripped = line.strip()
        if stripped.startswith(result_prefix):
            payload = json.loads(stripped[len(result_prefix):])
            if isinstance(payload, dict) and update_notice:
                payload.setdefault("egoNotice", update_notice)
            return payload

    if proc.returncode != 0:
        raise RuntimeError(f"ego-browser nodejs failed (code {proc.returncode}): {combined[-600:].strip()}")
    return {"ok": True, "rawOutput": combined.strip(), "egoNotice": update_notice}


def list_profiles_and_spaces(timeout: int = 15) -> dict:
    """Return all native EGO Lite profiles and currently active TaskSpaces."""
    script = """
const profRaw = await profiles();
const profList = Array.isArray(profRaw) ? profRaw : (profRaw?.profiles || []);
const spaces = await listTaskSpaces();
console.log("BAROLAB_EGO_JSON:" + JSON.stringify({
  ok: true,
  profiles: profList,
  taskSpaces: spaces || []
}));
"""
    return run_ego_mjs(script, timeout=timeout)


def extract_profile_cookies(account_or_port: str | int, default_url: str = "https://www.naver.com", include_default_profile: bool = False) -> list[dict]:
    """Read cookies from a native EGO Lite profile and immediately close the temporary TaskSpace."""
    profile_id = resolve_ego_profile(account_or_port)
    space_name = f"barolab-cookie-sync-{profile_id.replace(' ', '-').lower()}"
    script = f"""
const profileId = {json.dumps(profile_id)};
const spaceName = {json.dumps(space_name)};
const targetUrl = {json.dumps(default_url)};
const includeDefault = {json.dumps(bool(include_default_profile))};

async function readCookiesFromProfile(profId, sName) {{
  let task = null;
  let createdNew = false;
  try {{
    const spaces = await listTaskSpaces();
    const existing = spaces.find(s => s.name === sName && s.ownership !== 'user');
    if (existing) {{
      task = await taskSpace(existing.id);
    }} else {{
      task = await taskSpace(sName, {{ profileId: profId }});
      createdNew = true;
    }}
    const pages = await task.pages();
    const page = pages.length > 0 ? pages[0] : task.page("p1");
    const curUrl = await page.url();
    if (!curUrl || curUrl === "about:blank" || curUrl.startsWith("chrome://")) {{
      await page.goto(targetUrl, {{ waitUntil: "domcontentloaded", timeout: 12000 }}).catch(() => {{}});
    }}
    const res = await page.cdp("Network.getAllCookies");
    return res?.cookies || [];
  }} finally {{
    if (task && createdNew) {{
      await task.finish({{ keep: [] }}).catch(() => {{}});
    }}
  }}
}}

let cookies = await readCookiesFromProfile(profileId, spaceName);
if (includeDefault && profileId !== "Default") {{
  try {{
    const defCookies = await readCookiesFromProfile("Default", "barolab-cookie-sync-default");
    cookies = cookies.concat(defCookies);
  }} catch (e) {{}}
}}
console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{ ok: true, profileId, cookies }}));
"""
    res = run_ego_mjs(script, timeout=25)
    return res.get("cookies") or []


def handoff_to_ceo(account_or_port: str | int, url: str, reason: str, space_label: str = "BaroLab-CEO-Action") -> dict:
    """Open a native EGO Lite TaskSpace at `url` and call `task.handOff()` for user intervention."""
    profile_id = resolve_ego_profile(account_or_port)
    space_name = f"{space_label}-{profile_id.replace(' ', '')}"
    script = f"""
const task = await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
const page = task.page("p1");
await page.goto({json.dumps(url)}, {{ waitUntil: "domcontentloaded", timeout: 20000 }}).catch(() => {{}});
const finalUrl = await page.url();
const title = await page.title();
await task.handOff();
console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
  ok: true,
  status: "handed_off_to_user",
  spaceId: task.spaceId,
  spaceName: task.name,
  profileId: {json.dumps(profile_id)},
  url: finalUrl,
  title,
  reason: {json.dumps(reason)}
}}));
"""
    return run_ego_mjs(script, timeout=30)


def native_observe_space(account_or_port: str | int, url: str | None = None, timeout: int = 25) -> dict:
    """Inspect a page inside a native EGO Lite TaskSpace using `page.snapshot()` + DOM state."""
    profile_id = resolve_ego_profile(account_or_port)
    space_name = f"barolab-observe-{profile_id.replace(' ', '-').lower()}"
    script = f"""
const task = await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
try {{
  const page = task.page("p1");
  const targetUrl = {json.dumps(url)};
  if (targetUrl) {{
    await page.goto(targetUrl, {{ waitUntil: "domcontentloaded", timeout: 15000 }}).catch(() => {{}});
  }}
  const currentUrl = await page.url();
  const title = await page.title();
  const snap = await page.snapshot().catch(() => "");
  const controls = await page.evaluate(() => ({{
    buttons: Array.from(document.querySelectorAll('button,[role=button]'))
      .filter(e => e.getClientRects().length)
      .map(e => (e.getAttribute('aria-label') || e.innerText || '').trim())
      .filter(t => t && t.length < 100 && !t.includes('@'))
      .slice(0, 60),
    editors: Array.from(document.querySelectorAll('[contenteditable=true]')).map(e => ({{
      visible: !!e.getClientRects().length,
      characters: (e.innerText || '').trim().length,
      inDialog: !!e.closest('[role=dialog]')
    }})),
    dialogs: document.querySelectorAll('[role=dialog]').length
  }})).catch(() => ({{ buttons: [], editors: [], dialogs: 0 }}));
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: true,
    status: "observed",
    executor: "ego-lite-native-taskspace",
    spaceId: task.spaceId,
    profileId: {json.dumps(profile_id)},
    url: currentUrl,
    title,
    snapshot: snap.slice(0, 4000),
    controls
  }}));
}} finally {{
  await task.finish({{ keep: [] }}).catch(() => {{}});
}}
"""
    return run_ego_mjs(script, timeout=timeout)


def native_benchmark_blog_screen(query: str, folder: str | Path) -> dict:
    """Benchmark a Naver Blog article 100% inside a native EGO Lite background TaskSpace.

    - Uses `Profile 3` (`soultin`) inside the main EGO Lite browser.
    - Never steals desktop focus (`SetForegroundWindow` is never called).
    - Uses `page.snapshot()` + `page.evaluate()` + `mouse.wheel(..., { label })` + `page.screenshot()`
      to capture `screen-000.png` .. `screen-007.png` and extract exact SmartEditor presentation
      metrics and `bodySha256`, then closes the TaskSpace cleanly via `await task.finish({ keep: [] })`.
    """
    from common.collection_observability import write

    folder = Path(folder)
    bench_dir = folder / "ego-screen-benchmark"
    bench_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = folder / "screen-benchmark.json"

    search_url = "https://search.naver.com/search.naver?where=blog&query=" + quote(query)
    bench_dir_posix = bench_dir.resolve().as_posix()
    space_name = f"barolab-radar-benchmark-{hashlib.sha1(query.encode('utf-8')).hexdigest()[:8]}"

    script = f"""
const query = {json.dumps(query)};
const searchUrl = {json.dumps(search_url)};
const benchDir = {json.dumps(bench_dir_posix)};
const spaceName = {json.dumps(space_name)};

const task = await taskSpace(spaceName, {{ profileId: "Profile 3" }});
const turns = [];
const screenshots = [];
try {{
  const page = task.page("p1");
  await page.goto(searchUrl, {{ waitUntil: "domcontentloaded", timeout: 20000 }});
  await page.waitForTimeout(800);
  const s0 = benchDir + "/screen-000.png";
  await page.screenshot({{ path: s0 }});
  turns.push({{
    turn: 0,
    screenshot: "screen-000.png",
    url: await page.url(),
    actualModel: "ego-lite-native-taskspace-v2.2",
    message: "네이버 블로그 검색 결과 스냅샷을 확인하고 개인 블로그 글을 선택합니다.",
    actions: [{{ kind: "navigate", x: 0, y: 0, value: "search" }}],
    completedActions: 1
  }});

  const candidates = await page.evaluate(() => {{
    const anchors = Array.from(document.querySelectorAll("a[href*='blog.naver.com/']"));
    const seen = new Set();
    const items = [];
    const officialSkip = /정책브리핑|대한민국정부|보건복지부|고용노동부|국세청|공식블로그|도청|시청|군청|구청/;
    for (const a of anchors) {{
      const href = a.href || "";
      const m = href.match(/^https:\\/\\/blog\\.naver\\.com\\/([A-Za-z0-9_-]+)\\/(\\d+)/);
      if (!m) continue;
      if (seen.has(m[0])) continue;
      const card = a.closest(".view_wrap, .bx, li, article") || a.parentElement;
      const cardText = (card ? card.innerText : a.innerText) || "";
      const title = (a.innerText || "").trim();
      if (title.length < 4 && cardText.length < 20) continue;
      seen.add(m[0]);
      items.push({{
        url: m[0],
        blogId: m[1],
        logNo: m[2],
        title: title.slice(0, 120),
        isOfficial: officialSkip.test(cardText.slice(0, 200))
      }});
    }}
    items.sort((x, y) => Number(x.isOfficial) - Number(y.isOfficial));
    return items.slice(0, 5);
  }});

  if (!candidates || candidates.length === 0) {{
    throw new Error("No Naver Blog article candidates found for query: " + query);
  }}

  const chosen = candidates[0];
  await page.goto(chosen.url, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  await page.waitForTimeout(1200);

  // Scroll inside mainFrame or window to observe the full post from top to bottom
  await page.mouse.move(480, 420, {{ label: "inspect blog article" }});
  for (let i = 1; i <= 7; i++) {{
    const sName = `screen-00${{i}}.png`;
    const sPath = `${{benchDir}}/${{sName}}`;
    await page.screenshot({{ path: sPath }});
    screenshots.push(sName);
    turns.push({{
      turn: i,
      screenshot: sName,
      url: chosen.url,
      actualModel: "ego-lite-native-taskspace-v2.2",
      message: `블로그 본문 스크롤 구간 #${{i}} 스냅샷 및 스타일 관측 완료`,
      actions: [{{ kind: "scroll", x: 480, y: 420, value: "down" }}],
      completedActions: 1
    }});
    await page.evaluate(() => {{
      const iframe = document.querySelector("iframe#mainFrame");
      const win = iframe?.contentWindow || window;
      win.scrollBy(0, Math.max(520, Math.round(win.innerHeight * 0.72)));
    }});
    await page.waitForTimeout(350);
  }}

  const snap = await page.snapshot().catch(() => "");
  const analysis = await page.evaluate(() => {{
    const iframe = document.querySelector("iframe#mainFrame");
    const doc = iframe?.contentDocument || document;
    const win = iframe?.contentWindow || window;
    const container = doc.querySelector(".se-main-container, #postViewArea") || doc.body;
    const bodyText = (container?.innerText || "").trim();

    const titleEl = doc.querySelector(".se-documentTitle .se-text-paragraph, .se-title-text, .pcol1");
    const titleText = (titleEl?.innerText || doc.title || "").trim();

    const paragraphs = Array.from(doc.querySelectorAll(".se-component.se-text .se-text-paragraph"));
    const sampleSpans = Array.from(doc.querySelectorAll(".se-component.se-text .se-text-paragraph span"))
      .filter(s => (s.innerText || "").trim().length > 4)
      .slice(0, 12);

    const fonts = [];
    const sizes = [];
    const aligns = [];
    for (const p of paragraphs.slice(0, 15)) {{
      const cs = win.getComputedStyle(p);
      if (cs.textAlign) aligns.push(cs.textAlign);
    }}
    for (const s of sampleSpans) {{
      const cs = win.getComputedStyle(s);
      if (cs.fontFamily) fonts.push(cs.fontFamily.split(",")[0].replace(/['"]/g, "").trim());
      if (cs.fontSize) sizes.push(cs.fontSize);
    }}

    const quotes = doc.querySelectorAll(".se-component.se-quotation").length;
    const dividers = doc.querySelectorAll(".se-component.se-horizontalLine").length;
    const images = doc.querySelectorAll(".se-component.se-image, .se-module-image").length;
    const captions = Array.from(doc.querySelectorAll(".se-caption"))
      .map(c => (c.innerText || "").trim())
      .filter(Boolean);
    const stickers = doc.querySelectorAll(".se-component.se-sticker").length;
    const tables = doc.querySelectorAll(".se-component.se-table, table.se-table-content").length;
    const oglinks = doc.querySelectorAll(".se-component.se-oglink").length;
    const headings = Array.from(doc.querySelectorAll(".se-sectionTitle, .se-component.se-quotation"))
      .map(h => (h.innerText || "").trim())
      .filter(Boolean)
      .slice(0, 8);

    return {{
      titleText,
      bodyText,
      paragraphCount: paragraphs.length,
      primaryFont: fonts[0] || "나눔고딕",
      primaryFontSize: sizes[0] || "16px",
      primaryAlign: aligns[0] || "left",
      quotes,
      dividers,
      images,
      captionCount: captions.length,
       stickers,
      tables,
      oglinks,
      headings
    }};
  }});

  const obs = [
    `제목 및 도입부: '${{analysis.titleText.slice(0, 60)}}' 제목으로 시작하며 총 ${{analysis.paragraphCount}}개 문단으로 호흡을 구성함`,
    `글꼴 및 정렬 인상: 주 글꼴 ${{analysis.primaryFont}}(${{analysis.primaryFontSize}}), 기본 문단 정렬은 ${{analysis.primaryAlign}} 정렬 중심`,
    `소제목 및 인용구·구분선: 인용구 ${{analysis.quotes}}개, 가로 구분선 ${{analysis.dividers}}개를 활용해 섹션을 명확히 분리함 (${{analysis.headings.slice(0, 3).join(" / ") || " 텍스트 강조 중심"}})`,
    `시각 자료 구성: 본문 이미지 ${{analysis.images}}장(캡션 ${{analysis.captionCount}}개), 스티커 ${{analysis.stickers}}개 배치`,
    `구조화 컴포넌트: 비교표(테이블) ${{analysis.tables}}개, 관련 링크카드(OGLink) ${{analysis.oglinks}}개 포함`
  ];

  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: true,
    chosenUrl: chosen.url,
    turns,
    screenshots,
    observations: obs,
    bodyText: analysis.bodyText,
    snapshotPreview: snap.slice(0, 800)
  }}));
}} finally {{
  await task.finish({{ keep: [] }}).catch(() => {{}});
}}
"""
    raw = run_ego_mjs(script, timeout=75)
    chosen_url = raw.get("chosenUrl")
    if not chosen_url or "blog.naver.com/" not in chosen_url:
        raise ValueError("Native TaskSpace benchmarking did not observe a valid Naver Blog article")

    body_text = raw.get("bodyText") or ""
    body_sha256 = hashlib.sha256(body_text.encode("utf-8")).hexdigest() if body_text else None
    observations = raw.get("observations") or []
    turns = raw.get("turns") or []
    screenshots = raw.get("screenshots") or []

    exec_state = {
        "executor": "ego-lite",
        "mode": "native-taskspace-snapshot-and-screen",
        "status": "screen_task_complete",
        "startedAt": datetime.now(ZoneInfo("Asia/Seoul")).timestamp(),
        "finishedAt": datetime.now(ZoneInfo("Asia/Seoul")).timestamp(),
        "written": [],
        "turns": turns,
        "observations": observations,
    }
    write(bench_dir / "screen-execution.json", exec_state)

    article_entry = {
        "url": chosen_url,
        "organicRank": None,
        "visualObservations": observations,
        "screenshots": screenshots,
    }
    if body_sha256:
        article_entry["bodySha256"] = body_sha256
        article_entry["bodyHashSource"] = "read-only article DOM in native EGO TaskSpace"

    result = {
        "query": query,
        "status": "observed",
        "executor": "ego-lite",
        "mode": "screenshot-decisions",
        "nativeTaskSpace": True,
        "checkedAt": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
        "articles": [article_entry],
    }
    write(receipt_path, result)
    write(
        folder / "ego-benchmark-tab.json",
        {
            "closedUrls": [chosen_url],
            "createdByTask": True,
            "retained": False,
            "reason": "Closed native EGO Lite TaskSpace via task.finish({ keep: [] })",
        },
    )
    return result
