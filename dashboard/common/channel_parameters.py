"""Approved schedule/presentation wiring; channel publishing engines stay unchanged."""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / 'dashboard' / 'server', ROOT / 'dashboard', ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common.collection_observability import load, write

DATA = ROOT / 'dashboard/data'
KST = ZoneInfo('Asia/Seoul')


def policy():
    value = json.loads((DATA / 'daily_schedule.json').read_text(encoding='utf-8'))
    datetime.strptime(value['effectiveDate'], '%Y-%m-%d')
    if value['timezone'] != 'Asia/Seoul' or not value.get('cf') or not value.get('naver'):
        raise ValueError('Expected KST and valid CF/Naver schedule definitions')
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
            is_heading = block.get('type') == 'heading'
            component['layout'] = 'quotation_underline' if is_heading else (params['quoteStyle'] if params.get('quoteStyle') not in (None, 'none') else 'quotation_line')
            q_size = params['headingFontSize'] if is_heading else params['bodyFontSize']
            q_align = params.get('headingAlign', 'center') if is_heading else params.get('textAlign', 'left')
            for paragraph in component.get('value') or []:
                paragraph.setdefault('style', {})['align'] = q_align
                for node in paragraph.get('nodes', []):
                    node.setdefault('style', {}).update(fontSizeCode=f"fs{q_size}", bold=True)
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
                is_link = bool(node.get('link'))
                node['style'] = {**node.get('style', {}), 'fontSizeCode': f'fs{size}', 'bold': True if is_link else bold, '@ctype': 'nodeStyle'}
                if block_params.get('fontFamily'):
                    node['style']['fontFamily'] = block_params['fontFamily']
                if is_link:
                    node['style']['fontColor'] = '#0068c3'
                    node['style']['underline'] = True
                elif block_params.get('fontColor'):
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
        if any(token in str(exc).lower() for token in ('user_takeover', 'ego_task_space', 'user control', 'user-owned', 'unassigned', 'inactive', 'ownership')):
            raise
        from common.asset_map import collect_used_naver_topics, select_verified_naver_keyword
        if channel == 'naver':
            used = collect_used_naver_topics(identity, days=14, current_folder=folder)
            topic = select_verified_naver_keyword(identity, topic, None, used, max_docs=5000)
        from common.naver_reader import POLICY
        result={'status':'fallback','keyword':topic,'writingGuide':POLICY,'errorType':type(exc).__name__}
        Path(folder).mkdir(parents=True,exist_ok=True)
        write(Path(folder)/'strategy-status.json',result)
        return result


def naver_slots_for_date(plan, day):
    from common.operating_plan import naver_slots
    naver_eff = plan.get('naverEffectiveDate')
    if naver_eff and day < naver_eff and plan.get('naverPrior'):
        return plan['naverPrior']
    return naver_slots(plan['naver'],day)


def configure_naver(day):
    import naver_blog_posting.posting as engine
    plan = policy()
    engine.RUN_OPTIONS['workflow_day'] = day
    if not hasattr(engine, '_parameter_original_slots'):
        engine._parameter_original_slots = engine.DAILY_SLOTS.copy()
    if day < plan['effectiveDate']:
        engine.DAILY_SLOTS = engine._parameter_original_slots.copy()
    else:
        nv_map = naver_slots_for_date(plan, day)
        engine.DAILY_SLOTS = {key: tuple(row['slots']) for key, row in nv_map.items()}
    if getattr(engine, '_parameter_wiring', False):
        return engine
    prepare, builder, summary, attempt = engine.prepare_basic_content, engine.basic_native_document, getattr(engine, 'basic_summary_image', summary_table), engine.write_attempt
    acquire_editor = engine.acquire_naver_editor
    show_reservations = engine.show_reservation_popup

    def preserve_tabs_after_reservation(*args, **kwargs):
        from common.naver_ab import CURRENT
        if CURRENT.get() is not None:
            # Verification already finished; displaying its result must not
            # navigate the account's first tab (which can contain a Kin draft).
            return {'status': 'preserved_existing_tabs'}
        return show_reservations(*args, **kwargs)

    engine.show_reservation_popup = preserve_tabs_after_reservation

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
        workflow_day = engine.RUN_OPTIONS.get('workflow_day') or day
        params = styles(account, workflow_day)
        # Existing approved artifacts remain byte-identical.
        existing = folder and (Path(folder) / 'editor-content.json').exists()
        incomplete_media = existing and not load(Path(folder) / 'editor-content.json').get('presentation') and not load(Path(folder) / 'reservation-evidence.json')
        engine.basic_summary_image = lambda article, output: summary_table(article, output, params) if params['summaryTable'] else summary(article, output)
        from common.naver_ab import normalize_saved_tags
        normalize_saved_tags(folder)
        writer = load(Path(folder) / 'writer.json')
        from common.naver_ab import plan as experiment_plan
        exp_day = workflow_day
        exp_slot = engine.RUN_OPTIONS.get('slot') or Path(folder).name[-4:-2]+':'+Path(folder).name[-2:]
        trial_plan = experiment_plan(account, topic, folder, exp_day, exp_slot) if not writer and not existing else None
        if writer:
            # A prepared article (including a maintenance revision) keeps its
            # topic; image recovery must not launch another keyword campaign.
            from common.naver_reader import POLICY
            planning = {**load(Path(folder) / 'planning.json'),
                        'keyword':writer.get('mainKeyword') or writer.get('title'),
                        'writingGuide':POLICY,'bridgeTarget':None}
        elif load(Path(folder) / 'workflow-assignment.json').get('workflowProtocol') == 'moneyhomepan-search-download-v2' and (Path(folder) / 'b-slotted-post.json').is_file():
            # A prepared B manuscript keeps its original topic and workflow;
            # do not send it through A's planning/style authoring on resumption.
            planning = load(Path(folder) / 'planning.json')
            if not planning.get('keyword'):
                raise ValueError('Prepared B manuscript is missing its original keyword')
        elif trial_plan:
            planning = trial_plan
        else:
            planning = planning_or_memory(account, topic or engine.ACCOUNT_MAP[account]['topic'], folder, params)
        params.update(planning.get('presentation', {}))
        if not existing:
            topic = planning['keyword']
        from common import llm_client
        generate = llm_client.generate_json
        from common.naver_reader import POLICY
        writing_rule = '\n' + POLICY
        llm_client.generate_json = lambda prompt, *args, **kwargs: generate(prompt + (('\n[이번 발행의 지식그래프 스타일 설정 · 크루 회의 합의안]\n'+json.dumps({'parameters':params,'agreedWritingGuide':planning.get('writingGuide',''),'scope':'벤치마킹은 서식 참고이며 사실 근거는 research만 사용한다.'},ensure_ascii=False)+writing_rule) if kwargs.get('agent_slot') == 'publi' and not kwargs.get('_skip_memory') else ''), *args, **kwargs)
        try:
            if folder and not existing and load(Path(folder) / 'reservation-evidence.json').get('submissionStatus') not in ('submitting', 'submission_unknown', 'verified_reserved'):
                ed_manifest = Path(folder) / 'editorial-images.json'
                if ed_manifest.is_file() and load(ed_manifest).get('status') != 'ready':
                    ed_manifest.unlink(missing_ok=True)
                    (Path(folder) / 'image-preparation-status.json').unlink(missing_ok=True)
            from common.naver_ab import assignment, scope
            exp_day = workflow_day
            exp_slot = engine.RUN_OPTIONS.get('slot') or Path(folder).name[-4:-2]+':'+Path(folder).name[-2:]
            experiment = assignment(account, folder, exp_day, exp_slot, create=True)
            with scope(experiment, folder):
                if experiment and experiment.get('workflowProtocol') == 'moneyhomepan-search-download-v2':
                    from common.naver_download_workflow import prepare as prepare_download
                    result = prepare_download(engine, account, folder, planning['keyword'])
                else:
                    result = prepare(account, folder, topic)
        finally:
            engine.basic_summary_image = summary
            llm_client.generate_json = generate
        if not existing or incomplete_media:
            report = engine.validate_document(result[2], result[3], result[1] / 'images')
            if not report['ok']:
                raise ValueError('Document formatting invalid: ' + json.dumps(report['errors'], ensure_ascii=False))
            result[2]['planningId'] = planning.get('planningId')
            pres = {**params, 'guideSha256': hashlib.sha256((ROOT / 'AGENTS.md').read_bytes()).hexdigest()}
            if result[2].get('lineLinks'):
                pres['lineLinks'] = result[2]['lineLinks']
            result[2]['presentation'] = pres
            result[3]['documentSha256'] = engine.document_fingerprint(result[2])
            write(result[1] / 'photo-plan.json', result[3])
            write(result[1] / 'format-check.json', report)
            write(result[1] / 'editor-content.json', result[2])
        return result

    def dated_attempt(account, phase, *args, **kwargs):
        if phase == 'started' and kwargs.get('start_new', True) and engine.RUN_OPTIONS.get('reserve_time'):
            kwargs.setdefault('reserveTime', engine.RUN_OPTIONS['reserve_time'])
            kwargs.setdefault('publicationDate', engine.RUN_OPTIONS['reserve_time'][:10])
        from common.naver_ab import journal_row
        identity=journal_row({'account':account,'artifactFolder':kwargs.get('artifactFolder') or engine.RUN_OPTIONS.get('screen_folder'),
                              'reserveTime':kwargs.get('reserveTime') or engine.RUN_OPTIONS.get('reserve_time'),
                              'phase':'metadata'})
        if identity.get('workflowSlotSource'):
            kwargs['scheduledSlot']=identity['scheduledSlot']
        return attempt(account, phase, *args, **kwargs)

    engine.prepare_basic_content = prepare_with_style
    engine.acquire_naver_editor = preserved_editor
    engine.basic_native_document = lambda original, document: styled_native(builder, original, document)
    from common.visible_naver_editor import bind, editor_content
    content_reader = engine.basic_editor_content
    engine.basic_editor_content = lambda value: editor_content(value, reader=content_reader)
    engine.bind_basic_editor = bind
    engine.write_attempt = dated_attempt
    from common.naver_ab import install_image_slots
    install_image_slots(engine)
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
        from common.naver_ab import journal_row
        row=journal_row(row)
        planned = str(row.get('reserveTime') or row.get('publicationDate') or row.get('workDate') or '')[:10]
        if planned == day:
            records.append({**row, 'workDate': day})
    engine.read_journal = lambda *args, **kwargs: {**journal, 'attempts': records}
    try:
        result = engine.monitor(base or engine.BASE, now)
        # Match failures to their exact planned slot, including before the editor
        # records scheduledSlot. The engine's account-level last row loses this.
        for account in result.get('accounts', []):
            for slot in account['slots']:
                slot['scheduledTime'] = day + ' ' + slot['slot']
                if slot['status'] == 'verified':
                    continue
                matches = [r for r in records if r.get('account') == account['account']
                           and engine._infer_scheduled_slot(r.get('artifactFolder'), r.get('scheduledSlot')) == slot['slot']]
                if matches and matches[-1].get('phase') == 'failed':
                    last = matches[-1]
                    slot.update(status='failed', publicationStatus='failed',
                                failureReason=last.get('failureReason'),
                                submissionStarted=last.get('submissionStarted'),
                                lastAttemptAt=last.get('updatedAt'))
                elif matches and matches[-1] is records[-1] and matches[-1].get('phase') == 'started' and engine.pipeline_busy(base or engine.BASE):
                    slot.update(status='running', publicationStatus='running',
                                submissionStarted=matches[-1].get('submissionStarted'))
            account['counts'] = {k: sum(s['status'] == k for s in account['slots']) for k in result['counts']}
            account['status'] = next((s['status'] for s in account['slots'] if s['status'] != 'verified'), 'verified')
        result['counts'] = {k: sum(a['counts'][k] for a in result['accounts']) for k in result['counts']}
        if os.name == 'nt':
            import subprocess
            try:
                observed = subprocess.run(['powershell', '-NoProfile', '-Command',
                    "$t=Get-ScheduledTask -TaskName 'BaroLab-Naver-Daily' -ErrorAction Stop; "
                    "$i=$t | Get-ScheduledTaskInfo; "
                    "@{registered=$true;enabled=($t.State.ToString() -ne 'Disabled');state=$t.State.ToString();"
                    "lastResult=$i.LastTaskResult;lastRunAt=$i.LastRunTime.ToString('o');nextRunAt=$i.NextRunTime.ToString('o')} | ConvertTo-Json -Compress"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                current = json.loads(observed.stdout) if observed.returncode == 0 else {}
                if current.get('registered'):
                    result['scheduler'] = {**current, 'taskName': 'BaroLab-Naver-Daily',
                        'source': 'Windows Scheduled Tasks read-only', 'checkedAt': now.isoformat()}
                    result['registration'] = 'registered' if current['enabled'] else 'disabled'
            except (OSError, ValueError, subprocess.TimeoutExpired):
                result['scheduler'] = {'status': 'unknown', 'checkedAt': now.isoformat(), 'source': 'Windows Scheduled Tasks'}
                result['registration'] = 'unknown'
        plan = policy()
        result['schedulePolicy'] = {
            'effectiveDate': plan['effectiveDate'],
            'naverEffectiveDate': plan.get('naverEffectiveDate'),
            'naverPrior': plan.get('naverPrior'),
            'naver': plan['naver'],
        }
        from common.naver_reader import observe_outcomes
        result['readerOutcomes'] = observe_outcomes(ROOT)
        from common.naver_ab import observe as observe_workflow_experiment
        if (DATA/'naver/workflow-experiment.json').is_file():
            result['workflowExperiment'] = observe_workflow_experiment()
        write(DATA / 'naver/automation-status.json', result)
        return result
    finally:
        engine.read_journal = original


def folder_for(channel, day, identity):
    return ROOT / channel / 'output/scheduled' / str(day).replace(':', '') / str(identity).replace(':', '')


def run_naver(day, account, clock):
    from common.naver_ownership import require_legacy_naver_submission_allowed
    require_legacy_naver_submission_allowed(ROOT)
    from common.naver_ab import protected_slot
    protected = protected_slot(account, day, clock)
    if protected:
        return {**protected, 'executionStatus': 'preserved_existing_slot'}
    from common import work_agenda as agendas
    if agendas.enabled():
        agendas.require(project='naver_blog')
        agendas.bind_target({'kind':'parameters','arguments':{'action':'naver','date':day,'account':account,'slot':clock}})
    when = datetime.strptime(day + ' ' + clock, '%Y-%m-%d %H:%M').replace(tzinfo=KST)
    if when.strftime('%Y-%m-%d %H:%M') != day + ' ' + clock:
        raise ValueError('Expected exact reservation date and clock')
    engine = configure_naver(day)
    folder = folder_for('naver_blog_posting', day, account + '-' + clock.replace(':', ''))
    from common.naver_ab import experiment_folder
    folder = experiment_folder(folder, account, day, clock)
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
    original_slot = clock
    reserve_dt = when
    if receipt.get('submissionStatus') not in ('submitting', 'submission_unknown') and when < datetime.now(KST) + timedelta(minutes=55):
        reserve_dt = (datetime.now(KST) + timedelta(minutes=65)).replace(second=0, microsecond=0)
        reserve_dt += timedelta(minutes=-reserve_dt.minute % 10)
    reserve_target = reserve_dt.strftime('%Y-%m-%d %H:%M')
    from common.operating_plan import topic as allocated_topic
    planning_or_memory(account, allocated_topic('naver_blog',account,day,clock) or engine.ACCOUNT_MAP[account]['topic'], folder, styles(account, day))
    engine.RUN_OPTIONS.update(slot=original_slot, reserve_time=reserve_target, screen_folder=str(folder))
    from common.naver_ab import assignment, scope
    experiment=assignment(account,folder,day,clock,create=True)
    with scope(experiment,folder):
        result = engine.run_basic_pipeline(account, folder=folder, reserve_time=reserve_target)
    saved = load(folder / 'reserved-server-document.json')
    sizes = sorted({node.get('style', {}).get('fontSizeCode', '') for component in saved.get('document', {}).get('components', []) for paragraph in (component.get('value') or []) for node in paragraph.get('nodes', [])})
    write(folder / 'presentation-receipt.json', {'account': account, 'reserveTime': day + ' ' + clock, 'savedFontSizes': sizes, 'stylesVerified': bool(sizes) and {'fs'+str(styles(account)['bodyFontSize']), 'fs'+str(styles(account)['headingFontSize'])}.issubset(set(sizes)), 'parameters': load(folder / 'editor-content.json').get('presentation', {}), 'verifiedAt': datetime.now(KST).isoformat()})
    monitor()
    return result


def cf_prepared_images_verified(article, folder):
    """Readiness follows source evidence, including an explicit text-only decision."""
    from cf_posting.posting import verify_article_images
    try:
        verify_article_images(article, folder)
    except (ValueError, OSError, KeyError, TypeError):
        return False
    return True


def prepare_cf(day, domain, *, publish_if_due=True):
    from common import work_agenda as agendas
    if agendas.enabled():agendas.require(project='cf_blog')
    import cf_posting.posting as cf
    plan=policy()
    if domain not in plan['cf'] or day<plan['effectiveDate']:raise ValueError('Unapproved CF preparation')
    prior=cf.load_current_schedule() if day == datetime.now(KST).date().isoformat() else load(cf.SCHEDULE_JSON)
    item = next((r for r in prior.get('items', []) if r.get('domain') == domain), {'domain': domain})
    from common.operating_plan import cf_folder
    folder = cf_folder(item,day,folder_for('cf_posting',day,domain))
    folder.mkdir(parents=True, exist_ok=True)
    if day == datetime.now(KST).date().isoformat() and item.get('status') == 'published' and item.get('publicUrl'):
        return {'state': 'published', 'preparationVerified': True, 'publicPublicationVerified': True,
                'publicUrl': item['publicUrl'], 'account': domain, 'date': day, 'folder': str(folder)}
    # Future research must never overwrite today's active ledger/progress.
    progress = cf.basic_progress
    cf.basic_progress = lambda domain, stage, name, pct, detail, **kw: write(folder / 'preparation-progress.json', {'domain': domain, 'stage': stage, 'detail': detail, 'updatedAt': datetime.now(KST).isoformat()})
    try:
        from common.asset_map import CF_DOMAINS
        cf_info = CF_DOMAINS.get(domain, {})
        used_today = []
        for r in prior.get('items', []):
            if r.get('domain') != domain:
                for k in ('title', 'mainKeyword', 'slug'):
                    if r.get(k) and r.get(k) not in used_today:
                        used_today.append(str(r.get(k)))
        day_root = ROOT / 'cf_posting/output/scheduled' / str(day).replace(':', '')
        if day_root.is_dir():
            for peer_dir in day_root.iterdir():
                if peer_dir.is_dir() and peer_dir.name != domain:
                    for fn, fk in (('planning.json', 'keyword'), ('article.json', 'title')):
                        pdata = load(peer_dir / fn)
                        if pdata.get(fk) and pdata.get(fk) not in used_today:
                            used_today.append(str(pdata.get(fk)))
        scheduled = {k: v for k, v in item.items() if k in ('domain', 'category')}
        domain_topic = item.get('mainKeyword') or (f"{cf_info['niche']} ({cf_info['desc']})" if cf_info else str(scheduled.get('category') or domain))
        planning = load(folder / 'planning.json') if (folder / 'planning.json').is_file() else {}
        if not (folder / 'article.json').exists():
            planning = planning_or_memory(domain, domain_topic, folder, {'usedKeywordsToday': used_today}, channel='cf')
            scheduled['mainKeyword'] = planning['keyword']
        elif planning.get('keyword'):
            scheduled['mainKeyword'] = planning['keyword']
        from common import llm_client
        generate = llm_client.generate_json
        cf_writing_rule = '\n'+json.dumps({
            'domain':domain,'readerTopic':domain_topic,'persona':cf_info.get('persona'),
            'recentlyUsedTopics':used_today,
            'editorialAuthority':'Choose structure, length, tone and visuals to solve the reader task and test the business hypothesis; no fixed table, paragraph or image count.'},ensure_ascii=False)
        llm_client.generate_json = lambda prompt, *args, **kwargs: generate(prompt + (('\n[크루 회의 합의 작성 방식]\n'+planning.get('writingGuide','')+cf_writing_rule) if kwargs.get('agent_slot') == 'cf_pipeline' else ''), *args, **kwargs)
        try:
            article = cf.basic_article(domain, scheduled, folder)
        finally:
            llm_client.generate_json = generate
        article = cf.ensure_article_images(article, folder, domain=domain)
        from common.content_quality import ensure_publication_review
        ensure_publication_review(article, folder, generate=generate)
        if planning and not article.get('planningId'):
            article['planningId'] = planning.get('planningId')
            write(folder / 'article.json', article)
            write(folder / 'editor-content.json', article)
    finally:
        cf.basic_progress = progress
    article=load(folder/'article.json')
    assets=[(folder/'images'/p['filename'] if (folder/'images'/p['filename']).is_file() else folder/p['filename']) for p in article.get('imagePlans',[]) if isinstance(p,dict) and p.get('filename')]
    valid=cf_prepared_images_verified(article, folder)
    result = {'state':'prepared' if valid else 'preparation_unverified','preparationVerified':valid,
              'account':domain,'date':day,'folder':str(folder),
              'articleSha256':hashlib.sha256((folder/'article.json').read_bytes()).hexdigest(),
              'assetSha256':[hashlib.sha256(p.read_bytes()).hexdigest() for p in assets if p.is_file()]}
    if publish_if_due and valid and day == datetime.now(KST).date().isoformat() and cf.slot_due(item, datetime.now(KST)):
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
    from common.naver_ownership import legacy_naver_submission_allowed
    if legacy_naver_submission_allowed(ROOT):
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
    from common import runtime_locks as fcntl
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
    with cf.cleaner_lock(wait_seconds=60, poll_interval=1) as acquired:
        if not acquired:
            return {'status': 'busy'}
        schedule = cf.load_current_schedule()
        for item in schedule['items']:
            if item['domain'] in plan['cf'] and not item.get('allocationId') and item.get('status') in ('waiting', 'pending', 'prepared'):
                item['scheduledTime'] = plan['cf'][item['domain']]
        cf.save_schedule_file(cf.SCHEDULE_JSON, schedule)
        for item in sorted(schedule['items'], key=lambda r: r['scheduledTime']):
            if item.get('status') == 'published' or item['scheduledTime'] > now.strftime('%H:%M'):
                continue
            from common.operating_plan import cf_folder
            folder = cf_folder(item,day,folder_for('cf_posting',day,item['domain']))
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
    if args.action in ('naver', 'naver-cycle', 'conference'):
        from common.naver_ownership import require_legacy_naver_submission_allowed
        require_legacy_naver_submission_allowed(ROOT)
    if not conference_worker and args.action == 'naver-cycle':
        from common.naver_ab import cycle as workflow_cycle
        result = workflow_cycle()
        if result is not None:
            print(json.dumps(result, ensure_ascii=False), flush=True)
            return result
    if not conference_worker and args.action != 'monitor':
        from common.conference_dispatch import request
        result = request('parameters', vars(args))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result
    from common import work_agenda as agendas
    if agendas.enabled() and args.action!='monitor':
        row=agendas.require()
        target=(row.get('workTarget') or row.get('source') or {}).get('arguments',{})
        if target and args.action not in ('cf-cycle', 'naver-cycle') and any(target.get(k)!=vars(args).get(k) for k in ('action','date','account','slot')):
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
        current=load(DATA/'cf/daily_schedule.json')
        item=next((r for r in current.get('items',[]) if r.get('domain')==args.account),{})
        if item.get('allocationId') and args.slot!=item.get('scheduledTime'):
            raise ValueError('CF allocation changed; preserve original request for reconciliation')
        result=prepare_cf(args.date or today,args.account,publish_if_due=False)
    elif args.action == 'prepare':
        now = datetime.now(KST)
        target = now.date()
        result = prepare_all(args.date or max(target.isoformat(), policy()['effectiveDate']))
    elif args.action == 'monitor':
        result = monitor()
    elif args.action == 'naver':
        result = run_naver(args.date or today, args.account, args.slot or policy()['naver'][args.account]['slots'][0])
    elif args.action == 'naver-cycle':
        if os.name == 'nt' or today < policy()['effectiveDate']:
            naver = configure_naver(today)
            result = naver.basic_daily(1)
        else:
            result = {'status': 'timer_managed', 'owner': 'barolab-parameters-prepare.timer'}
    elif args.action == 'cf' or (args.action == 'cf-cycle' and (os.name == 'nt' or today < policy()['effectiveDate'])):
        import cf_posting.posting as cf
        if agendas.enabled() and args.date!=today:raise ValueError('Original CF publication date expired; preserve the original agenda')
        schedule = cf.load_current_schedule()
        if args.action == 'cf' and args.account not in cf.ALL_DOMAINS:
            raise ValueError('Unknown CF domain')
        item = next((r for r in schedule.get('items', []) if (r['domain'] == args.account if args.action == 'cf' else cf.slot_due(r, datetime.now(KST)))), None)
        if item is None:
            result = {'status':'waiting'}
        else:
            if args.action=='cf' and args.slot and args.slot!=item.get('scheduledTime'):
                raise ValueError('CF slot identity changed; no publication attempted')
            from common.asset_map import CF_DOMAINS
            cf_info = CF_DOMAINS.get(item['domain'], {})
            used_today = [str(r.get(k)) for r in schedule.get('items', []) if r.get('domain') != item['domain'] for k in ('title', 'mainKeyword', 'slug') if r.get(k)]
            from common.operating_plan import cf_folder
            folder = cf_folder(item,today,folder_for('cf_posting',today,item['domain']))
            topic = load(folder / 'article.json').get('title') or item.get('mainKeyword') or (f"{cf_info['niche']} ({cf_info['desc']})" if cf_info else item['domain'])
            planning = planning_or_memory(item['domain'], topic, folder, {'usedKeywordsToday': used_today}, channel='cf')
            with cf.cleaner_lock(wait_seconds=120, poll_interval=1) as acquired:
                if acquired:
                    from common import llm_client
                    generate = llm_client.generate_json
                    article_builder = cf.basic_article
                    llm_client.generate_json = lambda prompt, *a, **kw: generate(
                        prompt+('\n[팀장 회의 실행안]\n'+planning['writingGuide'] if kw.get('agent_slot')=='cf_pipeline' else ''), *a, **kw)
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
