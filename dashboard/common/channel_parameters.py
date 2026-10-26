"""Approved schedule/presentation wiring; channel publishing engines stay unchanged."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from common.collection_observability import load, write

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'dashboard/data'
KST = ZoneInfo('Asia/Seoul')


def policy():
    value = json.loads((DATA / 'daily_schedule.json').read_text())
    datetime.strptime(value['effectiveDate'], '%Y-%m-%d')
    if value['timezone'] != 'Asia/Seoul' or len(value['cf']) != 16 or sum(len(x['slots']) for x in value['naver'].values()) != 7:
        raise ValueError('Expected KST, 16 CF domains and 7 Naver slots')
    for clock in list(value['cf'].values()) + [s for row in value['naver'].values() for s in row['slots']]:
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
            raise ValueError('Invalid schedule clock')
    return value


def styles(account, day=None):
    guide = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    match = re.search(r'```json:editor-parameters\s*\n(.*?)\n```', guide, re.S)
    if not match:
        raise ValueError('Missing guide presentation parameters')
    settings = json.loads(match[1])
    row = {**settings['default'], **settings.get('accounts', {}).get(account, {})}
    if any(row[key] not in (16, 19, 24, 28) for key in ('bodyFontSize', 'headingFontSize', 'summaryFontSize')):
        raise ValueError('Unsupported native font size')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', row['tableHeaderColor']):
        raise ValueError('Invalid table color')
    variant = load(DATA / 'synapse-recipes.json').get('styles', {}).get(account, {})
    if variant.get('effectiveDate', '9999') <= (day or datetime.now(KST).date().isoformat()):
        from dashboard.agents.style_strategy import FIELDS
        for key, value in variant.get('parameters', {}).items():
            if key in FIELDS and value in FIELDS[key]:
                row[key] = value
        row['styleVariantId'] = variant['styleVariantId']
    else:
        row['styleVariantId'] = 'style:naver:' + account + ':baseline'
    row['screenDriven'] = False
    return row


def styled_native(builder, original, document):
    from common.visible_naver_editor import displayed_document, text_style
    document = displayed_document(document)
    native = builder(original, document)
    params = document.get('presentation')
    if not params:
        return native
    for index, (block, component) in enumerate(zip(document['blocks'], native['document']['components'][1:])):
        ctype = component.get('@ctype')
        if ctype == 'quotation':
            component['layout'] = params['quoteStyle'] if params.get('quoteStyle') not in (None, 'none') else 'quotation_line'
            for paragraph in component.get('value') or []:
                paragraph.setdefault('style', {})['align'] = params.get('textAlign', 'left')
                for node in paragraph.get('nodes', []):
                    node.setdefault('style', {}).update(fontSizeCode=f"fs{params['bodyFontSize']}", bold=True)
            continue
        if ctype == 'table':
            for r_idx, row in enumerate(component.get('rows', [])):
                for cell in row.get('cells', []):
                    if r_idx == 0:
                        cell['backgroundColor'] = '#f1f5f9'
                    for paragraph in cell.get('value') or []:
                        paragraph.setdefault('style', {})['align'] = 'center' if r_idx == 0 else params.get('textAlign', 'left')
                        for node in paragraph.get('nodes', []):
                            node['style'] = {**node.get('style', {}), 'fontFamily': params.get('fontFamily', 'nanumgothic'), 'fontColor': params.get('fontColor', '#222222'), 'fontSizeCode': f"fs{params['bodyFontSize']}", 'bold': r_idx == 0, '@ctype': 'nodeStyle'}
            continue
        size, bold, align = text_style(params, index, block)
        block_params = {**params, **params.get('blockStyles', {}).get(str(index), {})}
        for paragraph in component.get('value') or []:
            paragraph.setdefault('style', {})['align'] = align
            if block_params.get('lineHeight'):
                paragraph['style']['lineHeight'] = block_params['lineHeight']
            for node in paragraph.get('nodes', []):
                node['style'] = {**node.get('style', {}), 'fontSizeCode': f'fs{size}', 'bold': bold, '@ctype': 'nodeStyle'}
                if block_params.get('fontFamily'):
                    node['style']['fontFamily'] = block_params['fontFamily']
                if block_params.get('fontColor'):
                    node['style']['fontColor'] = block_params['fontColor']
    return native


def summary_table(article, folder, params):
    """Delegate image asset creation to Google Flow Ultra instead of PIL text tables."""
    from common.flow_images import generate as flow_image
    return flow_image(article['title'], article.get('intro', ''), folder, custom_prompt=article.get('imagePrompt'))



def planning_or_memory(identity, topic, folder, params, channel='naver'):
    from dashboard.agents.style_strategy import plan_post
    try:
        return plan_post(identity, topic, folder, params, channel)
    except Exception as exc:
        result={'status':'fallback','keyword':topic,'writingGuide':'기존 지식그래프의 합의된 페르소나와 확인된 사실로 작성한다.','errorType':type(exc).__name__}
        Path(folder).mkdir(parents=True,exist_ok=True)
        write(Path(folder)/'strategy-status.json',result)
        return result


def configure_naver(day):
    import naver_blog_posting.posting as engine
    plan = policy()
    if not hasattr(engine, '_parameter_original_slots'):
        engine._parameter_original_slots = engine.DAILY_SLOTS.copy()
    if day < plan['effectiveDate']:
        engine.DAILY_SLOTS = engine._parameter_original_slots.copy()
    else:
        engine.DAILY_SLOTS = {key: tuple(row['slots']) for key, row in plan['naver'].items()}
    if getattr(engine, '_parameter_wiring', False):
        return engine
    prepare, builder, summary, attempt = engine.prepare_basic_content, engine.basic_native_document, engine.basic_summary_image, engine.write_attempt
    acquire_editor = engine.acquire_naver_editor

    def preserved_editor(context, pages, blog_id):
        screen_folder = engine.RUN_OPTIONS.get('screen_folder')
        if screen_folder:
            folder = Path(screen_folder)
            proof = load(folder / 'preserved-screen-editor.json')
            progress = load(folder / 'ego-screen-editor/screen-execution.json')
            target = proof.get('targetId') or progress.get('editorTargetId')
            if target and progress.get('written'):
                for candidate in context.pages:
                    session = context.new_cdp_session(candidate)
                    try:
                        identity = session.send('Target.getTargetInfo')['targetInfo']['targetId']
                    finally:
                        session.detach()
                    if identity != target:
                        continue
                    frame = candidate.frame(name='mainFrame') or candidate
                    actual = frame.evaluate("SmartEditor.getEditor('blogpc001').getDocumentData()")
                    if proof.get('documentSha256') and engine.editor_review_hash(actual) != proof['documentSha256']:
                        raise ValueError('Preserved editor changed outside the recorded checkpoint')
                    from common.visible_naver_editor import editor_content
                    if editor_content(actual)['title'] != load(folder / 'editor-content.json')['title']:
                        raise ValueError('Preserved editor title differs from this task')
                    return candidate, frame
                raise RuntimeError('Recorded EGO editor is unavailable; do not create a duplicate')
        page, frame = acquire_editor(context, pages, blog_id)
        pages.retain(page, 'EGO screen editor: preserve partial input and uncertain results')
        return page, frame

    def prepare_with_style(account, folder=None, topic=None):
        if folder is None:
            when = engine.RUN_OPTIONS.get('reserve_time') or day+' '+engine.RUN_OPTIONS.get('slot', engine.DAILY_SLOTS[account][0])
            folder = folder_for('naver_blog_posting', when[:10], account+'-'+when[-5:].replace(':',''))
            folder.mkdir(parents=True, exist_ok=True)
        params = styles(account, engine.RUN_OPTIONS.get('reserve_time', '')[:10] or day)
        # Existing approved artifacts remain byte-identical.
        existing = folder and (Path(folder) / 'editor-content.json').exists()
        incomplete_media = existing and not load(Path(folder) / 'editor-content.json').get('presentation') and not load(Path(folder) / 'reservation-evidence.json')
        engine.basic_summary_image = lambda article, output: summary_table(article, output, params) if params['summaryTable'] else summary(article, output)
        planning = {}
        planning = planning_or_memory(account, topic or engine.ACCOUNT_MAP[account]['topic'], folder, params)
        params.update(planning.get('presentation', {}))
        if not existing:
            topic = planning['keyword']
        from common import llm_client
        generate = llm_client.generate_json
        writing_rule = (
            '\n[절대 금지 가드레일(Never Do) — 나머지는 크루 자율 판단]\n'
            '- 허위 사실·근거 없는 수치 날조 금지\n'
            '- "AI 생성", "참고사진", "자료 부족으로 비교 불가", "공식 공고를 참고하세요" 같은 메타/면피 문구 금지\n'
        )
        llm_client.generate_json = lambda prompt, *args, **kwargs: generate(prompt+'\n[이번 발행의 지식그래프 스타일 설정 · 사실 근거와 구분]\n'+json.dumps({'parameters':params,'agreedWritingGuide':planning.get('writingGuide',''),'scope':'벤치마킹은 서식 참고이며 사실 근거는 research만 사용한다.'},ensure_ascii=False)+writing_rule, *args, **kwargs)
        try:
            result = prepare(account, folder, topic)
        finally:
            engine.basic_summary_image = summary
            llm_client.generate_json = generate
        if not existing or incomplete_media:
            article = load(result[1] / 'writer.json')
            main_kw = article.get('mainKeyword') or article.get('title', '주요 내용')
            from common.flow_images import generate as flow_image
            image = flow_image(article['title'], article['intro'], result[1], custom_prompt=article.get('imagePrompt'))
            raw_cap = (article.get('imageCaption') or f"{main_kw} 주요 포인트").replace('|', ' ').replace('｜', ' ').replace('\n', ' ').strip()
            hero_caption = raw_cap or f"{main_kw} 주요 포인트"
            hero_credit = main_kw or "핵심 정리"
            hero_asset = {'id': 0, 'file': image.name, 'description': hero_caption, 'credit': hero_credit, 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
            result[3]['assets'] = [hero_asset]
            result[3]['representative_file'] = image.name
            result[2]['blocks'] = [b for b in result[2]['blocks'] if b.get('type') != 'image']
            hero_block = {'type': 'image', 'id': 0, 'file': image.name, 'alt': hero_caption, 'caption': f"{hero_caption}｜{hero_credit}"}
            result[2]['blocks'].insert(1, hero_block)

            report = engine.validate_document(result[2], result[3], result[1] / 'images')
            if not report['ok']:
                raise ValueError('Document formatting invalid: ' + json.dumps(report['errors'], ensure_ascii=False))
            write(result[1] / 'photo-plan.json', result[3])
            write(result[1] / 'format-check.json', report)
            result[2]['planningId'] = planning.get('planningId')
            result[2]['presentation'] = {**params, 'guideSha256': hashlib.sha256((ROOT / 'AGENTS.md').read_bytes()).hexdigest()}
            write(result[1] / 'editor-content.json', result[2])
        elif existing:
            doc_blocks = result[2]['blocks']
            has_legacy_summary = any(b.get('type') == 'image' and b.get('file') == 'summary.png' for b in doc_blocks)
            if has_legacy_summary and not load(Path(folder) / 'reservation-evidence.json'):
                article = load(result[1] / 'writer.json') or {}
                main_kw = article.get('mainKeyword') or result[2].get('title', '주요 내용')
                from common.flow_images import generate as flow_image
                image = flow_image(result[2]['title'], article.get('intro', ''), result[1], custom_prompt=article.get('imagePrompt'))
                raw_cap = (article.get('imageCaption') or f"{main_kw} 주요 포인트").replace('|', ' ').replace('｜', ' ').replace('\n', ' ').strip()
                hero_caption = raw_cap or f"{main_kw} 주요 포인트"
                hero_credit = main_kw or "핵심 정리"
                hero_asset = {'id': 0, 'file': image.name, 'description': hero_caption, 'credit': hero_credit, 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
                result[3]['assets'] = [hero_asset]
                result[3]['representative_file'] = image.name
                result[2]['blocks'] = [b for b in doc_blocks if b.get('type') != 'image']
                result[2]['blocks'].insert(1, {'type': 'image', 'id': 0, 'file': image.name, 'alt': hero_caption, 'caption': f"{hero_caption}｜{hero_credit}"})
                report = engine.validate_document(result[2], result[3], result[1] / 'images')
                if report['ok']:
                    write(result[1] / 'photo-plan.json', result[3])
                    write(result[1] / 'format-check.json', report)
                    write(result[1] / 'editor-content.json', result[2])
        return result

    def dated_attempt(account, phase, *args, **kwargs):
        if phase == 'started' and kwargs.get('start_new', True) and engine.RUN_OPTIONS.get('reserve_time'):
            kwargs.setdefault('reserveTime', engine.RUN_OPTIONS['reserve_time'])
            kwargs.setdefault('publicationDate', engine.RUN_OPTIONS['reserve_time'][:10])
        return attempt(account, phase, *args, **kwargs)

    engine.prepare_basic_content = prepare_with_style
    engine.acquire_naver_editor = preserved_editor
    engine.basic_native_document = lambda original, document: styled_native(builder, original, document)
    from common.visible_naver_editor import bind, editor_content
    content_reader = engine.basic_editor_content
    engine.basic_editor_content = lambda value: editor_content(value, reader=content_reader)
    engine.bind_basic_editor = bind
    engine.write_attempt = dated_attempt
    engine._parameter_wiring = True
    return engine


def monitor(base=None, now=None):
    """Exclude tomorrow's advance reservations from today's counters without altering receipts."""
    import naver_blog_posting.posting as engine
    now = now or datetime.now(KST)
    day = now.date().isoformat()
    configure_naver(day)
    original = engine.read_journal
    journal = original(base or engine.BASE)
    records = []
    for row in journal['attempts']:
        planned = str(row.get('reserveTime') or row.get('publicationDate') or row.get('workDate') or '')[:10]
        if planned == day:
            records.append({**row, 'workDate': day})
    engine.read_journal = lambda *args, **kwargs: {**journal, 'attempts': records}
    try:
        result = engine.monitor(base or engine.BASE, now)
        plan = policy()
        result['schedulePolicy'] = {'effectiveDate': plan['effectiveDate'], 'naver': plan['naver']}
        write(DATA / 'naver/automation-status.json', result)
        return result
    finally:
        engine.read_journal = original


def folder_for(channel, day, identity):
    return ROOT / channel / 'output/scheduled' / day / identity


def run_naver(day, account, clock):
    from common import work_agenda as agendas
    if agendas.enabled():
        agendas.require(project='naver_blog')
        agendas.bind_target({'kind':'parameters','arguments':{'action':'naver','date':day,'account':account,'slot':clock}})
    when = datetime.strptime(day + ' ' + clock, '%Y-%m-%d %H:%M').replace(tzinfo=KST)
    if when.strftime('%Y-%m-%d %H:%M') != day + ' ' + clock:
        raise ValueError('Expected exact reservation date and clock')
    engine = configure_naver(day)
    folder = folder_for('naver_blog_posting', day, account + '-' + clock.replace(':', ''))
    if clock not in engine.DAILY_SLOTS[account]:
        contract = load(folder / 'style-reproduction-contract.json')
        directive = load(DATA / 'memory_graph.json').get('nodes', {}).get(contract.get('sourceDirectiveId'), {})
        if not (contract.get('status') == 'ready_for_screen_execution'
                and contract.get('account') == account and contract.get('reserveTime') == day + ' ' + clock
                and directive.get('active') is True and directive.get('sourceType') == 'direct_user_instruction'
                and directive.get('account') == account and directive.get('publicationDate') == day):
            raise ValueError('Unapproved account slot')
    receipt = load(folder / 'reservation-evidence.json')
    if receipt.get('submissionStatus') == 'verified_reserved' and not engine.needs_quality_revision(folder):
        return receipt
    if receipt.get('submissionStatus') not in ('submitting', 'submission_unknown') and when < datetime.now(KST) + timedelta(minutes=30):
        when = (datetime.now(KST) + timedelta(minutes=45)).replace(second=0, microsecond=0)
        when += timedelta(minutes=-when.minute % 10)
        clock = when.strftime('%H:%M')
    planning_or_memory(account, engine.ACCOUNT_MAP[account]['topic'], folder, styles(account, day))
    engine.RUN_OPTIONS.update(slot=clock, reserve_time=day + ' ' + clock, screen_folder=str(folder))
    result = engine.run_basic_pipeline(account, folder=folder, reserve_time=day + ' ' + clock)
    saved = load(folder / 'reserved-server-document.json')
    sizes = sorted({node.get('style', {}).get('fontSizeCode', '') for component in saved.get('document', {}).get('components', []) for paragraph in (component.get('value') or []) for node in paragraph.get('nodes', [])})
    write(folder / 'presentation-receipt.json', {'account': account, 'reserveTime': day + ' ' + clock, 'savedFontSizes': sizes, 'stylesVerified': bool(sizes) and {'fs'+str(styles(account)['bodyFontSize']), 'fs'+str(styles(account)['headingFontSize'])}.issubset(set(sizes)), 'parameters': load(folder / 'editor-content.json').get('presentation', {}), 'verifiedAt': datetime.now(KST).isoformat()})
    monitor()
    return result


def prepare_cf(day, domain):
    from common import work_agenda as agendas
    if agendas.enabled():agendas.require(project='cf_blog')
    import cf_posting.posting as cf
    plan=policy()
    if domain not in plan['cf'] or day<plan['effectiveDate']:raise ValueError('Unapproved CF preparation')
    prior=cf.load_current_schedule() if day == datetime.now(KST).date().isoformat() else load(cf.SCHEDULE_JSON)
    folder = folder_for('cf_posting', day, domain)
    folder.mkdir(parents=True, exist_ok=True)
    item = next((r for r in prior.get('items', []) if r.get('domain') == domain), {'domain': domain})
    if day == datetime.now(KST).date().isoformat() and item.get('status') == 'published' and item.get('publicUrl'):
        return {'state': 'published', 'preparationVerified': True, 'publicPublicationVerified': True,
                'publicUrl': item['publicUrl'], 'account': domain, 'date': day, 'folder': str(folder)}
    # Future research must never overwrite today's active ledger/progress.
    progress = cf.basic_progress
    cf.basic_progress = lambda domain, stage, name, pct, detail, **kw: write(folder / 'preparation-progress.json', {'domain': domain, 'stage': stage, 'detail': detail, 'updatedAt': datetime.now(KST).isoformat()})
    try:
        scheduled = {k: v for k, v in item.items() if k in ('domain', 'category')}
        planning = {}
        if not (folder / 'article.json').exists():
            planning = planning_or_memory(domain, str(scheduled.get('category') or domain), folder, {}, channel='cf')
            scheduled['mainKeyword'] = planning['keyword']
        from common import llm_client
        generate = llm_client.generate_json
        llm_client.generate_json = lambda prompt, *args, **kwargs: generate(prompt+'\n[직원 합의 작성 방식]\n'+planning.get('writingGuide',''), *args, **kwargs)
        try:
            article = cf.basic_article(domain, scheduled, folder)
        finally:
            llm_client.generate_json = generate
        if not article.get('imagePlans'):
            from common.flow_images import generate as flow_image
            from html import escape
            image = flow_image(article['title'], article['summary'], folder, custom_prompt=article.get('imagePrompt'))
            caption = (article.get('imageCaption') or f"{article.get('mainKeyword') or article['title']} 핵심 포인트").strip()
            article['imagePlans'] = [{'filename':image.name,'source':'generated','caption':caption}]
            article['contentHtml'] = '<figure><img src="{{IMAGE_0}}" alt="'+escape(caption)+'"><figcaption>'+escape(caption)+'</figcaption></figure>'+article['contentHtml']
            if planning:
                article['planningId'] = planning.get('planningId')
            cf.validate_basic_article(article)
            write(folder / 'article.json', article)
            write(folder / 'editor-content.json', article)
            write(folder / 'photo-plan.json', {'assets':article['imagePlans'],'medium':'google-flow','sha256':hashlib.sha256(image.read_bytes()).hexdigest()})
    finally:
        cf.basic_progress = progress
    article=load(folder/'article.json')
    assets=[(folder/'images'/p['filename'] if (folder/'images'/p['filename']).is_file() else folder/p['filename']) for p in article.get('imagePlans',[]) if isinstance(p,dict) and p.get('filename')]
    valid=bool(assets) and all(p.is_file() and p.stat().st_size>0 for p in assets)
    result = {'state':'prepared' if valid else 'preparation_unverified','preparationVerified':valid,
              'account':domain,'date':day,'folder':str(folder),
              'articleSha256':hashlib.sha256((folder/'article.json').read_bytes()).hexdigest(),
              'assetSha256':[hashlib.sha256(p.read_bytes()).hexdigest() for p in assets if p.is_file()]}
    if valid and day == datetime.now(KST).date().isoformat():
        with cf.cleaner_lock(wait_seconds=120, poll_interval=1) as acquired:
            if acquired:
                pub_receipt = cf.run_basic_posting(domain, folder)
                if isinstance(pub_receipt, dict) and (pub_receipt.get('publicPublicationVerified') or pub_receipt.get('status') == 'already_published'):
                    result.update(state='published', publicPublicationVerified=True, publicUrl=pub_receipt.get('publicUrl'), title=article.get('title'))
    return result


def _prepare_all(day):
    from common import work_agenda as agendas
    if agendas.enabled():
        from common.conference_dispatch import request
        return request('parameters',{'action':'prepare','date':day,'account':None,'slot':None})
    import cf_posting.posting as cf
    plan = policy()
    if day < plan['effectiveDate']:
        raise ValueError('Policy not effective for requested day')
    state = {'date': day, 'startedAt': datetime.now(KST).isoformat(), 'naver': {}, 'cf': {}, 'errors': {}}
    status_path = DATA / 'parameter-runtime.json'
    prior = load(cf.SCHEDULE_JSON)
    for account, row in plan['naver'].items():
        for clock in row['slots']:
            key = account + ' ' + clock
            try:
                run_naver(day, account, clock)
                state['naver'][key] = {'status': 'reserved', 'reserveTime': day + ' ' + clock}
            except Exception as exc:
                state['errors'][key] = type(exc).__name__ + ': ' + str(exc)[:180]
            write(status_path, state)
    for domain, clock in plan['cf'].items():
        try:
            result = prepare_cf(day, domain)
            state['cf'][domain] = {'status': result['state'], 'time': clock, 'folder': result['folder']}
        except Exception as exc:
            state['errors'][domain] = type(exc).__name__ + ': ' + str(exc)[:180]
        write(status_path, state)
    state['finishedAt'] = datetime.now(KST).isoformat()
    write(status_path, state)
    return state


def prepare_all(day):
    import fcntl
    from common.runtime_locks import runtime_lock_path
    lock = runtime_lock_path(DATA / 'parameters-prepare.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy'}
        return _prepare_all(day)


def dispatch_cf():
    from common import work_agenda as agendas
    if agendas.enabled():
        from common.conference_dispatch import request
        return request('parameters',{'action':'dispatch','date':None,'account':None,'slot':None},one=bool(agendas.current()))
    import cf_posting.posting as cf
    now = datetime.now(KST)
    day = now.date().isoformat()
    plan = policy()
    if day < plan['effectiveDate']:
        return {'status': 'not_effective'}
    with cf.cleaner_lock() as acquired:
        if not acquired:
            return {'status': 'busy'}
        schedule = cf.load_current_schedule()
        for item in schedule['items']:
            if item['domain'] in plan['cf'] and item.get('status') in ('waiting', 'pending', 'prepared'):
                item['scheduledTime'] = plan['cf'][item['domain']]
        cf.save_schedule_file(cf.SCHEDULE_JSON, schedule)
        for item in sorted(schedule['items'], key=lambda r: r['scheduledTime']):
            if item.get('status') == 'published' or item['scheduledTime'] > now.strftime('%H:%M'):
                continue
            folder = folder_for('cf_posting', day, item['domain'])
            prior = Path(item.get('artifactFolder') or '')
            if item.get('artifactFolder'):
                prior = prior if prior.is_absolute() else cf.BASE_DIR / prior
                if prior.resolve() != folder.resolve() and (prior / 'publication-receipt.json').exists():
                    folder = prior
            if not (folder / 'article.json').exists():
                continue
            planning_or_memory(item['domain'], load(folder / 'article.json').get('title', item['domain']), folder, {}, channel='cf')
            return cf.run_basic_posting(item['domain'], folder)
    return {'status': 'waiting'}


def main(argv=None, *, conference_worker=False):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'dispatch', 'monitor', 'cf-cycle', 'naver-cycle', 'naver', 'conference', 'cf', 'cf-prepare'))
    parser.add_argument('--date')
    parser.add_argument('--account')
    parser.add_argument('--slot')
    args = parser.parse_args(argv)
    if not conference_worker and args.action != 'monitor':
        from common.conference_dispatch import request
        result = request('parameters', vars(args))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result
    from common import work_agenda as agendas
    if agendas.enabled() and args.action!='monitor':
        row=agendas.require()
        target=(row.get('workTarget') or row.get('source') or {}).get('arguments',{})
        if target and any(target.get(k)!=vars(args).get(k) for k in ('action','date','account','slot')):
            raise agendas.AgendaWaiting('현재 안건의 날짜·계정·슬롯과 다른 실행입니다.')
    today = datetime.now(KST).date().isoformat()
    if (Path.home() / 'EGO_EXEC_DISABLED').exists() and args.action != 'monitor':
        raise RuntimeError('Execution disabled')
    if args.action == 'conference':
        day = args.date or today
        account = args.account
        clock = args.slot or configure_naver(day).DAILY_SLOTS[account][0]
        folder = folder_for('naver_blog_posting', day, account+'-'+clock.replace(':',''))
        result = planning_or_memory(account, '다음 발행의 키워드·독자·서식 결정', folder, styles(account, day))
    elif args.action == 'cf-prepare':
        result=prepare_cf(args.date or today,args.account)
    elif args.action == 'prepare':
        now = datetime.now(KST)
        target = now.date()
        result = prepare_all(args.date or max(target.isoformat(), policy()['effectiveDate']))
    elif args.action == 'monitor':
        result = monitor()
    elif args.action == 'naver':
        result = run_naver(args.date or today, args.account, args.slot or policy()['naver'][args.account]['slots'][0])
    elif args.action == 'naver-cycle':
        if today < policy()['effectiveDate']:
            naver = configure_naver(today)
            result = naver.basic_daily(1)
        else:
            result = {'status': 'timer_managed', 'owner': 'barolab-parameters-prepare.timer'}
    elif args.action == 'cf' or args.action == 'cf-cycle' and today < policy()['effectiveDate']:
        import cf_posting.posting as cf
        if agendas.enabled() and args.date!=today:raise ValueError('Original CF publication date expired; preserve the original agenda')
        schedule = cf.load_current_schedule()
        if args.action == 'cf' and args.account not in cf.ALL_DOMAINS:
            raise ValueError('Unknown CF domain')
        item = next((r for r in schedule.get('items', []) if (r['domain'] == args.account if args.action == 'cf' else cf.slot_due(r, datetime.now(KST)))), None)
        if item is None:
            result = {'status':'waiting'}
        else:
            folder = folder_for('cf_posting', today, item['domain'])
            topic = load(folder / 'article.json').get('title') or item.get('mainKeyword') or item.get('category') or item['domain']
            planning = planning_or_memory(item['domain'], topic, folder, {}, channel='cf')
            with cf.cleaner_lock() as acquired:
                if acquired:
                    from common import llm_client
                    generate = llm_client.generate_json
                    article_builder = cf.basic_article
                    llm_client.generate_json = lambda prompt, *a, **kw: generate(prompt+'\n[팀장 회의 실행안]\n'+planning['writingGuide'], *a, **kw)
                    cf.basic_article = lambda domain, item, folder: article_builder(domain, {**item, 'mainKeyword': planning['keyword']}, folder)
                    try:
                        result = cf.run_basic_posting(item['domain'], folder)
                    finally:
                        llm_client.generate_json = generate
                        cf.basic_article = article_builder
                else:
                    result = {'status':'busy'}
    else:
        result = dispatch_cf()
    print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
    return result


if __name__ == '__main__':
    main()
