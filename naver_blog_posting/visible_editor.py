"""Write an approved article through visible SmartEditor keyboard/toolbar actions."""
from common.ego_telemetry import action as ego_action, async_action as ego_async_action
import json
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

SOULTIN_UI_PALETTE = {'textColor': '#333333', 'headingColor': '#245b12'}

READ_DOCUMENT = "SmartEditor.getEditor('blogpc001').getDocumentData()"


def load_decoration_plan(folder, block_count):
    path = Path(folder) / 'visible-decoration-plan.json'
    if not path.exists():
        return [], None
    raw = path.read_bytes()
    value = json.loads(raw)
    if (not isinstance(value, dict) or set(value) != {'version', 'stickers'}
            or value['version'] != 1 or not isinstance(value['stickers'], list)
            or len(value['stickers']) != 1):
        raise RuntimeError('One explicit verified free builtin sticker plan required')
    for item in value['stickers']:
        if (not isinstance(item, dict) or set(item) != {'afterBlock', 'packCode', 'seq'}
                or type(item['afterBlock']) is not int or not 0 <= item['afterBlock'] < block_count
                or item['packCode'] != 'motion2d_01' or type(item['seq']) is not int or item['seq'] != 19):
            raise RuntimeError('Unobserved sticker or invalid placement rejected')
    return value['stickers'], hashlib.sha256(raw).hexdigest()


def require_decoration_hash(folder, expected):
    path = Path(folder) / 'visible-decoration-plan.json'
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if actual != expected:
        raise RuntimeError('Visible decoration plan changed after composition/review')


def _text(paragraphs):
    return [''.join(node.get('value', '') for node in paragraph.get('nodes', []))
            for paragraph in paragraphs]


def verify_visible_content(document, title, blocks, plans, decorations=()):
    """Compare ordered nonblank paragraphs, links and images without editor IDs."""
    actual = []
    components = document['document']['components']
    if not components or components[0].get('@ctype') != 'documentTitle':
        raise RuntimeError('Visible editor title component missing')
    if ''.join(_text(components[0].get('title', []))) != title:
        raise RuntimeError('Visible editor title differs from approved title')
    for component in components[1:]:
        if component.get('@ctype') == 'text':
            for paragraph in component.get('value', []):
                text = ''.join(_text([paragraph]))
                if text.strip():
                    links = [(node.get('value', ''), node['link']['url']) for node in paragraph.get('nodes', [])
                             if node.get('link', {}).get('@ctype') == 'urlLink']
                    actual.append(('text', text, links))
        elif component.get('@ctype') == 'image':
            actual.append(('image', component.get('fileName'), '\n'.join(_text(component.get('caption', []))).strip()))
        elif component.get('@ctype') == 'sticker':
            if component.get('thumbnail', {}).get('src') != 'https://storep-phinf.pstatic.net/motion2d_01/original_19.png':
                raise RuntimeError('Unexpected sticker image source')
            actual.append(('sticker', component.get('packCode'), component.get('seq')))
        else:
            raise RuntimeError('Unexpected visible editor component')
    expected = []
    for index, block in enumerate(blocks):
        for segments in block['paragraphs']:
            text = ''.join(part['text'] for part in segments)
            if text.strip():
                expected.append(('text', text, [(part['text'], part['url']) for part in segments if 'url' in part]))
        for plan in plans:
            if plan['afterBlock'] == index:
                expected.append(('image', plan['filename'], plan['caption']))
        for decoration in decorations:
            if decoration['afterBlock'] == index:
                expected.append(('sticker', decoration['packCode'], decoration['seq']))
    if actual != expected:
        raise RuntimeError('Visible editor body, links, image order or captions differ from approved content')


def _option(frame, name, option):
    with ego_action('click', 'naver-toolbar'):
        frame.locator(f'button[data-name="{name}"][data-group="propertyToolbar"]').click()
    with ego_action('click', 'naver-toolbar'):
        frame.locator(option).click()


def _style(frame, profile, heading):
    _option(frame, 'font-family', '.se-toolbar-option-font-family-' + profile['fontFamily'] + '-button')
    size = profile['headingSize'] if heading else profile['bodySize']
    _option(frame, 'font-size', f'.se-toolbar-option-font-size-code-fs{size}-button')
    _option(frame, 'line-height', f'.se-toolbar-option-line-height-{round(profile["lineHeight"] * 100)}-button')
    with ego_action('click', 'naver-toolbar'):
        frame.locator('button[data-name="font-color"][data-group="propertyToolbar"]').click()
    with ego_action('click', 'naver-toolbar'):
        frame.locator('button.se-color-palette:visible:not(:disabled)').filter(has_text=re.compile('^' + re.escape(profile['headingColor'] if heading else profile['textColor']) + '$', re.I)).first.click()
    bold = frame.locator('button[data-name="bold"][data-group="propertyToolbar"]')
    selected = 'se-is-selected' in (bold.get_attribute('class') or '').split()
    if selected != heading:
        with ego_action('click', 'naver-toolbar'):
            bold.click()


def write_visible_editor(page, frame, title, blocks, plans, folder, profile):
    from common.ego_telemetry import current_context, execution_context
    context = current_context()
    fields = {'project': 'naver_blog', 'actor': 'publi'}
    if context.get('source') == 'direct':
        fields['task_id'] = 'naver:' + hashlib.sha256(str(Path(folder).resolve()).encode()).hexdigest()[:24]
    with execution_context(**fields):
        return _write_visible_editor(page, frame, title, blocks, plans, folder, profile)


def _write_visible_editor(page, frame, title, blocks, plans, folder, profile):
    """No editor mutation APIs, clipboard, fill, or whole-document insertion."""
    folder = Path(folder)
    decorations, decoration_hash = load_decoration_plan(folder, len(blocks))
    events = []
    def record(stage, **details):
        events.append({'stage': stage, 'at': datetime.now(timezone.utc).isoformat(), **details})
        (folder / 'visible-editor-progress.json').write_text(json.dumps({
            'mode': 'keyboard-toolbar-sequential', 'profile': profile, 'decorationPlanSha256': decoration_hash, 'events': events}, ensure_ascii=False, indent=2), encoding='utf-8')
        print('[visible-editor] ' + stage + ' ' + json.dumps(details), flush=True)
    page.bring_to_front()
    record('start')
    with ego_action('click', 'naver-title'):
        frame.locator('.se-component.se-documentTitle .se-title-text').first.click()
    with ego_action('type', 'naver-title', count=len(title)):
        page.keyboard.type(title, delay=25)
    record('title', characters=len(title))
    with ego_action('click', 'naver-body'):
        frame.locator('.se-component.se-text .se-module-text').first.click()
    uploaded = 0
    for index, block in enumerate(blocks):
        if index:
            previous_heading = blocks[index - 1]['kind'] == 'heading'
            gap = profile['headingGapLines'] if block['kind'] == 'heading' or previous_heading else profile['paragraphGapLines']
            for _ in range(gap):
                with ego_action('press', 'naver-editor-key'):
                    page.keyboard.press('Enter')
        _style(frame, profile, block['kind'] == 'heading')
        for segments in block['paragraphs']:
            for part in segments:
                with ego_action('type', 'naver-body', count=len(part['text'])):
                    page.keyboard.type(part['text'], delay=25)
                if 'url' in part:
                    for _ in part['text']:
                        with ego_action('press', 'naver-editor-key'):
                            page.keyboard.press('Shift+ArrowLeft')
                    with ego_action('click', 'naver-link'):
                        frame.locator('button[data-name="text-link"]').click()
                    field = frame.locator('input.se-custom-layer-link-input')
                    with ego_action('click', 'naver-link'):
                        field.click()
                    with ego_action('press', 'naver-editor-key'):
                        page.keyboard.press('Control+A')
                    with ego_action('type', 'naver-link', count=len(part['url'])):
                        page.keyboard.type(part['url'], delay=25)
                    with ego_action('click', 'naver-link'):
                        frame.locator('button.se-custom-layer-link-apply-button').click()
                    frame.wait_for_function("part=>SmartEditor.getEditor('blogpc001').getDocumentData().document.components.some(c=>c['@ctype']==='text' && (c.value||[]).some(p=>(p.nodes||[]).some(n=>n.value===part.text && n.link?.url===part.url)))", arg=part, timeout=10000)
                    # The toolbar keeps focus after applying; restore it with actual UI actions.
                    with ego_action('click', 'naver-body'):
                        frame.locator('.se-component.se-text .se-module-text').last.click()
                    with ego_action('press', 'naver-editor-key'):
                        page.keyboard.press('End')
                    with ego_action('press', 'naver-editor-key'):
                        page.keyboard.press('ArrowRight')
            with ego_action('press', 'naver-editor-key'):
                page.keyboard.press('Enter')
        record('block', index=index, kind=block['kind'])
        for plan in plans:
            if plan['afterBlock'] != index:
                continue
            with page.expect_file_chooser(timeout=10000) as chooser:
                with ego_action('click', 'naver-image'):
                    frame.locator('button[data-name="image"][data-group="documentToolbar"]').click()
            with ego_action('upload', 'naver-image'):
                chooser.value.set_files(str(folder / 'images' / plan['filename']))
            page.wait_for_timeout(700)
            individual = frame.get_by_text('개별사진', exact=True)
            if individual.count() and individual.first.is_visible():
                with ego_action('click', 'naver-image'):
                    individual.first.click()
                with ego_action('click', 'naver-editor'):
                    frame.locator('.se-popup-button-confirm').click()
            uploaded += 1
            frame.wait_for_function("n=>SmartEditor.getEditor('blogpc001').getDocumentData().document.components.filter(c=>c['@ctype']==='image').length===n", arg=uploaded, timeout=30000)
            frame.wait_for_function(r"n=>{const img=document.querySelectorAll('.se-component.se-image img')[n-1];return img && img.complete && img.naturalWidth>0 && /^https:\/\/[^/]*pstatic\.net\//.test(img.src)}", arg=uploaded, timeout=30000)
            with ego_action('click', 'naver-image'):
                frame.locator('.se-component.se-image img.se-image-resource').nth(uploaded - 1).click()
            caption = frame.locator('.se-component.se-image .se-caption.se-module-text').nth(uploaded - 1)
            caption.wait_for(state='visible')
            with ego_action('click', 'naver-caption'):
                caption.click()
            with ego_action('type', 'naver-caption', count=len(plan['caption'])):
                page.keyboard.type(plan['caption'], delay=25)
            record('image', afterBlock=index, filename=plan['filename'])
            with ego_action('press', 'naver-editor-key'):
                page.keyboard.press('ArrowDown')
            with ego_action('press', 'naver-editor-key'):
                page.keyboard.press('End')
            with ego_action('press', 'naver-editor-key'):
                page.keyboard.press('Enter')
        for decoration in decorations:
            if decoration['afterBlock'] != index:
                continue
            with ego_action('click', 'naver-sticker'):
                frame.locator('button[data-name="sticker"][data-group="documentToolbar"]').click()
            with ego_action('click', 'naver-sticker'):
                frame.get_by_role('button', name='motion2d_01-19', exact=True).click()
            frame.wait_for_function("()=>SmartEditor.getEditor('blogpc001').getDocumentData().document.components.filter(c=>c['@ctype']==='sticker' && c.packCode==='motion2d_01' && c.seq===19).length===1", timeout=10000)
            with ego_action('press', 'naver-editor-key'):
                page.keyboard.press('ArrowDown')
            with ego_action('press', 'naver-editor-key'):
                page.keyboard.press('End')
            with ego_action('press', 'naver-editor-key'):
                page.keyboard.press('Enter')
            record('sticker', afterBlock=index, packCode='motion2d_01', seq=19)
    # SmartEditor may commit the last keyboard event asynchronously. Read only; never retype.
    for observation in range(11):
        document = frame.evaluate(READ_DOCUMENT)
        try:
            verify_visible_content(document, title, blocks, plans, decorations)
            break
        except RuntimeError:
            if observation == 10:
                (folder / 'visible-editor-mismatch.json').write_text(
                    json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
                record('content-mismatch', observations=11)
                raise
            page.wait_for_timeout(500)
    require_decoration_hash(folder, decoration_hash)
    record('verified', blocks=len(blocks), images=uploaded)
    return document
