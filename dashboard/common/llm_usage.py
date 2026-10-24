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

_CURRENT = contextvars.ContextVar('llm_usage_call', default=None)
RATE_HEADERS = frozenset('x-ratelimit-limit-requests x-ratelimit-limit-tokens x-ratelimit-remaining-requests x-ratelimit-remaining-tokens x-ratelimit-reset-requests x-ratelimit-reset-tokens retry-after'.split())


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
        if state.get('date')!=day:state={'schema':'llm-usage-ledger-v1','date':day,'byModel':{},'active':{},'recent':[],'coverageStartedAt':now.isoformat()}
        if phase=='started':
            state['active'][call['id']]={k:call[k] for k in ('provider','model','startedAt')}
            state['active'][call['id']]['agentSlot']=call.get('agentSlot')
            state['active'][call['id']]['reasoningEffort']=call.get('reasoningEffort')
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
            state['recent'].append({k:call.get(k) for k in ('id','provider','model','startedAt','latencyMs','inputTokens','outputTokens','httpStatus','errorType','reasoningEffort')})
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
        token=_CURRENT.set(call);start=time.monotonic();_safe_record(call,'started');phase='failed'
        try:
            result=function(*args,**kwargs);phase='completed';return result
        except Exception as exc:
            call['errorType']=type(exc).__name__
            call['rateLimited']=any(w in str(exc).lower() for w in ('429','rate limit','quota','한도 초과'))
            raise
        finally:
            call['latencyMs']=round((time.monotonic()-start)*1000);_safe_record(call,phase);_CURRENT.reset(token)
    return wrapped
