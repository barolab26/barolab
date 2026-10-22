"""Host-observed failures request diagnosis only; this module cannot retry work."""
import hashlib
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]/'server/data/repair-workflows/evidence'


def report_host_failure(*, actor, task_key, state, evidence_ref, source_record, error_type=''):
    try:
        from common.crew_chat_bridge import emit_work_event, work_task_id
        task_id = work_task_id(task_key)
        source_hash = hashlib.sha256(json.dumps(source_record,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
        receipt = {'taskId':task_id,'state':state,'errorType':error_type,
                   'sourceRef':str(evidence_ref),'sourceRecordSha256':source_hash,
                   'automaticResumeAllowed':False}
        raw = json.dumps(receipt,ensure_ascii=False,sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        ROOT.mkdir(parents=True,exist_ok=True)
        path = ROOT/(digest+'.json')
        if not path.exists():
            try:
                with path.open('xb') as output: output.write(raw)
            except FileExistsError:
                pass
        if path.read_bytes() != raw:
            raise ValueError('Existing failure evidence differs')
        return emit_work_event(actor=actor,actor_label=actor,task_id=task_id,
            phase='failed',stage=state,evidence_id=digest,
            output_kind='host failure; needs diagnosis; no automatic resume')
    except Exception as exc:
        logging.getLogger(__name__).warning('Host failure reporting unavailable: %s',type(exc).__name__)
        return None
