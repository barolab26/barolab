"""One serialized Flow image with durable submission/download provenance."""
import asyncio
import hashlib
import io
import time
from pathlib import Path

from common.collection_observability import load, write, stamp


def image_prompt(title, summary):
    return ('이미지 한 장만 생성해 주세요. 동영상은 만들지 마세요. 블로그 주제를 설명하는 고품질 개념 일러스트입니다. '
            '실제 체험 사진·정부 문서·증빙 화면으로 보이게 만들지 마세요. 글자, 로고, 통계, 제품 UI는 넣지 마세요. '
            '관찰된 사실을 증명하는 용도가 아닌 설명용 이미지입니다. 주제: ' + title[:160] + '\n설명: ' + summary[:600])


def generate(title, summary, folder):
    return asyncio.run(_generate(title, summary, Path(folder)))


async def _generate(title, summary, folder):
    from playwright.async_api import async_playwright, expect
    from common.browser_session import flow_generation_lock, connect_async
    from common.ubuntu_naver_browser import account_paths, ensure_account, focus_workflow_window
    from common.ego_telemetry import async_action
    from PIL import Image

    prompt = image_prompt(title, summary)
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    folder.mkdir(parents=True, exist_ok=True)
    evidence_file = folder / 'flow-generation.json'
    output = folder / 'images/flow-hero.png'
    async with flow_generation_lock(timeout=30):
        active_file = Path(__file__).resolve().parents[1] / 'data/flow-active.json'
        active = load(active_file)
        if active.get('folder') and active['folder'] != str(folder.resolve()):
            previous = load(Path(active['folder']) / 'flow-generation.json')
            if previous.get('status') != 'downloaded':
                raise RuntimeError('Another Flow result needs reconciliation before another request')
        prior = load(evidence_file)
        if prior.get('promptSha256') == digest and prior.get('status') == 'downloaded':
            if output.exists() and hashlib.sha256(output.read_bytes()).hexdigest() == prior.get('sha256'):
                return output
            raise RuntimeError('Flow output differs from downloaded receipt')
        if prior and prior.get('promptSha256') != digest:
            raise RuntimeError('Flow prompt changed; keep original generation evidence')
        await asyncio.to_thread(ensure_account, 9440)
        binary, profile, _ = account_paths(9440)
        async with async_playwright() as playwright:
            browser, _ = await connect_async(playwright, 'http://127.0.0.1:9440', binary, profile)
            context = browser.contexts[0]
            pages = [p for p in context.pages if 'flow.google.com/project/' in p.url]
            page = next((p for p in pages if p.url == prior.get('projectUrl')), None) if prior else next(iter(pages), None)
            if page is None:
                raise RuntimeError('Existing Flow project required; user tabs retained')
            await asyncio.to_thread(focus_workflow_window, 9440)
            await page.bring_to_front()
            editor = page.locator('div.ProseMirror')
            if not prior:
                if (await editor.inner_text()).strip():
                    raise RuntimeError('Existing Flow prompt retained; no overwrite')
                section = page.locator('.settings-section').filter(has_text='이미지 생성 기본값')
                if not await section.is_visible():
                    async with async_action('click', 'flow-settings'):
                        await page.get_by_role('button', name='Settings', exact=True).click()
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
                         'initialImages': initial, 'outputCount': 1, 'owned': False, 'reused': True, 'submittedAt': stamp()}
                write(active_file, {'folder':str(folder.resolve()),'promptSha256':digest,'submittedAt':prior['submittedAt']})
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
