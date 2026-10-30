"""One durable business agenda, from briefing through acknowledged closing report."""
from contextlib import contextmanager
from contextvars import ContextVar
from common import runtime_locks as fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from common.collection_observability import load, write, locked

DATA = Path(__file__).resolve().parents[1] / 'data'
STATE = DATA / 'active-agenda.json'
ROWS = DATA / 'publication-conferences' / 'operations'
_CONTEXT = ContextVar('business_agenda', default=None)
_EXECUTING = ContextVar('agenda_execution', default=False)
READ_ONLY = frozenset(('read_agent_status', 'read_coding_job_status', 'read_patch_code_status'))
LABELS = {'queued':'대기', 'meeting':'방향·전략 협의', 'executing':'실행 중',
          'recovering':'같은 안건 복구 중', 'verifying':'실제 결과 검증',
          'report_pending':'마무리 보고 전달 중', 'blocked':'미해결 · 재개 조건 대기',
          'closed':'검증·마무리 완료', 'suspended':'대표 지시로 유예 · 미해결'}


class AgendaWaiting(RuntimeError):
    pass


def validate_business_experiment(value):
    from datetime import date
    from urllib.parse import urlsplit
    if not isinstance(value, dict):
        raise ValueError('Business experiment required')
    for key in ('hypothesis', 'measurementDate', 'successMetric', 'stopCondition'):
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 1000:
            raise ValueError('Missing bounded experiment field: ' + key)
    date.fromisoformat(value['measurementDate'])
    if value.get('evidenceConfidence') not in ('low', 'medium', 'high') or type(value.get('maxModelCalls')) is not int or not 1 <= value['maxModelCalls'] <= 40:
        raise ValueError('Invalid experiment confidence or resource bound')
    target = value.get('targetUrl')
    if not isinstance(target, str):
        raise ValueError('Experiment target must be a URL or empty')
    parsed = urlsplit(target)
    if target and (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password):
        raise ValueError('Invalid experiment target URL')
    return value


def enabled():
    return load(STATE).get('enabled', True) is not False


def path(identity):
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
        raise ValueError('Invalid business agenda identity')
    result = ROWS / (identity + '.json')
    if result.is_symlink():
        raise ValueError('Symlink agenda denied')
    return result


def get(identity):
    return load(path(identity))


def _save(row):
    row['updatedAt'] = time.time()
    write(path(row['id']), row)
    path(row['id']).chmod(0o600)


def initialize():
    """Deployment calls this only after existing publishers have drained."""
    with locked(ROWS):
        state = load(STATE)
        state.update(schema='barolab-work-agenda-v1', enabled=True)
        state.setdefault('pending', [])
        state.setdefault('recent', [])
        write(STATE, state)


LANE_LIMITS = {'cf_blog': 3, 'naver_blog': 1, 'naver_kin': 1, 'threads': 1}


def active_ids(state=None):
    state = load(STATE) if state is None else state
    ids = list(state.get('activeIds') or [])
    primary = state.get('activeId')
    if primary and primary not in ids:
        ids.insert(0, primary)
    out = []
    for i in ids:
        if i and i not in out:
            r = get(i)
            if r and r.get('status') not in ('closed', 'suspended'):
                out.append(i)
    return out


def active_rows(state=None):
    return [get(i) for i in active_ids(state)]


def active():
    state = load(STATE)
    rows = active_rows(state)
    primary = next((r for r in rows if r['id']==state.get('activeId')), None)
    if primary and not waiting_investigation(primary):
        return primary
    runnable = next((r for r in rows if not waiting_investigation(r)), None)
    if runnable:
        return runnable
    identity = state.get('activeId')
    if identity:
        r = get(identity)
        if r and r.get('status') not in ('closed', 'suspended'):
            return r
    rows = active_rows(state)
    return rows[0] if rows else {}


def waiting_investigation(row):
    if row.get('kind') != 'goal' or row.get('status') != 'blocked' or running(row):
        return False
    identity=row.get('controllerGoalId') or row.get('source',{}).get('goalId')
    goal=load(DATA/'chats/reasoning-goals'/(identity+'.json')) if identity and re.fullmatch(r'[a-f0-9]{64}',identity) else {}
    return goal.get('status') in ('answered','blocked') and not goal.get('pendingAction') and not goal.get('pendingConference')


def current():
    value = _CONTEXT.get()
    if value is None:
        try:
            value = json.loads(os.environ.get('BAROLAB_AGENDA_CONTEXT', 'null'))
        except (ValueError, TypeError):
            value = None
    return value if isinstance(value, dict) else None


def token(row):
    return {key: row[key] for key in ('id', 'version', 'owner')}


def require(*, project=None):
    if not enabled():
        return {}
    value = current()
    row = get(value['id']) if value and isinstance(value.get('id'), str) else active()
    if not value or not row or token(row) != value or row['status'] in ('closed', 'suspended'):
        raise AgendaWaiting('현재 안건의 실행권이 없습니다. 회의실 안건 순서에 따라 대기합니다.')
    if project and row.get('project') not in (project, 'all'):
        raise AgendaWaiting('다른 프로젝트 작업은 현재 안건을 마무리한 뒤 진행합니다.')
    return row


@contextmanager
def context(value):
    marker = _CONTEXT.set(value)
    try:
        if enabled():
            require()
        yield
    finally:
        _CONTEXT.reset(marker)


def child_environment(environment=None):
    result = dict(os.environ if environment is None else environment)
    value = current()
    if value:
        result['BAROLAB_AGENDA_CONTEXT'] = json.dumps(value)
    return result


def process_identity(pid):
    if os.name == 'nt':
        return fcntl.process_start_ticks(pid)
    try:
        stat = Path('/proc', str(pid), 'stat').read_text().split(') ', 1)[1].split()
        return stat[19] if stat[0] != 'Z' else None
    except (OSError, IndexError):
        return None


def running(row):
    return [p for p in row.get('processes', []) if process_identity(p['pid']) == p['startTicks']]


def register_process(pid):
    if not enabled():
        return
    row = require()
    ticks = process_identity(pid)
    if not ticks:
        return
    with locked(ROWS):
        row = get(row['id'])
        row['processes'] = [p for p in running(row) if p['pid'] != pid] + [{'pid':pid, 'startTicks':ticks}]
        _save(row)


def bind_target(target):
    if not enabled() or not current():
        return
    row=require()
    with locked(ROWS):
        row=get(row['id'])
        if row.get('workTarget') and row['workTarget']!=target:
            raise AgendaWaiting('현재 계정·날짜·슬롯을 먼저 마무리해야 합니다. 다른 작업은 다음 안건입니다.')
        row['workTarget']=target
        _save(row)


def staff_agenda(request_id, actions):
    if not enabled():return None
    projects=set()
    for action in actions:
        args=action['args'];project=args.get('project')
        if action['tool']=='advance_project_recovery':
            from common.repair_workflow import _recovery_row
            _,recovery=_recovery_row(args['task_id'],args['plan_sha256'])
            project=recovery['plan']['project']
        project=project or ('naver_kin' if action['tool']=='repair_kin_submission' else 'cf_blog' if 'cf_' in action['tool'] else 'all')
        projects.add(project)
    if len(projects)>1:raise ValueError('Different projects require separate business agendas')
    project=next(iter(projects))
    inspection=all(a['tool'] in READ_ONLY for a in actions)
    title=('원천 상태 확인' if inspection else '등록된 작업 실행·복구')+' · '+project
    return propose('staff',request_id,title=title,project=project,source={'requestId':request_id,'actions':actions},
                   completion='등록된 원천 상태를 읽고 관측 결과와 미확인 항목을 보고' if inspection else '원래 작업의 실제 해결 증거와 담당자·팀장 마무리 보고')


def staff_result(row, receipt_path):
    if not enabled() or not row.get('businessAgendaId'):return
    agenda=get(row['businessAgendaId'])
    if row['status'] in ('queued','acknowledged','awaiting_completion'):return
    results=[r.get('result',{}) for r in row.get('results',[])]
    if agenda['kind']=='conference':
        actions=row.get('actions',[])
        if len(actions)!=1 or actions[0]['tool']!='repair_kin_submission' or agenda['project']!='naver_kin':return
        source=agenda.get('workTarget') or agenda['source']
        original=load(ROWS.parent/(agenda['source']['conferenceId']+'.json'))
        target=original.get('retryTarget') or next(iter(original.get('executionFailures',[])),{})
        args=actions[0]['args'];result=results[0] if len(results)==1 else {}
        if args.get('account')!=source['arguments'].get('account') or args.get('question_id')!=target.get('questionId'):return
        exact=(args.get('account')==source['arguments'].get('account')==result.get('account')
               and args.get('question_id')==target.get('questionId')==result.get('questionId'))
        if not exact or not result.get('publicUrl') or result.get('httpStatus')!=200 or result.get('publicVerified') is not True:
            hold(agenda['id'],result.get('reason') or '같은 답변의 실제 공개·계정 검증이 아직 완료되지 않았습니다.',recovery=True)
            return
    elif agenda['kind']!='staff':return
    inspection=all(a['tool'] in READ_ONLY for a in row['actions'])
    proof=bool(results) and row['status']=='completed' and all(r.get('ok') is True and
        (inspection or r.get('publicationVerified') is True or r.get('recoveryVerified') is True or r.get('reservationVerified') is True) for r in results)
    if proof:
        replies=[r for r in row.get('results',[]) if r.get('staffResponse')]
        last=replies[-1] if replies else None
        response=last['staffResponse'] if last else None
        observed=(response['route'].get('events') or [{}])[-1] if response else {}
        staff={'actor':last['agent'],'text':response['reply'],'route':{'provider':observed.get('provider'),
               'model':observed.get('actualModel'),'reasoningEffort':observed.get('reasoningEffort')}} if response else None
        verified(agenda['id'],{'verified':True,'source':str(receipt_path),'scope':'원천 상태 조회' if inspection else '실제 업무 결과',
            'results':[{k:r.get(k) for k in ('status','project','publicationVerified','recoveryVerified','reservationVerified','publicUrl','account','questionId')} for r in results]},staff=staff)
    else:
        hold(agenda['id'],'직원 실행 결과에서 원래 업무의 해결 증거가 확인되지 않았습니다. 같은 안건에서 원인을 조사합니다.',recovery=True)


@contextmanager
def execution(project=None):
    """The process lock also excludes simultaneous steps of the SAME agenda."""
    if not enabled() or _EXECUTING.get()==os.getpid():
        if enabled():
            require(project=project)
        yield
        return
    row = require(project=project)
    if row['status']=='report_pending':raise AgendaWaiting('실행 검증은 끝났습니다. 보고 전달만 재시도합니다.')
    if row.get('switchRequest'):
        raise AgendaWaiting('대표님의 전환 지시를 안전한 중단점에서 반영하고 있습니다.')
    if not row.get('plan') or not row.get('events', {}).get('opening', {}).get('receivedAt'):
        raise AgendaWaiting('실행 방향과 완료 조건을 회의실에 기록한 뒤 실행합니다.')
    ROWS.mkdir(parents=True, exist_ok=True)
    lock_file = ROWS / f"execution-{row['id']}.lock"
    with lock_file.open('a+b') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AgendaWaiting('현재 안건의 앞선 실행이 아직 진행 중입니다.') from None
        require(project=project)
        marker = _EXECUTING.set(os.getpid())
        register_process(os.getpid())
        try:
            yield
        finally:
            _EXECUTING.reset(marker)
            with locked(ROWS):
                saved = get(row['id'])
                saved['processes'] = [p for p in running(saved) if p['pid'] != os.getpid()]
                _save(saved)


def propose(kind, key, *, title, project, source, completion, priority=10, not_before=0, inherit=True):
    """Stable business keys merge timer ticks; attempts never replace the agenda."""
    if not enabled():
        return None
    if inherit and current():
        row = require(project=project)
        return row['id']
    identity = hashlib.sha256(json.dumps([kind, key], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with locked(ROWS):
        state = load(STATE)
        row = get(identity)
        if row:
            # Merge observations without resetting ownership, the plan or attempt history.
            if row.get('status') == 'closed' and kind == 'conference' and not row.get('verification', {}).get('verified') and row.get('closeReason') != 'jarvis_executive_pruned':
                row.update(status='queued', priority=priority, notBefore=not_before, controllerFailures=0, nextCheckAt=0, processes=[], events={})
                for k in ('blocker', 'closedAt', 'closeReason', 'recoveryWatch', 'controllerGoalId', 'recoveryGoalId'):
                    row.pop(k, None)
                conf_id = (source or {}).get('conferenceId') or (row.get('source') or {}).get('conferenceId')
                if conf_id:
                    cpath = ROWS.parent / f'{conf_id}.json'
                    crow = load(cpath)
                    if crow and crow.get('status') in ('failed', 'unknown'):
                        crow.update(status='queued', retryAt=0, requestedAt=time.time())
                        for ck in ('errorType', 'failureReason', 'failureDiagnostic', 'failureReport', 'interruptedAt', 'completedAt', 'pid', 'startTicks'):
                            crow.pop(ck, None)
                        write(cpath, crow)
            row.update(lastObservedAt=time.time(),observationCount=row.get('observationCount',1)+1,
                       latestObservationSha256=hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
            _save(row)
            cur_active = set(active_ids(state))
            if row.get('status') == 'queued' and identity not in cur_active and identity not in state.get('pending', []) and identity not in state.get('suspended', []):
                state.setdefault('pending', []).append(identity)
                write(STATE, state)
            return identity
        if len(state.get('pending', [])) >= 200:
            raise AgendaWaiting('안건 대기열이 가득 찼습니다. 기존 안건을 먼저 마무리합니다.')
        row = {'id':identity, 'kind':kind, 'title':str(title)[:500], 'project':project,
               'source':source, 'completionCriteria':completion, 'priority':priority,
               'notBefore':not_before, 'createdAt':time.time(), 'status':'queued','manualNudges':0,
               'version':1, 'owner':uuid.uuid4().hex, 'plan':[], 'events':{}, 'processes':[]}
        _save(row)
        state.setdefault('pending', []).append(identity)
        write(STATE, state)
    return identity


def read_only_agenda(row):
    actions=row.get('source',{}).get('actions') or []
    return row.get('kind')=='staff' and bool(actions) and all(a.get('tool') in READ_ONLY for a in actions)


def admit(identity):
    if not enabled():
        return None
    with locked(ROWS):
        state = load(STATE)
        cur_rows = active_rows(state)
        for r in cur_rows:
            if r['id'] == identity:
                return token(r)
        candidates = [get(key) for key in state.get('pending', [])]
        eligible = [r for r in candidates if r and r['status']=='queued' and r.get('notBefore',0)<=time.time()]
        if not eligible:
            return None
        chosen = next((r for r in sorted(eligible, key=lambda r:(0 if r.get('kind') == 'conference' else 1, r['priority'], r['createdAt'])) if r['id'] == identity), None)
        if not chosen:
            return None
        proj = chosen.get('project') or 'other'
        limit = LANE_LIMITS.get(proj, 1)
        lane_active = [r for r in cur_rows if (r.get('project') or 'other') == proj and not waiting_investigation(r)
                       and read_only_agenda(r)==read_only_agenda(chosen)]
        if len(lane_active) >= limit:
            return None
        chosen.update(status='report_pending' if chosen.get('verification',{}).get('verified') else 'meeting', activatedAt=time.time())
        chosen['measurementStartedAt'] = chosen['activatedAt']
        _save(chosen)
        new_ids = [r['id'] for r in cur_rows] + [identity]
        state['activeIds'] = new_ids
        state['activeId'] = new_ids[0]
        if identity in state.get('pending', []):
            state['pending'].remove(identity)
        write(STATE, state)
        return token(chosen)


def short_title(row):
    name = {'naver_blog': '네이버 블로그', 'cf_blog': 'CF 블로그', 'naver_kin': '네이버 지식iN',
            'threads': 'Threads', 'collections': '조회·수집', 'legacy_remodel': '콘텐츠 점검',
            'mobile_apps': '앱 프로젝트'}.get(row.get('project'), '운영 점검')
    args = (row.get('workTarget') or row.get('source') or {}).get('arguments', {})
    match = re.search(r'(?:^|T)([0-2][0-9]:[0-5][0-9])', str(args.get('slot') or ''))
    return '[' + name + (' ' + match[1] + ' 슬롯' if match else '') + ']'


def event(row, stage, actor, text, route=None):
    if stage == 'closing':
        text = ('[안건 종결] ' + short_title(row))[:30]
    suffix=stage+('-'+str(row['version']) if stage=='suspension' else '')
    return {'id':'agenda-'+row['id']+'-'+suffix, 'agendaId':row['id'], 'stage':stage,
            'who':actor, 'text':text, 'route':route or {}, 'ts':int(time.time()*1000)}


def record_plan(identity, plan, route=None):
    with locked(ROWS):
        row = get(identity)
        if not row.get('plan'):
            if not plan or not all(isinstance(step,str) and step.strip() for step in plan):
                raise ValueError('An agenda needs a concrete plan before execution')
            row['plan'] = plan[:8]
        if 'opening' not in row.get('events', {}):
            text = '안건: '+row['title']+'\n진행 방향: '+' → '.join(row['plan'])+'\n완료 조건: '+row['completionCriteria']
            row.setdefault('events', {})['opening'] = event(row, 'opening', 'jarvis', text, route)
        _save(row)


def acknowledge(identity, stage, event_id):
    with locked(ROWS):
        row = get(identity)
        note = row.get('events', {}).get(stage)
        if not note or note['id'] != event_id:
            raise ValueError('Unrecorded agenda event')
        note.setdefault('receivedAt', time.time())
        _save(row)


def flush_events(identity):
    from common.crew_chat_bridge import _deliver
    row = get(identity)
    for stage in ('opening', 'blocked', 'staff_result', 'closing', 'suspension'):
        note = row.get('events', {}).get(stage)
        if note and not note.get('receivedAt'):
            _deliver({'id':note['id'], 'eventType':'crew_agenda_event', 'agendaId':identity, 'stage':stage})
            row = get(identity)
            if not row.get('events', {}).get(stage, {}).get('receivedAt'):
                return False
    return True


def progress(identity, status, detail):
    with locked(ROWS):
        row = get(identity)
        if row['status'] in ('closed','suspended','report_pending'):
            return
        row.update(status=status, lastAction=str(detail)[:1000])
        _save(row)


def hold(identity, reason, *, recovery=False):
    with locked(ROWS):
        row = get(identity)
        if row['status'] in ('closed','suspended','report_pending'):
            return
        conference=load(ROWS.parent/(row['source']['conferenceId']+'.json')) if row.get('source',{}).get('conferenceId') else {}
        pending=(conference.get('businessAgendaId')==identity and conference.get('status') in ('queued','running'))
        row.update(status='recovering' if recovery or pending or running(row) else 'blocked', blocker=str(reason)[:1000])
        row['waitingFor']={'owner':'patch' if row.get('project')!='collections' else 'trace',
                           'condition':str(reason)[:500],'nextCheckAt':time.time()+300}
        if 'blocked' not in row['events']:
            row['events']['blocked'] = event(row, 'blocked', 'jarvis',
                '같은 안건을 유지합니다: '+row['title']+'\n'+row['blocker']+'\n실제 해결은 미완료이며 다음 안건을 시작하지 않았습니다.')
        _save(row)


def verified(identity, evidence, *, staff=None, manager=None):
    """Only trusted receipt adapters call this; models cannot call the closing API."""
    if not evidence or evidence.get('verified') is not True or not evidence.get('source'):
        raise ValueError('Actual operation evidence is required')
    with locked(ROWS):
        row = get(identity)
        if row['status'] == 'closed':
            return
        row.update(status='suspended' if row['status']=='suspended' else 'report_pending', verification=evidence, verifiedAt=time.time(),
                   lastAction='정해 둔 범위의 실제 결과를 확인했습니다. 담당자와 팀장의 마무리 보고를 전달하고 있습니다.')
        row.pop('blocker',None)
        for stage, reply in (('staff_result',staff), ('closing',manager)):
            if reply and stage not in row['events']:
                row['events'][stage] = event(row, stage, reply['actor'], reply['text'], reply.get('route'))
        _save(row)


def finish_investigation(identity, summary, reason):
    """End investigation and report honestly; this does not certify publication or repair."""
    row = get(identity)
    if row.get('status') in ('closed', 'suspended'):
        return
    route = {'provider': 'host', 'model': 'investigation-reporter'}
    if not row.get('events', {}).get('opening'):
        record_plan(identity, ['수집한 근거와 미해결 사항을 보고하고 조사 안건을 종결합니다.'], route)
    with locked(ROWS):
        row = get(identity)
        row.update(status='report_pending', investigationReport={'reason': reason, 'summary': summary},
                   nextCheckAt=0, controllerFailures=0, lastAction='조사 요약 보고 후 다음 안건으로 전환합니다.')
        row.pop('blocker', None)
        for stage, actor, message in (('staff_result', 'jarvis', summary), ('closing', 'jarvis', '조사 종결')):
            row.setdefault('events', {}).setdefault(stage, event(row, stage, actor, message, route))
        _save(row)


def _model_message(row, stage):
    from common.llm_client import generate_json
    routes = []
    def observed(provider, requested, state, **details):
        if state == 'returned':
            routes.append({'provider':provider,'model':details.get('actual_model'), 'reasoningEffort':details.get('reasoning_effort')})
    actor = ('doctor' if row['kind']=='audit' else 'radar' if row['kind']=='radar' else 'publi') if stage == 'staff_result' else 'jarvis'
    actor_label = '담당 직원' if stage == 'staff_result' else '팀장'
    channel_purposes = {
        'naver_blog': '소모성 비실명 블로그: 본진 리스크 방어 및 네이버 검색 트래픽을 CF 블로그(애드센스)로 토스하는 유입 브릿지. 계정 사리기보다 노출과 클릭 유도가 핵심 목적.',
        'cf_blog': '핵심 캐시카우 (하루  애드센스 수익 기지): 양질의 정보와 체류시간 확보, 고단가 광고 배치 최적화 및 외부 유입 트래픽 흡수가 핵심 목적.',
        'threads': 'SNS 고속 유입 채널: 피드 후킹과 첫 댓글 브릿지를 통해 CF 블로그로 대량 트래픽을 넘기는 것이 핵심 목적.',
        'naver_kin': '지식인 맞춤형 솔루션 제공 및 CF 블로그 신뢰 유입을 만드는 전초기지.',
    }
    purpose = (row.get('source') or {}).get('businessPurpose') or channel_purposes.get(row.get('project'), '하루  수익 달성에 기여하는 채널 콘텐츠 생산 및 트래픽 유입')
    from common.asset_map import get_asset_map_summary
    asset_map_text = get_asset_map_summary()
    prompt = ('당신은 단순한 규칙 검사관이 아니라 사업가 정신을 가진 ' + actor_label + '이다. 우리 팀의 최우선 단일 목표는 [하루 수익  달성]이다.\n' + asset_map_text + '\n'
              '[이 안건의 비즈니스 목적(Why)] ' + purpose + '\n'
              '[의무 자문 2단계 (First-Principles Check)]\n'
              '판단과 계획 수립 시 반드시 다음 2가지를 스스로 묻고 답변에 반영하라:\n'
              '1) 원초적 목적: 지금 내 판단/계획이 하루  수익과 트래픽 유입에 실제로 기여하는가? 껍데기 형식(도장 찍기)에 매몰되지 않았는가?\n'
              '2) 사소한 껍데기 의심: 마주한 에러나 제한(로그인 필요, 형식 불일치, 일시적 차단 등)이 진짜 물리적 벽인가, 아니면 URL 이동, API 폴백, 대안 경로로 뚫을 수 있는 사소한 껍데기인가? 소극적 보류·중단은 엄격히 금지하며 무조건 대안을 찾아 전진하라.\n'
              '[절대 금지: 미수집 수치나 성공 날조, 예약/공개/조회 구분 혼동, 다른 작업을 완료했다고 허위 보고.]\n'
              '한국어로 간결하게 400자 이내로 답한다.\n' + json.dumps({
                  'stage': stage, 'title': row['title'], 'project': row['project'],
                  'businessPurpose': purpose, 'completionCriteria': row['completionCriteria'],
                  'source': row['source'], 'plan': row['plan'], 'verification': row.get('verification')}, ensure_ascii=False))
    schema = {'type':'object','properties':{'message':{'type':'string','minLength':1,'maxLength':500},
              'plan':{'type':'array','maxItems':4,'items':{'type':'string','minLength':1,'maxLength':300}}},
              'required':['message','plan'],'additionalProperties':False}
    value = generate_json(prompt, agent_slot=actor, response_schema=schema, timeout_seconds=150,
                          observer=observed, memory_read_only=True, crew_actor=actor,
                          crew_task_id='agenda:'+row['id'], crew_stage='agenda-'+stage)
    if not routes or not routes[-1].get('model'):
        raise ValueError('Actual agenda model route required')
    return value, routes[-1], actor


def prepare_open(identity):
    row = get(identity)
    if not row.get('plan') or 'opening' not in row.get('events', {}):
        if not row.get('plan'):
            if row.get('kind') in ('conference','staff'):
                fast_plan = [
                    f"[{row.get('project')}] 타깃 키워드 및 수익화(CPA/CPC/애드센스) 전략 앵글 확정",
                    "독자 체류시간·전환 극대화 본문 및 고해상도 시각 자료 생성",
                    "채널 발행·예약 실행 및 실제 영수증/공개 상태 검증",
                ]
                if row['kind']=='staff':
                    fast_plan=['등록된 담당자·도구로 지정 작업 실행','실제 반환값·공개 또는 조회 결과 확인','검증된 결과와 미해결 사항 보고']
                record_plan(identity, fast_plan, {'provider': 'host', 'model': 'fast-lane-dispatcher', 'reasoningEffort': 'fast'})
            else:
                value, route, _ = _model_message(row, 'opening')
                record_plan(identity, value['plan'], route)
        else:
            record_plan(identity, row['plan'])
    return flush_events(identity)


def finish_reports(identity):
    row = get(identity)
    if row['status'] != 'report_pending' or running(row):
        return False
    if row.get('verification', {}).get('verified') is True:
        fast_route = {'provider': 'host', 'model': 'fast-verified-reporter', 'reasoningEffort': 'fast'}
        with locked(ROWS):
            row = get(identity)
            if 'staff_result' not in row.get('events', {}):
                row.setdefault('events', {})['staff_result'] = event(row, 'staff_result', 'publi', f"[실행·검증 완료] {short_title(row)}", fast_route)
            if 'closing' not in row.get('events', {}):
                row.setdefault('events', {})['closing'] = event(row, 'closing', 'jarvis', '[안건 종결] ' + short_title(row), fast_route)
            _save(row)
    else:
        for stage in ('staff_result','closing'):
            if stage not in row['events']:
                value, route, actor = _model_message(row, stage)
                with locked(ROWS):
                    row = get(identity)
                    row['events'].setdefault(stage, event(row, stage, actor, value['message'], route))
                    _save(row)
                return True
    if not flush_events(identity):
        return False
    with locked(ROWS):
        state = load(STATE)
        row = get(identity)
        cur_ids = active_ids(state)
        if (identity not in cur_ids or running(row)
                or not all(row['events'][s].get('receivedAt') for s in ('opening','staff_result','closing'))):
            return False
        row.update(status='closed', closedAt=time.time())
        row['performance'] = performance(row)
        _save(row)
        new_ids = [i for i in cur_ids if i != identity]
        state['activeIds'] = new_ids
        state['activeId'] = new_ids[0] if new_ids else None
        state['recent'] = ([identity] + [i for i in state.get('recent',[]) if i!=identity])[:30]
        write(STATE, state)
    return True


def performance(row, ledger=None):
    ledger = load(DATA/'llm_usage_ledger.json') if ledger is None else ledger
    measured = ledger.get('byAgenda', {}).get(row['id'])
    result = {'wallTimeSeconds':max(0,(row.get('closedAt') or time.time())-row['activatedAt']) if row.get('activatedAt') else None,
        'measurementStartedAt':row.get('measurementStartedAt'),
        'coverage':'observed_calls_only', 'manualNudges':row.get('manualNudges'),
        'verifiedCompletions':1 if row.get('verification',{}).get('verified') is True else None}
    for key in ('coverageStartedAt','modelCalls','modelErrors','modelLatencyMs','routes','toolRoundTrips','toolFailures','uiActions','uiFailures'):
        result[key] = measured.get(key) if measured else None
    return result


def operational_state(row, goal=None, conference=None):
    goal=goal or {};conference=conference or {}
    if row.get('status') in ('report_pending','verifying') or goal.get('status')=='waiting_verification':return 'verification_or_ack_pending'
    if conference.get('status')=='running' and running(row):return 'running_publisher'
    if conference.get('status')=='failed' and conference.get('executionGeneration') and conference.get('attempts',0)>=3:return 'needs_ceo_action'
    if goal.get('status')=='waiting_external':return 'waiting_external'
    if row.get('status')=='blocked' and row.get('recoveryWatch',{}).get('state')=='needs_ceo_action':return 'needs_ceo_action'
    return 'internal_action_ready'


def compute_reverse_funnel_gap(business=None):
    """Calculate the Reverse-Funnel gap from observed revenue/traffic to the $100/day North Star."""
    import math
    if business is None:
        try:
            from server.growth import business_evidence
            business = business_evidence()
        except Exception:
            business = {}
    daily_target_usd = 100.0
    observed_usd = 0.0
    for row in business.get('priorDayRevenue') or []:
        amt = row.get('amount')
        if isinstance(amt, (int, float)) and amt > 0:
            cur = str(row.get('currency') or 'USD').upper()
            observed_usd += (amt / 1380.0) if cur == 'KRW' else float(amt)
    observed_usd = round(observed_usd, 4)
    revenue_gap_usd = round(max(0.0, daily_target_usd - observed_usd), 2)
    assumed_cpc_usd = 0.50
    required_clicks = int(math.ceil(revenue_gap_usd / assumed_cpc_usd))
    required_pv = int(required_clicks * 12.5)  # ~8% effective ad CTR across funnel

    observed_pv = 0
    observed_sessions = 0
    for site in business.get('trafficSites') or []:
        day_p = (site.get('periods') or {}).get('day') or {}
        pv = day_p.get('pageViews')
        sess = day_p.get('sessions')
        if isinstance(pv, (int, float)) and pv > 0:
            observed_pv += int(pv)
        if isinstance(sess, (int, float)) and sess > 0:
            observed_sessions += int(sess)
    traffic_gap_pv = max(0, required_pv - observed_pv)
    achievement_pct = round((observed_usd / daily_target_usd) * 100, 2)
    status = 'achieved' if observed_usd >= daily_target_usd else ('critical_gap' if observed_usd < 5.0 and observed_pv < 500 else 'in_progress')
    diagnosis = (
        f"목표 일수익 $100.00 (필요 클릭 약 {required_clicks}회 @ CPC $0.50 · 필요 유입 약 {required_pv:,} PV) 대비 "
        f"현재 실측 일수익 ${observed_usd:.2f} / 일유입 {observed_pv:,} PV ({observed_sessions:,} 세션) — "
        f"부족분 ${revenue_gap_usd:.2f} ({traffic_gap_pv:,} PV). "
        + ("단순 블로그 할당량 양산으로는 도달 불가. 고단가 앵커 원고 + 외부유입(Threads·지식iN·네이버 브릿지) 집중 살포 및 대표님 자원/승인 역제안(ask_ceo) 필수."
           if status == 'critical_gap' else "유입·전환율 상위 자산 중심 OSMU 확산 가속 필요.")
    )
    return {
        'dailyTargetUsd': daily_target_usd,
        'observedDailyRevenueUsd': observed_usd,
        'revenueGapUsd': revenue_gap_usd,
        'achievementPct': achievement_pct,
        'assumedCpcUsd': assumed_cpc_usd,
        'requiredDailyClicks': required_clicks,
        'requiredDailyPv': required_pv,
        'observedDailyPv': observed_pv,
        'observedDailySessions': observed_sessions,
        'trafficGapPv': traffic_gap_pv,
        'status': status,
        'diagnosis': diagnosis,
    }


def view():
    if not enabled():
        return {'enabled':False}
    state = load(STATE)
    def public(row):
        return {**{k:row.get(k) for k in ('id','title','project','status','plan','completionCriteria','lastAction','blocker','updatedAt','verifiedAt','closedAt')},
                'phase':('미해결 · 복구 조건 자동 확인' if row.get('status')=='blocked' and row.get('recoveryWatch') else LABELS.get(row.get('status'),'대기')), 'verified':bool(row.get('verification',{}).get('verified')),
                'automaticRecovery':{k:row.get('recoveryWatch',{}).get(k) for k in ('state','nextCheckAt','checks','lastChangeAt')},
                'ownerLabel':'팀장' if row.get('status') in ('meeting','report_pending') else {'publi':'퍼블리','trace':'트레이스','patch':'패치','doctor':'닥터','radar':'레이더','jarvis':'팀장'}.get((row.get('source',{}).get('actions') or [{}])[0].get('agent'), '퍼블리' if row.get('kind')=='conference' else '팀장')}
    current_row = active()
    shared=load(DATA/'live_snapshot.json').get('agendaControl',{}).get('active') or {}
    activity=shared.get('activity',{}) if current_row and shared.get('id')==current_row['id'] else {}
    proposals_state = load(DATA / 'ceo-proposals.json') or {}
    result={'enabled':True, 'active':public(current_row) if current_row else None,
            'pending':[public(get(i)) for i in state.get('pending',[])[:8]],
            'pendingCount':len(state.get('pending',[])),
            'waiting':[{**public(r),'waitingFor':r.get('waitingFor',{})} for r in active_rows(state) if waiting_investigation(r)],
            'suspended':[public(get(i)) for i in state.get('suspended',[])],
            'recent':[public(get(i)) for i in state.get('recent',[])[:5]],
            'reverseFunnel': state.get('reverseFunnel') or compute_reverse_funnel_gap(),
            'executiveBriefing': state.get('lastExecutiveBriefing', ''),
            'focusChannels': state.get('focusChannels', []),
            'ceoProposals': (proposals_state.get('proposals') or [])[:5]}
    if result['active']:result['active']['activity']=activity
    return result


def request_switch(identity, next_identity, command):
    """Only a direct CEO instruction or the explicit room control calls this."""
    with locked(ROWS):
        row=get(identity);next_row=get(next_identity)
        if active().get('id')!=identity or next_row.get('status')!='queued' or identity==next_identity:
            raise ValueError('현재 안건과 대기 안건을 다시 확인해 주세요.')
        if row['status']=='report_pending':
            raise ValueError('현재 안건의 마무리 보고 수신을 먼저 확인합니다.')
        row['switchRequest']={'nextId':next_identity,'command':command,'requestedAt':time.time()}
        _save(row)


def switch_once(row):
    request=row.get('switchRequest')
    if not request:return False
    with (ROWS/'execution.lock').open('a+b') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return False
        row=get(row['id'])
        if running(row):return False
        from common.conference_dispatch import QUEUE
        receipts=[load(p) for p in QUEUE.glob('*.json')]
        unsafe=any(r.get('businessAgendaId')==row['id'] and
            (r.get('status') in ('running','unknown') or any(o.get('outcome')=='게시 확인 중' for o in r.get('outcomes',[]))) for r in receipts)
        if unsafe:
            hold(row['id'],'전환 지시는 보존했습니다. 제출 여부가 불명확하여 기존 결과 확인 전에는 실행권을 넘기지 않습니다.')
            return False
        with locked(ROWS):
            row=get(row['id'])
            row['events'].setdefault('suspension',event(row,'suspension','jarvis',
                '대표님 지시로 현재 안건을 미해결 상태로 유예합니다: '+row['title']+'\n지시: '+request['command']))
            _save(row)
        if not flush_events(row['id']):return False
        with locked(ROWS):
            state=load(STATE);row=get(row['id'])
            if state.get('activeId')!=row['id']:return False
            row.update(status='suspended',suspendedAt=time.time(),version=row['version']+1,owner=uuid.uuid4().hex)
            row.pop('switchRequest',None);_save(row)
            state['activeId']=None
            state.setdefault('suspended',[]).append(row['id'])
            next_row=get(request['nextId']);next_row['priority']=-1;_save(next_row)
            write(STATE,state)
        return True


def resume(identity):
    with locked(ROWS):
        state=load(STATE);row=get(identity)
        if row.get('status')!='suspended':raise ValueError('유예 상태의 안건만 재개할 수 있습니다.')
        row.update(status='queued',priority=-1,controllerFailures=0,nextCheckAt=0,manualNudges=row.get('manualNudges',0)+1)
        # The original target, proof and attempt budget survive the explicit resume.
        row['events'].pop('suspension',None)
        _save(row)
        state['suspended'].remove(identity);state['pending'].append(identity);write(STATE,state)
    if row.get('controllerGoalId'):
        from agents.crew_reasoning import claim,goal_path,save
        with claim(row['controllerGoalId']) as acquired:
            if acquired:
                goal=load(goal_path(row['controllerGoalId']))
                if goal.get('status') in ('blocked','answered'):
                    goal.update(status='ready',nextCheckAt=0,delivered=False,modelFailures=0,finishRejections=0,
                                maxSteps=goal.get('decisions',0)+12)
                    goal.pop('answer',None);save(goal)


def close_and_advance(identity, status='closed', reason=None):
    with locked(ROWS):
        state = load(STATE)
        row = get(identity)
        row.update(status=status, closedAt=time.time())
        if reason:
            row['closeReason'] = str(reason)[:300]
        row['performance'] = performance(row)
        _save(row)
        cur_ids = [i for i in active_ids(state) if i != identity]
        state['activeIds'] = cur_ids
        state['activeId'] = cur_ids[0] if cur_ids else None
        state['recent'] = ([identity] + [i for i in state.get('recent', []) if i != identity])[:30]
        if identity in state.get('pending', []):
            state['pending'] = [i for i in state.get('pending', []) if i != identity]
        write(STATE, state)


def recovery_watch(row):
    """A spent reasoning turn waits on new evidence; it never abandons the agenda."""
    if row.get('status') not in ('blocked','recovering') or running(row):return False
    if waiting_investigation(row) and any(p['id']!=row['id'] and p.get('project')==row.get('project')
            and not waiting_investigation(p) for p in active_rows()):return False
    watch=row.get('recoveryWatch',{})
    from common import repair_workflow
    internal=[]
    for file in repair_workflow.ROOT.glob('*.json'):
        repair=load(file)
        if repair.get('businessAgendaId')==row['id'] and repair.get('status')=='ready':
            internal.append({k:repair.get(k) for k in ('taskId','planSha256','step','steps')})
    if internal:
        ready=internal[0]
        with locked(ROWS):
            saved=get(row['id']);saved['recoveryWatch']={**watch,'state':'internal_action_ready',
                'nextCheckAt':time.time()+5,'taskId':ready['taskId'],'step':ready['step']};_save(saved)
        # Internal phases already have host-owned queue tokens. Do not spend model decisions watching them.
        with context(token(get(row['id']))):return repair_workflow.dispatch_project_recovery_once()
    if watch.get('nextCheckAt',0)>time.time() and not internal:return False
    from agents import crew_reasoning as crew
    identity=row.get('controllerGoalId') or row.get('recoveryGoalId')
    if not identity or load(crew.goal_path(identity)).get('status') not in ('blocked','answered'):return False
    from server.project_health import SOURCES,ROOT as project_root
    from common.recovery_evidence import environment_evidence
    def stable(value):
        clocks={'checkedAt','observedAt','collectedAt','generatedAt','updatedAt','modifiedAt','lastPoll','ts'}
        if isinstance(value,dict):return {k:stable(v) for k,v in value.items() if k not in clocks}
        if isinstance(value,list):return [stable(v) for v in value]
        return value
    args=(row.get('workTarget') or row.get('source',{})).get('arguments',{})
    source=next((project_root/s[2] for s in SOURCES if s[0]==row['project']),None)
    files=['dashboard/agents/crew_reasoning.py','dashboard/agents/agent_tools.py',
           *['dashboard/common/'+name+'.py' for name in ('repair_workflow','recovery_evidence','ubuntu_naver_browser',
              'ego_screen','kin_screen','kin_submit_repair','channel_parameters','conference_dispatch','project_autonomy','visible_naver_editor','staff_capabilities')]]
    document=load(source) if source else {}
    if args.get('account') and row['project'] in ('cf_blog','naver_blog'):
        key='items' if row['project']=='cf_blog' else 'accounts'
        document={'date':document.get('publicationDate') or document.get('date'),
                  key:[v for v in document.get(key,[]) if v.get('domain',v.get('account'))==args['account']]}
    evidence={'internalRecovery':internal,'source':stable(document),
              'code':{name:hashlib.sha256((project_root/name).read_bytes()).hexdigest() for name in files if (project_root/name).is_file()},
              'environment':environment_evidence(project_root,row['project'],{'identity':args.get('account')})}
    fingerprint=hashlib.sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    changed=fingerprint not in watch.get('seen',[])
    if changed and watch.get('continuationEpisodes',0)>=2:
        watch.update(state='needs_ceo_action',nextCheckAt=time.time()+300)
        with locked(ROWS):
            saved=get(row['id']);saved['recoveryWatch']=watch;_save(saved)
        return False
    watch.update(state='internal_action_ready' if internal else 'evidence_changed' if changed else 'waiting_for_change',checks=watch.get('checks',0)+1,nextCheckAt=time.time()+300)
    if changed:
        watch.update(continuationEpisodes=watch.get('continuationEpisodes',0)+1,lastChangeAt=time.time(),seen=[*watch.get('seen',[]),fingerprint][-64:])
    with locked(ROWS):
        saved=get(row['id'])
        if saved['status'] not in ('blocked','recovering'):return False
        saved['recoveryWatch']=watch
        if changed:saved.update(controllerFailures=0,nextCheckAt=0)
        if not changed:saved['lastAction']='같은 안건의 복구 조건을 자동 확인 중입니다. 새 증거가 생기면 진단을 재개합니다.'
        _save(saved)
    if not changed:return False
    with crew.claim(identity) as acquired:
        if not acquired:
            # A running decision keeps its budget; recheck this evidence after it returns.
            with locked(ROWS):
                saved=get(row['id']);saved['recoveryWatch']['seen'].remove(fingerprint)
                saved['recoveryWatch']['nextCheckAt']=time.time()+5;_save(saved)
            return False
        goal=load(crew.goal_path(identity))
        if goal.get('status') not in ('blocked','answered'):return False
        goal.setdefault('investigationEpisodes',[]).append({'reason':'automatic evidence change','at':time.time(),
            'fingerprint':fingerprint,'previousMaxSteps':goal.get('maxSteps'),'previousAnswer':goal.get('answer')})
        goal['maxSteps']=goal.get('decisions',0)+8
        goal.update(status='ready',actor=goal.get('leadActor','jarvis'),delivered=False,nextCheckAt=time.time()+1)
        goal.pop('answer',None);goal.pop('resolution',None)
        crew.observe(goal,'host','automatic_recovery_recheck',{}, {'reason':'New runtime, source or tool evidence is available. Reassess the SAME agenda; do not replay an uncertain submission or bypass a held code review.',
            'fingerprint':fingerprint,'environment':evidence['environment']})
        progress(row['id'],'recovering','새 증거·도구 변경을 자동 감지해 같은 안건의 진단을 재개합니다.')
    return True


def reconcile_monitor_goal(row):
    """Close a missing-publication incident from fresh receipts, without model budget."""
    if row.get('kind') != 'goal' or row.get('status') not in ('meeting', 'executing', 'blocked', 'recovering') or running(row):
        return False
    from agents import crew_reasoning as crew
    identity = row.get('controllerGoalId') or row.get('source', {}).get('goalId')
    if not identity:
        return False
    with crew.claim(identity) as acquired:
        if not acquired:
            return False
        goal = load(crew.goal_path(identity))
        if goal.get('origin') != 'project-monitor' or goal.get('permissions', {}).get('projects') != [row.get('project')] or row.get('workTarget'):
            return False
        baseline = next((p for p in goal.get('baselineMetrics', []) if p.get('id') == row['project']), {})
        before = baseline.get('quota') or {}
        if before.get('status') != 'observed' or not before.get('missingSlots') or any(baseline.get('counts', {}).get(k) for k in ('failed', 'error', 'unknown', 'review_required')):
            return False
        from server.project_health import observed_projects
        current = next((p for p in observed_projects() if p['id'] == row['project']), {})
        quota = current.get('quota') or {}
        source = current.get('source') or {}
        if (not source.get('fresh') or quota.get('status') != 'observed' or quota.get('date') != before.get('date')
                or quota.get('due', 0) < before.get('due', 0) or 'missingSlots' not in quota
                or set(before['missingSlots']) & set(quota['missingSlots'])):
            return False
        proof_path = DATA / ('naver/public-verification.json' if row['project'] == 'naver_blog' else 'cf/daily_schedule.json')
        if not proof_path.is_file() or row['project'] not in ('naver_blog', 'cf_blog'):
            return False
        evidence = {'verified': True, 'monitorReconciled': True, 'source': str(proof_path),
                    'sha256': hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                    'scope': str(before['date']) + ' 공개 게시 확인: ' + ', '.join(before['missingSlots']),
                    'bodyVerification': '별도 검증 대상', 'quota': quota}
        if not row.get('events', {}).get('opening'):
            record_plan(row['id'], [evidence['scope']], {'provider': 'host', 'model': 'publication-reconciler'})
        verified(row['id'], evidence)
        goal.update(status='answered', delivered=True, answer=evidence['scope'],
                    resolution={'status': 'verified_resolved', 'label': evidence['scope'], 'source': str(proof_path)})
        crew.save(goal)
    return True


def _should_auto_advance(row):
    if row.get('status') not in ('blocked', 'suspended', 'recovering') or row.get('status') == 'report_pending':
        return False
    if running(row):
        return False
    if row.get('kind') == 'goal':
        return False
    if row.get('kind') == 'conference' and row.get('project') == 'threads':
        args = (row.get('workTarget') or row.get('source') or {}).get('arguments', {})
        part_id = args.get('partId')
        import sqlite3
        from contextlib import closing
        try:
            database=DATA/'threads.sqlite3'
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                if part_id:
                    main_id=part_id.rsplit('-',1)[0]+'-0'
                    main=db.execute("SELECT state FROM parts WHERE part_id=? AND kind='main'",(main_id,)).fetchone()
                else:
                    main=db.execute("SELECT state FROM parts WHERE account_key=? AND publication_date=? AND slot=? AND kind='main'",
                                    (args.get('account'),args.get('date'),args.get('slot'))).fetchone()
                if main and main[0]=='published_verified':return True
        except (OSError,sqlite3.Error):
            pass
        return False
    if row.get('kind') == 'conference' and row.get('project') == 'naver_kin':
        conf_id = (row.get('source') or {}).get('conferenceId')
        if conf_id:
            try:
                conf = load(ROWS.parent / (conf_id + '.json'))
                if conf.get('status') == 'completed':
                    runs = (conf.get('eligibility') or {}).get('runs', [])
                    if any(r.get('state') == 'skipped' or r.get('reason') in ('model_skipped_no_good_match', 'no_eligible_candidate') for r in runs):
                        return True
                    if (conf.get('eligibility') or {}).get('cadenceState') == 'waiting':
                        return True
            except Exception:
                pass
    if row.get('blocker') in ('no_new_supported_candidate', 'no_due_slot', 'no_due_draft', 'followup_delay_waiting', 'no_work', 'model_skipped_no_good_match', 'no_eligible_candidate'):
        return True
    return False


def _top_up_channel_lanes():
    """Feed channel lanes according to Jarvis's Reverse-Funnel strategy (focusChannels) rather than blind quota stuffing."""
    try:
        from common.conference_dispatch import request as conf_request
        autonomy_cfg = load(DATA / 'project-autonomy.json')
        if autonomy_cfg.get('enabled') is True and not (Path.home() / 'EGO_EXEC_DISABLED').exists():
            cur_st = load(STATE)
            all_ids = list(active_ids(cur_st)) + list(cur_st.get('pending', []))
            lane_counts = {}
            for pid in all_ids:
                r = get(pid)
                if r and r.get('kind') == 'conference':
                    proj = r.get('project') or 'other'
                    lane_counts[proj] = lane_counts.get(proj, 0) + 1
            enabled_projs = set(autonomy_cfg.get('projects', []))
            focus_projs = set(cur_st.get('focusChannels') or [])
            active_projs = (enabled_projs & focus_projs) if focus_projs else enabled_projs
            if 'threads' in active_projs and lane_counts.get('threads', 0) == 0:
                conf_request('threads', {}, one=True)
            if 'naver_kin' in active_projs and lane_counts.get('naver_kin', 0) == 0:
                conf_request('kin', {}, one=True)
            if 'naver_blog' in active_projs and lane_counts.get('naver_blog', 0) == 0:
                conf_request('parameters', {'action': 'naver-cycle'}, one=True)
            if 'cf_blog' in active_projs and lane_counts.get('cf_blog', 0) < 2:
                cf_res = conf_request('parameters', {'action': 'cf-cycle'}, one=False)
                if cf_res.get('status') == 'no_work':
                    conf_request('parameters', {'action': 'prepare'}, one=False)
    except Exception:
        pass


def company_executive_check_once(force=False):
    """Reverse-Funnel Strategy Brain (@jarvis): calculates gap to $100/day, pivots channel lanes, and proactively calls ask_ceo."""
    now = time.time()
    state = load(STATE)
    if not force and now - state.get('lastExecutiveCheckAt', 0) < 300 and state.get('pending'):
        return False
    _top_up_channel_lanes()
    state = load(STATE)
    pending_ids = list(state.get('pending', []))
    try:
        from agents.crew_reasoning import overview
        from common.llm_client import generate_json
        from common.crew_chat_bridge import emit_work_event, emit_ceo_proposal
        company = overview()
        projects_summary = [
            {
                'id': p.get('id'),
                'title': p.get('title'),
                'status': p.get('status'),
                'quota': p.get('quota'),
                'counts': p.get('counts'),
                'blocker': p.get('blocker'),
                'recoverableCount': len(p.get('recoverableWork') or []),
            }
            for p in company.get('projects', [])
        ]
        healthy_ids = {p['id'] for p in projects_summary if p.get('status') == 'healthy'}
        valid_pending = []
        pruned = []
        for pid in pending_ids:
            prow = get(pid)
            if not prow or prow.get('status') != 'queued':
                continue
            if (str(prow.get('title', '')).startswith('자동 운영 점검:') or str(prow.get('title', '')).endswith('자동 운영 점검')) and prow.get('project') in healthy_ids:
                prow.update(status='closed', closedAt=now, closeReason='auto_pruned_project_healthy')
                _save(prow)
                pruned.append(pid)
                continue
            valid_pending.append(prow)
        if pruned:
            with locked(ROWS):
                st = load(STATE)
                st['pending'] = [i for i in st.get('pending', []) if i not in pruned]
                st['recent'] = (pruned + [i for i in st.get('recent', []) if i not in pruned])[:30]
                write(STATE, st)
        business = company.get('businessEvidence', {})
        reverse_funnel = compute_reverse_funnel_gap(business)
        fp_src = json.dumps({
            'projects': [(p['id'], p['status'], p['recoverableCount']) for p in projects_summary],
            'pending': [r['id'] for r in valid_pending],
            'performanceCheckedAt': business.get('performanceCheckedAt'),
            'funnelStatus': reverse_funnel.get('status'),
        }, sort_keys=True)
        fp = hashlib.sha256(fp_src.encode('utf-8')).hexdigest()
        if not force and now - state.get('lastExecutiveCheckAt', 0) < 900 and state.get('lastExecutiveFingerprint') == fp:
            return False
        candidates = [{'id': r['id'], 'title': r.get('title', '')[:120], 'project': r.get('project'), 'kind': r.get('kind'), 'priority': r.get('priority', 10)} for r in valid_pending[:10]]
        schema = {
            'type': 'object',
            'properties': {
                'briefing': {'type': 'string', 'minLength': 1, 'maxLength': 600},
                'topAgendaId': {'type': 'string'},
                'dropAgendaIds': {'type': 'array', 'items': {'type': 'string'}},
                'focusChannels': {
                    'type': 'array',
                    'items': {'type': 'string', 'enum': ['cf_blog', 'threads', 'naver_kin', 'naver_blog', 'legacy_remodel']},
                    'minItems': 1,
                },
                'experiment': {'type': 'object', 'properties': {
                    'hypothesis': {'type': 'string'}, 'targetUrl': {'type': 'string'},
                    'measurementDate': {'type': 'string'}, 'evidenceConfidence': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                    'maxModelCalls': {'type': 'integer', 'minimum': 1, 'maximum': 40},
                    'successMetric': {'type': 'string'}, 'stopCondition': {'type': 'string'}},
                    'required': ['hypothesis', 'targetUrl', 'measurementDate', 'evidenceConfidence', 'maxModelCalls', 'successMetric', 'stopCondition'], 'additionalProperties': False},
                'ceoProposal': {
                    'type': 'object',
                    'properties': {
                        'shouldAskCeo': {'type': 'boolean'},
                        'title': {'type': 'string'},
                        'currentReality': {'type': 'string'},
                        'proposal': {'type': 'string'},
                        'requiredApprovals': {'type': 'array', 'items': {'type': 'string'}},
                        'expectedImpact': {'type': 'string'},
                    },
                    'required': ['shouldAskCeo', 'title', 'currentReality', 'proposal', 'requiredApprovals', 'expectedImpact'],
                    'additionalProperties': False,
                },
            },
            'required': ['briefing', 'topAgendaId', 'dropAgendaIds', 'focusChannels', 'experiment', 'ceoProposal'],
            'additionalProperties': False,
        }
        prompt = (
            '당신은 하루 $100 수익을 책임지는 자율 에이전트 조직의 총괄 디렉터(@jarvis)다. "블로그 글 몇 개 찍어냈는가"만 보는 컨베이어 벨트 사고방식이나 "미검증입니다/아직 실행 전입니다" 같은 방어적 면피 말투를 버리고, 진짜 사업가이자 팀장으로서 [역산형 전략 두뇌(Reverse-Funnel Brain)]로 결단하라.\n'
            '⚠️ [언어 절대 규칙] 모든 응답 텍스트 필드(briefing, experiment.hypothesis, experiment.successMetric, experiment.stopCondition, ceoProposal.title, ceoProposal.currentReality, ceoProposal.proposal, ceoProposal.requiredApprovals, ceoProposal.expectedImpact)는 반드시 100% 자연스러운 한국어(Korean)로만 작성하라. 중국어(Chinese/한자)나 영어 문장 사용은 절대 금지한다.\n'
            + __import__('common.asset_map', fromlist=['get_asset_map_summary']).get_asset_map_summary() + '\n'
            '[역산(Reverse-Funnel) 수치 진단]\n'
            + json.dumps(reverse_funnel, ensure_ascii=False) + '\n'
            '1) briefing: 현재 일수익($)·일유입(PV)과 목표 $100(약 2,500 PV / 200 클릭) 사이의 격차를 역산하고, 왜 단순 블로그 검색 대기로는 안 되는지 짚은 뒤 오늘 집중할 고단가 타깃 + 외부유입(Threads·지식iN·블로그 브릿지) 작전을 결단력 있는 한국어 팀장 말투(2~4문장)로 브리핑하라.\n'
            '2) focusChannels: 오늘 우선 가동할 핵심 유입·수익 채널 배열(cf_blog, threads, naver_kin, naver_blog, legacy_remodel 중 선택)을 지정하라.\n'
            '3) topAgendaId & dropAgendaIds: 대기 안건(pendingAgendas) 중 실질 유입(PV)과 수익($) 기여도가 가장 높은 최우선 안건 1개를 topAgendaId로 고르고(없으면 빈 문자열 ""), 유입 효과가 없는 중복/형식적 티켓은 dropAgendaIds에 넣어 과감히 폐기하라.\n'
            '4) experiment: 이번 집중 작전의 가설(hypothesis), 타깃 URL(없으면 ""), 측정일(YYYY-MM-DD), 성공 지표(예: "외부유입 +500 PV 및 애드센스 고단가 클릭 20회 달성"), 중단 조건을 한국어로 설정하라.\n'
            '5) ceoProposal (대표님께 역제안 · ask_ceo): 현재 수익/유입이 목표 대비 턱없이 부족하거나(status=="critical_gap"), 브라우저 로그인 세션 갱신·추가 계정 지원·외부 링크 공격적 살포 승인이 필요하면 반드시 shouldAskCeo=true로 설정하고, 대표님께 당당하게 역제안할 제목(title), 냉정한 현실 진단(currentReality), 구체적 돌파 작전(proposal), 대표님이 해주셔야 할 승인/지원 항목 2~3가지(requiredApprovals), 기대 효과(expectedImpact)를 100% 한국어로 생생하게 작성하라.\n'
            + json.dumps({'reverseFunnel': reverse_funnel, 'projects': projects_summary, 'pendingAgendas': candidates, 'businessEvidence': business}, ensure_ascii=False)
        )
        decision = generate_json(prompt, agent_slot='jarvis', response_schema=schema, timeout_seconds=120, memory_read_only=True, _skip_memory=True, crew_actor='jarvis', crew_actor_label='팀장', crew_stage='company-executive-check')
        experiment = validate_business_experiment(decision.get('experiment'))
        drop_set = set(decision.get('dropAgendaIds') or []) - {decision.get('topAgendaId')}
        top_id = decision.get('topAgendaId')
        focus_channels = decision.get('focusChannels') or ['cf_blog', 'threads', 'naver_kin', 'naver_blog']
        with locked(ROWS):
            st = load(STATE)
            st.setdefault('schema', 'barolab-work-agenda-v1')
            st['enabled'] = True
            for drop_id in drop_set:
                if drop_id in st.get('pending', []):
                    drow = get(drop_id)
                    if drow:
                        drow.update(status='closed', closedAt=now, closeReason='jarvis_executive_pruned')
                        _save(drow)
                    st['pending'] = [i for i in st.get('pending', []) if i != drop_id]
            if top_id and top_id in st.get('pending', []):
                trow = get(top_id)
                if trow:
                    trow['priority'] = -10
                    trow['businessExperiment'] = experiment
                    _save(trow)
                st['pending'] = [top_id] + [i for i in st.get('pending', []) if i != top_id]
            st['lastExecutiveCheckAt'] = now
            st['lastExecutiveFingerprint'] = fp
            st['lastExecutiveBriefing'] = decision.get('briefing', '')
            st['reverseFunnel'] = reverse_funnel
            st['focusChannels'] = focus_channels
            write(STATE, st)
        emit_work_event(actor='jarvis', actor_label='팀장', task_id='executive-check:'+str(int(now)), phase='completed', stage='company-executive-check', output_kind='[역산 전략 총괄 점검] ' + decision.get('briefing', ''))
        ceo_prop = decision.get('ceoProposal') or {}
        if (ceo_prop.get('shouldAskCeo') or reverse_funnel.get('status') == 'critical_gap') and (ceo_prop.get('title') or ceo_prop.get('proposal')):
            emit_ceo_proposal(
                actor='jarvis',
                title=ceo_prop.get('title') or '단순 발행 대기 중단 및 하루 $100 역산 외부유입 집중 작전 승인 요청',
                current_reality=ceo_prop.get('currentReality') or reverse_funnel['diagnosis'],
                proposal=ceo_prop.get('proposal') or decision.get('briefing', ''),
                required_approvals=ceo_prop.get('requiredApprovals') or ['고단가 타깃 집중 유입 작전 및 외부채널 브릿지 배포 승인'],
                expected_impact=ceo_prop.get('expectedImpact') or '일일 외부유입 +500 PV 확보 및 애드센스 고단가 클릭 전환 검증',
                urgency='high',
            )
        return True
    except Exception:
        return False


def _step_single_agenda(row):
    if not row:
        return False
    if row.get('switchRequest'):
        return switch_once(row)
    if row.get('controllerFailures',0)>=3 and row['status'] in ('blocked','recovering'):
        with context(token(row)):
            return recovery_watch(row)
    if row.get('nextCheckAt',0)>time.time() or (row.get('controllerFailures',0)>=3 and row['status']!='report_pending'):
        return False
    try:
        with context(token(row)):
            if row['status']=='report_pending':
                return finish_reports(row['id'])
            if waiting_investigation(row):
                identity=row.get('controllerGoalId') or row.get('source',{}).get('goalId')
                goal=load(DATA/'chats/reasoning-goals'/(identity+'.json'))
                finish_investigation(row['id'],goal.get('answer') or row.get('blocker') or '조사 결과는 저장했으며 실제 해결은 미확인입니다.',
                                     'investigation_finished_unresolved')
                return True
            if row['status']=='meeting' and row['kind']!='goal' and not row.get('events',{}).get('opening',{}).get('receivedAt'):
                return prepare_open(row['id'])
            flush_events(row['id'])
            if row['status'] in ('blocked','recovering') and recovery_watch(row):
                return True
            if row['kind']=='conference' and row['status'] in ('meeting','executing') and not running(row):
                from common.conference_dispatch import QUEUE, record_conference_result, process_once as dispatch_conference_once
                receipt=load(QUEUE/(row['source']['conferenceId']+'.json'))
                if receipt.get('status') == 'queued':
                    return dispatch_conference_once()
                if receipt.get('status') in ('completed','failed','unknown'):
                    record_conference_result(receipt,receipt.get('preparation'))
                    return True
            if row['kind'] in ('style','radar','audit') and row['status']=='meeting':
                if row.get('auxiliaryStartedAt'):
                    hold(row['id'],'실행이 중단되었습니다. 저장된 결과를 먼저 확인하며 같은 작업을 자동 재실행하지 않습니다.')
                    return False
                with locked(ROWS):
                    row=get(row['id']);row['auxiliaryStartedAt']=time.time();_save(row)
                with execution(row['project']):
                    if row['kind']=='style':
                        from dashboard.agents.style_strategy import review_once
                        result=review_once()
                        good=result.get('status') in ('completed','already_reviewed')
                    elif row['kind']=='audit':
                        from server.content_auditor import run_patrol_batch
                        result=run_patrol_batch(1,row['source']['domain'],False)
                        records=result.get('results',[])
                        good=len(records)==1 and records[0].get('postId')==row['source']['post']['id'] and bool(records[0].get('checklist'))
                    else:
                        from server.radar_scout import SCOUT
                        result=SCOUT.trigger(slot=row['source'].get('slot'),background=False)
                        good=bool(result.get('sources')) and result.get('sourceStatus')=='collected'
                with locked(ROWS):
                    row=get(row['id']);row['auxiliaryResult']=result;_save(row)
                if good:
                    verified(row['id'],{'verified':True,'source':str(path(row['id'])),'scope':row['completionCriteria'],
                             'resultStatus':result.get('status'),'result':result,'publicationVerified':False})
                else:
                    hold(row['id'],'실제 조사·전략 결과를 확인하지 못했습니다. 기존 결과와 안건을 보존했습니다.')
                return True
            if row['kind']=='conference' and row['status']=='recovering' and not row.get('recoveryPreparation'):
                from common.repair_workflow import prepare_conference_recovery
                try:prepared=prepare_conference_recovery()
                except (OSError,ValueError,KeyError) as exc:
                    prepared={'status':'needs_evidence','errorType':type(exc).__name__}
                with locked(ROWS):
                    saved=get(row['id']);saved['recoveryPreparation']=prepared;_save(saved)
            if row['kind'] in ('conference','staff') and row['status']=='recovering' and not row.get('recoveryGoalId'):
                from agents.crew_reasoning import reason_request
                goal = reason_request('agenda-recovery:'+row['id'],
                    '현재 안건 '+row['title']+'의 실패를 같은 안건에서 조사·복구·검증하라. '
                    '다른 계정·슬롯·프로젝트를 실행하지 마라. 원인 수정 후 retry_conference 도구로 '
                    '이 안건의 기존 실행만 재개할 수 있다. 제출 불명확은 원천 결과부터 조회하며 재제출하지 마라. '
                    '안건 ID: '+row['id']+' 원인: '+row.get('blocker','')+
                    ' 원래 실행 ID: '+str((row.get('workTarget') or row.get('source',{})).get('conferenceId',''))+
                    ' 자동 수집한 실패 로그와 실제 복구 단계 결과를 먼저 확인하라. 코드 결함은 Patch 수정안→Jarvis 검토→Doctor 테스트→적용→Publi 재개→실제 결과 검증으로 처리하라.',
                    execute=True, repair=True, steps=0, origin='agenda', projects=[row['project']],
                    agenda_id=row['id'])
                with locked(ROWS):
                    saved=get(row['id']);saved['recoveryGoalId']=goal['id'];_save(saved)
                return True
    except Exception as exc:
        from common.llm_usage import UsageBudgetExceeded
        if isinstance(exc, UsageBudgetExceeded) and str(exc).startswith('agenda_'):
            finish_investigation(row['id'], '조사 예산 한도로 안건을 종결합니다. 마지막 확인: ' +
                                 str(get(row['id']).get('lastAction') or '추가 확인 필요')[:500] +
                                 ' · 미검증 실행·복구 결과는 원천 기록에 남겨 후속 확인합니다.', str(exc))
            return True
        with locked(ROWS):
            saved=get(row['id'])
            failures=saved.get('controllerFailures',0)+1
            saved.update(controllerFailures=failures,controllerError=type(exc).__name__,nextCheckAt=time.time()+min(300,30*failures))
            if failures>=3 and saved['status']!='report_pending':
                saved.update(status='blocked',blocker='안건 판단·보고가 반복 실패했습니다. 같은 안건과 실행 결과를 보존했습니다.')
            _save(saved)
        return False
    return False

def process_once():
    """Reverse-Funnel Multi-lane dispatcher: Jarvis evaluates the $100/day gap first, then advances prioritized channel lanes."""
    if not enabled():
        return False
    with (ROWS / 'controller.lock').open('a+b') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        for r in list(active_rows()):
            if reconcile_monitor_goal(r):
                continue
            if _should_auto_advance(r):
                close_and_advance(r['id'], status='closed', reason=r.get('blocker') or r.get('controllerError') or 'auto_advance')
        company_executive_check_once()
        _top_up_channel_lanes()
        for identity in list(load(STATE).get('pending', [])):
            admit(identity)
        rows = active_rows()
        if not rows:
            return False
        progressed = False
        for r in rows:
            if _step_single_agenda(r):
                progressed = True
        return progressed
