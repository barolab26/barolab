"""Build blocks through the visible SmartEditor toolbar, keyboard and photo picker."""
import time
import copy
import json

from common.collection_observability import write
from common.ego_telemetry import action


def displayed_document(document):
    """Keep the validated source and attribution while rendering the chosen style."""
    result = copy.deepcopy(document)
    params = document.get('presentation', {})
    for block in result['blocks']:
        if block['type'] == 'heading' and 'headingPrefix' in params:
            block['text'] = params['headingPrefix'] + block['text'].lstrip('▼ ').strip()
        if block['type'] == 'image' and params.get('imageCaptions') is False:
            block['caption'] = ''
    return result


def text_style(params, index, block):
    params = {**params, **params.get('blockStyles', {}).get(str(index), {})}
    heading = block['type'] == 'heading'
    return (params['headingFontSize'] if heading else params['summaryFontSize'] if index == 0 else params['bodyFontSize'],
            params.get('headingBold', True) if heading else bool(block.get('emphasis')) or index == 0 and params['summaryBold'],
            params.get('headingAlign', 'center') if heading else params.get('textAlign', 'left'))


def native_paragraphs(value):
    if isinstance(value, dict):
        if value.get('@ctype') == 'paragraph':
            yield value
        else:
            for child in value.values():
                yield from native_paragraphs(child)
    elif isinstance(value, list):
        for child in value:
            yield from native_paragraphs(child)


def editor_content(value, *, reader=None):
    """An image without a caption is emitted as null by the live editor."""
    import naver_blog_posting.posting as engine
    normalized = copy.deepcopy(value)
    for component in normalized['document']['components']:
        if component.get('@ctype') == 'image' and component.get('caption') is None:
            component['caption'] = []
    return (reader or engine.basic_editor_content)(normalized)


def write_image_caption(page, reference):
    """Type the approved caption only into the exact uploaded image's empty caption."""
    from pathlib import Path
    frame=page.frame(name='mainFrame') or page
    actual=frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
    images=[c for c in actual['document']['components'] if c.get('@ctype')=='image']
    matches=[(i,c) for i,c in enumerate(images) if c.get('fileName')==Path(reference['file']).name]
    if len(matches)!=1 or not reference.get('caption'):raise ValueError('Exact caption image is unavailable')
    index,component=matches[0]
    caption=' '.join(''.join(n.get('value','') for n in p.get('nodes',[])) for p in native_paragraphs(component.get('caption')))
    if ' '.join(caption.split())==' '.join(reference['caption'].split()):return
    if caption.strip():raise ValueError('Existing image caption preserved; content differs')
    image=frame.locator('.se-component.se-image').nth(index)
    if image.get_attribute('id')!=component.get('id'):raise ValueError('Visible caption image identity mismatch')
    field=image.locator('.se-caption .se-text-paragraph')
    if field.count()!=1:raise ValueError('Visible caption field is not unique')
    if not field.is_visible():raise ValueError('Image caption is hidden; reveal the caption through the visible image toolbar first')
    with action('click','naver-caption'):field.click()
    with action('type','naver-caption',count=len(reference['caption'])):
        page.keyboard.type(reference['caption'],delay=1)


def bind(page, frame, document, plan, folder):
    import naver_blog_posting.posting as engine
    from common.ubuntu_naver_browser import focus_workflow_window
    from common.channel_parameters import styles
    from common.collection_observability import load

    started = time.monotonic()
    current = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
    if not engine.blank_naver_document(current):
        proof = load(folder / 'preserved-screen-editor.json')
        progress = load(folder / 'ego-screen-editor/screen-execution.json')
        session = page.context.new_cdp_session(page)
        try:
            target = session.send('Target.getTargetInfo')['targetInfo']['targetId']
        finally:
            session.detach()
        if not (document.get('presentation', {}).get('screenDriven') and progress.get('written')
                and target == (proof.get('targetId') or progress.get('editorTargetId'))
                and editor_content(current)['title'] == document['title']):
            raise ValueError('Existing editor draft preserved')
    identity = load(folder / 'identity.json')
    account = engine.ACCOUNT_MAP[identity['account']]
    focus_workflow_window(account['cdp_port'])
    page.bring_to_front()
    params = document.get('presentation') or styles(identity['account'])
    document = displayed_document(document)
    document['presentation'] = params
    steps = []
    if params.get('screenDriven'):
        from common.ego_executor import execute_screen_editor, review_screen_editor
        receipt = execute_screen_editor(page, document, folder, account['cdp_port'])
        actual = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
        verify_binding(page, document, actual, folder, started, receipt['turns'], mode='ego-screen')
        review = review_screen_editor(page, document, folder, account['cdp_port'])
        current = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
        if engine.editor_review_hash(current) != engine.editor_review_hash(actual):
            raise ValueError('Document changed during read-only EGO visual review')
        write(folder / 'pre-reservation-review.json', {**review, 'account': identity['account'],
              'title': document['title'], 'reserveTime': engine.RUN_OPTIONS.get('reserve_time'),
              'documentSha256': engine.editor_review_hash(actual)})
        return actual

    def click(locator, target='naver-toolbar'):
        with action('click', target):
            locator.click(timeout=10000)

    def select(name, value):
        click(frame.locator(f'button[data-name="{name}"]:not([data-role="option"])'))
        click(frame.locator(f'button[data-name="{name}"][data-role="option"][data-value="{value}"]'))

    def font(size, bold, align):
        if params.get('fontFamily'):
            select('font-family', params['fontFamily'])
        select('font-size', 'fs' + str(size))
        toggle = frame.locator('button[data-name="bold"]')
        active = 'se-is-selected' in (toggle.get_attribute('class') or '')
        if active != bold:
            click(toggle)
        select('align-drop-down-with-justify', align)
        if params.get('fontColor'):
            click(frame.locator('button[data-name="font-color"]:not([data-role="option"])'))
            click(frame.locator(f'button.se-color-palette[data-color="{params["fontColor"]}"]'))
        if params.get('lineHeight'):
            click(frame.locator('button[data-name="line-height"]:not([data-role="option"])'))
            control = frame.locator('input.se-line-height-option-value-input')
            control.fill(str(round(params['lineHeight'] * 100)))
            control.press('Enter')

    def type_lines(text, target):
        with action('type', target, count=len(text)):
            for index, line in enumerate(text.split('\n')):
                if index:
                    page.keyboard.press('Enter')
                page.keyboard.type(line, delay=1)

    click(frame.locator('.se-documentTitle .se-text-paragraph').first, 'naver-title')
    type_lines(document['title'], 'naver-title')
    click(frame.locator('.se-component.se-text .se-text-paragraph').last, 'naver-body')
    image_count = 0
    for index, block in enumerate(document['blocks']):
        if block['type'] == 'image':
            with page.expect_file_chooser(timeout=10000) as chooser:
                click(frame.locator('button[data-name="image"][data-group="documentToolbar"]'), 'naver-image')
            with action('upload', 'naver-image'):
                chooser.value.set_files(str(folder / 'images' / block['file']))
            individual = frame.get_by_text('개별사진', exact=True)
            if individual.count() and individual.first.is_visible():
                click(individual.first, 'naver-image')
                click(frame.locator('.se-popup-button-confirm'), 'naver-image')
            image_count += 1
            frame.wait_for_function("n=>document.querySelectorAll('.se-component.se-image img').length===n&&[...document.querySelectorAll('.se-component.se-image img')].every(x=>x.complete&&x.naturalWidth>0&&x.src.includes('.pstatic.net/'))", arg=image_count, timeout=30000)
            image = frame.locator('.se-component.se-image').last
            click(image.locator('img'), 'naver-image')
            if block['caption']:
                click(image.locator('.se-caption .se-text-paragraph'), 'naver-caption')
                type_lines(block['caption'], 'naver-caption')
            click(frame.locator('.se-component.se-text .se-text-paragraph').last, 'naver-body')
            steps.append({'block':index,'action':'photo-upload-and-caption','file':block['file']})
            continue
        size, bold, align = text_style(params, index, block)
        font(size, bold, align)
        type_lines(block['text'], 'naver-body')
        with action('press', 'naver-editor-key'):
            page.keyboard.press('Enter')
        steps.append({'block':index,'action':'keyboard-and-toolbar','fontSize':size,'bold':bold})
    actual = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
    return verify_binding(page, document, actual, folder, started, steps)


def verify_binding(page, document, actual, folder, started, steps, mode='visible-ui', record=True):
    import naver_blog_posting.posting as engine
    params = document['presentation']
    expected = engine.basic_native_document(actual, document)
    if record:
        write(folder / 'bound-native-document.json', actual)
        write(folder / 'requested-native-document.json', expected)
    actual_content, expected_content = editor_content(actual), editor_content(expected)
    if len(actual_content['images'])==len(expected_content['images']):
        image_blocks=[i for i,b in enumerate(document['blocks']) if b['type']=='image']
        for index,(observed_image,approved_image) in enumerate(zip(actual_content['images'],expected_content['images'])):
            if observed_image['caption']!=approved_image['caption'] and not observed_image['caption'] and approved_image['caption']:
                reference='block-'+str(image_blocks[index])
                raise ValueError('Approved image caption missing for '+reference+'; reveal the image caption in the visible toolbar, then use caption action with this ref')
    link_urls = params.get('linkCardURLs', [])
    def body(value):
        lines = []
        for component in value['document']['components'][1:]:
            if component.get('@ctype') in ('image', 'oglink'):
                continue
            for paragraph in native_paragraphs(component):
                text = ''.join(node.get('value', '') for node in paragraph['nodes'])
                if text.strip() not in link_urls:
                    lines.append(text)
        return ' '.join(' '.join(lines).split())
    actual_content['body'], expected_content['body'] = body(actual), body(expected)
    if actual_content != expected_content:
        raise ValueError('Visible editor differs from supplied title/body/images/captions; submission stopped')
    components = actual['document']['components'][1:]
    for field, kind in (('quoteCount', 'quotation'), ('dividerCount', 'horizontalLine'),
                        ('stickerCount', 'sticker'), ('tableCount', 'table'), ('imageCount', 'image')):
        count = sum(c.get('@ctype') == kind for c in components)
        if field in params and count != params[field]:
            raise ValueError(f'Visible {field}: expected {params[field]}, observed {count}; inspect and remove empty/duplicate components')
    if link_urls:
        cards = [c for c in components if c.get('@ctype') == 'oglink']
        matched = {url for url in link_urls if any(url in json.dumps(card, ensure_ascii=False) for card in cards)}
        if len(cards) != len(link_urls) or matched != set(link_urls):
            raise ValueError('Visible official link cards differ from approved URLs')
    observed = []
    for component in actual['document']['components']:
        if component.get('@ctype') in ('documentTitle', 'image', 'oglink'):
            continue
        for paragraph in native_paragraphs(component):
            nodes = [n for n in paragraph.get('nodes', []) if n.get('value')]
            if nodes and ''.join(n['value'] for n in nodes).strip() not in link_urls:
                observed.append((nodes, paragraph.get('style', {}).get('align', 'left')))
    expected_styles = []
    for index, block in enumerate(document['blocks']):
        if block['type'] == 'image':
            continue
        size, bold, align = text_style(params, index, block)
        block_params = {**params, **params.get('blockStyles', {}).get(str(index), {})}
        for text in block['text'].split('\n'):
            if text and text.strip() not in link_urls:
                expected_styles.append((size, bold, align, text, block_params))
    if len(observed) != len(expected_styles):
        raise ValueError('Visible paragraph count differs from supplied document')
    effective = {}
    try:
        frame = page.frame(name='mainFrame') or page
        measured = frame.evaluate('''ids=>{const out={};const hex=c=>{const n=c.match(/\\d+/g);
            return n&&n.length>=3?'#'+n.slice(0,3).map(x=>(+x).toString(16).padStart(2,'0')).join(''):c};
            for(const id of ids){const e=document.getElementById(id);if(!e)continue;
              const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),leaves=[];
              while(walker.nextNode()){if(walker.currentNode.nodeValue.trim())leaves.push(walker.currentNode.parentElement)}
              const leaf=leaves[0]||e,s=getComputedStyle(leaf),p=e.closest('.se-text-paragraph');
              const weights=leaves.map(n=>parseInt(getComputedStyle(n).fontWeight)>=600);
              const mixedBold=new Set(weights).size>1;
              let background='';for(let n=leaf;n;n=n.parentElement){const c=getComputedStyle(n).backgroundColor;
                if(c&&c!=='rgba(0, 0, 0, 0)'&&c!=='transparent'){background=hex(c);break}if(n===e)break}
              const family=(e.className||'').match(/se-ff-([\\w]+)/);
              const size=(e.className||'').match(/se-fs(\\d+)/);
              out[id]={fontSizeCode:'fs'+(size?size[1]:parseInt(s.fontSize)),fontFamily:family?family[1]:'system',
                fontColor:hex(s.color),bold:parseInt(s.fontWeight)>=600,mixedBold,
                backgroundColor:background,
                align:p?getComputedStyle(p).textAlign:'left',lineHeight:p?parseFloat(p.style.lineHeight):null};}
            return out}''', [n.get('id') for nodes, _ in observed for n in nodes if n.get('id')])
        if isinstance(measured, dict):
            effective = measured
    except Exception:
        pass  # Native values remain mandatory when read-only CSS measurement is unavailable.
    for number, ((nodes, align), (size, bold, expected_align, text, block_params)) in enumerate(zip(observed, expected_styles), 1):
        if nodes and nodes[0].get('id') in effective:
            align = effective[nodes[0]['id']]['align']
        if ''.join(n['value'] for n in nodes) != text or align != expected_align:
            raise ValueError(f'Paragraph {number} ({text[:30]}): text/alignment differs from {expected_align}')
        offset = 0
        for node in nodes:
            style = {**node.get('style', {}), **effective.get(node.get('id'), {})}
            if style.get('mixedBold'):raise ValueError('Rendered text has mixed bold formatting inside one native run')
            for position in range(offset, offset + len(node['value'])):
                selected = {'bold': bold, 'backgroundColor': ''}
                for rule in block_params.get('inlineStyles', []):
                    start = text.find(rule['text'])
                    if start >= 0 and start <= position < start + len(rule['text']):
                        selected.update({key: value for key, value in rule.items() if key != 'text'})
                if style.get('fontSizeCode') != 'fs' + str(size) or bool(style.get('bold')) != selected['bold']:
                    raise ValueError(f'Paragraph {number} ({text[:30]}): expected fs{size}, bold={selected["bold"]}; observed {style}')
                if selected.get('backgroundColor') and style.get('backgroundColor', '').lower() != selected['backgroundColor'].lower():
                    raise ValueError(f'Paragraph {number} ({text[:30]}): missing highlight {selected["backgroundColor"]}')
                if not selected['backgroundColor'] and style.get('backgroundColor', '').lower() not in ('', '#ffffff'):
                    raise ValueError(f'Paragraph {number} ({text[:30]}): unintended background highlight')
            offset += len(node['value'])
            if block_params.get('fontFamily') and style.get('fontFamily', 'system') != block_params['fontFamily']:
                raise ValueError(f'Paragraph {number} ({text[:30]}): expected font {block_params["fontFamily"]}, observed {style.get("fontFamily", "system")}')
            if block_params.get('fontColor') and style.get('fontColor', '#000000').lower() != block_params['fontColor'].lower():
                raise ValueError(f'Paragraph {number} ({text[:30]}): expected color {block_params["fontColor"]}, observed {style.get("fontColor", "#000000")}')
            if style.get('lineHeight') and block_params.get('lineHeight') and abs(style['lineHeight'] - block_params['lineHeight']) > .001:
                raise ValueError(f'Paragraph {number} ({text[:30]}): expected line height {block_params["lineHeight"]}, observed {style["lineHeight"]}')
    if record:
        page.screenshot(path=str(folder / 'visible-editor.png'))
        write(folder / 'binding-receipt.json', {'mode':mode,'nativeDocumentWrite':False,
              'seconds':round(time.monotonic()-started,3),'steps':steps,'documentSha256':engine.editor_review_hash(actual)})
    return actual
