"""Read-only mission cockpit. Collection runs off the terminal rendering thread."""
import argparse
import datetime as dt
import json
import math
import os
import re
import socket
import sqlite3
from contextlib import closing
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, TextColumn
from rich.table import Table
from rich.text import Text

ROOT = Path(__file__).resolve().parents[2]
KST = dt.timezone(dt.timedelta(hours=9))
ROLES = {'jarvis':'팀장', 'patch':'패치', 'publi':'퍼블리',
         'trace':'트레이스', 'doctor':'닥터', 'radar':'레이더'}
PORTS = (9334, 9333, 9335, 9231, 9230, 8790)
STAGES = {'original-work-diagnosis':'원작업 차단 원인 진단', 'repair-diagnosis-model':'수정할 코드 분석',
          'staff-response':'업무 결과 보고', 'staff-result-response':'직원 결과 정리',
          'staff-action-routing':'담당 업무 배정', 'keyword-selector':'키워드 선정',
          'writer':'원고 작성', 'researcher':'근거 자료 수집', 'reviewer':'원고 검수',
          'image-maker':'이미지 제작', 'lesson-extraction':'발행 결과 학습',
          'lesson-verification':'지식 검증', 'model-call':'모델 응답 생성', 'revenue-collection':'수익 원천 수집',
          'browser-lock-recovery':'브라우저 잠금 복구', 'audit-path-recovery':'모델 진단 경로 복구'}
TOOLS = {'advance_project_recovery':'원작업 복구 단계 처리', 'run_project_cycle':'발행 파이프라인 실행',
         'read_agent_status':'운영 상태 점검', 'repair_cf_known_failure':'CF 오류 수정'}
STAGES.update({'project-recovery-classification':'원작업 복구 담당 배정',
    'project-incident-triage':'발행 차단 원인 분류','project-instruction-issued':'직원 업무 배정',
    'project-result-review':'실행 결과 검토','project-result-reviewed':'실행 결과 검토',
    'repair-diagnosis':'코드 수정안 작성','repair-diagnosis-review':'수정안 검수',
    'repair-diagnosis-review-model':'수정안 독립 검수','staff-terminal-response':'업무 결과 보고',
    'handoff-accepted':'다음 직원에 인계',**TOOLS})
STAGES.update({'editorial-query':'지연 슬롯 추가 리서치','editorial-scope':'근거에 맞춘 범위 재승인',
               'editorial-pivot':'동일 슬롯 대체 주제 선정','editorial-watchdog':'당일 지연 슬롯 검사',
               'editorial-renewal':'오래된 초안의 동일 질문 재검수'})


def clean(value, limit=110):
    value = ''.join(c if c.isprintable() else ' ' for c in str(value or ''))
    return re.sub(r'\s+', ' ', value).strip()[:limit]


def error_reason(value):
    lines=str(value or '').strip().splitlines()
    reason=lines[-1] if lines else '원작업 복구 대기'
    return clean(reason,90)


def epoch(value):
    try:
        if isinstance(value, (float, int)):
            return float(value) if math.isfinite(value) else 0
        parsed = dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0


def valid_url(value):
    try:
        u = urlsplit(str(value or ''))
        return u.scheme in ('http','https') and bool(u.hostname) and not u.username and not u.password
    except ValueError:
        return False


class JsonCache:
    """Never cache a partial write; unchanged files require only a stat call."""
    def __init__(self):
        self.values = {}
        self.signatures = {}
        self.errors = set()

    def read(self, path, projection=None):
        path = Path(path)
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            if signature == self.signatures.get(path):
                self.errors.discard(path)
                return self.values[path]
            if not path.is_file() or stat.st_size > 12_000_000:
                raise ValueError('bounded object required')
            with path.open('rb') as stream:
                raw = stream.read(12_000_001)
            if len(raw) > 12_000_000:
                raise ValueError('file grew beyond bound')
            content=raw.decode('utf-8-sig')
            if path.name=='pipeline_status.js':
                matched=re.fullmatch(r'\s*window\.__NAVER_PIPELINE_STATUS__\s*=\s*(\{.*\})\s*;?\s*',content,re.S)
                if not matched:raise ValueError('invalid pipeline assignment')
                content=matched.group(1)
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError('object required')
            if projection is not None:value=projection(value)
            after = path.stat()
            if signature != (after.st_mtime_ns, after.st_size, after.st_ino):
                raise ValueError('concurrent write')
            self.values[path] = value
            self.signatures[path] = signature
            self.errors.discard(path)
        except (OSError, ValueError, UnicodeError):
            self.errors.add(path)
        return self.values.get(path, {})


def channels(cf, naver, kin, now):
    day = now.date().isoformat()
    clock = now.strftime('%H:%M')
    items = [r for r in cf.get('items',[]) if isinstance(r,dict)]
    current_cf = cf.get('date') == day
    done_cf = sum(r.get('status')=='published' and valid_url(r.get('publicUrl')) for r in items) if current_cf else None
    active = next((r for r in items if r.get('status')=='processing'), None) if current_cf else None
    upcoming = next((r for r in sorted(items,key=lambda r:str(r.get('scheduledTime','')))
                     if r.get('scheduledTime','')>=clock and r.get('status') not in ('published','failed','processing')),None) if current_cf else None
    cf_note = ('Order '+str(active.get('order'))+' · '+clean(active.get('stageName') or '작성 중',35)) if active else (
        '다음 Order '+str(upcoming.get('order'))+' · '+clean(upcoming.get('scheduledTime'))) if upcoming else '다음 슬롯 대기'
    if current_cf and not active and any(r.get('status')=='failed' for r in items):
        cf_note = '실패 원작업 복구 대기'
    slots = []
    current_nv = (naver.get('publicationDate') or naver.get('date')) == day
    for account in naver.get('accounts',[]):
        if not isinstance(account,dict):continue
        for slot in account.get('slots',[]):
            if isinstance(slot,dict) and slot.get('publicationDate',day)==day:
                slots.append({**slot,'account':account.get('account')})
    public = [r for r in slots if r.get('publicPublicationVerified') is True and valid_url(r.get('publicUrl'))]
    done_nv = len({r['publicUrl'] for r in public}) if current_nv else None
    reserved = sum((r.get('status') in ('reserved','scheduled') or r.get('publicationStatus')=='reserved')
                   and r.get('publicPublicationVerified') is not True for r in slots) if current_nv else 0
    runner = naver.get('runner') or {}
    tomorrow=(now.date()+dt.timedelta(days=1)).isoformat()
    future_slots=[s for a in naver.get('accounts',[]) if isinstance(a,dict) for s in a.get('slots',[]) if isinstance(s,dict) and s.get('publicationDate')==tomorrow]
    future_reserved=sum(s.get('status') in ('reserved','scheduled') or s.get('publicationStatus')=='reserved' for s in future_slots)
    nv_note='오늘 발행 '+str(done_nv if done_nv is not None else '—')+' · 오늘 예약 '+str(reserved)+'건 · 내일 예약 '+(str(future_reserved)+'건' if future_slots else '—')
    if runner.get('running') is True:
        nv_note += ' · '+clean(runner.get('activeAccount') or '계정',25)+' 작성 중'
    else:
        future = sorted(str(r.get('scheduledSlot','')) for r in slots if r.get('scheduledSlot','')>=clock and r not in public)
        nv_note += ' · '+('다음 '+future[0] if future else '다음 슬롯 대기')
    daily = kin.get('daily') or {}
    done_kin = daily.get('publishedVerified') if daily.get('date')==day else None
    schedule = kin.get('automation') or kin.get('schedule') or {}
    kin_note = clean(schedule.get('activeAccount'),25)+' 답변 작성 중' if schedule.get('activeRunId') else '다음 배포: '+format_time(schedule.get('nextEligibleAt'),now)
    kin_note += ' · '+str(schedule.get('intervalMinutes') or 20)+'분 텀'
    rows = [dict(name='CF 블로그',done=done_cf,target=16,note=cf_note),
            dict(name='네이버 블로그',done=done_nv,target=7,note=nv_note),
            dict(name='네이버 지식iN',done=done_kin,target=20,note=kin_note)]
    for row in rows:
        if type(row['done']) is not int or row['done']<0:row['done']=None
        if row['done'] is None:row['note']='당일 데이터 연결 대기'
    return rows


def format_time(value, now):
    stamp=epoch(value)
    if not stamp:return '대기'
    at=dt.datetime.fromtimestamp(stamp,KST)
    return at.strftime('%H:%M' if at.date()==now.date() else '%m-%d %H:%M')


def crew_rows(events, requests, brains, now):
    """Terminal lifecycle events supersede older starts, even on the same task."""
    output=[]
    for role, name in ROLES.items():
        owned=[e for e in events if (e.get('ownerAgent') or e.get('who'))==role]
        latest=max(owned,key=lambda e:e.get('ts',0),default={})
        at=epoch(latest.get('ts',0)/1000)
        phase=latest.get('phase')
        fresh=0<=now.timestamp()-at<=180
        state='IDLE'; action='다음 업무 대기'; model=''
        if fresh and phase in ('started','requested','progress'):
            model_call=str(latest.get('requestedTo','')).startswith('model:') or latest.get('requestedTo')=='configured-model-runner'
            state='RUNNING' if phase=='started' or model_call else 'CYCLING'
            action=STAGES.get(latest.get('stage'),clean(latest.get('stage')) or '배정 업무 처리')
            model=clean(latest.get('modelBadge') or latest.get('model') or (brains.get(role) or {}).get('badge') or (brains.get(role) or {}).get('model'),50) if state=='RUNNING' else ''
        elif fresh and phase=='failed':
            state='ERROR';action=STAGES.get(latest.get('stage'),clean(latest.get('stage')) or '원작업 복구 대기')
        elif latest and phase=='completed':
            action=STAGES.get(latest.get('stage'),clean(latest.get('stage')) or '업무 처리')+' 완료'
        if str(latest.get('stage','')).startswith('editorial-') and latest.get('outputKind'):
            action=STAGES.get(latest.get('stage'),'지연 복구')+' · '+clean(latest['outputKind'],90)
        for request in requests:
            live=request.get('latestAction') or {}
            if (request.get('status') in ('acknowledged','awaiting_completion') and live.get('agent')==role
                    and live.get('state')=='calling' and epoch(live.get('observedAt'))>at
                    and 0<=now.timestamp()-epoch(live.get('observedAt'))<=180):
                state='RUNNING';action='업무 판단 · 모델 응답 생성'
                routes=[r.get('staffRoute') or {} for r in request.get('results',[]) if r.get('agent')==role]
                model=next((clean(r.get('configuredBadge') or r.get('configuredModel'),70) for r in routes if r.get('configuredModel')),
                           clean((brains.get(role) or {}).get('badge') or (brains.get(role) or {}).get('model'),70))
                break
        completed=max((e.get('ts',0)/1000 for e in owned if e.get('phase')=='completed'),default=0)
        output.append(dict(lastActivity=dt.datetime.fromtimestamp(at,KST).isoformat() if at else None,lastCompleted=dt.datetime.fromtimestamp(completed,KST).strftime('%m-%d %H:%M:%S') if completed else '—',role=role,name=name,state=state,action=action,model=model,
                           configuredModel=clean((brains.get(role) or {}).get('badge') or (brains.get(role) or {}).get('model'),70)))
    return output


def activity_log(events, cf, kin, now):
    """Two business/tool completions and one most recent current-day alert."""
    day=now.date().isoformat(); completed=[];alerts=[]
    for event in events:
        at=epoch(event.get('ts',0)/1000)
        if not at or dt.datetime.fromtimestamp(at,KST).date().isoformat()!=day:continue
        stage=event.get('stage') or ''
        who=ROLES.get(event.get('ownerAgent') or event.get('who'),'업무')
        summary=who+' · '+STAGES.get(stage,clean(stage,65))
        if stage.startswith('editorial-') and event.get('outputKind'):
            summary=who+' · '+clean(event['outputKind'],105)
        if event.get('phase')=='completed' and stage not in ('staff-response','staff-result-response','model-call'):
            completed.append((at,summary+' 완료'))
        if event.get('phase')=='failed':alerts.append((at,summary+' 실패 · 복구 확인 필요'))
    if cf.get('date')==day:
        for item in cf.get('items',[]):
            if not isinstance(item,dict):continue
            label='CF Order '+str(item.get('order'))+' · '+clean(item.get('domain'),35)
            if item.get('status')=='published' and valid_url(item.get('publicUrl')):
                at=item.get('completedAt') or ''
                if re.fullmatch(r'\d{2}:\d{2}:\d{2}',str(at)):at=day+'T'+at+'+09:00'
                completed.append((epoch(at),label+' 발행 완료'))
            if item.get('status')=='failed':alerts.append((epoch(item.get('lastErrorAt')),label+' · '+error_reason(item.get('lastError'))))
    if (kin.get('daily') or {}).get('date')==day and kin.get('blockedReason'):
        reasons=kin.get('accountBlockedReasons') or {}
        summary=', '.join(clean(account,25) for account in reasons)+' 답변 실행 오류' if reasons else error_reason(kin['blockedReason'])
        alerts.append((epoch(kin.get('checkedAt')),'지식iN · '+summary))
    completed=sorted(set(completed),reverse=True)[:2]
    rows=[dict(at=at,text=text,alert=False) for at,text in completed]
    while len(rows)<2:rows.append(dict(at=0,text='완료 이벤트 대기',alert=False))
    warning=max(alerts,default=(0,'현재 경고 없음'))
    rows.append(dict(at=warning[0],text=warning[1],alert=bool(alerts)))
    return rows


def token_summary(usage, now):
    """Only a dated, explicitly reported total/budget may drive this gauge."""
    if usage.get('date')!=now.date().isoformat():return '집계 연결 대기',None
    used=usage.get('totalTokens');budget=usage.get('dailyTokenBudget')
    if type(used) is not int or used<0:return '집계 연결 대기',None
    if type(budget) is not int or budget<=0:return f'{used:,} / 한도 미설정',None
    return f'{used:,}/{budget:,} ({used/budget:.0%}) · 잔여 {max(0,budget-used):,}',min(1,used/budget)


class Collector:
    def __init__(self, root=ROOT, host=None):
        self.root=Path(root);self.cache=JsonCache();self.lock=threading.Lock()
        self.stop=threading.Event();self.snapshot={};self.thread=None
        self.hosts=list(dict.fromkeys(['127.0.0.1',host] if host else ['127.0.0.1']))
        self.ports={};self.port_checked=0;self.requests=[];self.queue_checked=0;self.db_states={};self.alert_checked=0;self.kin_alert_rows=[];self.editor_stalls={}
        from server.cockpit_telemetry import RemoteTelemetry
        self.remote=RemoteTelemetry(self.root,self.hosts)

    def read(self, relative):return self.cache.read(self.root/relative)

    def kin_alerts(self,day):
        path=self.root/'dashboard/data/kin.sqlite3'
        if not path.is_file():return []
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05)) as db:
                db.row_factory=sqlite3.Row
                rows=[]
                for row in db.execute("SELECT question_id,account,state,updated_at,answer_url,document,result FROM questions WHERE date(updated_at,'+9 hours')=? ORDER BY updated_at DESC LIMIT 64",(day,)):
                    doc=json.loads(row['document']);result=json.loads(row['result'] or '{}')
                    rows.append({k:row[k] for k in ('question_id','account','state','updated_at','answer_url')})
                    rows[-1].update(title=doc.get('question',{}).get('title',''),reason=result.get('reason',''))
                return rows
        except (OSError,sqlite3.Error,ValueError,TypeError):return self.kin_alert_rows

    def operation_states(self, filename, table, day, timestamp=False):
        """Cache daily operation counts by DB/WAL revision; a busy writer never blocks the screen."""
        path=self.root/'dashboard/data'/filename
        previous=self.db_states.get(filename,{})
        cached=previous.get('states') if (previous.get('signature') or (None,))[0]==day else None
        try:
            signature=(day,*(p.stat().st_mtime_ns if p.exists() else None for p in (path,Path(str(path)+'-wal'))))
            if previous.get('signature')==signature:return previous['states']
            if not path.is_file():return cached
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05)) as db:
                db.execute('PRAGMA query_only=ON')
                condition="date(planned_at,'+9 hours')" if timestamp else 'day'
                states=dict(db.execute(f'SELECT state,COUNT(*) FROM {table} WHERE {condition}=? GROUP BY state',(day,)))
            self.db_states[filename]=dict(signature=signature,states=states)
            return states
        except (OSError,sqlite3.Error):return cached

    def read_agenda(self):
        control=self.read('dashboard/data/active-agenda.json')
        identity=control.get('activeId')
        agenda=self.read('dashboard/data/publication-conferences/operations/'+identity+'.json') if isinstance(identity,str) and re.fullmatch(r'[a-f0-9]{64}',identity) else {}
        active=None
        if control.get('enabled') is True and identity and agenda.get('id')==identity and agenda.get('status') not in ('closed','suspended','linked'):
            from common.work_agenda import running
            args=(agenda.get('workTarget') or agenda.get('source') or {}).get('arguments',{})
            active={k:agenda.get(k) for k in ('id','project','title','status','activatedAt','updatedAt')}
            if agenda.get('kind')=='goal':active['title']='대표 지시 안건 · '+str(agenda.get('project') or '전사')
            active.update(target={k:args.get(k) for k in ('account','date','slot','partId')},processObserved=bool(running(agenda)))
            active['automaticRecovery']={k:agenda.get('recoveryWatch',{}).get(k) for k in ('state','nextCheckAt','checks')}
            identity=agenda.get('controllerGoalId') or agenda.get('recoveryGoalId')
            goal=self.read('dashboard/data/chats/reasoning-goals/'+identity+'.json') if isinstance(identity,str) and re.fullmatch(r'[a-f0-9]{64}',identity) else {}
            progress=goal.get('progress',{});last=(goal.get('observations') or [{}])[-1]
            conf_id=agenda.get('source',{}).get('conferenceId')
            conference=self.read('dashboard/data/publication-conferences/'+str(conf_id)+'.json') if agenda.get('kind')=='conference' and conf_id else {}
            if conf_id:
                active['conferenceId']=conf_id
                active['conferenceStatus']=conference.get('status')
                active['conferenceEligibility']=conference.get('eligibility')
            from common.work_agenda import operational_state, performance
            active['operationalState']=operational_state(agenda,goal,conference)
            active['performance']=performance(agenda,self.read('dashboard/data/llm_usage_ledger.json'))
            active['activity']={'owner':goal.get('actor') or agenda.get('ownerAgent'),
                'action':clean(progress.get('summary') or agenda.get('lastAction'),500),
                'phase':clean(progress.get('phase'),100),'lastResult':clean(last.get('tool'),100),
                'lastResultAt':last.get('observedAt'),'lastActivityAt':goal.get('updatedAt') or agenda.get('updatedAt'),
                'nextCheckAt':goal.get('nextCheckAt') or agenda.get('recoveryWatch',{}).get('nextCheckAt'),
                'handoff':{k:goal.get('handoff',{}).get(k) for k in ('owner','expectedResult','deadlineAt','status','nextAction')},
                'intervention':clean(agenda.get('blocker'),500) if agenda.get('status')=='blocked' else None,
                'decisions':goal.get('decisions'),'maxSteps':goal.get('maxSteps'),
                'wallTimeSeconds':max(0,time.time()-agenda['activatedAt']) if agenda.get('activatedAt') else None,
                'toolRoundTrips':sum(e.get('actor') in ROLES and e.get('tool') not in ('colleague_request','colleague_answer','colleague_partial') for e in goal.get('observations',[])),
                'manualNudges':agenda.get('manualNudges',goal.get('manualNudges')),
                'verifiedCompletions':1 if agenda.get('verification',{}).get('verified') is True else 0,
                'modelLatencyMs':sum(d.get('modelLatencyMs',0) for d in goal.get('discussion',[])),
                'toolFailures':sum(e.get('result',{}).get('ok') is False for e in goal.get('observations',[]) if isinstance(e.get('result'),dict)),
                'lastRoute':{k:goal.get('lastRoute',{}).get(k) for k in ('provider','model','reasoningEffort')},
                'reportAcknowledgments':{k:agenda.get('events',{}).get(k,{}).get('receivedAt') for k in ('staff_result','closing')}}
            for key in ('wallTimeSeconds','toolRoundTrips','toolFailures','modelLatencyMs','manualNudges','verifiedCompletions'):
                active['activity'][key]=active['performance'].get(key)
            active['activity']['metricsCoverage']=active['performance']['coverage']
            if active['operationalState']=='needs_ceo_action' and conference.get('executionGeneration'):
                active['activity']['intervention']='검증 수리 후 추가 실행권까지 소비했습니다. 새 실행 범위에 대한 대표 지시가 필요합니다.'
            if agenda.get('project')=='naver_blog' and all(isinstance(args.get(k),str) for k in ('account','date','slot')):
                account,day,slot=args['account'],args['date'],args['slot']
                if re.fullmatch(r'[A-Za-z0-9_]+',account) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) and re.fullmatch(r'\d{2}:\d{2}',slot):
                    folder='naver_blog_posting/output/scheduled/'+day+'/'+account+'-'+slot.replace(':','')
                    screen=self.read(folder+'/ego-screen-editor/screen-execution.json')
                    turns=screen.get('turns',[]);latest=turns[-1] if turns else {}
                    measured=[t['modelLatencyMs'] for t in turns if type(t.get('modelLatencyMs')) in (int,float)]
                    active['activity']['screenMetrics']={'turns':len(turns),'writtenReferences':len(screen.get('written',[])),
                        'modelLatencyObservedMs':sum(measured),'modelCallsMeasured':len(measured),'modelCallsUnmeasured':len(turns)-len(measured)}
                    if screen.get('status')=='running' and active['processObserved']:
                        active['activity'].update(owner='publi',phase='보존 편집기 입력·서식 확인',
                            action='승인 원고 입력 '+str(len(screen.get('written',[])))+'개 참조 확인 · 화면 '+str(len(turns))+'회 관측',
                            lastResult='화면 행동 '+str(latest.get('completedActions',0))+'개 완료',
                            lastActivityAt=self.root.joinpath(folder+'/ego-screen-editor/screen-execution.json').stat().st_mtime)
                    receipt=self.read(folder+'/reservation-evidence.json')
                    active['submissionStarted']=True if receipt.get('preCommitIntent') is True or receipt.get('submissionStatus') in ('submitting','submission_unknown','verified_reserved') else None


        return {'enabled':control.get('enabled') is True,'active':active}

    def collect(self):
        now=dt.datetime.now(KST); tick=time.monotonic()
        cf=self.read('dashboard/data/cf/daily_schedule.json')
        nv=self.read('dashboard/data/naver/automation-status.json');kin=self.read('dashboard/data/public/kin.json')
        room=self.cache.read(self.root/'dashboard/data/chats/room-main.json',projection=lambda d:
            {'messages':[e for e in (d.get('messages',[]) + d.get('workEvents',[])) if isinstance(e,dict) and e.get('eventType')=='crew_work_event'][-600:]})
        events=[e for e in room.get('messages',[])[-600:] if isinstance(e,dict) and e.get('eventType')=='crew_work_event'
                and isinstance(e.get('ts'),(int,float))]
        local=self.read('dashboard/data/editorial-live-events.json').get('messages',[])
        merged={}
        for e in events+[r for r in local if isinstance(r,dict) and isinstance(r.get('ts'),(int,float))]:
            key=tuple(e.get(k,'') for k in ('taskId','phase','stage','who','outputKind'))
            if key not in merged or merged[key]['ts']<e['ts']:merged[key]=e
        dismissed={identity for identity,row in self.read('dashboard/data/ego-alerts/tickets.json').get('tickets',{}).items() if row.get('status')=='dismissed'}
        events=[e for e in merged.values() if not (e.get('stage')=='ego-alert' and str(e.get('taskId','')).removeprefix('ego-alert:') in dismissed)]
        if tick-self.queue_checked>=15:
            directory=self.root/'dashboard/data/chats/staff-requests'
            try:
                paths=sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:128]
                self.requests=[self.cache.read(p) for p in paths if not p.is_symlink()]
                keep={p for p in self.cache.values if p.parent!=directory}.union(paths)
                for collection in (self.cache.values,self.cache.signatures):
                    for key in list(collection):
                        if key not in keep:collection.pop(key,None)
                self.cache.errors.intersection_update(keep)
            except OSError:pass
            self.queue_checked=tick
        if tick-self.port_checked>=5:
            for port in PORTS:
                self.ports[port]=False
                for host in self.hosts:
                    try:
                        with socket.create_connection((host,port),timeout=.08):self.ports[port]=True
                        break
                    except OSError:continue
            self.port_checked=tick
        from common.llm_settings import ensure_agent_brains
        brains=ensure_agent_brains(self.read('dashboard/data/llm-settings.json'))
        data=dict(schedulePolicy=self.read('dashboard/data/daily_schedule.json'),scheduleRuntime=self.read('dashboard/data/parameter-runtime.json'),agentBrains=brains,channels=channels(cf,nv,kin,now),crew=crew_rows(events,self.requests,brains,now),
                  logs=activity_log(events,cf,kin,now),ports=dict(self.ports),
                  tokens=token_summary(self.read('dashboard/data/llm-usage.json'),now),
                  cached=any(self.root/p in self.cache.errors for p in (
                      'dashboard/data/cf/daily_schedule.json','dashboard/data/naver/automation-status.json','dashboard/data/public/kin.json')),
                  collectedAt=now.timestamp())
        for key,path in {'cf':'dashboard/data/cf/daily_schedule.json','naver':'dashboard/data/naver/automation-status.json',
            'kin':'dashboard/data/public/kin.json','usage':'dashboard/data/llm_usage_ledger.json','revenue':'dashboard/data/revenue.json','revenueRefresh':'dashboard/data/revenue-refresh.json',
            'metrics':'dashboard/data/metrics.json','threads':'dashboard/data/public/threads.json',
            'synapses':'dashboard/data/memory_graph.json','maintenance':'dashboard/data/content-maintenance.json','graph':'dashboard/data/editorial-memory-graph.json',
            'naverJournal':'dashboard/data/naver/automation-journal.json','naverWorkflow':'dashboard/data/naver/active-workflow.json',
            'workflow':'dashboard/data/naver/pipeline_status.js'}.items():data[key]=self.read(path)
        data['agendaControl']=self.read_agenda()
        data.update(events=events,remote=self.remote.get(),timeline=business_timeline(events,cf,kin,data['revenue'],now))
        data['kinOperations']=self.operation_states('kin.sqlite3','automation_slots',now.date().isoformat(),True)
        data['threadsOperations']=self.operation_states('threads.sqlite3','authoring_slots',now.date().isoformat())
        from server.cockpit_telemetry import env_values
        try:data['openaiKey']=bool(env_values(self.root).get('OPENAI_API_KEY') or self.read('dashboard/data/llm-settings.json').get('providers',{}).get('openai',{}).get('encrypted_key'))
        except (OSError,ImportError):data['openaiKey']=False
        owners={'keyword-selector':'radar','researcher':'radar','writer':'publi','image-maker':'publi','assembler':'publi','reviewer':'doctor'}
        for item in cf.get('items',[]):
            if item.get('status') not in ('processing','publishing'):continue
            model=item.get('currentModel') or {};owner=owners.get(model.get('agent'))
            for member in data['crew']:
                if member['role']==owner and model.get('status')=='calling':
                    member.update(state='RUNNING',model=model.get('actualModel') or model.get('requestedModel') or member.get('model'),
                                  action=clean(item.get('domain'))+' · '+clean(item.get('stageName')))
        if tick-self.alert_checked>=5:
            self.alert_checked=tick
            self.kin_alert_rows=self.kin_alerts(now.date().isoformat())
            active_editors={}
            for browser in data.get('remote',{}).get('fleet',[]):
                for tab in browser.get('tabs',[]):
                    if not tab.get('editorHasContent') or not tab.get('registerPresent'):continue
                    key=(browser.get('account'),tab.get('questionId'))
                    prior=self.editor_stalls.get(key)
                    first=prior[1] if prior and prior[0]==tab.get('editorCharCount') else now.isoformat()
                    active_editors[key]=(tab.get('editorCharCount'),first)
            self.editor_stalls=active_editors
            for row in self.kin_alert_rows:
                editor=active_editors.get((row['account'],row['question_id']))
                if row['state']=='drafted' and editor:
                    row.update(state='prepared',updated_at=editor[1])
            data['kinOperationsRows']=self.kin_alert_rows
            try:
                from common.ego_alerts import observe
                observe(data,self.root,now)
            except (OSError,ValueError,RuntimeError):
                pass  # A busy incident bus never interrupts the shared telemetry snapshot.
        with self.lock:self.snapshot=data

    def run(self):
        while not self.stop.is_set():
            try:
                self.collect()
                from common.dashboard_jobs import write
                write(self.root/'dashboard/data/live_snapshot.json', shared_snapshot(self.get()))
            except (OSError,ValueError,TypeError,KeyError,AttributeError):
                with self.lock:self.snapshot={**self.snapshot,'cached':True}
            self.stop.wait(1)

    def start(self):
        self.remote.start()
        self.thread=threading.Thread(target=self.run,name='cockpit-read-only',daemon=True);self.thread.start()

    def get(self):
        with self.lock:return self.snapshot


def shared_snapshot(data):
    """One public, immutable projection drives both screens; never exports raw chats or credentials."""
    import hashlib
    from server import cockpit_panels as panels
    now=dt.datetime.fromtimestamp(data.get('collectedAt',time.time()),KST)
    graph=data.get('synapses') or {}
    vault=dict(nodes=len(graph.get('nodes',{})),edges=len(graph.get('edges',[])),
        episodes=sum(n.get('resolvedCount',0) for n in graph.get('nodes',{}).values()))
    channel_rows=[]
    for index,row in enumerate(data.get('channels',[])):
        key=('cf','naver','kin')[index]
        source=data.get(key,{})
        items=source.get('items',[]) if key=='cf' and source.get('date')==now.date().isoformat() else []
        states={}
        for item in items:states[item.get('status','waiting')]=states.get(item.get('status','waiting'),0)+1
        if key=='naver':
            slots=[slot for account in source.get('accounts',[]) for slot in account.get('slots',[])]
            for slot in slots:states[slot.get('status','waiting')]=states.get(slot.get('status','waiting'),0)+1
            reserved=sum(slot.get('publicationStatus')=='reserved' and str(slot.get('reserveTime','')).startswith(now.date().isoformat()) for slot in slots)
            tomorrow=(now.date()+dt.timedelta(days=1)).isoformat()
            future_reserved=sum(slot.get('publicationStatus')=='reserved' and str(slot.get('reserveTime','')).startswith(tomorrow) for slot in slots)
        else:reserved=future_reserved=0
        channel_rows.append(dict(row,id=key,states=states,reserved=reserved,tomorrowReserved=future_reserved))
    today=data.get('threads',{}).get('today',{})
    states={}
    if today.get('date')==now.date().isoformat():
        for item in today.get('counts',[]):
            if item.get('kind')=='main':states[item['state']]=states.get(item['state'],0)+int(item.get('n',0))
    channel_rows.append(dict(id='threads',name='Threads',done=states.get('published_verified',0) if today.get('date')==now.date().isoformat() else None,target=4,states=states,note='당일 본문 발행'))
    for row in channel_rows:
        states=row['states'];key=row['id'];current=row['done'] is not None
        prepared=sum(states.get(k,0) for k in ('prepared','ready','approved','validated'))
        running=sum(states.get(k,0) for k in ('processing','publishing','running'))
        failed=sum(states.get(k,0) for k in ('failed','error','rejected'))
        completed=(row['done'] or 0)+(row.get('reserved') or 0)
        row['counts']=dict(completed=completed if current else None,prepared=prepared if current else None,
            running=running if current else None,failed=failed if current else None,
            waiting=max(0,row['target']-completed-prepared-running-failed) if current else None)
        operations=data.get('kinOperations' if key=='kin' else 'threadsOperations') if key in ('kin','threads') else None
        if key in ('kin','threads') and operations is None and current:
            row['counts'].update(prepared=None,running=None,failed=None,waiting=None)
        row['operationStates']=operations
        row['blockedAttempts']=sum(operations.get(k,0) for k in ('blocked','review_required','manual_review')) if isinstance(operations,dict) else None
    crew=[{**{k:r.get(k) for k in ('role','name','state','action','lastCompleted','lastActivity')},'model':r.get('model') or r.get('configuredModel')} for r in data.get('crew',[])]
    fleet=data.get('remote',{}).get('fleet',[])
    fleet_lines=[]
    for row in fleet:
        tabs=sorted(row.get('tabs',[]),key=lambda r:not r.get('active'))
        active=tabs[0] if tabs else {}
        fleet_lines.append(f"{row['port']} {row['account']} ({row.get('profile','')}) · {'● ON' if row['online'] else '● OFF'} · 탭 {len(tabs)}개 · {row['purpose']}")
        fleet_lines.append('  '+active.get('title','열린 탭 없음')+' · '+active.get('url',''))
    crew_lines=[f"@{r['role']} · {r.get('model') or '지정 모델 대기'} · {r['state']} · {r.get('action') or '다음 작업 대기'} · 완료 {r.get('lastCompleted') or '—'}" for r in crew]
    crew_lines.append(f"Vault {vault['nodes']} 노드 · {vault['edges']} 연결 · 누적 해결 {vault['episodes']}회")
    timeline=data.get('timeline',[])[:6]
    rows=[panels.revenue_summary(data.get('revenue',{}),data.get('metrics',{}),now),
          panels.brain_lines(data,now),fleet_lines,panels.pipeline_lines({**data,'channels':channel_rows[:3],'threadCounts':channel_rows[3]['counts']},now),crew_lines,
          [dt.datetime.fromtimestamp(r['at'],KST).strftime('%H:%M:%S')+' '+r['text'] for r in timeline]]
    workflow=data.get('naverWorkflow') or {}
    live_workflow={k:workflow.get(k) for k in ('schema','workerId','account','accId','publicationDate','scheduledSlot','reserveTime','startedAt','attemptStartedAt','observedAt','status','pid','mode')}
    if isinstance(workflow.get('progress'),dict):
        live_workflow['progress']={k:workflow['progress'].get(k) for k in ('workerId','currentStage','stageName','status','progressPct','workDate','publicationDate','updatedAt','topic')}
    if not workflow:live_workflow={}
    live_attempts=[{k:attempt.get(k) for k in ('account','accId','workerId','workDate','publicationDate','scheduledSlot','reserveTime','startedAt','updatedAt','runMode','submissionStarted','phase','topic','title','verificationSource','verifiedAt','blogId','publicUrl','publicPublicationVerified')}
        for attempt in data.get('naverJournal',{}).get('attempts',[])[-128:]]
    cf_items=[{k:item.get(k) for k in ('domain','status','publicUrl','title','completedAt','stageName','order')} for item in data.get('cf',{}).get('items',[]) if data.get('cf',{}).get('date')==now.date().isoformat()]
    revenue_sources=[{k:source.get(k) for k in ('id','label','category','currency','daily','status','checkedAt','aggregationEligible','aggregationKey','domains','account','collectionAccount','mediaIds','accountBreakdownVerified','pendingDates','scope') if source.get(k) is not None}
        for source in data.get('revenue',{}).get('months',{}).get(now.strftime('%Y-%m'),{}).get('sources',[])]
    from dashboard.collectors.revenue import summarize
    revenue_document={'months':{now.strftime('%Y-%m'):{'sources':revenue_sources,'checkedAt':data.get('revenue',{}).get('months',{}).get(now.strftime('%Y-%m'),{}).get('checkedAt')}}}
    revenue_projection={**summarize(revenue_document,now),'months':revenue_document['months']}
    result=dict(agendaControl=data.get('agendaControl',{}),schedulePolicy=data.get('schedulePolicy',{}),scheduleRuntime=data.get('scheduleRuntime',{}),schema='barolab-mission-control-v2',date=now.date().isoformat(),generatedAt=now.isoformat(),
        refreshSeconds=1,cfItems=cf_items,revenue=revenue_projection,
        naverLive={'workflow':live_workflow or None,'journal':{'attempts':live_attempts}},channels=channel_rows,crew=crew,vault=vault,timeline=timeline,
        naverAccounts=[dict(account=a.get('account'),accId=a.get('accId'),expected=a.get('expected'),
            slots=[{k:slot.get(k) for k in ('status','publicationStatus','publicationDate','reserveTime','publicPublicationVerified','publicUrl','title','verifiedAt')} for slot in a.get('slots',[])])
            for a in data.get('naver',{}).get('accounts',[])],
        fleet=fleet,panels=rows,brainDisplay=panels.brain_display(data,now),ports=data.get('ports',{}),
        brains=dict(usage=data.get('usage',{}),quotas={k:v for k,v in data.get('remote',{}).items() if k!='fleet'}))
    result['revision']=hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return result


class SnapshotReader:
    """Monitor only reads the hub snapshot: no independent probes, aggregation or subprocesses."""
    def __init__(self,root=ROOT):
        self.path=Path(root)/'dashboard/data/live_snapshot.json';self.cache=JsonCache()
        self.stop=threading.Event();self.remote=self;self.thread=None
    def start(self):pass
    def get(self):
        data=self.cache.read(self.path)
        return data if data.get('schema')=='barolab-mission-control-v2' else {}


def business_timeline(events,cf,kin,revenue,now):
    day=now.date().isoformat();rows=[]
    for event in events:
        at=epoch(event.get('ts',0)/1000);stage=event.get('stage','')
        if not at or dt.datetime.fromtimestamp(at,KST).date().isoformat()!=day:continue
        if stage=='ego-alert':
            rows.append(dict(at=at,text='[EGO ALERT] '+clean(event.get('outputKind'),150),alert=True))
            continue
        if str(event.get('outputKind','')).startswith('dict fields:') or 'model response only' in str(event.get('outputKind','')):continue
        if event.get('phase')=='completed' and stage in ('editorial-query','editorial-scope','editorial-pivot','editorial-renewal','publication-verified','revenue-collected','recovery-verified','browser-lock-recovery','audit-path-recovery'):
            rows.append(dict(at=at,text=ROLES.get(event.get('ownerAgent') or event.get('who'),'업무')+' · '+clean(event.get('outputKind') or STAGES.get(stage,stage),150),alert=False))
        elif event.get('phase')=='failed' and stage.startswith('editorial-'):
            rows.append(dict(at=at,text='▲ ALERT · '+clean(event.get('outputKind') or stage,150),alert=True))
    for r in activity_log([],cf,{},now):
        if r['at'] and '발행 완료' in r['text']:rows.append(r)
    for r in kin.get('recent',[]):
        if r.get('state')=='published_verified' and r.get('send_day')==day:
            rows.append(dict(at=epoch(r.get('updated_at')),text='지식iN '+clean(r.get('account'))+' · 발행 성공 · '+clean(r.get('title'),80),alert=False))
    for src in revenue.get('months',{}).get(day[:7],{}).get('sources',[]):
        at=epoch(src.get('checkedAt'))
        if src.get('status')=='collected' and at and dt.datetime.fromtimestamp(at,KST).date().isoformat()==day:
            rows.append(dict(at=at,text=clean(src.get('label'))+' 수익 수집 완료',alert=False))
    return sorted({(r['at'],r['text']):r for r in rows}.values(),key=lambda r:r['at'],reverse=True)[:6]


def render(data, now=None, height=32):
    from server.cockpit_panels import render as vivid_render
    return vivid_render(data,now or dt.datetime.now(KST),height)


def main(argv=None):
    parser=argparse.ArgumentParser(description='EGO LITE read-only mission control')
    parser.add_argument('--once',action='store_true',help='Render one static frame')
    parser.add_argument('--seconds',type=float,help='Run a bounded terminal preview')
    parser.add_argument('--host',default=os.environ.get('BAROLAB_CDP_HOST'),help='Optional Windows CDP socket host')
    args=parser.parse_args(argv)
    terminal=sys.stdout.isatty()
    if terminal:
        # Agent shells may export a stale 24-row size; use the live PTY dimensions.
        os.environ.pop('LINES',None);os.environ.pop('COLUMNS',None)
    console=Console(force_terminal=terminal,color_system='truecolor' if terminal else None,no_color=False)
    collector=SnapshotReader()
    if args.once:
        console.print(render(collector.get(),height=console.height));return 0
    collector.start();deadline=time.monotonic()+args.seconds if args.seconds is not None else None
    try:
        with Live(render(collector.get(),height=console.height),console=console,refresh_per_second=1,screen=True,
                  auto_refresh=False,vertical_overflow='crop') as live:
            while deadline is None or time.monotonic()<deadline:
                live.update(render(collector.get(),height=console.height),refresh=True)
                time.sleep(1)
    except KeyboardInterrupt:pass
    finally:
        collector.stop.set();collector.remote.stop.set()
        if collector.thread:collector.thread.join(timeout=2)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
