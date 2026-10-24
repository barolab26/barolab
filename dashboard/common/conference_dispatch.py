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


def request(kind, arguments):
    if kind not in ('parameters', 'kin', 'threads'):
        raise ValueError('Unknown conference channel')
    QUEUE.mkdir(parents=True, exist_ok=True)
    # Repeated timer ticks share one pending agenda, including model retries.
    key = hashlib.sha256(json.dumps([kind, arguments], sort_keys=True).encode()).hexdigest()
    path = QUEUE / (key + '.json')
    with locked(QUEUE):
        row = load(path)
        if row.get('status') in ('queued', 'running'):
            return {'status': 'conference_pending', 'agendaId': key, 'requestedAt':row['requestedAt']}
        if time.time() < row.get('retryAt', 0):
            return {'status': 'conference_retry_wait', 'agendaId': key, 'requestedAt':row['requestedAt']}
        row = {'agendaId': key, 'kind': kind, 'arguments': arguments, 'status': 'queued', 'requestedAt': time.time()}
        write(path, row)
    return {'status': 'conference_requested', 'agendaId': key, 'requestedAt':row['requestedAt']}


def process_once():
    """At most one child globally; never block the monitor or create timer workers."""
    if not QUEUE.exists() or (Path.home() / 'EGO_EXEC_DISABLED').exists():
        return False
    with locked(QUEUE):
        entries = [(p, load(p)) for p in QUEUE.glob('*.json')]
        for path, row in entries:
            if row.get('status') == 'running':
                try:
                    stat = Path('/proc', str(row['pid']), 'stat').read_text().split(') ', 1)[1].split()
                    identity = stat[19]
                    if stat[0] != 'Z' and identity == row.get('startTicks'):
                        return False
                except (OSError, KeyError, IndexError):
                    pass
                row.update(status='queued', interruptedAt=time.time())
                write(path, row)
        for path, row in sorted(entries, key=lambda pair: pair[1].get('requestedAt', 0)):
            if row.get('status') != 'queued':
                continue
            log = path.with_suffix('.log')
            with log.open('ab') as output:
                child = subprocess.Popen([sys.executable, '-u', '-B', '-m', 'common.conference_dispatch', 'work', path.stem], cwd=ROOT, stdout=output, stderr=output)
            row.update(status='running', pid=child.pid, startTicks=Path('/proc', str(child.pid), 'stat').read_text().split(') ', 1)[1].split()[19])
            write(path, row)
            return True
    return False


def install_channel_conferences(kind):
    """Inject meetings at shared call boundaries; frozen engines are not edited."""
    from common.channel_parameters import planning_or_memory, folder_for, KST
    from datetime import datetime
    day = datetime.now(KST).date().isoformat()
    def author_after_conference(identity, slot, topic, original, *args, **kwargs):
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
        author = engine._naver_authoring_generate_for_slot
        def generate_for_slot(account, slot_id, model, *args, **kwargs):
            return author_after_conference(account, slot_id, '다음 지식iN 답변의 질문 탐색 주제·독자·구성을 결정한다.', author, account, slot_id, model, *args, **kwargs)
        engine._naver_authoring_generate_for_slot = generate_for_slot
        original = engine._naver_browser_publish
        def publish(account, url, answer, before_submit=None):
            folder = folder_for('naver_kin', day, account + '-' + hashlib.sha256(url.encode()).hexdigest()[:16])
            planning_or_memory(account, '이 질문에 대한 답변 실행 계획: '+url+'\n'+answer[:800], folder, {}, channel='kin')
            from common.kin_screen import publish_with_screen
            return publish_with_screen(engine, original, account, url, answer, before_submit, folder)
        engine._naver_browser_publish = publish
        engine._conference_results = []
        verify = engine._naver_browser_verify_public
        def verify_and_record(*a, **kw):
            result = verify(*a, **kw)
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
        engine._conference_context = {'channel':'Threads', 'account':part['account_key'], 'slot':part['slot'],
            'reserveTime':part['publication_date']+' '+part['slot'], 'title':part['text'].splitlines()[0], 'partId':part_id}
        readiness = engine._namespace_adapter.readiness_status(config)
        if readiness.get('publishReady') is not True:
            raise RuntimeError(readiness.get('reason') or 'threads_readiness_incomplete')
        planning_or_memory(config['account_key'], '기존 승인 원고의 주제를 유지한다. '+part['text']+'\n복구 안건: '+getattr(engine,'_conference_agenda',''), folder/'publication-plan',
            {'agenda':{'publicationDate':part['publication_date'],'slot':part['slot'],'kind':part['kind']},
             'existingDraft':{'title':part['text'].splitlines()[0],'text':part['text'],'partId':part_id}}, channel='threads')
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
    response=staff_tool_reply('publi',task_id,{'tool':'publication_verification' if public or reserved or pending else 'channel_execution'},facts,stage='staff-terminal-response')
    emit_work_event(actor='publi',actor_label='퍼블리',task_id=task_id,phase='completed',stage='staff-terminal-response',
        message_kind='staff_reply',requested_to='jarvis',model=response['route']['events'][-1]['actualModel'],
        output_kind=response['reply'],deliverable_url=link,deliverable_label=label,report=report)
    return facts


def conference_failure_reason(exc):
    """Retain a safe actionable cause rather than only the outer RuntimeError."""
    for _ in range(8):
        message = str(exc)
        if isinstance(exc, TimeoutError) or '응답 시간 제한' in message:
            return 'model_timeout'
        if 'AGY CLI 모델·구조화 응답 확인 실패' in message:
            return 'model_response_invalid'
        if 'duplicate submission prevented' in message:
            return 'duplicate_submission_prevented'
        if message in ('threads_web_login_required','threads_readiness_incomplete','threads_existing_draft_preserved','threads_uncertain_submission_tab_preserved'):
            return message
        exc = exc.__cause__
        if exc is None:break
    return 'execution_error'


def work(identity):
    if len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('Invalid agenda identity')
    path = QUEUE / (identity + '.json')
    # Parent stores ownership before the child reads the request.
    with locked(QUEUE):
        row = load(path)
    context = {'channel': {'kin':'지식iN','threads':'Threads'}.get(row['kind'], '')}
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
            if isinstance(result,dict):
                row['eligibility'] = {k:result[k] for k in ('state','status','reason','owner') if k in result}
            receipts = result if isinstance(result, list) else [result]
        else:
            engine = install_channel_conferences(row['kind'])
            if row['kind'] == 'kin':
                engine.main(['--tick', '--scheduled'])
                state = load(ROOT/'dashboard/data/kin-automation-state.json')
                row['eligibility'] = {k:state.get(k) for k in ('reason','cadenceState','nextEligibleAt','globalRemainingRuns','submissionCounts')}
            else:
                engine._conference_agenda = row['arguments'].get('topic', '')
                dispatch = engine._threads_scheduler_tick()
                if isinstance(dispatch,dict):
                    row['eligibility'] = {k:dispatch[k] for k in ('state','status','reason') if k in dispatch}
            receipts = engine._conference_results
        row['outcomes'] = []
        for receipt in receipts:
            try:
                outcome = report_outcome(receipt, 'conference:'+identity[:24], context)
                if outcome: row['outcomes'].append(outcome)
            except Exception as exc:
                row['reportPending'] = True
                row['reportErrorType'] = type(exc).__name__
        row.update(status='completed', completedAt=time.time(), retryAt=time.time()+60)
    except Exception as exc:
        row.update(status='failed', errorType=type(exc).__name__, retryAt=time.time()+300,
                   failureReason=conference_failure_reason(exc))
        try:
            failure_context = {**context, **(getattr(locals().get('engine'), '_conference_context', {}) or {})}
            row['failureReport'] = report_outcome({'errorType':type(exc).__name__, 'reason':str(exc) if str(exc) in ('threads_web_login_required','threads_readiness_incomplete') else None}, 'conference:'+identity[:24], failure_context)
        except Exception:
            row['reportPending'] = True
        raise
    finally:
        write(path, row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('kin','threads','work'))
    parser.add_argument('identity', nargs='?')
    args = parser.parse_args()
    if args.action == 'work': work(args.identity)
    else: print(json.dumps(request(args.action, {})))


if __name__ == '__main__':
    main()
