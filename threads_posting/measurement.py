"""Observed Threads metrics and exact UTM acquisition, never estimated revenue.

24h/72h/7d are checkpoint snapshots, not claims of exact hourly API windows.
Each snapshot records its real capture age/lag and GA4 calendar-date scope.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from common.dashboard_jobs import write
from .adapter import ROOT, Client, AdapterError, EXPECTED_ACCOUNT, _identity, stamp

PRIVATE = ROOT / 'server/data/threads-measurement.json'
PUBLIC = ROOT / 'dashboard/data/threads-measurement.json'
CHECKPOINTS = {'24h':24, '72h':72, '7d':168}
PLATFORM_METRICS = ('views','likes','replies','reposts','quotes','shares')
RETRY_HOURS = 6


def _read(path):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError): return {}


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z','+00:00'))
        return result if result.tzinfo else None
    except (ValueError,TypeError,AttributeError): return None


def _actual_time(publication):
    basis=publication.get('publication_time_basis')
    if basis is not None and basis!='api_timestamp': return None
    return _time(publication.get('published_at'))


def should_collect(publications, now=None):
    """Cheap scheduler gate: due checkpoints only, failed reads at most every 6h."""
    now=now or datetime.now(timezone.utc); previous=_read(PRIVATE)
    last=_time(previous.get('collected_at'))
    if last and now-last<timedelta(hours=RETRY_HOURS): return False
    old={row.get('part_id'):row for row in previous.get('posts',[]) if isinstance(row,dict)}
    for post in publications:
        published=_actual_time(post)
        if post.get('account_key')!=EXPECTED_ACCOUNT or not published or not str(post.get('platform_id','')).isdigit(): continue
        age=(now-published).total_seconds()/3600
        for key,hours in CHECKPOINTS.items():
            snap=old.get(post.get('part_id'),{}).get('snapshots',{}).get(key,{})
            if age>=hours and (snap.get('platform',{}).get('status')!='collected' or snap.get('ga4',{}).get('complete') is not True): return True
    return False


def feedback(posts, now=None):
    """Small diagnostic evidence for the next draft; never auto-scales frequency."""
    now=now or datetime.now(timezone.utc)
    result={'status':'insufficient_data','computedAt':now.isoformat(),'checkpoint':None,
            'comparablePosts':0,'evidence':[],'recommendations':[],'authoringHints':[],
            'policy':'diagnostic heuristics, not platform ranking rules or causal lift; no automatic frequency increase'}
    selected=[]
    for key in ('7d','72h','24h'):
        candidates=[]
        for post in posts:
            snap=post.get('snapshots',{}).get(key,{})
            ga=snap.get('ga4',{}); platform=snap.get('platform',{})
            lag=snap.get('capture_lag_hours')
            if platform.get('status')!='collected' or ga.get('complete') is not True or type(lag) not in (int,float) or lag>max(6,CHECKPOINTS[key]*0.25): continue
            if any(type(ga.get(metric)) is not int or ga[metric]<0 for metric in ('sessions','engaged_sessions','page_views')):continue
            candidates.append((post,snap))
        if len(candidates)>=3:
            selected=candidates;result.update(status='diagnostic',checkpoint=key,comparablePosts=len(candidates));break
    if not selected:
        result['recommendations']=['동일 체크포인트의 비교 가능한 게시물 3개 이상을 기다립니다. 미수집을 성과 0으로 해석하지 않습니다.']
        return result
    groups={}
    for post,snap in selected:
        ga=snap['ga4'];metrics=snap['platform'].get('metrics',{});views=metrics.get('views')
        evidence={'part_id':post['part_id'],'format':post.get('format','unclassified'),'topic':post.get('topic','unclassified'),
                  'views':views,'sessions':ga['sessions'],'engaged_sessions':ga['engaged_sessions'],
                  'ga4_start':ga.get('start_date'),'ga4_end':ga.get('end_date'),'capture_lag_hours':snap['capture_lag_hours'],
                  'provisional':ga.get('provisional',True)}
        result['evidence'].append(evidence)
        if type(views) is int and views>=100 and ga['sessions']==0:
            result['recommendations'].append(post['part_id']+': 조회 대비 측정 유입이 없습니다. 링크 도착·UTM 보존과 본문 CTA의 관련성을 점검하세요.')
            result['authoringHints'].append('클릭 유도 문구를 늘리기보다 링크가 제공하는 추가 정보를 구체적으로 설명하고, 본문만으로도 질문에 답합니다.')
        if ga['sessions']>=10 and ga['engaged_sessions']/ga['sessions']<0.3:
            result['recommendations'].append(post['part_id']+': 유입 대비 참여 세션 비율이 낮습니다. 랜딩 글과 게시물의 기대 일치를 점검하세요.')
            result['authoringHints'].append('랜딩 글에서 실제 제공하는 내용에 맞춰 제목과 약속을 좁히고 과장된 기대를 만들지 않습니다.')
        for dimension in ('format','topic'):
            value=post.get(dimension)
            if not isinstance(value,str) or not value or value=='unclassified':continue
            # Different GA4 calendar coverage must never be compared as equal exposure.
            start=_time((ga.get('start_date') or '')+'T00:00:00+09:00');end=_time((ga.get('end_date') or '')+'T00:00:00+09:00')
            days=(end-start).days+1 if start and end else None
            group=groups.setdefault((dimension,value,days),{'posts':0,'sessions':0,'engaged_sessions':0})
            group['posts']+=1;group['sessions']+=ga['sessions'];group['engaged_sessions']+=ga['engaged_sessions']
    result['groups']=[{'dimension':key[0],'value':key[1],'ga_calendar_days':key[2],**value,
                       'engaged_sessions_per_post':round(value['engaged_sessions']/value['posts'],3)} for key,value in groups.items()]
    comparable=[group for group in result['groups'] if group['posts']>=3 and group['sessions']>=10 and group['ga_calendar_days'] is not None]
    for dimension in ('format','topic'):
        by_days={}
        for group in comparable:
            if group['dimension']==dimension:by_days.setdefault(group['ga_calendar_days'],[]).append(group)
        for values in by_days.values():
            if len(values)<2:continue
            ranked=sorted(values,key=lambda row:row['engaged_sessions_per_post'],reverse=True)
            if ranked[0]['engaged_sessions_per_post']<=ranked[-1]['engaged_sessions_per_post']:continue
            result['recommendations'].append(dimension+' '+ranked[0]['value']+': 게시물당 참여 세션 관측값이 상대적으로 높습니다. 동일 조건에서 반복 검증하고 게시 빈도는 늘리지 않습니다.')
            result['authoringHints'].append(dimension+' '+ranked[0]['value']+'의 정보 구성·질문 일치를 참고하되, 표본이 작고 잠정 집계이므로 정답 형식이나 인과 효과로 단정하지 않습니다.')
    result['authoringHints']=list(dict.fromkeys(result['authoringHints']))[:5]
    if not result['recommendations']:result['recommendations']=['비교 가능한 관측은 있으나 변경을 권고할 뚜렷한 근거가 없습니다. 현재 빈도를 유지하며 추가 측정합니다.']
    return result


def _insights(client, endpoint, names):
    raw = client.request('GET', endpoint, {'metric':','.join(names)})
    values = {name:None for name in names}
    for row in raw.get('data',[]):
        if not isinstance(row,dict) or row.get('name') not in values: continue
        candidates = row.get('values')
        value = candidates[0].get('value') if isinstance(candidates,list) and len(candidates)==1 and isinstance(candidates[0],dict) else None
        if value is None and isinstance(row.get('total_value'),dict): value=row['total_value'].get('value')
        if type(value) is int and value >= 0: values[row['name']]=value
    return {'status':'collected' if all(v is not None for v in values.values()) else 'partial',
            'scope':'platform_reported_lifetime_post_metrics','metrics':values,'collected_at':stamp()}


def _ga4(publication, now):
    unknown={'status':'unmeasured','complete':False,'sessions':None,'engaged_sessions':None,'page_views':None,
             'source':'GA4 Data API','timezone':'Asia/Seoul','scope':'exact Threads UTM; publication date through yesterday; calendar-day cohort, not exact 24h/72h/7d',
             'provisional':True,'reason':'attribution_url_unverified'}
    url=publication.get('outbound_url'); parsed=urlsplit(url or ''); query=parse_qs(parsed.query)
    if parsed.scheme!='https' or not parsed.hostname or any(query.get(k)!=[v] for k,v in [('utm_source','threads'),('utm_medium','social'),('utm_campaign','cf_bridge')]) or len(query.get('utm_content',[]))!=1:
        return unknown
    token=query['utm_content'][0]
    published=_actual_time(publication)
    if not published: return {**unknown,'reason':'publication_time_unverified'}
    start=published.astimezone(ZoneInfo('Asia/Seoul')).date()
    end=now.astimezone(ZoneInfo('Asia/Seoul')).date()-timedelta(days=1)
    if end<start: return {**unknown,'status':'pending_reporting','reason':'today_not_reported','start_date':str(start),'end_date':None}
    if str(ROOT/'dashboard') not in sys.path: sys.path.insert(0,str(ROOT/'dashboard'))
    import traffic
    from metrics import CONFIG
    config=_read(CONFIG); domain=parsed.hostname.removeprefix('www.')
    settings=config.get('sites',{}).get(domain,{})
    unknown.update(start_date=str(start),end_date=str(end))
    if not settings.get('ga4_property') or not settings.get('analytics_reader'):
        return {**unknown,'reason':'ga4_not_connected'}
    expressions=[{'filter':{'fieldName':field,'stringFilter':{'matchType':'EXACT','value':value,'caseSensitive':True}}}
                 for field,value in [('sessionSource','threads'),('sessionMedium','social'),('sessionManualCampaignName','cf_bridge'),('sessionManualAdContent',token)]]
    expressions.append({'filter':{'fieldName':'hostName','inListFilter':{'values':[domain,'www.'+domain],'caseSensitive':False}}})
    body={'dateRanges':[{'startDate':str(start),'endDate':str(end)}],
          'metrics':[{'name':name} for name in ['sessions','engagedSessions','screenPageViews']],
          'dimensionFilter':{'andGroup':{'expressions':expressions}},'limit':10000}
    try:
        with traffic.session(settings,config.get('analytics_readers',{}),'https://www.googleapis.com/auth/analytics.readonly') as client:
            rows,limited=traffic.ga_report(client,settings['ga4_property'],body,[])
        if limited or len(rows)>1: return {**unknown,'status':'partial','reason':'ga4_limited_or_unexpected_rows'}
        values=rows[0][1] if rows else [0,0,0]
        return {**unknown,'status':'collected','complete':True,'sessions':values[0],
                'engaged_sessions':values[1],'page_views':values[2],'reason':None,'collected_at':stamp(),
                'utm_content':token,'host':parsed.hostname}
    except Exception as exc:
        return {**unknown,'status':'collection_error','reason':'ga4_'+type(exc).__name__}


def collect(config, publications, now=None, *, persist=True):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None: raise ValueError('Aware collection timestamp required')
    previous=_read(PRIVATE) if persist else {}
    old={row['part_id']:row for row in previous.get('posts',[]) if isinstance(row,dict) and row.get('part_id')}
    output={'schema':'threads-measurement-v1','status':'unmeasured','complete':False,'collected_at':now.isoformat(),
            'scope':'@mustpickinfo published parts only; platform lifetime checkpoint metrics and exact-UTM GA4 calendar-day acquisition; no causal lift',
            'windows':{key:{'status':'not_due','due_parts':0,'captured_parts':0} for key in CHECKPOINTS},
            'posts':[],'account_metrics':{'status':'unmeasured','clicks':None,'scope':'account_link_clicks_not_post_clicks'},
            'revenue':None,'revenue_status':'publisher_attribution_unverified'}
    client=None; connection_reason='needs_connection'
    try: client=Client(config);_identity(client)
    except AdapterError as exc: connection_reason=exc.code;client=None
    if client:
        try:
            account_start=_time(config.get('activatedAt')) or (now-timedelta(days=14))
            raw=client.request('GET','me/threads_insights',{'metric':'clicks','since':int(account_start.timestamp()),'until':int(now.timestamp())})
            output['account_metrics'].update(requested_since=account_start.isoformat(),requested_until=now.isoformat())
            clicks_row=next((row for row in raw.get('data',[]) if isinstance(row,dict) and row.get('name')=='clicks'),None)
            links=clicks_row.get('link_total_values') if clicks_row else None
            if isinstance(links,list) and all(isinstance(row,dict) and type(row.get('value')) is int and row['value']>=0 for row in links):
                output['account_metrics'].update(status='collected',clicks=sum(row['value'] for row in links),collected_at=stamp(),scope='account_link_clicks_all_links_in_requested_period; not per-post clicks or unique visits')
            else: output['account_metrics']['reason']='account_clicks_response_unavailable'
        except AdapterError as exc: output['account_metrics']['reason']=exc.code
    else: output['account_metrics']['reason']=connection_reason
    for publication in publications:
        if publication.get('account_key')!=EXPECTED_ACCOUNT or not str(publication.get('platform_id','')).isdigit(): continue
        published=_actual_time(publication); part_id=publication.get('part_id')
        if not isinstance(part_id,str):continue
        if not published:
            output['posts'].append({'part_id':part_id,'attempt_id':publication.get('attempt_id'),'platform_id':publication['platform_id'],
                'permalink':publication.get('permalink'),'published_at':None,'publication_time_basis':'unknown','status':'publication_time_unverified','snapshots':{}})
            continue
        age=(now-published).total_seconds()/3600
        if age<0: continue
        row={'part_id':part_id,'attempt_id':publication.get('attempt_id'),'platform_id':publication['platform_id'],'permalink':publication.get('permalink'),
             'format':publication.get('format','unclassified'),'topic':publication.get('topic','unclassified'),
             'published_at':published.isoformat(),'publication_time_basis':'api_timestamp','snapshots':dict(old.get(part_id,{}).get('snapshots',{}))}
        for key,hours in CHECKPOINTS.items():
            if age<hours: continue
            output['windows'][key]['due_parts']+=1
            snapshot=row['snapshots'].get(key)
            platform_captured = bool(snapshot and snapshot.get('platform',{}).get('status')=='collected')
            # Preserve successful checkpoint evidence; retry unconnected/error data later.
            if not snapshot or snapshot.get('platform',{}).get('status')!='collected' or snapshot.get('ga4',{}).get('complete') is not True:
                platform=snapshot.get('platform') if snapshot and snapshot.get('platform',{}).get('status')=='collected' else {'status':'unmeasured','metrics':dict.fromkeys(PLATFORM_METRICS),'reason':connection_reason}
                if client and platform.get('status')!='collected':
                    try: platform=_insights(client,str(publication['platform_id'])+'/insights',PLATFORM_METRICS)
                    except AdapterError as exc: platform['reason']=exc.code
                ga4=snapshot.get('ga4') if snapshot and snapshot.get('ga4',{}).get('complete') is True else _ga4(publication,now)
                metadata = snapshot if platform_captured else {'target_hours':hours,'captured_at':now.isoformat(),'actual_age_hours':round(age,3),'capture_lag_hours':round(age-hours,3)}
                snapshot={**metadata,'platform':platform,'ga4':ga4}
                row['snapshots'][key]=snapshot
            if snapshot.get('platform',{}).get('status')=='collected' and snapshot.get('ga4',{}).get('complete') is True:
                output['windows'][key]['captured_parts']+=1
        output['posts'].append(row)
    for window in output['windows'].values():
        if window['due_parts']: window['status']='collected' if window['captured_parts']==window['due_parts'] else 'partial'
    due=sum(window['due_parts'] for window in output['windows'].values())
    unknown_time=any(row.get('status')=='publication_time_unverified' for row in output['posts'])
    output['complete']=bool(due) and not unknown_time and all(window['status'] in ('collected','not_due') for window in output['windows'].values())
    output['status']='collected' if output['complete'] else 'partial' if due else 'unmeasured' if unknown_time else 'not_due' if output['posts'] else 'unmeasured'
    if unknown_time:output['unmeasured_reason']='publication_time_unverified'
    output['feedback']=feedback(output['posts'],now)
    if persist: write(PRIVATE,output);write(PUBLIC,output)
    return output
