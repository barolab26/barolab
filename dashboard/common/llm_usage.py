"""Aggregate provider-reported usage only; never store prompts or credentials."""
import datetime as dt
from pathlib import Path

from common.collection_observability import locked, write

ROOT=Path(__file__).resolve().parents[2]
KST=dt.timezone(dt.timedelta(hours=9))


def record_codex_usage(events, model, root=None, now=None):
    import json
    now=now or dt.datetime.now(KST)
    day=now.astimezone(KST).date().isoformat()
    reports=[e.get('usage') for e in events if e.get('type')=='turn.completed']
    reports=[u for u in reports if isinstance(u,dict) and
             all(type(u.get(k)) is int and u[k]>=0 for k in ('input_tokens','output_tokens'))]
    if not reports:return
    path=Path(root or ROOT)/'dashboard/data/llm-usage.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    with locked(path.with_suffix('.lock')):
        try:state=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):state={}
        if state.get('date')!=day:state={'date':day,'totalTokens':0,'byModel':{},'calls':0}
        count=sum(u['input_tokens']+u['output_tokens'] for u in reports)
        state['totalTokens']+=count
        state['byModel'][model]=state['byModel'].get(model,0)+count
        state['calls']+=len(reports)
        state.update(schema='barolab-llm-usage-v1',scope='codex_cli_reported_usage',
                     checkedAt=now.isoformat(),coverageStartedAt=state.get('coverageStartedAt') or now.isoformat())
        write(path,state)

# One logical call is counted once across llm_client -> codex_cli nesting.
import contextvars
from collections.abc import Mapping
import functools
import json
import math
import time
import uuid
import re
from contextlib import contextmanager

# Reported tokens are resource usage, not a dollar cost. Limits apply before the next call.
DEFAULT_BUDGET = {'dailyTokens': 100000000, 'dailyCalls': 5000,
                  'agendaTokens': 5000000, 'agendaCalls': 200, 'agendaModelSeconds': 3600}


class UsageBudgetExceeded(RuntimeError):
    pass


class RouteCoolingDown(RuntimeError):
    pass


def budget_policy(root=ROOT):
    from common.collection_observability import load
    configured = load(Path(root) / 'dashboard/data/llm-settings.json').get('resourceBudget', {})
    return {k: configured.get(k) if type(configured.get(k)) is int and configured[k] > 0 else v
            for k, v in DEFAULT_BUDGET.items()}


def check_budget(state, call, policy, root=ROOT):
    models = list(state.get('byModel', {}).values())
    active = list(state.get('active', {}).values())
    if sum(m.get('inputTokens', 0) + m.get('outputTokens', 0) for m in models) >= policy['dailyTokens']:
        raise UsageBudgetExceeded('daily_token_budget_exhausted')
    if sum(m.get('calls', 0) for m in models) + len(active) >= policy['dailyCalls']:
        raise UsageBudgetExceeded('daily_call_budget_exhausted')
    agenda = call.get('agendaId')
    if not agenda:
        return
    row = state.get('byAgenda', {}).get(agenda, {})
    from common.collection_observability import load
    experiment = load(Path(root) / 'dashboard/data/publication-conferences/operations' / (agenda + '.json')).get('businessExperiment', {})
    planned_calls = experiment.get('maxModelCalls')
    call_limit = max(policy['agendaCalls'], planned_calls) if type(planned_calls) is int and planned_calls > 0 else policy['agendaCalls']
    if row.get('inputTokens', 0) + row.get('outputTokens', 0) >= policy['agendaTokens']:
        raise UsageBudgetExceeded('agenda_token_budget_exhausted')
    if row.get('modelCalls', 0) + sum(a.get('agendaId') == agenda for a in active) >= call_limit:
        raise UsageBudgetExceeded('agenda_call_budget_exhausted')
    if row.get('modelLatencyMs', 0) >= policy['agendaModelSeconds'] * 1000:
        raise UsageBudgetExceeded('agenda_time_budget_exhausted')


def resource_summary(root=ROOT, now=None):
    from common.collection_observability import load
    state = load(Path(root) / 'dashboard/data/llm_usage_ledger.json')
    day = (now or dt.datetime.now(KST)).astimezone(KST).date().isoformat()
    models = list(state.get('byModel', {}).values()) if state.get('date') == day else []
    agendas = sorted(state.get('byAgenda', {}).items(), key=lambda p: p[1].get('checkedAt', ''), reverse=True)[:8]
    recent = []
    for identity, row in agendas:
        work = load(Path(root) / 'dashboard/data/publication-conferences/operations' / (identity + '.json'))
        recent.append({'agendaId': identity, **{f: row.get(f) for f in ('modelCalls', 'modelErrors', 'modelLatencyMs', 'inputTokens', 'outputTokens', 'usageReportedCalls')},
                       'project': work.get('project'), 'status': work.get('status'),
                       'verifiedCompletion': work.get('verification', {}).get('verified') is True,
                       'experiment': work.get('businessExperiment')})
    return {'date': day, 'reportedTokens': sum(m.get('inputTokens', 0) + m.get('outputTokens', 0) for m in models),
            'modelCalls': sum(m.get('calls', 0) for m in models), 'limits': budget_policy(root),
            'actualCostUsd': None, 'costStatus': 'billing_not_connected',
            'recentAgendas': recent,
            'routeHealth': state.get('routeHealth', {}), 'lastBudgetBlock': state.get('lastBudgetBlock')}


@contextmanager
def route_attempt(provider, model, *, root=ROOT, now=None):
    """Three consecutive route failures open a shared, expiring circuit; one recovery probe."""
    from common.collection_observability import load
    path = Path(root) / 'dashboard/data/llm_usage_ledger.json'
    key = provider + ':' + model
    clock = now or time.time
    with locked(path.with_suffix('.lock')):
        state = load(path)
        route = state.setdefault('routeHealth', {}).setdefault(key, {})
        if route.get('retryAt', 0) > clock() or route.get('probeUntil', 0) > clock():
            raise RouteCoolingDown('model_route_cooling_down: ' + key)
        if route.get('failures', 0) >= 3:
            route['probeUntil'] = clock() + 600
        write(path, state)
    error = None
    try:
        yield
    except Exception as exc:
        error = exc
        raise
    finally:
        with locked(path.with_suffix('.lock')):
            state = load(path)
            route = state.setdefault('routeHealth', {}).setdefault(key, {})
            if error is None:
                route.update(failures=0, retryAt=0, probeUntil=0)
            else:
                failures = route.get('failures', 0) + 1
                route.update(failures=failures, probeUntil=0, errorType=type(error).__name__,
                             retryAt=clock() + min(3600, 300 * 2 ** min(failures - 3, 4)) if failures >= 3 else 0)
            route['checkedAt'] = clock()
            write(path, state)

_CURRENT = contextvars.ContextVar('llm_usage_call', default=None)
RATE_HEADERS = frozenset('x-ratelimit-limit-requests x-ratelimit-limit-tokens x-ratelimit-remaining-requests x-ratelimit-remaining-tokens x-ratelimit-reset-requests x-ratelimit-reset-tokens retry-after'.split())


def agenda_identity():
    from common import work_agenda
    value = work_agenda.current()
    if not value:
        return None
    row = work_agenda.require()
    identity = row.get('id')
    return identity if isinstance(identity, str) and re.fullmatch(r'[a-f0-9]{64}', identity) else None


def _agenda_metrics(state, call, phase, now):
    identity = call.get('agendaId')
    if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{64}', identity):
        return
    groups = state.setdefault('byAgenda', {})
    row = groups.setdefault(identity, {'coverageStartedAt':now.isoformat(), 'modelCalls':0,
        'modelErrors':0, 'modelLatencyMs':0, 'routes':{}, 'toolRoundTrips':0,
        'toolFailures':0, 'uiActions':0, 'uiFailures':0})
    if call['id'] in row.get('recentIds', []):
        return
    if phase.startswith('action_'):
        tool = call.get('action') == 'tool'
        row['toolRoundTrips' if tool else 'uiActions'] += 1
        if phase == 'action_failed':
            row['toolFailures' if tool else 'uiFailures'] += 1
    elif phase != 'started':
        row['modelCalls'] += 1
        row['modelErrors'] += phase != 'completed'
        row['modelLatencyMs'] += call['latencyMs']
        for key in ('inputTokens', 'outputTokens'):
            row[key] = row.get(key, 0) + call.get(key, 0)
        row['usageReportedCalls'] = row.get('usageReportedCalls', 0) + int(call.get('usageReports', 0) > 0)
        route = '|'.join(str(call.get(k) or 'unknown') for k in ('provider','model','reasoningEffort'))
        row['routes'][route] = row['routes'].get(route, 0) + 1
    else:
        return
    row['recentIds'] = (row.get('recentIds', []) + [call['id']])[-256:]
    row['checkedAt'] = now.isoformat()
    state['byAgenda'] = dict(list(groups.items())[-128:])


def record_action(identity, action, phase):
    try:
        agenda = agenda_identity()
        if agenda:
            record_call({'id':identity, 'agendaId':agenda, 'action':action}, 'action_'+phase)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        pass


def report_response(data=None, headers=None, status=None, model=None, events=None):
    call = _CURRENT.get()
    if call is None:return
    if model:call['model'] = str(model)[:120]
    if status is not None:call['httpStatus'] = status
    call['rateLimitHeaders'].update({str(k).lower():str(v)[:80] for k,v in (headers if isinstance(headers,Mapping) else {}).items()
                                    if str(k).lower() in RATE_HEADERS and
                                    all(c.isdigit() or c in '.smhd, -' for c in str(v))})
    usages=[]
    if events is not None:
        usages=[e.get('usage') for e in events if e.get('type')=='turn.completed']
    elif isinstance(data,dict):
        raw=data.get('usageMetadata') or data.get('usage') or {}
        usages=[{'input_tokens':raw.get('input_tokens',raw.get('prompt_tokens',raw.get('promptTokenCount'))),
                 'output_tokens':raw.get('output_tokens',raw.get('completion_tokens',
                     raw.get('candidatesTokenCount',0)+raw.get('thoughtsTokenCount',0) if 'candidatesTokenCount' in raw else None))}]
    for usage in usages:
        if isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ('input_tokens','output_tokens')):
            call['inputTokens']+=usage['input_tokens'];call['outputTokens']+=usage['output_tokens'];call['usageReports']+=1


def record_call(call, phase, *, root=None, now=None):
    now=now or dt.datetime.now(KST);day=now.astimezone(KST).date().isoformat()
    path=Path(root or ROOT)/'dashboard/data/llm_usage_ledger.json';path.parent.mkdir(parents=True,exist_ok=True)
    with locked(path.with_suffix('.lock')):
        try:state=json.loads(path.read_text())
        except (OSError,ValueError):state={}
        if state.get('date')!=day:state={'schema':'llm-usage-ledger-v1','date':day,'byModel':{},'active':state.get('active',{}),'byAgenda':state.get('byAgenda',{}),'routeHealth':state.get('routeHealth',{}),'recent':[],'coverageStartedAt':now.isoformat()}
        if phase == 'started':
            import os
            for identity, active in list(state['active'].items()):
                try:
                    age = (now - dt.datetime.fromisoformat(active['startedAt'])).total_seconds()
                    if os.name == 'nt':
                        from common.runtime_locks import process_start_ticks
                        dead = active.get('pid') and process_start_ticks(active['pid']) is None
                    else:
                        dead = active.get('pid') and not Path('/proc', str(active['pid'])).exists()
                    if dead or age > 7200:
                        state['active'].pop(identity)
                except (KeyError, ValueError, TypeError):
                    state['active'].pop(identity)
            try:
                check_budget(state, call, budget_policy(root or ROOT), root or ROOT)
            except UsageBudgetExceeded as exc:
                state['lastBudgetBlock'] = {'agendaId': call.get('agendaId'), 'reason': str(exc), 'checkedAt': now.isoformat()}
                write(path, state)
                raise
        if phase == 'blocked':
            state['active'].pop(call['id'], None)
            state['lastRouteBlock'] = {'provider': call['provider'], 'model': call['model'], 'checkedAt': now.isoformat()}
            write(path, state)
            return
        _agenda_metrics(state, call, phase, now)
        if phase.startswith('action_'):
            state['checkedAt']=now.isoformat();write(path,state)
            return
        if phase=='started':
            state['active'][call['id']]={k:call[k] for k in ('provider','model','startedAt')}
            state['active'][call['id']]['agentSlot']=call.get('agentSlot')
            state['active'][call['id']]['reasoningEffort']=call.get('reasoningEffort')
            state['active'][call['id']]['agendaId']=call.get('agendaId')
            state['active'][call['id']]['pid']=os.getpid()
            state['active']=dict(list(state['active'].items())[-128:])
        else:
            state['active'].pop(call['id'],None)
            key=call['provider']+':'+call['model'];row=state['byModel'].setdefault(key,dict(provider=call['provider'],model=call['model'],
                calls=0,success=0,errors=0,inputTokens=0,outputTokens=0,usageReportedCalls=0,totalLatencyMs=0,rateLimited=0))
            row['calls']+=1;row['success' if phase=='completed' else 'errors']+=1
            for k in ('inputTokens','outputTokens'):row[k]+=call[k]
            row['usageReportedCalls']+=int(call['usageReports']>0)
            row['totalLatencyMs']+=call['latencyMs'];row['averageLatencyMs']=round(row['totalLatencyMs']/row['calls'])
            row.update(lastLatencyMs=call['latencyMs'],lastAt=now.isoformat(),lastStatus=phase,
                       errorType=call.get('errorType'),rateLimitHeaders=call['rateLimitHeaders'],httpStatus=call.get('httpStatus'))
            row['rateLimited']+=int(call.get('rateLimited',False))
            state['recent'].append({k:call.get(k) for k in ('id','agendaId','provider','model','startedAt','latencyMs','inputTokens','outputTokens','httpStatus','errorType','reasoningEffort')})
            state['recent']=state['recent'][-40:]
        state['checkedAt']=now.isoformat();write(path,state)


def _safe_record(call,phase):
    try:record_call(call,phase)
    except (OSError,ValueError,TypeError,KeyError):pass


def metered(function):
    @functools.wraps(function)
    def wrapped(*args,**kwargs):
        if _CURRENT.get() is not None:return function(*args,**kwargs)
        provider=kwargs.get('provider') or ('codex' if function.__module__.endswith('codex_cli') else None)
        model=kwargs.get('model_override') or kwargs.get('model')
        if provider=='codex' and len(args)>1:model=model or args[1]
        if not provider or not model:
            from common import llm_settings
            try:
                config=llm_settings.load();brain=llm_settings.get_agent_brain(kwargs['agent_slot'],config) if kwargs.get('agent_slot') else {}
            except (OSError,ValueError,KeyError):config={};brain={}
            provider=provider or brain.get('provider') or config.get('active','unknown')
            model=model or brain.get('model') or config.get('providers',{}).get(provider,{}).get('model','unknown')
        from common.crew_chat_bridge import current_model_identity
        actor,owner=current_model_identity()
        call=dict(id=uuid.uuid4().hex,agentSlot=kwargs.get('agent_slot') or owner or actor,provider=provider,model=model or 'unknown',startedAt=dt.datetime.now(KST).isoformat(),
                  inputTokens=0,outputTokens=0,usageReports=0,rateLimitHeaders={})
        try:call['agendaId']=agenda_identity()
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):pass
        record_call(call,'started')
        token=_CURRENT.set(call);start=time.monotonic();phase='failed'
        try:
            if function.__module__.endswith('codex_cli'):
                with route_attempt(provider, model or 'unknown'):
                    result=function(*args,**kwargs)
            else:
                result=function(*args,**kwargs)
            phase='completed'
            return result
        except Exception as exc:
            if isinstance(exc, (UsageBudgetExceeded, RouteCoolingDown)):
                phase = 'blocked'
            call['errorType']=type(exc).__name__
            call['rateLimited']=any(w in str(exc).lower() for w in ('429','rate limit','quota','한도 초과'))
            raise
        finally:
            call['latencyMs']=round((time.monotonic()-call.pop('latencyStart',start))*1000)
            try:
                _safe_record(call,phase)
            finally:
                _CURRENT.reset(token)
    return wrapped
