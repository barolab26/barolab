"""Drive registered schedulers through the durable staff queue, with backoff."""
import hashlib
import json
import subprocess
import sys
import time
from contextvars import ContextVar
from pathlib import Path

from common.collection_observability import locked, write

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'server/data/project-autonomy.json'
STATE = ROOT / 'server/data/project-autonomy-state.json'
_bound_work = ContextVar('bound_recovery_work', default=None)
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
    from common.recovery_evidence import work_barrier
    bound = _bound_work.get()
    if bound:
        if bound['plan']['project'] != project: raise ValueError('Recovery project changed')
        command = ['-m', 'common.project_autonomy', '--resume-work', bound['taskId'], '--plan', bound['planSha256']]
    elif work_barrier(project, ROOT):
        return {'ok': False, 'status': 'held', 'reason': 'unfinished_original_work_requires_repair'}
    else:
        command = COMMANDS[project]
    process = _ego_popen([sys.executable, '-u', '-B', '-X', 'utf8', *command],
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
            from common.recovery_evidence import failure_targets
            targets = failure_targets(ROOT, project)
            work = row.get('failureWork')
            if work:
                # Keep the exact original request even when the source changes,
                # the date rolls over, or a repair is held. Never select a new topic.
                row['status'] = 'awaiting_original_work_completion'
                row['failureBacklogCount'] = len(targets)
                from common.repair_workflow import _recovery_path, RECOVERY_ROLES
                repair = _recovery_path('project-work:' + work['workId'])
                if repair.is_file():
                    recovery = json.loads(repair.read_bytes())
                    assigned = (recovery.get('classification') or {}).get('inspectRole') if recovery.get('step')=='inspect' else RECOVERY_ROLES.get(recovery.get('step'))
                    work.update(recoveryStatus=recovery.get('status'), step=recovery.get('step'), assignedRole=assigned,
                                blocker=recovery.get('errorCode') or (recovery.get('classification') or {}).get('reason'))
                    if recovery.get('status') == 'work_verified_learning_queued':
                        work.update(status='public_verified', completedAt=now,
                                    verifiedWorkProof=recovery.get('resumeResult', {}).get('verifiedWorkProof'))
                        row.setdefault('completedWork', []).append(work)
                        row['completedWork'] = row['completedWork'][-20:]
                        row.pop('failureWork')
                        row.update(status='original_work_verified', nextRunAt=now+60)
                continue
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
                if targets:
                    from server.project_monitor import INCIDENTS
                    target = targets[0]
                    incident = INCIDENTS / ('work-' + target['workId'] + '.json')
                    INCIDENTS.mkdir(parents=True, exist_ok=True)
                    if not incident.exists():
                        write(incident, {'version': 2, 'taskId': 'project-work:' + target['workId'],
                            'status': 'dispatched', 'observedAt': now, 'observation': observation,
                            'workTarget': target, 'publicationAttempted': None,
                            'dispatch': {'requestId': request_id, 'taskId': request['taskId']}})
                    row['failureWork'] = {'workId': target['workId'], 'target': target,
                        'incidentPath': str(incident), 'requestId': request_id,
                        'status': 'awaiting_repair', 'claimedAt': now}
                    row['failureBacklogCount'] = len(targets)
                    row['status'] = 'awaiting_original_work_completion'
                    write(STATE, state)
                    continue
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


def resume_bound_work(task_id, plan_sha256):
    """Publish only the repaired original reviewed manuscript, never a new topic."""
    from common.repair_workflow import _recovery_row, _recovery_resume_guard
    from common.recovery_evidence import artifact_folder
    _, row = _recovery_row(task_id, plan_sha256)
    if row.get('status') != 'processing' or row.get('step') != 'resume' or not row.get('resumeAttempted'):
        raise ValueError('Original-work resume was not claimed')
    _recovery_resume_guard(row)
    plan = row['plan']; target = plan['workTarget']
    if plan['project'] == 'naver_blog':
        from naver_blog_posting import pipeline_runner as runner
        from common.recovery_evidence import read_object
        original = artifact_folder(ROOT,target)
        prepared = read_object(original/'original-work-preparation.json') if original else {}
        if prepared.get('workId') != target['workId'] or prepared.get('status') != 'prepared':
            raise ValueError('Original Naver work still requires prepared and reviewed content')
        folder = Path(prepared['preparedFolder']).resolve()
        if not folder.is_relative_to((ROOT/'naver_blog_posting/output'/target['identity']).resolve()):
            raise ValueError('Original Naver account binding changed')
        context = read_object(folder/'preparation-context.json')
        runner.RUN_OPTIONS.update(context['runOptions'])
        runner.RUN_OPTIONS.update(publication_date=target['date'],prepared_dir=str(folder),worker_mode='catch_up')
        runner.validate_prepared_context(target['identity'],folder,slot=target['slot'],publication_date=target['date'],
                                        override_strategy_id=context.get('strategyOverride'))
        runner.run_accounts([target['identity']],slot=target['slot'],publication_date=target['date'],
                            override_strategy_id=context.get('strategyOverride'))
        return {'status':'reservation_returned','publicVerificationRequired':True}
    if plan['project'] != 'cf_blog':
        raise ValueError('This original-work publisher requires a registered channel adapter')
    from cf_posting import pipeline_runner as runner
    with runner.cleaner_lock() as acquired:
        if not acquired: raise RuntimeError('Original publisher busy; no replacement work started')
        schedule = json.loads(runner.SCHEDULE_JSON.read_bytes())
        if schedule.get('date') != target['date']: raise ValueError('Original publication date changed')
        item = next(item for item in schedule['items'] if item['domain'] == target['identity'])
        if runner.publication_may_be_inflight(item):
            if runner.reconcile_item(item, schedule['date'], strict=True):
                runner.save_schedule_file(runner.SCHEDULE_JSON, schedule)
                return {'status': 'published', 'publicVerificationRequired': True}
            raise ValueError('Original submission requires reconciliation')
        original = artifact_folder(ROOT, target)
        current = artifact_folder(ROOT, {**target, 'artifactFolder': item.get('artifactFolder')})
        if not original or not current or not current.is_relative_to(original):
            raise ValueError('Repaired manuscript belongs to a different work')
        runner.bind_prepared_reviewed_articles(schedule)
        if item.get('status') != 'prepared' or not item.get('reviewedArticle'):
            raise ValueError('Original manuscript still requires completion; new topic prohibited')
        runner.save_schedule_file(runner.SCHEDULE_JSON, schedule)
        published = runner.run_publisher_for_item(item, schedule, runner.SCHEDULE_JSON,
                                                  _repair_authorization=runner._REPAIR_AUTHORIZATION)
        if not published: raise RuntimeError('Original work did not pass publication verification')
        return {'status': 'published', 'publicVerificationRequired': True}


def acquire_bound_work(task_id, plan_sha256):
    """Recollect real Naver evidence for the same rejected question, before writing."""
    from common.repair_workflow import _recovery_row, _recovery_resume_guard
    from common.recovery_evidence import task_evidence, artifact_folder, read_object
    from naver_blog_posting import pipeline_runner as runner
    _, row = _recovery_row(task_id,plan_sha256)
    if row.get('status') != 'awaiting_inputs' or row.get('step') != 'acquire':
        # The observer may not yet have saved the launch receipt; the phase claim
        # still proves that this exact acquisition was started once.
        if row.get('status') != 'processing' or row.get('step') != 'acquire':
            raise ValueError('Original-work acquisition was not claimed')
    plan=row['plan'];target=plan['workTarget']
    _recovery_resume_guard(row)
    cap=task_evidence(ROOT,target).get('inputCapability')
    if not cap or cap['kind'] not in ('naver_same_question_preparation','naver_original_review'):
        raise ValueError('Original Naver acquisition capability changed')
    folder=artifact_folder(ROOT,target)
    claim=folder/'original-work-acquisition-claim.json'
    with claim.open('x',encoding='utf-8') as stream:
        json.dump({'workId':target['workId'],'readerQuestion':cap['readerQuestion'],
                   'publicationAttempted':False,'attemptLimit':1},stream,ensure_ascii=False)
    context=read_object(folder/'preparation-context.json')
    runner.RUN_OPTIONS.update(context['runOptions'])
    review_folder=str(folder) if cap['kind']=='naver_original_review' else None
    evidence_dir=None
    if not review_folder:
        evidence_dir=folder/'original-work-keyword-evidence';evidence_dir.mkdir(exist_ok=False)
        packet=runner.collect_evidence(target['identity'],cap['query'])
        write(evidence_dir/'keyword-evidence.json',packet)
        write(folder/'original-work-acquisition.json',{'workId':target['workId'],'readerQuestion':cap['readerQuestion'],
            'query':cap['query'],'keywordEvidencePath':str(evidence_dir/'keyword-evidence.json'),
            'scope':'Actual observed search bodies; demand is remeasured by the keyword stage. No approval inferred.'})
        runner.RUN_OPTIONS.update(topic_seed=cap['readerQuestion'],main_keyword=None,evidence_dir=str(evidence_dir))
    runner.RUN_OPTIONS.update(publication_date=target['date'],allow_retry_handoff=False)
    # Explicit topic_seed is enforced by bind_reader_demand; failed alignment
    # cannot choose another reader question or produce a replacement post.
    try:
        with runner.pipeline_lock():
            _, prepared_folder, _, _, _, _ = runner.prepare_content(target['identity'],context.get('strategyOverride'),
                str(evidence_dir) if evidence_dir else context['runOptions'].get('evidence_dir'),
                publication_attempt=False,attribution_slot=target['slot'],review_folder=review_folder)
    except Exception as exc:
        import traceback
        from common.hermes_memory import learning_text
        write(folder/'failure-diagnostics.json',{'workId':target['workId'],
            'error':learning_text(type(exc).__name__+': '+str(exc)[:2000]),
            'lastTraceback':'\n'.join(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}' for frame in traceback.extract_tb(exc.__traceback__)),
            'publicationAttempted':False})
        raise
    write(folder/'original-work-preparation.json',{'workId':target['workId'],'status':'prepared',
        'readerQuestion':cap['readerQuestion'],'preparedFolder':str(prepared_folder),
        'publicationAttempted':False})
    return {'status':'prepared','publicationAttempted':False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    selection=parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--resume-work')
    selection.add_argument('--acquire-work')
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    operation=resume_bound_work if args.resume_work else acquire_bound_work
    print(json.dumps(operation(args.resume_work or args.acquire_work,args.plan), ensure_ascii=False))
