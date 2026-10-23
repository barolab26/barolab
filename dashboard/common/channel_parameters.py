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
    guide = (ROOT / 'naver_blog_posting/guides/blog_style.md').read_text()
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
    return row


def styled_native(builder, original, document):
    native = builder(original, document)
    params = document.get('presentation')
    if not params:
        return native
    for index, (block, component) in enumerate(zip(document['blocks'], native['document']['components'][1:])):
        size = params['headingFontSize'] if block['type'] == 'heading' else params['summaryFontSize'] if index == 0 else params['bodyFontSize']
        for paragraph in component.get('value', []):
            for node in paragraph.get('nodes', []):
                node.setdefault('style', {}).update(fontSizeCode=f'fs{size}')
                if block['type'] == 'heading' or index == 0 and params['summaryBold']:
                    node['style']['bold'] = True
    return native


def summary_table(article, folder, params):
    """Use the supported image block for a real two-column table, never fake native table JSON."""
    from PIL import Image, ImageDraw, ImageFont
    font_path = '/usr/share/fonts/truetype/nanum/NanumGothic.ttf'
    font = ImageFont.truetype(font_path, 44)
    heading = ImageFont.truetype(font_path, 52)
    width, pad, split = 1080, 28, 330
    canvas = Image.new('RGB', (width, 12000), 'white')
    draw = ImageDraw.Draw(canvas)

    def lines(text, limit):
        result, line = [], ''
        for char in text:
            if char == '\n' or draw.textlength(line + char, font=font) > limit:
                result.append(line)
                line = '' if char == '\n' else char
            else:
                line += char
        return result + ([line] if line else [])

    draw.rectangle((0, 0, width, 100), fill=params['tableHeaderColor'])
    draw.text((pad, 20), '핵심 내용 요약', font=heading, fill='white')
    y = 100
    for section in article['sections'][:3]:
        left = lines(section['heading'], split - pad * 2)
        # Preserve complete supplied sentences; an oversized image is an explicit error.
        right = lines(section['text'], width - split - pad * 2)
        height = max(len(left), len(right)) * 58 + pad * 2
        if y + height > 12000:
            raise ValueError('Summary table exceeds image size budget')
        draw.rectangle((0, y, split, y + height), fill='#f8fafc')
        for column, offset in ((left, pad), (right, split + pad)):
            for row, text in enumerate(column):
                draw.text((offset, y + pad + row * 58), text, font=font, fill='#172033')
        draw.line((0, y + height, width, y + height), fill='#cbd5e1', width=2)
        y += height
    path = folder / 'images/summary.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.crop((0, 0, width, y)).save(path)
    return path



def planning_or_memory(identity, topic, folder, params, channel='naver'):
    from dashboard.agents.style_strategy import plan_post
    try:
        return plan_post(identity, topic, folder, params, channel)
    except Exception as exc:
        # Keep the agenda pending; never publish through a failed conference.
        result={'status':'deferred','keyword':topic,'writingGuide':'기존 지식그래프의 합의된 페르소나와 확인된 사실로 작성한다.','errorType':type(exc).__name__}
        Path(folder).mkdir(parents=True,exist_ok=True)
        write(Path(folder)/'strategy-status.json',result)
        raise RuntimeError('Conference pending; retry the same agenda') from exc


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
        if not existing:
            topic = planning['keyword']
        from common import llm_client
        generate = llm_client.generate_json
        llm_client.generate_json = lambda prompt, *args, **kwargs: generate(prompt+'\n[이번 발행의 지식그래프 스타일 설정 · 사실 근거와 구분]\n'+json.dumps({'parameters':params,'agreedWritingGuide':planning.get('writingGuide',''),'scope':'벤치마킹은 서식 참고이며 사실 근거는 research만 사용한다.'},ensure_ascii=False), *args, **kwargs)
        try:
            result = prepare(account, folder, topic)
        finally:
            engine.basic_summary_image = summary
            llm_client.generate_json = generate
        if not existing or incomplete_media:
            from common.flow_images import generate as flow_image
            article = load(result[1] / 'writer.json')
            image = flow_image(article['title'], article['intro'], result[1])
            caption = '주제 이해를 돕는 개념 이미지'
            credit = 'Google Flow AI 생성'
            asset_id = max(a['id'] for a in result[3]['assets']) + 1
            result[3]['assets'].append({'id':asset_id,'file':image.name,'description':caption,'credit':credit,'sha256':hashlib.sha256(image.read_bytes()).hexdigest()})
            result[3]['representative_file'] = image.name
            result[2]['blocks'].insert(1, {'type':'image','id':asset_id,'file':image.name,'alt':caption,'caption':caption+'｜'+credit})
            report = engine.validate_document(result[2], result[3], result[1] / 'images')
            if not report['ok']:
                raise ValueError('Flow asset binding invalid')
            write(result[1] / 'photo-plan.json', result[3])
            write(result[1] / 'format-check.json', report)
            result[2]['planningId'] = planning.get('planningId')
            result[2]['presentation'] = {**params, 'tableRendering': 'summary-image', 'guideSha256': hashlib.sha256((ROOT / 'naver_blog_posting/guides/blog_style.md').read_bytes()).hexdigest()}
            write(result[1] / 'editor-content.json', result[2])
        return result

    def dated_attempt(account, phase, *args, **kwargs):
        if phase == 'started' and kwargs.get('start_new', True) and engine.RUN_OPTIONS.get('reserve_time'):
            kwargs.setdefault('reserveTime', engine.RUN_OPTIONS['reserve_time'])
            kwargs.setdefault('publicationDate', engine.RUN_OPTIONS['reserve_time'][:10])
        return attempt(account, phase, *args, **kwargs)

    engine.prepare_basic_content = prepare_with_style
    engine.basic_native_document = lambda original, document: styled_native(builder, original, document)
    from common.visible_naver_editor import bind
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
    engine = configure_naver(day)
    if clock not in engine.DAILY_SLOTS[account]:
        raise ValueError('Unapproved account slot')
    when = datetime.fromisoformat(day + 'T' + clock).replace(tzinfo=KST)
    folder = folder_for('naver_blog_posting', day, account + '-' + clock.replace(':', ''))
    receipt = load(folder / 'reservation-evidence.json')
    if receipt.get('submissionStatus') == 'verified_reserved':
        return receipt
    if receipt.get('submissionStatus') not in ('submitting', 'submission_unknown') and when < datetime.now(KST) + timedelta(minutes=30):
        raise ValueError('Approved reservation is too close; do not silently shift its time')
    planning_or_memory(account, engine.ACCOUNT_MAP[account]['topic'], folder, styles(account, day))
    engine.RUN_OPTIONS.update(slot=clock, reserve_time=day + ' ' + clock)
    result = engine.run_basic_pipeline(account, folder=folder, reserve_time=day + ' ' + clock)
    saved = load(folder / 'reserved-server-document.json')
    sizes = sorted({node.get('style', {}).get('fontSizeCode', '') for component in saved.get('document', {}).get('components', []) for paragraph in component.get('value', []) for node in paragraph.get('nodes', [])})
    write(folder / 'presentation-receipt.json', {'account': account, 'reserveTime': day + ' ' + clock, 'savedFontSizes': sizes, 'stylesVerified': bool(sizes) and {'fs'+str(styles(account)['bodyFontSize']), 'fs'+str(styles(account)['headingFontSize']), 'fs'+str(styles(account)['summaryFontSize'])}.issubset(set(sizes)), 'parameters': load(folder / 'editor-content.json').get('presentation', {}), 'verifiedAt': datetime.now(KST).isoformat()})
    monitor()
    return result


def _prepare_all(day):
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
            folder = folder_for('cf_posting', day, domain)
            folder.mkdir(parents=True, exist_ok=True)
            item = next((r for r in prior.get('items', []) if r.get('domain') == domain), {'domain': domain})
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
                    image = flow_image(article['title'], article['summary'], folder)
                    caption = '주제 이해를 돕는 AI 생성 개념 이미지'
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
            state['cf'][domain] = {'status': 'prepared', 'time': clock, 'folder': str(folder)}
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
    parser.add_argument('action', choices=('prepare', 'dispatch', 'monitor', 'cf-cycle', 'naver-cycle', 'naver', 'conference', 'cf'))
    parser.add_argument('--date')
    parser.add_argument('--account')
    parser.add_argument('--slot')
    args = parser.parse_args(argv)
    if not conference_worker and args.action != 'monitor':
        from common.conference_dispatch import request
        result = request('parameters', vars(args))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result
    today = datetime.now(KST).date().isoformat()
    if (Path.home() / 'EGO_EXEC_DISABLED').exists() and args.action != 'monitor':
        raise RuntimeError('Execution disabled')
    if args.action == 'conference':
        day = args.date or today
        account = args.account
        clock = args.slot or configure_naver(day).DAILY_SLOTS[account][0]
        folder = folder_for('naver_blog_posting', day, account+'-'+clock.replace(':',''))
        result = planning_or_memory(account, '다음 발행의 키워드·독자·서식 결정', folder, styles(account, day))
    elif args.action == 'prepare':
        now = datetime.now(KST)
        target = now.date() if now.hour < 6 else (now + timedelta(days=1)).date()
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
