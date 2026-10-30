"""One registered channel worker at a time; no editorial approval chain."""
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from common.collection_observability import locked, write, load
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'dashboard/data/project-autonomy.json'
STATE = ROOT / 'dashboard/data/project-autonomy-state.json'
COMMANDS = {
    'cf_blog': ['-m', 'common.channel_parameters', 'cf-cycle'],
    'naver_blog': ['-m', 'common.channel_parameters', 'naver-cycle'],
    'naver_kin': ['-m', 'common.conference_dispatch', 'kin'],
    'threads': ['-m', 'common.conference_dispatch', 'threads'],
    'legacy_remodel': ['-m', 'common.content_maintenance'],
}


def run_project_cycle(project):
    from common import work_agenda as agendas
    if agendas.enabled():agendas.require(project=project)
    from server.agent_tools import _ego_popen
    from common.system_watchdog import is_process_running_match
    if project not in COMMANDS: raise ValueError('Unknown project')
    config = json.loads(CONFIG.read_bytes())
    if config.get('enabled') is not True or project not in config.get('projects', []) or (Path.home()/'EGO_EXEC_DISABLED').exists():
        return {'ok': False, 'status': 'held', 'reason': 'execution_disabled'}
    if project in ('cf_blog','naver_blog','naver_kin','threads'):
        from common.conference_dispatch import request
        kind = {'naver_kin':'kin','threads':'threads'}.get(project,'parameters')
        arguments = ({'action':'cf-cycle' if project=='cf_blog' else 'naver-cycle',
                      'date':None,'account':None,'slot':None} if kind=='parameters' else {})
        receipt = request(kind, arguments, one=True)
        if not receipt.get('agendaId'):return {'ok':True,'status':'no_work','project':project,'reason':receipt.get('reason'),'publicationVerified':False}
        return {'ok':True, 'status':'awaiting_completion', 'project':project,
                'conferenceAgendaId':receipt['agendaId'], 'conferenceRequestedAt':receipt['requestedAt'],
                'publicationVerified':False}
    command = COMMANDS[project]
    marker = ' '.join(command[1:]) if command[0]=='-m' else str(ROOT/command[0])
    if is_process_running_match(marker):
        return {'ok': False, 'status': 'busy', 'project': project}
    child = _ego_popen([sys.executable,'-u','-B','-X','utf8',*command],cwd=str(ROOT),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'ok':True,'status':'running','project':project,'pid':child.pid,'receiptPath':child.ego_receipt_path,'publicationVerified':False}


def publish_strategy_link(target_url):
    """Bind one selected asset to the existing Threads slot and publication guards."""
    from common import work_agenda as agendas
    from common.conference_dispatch import concrete_requests, request
    import threads_posting.posting as engine
    import sqlite3
    engine._threads_authoring__canonical(target_url, engine._threads_config_HOSTS)
    if agendas.enabled():agendas.require(project='threads')
    config=load(CONFIG)
    if config.get('enabled') is not True or 'threads' not in config.get('projects',[]) or (Path.home()/'EGO_EXEC_DISABLED').exists():
        return {'ok':False,'status':'held','project':'threads','reason':'execution_disabled'}
    choices=concrete_requests('threads',{})
    if not choices:return {'ok':False,'status':'held','project':'threads','reason':'no_due_slot','targetUrl':target_url}
    args=choices[0]
    if args.get('partId'):
        from contextlib import closing
        with closing(sqlite3.connect(Path(engine._threads_config_DB).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            part=db.execute('SELECT document FROM parts WHERE part_id=?',(args['partId'],)).fetchone()
        if not part or json.loads(part[0]).get('source',{}).get('url')!=target_url:
            return {'ok':False,'status':'held','project':'threads','reason':'existing_slot_has_different_content','targetUrl':target_url}
    if engine._threads_authoring__slot_mode(engine._threads_config_load(),args['slot'])!='cf_inbound':
        return {'ok':False,'status':'held','project':'threads','reason':'slot_not_cf_inbound','targetUrl':target_url}
    receipt=request('threads',{**args,'targetUrl':target_url},one=True)
    if not receipt.get('agendaId'):
        return {'ok':False,'status':'held','project':'threads','reason':'no_conference_receipt','targetUrl':target_url}
    return {'ok':True,'status':'awaiting_completion','project':'threads','targetUrl':target_url,
            'conferenceAgendaId':receipt['agendaId'],'conferenceRequestedAt':receipt['requestedAt'],'publicationVerified':False}


def recoverable_work(project):
    """Exact current approved slots that failed before any submission evidence."""
    from datetime import datetime, timedelta
    from common.channel_parameters import policy, KST, folder_for
    from common.recovery_evidence import failure_targets, artifact_folder, read_object
    if project not in ('cf_blog','naver_blog'):return []
    now=datetime.now(KST);plan=policy();result=[]
    for target in failure_targets(ROOT,project):
        if target['status'] not in ('failed','error') or target['submissionStarted']:continue
        day=target['date'];identity=target['identity'];slot=target['slot']
        if day not in (now.date().isoformat(),(now+timedelta(days=1)).date().isoformat()):continue
        if day<plan['effectiveDate']:continue
        if project=='cf_blog':
            if day!=now.date().isoformat() or identity not in plan['cf']:continue
            folder=folder_for('cf_posting',day,identity)
        else:
            if slot not in plan['naver'].get(identity,{}).get('slots',[]):continue
            if datetime.fromisoformat(day+'T'+slot).replace(tzinfo=KST)<now+timedelta(minutes=30):continue
            folder=folder_for('naver_blog_posting',day,identity+'-'+slot.replace(':',''))
            evidence=read_object(ROOT/'dashboard/data/naver/public-verification.json').get('evidence',[])
            attempts=read_object(ROOT/'dashboard/data/naver/automation-journal.json').get('attempts',[])
            same=lambda r: r.get('account')==identity and (r.get('publicationDate') or str(r.get('reserveTime') or '')[:10])==day and (r.get('scheduledSlot') or str(r.get('reserveTime') or '')[-5:])==slot
            if any(same(r) and (r.get('publicPublicationVerified') is True or any(r.get(k) for k in ('submittedAt','submissionStarted','submissionStartedAt')) or r.get('phase') in ('done','reserved','submitting','submission_unknown')) for r in evidence+attempts if isinstance(r,dict)):continue
        if artifact_folder(ROOT,target)!=folder.resolve():continue
        # Even an unconfirmed receipt fences resubmission; the existing engine owns reconciliation.
        if any(folder.glob('*publication*receipt*')) or (folder/'reservation-evidence.json').exists():continue
        result.append(target)
    return result


def recover_project_work(project, work_id, *, repair_task_id=None, repair_plan_sha256=None):
    from common import work_agenda as agendas
    if agendas.enabled():agendas.require(project=project)
    from common.conference_dispatch import request, QUEUE
    if project not in ('cf_blog','naver_blog') or not isinstance(work_id,str) or not re.fullmatch(r'[0-9a-f]{64}',work_id):
        raise ValueError('Invalid exact work recovery identity')
    config=json.loads(CONFIG.read_bytes())
    if config.get('enabled') is not True or project not in config.get('projects',[]) or (Path.home()/'EGO_EXEC_DISABLED').exists():
        return {'ok':False,'status':'held','project':project,'reason':'execution_disabled'}
    folder=STATE.parent/'project-work-recovery'
    with locked(folder):
        path=folder/(work_id+'.json')
        prior=load(path)
        if prior:
            if prior.get('project')!=project:raise ValueError('Recovery project identity mismatch')
            agenda=load(QUEUE/(prior['conference']['agendaId']+'.json'))
            if agendas.enabled():
                current=agendas.require(project=project)
                # The exact conference owns submission attempts; old recovery counters counted requests.
                native_retry=(agenda.get('businessAgendaId')==current['id'] and agenda.get('status')=='failed' and (agenda.get('attempts',1)<2 or bool(repair_task_id and repair_plan_sha256)))
            else:native_retry=False
            if not native_retry and (prior.get('attempts',1)>=2 or agenda.get('status')!='failed' or agenda.get('retryAt',float('inf'))>time.time()):
                return completion_receipt(prior)
        target=next((t for t in recoverable_work(project) if t['workId']==work_id),None)
        if target is None:
            return {'ok':False,'status':'held','project':project,'reason':'same_work_not_eligible_or_requires_reconciliation'}
        args={'action':'cf' if project=='cf_blog' else 'naver','date':target['date'],
              'account':target['identity'],'slot':target['slot']}
        # Same conference identity as the standard scheduler, never an alternate engine.
        agenda=request('parameters',args)
        if agendas.enabled() and agenda.get('status')=='conference_failed':
            from common.conference_dispatch import retry_active
            retry_active(**({'repair_task_id':repair_task_id,'repair_plan_sha256':repair_plan_sha256} if repair_task_id else {}))
        attempts=(load(QUEUE/(agenda['agendaId']+'.json')).get('attempts',1) if agendas.enabled()
                  else prior.get('attempts',1)+1 if prior else 1)
        result={'ok':True,'status':'requested','project':project,'workId':work_id,
                'account':target['identity'],'date':target['date'],'slot':target['slot'],
                'conference':agenda,'publicationVerified':False,'requestedAt':time.time(),
                'attempts':attempts,
                'attemptHistory':(prior.get('attemptHistory',[])+[{k:prior[k] for k in ('conference','requestedAt')}]) if prior else []}
        write(path,result)
        return completion_receipt(result)


def completion_receipt(result):
    conference=result.get('conference') or {}
    if conference.get('agendaId'):
        return {**result,'status':'awaiting_completion','conferenceAgendaId':conference['agendaId'],
                'conferenceRequestedAt':conference.get('requestedAt')}
    return result


def strategy_link_state(database, arguments, target):
    import sqlite3
    from contextlib import closing
    from urllib.parse import urlsplit
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            rows=db.execute('SELECT kind,state,permalink,document FROM parts WHERE account_key=? AND publication_date=? AND slot=?',
                            (arguments.get('account'),arguments.get('date'),arguments.get('slot'))).fetchall()
        parts=[(kind,state,address,json.loads(document)) for kind,state,address,document in rows]
        parts=[p for p in parts if p[3].get('source',{}).get('url')==target]
        public=lambda p:p[1]=='published_verified' and urlsplit(str(p[2] or '')).scheme=='https' and urlsplit(str(p[2] or '')).hostname in ('threads.com','www.threads.com','threads.net','www.threads.net')
        main=any(p[0]=='main' and public(p) for p in parts)
        selected=urlsplit(target)
        def linked(part):
            outbound=urlsplit(part[3].get('outbound_url') or '')
            return (outbound.scheme,outbound.hostname,outbound.path)==(selected.scheme,selected.hostname,selected.path)
        reply=any(p[0]=='followup' and public(p) and linked(p) for p in parts)
        if main and reply:return 'verified'
        if any(p[1] in ('sending_intent','submitted_unknown','api_submitted') for p in parts):return 'waiting'
        if main and any(p[0]=='followup' and p[1]=='queued' and linked(p) for p in parts):return 'waiting'
        return 'failed'
    except (OSError,sqlite3.Error,ValueError,TypeError):return 'unknown'


def terminal_result(result):
    """Read only the exact registered child; exit zero is not publication proof."""
    if result.get('conferenceAgendaId'):
        from common.conference_dispatch import QUEUE
        identity = result['conferenceAgendaId']
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{64}',identity):
            raise ValueError('Invalid conference receipt')
        path = QUEUE / (identity + '.json')
        if path.is_symlink():raise ValueError('Unregistered conference receipt')
        raw = path.read_bytes(); receipt = json.loads(raw)
        expected = {'cf_blog':'parameters','naver_blog':'parameters','naver_kin':'kin','threads':'threads'}.get(result.get('project'))
        if not expected or receipt.get('agendaId') != identity or receipt.get('kind') != expected:
            raise ValueError('Conference identity mismatch')
        if expected == 'parameters' and receipt.get('arguments',{}).get('action') not in (('cf-cycle','cf') if result['project']=='cf_blog' else ('naver-cycle','naver')):
            raise ValueError('Conference channel action mismatch')
        if receipt.get('requestedAt') != result.get('conferenceRequestedAt'):
            return {'ok':False, 'status':'unknown', 'project':result['project'],
                    'publicationVerified':False, 'reason':'conference_receipt_superseded'}, receipt
        if receipt.get('status') in ('queued','running'):return None
        outcomes = receipt.get('outcomes') or []
        status = 'failed'
        if receipt.get('status') == 'completed':
            verified = [row.get('publicationVerified') is True or row.get('reservationVerified') is True for row in outcomes]
            status = 'no_work' if not outcomes else 'completed' if all(verified) else 'partial' if any(verified) else 'unknown'
        link_verified=False
        if expected=='threads' and result.get('targetUrl'):
            if receipt.get('arguments',{}).get('targetUrl')!=result['targetUrl']:
                status='unknown'
            else:
                from threads_posting.posting import _threads_config_DB
                link=strategy_link_state(_threads_config_DB,receipt.get('arguments',{}),result['targetUrl'])
                if link=='waiting':return None
                link_verified=link=='verified'
                status='completed' if link_verified else 'unknown' if link=='unknown' else 'failed'
        return {'ok':status in ('completed','no_work'), 'status':status,
                'outboundLinkVerified':link_verified,
                'project':result['project'], 'conferenceAgendaId':identity,
                'publicationVerified':status=='completed' and all(row.get('publicationVerified') is True for row in outcomes),
                'reservationVerified':status=='completed' and bool(outcomes) and all(row.get('reservationVerified') is True for row in outcomes),
                'outcomes':outcomes, 'eligibility':receipt.get('eligibility'),
                'errorType':receipt.get('errorType'), 'reason':receipt.get('failureReason'),
                'controllerEvidenceSha256':hashlib.sha256(raw).hexdigest()}, receipt
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
            if os.name == 'nt':
                from common.runtime_locks import process_start_ticks
                raw_ticks = process_start_ticks(receipt['pid'])
                ticks = int(raw_ticks) if raw_ticks is not None else None
                same = ticks is not None and receipt.get('processStartTicks') in (None, ticks)
            else:
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
    from common import work_agenda as agendas
    if agendas.enabled():
        # Channel timers propose concrete due work; no five-minute no-work staff meetings.
        from common.conference_dispatch import request
        config=load(CONFIG)
        if config.get('enabled') and 'threads' in config.get('projects',[]):request('threads',{})
        return False
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
            if os.name != 'nt' and project in ('cf_blog','naver_blog'):
                from common.channel_parameters import policy, KST
                from datetime import datetime
                if datetime.now(KST).date().isoformat() >= policy()['effectiveDate']:
                    row.update(dispatchOwner='barolab-parameters.timer',status='timer_managed')
                    continue
            if os.name != 'nt' and project=='naver_kin':
                row.update(dispatchOwner='barolab-kin.timer',status='timer_managed')
                continue
            if now<row.get('nextRunAt',0):continue
            actor='doctor' if project=='legacy_remodel' else 'publi'
            action={'agent':actor,'tool':'run_project_cycle','args':{'project':project}}
            request_id=f'autonomy-basic:{project}:{int(now)}'
            row.update(requestId=request_id,action=action,lastStartedAt=now,nextRunAt=now+300,status='requested')
            write(STATE,state);enqueue_staff_request(request_id,[action])
            from common.crew_chat_bridge import emit_work_event
            emit_work_event(actor='jarvis',actor_label='팀장',task_id=request_id,phase='completed',stage='project-instruction-issued',requested_to=actor,output_kind=project+' 기본 워크플로우 실행 배정')
            return True
        write(STATE,state)
    return False
