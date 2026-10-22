"""Drive registered schedulers through the durable staff queue, with backoff."""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from common.collection_observability import locked, write

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'server/data/project-autonomy.json'
STATE = ROOT / 'server/data/project-autonomy-state.json'
# These entrypoints retain their own enabled/account/slot/quality/submission locks.
# Never use force, manual-retry, a model-supplied command, or a shifted slot here.
COMMANDS = {
    'cf_blog': ['cf_posting/pipeline_runner.py', '--catch-up-today-once'],
    'naver_blog': ['naver_blog_posting/pipeline_runner.py', '--catch-up'],
    'naver_kin': ['-m', 'naver_kin.scheduler', '--tick'],
    'threads': ['-m', 'threads_posting.scheduler', '--tick'],
    'legacy_remodel': ['-m', 'common.content_maintenance'],
}


def run_project_cycle(project):
    from server.agent_tools import _ego_popen
    if project not in COMMANDS:
        raise ValueError('No registered autonomous project scheduler')
    config = json.loads(CONFIG.read_bytes())
    if (config.get('enabled') is not True or project not in config.get('projects', [])
            or (Path.home() / 'EGO_EXEC_DISABLED').exists()):
        return {'ok': False, 'status': 'held', 'reason': 'execution_disabled'}
    process = _ego_popen([sys.executable, '-u', '-B', '-X', 'utf8', *COMMANDS[project]],
                         cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {'ok': True, 'status': 'running', 'project': project,
            'pid': process.pid, 'receiptPath': process.ego_receipt_path,
            'publicationVerified': False}


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
        # Preserve uncertain children across restart; never spawn another one.
        return None
    status = receipt.get('status')
    outcome = ('completed' if receipt.get('exitCode') == 0 else 'failed') if status == 'exited' else (
        'failed' if status in ('failed', 'launch_failed') else 'unknown')
    return {'ok': outcome == 'completed',
            'status': outcome,
            'project': result['project'], 'receiptPath': str(path), 'pid': result['pid'],
            'exitCode': receipt.get('exitCode'), 'publicationVerified': False,
            'controllerEvidenceSha256': hashlib.sha256(raw).hexdigest()}, receipt


def process_project_autonomy_once():
    """One claim per poll; failed speech/model calls cannot suppress execution."""
    from server.agent_tools import STAFF_REQUEST_DIR, enqueue_staff_request
    from server.project_health import observed_projects, today_kst_str
    try:
        config = json.loads(CONFIG.read_bytes())
    except (OSError, ValueError):
        return False
    if config.get('enabled') is not True or (Path.home() / 'EGO_EXEC_DISABLED').exists():
        return False
    now = time.time()
    projects = {p['id']: p for p in observed_projects()}
    with locked(STATE.parent / 'project-autonomy-lock'):
        state = json.loads(STATE.read_bytes()) if STATE.exists() else {}
        rows = state.setdefault('projects', {})
        eligible = []
        for project in sorted(COMMANDS, key=lambda key: rows.get(key, {}).get('lastStartedAt', 0)):
            if project not in config.get('projects', []):
                continue
            observation = projects.get(project, {})
            row = rows.setdefault(project, {})
            request_id = row.get('requestId')
            if request_id:
                path = STAFF_REQUEST_DIR / (hashlib.sha256(request_id.encode()).hexdigest() + '.json')
                if not path.exists():
                    # Outbox claim persisted before enqueue: same ID is safe to redeliver.
                    enqueue_staff_request(request_id, [row['action']])
                    return True
                request = json.loads(path.read_bytes())
                if request.get('status') in ('queued', 'acknowledged', 'awaiting_completion', 'unknown'):
                    continue
                if row.get('observedRequestId') != request_id:
                    row.update(observedRequestId=request_id, lastResult=request.get('status'),
                               lastObservation=observation)
                    # No progress is a failure even when a scheduler exits cleanly.
                    signature = hashlib.sha256(json.dumps({k: observation.get(k) for k in
                        ('counts', 'observedState', 'failures', 'verifiedPublicCount', 'reservedCount')},
                        sort_keys=True).encode()).hexdigest()
                    stalled = signature == row.get('progressSignature')
                    row['stalledCycles'] = row.get('stalledCycles', 0) + 1 if stalled else 0
                    row['progressSignature'] = signature
                    row['nextRunAt'] = now + min(3600, 300 * 2 ** min(row['stalledCycles'], 4))
                    if observation.get('status') in ('attention', 'stale', 'unknown'):
                        # Bind feedback/repair to this executable request, not a
                        # read-only status request with no resumption capability.
                        from server.project_monitor import INCIDENTS
                        INCIDENTS.mkdir(parents=True, exist_ok=True)
                        incident = INCIDENTS / (hashlib.sha256(request_id.encode()).hexdigest() + '.json')
                        if not incident.exists():
                            write(incident, {'version': 1, 'taskId': request['taskId'],
                                'status': 'dispatched', 'observedAt': now,
                                'observation': observation, 'publicationAttempted': None,
                                'dispatch': {'requestId': request_id, 'taskId': request['taskId']}})
                    write(STATE, state)
            if row.get('nextRunAt', 0) > now:
                continue
            # One execution globally: channels share browser accounts and LLM routes.
            active = False
            for path in STAFF_REQUEST_DIR.glob('*.json'):
                try:
                    request = json.loads(path.read_bytes())
                except (OSError, ValueError):
                    continue
                if (request.get('status') in ('queued', 'acknowledged', 'awaiting_completion', 'unknown')
                        and any(a.get('tool') == 'run_project_cycle'
                            or (request.get('status') != 'unknown' and a.get('tool') in
                                ('advance_project_recovery', 'repair_cf_known_failure'))
                            for a in request.get('actions', []))):
                    active = True
                    break
            if active:
                continue
            eligible.append(project)
        if eligible:
            project = eligible[0]
            row = rows[project]
            actor = 'doctor' if project == 'legacy_remodel' else 'publi'
            action = {'agent': actor, 'tool': 'run_project_cycle', 'args': {'project': project}}
            request_id = f'autonomy:{project}:{today_kst_str()}:{int(now)}'
            row.update(requestId=request_id, action=action, lastStartedAt=now,
                       nextRunAt=now + 300, status='requested')
            write(STATE, state)
            enqueue_staff_request(request_id, [action])
            return True
        write(STATE, state)
    return False
