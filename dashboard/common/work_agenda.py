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
import math
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit

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


def validate_business_experiment(value, *, strict=False):
    from datetime import date
    from urllib.parse import urlsplit
    if not isinstance(value, dict):
        raise ValueError('Business experiment required')
    for key in ('hypothesis', 'measurementDate', 'successMetric', 'stopCondition'):
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 1000:
            raise ValueError('Missing bounded experiment field: ' + key)
    date.fromisoformat(value['measurementDate'])
    if value.get('evidenceConfidence') not in ('low', 'medium', 'high') or type(value.get('maxModelCalls')) is not int or not 1 <= value['maxModelCalls'] <= 500:
        raise ValueError('Invalid experiment confidence or resource bound')
    target = value.get('targetUrl')
    if not isinstance(target, str):
        raise ValueError('Experiment target must be a URL or empty')
    parsed = urlsplit(target)
    if (strict or target) and (not target or parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password):
        raise ValueError('Invalid experiment target URL')
    if strict and value.get('primaryMetric') not in ('pageViews', 'sessions', 'estimatedRevenue'):
        raise ValueError('Invalid experiment primary metric')
    if strict and value.get('measurementWindowDays') not in (7, 14, 28):
        raise ValueError('Experiment requires a 7, 14 or 28 day observation window')
    if strict and (type(value.get('minimumSample')) is not int or not 1 <= value['minimumSample'] <= 100000):
        raise ValueError('Experiment requires a positive minimum sample')
    return value


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.timestamp() if stamp.tzinfo else None
    except (ValueError, TypeError):
        return None


def _url_key(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            return None
        # UTM/query identity is retained: observations from different campaigns cannot mix.
        return ((parsed.hostname or '').lower().removeprefix('www.'), parsed.path.rstrip('/') or '/', parsed.query)
    except (ValueError, TypeError):
        return None


def _observations(business, target, metric):
    key = _url_key(target)
    return [r for r in business.get('pageObservations', []) if key and _url_key(r.get('url')) == key
            and _number(r.get(metric)) is not None and r.get('complete') is True
            and r.get('source') and r.get('timezone') and r.get('start') and r.get('end')]


def bind_business_experiment(value, business, channels, now=None):
    """Bind model hypotheses to host-observed baseline data, never model-invented metrics."""
    now = time.time() if now is None else now
    proposal = validate_business_experiment(dict(value), strict=True)
    metric = proposal['primaryMetric']
    candidates = []
    for row in _observations(business, proposal['targetUrl'], metric):
        checked = _stamp(row.get('checkedAt'))
        try:
            duration = (datetime.fromisoformat(row['end']) - datetime.fromisoformat(row['start'])).days + 1
        except (ValueError, TypeError):
            continue
        if checked is not None and 0 <= now - checked <= 26 * 3600 and duration == proposal['measurementWindowDays']:
            candidates.append(row)
    if not candidates:
        raise ValueError('Experiment requires a fresh observed target baseline for the chosen window')
    baseline = max(candidates, key=lambda r: r['checkedAt'])
    domain = _url_key(proposal['targetUrl'])[0]
    allowed_channels = sorted(set(channels) & {'cf_blog', 'naver_blog', 'naver_kin', 'threads', 'brunch', 'legacy_remodel'})
    if not allowed_channels:
        raise ValueError('Experiment requires an explicit channel allocation')
    identity = hashlib.sha256(json.dumps([proposal['targetUrl'], proposal['hypothesis'], metric,
        proposal['measurementWindowDays'], baseline['start'], baseline['end'], baseline.get('source'),
        baseline.get('currency'), baseline.get('timezone')], ensure_ascii=False).encode()).hexdigest()
    return {**proposal, 'id': identity, 'baseline': baseline, 'focusDomains': [domain],
            'focusChannels': allowed_channels, 'startedAt': now, 'observationStart': None,
            'observationEnd': None, 'observationState': 'waiting_intervention', 'nextMeasureDate': None,
            'status': 'active', 'causalClaim': False, 'resourceScope': 'experiment_lifetime', 'finalObservation': None,
            'maxNewPublications': 2, 'newPublicationAgendaIds': [],
            'secondaryMetrics': ['sessions'], 'revenueAttributionStatus': 'unknown',
            'interpretation': '관측된 대상의 가설 실험; 수익·순위 개선 보장 없음'}


def autonomous_experiment_allows(project, target_url='', domain='', state=None, reserved_agenda_id=None):
    """Read-only admission gate for NEW autonomous work; existing submissions keep ownership."""
    state = load(STATE) if state is None else state
    experiment = state.get('activeExperiment') or {}
    if experiment.get('status') != 'active' or not experiment.get('id') or not experiment.get('baseline'):
        return False
    if len(experiment.get('focusDomains') or []) not in (1, 2):
        return False
    if project not in experiment.get('focusChannels', []):
        return False
    if project in ('cf_blog', 'naver_blog', 'naver_kin', 'threads', 'brunch'):
        reservations = experiment.get('newPublicationAgendaIds') or []
        if reserved_agenda_id not in reservations and len(reservations) >= experiment.get('maxNewPublications', 2):
            return False
    if experiment.get('observationEnd') and datetime.now(timezone.utc).date().isoformat() > experiment['observationEnd']:
        return False
    if not experiment.get('interventionReceipt'):
        checked = _stamp(experiment['baseline'].get('checkedAt'))
        if checked is None or not 0 <= time.time() - checked <= 26 * 3600:
            return False
    ledger = load(DATA / 'llm_usage_ledger.json')
    used = (ledger.get('byExperiment') or {}).get(experiment['id'], {}).get('modelCalls', 0)
    used += sum(r.get('experimentId') == experiment['id'] for r in (ledger.get('active') or {}).values())
    if type(experiment.get('maxModelCalls')) is not int or used >= experiment['maxModelCalls']:
        return False
    requested = _url_key(target_url)
    if target_url and requested != _url_key(experiment.get('targetUrl')):
        return False
    host = requested[0] if requested else str(domain or '').lower().removeprefix('www.')
    return bool(host and host in experiment['focusDomains'])


def new_authoring_allowed(project, *, domain='', target_url=''):
    """A direct timer must obtain a durable agenda before spending an experiment budget."""
    if not current():
        return True
    try:
        row = require(project=project)
    except (AgendaWaiting, ValueError, KeyError):
        return False
    source = row.get('source') or {}
    if not source.get('autonomousExperiment'):
        return True  # Existing explicitly owned work retains its authorization.
    return (source.get('experimentId') == (load(STATE).get('activeExperiment') or {}).get('id')
            and autonomous_experiment_allows(project,
                target_url=target_url or source.get('targetUrl', ''), domain=domain or source.get('domain', ''), reserved_agenda_id=row['id']))


def evaluate_business_experiment(experiment, business, now=None):
    """Compare complete, equally long target windows. This is descriptive, not causal."""
    now = time.time() if now is None else now
    base = experiment.get('baseline') or {}
    metric = experiment.get('primaryMetric')
    result = {'status': 'inconclusive', 'causalClaim': False, 'reason': 'target_measurement_missing', 'metric': metric}
    if not experiment.get('interventionReceipt'):
        return {**result, 'reason': 'waiting_intervention'}
    if metric not in ('pageViews', 'sessions', 'estimatedRevenue') or not base:
        return result
    observations = _observations(business, experiment.get('targetUrl'), metric)
    archived = experiment.get('finalObservation') or {}
    if archived.get('row') and _url_key(archived['row'].get('url')) == _url_key(experiment.get('targetUrl')):
        observations = observations + [archived['row']]
    for post in observations:
        checked = _stamp(post.get('checkedAt'))
        anchor = archived.get('capturedAt') if post is archived.get('row') else now
        if (checked is None or type(anchor) not in (int, float) or not experiment.get('startedAt', 0) <= anchor <= now
                or not 0 <= anchor - checked <= 26 * 3600 or post.get('complete') is not True):
            result['reason'] = 'target_measurement_stale'; continue
        if any(base.get(k) != post.get(k) for k in ('source', 'timezone', 'currency', 'scope', 'trafficSource')):
            result['reason'] = 'incompatible_measurement_scope'; continue
        try:
            days = (datetime.fromisoformat(post['end']) - datetime.fromisoformat(post['start'])).days + 1
            baseline_days = (datetime.fromisoformat(base['end']) - datetime.fromisoformat(base['start'])).days + 1
        except (ValueError, TypeError, KeyError):
            continue
        if (post.get('start') != experiment.get('observationStart')
                or post.get('end') != experiment.get('observationEnd')
                or days != experiment.get('measurementWindowDays') or baseline_days != days):
            result['reason'] = 'observation_window_incomplete'; continue
        if base.get('end', '') >= post['start']:
            result['reason'] = 'overlapping_observation_windows'; continue
        before, after = _number(base.get(metric)), _number(post.get(metric))
        if before is None or after is None:
            continue
        sample_before = _number(base.get('pageViews'))
        sample_after = _number(post.get('pageViews'))
        minimum = experiment.get('minimumSample')
        if type(minimum) is not int or sample_before is None or sample_after is None or sample_after < minimum:
            result.update(reason='insufficient_sample', before=before, after=after); continue
        result.update(status='observed_gain' if after > before else 'no_observed_gain', reason='matched_target_windows',
                      before=before, after=after, delta=after-before, baseline=base, observation=post,
                      minimumSampleBasis='post_window_page_views', baselineSampleLimited=sample_before < minimum,
                      statisticalSignificance='not_established')
        return result
    return result


def capture_experiment_observation(experiment, business, now=None):
    """Keep the exact completed window before rolling reports replace it."""
    now = time.time() if now is None else now
    if not experiment.get('interventionReceipt'):
        return experiment
    for row in _observations(business, experiment.get('targetUrl'), experiment.get('primaryMetric')):
        checked = _stamp(row.get('checkedAt'))
        if (row.get('start') == experiment.get('observationStart') and row.get('end') == experiment.get('observationEnd')
                and checked is not None and 0 <= now-checked <= 26*3600):
            experiment['finalObservation'] = {'row': dict(row), 'capturedAt': now}
    return experiment


def _merge_experiment_observation(identity, **updates):
    """Merge evaluation fields without losing concurrent reservations or overriding a stop."""
    allowed = {'finalObservation','status','evaluation','evaluatedAt','observationClosed','followupNeeded'}
    if set(updates) - allowed:
        raise ValueError('Only observation lifecycle fields may be merged')
    with locked(ROWS):
        state = load(STATE)
        experiment = state.get('activeExperiment') or {}
        if experiment.get('id') != identity or experiment.get('status') not in ('active','inconclusive'):
            return False
        experiment.update(updates)
        state['activeExperiment'] = experiment
        write(STATE, state)
    return True


def experiment_observation_closed(experiment, evaluation, now=None):
    """A sparse completed window can finish without success; missing reports get three days."""
    if not experiment.get('interventionReceipt'):
        return False
    if evaluation.get('status') != 'inconclusive':
        return True
    if evaluation.get('reason') == 'insufficient_sample' and experiment.get('finalObservation'):
        return True
    try:
        day = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).date()
        due = datetime.fromisoformat(experiment['measurementDate']).date()
        return day >= due + timedelta(days=3)
    except (KeyError, TypeError, ValueError):
        return False


def preview_business_experiment(business, target_url=None, now=None):
    """Deterministic, read-only preview; activation is an explicit state update."""
    now = time.time() if now is None else now
    candidates = sorted((r for r in business.get('pageObservations', [])
                         if r.get('source') == 'GA4 Data API' and r.get('complete') is True
                         and _number(r.get('pageViews')) is not None
                         and (not target_url or _url_key(r.get('url')) == _url_key(target_url))),
                        key=lambda r: (-float(r['pageViews']), r.get('url', '')))
    for row in candidates:
        proposal = {'targetUrl': row['url'], 'hypothesis': '대상 글의 비교·선택 정보와 내부 안내를 개선하고 측정 가능한 방문 변화를 확인한다',
                    'measurementDate': datetime.fromtimestamp(now, timezone.utc).date().isoformat(),
                    'evidenceConfidence': 'low', 'maxModelCalls': 20, 'primaryMetric': 'pageViews',
                    'measurementWindowDays': 7, 'minimumSample': 50,
                    'successMetric': '완전한 대상 관측기간에서 50 PV 이상과 기준선 대비 증가; 수익 효과는 별도 검증',
                    'stopCondition': '7일 관측 후 주지표 증가 미확인 또는 공유 호출 20회 소진 시 추가 자동배정 중단'}
        try:
            return bind_business_experiment(proposal, business, ['legacy_remodel', 'threads'], now)
        except ValueError:
            continue
    return {'status': 'awaiting_baseline', 'reason': 'no_fresh_complete_seven_day_target_observation'}


def activate_experiment_preview(preview):
    """Explicit internal-state activation only; does not publish, collect or call a model."""
    validate_business_experiment(preview, strict=True)
    if not preview.get('id') or not preview.get('baseline') or preview.get('status') != 'active':
        raise ValueError('An observed host-bound preview is required')
    with locked(ROWS):
        state = load(STATE)
        previous = state.get('activeExperiment') or {}
        if previous.get('id') == preview['id']:
            return previous  # Never reset its observation clock or resource ledger.
        if any(row.get('id') == preview['id'] for row in state.get('experimentHistory', [])):
            raise ValueError('Archived experiment identities cannot be reactivated or reset')
        if previous.get('id') and previous.get('status') in ('active', 'inconclusive') and not previous.get('observationClosed'):
            raise ValueError('Existing experiment must be explicitly stopped before replacement')
        if previous.get('id'):
            history = state.setdefault('experimentHistory', [])
            if not any(row.get('id') == previous['id'] for row in history):
                history.append(previous)
        state['activeExperiment'] = preview
        state['focusChannels'] = preview['focusChannels']
        write(STATE, state)
    return preview


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
    return goal.get('status') in ('answered','blocked') and not _pending_owned_work(goal)


def _pending_owned_work(goal):
    pending = goal.get('pendingAction') or {}
    if pending:
        request_id = pending.get('requestId')
        receipt = load(DATA/'staff-requests'/(hashlib.sha256(str(request_id).encode()).hexdigest()+'.json')) if request_id else {}
        # Missing/stale receipts are uncertainty, never proof that a submitted action stopped.
        if receipt.get('status') not in ('completed', 'cancelled', 'denied') or receipt.get('pendingEffect'):
            return True
    conference = goal.get('pendingConference')
    if conference:
        receipt = load(ROWS.parent/(str(conference)+'.json')) if re.fullmatch(r'[a-f0-9]{64}', str(conference)) else {}
        if receipt.get('status') not in ('completed', 'cancelled') or receipt.get('pendingEffect'):
            return True
    return False


def occupies_lane(row):
    if running(row):
        return True
    if row.get('status') in ('blocked', 'recovering'):
        identity = row.get('controllerGoalId') or row.get('recoveryGoalId') or row.get('source', {}).get('goalId')
        goal = load(DATA/'chats/reasoning-goals'/(identity+'.json')) if identity and re.fullmatch(r'[a-f0-9]{64}', identity) else {}
        if goal.get('status') in ('ready', 'running'):
            return True
        return _pending_owned_work(goal) or _pending_owned_work(row)
    return not waiting_investigation(row)


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
            'results':[{k:r.get(k) for k in ('ok','status','project','publicationVerified','recoveryVerified','reservationVerified','publicUrl','account','questionId')} for r in results]},staff=staff)
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
            if (row.get('status') == 'closed' and kind == 'conference'
                    and row.get('resumeAuthorized') is True and not row.get('verification', {}).get('verified')):
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
            if row.get('status') == 'executing' and identity not in cur_active:
                row['status'] = 'queued'
                _save(row)
            if (kind == 'conference' and identity not in cur_active
                    and identity not in state.get('pending', []) and identity not in state.get('suspended', [])
                    and not row.get('verification', {}).get('verified')):
                conf_id = (source or {}).get('conferenceId') or (row.get('source') or {}).get('conferenceId')
                crow = load(ROWS.parent / f'{conf_id}.json') if conf_id else {}
                if crow and crow.get('status') == 'queued' and not crow.get('submissionStarted'):
                    row.update(status='queued', controllerFailures=0, nextCheckAt=0, processes=[], events={})
                    for k in ('blocker', 'closedAt', 'closeReason', 'recoveryWatch', 'controllerGoalId', 'recoveryGoalId', 'recoveryPreparation'):
                        row.pop(k, None)
                    _save(row)
            if row.get('status') == 'queued' and identity not in cur_active and identity not in state.get('pending', []) and identity not in state.get('suspended', []):
                state.setdefault('pending', []).append(identity)
                write(STATE, state)
            return identity
        if len(state.get('pending', [])) >= 200:
            raise AgendaWaiting('안건 대기열이 가득 찼습니다. 기존 안건을 먼저 마무리합니다.')
        if source.get('autonomousExperiment'):
            if source.get('experimentId') != (state.get('activeExperiment') or {}).get('id') or not autonomous_experiment_allows(source.get('gateProject') or project,
                    target_url=source.get('targetUrl', ''), domain=source.get('domain', ''), state=state):
                return None
        row = {'id':identity, 'kind':kind, 'title':str(title)[:500], 'project':project,
               'source':source, 'completionCriteria':completion, 'priority':priority,
               'notBefore':not_before, 'createdAt':time.time(), 'status':'queued','manualNudges':0,
               'version':1, 'owner':uuid.uuid4().hex, 'plan':[], 'events':{}, 'processes':[]}
        row['acceptanceRequirements'] = acceptance_requirements(row)
        if source.get('autonomousExperiment'):
            row['businessExperiment'] = state['activeExperiment']
            if kind == 'conference':
                state['activeExperiment'].setdefault('newPublicationAgendaIds', []).append(identity)
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
        source = chosen.get('source') or {}
        if source.get('autonomousExperiment') and not chosen.get('activatedAt'):
            experiment = state.get('activeExperiment') or {}
            if (source.get('experimentId') != experiment.get('id') or
                    not autonomous_experiment_allows(source.get('gateProject') or chosen.get('project'),
                        target_url=source.get('targetUrl', ''), domain=source.get('domain', ''), state=state, reserved_agenda_id=identity)):
                return None
        proj = chosen.get('project') or 'other'
        limit = LANE_LIMITS.get(proj, 1)
        lane_active = [r for r in cur_rows if (r.get('project') or 'other') == proj and occupies_lane(r)
                       and read_only_agenda(r)==read_only_agenda(chosen)]
        if len(lane_active) >= limit:
            return None
        chosen.update(status='report_pending' if chosen.get('verification',{}).get('verified') else 'meeting', activatedAt=time.time())
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
        text = (('[검증 완료] ' if (row.get('outcome') or {}).get('status') == 'completed'
                 else '[미해결 보고] ') + short_title(row))[:50]
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
        state = load(STATE)
        outcome = task_outcome(row)
        if not row.get('auxiliaryResult'):
            outcome.update(blocker=str(reason)[:1000], owner=row['waitingFor']['owner'])
        _retain_outcome(row, state, outcome)
        write(STATE, state)
        if 'blocked' not in row['events']:
            row['events']['blocked'] = event(row, 'blocked', 'jarvis',
                '같은 안건을 유지합니다: '+row['title']+'\n'+row['blocker']+'\n실제 해결은 미완료이며 다음 안건을 시작하지 않았습니다.')
        _save(row)


def acceptance_requirements(row):
    """Host-owned scope; a worker cannot narrow its assignment in a result."""
    explicit = row.get('acceptanceRequirements') or (row.get('source') or {}).get('acceptanceRequirements')
    if explicit:
        required = list(dict.fromkeys(str(value) for value in explicit))
        if (row.get('source') or {}).get('directive') and 'requested_directive' not in required:
            required.append('requested_directive')
        return required
    if row.get('kind') == 'conference' and 'prepare' in str((row.get('source') or {}).get('arguments', {}).get('action', '')):
        return ['preparation_receipt']
    requirements = [{'cro_widget_retrofit': 'target_intervention', 'indexnow_unindexed_push': 'submission_receipt',
             'radar': 'candidate_evidence', 'brunch_publish': 'publication_receipt',
             'audit': 'audit_results', 'style': 'review_results', 'conference': 'conference_receipt',
             'staff': 'requested_actions'}.get(row.get('kind'), 'requested_scope')]
    # Preserve a broader assignment verbatim; a tool's narrower receipt cannot discharge it.
    if (row.get('source') or {}).get('directive'):
        requirements.append('requested_directive')
    return requirements


def task_outcome(row, evidence=None, now=None):
    """Evaluate receipts, not administrative status, summaries or worker success flags."""
    now = time.time() if now is None else now
    evidence = evidence if evidence is not None else row.get('verification') or {}
    result = evidence.get('result') or row.get('auxiliaryResult') or {}
    required = acceptance_requirements(row)
    satisfied = set()
    owner = (row.get('source') or {}).get('assignedRole') or {
        'cro_widget_retrofit': 'doctor', 'radar': 'radar', 'indexnow_unindexed_push': 'trace',
        'brunch_publish': 'publi', 'audit': 'doctor'}.get(row.get('kind'), 'jarvis')
    def nodes(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from nodes(child)
        elif isinstance(value, list):
            for child in value:
                yield from nodes(child)
    records = list(nodes(result))
    ambiguous = any(r.get('pendingEffect') or r.get('pending_effect') or r.get('externalEffectUnknown')
                    or r.get('status') == 'submitted_unknown' for r in records + [evidence])
    ambiguous = ambiguous or bool(row.get('auxiliaryStartedAt') and not result)
    errors = any(r.get('error') or r.get('errors') or r.get('errorType') or
                 r.get('status') in ('failed', 'error') for r in records)
    held = any(r.get('holds') or r.get('status') in ('held', 'blocked', 'review_required', 'busy') for r in records)
    idle = result.get('status', result.get('state', result.get('action'))) in ('idle', 'no_work', 'no_due_slot', 'no_due_draft',
        'already_optimized', 'all_recent_pinged', 'already_claimed', 'no_matching_target')
    target = _url_key((row.get('source') or {}).get('targetUrl'))
    receipts = result.get('posts', []) or ([result] if result.get('durableSuccess') else [])
    posts = [p for p in receipts if isinstance(p, dict) and
             (not target or _url_key(p.get('url')) == target) and p.get('apiStatus', p.get('httpStatus')) in (200, 201, 204)
             and p.get('durableSuccess') is True and p.get('publicContentMatched') is True
             and _stamp(p.get('verifiedAt')) is not None and row.get('createdAt', 0) <= _stamp(p['verifiedAt']) <= now]
    if posts:
        satisfied.add('target_intervention')
    submitted = [p for p in result.get('pingedUrls', []) if isinstance(p, dict) and
                 (not target or _url_key(p.get('url')) == target) and p.get('accepted') is True and
                 any(r.get('httpStatus') in (200, 202) for r in p.get('results', []) if isinstance(r, dict))]
    if submitted:
        satisfied.add('submission_receipt')
    if result.get('publicationVerified') is True and result.get('publicUrl'):
        satisfied.add('publication_receipt')
    if result.get('candidates') and all(isinstance(c, dict) and c.get('source') for c in result['candidates']):
        satisfied.add('candidate_evidence')
    sources = result.get('sources') or (result.get('scout') or {}).get('sources') or []
    scan_scope = (row.get('source') or {}).get('scanScope')
    if (scan_scope and result.get('scanScope') == scan_scope and sources
            and all(s.get('status') == 'collected' and _stamp(s.get('fetchedAt')) is not None
                    and 0 <= now - _stamp(s['fetchedAt']) <= 26*3600 for s in sources)):
        satisfied.add('source_scan')  # A verified empty scan is valid when that is the requested deliverable.
    if result.get('results') and result.get('status') == 'completed':
        satisfied.add('audit_results')
    if result.get('status') in ('completed', 'already_reviewed') and result.get('source'):
        satisfied.add('review_results')
    if evidence.get('verified') is True and evidence.get('source'):
        outcomes = evidence.get('outcomes') or []
        if (evidence.get('preparation') or {}).get('preparationVerified') is True:
            satisfied.add('preparation_receipt')
        if outcomes and all(r.get('publicationVerified') is True or r.get('reservationVerified') is True for r in outcomes):
            satisfied.add('conference_receipt')
        actions = (row.get('source') or {}).get('actions') or []
        results = evidence.get('results') or []
        if actions and len(results) == len(actions) and all(r.get('ok') is True and
                (a.get('tool') in READ_ONLY or any(r.get(k) is True for k in
                 ('publicationVerified', 'recoveryVerified', 'reservationVerified'))) for a, r in zip(actions, results)):
            satisfied.add('requested_actions')
        for key, proof in (evidence.get('acceptanceResults') or {}).items():
            if not isinstance(proof, dict) or not proof.get('source') or not proof.get('sha256'):
                continue
            # Only a persisted host receipt bound to this agenda and the original scope is accepted.
            receipt_path = Path(proof['source']).resolve()
            if not receipt_path.is_relative_to(DATA.resolve()) or not receipt_path.is_file() or Path(proof['source']).is_symlink():
                continue
            raw = receipt_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != proof['sha256']:
                continue
            try:
                receipt = json.loads(raw)
            except (ValueError, UnicodeError):
                continue
            scope = (row.get('source') or {}).get('directive') if key == 'requested_directive' else row.get('completionCriteria')
            if (receipt.get('producer') == 'barolab-host-acceptance-v1' and receipt.get('agendaId') == row.get('id')
                    and receipt.get('scope') == scope and (receipt.get('requirements') or {}).get(key) is True
                    and type(receipt.get('verifiedAt')) in (int, float)
                    and row.get('createdAt', 0) <= receipt['verifiedAt'] <= now):
                satisfied.add(key)
    missing = [key for key in required if key not in satisfied]
    status = ('held' if ambiguous else 'partial' if satisfied and (missing or errors or held) else
              'error' if errors else 'held' if held else 'idle' if idle else
              'completed' if not missing else 'partial' if satisfied else 'held')
    reason = ('external_effect_unknown' if ambiguous else 'source_error' if errors else
              'independent_factual_review_required' if any(r.get('reason') == 'independent_factual_review_required' for r in records) else
              'acceptance_unverified' if missing else 'no_intervention' if idle else 'required_scope_verified')
    return {'status': status, 'owner': owner, 'required': required, 'verifiedScope': sorted(satisfied),
            'missingScope': missing, 'blocker': None if status == 'completed' else reason,
            'nextAction': None if status == 'completed' else
                'verify_existing_external_receipt' if ambiguous else
                'independent_factual_review' if reason == 'independent_factual_review_required' else 'review_missing_acceptance',
            'autoRetry': False, 'checkedAt': now}


def _retain_outcome(row, state, outcome):
    """One durable review followup per agenda; it is never an execution/retry queue."""
    row['outcome'] = outcome
    row['acceptanceRequirements'] = outcome['required']
    row['responsibleCrew'] = outcome['owner']
    row['decisionChain'] = {'judgment': outcome['status'], 'why': outcome['blocker'] or 'required_scope_verified',
        'evidence': {'source': (row.get('verification') or {}).get('source'),
                     'verifiedScope': outcome['verifiedScope'], 'checkedAt': outcome['checkedAt']},
        'responsibleCrew': outcome['owner'], 'acceptance': outcome['required'],
        'verifiedOutcome': outcome['status'] == 'completed'}
    if (row.get('source') or {}).get('evidenceReview'):
        return  # Review reports cannot recursively commission more reviews.
    followups = state.setdefault('unresolvedWork', {})
    key = 'agenda:' + row['id']
    if outcome['status'] == 'completed':
        if key in followups:
            followups[key].update(status='resolved', resolvedAt=time.time())
        row.pop('blocker', None)
        row.pop('nextAction', None)
    else:
        row.update(blocker=outcome['blocker'], nextAction=outcome['nextAction'])
        previous = followups.get(key) or {}
        followups[key] = {**previous, 'key': key, 'agendaId': row['id'], 'owner': outcome['owner'],
            'status': outcome['status'], 'blocker': outcome['blocker'], 'nextAction': outcome['nextAction'],
            'acceptance': outcome['missingScope'], 'createdAt': previous.get('createdAt', time.time()),
            'dueAt': previous.get('dueAt', time.time()), 'autoRetry': False}


def start_experiment_observation(experiment, row, evidence, now=None):
    """Pure, idempotent receipt adapter; planning and dispatch do not start the clock."""
    now = time.time() if now is None else now
    if experiment.get('interventionReceipt') or (row.get('source') or {}).get('experimentId') != experiment.get('id'):
        return experiment
    if task_outcome(row, evidence, now)['status'] != 'completed':
        return experiment
    result = evidence.get('result') or {}
    target = _url_key(experiment.get('targetUrl'))
    receipts = [p for p in (result.get('posts', []) or ([result] if result.get('durableSuccess') else [])) if _url_key(p.get('url')) == target
                and p.get('apiStatus', p.get('httpStatus')) in (200, 201, 204) and _stamp(p.get('verifiedAt')) is not None
                and p.get('durableSuccess') is True and p.get('publicContentMatched') is True]
    if not receipts and ((row.get('source') or {}).get('executionContract') or {}).get('scope') == 'accepted_target_submission':
        receipts = [p for p in result.get('pingedUrls', []) if _url_key(p.get('url')) == target
                    and p.get('accepted') is True and p.get('verificationScope') == 'submission_only'
                    and _stamp(p.get('verifiedAt')) is not None
                    and any(r.get('httpStatus') in (200, 202) for r in p.get('results', []))]
    if not receipts:
        return experiment
    receipt = max(receipts, key=lambda p: _stamp(p['verifiedAt']))
    stamp = _stamp(receipt['verifiedAt'])
    if not experiment.get('startedAt', 0) <= stamp <= now:
        return experiment
    start = datetime.fromtimestamp(stamp, timezone.utc).astimezone(
        __import__('zoneinfo').ZoneInfo(experiment['baseline']['timezone'])).date() + timedelta(days=1)
    end = start + timedelta(days=experiment['measurementWindowDays'] - 1)
    return {**experiment, 'interventionReceipt': {**receipt, 'agendaId': row['id'], 'source': evidence['source']},
            'interventionType': 'submission' if receipt.get('verificationScope') == 'submission_only' else 'public_content_change',
            'interventionAt': stamp, 'observationState': 'observing', 'observationStart': str(start),
            'observationEnd': str(end), 'measurementDate': str(end + timedelta(days=1)),
            'nextMeasureDate': str(end + timedelta(days=1))}


def reconcile_task_outcomes(identities, *, apply=False, expected_fingerprint=None):
    """Explicit bounded repair only. Preview first; apply rejects changed runtime inputs."""
    if not identities or len(identities) > 100:
        raise ValueError('Supply 1..100 audited agenda identities')
    with locked(ROWS):
        state = load(STATE)
        rows = [get(identity) for identity in sorted(set(identities))]
        fingerprint = hashlib.sha256(json.dumps([state, rows], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if apply and fingerprint != expected_fingerprint:
            raise ValueError('Reconciliation inputs changed; preview again')
        changes = []
        for row in rows:
            if not row or running(row):
                continue
            outcome = task_outcome(row, now=row.get('verifiedAt') or time.time())
            if outcome['status'] == 'completed' or not (row.get('auxiliaryResult') or row.get('auxiliaryStartedAt')
                                                       or row.get('investigationReport') or row.get('outcome')):
                continue
            if (row.get('outcomeCorrections') and row.get('status') == 'blocked'
                    and all((row.get('outcome') or {}).get(k) == outcome.get(k) for k in ('status', 'blocker', 'missingScope'))):
                continue
            changes.append({'agendaId': row['id'], 'previousStatus': row.get('status'), 'outcome': outcome})
            if apply:
                row.setdefault('outcomeCorrections', []).append({'at': time.time(), 'previousStatus': row.get('status'),
                    'previousClosedAt': row.get('closedAt'), 'reason': 'audited_acceptance_reconciliation'})
                _retain_outcome(row, state, outcome)
                row.update(status='blocked', nextCheckAt=0)
                _save(row)
                state['pending'] = [key for key in state.get('pending', []) if key != row['id']]
                state['activeIds'] = [key for key in state.get('activeIds', []) if key != row['id']]
                if state.get('activeId') == row['id']:
                    state['activeId'] = next(iter(state['activeIds']), None)
        experiment = state.get('activeExperiment') or {}
        affected = any((r.get('source') or {}).get('experimentId') == experiment.get('id') for r in rows if r)
        reset_clock = bool(affected and experiment.get('id') and experiment.get('status') in ('active', 'inconclusive')
                           and not experiment.get('interventionReceipt')
                           and experiment.get('observationState') != 'waiting_intervention')
        if apply and reset_clock:
            experiment.setdefault('lifecycleCorrections', []).append({k: experiment.get(k) for k in
                ('observationStart', 'observationEnd', 'measurementDate', 'evaluation', 'observationClosed')})
            experiment.update(observationState='waiting_intervention', observationStart=None, observationEnd=None,
                              nextMeasureDate=None, observationClosed=False, status='active')
        if apply:
            write(STATE, state)
        return {'applied': apply, 'fingerprint': fingerprint, 'changes': changes, 'resetObservationClock': reset_clock}


def verified(identity, evidence, *, staff=None, manager=None):
    """Only trusted receipt adapters call this; models cannot call the closing API."""
    if not evidence or evidence.get('verified') is not True or not evidence.get('source'):
        raise ValueError('Actual operation evidence is required')
    with locked(ROWS):
        row = get(identity)
        if row['status'] == 'closed':
            return False
        state = load(STATE)
        outcome = task_outcome(row, evidence)
        row['verification'] = evidence
        _retain_outcome(row, state, outcome)
        if outcome['status'] != 'completed':
            row['status'] = 'blocked'
            _save(row)
            write(STATE, state)
            return False
        experiment = state.get('activeExperiment') or {}
        state['activeExperiment'] = start_experiment_observation(experiment, row, evidence)
        write(STATE, state)
        row.update(status='suspended' if row['status']=='suspended' else 'report_pending', verification=evidence, verifiedAt=time.time(),
                   lastAction='정해 둔 범위의 실제 결과를 확인했습니다. 담당자와 팀장의 마무리 보고를 전달하고 있습니다.')
        row.pop('blocker',None)
        for stage, reply in (('staff_result',staff), ('closing',manager)):
            if reply and stage not in row['events']:
                row['events'][stage] = event(row, stage, reply['actor'], reply['text'], reply.get('route'))
        _save(row)
    return True


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
        state = load(STATE)
        _retain_outcome(row, state, task_outcome(row))
        write(STATE, state)
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
            if row.get('kind') in ('conference', 'staff', 'cro_widget_retrofit', 'indexnow_unindexed_push', 'audit', 'radar', 'style'):
                if row['kind'] == 'cro_widget_retrofit':
                    fast_plan = [
                        "기발행 CF 블로그 원고 중 전환 위젯(3초 자가진단·제휴·내부 브릿지) 미적용 글 스캔",
                        "표(Table) 가독성 리모델링 및 고단가 내부 브릿지·제휴 CTA 위젯 일괄 주입",
                        "Cloudflare API 업데이트 및 엣지 캐시 즉시 퍼지(Purge) 검증",
                    ]
                elif row['kind'] == 'indexnow_unindexed_push':
                    fast_plan = [
                        "CF 블로그 16개 도메인 기발행 글 중 미색인·미전송 URL 스캔",
                        "IndexNow · Bing · Google Sitemap Ping 일괄 강제 제출 및 사이트맵 캐시 워밍",
                        "전송 영수증(indexnow_log.json) 기록 및 응답 코드 검증",
                    ]
                elif row['kind'] == 'audit':
                    fast_plan = [
                        "기발행 콘텐츠 초반 3초 후킹·체류시간·CTA 동선 품질 감사(@doctor)",
                        "개선 대상 항목 체크리스트 도출 및 리모델링 반영",
                        "감사 결과 영수증 저장 및 보고",
                    ]
                elif row['kind'] == 'radar':
                    fast_plan = [
                        "실시간 검색·SNS 급상승 고단가(CPC/CPA) 트렌드 키워드 스카우팅(@radar)",
                        "외부유입(지식iN·Threads·블로그 브릿지) 연계 타깃 키워드 후보군 추출",
                        "수집 결과 저장 및 파이프라인 공급",
                    ]
                elif row['kind'] == 'staff':
                    fast_plan = ['등록된 담당자·도구로 지정 작업 실행', '실제 반환값·공개 또는 조회 결과 확인', '검증된 결과와 미해결 사항 보고']
                else:
                    fast_plan = [
                        f"[{row.get('project')}] 타깃 키워드 및 수익화(CPA/CPC/애드센스) 전략 앵글 확정",
                        "독자 체류시간·전환 극대화 본문 및 고해상도 시각 자료 생성",
                        "채널 발행·예약 실행 및 실제 영수증/공개 상태 검증",
                    ]
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
    if row.get('verification') and task_outcome(row)['status'] != 'completed':
        close_and_advance(identity, reason='acceptance_unverified')
        return True
    if row.get('verification', {}).get('verified') is True:
        fast_route = {'provider': 'host', 'model': 'fast-verified-reporter', 'reasoningEffort': 'fast'}
        staff_actor = (row.get('source') or {}).get('assignedRole') or (
            'doctor' if row.get('kind') in ('cro_widget_retrofit', 'audit') else
            'trace' if row.get('kind') == 'indexnow_unindexed_push' else
            'radar' if row.get('kind') == 'radar' else 'publi'
        )
        summary_detail = str((row.get('verification') or {}).get('summary') or short_title(row))
        with locked(ROWS):
            row = get(identity)
            if 'staff_result' not in row.get('events', {}):
                row.setdefault('events', {})['staff_result'] = event(row, 'staff_result', staff_actor, f"[실행·검증 완료] {summary_detail}", fast_route)
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
        outcome = task_outcome(row)
        _retain_outcome(row, state, outcome)
        row.update(status='closed' if outcome['status'] == 'completed' else 'blocked', reportedAt=time.time())
        if outcome['status'] == 'completed':
            row['closedAt'] = time.time()
        if outcome['status'] == 'completed' and row.get('waitingFor'):
            row['resolvedWaitingFor'] = {'previous': row.pop('waitingFor'), 'resolvedAt': row['closedAt'],
                                         'reason': 'verified_result_and_reports_acknowledged'}
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
            'verifiedCompletions':1 if task_outcome(row)['status'] == 'completed' else None}
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
    """Report measured scope; derive PV only from a matched revenue/PV report."""
    if business is None:
        try:
            from server.growth import business_evidence
            business = business_evidence()
        except Exception:
            business = {}
    totals, missing = {}, []
    observed_rows = business.get('priorDayRevenue') or []
    for row in observed_rows:
        amount = _number(row.get('amount'))
        currency = row.get('currency')
        if amount is None or not currency or row.get('status') != 'collected':
            missing.append(row.get('source')); continue
        totals[currency] = totals.get(currency, 0.0) + amount
    usd = totals.get('USD')
    pv = sessions = None
    traffic_scopes = []
    for site in business.get('trafficSites') or []:
        period = (site.get('periods') or {}).get('day') or {}
        if site.get('status') != 'collected':
            continue
        value, count = _number(period.get('pageViews')), _number(period.get('sessions'))
        if value is not None:
            pv = (pv or 0) + value
        if count is not None:
            sessions = (sessions or 0) + count
        traffic_scopes.append({'domain': site.get('domain'), **period, 'checkedAt': site.get('checkedAt')})
    matching = []
    for report in business.get('matchedRevenuePv') or []:
        revenue, views = _number(report.get('revenue')), _number(report.get('pageViews'))
        stamp = _stamp(report.get('checkedAt'))
        if (report.get('matched') is True and report.get('complete') is True and report.get('currency') == 'USD'
                and report.get('source') and report.get('start') and report.get('end') and report.get('timezone')
                and stamp is not None and 0 <= time.time()-stamp <= 26*3600
                and revenue is not None and views is not None and views > 0):
            matching.append(report)
    # Never pool different dates, currencies, page selections or reporting sources.
    chosen = max(matching, key=lambda r: (r['end'], r['checkedAt'])) if matching else None
    rpm = 1000 * float(chosen['revenue']) / float(chosen['pageViews']) if chosen else None
    required = math.ceil(100000 / rpm) if rpm is not None and rpm > 0 else None
    gap = round(max(0, 100-usd), 4) if usd is not None else None
    diagnosis = ('동일 기간·범위의 USD 수익과 PV 실측 RPM이 없어 목표 필요 PV는 미확인입니다.' if required is None else
                 f"선택된 관측 범위의 RPM ${rpm:.4f}를 가정한 $100/일 필요 PV는 {required:,}회입니다. 전체 회사 예측이나 수익 보장이 아닙니다.")
    return {'dailyTargetUsd': 100.0, 'observedDailyRevenueUsd': usd, 'revenueGapUsd': gap,
            'achievementPct': round(usd, 4) if usd is not None else None,
            'assumedCpcUsd': None, 'requiredDailyClicks': None, 'requiredDailyPv': required,
            'observedDailyPv': pv, 'observedDailySessions': sessions, 'trafficGapPv': None,
            'measuredRpmUsd': rpm, 'rpmEvidence': chosen, 'revenueByCurrency': totals,
            'revenueScope': {'reportedSources': observed_rows, 'missingSources': missing,
                             'complete': bool(observed_rows) and not missing and business.get('revenueCoverageComplete') is True},
            'trafficScope': traffic_scopes, 'currencyConversion': 'not_applied',
            'status': 'scoped_target_observed' if usd is not None and usd >= 100 else 'measurement_required' if required is None else 'in_progress',
            'diagnosis': diagnosis, 'causalClaim': False}


def view():
    if not enabled():
        return {'enabled':False}
    state = load(STATE)
    def experiment_summary(row):
        return {'id': row.get('id'), 'status': row.get('status'), 'causalClaim': False,
                'draft': {k: row.get(k) for k in ('targetUrl','hypothesis','primaryMetric','maxModelCalls','observationStart','observationEnd','measurementDate','minimumSample','maxNewPublications','stopCondition')},
                'measured': {'baseline': {k: (row.get('baseline') or {}).get(k) for k in ('source','start','end','checkedAt','complete','pageViews','sessions','estimatedRevenue','currency')},
                             'evaluation': {k: (row.get('evaluation') or {}).get(k) for k in ('status','reason','before','after','delta','baselineSampleLimited','statisticalSignificance')},
                             'modelCalls': ((load(DATA/'llm_usage_ledger.json').get('byExperiment') or {}).get(row.get('id')) or {}).get('modelCalls')},
                'publicationReservations': len(row.get('newPublicationAgendaIds') or [])}
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
            'activeExperiment': experiment_summary(state['activeExperiment']) if (state.get('activeExperiment') or {}).get('id') else None,
            'recentExperiments': [experiment_summary(row) for row in reversed(state.get('experimentHistory', [])[-5:])],
            'ceoProposals': (proposals_state.get('proposals') or [])[:5],
            'ceoApprovalReview': {k: proposals_state.get(k) for k in
                                  ('approvalReviewSummary', 'executionPackages', 'residualDecisions')}}
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
        outcome = task_outcome(row)
        _retain_outcome(row, state, outcome)
        row.update(status=('closed' if outcome['status'] == 'completed' else 'blocked') if status == 'closed' else status,
                   releasedAt=time.time())
        if row['status'] == 'closed':
            row['closedAt'] = time.time()
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
    if repair_workflow.agenda_recovery_blocker(row):
        return False
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
        if not verified(row['id'], evidence):
            return False
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
    if row.get('kind') == 'conference' and row.get('project') == 'cf_blog':
        args = (row.get('workTarget') or row.get('source') or {}).get('arguments', {})
        domain = args.get('account')
        sched = load(DATA / 'cf/daily_schedule.json')
        if domain and sched.get('date') == args.get('date'):
            item = next((i for i in sched.get('items', []) if i.get('domain') == domain), {})
            if item.get('status') == 'published' and item.get('publicUrl'):
                return True
            if args.get('action') == 'cf-prepare':
                from common.channel_parameters import folder_for
                folder = folder_for('cf_posting', args.get('date', ''), domain)
                if (folder / 'article.json').is_file() and (folder / 'photo-plan.json').is_file():
                    return True
    if row.get('kind') == 'conference' and row.get('project') == 'naver_blog':
        args = (row.get('workTarget') or row.get('source') or {}).get('arguments', {})
        if args.get('account') and args.get('date') and args.get('slot'):
            from common.channel_parameters import folder_for
            folder = folder_for('naver_blog_posting', args['date'], args['account'] + '-' + str(args['slot']).replace(':', ''))
            if load(folder / 'reservation-evidence.json').get('submissionStatus') == 'verified_reserved':
                return True
        conf_id = (row.get('source') or {}).get('conferenceId')
        if conf_id:
            crow = load(ROWS.parent / f'{conf_id}.json')
            err_msg = str((crow.get('failureDiagnostic') or {}).get('errorMessage') or '')
            if 'Unapproved account slot' in err_msg and not crow.get('submissionStarted'):
                return True
    if row.get('project') == 'threads' and row.get('kind') in ('conference', 'staff'):
        args = (row.get('workTarget') or row.get('source') or {}).get('arguments', {})
        part_id = args.get('partId')
        import sqlite3
        from contextlib import closing
        try:
            database=DATA/'threads.sqlite3'
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                if row.get('kind') == 'staff':
                    from datetime import datetime
                    from zoneinfo import ZoneInfo
                    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
                    pub_cnt = db.execute("SELECT count(*) FROM parts WHERE publication_date=? AND kind='main' AND state='published_verified'", (today,)).fetchone()[0]
                    if pub_cnt >= 2:
                        return True
                elif part_id:
                    main_id=part_id.rsplit('-',1)[0]+'-0'
                    main=db.execute("SELECT state FROM parts WHERE part_id=? AND kind='main'",(main_id,)).fetchone()
                    if main and main[0]=='published_verified':return True
                else:
                    main=db.execute("SELECT state FROM parts WHERE account_key=? AND publication_date=? AND slot=? AND kind='main'",
                                    (args.get('account'),args.get('date'),args.get('slot'))).fetchone()
                    if main and main[0]=='published_verified':return True
        except (OSError,sqlite3.Error):
            pass
        return False
    if row.get('kind') in ('cro_widget_retrofit', 'indexnow_unindexed_push', 'style', 'radar', 'audit', 'brunch_publish') and row.get('status') in ('blocked', 'recovering'):
        return True
    if row.get('kind') == 'conference' and row.get('project') == 'naver_kin':
        if time.time() - float(row.get('activatedAt') or row.get('createdAt') or 0) > 900:
            return True
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


def prune_stale_runtime_data(max_keep_per_dir=80):
    """Purge terminal/closed JSON runtime bloat so disk I/O and worker directory scans stay fast."""
    stats = {'deletedFiles': 0, 'deletedBytes': 0, 'byDir': {}}
    try:
        st = load(STATE)
        keep_agendas = set(active_ids(st)) | set(st.get('pending', [])) | set(st.get('suspended', [])) | set(st.get('recent', [])[:40])
        keep_confs = set()
        for aid in keep_agendas:
            arow = get(aid)
            cid = ((arow or {}).get('source') or {}).get('conferenceId')
            if cid:
                keep_confs.add(str(cid))

        def _prune_dir(folder, is_protected_fn, keep_count=max_keep_per_dir):
            if not folder.exists():
                return
            files = []
            for p in folder.glob('*.json'):
                try:
                    mtime = p.stat().st_mtime
                    size = p.stat().st_size
                    files.append((mtime, size, p))
                except OSError:
                    continue
            files.sort(key=lambda x: x[0], reverse=True)
            kept = 0
            del_cnt = 0
            del_bytes = 0
            for _, size, p in files:
                try:
                    if is_protected_fn(p):
                        continue
                except Exception:
                    continue
                if kept < keep_count:
                    kept += 1
                    continue
                try:
                    p.unlink()
                    del_cnt += 1
                    del_bytes += size
                except OSError:
                    pass
            if del_cnt:
                stats['deletedFiles'] += del_cnt
                stats['deletedBytes'] += del_bytes
                stats['byDir'][folder.name] = {'deletedFiles': del_cnt, 'deletedMB': round(del_bytes / (1024 * 1024), 2)}

        conf_dir = DATA / 'publication-conferences'
        if conf_dir.exists():
            for cp in conf_dir.glob('*.json'):
                try:
                    crow = load(cp)
                    if crow.get('status') in ('queued', 'running', 'pending') and crow.get('businessAgendaId'):
                        keep_agendas.add(str(crow['businessAgendaId']))
                        keep_confs.add(cp.stem)
                except Exception:
                    pass
        _prune_dir(
            ROWS,
            lambda p: p.stem in keep_agendas or load(p).get('status') in ('active', 'meeting', 'executing', 'queued', 'recovering', 'blocked', 'suspended'),
            keep_count=60,
        )
        _prune_dir(
            DATA / 'publication-conferences',
            lambda p: p.stem in keep_confs or load(p).get('status') in ('running', 'queued', 'pending'),
            keep_count=60,
        )
        _prune_dir(
            DATA / 'repair-workflows',
            lambda p: load(p).get('status') in ('running', 'queued', 'pending', 'active'),
            keep_count=60,
        )
        _prune_dir(
            DATA / 'chats' / 'work-event-history',
            lambda p: False,
            keep_count=120,
        )
        _prune_dir(
            DATA / 'chats' / 'staff-requests',
            lambda p: load(p).get('status') in ('queued', 'acknowledged', 'awaiting_completion', 'running'),
            keep_count=60,
        )
        _prune_dir(
            DATA / 'chats' / 'reasoning-goals',
            lambda p: load(p).get('status') in ('queued', 'running', 'active', 'pending'),
            keep_count=40,
        )
        _prune_dir(
            DATA / 'chats' / 'crew-outbox',
            lambda p: load(p).get('status') in ('queued', 'pending'),
            keep_count=60,
        )
    except Exception:
        pass
    return stats


def _queue_autonomous_work_order(work_type, role='doctor', target_domain='', directive='', hour_bucket=None,
                                 rationale='', additional_requirements=()):
    """Queue each selected experiment intervention once, not once per timer/hour."""
    state = load(STATE)
    experiment = state.get('activeExperiment') or {}
    domain = str(target_domain or '').lower().removeprefix('www.')
    definitions = {
        'cro_widget_retrofit': ('cro_widget_retrofit', 'legacy_remodel', '대상 원고 선택 기준·내부 안내 개선'),
        'indexnow_unindexed_push': ('indexnow_unindexed_push', 'collections', '대상 도메인 색인 제출 상태 확인'),
        'content_audit_patrol': ('audit', 'legacy_remodel', '대상 원고 근거·독자 과업 품질 감사'),
        'radar_high_cpc_scout': ('radar', 'collections', '관측된 주제의 검색 의도 가설 조사'),
        'brunch_daily_publish': ('brunch_publish', 'brunch', '대상 주제 외부 유입 실험'),
    }
    if work_type not in definitions:
        return None
    if not isinstance(additional_requirements, (list, tuple)) or not all(isinstance(r, str) and r.strip() for r in additional_requirements):
        raise ValueError('Additional requested scope must be explicit text requirements')
    kind, project, purpose = definitions[work_type]
    if kind in ('brunch_publish', 'radar', 'audit'):
        # Keep capability gaps visible without authorizing unsupported multi-target/channel writes.
        if (experiment.get('status') != 'active' or not experiment.get('id')
                or len(experiment.get('focusDomains') or []) not in (1, 2) or domain not in experiment['focusDomains']):
            return None
        identity = propose('capability_review', {'experimentId': experiment['id'], 'workType': work_type, 'domain': domain},
            title='정확한 대상 실행 기능 검토 · ' + work_type, project='collections',
            source={'assignedRole': 'patch', 'requestedWorkType': work_type, 'targetUrl': experiment['targetUrl'],
                    'rationale': rationale, 'directive': '\n'.join([*([directive] if directive else []), *additional_requirements]),
                    'acceptanceRequirements': ['exact_target_capability']},
            completion='정확한 대상에 한정된 실행·검증 기능과 제한을 읽기 전용으로 확인', inherit=False)
        if identity:
            with locked(ROWS):
                saved = get(identity); state = load(STATE)
                saved['businessExperiment'] = experiment
                outcome = task_outcome(saved)
                outcome.update(status='held', owner='patch', blocker='exact_target_capability_missing',
                               nextAction='review_exact_target_adapter')
                _retain_outcome(saved, state, outcome)
                saved['status'] = 'blocked'; _save(saved); write(STATE, state)
        return identity
    gate_project = 'legacy_remodel' if project == 'collections' else project
    if not autonomous_experiment_allows(gate_project, domain=domain, state=state):
        return None
    unsupported = [*([directive] if directive else []), *additional_requirements]
    required = ['target_intervention'] if kind == 'cro_widget_retrofit' else ['submission_receipt']
    identity = propose(kind, {'experimentId': experiment['id'], 'workType': work_type, 'domain': domain},
        title=purpose+' ? '+domain, project=project,
        source={'assignedRole': 'doctor' if kind == 'cro_widget_retrofit' else 'trace', 'domain': domain,
                'directive': '\n'.join(unsupported), 'rationale': rationale, 'businessPurpose': purpose,
                'acceptanceRequirements': required,
                'executionContract': {'version': 1, 'workType': work_type, 'targetUrl': experiment['targetUrl'],
                    'scope': 'public_editorial_rendering' if kind == 'cro_widget_retrofit' else 'accepted_target_submission'},
                'autonomousExperiment': True, 'experimentId': experiment['id'], 'targetUrl': experiment['targetUrl'],
                'gateProject': gate_project},
        completion=('지정 URL의 기존 내용으로 요약·표·내부 안내를 정리하고 저장된 HTML 및 공개 HTML을 확인'
                    if kind == 'cro_widget_retrofit' else '지정 URL의 접수 영수증 확인; 실제 색인은 별도 범위'),
        priority=3, inherit=False)
    if identity and unsupported:
        with locked(ROWS):
            saved = get(identity); state = load(STATE)
            if not saved.get('activatedAt') and saved.get('status') == 'queued':
                outcome = task_outcome(saved)
                outcome.update(status='held', blocker='unsupported_requested_scope', nextAction='scope_review_before_execution')
                _retain_outcome(saved, state, outcome)
                saved['status'] = 'blocked'; _save(saved); write(STATE, state)
    return identity


def _top_up_channel_lanes():
    """Keep enabled publication lanes stocked with due daily slots."""
    try:
        from common.conference_dispatch import request as conf_request
        config = load(DATA / 'project-autonomy.json')
        if config.get('enabled') is not True or (Path.home() / 'EGO_EXEC_DISABLED').exists():
            return
        projects = set(config.get('projects') or [])
        calls = []
        if 'cf_blog' in projects:
            calls.append(('parameters', {'action': 'cf-cycle'}))
        if 'naver_blog' in projects:
            calls.append(('parameters', {'action': 'naver-cycle'}))
        if 'naver_kin' in projects:
            calls.append(('kin', {}))
        if 'threads' in projects:
            calls.append(('threads', {}))
        for kind, payload in calls:
            try:
                conf_request(kind, payload, one=True, automatic=False)
            except (OSError, ValueError, AgendaWaiting):
                pass
    except (OSError, ValueError, AgendaWaiting):
        return


def _executive_proposal_key(experiment, focus_channels, proposal):
    """Deduplicate wording changes without hiding new accounts or larger requests."""
    health = load(DATA / 'collection-health.json')
    support = sorted((str(s.get('source')), str(s.get('reasonCode')))
                     for s in health.get('sources', []) if s.get('reasonCode') in (
                         'source_auth_required', 'source_not_connected', 'source_not_collected',
                         'source_configured_no_report_api'))
    blockers = sorted((r.get('project', ''), str(r.get('blocker', '')))
                      for r in active_rows() if r.get('status') in ('blocked', 'recovering'))
    quantities = re.findall(r'\d+(?:\.\d+)?', json.dumps(proposal.get('requiredApprovals') or [], ensure_ascii=False))
    context = {'target': experiment.get('targetUrl'), 'channels': sorted(focus_channels),
               'support': support, 'blockers': blockers, 'requestedQuantities': quantities}
    return 'executive-pivot:' + hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _build_live_executive_diagnostics():
    """Gather real-time, unvarnished telemetry across all 6 channels, quality audits, IndexNow receipts, and GA4/GSC traffic for @jarvis."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now_dt = datetime.now(ZoneInfo('Asia/Seoul'))
    today_str = now_dt.date().isoformat()

    cf_sched = load(DATA / 'cf/daily_schedule.json')
    cf_items = [r for r in (cf_sched.get('items') or []) if isinstance(r, dict)]
    cf_pub = [r['domain'] for r in cf_items if r.get('status') == 'published' and r.get('publicUrl')]
    cf_wait = [f"{r.get('domain')}({r.get('scheduledTime')})" for r in cf_items if r.get('status') != 'published']

    naver_ver = load(DATA / 'naver/public-verification.json')
    naver_today = [r for r in (naver_ver.get('evidence') or []) if isinstance(r, dict) and (r.get('publicationDate') == today_str or str(r.get('reserveTime') or '')[:10] == today_str)]

    kin_st = load(DATA / 'kin-automation-state.json')
    threads_st = load(DATA / 'public/threads.json')
    threads_pub = [r for r in (threads_st.get('recent') or []) if isinstance(r, dict) and r.get('publication_date') == today_str and r.get('kind') == 'main' and r.get('state') == 'published_verified']
    threads_slots = (threads_st.get('configuration') or {}).get('preferredTimes') or []

    brunch_st = load(DATA / 'brunch/status.json')
    brunch_acc = brunch_st.get('account') or {}
    brunch_pub = brunch_st.get('publishedArticles') or []
    brunch_drawer = brunch_st.get('drawerArticles') or []
    brunch_auto = brunch_st.get('automation') or {}

    idx_log = load(DATA / 'cf/indexnow_log.json')
    idx_entries = [e for e in (idx_log.get('pings') or []) if isinstance(e, dict)]
    idx_ok = sum(1 for e in idx_entries if any(isinstance(r, dict) and (r.get('accepted') or r.get('httpStatus') in (200, 202)) for r in (e.get('results') or [])))

    traffic_doc = load(DATA / 'traffic.json')
    raw_sites = traffic_doc.get('sites') or {}
    t_sites = list(raw_sites.values()) if isinstance(raw_sites, dict) else [s for s in raw_sites if isinstance(s, dict)]
    ga4_ok = sum(1 for s in t_sites if (s.get('ga4') or {}).get('status') == 'collected')
    gsc_ok = sum(1 for s in t_sites if (s.get('google') or {}).get('status') == 'collected')

    return {
        'checkedAtKst': now_dt.isoformat(timespec='seconds'),
        'channels': {
            'cf_blog': {
                'dailyTarget': 16,
                'publishedTodayCount': len(cf_pub),
                'publishedDomains': cf_pub,
                'remainingScheduled': cf_wait[:8],
                'qualityPolicy': '자청 4대 결핍 시냅스 주입 + 에디토리얼 정물 썸네일(인물 클론 0건) + 도메인 고유 카테고리 1:1 매칭',
            },
            'naver_blog': {
                'dailyTarget': 6,
                'verifiedOrReservedTodayCount': len(naver_today),
                'accountsActive': sorted({str(r.get('account')) for r in naver_today if r.get('account')}),
            },
            'naver_kin': {
                'dailyTarget': 20,
                'cadencePolicy': '30~35분 랜덤 교대 (계정당 60~70분 안전 간격)',
                'submissionCountsToday': kin_st.get('submissionCounts') or {},
                'lastRunAt': kin_st.get('lastRunAt'),
                'nextEligibleAt': kin_st.get('nextEligibleAt'),
                'nextAccount': kin_st.get('nextAccount'),
            },
            'threads': {
                'account': '@mustpickinfo',
                'dailyTarget': len(threads_slots) or 10,
                'preferredTimes': threads_slots,
                'publishedVerifiedTodayCount': len(threads_pub),
                'strategy': '하루 10슬롯 (CF 블로그 첫 댓글 브릿지 8회 + 순수 공감 2회)',
            },
            'brunch': {
                'account': f"{brunch_acc.get('pen_name', '머스트픽')} (@{brunch_acc.get('profile_id', '31d1f5fb288c4fc')})",
                'writerStatus': brunch_acc.get('writerStatus', 'approved'),
                'canPublishLive': bool(brunch_acc.get('canPublishLive', True)),
                'dailyTarget': 2,
                'dailySlots': brunch_auto.get('dailySlots') or ['09:30', '16:30'],
                'totalPublishedCount': len(brunch_pub),
                'drawerCount': len(brunch_drawer),
                'todayPublishedCount': brunch_auto.get('todayPublishedCount', 0),
                'lastRunTitle': brunch_auto.get('lastRunTitle'),
            },
            'naver_premium': {
                'channel': (brunch_st.get('naverPremium') or {}).get('serviceUrl'),
                'status': (brunch_st.get('naverPremium') or {}).get('status'),
                'statusLabel': (brunch_st.get('naverPremium') or {}).get('statusLabel'),
            },
        },
        'indexingAndAnalytics': {
            'indexNowAcceptedTodayCount': idx_ok,
            'ga4CollectedDomains': f'{ga4_ok}/{len(t_sites) or 16}',
            'gscCollectedDomains': f'{gsc_ok}/{len(t_sites) or 16}',
        },
        'dailyWinningTopics': {
            'revenueLeaders': (load(DATA / 'radar/daily_winning_topics.json').get('revenueLeaders') or {}),
            'provenTrafficWinnersTop5': (load(DATA / 'radar/daily_winning_topics.json').get('provenTrafficWinners') or [])[:5],
            'doctorCtrRemodelTargetsTop5': (load(DATA / 'radar/daily_winning_topics.json').get('doctorCtrRemodelTargets') or [])[:5],
            'pairedBridgeSetsTop5': (load(DATA / 'radar/daily_winning_topics.json').get('pairedBridgeSets') or [])[:5],
        },
    }


def _scoped_review_reads(followup, original, goal, crew):
    """Credit only a registered read of the current, exact host-owned source."""
    measurement = not original and followup['key'].startswith('measurement:')
    try:
        if measurement:
            name = crew.measurement_evidence_name(followup['key'])
            source_path, key = crew._measurement_source(name)
        elif original:
            name, key = 'agenda:' + original['id'], None
            source_path = path(original['id'])
        else:
            return []
        expected_source = source_path.resolve()
        expected_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except (OSError, ValueError, TypeError):
        return []
    reads = []
    for observation in goal.get('observations', []):
        result = observation.get('result') or {}
        if observation.get('tool') not in ('evidence', 'read_source') or not isinstance(result, dict):
            continue
        source = result.get('source') or result.get('path')
        if not isinstance(source, str) or result.get('sha256') != expected_hash:
            continue
        candidate = Path(source)
        if not candidate.is_absolute():
            candidate = crew.ROOT / candidate
        if candidate.resolve() != expected_source:
            continue
        if measurement:
            if (observation.get('tool') != 'evidence' or result.get('readerVersion') != 'measurement-json-v1'
                    or result.get('evidenceName') != name or result.get('followupKey') != key
                    or result.get('sha256') != followup.get('sourceFileSha256')
                    or observation.get('id') not in goal.get('evidenceIds', [])
                    or goal.get('answerSource') == 'host'):
                continue
            # Preloading makes the exact source available; it is not itself an employee review.
            if observation.get('actor') == 'host':
                if goal.get('decisions', 0) <= result.get('reviewAfterDecision', float('inf')):
                    continue
        else:
            data = result.get('data') or {}
            payload = (data.get('verification') or data.get('auxiliaryResult') or data) if isinstance(data, dict) else data
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if digest != followup.get('originalEvidenceHash'):
                continue
        reads.append(observation)
    return reads


def _review_source_coverage(observation):
    result = observation['result']
    def omitted(value):
        if isinstance(value, dict):
            return bool(value.get('detailRequired') or value.get('nextCharacter')) or any(omitted(v) for v in value.values())
        return isinstance(value, list) and any(omitted(v) for v in value)
    return {**{k: result.get(k) for k in ('source', 'sha256', 'evidenceName', 'pagination', 'selection', 'fields')},
            'detailRequired': omitted(result.get('data')),
            'coverage': 'partial' if omitted(result.get('data')) or (result.get('pagination') or {}).get('truncated')
                        or result.get('missingFields') else 'returned_page', 'acceptanceVerified': False}


def _check_review_budget(experiment, agenda_id=None):
    """Check shared lifetime usage before a new review agenda can be created."""
    from common import llm_usage
    root = DATA.parent.parent
    ledger = load(DATA / 'llm_usage_ledger.json'); policy = llm_usage.budget_policy(root)
    llm_usage.check_budget(ledger, {'agendaId': agenda_id} if agenda_id else {}, policy, root)
    if not isinstance(experiment, dict):
        raise llm_usage.UsageBudgetExceeded('experiment_call_budget_invalid')
    identity = experiment.get('id')
    if not isinstance(identity, str) or not identity.strip() or len(identity) > 160:
        raise llm_usage.UsageBudgetExceeded('experiment_identity_invalid')
    limit = experiment.get('maxModelCalls', policy['agendaCalls'])
    if type(limit) is not int or limit < 0:
        raise llm_usage.UsageBudgetExceeded('experiment_call_budget_invalid')
    used = ledger.get('byExperiment', {}).get(identity, {}).get('modelCalls', 0)
    active = sum(call.get('experimentId') == identity for call in ledger.get('active', {}).values())
    if used + active >= min(limit, policy['agendaCalls']):
        raise llm_usage.UsageBudgetExceeded('experiment_call_budget_exhausted')


def _hold_review_budget(followup, experiment, reason, now, agenda_id=None):
    """Persist a host-only decision request; repeated ticks share one CEO blocker."""
    from common.crew_chat_bridge import emit_ceo_proposal
    experiment = experiment if isinstance(experiment, dict) else {}
    target = experiment.get('targetUrl') or ('shared-experiment:' + str(experiment.get('id')))
    identity = {'experimentId': experiment.get('id'), 'target': target, 'reasonCode': reason,
                'scope': {k: experiment.get(k) for k in ('focusDomains', 'focusChannels')}}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    owner = followup.get('owner') or 'jarvis'
    with locked(ROWS):
        state = load(STATE); item = state.get('unresolvedWork', {}).get(followup['key'])
        if not item:
            return
        previous = item.get('reviewBudgetHold') or {}
        hold = {**identity, 'owner': owner, 'maxModelCalls': experiment.get('maxModelCalls'),
                'fingerprint': fingerprint, 'heldAt': previous.get('heldAt', now)}
        item.update(reviewBudgetHold=hold, blocker=reason, nextAction='await_budget_decision', autoRetry=False)
        if experiment.get('id'):
            item.setdefault('reviewExperiment', experiment)
        if previous.get('fingerprint') == fingerprint and previous.get('ceoProposalId'):
            hold['ceoProposalId'] = previous['ceoProposalId']
        write(STATE, state)
        if hold.get('ceoProposalId'):
            return
    refs = {'taskId': 'review-followup:' + hashlib.sha256(followup['key'].encode()).hexdigest()}
    if agenda_id:
        refs['agendaId'] = agenda_id
    if followup.get('reviewGoalId'):
        refs['goalId'] = followup['reviewGoalId']
    proposal = emit_ceo_proposal(owner, '원천 검토 예산 한도 도달 · 대표 결정 필요',
        json.dumps({**identity, 'owner': owner, 'followupKey': followup['key'],
                    'maxModelCalls': experiment.get('maxModelCalls')}, ensure_ascii=False),
        '기존 증거와 호출 원장을 보존하고 검토를 보류합니다. 우선순위 조정 또는 명시적 재개 조건을 결정해 주세요.',
        ['검토 우선순위와 허용된 재개 조건 결정; 예산 자동 증액·초기화 없음'],
        expected_impact='원문 검토와 사업 성과는 미확인 상태로 유지', request_key='review-budget:'+fingerprint,
        blocker_context={'project': 'evidence-review', 'reasonCode': reason, 'targetKey': fingerprint,
                         'securityScope': 'read_only_review', 'resumeCondition': 'explicit_budget_decision'},
        original_work=refs)
    with locked(ROWS):
        state = load(STATE); item = state.get('unresolvedWork', {}).get(followup['key'])
        if item and (item.get('reviewBudgetHold') or {}).get('fingerprint') == fingerprint:
            item['reviewBudgetHold']['ceoProposalId'] = proposal['proposal']['id']
            write(STATE, state)


def _queue_measurement_scope_correction(followup, goal, crew, now):
    """One newly reachable source may use the existing bounded material-review allowance."""
    if (goal.get('status') != 'answered' or goal.get('origin') != 'evidence-review'
            or goal.get('decisions', 0) < goal.get('maxSteps', 4) or goal.get('modelFailures')
            or any(goal.get('permissions', {}).get(k) for k in ('execute', 'repair'))):
        return False
    if not followup.get('reviewAgendaId'):
        return False
    previous_review = get(followup['reviewAgendaId'])
    experiment = previous_review.get('businessExperiment') or {}
    if (not experiment.get('id') or any(previous_review.get(k) or goal.get(k) for k in
            ('manualStop', 'cancelRequested')) or previous_review.get('status') == 'suspended'):
        return False
    from common import llm_usage
    try:
        source, _ = crew._measurement_source(crew.measurement_evidence_name(followup['key']))
        # Validate actual reachability through the same registered reader used by the employee.
        proof = crew.tool_call(goal, 'evidence', {'name': crew.measurement_evidence_name(followup['key'])})
        if not proof.get('available') or not proof.get('sha256'):
            return False
        _check_review_budget(experiment, previous_review['id'])
    except llm_usage.UsageBudgetExceeded as exc:
        _hold_review_budget(followup, experiment, str(exc), now, previous_review['id'])
        return False
    except (OSError, ValueError, TypeError):
        return False
    capability = 'measurement-json-v1:' + str(source.resolve())
    with locked(ROWS):
        state = load(STATE); item = state.get('unresolvedWork', {}).get(followup['key'])
        if (not item or item.get('reviewGoalId') != goal['id'] or len(item.get('reviewHistory', [])) >= 2
                or item.get('sourceReviewCapability') == capability):
            return False
        item.setdefault('reviewHistory', []).append({**{k: item.get(k) for k in
            ('reviewGoalId', 'reviewAgendaId', 'reviewOutcome', 'evidenceFingerprint')},
            'reason': 'registered_scoped_source_became_available', 'archivedAt': now})
        item.update(sourceReviewCapability=capability, reviewBudgetAgendaId=previous_review['id'],
                    reviewExperiment=experiment, nextAction='await_budgeted_scoped_source_review')
        for key in ('reviewGoalId', 'reviewAgendaId', 'reviewOutcome'):
            item.pop(key, None)
        write(STATE, state)
    return True


def _preload_scoped_review(goal_id, key, crew):
    try:
        result = crew.preload_measurement_review(goal_id, key)
        if result.get('preloaded'):
            with locked(ROWS):
                state = load(STATE); item = state.get('unresolvedWork', {}).get(key)
                if item and not item.get('sourceFileSha256'):
                    item.update(sourceFileSha256=result['sha256'], reviewSourceRef=result['source'])
                    write(STATE, state)
        return result
    except (OSError, ValueError, TypeError) as exc:
        with locked(ROWS):
            state = load(STATE); item = state.get('unresolvedWork', {}).get(key)
            if item:
                item.update(sourceReadHold=str(exc), nextAction='establish_registered_scoped_source_access')
                write(STATE, state)
        return {'preloaded': False, 'reason': str(exc)}


def dispatch_evidence_review_once(now=None):
    """Assign one bounded source review; model prose never certifies business acceptance."""
    now = time.time() if now is None else now
    from common import llm_usage
    from agents import crew_reasoning as crew
    state = load(STATE)
    pending = sorted(state.get('unresolvedWork', {}).values(), key=lambda f: (f.get('dueAt') or 0, f['key']))
    for followup in pending:
        measurement_proof = None
        if followup.get('status') == 'resolved' or (followup.get('dueAt') or 0) > now:
            continue
        original = get(followup['agendaId']) if followup.get('agendaId') else {}
        if followup.get('reviewGoalId'):
            goal = load(crew.goal_path(followup['reviewGoalId']))
            measurement = not original and followup['key'].startswith('measurement:')
            reads = _scoped_review_reads(followup, original, goal, crew)
            if goal.get('status') not in ('answered', 'blocked') and (not measurement or reads):
                continue
            with locked(ROWS):
                saved = load(STATE); item = saved.get('unresolvedWork', {}).get(followup['key'])
                if item:
                    status = 'reviewed_unresolved' if reads else ('scoped_source_review_missing' if measurement else 'missing_source_evidence')
                    previous = item.get('reviewOutcome')
                    if previous and previous.get('status') == 'reviewed_unresolved' and not reads:
                        item.setdefault('reviewOutcomeCorrections', []).append({'previous': previous, 'correctedAt': now,
                            'reason': status})
                    item['reviewOutcome'] = {'status': status,
                        'source': str(crew.goal_path(followup['reviewGoalId'])), 'answer': goal.get('answer'),
                        'evidenceHashes': [o['result']['sha256'] for o in reads],
                        'sourceReads': [_review_source_coverage(o) for o in reads],
                        'originalEvidenceHash': item.get('originalEvidenceHash'), 'businessOutcomeVerified': False}
                    item['nextAction'] = 'read_exact_scoped_source' if measurement and not reads else 'obtain_missing_acceptance_evidence'
                    current_hash = hashlib.sha256(json.dumps(original.get('verification') or original.get('auxiliaryResult') or {},
                        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    if (original and current_hash != item.get('originalEvidenceHash')
                            and task_outcome(original)['status'] == 'completed'):
                        _retain_outcome(original, saved, task_outcome(original)); _save(original)
                    write(STATE, saved)
            if measurement and not reads:
                review = get(followup.get('reviewAgendaId')) if followup.get('reviewAgendaId') else {}
                experiment = review.get('businessExperiment') or followup.get('reviewExperiment') or {}
                try:
                    _check_review_budget(experiment, review.get('id'))
                except llm_usage.UsageBudgetExceeded as exc:
                    _hold_review_budget(followup, experiment, str(exc), now, review.get('id'))
                    continue
                _preload_scoped_review(followup['reviewGoalId'], followup['key'], crew)
                _queue_measurement_scope_correction(followup, goal, crew, now)
            continue  # No new model budget or original-operation retry after a review.
        if original.get('manualStop') or original.get('cancelRequested') or original.get('status') == 'suspended':
            continue
        if original and not (original.get('businessExperiment') or {}).get('id'):
            # A fresh review agenda must never reset a legacy per-agenda call allowance.
            with locked(ROWS):
                saved = load(STATE)
                item = saved.get('unresolvedWork', {}).get(followup['key'])
                if item:
                    item['nextAction'] = 'host_review_required_missing_shared_budget'
                    write(STATE, saved)
            continue
        if not original and followup['key'].startswith('measurement:'):
            try:
                measurement_proof = crew.read_evidence({'name': crew.measurement_evidence_name(followup['key'])})
            except (OSError, ValueError, TypeError) as exc:
                with locked(ROWS):
                    saved = load(STATE); item = saved.get('unresolvedWork', {}).get(followup['key'])
                    if item:
                        item.update(sourceReadHold=str(exc), nextAction='establish_registered_scoped_source_access')
                        write(STATE, saved)
                continue
        project = original.get('project') or 'collections'
        owner = followup.get('owner') or 'trace'
        if owner not in ('jarvis', 'publi', 'trace', 'patch', 'doctor', 'radar'):
            continue
        experiment = original.get('businessExperiment') or followup.get('reviewExperiment') or state.get('activeExperiment')
        budget_agenda_id = original.get('id') or followup.get('reviewBudgetAgendaId')
        try:
            _check_review_budget(experiment, budget_agenda_id)
        except llm_usage.UsageBudgetExceeded as exc:
            _hold_review_budget(followup, experiment, str(exc), now, budget_agenda_id)
            continue
        request_id = 'evidence-review:' + hashlib.sha256(
            (followup['key'] + ':' + str(followup.get('evidenceFingerprint', 'original'))
             + (':' + followup['sourceReviewCapability'] if followup.get('sourceReviewCapability') else '')).encode()).hexdigest()
        original_hash = (measurement_proof['sha256'] if measurement_proof else
            hashlib.sha256(json.dumps(original.get('verification') or original.get('auxiliaryResult') or {},
                sort_keys=True, ensure_ascii=False).encode()).hexdigest())
        identity = propose('goal', request_id, title='미해결 원천 근거 검토 · ' + owner, project=project,
            source={'assignedRole': owner, 'evidenceReview': True,
                    'originalWorkRefs': {'agendaId': original.get('id'), 'followupKey': followup['key']},
                    'reviewAcceptance': followup.get('acceptance'), 'originalEvidenceHash': original_hash},
            completion='원래 요청 범위의 원천 증거와 해시를 대조하고 미확인 항목을 보고', inherit=False)
        if not identity:
            return False
        with locked(ROWS):
            review = get(identity)
            if experiment:
                review['businessExperiment'] = experiment
            _save(review)
        question = ('읽기 전용 원천 근거 검토. 실제 evidence 도구로 원래 안건과 관련 원천을 읽고 '
                    '각 수용 조건의 충족 여부와 정확한 출처·해시·미확인 이유를 보고하라. '
                    '상태 조회나 답변 작성은 사실 검증 완료가 아니다. 쓰기·패치·제출·재시도 금지. '
                    '근거 접근 권한 또는 기능이 없으면 담당자와 필요한 지원을 명시하라. '
                    + json.dumps({'originalAgendaId': original.get('id'), 'originalEvidenceHash': original_hash,
                        'sourceRef': followup.get('sourceRef') or (str(path(original['id'])) if original else None),
                        'evidenceName': 'agenda:' + original['id'] if original else crew.measurement_evidence_name(followup['key']),
                        'target': followup.get('target') or original.get('source', {}).get('targetUrl'),
                        'acceptance': followup.get('acceptance'), 'directive': original.get('source', {}).get('directive')}, ensure_ascii=False))
        goal = crew.reason_request(request_id, question, execute=False, repair=False, steps=0, max_steps=4,
                                   lead=owner, origin='evidence-review', projects=[project], agenda_id=identity)
        with locked(ROWS):
            review = get(identity); review['controllerGoalId'] = goal['id']; _save(review)
            saved = load(STATE); item = saved.get('unresolvedWork', {}).get(followup['key'])
            if item:
                item.update(reviewGoalId=goal['id'], reviewAgendaId=identity, reviewAssignedAt=now,
                            originalEvidenceHash=original_hash, nextAction='await_scoped_source_review')
                if item.get('reviewBudgetHold'):
                    item.setdefault('reviewBudgetHoldHistory', []).append({**item.pop('reviewBudgetHold'), 'clearedAt': now})
                    item['blocker'] = item.get('reason')
                if measurement_proof:
                    item.update(sourceFileSha256=measurement_proof['sha256'],
                                reviewSourceRef=measurement_proof['source'], sourceReadHold=None)
                write(STATE, saved)
        if not original and followup['key'].startswith('measurement:'):
            _preload_scoped_review(goal['id'], followup['key'], crew)
        return True
    return False


def executive_health_check(company, now=None):
    """Cheap current-evidence decisions run even while an experiment is observing."""
    now = time.time() if now is None else now
    from server.growth import measurement_followups
    followups = measurement_followups(DATA, now=now)
    projects = {p['id']: p for p in company.get('projects', []) if p.get('id')}
    decisions = []
    with locked(ROWS):
        state = load(STATE)
        for identity in dict.fromkeys([*state.get('pending', []), *active_ids(state)]):
            row = get(identity)
            if not row:
                continue
            project = projects.get(row.get('project')) or {}
            source = project.get('source') or {}
            fresh = source.get('fresh') is True
            if row.get('auxiliaryResult') or row.get('outcome'):
                outcome = task_outcome(row)
                _retain_outcome(row, state, outcome)
            judgment = 'review_unresolved' if row.get('blocker') else 'continue_owned_work' if fresh else 'refresh_evidence'
            chain = {'agendaId': identity, 'judgment': judgment,
                'why': row.get('blocker') or ('current_project_evidence' if fresh else 'stale_or_missing_project_evidence'),
                'evidence': {'source': source, 'checkedAt': now, 'status': project.get('status')},
                'responsibleCrew': row.get('responsibleCrew') or (row.get('source') or {}).get('assignedRole') or 'jarvis',
                'acceptance': acceptance_requirements(row), 'verifiedOutcome': (row.get('outcome') or {}).get('status') == 'completed'}
            row['priorityAssessment'] = chain
            # Preserve user priorities. Review urgency does not authorize execution/retry.
            row['reviewPriority'] = 0 if row.get('blocker') else 1 if not fresh else 2
            _save(row)
            decisions.append(chain)
        for followup in followups:
            key = 'measurement:' + followup['key']
            previous = state.setdefault('unresolvedWork', {}).get(key) or {}
            def material(value):
                if isinstance(value, dict):
                    return {k: material(v) for k, v in value.items() if not k.endswith(('At', 'Sha256'))
                            and k not in ('dueAt', 'runId', 'collected_at', 'checked_at', 'sourceRef', 'sourceFileSha256')}
                if isinstance(value, list):
                    return [material(v) for v in value]
                return value
            fingerprint = hashlib.sha256(json.dumps(material(followup), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if (previous.get('evidenceFingerprint') not in (None, fingerprint) and previous.get('reviewOutcome')
                    and len(previous.get('reviewHistory', [])) < 2):
                previous.setdefault('reviewHistory', []).append({k: previous.get(k) for k in
                    ('reviewGoalId', 'reviewAgendaId', 'reviewOutcome', 'evidenceFingerprint')})
                for field in ('reviewGoalId', 'reviewAgendaId', 'reviewOutcome'):
                    previous.pop(field, None)
            state['unresolvedWork'][key] = {**previous, **followup, 'key': key,
                'blocker': None if followup.get('status') == 'resolved' else followup.get('reason'),
                'nextAction': None if followup.get('status') == 'resolved' else 'collect_or_review_scoped_evidence',
                'evidenceFingerprint': fingerprint, 'createdAt': previous.get('createdAt', now), 'autoRetry': False}
        state['lastExecutiveHealthAt'] = now
        state['executiveHealth'] = {'checkedAt': now, 'decisions': decisions, 'measurementFollowups': len(followups),
                                    'modelCalls': 0, 'experimentPreserved': True}
        write(STATE, state)
    dispatch_evidence_review_once(now)
    return True


def company_executive_check_once(force=False):
    """Reverse-Funnel Strategy Brain (@jarvis): calculates gap to $100/day, audits all 6 channels live, pivots lanes, and proactively calls ask_ceo."""
    now = time.time()
    state = load(STATE)
    if not force and now - state.get('lastExecutiveHealthAt', 0) < 300:
        return False
    prune_stale_runtime_data()
    try:
        wt_path = DATA / 'radar/daily_winning_topics.json'
        if not wt_path.exists() or (now - wt_path.stat().st_mtime > 14400):
            from server.radar_scout import build_daily_winning_topics
            build_daily_winning_topics()
    except Exception:
        pass
    _top_up_channel_lanes()
    state = load(STATE)
    pending_ids = list(state.get('pending', []))
    try:
        from agents.crew_reasoning import overview
        from common.llm_client import generate_json
        from common.crew_chat_bridge import emit_work_event, emit_ceo_proposal
        company = overview()
        health_checked = executive_health_check(company, now)
        try:
            from common.repair_workflow import agenda_recovery_blocker
            with locked(ROWS):
                st_heal = load(STATE)
                for arow in active_rows(st_heal):
                    if arow.get('kind') == 'conference' and arow.get('status') in ('blocked', 'recovering') and not running(arow) and not agenda_recovery_blocker(arow):
                        conf_id = (arow.get('source') or {}).get('conferenceId')
                        cpath = ROWS.parent / f'{conf_id}.json' if conf_id else None
                        crow = load(cpath) if cpath else {}
                        if (crow and crow.get('status') == 'failed' and crow.get('submissionStarted') is not True
                                and crow.get('attempts', 1) < 3 and now >= crow.get('retryAt', 0)):
                            crow.update(status='queued', attempts=crow.get('attempts', 1) + 1, retryAt=0, requestedAt=now)
                            for ck in ('errorType', 'failureReason', 'failureDiagnostic', 'failureReport', 'interruptedAt', 'completedAt'):
                                crow.pop(ck, None)
                            write(cpath, crow)
                            arow.update(status='executing', controllerFailures=0, nextCheckAt=0)
                            for hk in ('blocker', 'recoveryGoalId', 'controllerGoalId', 'recoveryWatch', 'recoveryPreparation'):
                                arow.pop(hk, None)
                            if isinstance(arow.get('events'), dict):
                                arow['events'].pop('blocked', None)
                            _save(arow)
        except Exception:
            pass
        live_diag = _build_live_executive_diagnostics()
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
        valid_pending = []
        pruned = []
        for pid in pending_ids:
            prow = get(pid)
            if not prow or prow.get('status') != 'queued':
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
        previous_experiment = state.get('activeExperiment') or {}
        if (previous_experiment.get('id') and previous_experiment.get('status') in ('active', 'inconclusive')
                and not previous_experiment.get('observationClosed')):
            if not previous_experiment.get('interventionReceipt'):
                return health_checked
            prior_capture = previous_experiment.get('finalObservation')
            capture_experiment_observation(previous_experiment, business, now=now)
            if previous_experiment.get('finalObservation') != prior_capture:
                if not _merge_experiment_observation(previous_experiment['id'], finalObservation=previous_experiment['finalObservation']):
                    return False
            today = datetime.now(timezone.utc).date().isoformat()
            if today < previous_experiment.get('measurementDate', '9999'):
                return health_checked
            evaluation = evaluate_business_experiment(previous_experiment, business, now=now)
            closed = experiment_observation_closed(previous_experiment, evaluation, now)
            changes = {'status': evaluation['status'], 'evaluation': evaluation, 'evaluatedAt': now,
                       'observationClosed': closed, 'followupNeeded': closed and evaluation['status'] != 'observed_gain'}
            previous_experiment.update(changes)
            if not _merge_experiment_observation(previous_experiment['id'], **changes):
                return False
            # Missing reports get bounded collection grace; no new work or budget reset.
            if not closed:
                return health_checked
        fp_src = json.dumps({
            'projects': [(p['id'], p['status'], p['recoverableCount']) for p in projects_summary],
            'pending': [r['id'] for r in valid_pending],
            'observedValues': [{k: r.get(k) for k in ('url','source','start','end','complete','pageViews','sessions','estimatedRevenue','currency')}
                               for r in business.get('pageObservations', [])],
            'revenueValues': [{k: r.get(k) for k in ('source','date','amount','currency','status')}
                              for r in business.get('priorDayRevenue', [])],
            'funnelStatus': reverse_funnel.get('status'),
            'experimentLifecycle': {k: previous_experiment.get(k) for k in ('id','status','observationClosed','observationEnd')},
        }, sort_keys=True)
        fp = hashlib.sha256(fp_src.encode('utf-8')).hexdigest()
        if not force and state.get('lastExecutiveFingerprint') == fp:
            return False
        candidates = [{'id': r['id'], 'title': r.get('title', '')[:120], 'project': r.get('project'), 'kind': r.get('kind'), 'priority': r.get('priority', 10)} for r in valid_pending[:10]]
        active_blockers = []
        for arow in active_rows():
            if arow.get('status') in ('blocked', 'recovering'):
                cid = (arow.get('source') or {}).get('conferenceId')
                crow = load(ROWS.parent / f'{cid}.json') if cid else {}
                diag = crow.get('failureDiagnostic') or {}
                active_blockers.append({
                    'id': arow['id'],
                    'title': arow.get('title'),
                    'project': arow.get('project'),
                    'status': arow.get('status'),
                    'blocker': arow.get('blocker'),
                    'errorType': diag.get('errorType') or crow.get('errorType'),
                    'errorMessage': diag.get('errorMessage'),
                    'sourceLocation': diag.get('sourceLocation'),
                })
        schema = {
            'type': 'object',
            'properties': {
                'briefing': {'type': 'string', 'minLength': 1, 'maxLength': 600},
                'topAgendaId': {'type': 'string'},
                'dropAgendaIds': {'type': 'array', 'items': {'type': 'string'}},
                'healOrRetryAgendaIds': {'type': 'array', 'items': {'type': 'string'}},
                'focusChannels': {
                    'type': 'array',
                    'items': {'type': 'string', 'enum': ['cf_blog', 'threads', 'naver_kin', 'naver_blog', 'brunch', 'legacy_remodel']},
                    'minItems': 1,
                },
                'autonomousWorkOrders': {
                    'type': 'array',
                    'minItems': 0,
                    'maxItems': 3,
                    'items': {
                        'type': 'object',
                        'properties': {
                            'role': {'type': 'string', 'enum': ['doctor', 'patch', 'trace', 'radar', 'publi']},
                            'workType': {'type': 'string', 'enum': ['cro_widget_retrofit', 'indexnow_unindexed_push',
                                'content_audit_patrol', 'radar_high_cpc_scout', 'brunch_daily_publish']},
                            'targetDomain': {'type': 'string'},
                            'rationale': {'type': 'string', 'minLength': 1, 'maxLength': 300},
                            'additionalRequirements': {'type': 'array', 'maxItems': 8, 'items': {'type': 'string'}},
                        },
                        'required': ['role', 'workType', 'targetDomain', 'rationale', 'additionalRequirements'],
                        'additionalProperties': False,
                    },
                },
                'experiment': {'type': 'object', 'properties': {
                    'hypothesis': {'type': 'string'}, 'targetUrl': {'type': 'string'},
                    'measurementDate': {'type': 'string'}, 'evidenceConfidence': {'type': 'string', 'enum': ['low', 'medium', 'high']},
                    'maxModelCalls': {'type': 'integer', 'minimum': 1, 'maximum': 40},
                    'primaryMetric': {'type': 'string', 'enum': ['pageViews', 'sessions', 'estimatedRevenue']},
                    'measurementWindowDays': {'type': 'integer', 'enum': [7, 14, 28]},
                    'minimumSample': {'type': 'integer', 'minimum': 1, 'maximum': 100000},
                    'successMetric': {'type': 'string'}, 'stopCondition': {'type': 'string'}},
                    'required': ['hypothesis', 'targetUrl', 'measurementDate', 'evidenceConfidence', 'maxModelCalls', 'successMetric', 'stopCondition', 'primaryMetric', 'measurementWindowDays', 'minimumSample'], 'additionalProperties': False},
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
            'required': ['briefing', 'topAgendaId', 'dropAgendaIds', 'healOrRetryAgendaIds', 'focusChannels', 'autonomousWorkOrders', 'experiment', 'ceoProposal'],
            'additionalProperties': False,
        }
        prompt = (
            '당신은 하루 $100 수익을 책임지는 자율 에이전트 조직의 총괄 디렉터(@jarvis)다. 대표님이 일일이 지적하기 전에 전사 모든 채널의 가동 상태·정체 여부·콘텐츠 품질(자청 4대 결핍·썸네일)·유입 전환율을 스스로 감시하고 결단하라.\n'
            '⚠️ [언어 절대 규칙] 모든 응답 텍스트 필드는 반드시 100% 자연스러운 한국어(Korean)로만 작성하라.\n'
            + __import__('common.asset_map', fromlist=['get_asset_map_summary']).get_asset_map_summary() + '\n'
            '[역산(Reverse-Funnel) 수치 진단]\n'
            + json.dumps(reverse_funnel, ensure_ascii=False) + '\n'
            '[전 채널 실시간 실측 가동·품질·색인 진단팩 (liveCompanyDiagnostics)]\n'
            + json.dumps(live_diag, ensure_ascii=False) + '\n'
            '1) briefing: 수익·유입의 기간·통화·범위와 미측정을 구분하고 목표 $100과의 확인된 격차를 브리핑하라. 필요 PV는 reverseFunnel의 동일 범위 실측 RPM이 있을 때만 사용한다. 채널 진행 현황은 발행 할당량 달성도가 아닌 실제 관측과 병목으로 설명하라.\n'
            '2) focusChannels: 오늘 우선 가동할 핵심 유입·수익 채널 배열(cf_blog, threads, naver_kin, naver_blog, brunch, legacy_remodel 포함 가능)을 지정하라.\n'
            '3) autonomousWorkOrders: 작업이 필요할 때만 선택된 URL에 제안하라. cro_widget_retrofit은 기존 내용의 요약·표·내부 안내 정리와 저장·공개 HTML 검증, indexnow_unindexed_push는 지정 URL 제출 접수 검증만 실행한다. 나머지 세 workType은 Patch의 정확한 대상 기능 검토로 보류하며 자동 발행하지 않는다. rationale은 선택 이유이며 실행 지시가 아니다. 사실 검수·통계 조사 등 추가 요구는 반드시 additionalRequirements에 보존하라. 지원하지 않는 추가 요구가 있으면 실행 전에 보류한다.\n'
            '4) topAgendaId, dropAgendaIds & healOrRetryAgendaIds: 대기 안건(pendingAgendas) 중 실질 유입·수익 기여도가 가장 높은 최우선 안건 1개를 topAgendaId로 고르고, 불필요한 중복 티켓은 dropAgendaIds로 폐기하며, activeBlockers에 막힌 안건은 healOrRetryAgendaIds에 넣어 즉시 복구하라.\n'
            '5) experiment: pageObservations의 실제 targetUrl, 가설, primaryMetric(pageViews/sessions/estimatedRevenue), 기준선과 같은 measurementWindowDays(7/14/28), 사후 최소표본 minimumSample(PV), 공유 maxModelCalls(1~40), 성공 지표·중단 조건을 설정하라. 기준선 수치는 호스트가 연결한다. 초기 유입 관측과 수익 검증을 구분하고 효과를 보장하지 마라.\n'
            '6) ceoProposal (대표님께 역제안 · ask_ceo): 대표님의 결단/승인이 필요한 병목(예: 네이버 프리미엄콘텐츠 2단계 인증/심사 확인, 추가 계정/캠페인 승인, 수익 격차 돌파 작전 승인)을 선제적으로 정리해 보고하라.\n'
            + json.dumps({'reverseFunnel': reverse_funnel, 'liveCompanyDiagnostics': live_diag, 'projects': projects_summary, 'activeBlockers': active_blockers, 'pendingAgendas': candidates, 'businessEvidence': business}, ensure_ascii=False)
        )
        decision = generate_json(prompt, agent_slot='jarvis', response_schema=schema, timeout_seconds=120, memory_read_only=True, _skip_memory=True, crew_actor='jarvis', crew_actor_label='팀장', crew_stage='company-executive-check')
        focus_channels = decision.get('focusChannels') or []
        experiment = bind_business_experiment(decision.get('experiment'), business, focus_channels, now=now)
        experiment = activate_experiment_preview(experiment)
        drop_set = set(decision.get('dropAgendaIds') or []) - {decision.get('topAgendaId')}
        heal_set = set(decision.get('healOrRetryAgendaIds') or [])
        top_id = decision.get('topAgendaId')
        focus_channels = experiment['focusChannels']
        work_orders = decision.get('autonomousWorkOrders') or []
        dispatched_orders = []
        for order in work_orders[:3]:
            aid = _queue_autonomous_work_order(
                order.get('workType'),
                role=order.get('role') or 'doctor',
                target_domain=order.get('targetDomain') or '',
                directive=order.get('directive') or '',
                rationale=order.get('rationale') or '',
                additional_requirements=order.get('additionalRequirements') or [],
            )
            if aid:
                dispatched_orders.append(f"@{order.get('role')}: {order.get('rationale') or order.get('directive')}")
        with locked(ROWS):
            st = load(STATE)
            st.setdefault('schema', 'barolab-work-agenda-v1')
            st['enabled'] = True
            for arow in active_rows(st):
                if arow.get('kind') == 'conference' and arow.get('status') in ('blocked', 'recovering'):
                    heal_set.add(arow['id'])
            for hid in heal_set:
                hrow = get(hid)
                from common.repair_workflow import agenda_recovery_blocker
                if hrow and hrow.get('status') in ('blocked', 'recovering') and not running(hrow) and not agenda_recovery_blocker(hrow):
                    conf_id = (hrow.get('source') or {}).get('conferenceId')
                    cpath = ROWS.parent / f'{conf_id}.json' if conf_id else None
                    crow = load(cpath) if cpath else {}
                    if (hrow.get('kind') == 'conference' and crow and crow.get('status') == 'failed'
                            and crow.get('submissionStarted') is not True and crow.get('attempts', 1) < 2):
                        crow.update(status='queued', attempts=crow.get('attempts', 1) + 1, retryAt=0, requestedAt=now)
                        for ck in ('errorType', 'failureReason', 'failureDiagnostic', 'failureReport', 'interruptedAt', 'completedAt'):
                            crow.pop(ck, None)
                        write(cpath, crow)
                        hrow.update(status='executing', controllerFailures=0, nextCheckAt=0)
                        for hk in ('blocker', 'recoveryGoalId', 'controllerGoalId', 'recoveryWatch', 'recoveryPreparation'):
                            hrow.pop(hk, None)
                        if isinstance(hrow.get('events'), dict):
                            hrow['events'].pop('blocked', None)
                        _save(hrow)
                    elif hrow.get('status') == 'blocked' and hrow.get('resumeAuthorized') is True:
                        hrow.update(status='recovering', controllerFailures=0, nextCheckAt=0)
                        hrow.pop('recoveryGoalId', None)
                        _save(hrow)
            for drop_id in drop_set:
                if drop_id in st.get('pending', []):
                    drow = get(drop_id)
                    if drow and drow.get('kind') == 'conference' and not drow.get('verification', {}).get('verified'):
                        continue
                    if drow:
                        # Model advice cannot discard unresolved acceptance or owned submissions.
                        drow['executiveRecommendation'] = {'action': 'review_duplicate', 'at': now}
                        _save(drow)
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
            st['lastAutonomousWorkOrders'] = work_orders
            st['reverseFunnel'] = reverse_funnel
            st['focusChannels'] = focus_channels
            write(STATE, st)
        order_summary = (' | 즉시 하달 작업: ' + ' / '.join(dispatched_orders)) if dispatched_orders else ''
        emit_work_event(actor='jarvis', actor_label='팀장', task_id='executive-check:'+str(int(now)), phase='completed', stage='company-executive-check', output_kind='[역산 전략 총괄 점검] ' + decision.get('briefing', '') + order_summary)
        ceo_prop = decision.get('ceoProposal') or {}
        if (ceo_prop.get('shouldAskCeo') or reverse_funnel.get('status') == 'critical_gap') and (ceo_prop.get('title') or ceo_prop.get('proposal')):
            emit_ceo_proposal(
                actor='jarvis',
                title=ceo_prop.get('title') or '단순 발행 대기 중단 및 하루 $100 역산 외부유입 집중 작전 승인 요청',
                current_reality=ceo_prop.get('currentReality') or reverse_funnel['diagnosis'],
                proposal=ceo_prop.get('proposal') or decision.get('briefing', ''),
                required_approvals=ceo_prop.get('requiredApprovals') or ['고단가 타깃 집중 유입 작전 및 외부채널 브릿지 배포 승인'],
                expected_impact=ceo_prop.get('expectedImpact') or '선택된 대상의 유입·수익 변화 측정; 개선 효과는 미확인',
                urgency='high',
                request_key=_executive_proposal_key(experiment, focus_channels, ceo_prop),
            )
        return True
    except Exception:
        return False


def _step_single_agenda(row):
    if not row:
        return False
    if (row.get('source') or {}).get('executionContract') and (row.get('source') or {}).get('directive'):
        return False  # Typed work cannot execute while additional requested scope is unsupported.
    if row.get('switchRequest'):
        return switch_once(row)
    if row.get('status') in ('blocked', 'recovering'):
        from common.repair_workflow import agenda_recovery_blocker
        if agenda_recovery_blocker(row):
            return False
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
            if row['kind'] in ('cro_widget_retrofit', 'indexnow_unindexed_push', 'style', 'radar', 'audit', 'brunch_publish') and row['status'] in ('meeting', 'recovering', 'blocked'):
                if row.get('auxiliaryStartedAt'):
                    # Restarts and elapsed time never authorize replay of a possible external effect.
                    with locked(ROWS):
                        saved = get(row['id']); state = load(STATE)
                        outcome = task_outcome(saved)
                        if not saved.get('auxiliaryResult'):
                            outcome.update(status='held', blocker='external_effect_unknown', nextAction='verify_existing_external_receipt')
                        _retain_outcome(saved, state, outcome)
                        saved['status'] = 'blocked'; _save(saved); write(STATE, state)
                    return False
                with locked(ROWS):
                    row = get(row['id']); row['auxiliaryStartedAt'] = time.time(); _save(row)
                summary_text = short_title(row)
                with execution(row['project']):
                    if row['kind'] == 'cro_widget_retrofit':
                        from common.cf_tables import retrofit_cro_widgets_and_tables
                        dom = (row.get('source') or {}).get('domain') or ''
                        doms = [dom] if dom and '.' in dom else None
                        target_urls = [row['source']['targetUrl']] if row.get('source', {}).get('autonomousExperiment') else None
                        result = retrofit_cro_widgets_and_tables(limit_per_domain=2, domains=doms, target_urls=target_urls)
                        summary_text = f"CF 원고 수정 영수증 {result.get('updatedCount', 0)}건 관측; 사실 검수와 전체 수용 조건은 별도 확인"
                    elif row['kind'] == 'indexnow_unindexed_push':
                        from common.cf_tables import push_unindexed_cf_posts
                        dom = (row.get('source') or {}).get('domain') or ''
                        doms = [dom] if dom and '.' in dom else None
                        target_urls = [row['source']['targetUrl']] if row.get('source', {}).get('autonomousExperiment') else None
                        result = push_unindexed_cf_posts(limit_per_domain=4, domains=doms, target_urls=target_urls)
                        summary_text = f"색인 제출 접수 영수증 {result.get('pingedCount', 0)}건 관측; 실제 색인과 전체 조사 범위는 별도 확인"
                    elif row['kind'] == 'style':
                        from dashboard.agents.style_strategy import review_once
                        result = review_once()
                    elif row['kind'] == 'audit':
                        from server.content_auditor import run_patrol_batch
                        dom = (row.get('source') or {}).get('domain') or 'must-good.com'
                        result = run_patrol_batch(2, dom, False)
                        records = result.get('results', [])
                        summary_text = f"{dom} 감사 결과 {len(records)}건 반환; 전체 수용 조건은 별도 확인"
                    elif row['kind'] == 'brunch_publish':
                        from brunch_posting.posting import process_brunch_autonomy_once
                        result = process_brunch_autonomy_once(cdp_port=9450)
                        summary_text = f"브런치 원천 상태: {result.get('status', result.get('state', 'unknown'))}"
                    else:
                        from server.radar_scout import SCOUT, fetch_blokey_golden
                        blokey_res = fetch_blokey_golden(cdp_port=9440)
                        raw_slot = row['source'].get('slot')
                        valid_slot = raw_slot if raw_slot in (9, 14, 20, '09:00', '14:00', '20:00') else None
                        scout_res = SCOUT.trigger(slot=valid_slot, background=False)
                        result = {'status': 'completed', 'blokey': blokey_res, 'blokeyCount': len(blokey_res.get('items') or []),
                                  'pairedSets': len(blokey_res.get('pairedBridgeSets') or []), 'scout': scout_res,
                                  'candidates': blokey_res.get('items') or scout_res.get('candidates') or []}
                        summary_text = f"블로키 후보 {len(blokey_res.get('items') or [])}건 반환; 원천 수집 성공과 배정은 별도 확인"
                with locked(ROWS):
                    row = get(row['id']); row['auxiliaryResult'] = result; _save(row)
                verified(row['id'], {'verified': True, 'source': str(path(row['id'])), 'scope': row['completionCriteria'],
                         'summary': summary_text, 'resultStatus': result.get('status'), 'result': result, 'publicationVerified': False})
                return True
            if row['status'] in ('blocked','recovering') and recovery_watch(row):
                return True
            if row['kind']=='conference' and row['status'] in ('queued','meeting','executing','recovering') and not running(row):
                from common.conference_dispatch import QUEUE, record_conference_result, process_once as dispatch_conference_once
                receipt=load(QUEUE/(row['source']['conferenceId']+'.json'))
                if receipt.get('status') == 'queued':
                    return dispatch_conference_once()
                if row['status'] in ('meeting','executing') and receipt.get('status') in ('completed','failed','unknown'):
                    record_conference_result(receipt,receipt.get('preparation'))
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
                cid = str((row.get('workTarget') or row.get('source',{})).get('conferenceId',''))
                crow = load(ROWS.parent / f'{cid}.json') if cid else {}
                diag = crow.get('failureDiagnostic') or {}
                diag_summary = f" [원천 에러 진단: {diag.get('sourceLocation')} | {diag.get('errorType')}: {diag.get('errorMessage')}]" if diag else ''
                goal = reason_request('agenda-recovery:'+row['id']+':'+str(int(time.time())),
                    '현재 안건 '+row['title']+'의 실패를 같은 안건에서 즉시 자가 치유(Self-Healing)·복구·검증하라.' + diag_summary + ' '
                    '1) 원천 에러와 기존 영수증을 읽고 결정론적 진단과 검토용 수정안을 제안하라. 모델 출력이나 후보 패치를 자동 적용하지 마라. '
                    '2) 수동 중단·인증·설정·외부 효과 불확실성은 보류하고 담당자와 다음 검증 조건을 남겨라. 재실행은 호스트 안전 게이트와 명시적 권한이 있을 때만 가능하다. '
                    '안건 ID: '+row['id']+' 원인: '+row.get('blocker','')+' 원래 실행 ID: '+cid,
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
        def _pending_sort_key(aid):
            r = get(aid) or {}
            args = (r.get('workTarget') or r.get('source') or {}).get('arguments') or {}
            act = str(args.get('action') or '')
            slot = str(args.get('slot') or '00:00')
            return (0 if r.get('kind') == 'conference' else 1, 0 if act == 'cf' else 1, r.get('priority', 10), slot, r.get('createdAt', 0))
        for identity in sorted(list(load(STATE).get('pending', [])), key=_pending_sort_key):
            admit(identity)
        rows = active_rows()
        if not rows:
            return False
        progressed = False
        for r in rows:
            if _step_single_agenda(r):
                progressed = True
        return progressed
