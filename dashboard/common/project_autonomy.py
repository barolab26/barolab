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

NATIVE_CHANNELS={
    'brunch':('brunch_posting.posting','process_brunch_autonomy_once','brunch'),
    'naver_cafe':('naver_cafe_posting.posting','process_cafe_autonomy_once','cafe'),
    'youtube':('youtube_posting.posting','process_youtube_autonomy_once','youtube'),
}


def prepare_cafe_content(project,cafe_id,part_no,topic,source_queries=None):
    """Produce source-bound content through the existing independent Cafe reviewers; never submit."""
    from naver_cafe_posting import editorial as editor,posting as cafe
    from agents.crew_reasoning import safe
    if project!='naver_cafe' or cafe_id not in cafe.CAFE_POLICIES or type(part_no) is not int or part_no<1:
        raise ValueError('Unregistered Cafe preparation identity')
    if not isinstance(topic,str) or not topic.strip() or len(topic)>300:raise ValueError('Exact reader topic required')
    policy=cafe.CAFE_POLICIES[cafe_id]
    if policy.get('policyMode')=='suspended_banned' or policy.get('restrictionUntil'):
        return {'ok':False,'status':'held','project':project,'reason':'existing_cafe_restriction_preserved'}
    queries=source_queries or []
    if not isinstance(queries,list) or not all(isinstance(q,str) and q.strip() for q in queries):raise ValueError('Source queries must be text')
    folder=editor.OUTPUT/'prepared'/('part-'+str(part_no))/cafe_id
    request={'project':project,'cafeId':cafe_id,'part':part_no,'topic':topic.strip()}
    with locked(folder/'preparation'):
        owned=load(folder/'preparation-request.json')
        if owned and owned!=request:raise ValueError('Prepared part is already bound to a different reader topic')
        status=cafe.load_cafe_status()
        if any(status.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold','pendingEffect')):
            return {'ok':False,'status':'held','project':project,'reason':'original_resume_condition_required'}
        if any(r.get('cafeId')==cafe_id and r.get('part')==part_no for r in status.get('publishedArticles',[])):
            return {'ok':False,'status':'held','project':project,'reason':'existing_article_preserved_no_revision'}
        intent=load(folder/'intent.json')
        if intent.get('status') in ('submitting','submission_unknown','verified_published','verified_updated') or any(intent.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold')):
            return {'ok':False,'status':'held','project':project,'reason':'original_intent_requires_reconciliation'}
        write(folder/'preparation-request.json',request)
        def input_sha():
            from common.editorial_recovery import review_engine_sha256
            return hashlib.sha256(json.dumps({'request':request,'policy':editor.POLICY,
                'engine':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),Path(editor.__file__))},'reviewEngine':review_engine_sha256(),
                'inputs':{name:load(folder/name) for name in ('research.json','candidate.json','reader-review-response.json','claim-review-response.json')}},sort_keys=True).encode()).hexdigest()
        try:
            if queries:
                from common.editorial_recovery import acquire
                acquire(folder,queries)
            previous=load(folder/'preparation-result.json')
            if previous.get('status')=='needs_attention' and previous.get('inputSha256')==input_sha():
                return {**previous,'evidenceName':'cafe_preparation','reusedUnchangedInput':True}
            if (folder/'prepared.json').exists():
                prepared=editor.prepare(cafe_id,editor.read(folder/'document.json'),folder)
            else:prepared=editor.prepare_part(cafe_id,part_no,folder,topic=topic)
            status=cafe.load_cafe_status();status['approvedPreparedPart']=part_no;cafe.save_cafe_status(status)
            result={'ok':True,'status':'prepared','project':project,**request,'prepared':prepared,
                'publicationVerified':False,'nextAction':'run_channel_cycle with an active browser lease, then verify public body'}
        except Exception as exc:
            result={'ok':False,'status':'needs_attention',**request,'reason':safe(str(exc))[:1600],
                'errorType':type(exc).__name__,'publicationVerified':False,'nextAction':'read exact review feedback and supply observed missing-source queries'}
        result['inputSha256']=input_sha()
        write(folder/'preparation-result.json',result)
        index=ROOT/'dashboard/data/cafe/preparation-jobs.json'
        with locked(index.with_suffix('.lock')):
            jobs=load(index);jobs.setdefault('jobs',{})[cafe_id+':'+str(part_no)]={**result,'updatedAt':time.time()};write(index,jobs)
        return {**result,'evidenceName':'cafe_preparation'}


def request_native_channel_cycle(project,request_id):
    """Durable nonblocking handoff to an existing native controller; never infer publication."""
    if project not in NATIVE_CHANNELS:raise ValueError('Unknown native channel')
    if (Path.home()/'EGO_EXEC_DISABLED').exists():return {'status':'held','reason':'execution_disabled','publicationVerified':False}
    from common.runtime_locks import process_start_ticks
    from common.repair_workflow import _failure_cause
    folder=ROOT/'dashboard/data/native-channel-cycles';index=folder/(project+'.json')
    identity=hashlib.sha256(str(request_id).encode()).hexdigest()
    source=load(ROOT/'dashboard/data'/NATIVE_CHANNELS[project][2]/'status.json')
    def stable(v):
        if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if k not in ('checkedAt','updatedAt','generatedAt','collectedAt','lastPoll','lastCheckedAt')}
        if isinstance(v,list):return [stable(x) for x in v]
        return v
    source_sha=hashlib.sha256(json.dumps(stable(source),sort_keys=True).encode()).hexdigest()
    with locked(folder):
        previous=load(index)
        if previous.get('status') in ('starting','running'):
            alive=process_start_ticks(previous.get('pid')) if previous.get('pid') else None
            if previous.get('status')=='starting' or (alive is not None and alive==previous.get('startTicks')):return previous
            previous.update(status='unknown',nextAction='reconcile_original_native_result_no_retry');write(index,previous)
        if previous.get('status')=='unknown':return previous
        if previous.get('requestId')==identity or (_failure_cause(previous.get('result',{})) and previous.get('sourceSha256')==source_sha):return previous
        run=folder/identity;run.mkdir(parents=True,exist_ok=True)
        row={'requestId':identity,'project':project,'status':'starting','sourceSha256':source_sha,
             'owner':'publi','publicationVerified':False,'requestedAt':time.time(),'nextAction':'observe_native_operation_result'}
        write(index,row);write(run/'request.json',row)
        environment=dict(os.environ);environment.pop('BAROLAB_AGENDA_CONTEXT',None)
        environment['PYTHONPATH']=os.pathsep.join([str(ROOT/'dashboard'),str(ROOT),environment.get('PYTHONPATH','')])
        with (run/'operation.log').open('ab') as log:
            child=subprocess.Popen([sys.executable,'-u','-B','-X','utf8','-m','common.project_autonomy',
                '--native-channel',project,'--request-id',identity],cwd=ROOT,env=environment,stdin=subprocess.DEVNULL,
                stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        latest=load(index)
        if latest.get('requestId')==identity and latest.get('status')=='starting':
            row.update(status='running',pid=child.pid,startTicks=process_start_ticks(child.pid));write(index,row)
        return row


def allocation_phase(project, alloc_id):
    if project != 'cf_blog' or not alloc_id:
        return 'default'
    from common.operating_plan import STATE
    from common.conference_dispatch import QUEUE, concrete_requests
    state = load(STATE)
    alloc_row = state.get('publications', {}).get(alloc_id)
    if not alloc_row or alloc_row.get('project') != 'cf_blog':
        return 'default'
    kind = 'parameters'
    pub_args = {'action': 'cf', 'date': alloc_row['day'], 'account': alloc_row['account'], 'slot': alloc_row['slot']}
    pub_key = hashlib.sha256(json.dumps([kind, pub_args], sort_keys=True).encode()).hexdigest()
    pub_path = QUEUE / (pub_key + '.json')
    if pub_path.exists():
        rec = load(pub_path)
        if (rec.get('agendaId') == pub_key and rec.get('kind') == kind and
            rec.get('arguments', {}).get('account') == alloc_row['account'] and
            rec.get('arguments', {}).get('date') == alloc_row['day'] and
            rec.get('arguments', {}).get('slot') == alloc_row['slot'] and
            rec.get('arguments', {}).get('action') == 'cf'):
            return 'publication'
    prep_args = {'action': 'cf-prepare', 'date': alloc_row['day'], 'account': alloc_row['account'], 'slot': alloc_row['slot']}
    prep_key = hashlib.sha256(json.dumps([kind, prep_args], sort_keys=True).encode()).hexdigest()
    prep_path = QUEUE / (prep_key + '.json')
    if prep_path.exists():
        rec = load(prep_path)
        if (rec.get('agendaId') == prep_key and rec.get('kind') == kind and
            rec.get('arguments', {}).get('account') == alloc_row['account'] and
            rec.get('arguments', {}).get('date') == alloc_row['day'] and
            rec.get('arguments', {}).get('slot') == alloc_row['slot'] and
            rec.get('arguments', {}).get('action') == 'cf-prepare' and
            rec.get('status') == 'completed' and
            (rec.get('preparation') or {}).get('preparationVerified') is True):
            choices = concrete_requests(kind, {'action': 'cf-cycle', 'date': None, 'account': None, 'slot': None})
            matching_pub = next((c for c in choices if c.get('action') == 'cf' and c.get('account') == alloc_row['account'] and
                                 c.get('date') == alloc_row['day'] and c.get('slot') == alloc_row['slot']), None)
            if matching_pub:
                return 'publication'
    return 'preparation'


def run_project_cycle(project, allocation_id=None):
    from common import work_agenda as agendas
    if agendas.enabled():agendas.require(project=project)
    from server.agent_tools import _ego_popen
    from common.system_watchdog import is_process_running_match
    if project not in COMMANDS: raise ValueError('Unknown project')
    config = json.loads(CONFIG.read_bytes())
    if config.get('enabled') is not True or project not in config.get('projects', []) or (Path.home()/'EGO_EXEC_DISABLED').exists():
        return {'ok': False, 'status': 'held', 'reason': 'execution_disabled'}
    if project in ('cf_blog','naver_blog','naver_kin','threads'):
        from common.conference_dispatch import request, concrete_requests, QUEUE
        kind = {'naver_kin':'kin','threads':'threads'}.get(project,'parameters')
        if allocation_id is not None:
            if project not in ('cf_blog', 'naver_blog'):
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'reason': 'allocations_supported_for_cf_and_naver_only', 'publicationVerified': False}
            if not isinstance(allocation_id, str) or not re.fullmatch(r'[0-9a-f]{64}', allocation_id):
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'reason': 'invalid_allocation_identity', 'publicationVerified': False}
            from common.operating_plan import STATE
            state = load(STATE)
            alloc_row = state.get('publications', {}).get(allocation_id)
            if not alloc_row:
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'reason': 'allocation_not_found', 'publicationVerified': False}
            if alloc_row.get('project') != project:
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'reason': 'allocation_project_mismatch', 'publicationVerified': False}
            if alloc_row.get('status') == 'conflict_existing_work':
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'reason': alloc_row.get('conflict', 'allocation_conflict'), 'publicationVerified': False}
            if alloc_row.get('status') != 'allocated':
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'reason': 'allocation_not_allocated', 'allocationStatus': alloc_row.get('status'), 'publicationVerified': False}
            pub_act = 'cf' if project == 'cf_blog' else 'naver'
            pub_args = {'action': pub_act, 'date': alloc_row['day'], 'account': alloc_row['account'], 'slot': alloc_row['slot']}
            pub_key = hashlib.sha256(json.dumps([kind, pub_args], sort_keys=True).encode()).hexdigest()
            pub_path = QUEUE / (pub_key + '.json')
            pub_receipt = load(pub_path) if pub_path.exists() else None
            if pub_receipt and not (pub_receipt.get('agendaId') == pub_key and pub_receipt.get('kind') == kind and
                                    pub_receipt.get('arguments', {}).get('account') == alloc_row['account'] and
                                    pub_receipt.get('arguments', {}).get('date') == alloc_row['day'] and
                                    pub_receipt.get('arguments', {}).get('slot') == alloc_row['slot'] and
                                    pub_receipt.get('arguments', {}).get('action') == pub_act):
                pub_receipt = None

            prep_receipt = None
            prep_key = None
            if project == 'cf_blog':
                prep_args = {'action': 'cf-prepare', 'date': alloc_row['day'], 'account': alloc_row['account'], 'slot': alloc_row['slot']}
                prep_key = hashlib.sha256(json.dumps([kind, prep_args], sort_keys=True).encode()).hexdigest()
                prep_path = QUEUE / (prep_key + '.json')
                if prep_path.exists():
                    rec = load(prep_path)
                    if (rec.get('agendaId') == prep_key and rec.get('kind') == kind and
                        rec.get('arguments', {}).get('account') == alloc_row['account'] and
                        rec.get('arguments', {}).get('date') == alloc_row['day'] and
                        rec.get('arguments', {}).get('slot') == alloc_row['slot'] and
                        rec.get('arguments', {}).get('action') == 'cf-prepare'):
                        prep_receipt = rec

            if pub_receipt is not None:
                if pub_receipt.get('status') in ('queued', 'running'):
                    return {'ok': True, 'status': 'awaiting_completion', 'project': project,
                            'allocationId': allocation_id, 'conferenceAgendaId': pub_key,
                            'conferenceRequestedAt': pub_receipt['requestedAt'], 'publicationVerified': False}
                if pub_receipt.get('status') == 'completed':
                    term, _ = terminal_result({'project': project, 'allocationId': allocation_id,
                                               'conferenceAgendaId': pub_key, 'conferenceRequestedAt': pub_receipt['requestedAt']})
                    return {**term, 'allocationId': allocation_id}
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'conferenceAgendaId': pub_key, 'conferenceRequestedAt': pub_receipt.get('requestedAt'),
                        'reason': pub_receipt.get('failureReason') or pub_receipt.get('errorType') or ('existing_receipt_' + str(pub_receipt.get('status'))),
                        'publicationVerified': False, 'attempts': pub_receipt.get('attempts', 1)}

            if prep_receipt is not None:
                if prep_receipt.get('status') in ('queued', 'running'):
                    return {'ok': True, 'status': 'awaiting_completion', 'project': project,
                            'allocationId': allocation_id, 'conferenceAgendaId': prep_key,
                            'conferenceRequestedAt': prep_receipt['requestedAt'], 'publicationVerified': False}
                if prep_receipt.get('status') != 'completed':
                    return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                            'conferenceAgendaId': prep_key, 'conferenceRequestedAt': prep_receipt.get('requestedAt'),
                            'reason': prep_receipt.get('failureReason') or prep_receipt.get('errorType') or ('existing_receipt_' + str(prep_receipt.get('status'))),
                            'publicationVerified': False, 'attempts': prep_receipt.get('attempts', 1)}
                choices = concrete_requests(kind, {'action': 'cf-cycle', 'date': None, 'account': None, 'slot': None})
                matching_pub = next((c for c in choices if c.get('action') == 'cf' and c.get('account') == alloc_row['account'] and
                                     c.get('date') == alloc_row['day'] and c.get('slot') == alloc_row['slot']), None)
                if matching_pub:
                    if project == 'cf_blog':
                        schedule = load(ROOT / 'dashboard/data/cf/daily_schedule.json')
                        item = next((r for r in schedule.get('items', []) if r.get('domain') == alloc_row['account']), {})
                        if item and item.get('allocationId') and item.get('allocationId') != allocation_id and item.get('status') not in ('published', 'unallocated'):
                            return {'ok': False, 'status': 'waiting_existing_work', 'project': project,
                                    'allocationId': allocation_id, 'account': alloc_row['account'],
                                    'dependency': item.get('domain'), 'dependencyStatus': item.get('status'),
                                    'reason': 'waiting_domain_predecessor', 'publicationVerified': False}
                    with agendas.context(None):
                        receipt = request(kind, matching_pub, one=True, automatic=False)
                    if not receipt or not receipt.get('agendaId'):
                        return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                                'reason': (receipt or {}).get('reason') or 'no_conference_receipt', 'publicationVerified': False}
                    return {'ok': True, 'status': 'awaiting_completion', 'project': project, 'allocationId': allocation_id,
                            'conferenceAgendaId': receipt['agendaId'], 'conferenceRequestedAt': receipt['requestedAt'],
                            'publicationVerified': False}
                term, _ = terminal_result({'project': project, 'allocationId': allocation_id,
                                           'conferenceAgendaId': prep_key, 'conferenceRequestedAt': prep_receipt['requestedAt']})
                return {**term, 'allocationId': allocation_id, 'nextCondition': 'waiting_cf_publication_slot_eligibility'}

            if project == 'cf_blog':
                schedule = load(ROOT / 'dashboard/data/cf/daily_schedule.json')
                item = next((r for r in schedule.get('items', []) if r.get('domain') == alloc_row['account']), {})
                if item and item.get('allocationId') and item.get('allocationId') != allocation_id and item.get('status') not in ('published', 'unallocated'):
                    return {'ok': False, 'status': 'waiting_existing_work', 'project': project,
                            'allocationId': allocation_id, 'account': alloc_row['account'],
                            'dependency': item.get('domain'), 'dependencyStatus': item.get('status'),
                            'reason': 'waiting_domain_predecessor', 'publicationVerified': False}
            arguments = {'action': 'cf-cycle' if project == 'cf_blog' else 'naver-cycle',
                          'date': None, 'account': None, 'slot': None}
            choices = concrete_requests(kind, arguments)
            matching_choice = next((c for c in choices if c.get('account') == alloc_row['account'] and
                                    c.get('date') == alloc_row['day'] and c.get('slot') == alloc_row['slot']), None)
            if not matching_choice:
                # A prepared future slot is a normal wait, never a repair failure.
                if project=='cf_blog' and alloc_row.get('publishAt'):
                    from common.operating_plan import allocation_execution
                    readiness=allocation_execution(alloc_row)
                    if readiness.get('status')=='waiting_schedule':
                        return {'ok':True,**readiness,'project':project,'allocationId':allocation_id,
                                'submissionDispatched':False}
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'account': alloc_row['account'], 'slot': alloc_row['slot'], 'day': alloc_row['day'],
                        'reason': 'allocation_slot_not_currently_eligible', 'publicationVerified': False}
            with agendas.context(None):
                receipt = request(kind, matching_choice, one=True, automatic=False)
            if not receipt or not receipt.get('agendaId'):
                return {'ok': False, 'status': 'held', 'project': project, 'allocationId': allocation_id,
                        'reason': (receipt or {}).get('reason') or 'no_conference_receipt', 'publicationVerified': False}
            return {'ok': True, 'status': 'awaiting_completion', 'project': project, 'allocationId': allocation_id,
                    'conferenceAgendaId': receipt['agendaId'], 'conferenceRequestedAt': receipt['requestedAt'],
                    'publicationVerified': False}
        arguments = ({'action':'cf-cycle' if project=='cf_blog' else 'naver-cycle',
                      'date':None,'account':None,'slot':None} if kind=='parameters' else {})
        choices=concrete_requests(kind,arguments)
        from common.operating_plan import allocations
        managed={(r['account'],r['day'],r['slot']) for r in allocations(project)}
        choices.sort(key=lambda a:((a.get('account'),a.get('date'),a.get('slot')) not in managed))
        protected=[]
        receipt=None
        for choice in choices:
            key=hashlib.sha256(json.dumps([kind,choice],sort_keys=True).encode()).hexdigest()
            existing=load(QUEUE/(key+'.json'))
            if existing:
                if existing.get('status') in ('queued','running'):
                    receipt={'agendaId':key,'requestedAt':existing['requestedAt']}
                    break  # Observe the original owner; do not rebind or resubmit.
                protected.append({'conferenceId':key,'status':existing.get('status'),'reason':existing.get('failureReason')})
                continue
            # The scheduler request is the parent, not the child's publication lock.
            # One exact work item per native request avoids changing a bound target mid-loop.
            with agendas.context(None):
                receipt=request(kind,choice,one=True,automatic=False)
            break
        if receipt is None:
            return {'ok':not protected,'status':'held' if protected else 'no_work','project':project,
                    'reason':'existing_work_requires_reconciliation' if protected else 'no_eligible_concrete_work',
                    'protectedWork':protected,'publicationVerified':False}
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


def publish_strategy_link(target_url, *, automatic=False):
    """Bind one selected asset to the existing Threads slot and publication guards."""
    from common import work_agenda as agendas
    from common.conference_dispatch import concrete_requests, request
    import threads_posting.posting as engine
    import sqlite3
    engine._threads_authoring__canonical(target_url, engine._threads_config_HOSTS)
    if automatic and not agendas.autonomous_experiment_allows('threads',target_url=target_url):
        return {'ok':False,'status':'held','project':'threads','reason':'active_experiment_required'}
    if agendas.enabled() and not automatic:agendas.require(project='threads')
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
    receipt=request('threads',{**args,'targetUrl':target_url},one=True,automatic=automatic)
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
            from common.operating_plan import cf_folder
            schedule=load(ROOT/'dashboard/data/cf/daily_schedule.json')
            current=next((r for r in schedule.get('items',[]) if r.get('domain')==identity),{})
            default=folder_for('cf_posting',day,identity)
            folder=cf_folder(current,day,default) if current else default
        else:
            from common.channel_parameters import naver_slots_for_date
            if slot not in naver_slots_for_date(plan,day).get(identity,{}).get('slots',[]):continue
            # Keep an unsubmitted missed slot recoverable; run_naver chooses a
            # future clock. Never roll a catch-up into a different publication day.
            if day == now.date().isoformat() and (now+timedelta(minutes=75)).date()!=now.date():continue
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
        if project == 'cf_blog':
            from common.conference_dispatch import cf_recovery_original, retry_active
            if not agendas.enabled():raise ValueError('CF recovery requires the original owned agenda')
            current = agendas.require(project=project)
            identity, original = cf_recovery_original(current)
            args = original['arguments']
            if args['date'] != target['date'] or args['account'] != target['identity']:
                raise ValueError('Original CF conference does not match failed work')
            retry_active(**({'repair_task_id':repair_task_id,'repair_plan_sha256':repair_plan_sha256} if repair_task_id else {}))
            agenda = {'status':'conference_requested','agendaId':identity,'businessAgendaId':current['id']}
        else:
            args={'action':'naver','date':target['date'],'account':target['identity'],'slot':target['slot']}
            agenda=request('parameters',args)
        if project != 'cf_blog' and agendas.enabled() and agenda.get('status')=='conference_failed':
            from common.conference_dispatch import retry_active
            retry_active(**({'repair_task_id':repair_task_id,'repair_plan_sha256':repair_plan_sha256} if repair_task_id else {}))
        attempts=(load(QUEUE/(agenda['agendaId']+'.json')).get('attempts',1) if agendas.enabled()
                  else prior.get('attempts',1)+1 if prior else 1)
        result={'ok':True,'status':'requested','project':project,'workId':work_id,
                'account':target['identity'],'date':target['date'],'slot':args['slot'],'action':args['action'],
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
        if expected == 'parameters' and receipt.get('arguments',{}).get('action') not in (('cf-cycle','cf','cf-prepare') if result['project']=='cf_blog' else ('naver-cycle','naver')):
            raise ValueError('Conference channel action mismatch')
        if receipt.get('requestedAt') != result.get('conferenceRequestedAt'):
            return {'ok':False, 'status':'unknown', 'project':result['project'],
                    'publicationVerified':False, 'reason':'conference_receipt_superseded'}, receipt
        if result.get('allocationId'):
            alloc_id = result['allocationId']
            from common.operating_plan import STATE
            state = load(STATE)
            alloc_row = state.get('publications', {}).get(alloc_id)
            if not alloc_row or alloc_row.get('project') != result.get('project'):
                return {'ok': False, 'status': 'unknown', 'project': result['project'],
                        'allocationId': alloc_id, 'conferenceAgendaId': identity,
                        'publicationVerified': False, 'reservationVerified': False,
                        'preparationVerified': False, 'reason': 'allocation_identity_mismatch'}, receipt
            args = receipt.get('arguments', {})
            expected_action = ('cf', 'cf-prepare') if result['project'] == 'cf_blog' else ('naver',)
            if (args.get('account') != alloc_row.get('account') or
                args.get('date') != alloc_row.get('day') or
                args.get('slot') != alloc_row.get('slot') or
                args.get('action') not in expected_action):
                return {'ok': False, 'status': 'unknown', 'project': result['project'],
                        'allocationId': alloc_id, 'conferenceAgendaId': identity,
                        'publicationVerified': False, 'reservationVerified': False,
                        'preparationVerified': False, 'reason': 'allocation_receipt_target_mismatch'}, receipt
        if receipt.get('status') in ('queued','running'):return None
        outcomes = receipt.get('outcomes') or []
        prepared=(receipt.get('status')=='completed' and receipt.get('arguments',{}).get('action')=='cf-prepare'
                  and (receipt.get('preparation') or {}).get('preparationVerified') is True)
        status = 'failed'
        if receipt.get('status') == 'completed':
            verified = [row.get('publicationVerified') is True or row.get('reservationVerified') is True for row in outcomes]
            status = 'no_work' if not outcomes else 'completed' if all(verified) else 'partial' if any(verified) else 'unknown'
            if prepared:status='completed'
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
        ok_status = (status == 'completed') if result.get('allocationId') else status in ('completed','no_work')
        terminal_feedback = {'ok': ok_status, 'status': status,
                'outboundLinkVerified': link_verified,
                'project': result['project'], 'conferenceAgendaId': identity,
                'conferenceRequestedAt': result.get('conferenceRequestedAt'),
                'preparationVerified': prepared,
                'publicationVerified': status=='completed' and bool(outcomes) and all(row.get('publicationVerified') is True for row in outcomes),
                'reservationVerified': status=='completed' and bool(outcomes) and all(row.get('reservationVerified') is True for row in outcomes),
                'outcomes': outcomes, 'eligibility': receipt.get('eligibility'),
                'errorType': None if status in ('completed','no_work') else receipt.get('errorType'),
                'reason': ('allocation_unfulfilled_no_work' if (result.get('allocationId') and status == 'no_work') else (None if status in ('completed','no_work') else receipt.get('failureReason'))),
                'controllerEvidenceSha256': hashlib.sha256(raw).hexdigest()}
        if result.get('allocationId'):
            terminal_feedback['allocationId'] = result['allocationId']
        if receipt.get('attempts') is not None:
            terminal_feedback['attempts'] = receipt['attempts']
        elif status not in ('completed', 'no_work'):
            terminal_feedback['attempts'] = 1
        if isinstance(result.get('executorReceipt'), dict):
            exec_rec = dict(result['executorReceipt'])
            pending_term = (status in ('running', 'started', 'queued', 'awaiting_completion', 'unknown')
                            or bool(terminal_feedback.get('pendingEffect')) or bool(receipt.get('pendingEffect')))
            finished_at = None if pending_term else (receipt.get('completedAt') or receipt.get('finishedAt') or exec_rec.get('returnedAt'))
            exec_rec.update(status=status, completed=bool(not pending_term and finished_at), finishedAt=finished_at)
            terminal_feedback['executorReceipt'] = exec_rec
        return terminal_feedback, receipt
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
    expected_args = {'project': result['project']}
    if result.get('allocationId'):
        expected_args['allocation_id'] = result['allocationId']
    if (receipt.get('pid') != result.get('pid') or action.get('tool') != 'run_project_cycle'
            or action.get('argumentsComplete') is not True
            or action.get('args') != expected_args):
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
    proc_feedback = {'ok': outcome == 'completed',
            'status': outcome,
            'project': result['project'], 'receiptPath': str(path), 'pid': result['pid'],
            'exitCode': receipt.get('exitCode'), 'publicationVerified': False,
            'controllerEvidenceSha256': hashlib.sha256(raw).hexdigest()}
    if result.get('allocationId'):
        proc_feedback['allocationId'] = result['allocationId']
    return proc_feedback, receipt


def process_project_autonomy_once():
    from common import work_agenda as agendas
    if agendas.enabled():
        # Existing attempts retain their guards; new work follows the bounded experiment.
        from common.conference_dispatch import request
        config=load(CONFIG)
        if config.get('enabled') and 'threads' in config.get('projects',[]):request('threads',{},automatic=True)
        agendas._top_up_channel_lanes()
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
        state['newWorkStatus']='held_requires_experiment_dispatcher'
        write(STATE,state)
    return False


def acquire_registered_work(task_id, plan_sha256):
    """Prepare only the exact registered failed work; never submit or infer success."""
    from common import repair_workflow as recovery, work_agenda as agendas
    from common.recovery_evidence import task_evidence
    from common.editorial_recovery import repair_conference
    _,row=recovery._recovery_row(task_id,plan_sha256)
    if row.get('step')!='acquire' or row.get('status') not in ('ready','awaiting_inputs'):
        raise ValueError('Registered acquisition phase required')
    plan=row['plan'];target=row.get('observedWorkTarget') or plan['workTarget']
    fresh=task_evidence(plan['projectRoot'],target)
    cap=fresh.get('inputCapability')
    if not cap or cap!=row['discovered']['workEvidence'].get('inputCapability'):
        raise ValueError('Original input capability changed')
    if Path(plan['projectRoot']).resolve()!=ROOT.resolve() or plan['project']!='naver_blog':
        raise ValueError('Local registered Naver preparation required')
    with agendas.context(agendas.token(agendas.get(row['businessAgendaId']))):
        recovery._recovery_resume_guard(row)
        source=Path(plan['sourcePath'])
        from common.conference_dispatch import QUEUE
        if source.is_symlink() or source.resolve().parent!=QUEUE.resolve():
            raise ValueError('Exact native conference source required')
        result=repair_conference(source.stem,resume=False)
    if result.get('status')!='editorial_reviewed':raise ValueError('Original input preparation not verified')
    write(Path(cap['folder'])/'original-work-preparation.json',{
        'taskId':task_id,'planSha256':plan_sha256,'preparedAt':time.time(),**result})
    return result


if __name__=='__main__':
    import argparse,importlib
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--native-channel',choices=list(NATIVE_CHANNELS));mode.add_argument('--acquire-work')
    parser.add_argument('--request-id');parser.add_argument('--plan');options=parser.parse_args()
    if options.acquire_work:
        acquire_registered_work(options.acquire_work,options.plan)
        raise SystemExit(0)
    if not options.request_id or not re.fullmatch(r'[a-f0-9]{64}',options.request_id):raise ValueError('Exact registered native operation required')
    folder=ROOT/'dashboard/data/native-channel-cycles';index=folder/(options.native_channel+'.json')
    request=load(folder/options.request_id/'request.json')
    if request.get('requestId')!=options.request_id or request.get('project')!=options.native_channel:
        raise ValueError('Native operation identity mismatch')
    try:
        module,function,_=NATIVE_CHANNELS[options.native_channel]
        # A manager's explicit publication order is independent of background slot heuristics.
        function='write_next_curriculum_part' if options.native_channel=='brunch' else function
        result=getattr(importlib.import_module(module),function)()
        from common.repair_workflow import _failure_cause
        unknown=isinstance(result,dict) and (result.get('status') in ('unknown','submission_unknown') or _failure_cause(result)=='uncertain_effect')
        request.update(status='unknown' if unknown else 'returned',result=result,returnedAt=time.time(),
            nextAction='reconcile_original_external_effect_no_retry' if unknown else 'verify_native_receipt_and_public_result',publicationVerified=False)
    except Exception as exc:
        request.update(status='failed',errorType=type(exc).__name__,reason=str(exc),returnedAt=time.time(),publicationVerified=False)
    with locked(folder):
        write(folder/options.request_id/'result.json',request)
        if load(index).get('requestId')==options.request_id:write(index,request)
