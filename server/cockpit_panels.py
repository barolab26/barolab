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
STEPS=('키워드선정','리서치·근거수집','사전검수·자비스조정','원고집필','시각자료·조립검수','최종발행·색인')


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


def brain_lines(data,now):
    remote=data.get('remote',{});ledger=data.get('usage',{});rows=[]
    today=ledger if ledger.get('date')==now.date().isoformat() else {}
    for key,r in sorted(today.get('byModel',{}).items()):
        total=r.get('inputTokens',0)+r.get('outputTokens',0)
        latency=r.get('lastLatencyMs',0)/1000
        headers=r.get('rateLimitHeaders',{});remain=headers.get('x-ratelimit-remaining-requests')
        status='한도임박' if r.get('lastStatus')=='failed' and r.get('rateLimited') else '정상' if r.get('lastStatus')=='completed' else '호출 오류'
        rows.append(f"{r['provider']} · {r['model']}  성공 {r.get('success',0)} / 실패 {r.get('errors',0)}  IN {r.get('inputTokens',0):,} OUT {r.get('outputTokens',0):,}  {latency:.1f}s · {status}"+(f' · 잔여요청 {remain}' if remain is not None else ''))
    if not rows:rows.append('오늘 호출 상세 집계 시작 · 공급자 보고 토큰만 누적')
    if data.get('tokens'):rows.append('Codex 오늘 보고 토큰 · '+str(data['tokens'][0]))
    active=[r for r in today.get('active',{}).values() if 0<=now.timestamp()-_epoch(r.get('startedAt'))<900]
    rows.append('호출 중: '+(', '.join(r.get('model','')+' '+str(int(now.timestamp()-_epoch(r.get('startedAt'))))+'s' for r in active[:3]) or '다음 요청 대기'))
    quota=remote.get('codexQuota',{});windows=[]
    for name,bucket in quota.get('buckets',{}).items():
        for label_key in ('primary','secondary'):
            window=bucket.get(label_key) or {}
            used=window.get('usedPercent')
            if isinstance(used,(int,float)):
                mins=window.get('windowDurationMins');reset=_epoch(window.get('resetsAt'))
                label=f'{mins//1440}일' if isinstance(mins,int) and mins>=1440 else f'{mins}분'
                windows.append(f'{name} {label} 잔여 {max(0,100-used):g}%'+(f' · 초기화 {dt.datetime.fromtimestamp(reset,KST):%m-%d %H:%M}' if reset else ''))
    rows.append('Codex · ChatGPT Subscription  '+(' | '.join(windows) if windows else quota.get('status','한도 조회 중')))
    credit_rows=[]
    for name,bucket in quota.get('buckets',{}).items():
        credits=bucket.get('credits')
        if isinstance(credits,dict):
            balance=credits.get('balance')
            credit_rows.append(name+' '+('무제한' if credits.get('unlimited') is True else format(number(balance),',.2f')+' 크레딧' if number(balance) is not None else '보유' if credits.get('hasCredits') is True else '없음'))
    rows.append('Codex 계정 추가 크레딧  '+(' | '.join(credit_rows) if credit_rows else '계정 크레딧 조회 중'))
    rows.append('AGY Argon High / Med · 3.8 Flash: 현재 비활성 / Codex 우회 · 일일 쿼터 API 미제공')
    credit=remote.get('openrouter',{})
    rows.append('OpenRouter  사용 '+money(credit.get('usage'))+' · 키 잔여 '+('제한 없음' if credit.get('status')=='collected' and credit.get('limit') is None else money(credit.get('limit_remaining')))+' · 계정 잔액 '+money(credit.get('balance'))+' · '+credit.get('status','조회 중'))
    api=[r for r in today.get('byModel',{}).values() if r.get('provider')=='openai']
    rows.append('OpenAI API  '+('키 설정' if data.get('openaiKey') else '키 미설정')+' · API 잔액은 결제 페이지에서 제공 · 응답 한도 '+('연결' if api else '호출 대기'))
    proxy=data.get('proxy',{});route=proxy.get('model') or '호출 기록 대기'
    rows.append(f"FreeLLMAPI :3001  {'● ONLINE' if proxy.get('online') else '● OFFLINE'} · 라우팅 {route} · 평균 {proxy.get('latency','—')}ms")
    return rows


def stage_number(stage):
    text=str(stage).lower()
    if any(x in text for x in ('editorial','prewrit','사전','자비스')):return 3
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
        rows.append(f"{channel['name']} [{done if done is not None else '—':>2}/{target}] {bar(done,target)} {((done or 0)/target):.0%} · {note}")
    threads=data.get('threads',{}).get('today',{});count=sum(int(r.get('n',0)) for r in threads.get('counts',[]) if r.get('state')=='published_verified' and r.get('kind')=='main') if threads.get('date')==day else None
    experiments=data.get('maintenance',{}).get('growth',{}).get('experiments',[])
    repaired=sum(r.get('status')=='done' and _date(r.get('updatedAt'))==day for r in experiments)
    rows.append(f'Threads [{count if count is not None else "—"}/4] {bar(count,4)} · 닥터 오늘 개선 {repaired}건')
    active=[('CF Order '+str(r.get('order'))+' '+str(r.get('domain')),r.get('stageName',''),r.get('stageTimes',{}).get(str(r.get('currentStage'))) or r.get('attemptStartedAt'),r.get('detailMessage') or r.get('lastError','')) for r in items if r.get('status') in ('processing','publishing')]
    workflow=data.get('workflow',{});runtime=workflow.get('runtime',workflow)
    if workflow.get('status') in ('running','processing') or runtime.get('status')=='running':
        active.append(('네이버 '+str(workflow.get('account') or runtime.get('account','')),workflow.get('stageName') or runtime.get('stage',''),(day+'T'+workflow['updatedAt']+'+09:00') if len(str(workflow.get('updatedAt','')))==8 else workflow.get('attemptStartedAt'),workflow.get('detailMessage','')))
    for title,stage,started,detail in active[:2]:
        step=stage_number(stage);elapsed=max(0,int(now.timestamp()-_epoch(started))) if _epoch(started) else 0
        rows.append(title+' · '+str(stage)+' · '+str(elapsed)+'초')
        rows.append(' → '.join(('▶ ' if n==step else '')+f'{n}.{label}' for n,label in enumerate(STEPS,1)))
        if detail:rows.append(str(detail)[:180])
    if not active:
        rows.append('다음 슬롯 준비 / 자동 복구 대기')
        failed=next((r for r in reversed(items) if r.get('status') in ('failed','review_required')),None)
        if failed:rows.append(str(failed.get('domain'))+' · '+str(failed.get('lastError',''))[:160])
    events=[e for e in data.get('events',[]) if str(e.get('stage','')).startswith('editorial-')]
    if events:
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


def render(data,now,height):
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
    content.append(Group(*[line(s,'bold white on red' if '잔여 0%' in s or '한도임박' in s or '잔액 $-' in s else 'bold bright_green' if 'Codex 계정 추가 크레딧' in s else 'bold bright_cyan' if 'Subscription' in s else 'bold white') for s in brain_lines(data,now)]))
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
    content.append(Group(crew,line(graph_summary(graph,now),'bold bright_magenta'),line('최근 학습 · '+str(resolutions[-1].get('reason','')) if resolutions else '다음 검증 결과 학습 대기')))
    logs=[]
    for row in data.get('timeline',[])[:6]:
        when=dt.datetime.fromtimestamp(row['at'],KST).strftime('%H:%M:%S') if row.get('at') else '--:--:--'
        logs.append(line('['+when+'] '+row['text'],'bold white on red' if row.get('alert') else 'bold bright_green'))
    content.append(Group(*logs) if logs else line('다음 발행·복구·수익 수집 이벤트 대기'))
    titles=('EGO LITE MISSION CONTROL · ① 💰 $100/day','② 🧠 BRAIN · 크레딧 / 구독 / 호출','③ 🌐 우분투 격리 크롬 세션 · 계정/프로필','④ 🚀 PIPELINE · 6단계 위치','⑤ 🤖 ACTIVE CREW · VAULT','⑥ ⚡ 발행 / 검수 돌파 / 복구 / 수익')
    for i,name in enumerate(NAMES):
        layout[name].update(Panel(content[i],title=titles[i],subtitle=now.strftime('%Y-%m-%d %H:%M:%S KST') if i==0 else None,
             border_style='bold '+COLORS[i],box=box.HEAVY,padding=(0,1),style='white on black'))
    return layout
