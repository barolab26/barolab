"""Build blocks through the visible SmartEditor toolbar, keyboard and photo picker."""
import time

from common.collection_observability import write
from common.ego_telemetry import action


def bind(page, frame, document, plan, folder):
    import naver_blog_posting.posting as engine
    from common.ubuntu_naver_browser import focus_workflow_window
    from common.channel_parameters import styles
    from common.collection_observability import load

    started = time.monotonic()
    if not engine.blank_naver_document(frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")):
        raise ValueError('Existing editor draft preserved')
    identity = load(folder / 'identity.json')
    account = engine.ACCOUNT_MAP[identity['account']]
    focus_workflow_window(account['cdp_port'])
    page.bring_to_front()
    params = document.get('presentation') or styles(identity['account'])
    steps = []

    def click(locator, target='naver-toolbar'):
        with action('click', target):
            locator.click(timeout=10000)

    def select(name, value):
        click(frame.locator(f'button[data-name="{name}"]:not([data-role="option"])'))
        click(frame.locator(f'button[data-name="{name}"][data-role="option"][data-value="{value}"]'))

    def font(size, bold, align):
        select('font-size', 'fs' + str(size))
        toggle = frame.locator('button[data-name="bold"]')
        active = 'se-is-selected' in (toggle.get_attribute('class') or '')
        if active != bold:
            click(toggle)
        select('align-drop-down-with-justify', align)

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
            click(image.locator('.se-caption .se-text-paragraph'), 'naver-caption')
            type_lines(block['caption'], 'naver-caption')
            click(frame.locator('.se-component.se-text .se-text-paragraph').last, 'naver-body')
            steps.append({'block':index,'action':'photo-upload-and-caption','file':block['file']})
            continue
        heading = block['type'] == 'heading'
        size = params['headingFontSize'] if heading else params['summaryFontSize'] if index == 0 else params['bodyFontSize']
        font(size, heading or bool(block.get('emphasis')) or index == 0 and params['summaryBold'], 'center' if heading else params.get('textAlign', 'left'))
        type_lines(block['text'], 'naver-body')
        with action('press', 'naver-editor-key'):
            page.keyboard.press('Enter')
        steps.append({'block':index,'action':'keyboard-and-toolbar','fontSize':size,'bold':heading or bool(block.get('emphasis')) or index == 0 and params['summaryBold']})
    actual = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
    expected = engine.basic_native_document(actual, document)
    write(folder / 'bound-native-document.json', actual)
    write(folder / 'requested-native-document.json', expected)
    if engine.basic_editor_content(actual) != engine.basic_editor_content(expected):
        raise ValueError('Visible editor differs from supplied title/body/images/captions; submission stopped')
    observed = []
    for component in actual['document']['components']:
        if component.get('@ctype') != 'text':
            continue
        for paragraph in component.get('value', []):
            nodes = [n for n in paragraph.get('nodes', []) if n.get('value')]
            if nodes:
                observed.append((nodes, paragraph.get('style', {}).get('align', 'left')))
    expected_styles = []
    for index, block in enumerate(document['blocks']):
        if block['type'] == 'image':
            continue
        heading = block['type'] == 'heading'
        size = params['headingFontSize'] if heading else params['summaryFontSize'] if index == 0 else params['bodyFontSize']
        for text in block['text'].split('\n'):
            if text:
                expected_styles.append((size, heading or bool(block.get('emphasis')) or index == 0 and params['summaryBold'], 'center' if heading else params.get('textAlign','left')))
    if len(observed) != len(expected_styles):
        raise ValueError('Visible paragraph count differs from supplied document')
    for (nodes, align), (size, bold, expected_align) in zip(observed, expected_styles):
        if align != expected_align or any(n.get('style',{}).get('fontSizeCode') != 'fs'+str(size) or bool(n.get('style',{}).get('bold')) != bold for n in nodes):
            raise ValueError('Visible toolbar formatting not reflected in editor document')
    page.screenshot(path=str(folder / 'visible-editor.png'))
    write(folder / 'binding-receipt.json', {'mode':'visible-ui','nativeDocumentWrite':False,
          'seconds':round(time.monotonic()-started,3),'steps':steps,'documentSha256':engine.editor_review_hash(actual)})
    return actual
