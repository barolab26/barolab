"""Timers request conferences; the existing crew consumer owns execution."""
import argparse
import hashlib
import json
import re
import os
from pathlib import Path
import subprocess
import sys
import time
from common.collection_observability import load, write, locked

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / 'dashboard/data/publication-conferences'


def request(kind, arguments, *, one=False):
    from common import work_agenda as agendas
    if not agendas.enabled():return _request_single(kind,arguments)
    choices=concrete_requests(kind,arguments)
    if not choices:return {'status':'no_work','reason':'no_eligible_concrete_work'}
    receipts=[]
    for item in choices[:1] if one else choices:
        receipts.append(_request_single(kind,item))
    return receipts[0] if len(receipts)==1 else {'status':'conference_requested','items':receipts,'count':len(receipts)}


def concrete_requests(kind, arguments):
    from datetime import datetime,timedelta
    from common.channel_parameters import KST,policy,folder_for
    now=datetime.now(KST);today=now.date().isoformat()
    if kind=='parameters':
        action=arguments.get('action');plan=policy()
        if action=='cf' and arguments.get('account') in plan['cf']:
            arguments={**arguments,'slot':arguments.get('slot') or plan['cf'][arguments['account']]}
        if action in ('naver','cf','cf-prepare','conference'):
            return [{**arguments,'date':arguments.get('date') or today}]
        result=[]
        if action in ('prepare','naver-cycle'):
            day=arguments.get('date') or today
            day=max(day,plan['effectiveDate'])
            from naver_blog_posting.posting import needs_quality_revision
            for account,settings in plan['naver'].items():
                for slot in settings['slots']:
                    slot_folder=folder_for('naver_blog_posting',day,account+'-'+slot.replace(':',''))
                    receipt=load(slot_folder/'reservation-evidence.json')
                    if receipt.get('submissionStatus')=='verified_reserved' and not needs_quality_revision(slot_folder):continue
                    result.append({'action':'naver','date':day,'account':account,'slot':slot})
            if action=='prepare':
                import cf_posting.posting as cf_engine
                sched = cf_engine.load_current_schedule() if day == today else load(ROOT/'dashboard/data/cf/daily_schedule.json')
                pub_domains = {r.get('domain') for r in sched.get('items', []) if r.get('status') == 'published' and r.get('publicUrl')}
                for domain,slot in plan['cf'].items():
                    if domain in pub_domains:
                        continue
                    folder=folder_for('cf_posting',day,domain)
                    pub_rec = load(folder/'publication-receipt.json')
                    if pub_rec.get('state') == 'published' and pub_rec.get('publicPublicationVerified'):
                        continue
                    result.append({'action':'cf-prepare','date':day,'account':domain,'slot':slot})
        elif action in ('dispatch','cf-cycle'):
            import cf_posting.posting as cf_engine
            schedule=cf_engine.load_current_schedule()
            for item in sorted(schedule.get('items',[]),key=lambda r:r.get('scheduledTime','')):
                domain=item.get('domain');slot=plan['cf'].get(domain)
                folder=folder_for('cf_posting',today,domain)
                if slot and (folder/'photo-plan.json').exists() and item.get('status') not in ('published','failed','error'):
                    result.append({'action':'cf','date':today,'account':domain,'slot':slot})
        return result
    if kind=='kin':
        if arguments.get('account') and arguments.get('slot'):return [arguments]
        state=load(ROOT/'dashboard/data/kin-automation-state.json')
        due=state.get('nextEligibleAt');account=state.get('nextAccount')
        if not due or not account or state.get('activeRunId') or state.get('enabled') is False:return []
        when=datetime.fromisoformat(due)
        if when>now:return []
        return [{'date':today,'account':account,'slot':due}]
    if kind=='threads':
        if arguments.get('account') and arguments.get('slot'):return [arguments]
        import sqlite3
        import threads_posting.posting as engine
        config=engine._threads_config_load()
        if not config.get('enabled') or not config.get('connection',{}).get('connected'):return []
        try:day=engine._threads_pipeline__gate(config,now)
        except RuntimeError:return []
        with sqlite3.connect(Path(engine._threads_config_DB).resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            parts=db.execute("SELECT * FROM parts WHERE account_key=? AND publication_date=?",(config['account_key'],day)).fetchall()
            latest=engine._threads_scheduler_current_slot(config,now)
            for part in parts:
                due=part['kind']=='main' and part['slot']==latest
                if part['kind']=='followup':
                    parent=next((p for p in parts if p['attempt_id']==part['attempt_id'] and p['kind']=='main' and p['state']=='published_verified'),None)
                    due=bool(parent and engine._threads_pipeline_is_followup_delay_satisfied(parent,json.loads(part['document']),now))
                if part['state']=='queued' and part['slot']<=now.strftime('%H:%M') and due:
                    return [{'date':day,'account':config['account_key'],'slot':part['slot'],'partId':part['part_id']}]
            used={r['slot'] for r in parts}
            used.update(r[0] for r in db.execute('SELECT slot FROM authoring_slots WHERE account_key=? AND day=?',(config['account_key'],day)))
            slot=engine._threads_scheduler_current_slot(config,now,used)
            attempted=sum(p['kind']=='main' and p['state'] in ('sending_intent','submitted_unknown','api_submitted','published_verified') for p in parts)
            if slot and attempted<config['mainDailyCap']:
                return [{'date':day,'account':config['account_key'],'slot':slot}]
        return []
    raise ValueError('Unknown conference channel')


CHANNEL_PURPOSES = {
    'naver_blog': '소모성 비실명 블로그: 본진 리스크 방어 및 네이버 검색 트래픽을 CF 블로그(애드센스)로 토스하는 유입 브릿지. 계정 사리기보다 노출과 클릭 유도가 핵심 목적.',
    'cf_blog': '핵심 캐시카우 (하루  애드센스 수익 기지): 양질의 정보와 체류시간 확보, 고단가 광고 배치 최적화 및 외부 유입 트래픽 흡수가 핵심 목적.',
    'threads': 'SNS 고속 유입 채널: 피드 후킹과 첫 댓글 브릿지를 통해 CF 블로그로 대량 트래픽을 넘기는 것이 핵심 목적.',
    'naver_kin': '지식인 맞춤형 솔루션 제공 및 CF 블로그 신뢰 유입을 만드는 전초기지.',
}


def _request_single(kind, arguments):
    if kind not in ('parameters', 'kin', 'threads'):
        raise ValueError('Unknown conference channel')
    QUEUE.mkdir(parents=True, exist_ok=True)
    # Repeated timer ticks share one pending agenda, including model retries.
    key = hashlib.sha256(json.dumps([kind, arguments], sort_keys=True).encode()).hexdigest()
    path = QUEUE / (key + '.json')
    from common import work_agenda as agendas
    business = None
    if agendas.enabled():
        project = {'kin':'naver_kin','threads':'threads'}.get(kind, 'naver_blog' if arguments.get('action')=='naver' else 'cf_blog')
        target = {'kind':kind,'arguments':arguments}
        agendas.bind_target(target)
        title = {'naver_blog':'네이버 예약','cf_blog':'CF 글 준비' if arguments.get('action')=='cf-prepare' else 'CF 발행','naver_kin':'지식인 답변','threads':'Threads 게시'}[project]+' · '+' · '.join(str(arguments[k]) for k in ('account','date','slot') if arguments.get(k))
        purpose = CHANNEL_PURPOSES.get(project, '하루  수익 달성에 기여하는 채널 콘텐츠 생산 및 트래픽 유입')
        business = agendas.propose('conference',target,title=title,project=project,
            source={'conferenceId':key,'kind':kind,'arguments':arguments,'businessPurpose':purpose},
            completion='이 글의 승인 원고·이미지 준비 증거 확인' if arguments.get('action')=='cf-prepare' else '지정 계정·날짜·슬롯의 실제 예약 또는 공개 게시 증거 확인',
            priority=0)
    with locked(QUEUE):
        row = load(path)
        if business and row:
            previous=row.get('businessAgendaId')
            if previous and previous!=business and row['status'] not in ('completed',):
                with locked(agendas.ROWS):
                    prior=agendas.get(previous);state=load(agendas.STATE)
                    if prior.get('status')!='queued' or prior.get('activatedAt') or prior.get('kind')!='conference':
                        raise agendas.AgendaWaiting('원래 안건의 실행·복구 권한을 유지합니다. 해당 안건을 이어서 처리해야 합니다.')
                    prior.update(status='linked',parentAgendaId=business);agendas._save(prior)
                    state['pending']=[i for i in state.get('pending',[]) if i!=previous];write(agendas.STATE,state)
                    row['businessAgendaId']=business;write(path,row)
            if not row.get('businessAgendaId'):
                row['businessAgendaId']=business;write(path,row)
            biz_row = agendas.get(business)
            if row.get('status') in ('failed', 'unknown') and biz_row and biz_row.get('status') == 'queued' and not biz_row.get('verification', {}).get('verified'):
                row.update(status='queued', retryAt=0, attempts=1, requestedAt=time.time())
                for k in ('errorType', 'failureReason', 'failureDiagnostic', 'failureReport', 'interruptedAt', 'completedAt'):
                    row.pop(k, None)
                write(path, row)
                return {'status': 'conference_requested', 'agendaId': key, 'requestedAt': row['requestedAt'], 'businessAgendaId': business}
            # A timer tick cannot replace a failed/finished business attempt.
            return {'status':'conference_'+row['status'],'agendaId':key,'requestedAt':row['requestedAt'],'businessAgendaId':business}
        if row.get('status') in ('queued', 'running'):
            return {'status': 'conference_pending', 'agendaId': key, 'requestedAt':row['requestedAt']}
        if time.time() < row.get('retryAt', 0):
            return {'status': 'conference_retry_wait', 'agendaId': key, 'requestedAt':row['requestedAt']}
        row = {'agendaId': key, 'kind': kind, 'arguments': arguments, 'status': 'queued', 'requestedAt': time.time()}
        if business:row['businessAgendaId']=business
        write(path, row)
    return {'status': 'conference_requested', 'agendaId': key, 'requestedAt':row['requestedAt']}


LANE_LIMITS = {'cf_blog': 3, 'naver_blog': 1, 'naver_kin': 1, 'threads': 1}


def _lane_for_row(row):
    kind = row.get('kind')
    if kind == 'parameters':
        action = (row.get('arguments') or {}).get('action', '')
        if action in ('cf', 'cf-prepare', 'cf-cycle', 'dispatch'):
            return 'cf_blog'
        return 'naver_blog'
    if kind == 'kin':
        return 'naver_kin'
    if kind == 'threads':
        return 'threads'
    return str(kind or 'other')


def process_once():
    """Decoupled multi-lane execution: CF (3 workers), Naver (1), Kin (1), Threads (1)."""
    from common import work_agenda as agendas
    if not QUEUE.exists() or (Path.home() / 'EGO_EXEC_DISABLED').exists():
        return False
    spawned = False
    with locked(QUEUE):
        entries = [(p, load(p)) for p in QUEUE.glob('*.json')]
        active_lanes = {}
        active_accounts = set()
        for path, row in entries:
            if row.get('status') == 'running':
                try:
                    stat = Path('/proc', str(row['pid']), 'stat').read_text().split(') ', 1)[1].split()
                    identity = stat[19]
                    if stat[0] != 'Z' and identity == row.get('startTicks'):
                        lane = _lane_for_row(row)
                        active_lanes[lane] = active_lanes.get(lane, 0) + 1
                        acct = (row.get('arguments') or {}).get('account')
                        if acct:
                            active_accounts.add((lane, acct))
                        continue
                except (OSError, KeyError, IndexError):
                    pass
                if agendas.enabled():
                    row.update(status='unknown',interruptedAt=time.time(),failureReason='worker_interrupted_verify_before_retry')
                    if row.get('businessAgendaId'):agendas.hold(row['businessAgendaId'],'실행 프로세스가 중단됐습니다. 기존 제출 결과를 확인하기 전에는 재실행하지 않습니다.',recovery=True)
                    write(path,row)
                    continue
                row.update(status='queued', interruptedAt=time.time())
                write(path, row)
        active_agenda_set = set(agendas.active_ids()) if agendas.enabled() else set()
        for path, row in sorted(entries, key=lambda pair: pair[1].get('requestedAt', 0)):
            if row.get('status') != 'queued' or row.get('kind') not in ('parameters','kin','threads'):
                continue
            lane = _lane_for_row(row)
            if active_lanes.get(lane, 0) >= LANE_LIMITS.get(lane, 1):
                continue
            acct = (row.get('arguments') or {}).get('account')
            if acct and (lane, acct) in active_accounts:
                continue
            business = row.get('businessAgendaId')
            if agendas.enabled():
                if not business or business not in active_agenda_set:
                    continue
                current = agendas.get(business)
                if not current or not current.get('events',{}).get('opening',{}).get('receivedAt') or any(p.get('pid') != os.getpid() for p in agendas.running(current)):
                    continue
                if current.get('switchRequest') or current.get('status') not in ('meeting','executing','recovering'):
                    continue
            log = path.with_suffix('.log')
            with log.open('ab') as output:
                environment=dict(os.environ)
                if agendas.enabled():environment['BAROLAB_AGENDA_CONTEXT']=json.dumps(agendas.token(current))
                child = subprocess.Popen([sys.executable, '-u', '-B', '-m', 'common.conference_dispatch', 'work', path.stem], cwd=ROOT, stdout=output, stderr=output, start_new_session=True,env=environment)
            row.update(status='running', pid=child.pid, startTicks=Path('/proc', str(child.pid), 'stat').read_text().split(') ', 1)[1].split()[19])
            write(path, row)
            if agendas.enabled():
                with agendas.context(agendas.token(current)):agendas.register_process(child.pid)
            active_lanes[lane] = active_lanes.get(lane, 0) + 1
            if acct:
                active_accounts.add((lane, acct))
            spawned = True
    return spawned


def install_channel_conferences(kind):
    """Inject meetings at shared call boundaries; frozen engines are not edited."""
    from common.channel_parameters import planning_or_memory, folder_for, KST
    from datetime import datetime
    day = datetime.now(KST).date().isoformat()
    def verify_target(account,slot=None):
        from common import work_agenda as agendas
        if agendas.enabled():
            row=agendas.require(project={'kin':'naver_kin','threads':'threads'}[kind])
            args=(row.get('workTarget') or row.get('source') or {}).get('arguments',{})
            if args.get('account') and args['account']!=account:raise ValueError('Agenda account changed; preserve original work')
            if args.get('date')!=day:raise ValueError('Original publication date changed')
            if kind=='threads' and slot and slot not in (args.get('slot'),args['date']+'-'+str(args.get('slot'))):raise ValueError('Agenda slot changed')
    def author_after_conference(identity, slot, topic, original, *args, **kwargs):
        verify_target(identity, str(slot))
        from common import llm_client
        folder = folder_for('naver_kin' if kind == 'kin' else 'threads_posting', day, str(identity)+'-'+str(slot))
        plan = planning_or_memory(identity, topic, folder, {}, channel=kind)
        generate = llm_client.generate_json
        llm_client.generate_json = lambda prompt, *a, **kw: generate(prompt+'\n[팀장 컨퍼런스 실행안]\n'+plan['writingGuide'], *a, **kw)
        try:
            return original(*args, **kwargs)
        finally:
            llm_client.generate_json = generate
    if kind == 'kin':
        import naver_kin.posting as engine
        reserve=engine._naver_scheduler_reserve_run
        def reserve_original(db,config,now=None,force=False):
            from common import work_agenda as agendas
            if agendas.enabled():
                moment=now or engine._naver_scheduler_now_kst()
                status=engine._naver_scheduler_cadence_status(db,config,moment)
                verify_target(status.get('nextAccount'))
                expected=(agendas.require().get('workTarget') or agendas.require()['source'])['arguments']
                if status.get('activeRunId') or expected['date']!=moment.date().isoformat():
                    raise ValueError('Original Kin cadence needs reconciliation; no new reservation')
            if getattr(engine,'_conference_retry',None):
                if kin_retry_target(engine._conference_retry)!=engine._conference_retry['retryTarget']:
                    raise ValueError('Original Kin draft changed; reconcile before retry')
            return reserve(db,config,now=now,force=force)
        engine._naver_scheduler_reserve_run=reserve_original
        author = engine._naver_authoring_generate_for_slot
        def generate_for_slot(account, slot_id, model, *args, **kwargs):
            if getattr(engine,'_conference_retry',None):
                raise ValueError('Same-question recovery cannot author a replacement question')
            return author_after_conference(account, slot_id, '다음 지식iN 답변의 질문 탐색 주제·독자·구성을 결정한다.', author, account, slot_id, model, *args, **kwargs)
        engine._naver_authoring_generate_for_slot = generate_for_slot
        original = engine._naver_browser_publish
        engine._conference_failures = []
        def publish(account, url, answer, before_submit=None):
            verify_target(account)
            question=engine._naver_pipeline_question_id(url)
            retry=getattr(engine,'_conference_retry',None)
            if retry and (account!=retry['retryTarget']['account'] or question!=retry['retryTarget']['questionId']):
                raise ValueError('Different question is outside the current recovery agenda')
            try:
                folder = folder_for('naver_kin', day, account + '-' + hashlib.sha256(url.encode()).hexdigest()[:16])
                planning_or_memory(account, '이 질문에 대한 답변 실행 계획: '+url+'\n'+answer[:800], folder, {}, channel='kin')
                from common.kin_screen import publish_with_screen
                return publish_with_screen(engine, original, account, url, answer, before_submit, folder)
            except Exception as exc:
                engine._conference_failures.append({'account':account,'questionId':question,
                    'errorType':type(exc).__name__,'reason':conference_failure_reason(exc)})
                raise
        engine._naver_browser_publish = publish
        engine._conference_results = []
        verify = engine._naver_browser_verify_public
        def verify_and_record(*a, **kw):
            result = verify(*a, **kw)
            if not result.get('public') and len(a)>=5:
                import sqlite3
                from contextlib import closing
                from common.kin_submit_repair import public_evidence
                with closing(sqlite3.connect(Path(engine._naver_pipeline_DB).resolve().as_uri()+'?mode=ro',uri=True)) as db:
                    db.row_factory=sqlite3.Row
                    row=db.execute('SELECT * FROM questions WHERE account=? AND answer_id=?',(a[0],str(a[4]))).fetchone()
                if row:
                    document=json.loads(row['document'])
                    if row['answer_url']==a[1] and document['answer_text']==a[2] and document['attribution']['outboundUrl']==a[3]:
                        result=public_evidence(a[0],row,document,initial=result)
            engine._conference_results.append(result)
            return result
        engine._naver_browser_verify_public = verify_and_record
        return engine
    import threads_posting.posting as engine
    from common.threads_screen import install
    install(engine)
    author = engine._threads_authoring_prepare_next
    def prepare_next(config, publication_day, slot, *args, **kwargs):
        return author_after_conference(config['account_key'], str(publication_day)+'-'+str(slot), '다음 Threads 게시의 주제·독자·본문 구조와 유입 전략을 결정한다.', author, config, publication_day, slot, *args, **kwargs)
    engine._threads_authoring_prepare_next = prepare_next
    original = engine._threads_pipeline_publish
    def publish(part_id, config, *args, **kwargs):
        folder = folder_for('threads_posting', day, str(part_id))
        with engine._threads_pipeline_connect(kwargs.get('db_path', args[0] if args else engine._threads_config_DB)) as db:
            part = dict(db.execute('SELECT * FROM parts WHERE part_id=?', (part_id,)).fetchone())
        verify_target(part['account_key'],part['slot'])
        from common import work_agenda as agendas
        if agendas.enabled():
            bound=agendas.require();target=(bound.get('workTarget') or bound.get('source') or {}).get('arguments',{})
            if target.get('partId') and target['partId']!=part_id:raise ValueError('Different Threads part is outside the current agenda')
        engine._conference_context = {'channel':'Threads', 'account':part['account_key'], 'slot':part['slot'],
            'reserveTime':part['publication_date']+' '+part['slot'], 'title':part['text'].splitlines()[0], 'partId':part_id}
        readiness = engine._namespace_adapter.readiness_status(config)
        if readiness.get('publishReady') is not True:
            raise RuntimeError(readiness.get('reason') or 'threads_readiness_incomplete')
        result = {**engine._conference_context, **original(part_id, config, *args, **kwargs)}
        engine._conference_results.append(result)
        return result
    engine._conference_results = []
    engine._threads_pipeline_publish = publish
    return engine


def report_outcome(receipt, task_id, context=None):
    """Report verified publishing facts, never a child's operating-system exit code."""
    from agents.agent_tools import staff_tool_reply
    from common.crew_chat_bridge import emit_work_event
    if not isinstance(receipt, dict):
        return None
    context = context or {}
    receipt = {**context, **{k:v for k,v in receipt.items() if v is not None}}
    public = (receipt.get('publicPublicationVerified') is True and receipt.get('httpStatus') == 200
              or receipt.get('verified') is True and receipt.get('public') is True
              or receipt.get('state') == 'published_verified')
    reserved = receipt.get('submissionStatus') == 'verified_reserved' and bool(receipt.get('verificationSource'))
    pending = receipt.get('state') in ('api_submitted','submitted_unknown') or receipt.get('submissionStatus') in ('submitting','submission_unknown')
    if not public and not reserved and not pending and not receipt.get('errorType'):
        return None
    address = receipt.get('publicUrl') or receipt.get('answer_url') or receipt.get('permalink') or ''
    public = public and bool(address)
    facts = {'outcome':'게시 성공' if public and address else '예약 완료' if reserved else '게시 확인 중' if pending else '작업 차단',
             'publicationVerified':bool(public and address),'reservationVerified':reserved,
             'publicUrl':address if public else '', 'reserveTime':receipt.get('reserveTime'),
             'account':receipt.get('account') or receipt.get('domain'),
             'channel':receipt.get('channel') or receipt.get('project') or '발행 안건',
             'title':receipt.get('title'), 'slot':receipt.get('slot') or receipt.get('scheduledSlot'),
             'submissionState':receipt.get('submissionStatus') or receipt.get('state'),
             'submittedUrl':address if pending else '', 'errorType':receipt.get('errorType'),
             'failureReason':receipt.get('reason'),
             'nextAction':'열린 Threads 전용 Ubuntu 창에서 @mustpickinfo 로그인 후 같은 안건을 재개한다. 원고는 보존되어 있다.' if receipt.get('reason') == 'threads_web_login_required' else '실제 게시 본문과 계정 확인 완료' if public else '예약 목록과 지정 시각 확인 완료' if reserved else '담당 직원이 기존 제출 결과를 재조회한다. 확인 전에는 재제출하지 않는다.' if pending else '해당 안건의 실행 오류를 확인한다. 제출 여부 확인 전에는 재제출하지 않는다.'}
    report = {key: facts.get(key) for key in ('channel','account','title','reserveTime','slot','nextAction')}
    report['status'] = facts['outcome']
    if not address:
        report['linkStatus'] = '예약 글의 공개 URL은 아직 발급되지 않았습니다.' if reserved else '제출 확인 전 작업이 중단되어 공개 URL을 확인하지 못했습니다.' if not pending else '제출 기록에서 대상 URL을 확인해야 합니다.'
    link = address
    label = facts.get('title') or '대상 게시물 열기'
    if not link and reserved and isinstance(receipt.get('blogId'), str) and re.fullmatch(r'[A-Za-z0-9_]+', receipt['blogId']):
        link = 'https://blog.naver.com/' + receipt['blogId']
        label = '예약 계정 블로그 열기 · 예약 글은 미공개'
        report['linkStatus'] = '글은 아직 미공개입니다. 링크는 해당 계정 블로그로 연결됩니다.'
    try:
        if public or reserved:
            summary_reply = f"[{facts.get('channel') or '채널'} {facts['outcome']}] {facts.get('account') or ''} · {facts.get('title') or facts.get('slot') or '슬롯'} ({address or facts.get('reserveTime') or '검증 완료'})"
            response = {'reply': summary_reply, 'route': {'events': [{'provider': 'host', 'actualModel': 'fast-verified-reporter', 'reasoningEffort': 'fast'}]}}
        else:
            response=staff_tool_reply('publi',task_id,{'tool':'publication_verification' if public or reserved or pending else 'channel_execution'},facts,stage='staff-terminal-response')
        emit_work_event(actor='publi',actor_label='퍼블리',task_id=task_id,phase='completed',stage='staff-terminal-response',
            message_kind='staff_reply',requested_to='jarvis',model=response['route']['events'][-1]['actualModel'],
            output_kind=response['reply'],deliverable_url=link,deliverable_label=label,report=report)
        facts['staffResponse']=response
    except Exception as exc:
        facts.update(reportPending=True,reportErrorType=type(exc).__name__)
    return facts


def conference_failure_reason(exc):
    """Retain a safe actionable cause rather than only the outer RuntimeError."""
    for _ in range(8):
        message = str(exc)
        if isinstance(exc,FileExistsError):
            return 'execution_evidence_directory_collision'
        if 'Verified browser window is not visible on DISPLAY for port ' in message:
            return 'browser_window_unavailable'
        if 'Screen execution reached' in message:
            return 'screen_execution_budget_exhausted'
        if '응답 시간 제한' in message:
            return 'model_timeout'
        if isinstance(exc,TimeoutError):
            return 'execution_timeout'
        if 'AGY CLI 모델·구조화 응답 확인 실패' in message:
            return 'model_response_invalid'
        if message.startswith(('Interrupted action','Interrupted cut','Interrupted mutating action')):
            return 'screen_action_reconciliation_required'
        if 'duplicate submission prevented' in message:
            return 'duplicate_submission_prevented'
        if message in ('threads_web_login_required','threads_readiness_incomplete','threads_existing_draft_preserved','threads_uncertain_submission_tab_preserved'):
            return message
        exc = exc.__cause__ or exc.__context__
        if exc is None:break
    return 'execution_error'


def extract_screen_context():
    """Find the most recently updated screen-execution.json and extract live screen text."""
    try:
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        today_threads = ROOT / 'threads_posting' / 'output' / 'scheduled' / today
        candidates = []
        if today_threads.is_dir():
            for p in today_threads.rglob('screen-execution.json'):
                try:
                    candidates.append((p.stat().st_mtime, p))
                except OSError:
                    pass
        if not candidates:
            scheduled_root = ROOT / 'threads_posting' / 'output' / 'scheduled'
            if scheduled_root.is_dir():
                # Inspect only the top 3 most recent date subdirs
                subdirs = sorted([d for d in scheduled_root.iterdir() if d.is_dir()], key=lambda d: d.name, reverse=True)[:3]
                for d in subdirs:
                    for p in d.rglob('screen-execution.json'):
                        try:
                            candidates.append((p.stat().st_mtime, p))
                        except OSError:
                            pass
        if not candidates:
            return {}
        latest_path = max(candidates, key=lambda x: x[0])[1]
        data = json.loads(latest_path.read_text('utf-8'))
        turns = data.get('turns') or []
        last_turn = turns[-1] if turns else {}
        return {
            'lastUrl': last_turn.get('url') or '',
            'lastModelMessage': last_turn.get('message') or '',
            'observations': (data.get('observations') or [])[-5:],
            'inputFeedback': data.get('inputFeedback') or '',
            'sourceExecution': str(latest_path.relative_to(ROOT))
        }
    except Exception:
        return {}


def failure_diagnostic(exc):
    import traceback
    frames=[]
    for frame in traceback.extract_tb(exc.__traceback__):
        file=Path(frame.filename)
        if file.is_absolute() and file.is_relative_to(ROOT):
            frames.append({'file':str(file.relative_to(ROOT)),'line':frame.lineno,'function':frame.name})
    source_top = frames[-1] if frames else {}
    file_info = f"{source_top.get('file', 'unknown')}:{source_top.get('line', '?')} in {source_top.get('function', '?')}"
    screen = getattr(exc,'live_screen_context',{})
    summary = f"오류 발생 지점: [{file_info}] | 에러: {str(exc)[:200]}"
    if screen.get('observations'):
        summary += f" | 현장 화면: {' / '.join(screen['observations'][-3:])}"
    if screen.get('inputFeedback'):
        summary += f" | 화면 피드백: {screen['inputFeedback']}"
    return {
        'errorType': type(exc).__name__,
        'errorMessage': str(exc),
        'traceback': ''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)),
        'observations': screen.get('observations',[]),
        'messageSha256': hashlib.sha256(str(exc).encode()).hexdigest(),
        'sourceFrames': frames[-16:],
        'sourceLocation': file_info,
        'liveScreenContext': screen,
        'diagnosticSummary': summary
    }


def _work(identity):
    if len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('Invalid agenda identity')
    path = QUEUE / (identity + '.json')
    # Parent stores ownership before the child reads the request.
    with locked(QUEUE):
        row = load(path)
    context = {'channel': {'kin':'지식iN','threads':'Threads'}.get(row['kind'], ''),
               **{k:row['arguments'].get(k) for k in ('account','slot','date')}}
    if row['kind'] == 'parameters':
        args = row['arguments']
        context.update(channel={'naver':'네이버 블로그','cf':'CF 블로그','naver-cycle':'네이버 블로그','cf-cycle':'CF 블로그','dispatch':'CF 블로그','prepare':'네이버 블로그·CF 블로그 준비','conference':'발행 회의'}.get(args.get('action'), '발행 안건'),
                       account=args.get('account'), slot=args.get('slot'), publicationDate=args.get('date'), action=args.get('action'))
        if args.get('date') and args.get('slot'):
            context['reserveTime'] = args['date'] + ' ' + args['slot']
        if args.get('action') == 'naver' and all(args.get(k) for k in ('date','account','slot')):
            from common.channel_parameters import folder_for
            folder = folder_for('naver_blog_posting', args['date'], args['account'] + '-' + args['slot'].replace(':',''))
            document = load(folder / 'editor-content.json')
            context['title'] = document.get('title')
    try:
        if (Path.home() / 'EGO_EXEC_DISABLED').exists():
            raise RuntimeError('Execution disabled')
        if row['kind'] == 'parameters':
            from common.channel_parameters import main
            a = row['arguments']; argv = [a['action']]
            for key in ('date', 'account', 'slot'):
                if a.get(key): argv += ['--'+key, a[key]]
            result = main(argv, conference_worker=True)
            if isinstance(result,dict) and result.get('preparationVerified') is True:row['preparation']=result
            if isinstance(result,dict):
                row['eligibility'] = {k:result[k] for k in ('state','status','reason','owner') if k in result}
            receipts = result if isinstance(result, list) else [result]
        else:
            engine = install_channel_conferences(row['kind'])
            if row['kind']=='threads' and row['arguments'].get('targetUrl'):
                target=row['arguments']['targetUrl']
                engine._threads_authoring__canonical(target,engine._threads_config_HOSTS)
                catalog=engine._threads_authoring_catalog
                engine._threads_authoring_catalog=lambda *a,**kw:[item for item in catalog(*a,**kw) if item.get('url')==target]
            if row['kind'] == 'kin':
                if row.get('retryTarget'):engine._conference_retry=row
                engine.main(['--tick', '--scheduled'])
                state = load(ROOT/'dashboard/data/kin-automation-state.json')
                row['eligibility'] = {k:state.get(k) for k in ('reason','state','runs','runId','account','cadenceState','nextEligibleAt','globalRemainingRuns','submissionCounts')}
                row['executionFailures']=getattr(engine,'_conference_failures',[])
            else:
                engine._conference_agenda = row['arguments'].get('topic', '')
                if row['arguments'].get('partId'):
                    dispatch=engine._threads_pipeline_publish(row['arguments']['partId'],engine._threads_config_load())
                else:
                    dispatch = engine._threads_scheduler_tick()
                if isinstance(dispatch,dict):
                    row['eligibility'] = {k:dispatch[k] for k in ('state','status','reason') if k in dispatch}
            if row['kind']=='threads' and not engine._conference_results and row['arguments'].get('slot'):
                # Authoring and its matching main post finish inside the SAME agenda.
                config=engine._threads_config_load()
                with engine._threads_pipeline_connect() as db:
                    part=db.execute("SELECT part_id FROM parts WHERE account_key=? AND publication_date=? AND slot=? AND kind='main' AND state='queued'",(row['arguments']['account'],row['arguments']['date'],row['arguments']['slot'])).fetchone()
                if part:engine._threads_pipeline_publish(part['part_id'],config)
            receipts = engine._conference_results
        row['outcomes'] = []
        for receipt in receipts:
            try:
                outcome = report_outcome(receipt, 'conference:'+identity[:24], context)
                if outcome: row['outcomes'].append(outcome)
            except Exception as exc:
                row['reportPending'] = True
                row['reportErrorType'] = type(exc).__name__
        failed_runs=[r for r in (row.get('eligibility') or {}).get('runs',[]) if r.get('state') in ('blocked','failed','error')]
        if failed_runs and not row['outcomes']:
            failure=(row.get('executionFailures') or [{}])[-1]
            row.update(status='failed',failureReason=failure.get('reason') or 'native_run_blocked:'+str(failed_runs[0].get('reason','unknown'))[:120])
            row['failureReport']=report_outcome({'errorType':failure.get('errorType') or failed_runs[0].get('reason'),
                'reason':row['failureReason']},'conference:'+identity[:24],context)
        else:row['status']='completed'
        row.update(completedAt=time.time(), retryAt=time.time()+60)
    except Exception as exc:
        row.update(status='failed', errorType=type(exc).__name__, retryAt=time.time()+300,completedAt=time.time(),
                   failureReason=conference_failure_reason(exc),failureDiagnostic=failure_diagnostic(exc))
        try:
            failure_context = {**context, **(getattr(locals().get('engine'), '_conference_context', {}) or {})}
            row['failureReport'] = report_outcome({'errorType':type(exc).__name__, 'reason':str(exc) if str(exc) in ('threads_web_login_required','threads_readiness_incomplete') else None}, 'conference:'+identity[:24], failure_context)
        except Exception:
            row['reportPending'] = True
        raise
    finally:
        write(path, row)
        from common import work_agenda as agendas
        if agendas.enabled() and row.get('businessAgendaId'):
            record_conference_result(row, result if 'result' in locals() else None)


def work(identity):
    from common import work_agenda as agendas
    if not agendas.enabled():return _work(identity)
    row=load(QUEUE/(identity+'.json'))
    current=agendas.require()
    if row.get('businessAgendaId')!=current['id']:raise agendas.AgendaWaiting('Conference agenda ownership mismatch')
    with agendas.execution(current['project']):
        agendas.progress(current['id'],'executing','합의한 단일 계정·슬롯의 실행과 검증을 진행합니다.')
        return _work(identity)


def record_conference_result(row, result=None):
    from common import work_agenda as agendas
    business=agendas.get(row['businessAgendaId'])
    outcomes=row.get('outcomes',[])
    good=bool(outcomes) and all(o.get('publicationVerified') or o.get('reservationVerified') for o in outcomes)
    preparation=isinstance(result,dict) and result.get('preparationVerified') is True
    if row['status']=='completed' and (good or preparation):
        if business['kind']=='conference':
            response=next((o.get('staffResponse') for o in outcomes if o.get('staffResponse')),None)
            staff={'actor':'publi','text':response['reply'],'route':{k:v for k,v in response['route']['events'][-1].items() if k in ('provider','reasoningEffort')}} if response else None
            if staff:staff['route']['model']=response['route']['events'][-1].get('actualModel')
            agendas.verified(business['id'],{'verified':True,'source':str(QUEUE/(row['agendaId']+'.json')),
                'outcomes':[{k:o.get(k) for k in ('outcome','publicationVerified','reservationVerified','publicUrl','reserveTime','account','slot')} for o in outcomes],
                'preparation':result if preparation else None},staff=staff)
    else:
        eligibility=row.get('eligibility') or {}
        reason=row.get('failureReason') or eligibility.get('reason') or next((r.get('reason') for r in eligibility.get('runs',[]) if r.get('reason')),None) or row.get('errorType') or '실제 제출·예약 결과가 아직 확인되지 않았습니다.'
        agendas.close_and_advance(business['id'],status='closed',reason=reason) if row.get('status')=='completed' and (row.get('eligibility') or {}).get('reason') in ('no_due_slot','no_due_draft','followup_delay_waiting','disabled_or_needs_connection','publication_closed_measurement_continues','no_new_supported_candidate') else agendas.hold(business['id'],reason,recovery=True)


NAVER_SUBMISSION_BOUNDARY_SHA256 = '32866023d5fb8743a3e4c9935bd29b63f01fe8ed2cfe73349bb3467578c74018'


def _matching_naver_attempts(arguments):
    journal=load(ROOT/'dashboard/data/naver/automation-journal.json')
    return [r for r in journal.get('attempts',[]) if r.get('account')==arguments['account']
        and (r.get('publicationDate') or str(r.get('reserveTime') or '')[:10])==arguments['date']
        and (r.get('scheduledSlot') or str(r.get('reserveTime') or '')[-5:])==arguments['slot']]


def reconcile_repaired_retry(current, original, task_id, plan_sha256):
    """Observe legacy attempts on the real server; never rewrite their absent intent markers."""
    from common import repair_workflow as repair
    from common.recovery_evidence import artifact_folder
    _,row=repair._recovery_row(task_id,plan_sha256)
    if row.get('businessAgendaId')!=current['id'] or row['plan']['project']!='naver_blog':
        raise ValueError('Read-only reconciliation ownership mismatch')
    repair.verified_applied_repair(row)
    folder=artifact_folder(ROOT,row['plan']['workTarget'])
    if not folder:raise ValueError('Original artifact folder is unavailable')
    screen=load(folder/'ego-screen-editor/screen-execution.json')
    last=(screen.get('turns') or [{}])[-1]
    reconciled={ref for item in screen.get('reconciliations',[]) for ref in item['previousWritten'] if ref not in item['verifiedWritten']}
    if (last.get('completedActions',0)+len(last.get('rejectedActions',[]))!=len(last.get('actions',[]))
            or last.get('inputStarted') and last['inputStarted'] not in screen.get('written',[]) and last['inputStarted'] not in reconciled):
        raise ValueError('Preserved editor action needs read-only reconciliation before consuming a grant')
    attempts=_matching_naver_attempts(original['arguments'])
    if not attempts or any(r.get('submissionStarted') is not False or r.get('preCommitIntent') is True
            or r.get('phase') not in ('failed','material_required','superseded') for r in attempts):
        raise ValueError('Submitted or uncertain attempts require reconciliation without resubmission')
    if all(r.get('preCommitIntent') is False for r in attempts):return
    if not folder or (folder/'reservation-evidence.json').exists():raise ValueError('Existing receipt requires verification, never a retry')
    document=load(folder/'editor-content.json');args=original['arguments']
    from common.ego_screen import screen_lock
    from common.browser_session import connect_sync
    from playwright.sync_api import sync_playwright
    from naver_blog_posting import posting as engine
    account=engine.ACCOUNT_MAP[args['account']]
    with screen_lock(account['cdp_port']),sync_playwright() as playwright:
        browser=connect_sync(playwright,'http://127.0.0.1:'+str(account['cdp_port']),*engine.account_browser_paths(account))
        inventory=engine.check_existing_reservations(browser.contexts[0],account,
            title=document['title'],reserve_time=args['date']+' '+args['slot'],folder=folder)
    # The two complete, identity-checked server inventories are the evidence, not a snapshot count.
    write(folder/'pre-submit-reconciliation.json',{'schema':'original-reservation-absence-v1',
        'businessAgendaId':current['id'],'planSha256':plan_sha256,'workId':row['plan']['workTarget']['workId'],
        'failureReceiptSha256':row['plan']['originalRequestSha256'],
        'approvedDocumentSha256':row['plan']['approvedDocumentSha256'],
        'blogId':account['blog_id'],'arguments':args,'observedAt':time.time(),'inventory':inventory})


def _verified_legacy_absence(current, recovery, original, folder):
    from datetime import datetime, timezone
    from dashboard.collectors.naver_accounts import validated_reservation_rows
    evidence=load(folder/'pre-submit-reconciliation.json');plan=recovery['plan']
    if (evidence.get('schema')!='original-reservation-absence-v1' or evidence.get('businessAgendaId')!=current['id']
            or evidence.get('planSha256')!=recovery['planSha256'] or evidence.get('workId')!=plan['workTarget']['workId']
            or evidence.get('arguments')!=original['arguments'] or evidence.get('failureReceiptSha256')!=plan['originalRequestSha256']
            or evidence.get('approvedDocumentSha256')!=plan['approvedDocumentSha256']
            or not 0<=time.time()-evidence.get('observedAt',0)<=120):return False
    from naver_blog_posting.posting import ACCOUNT_MAP
    if evidence.get('blogId')!=ACCOUNT_MAP[original['arguments']['account']]['blog_id']:return False
    inventory=validated_reservation_rows(evidence.get('inventory',{}),evidence.get('blogId'),datetime.now(timezone.utc))
    if inventory is None:return False
    document=load(folder/'editor-content.json');args=original['arguments']
    from naver_blog_posting.posting import normalized_title
    return not any(r['reserveTime']==args['date']+' '+args['slot'] or normalized_title(r['title'])==normalized_title(document['title']) for r in inventory)


def authorize_repaired_retry(current, original, task_id, plan_sha256):
    """Called only under QUEUE lock; consuming the grant and queueing are one write."""
    from common import repair_workflow as repair, coding_job
    from common.recovery_evidence import artifact_folder, read_object
    from common.project_autonomy import recoverable_work
    if (not task_id or not plan_sha256 or current.get('project') != 'naver_blog'
            or original.get('attempts', 1) != 2 or original.get('executionGeneration')):
        raise ValueError('Finite repaired execution grant unavailable')
    _, recovery = repair._recovery_row(task_id, plan_sha256)
    plan = recovery['plan']
    if (recovery.get('businessAgendaId') != current['id'] or recovery.get('step') != 'resume'
            or plan.get('project') != current['project'] or plan.get('projectRoot') != str(ROOT)
            or recovery.get('status') not in ('ready', 'processing')):
        raise ValueError('Recovery revision ownership or phase mismatch')
    request_path = QUEUE / (hashlib.sha256(json.dumps([original['kind'],original['arguments']],sort_keys=True).encode()).hexdigest()+'.json')
    if plan.get('originalRequestPath') != str(request_path) or hashlib.sha256(request_path.read_bytes()).hexdigest() != plan.get('originalRequestSha256'):
        raise ValueError('Original terminal failure receipt changed')
    args = original['arguments']
    target = next((r for r in recoverable_work(current['project']) if r['workId'] == plan.get('workTarget',{}).get('workId')), None)
    if (not target or target['identity'] != args.get('account') or target['date'] != args.get('date')
            or target['slot'] != args.get('slot') or target.get('submissionStarted') is not False):
        raise ValueError('Exact original work is no longer eligible')
    folder = artifact_folder(ROOT,target)
    if not folder or not plan.get('approvedDocumentSha256') or hashlib.sha256((folder/'editor-content.json').read_bytes()).hexdigest() != plan['approvedDocumentSha256']:
        raise ValueError('Approved document binding missing or changed')
    # This frozen Naver path writes reservation-evidence through dashboard_jobs before its only final click.
    engine = ROOT/'naver_blog_posting/posting.py'
    if hashlib.sha256(engine.read_bytes()).hexdigest() != NAVER_SUBMISSION_BOUNDARY_SHA256:
        raise ValueError('Final submission boundary coverage changed')
    if (folder/'reservation-evidence.json').exists() or list(folder.glob('*publication*receipt*')):
        raise ValueError('Submission receipt exists; read-only reconciliation required')
    journal = read_object(ROOT/'dashboard/data/naver/automation-journal.json')
    attempts = [r for r in journal.get('attempts',[]) if r.get('account') == args['account']
        and (r.get('publicationDate') or str(r.get('reserveTime') or '')[:10]) == args['date']
        and (r.get('scheduledSlot') or str(r.get('reserveTime') or '')[-5:]) == args['slot']]
    public = read_object(ROOT/'dashboard/data/naver/public-verification.json')
    if not attempts or not isinstance(public.get('evidence'),list):
        raise ValueError('Authoritative submission observations missing')
    legacy_absence=_verified_legacy_absence(current,recovery,original,folder) if any(r.get('preCommitIntent') is None for r in attempts) else False
    for attempt in attempts:
        if (attempt.get('submissionStarted') is not False or (attempt.get('preCommitIntent') is not False and not (attempt.get('preCommitIntent') is None and legacy_absence))
                or attempt.get('submittedAt') or attempt.get('submissionStartedAt')
                or attempt.get('phase') not in ('failed','material_required','superseded')):
            raise ValueError('A previous execution has uncertain or submitted evidence')
    for evidence in public['evidence']:
        if (evidence.get('account') == args['account']
                and (evidence.get('reserveTime') or '') == args['date']+' '+args['slot']):
            raise ValueError('Server verification already exists; reconcile before executing')
    verified_repair = repair.verified_applied_repair(recovery)
    return {'generationId':2, 'parentGenerationId':1, 'budget':1, 'consumedAt':time.time(),
        'authorizingRepairRoundSha256':plan_sha256, 'repairTaskId':task_id,
        'patchCandidateSha256':verified_repair['candidateSha256'], 'testReceiptSha256':verified_repair['testReceiptSha256'],
        'workId':target['workId'], 'approvedDocumentSha256':plan['approvedDocumentSha256']}


def retry_active(*, repair_task_id=None, repair_plan_sha256=None):
    from common import work_agenda as agendas
    current=agendas.require()
    target=current.get('workTarget') or current.get('source',{})
    kind=target.get('kind');args=target.get('arguments',{})
    if kind not in ('kin','threads') and (kind!='parameters' or args.get('action') not in ('naver','cf')):
        raise ValueError('This original operation requires its registered reconciliation or repair tool')
    if kind not in ('kin','threads'):
        from common.project_autonomy import recoverable_work
        matches=[r for r in recoverable_work(current['project']) if r['date']==args.get('date') and r['identity']==args.get('account') and (r['slot'] is None if current['project']=='cf_blog' else r['slot']==args.get('slot'))]
        if len(matches)!=1:raise ValueError('Same work is not verified as a pre-submission failure; reconcile existing results')
    identity=hashlib.sha256(json.dumps([kind,args],sort_keys=True).encode()).hexdigest();file=QUEUE/(identity+'.json')
    observed=load(file)
    if kind=='parameters' and args.get('action')=='naver' and repair_task_id and observed.get('attempts',1)==2 and observed.get('status')=='failed':
        reconcile_repaired_retry(current,observed,repair_task_id,repair_plan_sha256)
    with locked(QUEUE):
        row=load(file)
        limit=3 if kind in ('kin','threads') else 2
        if row.get('businessAgendaId')!=current['id'] or (row.get('status')!='failed' and not (kind=='threads' and row.get('status')=='completed' and not row.get('outcomes'))) or any(p.get('pid') != os.getpid() for p in agendas.running(current)):
            raise ValueError('Original attempt is pending, unknown or owned by a live execution')
        if row.get('attempts',1)>=limit:
            if kind in ('kin','threads'):raise ValueError('Original retry budget is exhausted')
            generation=authorize_repaired_retry(current,row,repair_task_id,repair_plan_sha256)
            row['executionGeneration']=generation
        if kind=='kin':row['retryTarget']=kin_retry_target(row)
        terminal_raw=file.read_bytes();terminal_sha=hashlib.sha256(terminal_raw).hexdigest()
        archive=QUEUE/'attempt-receipts'/(identity+'-'+str(row.get('attempts',1))+'-'+terminal_sha+'.json')
        archive.parent.mkdir(parents=True,exist_ok=True)
        from common.dashboard_jobs import atomic_text
        if archive.exists():
            if archive.read_bytes()!=terminal_raw:raise ValueError('Immutable attempt receipt conflict')
        else:atomic_text(archive,terminal_raw.decode('utf-8'),durable=True)
        row.setdefault('attemptHistory',[]).append({**{k:row.get(k) for k in ('status','failureReason','errorType','completedAt','outcomes','eligibility','executionFailures')},
            'terminalReceipt':{'path':str(archive),'sha256':terminal_sha,'attempt':row.get('attempts',1)}})
        row.update(status='queued',attempts=row.get('attempts',1)+1,retryRequestedAt=time.time())
        if agendas.require()['id']!=current['id']:raise ValueError('Agenda ownership changed before retry consumption')
        from common.dashboard_jobs import write as durable_write
        durable_write(file,row,durable=True)
    agendas.progress(current['id'],'recovering','원래 계정·날짜·슬롯의 제출 전 실패를 같은 안건에서 재개합니다.')
    return {'ok':True,'status':'queued','agendaId':identity,'businessAgendaId':current['id'],'publicationVerified':False}


def kin_retry_target(row):
    """Bind a bounded retry to the original unsubmitted question, using a read-only ledger."""
    import sqlite3
    from contextlib import closing
    runs=(row.get('eligibility') or {}).get('runs',[])
    if len(runs)!=1 or runs[0].get('state')!='blocked':
        raise ValueError('One exact blocked Kin run is required')
    args=row['arguments'];run=runs[0]
    database=ROOT/'dashboard/data/kin.sqlite3'
    with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        slot=db.execute('SELECT * FROM automation_slots WHERE slot_id=?',(run.get('runId'),)).fetchone()
        if not slot or slot['account']!=args.get('account') or slot['planned_at'][:10]!=args.get('date') or slot['state']!='blocked':
            raise ValueError('Original Kin run/account/date does not match')
        question=db.execute('SELECT * FROM questions WHERE question_id=?',(slot['question_id'],)).fetchone()
        latest=db.execute("SELECT question_id FROM questions WHERE account=? AND state='drafted' ORDER BY created_at DESC LIMIT 1",(args['account'],)).fetchone()
        if (not question or question['account']!=args['account'] or question['state']!='drafted'
                or any(question[k] for k in ('send_day','answer_id','answer_url','result'))
                or not latest or latest['question_id']!=question['question_id']):
            raise ValueError('Original draft unavailable or submission uncertain; no retry')
        return {'runId':slot['slot_id'],'account':slot['account'],'questionId':slot['question_id']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('kin','threads','work'))
    parser.add_argument('identity', nargs='?')
    args = parser.parse_args()
    if args.action == 'work': work(args.identity)
    else: print(json.dumps(request(args.action, {})))


if __name__ == '__main__':
    main()
