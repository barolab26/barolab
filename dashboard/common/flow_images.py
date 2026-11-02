"""One serialized Flow image with durable submission/download provenance."""
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import re
import time
from pathlib import Path

from common.collection_observability import load, write, stamp


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
            'for a high-resolution editorial photograph matching this Korean article topic and summary. '
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
        'A bright, modern Korean lifestyle and business workspace scene with a clean desk, '
        'natural daylight streaming through a window, a warm cup of coffee, and a minimal notebook, '
        'captured in high-resolution editorial photography with shallow depth of field.'
    )


def image_prompt(title, summary, custom_prompt=None):
    scene = _ensure_english_scene(custom_prompt, title=title, summary=summary)
    return (
        'High-resolution editorial photography, realistic natural lighting, 35mm lens, shallow depth of field (do not generate video). '
        'Strictly no text, no letters, no numbers, no logos, no watermarks, and no document or UI screens inside the image. '
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
        try:
            return await capture_research_evidence(folder, filename=filename, source_index=source_index)
        except Exception:
            custom_prompt = None

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
    """Render an authentic iOS Mobile App UI Screen Capture (`1080 x 1920`, `IMG_83xx.PNG` style) matching the exact section heading and sentences."""
    from PIL import Image, ImageDraw

    folder = Path(folder)
    output = folder / "images" / filename
    output.parent.mkdir(parents=True, exist_ok=True)

    W, H = 1080, 1920
    # Vary theme slightly across sections 1~5 so horizontal search thumbnails look like distinct app screens
    themes = [
        {"bg": (242, 244, 248), "accent": (49, 130, 246), "accent_soft": (232, 243, 255), "header_bg": (255, 255, 255), "header_fg": (25, 31, 40), "badge": "핵심 기준 안내", "btn": "상세 기준 확인하기"},
        {"bg": (244, 246, 250), "accent": (3, 199, 90), "accent_soft": (230, 249, 239), "header_bg": (25, 31, 40), "header_fg": (255, 255, 255), "badge": "단계별 진행 절차", "btn": "신청 절차 순서대로 보기"},
        {"bg": (243, 245, 249), "accent": (91, 70, 246), "accent_soft": (238, 235, 255), "header_bg": (255, 255, 255), "header_fg": (25, 31, 40), "badge": "대상자 자가진단", "btn": "해당 여부 체크 완료"},
        {"bg": (245, 246, 248), "accent": (240, 68, 82), "accent_soft": (255, 238, 240), "header_bg": (25, 31, 40), "header_fg": (255, 255, 255), "badge": "필수 주의사항 체크", "btn": "주의사항 확인 완료"},
        {"bg": (242, 245, 248), "accent": (18, 149, 117), "accent_soft": (229, 247, 242), "header_bg": (255, 255, 255), "header_fg": (25, 31, 40), "badge": "최종 요약 리포트", "btn": "전체 요약 저장하기"},
    ]
    th = themes[(max(1, int(section_index)) - 1) % len(themes)]

    img = Image.new("RGB", (W, H), th["bg"])
    draw = ImageDraw.Draw(img)

    f_status = _load_kr_font(28, bold=True)
    f_nav = _load_kr_font(32, bold=True)
    f_badge = _load_kr_font(26, bold=True)
    f_title = _load_kr_font(44, bold=True)
    f_card_num = _load_kr_font(28, bold=True)
    f_card_head = _load_kr_font(34, bold=True)
    f_card_body = _load_kr_font(28, bold=False)
    f_pill = _load_kr_font(25, bold=True)
    f_btn = _load_kr_font(36, bold=True)

    # 1. iOS Status Bar (Top 0..96)
    draw.rectangle([0, 0, W, 180], fill=(255, 255, 255))
    draw.text((64, 34), "9:41", font=f_status, fill=(25, 31, 40))
    # Dynamic Island pill
    draw.rounded_rectangle([390, 24, 690, 74], radius=25, fill=(15, 18, 24))
    # Signal + Wi-Fi + Battery icon bars
    for bi, bh in enumerate((12, 18, 24, 30)):
        bx = 860 + bi * 12
        draw.rounded_rectangle([bx, 62 - bh, bx + 8, 62], radius=2, fill=(25, 31, 40))
    draw.rounded_rectangle([948, 36, 1012, 64], radius=8, outline=(25, 31, 40), width=3)
    draw.rounded_rectangle([953, 41, 1002, 59], radius=4, fill=(3, 199, 90))

    # 2. App Navigation Bar (96..180)
    nav_title = (main_keyword or "핵심 정보 가이드")[:18]
    draw.text((58, 114), "‹", font=_load_kr_font(48, bold=False), fill=(25, 31, 40))
    nb = draw.textbbox((0, 0), nav_title, font=f_nav)
    draw.text(((W - (nb[2] - nb[0])) // 2, 120), nav_title, font=f_nav, fill=(25, 31, 40))
    draw.line([(0, 180), (W, 180)], fill=(230, 233, 238), width=2)

    # 3. Top Section Hero Card (220..520)
    clean_heading = re.sub(r"^\s*0?\d+[\.\)\s-]+", "", (heading or "").strip()).strip()
    hx1, hy1, hx2, hy2 = 52, 216, W - 52, 520
    draw.rounded_rectangle([hx1, hy1 + 8, hx2, hy2 + 8], radius=36, fill=(224, 228, 236))
    draw.rounded_rectangle([hx1, hy1, hx2, hy2], radius=36, fill=th["header_bg"])

    # Badge inside Hero Card
    b_txt = f"STEP 0{section_index} · {th['badge']}"
    bb = draw.textbbox((0, 0), b_txt, font=f_badge)
    bw = (bb[2] - bb[0]) + 36
    draw.rounded_rectangle([hx1 + 44, hy1 + 40, hx1 + 44 + bw, hy1 + 88], radius=24, fill=th["accent_soft"] if th["header_bg"] == (255, 255, 255) else th["accent"])
    draw.text(
        (hx1 + 62, hy1 + 48),
        b_txt,
        font=f_badge,
        fill=th["accent"] if th["header_bg"] == (255, 255, 255) else (255, 255, 255),
    )

    h_lines = _wrap_kr_text(draw, clean_heading, f_title, max_width=(hx2 - hx1 - 88), max_lines=2)
    cur_hy = hy1 + 114
    for hl in h_lines:
        draw.text((hx1 + 44, cur_hy), hl, font=f_title, fill=th["header_fg"])
        cur_hy += 60

    # Subtitle status line inside Hero Card
    sub_hint = "실제 적용 기준 및 핵심 체크 포인트 요약"
    draw.text(
        (hx1 + 44, hy2 - 66),
        sub_hint,
        font=f_card_body,
        fill=(110, 120, 135) if th["header_bg"] == (255, 255, 255) else (190, 200, 215),
    )

    # 4. Extract 3~4 clean mobile UI cards from section_text
    raw_sents = [s.strip() for s in re.split(r"[\n]+|(?<=[.!?다요])\s+", (section_text or "").strip()) if len(s.strip()) >= 12]
    if not raw_sents:
        raw_sents = [clean_heading + " 관련 세부 기준을 확인하세요."]
    cards = raw_sents[:4]

    cy = 556
    pill_labels = ["핵심 체크", "필수 기준", "상세 요건", "실전 팁"]
    for idx, sent in enumerate(cards):
        if cy + 260 > 1680:
            break
        # Extract any number/amount/percent token for highlight pill
        num_m = re.search(r"(\d[\d,]*\s*(?:만\s*원|원|%|일|개월|년|세|점|회|시간|배))", sent)
        pill_txt = num_m.group(1).strip() if num_m else pill_labels[idx % len(pill_labels)]

        # Split sentence into non-overlapping bold lead phrase + remainder body description
        m_split = re.match(r"^(.{8,24}?(?:은|는|이|가|을|를|면|시|후|전|경우|때|마다|부터|까지|,|·))\s+(.+)$", sent)
        if m_split:
            c_head = m_split.group(1).rstrip(" ,·")
            c_body = m_split.group(2).strip()
        else:
            words = sent.split()
            if len(words) >= 4:
                c_head = " ".join(words[:3])
                c_body = " ".join(words[3:])
            else:
                c_head = f"핵심 체크 포인트 0{idx + 1}"
                c_body = sent

        body_lines = _wrap_kr_text(draw, c_body, f_card_body, max_width=(W - 220), max_lines=2)
        card_h = 176 + max(0, len(body_lines) - 1) * 44

        cx1, cy1, cx2, cy2 = 52, cy, W - 52, cy + card_h
        draw.rounded_rectangle([cx1, cy1 + 6, cx2, cy2 + 6], radius=32, fill=(226, 230, 238))
        draw.rounded_rectangle([cx1, cy1, cx2, cy2], radius=32, fill=(255, 255, 255))

        # Left number circle badge
        draw.ellipse([cx1 + 36, cy1 + 36, cx1 + 92, cy1 + 92], fill=th["accent_soft"])
        num_str = f"0{idx + 1}"
        nb_box = draw.textbbox((0, 0), num_str, font=f_card_num)
        draw.text(
            (cx1 + 64 - (nb_box[2] - nb_box[0]) // 2, cy1 + 46),
            num_str,
            font=f_card_num,
            fill=th["accent"],
        )

        # Right highlight value pill
        pb = draw.textbbox((0, 0), pill_txt, font=f_pill)
        pw = (pb[2] - pb[0]) + 32
        px1 = cx2 - 36 - pw
        draw.rounded_rectangle([px1, cy1 + 36, cx2 - 36, cy1 + 82], radius=23, fill=th["accent_soft"])
        draw.text((px1 + 16, cy1 + 44), pill_txt, font=f_pill, fill=th["accent"])

        # Card heading (clipped before right pill)
        head_lines = _wrap_kr_text(draw, c_head, f_card_head, max_width=(px1 - (cx1 + 114) - 16), max_lines=1)
        if head_lines:
            draw.text((cx1 + 114, cy1 + 42), head_lines[0], font=f_card_head, fill=(25, 31, 40))

        # Card body lines
        by_cur = cy1 + 106
        for bl in body_lines:
            draw.text((cx1 + 114, by_cur), bl, font=f_card_body, fill=(78, 89, 104))
            by_cur += 44

        cy = cy2 + 28

    # Bottom Tip Summary Box if space remains above CTA button
    if cy + 210 <= 1670:
        tx1, ty1, tx2, ty2 = 52, cy + 8, W - 52, min(1666, cy + 228)
        draw.rounded_rectangle([tx1, ty1, tx2, ty2], radius=28, fill=th["accent_soft"])
        draw.text((tx1 + 40, ty1 + 34), f"[핵심 체크] {clean_heading[:20]}", font=f_card_head, fill=th["accent"])
        tip_lines = _wrap_kr_text(
            draw,
            f"{main_keyword or clean_heading} 진행 전 위 {len(cards)}가지 세부 요건과 숫자를 반드시 먼저 대조해 보세요.",
            f_card_body,
            max_width=(tx2 - tx1 - 80),
            max_lines=2,
        )
        t_cur = ty1 + 94
        for tl in tip_lines:
            draw.text((tx1 + 40, t_cur), tl, font=f_card_body, fill=(55, 65, 81))
            t_cur += 42

    # 5. Bottom Sticky Action Button + iOS Home Indicator Bar
    btn_y1, btn_y2 = 1710, 1824
    draw.rounded_rectangle([52, btn_y1, W - 52, btn_y2], radius=28, fill=th["accent"])
    btn_txt = f"{th['btn']}  ›"
    btb = draw.textbbox((0, 0), btn_txt, font=f_btn)
    draw.text(((W - (btb[2] - btb[0])) // 2, btn_y1 + 34), btn_txt, font=f_btn, fill=(255, 255, 255))

    # iOS Home Bar
    draw.rounded_rectangle([(W - 360) // 2, 1878, (W + 360) // 2, 1892], radius=7, fill=(180, 186, 196))

    img.save(output, format="PNG")
    receipt = {
        "status": "downloaded",
        "mode": "mobile_ui_smart_capture",
        "sectionIndex": section_index,
        "completedAt": stamp(),
        "dimensions": [W, H],
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    write(_evidence_path(folder, filename), receipt)
    return output

