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
