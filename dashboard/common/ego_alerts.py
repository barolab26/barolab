"""Source-backed EGO incidents; the existing staff worker owns all execution."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re

from common.collection_observability import locked, load, write

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))
PORTS = {'soultin':9334, 'soul5373':9333, 'yoon_master':9335,
         'adinfo0905':9231, 'stone0747':9230}
DONE = {'published', 'published_verified', 'verified', 'reserved', 'completed', 'done', 'finished'}


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def incidents(data, now):
    """Do not infer a failed submission from an open tab, old count or old error."""
    day = now.astimezone(KST).date()
    candidates = []
    if data.get('cf', {}).get('date') == day.isoformat():
        candidates += [('cf_blog', r) for r in data['cf'].get('items', [])]
    if data.get('naver', {}).get('date') == day.isoformat():
        for account in data['naver'].get('accounts', []):
            candidates += [('naver_blog', {**r, 'account':account['account']}) for r in account.get('slots', [])]
    workflow = data.get('naverWorkflow') or {}
    candidates.append(('naver_blog', workflow))
    candidates += [('naver_kin', r) for r in data.get('kinOperationsRows', [])]
    for channel, row in candidates:
        status = row.get('state', row.get('status', ''))
        if status in DONE or row.get('publicPublicationVerified'):
            continue
        observed = next((_date(row.get(k)) for k in ('updated_at', 'lastErrorAt', 'updatedAt', 'attemptStartedAt', 'startedAt', 'observedAt') if _date(row.get(k))), None)
        progress=row.get('progress') or {}
        progress_at=progress.get('updatedAt')
        if isinstance(progress_at,str) and len(progress_at)==8:
            progress_at=str(progress.get('workDate') or row.get('workDate') or day.isoformat())+'T'+progress_at+'+09:00'
        observed=_date(progress_at) or observed
        if observed is None or observed.astimezone(KST).date() != day or observed > now:
            continue
        error = str(row.get('lastError') or row.get('failureReason') or row.get('reason') or '')
        cause = None
        uncertain = status in ('publishing', 'submitted_unverified', 'interrupted_unknown')
        if re.search(r'captcha|캡차|자동입력|보안문자|account.?protection', error, re.I):
            cause = 'captcha'; summary = '캡차 감지: 자동 제출 중지, 기존 결과 확인'
        elif re.search(r'blocked|disabled|등록.*차단|submit.*차단', error, re.I):
            cause = 'submit_blocked'; summary = '등록 버튼 차단: 편집기와 제출 결과 점검'
        elif channel == 'cf_blog' and re.search(r'\b[45]\d\d\b|timeout|timed out|타임아웃', error, re.I):
            cause = 'api_error'; summary = 'API 오류 또는 응답 제한 시간 초과'
        elif channel in ('naver_kin', 'naver_blog') and status in ('prepared', 'publishing', 'started', 'running', 'processing', 'submitted_unverified', 'interrupted_unknown') and 180 <= (now - observed).total_seconds():
            cause = 'submission_unknown' if uncertain else 'editor_stalled'
            summary = '제출 결과 미확정: 중복 등록 금지, 공개 결과 우선 확인' if uncertain else '편집·답변 작업 3분 이상 진행 갱신 없음'
        if cause is None:
            continue
        identity = str(row.get('question_id') or row.get('slot_id') or row.get('domain') or row.get('account') or '')
        if not identity:
            continue
        # Attempt identity changes only when a real new attempt is observed.
        attempt = row.get('attemptStartedAt') or row.get('startedAt') or row.get('slot_id') or day.isoformat()
        key = hashlib.sha256(json.dumps([day.isoformat(), channel, identity, attempt, cause]).encode()).hexdigest()[:32]
        yield {'id':key, 'channel':channel, 'identity':identity, 'account':row.get('account', ''),
               'port':PORTS.get(row.get('account'), 9440 if channel == 'cf_blog' else None),
               'cause':cause, 'summary':summary, 'submissionUncertain':uncertain,
               'observedAt':observed.isoformat(), 'title':re.sub(r'[\x00-\x1f<>]', ' ', str(row.get('title') or row.get('keyword') or row.get('topic') or identity))[:90]}
    active = {PORTS.get(r.get('account'), 9440 if channel == 'cf_blog' else r.get('port')) for channel, r in candidates
              if r.get('status', r.get('state')) in ('processing', 'publishing', 'started', 'running', 'prepared')
              and any((_date(r.get(k)) or datetime.min.replace(tzinfo=KST)).astimezone(KST).date() == day
                      for k in ('updated_at', 'observedAt', 'updatedAt', 'attemptStartedAt', 'startedAt'))}
    for browser in (data.get('remote') or {}).get('fleet', []):
        for tab in browser.get('tabs',[]):
            if tab.get('captchaVisible') is not True:continue
            port=browser.get('port');identity=str(tab.get('questionId') or tab.get('id') or port)
            key=hashlib.sha256(f'{day}:captcha:{port}:{identity}'.encode()).hexdigest()[:32]
            yield {'id':key,'channel':'naver_kin' if tab.get('questionId') else 'browser','identity':identity,
                   'account':browser.get('account',''),'port':port,'cause':'captcha','summary':'표시된 캡차 감지: 보호 절차 유지, 기존 제출 결과 확인',
                   'submissionUncertain':True,'observedAt':now.isoformat(),'title':str(tab.get('title',''))[:90]}
        if browser.get('online') is not False or browser.get('port') not in active:
            continue
        port = browser.get('port')
        key = hashlib.sha256(f'{day}:cdp:{port}'.encode()).hexdigest()[:32]
        yield {'id':key, 'channel':'browser', 'identity':str(port), 'account':browser.get('account', ''),
               'port':port, 'cause':'cdp_offline', 'summary':'작업 중 CDP 연결 끊김: 기존 프로필 상태 점검',
               'submissionUncertain':True, 'observedAt':now.isoformat(), 'title':''}


def observe(data, root=ROOT, now=None):
    """Claim one incident per tick; only the registered worker can repair submission."""
    now = now or datetime.now(KST)
    directory = Path(root) / 'dashboard/data/ego-alerts'
    path = directory / 'tickets.json'
    current = list(incidents(data, now))
    if not current:
        return None
    with locked(directory):
        state = load(path, {'tickets':{}})
        tickets = state.setdefault('tickets', {})
        pending = next((r for r in current if r['id'] not in tickets or tickets[r['id']].get('status') == 'delivery_pending'), None)
        if pending is None:
            return None
        if pending['id'] not in tickets:
            if len(tickets) >= 256:
                # Keep active-day dedup identities; old tickets remain in staff receipts.
                old = [k for k, r in tickets.items() if not r.get('createdAt', '').startswith(now.date().isoformat())]
                for key in old:
                    tickets.pop(key)
                if len(tickets) >= 256:
                    return None
            tickets[pending['id']] = {**pending, 'createdAt':now.isoformat(), 'status':'delivery_pending'}
        row = tickets[pending['id']]
        write(path, state)
    from common.crew_chat_bridge import emit_pipeline_crew_message
    from server.agent_tools import enqueue_staff_request
    message_id = 'ego-alert-' + row['id']
    receipt = emit_pipeline_crew_message('ego-lite',
        f"[EGO ALERT] @팀장: {row['port'] or ''} {row['account']} {row['channel']}에서 '{row['title']}' 작업 지연 감지 (원인: {row['summary']})",
        handoff='jarvis', status='needs_attention', step='ego-alert',
        result_summary=row['summary'], msg_id=message_id)
    if receipt != message_id:
        return row
    from common.crew_chat_bridge import emit_work_event
    emit_work_event(actor='ego-lite',actor_label='EGO Lite',owner_agent='jarvis',task_id='ego-alert:'+row['id'],phase='progress',stage='ego-alert',output_kind=f"{row['port']} {row['account']} · {row['title']} · {row['summary']}")
    # Reuse the bounded, durable worker queue, with no shell or unchecked retry.
    patch = {'agent':'patch', 'tool':'read_agent_status', 'args':{}}
    if (row['channel'] == 'naver_kin' and row['account'] in ('adinfo0905', 'stone0747')
            and re.fullmatch(r'[0-9]{1,24}', row['identity']) and row['cause'] != 'captcha'):
        # The registered helper checks existing publication before any bounded click.
        patch = {'agent':'patch', 'tool':'repair_kin_submission',
                 'args':{'account':row['account'], 'question_id':row['identity']}}
    dispatch = enqueue_staff_request('ego-alert:' + row['id'], [
        {'agent':'jarvis', 'tool':'read_agent_status', 'args':{}}, patch,
        {'agent':'trace', 'tool':'read_agent_status', 'args':{}}])
    with locked(directory):
        state = load(path, {'tickets':{}})
        state['tickets'][row['id']].update(status='inspection_queued', messageId=message_id,
                                          requestId=dispatch['requestId'])
        write(path, state)
    return state['tickets'][row['id']]
