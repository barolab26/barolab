"""Single-account polling worker. Disabled means snapshot-only, no network/model."""
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import os
import subprocess
import sys
try:
    from . import config as settings,pipeline
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from threads_posting import config as settings,pipeline

def current_slot(config,now,used_slots=()):
    past=[s for s in config['preferredTimes'] if s<=now.astimezone(pipeline.KST).strftime('%H:%M')]
    latest=max(past) if past else None
    return latest if latest and latest not in used_slots and not any(s>latest for s in used_slots) else None

def observe_task(db_path=settings.DB):
    command="$t=Get-ScheduledTask -TaskName 'BaroLab-Threads-Pilot' -ErrorAction Stop; $i=Get-ScheduledTaskInfo -TaskName 'BaroLab-Threads-Pilot' -ErrorAction Stop; @{registered=$true;enabled=[bool]$t.Settings.Enabled;state=$t.State.ToString();nextRunAt=$i.NextRunTime.ToString('o');lastResult=$i.LastTaskResult}|ConvertTo-Json -Compress"
    value={'registered':None,'enabled':None,'state':'unverified','checkedAt':settings.stamp(),'nextRunAt':None,'lastResult':None}
    try:
        result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,encoding='utf-8',timeout=15,env=export_environment(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode==0:value.update(json.loads(result.stdout))
    except (OSError,ValueError,subprocess.TimeoutExpired):pass
    with pipeline.connect(db_path) as db:db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('scheduler',json.dumps(value)))
    return value

@contextmanager
def lock(path=None):
    path=Path(path or settings.PRIVATE/'threads-scheduler.lock');path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b');handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:handle.close();raise RuntimeError('worker_already_running') from None
    try:yield
    finally:
        handle.seek(0)
        if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()

from common.ego_telemetry import observed_operation, action as ego_action, export_environment


@observed_operation('threads', 'threads-scheduler', requester='scheduler')
def tick(config_path=settings.CONFIG,db_path=settings.DB,output=settings.PUBLIC):
    with lock():
        config=settings.load(config_path)
        if not config.get('enabled') or config.get('connection',{}).get('connected') is not True:
            pipeline.snapshot(config,db_path,output);return {'state':'noop','reason':'disabled_or_needs_connection'}
        now=datetime.now(timezone.utc)
        with ego_action('tool','threads-recovery'):
            pipeline.recover_unknown(config,db_path)
        with ego_action('tool','threads-reconcile'):
            pipeline.reconcile(config,db_path)
        from . import measurement
        with pipeline.connect(db_path) as db:
            publications=[dict(r) for r in db.execute("SELECT * FROM parts WHERE state='published_verified'")]
        if getattr(measurement,'should_collect',lambda p:False)(publications):
            with ego_action('tool','threads-measurement'):
                measured=measurement.collect(config,publications)
            with pipeline.connect(db_path) as db:
                db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('measurement',json.dumps(measured)))
        try:day=pipeline._gate(config,now)
        except RuntimeError:
            result={'state':'trial_ended','reason':'publication_closed_measurement_continues'}
            with pipeline.connect(db_path) as db:db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('lastRun',json.dumps({'lastRunAt':settings.stamp(),'lastResult':result['state'],'issue':result['reason']})))
            pipeline.snapshot(config,db_path,output);return result
        with pipeline.connect(db_path) as db:
            latest_slot=current_slot(config,now)
            now_hm=now.astimezone(pipeline.KST).strftime('%H:%M')
            candidate_rows=db.execute("SELECT * FROM parts p WHERE state='queued' AND publication_date=? AND slot<=? AND ((kind='main' AND slot=?) OR (kind='followup' AND EXISTS(SELECT 1 FROM parts parent WHERE parent.attempt_id=p.attempt_id AND parent.kind='main' AND parent.state='published_verified'))) ORDER BY kind='followup',created_at",(day,now_hm,latest_slot)).fetchall()
            due=None
            waiting_followup_delay=False
            for cand in candidate_rows:
                if cand['kind']=='followup':
                    parent=db.execute("SELECT * FROM parts WHERE attempt_id=? AND kind='main' AND state='published_verified'",(cand['attempt_id'],)).fetchone()
                    doc=json.loads(cand['document'])
                    if not parent or not pipeline.is_followup_delay_satisfied(parent,doc,now):
                        waiting_followup_delay=True
                        continue
                due=(cand['part_id'],)
                break
            used_slots={x[0] for x in db.execute("SELECT DISTINCT slot FROM parts WHERE publication_date=?",(day,))}
            used_slots.update(x[0] for x in db.execute('SELECT slot FROM authoring_slots WHERE account_key=? AND day=?',(config['account_key'],day)))
            attempted=db.execute("SELECT count(*) FROM parts WHERE publication_date=? AND kind='main' AND state IN ('sending_intent','submitted_unknown','api_submitted','published_verified')",(day,)).fetchone()[0]
        if not due and attempted<config['mainDailyCap'] and not waiting_followup_delay:
            selected_slot=current_slot(config,now,used_slots)
            slots=[selected_slot] if selected_slot else []
            if slots:
                from .authoring import prepare_next
                with pipeline.connect(db_path) as db:db.execute('INSERT INTO authoring_slots VALUES(?,?,?,?,?,?)',(config['account_key'],day,slots[0],'claimed',None,settings.stamp()))
                try:
                    with ego_action('tool','threads-authoring'):
                        result=prepare_next(config,day,slots[0],db_path)
                except Exception:
                    with pipeline.connect(db_path) as db:db.execute("UPDATE authoring_slots SET state='blocked',reason='authoring_failed',updated_at=? WHERE account_key=? AND day=? AND slot=?",(settings.stamp(),config['account_key'],day,slots[0]))
                    raise
                with pipeline.connect(db_path) as db:db.execute('UPDATE authoring_slots SET state=?,reason=?,updated_at=? WHERE account_key=? AND day=? AND slot=?',(result['state'],result.get('reason'),settings.stamp(),config['account_key'],day,slots[0]))
            else:result={'state':'waiting','reason':'no_due_slot'}
        else:result={'state':'waiting','reason':'followup_delay_waiting' if waiting_followup_delay else 'no_reviewed_due_draft'}
        if due:result=pipeline.publish(due[0],config,db_path,config_loader=lambda:settings.load(config_path))
        with pipeline.connect(db_path) as db:db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('lastRun',json.dumps({'lastRunAt':settings.stamp(),'lastResult':result['state'],'issue':result.get('reason')})))
        pipeline.snapshot(settings.load(config_path),db_path,output);return result

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--tick',action='store_true');parser.add_argument('--dry-run',action='store_true');args=parser.parse_args()
    if args.dry_run:
        config=settings.load();print(json.dumps({'enabled':config['enabled'],'would_publish':False,'reviewed_queue_only':True,'account_key':config['account_key']},ensure_ascii=False));return
    try:
        observe_task()
        result=tick()
    except Exception as exc:
        result={'state':'blocked','reason':type(exc).__name__}
        with pipeline.connect() as db:db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('lastRun',json.dumps({'lastRunAt':settings.stamp(),'lastResult':'blocked','issue':type(exc).__name__})))
        pipeline.snapshot(settings.load())
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
