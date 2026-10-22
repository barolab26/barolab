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

ROOT = Path(__file__).resolve().parents[2]
KST = dt.timezone(dt.timedelta(hours=9))
ROLES = {'jarvis':'자비스', 'patch':'패치', 'publi':'퍼블리',
         'trace':'트레이스', 'doctor':'닥터', 'radar':'레이더'}
PORTS = (9334, 9333, 9335, 9231, 9230, 8790, 3001)
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
            model=clean(latest.get('model') or (brains.get(role) or {}).get('model'),50) if state=='RUNNING' else ''
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
                model=next((clean(r.get('configuredModel'),50) for r in routes if r.get('configuredModel')),
                           clean((brains.get(role) or {}).get('model'),50))
                break
        completed=max((e.get('ts',0)/1000 for e in owned if e.get('phase')=='completed'),default=0)
        output.append(dict(lastCompleted=dt.datetime.fromtimestamp(completed,KST).strftime('%H:%M:%S') if completed else '—',role=role,name=name,state=state,action=action,model=model,
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
        self.ports={};self.port_checked=0;self.requests=[];self.queue_checked=0
        from server.cockpit_telemetry import RemoteTelemetry
        self.remote=RemoteTelemetry(self.root,self.hosts)

    def read(self, relative):return self.cache.read(self.root/relative)

    def collect(self):
        now=dt.datetime.now(KST); tick=time.monotonic()
        cf=self.read('cf_posting/data/daily_schedule.json')
        nv=self.read('dashboard/naver_automation.json');kin=self.read('dashboard/data/public/kin.json')
        room=self.cache.read(self.root/'server/data/chats/room-main.json',projection=lambda d:
            {'messages':[e for e in d.get('messages',[])[-600:] if isinstance(e,dict) and e.get('eventType')=='crew_work_event']})
        events=[e for e in room.get('messages',[])[-600:] if isinstance(e,dict) and e.get('eventType')=='crew_work_event'
                and isinstance(e.get('ts'),(int,float))]
        local=self.read('server/data/editorial-live-events.json').get('messages',[])
        merged={}
        for e in events+[r for r in local if isinstance(r,dict) and isinstance(r.get('ts'),(int,float))]:
            key=tuple(e.get(k,'') for k in ('taskId','phase','stage','who','outputKind'))
            if key not in merged or merged[key]['ts']<e['ts']:merged[key]=e
        events=list(merged.values())
        if tick-self.queue_checked>=15:
            directory=self.root/'server/data/chats/staff-requests'
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
        brains=self.read('server/data/llm-settings.json').get('agentBrains') or {}
        data=dict(channels=channels(cf,nv,kin,now),crew=crew_rows(events,self.requests,brains,now),
                  logs=activity_log(events,cf,kin,now),ports=dict(self.ports),
                  tokens=token_summary(self.read('server/data/llm-usage.json'),now),
                  cached=any(self.root/p in self.cache.errors for p in (
                      'cf_posting/data/daily_schedule.json','dashboard/naver_automation.json','dashboard/data/public/kin.json')),
                  collectedAt=now.timestamp())
        for key,path in {'cf':'cf_posting/data/daily_schedule.json','naver':'dashboard/naver_automation.json',
            'kin':'dashboard/data/public/kin.json','usage':'server/data/llm_usage_ledger.json','revenue':'server/data/revenue.json','revenueRefresh':'server/data/revenue-refresh.json',
            'metrics':'server/data/metrics.json','threads':'dashboard/data/public/threads.json',
            'synapses':'dashboard/data/memory_graph.json','maintenance':'server/data/content-maintenance.json','graph':'server/data/editorial-memory-graph.json',
            'workflow':'naver_blog_posting/data/pipeline_status.js'}.items():data[key]=self.read(path)
        # Prefer the documented dashboard contract when deployed there, else server collector ledger.
        public_revenue=self.read('dashboard/data/public/revenue.json')
        if public_revenue.get('months') and epoch(public_revenue.get('checkedAt'))>epoch(data['revenue'].get('checkedAt')):data['revenue']=public_revenue
        from server.cockpit_panels import dated_graph_nodes
        data['graph']={**data['graph'],'todayVerifiedNodes':dated_graph_nodes(data['graph'],now,self.root)}
        data.update(events=events,remote=self.remote.get(),timeline=business_timeline(events,cf,kin,data['revenue'],now))
        from server.cockpit_telemetry import env_values
        try:data['openaiKey']=bool(env_values(self.root).get('OPENAI_API_KEY') or self.read('server/data/llm-settings.json').get('providers',{}).get('openai',{}).get('encrypted_key'))
        except (OSError,ImportError):data['openaiKey']=False
        proxy_calls=[r for r in data['usage'].get('byModel',{}).values() if r.get('provider')=='freellm']
        proxy_call=max(proxy_calls,key=lambda r:r.get('lastAt',''),default={})
        data['proxy']=dict(online=self.ports.get(3001),model=proxy_call.get('model'),latency=proxy_call.get('averageLatencyMs','—'))
        owners={'keyword-selector':'radar','researcher':'radar','writer':'publi','image-maker':'publi','assembler':'publi','reviewer':'doctor'}
        for item in cf.get('items',[]):
            if item.get('status') not in ('processing','publishing'):continue
            model=item.get('currentModel') or {};owner=owners.get(model.get('agent'))
            for member in data['crew']:
                if member['role']==owner and model.get('status')=='calling':
                    member.update(state='RUNNING',model=model.get('actualModel') or model.get('requestedModel') or member.get('model'),
                                  action=clean(item.get('domain'))+' · '+clean(item.get('stageName')))
        with self.lock:self.snapshot=data

    def run(self):
        while not self.stop.is_set():
            try:self.collect()
            except (OSError,ValueError,TypeError,KeyError,AttributeError):
                with self.lock:self.snapshot={**self.snapshot,'cached':True}
            self.stop.wait(2)

    def start(self):
        self.remote.start()
        self.thread=threading.Thread(target=self.run,name='cockpit-read-only',daemon=True);self.thread.start()

    def get(self):
        with self.lock:return self.snapshot


def business_timeline(events,cf,kin,revenue,now):
    day=now.date().isoformat();rows=[]
    for event in events:
        at=epoch(event.get('ts',0)/1000);stage=event.get('stage','')
        if not at or dt.datetime.fromtimestamp(at,KST).date().isoformat()!=day:continue
        if str(event.get('outputKind','')).startswith('dict fields:') or 'model response only' in str(event.get('outputKind','')):continue
        if event.get('phase')=='completed' and stage in ('editorial-query','editorial-scope','editorial-pivot','editorial-renewal','publication-verified','revenue-collected','recovery-verified'):
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
        collector.stop.set();collector.remote.stop.set()
        if collector.thread:collector.thread.join(timeout=2)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
