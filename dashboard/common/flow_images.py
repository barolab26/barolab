"""One serialized Flow image with durable submission/download provenance."""
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import re
import time
from pathlib import Path

from common.collection_observability import load, write, stamp


def hold_editorial_images(folder, reason):
    """Persist an actionable hold without modifying the draft or submission receipt."""
    write(Path(folder) / 'image-preparation-status.json', {
        'status': 'held', 'reason': str(reason), 'updatedAt': stamp(),
        'action': 'Review real browser sources and reprepare images in an unsubmitted draft; preserve submitted receipts.',
    })
    raise ValueError('editorial_images_held: ' + str(reason))


def require_editorial_images(title, sections, folder, *, channel, existing=None, sources=None):
    """The shared browser engine is the only authority for evidence image readiness."""
    try:
        from common.editorial_images import build_editorial_assets, validate_editorial_assets
    except ImportError:
        hold_editorial_images(folder, 'browser_capture_engine_unavailable; install the shared engine before repreparing')
    if existing is None:
        try:
            existing = build_editorial_assets(title, sections, folder, sources=sources, channel=channel)
        except Exception as exc:
            hold_editorial_images(folder, 'browser_capture_failed: ' + str(exc))
    if not isinstance(existing, dict) or existing.get('status') != 'ready':
        hold_editorial_images(folder, (existing or {}).get('reasons') or 'browser_capture_missing_or_failed; reprepare required')
    try:
        valid = validate_editorial_assets(title, sections, folder, existing, channel=channel)
    except Exception:
        valid = False
    if not valid:
        hold_editorial_images(folder, 'browser_capture_stale_or_mismatched; reprepare and review exact document sections')
    return existing


def _ensure_english_scene(custom_prompt, title='', summary=''):
    text = (custom_prompt or '').strip()
    # Strip Korean characters if mixed, or if custom_prompt is mostly English keep it clean
    english_only = re.sub(r'[가-힣ㄱ-ㅎㅏ-ㅣ]+', ' ', text)
    english_only = re.sub(r'\s+', ' ', english_only).strip(' ,.-;:')
    if len(english_only) >= 25:
        return english_only[:800]
    # Fallback when manuscript did not supply a sufficient English prompt
    try:
        from common.llm_client import generate_text
        translated = generate_text(
            'Write ONLY one concise, vivid English photography prompt (2-3 sentences, no Korean, no markdown, no quotes) '
            'for a high-resolution editorial photograph set in modern South Korea matching this Korean article topic and summary. '
            'If a person appears, they MUST be an East Asian / Korean person in a realistic Korean apartment, Korean hospital/pharmacy, or Korean office setting. '
            'If medicine is shown, use Korean-style paper pharmacy envelopes or blister packs—NEVER Western/US orange prescription pill bottles. '
            'Describe realistic lighting, environment, objects, and atmosphere without any text, letters, logos, or screens.\n'
            f'Title: {title[:160]}\nSummary: {summary[:400]}\nDraft prompt: {text[:300]}',
            agent_slot='synapse',
            timeout_seconds=30,
            reasoning_effort='low',
        )
        cleaned = re.sub(r'[가-힣ㄱ-ㅎㅏ-ㅣ]+', ' ', str(translated or '')).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned).strip(' "\'')
        if len(cleaned) >= 20:
            return cleaned[:800]
    except Exception:
        pass
    return (
        'An authentic modern South Korean lifestyle and home office scene featuring a Korean adult at a clean wooden desk '
        'in a bright Korean apartment living room, natural daylight streaming through a window, a warm cup of coffee, and a minimal notebook, '
        'captured in high-resolution editorial photography with shallow depth of field.'
    )


def image_prompt(title, summary, custom_prompt=None):
    scene = _ensure_english_scene(custom_prompt, title=title, summary=summary)
    return (
        'High-resolution editorial photography set in modern South Korea, realistic natural lighting, 35mm lens, shallow depth of field (do not generate video). '
        'Mandatory localization: any person shown MUST be Korean (East Asian appearance) in an authentic Korean apartment, Korean clinic/pharmacy, or Korean office environment; '
        'never depict Western/Caucasian models, foreign currency, or US-style orange plastic prescription pill bottles. '
        'Strictly no text, no letters, no numbers, no logos, no watermarks, and no readable document or UI screens inside the image. '
        'Scene direction: ' + scene
    )


async def prepare_fresh_project_page(context, prior):
    """Always navigate to Flow main page, refresh, and click 'New project' unless reconciling an in-flight submission."""
    usable = [p for p in context.pages if p.url in ('about:blank', 'chrome://newtab/') or p.url.startswith('http')]
    home = next((p for p in usable if p.url.startswith('https://flow.google.com')), None)
    if home is None:
        home = usable[0] if usable else await context.new_page()
    for extra in list(context.pages):
        if extra is not home and extra.url.startswith('https://flow.google.com/project/'):
            try:
                await extra.close()
            except Exception:
                pass
    if prior and prior.get('status') == 'submission_started' and re.fullmatch(r'https://flow\.google\.com/project/[A-Za-z0-9-]+', prior.get('projectUrl', '')):
        target = prior['projectUrl']
        if home.url != target:
            await home.goto(target, wait_until='domcontentloaded', timeout=30000)
        await home.locator('div.ProseMirror').wait_for(state='visible', timeout=30000)
        return home

    await home.goto('https://flow.google.com/', wait_until='domcontentloaded', timeout=30000)
    await asyncio.sleep(1)
    await home.reload(wait_until='domcontentloaded', timeout=30000)
    await asyncio.sleep(2)

    for banner_sel in ('button.glue-cookie-notification-bar__accept', 'button.promotion-banner-close-button'):
        try:
            btn = home.locator(banner_sel).first
            if await btn.is_visible():
                await btn.click(timeout=2000)
        except Exception:
            pass

    new_btn = home.locator('button.new-project-button').first
    if not await new_btn.count():
        new_btn = home.get_by_role('button', name=re.compile(r'(새 프로젝트|New project)', re.I)).first
    await new_btn.wait_for(state='visible', timeout=15000)
    await new_btn.click(timeout=10000)

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if re.fullmatch(r'https://flow\.google\.com/project/[A-Za-z0-9-]+', home.url):
            break
        await asyncio.sleep(0.5)
    await home.locator('div.ProseMirror').wait_for(state='visible', timeout=30000)
    return home


def _evidence_path(folder: Path, filename: str) -> Path:
    if filename == 'flow-hero.png':
        return folder / 'flow-generation.json'
    return folder / f'flow-generation-{Path(filename).stem}.json'


def _generate_via_ego_flow(prompt: str, digest: str, output: Path, evidence_file: Path) -> Path:
    import base64
    import json
    from PIL import Image
    from common.ego_taskspace import run_ego_mjs

    script = f"""
const promptText = {json.dumps(prompt)};
const existing = await listTaskSpaces();
const found = Array.isArray(existing) ? existing.find(s => s && s.name === "barolab-cf-flow") : null;
const task = found ? await taskSpace(found.id) : await taskSpace("barolab-cf-flow", {{ profileId: "Profile 3" }});
const page = task.page("p1");
let curUrl = await page.url().catch(() => "");
if (!curUrl.startsWith("https://flow.google.com/project/")) {{
  if (!curUrl.startsWith("https://flow.google.com")) {{
    await page.goto("https://flow.google.com/", {{ waitUntil: "domcontentloaded", timeout: 25000 }});
    await page.waitForTimeout(2500);
  }}
  const projHref = await page.evaluate(() => {{
    const a = document.querySelector("a.project-thumbnail-container[href*='/project/']");
    return a ? a.href : "";
  }});
  if (projHref) {{
    await page.goto(projHref, {{ waitUntil: "domcontentloaded", timeout: 25000 }});
  }} else {{
    await page.evaluate(() => {{
      const btn = document.querySelector("button.new-project-button");
      if (btn) btn.click();
    }});
  }}
  for (let w = 0; w < 25; w++) {{
    await page.waitForTimeout(1000);
    const hasEd = await page.evaluate(() => !!document.querySelector("div.ProseMirror"));
    if (hasEd) break;
  }}
}}
await page.waitForTimeout(2200);
await page.evaluate(() => {{
  window.__barolabInitialImgs = Array.from(document.querySelectorAll("img"))
    .map(x => x.currentSrc || x.src)
    .filter(Boolean);
}});
await page.click("div.ProseMirror");
await page.keyboard.press("Control+A");
await page.keyboard.press("Backspace");
await page.waitForTimeout(250);
await page.keyboard.insertText(promptText);
await page.waitForTimeout(600);
let clicked = false;
try {{
  await page.click("button[aria-label='생성 시작']");
  clicked = true;
}} catch (e) {{
  clicked = await page.evaluate(() => {{
    const btns = Array.from(document.querySelectorAll("button"));
    const btn = btns.find(b => b.getAttribute("aria-label") === "생성 시작" || (b.innerText || "").includes("arrow_forward"));
    if (btn && !btn.disabled) {{
      btn.click();
      return true;
    }}
    return false;
  }});
}}
if (!clicked) {{
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{ ok: false, error: "Flow generate button not enabled" }}));
}} else {{
  let dataUrl = null;
  let freshUrl = null;
  for (let i = 0; i < 40; i++) {{
    await page.waitForTimeout(2000);
    const res = await page.evaluate(async () => {{
      const initList = window.__barolabInitialImgs || [];
      const imgs = Array.from(document.querySelectorAll("img")).filter(
        x => x.complete && x.naturalWidth >= 256 && x.naturalHeight >= 256 && !(x.currentSrc || x.src || "").includes("zero_states/")
      );
      const fresh = imgs.find(x => !initList.includes(x.currentSrc || x.src));
      if (!fresh) return null;
      const src = fresh.currentSrc || fresh.src;
      try {{
        const r = await fetch(src, {{ credentials: "include" }});
        const blob = await r.blob();
        const b64 = await new Promise((resolve) => {{
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result);
          reader.readAsDataURL(blob);
        }});
        return {{ src, b64 }};
      }} catch (e) {{
        try {{
          const c = document.createElement("canvas");
          c.width = fresh.naturalWidth;
          c.height = fresh.naturalHeight;
          c.getContext("2d").drawImage(fresh, 0, 0);
          return {{ src, b64: c.toDataURL("image/png") }};
        }} catch (e2) {{
          return null;
        }}
      }}
    }});
    if (res && res.b64) {{
      freshUrl = res.src;
      dataUrl = res.b64;
      break;
    }}
  }}
  console.log("BAROLAB_EGO_JSON:" + JSON.stringify({{
    ok: !!dataUrl,
    projectUrl: await page.url(),
    freshUrl,
    dataUrl
  }}));
}}
"""
    res = run_ego_mjs(script, timeout=110)
    if not (res or {}).get("ok") or not res.get("dataUrl"):
        raise RuntimeError(f"EGO Flow generation failed: {(res or {}).get('error') or 'timeout'}")
    b64_part = res["dataUrl"].split(",", 1)[-1]
    raw = base64.b64decode(b64_part)
    with Image.open(io.BytesIO(raw)) as image:
        if min(image.size) < 256:
            raise RuntimeError("Flow result is a thumbnail")
        output.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(output, format="PNG")
        dimensions = list(image.size)
    receipt = {
        "status": "downloaded",
        "mode": "google_flow_ego_taskspace",
        "projectUrl": res.get("projectUrl", "https://flow.google.com/"),
        "promptSha256": digest,
        "completedAt": stamp(),
        "dimensions": dimensions,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    write(evidence_file, receipt)
    return output


def _generate_via_openai_api(prompt: str, digest: str, output: Path, evidence_file: Path) -> Path:
    import base64
    import requests
    from dotenv import dotenv_values
    from PIL import Image

    env = dotenv_values(Path(__file__).resolve().parents[2] / '.env')
    last_err = None
    for key_name in ('OPENAI_API_KEY_JUSTINCOME', 'OPENAI_API_KEY_MAKE'):
        api_key = (env.get(key_name) or '').strip()
        if not api_key:
            continue
        for model in ('gpt-image-2.5-flare', 'gpt-image-2.5-sunburst', 'gpt-image-2', 'gpt-image-1.5', 'chatgpt-image-latest'):
            try:
                resp = requests.post(
                    'https://api.openai.com/v1/images/generations',
                    headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                    json={'model': model, 'prompt': prompt, 'n': 1, 'size': '1024x1024'},
                    timeout=60,
                )
                if resp.status_code != 200:
                    last_err = f'{model} HTTP {resp.status_code}'
                    continue
                item = (resp.json().get('data') or [{}])[0]
                raw = base64.b64decode(item['b64_json']) if item.get('b64_json') else requests.get(item['url'], timeout=30).content
                with Image.open(io.BytesIO(raw)) as image:
                    if min(image.size) < 256:
                        raise RuntimeError('Generated image is too small')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    image.convert('RGB').save(output, format='PNG')
                    dimensions = list(image.size)
                receipt = {
                    'status': 'downloaded',
                    'mode': 'editorial_image_api',
                    'model': model,
                    'promptSha256': digest,
                    'completedAt': stamp(),
                    'dimensions': dimensions,
                    'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                }
                write(evidence_file, receipt)
                return output
            except Exception as exc:
                last_err = str(exc)
    raise RuntimeError(f'Image generation failed: {last_err}')


async def capture_research_evidence(folder, filename='flow-hero.png', source_index=0):
    """Capture a clean screenshot of the verified research source when evidence capture is requested."""
    from playwright.async_api import async_playwright
    from common.ubuntu_naver_browser import EGO_BINARY
    from PIL import Image
    folder = Path(folder)
    research_data = load(folder / 'research.json')
    sources = [s for s in (research_data.get('sources') or []) if isinstance(s, dict) and s.get('url')]
    if not sources:
        raise RuntimeError('No verified research source URL available to capture')
    target_url = sources[min(max(0, int(source_index)), len(sources) - 1)]['url']
    output = folder / 'images' / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    launch_kwargs = {'headless': True}
    if EGO_BINARY and Path(EGO_BINARY).exists():
        launch_kwargs['executable_path'] = str(EGO_BINARY)
    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        try:
            page = await browser.new_page(viewport={'width': 1280, 'height': 800})
            await page.goto(target_url, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(1.5)
            raw = await page.screenshot(type='png', full_page=False)
        finally:
            await browser.close()
    with Image.open(io.BytesIO(raw)) as image:
        image.convert('RGB').save(output, format='PNG')
        dimensions = list(image.size)
    receipt = {
        'status': 'downloaded',
        'mode': 'research_evidence_capture',
        'sourceUrl': target_url,
        'completedAt': stamp(),
        'dimensions': dimensions,
        'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    write(_evidence_path(folder, filename), receipt)
    return output


async def open_generation_settings(page):
    """Prefer the prompt's settings control over the unrelated global menu."""
    settings = page.locator('flow-base-prompt-box').get_by_role('button', name=re.compile(r'^(Settings|설정)$'))
    if await settings.count() != 1:
        settings = page.locator('button.settings-trigger-button')
    if await settings.count() != 1:
        settings = page.get_by_role('button', name=re.compile(r'^(Settings|설정)$')).last
    await settings.click(timeout=5000)


def generate(title, summary, folder, custom_prompt=None, filename='flow-hero.png', source_index=0):
    return asyncio.run(_generate(title, summary, Path(folder), custom_prompt=custom_prompt, filename=filename, source_index=source_index))


async def _generate(title, summary, folder, custom_prompt=None, filename='flow-hero.png', source_index=0):
    from playwright.async_api import async_playwright, expect
    from common.browser_session import flow_generation_lock, connect_async
    from common.ubuntu_naver_browser import account_paths, ensure_account, focus_workflow_window
    from common.ego_telemetry import async_action
    from PIL import Image

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    evidence_file = _evidence_path(folder, filename)
    output = folder / 'images' / filename

    if isinstance(custom_prompt, str) and custom_prompt.strip().upper().startswith('RESEARCH_CAPTURE'):
        # A request for evidence must never fall through to image generation.
        return await capture_research_evidence(folder, filename=filename, source_index=source_index)

    prompt = image_prompt(title, summary, custom_prompt=custom_prompt)
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    prior = load(evidence_file)
    if prior.get('promptSha256') == digest and prior.get('status') == 'downloaded' and output.exists():
        if hashlib.sha256(output.read_bytes()).hexdigest() == prior.get('sha256'):
            return output

    async with flow_generation_lock(timeout=300):
        prior = load(evidence_file)
        if prior.get('promptSha256') == digest and prior.get('status') == 'downloaded' and output.exists():
            if hashlib.sha256(output.read_bytes()).hexdigest() == prior.get('sha256'):
                return output
        try:
            if __import__('os').name == 'nt':
                try:
                    return await asyncio.to_thread(_generate_via_ego_flow, prompt, digest, output, evidence_file)
                except Exception:
                    return await asyncio.to_thread(_generate_via_openai_api, prompt, digest, output, evidence_file)
            await asyncio.to_thread(ensure_account, 9440)
            binary, profile, _ = account_paths(9440)
            async with async_playwright() as playwright:
                browser, _ = await connect_async(playwright, 'http://127.0.0.1:9440', binary, profile)
                context = browser.contexts[0]
                probe = context.pages[0] if context.pages else await context.new_page()
                if '/about' in (probe.url or '') or 'accounts.google.com' in (probe.url or '') or not (probe.url or '').startswith('https://flow.google.com/project'):
                    return await asyncio.to_thread(_generate_via_openai_api, prompt, digest, output, evidence_file)
                page = await prepare_fresh_project_page(context, prior if prior.get('promptSha256') == digest else {})
                if page is None:
                    raise RuntimeError('Fresh Flow project creation failed')
                await asyncio.to_thread(focus_workflow_window, 9440)
                if __import__('os').name != 'nt':
                    await page.bring_to_front()
                editor = page.locator('div.ProseMirror')
                if not prior or prior.get('promptSha256') != digest:
                    if (await editor.inner_text()).strip():
                        await editor.click()
                        await page.keyboard.press('Control+A')
                        await page.keyboard.press('Backspace')
                    section = page.locator('.settings-section').filter(has_text='이미지 생성 기본값')
                    if not await section.is_visible():
                        async with async_action('click', 'flow-settings'):
                            await open_generation_settings(page)
                    await section.wait_for(state='visible', timeout=5000)
                    single = section.get_by_role('radio', name='x1', exact=True)
                    if await single.get_attribute('aria-checked') != 'true':
                        async with async_action('click', 'flow-single-output'):
                            await single.click()
                    await expect(single).to_have_attribute('aria-checked', 'true', timeout=5000)
                    async with async_action('click', 'flow-settings'):
                        await page.get_by_role('button', name='저장', exact=True).click()
                    await section.wait_for(state='hidden', timeout=10000)
                    initial = await page.locator('img').evaluate_all('(xs)=>xs.map(x=>x.currentSrc)')
                    async with async_action('insert_text', 'flow-prompt', count=len(prompt)):
                        await editor.fill(prompt)
                    button = page.get_by_role('button', name='생성 시작', exact=True)
                    await button.wait_for(state='visible')
                    if not await button.is_enabled():
                        raise RuntimeError('Flow generation button disabled')
                    prior = {'status': 'submission_started', 'promptSha256': digest, 'projectUrl': page.url,
                             'initialImages': initial, 'outputCount': 1, 'owned': True, 'reused': False, 'freshProject': True, 'submittedAt': stamp()}
                    write(evidence_file, prior)
                    async with async_action('click', 'flow-generate'):
                        await button.click()
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    candidates = await page.locator('img').evaluate_all('(xs)=>xs.filter(x=>x.complete&&x.naturalWidth>=256&&x.naturalHeight>=256).map(x=>x.currentSrc)')
                    fresh = [src for src in candidates if src and src not in prior['initialImages'] and 'zero_states/' not in src]
                    if fresh:
                        async with async_action('download', 'flow-image'):
                            response = await context.request.get(fresh[0], timeout=20000)
                            if not response.ok:
                                raise RuntimeError('Flow image download failed')
                            raw = await response.body()
                        with Image.open(io.BytesIO(raw)) as image:
                            if min(image.size) < 256:
                                raise RuntimeError('Flow result is a thumbnail')
                            output.parent.mkdir(parents=True, exist_ok=True)
                            image.convert('RGB').save(output, format='PNG')
                            dimensions = list(image.size)
                        prior.update(status='downloaded', completedAt=stamp(), dimensions=dimensions,
                                     sha256=hashlib.sha256(output.read_bytes()).hexdigest())
                        write(evidence_file, prior)
                        return output
                    await asyncio.sleep(2)
        except Exception:
            pass
        return await asyncio.to_thread(_generate_via_openai_api, prompt, digest, output, evidence_file)


def _load_kr_font(size: int, bold: bool = True):
    from PIL import ImageFont
    candidates = (
        ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/NanumGothicBold.ttf", "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"]
        if bold
        else ["C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/NanumGothic.ttf", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]
    )
    for fp in candidates:
        if Path(fp).is_file():
            try:
                return ImageFont.truetype(fp, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap_kr_text(draw, text: str, font, max_width: int, max_lines: int = 3) -> list[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    lines: list[str] = []
    cur = ""
    for ch in text:
        test = cur + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= max_width or not cur:
            cur = test
        else:
            lines.append(cur.strip())
            cur = ch.lstrip()
            if len(lines) >= max_lines:
                break
    if len(lines) < max_lines and cur.strip():
        lines.append(cur.strip())
    elif len(lines) == max_lines and cur.strip():
        if len(lines[-1]) > 2:
            lines[-1] = lines[-1][:-1].rstrip() + "…"
    return lines


def render_postincome_hero_thumbnail(image_path: Path, keyword: str, title: str) -> Path:
    """Overlay PostIncome-style high-contrast 2-line big typography (White + Yellow with black stroke) onto the 1:1 hero thumbnail."""
    from PIL import Image, ImageDraw

    image_path = Path(image_path)
    if not image_path.is_file():
        return image_path

    with Image.open(image_path) as raw_img:
        base = raw_img.convert("RGBA").resize((1024, 1024), Image.Resampling.LANCZOS)

    overlay = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)

    # Subtle top gradient for badge legibility + rich bottom dark gradient for 2-line big typography
    for y in range(180):
        alpha = int(105 * (1.0 - y / 180.0))
        odraw.line([(0, y), (1024, y)], fill=(8, 12, 22, alpha))
    for y in range(460, 1024):
        ratio = (y - 460) / (1024 - 460)
        alpha = int(238 * (ratio ** 1.35))
        odraw.line([(0, y), (1024, y)], fill=(8, 12, 22, min(242, alpha)))

    comp = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(comp)

    # Extract Line 1 (Keyword hook) & Line 2 (Yellow punchline)
    clean_kw = re.sub(r"\s+", " ", (keyword or "").strip())
    raw_title = re.sub(r"\s+", " ", (title or "").strip())
    sub_part = ""
    if "..." in raw_title:
        sub_part = raw_title.split("...", 1)[1].strip(" .,?!")
    elif "," in raw_title:
        sub_part = raw_title.split(",", 1)[1].strip(" .,?!")
    elif len(raw_title) > len(clean_kw):
        sub_part = raw_title.replace(clean_kw, "", 1).strip(" .,?!")

    line1 = clean_kw[:13] if clean_kw else raw_title[:12]
    # Pick punchy 10~13 char hook for Line 2
    sub_words = [w for w in sub_part.split() if w not in ("실제", "주요", "대한", "관련", "총정리", "정리")]
    line2 = " ".join(sub_words[:3]).strip() if sub_words else "핵심 기준 총정리"
    if len(line2) > 12:
        line2 = line2[:12].rstrip()
    if not line2.endswith(("?", "!")):
        line2 = line2 + ("?" if any(k in raw_title for k in ("얼마", "될까", "가능", "최대", "이유", "방법")) else "!")

    # Top pill badge
    badge_font = _load_kr_font(30, bold=True)
    badge_text = "2026 핵심 요약 가이드"
    bb = draw.textbbox((0, 0), badge_text, font=badge_font)
    bw, bh = (bb[2] - bb[0]) + 44, (bb[3] - bb[1]) + 24
    bx, by = (1024 - bw) // 2, 54
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh // 2, fill=(3, 199, 90, 245))
    draw.text((bx + 22, by + 8), badge_text, font=badge_font, fill=(255, 255, 255, 255))

    # Fit Line 1 (White + Black Stroke) & Line 2 (Yellow + Black Stroke)
    def _fit_font(txt: str, start_sz: int, max_w: int = 910):
        for sz in range(start_sz, 44, -4):
            f = _load_kr_font(sz, bold=True)
            b = draw.textbbox((0, 0), txt, font=f, stroke_width=8)
            if (b[2] - b[0]) <= max_w:
                return f, (b[2] - b[0]), (b[3] - b[1])
        f = _load_kr_font(44, bold=True)
        b = draw.textbbox((0, 0), txt, font=f, stroke_width=8)
        return f, (b[2] - b[0]), (b[3] - b[1])

    f1, w1, h1 = _fit_font(line1, 82)
    f2, w2, h2 = _fit_font(line2, 92)

    y1 = 720
    y2 = y1 + h1 + 26
    x1 = (1024 - w1) // 2
    x2 = (1024 - w2) // 2

    # Drop shadows + thick black stroke + high-contrast fill
    draw.text((x1, y1 + 6), line1, font=f1, fill=(0, 0, 0, 180), stroke_width=10, stroke_fill=(0, 0, 0, 180))
    draw.text((x1, y1), line1, font=f1, fill=(255, 255, 255, 255), stroke_width=8, stroke_fill=(10, 14, 24, 255))

    draw.text((x2, y2 + 6), line2, font=f2, fill=(0, 0, 0, 190), stroke_width=10, stroke_fill=(0, 0, 0, 190))
    draw.text((x2, y2), line2, font=f2, fill=(255, 214, 0, 255), stroke_width=8, stroke_fill=(10, 14, 24, 255))

    out_rgb = comp.convert("RGB")
    out_rgb.save(image_path, format="PNG")
    try:
        ev_file = _evidence_path(image_path.parents[1], image_path.name)
        if ev_file.is_file():
            prior = load(ev_file)
            prior["sha256"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
            prior["heroTypographyOverlay"] = True
            write(ev_file, prior)
    except Exception:
        pass
    return image_path


def generate_section_smart_capture(
    heading: str,
    section_text: str,
    folder: Path,
    filename: str,
    *,
    section_index: int = 1,
    main_keyword: str = "",
) -> Path:
    """Removed: fabricated application screens are not source evidence."""
    hold_editorial_images(folder, 'simulated_capture_removed; use build_editorial_assets with exact article sections')
