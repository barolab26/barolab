"""Evidence-only completed-window growth and improvement suggestions."""
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from metrics import DATA, read_json, inventory
from traffic import search_windows
from revenue import growth_revenue_summary


def periods(now=None):
    windows = search_windows(now or datetime.now(timezone.utc))
    return {'current': windows['current28'], 'previous': windows['previous28'],
            'searchTimezone': 'America/Los_Angeles', 'lagDays': 3}


def report_valid(report, window, now):
    if report.get('status','collected') not in ('collected','partial'):
        return False
    if any(isinstance(report.get(k),bool) or not isinstance(report.get(k),(int,float)) or
           not math.isfinite(report[k]) or report[k]<0 for k in ('clicks','impressions')):
        return False
    try:
        age = (now - datetime.fromisoformat(report['checkedAt'])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return False
    return (0 <= age <= 26*3600 and not report.get('partialPeriod') and
            all(report.get(k) == window[k] for k in ('start', 'end')))


def metric(report, valid):
    return {k: report.get(k) if valid else None for k in ('impressions','clicks','ctr','position')}


def measured_row(row):
    return all(not isinstance(row.get(k),bool) and isinstance(row.get(k),(int,float)) and
               math.isfinite(row[k]) and row[k]>=0 for k in ('clicks','impressions'))


def linkage_fresh(report,now):
    try:
        age=(now-datetime.fromisoformat(report['checkedAt'])).total_seconds()
        return 0<=age<=26*3600 and report.get('queriesStatus')=='collected' and report.get('filterVerified') is True
    except (KeyError,ValueError,TypeError):
        return False


def pct(current, previous):
    return (current-previous)/previous*100 if current is not None and previous is not None and previous > 0 else None


def click_decomposition(current, previous):
    """Symmetric accounting identity; neither component establishes causality."""
    c1,c0=current.get('clicks'),previous.get('clicks')
    i1,i0=current.get('impressions'),previous.get('impressions')
    result={'identityVerified':False,'clickDelta':None,'impressionEffect':None,'ctrEffect':None,
            'reason':'양기간 노출·클릭이 확인되지 않아 분해하지 않음'}
    if any(v is None for v in (c1,c0,i1,i0)) or i1<=0 or i0<=0:
        return result
    r1,r0=c1/i1,c0/i0
    impression=(i1-i0)*(r1+r0)/2
    ctr=(r1-r0)*(i1+i0)/2
    result.update(identityVerified=abs(impression+ctr-(c1-c0))<1e-8,clickDelta=c1-c0,
                  impressionEffect=impression,ctrEffect=ctr,
                  reason='노출과 CTR의 산술 분해이며 원인·개선 효과를 입증하지 않음')
    return result


def matched_contributors(current,previous,kind,domain):
    scope=current.get('queriesScope') if kind=='query' else 'page'
    if kind=='query' and scope!=previous.get('queriesScope'):
        return [], {'currentUnmatched':len(current.get('queries',[])), 'previousUnmatched':len(previous.get('queries',[]))}
    rows='queries' if kind=='query' else 'pages'
    def identity(row):
        return (row.get('query'),row.get('page')) if kind=='query' else row.get('page')
    a={identity(r):r for r in current.get(rows,[])}
    b={identity(r):r for r in previous.get(rows,[])}
    matched=[]
    for key in a.keys() & b.keys():
        left,right=a[key],b[key]
        if not measured_row(left) or not measured_row(right):
            continue
        row={'current':metric(left,True),'previous':metric(right,True),
             'clickDelta':left['clicks']-right['clicks'],
             'impressionDelta':left['impressions']-right['impressions'],
             'status':'matched','comparable':True,'scope':scope,'sharePct':None,
             'shareReason':'상위 일부 행·누락·증감 상쇄 가능성으로 전체 기여율을 계산하지 않음'}
        if kind=='query':
            row.update(query=left.get('query'),url=left.get('page'))
        else:
            row.update(url=key)
        matched.append(row)
    matched.sort(key=lambda r:(-abs(r['clickDelta']),-abs(r['impressionDelta']),-r['current']['impressions']))
    return matched[:20], {'currentUnmatched':len(a.keys()-b.keys()),'previousUnmatched':len(b.keys()-a.keys())}


def diagnose_domain(domain,source,windows,now):
    current=source.get('periods',{}).get('current28',{})
    previous=source.get('periods',{}).get('previous28',{})
    valid=report_valid(current,windows['current'],now) and report_valid(previous,windows['previous'],now)
    facts,hypotheses,unknowns,actions=[],[],[],[]
    pages,queries=[],[]
    coverage={'topRowsOnly':True,'reason':'글·검색어는 상위 일부 행이며 비공개 검색어가 빠질 수 있음',
              'pageComparable':False,'queryComparable':False}
    decomposition=click_decomposition(metric(current,valid),metric(previous,valid))
    if valid:
        facts.append(f"동일한 28일 비교에서 클릭 {previous['clicks']}→{current['clicks']}, 노출 {previous['impressions']}→{current['impressions']} 확인")
        if current.get('pagesStatus')==previous.get('pagesStatus')=='collected':
            pages,page_missing=matched_contributors(current,previous,'page',domain)
            coverage.update(pageComparable=bool(pages),pageReportCollected=True,pageRows=page_missing)
        if current.get('queriesStatus')==previous.get('queriesStatus')=='collected' and current.get('queriesScope')==previous.get('queriesScope'):
            queries,query_missing=matched_contributors(current,previous,'query',domain)
            coverage.update(queryComparable=bool(queries),queryReportCollected=True,queryRows=query_missing,queryScope=current.get('queriesScope'))
        linked=source.get('linkedPageQueries',{})
        linked_pair=linked.get('periods',{})
        if linked.get('status')=='collected' and not linked.get('stale') and all(linkage_fresh(linked_pair.get(k,{}),now) and
               all(linked_pair[k].get(v)==windows[name][v] for v in ('start','end'))
               for k,name in [('current28','current'),('previous28','previous')]):
            left,right=linked_pair['current28'],linked_pair['previous28']
            linked_rows,_=matched_contributors({**left,'queriesScope':'page_query'}, {**right,'queriesScope':'page_query'},'query',domain)
            queries.extend(linked_rows)
            queries=list({(r['query'],r.get('url'),r['scope']):r for r in queries}.values())
            coverage['linkedPageFilterVerified']=True
            coverage['queryComparable']=bool(queries)
        for row in pages[:3]:
            before,after=row['previous'],row['current']
            position_before,position_after=before.get('position'),after.get('position')
            ctr_before,ctr_after=before.get('ctr'),after.get('ctr')
            facts.append(f"{row['url']} 노출 {before['impressions']}→{after['impressions']}, 클릭 {before['clicks']}→{after['clicks']} 실측")
            if position_before is not None and position_after is not None and abs(position_after-position_before)<=1 and after['impressions']>before['impressions']:
                hypotheses.append({'reason':f"{row['url']} 순위가 유사한 상태에서 노출 증가: 수요·노출 범위 변화 가능성",
                    'confidence':'낮음','evidence':f"평균순위 {position_before:.2f}→{position_after:.2f}, 노출 {before['impressions']}→{after['impressions']}; 검색어 구성 영향 미분리"})
            if ctr_before is not None and ctr_after is not None and ctr_after<ctr_before:
                wording='순위 악화와 CTR 하락이 함께 관측됨' if position_before is not None and position_after is not None and position_after>position_before+1 else 'CTR 하락: 검색 결과 표현·검색어 구성 점검 필요'
                hypotheses.append({'reason':f"{row['url']} {wording}",'confidence':'낮음',
                    'evidence':f"CTR {ctr_before*100:.2f}%→{ctr_after*100:.2f}%; 원인을 확정하지 않음"})
            actions.append({'url':row['url'],'action':'기여글의 검색 의도·내용·제목 점검',
                'reason':f"노출 변화 {row['impressionDelta']:+g}, 클릭 변화 {row['clickDelta']:+g} 확인",
                'expectedMetric':'노출·클릭·CTR·평균순위','verification':'완료일 전후 정확한 28일 글별 보고를 비교하고 검색어 구성을 함께 확인'})
        if current['impressions']!=previous['impressions']:
            hypotheses.append({'reason':'검색 수요·노출 대상·순위 변화가 노출 증감에 관여했을 가능성',
                'confidence':'낮음','evidence':'노출 변화는 확인됐으나 검색 수요와 검색어 구성을 분리한 인과 자료 없음'})
        if decomposition['identityVerified'] and abs(decomposition['ctrEffect'])>0:
            hypotheses.append({'reason':'검색어 구성·검색 결과 표현·순위 변화가 CTR 변화에 관여했을 가능성',
                'confidence':'낮음','evidence':'클릭/노출 비율 변화의 산술 기여만 확인됨'})
        unknowns.append('평균순위는 검색어 구성과 노출 가중치의 영향을 받으므로 순위 변화만으로 원인을 확정하지 않음')
        if not coverage['queryComparable']:
            unknowns.append('양기간에 같은 검색어·글로 매칭되는 근거 부족 · 미수집 또는 교집합 없음')
        if not coverage['pageComparable']:
            unknowns.append('양기간에 같은 글로 매칭되는 근거 부족 · 미수집 또는 교집합 없음')
        if any(r['current']['impressions']>=30 and r['current']['clicks']==0 for r in pages):
            actions.append({'action':'제목·검색 의도 점검','reason':'양기간 매칭 글 중 최근 30회 이상 노출·클릭 0회 확인',
                            'verification':'완료일 전후 28일 글별 노출·클릭·CTR을 다시 비교'})
        actions.append({'action':'기여글과 검색어의 실제 내용 점검','reason':'양기간에 관측된 글·검색어 행의 변화만 비교',
                        'verification':'개선 기록을 남기고 다음 수집에서 정확한 후속 기간 확인'})
    else:
        unknowns.append('정확하고 최신인 양기간 속성 합계가 부족하여 성장 원인 진단 보류')
    unknowns.append('행이 없다는 이유로 노출 0이나 신규 발행 글로 판단하지 않음')
    unknowns.append('날씨·시즌·광고 배치·문서 개선 효과는 별도 근거 없으면 미확인')
    return {'domain':domain,'facts':facts,'hypotheses':hypotheses,'unknowns':unknowns,
            'confidence':'측정 사실 확인·원인 가설 낮음' if valid else '미확인',
            'pageContributors':pages,'queryContributors':queries,'decomposition':decomposition,
            'coverage':coverage,'actions':actions}


def summary(now=None):
    now = now or datetime.now(timezone.utc)
    windows = periods(now)
    raw = read_json(DATA/'traffic.json')
    revenue = growth_revenue_summary(windows)
    domains, priorities = [], []
    indexing=read_json(DATA/'metrics.json')
    titles={url:title for r in indexing.get('sites',{}).values() for url,title in r.get('posts',{}).get('titles',{}).items()}
    for site in inventory():
        if site['platform'] != 'cf':
            continue
        domain = site['site_id']
        source = raw.get('sites',{}).get(domain,{}).get('google',{})
        pair, valid = {}, {}
        for name in ('current','previous'):
            report = source.get('periods',{}).get(name+'28',{})
            valid[name] = report_valid(report,windows[name],now)
            pair[name] = {**metric(report,valid[name]), **windows[name],
                'checkedAt': report.get('checkedAt'), 'revenue': revenue.get('domains',{}).get(domain,{}).get(name,{'amounts':{},'complete':False,'reason':'수익 미수집'})}
        comparable = all(valid.values())
        a,b = pair['current'],pair['previous']
        delta = {'impressionsPct':pct(a['impressions'],b['impressions']),
                 'clicksPct':pct(a['clicks'],b['clicks']),
                 'ctrPoints':(a['ctr']-b['ctr'])*100 if a['ctr'] is not None and b['ctr'] is not None else None,
                 'positionChange':b['position']-a['position'] if a['position'] is not None and b['position'] is not None else None,
                 'revenuePct':None}
        ar,br = a['revenue'],b['revenue']
        if ar.get('complete') and br.get('complete') and ar.get('sourceTimezone') == br.get('sourceTimezone'):
            currencies=set(ar.get('amounts',{}))&set(br.get('amounts',{}))
            if len(currencies)==1:
                currency=next(iter(currencies)); delta['revenuePct']=pct(ar['amounts'][currency],br['amounts'][currency])
        domains.append({'domain':domain,**pair,'comparable':comparable,'delta':delta,
            'status':('growing' if a['clicks']>b['clicks'] else 'declining' if a['clicks']<b['clicks'] else 'stable') if comparable else 'not_collected',
            'reason':None if comparable else '정확한 28일 비교창 미수집·기간 부족·오래된 자료'})
        report=source.get('periods',{}).get('current28',{})
        if valid['current'] and report.get('pagesStatus')=='collected':
            for row in report.get('pages',[]):
                imp,pos=row.get('impressions',0),row.get('position')
                if not measured_row(row) or not imp or not isinstance(pos,(int,float)) or not math.isfinite(pos) or not 11 <= pos <= 100:
                    continue
                priorities.append({'domain':domain,'url':row['page'],'kind':'ranking_opportunity',
                    'title':'실측 11~100위 노출 상승 후보','reason':'실제 노출·평균순위 11~100위 확인 · 소표본은 관찰 필요',
                    **{k:row.get(k) for k in ('impressions','clicks','ctr','position')},
                    'searchStart':report['start'],'searchEnd':report['end'],
                    'evidence':{'source':source.get('source'),'topRowsOnly':True,'lowSample':imp<10}})
                if imp>=30 and row.get('clicks')==0:
                    priorities.append({'domain':domain,'url':row['page'],'kind':'ctr_opportunity',
                        'title':'제목·검색 의도 점검','reason':'30회 이상 노출·클릭 0회 확인 · 개선 효과를 보장하지 않는 점검 기준',
                        **{k:row.get(k) for k in ('impressions','clicks','ctr','position')},
                        'searchStart':report['start'],'searchEnd':report['end'],'evidence':{'source':source.get('source'),'topRowsOnly':True}})
    groups={}
    for record in indexing.get('sites',{}).values():
        for row in record.get('google',{}).get('urls',[]):
            if row.get('indexed') is not False:
                continue
            try:
                age=(now-datetime.fromisoformat(row['checkedAt'])).total_seconds()
            except (KeyError,ValueError,TypeError):
                continue
            if not 0<=age<=26*3600:
                continue
            reason=row.get('coverageState') or '미색인 확인 · 세부 원인 미확인'
            groups[reason]=groups.get(reason,0)+1
    dedup = {}
    for row in priorities:
        key=(row['domain'],row['url'])
        if key in dedup:
            dedup[key]['kinds'].append(row['kind'])
            dedup[key]['reason'] += ' · '+row['reason']
        else:
            row['kinds']=[row['kind']]; row['title']=titles.get(row['url']) or row['url']; dedup[key]=row
    priorities=list(dedup.values())
    priorities.sort(key=lambda r:(r['impressions']<10,-r['impressions'],r['position']))
    from gsc_ui_state import state as ui_state
    diagnosis={'domains':[diagnose_domain(r['domain'],raw.get('sites',{}).get(r['domain'],{}).get('google',{}),windows,now) for r in domains],
               'collection':{**raw.get('growthCollection',{}),'uiAccount':ui_state('sj'),
                             'runtime':read_json(DATA/'metrics-runtime.json'), 'revenue':revenue.get('collection',{})}}
    for domain in diagnosis['domains']:
        domain['revenueDecomposition']=revenue.get('domains',{}).get(domain['domain'],{}).get('decomposition',{})
    return {'searchTimezone':windows['searchTimezone'],'periods':windows,'domains':domains,'priorities':priorities[:100],
            'diagnosis':diagnosis,
            'indexReasons':[{'reason':r,'count':c,'action':index_action(r)} for r,c in groups.items()],
            'records':[], 'checkedAt':now.isoformat(),
            'note':'검색 글별 행은 일부 관측값이며 속성 전체 합계와 다릅니다. AdSense 페이지뷰는 광고 측 페이지뷰입니다. 변화는 개선의 인과효과를 입증하지 않습니다.'}


def index_action(reason):
    from content import next_action
    return ' · '.join(next_action('not_indexed',None,{'coverageState':reason}))


def action_evidence(domain,url,start,end):
    source=read_json(DATA/'traffic.json').get('sites',{}).get(domain,{}).get('google',{})
    result={'start':start,'end':end,'impressions':None,'clicks':None,'ctr':None,'position':None,
            'status':'not_collected','reason':'정확한 글별 비교기간 미수집'}
    for report in source.get('periods',{}).values():
        if report.get('start')!=start or report.get('end')!=end or report.get('partialPeriod') or report.get('pagesStatus')!='collected':
            continue
        matches=[r for r in report.get('pages',[]) if r.get('page')==url]
        if len(matches)==1:
            result.update(metric(matches[0],True),status='collected',reason=None,checkedAt=report.get('checkedAt'))
    return result
