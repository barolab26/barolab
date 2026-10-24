"""
Real-time bridge allowing background pipelines (`cf_posting`, `naver_blog_posting`, `growth.py`)
to broadcast live agent collaboration messages and in-place task status updates into the
BaroLab Meeting Room (`server/chat_room.py` & `dashboard/chat.html`).
"""

import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from contextvars import ContextVar
_model_crew_identity = ContextVar('model_crew_identity', default=('', ''))
_model_call_route = ContextVar('model_call_route', default=None)
_last_model_route = ContextVar('last_model_route', default=None)


def record_model_route(provider, model, reasoning_effort=None):
    _model_call_route.set({'provider':provider,'model':model,'reasoningEffort':reasoning_effort or ('low' if provider=='codex' else None)})


def last_model_route():
    return dict(_last_model_route.get() or {})


def current_model_identity():
    return _model_crew_identity.get()


BASE_DIR = Path(__file__).resolve().parents[2]
ROOM_MAIN_FILE = BASE_DIR / 'dashboard' / 'data' / "chats" / "room-main.json"


def emit_pipeline_crew_message(
    who: str,
    text: str,
    handoff: Optional[str] = None,
    status: str = "completed",
    step: str = "",
    result_summary: str = "",
    deliverable_url: str = "",
    deliverable_label: str = "",
    synapse_linked: bool = False,
    synapse_label: str = "",
    msg_id: Optional[str] = None,
) -> Optional[str]:
    """
    Send a live autonomous crew message or in-place status update to the meeting room server.
    Never raises an exception so pipelines are never blocked.
    """
    ts = int(time.time() * 1000)
    mid = msg_id or f"auto-{ts}-{who}"
    payload: Dict[str, Any] = {
        "id": mid,
        "who": who,
        "text": text,
        "ts": ts,
        "autonomous": True,
        "taskTracker": {
            "handoff": handoff or "",
            "status": status,
            "step": step,
            "resultSummary": result_summary or step,
            "deliverableUrl": deliverable_url,
            "deliverableLabel": deliverable_label,
            "synapseLinked": synapse_linked,
            "synapseLabel": synapse_label or ("🧠 기억 그래프에 새 노하우 연결됨" if synapse_linked else ""),
        },
    }

    return _deliver(payload)


OUTBOX_DIR = BASE_DIR / 'dashboard' / 'data' / 'chats' / 'crew-outbox'


def _deliver(payload):
    """Canonical local receiver, then atomic per-event outbox; never edit its ledger."""
    import logging
    import uuid
    try:
        endpoint = 'agenda-event' if payload.get('eventType') == 'crew_agenda_event' else 'work-event' if payload.get('eventType') == 'crew_work_event' else 'autonomous/event'
        req = urllib.request.Request('http://127.0.0.1:8790/api/chat/'+endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=0.6) as response:
            if response.status == 200:
                return payload['id']
    except Exception as exc:
        logging.getLogger(__name__).warning('Crew HTTP delivery deferred: %s', type(exc).__name__)
    try:
        import hashlib
        outbox_dir = OUTBOX_DIR if payload.get('eventType') in ('crew_work_event','crew_agenda_event') else OUTBOX_DIR / 'legacy'
        outbox_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(payload['id'].encode('utf-8')).hexdigest()
        target = outbox_dir / (name+'.json')
        tmp = outbox_dir / (name+'.'+uuid.uuid4().hex+'.tmp')
        tmp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
        tmp.replace(target)
        return payload['id']
    except Exception as exc:
        logging.getLogger(__name__).error('Crew outbox unavailable: %s', type(exc).__name__)
        return None


STAFF_ACTORS = frozenset(('jarvis','publi','trace','patch','radar','doctor'))
TOOL_OWNERS = {
    **{prefix+'-'+role: ('radar' if role in ('keyword-selector','researcher') else 'doctor' if role=='reviewer' else 'publi')
       for prefix in ('cf','naver')
       for role in ('keyword-selector','researcher','writer','image-maker','assembler','reviewer')},
    'cf-pipeline':'publi', 'naver-pipeline':'publi',
    'kin_pipeline':'publi', 'threads_pipeline':'publi',
    'kin-pipeline':'publi', 'threads-pipeline':'publi',
}


def work_actor_owner(actor, owner_agent=''):
    """Configured responsibility only; an unknown caller has no invented owner."""
    if owner_agent and owner_agent not in STAFF_ACTORS:
        raise ValueError('Unknown staff owner')
    if actor in STAFF_ACTORS:
        if owner_agent and owner_agent != actor:
            raise ValueError('Staff actor owner mismatch')
        return actor
    return owner_agent or TOOL_OWNERS.get(actor, '')


def report_context(value):
    """Bounded public task facts; prose and URLs travel through their own fields."""
    allowed = {'channel', 'account', 'domain', 'title', 'reserveTime', 'slot', 'status', 'scope', 'nextAction', 'linkStatus'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Invalid report context')
    result = {}
    for key, item in value.items():
        if item is None or item == '':
            continue
        if not isinstance(item, str) or len(item) > 500 or any(ord(c) < 32 for c in item):
            raise ValueError('Invalid report field')
        if re.search(r'https?://|(?:password|secret|cookie|api[_ -]?key|access[_ -]?token)\s*[:=]', item, re.I):
            raise ValueError('Private report field')
        result[key] = item
    return result


def emit_work_event(*, actor, actor_label, task_id, phase, stage='',
                    parent_request_id='', requested_to='', model='', evidence_id='', output_kind='', owner_agent='', message_kind='', deliverable_url='', deliverable_label='', report=None, provider='', reasoning_effort=None):
    """Host-observed lifecycle metadata only; never pass prompts, responses or secrets."""
    import uuid
    phases = {'requested':'실행 요청', 'completed':'실행 반환', 'failed':'실행 실패', 'progress':'작업 진행'}
    if phase not in phases:
        raise ValueError('Unknown crew lifecycle phase')
    if message_kind=='staff_reply' and stage!='ceo-result-review':
        from common.staff_message import display_message
        output_kind=display_message(output_kind)
    clean = lambda value: str(value or '').replace('\n',' ')[:160]
    event_id = 'crew-'+uuid.uuid4().hex
    stage = clean(stage)
    owner = work_actor_owner(actor, owner_agent)
    if message_kind not in ('','host_instruction','host_ack','tool_result','staff_reply'):
        raise ValueError('Unknown work message kind')
    route=_model_call_route.get() or {}
    last=_last_model_route.get() or {}
    if not route and last.get('taskId')==task_id:route=last
    if route.get('model')==model:
        provider=provider or route.get('provider','')
        reasoning_effort=reasoning_effort or route.get('reasoningEffort')
    from common.llm_settings import format_brain_badge
    badge=format_brain_badge(provider,model,reasoning_effort) if provider else model
    payload = {'id':event_id,'eventId':event_id,'eventType':'crew_work_event',
        'taskId':clean(task_id),'parentRequestId':clean(parent_request_id),
        'requestedTo':clean(requested_to),'phase':phase,'who':clean(actor),
        'actorLabel':clean(actor_label),'ownerAgent':owner,'toolActor':clean(actor) if actor not in STAFF_ACTORS else '', 'provider':clean(provider),'reasoningEffort':clean(reasoning_effort),'modelBadge':clean(badge),'model':clean(model),'evidenceId':clean(evidence_id),
        'outputKind':clean(output_kind),'messageKind':message_kind,'stage':stage,'ts':int(time.time()*1000),'autonomous':True,
        'text':f'{stage}: {phases[phase]}. 업무 성공·게시 확인은 별도 검증합니다.',
        'taskTracker':{'status':phase,'step':stage,'resultSummary':clean(output_kind),
                       'handoff':'','synapseLinked':False}}
    from common.work_agenda import current
    if current():payload['agendaId'] = current()['id']
    if report is not None:
        payload['reportContext'] = report_context(report)
    if deliverable_url:
        from dashboard.agents.synapse import url
        address = url(deliverable_url)
        if not address:
            raise ValueError('Invalid public deliverable URL')
        payload['deliverableUrl'] = address
        if deliverable_label:
            payload['deliverableLabel'] = clean(deliverable_label)
    _deliver(payload)
    if phase == 'failed':
        try:
            from common.repair_workflow import record_failed_event
            record_failed_event(payload)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error('Repair intake unavailable: %s',type(exc).__name__)
    return event_id


from contextvars import ContextVar
_model_crew_active = ContextVar('barolab_model_crew_active', default=False)


def work_task_id(folder):
    """Stable opaque run identity; model-audit descendants share the host run."""
    import hashlib
    path = Path(folder).resolve()
    if 'model-audit' in path.parts:
        path = Path(*path.parts[:path.parts.index('model-audit')])
    return 'run-'+hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:24]


def model_crew_call(function):
    """One honest outer call pair, including skip-memory and direct CLI entry points."""
    import functools
    import uuid
    @functools.wraps(function)
    def wrapped(prompt, *args, **kwargs):
        task_id = kwargs.pop('crew_task_id', None)
        stage = kwargs.pop('crew_stage', 'model-call')
        slot = kwargs.get('agent_slot', '')
        default_actor = slot if slot in STAFF_ACTORS else {'cf_pipeline':'publi','naver_pipeline':'publi','kin_pipeline':'publi','threads_pipeline':'publi'}.get(slot, 'common-runner')
        actor = kwargs.pop('crew_actor', default_actor)
        label = kwargs.pop('crew_actor_label', '공통 실행기')
        owner = kwargs.pop('crew_owner_agent', '')
        if _model_crew_active.get():
            return function(prompt,*args,**kwargs)
        task = task_id or 'model-'+uuid.uuid4().hex
        model = kwargs.get('model') or (args[0] if args and isinstance(args[0],str) else '')
        request = emit_work_event(actor=actor,actor_label=label,task_id=task,owner_agent=owner,
            phase='requested',stage=stage,model=model,requested_to='model:'+str(model) if model else 'configured-model-runner',output_kind='model response pending')
        token = _model_crew_active.set(True)
        identity_token = _model_crew_identity.set((actor, owner))
        route_token = _model_call_route.set(None)
        try:
            result = function(prompt,*args,**kwargs)
        except BaseException:
            emit_work_event(actor=actor,actor_label=label,task_id=task,owner_agent=owner,phase='failed',
                stage=stage,parent_request_id=request,model=model,output_kind='no response confirmed')
            raise
        else:
            response = result[0] if isinstance(result,tuple) else result
            kind = type(response).__name__
            if isinstance(response,dict):
                import re
                keys = [key for key in response if isinstance(key,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,31}',key)]
                kind += ' fields:'+','.join(keys[:6])
                allowed = {'held','running','waiting','failed','unknown','skip','record','approve','reject','verified'}
                observed = []
                for key in ('classification','state','status','decision'):
                    value = response.get(key)
                    if isinstance(value,str) and value in allowed:
                        observed.append(key+'='+value)
                if type(response.get('passed')) is bool:
                    observed.append('passed='+str(response['passed']).lower())
                # Fixed enum values only: never render arbitrary response strings.
                if observed:
                    kind = type(response).__name__+' '+','.join(observed)+' fields:'+','.join(keys[:6])
            route=_model_call_route.get() or {}
            actual = route.get('model') or (result[1] if isinstance(result,tuple) and len(result)>1 and isinstance(result[1],str) else model)
            _last_model_route.set({**route,'taskId':task,'actor':actor,'observedAt':time.time()})
            emit_work_event(actor=actor,actor_label=label,task_id=task,owner_agent=owner,phase='completed',
                stage=stage,parent_request_id=request,model=actual,output_kind=kind+'; model response only')
            return result
        finally:
            _model_call_route.reset(route_token)
            _model_crew_identity.reset(identity_token)
            _model_crew_active.reset(token)
    return wrapped
