"""Six high contrast panels; all rendering is pure and size aware."""
import datetime as dt
from decimal import Decimal,InvalidOperation
from pathlib import Path

from rich import box
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

KST=dt.timezone(dt.timedelta(hours=9))
NAMES=('revenue','brains','fleet','pipeline','crew','timeline')
COLORS=('bright_yellow','bright_magenta','bright_cyan','bright_blue','bright_magenta','bright_yellow')
STEPS=('키워드선정','리서치·근거수집','구성·블록계획','원고집필','이미지·에디터입력','최종발행·색인')


def number(value):
    try:
        v=Decimal(str(value));return v if v.is_finite() else None
    except (InvalidOperation,ValueError):return None


def money(value,currency='$'):
    v=number(value);return currency+format(v,',.2f' if currency=='$' else ',.0f') if v is not None else '집계 대기'


def bar(done,target,width=12):
    filled=round(width*max(0,min(1,(done or 0)/target)))
    return '■'*filled+'░'*(width-filled)


def table(*columns):
    t=Table.grid(expand=True,padding=(0,1))
    for width in columns:t.add_column(width=width,ratio=1 if width is None else None,no_wrap=True,overflow='ellipsis')
    return t


def line(value='',style='bold white'):
    return Text(str(value),style=style,no_wrap=True,overflow='ellipsis')


def revenue_summary(revenue,metrics,now):
    day=now.date().isoformat();month=day[:7];yesterday=(now.date()-dt.timedelta(days=1)).isoformat()
    sources=revenue.get('months',{}).get(month,{}).get('sources',[])
    usd=[s for s in sources if s.get('category')=='adsense' and s.get('currency')=='USD']
    def amount(rows,date):
        values=[number(r.get('daily',{}).get(date)) for r in rows]
        return sum(v for v in values if v is not None) if any(v is not None for v in values) else None
    today=amount(usd,day);prior=amount(usd,yesterday)
    subtotal=sum((v for s in usd for k,a in s.get('daily',{}).items() if k.startswith(month) and (v:=number(a)) is not None),Decimal(0)) if usd else None
    through=max((k for s in usd for k in s.get('daily',{})),default='—')
    coverage=len({domain for s in usd if s.get('status')=='collected' for domain in s.get('domains',[])})
    rows=[f'애드센스 수집분 ({coverage}/16 CF)  오늘 {money(today)}  /  어제 {money(prior)}  /  월 수집합 {money(subtotal)}  (기준일 {through})',
          '일일 목표 $100.00  '+bar(float(today or 0),100,24)+'  '+(f'{today:.2f}%' if today is not None else '당일 집계 대기')]
    seen=set()
    for s in sources:
        if s.get('currency')!='KRW' or s.get('aggregationEligible') is False:continue
        key=s.get('aggregationKey') or s.get('id')
        if key in seen:continue
        seen.add(key);daily=s.get('daily',{});date=max(daily,default='—');at=_epoch(s.get('checkedAt'))
        age=f'{max(0,int((now.timestamp()-at)/60))}분 전' if at else '수집 대기'
        rows.append(f"{s.get('label',s.get('id'))}  오늘 {money(daily.get(day),'₩')} / 최근 {money(daily.get(date),'₩')} ({date}) · {age} · {s.get('status','대기')}")
    app_rows=[s for s in sources if s.get('category')=='admob']
    if app_rows:
        for currency in sorted({s.get('currency','USD') for s in app_rows}):
            values=[s for s in app_rows if s.get('currency','USD')==currency]
            rows.append('AdMob (4앱) 오늘 '+money(amount(values,day),'$' if currency=='USD' else currency+' ')+' · 실제 보고 기준')
    else:rows.append('AdMob (4앱) 당일 수익 원장 수집 대기')
    indexed=total=submitted=inspected=0
    for site in metrics.get('sites',{}).values():
        posts=site.get('posts',{});google=site.get('google',{})
        total+=len(posts) if isinstance(posts,list) else int(posts.get('count') or posts.get('total') or len(posts.get('urls',[])) or google.get('inventoryTotal') or 0)
        indexed+=int(google.get('indexed') or 0);inspected+=int(google.get('inspected') or 0)
        req=site.get('indexingRequest',{})
        # Count only successful IndexNow submissions, never requests or inspected URLs.
        for provider,result in req.items():
            if isinstance(result,dict) and result.get('method')=='IndexNow' and _date(result.get('completedAt') or req.get('requestedAt'))==day:
                submitted+=int(result.get('submittedCount') or 0)
    rows.append(f'색인 확인 {indexed:,}/{total:,}건 ({indexed/total:.1%}) · 검사 {inspected:,}건 · 오늘 IndexNow {submitted}건' if total else '색인 데이터 수집 대기')
    if len(rows)>3:rows.insert(2,rows.pop())
    return rows


def _epoch(value):
    try:
        if isinstance(value,(int,float)):return value
        parsed=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'));return parsed.replace(tzinfo=parsed.tzinfo or KST).timestamp()
    except (ValueError,TypeError):return 0


def _date(value):
    at=_epoch(value);return dt.datetime.fromtimestamp(at,KST).date().isoformat() if at else ''


def brain_display(data,now):
    remote=data.get('remote',{});ledger=data.get('usage',{})
    active=[r for r in ledger.get('active',{}).values() if ledger.get('date')==now.date().isoformat() and 0<=now.timestamp()-_epoch(r.get('startedAt'))<900]
    providers={r.get('provider') for r in active}
    buckets=remote.get('codexQuota',{}).get('buckets',{})
    windows=[w for b in buckets.values() for k in ('primary','secondary') if isinstance(w:=b.get(k),dict) and number(w.get('usedPercent')) is not None]
    window=max(windows,key=lambda w:number(w['usedPercent']),default={})
    remaining=max(0,100-number(window['usedPercent'])) if window else None
    reset=_epoch(window.get('resetsAt'));credit=next((number(b.get('credits',{}).get('balance')) for b in buckets.values() if number(b.get('credits',{}).get('balance')) is not None),None)
    def gauge(value):
        return ('—' if value is None else f'{value:g}%')+' ['+('░'*15 if value is None else '■'*round(max(0,min(100,value))*15/100)+'░'*(15-round(max(0,min(100,value))*15/100)))+']'
    rows=['[Codex 구독] 잔여 '+gauge(remaining)+' | 리셋: '+(dt.datetime.fromtimestamp(reset,KST).strftime('%m-%d %H:%M') if reset else '—')+' | '+(f'{credit:,.2f} C' if credit is not None else '— C')]
    agy=remote.get('agy',{})
    agy_fresh=agy.get('status')=='collected' and 0<=now.timestamp()-_epoch(agy.get('checkedAt'))<=180
    agy_remaining=number(agy.get('remainingPercent')) if agy_fresh else None
    agy_parts=[];agy_resets=[];agy_values=[]
    if agy_fresh:
        for group in agy.get('groups',[]):
            values={b['window']:number(b.get('remainingPercent')) for b in group.get('buckets',[])}
            if not values or any(v is None or not 0<=v<=100 for v in values.values()):continue
            label={'Gemini Models':'Gemini','Claude and GPT models':'Claude/GPT'}.get(group.get('name'),group.get('name','모델'))
            agy_parts.append(label+' '+ '/'.join(f'{values[w]:g}%' if w in values else '—' for w in ('weekly','5h')))
            agy_values.extend(values.values())
            agy_resets.extend(_epoch(b.get('resetAt')) for b in group.get('buckets',[]) if _epoch(b.get('resetAt'))>now.timestamp())
    if agy_parts:
        agy_remaining=min(agy_values)
        next_reset=dt.datetime.fromtimestamp(min(agy_resets),KST).strftime('%m-%d %H:%M') if agy_resets else '—'
        rows.append('[안티그래비티] '+' | '.join(agy_parts)+' (주간/5h) | 다음 리셋 '+next_reset)
    elif agy_remaining is not None and 0<=agy_remaining<=100:
        rows.append('[안티그래비티 구독] 잔여 '+gauge(agy_remaining)+' | 리셋: '+str(agy.get('resetAt') or '—'))
    else:
        agy_remaining=None
        rows.append('[안티그래비티 구독] '+('구독량 조회 미연결' if not agy else '구독량 조회 미확인 · '+str(agy.get('status') or '갱신 필요')))
    router=remote.get('openrouter',{});balance=number(router.get('balance'));limit=number(router.get('limit'));left=number(router.get('limit_remaining'))
    router_remaining=max(0,min(100,left/limit*100)) if limit and left is not None else 0 if balance is not None and balance<=0 else None
    rows.append('[OpenRouter] 잔여 '+gauge(router_remaining)+' | 종량제'+(' (충전 필요)' if balance is not None and balance<=0 else '')+' | '+money(balance))
    styles=['bold red' if remaining is not None and remaining<=0 else 'bold cyan' if 'codex' in providers else 'dim',
            'bold red' if agy_remaining is not None and agy_remaining<=0 else 'bold cyan' if providers & {'agy','gemini'} else 'dim',
            'bold red' if router_remaining==0 else 'bold cyan' if 'openrouter' in providers else 'dim','dim']
    brains=data.get('agentBrains',{});crew={r.get('role'):r for r in data.get('crew',[])}
    def model(role):return brains.get(role,{}).get('badge') or brains.get(role,{}).get('model') or crew.get(role,{}).get('configuredModel') or crew.get(role,{}).get('model') or '—'
    mapping='[직원 매핑] @팀장('+model('jarvis')+') | '
    mapping+=('@publi·@patch('+model('publi')+')' if model('publi')==model('patch') else '@publi('+model('publi')+') | @patch('+model('patch')+')')
    mapping+=' | Threads('+model('threads_pipeline')+')';rows.append(mapping)
    spans=[]
    for r in active:
        role=r.get('agentSlot')
        if role in ('cf_pipeline','naver_pipeline','kin_pipeline'):role='publi'
        name='Threads' if role=='threads_pipeline' else '@팀장' if role=='jarvis' else '@'+str(role)
        if role in ('jarvis','publi','patch','threads_pipeline'):
            start=mapping.find(name)
            if start>=0:spans.append([start,start+len(name)])
    return dict(rows=rows,styles=styles,spans=spans)


def brain_lines(data,now):
    return brain_display(data,now)['rows']


def brain_render(display):
    rows=[line(value,style) for value,style in zip(display['rows'],display['styles'])]
    for start,end in display.get('spans',[]):rows[3].stylize('bold cyan not dim',start,end)
    return Group(*rows)


def stage_number(stage):
    text=str(stage).lower()
    if any(x in text for x in ('editorial','prewrit','사전','팀장','자비스')):return 3
    if any(x in text for x in ('keyword','키워드','주제')):return 1
    if any(x in text for x in ('research','리서치','근거','소싱')):return 2
    if any(x in text for x in ('writer','원고','집필','본문')):return 4
    if any(x in text for x in ('image','assembl','review','이미지','시각','조립','검수')):return 5
    if any(x in text for x in ('publish','index','발행','색인','예약')):return 6
    return None


def pipeline_lines(data,now):
    cf=data.get('cf',{});nv=data.get('naver',{});kin=data.get('kin',{});rows=[];day=now.date().isoformat()
    items=cf.get('items',[]) if cf.get('date')==day else []
    for channel in data.get('channels',[]):
        done=channel['done'];target=channel['target'];note=channel['note']
        if channel['name']=='CF 블로그':note=f"성공 {done or 0} · 진행 {sum(i.get('status') in ('processing','publishing') for i in items)} · 검수 {sum(i.get('status')=='review_required' for i in items)} · 실패 {sum(i.get('status')=='failed' for i in items)}"+' · '+channel['note']
        if channel['name']=='네이버 지식iN':note=' · '.join(f"{a} {v.get('publishedVerified',0)}건" for a,v in kin.get('daily',{}).get('byAccount',{}).items())+' · '+note
        counts={k:('—' if v is None else v) for k,v in (channel.get('counts') or {}).items()}
        if counts:note='준비 '+str(counts.get('prepared','—'))+' · 대기 '+str(counts.get('waiting','—'))+' · 실패 '+str(counts.get('failed','—'))+' · '+note
        if channel.get('blockedAttempts'):note='차단 이력 '+str(channel['blockedAttempts'])+'회 · '+note
        rows.append(f"{channel['name']} [{done if done is not None else '—':>2}/{target}] {bar(done,target)} {((done or 0)/target):.0%} · {note}")
    threads=data.get('threads',{}).get('today',{});count=sum(int(r.get('n',0)) for r in threads.get('counts',[]) if r.get('state')=='published_verified' and r.get('kind')=='main') if threads.get('date')==day else None
    thread_counts={k:('—' if v is None else v) for k,v in (data.get('threadCounts') or {}).items()}
    experiments=data.get('maintenance',{}).get('growth',{}).get('experiments',[])
    repaired=sum(r.get('status')=='done' and _date(r.get('updatedAt'))==day for r in experiments)
    rows.append(f'Threads [{count if count is not None else "—"}/4] {bar(count,4)} · 준비 {thread_counts.get("prepared","—")} · 대기 {thread_counts.get("waiting","—")} · 실패 {thread_counts.get("failed","—")} · 닥터 오늘 개선 {repaired}건')
    control=data.get('agendaControl') or {};agenda=control.get('active') or {};target=agenda.get('target') or {}
    def belongs(project,account,slot,at):
        if not control.get('enabled'):return True
        return (agenda.get('project')==project and target.get('account')==account
                and (not target.get('slot') or str(target['slot'])==str(slot))
                and agenda.get('processObserved') is True and now.timestamp()+2>=_epoch(at)>=_epoch(agenda.get('activatedAt'))>0)
    active=[('CF Order '+str(r.get('order'))+' '+str(r.get('domain')),r.get('stageName',''),r.get('stageTimes',{}).get(str(r.get('currentStage'))) or r.get('attemptStartedAt'),r.get('detailMessage') or r.get('lastError','')) for r in items if r.get('status') in ('processing','publishing')
            and belongs('cf_blog',r.get('domain'),target.get('slot'),r.get('stageTimes',{}).get(str(r.get('currentStage'))) or r.get('attemptStartedAt'))]
    workflow=data.get('workflow',{});runtime=workflow.get('runtime',workflow)
    workflow_at=(str(workflow.get('workDate') or workflow.get('date') or day)+'T'+workflow['updatedAt']+'+09:00') if len(str(workflow.get('updatedAt','')))==8 else workflow.get('attemptStartedAt')
    if workflow.get('status') in ('running','processing') or runtime.get('status')=='running':
        account=str(workflow.get('account') or runtime.get('account') or workflow.get('blogId','')).split(' ',1)[0]
        if belongs('naver_blog',account,workflow.get('scheduledSlot'),workflow_at):
            active.append(('네이버 '+str(workflow.get('account') or runtime.get('account','')),workflow.get('stageName') or runtime.get('stage',''),workflow_at,workflow.get('detailMessage','')))
        elif control.get('enabled'):
            rows.append('과거 실행 기록 · 네이버 '+str(workflow.get('account') or runtime.get('account',''))+' · '+str(workflow.get('updatedAt') or '시각 미상')+' · 현재 실행 근거 없음')
    if control.get('enabled'):
        from common.work_agenda import LABELS
        title='현재 안건 · '+str(agenda.get('title') or '활성 안건 없음')
        if agenda:title+=' · '+LABELS.get(agenda.get('status'),str(agenda.get('status')))
        rows.insert(0,title)
        rows.insert(1,'등록된 작업 프로세스 실행 관측' if agenda.get('processObserved') else '등록된 작업 프로세스 실행 미관측 · 회의·진단 상태는 안건 기준')
    for title,stage,started,detail in active[:2]:
        step=stage_number(stage);elapsed=max(0,int(now.timestamp()-_epoch(started))) if _epoch(started) else 0
        rows.append(title+' · '+str(stage)+' · '+str(elapsed)+'초')
        rows.append(' → '.join(('▶ ' if n==step else '')+f'{n}.{label}' for n,label in enumerate(STEPS,1)))
        if detail:rows.append(str(detail)[:180])
    approved=data.get('schedulePolicy',{});prepared=data.get('scheduleRuntime',{})
    if approved.get('effectiveDate'):
        rows.append('시간표 직결 '+str(approved['effectiveDate'])+' · '+str(prepared.get('date',''))+' 네이버 예약 '+str(len(prepared.get('naver',{})))+'/7 · CF 준비 '+str(len(prepared.get('cf',{})))+'/16')
    if not active:
        rows.append('다음 슬롯 준비 / 자동 복구 대기')
        failed=next((r for r in reversed(items) if r.get('status') in ('failed','review_required')),None)
        if failed:rows.append(str(failed.get('domain'))+' · '+str(failed.get('lastError',''))[:160])
    events=[e for e in data.get('events',[]) if str(e.get('stage','')).startswith('editorial-')
            and (not control.get('enabled') or e.get('businessAgendaId')==agenda.get('id'))]
    if active and events:
        last=max(events,key=lambda e:e.get('ts',0));rows.append('@jarvis · '+str(last.get('outputKind') or last.get('stage'))[:160])
    return rows


def dated_graph_nodes(graph,now,root):
    import hashlib
    nodes=graph.get('nodes',{});selected=set()
    for key,n in nodes.items():
        if n.get('type')!='Outcome':continue
        proof=n.get('verifiedWorkProof',{});path=Path(proof.get('sourceRef','')).resolve()
        if not path.is_relative_to(Path(root).resolve()):continue
        try:
            if path.stat().st_size>500000:continue
            if _date(path.stat().st_mtime)!=now.date().isoformat():continue
            if hashlib.sha256(path.read_bytes()).hexdigest()!=proof.get('sourceSha256'):continue
        except OSError:continue
        selected.add(key)
    # Dated immutable producer receipts anchor connected problem/resolution/vault nodes.
    for _ in range(3):
        for edge in graph.get('edges',[]):
            if edge.get('source') in selected or edge.get('target') in selected:
                selected.update((edge['source'],edge['target']))
    return len(selected)


def graph_summary(graph,now):
    return f"Vault/Graph {len(graph.get('nodes',{}))} 노드 · {len(graph.get('edges',[]))} 연결 · 누적 해결 {sum(n.get('resolvedCount',0) for n in graph.get('nodes',{}).values())}회 · 오늘 검증학습 {graph.get('todayVerifiedNodes',0)} 노드"


def panel_sizes(height):
    if height<36:
        base=[4,5,4,5,4,4]
    else:base=[8,11,9,11,10,8]
    total=sum(base)
    if total>height:
        while sum(base)>height:
            index=max(range(6),key=lambda i:base[i]);base[index]-=1
    else:
        weights=[1,2,2,3,2,1]
        for n in range(height-total):base[[i for i,w in enumerate(weights) for _ in range(w)][n%sum(weights)]]+=1
    return base


def render_snapshot(data,now,height):
    layout=Layout(name='cockpit')
    rows=data.get('panels') or [['허브 스냅샷 연결 중']]+[[] for _ in range(5)]
    desired=[len(r)+2 for r in rows]
    sizes=panel_sizes(height)
    if height>=58:
        sizes=[6,9,14,8,9,8]
        for _ in range(height-sum(sizes)):
            index=max(range(6),key=lambda i:desired[i]-sizes[i])
            sizes[index]+=1
    if height>=sum(desired):
        sizes=desired[:]
        for n in range(height-sum(sizes)):sizes[(3,4,2,0,1,5)[n%6]]+=1
    layout.split_column(*[Layout(name=name,size=size) for name,size in zip(NAMES,sizes)])
    titles=('① 💰 수익 · 일일 목표 $100','② 🧠 AI 구독 한도 & 크레딧','③ 🌐 우분투 격리 크롬 세션','④ 🚀 당일 채널 발행 · 실행 단계','⑤ 🤖 6인 크루 · Vault','⑥ ⚡ 완료 · 복구 타임라인')
    for name,color,title,values in zip(NAMES,COLORS,titles,rows):
        content=Group(*[line(v,'bold white on red' if any(t in v for t in ('ALERT','BLOCKED','OFFLINE')) else 'bold bright_green' if any(t in v for t in ('RUNNING','● ON','발행 성공')) else 'bold white') for v in values])
        if name=='brains' and data.get('brainDisplay'):content=brain_render(data['brainDisplay'])
        layout[name].update(Panel(content,title=title+(' · '+now.strftime('%H:%M:%S KST') if name=='revenue' else ''),subtitle=data.get('date','')+' KST · '+data.get('revision','연결 중')[:8],border_style=color,box=box.HEAVY))
    return layout


def render(data,now,height):
    if data.get('schema')=='barolab-mission-control-v2':return render_snapshot(data,now,height)
    layout=Layout(name='cockpit')
    desired=[len(revenue_summary(data.get('revenue',{}),data.get('metrics',{}),now))+2+int(bool(data.get('revenueRefresh'))),
             len(brain_lines(data,now))+2,2*len(data.get('remote',{}).get('fleet',[]))+2,
             len(pipeline_lines(data,now))+2,len(data.get('crew',[]))+4,8]
    if height>=sum(desired):
        sizes=desired[:]
        for n in range(height-sum(sizes)):sizes[(3,4,2,0,1,5)[n%6]]+=1
    elif height>=58:
        sizes=desired[:]
        while sum(sizes)>height:
            index=max(range(6),key=lambda i:sizes[i]-(8,9,12,9,10,8)[i]);sizes[index]-=1
    else:sizes=panel_sizes(height)
    layout.split_column(*[Layout(name=name,size=size) for name,size in zip(NAMES,sizes)])
    content=[]
    revenue_lines=revenue_summary(data.get('revenue',{}),data.get('metrics',{}),now)
    refresh=data.get('revenueRefresh',{})
    if refresh:revenue_lines.insert(2,'수익 자동수집 · API 5분 / 브라우저 10분 · '+str(refresh.get('status','대기'))+' · 원천 보고 지연 별도')
    content.append(Group(*[line(s,'bold bright_yellow' if i<2 else 'bold white') for i,s in enumerate(revenue_lines)]))
    content.append(brain_render(brain_display(data,now)))
    fleet=table(23,34,None)
    for row in data.get('remote',{}).get('fleet',[]):
        pages=sorted(row['tabs'],key=lambda t:not t.get('active'));page=pages[0] if pages else {}
        status='● ON' if row['online'] else '● OFF'
        fleet.add_row(line(f"{row['port']} {row['account']}"),line(row['blog']+' · '+status,'bold bright_green' if row['online'] else 'bold white on red'),
                      line(row['purpose']))
        fleet.add_row('',line(f"{len(pages)}탭 · {row.get('profile','')}"),line(page.get('title','연결 대기')+' · '+page.get('url','')))
    content.append(fleet)
    pipeline=[]
    for text in pipeline_lines(data,now):
        stage=Text(text,style='bold white',no_wrap=True,overflow='ellipsis')
        for symbol in ('■','░'):
            for index,char in enumerate(text):
                if char==symbol:stage.stylize('bold bright_cyan',index,index+1)
        if '▶ ' in text:
            start=text.index('▶ ');end=text.find(' → ',start);stage.stylize('bold black on bright_cyan',start,end if end>=0 else len(text))
        pipeline.append(stage)
    content.append(Group(*pipeline))
    crew=table(16,27,13,None)
    for row in data.get('crew',[]):
        state=row['state'];style='bold bright_cyan' if state=='RUNNING' else 'bold white on red' if state=='ERROR' else 'bold bright_yellow' if state=='CYCLING' else 'bold bright_green'
        crew.add_row(line('@'+row['name']),line(row.get('model') or row.get('configuredModel') or '모델 설정 대기'),line(state,style),line(row['action']+' · 완료 '+row.get('lastCompleted','—')))
    graph=data.get('graph',{});resolutions=[n for n in graph.get('nodes',{}).values() if n.get('type')=='Resolution']
    content.append(Group(crew,line(graph_summary(graph,now)+' · 시냅스 '+str(len(data.get('synapses',{}).get('nodes',{})))+' 노드 / '+str(len(data.get('synapses',{}).get('doctorPlans',[])))+' 유망 글','bold bright_magenta'),line('최근 학습 · '+str(resolutions[-1].get('reason','')) if resolutions else '다음 검증 결과 학습 대기')))
    logs=[]
    for row in data.get('timeline',[])[:6]:
        when=dt.datetime.fromtimestamp(row['at'],KST).strftime('%H:%M:%S') if row.get('at') else '--:--:--'
        logs.append(line('['+when+'] '+row['text'],'bold white on red' if row.get('alert') else 'bold bright_green'))
    content.append(Group(*logs) if logs else line('다음 발행·복구·수익 수집 이벤트 대기'))
    titles=('EGO LITE MISSION CONTROL · ① 💰 $100/day','② 🧠 AI 구독 한도 & 크레딧','③ 🌐 우분투 격리 크롬 세션 · 계정/프로필','④ 🚀 PIPELINE · 6단계 위치','⑤ 🤖 ACTIVE CREW · VAULT','⑥ ⚡ 발행 / 검수 돌파 / 복구 / 수익')
    for i,name in enumerate(NAMES):
        layout[name].update(Panel(content[i],title=titles[i],subtitle=now.strftime('%Y-%m-%d %H:%M:%S KST') if i==0 else None,
             border_style='bold '+COLORS[i],box=box.HEAVY,padding=(0,1),style='white on black'))
    return layout
