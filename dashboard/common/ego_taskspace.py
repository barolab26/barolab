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
import time
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
    9231: "adinfo0905",
    9230: "stone0747",
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


def _ego_cli_lock_path() -> Path:
    p = Path(__file__).resolve().parents[1] / "data" / "ego-cli.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def run_ego_mjs(script_source: str, *, timeout: int = 60, result_prefix: str = "BAROLAB_EGO_JSON:") -> dict:
    """Execute an ESM script in `ego-browser nodejs` via direct UTF-8 stdin pipe with serialized lock + retry."""
    ego_cli = find_ego_cli()
    if not ego_cli:
        raise RuntimeError("ego-browser CLI is not available on this host")

    wrapped_source = (
        "async function __barolabReclaimSpaces() {\n"
        "  try {\n"
        "    const sp = await listTaskSpaces();\n"
        "    for (const s of (Array.isArray(sp) ? sp : [])) {\n"
        "      if (s && typeof s.name === 'string' && s.name.startsWith('barolab-') && s.ownership === 'user' && s.id !== undefined) {\n"
        "        await claimTaskSpace(s.id).catch(() => {});\n"
        "      }\n"
        "    }\n"
        "  } catch (_) {}\n"
        "}\n"
        f"async function __barolabRun() {{\n  await __barolabReclaimSpaces();\n{script_source}\n}}\n"
        f"try {{ await __barolabRun(); }} catch (__err) {{ console.log({json.dumps(result_prefix)} + JSON.stringify({{ ok: false, error: String(__err) }})); }} finally {{ process.exit(0); }}\n"
    )
    cflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    lock_path = _ego_cli_lock_path()
    last_err = None

    for attempt in range(3):
        lock_file = lock_path.open("a+b")
        locked = False
        try:
            lock_file.seek(0, 2)
            if not lock_file.tell():
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt
                deadline = time.time() + max(15, min(timeout, 45))
                while time.time() < deadline:
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        time.sleep(0.25)
            proc = subprocess.run(
                [str(ego_cli), "nodejs"],
                input=wrapped_source,
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
                last_err = RuntimeError(f"ego-browser nodejs failed (code {proc.returncode}): {combined[-600:].strip()}")
                if proc.returncode == 5 and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise last_err
            return {"ok": True, "rawOutput": combined.strip(), "egoNotice": update_notice}
        except subprocess.TimeoutExpired as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        finally:
            if locked and os.name == "nt":
                try:
                    import msvcrt
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            lock_file.close()
    raise last_err or RuntimeError("ego-browser nodejs failed")


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


def _ensure_ego_window_visible_on_desktop() -> dict:
    """When called from the interactive desktop (WinSta0\\Default), ensure EGO Lite is running without stealing focus or killing user windows."""
    if os.name != "nt":
        return {"ok": True, "mode": "non_windows"}
    try:
        import ctypes
        from ctypes import wintypes
        u32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        total_hwnds = [0]
        def _count_cb(hwnd, lparam):
            total_hwnds[0] += 1
            return True
        u32.EnumWindows(WNDENUMPROC(_count_cb), 0)
        if total_hwnds[0] < 10:
            return {"ok": True, "mode": "sandbox_desktop", "totalHwnds": total_hwnds[0]}

        restart_flag = Path(__file__).resolve().parents[1] / "data" / "restart_ego_once.flag"
        force_restart = restart_flag.exists()
        ego_exe = Path(r"C:\Program Files\Citro Labs\ego lite\Application\ego.exe")
        if force_restart and ego_exe.exists():
            try:
                restart_flag.unlink()
            except OSError:
                pass
            subprocess.run(
                ["taskkill", "/F", "/IM", "ego-browser.exe", "/IM", "ego.exe"],
                capture_output=True,
                timeout=6,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(1.5)
            subprocess.Popen(
                [str(ego_exe), "http://127.0.0.1:8790/index.html"],
                cwd=str(ego_exe.parent),
            )
            time.sleep(4.0)
            return {"ok": True, "mode": "restarted_clean_on_desktop"}

        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-Process ego -ErrorAction SilentlyContinue).Id"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ego_pids = {int(x) for x in (res.stdout or "").split() if x.strip().isdigit()}
        if ego_pids:
            return {"ok": True, "mode": "already_running", "pidCount": len(ego_pids)}
        if ego_exe.exists():
            subprocess.Popen(
                [str(ego_exe), "http://127.0.0.1:8790/index.html"],
                cwd=str(ego_exe.parent),
            )
            time.sleep(3.5)
            return {"ok": True, "mode": "launched_on_desktop"}
        return {"ok": False, "mode": "ego_exe_missing"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def ensure_persistent_ego_spaces(timeout: int = 45) -> dict:
    """Ensure all 6 BaroLab Spaces (5 Naver accounts + Google Flow) stay open and clean (1 tab each) inside EGO Lite."""
    desktop_vis = _ensure_ego_window_visible_on_desktop()
    script = """
const TARGET_SPACES = [
  { account: "soultin", name: "barolab-soultin", profileId: "Profile 3", url: "https://blog.naver.com/mustpickinfo" },
  { account: "soul5373", name: "barolab-soul5373", profileId: "Profile 4", url: "https://adpost.naver.com/main" },
  { account: "yoon_master", name: "barolab-yoon_master", profileId: "Profile 5", url: "https://blog.naver.com/yoonviews" },
  { account: "adinfo0905", name: "barolab-kin-adinfo0905", profileId: "Profile 6", url: "https://kin.naver.com/" },
  { account: "stone0747", name: "barolab-kin-stone0747", profileId: "Profile 7", url: "https://kin.naver.com/" },
  { account: "cf-flow", name: "barolab-cf-flow", profileId: "Profile 3", url: "https://flow.google.com/" }
];
const targetNames = new Set(TARGET_SPACES.map(t => t.name));
const existing = await listTaskSpaces();
for (const s of (Array.isArray(existing) ? existing : [])) {
  if (!s || typeof s.name !== "string" || !s.name || targetNames.has(s.name)) continue;
  if (/^(editorial-|adpost-|barolab-cookie-sync-|barolab-cf-inline|barolab-verify|barolab-preview)/.test(s.name)) {
    try {
      const t = s.ownership === "agentDelegatedToUser" ? await takeOverTaskSpace(s.id) : (s.ownership === "user" ? await claimTaskSpace(s.id) : await taskSpace(s.id));
      try { const up = t.userPage && t.userPage(); if (up && up.dismissDialog) await up.dismissDialog().catch(() => {}); } catch (_) {}
      try { const p1 = t.page("p1"); if (p1 && p1.dismissDialog) await p1.dismissDialog().catch(() => {}); } catch (_) {}
      await t.finish({ keep: [] }).catch(() => {});
    } catch (_) {}
  }
}
const opened = [];
for (const cfg of TARGET_SPACES) {
  const found = Array.isArray(existing) ? existing.find(s => s && s.name === cfg.name) : null;
  const needTrim = found && Array.isArray(found.recentTabTitles) && found.recentTabTitles.length > 1;
  if (found && !needTrim && Array.isArray(found.recentTabTitles) && found.recentTabTitles.length === 1 && found.recentTabTitles[0] !== "새 탭") {
    opened.push({
      account: cfg.account,
      spaceName: cfg.name,
      spaceId: found.id,
      profileId: cfg.profileId
    });
    continue;
  }
  const task = found ? await taskSpace(found.id) : await taskSpace(cfg.name, { profileId: cfg.profileId });
  const pages = await task.pages().catch(() => []);
  if (pages.length > 1) {
    let keepIdx = pages.findIndex(p => p);
    for (let i = 0; i < pages.length; i++) {
      const u = await pages[i].url().catch(() => "");
      if (u && !u.startsWith("chrome-extension://") && !u.startsWith("chrome://") && u !== "about:blank") {
        keepIdx = i;
        break;
      }
    }
    for (let i = 0; i < pages.length; i++) {
      if (i !== keepIdx) {
        await pages[i].cdp("Page.close").catch(() => {});
      }
    }
  }
  const remPages = await task.pages().catch(() => []);
  const page = remPages.length > 0 ? remPages[0] : task.page("p1");
  const curUrl = await page.url().catch(() => "");
  if (!curUrl || curUrl === "about:blank" || curUrl.startsWith("chrome://") || curUrl.startsWith("chrome-extension://")) {
    await page.goto(cfg.url, { waitUntil: "domcontentloaded", timeout: 15000 }).catch(() => {});
  }
  opened.push({
    account: cfg.account,
    spaceName: cfg.name,
    spaceId: task.spaceId,
    profileId: cfg.profileId
  });
}
const profRaw = await profiles();
const profList = Array.isArray(profRaw) ? profRaw : (profRaw?.profiles || []);
const spaces = await listTaskSpaces();
console.log("BAROLAB_EGO_JSON:" + JSON.stringify({
  ok: true,
  profiles: profList,
  taskSpaces: Array.isArray(spaces) ? spaces : [],
  opened
}));
"""
    res = run_ego_mjs(script, timeout=timeout)
    if isinstance(res, dict):
        res["desktopVisibility"] = desktop_vis
        if desktop_vis.get("mode") != "sandbox_desktop":
            try:
                vis_path = Path(__file__).resolve().parents[1] / "data" / "ego-desktop-visibility.json"
                vis_path.write_text(json.dumps(desktop_vis, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
    return res


def extract_profile_cookies(account_or_port: str | int, default_url: str = "https://www.naver.com", include_default_profile: bool = False) -> list[dict]:
    """Read cookies from an existing EGO Lite profile TaskSpace without spawning extra profile windows."""
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
    const existing = spaces.find(s => s.profileId === profId && s.ownership !== 'user') || spaces.find(s => s.name === sName && s.ownership !== 'user');
    if (existing) {{
      task = await taskSpace(existing.name || existing.id);
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


def inject_profile_cookies(account_or_port: str | int, cookies: list[dict], default_url: str = "https://www.naver.com") -> bool:
    """Inject cookies into a native EGO Lite profile so the profile regains login session."""
    if not cookies:
        return False
    profile_id = resolve_ego_profile(account_or_port)
    account = PORT_TO_ACCOUNT.get(int(account_or_port), "soultin") if (isinstance(account_or_port, int) or str(account_or_port).isdigit()) else str(account_or_port).strip()
    space_map = {
        "soultin": "barolab-soultin",
        "soul5373": "barolab-soul5373",
        "yoon_master": "barolab-yoon_master",
        "adinfo0905": "barolab-kin-adinfo0905",
        "stone0747": "barolab-kin-stone0747",
    }
    space_name = space_map.get(account, f"barolab-{account}")
    clean_cookies = []
    for c in cookies:
        item = {k: c[k] for k in ("name", "value", "domain", "path", "secure", "httpOnly", "sameSite", "expires") if k in c and c[k] is not None}
        if item.get("expires", -1) <= 0:
            item.pop("expires", None)
        clean_cookies.append(item)
    script = f"""
const spaceName = {json.dumps(space_name)};
const profileId = {json.dumps(profile_id)};
const targetUrl = {json.dumps(default_url)};
const cookies = {json.dumps(clean_cookies)};
const spaces = await listTaskSpaces();
const existing = Array.isArray(spaces) ? spaces.find(s => s && s.name === spaceName) : null;
const task = existing ? await taskSpace(existing.id) : await taskSpace(spaceName, {{ profileId }});
const page = task.page("p1");
await page.cdp("Network.setCookies", {{ cookies }});
await page.goto(targetUrl, {{ waitUntil: "domcontentloaded", timeout: 15000 }}).catch(() => {{}});
console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{ ok: true, spaceName, injected: cookies.length }}));
"""
    try:
        res = run_ego_mjs(script, timeout=25)
        return bool((res or {}).get("ok"))
    except Exception:
        return False


def open_naver_reservation_in_ego_space(account_key: str, blog_id: str, latest_title: str | None = None, timeout: int = 35) -> dict:
    """Open the Naver SmartEditor ONE reservation list inside the account's persistent EGO Lite Space."""
    profile_id = resolve_ego_profile(account_key)
    space_map = {
        "soultin": "barolab-soultin",
        "soul5373": "barolab-soul5373",
        "yoon_master": "barolab-yoon_master",
        "adinfo0905": "barolab-kin-adinfo0905",
        "stone0747": "barolab-kin-stone0747",
    }
    space_name = space_map.get(account_key, f"barolab-{account_key}")
    write_url = f"https://blog.naver.com/{blog_id}?Redirect=Write&"
    script = f"""
const spaceName = {json.dumps(space_name)};
const profileId = {json.dumps(profile_id)};
const writeUrl = {json.dumps(write_url)};
const latestTitle = {json.dumps(latest_title or "")};

const spaces = await listTaskSpaces();
const existing = Array.isArray(spaces) ? spaces.find(s => s && s.name === spaceName) : null;
const task = existing ? await taskSpace(existing.id) : await taskSpace(spaceName, {{ profileId }});
const page = task.page("p1");
const curUrl = await page.url().catch(() => "");
if (!curUrl.includes("Redirect=Write")) {{
  await page.goto(writeUrl, {{ waitUntil: "domcontentloaded", timeout: 25000 }}).catch(() => {{}});
  await page.waitForTimeout(3200);
}}

const state = await page.evaluate(async () => {{
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const iframe = document.querySelector("iframe#mainFrame");
  const doc = iframe?.contentDocument || document;
  const cancelBtn = doc.querySelector(".se-popup-button-cancel");
  if (cancelBtn && cancelBtn.offsetParent !== null) {{
    cancelBtn.click();
    await sleep(400);
  }}
  const els = Array.from(doc.querySelectorAll("button, a"));
  const opener = els.find(el => /^예약 발행\\s*\\d+건$/.test((el.innerText || "").trim()) && el.offsetParent !== null);
  let reservationCountText = "";
  if (opener) {{
    reservationCountText = (opener.innerText || "").trim();
    const alreadyOpen = Array.from(doc.querySelectorAll("h1, h2, h3, strong, div, span")).some(el => (el.innerText || "").trim() === "예약 발행 글" && el.offsetParent !== null);
    if (!alreadyOpen) {{
      opener.click();
      await sleep(700);
    }}
  }}
  const modalOpen = Array.from(doc.querySelectorAll("h1, h2, h3, strong, div, span")).some(el => (el.innerText || "").trim() === "예약 발행 글" && el.offsetParent !== null);
  const items = Array.from(doc.querySelectorAll("li, tr, div")).map(el => (el.innerText || "").trim()).filter(t => t.includes("2026.") && t.length < 160).slice(0, 6);
  return {{
    url: location.href,
    reservationCountText,
    modalOpen,
    items
  }};
}});

console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
  ok: true,
  account: {json.dumps(account_key)},
  spaceName,
  ...state
}}));
"""
    return run_ego_mjs(script, timeout=timeout)


def handoff_to_ceo(account_or_port: str | int, url: str, reason: str, space_label: str = "BaroLab-CEO-Action") -> dict:
    """Open a native EGO Lite TaskSpace at `url` and call `task.handOff()` for user intervention."""
    profile_id = resolve_ego_profile(account_or_port)
    space_name = f"{space_label}-{profile_id.replace(' ', '')}"
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === {json.dumps(space_name)}) : null;
const task = found ? await taskSpace(found.id) : await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
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
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === {json.dumps(space_name)}) : null;
const task = found ? await taskSpace(found.id) : await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
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

const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === spaceName) : null;
const task = found ? await taskSpace(found.id) : await taskSpace(spaceName, {{ profileId: "Profile 3" }});
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


def native_kin_fetch_page_state(account: str, url: str, *, load_all_answers: bool = False, fast_fetch: bool = False) -> dict:
    """Read a Naver KnowledgeIn question/answer page inside the main EGO Lite browser's native TaskSpace."""
    profile_id = resolve_ego_profile(account)
    space_name = f"barolab-kin-{account}"
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === {json.dumps(space_name)}) : null;
const task = found ? await taskSpace(found.id) : await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
try {{
  const page = task.page("p1");
  const curHost = await page.evaluate(() => location.hostname).catch(() => "");
  if (curHost !== "kin.naver.com") {{
    await page.goto("https://kin.naver.com/", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  }}
  if ({json.dumps(bool(fast_fetch))}) {{
    const fast = await page.evaluate(async (targetUrl) => {{
      try {{
        const res = await fetch(targetUrl, {{ credentials: "include" }});
        if (!res.ok) return {{ ok: false }};
        const html = await res.text();
        const mTotal = html.match(/totalAnswerCount\\s*:\\s*(\\d+)/);
        const total = mTotal ? parseInt(mTotal[1], 10) : 0;
        const loaded = (html.match(/id="answer_\\d+"/g) || []).length;
        const hasMyAnswer = html.includes("_myAnswer") || html.includes("optModify");
        return {{
          ok: true,
          url: res.url || targetUrl,
          html,
          total,
          loaded,
          needsPagination: total > loaded && !hasMyAnswer
        }};
      }} catch (e) {{
        return {{ ok: false }};
      }}
    }}, {json.dumps(url)});
    if (fast && fast.ok && !fast.needsPagination && fast.html.includes("naver.isLogin")) {{
      console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
        ok: true,
        account: {json.dumps(account)},
        profileId: {json.dumps(profile_id)},
        spaceId: task.spaceId,
        url: fast.url,
        dialogs: [],
        html: fast.html,
        bodyText: "",
        answerCount: fast.loaded,
        fastFetch: true
      }}));
      return;
    }}
  }}
  await page.goto("https://kin.naver.com/", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  const loginCheck = await page.evaluate(() => {{
    const el = document.querySelector(".my_service .user_id");
    return {{ url: location.href, userId: el ? el.innerText.trim() : null }};
  }});
  if (loginCheck.url.includes("nid.naver.com") || loginCheck.userId !== {json.dumps(account)}) {{
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "LoginRequiredError",
      message: "Logged-in KnowledgeIn identity does not match authorized account",
      observedUserId: loginCheck.userId,
      url: loginCheck.url
    }}));
    return;
  }}

  await page.goto({json.dumps(url)}, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  await page.waitForTimeout(400);

  const inspectState = async () => {{
    return await page.evaluate(() => {{
      const dialogs = [];
      for (const sel of ["#notAnswerableLayer", "#deferredExpertLayer", "[role=\\"dialog\\"]"]) {{
        for (const el of document.querySelectorAll(sel)) {{
          if (el.getClientRects().length > 0) {{
            const msg = (el.innerText || "").trim();
            if (msg) dialogs.push({{ selector: sel, message: msg }});
          }}
        }}
      }}
      const qDetail = document.querySelector(".questionDetail");
      return {{
        url: location.href,
        dialogs,
        html: document.documentElement.outerHTML,
        bodyText: qDetail ? qDetail.innerText.trim() : "",
        answerCount: document.querySelectorAll(".answerArea[id^=answer_]").length
      }};
    }});
  }};

  let state = await inspectState();
  if ({json.dumps(bool(load_all_answers))}) {{
    for (let i = 0; i < 15; i++) {{
      const clicked = await page.evaluate(() => {{
        const btns = Array.from(document.querySelectorAll("#nextPageButton, #lastNextPageButton"))
          .filter(b => b.getClientRects().length > 0 && !b.disabled);
        if (btns.length !== 1) return false;
        btns[0].click();
        return true;
      }});
      if (!clicked) break;
      await page.waitForTimeout(900);
      state = await inspectState();
    }}
  }}

  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: true,
    account: {json.dumps(account)},
    profileId: {json.dumps(profile_id)},
    spaceId: task.spaceId,
    ...state
  }}));
}} finally {{
  // Keep persistent Space open inside the user's main EGO Lite browser sidebar
}}
"""
    return run_ego_mjs(script, timeout=60)


def native_kin_discover_links(account: str, search_urls: list[dict]) -> dict:
    """Collect KnowledgeIn search result links inside the main EGO Lite browser's native TaskSpace."""
    profile_id = resolve_ego_profile(account)
    space_name = f"barolab-kin-{account}"
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === {json.dumps(space_name)}) : null;
const task = found ? await taskSpace(found.id) : await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
try {{
  const page = task.page("p1");
  await page.goto("https://kin.naver.com/", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  const loginCheck = await page.evaluate(() => {{
    const el = document.querySelector(".my_service .user_id");
    return {{ url: location.href, userId: el ? el.innerText.trim() : null }};
  }});
  if (loginCheck.url.includes("nid.naver.com") || loginCheck.userId !== {json.dumps(account)}) {{
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "LoginRequiredError",
      message: "Logged-in KnowledgeIn identity does not match authorized account"
    }}));
    return;
  }}

  const groups = [];
  for (const item of {json.dumps(search_urls)}) {{
    await page.goto(item.searchUrl, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
    const hrefs = await page.evaluate(() => {{
      const rows = Array.from(document.querySelectorAll("._searchListTitleAnchor")).map((e, idx) => {{
        const href = e.href || "";
        const li = e.closest("li") || e.parentElement;
        const txt = li ? (li.innerText || "") : "";
        const m = txt.match(/답변수\\s*(\\d+)/);
        const ansCnt = m ? parseInt(m[1], 10) : 0;
        return {{ href, ansCnt, idx }};
      }}).filter(r => Boolean(r.href));
      const lowComp = rows.filter(r => r.ansCnt <= 3);
      const pool = lowComp.length > 0 ? lowComp : rows.filter(r => r.ansCnt <= 4);
      pool.sort((a, b) => (a.ansCnt - b.ansCnt) || (a.idx - b.idx));
      return pool.map(r => r.href);
    }});
    groups.push(hrefs.map(href => ({{ href, ordering: item.ordering, keyword: item.keyword }})));
  }}
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: true,
    account: {json.dumps(account)},
    profileId: {json.dumps(profile_id)},
    spaceId: task.spaceId,
    groups
  }}));
}} finally {{
  // Keep persistent Space open inside the user's main EGO Lite browser sidebar
}}
"""
    return run_ego_mjs(script, timeout=75)


def native_kin_prepare_and_submit(account: str, question_url: str, answer_text: str, expected_urls: list[str]) -> dict:
    """Type and submit a KnowledgeIn answer inside the main EGO Lite browser's native TaskSpace."""
    profile_id = resolve_ego_profile(account)
    space_name = f"barolab-kin-{account}"
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === {json.dumps(space_name)}) : null;
const task = found ? await taskSpace(found.id) : await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
let retainSpace = false;
try {{
  const page = task.page("p1");
  await page.goto("https://kin.naver.com/", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  const loginCheck = await page.evaluate(() => {{
    const el = document.querySelector(".my_service .user_id");
    return {{ url: location.href, userId: el ? el.innerText.trim() : null }};
  }});
  if (loginCheck.url.includes("nid.naver.com") || loginCheck.userId !== {json.dumps(account)}) {{
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "LoginRequiredError",
      message: "Logged-in KnowledgeIn identity does not match authorized account"
    }}));
    return;
  }}

  await page.goto({json.dumps(question_url)}, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  await page.waitForTimeout(500);

  const preDialogs = await page.evaluate(() => {{
    const dialogs = [];
    for (const sel of ["#notAnswerableLayer", "#deferredExpertLayer", "[role=\\"dialog\\"]"]) {{
      for (const el of document.querySelectorAll(sel)) {{
        if (el.getClientRects().length > 0) {{
          const msg = (el.innerText || "").trim();
          if (msg) dialogs.push({{ selector: sel, message: msg }});
        }}
      }}
    }}
    return dialogs;
  }});
  if (preDialogs.length > 0) {{
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "DialogRestriction",
      dialogs: preDialogs
    }}));
    return;
  }}

  const hasWriteBtn = await page.evaluate(() => {{
    const btn = document.querySelector("._answerWriteButton");
    if (!btn) return false;
    btn.scrollIntoView({{ block: "center" }});
    btn.click();
    return true;
  }});
  if (!hasWriteBtn) {{
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "WriteButtonMissing",
      message: "Answer write button is not available on this question"
    }}));
    return;
  }}
  await page.waitForSelector(".se-canvas .se-text-paragraph", {{ timeout: 15000 }});

  const existingDraft = await page.evaluate(() => {{
    return Array.from(document.querySelectorAll(".se-canvas .se-text-paragraph .__se-node"))
      .some(n => (n.innerText || "").trim().length > 0);
  }});
  if (existingDraft) {{
    retainSpace = true;
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "ExistingDraftError",
      message: "Existing editor text requires manual review"
    }}));
    return;
  }}

  await page.click(".se-canvas .se-text-paragraph");
  const lines = {json.dumps(answer_text)}.split("\\n");
  for (const line of lines) {{
    if (line) {{
      await page.keyboard.insertText(line);
    }}
    await page.keyboard.press("Enter");
  }}

  let editorReady = false;
  for (let i = 0; i < 60; i++) {{
    editorReady = await page.evaluate(() => {{
      const editor = window.SmartEditor?.getEditor?.("kinpc001");
      if (!editor || typeof editor.isDocumentProcessing !== "function" || typeof editor.isEmptyDocumentContent !== "function") {{
        return false;
      }}
      return editor.isDocumentProcessing() === false && editor.isEmptyDocumentContent() === false;
    }});
    if (editorReady) break;
    await page.waitForTimeout(500);
  }}
  if (!editorReady) {{
    throw new Error("SmartEditor readiness timeout");
  }}

  const editorVerification = await page.evaluate(() => {{
    const rendered = Array.from(document.querySelectorAll(".se-canvas .se-text-paragraph"))
      .map(el => el.innerText || "")
      .join("\\n");
    const actualLinks = Array.from(document.querySelectorAll(".se-canvas a[href], .se-canvas .se-link[data-href]"))
      .map(el => el.href || el.getAttribute("data-href"))
      .filter(Boolean);
    const btn = document.querySelector("#answerRegisterButton");
    return {{
      rendered,
      actualLinks,
      buttonReady: Boolean(btn && !btn.disabled)
    }};
  }});

  const norm = s => (s || "").replace(/\\u200b/g, "").replace(/\\s+/g, " ").trim();
  if (norm(editorVerification.rendered) !== norm({json.dumps(answer_text)})) {{
    retainSpace = true;
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "EditorMismatchError",
      message: "Editor did not retain the reviewed answer exactly"
    }}));
    return;
  }}
  const expectedUrls = {json.dumps(expected_urls)};
  if (expectedUrls.some(u => !editorVerification.actualLinks.includes(u))) {{
    retainSpace = true;
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "HyperlinkMissingError",
      message: "Reviewed outbound URL is not a clickable editor hyperlink"
    }}));
    return;
  }}
  if (!editorVerification.buttonReady) {{
    retainSpace = true;
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: false,
      errorType: "RegisterUnavailableError",
      message: "Registration is unavailable"
    }}));
    return;
  }}

  // Wait up to 4s for SmartEditor ONE to finish rendering the OG Card (.se-oglink),
  // then strip the duplicate raw URL text paragraph so ONLY the clean OG Card remains!
  for (let i = 0; i < 8; i++) {{
    const hasOgDom = await page.evaluate(() => document.querySelectorAll(".se-oglink, .se-module-oglink").length > 0);
    if (hasOgDom) break;
    await page.waitForTimeout(500);
  }}
  await page.evaluate(() => {{
    const ed = window.SmartEditor?.getEditor?.("kinpc001");
    if (!ed || typeof ed.getDocumentData !== "function" || typeof ed.setDocumentData !== "function") return;
    const data = ed.getDocumentData();
    const comps = data?.document?.components || [];
    const hasOg = comps.some(c => c["@ctype"] === "oglink");
    if (hasOg) {{
      for (const c of comps) {{
        if (c["@ctype"] === "text" && Array.isArray(c.value)) {{
          c.value = c.value.filter(p => {{
            const txt = (p.nodes || []).map(n => n.value || "").join("").trim();
            return !/^https?:\\/\\//i.test(txt);
          }});
        }}
      }}
      ed.setDocumentData(data);
    }}
  }});
  for (let i = 0; i < 25; i++) {{
    const postStripReady = await page.evaluate(() => {{
      const ed = window.SmartEditor?.getEditor?.("kinpc001");
      if (!ed || typeof ed.isDocumentProcessing !== "function" || typeof ed.isEmptyDocumentContent !== "function") return false;
      return ed.isDocumentProcessing() === false && ed.isEmptyDocumentContent() === false;
    }});
    if (postStripReady) break;
    await page.waitForTimeout(250);
  }}
  await page.waitForTimeout(300);

  // Install fetch/XHR interceptor for registerAnswerForSmartEditorOne.naver before clicking submit
  await page.evaluate(() => {{
    window.__barolabKinResponses = [];
    const origFetch = window.fetch;
    if (origFetch) {{
      window.fetch = async function(...args) {{
        const res = await origFetch.apply(this, args);
        try {{
          const u = String(args[0]?.url || args[0] || "");
          if (u.includes("/ajax/detail/registerAnswerForSmartEditorOne.naver")) {{
            const clone = res.clone();
            const data = await clone.json().catch(() => null);
            window.__barolabKinResponses.push({{ status: res.status, data }});
          }}
        }} catch (e) {{}}
        return res;
      }};
    }}
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {{
      this.__barolabUrl = String(url || "");
      return origOpen.call(this, method, url, ...rest);
    }};
    XMLHttpRequest.prototype.send = function(...args) {{
      if (this.__barolabUrl && this.__barolabUrl.includes("/ajax/detail/registerAnswerForSmartEditorOne.naver")) {{
        this.addEventListener("load", () => {{
          try {{
            const data = JSON.parse(this.responseText || "null");
            window.__barolabKinResponses.push({{ status: this.status, data }});
          }} catch (e) {{}}
        }});
      }}
      return origSend.apply(this, args);
    }};
  }});

  const clickRegisterBtn = async () => {{
    await page.evaluate(() => {{
      const area = document.querySelector("#answerButtonArea");
      if (area) area.style.display = "block";
      const btn = document.querySelector("#answerRegisterButton");
      if (btn) {{
        btn.scrollIntoView({{ block: "center" }});
        btn.click();
      }}
    }});
  }};
  await clickRegisterBtn();

  let finalHtml = "";
  let observedResponses = [];
  let postDialogs = [];
  for (let i = 0; i < 30; i++) {{
    await page.waitForTimeout(500);
    await page.dismissDialog().catch(() => {{}});
    const snap = await page.evaluate(() => {{
      const dialogs = [];
      for (const sel of ["#notAnswerableLayer", "#deferredExpertLayer", "[role=\\"dialog\\"]"]) {{
        for (const el of document.querySelectorAll(sel)) {{
          if (el.getClientRects().length > 0) {{
            const msg = (el.innerText || "").trim();
            if (msg) dialogs.push({{ type: "dom", message: msg.slice(0, 500) }});
          }}
        }}
      }}
      const btn = document.querySelector("#answerRegisterButton");
      return {{
        html: document.documentElement.outerHTML,
        responses: window.__barolabKinResponses || [],
        dialogs,
        editorPresent: document.querySelectorAll(".se-canvas").length > 0,
        registerVisible: Boolean(btn && btn.getClientRects().length > 0),
        registerEnabled: Boolean(btn && !btn.disabled)
      }};
    }});
    finalHtml = snap.html;
    observedResponses = snap.responses;
    postDialogs = snap.dialogs;
    if (i === 5 && snap.editorPresent && snap.registerEnabled && snap.dialogs.length === 0 && snap.responses.length === 0) {{
      await clickRegisterBtn();
    }}
    if (!snap.editorPresent && snap.html.includes("answer_") && snap.html.includes("loginUserId")) {{
      if (!snap.html.includes("_myAnswer")) {{
        await page.waitForTimeout(600);
        finalHtml = await page.evaluate(() => document.documentElement.outerHTML);
      }}
      break;
    }}
  }}

  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: true,
    account: {json.dumps(account)},
    profileId: {json.dumps(profile_id)},
    spaceId: task.spaceId,
    html: finalHtml,
    responses: observedResponses,
    dialogs: postDialogs
  }}));
}} finally {{
  // Keep persistent Space open inside the user's main EGO Lite browser sidebar
}}
"""
    return run_ego_mjs(script, timeout=90)


def create_naver_qr_short_url(
    account_or_port: str | int,
    target_url: str,
    *,
    title: str = "",
    post_key: str = "",
) -> str:
    """Convert an external bridge URL into a unique `https://m.site.naver.com/xxxx` Naver QR short URL.

    Uses Naver QR's official `POST https://qr-web.naver.com/code/createCode` API with
    `qrDirectLinkTypeCd: 29` so visitors are 302-redirected directly to `target_url` while
    Naver Blog's editor/crawler sees an internal `*.naver.com` domain (`m.site.naver.com`).
    Caches per `(account, post_key, target_url)` so retries of the same post reuse the same QR
    while every new post receives a fresh unique `m.site.naver.com` code.
    """
    raw_url = str(target_url or "").strip()
    if not raw_url.startswith(("http://", "https://")):
        return raw_url
    if "site.naver.com/" in raw_url or "qr.naver.com/" in raw_url:
        return raw_url

    # Append UTM parameters for GA4 bridge attribution if not already present
    final_url = raw_url
    if "utm_source=" not in final_url:
        sep = "&" if "?" in final_url else "?"
        final_url = f"{final_url}{sep}utm_source=naver_blog&utm_medium=qr_bridge"

    if isinstance(account_or_port, int) or (isinstance(account_or_port, str) and account_or_port.isdigit()):
        account = PORT_TO_ACCOUNT.get(int(account_or_port), "adinfo0905")
    else:
        account = str(account_or_port or "adinfo0905").strip()
    profile_id = resolve_ego_profile(account)
    space_name = f"barolab-naver-{account}"

    cache_path = Path(__file__).resolve().parents[1] / "data" / "naver" / "qr_links.json"
    cache_id = hashlib.sha1(f"{account}|{post_key or title}|{final_url}".encode("utf-8")).hexdigest()[:16]
    cache_data: dict = {}
    try:
        if cache_path.is_file():
            cache_data = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_entry = cache_data.get(cache_id)
            if isinstance(cached_entry, dict) and str(cached_entry.get("shortUrl", "")).startswith("https://m.site.naver.com/"):
                return str(cached_entry["shortUrl"])
    except Exception:
        cache_data = {}

    qr_title = (str(title or "상세 기준 확인표").split(",")[0].split("...")[0].strip() or "상세 기준 확인표")[:18]
    script = f"""
const spaceName = {json.dumps(space_name)};
const profileId = {json.dumps(profile_id)};
const qrTitle = {json.dumps(qr_title)};
const directLink = {json.dumps(final_url)};

const spaces = await listTaskSpaces();
const existing = Array.isArray(spaces) ? spaces.find(s => s && s.name === spaceName) : null;
const task = existing ? await taskSpace(existing.id) : await taskSpace(spaceName, {{ profileId }});
const pages = await task.pages();
const page = pages.length > 0 ? pages[0] : task.page("p1");

const curUrl = await page.url().catch(() => "");
if (!curUrl.startsWith("https://qr.naver.com")) {{
  await page.goto("https://qr.naver.com/create", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
}}

const apiRes = await page.evaluate(async ({{ qrTitle, directLink }}) => {{
  const payload = {{
    qrName: qrTitle,
    qrShape: 1,
    qrColorBorderCd: "#03C75A",
    infoType: "url",
    qrDirectLink: directLink,
    qrDirectLinkTypeCd: 29,
    sessions: [
      {{ orderId: 0, type: "Basic", attachment: {{ title: qrTitle, desc: "" }} }},
      {{ orderId: 1, type: "Link", attachment: {{ linkSubject: "" }}, attachments: [{{ linkUrl: directLink }}] }}
    ],
    qrSaveStatusCd: 79,
    isActive: true
  }};
  const r = await fetch("https://qr-web.naver.com/code/createCode", {{
    method: "POST",
    credentials: "include",
    headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify(payload)
  }});
  return await r.json();
}}, {{ qrTitle, directLink }});

console.log("BAROLAB_EGO_JSON:" + JSON.stringify(apiRes || {{}}));
"""
    try:
        res = run_ego_mjs(script, timeout=35)
        qr_code = str((res or {}).get("data") or "").strip()
        if (res or {}).get("code") == 1 and qr_code:
            short_url = f"https://m.site.naver.com/{qr_code}"
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_data[cache_id] = {
                    "account": account,
                    "title": qr_title,
                    "postKey": post_key or title,
                    "targetUrl": final_url,
                    "shortUrl": short_url,
                    "qrCode": qr_code,
                    "createdAt": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
                }
                cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
            return short_url
    except Exception as exc:
        logger.warning("Failed to create Naver QR short URL for %s: %s", final_url, exc)
    return raw_url


def native_publish_naver_cafe_article(
    account: str,
    clubid: str,
    menuid: str,
    title: str,
    paragraphs: list[str],
    cafe_slug: str = "",
) -> dict:
    """Publish a public (전체공개 + 검색허용) Naver Cafe bridge article inside EGO Lite TaskSpace."""
    profile_id = resolve_ego_profile(account)
    space_name = f"barolab-{account}"
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === {json.dumps(space_name)}) : null;
const task = found ? await taskSpace(found.id) : await taskSpace({json.dumps(space_name)}, {{ profileId: {json.dumps(profile_id)} }});
const page = task.page("p1");
const prevUrl = await page.url().catch(() => "");
try {{
  const writeUrl = "https://cafe.naver.com/ca-fe/cafes/" + {json.dumps(str(clubid))} + "/menus/" + {json.dumps(str(menuid))} + "/articles/write?boardType=L";
  await page.goto(writeUrl, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  await page.waitForTimeout(3500);

  await page.click("textarea.textarea_input");
  await page.keyboard.insertText({json.dumps(title)});
  await page.waitForTimeout(400);

  await page.click(".se-text-paragraph");
  await page.waitForTimeout(250);
  const paras = {json.dumps(paragraphs)};
  const fullBody = paras.filter(Boolean).map(p => String(p).trim()).join("\\n\\n");
  await page.keyboard.insertText(fullBody);
  await page.waitForTimeout(1200);

  await page.evaluate(() => {{
    window.alert = () => {{}};
    window.confirm = () => true;
    const btn = document.querySelector("a.BaseButton--skinGreen");
    if (btn) btn.click();
  }});
  await page.waitForTimeout(5500);
  const finalUrl = await page.url();
  const pageTitle = await page.title().catch(() => "");
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: !finalUrl.includes("/articles/write"),
    account: {json.dumps(account)},
    cafeSlug: {json.dumps(cafe_slug)},
    clubid: {json.dumps(str(clubid))},
    menuid: {json.dumps(str(menuid))},
    url: finalUrl,
    title: {json.dumps(title)},
    pageTitle
  }}));
}} catch (err) {{
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: false,
    error: String(err),
    account: {json.dumps(account)},
    clubid: {json.dumps(str(clubid))}
  }}));
}} finally {{
  if (prevUrl && !prevUrl.includes("cafe.naver.com")) {{
    await page.goto(prevUrl, {{ waitUntil: "domcontentloaded", timeout: 12000 }}).catch(() => {{}});
  }}
}}
"""
    return run_ego_mjs(script, timeout=90)


def native_sync_brunch_state(uid: str = "", upw: str = "") -> dict:
    """Sync Kakao Brunch writer state, drawer drafts, and published articles via EGO Lite `barolab-soultin`."""
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === "barolab-soultin") : null;
const task = found ? await taskSpace(found.id) : await taskSpace("barolab-soultin", {{ profileId: "Profile 3" }});
const page = task.page("p1");
const prevUrl = await page.url().catch(() => "");
try {{
  await page.goto("https://brunch.co.kr/ready", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
  await page.waitForTimeout(1800);
  let cur = await page.url();
  if ((cur.includes("signin") || cur.includes("accounts.kakao.com")) && {json.dumps(bool(uid and upw))}) {{
    await page.goto("https://brunch.co.kr/auth/kakao?url=%2Fsignin%2Ffinish%3Furl%3D%252Fready", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
    await page.waitForTimeout(2200);
    cur = await page.url();
    if (cur.includes("accounts.kakao.com")) {{
      await page.click("input[name=loginId]").catch(() => {{}});
      await page.keyboard.insertText({json.dumps(uid)});
      await page.waitForTimeout(250);
      await page.click("input[name=password]").catch(() => {{}});
      await page.keyboard.insertText({json.dumps(upw)});
      await page.waitForTimeout(250);
      await page.evaluate(() => {{
        const chk = document.querySelector("input[name=saveSignedIn]");
        if (chk && !chk.checked) chk.click();
        const btn = document.querySelector("button[type=submit]");
        if (btn) btn.click();
      }});
      await page.waitForTimeout(4000);
      await page.goto("https://brunch.co.kr/ready", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
      await page.waitForTimeout(1500);
    }}
  }}
  const loggedIn = !(await page.url()).includes("signin") && !(await page.url()).includes("accounts.kakao.com");
  let rawDrawer = [];
  let rawPub = [];
  let canPublishLive = true;
  if (loggedIn) {{
    rawDrawer = await page.evaluate(() => {{
      const items = [];
      document.querySelectorAll("li").forEach(li => {{
        const a = li.querySelector("a[href*='/@31d1f5fb288c4fc/']");
        if (!a) return;
        const href = a.getAttribute("href") || "";
        if (href.includes("/stats") || href.includes("/following")) return;
        const lines = (li.innerText || "").split("\\n").map(s => s.trim()).filter(Boolean);
        if (!lines.length) return;
        items.push({{
          title: lines[0],
          excerpt: lines.slice(1, -1).join(" ").slice(0, 160),
          href: href.startsWith("http") ? href : "https://brunch.co.kr" + href,
          savedAtLabel: lines[lines.length - 1] || "저장됨"
        }});
      }});
      return items;
    }}).catch(() => []);

    await page.goto("https://brunch.co.kr/@31d1f5fb288c4fc?tab=articles", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
    await page.waitForTimeout(2200);
    rawPub = await page.evaluate(() => {{
      const items = [];
      document.querySelectorAll("a[href*='/@31d1f5fb288c4fc/']").forEach(a => {{
        const href = a.getAttribute("href") || "";
        if (!/\\/@31d1f5fb288c4fc\\/\\d+$/.test(href)) return;
        const container = a.closest("li") || a;
        const lines = (container.innerText || "").split("\\n").map(s => s.trim()).filter(Boolean);
        if (!lines.length) return;
        items.push({{
          title: lines[0],
          excerpt: lines.slice(1).join(" ").slice(0, 160),
          href: href.startsWith("http") ? href : "https://brunch.co.kr" + href
        }});
      }});
      return items;
    }}).catch(() => []);
  }}
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: true,
    cdpOnline: true,
    loggedIn,
    canPublishLive,
    rawDrawer,
    rawPub
  }}));
}} catch (err) {{
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{ ok: false, error: String(err) }}));
}} finally {{
  if (prevUrl && !prevUrl.includes("brunch.co.kr")) {{
    await page.goto(prevUrl, {{ waitUntil: "domcontentloaded", timeout: 12000 }}).catch(() => {{}});
  }}
}}
"""
    return run_ego_mjs(script, timeout=55)


def native_publish_brunch_column(
    title: str,
    subtitle: str,
    paragraphs: list[str],
    bridge_url: str | None = None,
    auto_publish: bool = True,
    edit_url: str | None = None,
    uid: str = "",
    upw: str = "",
) -> dict:
    """Write or update a Brunch column natively inside EGO Lite `barolab-soultin` TaskSpace."""
    target_write_url = edit_url or "https://brunch.co.kr/write"
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === "barolab-soultin") : null;
const task = found ? await taskSpace(found.id) : await taskSpace("barolab-soultin", {{ profileId: "Profile 3" }});
const page = task.page("p1");
const prevUrl = await page.url().catch(() => "");
try {{
  await page.goto({json.dumps(target_write_url)}, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  await page.waitForTimeout(2200);
  let cur = await page.url();
  if ((cur.includes("signin") || cur.includes("accounts.kakao.com")) && {json.dumps(bool(uid and upw))}) {{
    await page.goto("https://brunch.co.kr/auth/kakao?url=%2Fsignin%2Ffinish%3Furl%3D%252Fready", {{ waitUntil: "domcontentloaded", timeout: 20000 }});
    await page.waitForTimeout(2200);
    if ((await page.url()).includes("accounts.kakao.com")) {{
      await page.click("input[name=loginId]").catch(() => {{}});
      await page.keyboard.insertText({json.dumps(uid)});
      await page.waitForTimeout(250);
      await page.click("input[name=password]").catch(() => {{}});
      await page.keyboard.insertText({json.dumps(upw)});
      await page.waitForTimeout(250);
      await page.evaluate(() => {{
        const chk = document.querySelector("input[name=saveSignedIn]");
        if (chk && !chk.checked) chk.click();
        const btn = document.querySelector("button[type=submit]");
        if (btn) btn.click();
      }});
      await page.waitForTimeout(4000);
      await page.goto({json.dumps(target_write_url)}, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
      await page.waitForTimeout(2200);
    }}
  }}
  const hasEditor = await page.evaluate(() => !!document.querySelector("h1.cover_title"));
  if (!hasEditor) {{
    await page.goto("https://brunch.co.kr/write", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
    await page.waitForTimeout(2200);
  }}
  await page.evaluate(() => {{
    window.alert = () => {{}};
    window.confirm = () => true;
    const g = document.querySelector("button.guide_close");
    if (g) g.click();
  }}).catch(() => {{}});
  await page.waitForTimeout(300);

  await page.click("h1.cover_title");
  await page.keyboard.press("Control+A");
  await page.keyboard.press("Backspace");
  await page.keyboard.insertText({json.dumps(title)});
  await page.waitForTimeout(250);

  await page.click("div.cover_sub_title");
  await page.keyboard.press("Control+A");
  await page.keyboard.press("Backspace");
  await page.keyboard.insertText({json.dumps(subtitle)});
  await page.waitForTimeout(250);

  await page.click("div.wrap_body");
  await page.keyboard.press("Control+A");
  await page.keyboard.press("Backspace");
  await page.waitForTimeout(250);

  const paras = {json.dumps(paragraphs)};
  for (let i = 0; i < paras.length; i++) {{
    await page.keyboard.insertText(String(paras[i] || "").trim());
    if (i < paras.length - 1) {{
      await page.keyboard.press("Enter");
      await page.keyboard.press("Enter");
    }}
    await page.waitForTimeout(120);
  }}

  const canPublish = await page.evaluate(() => !!document.querySelector("button.be_header_button_publish"));
  const bUrl = {json.dumps(bridge_url or "")};
  if (canPublish && bUrl) {{
    await page.keyboard.press("Enter");
    await page.keyboard.press("Enter");
    await page.keyboard.insertText("▶ 관련 실무 기준표 및 3분 자가진단 원문 보기:");
    await page.keyboard.press("Enter");
    await page.keyboard.insertText(bUrl);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(1800);
  }}

  if (canPublish && {json.dumps(bool(auto_publish))}) {{
    await page.click("button.be_header_button_publish");
    await page.waitForTimeout(1800);
    await page.evaluate(() => {{
      const selected = document.querySelectorAll("button.keyword.selected").length;
      if (selected < 3) {{
        const unsel = Array.from(document.querySelectorAll("button.keyword:not(.selected)"));
        for (let i = 0; i < Math.min(3 - selected, unsel.length); i++) {{
          unsel[i].click();
        }}
      }}
    }});
    await page.waitForTimeout(600);
    await page.click("button.save.button.mint");
    await page.waitForTimeout(4500);
    const finalUrl = await page.url();
    console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
      ok: true,
      mode: "published",
      writerApproved: true,
      url: finalUrl,
      title: {json.dumps(title)}
    }}));
    return;
  }}

  await page.click("button.btn_article_save_draft, button.be_header_button_save").catch(() => {{}});
  await page.waitForTimeout(2000);
  const finalUrl = await page.url();

  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: true,
    mode: "saved_to_drawer",
    writerApproved: canPublish,
    url: finalUrl,
    title: {json.dumps(title)}
  }}));
}} catch (err) {{
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{ ok: false, error: String(err) }}));
}} finally {{
  if (prevUrl && !prevUrl.includes("brunch.co.kr")) {{
    await page.goto(prevUrl, {{ waitUntil: "domcontentloaded", timeout: 12000 }}).catch(() => {{}});
  }}
}}
"""
    return run_ego_mjs(script, timeout=65)


def native_check_naver_premium_status() -> dict:
    """Check real-time Naver Premium Contents studio approval state on `barolab-yoon_master`."""
    script = """
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === "barolab-yoon_master") : null;
const task = found ? await taskSpace(found.id) : await taskSpace("barolab-yoon_master", { profileId: "Profile 5" });
const page = task.page("p1");
const prevUrl = await page.url().catch(() => "");
try {
  await page.goto("https://studio.premium.naver.com/home", { waitUntil: "domcontentloaded", timeout: 20000 });
  await page.waitForTimeout(2800);
  const url = await page.url();
  const bodyText = await page.evaluate(() => (document.body ? document.body.innerText : "").slice(0, 1200).replace(/\\s+/g, " ")).catch(() => "");
  const underReview = url.includes("/join/review") || bodyText.includes("가입 심사가 진행 중입니다");
  const approved = url.includes("/home") && !underReview && !url.includes("/intro") && !url.includes("nid.naver.com");
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({
    ok: true,
    account: "yoon_master",
    channelId: "baronotebrief",
    channelName: "머스트픽 연금 자산 연구소",
    url,
    underReview,
    approved,
    status: approved ? "approved" : (underReview ? "under_review" : "pending"),
    statusLabel: approved ? "🟢 심사 승인 완료 (스튜디오 즉시 발행 가능)" : "⏳ 판매회원 가입 심사 진행 중 (영업일 3~5일 소요)",
    snippet: bodyText.slice(0, 300)
  }));
} catch (err) {
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({ ok: false, error: String(err) }));
} finally {
  if (prevUrl && !prevUrl.includes("studio.premium.naver.com")) {
    await page.goto(prevUrl, { waitUntil: "domcontentloaded", timeout: 12000 }).catch(() => {});
  }
}
"""
    return run_ego_mjs(script, timeout=45)


def native_sync_youtube_channels() -> dict:
    """Sync live 3-channel status under baro76650@gmail.com (`@yoon_autolab`, `@숨은지원금`, `@바로랭크`) in `barolab-soultin`."""
    script = """
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === "barolab-soultin") : null;
const task = found ? await taskSpace(found.id) : await taskSpace("barolab-soultin", { profileId: "Profile 3" });
const page = task.page("p1");
const prevUrl = await page.url().catch(() => "");
try {
  await page.goto("https://www.youtube.com/@yoon_autolab/posts", { waitUntil: "domcontentloaded", timeout: 22000 });
  await page.waitForTimeout(3000);
  // Open top-right avatar menu -> Switch account -> select @yoon_autolab if composer not yet active
  let hasComposerNow = await page.evaluate(() => !!document.querySelector("ytd-backstage-post-dialog-renderer"));
  let switcherData = { switched: hasComposerNow };
  if (!hasComposerNow) {
    await page.evaluate(() => {
      const av = document.querySelector("#avatar-btn, button#avatar-btn");
      if (av) av.click();
    });
    await page.waitForTimeout(1800);
    await page.evaluate(() => {
      const links = Array.from(document.querySelectorAll("ytd-compact-link-renderer, tp-yt-paper-item, a"));
      const sw = links.find(el => (el.innerText || "").includes("계정 전환") || (el.innerText || "").includes("Switch account"));
      if (sw) sw.click();
    });
    await page.waitForTimeout(2500);
    switcherData = await page.evaluate((targetHandle) => {
      const items = Array.from(document.querySelectorAll("ytd-account-item-renderer, tp-yt-paper-icon-item"));
      const match = items.find(el => (el.innerText || "").includes(targetHandle) || (el.innerText || "").includes("윤랩 자동화 연구소"));
      if (match) {
        const clickable = match.querySelector("tp-yt-paper-icon-item") || match;
        clickable.click();
        return { switched: true, matchedText: (match.innerText || "").replace(/\\s+/g, " ").trim().slice(0, 100) };
      }
      return { switched: false, count: items.length };
    }, "@yoon_autolab");
    if (switcherData.switched) {
      await page.waitForTimeout(4200);
      await page.goto("https://www.youtube.com/@yoon_autolab/posts", { waitUntil: "domcontentloaded", timeout: 22000 });
      await page.waitForTimeout(3500);
    }
  }
  const postsInfo = await page.evaluate(() => {
    const postEls = Array.from(document.querySelectorAll("ytd-backstage-post-thread-renderer"));
    const posts = postEls.slice(0, 6).map(el => {
      const contentEl = el.querySelector("#content-text");
      const timeEl = el.querySelector("#published-time-text a");
      return {
        text: contentEl ? (contentEl.innerText || "").trim().slice(0, 260) : "",
        time: timeEl ? (timeEl.innerText || "").trim() : "",
        url: timeEl && timeEl.href ? timeEl.href : "https://www.youtube.com/@yoon_autolab/posts"
      };
    }).filter(p => p.text);
    const hasComposer = !!document.querySelector("ytd-backstage-post-dialog-renderer");
    const pageText = (document.body ? document.body.innerText : "").slice(0, 600).replace(/\\s+/g, " ");
    return { posts, hasComposer, url: location.href, pageText };
  });
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({
    ok: true,
    cdpOnline: true,
    accountEmail: "baro76650@gmail.com",
    switchedToMain: switcherData.switched,
    switcherData,
    mainChannelPosts: postsInfo.posts || [],
    hasComposer: postsInfo.hasComposer,
    pageText: postsInfo.pageText
  }));
} catch (err) {
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({ ok: false, error: String(err) }));
} finally {
  if (prevUrl && !prevUrl.includes("youtube.com")) {
    await page.goto(prevUrl, { waitUntil: "domcontentloaded", timeout: 12000 }).catch(() => {});
  }
}
"""
    return run_ego_mjs(script, timeout=55)


def native_publish_youtube_community_post(channel_handle: str, post_text: str) -> dict:
    """Publish a live Community Post (`게시물`) on the specified YouTube channel (`@yoon_autolab` or `@바로랭크`) via EGO Lite."""
    script = f"""
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === "barolab-soultin") : null;
const task = found ? await taskSpace(found.id) : await taskSpace("barolab-soultin", {{ profileId: "Profile 3" }});
const page = task.page("p1");
const prevUrl = await page.url().catch(() => "");
try {{
  await page.goto("https://www.youtube.com/" + {json.dumps(channel_handle)} + "/posts", {{ waitUntil: "domcontentloaded", timeout: 22000 }});
  await page.waitForTimeout(3200);
  const alreadyOwner = await page.evaluate(() => !!document.querySelector("ytd-backstage-post-dialog-renderer"));
  if (!alreadyOwner) {{
    await page.evaluate(() => {{
      const av = document.querySelector("#avatar-btn, button#avatar-btn");
      if (av) av.click();
    }});
    await page.waitForTimeout(1800);
    await page.evaluate(() => {{
      const links = Array.from(document.querySelectorAll("ytd-compact-link-renderer, tp-yt-paper-item, a"));
      const sw = links.find(el => (el.innerText || "").includes("계정 전환") || (el.innerText || "").includes("Switch account"));
      if (sw) sw.click();
    }});
    await page.waitForTimeout(2500);
    await page.evaluate((targetHandle) => {{
      const items = Array.from(document.querySelectorAll("ytd-account-item-renderer, tp-yt-paper-icon-item"));
      const match = items.find(el => (el.innerText || "").includes(targetHandle) || (el.innerText || "").includes("윤랩 자동화 연구소"));
      if (match) {{
        const clickable = match.querySelector("tp-yt-paper-icon-item") || match;
        clickable.click();
      }}
    }}, {json.dumps(channel_handle)});
    await page.waitForTimeout(4200);
    await page.goto("https://www.youtube.com/" + {json.dumps(channel_handle)} + "/posts", {{ waitUntil: "domcontentloaded", timeout: 22000 }});
    await page.waitForTimeout(3500);
  }}

  // Open community post box on @yoon_autolab/posts (or via Topbar Create -> 게시물 작성)
  await page.evaluate(() => {{
    const createBtn = Array.from(document.querySelectorAll("button, yt-icon-button")).find(b => {{
      const t = (b.innerText || b.getAttribute("aria-label") || "").trim();
      return t === "만들기" || t === "Create";
    }});
    if (createBtn) createBtn.click();
  }});
  await page.waitForTimeout(1200);
  await page.evaluate(() => {{
    const items = Array.from(document.querySelectorAll("ytd-compact-link-renderer, tp-yt-paper-item, a"));
    const postItem = items.find(el => (el.innerText || "").includes("게시물") || (el.innerText || "").includes("Create post"));
    if (postItem) postItem.click();
  }});
  await page.waitForTimeout(2500);
  // Click any visible simplebox-placeholder or contenteditable-root
  await page.evaluate(() => {{
    const placeholders = Array.from(document.querySelectorAll("#simplebox-placeholder, #placeholder-area"));
    for (const p of placeholders) {{
      if (p.offsetParent !== null) {{ p.click(); break; }}
    }}
  }});
  await page.waitForTimeout(1000);
  const focused = await page.evaluate(() => {{
    const eds = Array.from(document.querySelectorAll("#contenteditable-root[contenteditable='true'], div#contenteditable-root"));
    const visibleEd = eds.find(e => e.offsetParent !== null) || eds[0];
    if (!visibleEd) return false;
    visibleEd.click();
    visibleEd.focus();
    return true;
  }});
  await page.waitForTimeout(500);
  await page.keyboard.insertText({json.dumps(post_text)});
  await page.keyboard.press("Enter");
  await page.waitForTimeout(2000);
  const clickInfo = await page.evaluate(() => {{
    const btns = Array.from(document.querySelectorAll("#submit-button button, button[aria-label='게시'], button"));
    const postBtn = btns.find(b => {{
      const t = (b.innerText || b.getAttribute("aria-label") || "").trim();
      return (t === "게시" || t === "Post") && !b.disabled && b.getAttribute("aria-disabled") !== "true" && b.offsetParent !== null;
    }});
    if (postBtn) {{
      postBtn.click();
      return {{ clicked: true, label: (postBtn.innerText || postBtn.getAttribute("aria-label") || "게시").trim() }};
    }}
    return {{ clicked: false }};
  }});
  await page.waitForTimeout(4500);
  const latestPost = await page.evaluate(() => {{
    const posts = Array.from(document.querySelectorAll("ytd-backstage-post-thread-renderer")).map(el => {{
      const contentEl = el.querySelector("#content-text");
      const timeEl = el.querySelector("#published-time-text a");
      return {{
        text: contentEl ? (contentEl.innerText || "").trim().slice(0, 260) : "",
        time: timeEl ? (timeEl.innerText || "").trim() : "방금 전",
        url: timeEl && timeEl.href ? timeEl.href : location.href
      }};
    }}).filter(p => p.text);
    return posts[0] || null;
  }});
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: Boolean(clickInfo.clicked),
    clickInfo,
    channelHandle: {json.dumps(channel_handle)},
    post: latestPost,
    url: latestPost && latestPost.url ? latestPost.url : ("https://www.youtube.com/" + {json.dumps(channel_handle)} + "/posts")
  }}));
}} catch (err) {{
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{ ok: false, error: String(err) }}));
}} finally {{
  if (prevUrl && !prevUrl.includes("youtube.com")) {{
    await page.goto(prevUrl, {{ waitUntil: "domcontentloaded", timeout: 12000 }}).catch(() => {{}});
  }}
}}
"""
    return run_ego_mjs(script, timeout=65)




