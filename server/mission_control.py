"""Read-only mission cockpit. Collection runs off the terminal rendering thread."""
import argparse
import datetime as dt
import json
import math
import os
import re
import socket
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

ROOT = Path(__file__).resolve().parents[1]
KST = dt.timezone(dt.timedelta(hours=9))
ROLES = {'jarvis':'자비스', 'patch':'패치', 'publi':'퍼블리',
         'trace':'트레이스', 'doctor':'닥터', 'radar':'레이더'}
PORTS = (9334, 9333, 9231, 9230, 8790)
STAGES = {'original-work-diagnosis':'원작업 차단 원인 진단', 'repair-diagnosis-model':'수정할 코드 분석',
          'staff-response':'업무 결과 보고', 'staff-result-response':'직원 결과 정리',
          'staff-action-routing':'담당 업무 배정', 'keyword-selector':'키워드 선정',
          'writer':'원고 작성', 'researcher':'근거 자료 수집', 'reviewer':'원고 검수',
          'image-maker':'이미지 제작', 'lesson-extraction':'발행 결과 학습',
          'lesson-verification':'지식 검증', 'model-call':'모델 응답 생성'}
TOOLS = {'advance_project_recovery':'원작업 복구 단계 처리', 'run_project_cycle':'발행 파이프라인 실행',
         'read_agent_status':'운영 상태 점검', 'repair_cf_known_failure':'CF 오류 수정'}
STAGES.update({'project-recovery-classification':'원작업 복구 담당 배정',
    'project-incident-triage':'발행 차단 원인 분류','project-instruction-issued':'직원 업무 배정',
    'project-result-review':'실행 결과 검토','project-result-reviewed':'실행 결과 검토',
    'repair-diagnosis':'코드 수정안 작성','repair-diagnosis-review':'수정안 검수',
    'repair-diagnosis-review-model':'수정안 독립 검수','staff-terminal-response':'업무 결과 보고',
    'handoff-accepted':'다음 직원에 인계',**TOOLS})


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
            value = json.loads(raw.decode('utf-8-sig'))
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
    nv_note = '예약 '+str(reserved)+'건'
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
        if fresh and phase in ('started','requested'):
            model_call=str(latest.get('requestedTo','')).startswith('model:') or latest.get('requestedTo')=='configured-model-runner'
            state='RUNNING' if phase=='started' or model_call else 'CYCLING'
            action=STAGES.get(latest.get('stage'),clean(latest.get('stage')) or '배정 업무 처리')
            model=clean(latest.get('model') or (brains.get(role) or {}).get('model'),50) if state=='RUNNING' else ''
        elif fresh and phase=='failed':
            state='ERROR';action=STAGES.get(latest.get('stage'),clean(latest.get('stage')) or '원작업 복구 대기')
        elif latest and phase=='completed':
            action=STAGES.get(latest.get('stage'),clean(latest.get('stage')) or '업무 처리')+' 완료'
        for request in requests:
            live=request.get('latestAction') or {}
            if (request.get('status') in ('acknowledged','awaiting_completion') and live.get('agent')==role
                    and live.get('state')=='calling' and epoch(live.get('observedAt'))>at
                    and 0<=now.timestamp()-epoch(live.get('observedAt'))<=180):
                state='RUNNING';action='업무 판단 · 모델 응답 생성'
                routes=[r.get('staffRoute') or {} for r in request.get('results',[]) if r.get('agent')==role]
                model=next((clean(r.get('configuredModel'),50) for r in routes if r.get('configuredModel')),
                           clean((brains.get(role) or {}).get('model'),50))
                break
        output.append(dict(role=role,name=name,state=state,action=action,model=model,
                           configuredModel=clean((brains.get(role) or {}).get('model'),50)))
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
        if event.get('phase')=='completed' and stage not in ('staff-response','staff-result-response','model-call'):
            completed.append((at,summary+' 완료'))
        if event.get('phase')=='failed':alerts.append((at,summary+' 실패 · 복구 확인 필요'))
    if cf.get('date')==day:
        for item in cf.get('items',[]):
            if not isinstance(item,dict):continue
            label='CF Order '+str(item.get('order'))+' · '+clean(item.get('domain'),35)
            if item.get('status')=='published' and valid_url(item.get('publicUrl')):
                completed.append((epoch(item.get('completedAt')),label+' 발행 완료'))
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
        self.ports={};self.port_checked=0;self.requests=[];self.queue_checked=0

    def read(self, relative):return self.cache.read(self.root/relative)

    def collect(self):
        now=dt.datetime.now(KST); tick=time.monotonic()
        cf=self.read('cf_posting/data/daily_schedule.json')
        nv=self.read('dashboard/naver_automation.json');kin=self.read('dashboard/data/kin.json')
        room=self.cache.read(self.root/'server/data/chats/room-main.json',projection=lambda d:
            {'messages':[e for e in d.get('messages',[])[-600:] if isinstance(e,dict) and e.get('eventType')=='crew_work_event']})
        events=[e for e in room.get('messages',[])[-600:] if isinstance(e,dict) and e.get('eventType')=='crew_work_event'
                and isinstance(e.get('ts'),(int,float))]
        if tick-self.queue_checked>=15:
            directory=self.root/'server/data/chats/staff-requests'
            try:
                paths=sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:128]
                self.requests=[self.cache.read(p) for p in paths if not p.is_symlink()]
                keep={self.root/p for p in ('cf_posting/data/daily_schedule.json','dashboard/naver_automation.json',
                      'dashboard/data/kin.json','server/data/chats/room-main.json','server/data/llm-settings.json',
                      'server/data/llm-usage.json')}.union(paths)
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
        brains=self.read('server/data/llm-settings.json').get('agentBrains') or {}
        data=dict(channels=channels(cf,nv,kin,now),crew=crew_rows(events,self.requests,brains,now),
                  logs=activity_log(events,cf,kin,now),ports=dict(self.ports),
                  tokens=token_summary(self.read('server/data/llm-usage.json'),now),
                  cached=any(self.root/p in self.cache.errors for p in (
                      'cf_posting/data/daily_schedule.json','dashboard/naver_automation.json','dashboard/data/kin.json')),
                  collectedAt=now.timestamp())
        with self.lock:self.snapshot=data

    def run(self):
        while not self.stop.is_set():
            try:self.collect()
            except (OSError,ValueError,TypeError,KeyError,AttributeError):
                with self.lock:self.snapshot={**self.snapshot,'cached':True}
            self.stop.wait(2)

    def start(self):
        self.thread=threading.Thread(target=self.run,name='cockpit-read-only',daemon=True);self.thread.start()

    def get(self):
        with self.lock:return self.snapshot


def render(data, now=None, height=32):
    now=now or dt.datetime.now(KST)
    layout=Layout(name='cockpit')
    layout.split_column(Layout(name='hud',size=5),Layout(name='channels',size=5),
                        Layout(name='crew',size=8),Layout(name='logs',minimum_size=5))
    crew=data.get('crew',[])
    active={r['model'] for r in crew if r['state']=='RUNNING' and r.get('model')}
    brain=Text('활성: ',style='bold')
    brain.append(', '.join(sorted(active)) if active else ('모델 응답 대기' if any(r['state']=='RUNNING' for r in crew) else '대기'),style='cyan')
    waiting={r.get('configuredModel') for r in crew if r.get('configuredModel') and r['state']!='RUNNING'}-active
    if waiting:brain.append(' | 대기: '+', '.join(sorted(waiting)),style='dim')
    token,ratio=data.get('tokens',('집계 연결 대기',None))
    tokens=Text('오늘 수집 토큰(Codex): '+token)
    if ratio is not None:tokens.append(' '+'■'*round(10*ratio)+'░'*(10-round(10*ratio)),style='cyan')
    ports=Text('인프라  ')
    for port in PORTS:
        online=data.get('ports',{}).get(port)
        ports.append(('허브 ' if port==8790 else '')+str(port)+' ')
        ports.append('● '+('ON' if online else 'OFF' if online is False else '…')+'  ',style='green' if online else 'red' if online is False else 'dim')
    suffix=' · 데이터 캐시' if data.get('cached') else (' · 데이터 갱신 대기' if now.timestamp()-data.get('collectedAt',now.timestamp())>10 else '')
    layout['hud'].update(Panel(Group(brain,tokens,ports),title='[bold cyan]EGO LITE MISSION CONTROL[/]',
        subtitle=now.strftime('%Y-%m-%d %H:%M:%S KST')+suffix,border_style='cyan'))
    progress=Progress(TextColumn('{task.fields[name]}',markup=False),
        TextColumn('{task.fields[count]}',markup=False),TextColumn('{task.fields[bar]}',markup=False,style='cyan'),
        TextColumn('{task.fields[percent]}',markup=False),TextColumn('{task.fields[note]}',markup=False),expand=False)
    for row in data.get('channels',[]):
        done=row['done'];target=row['target']
        filled=round(18*min(done or 0,target)/target)
        progress.add_task('',total=target,completed=min(done or 0,target),name=row['name'],
            count=f'[{done if done is not None else "—":>2}/{target:>2}]',
            bar='■'*filled+'░'*(18-filled),
            percent=f'{done/target:.0%}' if done is not None else '—',note=clean(row['note'],65))
    total=sum(r['done'] or 0 for r in data.get('channels',[]))
    total_label=str(total) if data.get('channels') and all(r['done'] is not None for r in data['channels']) else '—'
    layout['channels'].update(Panel(progress,title='1. 채널별 당일 발행 · '+total_label+'/43건',border_style='bright_blue'))
    table=Table.grid(expand=True,padding=(0,1));table.add_column(width=24,no_wrap=True);table.add_column(ratio=1,no_wrap=True,overflow='ellipsis')
    colors={'IDLE':'green','RUNNING':'cyan','CYCLING':'yellow','ERROR':'red'}
    for row in crew:
        state=Text('@'+row['name']+'  ');state.append(row['state'],style=colors[row['state']])
        action=Text(row['action']);model=row.get('model') or row.get('configuredModel')
        if model:action.append(' · '+model,style='dim')
        table.add_row(state,action)
    layout['crew'].update(Panel(table,title='2. 6인 에이전트 실시간 동작',border_style='cyan'))
    logs=Table.grid(expand=True);logs.add_column(width=11);logs.add_column(no_wrap=True,overflow='ellipsis')
    for row in data.get('logs',[dict(at=0,text='이벤트 연결 중',alert=False)]):
        line=Text()
        if row['alert']:line.append('[ALERT] ',style='bold red')
        line.append(clean(row['text'],160),style='red' if row['alert'] else 'white')
        when=dt.datetime.fromtimestamp(row['at'],KST).strftime('%H:%M:%S') if row['at'] else '대기'
        logs.add_row('['+when+']',line)
    layout['logs'].update(Panel(logs,title='3. 최근 완료 2건 · 경고 1건',border_style='bright_blue'))
    if height<23:
        return Group(layout['hud'].renderable,layout['channels'].renderable,layout['crew'].renderable,layout['logs'].renderable)
    return layout


def main(argv=None):
    parser=argparse.ArgumentParser(description='EGO LITE read-only mission control')
    parser.add_argument('--once',action='store_true',help='Render one static frame')
    parser.add_argument('--seconds',type=float,help='Run a bounded terminal preview')
    parser.add_argument('--host',default=os.environ.get('BAROLAB_CDP_HOST'),help='Optional Windows CDP socket host')
    args=parser.parse_args(argv)
    terminal=sys.stdout.isatty()
    console=Console(force_terminal=terminal,color_system='truecolor' if terminal else None,no_color=False)
    collector=Collector(host=args.host)
    if args.once:
        collector.collect();console.print(render(collector.get(),height=console.height));return 0
    collector.start();deadline=time.monotonic()+args.seconds if args.seconds is not None else None
    try:
        with Live(render(collector.get(),height=console.height),console=console,refresh_per_second=1,screen=True,
                  auto_refresh=False,vertical_overflow='crop') as live:
            while deadline is None or time.monotonic()<deadline:
                live.update(render(collector.get(),height=console.height),refresh=True)
                time.sleep(1)
    except KeyboardInterrupt:pass
    finally:
        collector.stop.set()
        if collector.thread:collector.thread.join(timeout=2)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
