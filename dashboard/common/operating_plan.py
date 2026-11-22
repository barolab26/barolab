"""Manager-owned allocation and follow-through; publication volume is a decision, not a quota."""
import hashlib
import json
import re
import time
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from common.collection_observability import load, write, locked

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT/'dashboard/data'
STATE = DATA/'operating-plan.json'
KST = ZoneInfo('Asia/Seoul')


def enabled():
    return load(DATA/'daily_schedule.json').get('operatingMode') == 'adaptive'


def cap_reached(used, legacy_limit):
    return False if enabled() else legacy_limit is not None and used >= legacy_limit


def remaining(used, legacy_limit):
    return None if enabled() or legacy_limit is None else max(0, legacy_limit-used)


def account_decision(project, account):
    return load(STATE).get('accounts', {}).get(project+':'+account, {}) if enabled() else {}


def account_available(project, account, now=None):
    row = account_decision(project, account)
    if row.get('mode') != 'pause':
        return True
    return (now or time.time()) >= row.get('reviewAt', 0)


def _accounts():
    policy = load(DATA/'daily_schedule.json')
    return {'naver_blog':set(policy.get('naver', {})), 'cf_blog':set(policy.get('cf', {})),
            'naver_kin':{'adinfo0905','stone0747'}, 'threads':{'mustpickinfo'}}


def allocation_conflict(row):
    policy=load(DATA/'daily_schedule.json')
    if row['project']=='naver_blog':
        carry=policy.get('legacySlotsCarryThrough')
        if carry and row['day']<=carry and row['slot'] in policy.get('naver',{}).get(row['account'],{}).get('slots',[]):
            return 'existing_committed_naver_slot_choose_a_distinct_time'
    if row['project']=='cf_blog':
        schedule=load(DATA/'cf/daily_schedule.json')
        for current in schedule.get('items',[]):
            if (schedule.get('date')==row['day'] and current.get('domain')==row['account']
                    and current.get('scheduledTime')==row['slot'] and current.get('allocationId')!=row['id']
                    and current.get('status')!='unallocated'):
                return 'existing_cf_work_owns_this_time_choose_a_distinct_allocation'
    return None


_PROTECTED_STATES = frozenset({
    'protected_hold', 'submitting', 'unknown', 'held', 'blocked',
    'preparation_unknown', 'preparation_held', 'needs_reconciliation', 'submission_unknown',
})
_PROTECTED_REASONS = frozenset({
    'user_takeover', 'auth_required', 'manual_stop',
    'account_space_control_required', 'pending_effect', 'submission_unknown',
})
_PROTECTED_FLAGS = ('pendingEffect', 'manualResolutionRequired', 'manualStop', 'userTakeover', 'reviewBudgetHold')


def _dict_is_protected(d):
    if not isinstance(d, dict):
        return False
    if any(bool(d.get(k)) for k in _PROTECTED_FLAGS):
        return True
    if d.get('status') in _PROTECTED_STATES or d.get('submissionState') in _PROTECTED_STATES or d.get('state') in _PROTECTED_STATES:
        return True
    if d.get('lifecycleStage') == 'uncertain_or_protected_hold':
        return True
    for k in ('reason', 'reasonCode', 'failureReason', 'errorType', 'errorCode'):
        val = d.get(k)
        if isinstance(val, str) and val in _PROTECTED_REASONS:
            return True
    return False


def _is_protected_action_or_receipt(action, receipt):
    if _dict_is_protected(action) or _dict_is_protected(receipt):
        return True
    if isinstance(receipt, dict):
        if _dict_is_protected(receipt.get('currentExecution')):
            return True
        for item in receipt.get('results', []):
            if not isinstance(item, dict):
                continue
            if _dict_is_protected(item) or _dict_is_protected(item.get('result')) or _dict_is_protected(item.get('hostReport')):
                return True
    return False


def reconcile_action_receipt(action, receipt, now=None, expected_request_id=None):
    if not isinstance(action, dict) or not isinstance(receipt, dict) or not receipt.get('status'):
        return False
    act_req = action.get('requestId')
    req_id = act_req if act_req is not None else expected_request_id
    rec_req = receipt.get('requestId')
    if req_id is not None:
        if act_req is not None and expected_request_id is not None and act_req != expected_request_id:
            return False
        if rec_req != req_id:
            rpath = str(action.get('receiptPath') or '')
            if rec_req is not None or Path(rpath).stem != hashlib.sha256(str(req_id).encode()).hexdigest():
                return False
    elif rec_req is not None:
        return False
    act_task = action.get('taskId')
    rec_task = receipt.get('taskId')
    if act_task is not None and rec_task != act_task:
        return False
    if act_task is None and rec_task is not None and req_id is None:
        return False
    now = time.time() if now is None else now
    protected = _is_protected_action_or_receipt(action, receipt)
    if protected:
        pub_ok = False
        res_ok = False
        stage = 'uncertain_or_protected_hold'
        target_status = (action.get('status') if action.get('status') in _PROTECTED_STATES
                         else receipt.get('status') if receipt.get('status') in _PROTECTED_STATES else 'held')
    else:
        results = [r.get('result') or {} for r in receipt.get('results', []) if isinstance(r, dict)]
        rec_ok = receipt.get('status') == 'completed'
        pub_ok = rec_ok and bool(results) and all(r.get('publicationVerified') is True or r.get('publicPublicationVerified') is True for r in results)
        res_ok = rec_ok and bool(results) and all(r.get('reservationVerified') is True for r in results)
        sched_ok = rec_ok and bool(results) and all(r.get('status') in ('waiting_schedule', 'reserved_verified') for r in results)
        prep_ok = rec_ok and bool(results) and all(r.get('status') == 'prepared' for r in results)
        raw_stage = ('published_verified' if pub_ok else 'reserved_verified' if res_ok else 'waiting_schedule' if sched_ok
                     else 'prepared' if prep_ok else 'preparation_failed' if receipt.get('status') == 'failed' else receipt.get('status', 'queued'))
        stage = lifecycle_stage(raw_stage, publication_verified=pub_ok, reservation_verified=res_ok, protected=False)
        target_status = receipt.get('status')
    changed = (action.get('status') != target_status or action.get('lifecycleStage') != stage
               or action.get('publicationVerified') != pub_ok or action.get('reservationVerified') != res_ok)
    if changed:
        action.update(status=target_status, lifecycleStage=stage,
                      publicationVerified=pub_ok, reservationVerified=res_ok, checkedAt=now)
        if protected and bool(receipt.get('pendingEffect')):
            action['pendingEffect'] = True
    return changed


def reconcile_allocations():
    now=time.time()
    with locked(DATA/'operating-plan'):
        state=load(STATE);changed=False
        for row in state.get('publications',{}).values():
            conflict=allocation_conflict(row)
            if conflict and row.get('status')=='allocated':
                row.update(status='conflict_existing_work',conflict=conflict,checkedAt=now);changed=True
            execution=allocation_execution(row)
            if row.get('executionReview')!=execution:
                row['executionReview']=execution;row['executionChangedAt']=now;changed=True
        for req_key,action in state.get('actions',{}).items():
            if not isinstance(action,dict):continue
            rpath=Path(action.get('receiptPath',''))
            if not rpath.is_absolute() or not rpath.resolve().is_relative_to(DATA.resolve()) or not rpath.is_file():
                continue
            receipt=load(rpath)
            if isinstance(receipt,dict) and receipt.get('status'):
                if reconcile_action_receipt(action,receipt,now,expected_request_id=req_key):
                    changed=True
        if changed:write(STATE,state)
        return changed


def _goal_observations(goal_id='', observations=None):
    if isinstance(observations, list):
        return [e for e in observations if isinstance(e, dict) and e.get('id')]
    if isinstance(goal_id, str) and goal_id.strip():
        for folder in (DATA / 'chats/reasoning-goals', ROOT / 'dashboard/data/chats/reasoning-goals',
                       DATA / 'crew-goals', ROOT / 'dashboard/data/crew-goals'):
            path = folder / (goal_id.strip() + '.json')
            if path.is_file():
                doc = load(path)
                if isinstance(doc.get('observations'), list):
                    return [e for e in doc['observations'] if isinstance(e, dict) and e.get('id')]
    return None


def _action_matches_reviewed_url(act, url, request_id=None, task_id=None):
    if not isinstance(act, dict) or not isinstance(url, str) or not url:
        return False
    if act.get('status') in ('held', 'failed', 'unknown', 'submitting', 'blocked') or act.get('pendingEffect'):
        return False
    if request_id and act.get('requestId') != request_id:
        return False
    if task_id and act.get('taskId') != task_id:
        return False
    target = act.get('exactTarget') or (act.get('action', {}) or {}).get('args') or {}
    if not isinstance(target, dict):
        target = {}
    target_url = target.get('url') or target.get('target_url') or target.get('publicUrl') or target.get('articleUrl')
    receipt_urls = set()
    receipt_path = act.get('receiptPath')
    if isinstance(receipt_path, str) and receipt_path:
        path = Path(receipt_path)
        if path.is_absolute() and path.resolve().is_relative_to(DATA.resolve()) and path.is_file():
            receipt = load(path)
            if receipt.get('status') not in (None, 'completed') or receipt.get('pendingEffect'):
                return False
            for item in receipt.get('results', []):
                res = item.get('result') if isinstance(item, dict) else {}
                if not isinstance(res, dict):
                    continue
                for k in ('url', 'publicUrl', 'articleUrl', 'target_url'):
                    if isinstance(res.get(k), str) and res[k]:
                        receipt_urls.add(res[k])
    if target_url:
        if target_url != url:
            return False
        if receipt_urls and receipt_urls != {url}:
            return False
        return True
    if receipt_urls:
        return receipt_urls == {url}
    return False


def _result_verifies_url(res, url, require_acquisition=False):
    if not isinstance(res, dict) or not isinstance(url, str) or not url:
        return False
    if (res.get('ok') is False
            or res.get('status') in ('failed', 'held', 'busy', 'partial', 'unknown', 'error', 'blocked', 'needs_attention', 'review_required')
            or res.get('complete') is False or res.get('reconciled') is False
            or res.get('limited') is True or res.get('provisional') is True
            or res.get('collectionError') or res.get('budgetHold')
            or res.get('manualResolutionRequired') or res.get('pendingEffect')
            or res.get('detailRequired') is True):
        return False
    res_url = res.get('url') or res.get('publicUrl') or res.get('articleUrl')
    if res_url == url:
        if require_acquisition:
            return (res.get('complete') is True and res.get('reconciled') is True
                    and res.get('limited') is False and res.get('status') == 'collected'
                    and type(res.get('qualifiedSessions')) is int)
        return bool(
            (res.get('complete') is True and res.get('reconciled') is True and res.get('limited') is False and res.get('status') == 'collected')
            or res.get('publicPublicationVerified') is True
            or res.get('publicationVerified') is True
            or res.get('status') in ('collected', 'verified_published', 'published_verified')
            or type(res.get('qualifiedSessions')) is int
            or (isinstance(res.get('sessions'), (int, float)) and not isinstance(res.get('sessions'), bool))
            or (isinstance(res.get('estimatedRevenue'), (int, float)) and not isinstance(res.get('estimatedRevenue'), bool))
        )
    for key in ('data', 'results', 'pages', 'items', 'evidence', 'outcomes'):
        child = res.get(key)
        if isinstance(child, dict):
            if _result_verifies_url(child, url, require_acquisition=require_acquisition):
                return True
        elif isinstance(child, list):
            for entry in child:
                if isinstance(entry, dict):
                    inner = entry.get('result') if isinstance(entry.get('result'), dict) else entry
                    if _result_verifies_url(inner, url, require_acquisition=require_acquisition):
                        return True
    return False


def allocate(arguments, *, actor='jarvis', goal_id='', now=None, observations=None):
    """Accept typed operating decisions only. Never execute code or alter a submitted document."""
    if not enabled() or actor != 'jarvis':
        raise ValueError('Manager operating mandate required')
    now = time.time() if now is None else now
    known = _accounts()
    publications = arguments.get('publications', [])
    decisions = arguments.get('accounts', [])
    if not isinstance(publications,list) or not isinstance(decisions,list) or not publications and not decisions:
        raise ValueError('Concrete allocation or account decision required')
    goal_obs = _goal_observations(goal_id, observations)
    known_obs_ids = {e['id'] for e in goal_obs} if goal_obs is not None else None
    normalized = []
    for row in publications:
        project, account = row.get('project'), row.get('account')
        if account not in known.get(project, set()):
            raise ValueError('Unregistered publication account')
        when = datetime.fromisoformat(str(row.get('publishAt','')).replace('Z','+00:00'))
        if when.tzinfo is None or when.timestamp() <= now or when.second or when.microsecond:
            raise ValueError('Future timezone-aware minute required; no backdating')
        topic, why = row.get('topic'), row.get('why')
        if not isinstance(topic,str) or not topic.strip() or not isinstance(why,str) or not why.strip():
            raise ValueError('Reader topic and business rationale required')
        when = when.astimezone(KST)
        identity = hashlib.sha256(json.dumps([project,account,when.isoformat()],ensure_ascii=False).encode()).hexdigest()
        ev_ids = [x for x in (row.get('evidenceIds') or arguments.get('evidenceIds') or []) if isinstance(x, str) and x.strip()]
        if known_obs_ids is not None and ev_ids and not set(ev_ids).issubset(known_obs_ids):
            raise ValueError('Unknown allocation observation')
        obs_validated = bool(ev_ids and known_obs_ids is not None and set(ev_ids).issubset(known_obs_ids))
        normalized.append({'id':identity,'project':project,'account':account,'publishAt':when.isoformat(),
            'day':when.date().isoformat(),'slot':when.strftime('%H:%M'),'topic':topic.strip(),'why':why,
            'owner':row.get('owner') or 'publi',
            'exactTarget':{'project':project,'account':account,'day':when.date().isoformat(),'slot':when.strftime('%H:%M'),'topic':topic.strip()},
            'evidenceIds':ev_ids,
            'observationsValidated':obs_validated,
            'rationaleBound':bool(obs_validated and row.get('expectedOutcome') and row.get('verificationMethod') and (row.get('nextCheckAt') or row.get('publishAt'))),
            'expectedOutcome':str(row.get('expectedOutcome') or 'verified_publication_or_reservation_then_acquisition_check'),
            'verificationMethod':str(row.get('verificationMethod') or ('cf_publication_receipt_and_inspect_url_acquisition' if project=='cf_blog' else 'naver_public_verification_and_performance')),
            'nextCheckAt':str(row.get('nextCheckAt') or when.isoformat()),
            'lifecycleStage':'queued_or_accepted',
            'goalId':goal_id,'createdAt':now,'status':'allocated','publicationVerified':False,'reservationVerified':False,'businessOutcomeVerified':False})
    account_rows = []
    for row in decisions:
        project, account = row.get('project'), row.get('account')
        if account not in known.get(project,set()) or row.get('mode') not in ('expand','explore','reduce','pause'):
            raise ValueError('Invalid account decision')
        review = datetime.fromisoformat(str(row.get('reviewAt','')).replace('Z','+00:00'))
        if review.tzinfo is None or review.timestamp() <= now or not row.get('why'):
            raise ValueError('Account decision needs a reason and future reassessment')
        ev_ids = [x for x in (row.get('evidenceIds') or arguments.get('evidenceIds') or []) if isinstance(x, str) and x.strip()]
        if known_obs_ids is not None and ev_ids and not set(ev_ids).issubset(known_obs_ids):
            raise ValueError('Unknown allocation observation')
        obs_validated = bool(ev_ids and known_obs_ids is not None and set(ev_ids).issubset(known_obs_ids))
        account_rows.append({**row,'owner':'jarvis','exactTarget':{'project':project,'account':account},
            'evidenceIds':ev_ids,
            'observationsValidated':obs_validated,
            'rationaleBound':bool(obs_validated and row.get('expectedOutcome') and row.get('verificationMethod') and row.get('reviewAt')),
            'expectedOutcome':str(row.get('expectedOutcome') or ('account_'+row['mode']+'_reassessment')),
            'verificationMethod':str(row.get('verificationMethod') or 'operating_plan_account_review'),
            'nextCheckAt':review.isoformat(),'businessOutcomeVerified':False,
            'reviewAt':review.timestamp(),'goalId':goal_id,'decidedAt':now})
    conflicts=[]
    for row in normalized:
        conflict=allocation_conflict(row)
        if conflict:
            row.update(status='conflict_existing_work',conflict=conflict)
            conflicts.append({'id':row['id'],'project':row['project'],'account':row['account'],'publishAt':row['publishAt'],'reason':conflict})
    with locked(DATA/'operating-plan'):
        state = load(STATE)
        work = state.setdefault('publications',{})
        for row in normalized:
            previous = work.get(row['id'])
            if previous and previous['topic'] != row['topic']:
                raise ValueError('Existing allocation identity belongs to another topic')
        for row in normalized:
            work.setdefault(row['id'],row)
        for row in account_rows:
            key=row['project']+':'+row['account']
            previous=state.setdefault('accounts',{}).get(key)
            if previous:
                state.setdefault('accountHistory',[]).append(previous)
            state['accounts'][key]=row
        state.update(schema='barolab-operating-plan-v1',updatedAt=now)
        write(STATE,state)
    return {'ok':not conflicts,'status':'allocation_conflict' if conflicts else 'allocated',
            'allocationIds':[r['id'] for r in normalized if r['status']=='allocated'],'conflicts':conflicts,
            'accountDecisions':len(account_rows),'publicationVerified':False}


def allocations(project, account=None, day=None):
    if not enabled():
        return []
    return sorted([r for r in load(STATE).get('publications',{}).values()
        if r.get('status')=='allocated' and r['project']==project and (account is None or r['account']==account)
        and (day is None or r['day']==day)],key=lambda r:r['publishAt'])


def naver_slots(plan, day):
    result={k:{**v,'slots':list(v['slots'])} for k,v in plan.items()}
    carry=load(DATA/'daily_schedule.json').get('legacySlotsCarryThrough')
    if enabled() and carry and day>carry:
        for settings in result.values():settings['slots']=[]
        for row in load(DATA/'naver/automation-journal.json').get('attempts',[]):
            account=row.get('account');reserve=str(row.get('reserveTime') or '')
            if account in result and reserve[:10]==day:
                slot=row.get('scheduledSlot') or reserve[11:16]
                if slot and slot not in result[account]['slots']:result[account]['slots'].append(slot)
    for row in allocations('naver_blog',day=day):
        if row['account'] in result:
            slots=result[row['account']]['slots']
            if row['slot'] not in slots:
                slots.append(row['slot']);slots.sort()
    return result


def topic(project, account, day, slot):
    return next((r['topic'] for r in allocations(project,account,day) if r['slot']==slot),None)


def cf_folder(item, day, default=None):
    from cf_posting import posting as cf
    value=item.get('artifactFolder')
    if not value and default is not None:return Path(default)
    path=(Path(value) if Path(value).is_absolute() else cf.BASE_DIR/value) if value else cf.BASE_DIR/'output/scheduled'/day/item['domain']
    path=path.resolve()
    if not path.is_relative_to((cf.BASE_DIR/'output').resolve()):
        raise ValueError('CF artifact outside channel output')
    return path


def prepared_cf_asset(day,domain):
    """Read a reviewed unsubmitted asset; allocation and final publish guards stay separate."""
    from common.cf_recovery import prepared_revision,unsettled_publication
    state=load(DATA/'cf/normalization-state.json').get('slots',{}).get(day+'/'+domain,{})
    if any(state.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold','pendingEffect')):return None
    if unsettled_publication(ROOT,day,domain):return None
    original=Path(state.get('originalFolder',''))
    if original.is_dir() and (original/'publication-receipt.json').exists():return None
    folder=prepared_revision(day,domain,root=ROOT)
    if not folder:return None
    from common.editorial_recovery import writable
    try:writable(folder)
    except ValueError:return None
    article=load(folder/'article.json');planning=load(folder/'planning.json')
    return {'folder':str(folder),'topic':planning.get('keyword') or article.get('title'),
            'title':article.get('title'),'originalSlot':state.get('slot'),
            'articleSha256':hashlib.sha256((folder/'article.json').read_bytes()).hexdigest()}


def _can_activate_unallocated_cf(item, day):
    if item.get('status') == 'unallocated':
        return True
    if (item.get('allocationId') or item.get('status') != 'processing'
            or any(item.get(k) for k in ('submissionStarted', 'submittedAt', 'submissionStartedAt', 'preCommitIntent', 'pendingEffect'))):
        return False
    from common.cf_recovery import unsettled_publication
    if unsettled_publication(ROOT, day, item.get('domain', '')):
        return False
    folder = cf_folder(item, day)
    if (folder / 'publication-receipt.json').exists():
        return False
    for p in (DATA / 'publication-conferences').glob('*.json'):
        row = load(p)
        args = row.get('arguments') or {}
        if args.get('date') == day and args.get('account') == item.get('domain') and row.get('status') in ('queued', 'running', 'submitting', 'unknown'):
            return False
    return True


def activate_cf(now=None):
    """Advance a domain to its next distinct allocation only after verified completion."""
    if not enabled():return False
    from cf_posting import posting as cf
    now=now or datetime.now(KST)
    with cf.cleaner_lock() as acquired:
        if not acquired:return False
        schedule=cf.load_current_schedule();changed=False
        for item in schedule.get('items',[]):
            if not account_available('cf_blog',item['domain'],now.timestamp()):continue
            work=allocations('cf_blog',item['domain'],schedule['date'])
            history=item.get('publicationHistory',[])
            used={r.get('allocationId') for r in history}|{item.get('allocationId')}
            next_row=next((r for r in work if r['id'] not in used),None)
            if not next_row:continue
            if not _can_activate_unallocated_cf(item,schedule['date']):
                if item.get('status') != 'published' or not item.get('publicUrl'):continue
                receipt=load(cf_folder(item,schedule['date'])/'publication-receipt.json')
                if (receipt.get('state')!='published' or receipt.get('publicPublicationVerified') is not True
                        or receipt.get('publicUrl')!=item['publicUrl']):continue
                saved={k:v for k,v in item.items() if k!='publicationHistory'}
                history=[*history,saved]
            row={k:item[k] for k in ('domain','order','id','name','color','icon','category') if k in item}
            folder=cf.BASE_DIR/'output/scheduled'/schedule['date']/(item['domain']+'-'+next_row['slot'].replace(':','')+'-'+next_row['id'][:8])
            asset=prepared_cf_asset(schedule['date'],item['domain']) if _can_activate_unallocated_cf(item,schedule['date']) else None
            if asset and next_row['topic'] in (asset['topic'],asset['title']):
                folder=Path(asset['folder']);row['preparedFrom']=asset
            row.update(status='waiting',scheduledTime=next_row['slot'],mainKeyword=next_row['topic'],
                allocationId=next_row['id'],artifactFolder=str(folder.relative_to(cf.BASE_DIR)),publicationHistory=history)
            item.clear();item.update(row);changed=True
        if changed:cf.save_schedule_file(cf.SCHEDULE_JSON,schedule)
        return changed


def publication_inventory():
    """Exact receipt-backed public URLs; missing analytics stay unknown."""
    result={}
    naver=load(DATA/'naver/public-verification.json')
    rows=naver.get('evidence') or naver.get('records') or naver.get('posts') or naver.get('items') or []
    for row in rows:
        if row.get('publicPublicationVerified') is True and row.get('publicUrl'):
            result[row['publicUrl']]={'project':'naver_blog','account':row.get('account'),
                'url':row['publicUrl'],'title':row.get('title'),'publishedAt':row.get('publishedAt'),
                'publicBodyMatched':row.get('publicBodyMatched'),'checkedAt':row.get('checkedAt'),
                'source':'dashboard/data/naver/public-verification.json'}
    schedules=[DATA/'cf/daily_schedule.json',*(DATA/'cf/schedule_history').glob('*.json')]
    for path in schedules:
        doc=load(path)
        for current in doc.get('items',[]):
            for row in [*current.get('publicationHistory',[]),current]:
                if row.get('status')=='published' and row.get('publicUrl'):
                    try:receipt_path=cf_folder(row,doc['date'])/'publication-receipt.json'
                    except (ValueError,KeyError):continue
                    receipt=load(receipt_path)
                    if (receipt.get('state')!='published' or receipt.get('publicPublicationVerified') is not True
                            or receipt.get('httpStatus')!=200 or receipt.get('publicUrl')!=row['publicUrl']):continue
                    result[row['publicUrl']]={'project':'cf_blog','account':row.get('domain'),
                        'url':row['publicUrl'],'title':row.get('title'),'publishedAt':row.get('publishedAt'),
                        'source':str(receipt_path.relative_to(ROOT)),'artifactFolder':row.get('artifactFolder'),
                        'publicBodyMatched':None}
    for row in load(DATA/'cafe/status.json').get('publishedArticles',[]):
        if row.get('status')!='published_verified' or row.get('publicState')!='body_verified':continue
        folder=ROOT/'naver_cafe_posting/output/prepared'/('part-'+str(row.get('part')))/str(row.get('cafeId'))
        if not folder.resolve().is_relative_to((ROOT/'naver_cafe_posting/output/prepared').resolve()):continue
        document=load(folder/'document.json');prepared=load(folder/'prepared.json')
        intent=load(folder/'intent.json');evidence=load(folder/'public-evidence.json')
        from naver_cafe_posting.editorial import digest
        sha=digest(document);url=row.get('articleUrl')
        if (not url or prepared.get('cafeId')!=row.get('cafeId')
                or intent.get('status')!='verified_published' or evidence.get('status')!='verified_published'
                or any(v.get('documentSha256')!=sha for v in (prepared,intent,evidence))
                or intent.get('url')!=url or evidence.get('url')!=url):continue
        result[url]={'project':'naver_cafe','account':row.get('account'),'url':url,'title':document.get('title'),
                     'publishedAt':row.get('publishedAt'),'checkedAt':evidence.get('checkedAt'),
                     'publicBodyMatched':True,'source':str((folder/'public-evidence.json').relative_to(ROOT)),
                     'documentSha256':sha}
    return list(result.values())


def review_publication(arguments, *, actor='jarvis', goal_id='', observations=None):
    url=arguments.get('url');record=next((r for r in publication_inventory() if r['url']==url),None)
    if actor not in ('jarvis','doctor','trace') or not record:
        raise ValueError('Verified publication identity and responsible reviewer required')
    review_at=datetime.fromisoformat(str(arguments.get('nextReviewAt','')).replace('Z','+00:00'))
    if review_at.tzinfo is None or review_at.timestamp()<=time.time() or not arguments.get('assessment') or not arguments.get('nextAction'):
        raise ValueError('Assessment, next action and future follow-up required')
    evidence=arguments.get('evidenceIds')
    if not isinstance(evidence,list) or not evidence or not all(isinstance(x,str) and x.strip() for x in evidence):
        raise ValueError('Cited observations required')
    goal_obs=_goal_observations(goal_id,observations)
    observations_validated=False
    cited_events=[]
    if goal_obs is not None:
        obs_by_id={e['id']:e for e in goal_obs}
        if not set(evidence).issubset(obs_by_id):
            raise ValueError('Unknown review observation')
        cited_events=[obs_by_id[eid] for eid in evidence if eid in obs_by_id]
        observations_validated=any(_result_verifies_url(ev.get('result'),url) for ev in cited_events)
    req_id=arguments.get('requestId');task_id=arguments.get('taskId')
    matched_actions=[]
    with locked(DATA/'operating-plan'):
        state=load(STATE);prior=state.setdefault('reviews',{}).get(url)
        if prior:state.setdefault('reviewHistory',[]).append(prior)
        state['reviews'][url]={**arguments,'owner':actor,'goalId':goal_id,'reviewAt':review_at.timestamp(),
            'recordedAt':time.time(),'publication':record,'businessOutcomeVerified':False,
            'observationsValidated':observations_validated,
            'judgmentType':'model_assessment_with_cited_observations'}
        if observations_validated:
            for act_key,act in state.get('actions',{}).items():
                if not _action_matches_reviewed_url(act,url,request_id=req_id,task_id=task_id):
                    continue
                req_acq='inspect_url_acquisition' in str(act.get('verificationMethod') or '')
                if not any(_result_verifies_url(ev.get('result'),url,require_acquisition=req_acq) for ev in cited_events):
                    continue
                act['followupVerified']=True;act['reviewedAt']=time.time();act['reviewedUrl']=url
                matched_actions.append(act_key)
        write(STATE,state)
    return {'ok':True,'status':'followup_owned','url':url,'businessOutcomeVerified':False,
            'observationsValidated':observations_validated,'matchedActionIds':matched_actions}


def context(now=None):
    from common.asset_map import NAVER_ACCOUNTS
    now=time.time() if now is None else now
    state=load(STATE);reviews=state.get('reviews',{})
    publications=publication_inventory()
    due=[r for r in publications if r['url'] not in reviews or reviews[r['url']].get('reviewAt',0)<=now]
    due.sort(key=lambda r:str(r.get('publishedAt') or ''),reverse=True)
    policy=load(DATA/'daily_schedule.json')
    actions=[]
    for action in state.get('actions',{}).values():
        receipt=load(Path(action['receiptPath']))
        native=[]
        for item in receipt.get('results',[]):
            result=item.get('result') or {};identity=result.get('conferenceAgendaId')
            if not isinstance(identity,str) or not re.fullmatch(r'[a-f0-9]{64}',identity):continue
            child=load(DATA/'publication-conferences'/(identity+'.json'))
            original=item.get('initialResult') or result
            requested_at=result.get('conferenceRequestedAt',original.get('conferenceRequestedAt'))
            exact=child.get('agendaId')==identity and requested_at is not None and child.get('requestedAt')==requested_at
            native.append({'conferenceId':identity,'status':child.get('status') if exact else 'unknown',
                'arguments':child.get('arguments') if exact else None,
                'reason':(child.get('failureReason') if child.get('status') in ('failed','held','unknown') else None) if exact else 'native_receipt_identity_mismatch',
                'outcomes':child.get('outcomes',[]) if exact else [],
                'evidenceName':'conference:'+identity})
        actions.append({**{k:v for k,v in action.items() if k!='receiptPath'},
                        'evidenceName':'staff_request:'+Path(action['receiptPath']).stem,
                        'status':receipt.get('status',action.get('status')),
                        'results':receipt.get('results',[]),'reason':receipt.get('reason'),
                        'executionWait':receipt.get('executionWait'),'nativeExecutions':native})
    from common.llm_usage import resource_summary
    return {'resourceUse':resource_summary(ROOT),
        'mandate':'CEO authorized adaptive quantity and account allocation; pursue faster safe revenue growth.',
        'ownedOperatingActions':actions,
        'editorialRecoveryJobs':[load(p) for p in sorted((DATA/'editorial-recovery-jobs').glob('*.json'))],
        'nativeChannelOperations':[load(p) for p in sorted((DATA/'native-channel-cycles').glob('*.json'))],
        'accountRegistry':{'naver_blog':{k:{**{f:v.get(f) for f in ('blogId','target')},
            'monetization':NAVER_ACCOUNTS.get(k,{}).get('monetization',[]),
            'capabilityEvidence':v.get('capabilityEvidence',{})} for k,v in policy.get('naver',{}).items()},
            'cf_blog':sorted(policy.get('cf',{})),'naver_kin':['adinfo0905','stone0747'],'threads':['mustpickinfo']},
        'ceoObservations':policy.get('operatingMandate',{}),
        'publicationQuotas':None,'accounts':state.get('accounts',{}),
        'accountReviewsDue':[k for k,r in state.get('accounts',{}).items() if r.get('reviewAt',0)<=now],
        'observedAccountTraffic':load(DATA/'traffic.json').get('naverBlogs',{}),
        'trafficCaveat':'Public visitor counters are account totals, not search impressions or post-attributed revenue.',
        'allocations':[{**r,'execution':allocation_execution(r,now)} for r in state.get('publications',{}).values()],
        'publicationsNeedingReview':due,
        'inventoryCoverage':['CF schedule receipts and history','Naver public verification records'],
        'detailReaders':{'plan':'operating_plan','naverPublication':'naver_public','naverPerformance':'naver_performance',
                         'traffic':'traffic','revenue':'revenue','metrics':'metrics'}}


def lifecycle_stage(state, *, publication_verified=False, reservation_verified=False, business_verified=False, protected=False):
    if protected or state in _PROTECTED_STATES:return 'uncertain_or_protected_hold'
    if business_verified is True:return 'business_outcome_verified'
    if publication_verified is True or state=='published_verified':return 'published_verified'
    if reservation_verified is True or state in ('waiting_schedule','reserved_verified'):return 'scheduled_or_reserved'
    if state in ('prepared','preparation_completed','reviewed_asset_needs_allocation'):return 'prepared'
    if state in ('preparing','preparation_queued','preparation_running'):return 'preparing'
    if state in ('preparation_failed','review_required','needs_source_repair','needs_attention','failed','verification_missing'):return 'preparation_failed'
    return 'queued_or_accepted'


def allocation_execution(row, now=None):
    """Project the exact native work identity; an allocation is never a receipt."""
    now=time.time() if now is None else now
    base={'publicationVerified':False,'reservationVerified':False,'businessOutcomeVerified':False,'owner':'publi',
          'exactTarget':{'project':row['project'],'account':row['account'],'day':row['day'],'slot':row['slot'],'topic':row.get('topic')},
          'verificationMethod':'cf_publication_receipt_and_inspect_url_acquisition' if row['project']=='cf_blog' else 'naver_public_verification_and_performance'}
    if row.get('status')=='conflict_existing_work':
        return {**base,'status':'blocked','lifecycleStage':'uncertain_or_protected_hold','reason':row.get('conflict'),'nextAction':'manager_choose_distinct_work'}
    action='naver' if row['project']=='naver_blog' else 'cf'
    arguments={'action':action,'date':row['day'],'account':row['account'],'slot':row['slot']}
    identity=hashlib.sha256(json.dumps(['parameters',arguments],sort_keys=True).encode()).hexdigest()
    path=DATA/'publication-conferences'/(identity+'.json')
    receipt=load(path)
    if receipt and (receipt.get('kind')!='parameters' or receipt.get('arguments')!=arguments):
        return {**base,'status':'unknown','lifecycleStage':'uncertain_or_protected_hold','reason':'native_identity_mismatch','nextAction':'reconcile_without_resubmission'}
    if not receipt:
        schedule=load(DATA/'cf/daily_schedule.json') if action=='cf' else {}
        prior=next((r for r in schedule.get('items',[]) if r.get('domain')==row['account']),{})
        if prior and prior.get('allocationId')!=row['id'] and prior.get('status') not in ('published','unallocated'):
            return {**base,'status':'waiting_existing_work','lifecycleStage':'queued_or_accepted','reason':prior.get('status'),
                    'nextAction':'resolve_current_domain_work_before_rotation'}
        when=datetime.fromisoformat(row['publishAt']).timestamp()
        if action=='cf' and prior.get('allocationId')==row['id']:
            folder=cf_folder(prior,row['day'])
            if when>now and all((folder/name).is_file() for name in ('article.json','photo-plan.json')):
                return {**base,'status':'waiting_schedule','lifecycleStage':'scheduled_or_reserved','reason':'prepared_publication_not_due',
                        'notBefore':when,'nextAction':'wait_until_due_without_new_dispatch'}
        if action=='cf':
            prep_args={**arguments,'action':'cf-prepare'}
            prep_id=hashlib.sha256(json.dumps(['parameters',prep_args],sort_keys=True).encode()).hexdigest()
            prep=load(DATA/'publication-conferences'/(prep_id+'.json'))
            if prep.get('kind')=='parameters' and prep.get('arguments')==prep_args and prep.get('status') in ('queued','running','held','failed','unknown'):
                prep_state='preparation_'+prep['status']
                return {**base,'status':prep_state,'lifecycleStage':lifecycle_stage(prep_state,protected=prep['status'] in ('held','unknown')),'nativeReceipt':'dashboard/data/publication-conferences/'+prep_id+'.json',
                    'reason':prep.get('failureReason') or prep.get('errorType'),
                    'nextAction':'observe_original_preparation' if prep['status'] in ('queued','running') else 'inspect_original_preparation_and_resume_condition_no_blind_retry'}
        return {**base,'status':'not_dispatched','lifecycleStage':'queued_or_accepted','nextAction':'register_native_work',
                'publishAt':row['publishAt'],'overdue':datetime.fromisoformat(row['publishAt']).timestamp()<now}
    result={**base,'nativeReceipt':str(path.relative_to(ROOT)),
            'businessAgendaId':receipt.get('businessAgendaId'),'status':receipt.get('status','unknown')}
    outcomes=receipt.get('outcomes') or []
    if receipt.get('status')=='completed' and outcomes:
        # Native outcomes are bound to exact account/day/slot above. Public body checks remain separate.
        result['publicationVerified']=all(r.get('publicationVerified') is True for r in outcomes)
        result['reservationVerified']=all(r.get('reservationVerified') is True for r in outcomes)
        result['status']='published_verified' if result['publicationVerified'] else 'reserved_verified' if result['reservationVerified'] else 'verification_missing'
        result['outcomes']=outcomes
    elif receipt.get('status') in ('failed','held','unknown'):
        result.update(reason=receipt.get('failureReason') or receipt.get('errorType'),nextAction='inspect_same_work_evidence_no_blind_retry')
    elif receipt.get('status')=='queued':
        agenda=load(DATA/'publication-conferences/operations'/(str(receipt.get('businessAgendaId'))+'.json'))
        when=agenda.get('notBefore',0)
        result.update(status='waiting_schedule' if when>now else 'queued',notBefore=when,
                      nextAction='wait_until_due' if when>now else 'native_dispatcher_admit_and_execute')
    result['lifecycleStage']=lifecycle_stage(result['status'],publication_verified=result['publicationVerified'],reservation_verified=result['reservationVerified'])
    return result


def business_brief(revenue, traffic, now=None):
    """Bounded facts with original scope; never turn absent measurement into zero."""
    now=time.time() if now is None else now
    today=datetime.fromtimestamp(now,KST).date().isoformat()
    def freshness(value):
        try:
            stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if stamp.tzinfo is None:return 'unknown_timezone'
            age=now-stamp.timestamp()
            return 'future_timestamp' if age<0 else 'stale' if age>5400 else 'recent'
        except (ValueError,TypeError):return 'unknown'
    def number(value):
        try:
            n=float(value)
            return n if not isinstance(value,bool) and math.isfinite(n) and n>=0 else None
        except (TypeError,ValueError):return None
    sources=[]
    for month in sorted(revenue.get('months') or {},reverse=True)[:1]:
        for row in revenue['months'][month].get('sources',[]):
            daily=row.get('daily') or {}
            sources.append({k:row.get(k) for k in ('id','currency','scope','status','checkedAt','valueKind','reason')})
            sources[-1].update(latestDate=max(daily,default=None),
                latestAmount=daily[max(daily)] if daily else None,todayDate=today,
                todayAmount=daily.get(today),freshness=freshness(row.get('checkedAt')),
                todayDateBasis='dashboard date key; inspect source timezone before comparison')
    growth=revenue.get('growth') or {}
    windows=growth.get('windows') or {}
    performance=[]
    for account,source in (growth.get('sources') or {}).items():
        for label,window in windows.items():
            groups={};seen=set();duplicates=0
            for row in source.get('rows',[]):
                if not window.get('start','~')<=row.get('date','')<=window.get('end',''):continue
                identity=(row.get('date'),row.get('domain'),row.get('host'))
                if identity in seen:duplicates+=1;continue
                seen.add(identity)
                amount,pv=number(row.get('revenue')),number(row.get('pageViews'))
                if amount is None or pv is None:continue
                item=groups.setdefault(row.get('domain'),{'amount':0,'pageViews':0,'observedRows':0})
                item['amount']+=amount;item['pageViews']+=pv;item['observedRows']+=1
            performance.append({'account':account,'window':label,**window,'status':source.get('status'),
                'currency':source.get('currency'),'timezone':source.get('timezone'),'checkedAt':source.get('checkedAt'),
                'valueKind':source.get('valueKind'),'duplicateRowsExcluded':duplicates,
                'observedDomains':[{'domain':domain,**{**v,'amount':round(v['amount'],6)}}
                    for domain,v in sorted(groups.items(),key=lambda pair:-pair[1]['amount'])][:16],
                'scope':'observed valid rows only; missing rows unknown; domain earnings are not article earnings'})
    sites=[]
    for domain,row in (traffic.get('sites') or {}).items():
        ga=row.get('ga4') or {};periods={}
        for key in ('week',):
            value=(ga.get('periods') or {}).get(key) or {}
            periods[key]={k:value.get(k) for k in ('start','end','sessions','pageViews','provisional','limited','sourceReconciled','mix')}
            attr=value.get('sourceAttribution') or {}
            periods[key]['attribution']={k:attr.get(k) for k in ('status','qualifiedExternalSessions','excludedExternalSessions')}
        sites.append({'domain':domain,'status':ga.get('status'),'checkedAt':ga.get('checkedAt'),
                      'timezone':ga.get('timezone'),'periods':periods})
    pages=traffic.get('pagePerformance') or {}
    earnings=revenue.get('pagePerformance') or {}
    candidates=sorted([r for r in pages.get('pages',[]) if number(r.get('sessions')) is not None],
                      key=lambda r:-number(r['sessions']))
    return {'targetDailyUsd':100,'collectionStatus':revenue.get('collectionStatus'),
        'checkedAt':revenue.get('checkedAt'),'revenueSources':sources[:24],
        'domainRevenueWindows':performance,'trafficSites':sites[:16],
        'pageCoverage':{k:pages.get(k) for k in ('start','end','timezone','checkedAt','complete','source')},
        'trafficCandidates':[{k:r.get(k) for k in ('domain','url','sessions','pageViews')} for r in candidates[:12]],
        'candidateCaveat':'Raw GA4 totals may include operational/unattributed visits; inspect exact page acquisition before choosing a winner.',
        'pageRevenueCoverage':{k:earnings.get(k) for k in ('start','end','timezone','currency','complete','scope','source')},
        'pageRevenueGaps':[{k:r.get(k) for k in ('domain','status','reasonCode','reason')} for r in earnings.get('sites',[]) if r.get('complete') is not True][:16],
        'measurementBlockers':[{'id':r['id'],'owner':'trace','status':r['status'],
            'nextAction':'inspect collection evidence and exact source session/configuration; ask_ceo for required authentication only'}
            for r in sources if r.get('status')!='collected' or r['freshness']!='recent'],
        'detailReaders':{'revenue':{'name':'revenue'},'traffic':{'name':'traffic'},
                         'pageRevenue':{'name':'revenue','select':['pagePerformance']},'collection':{'name':'collection'},
                         'urlAcquisition':{'tool':'inspect_url_acquisition','owner':'trace'}},
        'decisionRule':'Compare measured demand, acquisition, scoped earnings and execution cost before allocation. '
            'State why the chosen action beats alternatives when alternatives exist; a single mandatory repair or verification needs only its evidence basis and exact verification condition. '
            'Unknown page revenue, human identity, costs or incomplete sources are unknown, not zero. '
            'Do not combine currencies/timezones/windows or attribute domain earnings to an article. '
            'Continue supported exploration while repairing measurement; publication is not business success.'}


def execution_board(now=None):
    """Small read-only decision surface: exact work, missing inputs and protected holds."""
    now=time.time() if now is None else now
    day=datetime.fromtimestamp(now,KST).date().isoformat()
    sources=[]
    def read(relative):
        path=DATA/relative
        value=load(path)
        if path.is_file():
            sources.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        return value
    state=read('operating-plan.json');policy=read('daily_schedule.json')
    work=[]
    for row in state.get('publications',{}).values():
        past=str(row.get('day',''))<day
        execution=allocation_execution(row,now)
        expired=past and execution['status'] in ('not_dispatched','failed','held','blocked')
        row_state='expired_allocation' if expired else execution['status']
        work.append({'id':'allocation:'+row['id'],'project':row['project'],'owner':'publi',
            'account':row['account'],'day':row['day'],'slot':row['slot'],'topic':row.get('topic'),
            'state':row_state,'lifecycleStage':lifecycle_stage(row_state,publication_verified=execution.get('publicationVerified'),reservation_verified=execution.get('reservationVerified')),
            'publicationVerified':bool(execution.get('publicationVerified')),'reservationVerified':bool(execution.get('reservationVerified')),'businessOutcomeVerified':False,
            'exactTarget':execution.get('exactTarget'),'verificationMethod':execution.get('verificationMethod'),'nextCheckAt':execution.get('notBefore') or row.get('publishAt'),
            'reason':execution.get('reason'),'notBefore':execution.get('notBefore'),
            'nextAction':'choose_new_future_allocation_preserve_original' if expired else execution.get('nextAction'),
            'dispatch':{'agent':'publi','tool':'run_project_cycle','args':{'project':row['project'],'allocation_id':row['id']}}
                if not past and execution['status']=='not_dispatched' else None,
            'evidenceName':'operating_plan','requiresFreshValidation':True})
    for key,action in state.get('actions',{}).items():
        path=Path(action.get('receiptPath',''))
        if not path.is_absolute() or not path.resolve().is_relative_to(DATA.resolve()):continue
        receipt=load(path)
        protected=_is_protected_action_or_receipt(action,receipt)
        results=[r.get('result') or {} for r in receipt.get('results',[]) if isinstance(r,dict)]
        if not protected and receipt.get('status')=='completed':
            if action.get('followupVerified'):continue
            due_val=action.get('nextCheckAt')
            due_ts=None
            if isinstance(due_val,(int,float)):due_ts=float(due_val)
            elif isinstance(due_val,str):
                try:due_ts=datetime.fromisoformat(due_val.replace('Z','+00:00')).timestamp()
                except ValueError:due_ts=None
            if due_ts is not None and now>=due_ts:
                pub_ok=bool(results) and all(r.get('publicationVerified') is True or r.get('publicPublicationVerified') is True for r in results)
                res_ok=bool(results) and all(r.get('reservationVerified') is True for r in results)
                sched_ok=bool(results) and all(r.get('status') in ('waiting_schedule','reserved_verified') for r in results)
                prep_ok=bool(results) and all(r.get('status')=='prepared' for r in results)
                raw_st='published_verified' if pub_ok else 'reserved_verified' if res_ok else 'waiting_schedule' if sched_ok else 'prepared' if prep_ok else 'queued'
                work.append({'id':'followup:'+key,'project':(action.get('action',{}).get('args') or {}).get('project'),
                    'owner':'trace' if pub_ok else (action.get('owner') or 'jarvis'),
                    'state':'followup_verification_due',
                    'lifecycleStage':lifecycle_stage(raw_st,publication_verified=pub_ok,reservation_verified=res_ok),
                    'publicationVerified':pub_ok,'reservationVerified':res_ok,'businessOutcomeVerified':False,
                    'exactTarget':action.get('exactTarget') or (action.get('action',{}).get('args') or {}),
                    'evidenceIds':action.get('evidenceIds',[]),
                    'expectedOutcome':action.get('expectedOutcome'),
                    'verificationMethod':action.get('verificationMethod') or ('staff_request:'+path.stem),
                    'nextCheckAt':due_val,
                    'nextAction':'inspect_url_acquisition_and_review_publication' if pub_ok else 'verify_execution_outcome_and_record_review',
                    'evidenceName':'staff_request:'+path.stem,'dispatch':None})
            continue
        row_state='protected_hold' if protected else receipt.get('status','unknown')
        work.append({'id':'staff:'+key,'project':(action.get('action',{}).get('args') or {}).get('project'),
            'owner':action.get('action',{}).get('agent'),'state':row_state,
            'lifecycleStage':lifecycle_stage(row_state,protected=protected),
            'publicationVerified':False,'businessOutcomeVerified':False,
            'exactTarget':action.get('exactTarget') or (action.get('action',{}).get('args') or {}),
            'verificationMethod':'staff_request:'+path.stem,
            'reason':receipt.get('reasonCode') or receipt.get('reason') or next((r.get('reason') for r in results if r.get('reason')),None),
            'nextAction':'inspect_original_receipt_and_resume_condition' if protected else 'inspect_exact_execution_result',
            'executionWait':receipt.get('executionWait'),'failures':[
                {k:r.get(k) for k in ('errorType','errorMessage','sourceLocation','failureFingerprint','reason','nextAction')}
                for r in results if r.get('errorType') or r.get('reason')],
            'dispatchFailure':{k:receipt.get(k) for k in ('errorCode','errorMessage','sourceLocation','failureFingerprint') if receipt.get(k)},
            'evidenceName':'staff_request:'+path.stem,'dispatch':None})
    for url,rev in state.get('reviews',{}).items():
        if isinstance(rev.get('reviewAt'),(int,float)) and now>=rev['reviewAt']:
            pub=rev.get('publication') or {}
            work.append({'id':'review-due:'+url,'project':pub.get('project') or 'cf_blog',
                'owner':rev.get('owner') or 'trace','account':pub.get('account'),'url':url,
                'state':'verification_review_due','lifecycleStage':'published_verified',
                'publicationVerified':True,'reservationVerified':False,'businessOutcomeVerified':False,
                'exactTarget':{'project':pub.get('project'),'account':pub.get('account'),'url':url},
                'evidenceIds':rev.get('evidenceIds',[]),'expectedOutcome':rev.get('nextAction'),
                'verificationMethod':'inspect_url_acquisition_and_review_publication' if pub.get('project')=='cf_blog' else 'naver_performance_and_review_publication',
                'nextCheckAt':rev.get('nextReviewAt'),'nextAction':'inspect_acquisition_and_record_updated_review_publication',
                'evidenceName':'operating_plan','dispatch':None})
    for acct_key,acct in state.get('accounts',{}).items():
        if isinstance(acct.get('reviewAt'),(int,float)) and now>=acct['reviewAt']:
            work.append({'id':'account-review-due:'+acct_key,'project':acct.get('project'),
                'owner':acct.get('owner') or 'jarvis','account':acct.get('account'),
                'state':'account_review_due','lifecycleStage':'queued_or_accepted',
                'publicationVerified':False,'reservationVerified':False,'businessOutcomeVerified':False,
                'exactTarget':acct.get('exactTarget') or {'project':acct.get('project'),'account':acct.get('account')},
                'evidenceIds':acct.get('evidenceIds',[]),'expectedOutcome':acct.get('expectedOutcome'),
                'verificationMethod':acct.get('verificationMethod') or 'operating_plan_account_review',
                'nextCheckAt':acct.get('nextCheckAt'),'nextAction':'reassess_account_mode_with_observed_traffic_and_revenue',
                'evidenceName':'operating_plan','dispatch':None})
    normal=read('cf/normalization-state.json')
    schedule=read('cf/daily_schedule.json')
    for row in schedule.get('items',[]):
        if row.get('status')!='unallocated':continue
        asset=prepared_cf_asset(day,row['domain'])
        if asset:
            work.append({'id':'prepared-asset:'+day+'/'+row['domain'],'project':'cf_blog','owner':'jarvis',
                'account':row['domain'],'state':'reviewed_asset_needs_allocation','lifecycleStage':'prepared','asset':asset,
                'nextAction':'allocate_publications with this exact topic and a future publishAt, then dispatch exact allocation; native activation reuses the reviewed asset',
                'publicationVerified':False,'businessOutcomeVerified':False})
    for identity,row in normal.get('slots',{}).items():
        if not identity.startswith(day+'/') or row.get('status') not in ('held','retry_wait','needs_attention'):continue
        domain=identity.split('/',1)[1]
        work.append({'id':'cf-preparation:'+identity,'project':'cf_blog','owner':'publi','account':domain,
            'state':'review_required','lifecycleStage':lifecycle_stage('review_required',protected=row.get('status')=='held'),'reason':row.get('reason'),'revision':row.get('revision'),
            'nextAction':'read_original_defects_then_supply_observed_missing_source_queries',
            'evidenceName':'cf_normalization','dispatch':{'agent':'publi','tool':'repair_cf_normalization',
                'args':{'project':'cf_blog','domain':domain,'day':day}},
            'publicationVerified':False,'businessOutcomeVerified':False,
            'requiresFreshValidation':True,'autoRetry':False})
    for project in ('cf_blog','naver_blog'):
        accounts=sorted(policy.get('cf' if project=='cf_blog' else 'naver',{}))
        if accounts:
            work.append({'id':'new-allocation:'+project,'project':project,'owner':'jarvis','state':'needs_manager_input','lifecycleStage':'queued_or_accepted',
                'availableAccounts':accounts,'missingInputs':['reader topic','future publishAt','account','why this reader task'],
                'nextAction':'allocate_publications_then_dispatch_exact_allocation',
                'publicationVerified':False,'businessOutcomeVerified':False,
                'measurementMissingBlocksExploration':False,'publicationQuota':None})
    cafe=read('cafe/status.json')
    cafes=[r.get('cafeId') for r in cafe.get('cafes',[]) if r.get('cafeId')
           and r.get('policyMode')!='suspended_banned' and not r.get('restrictionUntil')]
    parts=[r.get('part') for r in cafe.get('publishedArticles',[]) if type(r.get('part')) is int]
    for project,name in (('naver_cafe','cafe'),('youtube','youtube')):
        jobs=read(name+'/preparation-jobs.json').get('jobs') or {}
        for identity,job in jobs.items():
            if project=='naver_cafe' and type(job.get('part')) is int:parts.append(job['part'])
            if job.get('status')=='published_verified':continue
            result=job.get('result') or {}
            reason=job.get('reason') or result.get('reason')
            j_state=job.get('status','unknown')
            work.append({'id':name+'-input:'+identity,'project':project,
                'owner':'patch' if reason in ('account_space_control_required','user_takeover','auth_required') else 'publi',
                'state':j_state,'lifecycleStage':lifecycle_stage(j_state,protected=reason in ('account_space_control_required','user_takeover','auth_required')),
                'reason':reason,'part':job.get('part'),
                'account':job.get('cafeId') or job.get('channelHandle'),'topic':job.get('topic'),
                'nextAction':'run_channel_cycle with native validation' if job.get('status')=='prepared' else
                    'inspect_exact_original_input_and_resume_condition; no replacement or blind retry',
                'evidenceName':name+'_preparation','publicationVerified':False,'businessOutcomeVerified':False,'autoRetry':False})
    parts.extend(int(p.parents[1].name.removeprefix('part-')) for p in (ROOT/'naver_cafe_posting/output/prepared').glob('part-*/*/document.json')
                 if p.parents[1].name.removeprefix('part-').isdigit())
    work.append({'id':'prepare:naver_cafe','project':'naver_cafe','owner':'publi','state':'needs_manager_input','lifecycleStage':'queued_or_accepted',
        'availableCafeIds':cafes,'suggestedUnpublishedPart':max(parts,default=0)+1,
        'missingInputs':['reader topic','observed source queries','registered cafe_id','unpublished part_no'],
        'nextAction':'dispatch prepare_cafe_content; preparation is not publication',
        'publicationVerified':False,'businessOutcomeVerified':False,
        'dispatchTool':'prepare_cafe_content','evidenceName':'cafe_preparation'})
    youtube=read('youtube/status.json')
    handles=[r.get('handle') for r in youtube.get('channels',[]) if r.get('status') in ('active_flagship','active_shorts')]
    work.append({'id':'prepare:youtube','project':'youtube','owner':'publi','state':'needs_manager_input','lifecycleStage':'queued_or_accepted',
        'availableChannelHandles':handles,'supportedSurface':'source-reviewed community text; not video upload',
        'missingInputs':['channel_handle','reader topic','observed source queries'],
        'nextAction':'dispatch prepare_youtube_content, then native operation and exact public-body verification',
        'publicationVerified':False,'businessOutcomeVerified':False,
        'dispatchTool':'prepare_youtube_content','evidenceName':'youtube_preparation'})
    brunch=read('brunch/status.json')
    published={r.get('articleNo') for r in brunch.get('publishedArticles',[])}
    for path in sorted((ROOT/'brunch_posting/output/prepared').glob('part-*/article.json')):
        article=load(path);part=article.get('part')
        if type(part) is not int or part in published:continue
        intent=load(path.parent/'publication-intent.json')
        hold=intent.get('state') in ('submitting','unknown','published','staged_verified')
        failure=load(path.parent/'editorial-recovery.json')
        work.append({'id':'brunch-part:'+str(part),'project':'brunch','owner':'publi',
            'part':part,'title':article.get('title'),'state':'protected_hold' if hold else 'needs_source_repair',
            'lifecycleStage':lifecycle_stage('protected_hold' if hold else 'needs_source_repair',protected=hold),
            'publicationVerified':False,'businessOutcomeVerified':False,
            'reason':intent.get('state') if hold else (failure.get('feedback') or {}).get('error'),
            'nextAction':'reconcile_original_intent' if hold else 'dispatch prepare_brunch_content with exact missing-source queries',
            'dispatch':None if hold else {'agent':'publi','tool':'prepare_brunch_content','args':{'project':'brunch','part_no':part}},
            'evidenceName':'brunch_preparation','requiresFreshValidation':True})
    # Only meaningful facts wake reasoning; timestamps and read activity do not.
    business={}
    for name,keys in [('revenue.json',('date','checkedAt','collectionStatus','daily','sources','months','growth','pagePerformance')),
                      ('traffic.json',('date','checkedAt','naverBlogs','sites','pagePerformance'))]:
        value=read(name);business[name]={k:value.get(k) for k in keys}
    def stable(value):
        if isinstance(value,dict):return {k:stable(v) for k,v in value.items()
            if k not in ('checkedAt','updatedAt','observedAt','generatedAt','lastCheckedAt','ageSeconds','durationSeconds','elapsedSeconds')}
        if isinstance(value,list):return [stable(v) for v in value]
        return value
    handlers={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
              (Path(__file__),ROOT/'dashboard/common/channel_parameters.py',ROOT/'dashboard/agents/crew_reasoning.py') if p.is_file()}
    material={'work':stable(work),'business':stable(business),'handlers':handlers}
    fingerprint=hashlib.sha256(json.dumps(material,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    from common.llm_usage import resource_summary
    brief=business_brief(business['revenue.json'],business['traffic.json'],now)
    resources=resource_summary(ROOT,datetime.fromtimestamp(now,KST))
    brief['resourceUse']={k:resources.get(k) for k in ('date','reportedTokens','modelCalls','limits','currentAdmission','actualCostUsd','costStatus')}
    return {'fingerprint':fingerprint,'observedAt':now,'business':brief,
        'work':work[:64],'totalItems':len(work),
        'complete':len(work)<=64,'sourceRefs':sources,'publicationVerified':False,'businessOutcomeVerified':False,
        'decisionRule':'Choose scoped execution, concrete input preparation, or an evidence-bound wait binding evidenceIds, owner, exactTarget, expectedOutcome, verificationMethod and nextCheckAt. Single mandatory repairs or verifications do not require two dummy alternatives. Queued, prepared, scheduled (waiting_schedule), protected holds, public publication and business outcomes remain strictly separated.'}


def check_once(company, now=None):
    """Use the same continuing investigation/tool loop as an interactive request."""
    if not enabled():return False
    reconcile_allocations()
    from agents import crew_reasoning as crew
    now=time.time() if now is None else now
    state=load(STATE);manager=state.get('manager') or {}
    previous=load(crew.goal_path(manager['goalId'])) if manager.get('goalId') else {}
    if previous and manager.get('status')!=previous.get('status'):
        with locked(DATA/'operating-plan'):
            current=load(STATE)
            if current.get('manager',{}).get('goalId')==previous['id']:
                current['manager']['status']=previous.get('status');write(STATE,current)
    if previous.get('status') in ('blocked','waiting_resource'):
        with crew.claim(previous['id']) as acquired:
            if acquired:
                previous=load(crew.goal_path(previous['id']))
                if crew.resource_continuation(previous):return True
                if previous.get('status')=='waiting_resource':return False
    if previous and previous.get('status') not in ('answered','blocked'):
        return False  # Its normal background consumer continues the exact existing task.
    if now-manager.get('checkedAt',0)<300:return False
    ctx=context(now)
    material={'projects':[{k:p.get(k) for k in ('id','status','blocker','failures','runtimeOutcome','counts')} for p in company.get('projects',[])],
              'hostResourceStatus':company.get('hostResources',{}).get('status','unknown'),
              'reviewUrls':[r['url'] for r in ctx['publicationsNeedingReview']],
              'allocationStates':[(r['id'],r.get('execution')) for r in ctx['allocations']], 'accounts':ctx['accounts'],
              'accountReviewsDue':ctx['accountReviewsDue'],
              'executionStates':[(r['requestId'],r.get('status')) for r in ctx['ownedOperatingActions']],
              'editorialRecoveryStates':[(r.get('conferenceId'),r.get('status'),r.get('reason'),r.get('nextAction')) for r in ctx['editorialRecoveryJobs']],
              'nativeChannelOperations':[(r.get('project'),r.get('requestId'),r.get('status')) for r in ctx['nativeChannelOperations']],
              'business':company.get('businessEvidence',{})}
    def stable(v):
        if isinstance(v,dict):return {k:stable(x) for k,x in v.items() if not k.endswith(('At','Sha256')) and k not in ('checked_at','collected_at')}
        if isinstance(v,list):return [stable(x) for x in v]
        return v
    fingerprint=hashlib.sha256(json.dumps(stable(material),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if manager.get('fingerprint')==fingerprint:return False
    question=('현재 회사 전반을 점검하고 현재 자산으로 빠르고 안전하게 수익을 높일 다음 행동을 판단·실행·검증하세요. '
        '발행량은 목표나 고정 상한이 아니라 실측 노출·수요·독자 효용·실행 자원을 보고 조정하는 수단입니다. '
        '자료가 부족하면 탐색 발행과 측정을 병행하세요. 검색량/문서수 고정 기준이나 한 실험의 대기로 전사를 멈추지 마세요. '
        '노출이 확인되는 계정은 확대할 가설을, 약한 계정은 원인 조사와 조정안을 판단하세요. '
        '실제 검색 상위 글을 비교하고 수익 경로를 설명할 수 있는 주제를 선택하세요. '
        'allocate_publications로 구체적인 계정·주제·공개 시각을 배정하고 배정된 CF/Naver 작업은 run_project_cycle에 allocation_id를 지정해 진행하세요. '
        '발행 후 실제 결과와 성과를 검토하고 review_publication으로 후속 책임과 다음 확인 시점을 남기세요. '
        '승인된 작업·실제 플랫폼 제한·사용자 중지·불명확한 제출·기발행 네이버 글은 보존하세요. '
        '장애는 원천 기록과 코드까지 조사해 지원되는 복구를 실행하고, 코드 수정안은 검토 가능한 후보로 제출하세요. '
        '필요한 계정·인증·사업 판단만 대표에게 구체적으로 요청하세요.')
    projects=[p['id'] for p in company.get('projects',[]) if p.get('id')]
    from common.llm_usage import budget_policy
    goal=crew.reason_request('company-manager:'+fingerprint,question,execute=True,repair=True,steps=0,
        lead='jarvis',origin='company-manager',projects=projects,max_steps=budget_policy(ROOT)['agendaCalls'])
    with locked(DATA/'operating-plan'):
        current=load(STATE);current['manager']={'goalId':goal['id'],'fingerprint':fingerprint,'checkedAt':now,'status':goal['status']}
        write(STATE,current)
    return True
