"""Private, durable Threads publication ledger. Never retry uncertain writes."""
from contextlib import contextmanager
from datetime import datetime, timezone,timedelta
import hashlib
import json
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from common.channel_attribution import build_attribution_receipt
from common.dashboard_jobs import write
from . import config as settings

KST=ZoneInfo('Asia/Seoul')
CONSUMED=('sending_intent','submitted_unknown','api_submitted','published_verified')
REVIEW_KEYS={'factual_supported','no_fabricated_experience','safe_nonindividual_advice','ownership_and_link','standalone_value','source_quotes_exact','required_official_present'}

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

@contextmanager
def connect(path=settings.DB):
    path=__import__('pathlib').Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=15,isolation_level=None)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA journal_mode=DELETE')
    db.execute('PRAGMA busy_timeout=15000')
    db.executescript('''CREATE TABLE IF NOT EXISTS parts(
      part_id TEXT PRIMARY KEY,attempt_id TEXT NOT NULL,account_key TEXT NOT NULL,
      kind TEXT NOT NULL,state TEXT NOT NULL,publication_date TEXT NOT NULL,slot TEXT NOT NULL,
      document TEXT NOT NULL,text TEXT NOT NULL,text_sha256 TEXT NOT NULL,outbound_url TEXT,
      parent_platform_id TEXT,platform_id TEXT,permalink TEXT,created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,published_at TEXT,reason TEXT,evidence TEXT);
      CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,part_id TEXT,state TEXT,at TEXT,reason TEXT);
      CREATE TABLE IF NOT EXISTS runtime(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS authoring_slots(account_key TEXT,day TEXT,slot TEXT,state TEXT,reason TEXT,updated_at TEXT,PRIMARY KEY(account_key,day,slot));''')
    columns={row[1] for row in db.execute('PRAGMA table_info(parts)')}
    for name in ('api_submitted_at','verified_at','publication_time_basis'):
        if name not in columns:db.execute('ALTER TABLE parts ADD COLUMN '+name+' TEXT')
    try:yield db
    finally:db.close()

def binding(document):
    return digest({k:v for k,v in document.items() if k!='review'})

def receipt(account,url,day,slot,content_id,allowed_hosts=None):
    return build_attribution_receipt(url,source='threads',account=account,work_date=day,
      publication_date=day,slot=slot,article_id=content_id,allowed_hosts=allowed_hosts or settings.HOSTS)

def validate_document(doc,config):
    if doc.get('schema')!='threads-document-v1' or doc.get('account_key')!=config.get('account_key'):
        raise ValueError('Document account/schema mismatch')
    mode=doc.get('mode','cf_inbound')
    if mode not in ('warmup','cf_inbound','affiliate'):
        raise ValueError('Invalid Threads document mode')
    source=doc.get('source',{})
    if not source.get('body') or hashlib.sha256(source['body'].encode()).hexdigest()!=source.get('body_sha256'):
        raise ValueError('Source snapshot hash mismatch')
    sources={source['url']:source}
    for official in doc.get('official_sources',[]):
        host=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(official.get('url','')).hostname or ''
        if official.get('official') is not True or not (host=='gov.kr' or host.endswith(('.go.kr','.gov.kr','.scourt.go.kr'))) or hashlib.sha256(official.get('body','').encode()).hexdigest()!=official.get('body_sha256'):raise ValueError('Official provenance invalid')
        sources[official['url']]=official
    parts=doc.get('parts',[])
    if not parts or len(parts)>1+config['maxFollowups'] or parts[0].get('kind')!='main':
        raise ValueError('One main and at most one followup required')
    for i,p in enumerate(parts):
        if p.get('kind')!=('main' if i==0 else 'followup') or not isinstance(p.get('text'),str) or not 1<=len(p['text'])<=500:
            raise ValueError('Invalid Threads part')
    main_text=parts[0]['text']
    if 'http://' in main_text or 'https://' in main_text:
        raise ValueError('Zero links in main post required: main text must not contain http/https URLs')
    attr=doc.get('attribution')
    if mode=='warmup':
        if len(parts)!=1 or attr is not None:
            raise ValueError('Warmup post must have exactly 1 main part and no attribution link')
    elif mode=='affiliate':
        if len(parts)!=2 or not isinstance(attr,dict) or not attr.get('outboundUrl'):
            raise ValueError('Affiliate post requires main + followup with affiliate outboundUrl')
        outbound=attr['outboundUrl']
        aff_host=(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(outbound).hostname or '').lower()
        if aff_host not in settings.ALL_OUTBOUND_HOSTS:
            raise ValueError('Affiliate outboundUrl host not in allowed hosts')
        if outbound in main_text or parts[1]['text'].count(outbound)!=1:
            raise ValueError('Affiliate outboundUrl must appear once in followup and never in main')
    else:
        expected_attr=receipt(doc['account_key'],source['url'],doc['publication_date'],doc['slot'],doc['content_id'])
        if attr!=expected_attr:raise ValueError('Attribution changed; new review required')
        outbound=attr['outboundUrl']
        if len(parts)!=2 or outbound in main_text or parts[1]['text'].count(outbound)!=1:
            raise ValueError('CF inbound post requires 0 links in main and exact attributed link in followup')
    combined='\n'.join(p['text'] for p in parts)
    review=doc.get('review',{})
    if review.get('approved') is not True or review.get('binding')!=binding(doc) or set(review.get('checks',{}))!=REVIEW_KEYS or not all(v is True for v in review['checks'].values()):
        raise ValueError('Independent final-content review required')
    if not review.get('claims') or any(not c.get('claim') or not c.get('quote') or c.get('source_url') not in sources or c['claim'] not in combined or c['quote'] not in sources[c['source_url']]['body'] for c in review['claims']):raise ValueError('Exact review provenance required')
    return doc

def import_document(doc,config,db_path=settings.DB):
    validate_document(doc,config);now=settings.stamp();attempt=doc['content_id']
    attr=doc.get('attribution') or {}
    outbound_val=attr.get('outboundUrl')
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for i,p in enumerate(doc['parts']):
                part_id=attempt+'-'+str(i)
                part_outbound=outbound_val if (outbound_val and outbound_val in p['text']) else None
                db.execute('INSERT INTO parts(part_id,attempt_id,account_key,kind,state,publication_date,slot,document,text,text_sha256,outbound_url,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (part_id,attempt,doc['account_key'],p['kind'],'queued',doc['publication_date'],doc['slot'],json.dumps(doc,ensure_ascii=False),p['text'],hashlib.sha256(p['text'].encode()).hexdigest(),part_outbound,now,now))
            db.commit()
        except:db.rollback();raise
    return attempt

def _gate(config,now):
    settings.validate(config)
    day=now.astimezone(KST).date().isoformat()
    if not config.get('enabled') or not config.get('activationApproved'):raise RuntimeError('disabled')
    if not config.get('activatedAt'):raise RuntimeError('outside_trial')
    if not config.get('continuousMode'):
        if not datetime.fromisoformat(config['activatedAt'])<=now<datetime.fromisoformat(config.get('endsAt') or config['activatedAt']):raise RuntimeError('outside_trial')
        if not config.get('startDate') or not config['startDate']<=day<=config['endDate']:raise RuntimeError('outside_trial')
    return day

def is_followup_delay_satisfied(parent_row, doc, now=None):
    """Check whether at least followup_delay_seconds (90~180s, default 120s) has elapsed since parent main post."""
    now = now or datetime.now(timezone.utc)
    delay_sec = int((doc or {}).get('followup_delay_seconds', 120))
    if delay_sec <= 0:
        return True
    ref_ts = parent_row['published_at'] or parent_row['verified_at'] or parent_row['updated_at']
    if not ref_ts:
        return False
    try:
        pub_dt = datetime.fromisoformat(str(ref_ts).replace('Z', '+00:00'))
        return (now - pub_dt).total_seconds() >= delay_sec
    except Exception:
        return False

def begin_send(db,part_id,config,now=None,expected=None):
    now=now or datetime.now(timezone.utc);day=_gate(config,now)
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT * FROM parts WHERE part_id=?',(part_id,)).fetchone()
        if not row or row['state']!='queued' or row['publication_date']!=day:raise RuntimeError('not_due_or_not_queued')
        if now.astimezone(KST)<datetime.fromisoformat(day+'T'+row['slot']).replace(tzinfo=KST):raise RuntimeError('slot_not_due')
        if expected and any(row[k]!=expected[k] for k in ('text','text_sha256','outbound_url','document')):raise RuntimeError('draft_changed')
        doc=json.loads(row['document'])
        validate_document(doc,config)
        index=0 if row['kind']=='main' else 1
        if row['text']!=doc['parts'][index]['text'] or row['text_sha256']!=hashlib.sha256(row['text'].encode()).hexdigest():raise RuntimeError('ledger_document_mismatch')
        attr=doc.get('attribution') or {}
        expected_url=attr.get('outboundUrl') if (attr.get('outboundUrl') and attr.get('outboundUrl') in row['text']) else None
        if row['outbound_url']!=expected_url:raise RuntimeError('ledger_attribution_mismatch')
        if row['account_key']!=config['account_key']:raise RuntimeError('account_changed')
        if row['kind']=='main':
            if not config.get('continuousMode'):
                trial_cap=int(config.get('mainTrialCap', config.get('trialDays',14)*config.get('mainDailyCap',4)))
                total=db.execute("SELECT count(*) FROM parts WHERE account_key=? AND kind='main' AND state IN ('sending_intent','submitted_unknown','api_submitted','published_verified')",(row['account_key'],)).fetchone()[0]
                if total>=trial_cap:raise RuntimeError('trial_cap')
            n=db.execute("SELECT count(*) FROM parts WHERE account_key=? AND publication_date=? AND kind='main' AND state IN ('sending_intent','submitted_unknown','api_submitted','published_verified')",(row['account_key'],day)).fetchone()[0]
            if n>=config['mainDailyCap']:raise RuntimeError('daily_cap')
        else:
            parent=db.execute("SELECT * FROM parts WHERE attempt_id=? AND kind='main' AND state='published_verified'",(row['attempt_id'],)).fetchone()
            if not parent:raise RuntimeError('verified_parent_required')
            if not is_followup_delay_satisfied(parent, doc, now):
                raise RuntimeError('followup_delay_not_elapsed')
            db.execute('UPDATE parts SET parent_platform_id=? WHERE part_id=?',(parent['platform_id'],part_id))
        db.execute("UPDATE parts SET state='sending_intent',updated_at=? WHERE part_id=?",(now.isoformat(),part_id))
        db.execute('INSERT INTO events(part_id,state,at) VALUES(?,?,?)',(part_id,'sending_intent',now.isoformat()));db.commit()
    except:db.rollback();raise

def _update(db,part_id,state,reason=None,**fields):
    fields.update(state=state,reason=reason,updated_at=settings.stamp())
    db.execute('UPDATE parts SET '+','.join(k+'=?' for k in fields)+' WHERE part_id=?',(*fields.values(),part_id))
    db.execute('INSERT INTO events(part_id,state,at,reason) VALUES(?,?,?,?)',(part_id,state,settings.stamp(),reason))

def publish(part_id,config,db_path=settings.DB,adapter=None,config_loader=None):
    from .scheduler import lock
    with lock(settings.PRIVATE/('threads-account-'+config['account_key']+'.lock')):
        return _publish(part_id,config,db_path,adapter,config_loader)

def _publish(part_id,config,db_path=settings.DB,adapter=None,config_loader=None):
    from . import adapter as default_adapter
    adapter=adapter or default_adapter
    now=datetime.now(timezone.utc)
    _gate(config,now)
    status=adapter.readiness_status(config) if hasattr(adapter,'readiness_status') else adapter.connection_status(config)
    if status.get('connected') is not True or status.get('account_verified') is not True or status.get('account_key')!=config['account_key']:raise RuntimeError('needs_connection')
    if hasattr(adapter,'readiness_status') and status.get('publishReady') is not True:raise RuntimeError('publish_readiness_incomplete')
    with connect(db_path) as db:
        row=db.execute('SELECT * FROM parts WHERE part_id=?',(part_id,)).fetchone()
        if not row or row['state']!='queued':raise RuntimeError('never_resend_nonqueued')
        part=dict(row)
        from .authoring import article_snapshot
        document=json.loads(part['document'])
        if not document['source'].get('original_input_url'):
            for source in [document['source'],*document.get('official_sources',[])]:
                fresh=article_snapshot(source['url'],official=source.get('official',False))
                if fresh['body_sha256']!=source['body_sha256']:raise RuntimeError('source_changed_review_required')
        if part['kind']=='followup':
            parent=db.execute("SELECT * FROM parts WHERE attempt_id=? AND kind='main' AND state='published_verified'",(part['attempt_id'],)).fetchone()
            if not parent:raise RuntimeError('verified_parent_required')
            if not is_followup_delay_satisfied(parent, document, now):
                raise RuntimeError('followup_delay_not_elapsed')
            part['parent_platform_id']=parent['platform_id']
        committed=False
        def before_submit():
            nonlocal committed
            if committed:raise RuntimeError('duplicate_submit_callback')
            begin_send(db,part_id,config_loader() if config_loader else config,expected=part);committed=True
        try:
            result=adapter.submit_part(config,part,before_submit)
            if not committed:raise RuntimeError('adapter_did_not_commit_intent')
            if not result.get('platform_id'):raise RuntimeError('publish_result_unknown')
            submitted_at=settings.stamp()
            _update(db,part_id,'api_submitted',result.get('reason'),platform_id=result['platform_id'],permalink=result.get('permalink'),api_submitted_at=submitted_at,published_at=result.get('published_at'),publication_time_basis='api_timestamp' if result.get('published_at') else 'unknown')
        except Exception:
            if committed:_update(db,part_id,'submitted_unknown','publish_outcome_unknown')
            raise
        try:evidence=adapter.verify_public(config,part,result)
        except Exception:
            _update(db,part_id,'api_submitted','public_verification_pending');return {'part_id':part_id,'state':'api_submitted','platform_id':result['platform_id'],'permalink':result.get('permalink')}
        valid=(evidence.get('verified') is True and evidence.get('public') is True and evidence.get('account_key')==part['account_key'] and evidence.get('platform_id')==result['platform_id'] and evidence.get('text_sha256')==part['text_sha256'] and evidence.get('outbound_url')==part['outbound_url'])
        if valid:_update(db,part_id,'published_verified',verified_at=settings.stamp(),published_at=evidence.get('published_at') or result.get('published_at'),publication_time_basis='api_timestamp' if evidence.get('published_at') or result.get('published_at') else 'unknown',evidence=json.dumps(evidence,ensure_ascii=False))
        else:_update(db,part_id,'api_submitted','public_verification_pending',evidence=json.dumps(evidence,ensure_ascii=False))
        return {'part_id':part_id,'state':'published_verified' if valid else 'api_submitted','platform_id':result['platform_id'],'permalink':result.get('permalink')}

def reconcile(config,db_path=settings.DB,adapter=None):
    from . import adapter as default_adapter
    adapter=adapter or default_adapter;results=[]
    with connect(db_path) as db:
        for row in db.execute("SELECT * FROM parts WHERE state='api_submitted' OR (state='published_verified' AND published_at IS NULL)").fetchall():
            part=dict(row);result={'platform_id':row['platform_id'],'permalink':row['permalink']}
            try:e=adapter.verify_public(config,part,result)
            except Exception:continue
            identity_matches=all(e.get(k)==part[k] for k in ('account_key','platform_id','text_sha256','outbound_url'))
            if e.get('published_at') and identity_matches:
                db.execute('UPDATE parts SET published_at=?,publication_time_basis=? WHERE part_id=?',(e['published_at'],'api_timestamp',part['part_id']))
                part['published_at']=e['published_at'];part['publication_time_basis']='api_timestamp'
            if part['state']=='published_verified':continue
            if e.get('verified') is True and e.get('public') is True and all(e.get(k)==part[k] for k in ('account_key','platform_id','text_sha256','outbound_url')):
                _update(db,part['part_id'],'published_verified',verified_at=settings.stamp(),published_at=e.get('published_at') or part['published_at'],publication_time_basis='api_timestamp' if e.get('published_at') else part.get('publication_time_basis') or 'unknown',permalink=e.get('permalink') or part['permalink'],evidence=json.dumps(e,ensure_ascii=False));results.append(part['part_id'])
    return results

def adopt_recovered(part_id,recovery,db_path=settings.DB):
    """Adopt only uniquely matched authenticated read evidence; never submit."""
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            row=db.execute("SELECT * FROM parts WHERE part_id=? AND state='submitted_unknown'",(part_id,)).fetchone()
            intent=db.execute("SELECT at FROM events WHERE part_id=? AND state='sending_intent' ORDER BY id LIMIT 1",(part_id,)).fetchone()
            if not row or not intent or recovery.get('matched') is not True or recovery.get('match_count')!=1:raise ValueError('Unique uncertain intent match required')
            if any(recovery.get(k)!=row[k] for k in ('account_key','text_sha256','outbound_url')):raise ValueError('Recovery account/text/UTM mismatch')
            actual=datetime.fromisoformat(recovery['published_at'].replace('Z','+00:00'))
            if actual<datetime.fromisoformat(intent[0]) or actual>datetime.now(timezone.utc):raise ValueError('Recovery timestamp outside intent interval')
            if not recovery.get('platform_id') or not recovery.get('permalink'):raise ValueError('Observed API identity required')
            _update(db,part_id,'api_submitted','recovered_by_unique_readonly_match',platform_id=recovery['platform_id'],permalink=recovery['permalink'],published_at=actual.isoformat(),publication_time_basis='api_timestamp',evidence=json.dumps(recovery,ensure_ascii=False))
            db.commit()
            from common.llm_client import memory_event
            memory_event(f'threads:{part_id}:recovered:{recovery["platform_id"]}', 'pipeline_recovery_success',
                         'Uncertain Threads submission recovered by unique authenticated API match; public-page verification is separate.',
                         evidence={**recovery, 'verificationScope': 'authenticated_api_identity'}, review=True)
        except:db.rollback();raise

def recover_unknown(config,db_path=settings.DB,adapter=None):
    from . import adapter as default_adapter
    adapter=adapter or default_adapter
    if not hasattr(adapter,'recover_unknown'):return []
    recovered=[]
    with connect(db_path) as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM parts WHERE state='submitted_unknown'")]
        for row in rows:
            key='recovery_checked_'+row['part_id'];last=db.execute('SELECT value FROM runtime WHERE key=?',(key,)).fetchone()
            now=datetime.now(timezone.utc)
            if last and (now-datetime.fromisoformat(json.loads(last[0]))).total_seconds()<21600:continue
            intent=db.execute("SELECT at FROM events WHERE part_id=? AND state='sending_intent' ORDER BY id LIMIT 1",(row['part_id'],)).fetchone()
            if not intent:continue
            row['intent_at']=intent[0]
            db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',(key,json.dumps(now.isoformat())))
            try:result=adapter.recover_unknown(config,row)
            except Exception:continue
            if result.get('matched') is True:
                adopt_recovered(row['part_id'],result,db_path);recovered.append(row['part_id'])
    return recovered

def snapshot(config,db_path=settings.DB,output=settings.PUBLIC):
    with connect(db_path) as db:
        rows=[dict(x) for x in db.execute('SELECT * FROM parts ORDER BY created_at DESC LIMIT 100')]
        counts={x['state']:x['n'] for x in db.execute('SELECT state,count(*) n FROM parts GROUP BY state')}
        runtime={x['key']:json.loads(x['value']) for x in db.execute('SELECT * FROM runtime')}
    connection=config.get('connection',{});connected=connection.get('connected') is True and connection.get('account_verified') is True
    recent=[]
    threads_by_attempt={}
    for row in rows:
        doc=json.loads(row['document']);review=doc.get('review',{})
        item={k:row.get(k) for k in ('attempt_id','part_id','kind','account_key','state','permalink','updated_at','publication_date','slot','outbound_url','parent_platform_id')}|{
            'title':doc.get('title'),
            'mode':doc.get('mode','cf_inbound'),
            'followup_delay_seconds':doc.get('followup_delay_seconds',120),
            'variants':doc.get('variants'),
            'selected_variant':doc.get('selected_variant','hook'),
            'preview':row['text'] if review.get('approved') else None,
            'review':{'status':'approved' if review.get('approved') else 'pending','reason':review.get('reason')},
            'source_url':doc['source']['url'],
            'published_at':row.get('published_at'),
            'verified_at':row.get('verified_at'),
            'publication_time_basis':row.get('publication_time_basis'),
        }
        recent.append(item)
        grp=threads_by_attempt.setdefault(row['attempt_id'],{'attempt_id':row['attempt_id'],'title':doc.get('title'),'publication_date':row.get('publication_date'),'slot':row.get('slot'),'mode':doc.get('mode','cf_inbound'),'followup_delay_seconds':doc.get('followup_delay_seconds',120),'source_url':doc['source']['url'],'variants':doc.get('variants'),'main':None,'followup':None})
        grp[row['kind']]=item
    status='needs_account' if not config.get('account_key') else 'paused_token' if not connected else 'ready' if config['enabled'] else 'disabled'
    today=datetime.now(timezone.utc).astimezone(KST).date().isoformat()
    with connect(db_path) as db:
        today_rows=[dict(x) for x in db.execute('SELECT kind,state,count(*) n FROM parts WHERE publication_date=? GROUP BY kind,state',(today,))]
    from .authoring import load_hook_templates
    value={
        'schema':'threads-pilot-v1',
        'checkedAt':settings.stamp(),
        'configuration':{k:config.get(k) for k in ('enabled','account_key','accountConfirmed','model','provider','trialDays','continuousMode','activatedAt','startDate','endDate','mainDailyCap','maxFollowups','preferredTimes','slotModes','followupDelaySeconds')}|{'status':status,'apiConnected':connected,'connection':{k:connection.get(k) for k in ('status','checkedAt','reason')}},
        'counts':counts,
        'recent':recent,
        'pairedThreads':list(threads_by_attempt.values()),
        'hookVault':load_hook_templates(),
        'automation':{'state':'needs_connection' if not connected else 'waiting' if config['enabled'] else 'disabled','nextEligibleAt':None,**runtime.get('lastRun',{})},
        'measurement':runtime.get('measurement',{'status':'not_collected','complete':False,'scope':'threads_pilot_only','collected_at':None,'windows':{},'revenue':None}),
        'feedback':{'status':'insufficient_data','checkpoints':['24h','72h','7d']},
        'revenue':None,
    }
    value['connection']={k:connection.get(k) for k in ('status','checkedAt','reason','connected','account_verified')}
    value['connection']['checkedAt']=connection.get('checkedAt') or connection.get('checked_at')
    value['configuration']['connection']['checkedAt']=value['connection']['checkedAt']
    for key in ('publishReady','readinessStatus','scopesStatus','grantedScopes','missingScopes','expiryStatus','expiresAtUTC','tokenUserMatches','quotaStatus','quota'):
        if key in connection:value['connection'][key]=connection[key]
    value['configuration']['endsAt']=config.get('endsAt')
    value['configuration']['mainTrialCap']=int(config.get('mainTrialCap',56))
    value['today']={'date':today,'timezone':'Asia/Seoul','counts':[dict(x) for x in today_rows]}
    value['countsScope']='all_time_parts_not_today'
    value['countsComplete']=True
    if config.get('enabled') and connection.get('publishReady') is True:
        now=datetime.now(timezone.utc)
        end=datetime.fromisoformat(config['endsAt']) if config.get('endsAt') and not config.get('continuousMode') else (now+timedelta(days=365))
        total_main=sum(1 for r in rows if r['kind']=='main' and r['state'] in CONSUMED)
        trial_cap=int(config.get('mainTrialCap',56))
        if config.get('continuousMode') or total_main<trial_cap:
            for offset in range(15):
                day=(now.astimezone(KST).date()+timedelta(days=offset)).isoformat()
                used={r['slot'] for r in rows if r['publication_date']==day and r['kind']=='main'}
                options=[datetime.fromisoformat(day+'T'+s).replace(tzinfo=KST) for s in sorted(config['preferredTimes']) if s not in used]
                future=[t for t in options if now<t<end]
                if future:
                    value['automation']['nextEligibleAt']=future[0].isoformat();break
    value['automation']['scheduler']=runtime.get('scheduler',{'registered':None,'enabled':None,'state':'unverified','checkedAt':None,'nextRunAt':None,'lastResult':None})
    if runtime.get('lastRun',{}).get('lastResult')=='trial_ended' and config.get('enabled') and not config.get('continuousMode'):
        value['automation']['state']='ended'
    if runtime.get('measurement',{}).get('feedback'):value['feedback']=runtime['measurement']['feedback']
    if connection.get('status')=='unchecked':
        value['configuration']['apiConnected']=None;value['configuration']['status']='needs_connection'
    write(output,value);return value
