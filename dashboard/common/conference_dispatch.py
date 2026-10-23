"""Timers request conferences; the existing crew consumer owns execution."""
import argparse
import hashlib
import json
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
            return {'status': 'conference_pending', 'agendaId': key}
        if time.time() < row.get('retryAt', 0):
            return {'status': 'conference_retry_wait', 'agendaId': key}
        row = {'agendaId': key, 'kind': kind, 'arguments': arguments, 'status': 'queued', 'requestedAt': time.time()}
        write(path, row)
    return {'status': 'conference_requested', 'agendaId': key}


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
            return original(account, url, answer, before_submit)
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
    author = engine._threads_authoring_prepare_next
    def prepare_next(config, publication_day, slot, *args, **kwargs):
        return author_after_conference(config['account_key'], str(publication_day)+'-'+str(slot), '다음 Threads 게시의 주제·독자·본문 구조와 유입 전략을 결정한다.', author, config, publication_day, slot, *args, **kwargs)
    engine._threads_authoring_prepare_next = prepare_next
    original = engine._threads_pipeline_publish
    def publish(part_id, config, *args, **kwargs):
        folder = folder_for('threads_posting', day, str(part_id))
        planning_or_memory(config['account_key'], 'Threads 게시 건 '+str(part_id)+'의 독자·표현·유입 전략', folder, {}, channel='threads')
        result = original(part_id, config, *args, **kwargs)
        engine._conference_results.append(result)
        return result
    engine._conference_results = []
    engine._threads_pipeline_publish = publish
    return engine


def report_outcome(receipt, task_id):
    """Report verified publishing facts, never a child's operating-system exit code."""
    from agents.agent_tools import staff_tool_reply
    from common.crew_chat_bridge import emit_work_event
    if not isinstance(receipt, dict):
        return None
    public = (receipt.get('publicPublicationVerified') is True and receipt.get('httpStatus') == 200
              or receipt.get('verified') is True and receipt.get('public') is True
              or receipt.get('state') == 'published_verified')
    reserved = receipt.get('submissionStatus') == 'verified_reserved' and bool(receipt.get('verificationSource'))
    pending = receipt.get('state') in ('api_submitted','submitted_unknown') or receipt.get('submissionStatus') in ('submitting','submission_unknown')
    if not public and not reserved and not pending and not receipt.get('errorType'):
        return None
    address = receipt.get('publicUrl') or receipt.get('answer_url') or receipt.get('permalink') or ''
    facts = {'outcome':'게시 성공' if public and address else '예약 완료' if reserved else '게시 확인 중' if pending else '게시 실패',
             'publicationVerified':bool(public and address),'reservationVerified':reserved,
             'publicUrl':address if public else '', 'reserveTime':receipt.get('reserveTime'),
             'account':receipt.get('account') or receipt.get('domain'),
             'channel':receipt.get('channel') or receipt.get('project'),
             'title':receipt.get('title'), 'slot':receipt.get('slot') or receipt.get('scheduledSlot'),
             'submissionState':receipt.get('submissionStatus') or receipt.get('state'),
             'submittedUrl':address if pending else '', 'errorType':receipt.get('errorType'),
             'nextAction':'실제 게시 본문과 계정 확인 완료' if public else '예약 목록과 지정 시각 확인 완료' if reserved else '담당 직원이 기존 제출 결과를 재조회한다. 확인 전에는 재제출하지 않는다.' if pending else '담당 직원이 원인을 진단하고 같은 안건에서 복구한다.'}
    response=staff_tool_reply('publi',task_id,{'tool':'publication_verification'},facts,stage='staff-terminal-response')
    emit_work_event(actor='publi',actor_label='퍼블리',task_id=task_id,phase='completed',stage='staff-terminal-response',
        message_kind='staff_reply',requested_to='jarvis',model=response['route']['events'][-1]['actualModel'],
        output_kind=response['reply'],deliverable_url=facts['publicUrl'])
    return facts


def work(identity):
    if len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
        raise ValueError('Invalid agenda identity')
    path = QUEUE / (identity + '.json')
    # Parent stores ownership before the child reads the request.
    with locked(QUEUE):
        row = load(path)
    try:
        if (Path.home() / 'EGO_EXEC_DISABLED').exists():
            raise RuntimeError('Execution disabled')
        if row['kind'] == 'parameters':
            from common.channel_parameters import main
            a = row['arguments']; argv = [a['action']]
            for key in ('date', 'account', 'slot'):
                if a.get(key): argv += ['--'+key, a[key]]
            result = main(argv, conference_worker=True)
            receipts = result if isinstance(result, list) else [result]
        else:
            engine = install_channel_conferences(row['kind'])
            if row['kind'] == 'kin': engine.main(['--tick', '--scheduled'])
            else:
                sys.argv = ['conference', '--tick']
                engine.main()
            receipts = engine._conference_results
        row['outcomes'] = []
        for receipt in receipts:
            try:
                outcome = report_outcome(receipt, 'conference:'+identity[:24])
                if outcome: row['outcomes'].append(outcome)
            except Exception as exc:
                row['reportPending'] = True
                row['reportErrorType'] = type(exc).__name__
        row.update(status='completed', completedAt=time.time(), retryAt=time.time()+60)
    except Exception as exc:
        row.update(status='failed', errorType=type(exc).__name__, retryAt=time.time()+300)
        try:
            row['failureReport'] = report_outcome({'errorType':type(exc).__name__}, 'conference:'+identity[:24])
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
