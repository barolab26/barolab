"""One registered channel worker at a time; no editorial approval chain."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from common.collection_observability import locked, write
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'dashboard/data/project-autonomy.json'
STATE = ROOT / 'dashboard/data/project-autonomy-state.json'
COMMANDS = {
    'cf_blog': ['cf_posting/posting.py', '--catch-up-today-once', '--limit', '1'],
    'naver_blog': ['naver_blog_posting/posting.py', '--catch-up', '--limit', '1'],
    'naver_kin': ['-m', 'naver_kin.posting', '--tick'],
    'threads': ['-m', 'threads_posting.posting', '--tick'],
    'legacy_remodel': ['-m', 'common.content_maintenance'],
}


def run_project_cycle(project):
    from server.agent_tools import _ego_popen
    from common.system_watchdog import is_process_running_match
    if project not in COMMANDS: raise ValueError('Unknown project')
    config = json.loads(CONFIG.read_bytes())
    if config.get('enabled') is not True or project not in config.get('projects', []) or (Path.home()/'EGO_EXEC_DISABLED').exists():
        return {'ok': False, 'status': 'held', 'reason': 'execution_disabled'}
    command = COMMANDS[project]
    marker = command[1] if command[0]=='-m' else str(ROOT/command[0])
    if is_process_running_match(marker):
        return {'ok': False, 'status': 'busy', 'project': project}
    child = _ego_popen([sys.executable,'-u','-B','-X','utf8',*command],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'ok':True,'status':'running','project':project,'pid':child.pid,'receiptPath':child.ego_receipt_path,'publicationVerified':False}


def terminal_result(result):
    """Read only the exact registered child; exit zero is not publication proof."""
    from server.agent_tools import EGO_PROCESS_DIR
    path = Path(result['receiptPath'])
    if (path.name != 'receipt.json' or path.is_symlink() or path.parent.is_symlink()
            or path.resolve().parent.parent != EGO_PROCESS_DIR.resolve()):
        raise ValueError('Unregistered process receipt')
    raw = path.read_bytes()
    if len(raw) > 100000:
        raise ValueError('Oversized process receipt')
    receipt = json.loads(raw)
    action = receipt.get('action') or {}
    if (receipt.get('pid') != result.get('pid') or action.get('tool') != 'run_project_cycle'
            or action.get('argumentsComplete') is not True
            or action.get('args') != {'project': result['project']}):
        raise ValueError('Process identity mismatch')
    if receipt.get('status') in ('starting', 'running'):
        try:
            ticks=int((Path('/proc')/str(receipt['pid'])/'stat').read_text().split(') ',1)[1].split()[19])
            same=receipt.get('processStartTicks') in (None,ticks)
        except (OSError,ValueError,IndexError):
            same=False
        if same:return None
        receipt={**receipt,'status':'interrupted','livenessObservedAt':time.time()}
    status = receipt.get('status')
    outcome = ('completed' if receipt.get('exitCode') == 0 else 'failed') if status == 'exited' else (
        'failed' if status in ('failed', 'launch_failed') else 'unknown')
    return {'ok': outcome == 'completed',
            'status': outcome,
            'project': result['project'], 'receiptPath': str(path), 'pid': result['pid'],
            'exitCode': receipt.get('exitCode'), 'publicationVerified': False,
            'controllerEvidenceSha256': hashlib.sha256(raw).hexdigest()}, receipt


def process_project_autonomy_once():
    from server.agent_tools import STAFF_REQUEST_DIR, enqueue_staff_request
    try: config=json.loads(CONFIG.read_bytes())
    except (OSError,ValueError): return False
    if config.get('enabled') is not True or (Path.home()/'EGO_EXEC_DISABLED').exists(): return False
    now=time.time()
    with locked(STATE.parent/'project-autonomy-lock'):
        state=json.loads(STATE.read_bytes()) if STATE.exists() else {}
        if state.get('mode')!='basic-one-pass':
            backup=STATE.parent/'maintenance-backups'/'project-autonomy-before-basic.json'
            if not backup.exists(): write(backup,state)
            state={'mode':'basic-one-pass','projects':{}}
        rows=state.setdefault('projects',{})
        # The same durable request is redelivered after a crash, never duplicated.
        pending_projects=set()
        for project,row in rows.items():
            request_id=row.get('requestId')
            if not request_id: continue
            path=STAFF_REQUEST_DIR/(hashlib.sha256(request_id.encode()).hexdigest()+'.json')
            if not path.exists(): enqueue_staff_request(request_id,[row['action']]);return True
            request=json.loads(path.read_bytes())
            if request.get('status') in ('queued','acknowledged','awaiting_completion'):pending_projects.add(project)
        enabled=[p for p in config.get('projects',[]) if p in COMMANDS]
        for project in sorted(enabled,key=lambda p:rows.get(p,{}).get('lastStartedAt',0)):
            if project in pending_projects:continue
            row=rows.setdefault(project,{})
            if project=='naver_kin':
                row.update(dispatchOwner='barolab-kin.timer',status='timer_managed')
                continue
            if now<row.get('nextRunAt',0):continue
            actor='doctor' if project=='legacy_remodel' else 'publi'
            action={'agent':actor,'tool':'run_project_cycle','args':{'project':project}}
            request_id=f'autonomy-basic:{project}:{int(now)}'
            row.update(requestId=request_id,action=action,lastStartedAt=now,nextRunAt=now+300,status='requested')
            write(STATE,state);enqueue_staff_request(request_id,[action])
            from common.crew_chat_bridge import emit_work_event
            emit_work_event(actor='jarvis',actor_label='자비스',task_id=request_id,phase='completed',stage='project-instruction-issued',requested_to=actor,output_kind=project+' 기본 워크플로우 실행 배정')
            return True
        write(STATE,state)
    return False
