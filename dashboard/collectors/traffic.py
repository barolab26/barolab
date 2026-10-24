"""Read-only, domain-scoped GA4 and Search Console reports for the situation room.

Windows collector: python -B -X utf8 dashboard/traffic.py --collect
NAS reads dashboard/data/traffic.json. No credentials are stored in public assets.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from contextlib import closing
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse, unquote
from zoneinfo import ZoneInfo
from xml.etree import ElementTree

import requests

try:
    from .metrics import DATA, CONFIG, inventory, read_json, atomic_write, collector_lock, stamp, search_property
except ImportError:
    from metrics import DATA, CONFIG, inventory, read_json, atomic_write, collector_lock, stamp, search_property

SNAPSHOT = DATA / 'traffic.json'
METRICS = ['totalUsers', 'sessions', 'screenPageViews']
SEARCH_HOSTS = {'search.naver.com', 'm.search.naver.com'}


from common.ego_telemetry import observed_operation, action as ego_action


def classify_source(channel, source, medium):
    """Explicit Naver search referrals are search; blog/cafe links are external."""
    if channel == 'Paid Search':
        return 'paid'
    if channel == 'Organic Search' or (source.lower() in SEARCH_HOSTS and medium == 'referral'):
        return 'search'
    if channel == 'Direct':
        return 'direct'
    if channel in {'Referral', 'Organic Social', 'Email', 'Affiliates', 'AI Assistant', 'Organic Video'}:
        return 'external'
    if channel.startswith('Paid ') or channel in {'Display', 'Cross-network'}:
        return 'paid'
    return 'other'


SOURCE_ALIASES = {
    'naver_blog': {'naver_blog', 'naver-blog', 'blog.naver.com', 'm.blog.naver.com'},
    'naver_kin': {'naver_kin', 'naver-kin', 'naver_jisikin', 'naver-jisikin', 'kin.naver.com', 'm.kin.naver.com'},
    'naver_cafe': {'naver_cafe', 'naver-cafe', 'cafe.naver.com', 'm.cafe.naver.com'},
    'threads': {'threads', 'threads.net', 'www.threads.net', 'l.threads.net',
                'threads.com', 'www.threads.com', 'l.threads.com'},
}


def canonical_source(source):
    value = source.strip().lower() if isinstance(source, str) else ''
    for key, aliases in SOURCE_ALIASES.items():
        if value in aliases:
            return key
    return None


def external_exclusion(source, site_host):
    """Known local/self/internal sources are not qualified acquisition sessions."""
    import ipaddress
    value = source.strip().lower()
    try:
        host = urlparse(value if '://' in value else '//' + value).hostname or ''
    except ValueError:
        return 'internal'
    if host == 'localhost' or host.endswith('.localhost'):
        return 'local'
    try:
        address = ipaddress.ip_address(host)
        if address.is_loopback or address.is_private or address.is_link_local:
            return 'local'
    except ValueError:
        pass
    own = site_host.lower().removeprefix('www.')
    if host == own or host.endswith('.' + own):
        return 'self'
    if host == 'navercorp.com' or host.endswith('.navercorp.com'):
        return 'internal'
    return None


def aggregate_source_attribution(report, site_host, derived_at=None):
    """Preserve raw mix; qualify only reconciled, complete measured sessions.

    This excludes known operational sources, not every bot or operator visit.
    It is attribution grouping, never verified human traffic or causal lift.
    """
    channels = ('naver_blog', 'naver_kin', 'naver_cafe', 'threads', 'other')
    result = {'schema': 'source-attribution-v1', 'status': 'unknown',
              'canonicalExternalSessions': {key: None for key in channels},
              'qualifiedExternalSessions': None, 'excludedExternalSessions': None,
              'exclusions': {key: None for key in ('local', 'self', 'internal')},
              'naverExternalSessions': None,
              'qualificationMeaning': 'known local/self/internal sources excluded; not verified human traffic or incremental conversions'}
    if derived_at is not None:
        result['derivedAt'] = derived_at
    if not isinstance(report, dict) or not isinstance(site_host, str) or not re.fullmatch(r'[a-zA-Z0-9.-]+', site_host):
        result['reason'] = 'report or destination hostname unavailable'
        return result
    sources = report.get('sources')
    if (report.get('limited') or report.get('sourceLimited')
            or report.get('sourceReconciled') is not True or not isinstance(sources, list)
            or not isinstance(report.get('sessions'), int) or isinstance(report.get('sessions'), bool)):
        result['reason'] = 'source collection incomplete, limited or unreconciled'
        return result
    if any(not isinstance(row, dict) or not isinstance(row.get('source'), str) or not row['source'].strip()
           or not isinstance(row.get('sessions'), int) or isinstance(row.get('sessions'), bool)
           or row['sessions'] < 0 or row.get('kind') not in ('search', 'external', 'direct', 'paid', 'other')
           for row in sources):
        result['reason'] = 'source rows malformed; unknown is not zero'
        return result
    if sum(row['sessions'] for row in sources) != report['sessions']:
        result['reason'] = 'source session sum does not match reported total'
        return result
    counts = dict.fromkeys(channels, 0)
    exclusions = dict.fromkeys(('local', 'self', 'internal'), 0)
    for row in sources:
        if row['kind'] != 'external':
            continue
        exclusion = external_exclusion(row['source'], site_host)
        if exclusion:
            exclusions[exclusion] += row['sessions']
        else:
            counts[canonical_source(row['source']) or 'other'] += row['sessions']
    result.update(status='collected', canonicalExternalSessions=counts,
                  qualifiedExternalSessions=sum(counts.values()),
                  excludedExternalSessions=sum(exclusions.values()), exclusions=exclusions,
                  naverExternalSessions=sum(counts[k] for k in ('naver_blog', 'naver_kin', 'naver_cafe')))
    return result


def periods(now, timezone):
    today = now.astimezone(ZoneInfo(timezone)).date()
    yesterday = today - timedelta(days=1)
    return [{'name': key, 'startDate': (end - timedelta(days=days - 1)).isoformat(),
             'endDate': end.isoformat()}
            for key, end, days in [('today', today, 1), ('day', yesterday, 1),
                                   ('week', yesterday, 7), ('month', yesterday, 30)]]


def session(settings, readers, scope):
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    binding = readers.get(settings.get('analytics_reader'))
    if not binding:
        raise ValueError('통계 조회 계정 미설정')
    try:
        credentials = service_account.Credentials.from_service_account_file(binding['file'], scopes=[scope])
    except OSError as exc:
        exc.safe_operation = 'credential_file_read'
        raise
    if credentials.service_account_email != binding['email']:
        raise ValueError('통계 조회 계정 인증 파일 불일치')
    return AuthorizedSession(credentials)


def request(client, method, endpoint, body=None):
    r = client.request(method, endpoint, json=body, timeout=25)
    if not r.ok:
        if r.status_code == 403 and '/webmasters/v3/sites/' in endpoint:
            error = ValueError('GSC_PROPERTY_ACCESS_DENIED: 설정 속성 접근 거절 (HTTP 403; 사용자 권한 및 속성 범위 확인 필요)')
        else:
            error = ValueError(f'통계 원천 HTTP {r.status_code}')
        error.http_status = r.status_code
        raise error
    return r.json()


def ga_report(client, property_id, body, dimensions):
    data = request(client, 'POST', f'https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport', body)
    if [h['name'] for h in data.get('metricHeaders', [])] != [m['name'] for m in body['metrics']]:
        raise ValueError('GA4 지표 열 불일치')
    if [h['name'] for h in data.get('dimensionHeaders', [])] != dimensions:
        raise ValueError('GA4 분류 열 불일치')
    if data.get('metadata', {}).get('timeZone') != 'Asia/Seoul':
        raise ValueError('GA4 원천 시간대 불일치')
    count, length = int(data.get('rowCount', 0)), len(data.get('rows', []))
    # Multiple ranges can expand each dimension row into one row per dateRange.
    if count > int(body.get('limit', 10000)) or not count <= length <= count * len(body['dateRanges']):
        raise ValueError('GA4 보고서 행 잘림; 합계 미확정')
    meta = data.get('metadata', {})
    limited = any(meta.get(k) for k in ('subjectToThresholding', 'samplingMetadatas', 'dataLossFromOtherRow'))
    rows = []
    for row in data.get('rows', []):
        values = [v['value'] for v in row['metricValues']]
        if not all(re.fullmatch(r'\d+', v) for v in values):
            raise ValueError('GA4 사용자/세션 값 형식 불일치')
        rows.append(([v['value'] for v in row.get('dimensionValues', [])], list(map(int, values))))
    return rows, limited


def is_article_path(path):
    if not isinstance(path, str):
        return False
    p = path.strip()
    if not p or p in ('/', '/index.html') or p.startswith(('/admin', '/login', '/api/', '/media/', '/category/', '/tag/', '/search')):
        return False
    return p.startswith('/')


def clean_post_title(title, path):
    if isinstance(title, str) and title.strip() and title.strip() != '(not set)':
        cleaned = re.split(r'\s+\|\s+', title.strip())[0].strip()
        if cleaned:
            return cleaned
    return unquote(path.lstrip('/')).replace('-', ' ')


def collect_ga_pages(client, property_id, base, domain, ranges):
    page_rows, page_limited = ga_report(client, property_id,
        {**base, 'dateRanges': ranges, 'dimensions': [{'name': 'pagePath'}, {'name': 'pageTitle'}],
         'metrics': [{'name': 'sessions'}, {'name': 'screenPageViews'}, {'name': 'totalUsers'}], 'limit': 500},
        ['pagePath', 'pageTitle', 'dateRange'])
    grouped = {r['name']: {} for r in ranges}
    for (path, title, key), (sess, pv, usr) in page_rows:
        if key not in grouped or not is_article_path(path) or (sess <= 0 and pv <= 0):
            continue
        norm_path = '/' + path.strip().lstrip('/')
        bucket = grouped[key].setdefault(norm_path, {
            'domain': domain, 'path': norm_path,
            'url': f'https://www.{domain}{norm_path}',
            'title': clean_post_title(title, norm_path),
            'sessions': 0, 'pageViews': 0, 'users': 0
        })
        bucket['sessions'] += sess
        bucket['pageViews'] += pv
        bucket['users'] = max(bucket['users'], usr)
        if (not bucket['title'] or bucket['title'] == unquote(norm_path.lstrip('/')).replace('-', ' ')) and title and title != '(not set)':
            bucket['title'] = clean_post_title(title, norm_path)
    return {
        k: sorted(v.values(), key=lambda x: (-x['pageViews'], -x['sessions'], -x['users'], x['path']))[:25]
        for k, v in grouped.items()
    }, page_limited


def collect_growth_pages(client, property_id, base, domain, now):
    """Exact completed KST week, without top-N or page-title session double counts."""
    end = now.astimezone(ZoneInfo('Asia/Seoul')).date() - timedelta(days=1)
    start = end - timedelta(days=6)
    rows, limited = ga_report(client, property_id, {
        **base, 'dateRanges': [{'startDate': start.isoformat(), 'endDate': end.isoformat()}],
        'dimensions': [{'name': 'pagePath'}],
        'metrics': [{'name': 'sessions'}, {'name': 'screenPageViews'}], 'limit': 100000}, ['pagePath'])
    pages, seen = [], set()
    for (path,), (sessions, views) in rows:
        if not is_article_path(path):
            continue
        if path in seen:
            raise ValueError('GA4 page duplicate')
        seen.add(path)
        pages.append({'domain': domain, 'url': f'https://www.{domain}{path}',
                      'sessions': sessions, 'pageViews': views})
    return {'start': start.isoformat(), 'end': end.isoformat(), 'timezone': 'Asia/Seoul',
            'checkedAt': stamp(), 'complete': not limited, 'status': 'partial' if limited else 'collected',
            'source': 'GA4 Data API', 'fullEnumeration': not limited, 'pages': pages}


@observed_operation('metrics', 'traffic-collection')
def collect_ga(site, settings, readers, now):
    domain = site['site_id']
    ranges = periods(now, 'Asia/Seoul')
    base = {'dateRanges': ranges, 'dimensionFilter': {'filter': {'fieldName': 'hostName',
             'inListFilter': {'values': [domain, 'www.' + domain], 'caseSensitive': False}}},
             'keepEmptyRows': True, 'limit': 10000}
    with session(settings, readers, 'https://www.googleapis.com/auth/analytics.readonly') as client:
        # No date/host dimensions: root + www and returning users deduplicated per period.
        rows, limited = ga_report(client, settings['ga4_property'],
                                 {**base, 'metrics': [{'name': m} for m in METRICS]}, ['dateRange'])
        reports = {r['name']: {'start': r['startDate'], 'end': r['endDate'],
                              'users': 0, 'sessions': 0, 'pageViews': 0,
                              'provisional': True, 'limited': limited} for r in ranges}
        seen = set()
        for keys, values in rows:
            key = keys[0]
            if key not in reports or key in seen:
                raise ValueError('GA4 기간 합계 중복/불일치')
            seen.add(key)
            reports[key].update(zip(('users', 'sessions', 'pageViews'), values))
        dimensions = ['sessionDefaultChannelGroup', 'sessionSource', 'sessionMedium']
        rows, source_limited = ga_report(client, settings['ga4_property'],
            {**base, 'dimensions': [{'name': d} for d in dimensions], 'metrics': [{'name': 'sessions'}]},
            dimensions + ['dateRange'])
        sources = {r['name']: [] for r in ranges}
        for keys, values in rows:
            channel, origin, medium, key = keys
            if key not in sources:
                raise ValueError('GA4 유입 보고서 기간 불일치')
            sources[key].append({'channel': channel, 'source': origin, 'medium': medium,
                                 'kind': classify_source(channel, origin, medium), 'sessions': values[0]})
        try:
            pages_by_period, _ = collect_ga_pages(client, settings['ga4_property'], base, domain, ranges)
        except Exception:
            pages_by_period = {r['name']: [] for r in ranges}
        for key, report in reports.items():
            report['sources'] = sorted(sources[key], key=lambda r: -r['sessions'])
            report['pages'] = pages_by_period.get(key, [])
            report['mix'] = {k: sum(r['sessions'] for r in sources[key] if r['kind'] == k)
                             for k in ('search', 'external', 'direct', 'paid', 'other')}
            report['sourceLimited'] = source_limited
            report['sourceReconciled'] = sum(report['mix'].values()) == report['sessions']
            report['sourceAttribution'] = aggregate_source_attribution(report, domain, derived_at=stamp())
            report['naverExternal'] = report['sourceAttribution']['naverExternalSessions']
        try:
            growth_pages = collect_growth_pages(client, settings['ga4_property'], base, domain, now)
        except Exception:
            growth_pages = {'complete': False, 'status': 'not_collected', 'pages': [],
                            'attemptedAt': stamp(), 'reason': 'Exact seven-day page report unavailable'}
        daily_rows, daily_limited = ga_report(client, settings['ga4_property'],
            {**base, 'dateRanges': [ranges[-1]], 'dimensions': [{'name': 'date'}],
             'metrics': [{'name': m} for m in METRICS]}, ['date'])
        daily = [{'day': datetime.strptime(keys[0], '%Y%m%d').date().isoformat(),
                  **dict(zip(('users', 'sessions', 'pageViews'), values))} for keys, values in daily_rows]
    return {'status': 'partial' if limited or source_limited or daily_limited else 'collected',
            'checkedAt': stamp(), 'timezone': 'Asia/Seoul', 'source': 'GA4 Data API',
            'property': settings['ga4_property'], 'periods': reports, 'daily': sorted(daily, key=lambda r: r['day']),
            'pagePerformance': growth_pages,
            'note': '측정된 사용자 · 기간 내 중복 제거 · 날짜/도메인별 사용자를 합산하지 않음'}


def action_windows(now, snapshot=None):
    """Completed shared actions enqueue exact before/after windows, without submissions."""
    import sqlite3
    path = DATA / 'growth.sqlite3'
    if not path.exists():
        return {}
    end = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
    try:
        with closing(sqlite3.connect(path)) as db:
            rows = db.execute("SELECT id,domain,completed_at FROM improvement_actions WHERE status='done' AND completed_at IS NOT NULL ORDER BY completed_at,id").fetchall()
    except sqlite3.Error:
        return {}
    windows = {}
    for ident, domain, completed in rows:
        try:
            day = datetime.fromisoformat(completed).date()
        except (ValueError,TypeError):
            continue
        for label, start, last in [('before',day-timedelta(days=28),day-timedelta(days=1)),
                                   ('after',day+timedelta(days=1),day+timedelta(days=28))]:
            if last <= end:
                windows['action_'+str(ident)+'_'+label] = {'start':start.isoformat(),'end':last.isoformat(),'domain':domain}
    old = (snapshot if snapshot is not None else read_json(SNAPSHOT)).get('sites', {})
    pending = []
    for key, window in windows.items():
        report = old.get(window['domain'], {}).get('google', {}).get('periods', {}).get(key, {})
        if cached_search_period(window['domain'],key,window,now,snapshot):
            continue
        pending.append((report.get('checkedAt') or '',key,window))
    selected, grouped = {}, {}
    for _,key,window in sorted(pending):
        grouped.setdefault(window['domain'],[]).append((key,window))
    cursors=(snapshot if snapshot is not None else read_json(SNAPSHOT)).get('growthActionCursor',{})
    for domain, candidates in grouped.items():
        cursor=int(cursors.get(domain,0)) % len(candidates)
        count=min(2,len(candidates))
        for offset in range(count):
            key,window=candidates[(cursor+offset)%len(candidates)]
            selected[key]={**window,'nextCursor':(cursor+count)%len(candidates)}
    return selected


def search_windows(now):
    end = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
    return {key: {'start': (end - timedelta(days=offset + days - 1)).isoformat(),
                  'end': (end - timedelta(days=offset)).isoformat()}
            for key, days, offset in [('day',1,0),('week',7,0),('month',30,0),
                                     ('current28',28,0),('previous28',28,28)]}


def cached_search_period(domain, key, window, now, snapshot=None):
    if key in ('day', 'week', 'month'):
        return None
    old = (snapshot if snapshot is not None else read_json(SNAPSHOT)).get('sites', {}).get(domain, {}).get('google', {})
    report = old.get('periods', {}).get(key, {})
    try:
        age = (now - datetime.fromisoformat(report['checkedAt'])).total_seconds()
    except (KeyError, ValueError, TypeError):
        return None
    has_queries = key not in ('current28', 'previous28') or report.get('queriesStatus') == 'collected'
    if 0 <= age < 43200 and has_queries and report.get('start') == window['start'] and report.get('end') == window['end'] and not report.get('partialPeriod'):
        return report
    return None


def saved_action_periods(domain, snapshot=None):
    reports=(snapshot if snapshot is not None else read_json(SNAPSHOT)).get('sites',{}).get(domain,{}).get('google',{}).get('periods',{})
    return {key:value for key,value in reports.items() if key.startswith('action_')}


def growth_browser_targets(sites, now, maximum=4):
    old=read_json(SNAPSHOT)
    windows=search_windows(now)
    due=[s['site_id'] for s in sites if any(not cached_search_period(s['site_id'],k,windows[k],now)
                                          for k in ('current28','previous28'))]
    if not due:
        return set(), old.get('growthCollection',{}).get('cursor',0)
    cursor=int(old.get('growthCollection',{}).get('cursor',0)) % len(due)
    count=min(maximum,len(due))
    return {due[(cursor+i)%len(due)] for i in range(count)}, (cursor+count)%len(due)


def parse_query_cells(rows,page_url=None):
    output=[]
    for cells in rows:
        if not cells or cells[0]=='데이터 없음':
            continue
        if len(cells)!=5:
            raise ValueError('Google 검색어 표 구성 미확인')
        query,c,i,_ctr,pos=cells
        c,i,pos=int(c.replace(',','')),int(i.replace(',','')),float(pos.replace(',',''))
        if c<0 or i<0 or not math.isfinite(pos) or pos<0:
            raise ValueError('Google 검색어 수치 불일치')
        output.append({'query':query,'page':page_url,'clicks':c,'impressions':i,
                       'ctr':c/i if i else None,'position':pos})
    return output


def collect_linked_page_queries(page,record,domain,now):
    """Observe a real page row, use its GSC filter, then verify both exact windows."""
    from gsc_ui_state import check_response,check_text,mark_success
    current=record.get('periods',{}).get('current28',{})
    previous=record.get('periods',{}).get('previous28',{})
    windows=search_windows(now)
    if any(r.get('pagesStatus')!='collected' or r.get('partialPeriod') or
           any(r.get(k)!=windows[name][k] for k in ('start','end'))
           for name,r in [('current28',current),('previous28',previous)]):
        return {'status':'not_collected','reason':'정확한 양기간 글별 보고 부족'}
    older={r['page']:r for r in previous.get('pages',[])}
    candidates=[r for r in current.get('pages',[]) if urlparse(r['page']).path not in ('','/')]
    if not candidates:
        return {'status':'not_collected','reason':'조회 가능한 본문 글 행 없음'}
    candidates.sort(key=lambda r:(-abs(r['impressions']-older.get(r['page'],{}).get('impressions',r['impressions'])), -r['impressions']))
    target=candidates[0]['page']
    url=('https://search.google.com/search-console/performance/search-analytics?resource_id='
         +quote(record['property'],safe='')+'&start_date='+windows['current28']['start'].replace('-','')
         +'&end_date='+windows['current28']['end'].replace('-',''))
    with ego_action('navigate', 'metrics-browser'):
        response=page.goto(url,wait_until='domcontentloaded',timeout=15000)
    check_response('sj',response);check_text('sj',page.locator('body').inner_text())
    with ego_action('click', 'metrics-browser'):
        page.get_by_role('tab',name='페이지',exact=True).click(timeout=5000)
    table=page.locator('table:visible').first
    table.locator('tr').nth(1).wait_for(timeout=5000)
    rows=table.locator('tr').all()
    matches=[row for row in rows[1:] if row.locator('td').count() and row.locator('td').first.inner_text().split()[0]==target]
    if len(matches)!=1:
        return {'status':'not_collected','reason':'실제 화면에서 목표 글 행을 확인하지 못함'}
    with ego_action('click', 'metrics-browser'):
        matches[0].locator('td').first.click(timeout=5000)
    page.wait_for_function('target => decodeURIComponent(location.href).includes(target)',arg=target,timeout=5000)
    filtered=page.url
    result={'status':'collected','url':target,'source':'Google owner UI exact page filter','periods':{}}
    for key in ('current28','previous28'):
        parsed=urlparse(filtered);params=parse_qs(parsed.query)
        params.update(start_date=[windows[key]['start'].replace('-','')],end_date=[windows[key]['end'].replace('-','')])
        address=urlunparse(parsed._replace(query=urlencode(params,doseq=True)))
        with ego_action('navigate', 'metrics-browser'):
            response=page.goto(address,wait_until='domcontentloaded',timeout=15000)
        check_response('sj',response);check_text('sj',page.locator('body').inner_text())
        actual=parse_qs(urlparse(page.url).query)
        if actual.get('resource_id')!=[record['property']] or not any(target in unquote(v) for k,values in actual.items() if k not in ('resource_id','start_date','end_date') for v in values):
            raise ValueError('글별 검색어 필터 실제 URL 불일치')
        start,end=[datetime.fromisoformat(windows[key][k]).date() for k in ('start','end')]
        caption=f'{start.year}년 {start.month}월 {start.day}일부터 {end.year}년 {end.month}월 {end.day}일까지의 총 클릭수'
        page.wait_for_function('text=>document.body.innerText.includes(text)',arg=caption,timeout=7000)
        identity=page.locator('[aria-label*="Google 계정"]').get_attribute('aria-label') or ''
        if record.get('accountEmail') not in identity:
            raise ValueError('글별 검색어 계정 불일치')
        tabs=page.get_by_role('tab',name='검색어',exact=True)
        if tabs.count()!=1:
            raise ValueError('실제 검색어 탭 미확인')
        with ego_action('click', 'metrics-browser'):
            tabs.click(timeout=5000)
        page.wait_for_function("() => Array.from(document.querySelectorAll('table')).some(t=>t.getClientRects().length&&t.innerText.includes('인기 검색어')&&(t.querySelectorAll('tr').length>1||document.body.innerText.includes('데이터 없음')))",timeout=7000)
        rows=page.locator('table:visible').first.locator('tr').evaluate_all('rows=>rows.slice(1).map(r=>Array.from(r.querySelectorAll("td")).map(c=>c.innerText))')
        result['periods'][key]={**windows[key],'queries':parse_query_cells(rows,target),
                               'checkedAt':stamp(),'queriesStatus':'collected','filterVerified':True,'topRowsOnly':True}
        mark_success('sj')
    return result


@observed_operation('metrics', 'traffic-collection')
def collect_search(site, settings, readers, now, snapshot=None):
    if snapshot is None:
        try:
            snapshot = read_json(SNAPSHOT)
        except OSError as exc:
            exc.safe_operation = 'snapshot_read'
            raise
    property_id = settings.get('search_property')
    if not property_id:
        return {'status': 'not_connected', 'reason': '실제 www 주소의 Search Console 조회 권한 미연결'}
    domain = site['site_id']
    property_id = search_property(site, settings)
    end = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
    result = {'status': 'collected', 'checkedAt': stamp(), 'timezone': 'America/Los_Angeles',
              'source': 'Google Search Console', 'property': property_id, 'periods': saved_action_periods(domain,snapshot)}
    # Domain properties can contain other subdomains; exact root/www page filter isolates inventory.
    page_filter = {'groupType': 'and', 'filters': [{'dimension': 'page', 'operator': 'includingRegex',
                    'expression': r'^https://(www\.)?' + re.escape(domain) + r'/'}]}
    with session(settings, readers, 'https://www.googleapis.com/auth/webmasters.readonly') as client:
        endpoint = 'https://www.googleapis.com/webmasters/v3/sites/' + quote(property_id, safe='') + '/searchAnalytics/query'
        for key, window in {**search_windows(now), **action_windows(now,snapshot)}.items():
            if window.get('domain', domain) != domain:
                continue
            start = datetime.fromisoformat(window['start']).date()
            end = datetime.fromisoformat(window['end']).date()
            cached = cached_search_period(domain, key, window, now,snapshot)
            if cached:
                result['periods'][key] = cached
                continue
            body = {'startDate': start.isoformat(), 'endDate': end.isoformat(),
                    'type': 'web', 'dataState': 'final', 'dimensionFilterGroups': [page_filter]}
            totals = request(client, 'POST', endpoint, body).get('rows', [])
            if len(totals) > 1:
                raise ValueError('검색 합계 응답 중복')
            total = totals[0] if totals else {'clicks': 0, 'impressions': 0, 'ctr': None, 'position': None}
            rows = [] if key.startswith('action_') else request(client, 'POST', endpoint, {**body, 'dimensions': ['query', 'page'], 'rowLimit': 1000}).get('rows', [])
            queries = []
            for row in rows:
                query, page = row['keys']
                if urlparse(page).hostname not in {domain, 'www.' + domain}:
                    raise ValueError('검색어 보고서에 다른 도메인 포함')
                queries.append({'query': query, 'page': page, **{k: row[k] for k in ('clicks', 'impressions', 'ctr', 'position')}})
            for row in [total] + queries:
                if any(v is not None and (not math.isfinite(v) or v < 0) for v in (row.get(k) for k in ('clicks', 'impressions', 'ctr', 'position'))):
                    raise ValueError('검색 보고서 수치 불일치')
            result['periods'][key] = {'start': start.isoformat(), 'end': end.isoformat(),
                'checkedAt': stamp(), **{k: total[k] for k in ('clicks', 'impressions', 'ctr', 'position')},
                'queries': queries, 'queriesStatus': 'collected', 'queriesScope': 'page_query',
                'topRowsOnly': True, 'note': '검색어/URL 상위 행 · 비공개 검색어 제외 · 평균 게재순위'}
            if key in ('month', 'current28', 'previous28') or key.startswith('action_'):
                try:
                    page_rows = request(client, 'POST', endpoint, {**body, 'dimensions': ['page'], 'rowLimit': 1000}).get('rows', [])
                    pages = []
                    for row in page_rows:
                        page = row['keys'][0]
                        if urlparse(page).hostname not in {domain, 'www.' + domain}:
                            raise ValueError('페이지 보고서에 다른 도메인 포함')
                        values = {k: row[k] for k in ('clicks', 'impressions', 'ctr', 'position')}
                        if any(v is not None and (not math.isfinite(v) or v < 0) for v in values.values()):
                            raise ValueError('페이지 보고서 수치 불일치')
                        pages.append({'page': page, **values})
                    result['periods'][key]['pages'] = pages
                    result['periods'][key]['pagesStatus'] = 'collected'
                except Exception as exc:
                    result['periods'][key]['pagesStatus'] = 'error'
                    result['periods'][key]['pagesReason'] = str(exc) if type(exc) is ValueError else f'페이지 보고서 조회 실패 ({type(exc).__name__})'
    return result


@observed_operation('metrics', 'traffic-collection')
def collect_browser_search(sites, config, now, on_record=None):
    from gsc_ui_state import paused,state
    if paused('sj',now):
        return {s['site_id']:{'status':'backoff','reason':state('sj').get('reason'),
                             'nextRetryAt':state('sj').get('nextRetryAt')} for s in sites}
    with collector_lock(DATA / 'gsc-ui-sj.lock') as acquired:
        if not acquired:
            return {s['site_id']: {'status': 'error', 'reason': 'SJ 소유자 브라우저 검사 진행 중 · 검색 실적은 다음 수집에서 재시도'} for s in sites}
        return _collect_browser_search(sites, config, now, on_record)


def _collect_browser_search(sites, config, now, on_record=None):
    """Read SJ owner reports without granting the API reader more permissions."""
    from playwright.sync_api import sync_playwright
    from gsc_ui_state import check_response,check_text,mark_success
    from common.browser_session import PageScope, reusable_search_console_page
    end = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
    account = config.get('gsc_accounts', {}).get('sj', {})
    output = {}
    growth_targets, _ = growth_browser_targets(sites,now)
    due_linked=[s['site_id'] for s in sites]
    due_linked.sort(key=lambda domain:(domain!='must-good.com',domain))
    linked_cursor=int(read_json(SNAPSHOT).get('growthCollection',{}).get('pageCursor',0))
    linked_domain=due_linked[linked_cursor%len(due_linked)] if due_linked else None
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{account['cdp']}", timeout=10000)
        original_page=None
        for candidate in browser.contexts[0].pages:
            try:
                if candidate.evaluate('document.hasFocus()'):
                    original_page=candidate
                    break
            except Exception:
                pass
        scope = PageScope()
        page = scope.acquire(browser.contexts[0], reusable_search_console_page)
        try:
            for site in sites:
                domain = site['site_id']
                if domain not in account.get('sites', []):
                    continue
                record = {'status': 'collected', 'checkedAt': stamp(), 'timezone': 'America/Los_Angeles',
                          'source': 'Google Search Console UI', 'property': site['url'].rstrip('/') + '/',
                          'accountEmail':account['email'],'periods': saved_action_periods(domain)}
                try:
                    for key, window in {**search_windows(now), **action_windows(now)}.items():
                        if window.get('domain', domain) != domain:
                            continue
                        start = datetime.fromisoformat(window['start']).date()
                        end = datetime.fromisoformat(window['end']).date()
                        cached = cached_search_period(domain, key, window, now)
                        if cached:
                            record['periods'][key] = cached
                            continue
                        if key in ('current28','previous28') and domain not in growth_targets:
                            saved=read_json(SNAPSHOT).get('sites',{}).get(domain,{}).get('google',{}).get('periods',{}).get(key)
                            if saved:
                                record['periods'][key]=saved
                            continue
                        url = ('https://search.google.com/search-console/performance/search-analytics?resource_id='
                               + quote(record['property'], safe='') + '&start_date=' + start.strftime('%Y%m%d')
                               + '&end_date=' + end.strftime('%Y%m%d'))
                        with ego_action('navigate', 'metrics-browser'):
                            response=page.goto(url, wait_until='domcontentloaded', timeout=25000)
                        check_response('sj',response)
                        check_text('sj',page.locator('body').inner_text())
                        caption = f'{end.year}년 {end.month}월 {end.day}일까지의 총 클릭수'
                        page.wait_for_function("text => document.body.innerText.includes(text)", arg=caption, timeout=10000)
                        match = re.search(r'(\d{4})년 (\d{1,2})월 (\d{1,2})일부터 (\d{4})년 (\d{1,2})월 (\d{1,2})일까지의 총 클릭수', page.locator('body').inner_text())
                        if not match:
                            raise ValueError('Google 보고서 실제 날짜 범위 미확인')
                        actual_start = datetime(*map(int, match.groups()[:3])).date()
                        actual_end = datetime(*map(int, match.groups()[3:])).date()
                        if actual_end != end or not start <= actual_start <= end:
                            raise ValueError('Google 보고서 날짜 범위 불일치')
                        identity = page.locator('[aria-label*="Google 계정"]').get_attribute('aria-label') or ''
                        if account['email'] not in identity:
                            raise ValueError('Google 보고서 로그인 계정 불일치')
                        if parse_qs(urlparse(page.url).query).get('resource_id') != [record['property']]:
                            raise ValueError('Google 보고서 속성 주소 불일치')
                        # The report DOM includes all five metric columns, even when a view hides CTR/position.
                        page.wait_for_function("() => document.body.innerText.includes('데이터 없음') || Array.from(document.querySelectorAll('table')).some(t=>t.querySelectorAll('tr').length>1)", timeout=7000)
                        def value(title):
                            node = page.get_by_text(title, exact=True).locator('..').locator('..')
                            return node.locator('div[title]').last.get_attribute('title')
                        clicks, impressions = [int(value(t).replace(',', '')) for t in ('총 클릭수', '총 노출수')]
                        position = float(value('평균 게재순위').replace(',', '')) if impressions else None
                        rows = page.locator('table').first.locator('tr').evaluate_all("""rows => rows.slice(1).map(r => Array.from(r.querySelectorAll('td')).map(c=>c.innerText))""")
                        queries = []
                        for cells in rows:
                            if not cells or cells[0] == '데이터 없음':
                                continue
                            if len(cells) != 5:
                                raise ValueError('Google 검색어 표의 열 구성이 바뀜')
                            query, c, i, _ctr, pos = cells
                            c, i, pos = int(c.replace(',', '')), int(i.replace(',', '')), float(pos.replace(',', ''))
                            queries.append({'query': query, 'page': None, 'clicks': c, 'impressions': i,
                                            'ctr': c / i if i else None, 'position': pos})
                        record['periods'][key] = {'start': actual_start.isoformat(), 'end': end.isoformat(),
                            'checkedAt': stamp(), 'requestedStart': start.isoformat(), 'partialPeriod': actual_start != start,
                            'clicks': clicks, 'impressions': impressions, 'ctr': clicks / impressions if impressions else None,
                            'position': position, 'queries': queries, 'queriesStatus': 'collected',
                            'queriesScope': 'domain_query', 'topRowsOnly': True,
                            'note': '소유자 화면의 공개 검색어 · 페이지 연결은 미제공 · 평균 게재순위'}
                        if key in ('month', 'current28', 'previous28') or key.startswith('action_'):
                            try:
                                with ego_action('click', 'metrics-browser'):
                                    page.get_by_role('tab', name='페이지', exact=True).click()
                                page.wait_for_function("""() => Array.from(document.querySelectorAll('table')).some(t =>
                                    t.getClientRects().length && t.innerText.includes('인기 페이지') &&
                                    (t.querySelectorAll('tr').length > 1 || document.body.innerText.includes('데이터 없음')))""", timeout=10000)
                                rows = page.locator('table:visible').first.locator('tr').evaluate_all("rows => rows.slice(1).map(r => Array.from(r.querySelectorAll('td')).map(c=>c.innerText))")
                                pages = []
                                for cells in rows:
                                    if not cells or cells[0] == '데이터 없음':
                                        continue
                                    if len(cells) != 5 or urlparse(cells[0]).hostname not in {domain, 'www.' + domain}:
                                        raise ValueError('Google 페이지 실적 표 형식 또는 도메인 불일치')
                                    address, c, i, _ctr, pos = cells
                                    address = address.split()[0]
                                    c, i, pos = int(c.replace(',', '')), int(i.replace(',', '')), float(pos.replace(',', ''))
                                    if c < 0 or i < 0 or not math.isfinite(pos) or pos < 0:
                                        raise ValueError('Google 페이지 실적 수치 불일치')
                                    pages.append({'page': address, 'clicks': c, 'impressions': i,
                                                  'ctr': c / i if i else None, 'position': pos})
                                record['periods'][key].update(pages=pages, pagesStatus='collected')
                            except Exception as exc:
                                record['periods'][key].update(pagesStatus='error', pagesReason=f'글별 실적 미수집 ({type(exc).__name__})')
                        mark_success('sj')
                        if on_record:
                            on_record(domain,record)
                    record['checkedAt'] = stamp()
                    record['linkedPageQueries']=read_json(SNAPSHOT).get('sites',{}).get(domain,{}).get('google',{}).get('linkedPageQueries',{})
                    if domain==linked_domain:
                        try:
                            record['linkedPageQueries']=collect_linked_page_queries(page,record,domain,now)
                            record['linkedPageQueries']['attemptAt']=stamp()
                        except Exception as exc:
                            record['linkedPageQueries']={**record.get('linkedPageQueries',{}),'status':'error','reason':str(exc) if isinstance(exc,ValueError) else '글별 검색어 조회 실패','attemptAt':stamp()}
                            from gsc_ui_state import paused
                            if paused('sj'):
                                raise
                        if on_record:
                            on_record(domain,record)
                    output[domain] = record
                except Exception as exc:
                    output[domain] = {**record,'status': 'error', 'reason': str(exc) if type(exc) is ValueError else f'Google 소유자 보고서 조회 실패 ({key}, {type(exc).__name__})'}
                    from gsc_ui_state import paused,state
                    if paused('sj'):
                        output[domain].update(status='backoff',nextRetryAt=state('sj').get('nextRetryAt'))
                        break
                    if type(exc) is ValueError and '계정 불일치' in str(exc):
                        break
        finally:
            if scope.owns(page):
                page.close()
            if original_page and not original_page.is_closed():
                original_page.bring_to_front()
    return output


def parse_naver_visitors(body):
    if len(body) > 65536 or b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('네이버 방문자 응답 형식 불일치')
    root = ElementTree.fromstring(body)
    if root.tag != 'visitorcnts':
        raise ValueError('네이버 방문자 XML 미확인')
    days = {}
    for row in root.findall('visitorcnt'):
        day, count = row.get('id', ''), row.get('cnt', '')
        if not re.fullmatch(r'\d{8}', day) or not re.fullmatch(r'\d{1,12}', count):
            raise ValueError('네이버 날짜/방문자 값 불일치')
        day = datetime.strptime(day, '%Y%m%d').date().isoformat()
        if day in days:
            raise ValueError('네이버 방문자 날짜 중복')
        days[day] = int(count)
    return days


@observed_operation('metrics', 'traffic-collection')
def collect_naver_visitors():
    sites = [s for s in inventory() if s['platform'] == 'naver']
    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    def one(site):
        blog = urlparse(site['url']).path.strip('/')
        record = {'site': site, 'timezone': 'Asia/Seoul', 'source': '네이버 공개 방문자 카운터',
                  'date': today, 'checkedAt': stamp()}
        try:
            if not re.fullmatch(r'[a-zA-Z0-9_-]{2,30}', blog):
                raise ValueError('네이버 블로그 ID 미확인')
            response = requests.get('https://blog.naver.com/NVisitorgp4Ajax.naver', params={'blogId': blog},
                headers={'User-Agent': 'Mozilla/5.0', 'Referer': site['url']}, timeout=8)
            if response.status_code != 200:
                raise ValueError(f'네이버 방문자 원천 HTTP {response.status_code}')
            days = parse_naver_visitors(response.content)
            if today not in days:
                raise ValueError('네이버 오늘 방문자 값 미제공')
            record.update(status='collected', days=days)
        except Exception as exc:
            record.update(status='error', days={}, reason=str(exc) if type(exc) is ValueError else '네이버 공개 방문자 조회 실패')
        return record
    with ThreadPoolExecutor(max_workers=3) as workers:
        return {r['site']['site_id']: r for r in workers.map(one, sites)}


def bing_request(method, site_url, credentials, client=requests):
    """Read-only JSON/HTTP; never log the credential-bearing request URL/body."""
    if method not in ('GetQueryStats', 'GetRankAndTrafficStats', 'GetUserSites'):
        raise ValueError('BING_METHOD_NOT_READ_ONLY')
    params, headers = ({'siteUrl': site_url} if site_url else {}), {}
    if credentials.get('token'):
        headers['Authorization'] = 'Bearer ' + credentials['token']
    else:
        params['apikey'] = credentials['key']
    try:
        response = client.get('https://ssl.bing.com/webmaster/api.svc/json/' + method,
                              params=params, headers=headers, timeout=25, allow_redirects=False)
        if response.status_code != 200:
            return None, 'BING_HTTP_' + str(response.status_code)
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('d'), list):
            return None, 'BING_RESPONSE_INVALID'
        return payload['d'], None
    except Exception:
        return None, 'BING_TRANSPORT_OR_JSON_ERROR'


def bing_sites(credentials, client=requests):
    rows, error = bing_request('GetUserSites', None, credentials, client)
    if error:
        return None, error
    # The API also returns verification tokens. Never retain the raw response.
    return [{'url': row['Url'], 'verified': row.get('IsVerified') is True}
            for row in rows if isinstance(row, dict) and isinstance(row.get('Url'), str)], None


def _configured_bing_site(site_url):
    allowed = {s['url'] for s in inventory() if s.get('platform') == 'cf'}
    if site_url not in allowed or not site_url.startswith('https://www.'):
        raise ValueError('BING_SITE_OUTSIDE_CANONICAL_CF_INVENTORY')


def bing_site_registration(method, site_url, credentials, *, authorized=False, client=requests):
    """Explicitly authorized AddSite/VerifySite only; never general API dispatch."""
    if not authorized:
        raise ValueError('BING_SITE_REGISTRATION_AUTHORIZATION_REQUIRED')
    if method not in ('AddSite', 'VerifySite'):
        raise ValueError('BING_SITE_REGISTRATION_METHOD_NOT_ALLOWED')
    _configured_bing_site(site_url)
    params, headers = {}, {}
    if credentials.get('token'):
        headers['Authorization'] = 'Bearer ' + credentials['token']
    elif credentials.get('key'):
        params['apikey'] = credentials['key']
    else:
        return {'status': 'credential_missing', 'verified': False}
    try:
        response = client.post('https://ssl.bing.com/webmaster/api.svc/json/' + method,
            params=params, headers=headers, json={'siteUrl': site_url}, timeout=25,
            allow_redirects=False)
        if response.status_code != 200:
            return {'status': 'request_rejected', 'httpStatus': response.status_code, 'verified': False}
        payload = response.json()
        if not isinstance(payload, dict) or 'd' not in payload:
            return {'status': 'invalid_response', 'verified': False}
        value = payload['d']
        if method == 'AddSite':
            return {'status': 'added' if value is None else 'invalid_response',
                    'httpStatus': 200, 'verified': False}
        if type(value) is not bool:
            return {'status': 'invalid_response', 'verified': False}
        return {'status': 'verified' if value else 'verification_pending',
                'httpStatus': 200, 'verified': value}
    except Exception:
        return {'status': 'request_unconfirmed', 'verified': False}


def bing_verification_material(site_url, credentials, client=requests):
    """Return only one configured site's codes IN MEMORY; caller must not log/save."""
    _configured_bing_site(site_url)
    rows, error = bing_request('GetUserSites', None, credentials, client)
    if error:
        return None, error
    row = next((r for r in rows if isinstance(r, dict) and r.get('Url') == site_url), None)
    if row is None:
        return None, 'BING_SITE_NOT_REGISTERED'
    return {'verified': row.get('IsVerified') is True,
            'authenticationCode': row.get('AuthenticationCode'),
            'dnsVerificationCode': row.get('DnsVerificationCode')}, None


def ensure_bing_verification_cname(domain, dns_name, zone_id, headers, *, authorized=False, client=requests):
    """Add or reuse the one Bing proof CNAME; never edit/delete another record."""
    if not authorized:
        raise ValueError('BING_DNS_AUTHORIZATION_REQUIRED')
    _configured_bing_site('https://www.' + domain + '/')
    name = str(dns_name or '').lower().rstrip('.')
    if not re.fullmatch(r'[a-f0-9]{16,64}\.' + re.escape(domain), name):
        raise ValueError('BING_DNS_PROOF_OUTSIDE_EXACT_DOMAIN')
    endpoint = 'https://api.cloudflare.com/client/v4/zones/' + zone_id
    def checked(response):
        if response.status_code != 200:
            raise RuntimeError('CF_DNS_HTTP_' + str(response.status_code))
        body = response.json()
        if body.get('success') is not True:
            raise RuntimeError('CF_DNS_OPERATION_UNCONFIRMED')
        return body['result']
    zone = checked(client.get(endpoint, headers=headers, timeout=25, allow_redirects=False))
    if zone.get('name') != domain or zone.get('status') != 'active' or not zone.get('account', {}).get('id'):
        raise ValueError('CF_DNS_ZONE_OR_ACCOUNT_MISMATCH')
    records = checked(client.get(endpoint + '/dns_records', params={'name': name},
                                 headers=headers, timeout=25, allow_redirects=False))
    def matches(record):
        return (record.get('name', '').lower().rstrip('.') == name and record.get('type') == 'CNAME'
                and record.get('content', '').lower().rstrip('.') == 'verify.bing.com'
                and record.get('proxied') is False)
    if records:
        if not all(matches(record) for record in records):
            raise ValueError('CF_DNS_EXISTING_RECORD_CONFLICT')
        record, action = records[0], 'reused'
    else:
        record = checked(client.post(endpoint + '/dns_records', headers=headers,
            json={'type': 'CNAME', 'name': name, 'content': 'verify.bing.com', 'ttl': 300, 'proxied': False},
            timeout=25, allow_redirects=False))
        if not matches(record) or not record.get('id'):
            raise RuntimeError('CF_DNS_CREATED_RECORD_UNCONFIRMED')
        action = 'created'
    confirmed = checked(client.get(endpoint + '/dns_records/' + record['id'], headers=headers,
                                   timeout=25, allow_redirects=False))
    if not matches(confirmed):
        raise RuntimeError('CF_DNS_READBACK_MISMATCH')
    return {'domain': domain, 'type': 'CNAME', 'target': 'verify.bing.com', 'proxied': False,
            'action': action, 'recordId': record['id'], 'zoneVerified': True, 'accountVerified': True}


def bing_submission_request(method, site_url, credentials, urls=None, client=requests):
    """Only the documented quota GET and SubmitUrlBatch POST are writable here.

    No response text, request URL, token or credential is included in failures.
    Submit receipt is not evidence that a URL was crawled or indexed.
    """
    if method not in ('GetUrlSubmissionQuota', 'SubmitUrlBatch'):
        raise ValueError('BING_SUBMISSION_METHOD_NOT_ALLOWED')
    if method == 'SubmitUrlBatch' and (not isinstance(urls, list) or not 1 <= len(urls) <= 500):
        raise ValueError('BING_BATCH_SIZE_INVALID')
    params, headers = {}, {}
    if credentials.get('token'):
        headers['Authorization'] = 'Bearer ' + credentials['token']
    elif credentials.get('key'):
        params['apikey'] = credentials['key']
    else:
        return None, 'BING_CREDENTIAL_MISSING'
    endpoint = 'https://ssl.bing.com/webmaster/api.svc/json/' + method
    try:
        if method == 'GetUrlSubmissionQuota':
            response = client.get(endpoint, params={**params, 'siteUrl': site_url}, headers=headers,
                                  timeout=25, allow_redirects=False)
        else:
            response = client.post(endpoint, params=params, headers=headers,
                json={'siteUrl': site_url, 'urlList': urls}, timeout=25, allow_redirects=False)
        if response.status_code != 200:
            return None, 'BING_HTTP_' + str(response.status_code)
        payload = response.json()
        if not isinstance(payload, dict) or 'd' not in payload:
            return None, 'BING_RESPONSE_INVALID'
        if method == 'SubmitUrlBatch':
            return ({'accepted': True, 'httpStatus': 200}, None) if payload['d'] is None else (None, 'BING_RESPONSE_INVALID')
        quota = payload['d']
        if not isinstance(quota, dict) or any(type(quota.get(k)) is not int or quota[k] < 0
                                            for k in ('DailyQuota', 'MonthlyQuota')):
            return None, 'BING_QUOTA_INVALID'
        return {k: quota[k] for k in ('DailyQuota', 'MonthlyQuota')}, None
    except Exception:
        return None, 'BING_TRANSPORT_OR_JSON_ERROR'


def bing_credentials(config):
    """Read private configured credentials without copying secrets into state."""
    options = config.get('bing_search', {})
    def read_private(filename):
        if not filename:
            return None
        path = Path(filename).expanduser().resolve()
        if not path.is_relative_to((Path.home() / '.barolab' / 'credentials').resolve()):
            raise ValueError('BING_CREDENTIAL_FILE_NOT_PRIVATE')
        value = path.read_text(encoding='utf-8-sig').strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError('BING_CREDENTIAL_FILE_INVALID')
        return value
    return {'key': options.get('api_key') or os.environ.get(options.get('api_key_env', 'BING_WEBMASTER_API_KEY'))
                   or read_private(options.get('api_key_file')),
            'token': options.get('access_token') or os.environ.get(options.get('access_token_env', 'BING_WEBMASTER_ACCESS_TOKEN'))
                     or read_private(options.get('access_token_file'))}


def bing_rows(rows, queries=False):
    output = []
    for row in rows:
        item = {'sourceDate': row.get('Date')}
        if not isinstance(item['sourceDate'], str):
            raise ValueError('BING_DATE_INVALID')
        for source, target in [('Clicks', 'clicks'), ('Impressions', 'impressions')]:
            value = row.get(source)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('BING_METRIC_INVALID')
            item[target] = value
        if queries:
            if not isinstance(row.get('Query'), str):
                raise ValueError('BING_QUERY_INVALID')
            item['query'] = row['Query']
            for source, target in [('AvgClickPosition', 'averageClickPosition'),
                                   ('AvgImpressionPosition', 'averageImpressionPosition')]:
                value = row.get(source)
                # No-click/no-position rows may omit an average or return a sentinel.
                # Keep verified clicks/impressions; unavailable averages are unknown, never zero-rank.
                numeric = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
                item[target] = value if numeric and value > 0 else None
                reason = ('observed' if value > 0 else 'non_positive_or_sentinel') if numeric else 'missing' if value is None else 'non_numeric_or_non_finite'
                item.setdefault('positionValidity', {})[target] = {'reason': reason,
                    'reportedType': type(value).__name__, 'reportedNumericValue': value if numeric else None}
        output.append(item)
    return output


def bing_date_metadata(source, now):
    """Provider event dates are independent of this collector's checkedAt."""
    ranges, all_dates = {}, []
    for key in ('queries', 'traffic'):
        dates, invalid = [], 0
        for row in source.get(key, []):
            raw = row.get('sourceDate')
            try:
                match = re.fullmatch(r'/Date\((-?\d+)(?:[+-]\d{4})?\)/', raw or '')
                parsed = datetime.fromtimestamp(int(match[1])/1000, timezone.utc) if match else datetime.fromisoformat(raw)
                if parsed.tzinfo is None:
                    raise ValueError('Provider timezone unknown')
                dates.append(parsed.astimezone(timezone.utc).date())
            except (ValueError, TypeError, OverflowError, OSError):
                invalid += 1
        ranges[key] = {'minDateUTC': min(dates).isoformat() if dates else None,
                       'maxDateUTC': max(dates).isoformat() if dates else None,
                       'parsedRows': len(dates), 'unparsedRows': invalid}
        all_dates.extend(dates)
    age = (now.astimezone(timezone.utc).date() - max(all_dates)).days if all_dates else None
    return {'sourceDateRanges': ranges, 'providerLatestDateAgeDays': age,
            'cadence': 'queries_weekly;traffic_daily',
            'trafficSearchScope': 'all_verticals: web/chat/news/images/videos/knowledge_panel',
            'historicalOnly': age > 35 if age is not None else None,
            'providerDateStatus': 'unknown' if age is None else 'historical_only' if age > 35 else 'provider_date_available',
            'historicalThresholdDays': 35,
            'dateRangeScope': 'Min/max dates in returned rows, UTC epoch decoded; not a continuous or exact 7/28-day reporting window'}


@observed_operation('metrics', 'traffic-collection')
def collect_bing(sites, config, previous, now, client=requests):
    options = config.get('bing_search', {})
    def private_credential(filename):
        if not filename:
            return None
        path = Path(filename).expanduser().resolve()
        if not path.is_relative_to((Path.home() / '.barolab' / 'credentials').resolve()):
            raise ValueError('BING_CREDENTIAL_FILE_NOT_PRIVATE')
        value = path.read_text(encoding='utf-8-sig').strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError('BING_CREDENTIAL_FILE_INVALID')
        return value
    credentials = {'key': options.get('api_key') or os.environ.get(options.get('api_key_env', 'BING_WEBMASTER_API_KEY')),
                   'token': options.get('access_token') or os.environ.get(options.get('access_token_env', 'BING_WEBMASTER_ACCESS_TOKEN'))}
    credential_error = None
    try:
        credentials['key'] = credentials['key'] or private_credential(options.get('api_key_file'))
        credentials['token'] = credentials['token'] or private_credential(options.get('access_token_file'))
    except Exception:
        credential_error = 'BING_CREDENTIAL_FILE_UNAVAILABLE_OR_INVALID'
    output, stopped = {}, None
    # A persisted account denial/backoff prevents retries across all domains on the next run.
    for record in previous.values():
        old = record.get('bing', {})
        retry = old.get('nextRetryAt')
        try:
            if retry and datetime.fromisoformat(retry) > now:
                stopped = {'status': old.get('status', 'backoff'), 'reasonCode': old.get('reasonCode'), 'nextRetryAt': retry}
                break
        except (ValueError, TypeError):
            pass
    for site in sites:
        domain = site['site_id']
        old = previous.get(domain, {}).get('bing', {})
        base = {'source': 'Bing Webmaster JSON REST', 'scope': 'verified_site_top_queries',
                'metric': 'historical_average_position', 'country': 'all', 'device': 'all',
                'cadence': 'queries_weekly;traffic_daily', 'period': None,
                'trafficSearchScope': 'all_verticals: web/chat/news/images/videos/knowledge_panel',
                'periodScope': 'provider_returned_dates; not an exact daily/7/28-day window',
                'complete': False, 'attemptedAt': stamp()}
        if credential_error:
            output[domain] = {**old, **base, 'status': 'not_connected', 'stale': bool(old.get('checkedAt')),
                              'reasonCode': credential_error, 'nextAction': '로컬 비공개 credentials 파일 경로·형식 확인'}
            continue
        if not any(credentials.values()):
            output[domain] = {**old, **base, 'status': 'not_connected', 'stale': bool(old.get('checkedAt')),
                              'reasonCode': 'BING_CREDENTIAL_MISSING',
                              'nextAction': '기존 Bing 계정과 정확한 사이트 권한 확인 후 기존 키/토큰을 조회 전용 수집기에 연결'}
            continue
        if stopped:
            output[domain] = {**old, **base, **stopped, 'stale': True}
            continue
        settings = config.get('sites', {}).get(domain, {})
        property_id = settings.get('bing_property')
        prefix = urlparse(property_id or '')
        exact = property_id == site['url'].rstrip('/') + '/'
        registered = (settings.get('bing_property_verified') is True
            and prefix.scheme in ('https', 'http') and prefix.hostname in (domain, 'www.'+domain)
            and not prefix.username and not prefix.password and not prefix.port
            and not prefix.query and not prefix.fragment and prefix.path in ('', '/'))
        if not exact and not registered:
            output[domain] = {**old, **base, 'status': 'not_connected', 'stale': bool(old.get('checkedAt')),
                              'reasonCode': 'BING_PROPERTY_UNVERIFIED', 'nextAction': '실제 운영 주소의 Bing 등록 속성을 확인하여 bing_property에 연결'}
            continue
        base.update(scope='verified_registered_property_top_queries', canonicalUrl=site['url'],
                    canonicalScopeExact=exact)
        try:
            checked = datetime.fromisoformat(old['checkedAt'])
            if old.get('property') == property_id and old.get('status') in ('collected', 'partial') and not old.get('stale') and timedelta(0) <= now - checked < timedelta(hours=12):
                output[domain] = {**old, **bing_date_metadata(old, now), 'cacheHit': True}
                continue
        except (KeyError, ValueError, TypeError):
            pass
        reports, error = {}, None
        for method, key in [('GetQueryStats', 'queries'), ('GetRankAndTrafficStats', 'traffic')]:
            rows, error = bing_request(method, property_id, credentials, client)
            if error:
                break
            try:
                reports[key] = bing_rows(rows, key == 'queries')
            except ValueError as exc:
                error = str(exc)
                break
        if error:
            status = 'backoff' if error == 'BING_HTTP_429' else 'error'
            failure = {'status': status, 'reasonCode': error, 'stale': True}
            if error in ('BING_HTTP_401', 'BING_HTTP_403', 'BING_HTTP_429'):
                failure['nextRetryAt'] = (now + timedelta(hours=6)).isoformat()
                stopped = failure
            output[domain] = {**old, **base, **failure, 'property': property_id}
        else:
            position_incomplete = any(row.get('averageImpressionPosition') is None for row in reports['queries'])
            output[domain] = {**base, **reports, 'property': property_id, 'checkedAt': stamp(),
                              'status': 'collected' if all(reports.values()) and not position_incomplete else 'partial', 'stale': False,
                              'positionIncomplete': position_incomplete,
                              'topRowsOnly': True, 'emptyResponse': not all(reports.values()),
                              'note': 'Bing 과거 보고서의 평균 위치 · 빈 응답은 미노출/0을 확정하지 않음 · 실시간 검색 순위와 다름'}
            output[domain].update(bing_date_metadata(output[domain], now))
    return output


def keyword_tracking(site, settings, google, previous, now):
    """Persist bounded daily report observations, never synthesize live SERP ranks."""
    watchlist = settings.get('keyword_watchlist', previous.get('watchlist', []))
    seed = previous.get('initialSeed')
    if not watchlist and 'keyword_watchlist' not in settings and google.get('status') in ('collected', 'partial') and not google.get('stale'):
        for key in ('current28', 'month', 'week', 'day'):
            candidate = google.get('periods', {}).get(key, {})
            if candidate.get('queriesStatus') != 'collected' or candidate.get('partialPeriod'):
                continue
            totals = {}
            for row in candidate.get('queries', []):
                query, impressions = row.get('query'), row.get('impressions')
                if isinstance(query, str) and query.strip() and isinstance(impressions, (int, float)) and not isinstance(impressions, bool) and math.isfinite(impressions) and impressions > 0:
                    totals[query] = totals.get(query, 0) + impressions
            if totals:
                watchlist = sorted(totals, key=lambda query: (-totals[query], query))[:10]
                seed = {'source': 'Google Search Console public query/page rows', 'seededAt': stamp(),
                        'sourceCheckedAt': candidate.get('checkedAt'),
                        'period': {'start': candidate.get('start'), 'end': candidate.get('end')},
                        'method': 'Top 10 observed queries by summed impressions; not live SERP selection'}
                break
    watchlist = [({'query': row} if isinstance(row, str) else row) for row in watchlist]
    watchlist = [dict(query=row['query'].strip(), country=row.get('country', 'all'), device=row.get('device', 'all'))
                 for row in watchlist if isinstance(row, dict) and isinstance(row.get('query'), str) and row['query'].strip()][:50]
    report = google.get('periods', {}).get('day', {})
    valid = google.get('status') in ('collected', 'partial') and not google.get('stale') and report.get('queriesStatus') == 'collected' and not report.get('partialPeriod')
    history = {tuple(row.get(k) for k in ('date', 'query', 'country', 'device', 'source')): row
               for row in previous.get('observations', []) if isinstance(row, dict) and row.get('date', '') >= (now.date() - timedelta(days=90)).isoformat()}
    for watch in watchlist:
        rows = [row for row in report.get('queries', []) if row.get('query') == watch['query']] if valid and watch['country'] == watch['device'] == 'all' else []
        measured = bool(rows) and all(all(not isinstance(row.get(key), bool)
            and isinstance(row.get(key), (int, float)) and math.isfinite(row[key]) and row[key] >= 0
            for key in ('impressions', 'position', 'clicks')) for row in rows)
        impressions = sum(row['impressions'] for row in rows) if measured else None
        entry = {**watch, 'date': report.get('end') if valid else now.date().isoformat(),
                 'source': 'Google Search Console query/page daily report', 'metric': 'average_position',
                 'period': {'start': report.get('start'), 'end': report.get('end')} if valid else None,
                 'status': 'observed' if measured and impressions else 'unknown',
                 'observedAt': report.get('checkedAt') if measured else None, 'checkedAt': stamp(),
                 'clicks': sum(row['clicks'] for row in rows) if measured else None,
                 'impressions': impressions,
                 'position': sum(row['position'] * row['impressions'] for row in rows) / impressions if measured and impressions else None,
                 'scope': 'public_top_query_page_rows', 'topRowsOnly': True}
        identity = tuple(entry[k] for k in ('date', 'query', 'country', 'device', 'source'))
        if entry['status'] == 'observed' or history.get(identity, {}).get('status') != 'observed':
            history[identity] = entry
    return {'status': 'configured' if watchlist else 'not_configured', 'watchlist': watchlist, 'initialSeed': seed,
            'observations': sorted(history.values(), key=lambda row: row['date'])[-4500:],
            'liveSerp': {'status': 'not_connected', 'position': None, 'nextAction': '실제 SERP 제공자·국가·기기 범위 확정 및 별도 연결 필요'},
            'note': '일별 GSC 평균 관측 · 미관측은 unknown · Naver 웹검색 API 결과를 일반 SERP 순위로 취급하지 않음'}


def naver_ui_report(site, previous, options, now):
    if previous.get('source') in ('Naver Search Advisor verified UI', 'Naver Search Advisor site registry verified UI'):
        result = dict(previous)
        try:
            age = now - datetime.fromisoformat(result['checkedAt'])
            source_age = (now.astimezone(ZoneInfo('Asia/Seoul')).date() - datetime.fromisoformat(result['sourceUpdatedDate']).date()
                          if result.get('sourceUpdatedDate') else timedelta(0))
            result['stale'] = not timedelta(0) <= age <= timedelta(hours=48) or not timedelta(0) <= source_age <= timedelta(days=3)
        except (KeyError, TypeError, ValueError):
            result['stale'] = True
        if result['stale']:
            result['status'] = 'stale'
        return result
    return {'status': options.get('status', 'not_connected'), 'account': options.get('account'),
            'reason': options.get('reason') or '서치어드바이저 보고서 미연결 · 네이버 검색 유입은 GA4에서 별도 확인',
            'rankingStatus': 'not_provided', 'complete': False,
            'nextAction': '정확한 운영 주소의 서치어드바이저 보고서 조회 및 검증된 UI 결과 가져오기',
            'note': '검색 노출/클릭 보고서의 키워드는 고정 검색 순위와 다름'}


def import_naver_ui(path):
    """Import manually verified reports, not hidden browser state or inferred counters."""
    document = read_json(path)
    if document.get('schema') != 'naver-search-ui-v1' or not isinstance(document.get('sites'), dict):
        raise ValueError('NAVER_UI_SCHEMA_INVALID')
    catalog = {site['site_id']: site for site in inventory() if site['platform'] == 'cf'}
    now = datetime.now(ZoneInfo('UTC'))
    validated = {}
    registration = document.get('siteRegistration')
    if registration is not None:
        registered = registration.get('registeredCanonicalDomains')
        if not isinstance(registered, list) or not set(registered) <= set(catalog):
            raise ValueError('NAVER_UI_REGISTRATION_INVALID')
        registry_time = datetime.fromisoformat(registration['capturedAt'])
        if registry_time.tzinfo is None or not timedelta(0) <= now - registry_time <= timedelta(hours=48):
            raise ValueError('NAVER_UI_REGISTRATION_NOT_FRESH')
    for domain, report in document['sites'].items():
        if domain not in catalog or not isinstance(report, dict):
            raise ValueError('NAVER_UI_DOMAIN_INVALID')
        if report.get('property') != catalog[domain]['url'].rstrip('/') + '/':
            raise ValueError('NAVER_UI_PROPERTY_SCOPE_MISMATCH')
        checked = datetime.fromisoformat(report['capturedAt'])
        if checked.tzinfo is None:
            raise ValueError('NAVER_UI_CAPTURE_TIMEZONE_MISSING')
        age = now - checked
        if age < -timedelta(minutes=5) or age > timedelta(hours=48):
            raise ValueError('NAVER_UI_CAPTURE_NOT_FRESH')
        unavailable = report.get('reportUnavailable') is True
        source_date = datetime.fromisoformat(report['sourceUpdatedDate']).date() if report.get('sourceUpdatedDate') else None
        if source_date is None and not unavailable:
            raise ValueError('NAVER_UI_SOURCE_DATE_MISSING')
        if source_date and source_date > checked.astimezone(ZoneInfo('Asia/Seoul')).date():
            raise ValueError('NAVER_UI_SOURCE_DATE_INVALID')
        period = report.get('period', {})
        if not isinstance(period, dict) or not isinstance(period.get('label'), str):
            raise ValueError('NAVER_UI_PERIOD_MISSING')
        for field in ('clicks', 'impressions', 'ctrPercent'):
            value = report.get(field)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0):
                raise ValueError('NAVER_UI_METRIC_INVALID')
        if report.get('impressionsRounded') and report.get('impressions') is not None:
            raise ValueError('NAVER_UI_ROUNDED_VALUE_NOT_EXACT')
        rows = {}
        for kind, identity in (('queries', 'query'), ('pages', 'page')):
            rows[kind] = []
            if not isinstance(report.get(kind, []), list):
                raise ValueError('NAVER_UI_ROWS_INVALID')
            for row in report.get(kind, []):
                if not isinstance(row, dict) or not isinstance(row.get(identity), str):
                    raise ValueError('NAVER_UI_ROW_INVALID')
                if kind == 'pages' and urlparse(row['page']).hostname != urlparse(catalog[domain]['url']).hostname:
                    raise ValueError('NAVER_UI_PAGE_SCOPE_MISMATCH')
                cleaned = {identity: row[identity]}
                for key in ('clicks', 'impressions', 'ctrPercent'):
                    value = row.get(key)
                    if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                        raise ValueError('NAVER_UI_ROW_METRIC_INVALID')
                    cleaned[key] = value
                rows[kind].append(cleaned)
        validated[domain] = {**rows, 'source': 'Naver Search Advisor verified UI',
            'status': 'report_unavailable' if unavailable else 'partial', 'complete': False, 'stale': False, 'topRowsOnly': True,
            'property': report['property'], 'checkedAt': checked.isoformat(), 'importedAt': stamp(),
            'sourceUpdatedDate': source_date.isoformat() if source_date else None,
            'freshnessScope': 'capture_only' if unavailable else 'capture_and_source_date',
            'reasonCode': 'NAVER_UI_REPORT_UNAVAILABLE' if unavailable else None,
            'period': {key: period.get(key) for key in ('label', 'start', 'end')},
            'device': report.get('device', 'unknown'), 'country': 'provider_unspecified',
            'clicks': report.get('clicks'), 'impressions': report.get('impressions'),
            'impressionsDisplay': report.get('impressionsDisplay'),
            'impressionsRounded': bool(report.get('impressionsRounded')), 'ctrPercent': report.get('ctrPercent'),
            'rankingStatus': 'not_provided', 'note': 'UI 검증 보고서 · 기간 전체 검색어가 아님 · 실시간 검색 순위 미제공'}
        if unavailable and (any(report.get(key) is not None for key in ('clicks', 'impressions', 'ctrPercent')) or any(rows.values())):
            raise ValueError('NAVER_UI_UNAVAILABLE_MUST_NOT_INVENT_METRICS')
    with collector_lock(DATA / 'traffic.lock') as acquired:
        if not acquired:
            return {'status': 'busy'}
        snapshot = read_json(SNAPSHOT)
        if registration is not None:
            for domain, site in catalog.items():
                record = snapshot.setdefault('sites', {}).setdefault(domain, {'site': site})
                if record.get('naver', {}).get('source') == 'Naver Search Advisor verified UI':
                    continue
                connected = domain in registered
                record['naver'] = {'source': 'Naver Search Advisor site registry verified UI',
                    'status': 'not_collected' if connected else 'not_connected', 'complete': False,
                    'stale': False, 'checkedAt': registry_time.isoformat(),
                    'sourceUpdatedDate': registry_time.astimezone(ZoneInfo('Asia/Seoul')).date().isoformat(),
                    'property': site['url'].rstrip('/')+'/', 'account': registration.get('account'),
                    'reasonCode': 'NAVER_REPORT_NOT_COLLECTED' if connected else 'NAVER_CANONICAL_PROPERTY_NOT_REGISTERED',
                    'nextAction': '등록 속성 보고서 UI 검증·가져오기' if connected else '실제 www 운영 주소의 등록·권한 확인 필요',
                    'rankingStatus': 'not_provided'}
            snapshot['naverSearchAccount'] = {'status': 'connected', 'checkedAt': registry_time.isoformat(),
                'account': registration.get('account'), 'registeredCanonicalDomains': registered,
                'scope': 'canonical www registrations; apex registrations do not cover www',
                'continuousCollectionVerified': False}
        for domain, report in validated.items():
            record = snapshot.setdefault('sites', {}).setdefault(domain, {'site': catalog[domain]})
            previous = record.get('naver', {})
            if previous.get('checkedAt') and datetime.fromisoformat(previous['checkedAt']) > datetime.fromisoformat(report['checkedAt']):
                raise ValueError('NAVER_UI_OLDER_THAN_SAVED_REPORT')
            record['naver'] = report
        # Global checkedAt belongs to the full collector and is deliberately preserved.
        snapshot['naverSearchImportedAt'] = stamp()
        atomic_write(SNAPSHOT, snapshot)
    return {'status': 'imported', 'domains': sorted(validated), 'sourceCheckedAt': {d:r['checkedAt'] for d,r in validated.items()}}


@observed_operation('metrics', 'traffic-collection')
def collect_naver_only():
    with collector_lock(DATA / 'traffic.lock') as locked:
        if not locked:
            return {'status': 'busy'}
        document = read_json(SNAPSHOT)
        document.update(naverBlogs=collect_naver_visitors(), naverCheckedAt=stamp())
        atomic_write(SNAPSHOT, document)
    return summary()


def safe_error_metadata(exc, stage):
    name = type(exc).__name__
    name = name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) else 'UnknownException'
    status = getattr(exc, 'http_status', None)
    if status is None:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    return {'exceptionClass': name, 'httpStatus': status,
            'stage': stage if stage in ('ga4_collect', 'google_collect') else 'unknown',
            'winerror': getattr(exc, 'winerror', None) if type(getattr(exc, 'winerror', None)) is int else None,
            'operation': getattr(exc, 'safe_operation', None) if getattr(exc, 'safe_operation', None) in ('credential_file_read', 'snapshot_read') else 'unknown'}


def safe_error_reason(metadata):
    status = metadata['httpStatus']
    if metadata['stage'] == 'google_collect' and status == 403:
        return 'GSC_PROPERTY_ACCESS_DENIED: 설정 속성 접근 거절 (HTTP 403; 사용자 권한 및 속성 범위 확인 필요)'
    return f'통계 원천 HTTP {status}' if status is not None else '통계 원천 연결 실패'


@observed_operation('metrics', 'traffic-collection')
def collect():
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    with collector_lock(DATA / 'traffic.lock') as locked:
        if not locked:
            return {'status': 'busy'}
        config, old = read_json(CONFIG), read_json(SNAPSHOT)
        sites = [s for s in inventory() if s['platform'] == 'cf']
        started=stamp()
        old_health=old.get('growthCollection',{})
        atomic_write(SNAPSHOT,{**old,'growthCollection':{**old_health,'status':'running','lastAttemptAt':started,
                    'nextRunAt':(now+timedelta(minutes=30)).isoformat(),'scheduleEstimate':True}})
        checkpoint_lock=threading.Lock()
        def checkpoint(domain,source):
            with checkpoint_lock:
                document=read_json(SNAPSHOT)
                record=document.setdefault('sites',{}).setdefault(domain,{})
                previous=record.get('google',{})
                record['google']={**previous,**source,'periods':{**previous.get('periods',{}),**source.get('periods',{})}}
                checked=max((r.get('checkedAt') or '' for k,r in source.get('periods',{}).items() if k in ('current28','previous28') and r.get('queriesStatus')=='collected'),default='')
                if checked>=started:
                    document.setdefault('growthCollection',{})['lastSuccessAt']=checked
                atomic_write(SNAPSHOT,document)
        def one(site):
            record = {'site': site, 'attemptedAt': stamp()}
            settings = config.get('sites', {}).get(site['site_id'], {})
            for key, job in [('ga4', collect_ga), ('google', collect_search)]:
                try:
                    record[key] = job(site, settings, config.get('analytics_readers', {}), now, snapshot=old) if key == 'google' else job(site, settings, config.get('analytics_readers', {}), now)
                    record[key].pop('errorMetadata', None)
                except Exception as exc:
                    previous = old.get('sites', {}).get(site['site_id'], {}).get(key, {})
                    error_metadata = safe_error_metadata(exc, key + '_collect')
                    record[key] = {**previous, 'status': 'error', 'attemptedAt': stamp(),
                        'reason': safe_error_reason(error_metadata), 'stale': True,
                        'errorMetadata': error_metadata}
                if key=='google':
                    checkpoint(site['site_id'],record[key])
            record['naver'] = naver_ui_report(site, old.get('sites', {}).get(site['site_id'], {}).get('naver', {}), config.get('naver_search', {}), now)
            return record
        with ThreadPoolExecutor(max_workers=4) as workers:
            output = {'schema': 'domain-traffic-v1', 'checkedAt': stamp(),
                      'naverSearchAccount': old.get('naverSearchAccount'),
                      'sites': {r['site']['site_id']: r for r in workers.map(
                          lambda item: item[0].run(one, item[1]),
                          [(copy_context(), site) for site in sites])}}
        missing = [s for s in sites if not config['sites'][s['site_id']].get('search_property')]
        if missing:
            try:
                recovered = collect_browser_search(missing, config, now, checkpoint)
                for domain, record in recovered.items():
                    if record.get('periods'):
                        output['sites'][domain]['google'] = record
                    else:
                        saved = old.get('sites', {}).get(domain, {}).get('google', {})
                        output['sites'][domain]['google'] = {**saved, **record, 'stale': True}
            except Exception:
                for site in missing:
                    domain = site['site_id']
                    saved = old.get('sites', {}).get(domain, {}).get('google', {})
                    output['sites'][domain]['google'] = {**saved, 'status': 'error',
                        'reason': 'SJ 브라우저 소유자 보고서 연결 실패', 'stale': True}
        output['checkedAt'] = stamp()
        output['growthActionCursor'] = {**old.get('growthActionCursor',{}), **{w['domain']:w['nextCursor'] for w in action_windows(now).values()}}
        windows=search_windows(now)
        successful=[]
        backlog=0
        failures=0
        ui_measured=False
        linked_attempt=False
        for domain,record in output['sites'].items():
            source=record.get('google',{})
            linked_attempt|=(source.get('linkedPageQueries',{}).get('attemptAt') or '')>=started
            failures+=source.get('status') in ('error','backoff')
            pair=[source.get('periods',{}).get(k,{}) for k in ('current28','previous28')]
            due=False
            for key,report in zip(('current28','previous28'),pair):
                if (not report.get('queriesStatus')=='collected' or report.get('partialPeriod') or
                        any(report.get(k)!=windows[key][k] for k in ('start','end'))):
                    due=True
                checked=report.get('checkedAt') or ''
                if checked>=started and report.get('queriesStatus')=='collected':
                    successful.append(checked)
                    ui_measured|=source.get('queriesScope')=='domain_query' or report.get('queriesScope')=='domain_query'
            backlog+=due
        _,next_cursor=growth_browser_targets(missing,now)
        from gsc_ui_state import state as ui_state
        output['growthCollection']={**old_health,'status':'partial' if failures or backlog else 'completed',
            'lastAttemptAt':started,'lastSuccessAt':max(successful) if successful else old_health.get('lastSuccessAt'),
            'finishedAt':stamp(),'nextRunAt':(now+timedelta(minutes=30)).isoformat(),'scheduleEstimate':True,
            'backlog':backlog,'failures':failures,'expectedDomains':len(sites),'uiMaxDomains':4,
            'cursor':next_cursor if ui_measured else old_health.get('cursor',0),'uiAccount':ui_state('sj')}
        output['growthCollection']['pageCursor']=int(old_health.get('pageCursor',0))+int(linked_attempt)
        bing = collect_bing(sites, config, old.get('sites', {}), now)
        for domain, record in output['sites'].items():
            record['bing'] = bing[domain]
            record['keywordTracking'] = keyword_tracking(record['site'], config['sites'].get(domain, {}),
                record.get('google', {}), old.get('sites', {}).get(domain, {}).get('keywordTracking', {}), now)
        output.update(naverBlogs=collect_naver_visitors(), naverCheckedAt=stamp())
        output['checkedAt'] = stamp()
        end = now.date() - timedelta(days=1)
        page_sites, page_rows = [], []
        for domain, record in output['sites'].items():
            ga = record.get('ga4', {})
            evidence = ga.get('pagePerformance', {})
            valid = (ga.get('status') != 'error' and not ga.get('stale')
                     and evidence.get('complete') is True
                     and evidence.get('start') == (end - timedelta(days=6)).isoformat()
                     and evidence.get('end') == end.isoformat())
            page_sites.append({**{k: v for k, v in evidence.items() if k != 'pages'},
                               'domain': domain, 'complete': valid})
            if valid:
                page_rows.extend(evidence.get('pages', []))
        output['pagePerformance'] = {'start': (end - timedelta(days=6)).isoformat(),
            'end': end.isoformat(), 'timezone': 'Asia/Seoul', 'checkedAt': stamp(),
            'complete': bool(page_sites) and all(s['complete'] for s in page_sites),
            'source': 'GA4 Data API', 'sites': page_sites, 'pages': page_rows}
        atomic_write(SNAPSHOT, output)
    return summary()


def rank_overview(sites, period):
    items, known, partial_periods = [], 0, 0
    ranges = set()
    for record in sites:
        source = record.get('google', {})
        report = source.get('periods', {}).get(period)
        if not report or source.get('stale') or source.get('status') not in ('collected', 'partial'):
            continue
        known += 1
        partial_periods += bool(report.get('partialPeriod'))
        ranges.add((report['start'], report['end']))
        seen = set()
        for row in report.get('queries', []):
            position, impressions = row.get('position'), row.get('impressions')
            if not isinstance(position, (int, float)) or not math.isfinite(position) or position <= 0 or not isinstance(impressions, (int, float)) or impressions <= 0:
                continue
            identity = (row['query'], row.get('page'))
            if identity in seen:
                continue
            seen.add(identity)
            items.append({**row, 'domain': record['site']['site_id'], 'source': source.get('source'),
                          'lowSample': impressions < 10, 'start': report['start'], 'end': report['end']})
    bands = [{'limit': limit, 'observations': sum(r['position'] <= limit for r in items),
              'domains': len({r['domain'] for r in items if r['position'] <= limit}),
              'lowSample': sum(r['position'] <= limit and r['lowSample'] for r in items)}
             for limit in (5, 10, 50, 100)]
    ranked = sorted((r for r in items if r['position'] <= 100),
        key=lambda r: (r['lowSample'], -r.get('clicks', 0), r['position'], -r['impressions']))
    highlights, selected_domains = [], set()
    for row in ranked:
        if row['domain'] not in selected_domains:
            highlights.append(row)
            selected_domains.add(row['domain'])
        if len(highlights) == 5:
            break
    if len(highlights) < 5:
        highlights += [r for r in ranked if r not in highlights][:5-len(highlights)]
    return {'engine': 'google', 'metric': 'average_position', 'bands': bands,
            'connectedDomains': known, 'expectedDomains': len(sites), 'partialPeriods': partial_periods,
            'ranges': [list(r) for r in sorted(ranges)], 'highlights': highlights,
            'highlightSelection': '도메인별 대표 관측 우선 · 최대 5행 · 전체 상위 순위 목록이 아님',
            'queryRows': len(items), 'pageLinkedRows': sum(bool(r.get('page')) for r in items),
            'note': 'Google 평균 게재순위 · 공개 검색어/URL 관측 행 · 구간 누적 집계 · 고정 실시간 순위와 다름'}


def source_coverage(sites, key, period='month', today=None):
    known, partial = 0, 0
    for record in sites:
        source = record.get(key, {})
        report = source.get('periods', {}).get('day' if key == 'google' and period == 'today' else period, {})
        if source.get('stale') or source.get('status') not in ('collected', 'partial') or not report.get('start') or not report.get('end'):
            continue
        if key == 'ga4' and period == 'today' and report['end'] != today:
            continue
        known += 1
        partial += bool(source.get('status') == 'partial' or report.get('partialPeriod') or report.get('limited') or report.get('sourceLimited'))
    return {'connectedDomains': known, 'partialDomains': partial}


def top_posts_overview(sites, today=None):
    by_period = {'today': {}, 'day': {}, 'week': {}, 'recent24h': {}}
    connected = 0
    for record in sites:
        domain = record.get('site', {}).get('site_id', '')
        ga = record.get('ga4', {})
        if not domain or ga.get('status') not in ('collected', 'partial'):
            continue
        periods_map = ga.get('periods', {})
        if any(isinstance(periods_map.get(k, {}).get('pages'), list) for k in ('today', 'day', 'week')):
            connected += 1
        for key in ('today', 'day', 'week'):
            for item in periods_map.get(key, {}).get('pages', []) or []:
                path = item.get('path') or ''
                if not is_article_path(path):
                    continue
                ident = (domain, path)
                entry = by_period[key].setdefault(ident, {
                    'domain': domain, 'path': path,
                    'url': item.get('url') or f'https://www.{domain}{path}',
                    'title': clean_post_title(item.get('title'), path),
                    'sessions': 0, 'pageViews': 0, 'users': 0
                })
                entry['sessions'] += int(item.get('sessions') or 0)
                entry['pageViews'] += int(item.get('pageViews') or 0)
                entry['users'] = max(entry['users'], int(item.get('users') or 0))
                if key in ('today', 'day'):
                    r24 = by_period['recent24h'].setdefault(ident, {
                        'domain': domain, 'path': path,
                        'url': item.get('url') or f'https://www.{domain}{path}',
                        'title': clean_post_title(item.get('title'), path),
                        'sessions': 0, 'pageViews': 0, 'users': 0
                    })
                    r24['sessions'] += int(item.get('sessions') or 0)
                    r24['pageViews'] += int(item.get('pageViews') or 0)
                    r24['users'] += int(item.get('users') or 0)
    rank_key = lambda x: (-x['pageViews'], -x['sessions'], -x['users'], x['domain'], x['path'])
    return {
        'connectedDomains': connected,
        'expectedDomains': len(sites),
        'recent24h': sorted(by_period['recent24h'].values(), key=rank_key)[:10],
        'today': sorted(by_period['today'].values(), key=rank_key)[:10],
        'day': sorted(by_period['day'].values(), key=rank_key)[:10],
        'week': sorted(by_period['week'].values(), key=rank_key)[:10],
    }


def summary(path=SNAPSHOT):
    data = read_json(path)
    sites = list(data.get('sites', {}).values())
    naver = list(data.get('naverBlogs', {}).values())
    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    for record in sites:
        for key in ('ga4', 'google'):
            source = record.get(key, {})
            try:
                source['stale'] = source.get('stale', False) or datetime.now(ZoneInfo('UTC')) - datetime.fromisoformat(source['checkedAt']) > timedelta(hours=2)
            except (ValueError, TypeError, KeyError):
                source['stale'] = True
        ga = record.get('ga4', {})
        for report in ga.get('periods', {}).values():
            report['sourceAttribution'] = aggregate_source_attribution(report, record.get('site', {}).get('site_id', ''), derived_at=stamp())
            report['naverExternal'] = report['sourceAttribution']['naverExternalSessions']
        if ga.get('status') == 'collected' and any(not p.get('sourceReconciled', False) for p in ga.get('periods', {}).values()):
            ga['status'] = 'partial'
        current = record.get('ga4', {}).get('periods', {}).get('today')
        if current and current['end'] != today:
            record['ga4']['status'] = 'stale'
            record['ga4']['stale'] = True
    for record in naver:
        try:
            record['stale'] = datetime.now(ZoneInfo('UTC')) - datetime.fromisoformat(record['checkedAt']) > timedelta(hours=2) or record.get('date') != today
        except (ValueError, TypeError, KeyError):
            record['stale'] = True
    return {'checkedAt': data.get('checkedAt'), 'sites': sites, 'today': today,
            'naverBlogs': naver, 'naverCheckedAt': data.get('naverCheckedAt'),
            'expectedNaverBlogs': sum(s['platform'] == 'naver' for s in inventory()),
            'rankings': {key: rank_overview(sites, key) for key in ('day', 'week', 'month')},
            'topPosts': top_posts_overview(sites, today),
            'connectedDomains': source_coverage(sites, 'ga4')['connectedDomains'],
            'searchDomains': source_coverage(sites, 'google')['connectedDomains'],
            'coverage': {period: {key: source_coverage(sites, key, period, today) for key in ('ga4', 'google')}
                         for period in ('today', 'day', 'week', 'month')},
            'expectedDomains': len(sites), 'note': '방문자는 도메인별 기간 중복 제거 · 유입 비중은 세션 기준'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--collect-naver', action='store_true', help='Refresh public Naver counters only; no login')
    parser.add_argument('--import-naver-ui', help='Import manually verified canonical-site Search Advisor reports')
    args = parser.parse_args()
    if sum(bool(value) for value in (args.collect, args.collect_naver, args.import_naver_ui)) > 1:
        parser.error('Choose one collection/import action')
    result = import_naver_ui(args.import_naver_ui) if args.import_naver_ui else collect() if args.collect else collect_naver_only() if args.collect_naver else summary()
    print(json.dumps({k: v for k, v in result.items() if k not in ('sites', 'naverBlogs')}, ensure_ascii=False, indent=2))
