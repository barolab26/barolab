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


async def capture_research_evidence(folder):
    """Capture a clean screenshot of the verified research source when evidence capture is requested."""
    from playwright.async_api import async_playwright
    from PIL import Image
    folder = Path(folder)
    research_data = load(folder / 'research.json')
    sources = research_data.get('sources') or []
    if not sources or not sources[0].get('url'):
        raise RuntimeError('No verified research source URL available to capture')
    target_url = sources[0]['url']
    output = folder / 'images/flow-hero.png'
    output.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
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
    write(folder / 'flow-generation.json', receipt)
    return output


async def open_generation_settings(page):
    """Prefer the prompt's settings control over the unrelated global menu."""
    settings = page.locator('flow-base-prompt-box').get_by_role('button', name=re.compile(r'^(Settings|설정)$'))
    if await settings.count() != 1:
        settings = page.locator('button.settings-trigger-button')
    if await settings.count() != 1:
        settings = page.get_by_role('button', name=re.compile(r'^(Settings|설정)$')).last
    await settings.click(timeout=5000)


def generate(title, summary, folder, custom_prompt=None):
    return asyncio.run(_generate(title, summary, Path(folder), custom_prompt=custom_prompt))


async def _generate(title, summary, folder, custom_prompt=None):
    from playwright.async_api import async_playwright, expect
    from common.browser_session import flow_generation_lock, connect_async
    from common.ubuntu_naver_browser import account_paths, ensure_account, focus_workflow_window
    from common.ego_telemetry import async_action
    from PIL import Image

    if isinstance(custom_prompt, str) and custom_prompt.strip().upper().startswith('RESEARCH_CAPTURE'):
        return await capture_research_evidence(folder)

    prompt = image_prompt(title, summary, custom_prompt=custom_prompt)
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    evidence_file = folder / 'flow-generation.json'
    output = folder / 'images/flow-hero.png'
    async with flow_generation_lock(timeout=300):
        active_file = Path(__file__).resolve().parents[1] / 'data/flow-active.json'
        active = load(active_file)
        if active.get('folder') and active['folder'] != str(folder.resolve()):
            previous = load(Path(active['folder']) / 'flow-generation.json')
            try:
                sub_time = datetime.fromisoformat(active.get('submittedAt', '1970-01-01T00:00:00+00:00'))
                is_stale = (datetime.now(timezone.utc) - sub_time).total_seconds() > 240
            except Exception:
                is_stale = True
            if previous.get('status') not in ('downloaded', None) and not is_stale:
                raise RuntimeError('Another Flow result needs reconciliation before another request')
        prior = load(evidence_file)
        if prior.get('promptSha256') == digest and prior.get('status') == 'downloaded':
            if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest() == prior.get('sha256'):
                return output
            raise RuntimeError('Flow output differs from downloaded receipt')
        if prior and prior.get('promptSha256') != digest:
            prior = {}
        await asyncio.to_thread(ensure_account, 9440)
        binary, profile, _ = account_paths(9440)
        async with async_playwright() as playwright:
            browser, _ = await connect_async(playwright, 'http://127.0.0.1:9440', binary, profile)
            context = browser.contexts[0]
            page = await prepare_fresh_project_page(context, prior)
            if page is None:
                raise RuntimeError('Fresh Flow project creation failed')
            await asyncio.to_thread(focus_workflow_window, 9440)
            await page.bring_to_front()
            editor = page.locator('div.ProseMirror')
            if not prior:
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
                write(active_file, {'folder': str(folder.resolve()), 'promptSha256': digest, 'submittedAt': prior['submittedAt']})
                write(evidence_file, prior)
                # Once this receipt exists, retries only reconcile. Never submit or spend credits twice.
                async with async_action('click', 'flow-generate'):
                    await button.click()
            deadline = time.monotonic() + 240
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
            prior.update(status='unconfirmed', lastCheckedAt=stamp())
            write(evidence_file, prior)
            raise RuntimeError('Flow result pending; preserve project and reconcile without resubmitting')
