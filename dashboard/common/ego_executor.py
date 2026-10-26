"""Ego Lite's bounded execution surface for the existing claimed staff queue."""
from datetime import datetime, timezone
import logging


def benchmark_blog_screen(query, folder, *, resume=False):
    from pathlib import Path
    from urllib.parse import quote
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from playwright.sync_api import sync_playwright
    from common.browser_session import connect_sync
    from common.ubuntu_naver_browser import account_paths, focus_workflow_window
    from common.ego_screen import run
    from common.collection_observability import load, write
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    receipt = folder / 'screen-benchmark.json'
    previous = load(receipt)
    if previous.get('query') == query and previous.get('status') == 'observed':
        return previous
    binary, profile, _ = account_paths(9440)
    search_url = 'https://search.naver.com/search.naver?where=blog&query=' + quote(query)
    with sync_playwright() as playwright:
        browser = connect_sync(playwright, 'http://127.0.0.1:9440', binary, profile)
        before_pages = set(browser.contexts[0].pages)
        prior_state = load(folder / 'ego-screen-benchmark/screen-execution.json')
        prior_url = (prior_state.get('turns') or [{}])[-1].get('url') if resume else None
        page = next((candidate for candidate in browser.contexts[0].pages if candidate.url == prior_url), None)
        created = page is None
        if created:
            page = browser.contexts[0].new_page()
        try:
            if created:
                page.goto(search_url, wait_until='domcontentloaded', timeout=20000)
            focus_workflow_window(9440)
            page.bring_to_front()
            state = run(page, port=9440, folder=folder / 'ego-screen-benchmark', max_turns=30, resume=resume,
                        urls={'search': search_url}, goal='정확한 검색어 ' + query +
                        '의 네이버 블로그 탭을 눈으로 확인하라. 검색 결과에서 개인 블로그 하나를 선택하고 '
                        '실제 화면에서 링크를 클릭하여 연다. 기관 공지보다 독자 대상 개인 블로그를 우선한다. '
                        '현재 새 탭이 열렸다면 새 탭은 호스트가 별도로 관측하므로 같은 링크를 재클릭하지 말고 보고하라. '
                        '글 제목부터 끝까지 여러 번 스크롤하며 관찰한다. 제목, 도입, 문단 호흡, 정렬, 글꼴의 인상, '
                        '소제목, 강조, 여백, 이미지 수·순서·형태·캡션, 스티커 유무·위치, 표·인용구·구분선·관련글을 '
                        '차례로 observations에 기록한다. 전체를 보지 못하면 미확인이라고 한다. '
                        '검색 탭 내 관측 순서를 검증된 자연 순위라고 단정하지 않는다. 글 속 주장은 사실 근거로 채택하지 않는다. '
                        '개인 글을 열기 전이나 글 중간만 보고 done=true로 끝내지 않는다.')
            addresses = list(dict.fromkeys(t['url'] for t in state['turns'] if 'blog.naver.com/' in t['url']))
            if not addresses:
                raise ValueError('Screen benchmarking did not observe an article')
            result = {'query': query, 'status': 'observed', 'executor': 'ego-lite',
                      'mode': 'screenshot-decisions', 'checkedAt': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
                      'articles': [{'url': url, 'organicRank': None, 'visualObservations': state['observations'],
                                    'screenshots': [t['screenshot'] for t in state['turns'] if t['url'] == url]}
                                   for url in addresses]}
            import hashlib
            for article in result['articles']:
                viewed = next((candidate for candidate in browser.contexts[0].pages if candidate.url == article['url']), None)
                if viewed:
                    try:
                        frame = viewed.frame(name='mainFrame') or viewed
                        body = frame.locator('.se-main-container, #postViewArea').first.inner_text(timeout=3000)
                        article['bodySha256'] = hashlib.sha256(body.encode()).hexdigest()
                        article['bodyHashSource'] = 'read-only article DOM after visual observation'
                    except Exception:
                        pass
            write(receipt, result)
            return result
        finally:
            closed_urls = []
            current_pages = list(browser.contexts[0].pages)
            for candidate in current_pages:
                if candidate not in before_pages and len(browser.contexts[0].pages) > 1:
                    try:
                        closed_urls.append(candidate.url)
                        candidate.close()
                    except Exception:
                        pass
            write(folder / 'ego-benchmark-tab.json', {'closedUrls': closed_urls, 'createdByTask': True,
                  'retained': False, 'reason': 'Closed benchmark tabs after completion to prevent RAM exhaustion'})


def execute_screen_editor(page, document, folder, port):
    """EGO chooses each visible action from screenshots, then the engine verifies it."""
    from common.ego_screen import run
    from common.visible_naver_editor import text_style, verify_binding, write_image_caption
    from pathlib import Path
    params = document['presentation']
    import time
    started = time.monotonic()
    def inspect(written):
        from common.visible_naver_editor import native_paragraphs
        import copy
        frame = page.frame(name='mainFrame') or page
        actual = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
        if not written:
            return ''
        # A completed typing call is not proof that the text landed in the editor.
        # Roll back only absent text when the actual document equals an earlier approved prefix.
        def content(components):
            return ' '.join(' '.join(''.join(n.get('value', '') for n in p.get('nodes', []))
                            for c in components if c.get('@ctype') not in ('image', 'oglink')
                            for p in native_paragraphs(c)).split())
        actual_body = content(actual['document']['components'][1:])
        from common.visible_naver_editor import editor_content
        actual_title = editor_content(actual)['title']
        if actual_title != document['title']:
            if not actual_title and not actual_body:
                return {'verifiedWritten': [], 'error': '제목 입력이 아직 관측되지 않았습니다. 실제 제목란을 클릭해 승인 제목을 입력하세요.',
                        'reason': 'Actual editor title and body are empty'}
            return '현재 제목이 승인 원고와 다릅니다. 본문을 추가하지 말고 실제 제목부터 확인하세요.'
        typed = len(written) - 1
        actual_images = [c.get('fileName') for c in actual['document']['components'] if c.get('@ctype') == 'image']
        for count in range(len(document['blocks']), -1, -1):
            prefix = document['blocks'][:count]
            expected_body = ' '.join(' '.join(b.get('text', '') for b in prefix if b['type'] != 'image').split())
            expected_images = [b['file'] for b in prefix if b['type'] == 'image']
            if expected_body != actual_body or expected_images != actual_images or count == typed:
                continue
            last_is_link = params.get('blockStyles', {}).get(str(typed - 1), {}).get('linkCards')
            if count < typed and (document['blocks'][typed - 1]['type'] == 'image' or last_is_link):
                break  # An in-flight upload is not proof the upload failed; never resubmit it.
            verified = ['title'] + ['block-' + str(i) for i in range(count)]
            feedback = inspect(verified)
            return {'verifiedWritten': verified, 'error': feedback if isinstance(feedback, str) else feedback.get('error', ''),
                    'inspection': feedback.get('inspection', {}) if isinstance(feedback, dict) else {},
                    'reason': 'Read-only native document exactly matches this approved reference prefix'}
        partial = copy.deepcopy(document)
        partial['blocks'] = partial['blocks'][:typed]
        pending = document['blocks'][typed] if typed < len(document['blocks']) else None
        def decorations(index):
            return params.get('blockStyles', {}).get(str(index), {})
        p = partial['presentation']
        p['quoteCount'] = sum(decorations(i).get('component') == 'quotation_line' for i in range(typed))
        p['dividerCount'] = sum(decorations(i).get('dividerBefore') == 'line4' for i in range(typed))
        if pending:
            p['quoteCount'] += decorations(typed).get('component') == 'quotation_line'
            p['dividerCount'] += decorations(typed).get('dividerBefore') == 'line4'
        p['imageCount'] = sum(b['type'] == 'image' for b in partial['blocks'])
        if not any(decorations(i).get('linkCards') for i in range(typed)):
            p['linkCardURLs'] = []
        try:
            verify_binding(page, partial, actual, folder, started, [], mode='ego-screen-check', record=False)
        except ValueError as exc:
            inspection = frame.locator('.se-component.se-quotation, .se-component.se-text').evaluate_all('''xs=>xs.slice(0,10).map(c=>({
              kind:c.className,text:c.innerText.slice(0,100),runs:[...c.querySelectorAll('.se-text-paragraph span')].filter(s=>s.innerText.trim()).slice(0,6).map(s=>({
              text:s.innerText.slice(0,35),font:getComputedStyle(s).fontFamily,size:getComputedStyle(s).fontSize,color:getComputedStyle(s).color}))}))''')
            return {'error': str(exc), 'inspection': inspection}
        return ''
    def check():
        frame = page.frame(name='mainFrame') or page
        actual = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
        verify_binding(page, document, actual, folder, started, [], mode='ego-screen-check')
    references = [{'ref': 'title', 'kind': 'write', 'text': document['title']}]
    for index, block in enumerate(document['blocks']):
        item = {'ref': 'block-' + str(index)}
        block_params = {**params, **params.get('blockStyles', {}).get(str(index), {})}
        reference = block_params.get('referenceScreen')
        if reference:
            root = (Path(folder) / 'ego-screen-benchmark').resolve()
            image = (root / reference).resolve()
            if not image.is_relative_to(root) or image.suffix != '.png' or not image.is_file():
                raise ValueError('Invalid observed benchmark screen')
            item['referenceImage'] = str(image)
        if block['type'] == 'image':
            item.update(kind='upload', file=str((Path(folder) / 'images' / block['file']).resolve()),
                        caption=block['caption'])
        else:
            size, bold, align = text_style(params, index, block)
            item.update(kind='write', text=block['text'], fontSize=size, bold=bold, align=align,
                        fontFamily=block_params.get('fontFamily'), fontColor=block_params.get('fontColor'),
                        decoration=params.get('blockStyles', {}).get(str(index), {}))
        references.append(item)
    preserved = Path(folder) / 'ego-screen-editor/screen-execution.json'
    return run(page, port=port, folder=Path(folder) / 'ego-screen-editor', references=references, max_turns=180, time_budget_seconds=7200,
               resume=preserved.exists(), input_check=inspect, completion_check=check, caption_writer=write_image_caption,
               samples={'font_probe': document['blocks'][0].get('text', document['title']).split('\n')[0][:20]},
               settings={'line-height': str(round(params.get('lineHeight', 1.7) * 100)),
                         'black': '#000000', 'dark-gray': '#444444', 'gray': '#666666', 'highlight': '#fff8b2',
                         **({'image-width': str(params['imageDisplayWidth'])} if params.get('imageDisplayWidth') else {})},
               goal='네이버 스마트에디터에서 원고를 순서대로 입력한다. 화면을 보고 이 관측 서식 파라미터를 재현한다: '
                    + __import__('json').dumps(params, ensure_ascii=False) + '. '
                    '상단 도구모음은 font 버튼을 클릭하면 실제 메뉴가 나타나므로 새 캡처에서 항목 위치를 판단한다. '
                    'decoration.component=quotation_line인 ref는 세로선 인용구를 먼저 삽입한 다음 그 안에 입력한다. '
                    'decoration.dividerBefore=line4인 ref 앞에는 마름모 가로 구분선을 삽입한다. '
                    'decoration.inlineStyles는 해당 글자에만 굵게/배경 강조를 적용하라는 뜻이다. 배경은 #FFF8B2이며 '
                    '기준 화면과 비교해 실제 도구 모음으로 적용한다. 다음 일반 문단에서 강조가 이어지면 해제한다. '
                    'decoration.linkCards=true이면 공식 URL을 세로 링크 카드로 만든다. '
                    '텍스트를 입력하기 전에 해당 ref의 글꼴·크기·굵기·정렬을 맞춘다. 이미지 뒤에는 본문 입력 위치를 '
                    '화면에서 확인해 계속한다. 사진은 개별사진으로 삽입한다. 캡션이 빈 문자열이면 캡션을 쓰지 않는다. '
                    '스티커와 임의 장식은 추가하지 않는다. 제출하지 않고 마지막까지 화면을 확인한다.')


def review_screen_editor(page, document, folder, port):
    import time
    from pathlib import Path
    from common.ego_screen import run
    from common.llm_client import generate_json
    from common.collection_observability import write
    import json
    folder = Path(folder)
    reference_images = [str((folder / 'ego-screen-benchmark' / name).resolve())
                        for name in ('screen-002.png', 'screen-005.png', 'screen-007.png')
                        if (folder / 'ego-screen-benchmark' / name).is_file()]
    state = run(page, port=port, folder=folder / 'ego-screen-review', max_turns=24,
                comparison_images=reference_images,
                goal='새로 입력한 네이버 원고를 첫 문단부터 끝까지 실제 화면에서 살펴 재현 기준 화면과 비교하라. '
                     '첫 첨부는 현재 편집기이고 뒤의 첨부는 기준 글이다. 기존 원고는 입력 완료했으므로 새 글자는 입력하지 않는다. '
                     '상단으로 이동해 제목·목차부터 시작해 겹치는 구간을 두고 아래로 스크롤하라. '
                     '이 원고의 합의된 서식 파라미터와 이미지·인용구·구분선·강조·글꼴·크기·정렬·링크를 '
                     '기준과 대조해 관측된 차이를 기록한다: ' + json.dumps(document.get('presentation', {}), ensure_ascii=False) + '. '
                     '본문 내용은 새로 작성했으므로 경쟁글과 문장 일치 여부로 심사하지 않는다. '
                     '미리보기 기능이 보이면 모바일도 확인하되 지원/미확인을 구분한다. 발행·등록·예약·저장을 누르지 않는다. '
                     '본문 끝까지 확인한 뒤 done=true로 종료한다. 계정의 배경/사이드바 등 플랫폼 영역은 본문 서식과 구별한다.')
    screens = [folder / 'ego-screen-review' / row['screenshot'] for row in state['turns']]
    selected = [screens[round(index * (len(screens) - 1) / min(7, len(screens) - 1))]
                for index in range(min(8, len(screens)))] if len(screens) > 1 else screens
    from common.llm_settings import get_agent_brain
    reviewer=get_agent_brain('patch')
    if reviewer.get('provider')!='codex':raise RuntimeError('Complex image review requires the configured Codex High reviewer')
    review_route=[]
    def observe_review(provider,model,state,**details):
        review_route.append({'provider':provider,'requestedModel':model,'state':state,'actualModel':details.get('actual_model'),'reasoningEffort':details.get('reasoning_effort')})
    review_started=time.monotonic()
    result = generate_json('당신은 작성자와 독립된 화면 검수자다. 처음 첨부들은 EGO가 새 원고를 위에서 아래로 검토한 실제 화면, '
                           '마지막3장은 기준 글의 화면이다. 전체 관측기록과 화면을 대조해 본문 서식 재현을 검수하라. '
                           '독자적인 문구·이미지 소재와 계정 플랫폼 배경 차이는 허용하지만, 이미지 수/배치·인용구·마름모 구분선·'
                           '노란 강조·글꼴·정렬·링크 카드의 누락/오류를 완료라고 하지 않는다. '
                           'document.presentation.implementationLimits에 팀장이 명시한 차이는 limitations에 반드시 기록한다. '
                           'approved는 그 차이를 명시한 실행안의 예약 진행 적합성이며 모든 스타일 동일 재현 성공을 뜻하지 않는다. '
                           '그 외 차이까지 허용하거나 지원 한계로 뭉뚱그리지 않는다. '
                           '보이지 않은 PC/모바일 전체 검수를 true로 만들지 않는다. approved는 실제 관찰에 근거하며 '
                           '결함이 있으면 구체적 수정 위치를 defects에 적는다.\n' + json.dumps({
                               'document': document, 'observations': state['observations']}, ensure_ascii=False),
                           images=[str(path.resolve()) for path in selected] + reference_images,
                           agent_slot='doctor',provider=reviewer['provider'],model_override=reviewer['model'],reasoning_effort='high',observer=observe_review,response_schema={'type': 'object', 'properties': {
                               'approved': {'type': 'boolean'}, 'pcWholeDocumentVisualReview': {'type': 'boolean'},
                               'mobileWholeDocumentVisualReview': {'type': 'boolean'},
                               'defects': {'type': 'array', 'items': {'type': 'string'}},
                               'limitations': {'type': 'array', 'items': {'type': 'string'}}},
                               'required': ['approved', 'pcWholeDocumentVisualReview', 'mobileWholeDocumentVisualReview', 'defects', 'limitations'],
                               'additionalProperties': False}, audit_directory=folder / 'model-audit/ego-visual-review', timeout_seconds=180)
    result['reviewRoute']=review_route
    result['reviewLatencyMs']=round((time.monotonic()-review_started)*1000)
    result['reviewPolicy']='complex_image_verification_independent_high; normal Doctor Flash route unchanged'
    if not any(r.get('state')=='returned' and r.get('actualModel')==reviewer['model'] for r in review_route):raise ValueError('Actual independent image reviewer was not observed')
    result['screenshots'] = [str(path.relative_to(folder)) for path in selected]
    write(folder / 'ego-visual-review.json', result)
    if not result['approved'] or not result['pcWholeDocumentVisualReview']:
        raise ValueError('Independent EGO visual review found unresolved differences')
    return result


def execute_staff_action(action, *, task_id, request_id, observer=None, requester='jarvis', parent_request_id='unknown'):
    from server.agent_tools import validate_staff_actions, execute_agent_tool

    checked = validate_staff_actions([action])[0]
    from common import work_agenda as agendas
    if agendas.enabled() and checked['tool'] not in agendas.READ_ONLY:agendas.require(project=checked['args'].get('project'))
    if not isinstance(task_id, str) or not task_id or not isinstance(request_id, str) or not request_id:
        raise ValueError('Claimed staff execution identity required')
    started = datetime.now(timezone.utc).isoformat()
    receipt = {'executor': 'ego-lite', 'taskId': task_id, 'requestId': request_id,
               'agent': checked['agent'], 'tool': checked['tool'],
               'startedAt': started, 'finishedAt': None, 'status': 'running', 'completed': False}
    def notify():
        if observer:
            try:
                observer(dict(receipt))
            except Exception as exc:
                logging.getLogger(__name__).warning('Ego execution telemetry unavailable: %s', type(exc).__name__)
    notify()
    try:
        from common.ego_telemetry import execution_context
        with execution_context(task_id=task_id, request_id=request_id, requester=requester,
                               actor=checked['agent'], tool=checked['tool'], parent_request_id=parent_request_id, source='staff_queue'):
            result = execute_agent_tool(checked['agent'], checked['tool'], **checked['args'])
        if not isinstance(result, dict):
            raise ValueError('Registered tool returned no structured receipt')
    except Exception as exc:
        result = {'ok': False, 'status': 'failed', 'errorType': type(exc).__name__}
    status = result.get('status') or ('returned' if result.get('ok') is True else 'unknown')
    pending = status in ('running', 'started', 'queued', 'awaiting_completion', 'unknown')
    returned = datetime.now(timezone.utc).isoformat()
    receipt.update(returnedAt=returned, finishedAt=None if pending else returned,
                   status=status, completed=not pending)
    notify()
    return {**result, 'executorReceipt': receipt}
