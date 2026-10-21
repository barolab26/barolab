"""
Real-time bridge allowing background pipelines (`cf_posting`, `naver_blog_posting`, `growth.py`)
to broadcast live agent collaboration messages and in-place task status updates into the
BaroLab Meeting Room (`server/chat_room.py` & `dashboard/chat.html`).
"""

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
ROOM_MAIN_FILE = BASE_DIR / "server" / "data" / "chats" / "room-main.json"


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


OUTBOX_DIR = BASE_DIR / 'server' / 'data' / 'chats' / 'crew-outbox'


def _deliver(payload):
    """Canonical local receiver, then atomic per-event outbox; never edit its ledger."""
    import logging
    import uuid
    try:
        endpoint = 'work-event' if payload.get('eventType') == 'crew_work_event' else 'autonomous/event'
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
        outbox_dir = OUTBOX_DIR if payload.get('eventType') == 'crew_work_event' else OUTBOX_DIR / 'legacy'
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


def emit_work_event(*, actor, actor_label, task_id, phase, stage='',
                    parent_request_id='', requested_to='', model='', evidence_id='', output_kind=''):
    """Host-observed lifecycle metadata only; never pass prompts, responses or secrets."""
    import uuid
    phases = {'requested':'실행 요청', 'completed':'실행 반환', 'failed':'실행 실패', 'progress':'작업 진행'}
    if phase not in phases:
        raise ValueError('Unknown crew lifecycle phase')
    clean = lambda value: str(value or '').replace('\n',' ')[:160]
    event_id = 'crew-'+uuid.uuid4().hex
    stage = clean(stage)
    payload = {'id':event_id,'eventId':event_id,'eventType':'crew_work_event',
        'taskId':clean(task_id),'parentRequestId':clean(parent_request_id),
        'requestedTo':clean(requested_to),'phase':phase,'who':clean(actor),
        'actorLabel':clean(actor_label),'model':clean(model),'evidenceId':clean(evidence_id),
        'outputKind':clean(output_kind),'stage':stage,'ts':int(time.time()*1000),'autonomous':True,
        'text':f'{stage}: {phases[phase]}. 업무 성공·게시 확인은 별도 검증합니다.',
        'taskTracker':{'status':phase,'step':stage,'resultSummary':clean(output_kind),
                       'handoff':'','synapseLinked':False}}
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
        actor = kwargs.pop('crew_actor', 'common-runner')
        label = kwargs.pop('crew_actor_label', '공통 실행기')
        if _model_crew_active.get():
            return function(prompt,*args,**kwargs)
        task = task_id or 'model-'+uuid.uuid4().hex
        model = kwargs.get('model') or (args[0] if args and isinstance(args[0],str) else '')
        request = emit_work_event(actor=actor,actor_label=label,task_id=task,
            phase='requested',stage=stage,model=model,requested_to='model:'+str(model) if model else 'configured-model-runner',output_kind='model response pending')
        token = _model_crew_active.set(True)
        try:
            result = function(prompt,*args,**kwargs)
        except BaseException:
            emit_work_event(actor=actor,actor_label=label,task_id=task,phase='failed',
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
            actual = result[1] if isinstance(result,tuple) and len(result)>1 and isinstance(result[1],str) else model
            emit_work_event(actor=actor,actor_label=label,task_id=task,phase='completed',
                stage=stage,parent_request_id=request,model=actual,output_kind=kind+'; model response only')
            return result
        finally:
            _model_crew_active.reset(token)
    return wrapped
