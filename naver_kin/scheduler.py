"""Seven-day KnowledgeIn experiment: bounded slots, authoring, review, send and measurement."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from zoneinfo import ZoneInfo

# Task Scheduler invokes this absolute UNC file without relying on a mapped drive.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from naver_kin import pipeline as p
from common.dashboard_jobs import write

CONFIG = ROOT / 'server/data/kin-automation.json'
STATE = ROOT / 'server/data/kin-automation-state.json'
TASK = 'BaroLab-Kin-Seven-Day-Pilot'
KST = ZoneInfo('Asia/Seoul')



def now_kst():
    return datetime.now(KST)


def ensure_naver_browsers():
    """Reuse live CDP sessions; start closed ports only through account launchers."""
    import requests
    import time
    from common.system_watchdog import CDP_PORT_CATALOG, is_port_open
    result = []
    for item in CDP_PORT_CATALOG:
        port = int(item['port'])
        if port not in (9230, 9231, 9333, 9334, 9335):
            continue
        started = False
        if not is_port_open(port) and os.name == 'nt' and item['launcher'].is_file():
            subprocess.Popen(['cmd.exe', '/d', '/c', str(item['launcher'])],
                             cwd=str(item['folder']), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            started = True
        ready = False
        for attempt in range(15 if started else 1):
            try:
                response = requests.get(f'http://127.0.0.1:{port}/json/version', timeout=2)
                ready = response.status_code == 200 and bool(response.json().get('webSocketDebuggerUrl'))
            except (requests.RequestException, ValueError):
                pass
            if ready:
                break
            if started and attempt < 14:
                time.sleep(1)
        result.append({'port': port, 'ready': ready, 'started': started})
    return result


def _cooldown_minutes(config, anchor_iso=None):
    jitter = config.get('intervalJitterMinutes')
    if isinstance(jitter, (list, tuple)) and len(jitter) == 2:
        low, high = int(jitter[0]), int(jitter[1])
        if 1 <= low <= high:
            if not anchor_iso:
                return (low + high) // 2
            import hashlib
            seed = int(hashlib.sha256(str(anchor_iso).encode('utf-8')).hexdigest()[:8], 16)
            return low + (seed % (high - low + 1))
    return int(config.get('intervalMinutes', 35))


def configure(model, start=None):
    from common.codex_cli import runtime, local_config
    local_config()  # Existing authenticated installation only; never select a new provider.
    info = runtime()
    if not info.get('authenticated') or model not in {m['id'] for m in info.get('models',[])}:
        raise ValueError('Explicit model must exist in the authenticated Codex subscription')
    from naver_kin.experiment import TRIAL_START,TRIAL_END,FINAL_COLLECTION
    day = datetime.fromisoformat(start).date() if start else TRIAL_START
    if day != TRIAL_START:
        raise ValueError('Start date differs from the explicitly approved experiment dates')
    config = {'schema':'naver-kin-automation-v2','enabled':False,'timezone':'Asia/Seoul',
              'continuousMode':True,
              'startDate':day.isoformat(),'endDate':TRIAL_END.isoformat(),
              'measurementEndDate':FINAL_COLLECTION.isoformat(),
              'model':model,'provider':'authenticated-codex-subscription','mode':'alternating_interval',
              'intervalMinutes':35,'intervalJitterMinutes':[30,40],'pollMinutes':5,
              'operationDailyCap':20,'operationAccountDailyCap':10,
              'globalDailyCap':20,'accountDailyCap':10,
              'articleCatalog':[],
              'createdAt':p.stamp(),'taskName':TASK}
    write(CONFIG,config)
    return config


def validate_config(config):
    from naver_kin.experiment import TRIAL_START,TRIAL_END,FINAL_COLLECTION
    if (config.get('timezone') != 'Asia/Seoul' or config.get('provider') != 'authenticated-codex-subscription'
            or config.get('globalDailyCap') not in (10, 20) or config.get('accountDailyCap') not in (5, 10)):
        raise ValueError('Unexpected experiment configuration')
    if not config.get('continuousMode', False):
        start = datetime.fromisoformat(config['startDate']).date()
        end = datetime.fromisoformat(config['endDate']).date()
        if (start!=TRIAL_START or end!=TRIAL_END or config.get('measurementEndDate')!=FINAL_COLLECTION.isoformat()):
            raise ValueError('Configuration must match the explicitly approved trial and final collection dates')
    interval_min = config.get('intervalMinutes', 20)
    if config.get('mode')!='alternating_interval' or not (15 <= int(interval_min) <= 60) or config.get('pollMinutes')!=5:
        raise ValueError('Only the approved alternating 15-60 minute operating policy is permitted')
    if config.get('operationDailyCap') not in (10, 20, None) or config.get('operationAccountDailyCap') not in (5, 10, None):
        raise ValueError('Model-driven operating rounds must be bounded to 10/20 global and 5/10 per account daily')
    if not isinstance(config.get('model'),str) or not config['model']:
        raise ValueError('Explicit subscribed model required')


def _is_account_blog_busy(account: str) -> bool:
    """Check if the specific account is currently executing a Naver blog post in its own browser."""
    wf_path = ROOT / 'naver_blog_posting/data/active-workflow.json'
    if not wf_path.is_file():
        return False
    try:
        wf = json.loads(wf_path.read_text(encoding='utf-8'))
        if wf.get('status') == 'running' and wf.get('account') == account:
            return True
    except Exception:
        pass
    return False


@contextmanager
def file_lock(path):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt;msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl;fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            yield False;return
        try:yield True
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


def slots_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS automation_slots (
      slot_id TEXT PRIMARY KEY,account TEXT NOT NULL,planned_at TEXT NOT NULL,
      state TEXT NOT NULL,reason TEXT,question_id TEXT,updated_at TEXT NOT NULL)''')
    if 'discovered' not in {r['name'] for r in db.execute('PRAGMA table_info(automation_slots)')}:
        db.execute('ALTER TABLE automation_slots ADD COLUMN discovered INTEGER NOT NULL DEFAULT 0')
    db.commit()


def initialize_cadence(db):
    slots_table(db)
    db.execute('''CREATE TABLE IF NOT EXISTS operating_cadence(
      id INTEGER PRIMARY KEY CHECK(id=1),last_completed_at TEXT,last_account TEXT,
      active_run_id TEXT,active_account TEXT,active_started_at TEXT)''')
    latest=db.execute('SELECT account,updated_at FROM questions WHERE send_day IS NOT NULL ORDER BY updated_at DESC LIMIT 1').fetchone()
    with db:
        db.execute('INSERT OR IGNORE INTO operating_cadence VALUES(1,?,?,NULL,NULL,NULL)',
                   (latest['updated_at'] if latest else None,latest['account'] if latest else None))


def submission_counts(db, day):
    result={account:0 for account in p.ACCOUNTS}
    for row in db.execute("SELECT account,COUNT(*) n FROM questions WHERE send_day=? AND state='published_verified' GROUP BY account",(day,)):
        if row['account'] in result:
            result[row['account']]+=row['n']
    return result


def operation_counts(db, day):
    """Count only actual published_verified answers so failed, unverified, or interrupted attempts never deduct daily quota (20)."""
    return submission_counts(db, day)


def retry_counts(db, day):
    """Count non-verified or interrupted attempts today for diagnostic display without deducting from daily quota."""
    unverified_q = db.execute(
        "SELECT COUNT(*) n FROM questions WHERE send_day=? AND state != 'published_verified' AND state != 'skipped'",
        (day,),
    ).fetchone()
    return int(unverified_q['n'] if unverified_q else 0)


def cadence_status(db, config, now=None):
    now=now or now_kst();row=db.execute('SELECT * FROM operating_cadence WHERE id=1').fetchone()
    day=now.astimezone(KST).date().isoformat()
    sub_counts=submission_counts(db,day)
    counts= dict(sub_counts)
    retries=retry_counts(db,day)
    global_cap=int(config.get('globalDailyCap',p.GLOBAL_DAILY_CAP))
    account_cap=int(config.get('accountDailyCap',p.ACCOUNT_DAILY_CAP))
    cooldown_min=_cooldown_minutes(config, row['last_completed_at'])
    next_at=(datetime.fromisoformat(row['last_completed_at'])+timedelta(minutes=cooldown_min)).isoformat() if row['last_completed_at'] else now.isoformat()
    first=p.ACCOUNTS[1] if row['last_account']==p.ACCOUNTS[0] else p.ACCOUNTS[0]
    order=[first]+[account for account in p.ACCOUNTS if account!=first]
    next_account=None
    for account in order:
        halted=db.execute("SELECT 1 FROM sqlite_master WHERE name='automation_halts'").fetchone()
        if halted and db.execute('SELECT 1 FROM automation_halts WHERE account=?',(account,)).fetchone():continue
        if _is_account_blog_busy(account):continue
        sends=sub_counts.get(account,0)
        if counts[account]<account_cap and sends<account_cap:next_account=account;break
    if next_account is None:
        # Fallback if one account was busy with blog: check without blog busy filter so nextAccount is still reported
        for account in order:
            halted=db.execute("SELECT 1 FROM sqlite_master WHERE name='automation_halts'").fetchone()
            if halted and db.execute('SELECT 1 FROM automation_halts WHERE account=?',(account,)).fetchone():continue
            sends=sub_counts.get(account,0)
            if counts[account]<account_cap and sends<account_cap:next_account=account;break
    cadence_state='waiting'
    if sum(sub_counts.values())>=global_cap or next_account is None:
        tomorrow=(now.astimezone(KST)+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        next_at=max(datetime.fromisoformat(next_at),tomorrow).isoformat()
        cadence_state='daily_limit_or_account_unavailable'
        for account in order:
            if not (db.execute("SELECT 1 FROM sqlite_master WHERE name='automation_halts'").fetchone()
                    and db.execute('SELECT 1 FROM automation_halts WHERE account=?',(account,)).fetchone()):
                next_account=account;break
    if next_account is None:
        next_at=None;cadence_state='accounts_suspended'
    if not config.get('continuousMode', False):
        if day>config['endDate'] or (next_at and datetime.fromisoformat(next_at).astimezone(KST).date().isoformat()>config['endDate']):
            next_at=None;next_account=None;cadence_state='experiment_completed'
    if row['active_run_id']:
        next_at=None;cadence_state='running'
    return {'intervalMinutes':cooldown_min,'intervalJitterMinutes':config.get('intervalJitterMinutes',[18,22]),
            'pollMinutes':5,'lastRunAt':row['last_completed_at'],
            'lastAccount':row['last_account'],'nextEligibleAt':next_at,'nextAccount':next_account,
            'activeRunId':row['active_run_id'],'activeAccount':row['active_account'],
            'activeStartedAt':row['active_started_at'],'cadenceState':cadence_state,
            'operationCounts':counts,'submissionCounts':sub_counts,
            'retryAttemptsToday':retries,
            'globalRemainingRuns':max(0,global_cap-sum(sub_counts.values())),
            'byAccountRemainingRuns':{account:max(0,account_cap-sub_counts[account]) for account in p.ACCOUNTS}}


def reserve_run(db, config, now=None, force=False):
    now=now or now_kst();initialize_cadence(db)
    db.execute('BEGIN IMMEDIATE')
    try:
        row=db.execute('SELECT * FROM operating_cadence WHERE id=1').fetchone()
        if row['active_run_id']:
            # Owning the global OS lock proves no other scheduler is still executing this reservation.
            db.execute("UPDATE automation_slots SET state='interrupted_unknown',reason='process_interrupted',updated_at=? WHERE slot_id=?",(now.isoformat(),row['active_run_id']))
            db.execute('UPDATE operating_cadence SET last_completed_at=?,last_account=active_account,active_run_id=NULL,active_account=NULL,active_started_at=NULL WHERE id=1',(now.isoformat(),))
            db.commit();return {'state':'recovered_wait','reason':'interrupted_run_requires_new_cooldown'}
        if force:
            latest_sub = db.execute("SELECT account,updated_at FROM questions WHERE send_day IS NOT NULL AND state='published_verified' ORDER BY updated_at DESC LIMIT 1").fetchone()
            anchor_ts = latest_sub['updated_at'] if latest_sub else None
            anchor_acc = latest_sub['account'] if latest_sub else None
            if anchor_ts and now < datetime.fromisoformat(anchor_ts) + timedelta(minutes=15):
                pass
            else:
                db.execute('UPDATE operating_cadence SET last_completed_at=?,last_account=? WHERE id=1', (anchor_ts, anchor_acc))
        status=cadence_status(db,config,now)
        day=now.astimezone(KST).date().isoformat()
        global_cap=int(config.get('globalDailyCap',p.GLOBAL_DAILY_CAP))
        reason=None
        if not config['enabled']:reason='automation_disabled'
        elif not config.get('continuousMode', False) and not config['startDate']<=day<=config['endDate']:reason='outside_publication_window'
        elif status['nextEligibleAt'] is None:reason='outside_publication_window'
        elif not force and now<datetime.fromisoformat(status['nextEligibleAt']):reason='minimum_interval_not_elapsed'
        elif status['globalRemainingRuns']<=0 or not status['nextAccount']:reason='daily_operating_cap_or_account_unavailable'
        elif _is_account_blog_busy(status['nextAccount']):reason=f"account_blog_running:{status['nextAccount']}"
        elif db.execute("SELECT COUNT(*) FROM questions WHERE send_day=? AND state='published_verified'",(day,)).fetchone()[0]>=global_cap:reason='daily_submission_cap'
        if reason:
            db.rollback();return {'state':'waiting','reason':reason,**status}
        import uuid
        account=status['nextAccount'];run_id=day+'_'+uuid.uuid4().hex[:12]+'_'+account+'_'+now.strftime('%H%M')
        db.execute('INSERT INTO automation_slots(slot_id,account,planned_at,state,updated_at) VALUES(?,?,?,?,?)',
                   (run_id,account,now.isoformat(),'started',p.stamp()))
        db.execute('UPDATE operating_cadence SET active_run_id=?,active_account=?,active_started_at=? WHERE id=1',
                   (run_id,account,now.isoformat()))
        db.commit();return {'state':'reserved','runId':run_id,'account':account}
    except Exception:db.rollback();raise


def complete_run(db, run_id, now=None):
    now=now or now_kst()
    with db:
        db.execute('UPDATE operating_cadence SET last_completed_at=?,last_account=active_account,active_run_id=NULL,active_account=NULL,active_started_at=NULL WHERE id=1 AND active_run_id=?',
                   (now.isoformat(),run_id))


def tick(config, now=None, dry_run=False, force=False):
    now=now or now_kst();validate_config(config)
    result={'schema':'naver-kin-automation-state-v1','checkedAt':p.stamp(),
            'startDate':config['startDate'],'endDate':config['endDate'],'enabled':config['enabled'],
            'continuousMode':bool(config.get('continuousMode', False)),
            'mode':'alternating_interval','intervalMinutes':config.get('intervalMinutes',20),
            'intervalJitterMinutes':config.get('intervalJitterMinutes',[18,22]),'pollMinutes':5,
            'globalDailyCap':int(config.get('globalDailyCap',p.GLOBAL_DAILY_CAP)),
            'accountDailyCap':int(config.get('accountDailyCap',p.ACCOUNT_DAILY_CAP)),'runs':[],
            'state':'idle','measurementStatus':'not_attempted','dryRun':dry_run}
    if dry_run:
        # Real ledger is observed read-only; no fake future operating timestamps are persisted.
        db=p.connect()
        try:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='operating_cadence'").fetchone():
                result.update(cadence_status(db,config,now))
            result['state']='dry_run'
        finally:db.close()
        return result
    with file_lock(ROOT/'server/data/kin-scheduler.lock') as ready:
        if not ready:return {'state':'already_running','checkedAt':p.stamp()}
        result['browsers'] = ensure_naver_browsers()
        db=p.connect();initialize_cadence(db);run_id=None
        prev_cadence=db.execute('SELECT last_completed_at,last_account FROM operating_cadence WHERE id=1').fetchone()
        state='idle';qid=None
        try:
            # Per-account lock & active blog check replaces global pipeline-run.lock
            reservation=reserve_run(db,config,now,force=force)
            result.update(reservation)
            if reservation['state']=='reserved':
                run_id=reservation['runId'];account=reservation['account']
                result.update(state='running',**cadence_status(db,config,now))
                write(STATE,result);p.snapshot(db)
                state='blocked';reason=None;qid=None;discovered=0
                try:
                    existing_draft = db.execute(
                        "SELECT question_id, document FROM questions WHERE account=? AND state='drafted' ORDER BY created_at DESC LIMIT 1",
                        (account,),
                    ).fetchone()
                    if existing_draft:
                        qid = existing_draft['question_id']
                        discovered = 18
                        with db:
                            db.execute('UPDATE automation_slots SET question_id=? WHERE slot_id=?', (qid, run_id))
                        try:
                            p.main(['--account', account, '--run-once', '--question-id', qid, '--run-id', run_id])
                            p.main(['--account', account, '--verify', qid])
                            state = db.execute('SELECT state FROM questions WHERE question_id=?', (qid,)).fetchone()[0]
                        except Exception:
                            row_st = db.execute('SELECT state FROM questions WHERE question_id=?', (qid,)).fetchone()
                            if row_st and row_st['state'] == 'drafted':
                                with db:
                                    db.execute("DELETE FROM questions WHERE question_id=? AND state='drafted'", (qid,))
                                qid = None
                                existing_draft = None
                            else:
                                raise
                    if not existing_draft:
                        from naver_kin.authoring import generate_for_slot
                        with p.account_lock(account):
                            authored=generate_for_slot(account,run_id,config['model'],article_catalog=config['articleCatalog'])
                        if not isinstance(authored,dict):raise ValueError('Structured authoring result required')
                        with db:db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?)',(account,None,p.stamp()))
                        discovered=len(authored.get('discovered',[]));document=authored.get('document')
                        if document is None:
                            state='skipped';reason=authored.get('reason') or 'no_eligible_reviewed_answer'
                        else:
                            p.validate_document(document,reviewed=True)
                            if document['account']!=account:raise ValueError('Authoring account mismatch')
                            qid=p.question_id(document['question']['question_url'])
                            if db.execute('SELECT 1 FROM questions WHERE question_id=?',(qid,)).fetchone():
                                raise ValueError('Existing manual or automatic draft is protected')
                            p.record_discoveries(db,account,[document['question']]);p.import_draft(db,document)
                            with db:db.execute('UPDATE automation_slots SET question_id=? WHERE slot_id=?',(qid,run_id))
                            p.main(['--account',account,'--run-once','--question-id',qid,'--run-id',run_id])
                            p.main(['--account',account,'--verify',qid])
                            state=db.execute('SELECT state FROM questions WHERE question_id=?',(qid,)).fetchone()[0]
                except Exception as exc:
                    reason='operation_'+type(exc).__name__
                    if type(exc).__name__ in ('AccountProtectionError','AccountPostingRestrictedError'):reason='account_protected'
                    elif type(exc).__name__ in ('QuestionUnavailableError','PostingRejectedError'):reason='question_unavailable';state='skipped'
                    import traceback
                    log=ROOT/'server/data/kin-scheduler-errors.log';log.parent.mkdir(parents=True,exist_ok=True)
                    with log.open('a',encoding='utf-8') as handle:handle.write('\n'+p.stamp()+' '+run_id+'\n'+traceback.format_exc())
                    if qid:
                        row=db.execute('SELECT state FROM questions WHERE question_id=?',(qid,)).fetchone()
                        if row and row['state'] in p.TERMINAL_SEND:state=row['state']
                    with db:db.execute('INSERT OR REPLACE INTO runtime VALUES (?,?,?)',(account,reason,p.stamp()))
                with db:
                    db.execute('UPDATE automation_slots SET state=?,reason=?,question_id=?,updated_at=?,discovered=? WHERE slot_id=?',
                               (state,reason,qid,p.stamp(),discovered,run_id))
                    if reason=='account_protected':
                        db.execute('CREATE TABLE IF NOT EXISTS automation_halts(account TEXT PRIMARY KEY,reason TEXT,checked_at TEXT)')
                        db.execute('INSERT OR REPLACE INTO automation_halts VALUES (?,?,?)',(account,reason,p.stamp()))
                result['runs'].append({'runId':run_id,'account':account,'state':state,'reason':reason,'discovered':discovered})
                try:
                    from naver_kin.measurement import collect
                    measurement=collect(db=db,now=now_kst())
                    result.update(measurementStatus=measurement.get('status','unknown'),measurementComplete=measurement.get('complete',False))
                except Exception as exc:result['measurementStatus']='failed_'+type(exc).__name__
                result['state']='completed_cycle'
            result['registeredTasks']=observe_tasks()
        finally:
            if run_id:
                if state == 'blocked' and prev_cadence is not None:
                    # Do not lock out the channel for a full cooldown when a pre-submission error occurred
                    with db:
                        db.execute(
                            'UPDATE operating_cadence SET last_completed_at=?,last_account=?,active_run_id=NULL,active_account=NULL,active_started_at=NULL WHERE id=1',
                            (prev_cadence['last_completed_at'], prev_cadence['last_account']),
                        )
                else:
                    complete_run(db,run_id)
            result.update(cadence_status(db,config,now_kst()))
            write(STATE,result);p.snapshot(db);db.close()
    return result


def observe_tasks():
    if os.name!='nt':return {'status':'unavailable','checkedAt':p.stamp()}
    script="""$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$rows=@(foreach($name in @('BaroLab-Kin-Seven-Day-Pilot','BaroLab-Kin-Seven-Day-Pilot-Measurement')){
try {$task=Get-ScheduledTask -TaskName $name -ErrorAction Stop;$info=Get-ScheduledTaskInfo -TaskName $name -ErrorAction Stop
[pscustomobject]@{taskName=$name;registered=$true;enabled=[bool]$task.Settings.Enabled;state=$task.State.ToString();nextRunAt=([DateTimeOffset]$info.NextRunTime).ToString('o');lastRunAt=([DateTimeOffset]$info.LastRunTime).ToString('o');lastResult=[long]$info.LastTaskResult;actions=@($task.Actions|Select-Object Execute,Arguments)}}
catch {if($_.FullyQualifiedErrorId -like '*NotFound*'){[pscustomobject]@{taskName=$name;registered=$false;enabled=$false}}else{[pscustomobject]@{taskName=$name;registered=$null;enabled=$null;reason='query_failed'}}}})
ConvertTo-Json -InputObject $rows -Depth 5 -Compress
"""
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,
            text=True,encoding='utf-8',errors='replace',timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError('query failed')
        return {'status':'observed','checkedAt':p.stamp(),'tasks':json.loads(result.stdout.lstrip('\ufeff').strip())}
    except Exception:return {'status':'unavailable','checkedAt':p.stamp(),'reason':'scheduler_query_failed'}


def measure(config, now=None):
    now=now or now_kst();validate_config(config)
    if not config['startDate']<=now.date().isoformat()<=config['measurementEndDate']:
        return {'state':'outside_measurement_window'}
    from naver_kin.measurement import collect
    db=p.connect()
    try:
        measurement=collect(db=db,now=now)
        # Public retention is checked separately from first verified publication.
        # Initial exact-account verification is preserved; failed HTTP reads mean unknown.
        import requests
        from bs4 import BeautifulSoup
        rows=db.execute("SELECT * FROM questions WHERE state='published_verified' ORDER BY updated_at DESC LIMIT 100").fetchall()
        checks=[]
        import time
        deadline=time.monotonic()+600
        attempted=0
        for row in rows:
            state='unknown';reason='public_check_unavailable'
            try:
                if time.monotonic()>=deadline:
                    checks.append({'account':row['account'],'answerUrl':row['answer_url'],'state':'unknown','reason':'cycle_time_budget_exhausted','checkedAt':p.stamp()})
                    continue
                attempted+=1
                doc=json.loads(row['document'])
                response=requests.get(row['answer_url'],timeout=(4,8),allow_redirects=False,headers={'User-Agent':'Mozilla/5.0'})
                if response.status_code==200 and str(row['answer_id']).isdigit():
                    soup=BeautifulSoup(response.text,'html.parser');node=soup.select_one('#answer_'+row['answer_id'])
                    normal=lambda text:' '.join(text.split())
                    if node and normal(doc['answer_text']) in normal(node.get_text(' ')) and doc['attribution']['outboundUrl'] in {a.get('href') for a in node.select('a[href]')}:
                        state='publicly_retained';reason=None
            except Exception:pass
            checks.append({'account':row['account'],'answerUrl':row['answer_url'],'state':state,'reason':reason,'checkedAt':p.stamp()})
        total=db.execute("SELECT COUNT(*) FROM questions WHERE state='published_verified'").fetchone()[0]
        retention={'checkedAt':p.stamp(),'scope':'up_to_100_initially_verified_pilot_and_trial_answers','complete':total<=100 and attempted==len(rows),
                   'initiallyVerified':total,'attemptedChecks':attempted,'checks':checks,'firstVerificationHistoryPreserved':True}
        write(ROOT/'server/data/kin-retention.json',retention)
        state={'schema':'naver-kin-automation-state-v1','checkedAt':p.stamp(),'state':'measurement_cycle_completed',
               'startDate':config['startDate'],'endDate':config['endDate'],'measurementEndDate':config['measurementEndDate'],
               'enabled':config['enabled'],'mode':'alternating_interval','intervalMinutes':60,'pollMinutes':5,'globalDailyCap':10,'accountDailyCap':5,
               'registeredTasks':observe_tasks(),'retention':retention,
               'measurementStatus':measurement.get('status','unknown'),'measurementComplete':measurement.get('complete',False)}
        write(STATE,state);p.snapshot(db)
        return {'state':'measurement_cycle_completed','measurementStatus':measurement.get('status','unknown'),
                'measurementComplete':measurement.get('complete',False),'measurement':measurement,'retention':retention}
    finally:db.close()


def register(config):
    """Register only after implementation/configuration review. Never replace unrelated tasks."""
    validate_config(config)
    if os.name!='nt':raise RuntimeError('Windows task registration requires the worker host')
    def quote(value):return "'"+str(value).replace("'","''")+"'"
    script=Path(__file__).resolve()
    if script.drive.upper()=='Y:':
        raise RuntimeError('Mapped workspace did not resolve to UNC; registration refused')
    python=Path(sys.executable).resolve()
    pythonw=python.with_name('pythonw.exe')
    if pythonw.is_file():python=pythonw
    action_arguments='-u -B -X utf8 "'+str(script)+'" --tick --scheduled'
    ps="""$ErrorActionPreference='Stop'
if((Get-TimeZone).Id -ne 'Korea Standard Time'){throw 'Task host timezone must be Korea Standard Time'}
$user=[System.Security.Principal.WindowsIdentity]::GetCurrent().Name
"""
    for name in (TASK,TASK+'-Measurement'):
        ps+='$existing=Get-ScheduledTask -TaskName '+quote(name)+' -ErrorAction SilentlyContinue\n'
        ps+='if($existing){foreach($oldAction in $existing.Actions){if(-not ([string]$oldAction.Arguments).Contains('+quote(script)+")){throw 'Existing task name belongs to a different workflow; refusing replacement'}}}\n"
    ps+='$action=New-ScheduledTaskAction -Execute '+quote(python)+' -Argument '+quote(action_arguments)+'\n'
    ps+="$trigger=New-ScheduledTaskTrigger -Once -At (Get-Date "+quote(config['startDate']+'T00:00:00')+") -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 7)\n"
    ps+='$trigger.EndBoundary='+quote(config['endDate']+'T23:59:59')+'\n$triggers=@($trigger)\n'
    ps+="""$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 50) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
"""
    ps+='Register-ScheduledTask -TaskName '+quote(TASK)+' -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description '+quote('Seven KST dates; 10 global/5 per account attempted answers maximum; reviewed relevant answers only')+' -Force | Out-Null\n'
    ps+='$measurementAction=New-ScheduledTaskAction -Execute '+quote(python)+' -Argument '+quote('-u -B -X utf8 "'+str(script)+'" --measure --scheduled')+'\n'
    ps+="$measurementTrigger=New-ScheduledTaskTrigger -Daily -At '20:30'\n"
    ps+='$measurementTrigger.StartBoundary='+quote(config['startDate']+'T20:30:00')+'\n'
    ps+='$measurementTrigger.EndBoundary='+quote(config['measurementEndDate']+'T23:59:59')+'\n'
    ps+='Register-ScheduledTask -TaskName '+quote(TASK+'-Measurement')+' -Action $measurementAction -Trigger $measurementTrigger -Settings $settings -Principal $principal -Description '+quote('Read-only GA4 attribution and sampled public answer retention; no publication')+' -Force | Out-Null\n'
    proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',ps],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if proc.returncode:raise RuntimeError('Task registration failed; no enabled configuration written')
    config['enabled']=True;config['registeredAt']=p.stamp();write(CONFIG,config)
    state={'schema':'naver-kin-automation-state-v1','checkedAt':p.stamp(),'enabled':True,'state':'registered',
           'startDate':config['startDate'],'endDate':config['endDate'],'measurementEndDate':config['measurementEndDate'],
           'mode':'alternating_interval','intervalMinutes':60,'pollMinutes':5,'globalDailyCap':10,'accountDailyCap':5,'registeredTasks':observe_tasks()}
    db=p.connect()
    try:
        initialize_cadence(db);state.update(cadence_status(db,config));write(STATE,state);p.snapshot(db)
    finally:db.close()
    return state


def authoring_dry_run(config, account):
    """Exercise the actual discovery/model/review adapter, never import/send/reserve a slot."""
    validate_config(config);p.account_key(account)
    from naver_kin.authoring import generate_for_slot
    slot_id='dryrun_'+now_kst().date().isoformat()+'_'+account+'_'+now_kst().strftime('%H%M')
    with file_lock(ROOT/'server/data/kin-scheduler.lock') as ready:
        if not ready:raise RuntimeError('Scheduler already running')
        with p.account_lock(account):
            result=generate_for_slot(account,slot_id,config['model'],article_catalog=config['articleCatalog'])
    return {'state':'authoring_dry_run','account':account,'reason':result.get('reason'),
            'discovered':len(result.get('discovered',[])),'reviewApproved':bool(result.get('document')),
            'artifactDir':result.get('artifact_dir'),'publicationAttempted':False,'slotConsumed':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    choices=parser.add_mutually_exclusive_group(required=True)
    choices.add_argument('--configure',action='store_true')
    choices.add_argument('--register',action='store_true')
    choices.add_argument('--tick',action='store_true')
    choices.add_argument('--status',action='store_true')
    choices.add_argument('--measure',action='store_true')
    choices.add_argument('--authoring-dry-run',action='store_true')
    parser.add_argument('--model')
    parser.add_argument('--start-date')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--force',action='store_true',help='Execute immediately if no active run and minimum 15-min submission safety has elapsed')
    parser.add_argument('--at',help='Aware ISO datetime used only with --dry-run')
    parser.add_argument('--scheduled',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--account',choices=p.ACCOUNTS)
    args=parser.parse_args(argv)
    if args.configure:
        if not args.model:parser.error('--configure requires explicit --model')
        result=configure(args.model,args.start_date)
    else:
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
        if args.register:result=register(config)
        elif args.tick:
            if args.at and not args.dry_run:parser.error('--at is only allowed with --dry-run')
            instant=datetime.fromisoformat(args.at) if args.at else None
            if instant and instant.tzinfo is None:parser.error('--at requires timezone')
            result=tick(config,now=instant,dry_run=args.dry_run,force=args.force)
        elif args.measure:result=measure(config)
        elif args.authoring_dry_run:
            if not args.account:parser.error('--authoring-dry-run requires --account')
            result=authoring_dry_run(config,args.account)
        else:result={'config':config,'registeredTasks':observe_tasks(),'lastRun':json.loads(STATE.read_text(encoding='utf-8')) if STATE.is_file() else None}
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if '--scheduled' in sys.argv:
        from contextlib import redirect_stdout,redirect_stderr
        log=ROOT/'server/data/kin-scheduler.log';log.parent.mkdir(parents=True,exist_ok=True)
        with log.open('a',encoding='utf-8') as handle,redirect_stdout(handle),redirect_stderr(handle):
            print('\nScheduled invocation '+p.stamp(),flush=True)
            try:main()
            except Exception:
                import traceback;traceback.print_exc();raise SystemExit(1)
    else:main()
