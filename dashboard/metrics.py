"""One collector for indexing requests, index evidence and site traffic.

Run from the repository root: python dashboard/metrics.py --collect.
Credentials/configuration and collected data stay outside this public directory.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from common.channel_attribution import is_dummy_rescue_url
DATA = ROOT / 'server' / 'data'
CONFIG = DATA / 'metrics-config.json'
SNAPSHOT = DATA / 'metrics.json'
SCOPES = ['https://www.googleapis.com/auth/webmasters',
          'https://www.googleapis.com/auth/analytics.readonly']


from common.ego_telemetry import observed_operation, action as ego_action


def read_json(path, default=None):
    if not Path(path).exists():
        return {} if default is None else default
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def stamp():
    return datetime.now(timezone.utc).isoformat()


def unknown(reason):
    return {'status': 'not_collected', 'reason': reason, 'checkedAt': stamp()}


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        for delay in (0.1, 0.2, 0.4, 0.8, 1.0, None):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as exc:
                if getattr(exc, 'winerror', None) not in (5, 32) or delay is None:
                    raise
                time.sleep(delay)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def collector_lock(path=None):
    DATA.mkdir(parents=True, exist_ok=True)
    with Path(path or DATA / 'metrics.lock').open('a+b') as handle:
        handle.write(b'0') if handle.tell() == 0 else None
        handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def inventory():
    # Reuse the existing channel inventory rather than maintain another list.
    with closing(sqlite3.connect(DATA / 'growth.sqlite3')) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute('SELECT site_id,url,platform FROM sites ORDER BY site_id')]


def owned_url(site, url):
    target, owner = urlparse(url), urlparse(site['url'])
    allowed = {owner.hostname, site['site_id'], 'www.' + site['site_id']}
    if site['platform'] != 'cf' or target.scheme != 'https' or target.hostname not in allowed:
        raise ValueError('Only HTTPS URLs on an inventoried CF domain are supported')
    if target.username or target.password or target.port or target.fragment:
        raise ValueError('Use a canonical URL without user info, port or fragment')
    return url


def google_session(config, settings=None):
    reader_key = (settings or {}).get('analytics_reader') or 'sj'
    binding = config.get('analytics_readers', {}).get(reader_key)
    if binding:
        path = Path(binding['file']).expanduser().resolve()
        if path.is_relative_to((ROOT / 'dashboard').resolve()):
            raise ValueError('인증 파일은 dashboard 밖에 보관해야 합니다')
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        credentials = service_account.Credentials.from_service_account_file(
            str(path), scopes=SCOPES)
        if credentials.service_account_email != binding['email']:
            raise ValueError('통계 조회 계정 인증 파일 불일치')
        return AuthorizedSession(credentials)
    filename = config.get('google_credentials')
    if not filename:
        raise ValueError('Google 인증 파일 미설정')
    path = Path(filename).expanduser().resolve()
    if path.is_relative_to((ROOT / 'dashboard').resolve()):
        raise ValueError('인증 파일은 dashboard 밖에 보관해야 합니다')
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.load_credentials_from_file(str(path), scopes=SCOPES)
    return AuthorizedSession(credentials)


def api(session, method, url, payload=None, timeout=25):
    response = session.request(method, url, json=payload, timeout=timeout)
    if not response.ok:
        # Never persist request URLs, authorization headers or token responses.
        raise RuntimeError(f'원천 API HTTP {response.status_code}')
    return response.json() if response.content else {}


def public_inventory(site):
    origin = site['url'].rstrip('/')
    urls, titles, excluded = [], {}, []
    # The CF API caps each page at 100. Paginate; do not call page one a total.
    for page in range(1, 31):
        result = api(requests, 'GET', f'{origin}/api/posts?limit=100&page={page}')
        posts = result.get('posts')
        if not isinstance(posts, list):
            raise ValueError('CF 글 목록 형식 불일치')
        excluded.extend(origin + '/' + p['slug'] for p in posts if p.get('slug') and is_dummy_rescue_url(p['slug']))
        batch = [owned_url(site, origin + '/' + p['slug']) for p in posts if p.get('slug') and not is_dummy_rescue_url(p['slug'])]
        if set(batch) & set(urls):
            raise ValueError('CF 페이지 이동 결과 중복; 전체 목록 미확인')
        urls.extend(batch)
        for post in posts:
            if post.get('slug') and not is_dummy_rescue_url(post['slug']) and isinstance(post.get('title'), str):
                titles[origin + '/' + post['slug']] = post['title'][:500]
        if len(posts) < 100:
            return {'status': 'collected', 'urls': urls, 'titles': titles, 'total': len(urls),
                    'complete': True, 'source': origin + '/api/posts', 'checkedAt': stamp(),
                    'excludedDummyCount': len(excluded), 'excludedDummyUrls': excluded}
    return {'status': 'partial', 'urls': urls, 'total': None, 'complete': False,
            'reason': '페이지 상한 도달', 'checkedAt': stamp()}


def sitemap_status(site, settings):
    url = owned_url(site, settings.get('sitemap_url', site['url'].rstrip('/') + '/sitemap.xml'))
    response = requests.get(url, timeout=15, allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(f'사이트맵 HTTP {response.status_code}')
    root = ElementTree.fromstring(response.content)
    kind = root.tag.rsplit('}', 1)[-1]
    if kind not in ('urlset', 'sitemapindex'):
        raise ValueError('유효한 사이트맵 XML이 아닙니다')
    locations = [n.text.strip() for n in root.iter() if n.tag.rsplit('}', 1)[-1] == 'loc' and n.text]
    if not locations:
        raise ValueError('사이트맵이 비어 있습니다')
    excluded = [value for value in locations if is_dummy_rescue_url(value)]
    eligible = [value for value in locations if not is_dummy_rescue_url(value)]
    return {'status': 'available', 'url': url, 'kind': kind, 'entries': len(eligible),
            'locations': eligible, 'rawEntries': len(locations),
            'excludedDummyCount': len(excluded), 'excludedDummyUrls': excluded,
            'publicSitemapFiltered': False,
            'checkedAt': stamp(), 'source': url}


def inspection_time(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def inspection_current(row, now=None, hours=26):
    now = now or datetime.now(timezone.utc)
    checked = inspection_time(row.get('checkedAt'))
    return type(row.get('indexed')) is bool and checked is not None and timedelta(0) <= now - checked <= timedelta(hours=hours)


def inspection_rows(previous, posts):
    valid = set(posts.get('urls', []))
    known = {}
    for original in previous.get('urls', []):
        if original.get('url') not in valid:
            continue
        row = dict(original)
        if type(row.get('indexed')) is bool and inspection_time(row.get('checkedAt')) is None:
            row.update(indexed=None, attemptStatus='failed', reason='URL 검사 시각 미확인')
        if type(row.get('indexed')) is bool:
            row.setdefault('lastIndexed', row['indexed'])
            row.setdefault('lastSuccessAt', row.get('checkedAt'))
            row.setdefault('attemptAt', row.get('checkedAt'))
            row.setdefault('attemptStatus', 'verified')
        else:
            # Older collectors called an HTTP error checkedAt. It is an attempt, not evidence.
            row.setdefault('attemptAt', row.get('checkedAt'))
            row.setdefault('attemptStatus', 'failed')
            if not row.get('lastSuccessAt'):
                row.pop('checkedAt', None)
        row.setdefault('source', previous.get('source'))
        known[row['url']] = row
    return known


def inspection_targets(posts, previous, limit, now=None, ui=False):
    now = now or datetime.now(timezone.utc)
    known = inspection_rows(previous, posts)
    candidates = []
    for position, url in enumerate(posts.get('urls', [])):
        row = known.get(url, {})
        if inspection_current(row, now, 24):
            continue
        retry = inspection_time(row.get('retryAt'))
        permission_error = '403' in (row.get('reason') or '')
        if retry and retry > now and not (ui and permission_error):
            continue
        has_success = type(row.get('lastIndexed')) is bool and inspection_time(row.get('lastSuccessAt')) is not None
        # Never measured first. Ties use the oldest public inventory entries, not newest posts forever.
        candidates.append(((int(has_success), row.get('attemptAt') or '', -position), url))
    return [url for _, url in sorted(candidates)[:limit]]


def failed_inspection(url, previous, reason, now=None, retry_minutes=30):
    now = now or datetime.now(timezone.utc)
    row = dict(previous)
    if type(row.get('indexed')) is bool:
        row.update(lastIndexed=row['indexed'], lastSuccessAt=row.get('checkedAt'))
    row.update(url=url, indexed=None, attemptAt=now.isoformat(), attemptStatus='failed', reason=reason,
               retryAt=(now + timedelta(minutes=retry_minutes)).isoformat())
    if not row.get('lastSuccessAt'):
        row.pop('checkedAt', None)
    return row


def inspection_summary(posts, previous, now=None):
    now = now or datetime.now(timezone.utc)
    known = inspection_rows(previous, posts)
    measured = [row for row in known.values() if inspection_current(row, now)]
    ever = [row for row in known.values() if type(row.get('lastIndexed')) is bool
            and inspection_time(row.get('lastSuccessAt')) and inspection_time(row['lastSuccessAt']) <= now]
    stale = [row for row in ever if type(row.get('indexed')) is bool and not inspection_current(row, now)]
    failed = [row for row in known.values() if row.get('attemptStatus') == 'failed']
    total = len(set(posts.get('urls', [])))
    complete = bool(posts.get('complete')) and len(measured) == total
    reasons = sorted({row['reason'] for row in failed if row.get('reason')})
    result = {key: value for key, value in previous.items() if key not in ('urls', 'collection')}
    result.update(status='collected' if complete else 'partial' if measured else 'not_collected',
                  indexed=sum(row['indexed'] for row in measured) if measured else None,
                  inspected=len(measured), inventoryTotal=posts.get('total'), complete=complete,
                  checkedAt=now.isoformat(), urls=list(known.values()), reason=' · '.join(reasons) or result.get('apiReason'))
    result['collection'] = {'total': total, 'currentInspected': len(measured), 'everInspected': len(ever),
                            'staleInspected': len(stale), 'failed': len(failed),
                            'unresolvedInspected': len(ever) - len(measured) - len(stale),
                            'neverAttempted': total - len(known), 'neverInspected': total - len(ever),
                            'lastAttemptAt': max((row.get('attemptAt') or '' for row in known.values()), default=None)}
    return result


def search_property(site, settings, inspection=False):
    """An apex URL-prefix property never covers the canonical www inventory."""
    property_id = (settings.get('gsc_property') if inspection else None) or settings.get('search_property')
    if not property_id:
        raise ValueError('GSC_PROPERTY_UNCONFIGURED: 실제 공개 주소를 포함하는 GSC 속성 미설정')
    if property_id == 'sc-domain:' + site['site_id']:
        return property_id
    target, prefix = urlparse(site['url']), urlparse(property_id)
    if (prefix.scheme != 'https' or prefix.netloc != target.netloc
            or prefix.username or prefix.password or prefix.query or prefix.fragment
            or prefix.path != '/'):
        raise ValueError('GSC_PROPERTY_SCOPE_MISMATCH: 설정 속성이 실제 공개 주소 범위를 포함하지 않음')
    return property_id


def rotate_inspection_sites(sites, next_domain=None):
    cf = [site for site in sites if site['platform'] == 'cf']
    ids = [site['site_id'] for site in cf]
    cursor = ids.index(next_domain) if next_domain in ids else 0
    return cf[cursor:] + cf[:cursor] + [site for site in sites if site['platform'] != 'cf']


def initial_inspection_domain(sites, previous):
    cf = [site for site in sites if site['platform'] == 'cf']
    if not cf:
        return None
    return min(cf, key=lambda site: (previous.get('sites', {}).get(site['site_id'], {}).get('google', {}).get('collection', {}).get('lastAttemptAt') or '', site['site_id']))['site_id']


def api_property_verified(site, settings):
    try:
        actual = search_property(site, settings, inspection=True)
    except ValueError:
        return False
    return (settings.get('gsc_api_verified_property') == actual
            and settings.get('gsc_api_verified_reader') == settings.get('analytics_reader')
            and bool(settings.get('gsc_api_verified_at')))


def browser_fallback_sites(sites, config, manual=False):
    sites = [site for site in sites if site.get('platform') == 'cf']
    return list(sites) if manual else [site for site in sites
        if not api_property_verified(site, config.get('sites', {}).get(site['site_id'], {}))]


def inspect_urls(session, site, settings, posts, previous, limit, deadline=None):
    try:
        property_id = search_property(site, settings, inspection=True)
    except ValueError as exc:
        result = inspection_summary(posts, previous)
        result.update(apiReason=str(exc), reason=str(exc), apiAttemptStatus='skipped',
                      propertyScopeVerified=False, apiAttemptedCount=0)
        return result
    known = inspection_rows(previous, posts)
    now = datetime.now(timezone.utc)
    previous = dict(previous)
    previous.pop('apiAttemptStatus', None)
    previous['apiBudgetExhausted'] = False
    previous['apiAttemptedCount'] = 0
    if previous.get('property') and previous['property'] != property_id:
        # A prior rejection of another property must not delay the corrected mapping.
        # Preserve per-URL historical evidence; never bypass a retry for this property.
        previous.pop('apiRetryAt', None)
        previous.pop('apiReason', None)
    retry = inspection_time(previous.get('apiRetryAt'))
    if retry and retry > now:
        return inspection_summary(posts, {**previous, 'urls': list(known.values())})
    targets = inspection_targets(posts, previous, limit, now)
    for url in targets:
        remaining = deadline - time.monotonic() if deadline is not None else 25
        if remaining <= 0:
            previous.update(apiBudgetExhausted=True, apiAttemptStatus='deferred_budget')
            break
        try:
            previous['apiAttemptedCount'] += 1
            data = api(session, 'POST', 'https://searchconsole.googleapis.com/v1/urlInspection/index:inspect',
                       {'inspectionUrl': url, 'siteUrl': property_id}, timeout=max(0.1, min(25, remaining)))
            result = data.get('inspectionResult', {}).get('indexStatusResult', {})
            verdict = result.get('verdict')
            checked_at = stamp()
            indexed = True if verdict == 'PASS' else False if verdict in ('FAIL', 'NEUTRAL') else None
            if indexed is None:
                raise ValueError('URL 검사 결과의 색인 판정 미확인')
            known[url] = {'url': url, 'checkedAt': checked_at, 'attemptAt': checked_at,
                          'attemptStatus': 'verified', 'lastSuccessAt': checked_at, 'lastIndexed': indexed,
                          'source': 'Google Search Console URL Inspection', 'verdict': verdict,
                          'indexed': indexed,
                          'coverageState': result.get('coverageState'),
                          'lastCrawlTime': result.get('lastCrawlTime'),
                          'googleCanonical': result.get('googleCanonical')}
        except Exception as exc:
            permission = str(exc) == '원천 API HTTP 403'
            reason = ('GSC_PROPERTY_ACCESS_DENIED: 실제 공개 URL의 설정 속성 접근 거절 '
                      '(HTTP 403; 사용자 권한 및 속성 범위 확인 필요)') if permission else safe_reason(exc)
            known[url] = failed_inspection(url, known.get(url, {}), reason)
            if permission:
                # A property-level rejection is not 10 independent URL failures.
                previous.update(apiReason=reason, apiRetryAt=(datetime.now(timezone.utc) + timedelta(hours=6)).isoformat())
                break
    return inspection_summary(posts, {**previous, 'source': previous.get('source') or 'Google Search Console URL Inspection',
                                      'property': property_id, 'propertyScopeVerified': True,
                                      'urls': list(known.values())})


@observed_operation('metrics', 'traffic-collection')
def collect_traffic(session, site, settings):
    property_id = str(settings.get('ga4_property', ''))
    if not property_id.isdigit():
        return unknown('GA4 속성 ID 미설정')
    # Use the actual GA4 property timezone from report metadata, not the OS date.
    host = urlparse(site['url']).hostname
    host_filter = {'filter': {'fieldName': 'hostName', 'stringFilter': {
        'matchType': 'FULL_REGEXP', 'value': '(www\\.)?' + site['site_id'].replace('.', '\\.'),
        'caseSensitive': False}}}
    body = {'dateRanges': [{'startDate': '8daysAgo', 'endDate': '2daysAgo'}],
            'dimensions': [{'name': 'date'}],
            'metrics': [{'name': 'sessions'}, {'name': 'screenPageViews'}, {'name': 'totalUsers'}],
            'dimensionFilter': host_filter, 'limit': 100}
    url = f'https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport'
    result = api(session, 'POST', url, body)
    if [h.get('name') for h in result.get('metricHeaders', [])] != ['sessions', 'screenPageViews', 'totalUsers']:
        raise ValueError('GA4 지표 헤더 미확인; 빈 응답을 0으로 해석하지 않습니다')
    metadata = result.get('metadata', {})
    source_timezone = metadata.get('timeZone')
    if not source_timezone:
        raise ValueError('GA4 보고서 시간대 미확인')
    source_today = datetime.now(ZoneInfo(source_timezone)).date()
    end, start = source_today - timedelta(days=2), source_today - timedelta(days=8)
    rows = {datetime.strptime(r['dimensionValues'][0]['value'], '%Y%m%d').date().isoformat():
            {k: int(v['value']) for k, v in zip(('sessions', 'pageViews', 'users'), r['metricValues'])}
            for r in result.get('rows', [])}
    points = [{'day': (start + timedelta(days=i)).isoformat(),
               **rows.get((start + timedelta(days=i)).isoformat(), {'sessions': 0, 'pageViews': 0, 'users': 0})}
              for i in range(7)]
    limited = bool(metadata.get('subjectToThresholding') or metadata.get('dataLossFromOtherRow')
                   or metadata.get('samplingMetadatas'))
    bridge_filter = {'filter': {'fieldName': 'sessionSource', 'stringFilter': {
        'matchType': 'FULL_REGEXP', 'value': '.*naver.*', 'caseSensitive': False}}}
    referral = {**body, 'metrics': [{'name': 'sessions'}],
                'dimensionFilter': {'andGroup': {'expressions': [host_filter, bridge_filter]}}}
    naver = api(session, 'POST', url, referral)
    naver_meta = naver.get('metadata', {})
    if [h.get('name') for h in naver.get('metricHeaders', [])] != ['sessions'] or naver_meta.get('timeZone') != source_timezone:
        raise ValueError('네이버 출처 GA4 보고서의 지표 또는 시간대 미확인')
    referral_limited = any(naver_meta.get(k) for k in ('subjectToThresholding', 'dataLossFromOtherRow', 'samplingMetadatas'))
    return {'status': 'partial' if limited else 'collected', 'complete': not limited,
            'source': 'GA4 Data API', 'property': property_id, 'hostname': host,
            'start': start.isoformat(), 'end': end.isoformat(), 'timezone': source_timezone,
            'sessions': sum(p['sessions'] for p in points) if not limited else None,
            'pageViews': sum(p['pageViews'] for p in points) if not limited else None,
            'naverReferralSessions': None if referral_limited else sum(int(r['metricValues'][0]['value']) for r in naver.get('rows', [])),
            'referralScope': 'sessionSource에 naver 포함; 계정별 브릿지 클릭수와 다름',
            'points': points, 'checkedAt': stamp(), 'sourceRef': url}


def request_indexing(session, site, settings, urls, sitemap, *, indexnow=True):
    """Submit discovery hints; never represent an accepted request as indexed."""
    from dashboard.indexing_submissions import canonical_url
    excluded = [url for url in urls if is_dummy_rescue_url(url)]
    urls = [canonical_url(site, url) for url in urls if not is_dummy_rescue_url(url)]
    sitemap_blocked = bool(sitemap.get('excludedDummyCount') or any(is_dummy_rescue_url(u) for u in sitemap.get('locations', [])))
    result = {'requestedAt': stamp(), 'urls': urls, 'excludedDummyCount': len(excluded), 'excludedDummyUrls': excluded}
    if session and sitemap.get('status') == 'available' and not sitemap_blocked:
        try:
            property_id = settings.get('gsc_property') or settings.get('search_property') or ('sc-domain:' + site['site_id'])
            endpoint = 'https://www.googleapis.com/webmasters/v3/sites/' + quote(property_id, safe='')
            put_endpoint = endpoint + '/sitemaps/' + quote(sitemap['url'], safe='')
            submitted_ok = False
            try:
                api(session, 'PUT', put_endpoint)
                submitted_ok = True
            except Exception:
                # Only the exact canonical sitemap on this property is evidence.
                # A successful empty list or another host's sitemap proves nothing.
                sm_list = api(session, 'GET', endpoint + '/sitemaps')
                paths = [item.get('path') for item in sm_list.get('sitemap', []) if isinstance(item, dict)]
                submitted_ok = sitemap['url'] in paths
            if submitted_ok:
                result['google'] = {'status': 'submitted', 'method': 'sitemap', 'property': property_id,
                                    'sitemap': sitemap['url'], 'indexed': None}
            else:
                result['google'] = unknown('Google 사이트맵 제출 확인 필요')
        except Exception as exc:
            result['google'] = unknown(safe_reason(exc))
    else:
        result['google'] = unknown('Google 인증 또는 정상 사이트맵이 필요합니다')
    if sitemap_blocked:
        result['google'] = {'status': 'held_dummy_sitemap', 'reason': '공개 사이트맵에 테스트 URL이 남아 있어 제출을 보류합니다. 원본 수정·배포가 필요합니다.', 'indexed': None}
    if indexnow:
        from dashboard.indexing_submissions import submit_indexnow
        result['naver'] = submit_indexnow(site, settings, urls, providers=('naver',), client=requests)['naver']
    return result


def discover_indexnow_keys():
    """Read existing per-site keys; never change website settings or print secrets."""
    keys = read_json(ROOT / 'cf_posting' / 'data' / 'secure' / 'cf_blog_keys.json')
    existing_cfg_sites = read_json(CONFIG).get('sites', {})
    cf_sites = [s for s in inventory() if s.get('platform') == 'cf']

    def _verify_one(site):
        dom = site['site_id']
        value = keys.get(dom)
        existing_site_cfg = existing_cfg_sites.get(dom, {})
        key = None
        if isinstance(value, str) and value:
            try:
                response = requests.get(site['url'].rstrip('/') + '/api/settings',
                                        headers={'x-api-key': value, 'Authorization': 'Bearer ' + value},
                                        timeout=10, allow_redirects=False)
                if response.status_code == 200:
                    key = response.json().get('settings', {}).get('indexnow_key')
            except Exception:
                key = None
        if not isinstance(key, str) or not key:
            key = existing_site_cfg.get('indexnow_key')
        if not isinstance(key, str) or not key:
            if not isinstance(value, str) or not value:
                return dom, {'site': dom, 'status': 'missing_site_api_key'}, None
            return dom, {'site': dom, 'status': 'unavailable', 'reason': '기존 사이트 IndexNow 키가 없습니다'}, None
        try:
            location = owned_url(site, existing_site_cfg.get('indexnow_key_location') or (site['url'].rstrip('/') + '/' + key + '.txt'))
            public = requests.get(location, timeout=8, allow_redirects=False)
            if public.status_code != 200 or public.text.strip() != key:
                raise ValueError('공개 소유확인 키 파일 불일치')
            return dom, {'site': dom, 'status': 'verified'}, (key, location)
        except Exception as exc:
            return dom, {'site': dom, 'status': 'unavailable', 'reason': safe_reason(exc)}, None

    results = []
    verified_updates = {}
    if len(cf_sites) > 2:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            for dom, res_item, upd in pool.map(_verify_one, cf_sites):
                results.append(res_item)
                if upd:
                    verified_updates[dom] = upd
                print('IndexNow key', dom, res_item['status'], flush=True)
    else:
        for site in cf_sites:
            dom, res_item, upd = _verify_one(site)
            results.append(res_item)
            if upd:
                verified_updates[dom] = upd
            print('IndexNow key', dom, res_item['status'], flush=True)

    if verified_updates:
        with collector_lock() as acquired:
            if not acquired:
                raise RuntimeError('설정 저장 잠금 충돌; 다음 실행에서 재확인')
            config = read_json(CONFIG)
            for dom, (key, location) in verified_updates.items():
                config.setdefault('sites', {}).setdefault(dom, {}).update(
                    indexnow_key=key, indexnow_key_location=location)
            atomic_write(CONFIG, config)
    return results


def safe_reason(exc):
    if isinstance(exc, (ValueError, RuntimeError)):
        return str(exc)[:180]
    return type(exc).__name__ + ': 원천 연결 실패 (비밀정보 생략)'


def browser_recover(account_id, individual_limit=10):
    if not account_id.isalnum():
        raise ValueError('Invalid indexing account identifier')
    with collector_lock(DATA / ('gsc-recovery-' + account_id + '.lock')) as acquired:
        if not acquired:
            return {'status': 'already_running', 'account': account_id}
        with collector_lock(DATA / ('gsc-ui-' + account_id + '.lock')) as browser_acquired:
            if not browser_acquired:
                return {'status': 'browser_busy', 'account': account_id}
            return _browser_recover(account_id, individual_limit)


def parse_browser_inspection(text, url):
    """Require the inspected URL and an explicit Google verdict, never a search report row."""
    from urllib.parse import unquote
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    verdicts = ('URL이 Google에 등록되어 있음', 'URL is on Google',
                'URL이 Google에 등록되어 있지 않음', 'URL is not on Google')
    matches = [i for i, line in enumerate(lines) if unquote(line) == unquote(url)
               and any(candidate in verdicts for candidate in lines[i + 1:i + 14])]
    if not matches:
        raise ValueError('URL 검사 화면의 실제 검사 주소 불일치')
    section = lines[matches[-1] + 1:]
    positive = any(line in ('URL이 Google에 등록되어 있음', 'URL is on Google') for line in section)
    negative = any(line in ('URL이 Google에 등록되어 있지 않음', 'URL is not on Google') for line in section)
    if positive == negative:
        raise ValueError('Google URL 검사 판정 미확인')

    def value_after(label, url_only=False):
        for index, line in enumerate(section):
            if line == label:
                for candidate in section[index + 1:index + 8]:
                    if url_only and candidate.startswith('https://'):
                        return candidate
                    if not url_only and candidate not in ('info', '', '', 'check_circle', 'check_circle_filled'):
                        return candidate
        return None

    coverage = next((line for line in section if line.startswith('페이지 색인이 생성되지 않음:')
                     or line == '페이지 색인이 생성됨'), None)
    return {'indexed': positive, 'coverageState': coverage,
            'googleCanonical': value_after('Google에서 선택한 표준 URL', True),
            'userCanonical': value_after('사용자 선언 표준 URL', True),
            'lastCrawlTimeDisplay': value_after('최근 크롤링')}


def authorized_gsc_request_mode(config, manual=False, requested=None):
    options = config.get('url_inspection', {})
    authorized = (options.get('mode') == 'authorized_request_owner_ui'
                  and options.get('request_indexing_authorized') is True
                  and bool(options.get('request_indexing_accounts')))
    if requested is True and not (manual or authorized):
        raise ValueError('Indexing requests require explicit authorization')
    return authorized if requested is None else requested is True


@observed_operation('metrics', 'metrics-collection')
def collect_browser_inspections(config, sites, limit=None, seconds=None, manual=False, request_mode=None):
    """Read-only default; explicitly authorized scheduled/manual requests share quota."""
    request_mode = authorized_gsc_request_mode(config, manual, request_mode)
    options = config.get('url_inspection', {})
    from dashboard.indexing_submissions import gsc_budget
    if request_mode and not any(gsc_budget(a)['remaining'] for a in options.get('request_indexing_accounts', options.get('browser_accounts', []))):
        return {'status': 'daily_budget_exhausted', 'attempted': 0, 'completed': 0, 'requestMode': True}
    sites = browser_fallback_sites(sites, config, manual=manual or request_mode)
    if not sites:
        return {'status': 'skipped_api_verified', 'attempted': 0}
    enabled = options.get('browser_accounts', [])
    limit = min(36, max(0, int(limit if limit is not None else options.get('ui_limit', 10))))
    seconds = min(420, max(15, int(seconds if seconds is not None else options.get('ui_budget_seconds', 180))))
    if not enabled or not limit:
        return
    from playwright.sync_api import sync_playwright
    from common.browser_session import _runtime
    from urllib.parse import parse_qs
    from gsc_ui_state import paused, state as ui_state, check_response, check_text, mark_success

    def save(account_id, progress, site_id=None, row=None):
        for _ in range(20):
            with collector_lock() as acquired:
                if acquired:
                    document = read_json(SNAPSHOT)
                    automation = document.setdefault('inspectionAutomation', {'accounts': {}})
                    automation['accounts'][account_id] = dict(progress)
                    automation.update(status=progress['status'], checkedAt=stamp())
                    if row is not None:
                        record = document.get('sites', {}).get(site_id)
                        if record and row['url'] in record.get('posts', {}).get('urls', []):
                            previous = record.get('google', {})
                            known = inspection_rows(previous, record['posts'])
                            known[row['url']] = row
                            previous = {**previous, 'source': 'Google URL Inspection (API / owner UI)', 'urls': list(known.values())}
                            record['google'] = inspection_summary(record['posts'], previous)
                    document['checkedAt'] = stamp()
                    atomic_write(SNAPSHOT, document)
                    return
            time.sleep(0.1)
        raise RuntimeError('URL 검사 결과 저장 잠금 대기 초과')

    for account_id in enabled:
        if not isinstance(account_id, str) or not account_id.isalnum():
            raise ValueError('Invalid inspection account identifier')
        if paused(account_id):
            shared=ui_state(account_id)
            old=read_json(SNAPSHOT).get('inspectionAutomation',{}).get('accounts',{}).get(account_id,{})
            save(account_id,{**old,'status':'backoff','reason':shared.get('reason'),
                             'nextRetryAt':shared.get('nextRetryAt'),'attempted':0,'completed':0})
            continue
        account = config.get('gsc_accounts', {}).get(account_id, {})
        account_request_mode = request_mode and (manual or account_id in options.get('request_indexing_accounts', []))
        allowed = [site for site in sites if site.get('platform') == 'cf' and site['site_id'] in account.get('sites', [])]
        document = read_json(SNAPSHOT)
        # Only permission/unconfigured API properties need the owner UI fallback.
        allowed = [site for site in allowed if manual or account_request_mode or (
            document.get('sites', {}).get(site['site_id'], {}).get('google', {}).get('apiReason')
            or '403' in (document.get('sites', {}).get(site['site_id'], {}).get('google', {}).get('reason') or ''))]
        if not allowed:
            continue
        old_progress = document.get('inspectionAutomation', {}).get('accounts', {}).get(account_id, {})
        retry = inspection_time(old_progress.get('nextRetryAt'))
        if retry and retry > datetime.now(timezone.utc):
            continue
        with collector_lock(DATA / ('gsc-ui-' + account_id + '.lock')) as acquired:
            if not acquired:
                save(account_id, {**old_progress, 'status': 'browser_busy', 'lastRunAt': stamp(),
                                  'attempted': 0, 'completed': 0, 'maxUrls': limit, 'budgetSeconds': seconds,
                                  'reason': '전용 계정 브라우저를 다른 수집 작업이 사용 중입니다',
                                  'nextRetryAt': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
                continue
            progress = {'status': 'running', 'cursor': int(old_progress.get('cursor', 0)) % len(allowed),
                        'attempted': 0, 'completed': 0, 'maxUrls': limit, 'budgetSeconds': seconds,
                        'lastRunAt': stamp(), 'lastAttemptAt': None}
            save(account_id, progress)
            page, original_page = None, None
            started = time.monotonic()
            try:
                directory = Path(account.get('browser_dir', 'C:/99_포터블브라우저/CentBrowserPotable_' + account_id))
                _runtime(int(account['cdp']), str(directory / 'chrome.exe'), str(directory / 'User Data'))
                with sync_playwright() as playwright:
                    browser = playwright.chromium.connect_over_cdp('http://127.0.0.1:' + str(account['cdp']), timeout=10000)
                    context = browser.contexts[0]
                    for candidate in context.pages:
                        try:
                            if candidate.evaluate('document.hasFocus()'):
                                original_page = candidate
                                break
                        except Exception:
                            pass
                    page = context.new_page()
                    try:
                        page.set_default_timeout(5000)
                        if account.get('expected_ip'):
                            with ego_action('navigate', 'metrics-browser'):
                                page.goto('https://api.ipify.org?format=json', wait_until='domcontentloaded', timeout=15000)
                            if json.loads(page.locator('body').inner_text())['ip'] != account['expected_ip']:
                                raise ValueError('색인 계정의 전용 출구 IP가 일치하지 않습니다')
                        with ego_action('navigate', 'metrics-browser'):
                            response=page.goto('https://search.google.com/search-console', wait_until='domcontentloaded', timeout=15000)
                        check_response(account_id,response)
                        check_text(account_id,page.locator('body').inner_text())
                        identities = page.locator('a[aria-label]').evaluate_all("els=>els.map(e=>e.getAttribute('aria-label'))")
                        if not any(account.get('email') and account['email'] in (label or '') for label in identities):
                            raise ValueError('전용 색인 계정 로그인이 일치하지 않습니다')
                        empty_visits = 0
                        while progress['attempted'] < limit and time.monotonic() - started < seconds - 5:
                            request_budget = gsc_budget(account_id) if account_request_mode else None
                            if request_budget and request_budget['remaining'] == 0:
                                progress['status'] = 'daily_budget_exhausted'
                                break
                            index = progress['cursor']
                            site = allowed[index]
                            progress['cursor'] = (index + 1) % len(allowed)
                            current = read_json(SNAPSHOT).get('sites', {}).get(site['site_id'], {})
                            posts, previous = current.get('posts', {}), current.get('google', {})
                            urls = inspection_targets(posts, previous, 1, ui=True) if posts.get('status') in ('collected', 'partial') else []
                            if account_request_mode:
                                missing = {r['url'] for r in previous.get('urls', []) if r.get('indexed') is False}
                                urls = [u for u in posts.get('urls', []) if u in missing and u not in request_budget['recentUrls']
                                        and not is_dummy_rescue_url(u)][:1]
                            if not urls:
                                empty_visits += 1
                                if empty_visits >= len(allowed):
                                    break
                                continue
                            empty_visits = 0
                            url = urls[0]
                            progress['attempted'] += 1
                            progress['lastAttemptAt'] = stamp()
                            row = inspection_rows(previous, posts).get(url, {})
                            try:
                                property_url = site['url'].rstrip('/') + '/'
                                with ego_action('navigate', 'metrics-browser'):
                                    response=page.goto('https://search.google.com/search-console?resource_id=' + quote(property_url, safe=''),
                                              wait_until='domcontentloaded', timeout=min(15000, int((seconds - (time.monotonic() - started)) * 1000)))
                                check_response(account_id,response)
                                check_text(account_id,page.locator('body').inner_text())
                                box = page.locator('input[aria-label*="URL 검사"]').first
                                box.wait_for(state='visible', timeout=5000)
                                with ego_action('type', 'metrics-browser'):
                                    box.fill(url)
                                with ego_action('press', 'metrics-browser'):
                                    box.press('Enter')
                                deadline = min(started + seconds, time.monotonic() + 35)
                                proof = None
                                while time.monotonic() < deadline:
                                    text = page.locator('body').inner_text()
                                    check_text(account_id,text)
                                    if any(value in text.lower() for value in ('unusual traffic', 'captcha', '자동화된 쿼리', '할당량 초과', '요청 한도')):
                                        raise ValueError('Google 검사 제한 또는 계정 확인 필요')
                                    actual_property = parse_qs(urlparse(page.url).query).get('resource_id')
                                    if '/inspect' in page.url and actual_property == [property_url]:
                                        try:
                                            proof = parse_browser_inspection(text, url)
                                            break
                                        except ValueError:
                                            pass
                                    page.wait_for_timeout(400)
                                if proof is None:
                                    raise ValueError('Google URL 검사 결과 대기 시간 초과')
                                checked_at = stamp()
                                row = {'url': url, **proof, 'source': 'Google Search Console UI', 'account': account_id,
                                       'property': property_url, 'checkedAt': checked_at, 'attemptAt': checked_at,
                                       'attemptStatus': 'verified', 'lastIndexed': proof['indexed'], 'lastSuccessAt': checked_at}
                                progress['completed'] += 1
                                mark_success(account_id)
                                if account_request_mode and proof['indexed'] is False:
                                    row['indexingRequest'] = request_inspected_url(page, account_id, site, url, row)
                                    if row['indexingRequest']['status'] in ('quota_exceeded', 'request_unconfirmed'):
                                        progress.update(status='backoff', reason=row['indexingRequest']['status'],
                                            nextRetryAt=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
                            except Exception as exc:
                                reason = safe_reason(exc)
                                row = failed_inspection(url, row, reason)
                                if paused(account_id):
                                    shared=ui_state(account_id)
                                    progress.update(status='backoff',reason=shared.get('reason'),nextRetryAt=shared.get('nextRetryAt'))
                                if reason == 'Google 검사 제한 또는 계정 확인 필요':
                                    progress.update(status='backoff', reason=reason,
                                                    nextRetryAt=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
                            save(account_id, progress, site['site_id'], row)
                            if progress['status'] == 'backoff':
                                break
                    finally:
                        if page and not page.is_closed():
                            page.close()
                        if original_page and not original_page.is_closed():
                            original_page.bring_to_front()
            except Exception as exc:
                progress.update(status='error', reason=safe_reason(exc),
                                nextRetryAt=(datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat())
                if paused(account_id):
                    shared=ui_state(account_id)
                    progress.update(status='backoff',reason=shared.get('reason'),nextRetryAt=shared.get('nextRetryAt'))
            if progress['status'] == 'running':
                progress['status'] = 'completed' if progress['attempted'] == progress['completed'] else 'partial'
            progress.update(elapsedSeconds=round(time.monotonic() - started, 1), finishedAt=stamp())
            save(account_id, progress)


def request_inspected_url(page, account_id, site, url, proof):
    """Bounded authorized UI operation; no live test, reclick, or CAPTCHA bypass."""
    from dashboard.indexing_submissions import reserve_gsc_request, complete_gsc_request, observe_gsc_pending
    text = page.locator('body').inner_text()
    if any(value in text for value in ('색인 생성 요청됨', '색인 생성이 요청됨', 'Indexing requested')):
        return observe_gsc_pending(account_id, site, url, {'source': 'Google Search Console UI', 'pending': True})
    reservation = reserve_gsc_request(account_id, site, url, authorized=True, evidence=proof)
    if reservation['status'] != 'reserved':
        return reservation
    outcome = 'request_unconfirmed'
    try:
        with ego_action('click', 'metrics-browser'):
            page.get_by_text('색인 생성 요청', exact=True).filter(visible=True).first.click(timeout=8000)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            text = page.locator('body').inner_text()
            if any(value in text for value in ('색인 생성 요청됨', '색인 생성이 요청됨', 'Indexing requested')):
                outcome = 'requested'; break
            if any(value in text for value in ('할당량 초과', '일일 할당량', '요청 한도', 'Quota exceeded')):
                outcome = 'quota_exceeded'; break
            if any(value in text.lower() for value in ('captcha', 'unusual traffic', '자동화된 쿼리')):
                break
            page.wait_for_timeout(500)
    except Exception:
        pass
    return complete_gsc_request(reservation['id'], outcome,
        evidence={'source': 'Google Search Console UI', 'url': url, 'outcome': outcome})


def _browser_recover(account_id, individual_limit=10):
    """Use only the configured account's existing browser; retain its session."""
    from playwright.sync_api import sync_playwright
    config = read_json(CONFIG)
    account = config.get('gsc_accounts', {}).get(account_id)
    if not account:
        raise ValueError('전용 색인 계정 설정이 없습니다')
    history = read_json(DATA / 'indexing-recovery.json', {'events': []})
    legacy = read_json(history['historicalLog'], []) if history.get('historicalLog') else []
    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    successes = {(e.get('url'), e.get('at')) for e in history['events']
                 if e.get('outcome') == 'requested' and e.get('account') == account_id
                 and e.get('at', '').startswith(today)}
    successes.update((e.get('url'), e.get('requestedAt')) for e in legacy
                     if e.get('account') == account_id and e.get('outcome') in ('requested', 'already_pending')
                     and e.get('requestedAt', '').startswith(today))
    from dashboard.indexing_submissions import gsc_budget, canonical_url
    remaining = min(individual_limit, gsc_budget(account_id)['remaining'])
    snapshot = read_json(SNAPSHOT)
    sites = [s for s in inventory() if s['site_id'] in account['sites']]

    def save_event(site_id, event):
        event.update(account=account_id, at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat())
        for _ in range(20):
            with collector_lock() as acquired:
                if acquired:
                    journal = read_json(DATA / 'indexing-recovery.json', {'events': []})
                    journal['events'].append(event)
                    atomic_write(DATA / 'indexing-recovery.json', journal)
                    if event['kind'] == 'url' and event['outcome'] == 'requested' and journal.get('historicalLog'):
                        legacy_path = Path(journal['historicalLog'])
                        rows = read_json(legacy_path, [])
                        if not any(r.get('url') == event['url'] and r.get('requestedAt') == event['at'] for r in rows):
                            rows.append({'url': event['url'], 'site': 'https://www.' + site_id + '/',
                                         'blog': site_id, 'account': account_id, 'requestedAt': event['at'],
                                         'outcome': 'requested', 'source': 'BaroLab dashboard recovery'})
                            atomic_write(legacy_path, rows)
                    current = read_json(SNAPSHOT)
                    record = current['sites'][site_id]
                    record['checkedAt'] = stamp()
                    if event['kind'] == 'sitemap' and event['outcome'] == 'submitted':
                        request = record.get('indexingRequest') or {}
                        request.update(urls=record['posts']['urls'], requestedAt=event['at'])
                        request['google'] = {'status': 'submitted', 'method': 'sitemap_ui',
                                             'account': account_id, 'submittedAt': event['at'], 'indexed': None}
                        record['indexingRequest'] = request
                    elif event['kind'] == 'url' and event.get('indexed') is not None:
                        known = record.get('google', {}).get('urls', [])
                        known = [r for r in known if r['url'] != event['url']]
                        known.append({'url': event['url'], 'indexed': event['indexed'],
                                      'checkedAt': stamp(), 'outcome': event['outcome']})
                        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                        measured = [r for r in known if r.get('indexed') is not None
                                    and datetime.fromisoformat(r['checkedAt']) > cutoff]
                        record['google'] = {'status': 'partial', 'source': 'Google Search Console UI',
                            'account': account_id, 'indexed': sum(r['indexed'] is True for r in measured),
                            'inspected': len(measured), 'inventoryTotal': record['posts'].get('total'),
                            'complete': len(measured) == record['posts'].get('total'),
                            'checkedAt': stamp(), 'urls': known}
                    atomic_write(SNAPSHOT, current)
                    print(account_id, site_id, event['kind'], event['outcome'], flush=True)
                    return
            time.sleep(0.2)
        raise RuntimeError('색인 결과 저장 잠금 대기 초과')

    def wait_text(page, phrases, seconds):
        deadline = time.monotonic() + seconds
        text = ''
        while time.monotonic() < deadline:
            text = page.locator('body').first.inner_text()
            if any(phrase in text for phrase in phrases):
                return text
            page.wait_for_timeout(500)
        return text

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp('http://127.0.0.1:' + str(account['cdp']))
        page = browser.contexts[0].new_page()
        try:
            if account.get('expected_ip'):
                with ego_action('navigate', 'metrics-browser'):
                    page.goto('https://api.ipify.org?format=json', wait_until='domcontentloaded', timeout=30000)
                actual_ip = json.loads(page.locator('body').first.inner_text())['ip']
                if actual_ip != account['expected_ip']:
                    raise RuntimeError('색인 계정의 전용 출구 IP가 일치하지 않습니다')
            with ego_action('navigate', 'metrics-browser'):
                page.goto('https://search.google.com/search-console', wait_until='domcontentloaded')
            page.wait_for_timeout(1000)
            identities = page.locator('a[aria-label]').evaluate_all("els=>els.map(e=>e.getAttribute('aria-label'))")
            if not any(account['email'] in (identity or '') for identity in identities):
                raise RuntimeError('전용 색인 계정 로그인이 일치하지 않습니다')
            # Bulk discovery comes first, so individual quota does not limit coverage.
            for site in sites:
                dom = site['site_id']
                record = snapshot.get('sites', {}).get(dom, {})
                urls = [u for u in record.get('posts', {}).get('urls', []) if not is_dummy_rescue_url(u)]
                sitemap = record.get('sitemap', {})
                if not urls or sitemap.get('status') != 'available':
                    continue
                if sitemap.get('excludedDummyCount') or any(is_dummy_rescue_url(u) for u in sitemap.get('locations', [])):
                    save_event(dom, {'kind': 'sitemap', 'outcome': 'held_dummy_sitemap'})
                    continue
                previous_request = record.get('indexingRequest') or {}
                previous_google = previous_request.get('google', {})
                if (previous_google.get('status') == 'submitted'
                        and previous_google.get('account') == account_id
                        and set(previous_request.get('urls', [])) == set(urls)):
                    continue
                if sitemap.get('kind') != 'urlset' or not set(urls) <= set(sitemap.get('locations', [])):
                    save_event(dom, {'kind': 'sitemap', 'outcome': 'held_missing_urls'})
                    continue
                property_url = site['url'].rstrip('/') + '/'
                target = 'https://search.google.com/search-console/sitemaps?resource_id=' + quote(property_url, safe='')
                try:
                    with ego_action('navigate', 'metrics-browser'):
                        page.goto(target, wait_until='domcontentloaded', timeout=45000)
                    box = page.get_by_role('textbox', name='사이트맵 URL 입력', exact=True)
                    box.wait_for(state='visible', timeout=10000)
                    before = page.locator('body').first.inner_text()
                    with ego_action('type', 'metrics-browser'):
                        box.fill(urlparse(sitemap['url']).path.lstrip('/'))
                    with ego_action('click', 'metrics-browser'):
                        page.get_by_role('button', name='제출', exact=True).click()
                    text = wait_text(page, ['사이트맵이 제출됨', '사이트맵을 가져올 수 없음', '잘못된 사이트맵'], 45)
                    outcome = 'submitted' if '사이트맵이 제출됨' in text else 'submission_unconfirmed'
                    save_event(dom, {'kind': 'sitemap', 'outcome': outcome, 'sitemap': sitemap['url'],
                                     'coveredPublicUrls': len(urls), 'before': before[-1800:], 'after': text[-1000:]})
                except Exception as exc:
                    save_event(dom, {'kind': 'sitemap', 'outcome': 'error', 'reason': safe_reason(exc)})
            # Round-robin newest public URLs, without repeating recent requests.
            recent = {e.get('url') for e in history['events'] if e.get('outcome') in ('requested', 'pending')
                      and e.get('at', '') >= (datetime.now(ZoneInfo('Asia/Seoul')) - timedelta(days=7)).isoformat()}
            recent.update(e.get('url') for e in legacy if e.get('outcome') in ('requested', 'already_pending')
                          and e.get('requestedAt', '') >= (datetime.now(ZoneInfo('Asia/Seoul')) - timedelta(days=7)).isoformat())
            candidates = [(site, url) for i in range(10) for site in sites
                          for url in snapshot['sites'][site['site_id']].get('posts', {}).get('urls', [])[i:i+1]
                          if url not in recent and not is_dummy_rescue_url(url)
                          and urlparse(url).hostname == urlparse(site['url']).hostname]
            for site, url in candidates:
                if remaining <= 0:
                    break
                try:
                    with ego_action('navigate', 'metrics-browser'):
                        page.goto('https://search.google.com/search-console?resource_id=' + quote(site['url'].rstrip('/') + '/', safe=''), wait_until='domcontentloaded')
                    box = page.locator('input[aria-label*="URL 검사"]').first
                    box.wait_for(state='visible', timeout=10000)
                    with ego_action('type', 'metrics-browser'):
                        box.fill(url)
                    with ego_action('press', 'metrics-browser'):
                        box.press('Enter')
                    text = wait_text(page, ['URL이 Google에 등록되어 있음', 'URL이 Google에 등록되어 있지 않음',
                                            'URL is on Google', 'URL is not on Google'], 90)
                    indexed = ('URL이 Google에 등록되어 있음' in text or 'URL is on Google' in text)
                    missing = ('URL이 Google에 등록되어 있지 않음' in text or 'URL is not on Google' in text)
                    outcome = 'indexed' if indexed and not missing else 'inspection_unconfirmed'
                    if missing and not indexed:
                        outcome = 'not_indexed'
                        if '색인 생성이 요청됨' in text or '색인 생성 요청됨' in text:
                            outcome = 'pending'
                        else:
                            canonical_url(site, url)
                            proof = {'url': url, **parse_browser_inspection(text, url),
                                     'source': 'Google Search Console UI', 'checkedAt': stamp()}
                            request_result = request_inspected_url(page, account_id, site, url, proof)
                            outcome = request_result['status']
                            remaining = min(remaining, gsc_budget(account_id)['remaining'])
                            if outcome in ('quota_exceeded', 'daily_budget_exhausted'):
                                remaining = 0
                    save_event(site['site_id'], {'kind': 'url', 'url': url, 'outcome': outcome,
                                               'indexed': True if outcome == 'indexed' else False if missing else None,
                                               'evidence': text[-2000:]})
                    if outcome == 'request_unconfirmed':
                        break
                except Exception as exc:
                    save_event(site['site_id'], {'kind': 'url', 'url': url, 'outcome': 'error', 'reason': safe_reason(exc)})
        finally:
            # Close only this temporary tab; browser and login sessions stay open.
            page.close()
    return read_json(DATA / 'indexing-recovery.json')


@observed_operation('metrics', 'metrics-collection')
def collect(config_path=CONFIG, site_id=None, request_url=None, limit=3, read_only=False):
    if read_only and request_url:
        raise ValueError('Read-only collection cannot submit indexing requests')
    # Keep the long-running collection lock separate from brief result writes.
    with collector_lock(DATA / 'metrics-run.lock') as acquired:
        if not acquired:
            return {'status': 'already_running'}
        config = read_json(config_path)
        previous = read_json(SNAPSHOT)
        google_error = None
        try:
            submission_session = google_session(config)
        except Exception as exc:
            submission_session, google_error = None, safe_reason(exc)
        session = submission_session
        sites = inventory()
        old_cycle = previous.get('inspectionAutomation', {}).get('apiCycle', {})
        start_domain = old_cycle.get('nextDomain') or initial_inspection_domain(sites, previous)
        ordered = rotate_inspection_sites(sites, start_domain) if not site_id else sites
        cf_order = [site['site_id'] for site in ordered if site['platform'] == 'cf']
        budget_seconds = min(330, max(1, int(config.get('url_inspection', {}).get('api_budget_seconds', 330))))
        api_deadline = time.monotonic() + budget_seconds
        first_deferred = None
        cycle = {'startedAt': stamp(), 'budgetSeconds': budget_seconds, 'perSiteLimit': limit,
                 'status': 'running', 'nextDomain': cf_order[0] if cf_order else None,
                 'visitedDomains': [], 'deferredDomains': []}
        if site_id and not any(s['site_id'] == site_id for s in sites):
            raise ValueError('Unknown inventory site')
        output = {'schema': 'dashboard-metrics-v1', 'checkedAt': stamp(),
                  'sites': previous.get('sites', {}), 'inventorySites': sites}
        for site in ordered:
            if site_id and site['site_id'] != site_id:
                continue
            settings = config.get('sites', {}).get(site['site_id'], {})
            try:
                session = google_session(config, settings)
                google_error = None
            except Exception as exc:
                session, google_error = None, safe_reason(exc)
            old = previous.get('sites', {}).get(site['site_id'], {})
            record = {**old, 'site': site, 'checkedAt': stamp()}
            record['indexingRequest'] = old.get('indexingRequest')
            if site['platform'] != 'cf':
                record.update(posts=unknown('네이버 공개 글 목록 수집 미연결'),
                              google=unknown('네이버 블로그의 GSC 속성 접근 미확인'),
                              traffic=unknown('네이버 블로그 통계 원천 보고서 미연결'))
            else:
                for key, operation in [('posts', lambda: public_inventory(site)),
                                       ('sitemap', lambda: sitemap_status(site, settings))]:
                    try:
                        record[key] = operation()
                    except Exception as exc:
                        record[key] = unknown(safe_reason(exc))
                if record['posts'].get('status') == 'not_collected' and old.get('posts', {}).get('urls'):
                    record['posts'].update(urls=old['posts']['urls'], total=old['posts'].get('total'), complete=False,
                                           lastSuccessAt=old['posts'].get('checkedAt'))
                record['google'] = inspection_summary(record['posts'], old.get('google', {}))
                if not session:
                    record['google']['apiReason'] = google_error
                    record['google']['reason'] = google_error
                if session and record['posts'].get('status') in ('collected', 'partial'):
                    record['google'] = inspect_urls(session, site, settings, record['posts'], old.get('google', {}), limit, deadline=api_deadline)
                try:
                    record['traffic'] = collect_traffic(session, site, settings) if session else unknown(google_error)
                except Exception as exc:
                    record['traffic'] = unknown(safe_reason(exc))
                if request_url:
                    if request_url not in record['posts'].get('urls', []):
                        raise ValueError('Requested URL must be in the verified public post inventory')
                    record['indexingRequest'] = {**(old.get('indexingRequest') or {}),
                        **request_indexing(session or submission_session, site, settings, [request_url], record['sitemap'])}
                elif not read_only and settings.get('auto_submit', True) and record['posts'].get('urls'):
                    old_request = old.get('indexingRequest') or {}
                    current_urls = record['posts']['urls']
                    changed = set(current_urls) != set(old_request.get('urls', []))
                    active_sess = session or submission_session
                    google_pending = active_sess and old_request.get('google', {}).get('status') != 'submitted'
                    naver_pending = settings.get('indexnow_key') and old_request.get('naver', {}).get('status') not in ('ping_accepted', 'accepted_pending_key_check', 'submitted')
                    if changed or google_pending or naver_pending:
                        new_request = request_indexing(active_sess, site, settings, current_urls, record['sitemap'])
                        if old_request.get('google', {}).get('status') == 'submitted' and new_request['google']['status'] != 'submitted':
                            new_request['google']['previousSubmission'] = old_request['google']
                        record['indexingRequest'] = {**old_request, **new_request}
                cycle['visitedDomains'].append(site['site_id'])
                if record['google'].get('apiBudgetExhausted'):
                    cycle['deferredDomains'].append(site['site_id'])
                    next_id = cf_order[(cf_order.index(site['site_id']) + 1) % len(cf_order)]
                    first_deferred = first_deferred or (next_id if record['google'].get('apiAttemptedCount', 0) else site['site_id'])
                if cf_order and not site_id:
                    cycle['nextDomain'] = first_deferred or cf_order[(cf_order.index(site['site_id']) + 1) % len(cf_order)]
            for _ in range(20):
                with collector_lock() as write_lock:
                    if write_lock:
                        latest = read_json(SNAPSHOT)
                        saved = latest.get('sites', {}).get(site['site_id'], {})
                        old_request = saved.get('indexingRequest') or {}
                        new_request = record.get('indexingRequest') or {}
                        if set(new_request.get('urls', [])) == set(old_request.get('urls', [])):
                            if old_request.get('google', {}).get('status') == 'submitted' and new_request.get('google', {}).get('status') != 'submitted':
                                new_request.setdefault('google', {})['previousSubmission'] = old_request['google']
                        record['indexingRequest'] = {**old_request, **new_request}
                        if 'daum' in saved:
                            record['daum'] = saved['daum']
                        if 'naverInspection' in saved:
                            record['naverInspection'] = saved['naverInspection']
                        latest.update(schema='dashboard-metrics-v1', checkedAt=stamp(), inventorySites=sites)
                        latest.setdefault('inspectionAutomation', {})['apiCycle'] = dict(cycle)
                        latest.setdefault('sites', {})[site['site_id']] = record
                        atomic_write(SNAPSHOT, latest)
                        output = latest
                        break
                time.sleep(0.2)
            else:
                raise RuntimeError('수집 결과 저장 잠금 대기 초과')
        cycle.update(status='partial_budget' if first_deferred else 'completed', finishedAt=stamp())
        ui_result = collect_browser_inspections(config, [site for site in sites if not site_id or site['site_id'] == site_id],
                                                request_mode=False if read_only else None)
        if not read_only:
            from dashboard.indexing_submissions import record_gsc_queue_cycle
            record_gsc_queue_cycle([s['site_id'] for s in sites if not site_id or s['site_id'] == site_id], ui_result)
        with collector_lock() as write_lock:
            if not write_lock:
                raise RuntimeError('API 검사 회차 저장 잠금 대기 초과')
            latest = read_json(SNAPSHOT)
            latest.setdefault('inspectionAutomation', {})['apiCycle'] = cycle
            if ui_result:
                latest['inspectionAutomation']['automaticUi'] = ui_result
            atomic_write(SNAPSHOT, latest)
        # Read-only, bounded exact-URL checks reuse the existing collection schedule.
        collect_naver_inspections(site_id, limit=3)
        return read_json(SNAPSHOT)


def inspect_naver_public_url(url, client=requests):
    """Positive exact-URL public search evidence; absence never proves exclusion."""
    from bs4 import BeautifulSoup
    from content import url_key
    domain = (urlparse(url).hostname or '').removeprefix('www.')
    key = url_key(url, domain)
    if key is None:
        raise ValueError('invalid_public_url')
    query = 'https://search.naver.com/search.naver?where=web&query=' + quote('"' + url + '"', safe='')
    result = {'url': url, 'indexed': None, 'checkedAt': stamp(),
              'source': 'Naver public exact URL search', 'queryUrl': query}
    try:
        response = client.get(query, timeout=20)
        if response.status_code != 200:
            return dict(result, reason='http_' + str(response.status_code))
        if urlparse(response.url).hostname != 'search.naver.com':
            return dict(result, reason='unexpected_redirect')
        soup = BeautifulSoup(response.text, 'html.parser')
        # Exact direct target anchors inside result containers only; never query echoes.
        for container in soup.select('.title_area, .total_tit, .title_link, .link_tit, .api_txt_lines.total_tit'):
            links = [container] if container.name == 'a' else container.select('a[href]')
            for link in links:
                href = link.get('href', '')
                if url_key(href, domain) == key:
                    return dict(result, indexed=True, matchedUrl=href,
                                resultTitle=link.get_text(' ', strip=True)[:300], reason='exact_result_observed')
        return dict(result, reason='exact_result_not_observed')
    except requests.RequestException as exc:
        return dict(result, reason=type(exc).__name__)


@observed_operation('metrics', 'metrics-collection')
def collect_naver_inspections(site_id=None, limit=3):
    """Bounded read-only search; merge only per-URL evidence under collector lock."""
    if not 1 <= limit <= 5:
        raise ValueError('naver_inspection_limit_1_to_5')
    from content import fresh
    document = read_json(SNAPSHOT)
    targets = []
    now = datetime.now(timezone.utc)
    for domain, record in document.get('sites', {}).items():
        if record.get('site', {}).get('platform') != 'cf' or (site_id and domain != site_id):
            continue
        old = {row.get('url'): row for row in record.get('naverInspection', {}).get('urls', [])}
        for url in record.get('posts', {}).get('urls', []):
            if fresh(old.get(url, {}).get('checkedAt'), now, 26):
                continue
            targets.append((old.get(url, {}).get('checkedAt') or '', domain, url))
    results = []
    for _, domain, url in sorted(targets)[:limit]:
        results.append((domain, inspect_naver_public_url(url)))
        time.sleep(1)
    with collector_lock() as acquired:
        if not acquired:
            return {'status': 'blocked', 'reason': 'metrics_collector_active', 'persisted': 0}
        latest = read_json(SNAPSHOT)
        for domain, result in results:
            record = latest.get('sites', {}).get(domain)
            if record is None:
                continue
            evidence = record.setdefault('naverInspection', {})
            rows = {r['url']: r for r in evidence.get('urls', [])}
            rows[result['url']] = result
            evidence.update(urls=list(rows.values()), checkedAt=stamp(), source='Naver public exact URL search')
        atomic_write(SNAPSHOT, latest)
    return {'status': 'observed', 'results': [r for _, r in results], 'persisted': len(results)}


def searchadvisor_registration(site, ledger=None):
    """Read the exact canonical property's UI evidence, never IndexNow receipts."""
    state = read_json(ledger or DATA / 'searchadvisor-status.json')
    observed = state.get('sites', {}).get(site.get('site_id'), {})
    exact = observed.get('site', '').rstrip('/') == site.get('url', '').rstrip('/')
    registration = observed.get('registration') or {}
    ownership = observed.get('ownership') or {}
    verified = (exact and registration.get('status') == 'registered' and ownership.get('status') == 'verified'
                and bool(registration.get('evidence')) and bool(ownership.get('evidence')))
    return {'status': 'registered_verified' if verified else 'unconfirmed',
            'registered': True if verified else None, 'ownershipVerified': True if verified else None,
            'property': site.get('url'), 'source': 'SearchAdvisor visible UI ledger',
            'checkedAt': ownership.get('checkedAt') if verified else None,
            'sitemap': observed.get('sitemap') if exact else None,
            'rss': observed.get('rss') if exact else None, 'indexed': None}


def summary(path=SNAPSHOT):
    from content import summary as content_summary
    from revenue import summary as revenue_summary
    from traffic import summary as traffic_summary
    document = read_json(path)
    records = list(document.get('sites', {}).values())
    cutoff = datetime.now(timezone.utc) - timedelta(hours=26)
    for record in records:
        try:
            stale = datetime.fromisoformat(record['checkedAt']) < cutoff
        except (ValueError, KeyError, TypeError):
            stale = True
        if stale:
            record['traffic'] = unknown('수집 이력이 오래되어 재확인 필요')
        if record.get('site', {}).get('platform') == 'cf':
            record['google'] = inspection_summary(record.get('posts', {}), record.get('google', {}))
            record['searchAdvisor'] = searchadvisor_registration(record['site'])
    cf = [r for r in records if r['site']['platform'] == 'cf']
    expected = [s for s in document.get('inventorySites', []) if s['platform'] == 'cf']
    full_inventory = bool(expected) and {r['site']['site_id'] for r in cf} == {s['site_id'] for s in expected}
    known = [r for r in cf if r.get('google', {}).get('inspected')]
    indexed = sum(r['google']['indexed'] for r in known) if known else None
    inspected = sum(r['google']['inspected'] for r in known)
    total = sum(r['posts']['total'] for r in cf) if full_inventory and all(r.get('posts', {}).get('complete') for r in cf) else None
    traffic = [r['traffic'] for r in cf if r.get('traffic', {}).get('status') == 'collected']
    periods = {(t['start'], t['end'], t['timezone']) for t in traffic}
    # A subset can be reported as a subset, never as the entire system's total.
    compatible = bool(traffic) and len(periods) == 1
    analysis = traffic_summary()
    from growth_analysis import summary as growth_summary
    growth = growth_summary()
    collections = [record.get('google', {}).get('collection', {}) for record in cf]
    collection = {key: sum(item.get(key, 0) for item in collections)
                  for key in ('total', 'currentInspected', 'everInspected', 'staleInspected',
                              'unresolvedInspected', 'failed', 'neverAttempted', 'neverInspected')}
    collection['lastAttemptAt'] = max((item.get('lastAttemptAt') or '' for item in collections), default=None)
    collection['automation'] = document.get('inspectionAutomation', {})
    return {'checkedAt': document.get('checkedAt'), 'sites': records,
            'indexing': {'indexed': indexed, 'inspected': inspected, 'inventoryTotal': total,
                         'complete': full_inventory and all(r.get('google', {}).get('complete') for r in cf),
                         'collection': collection,
                         'source': 'GSC URL Inspection', 'scope': 'CF 소유 도메인; 네이버 색인 미측정'},
            'traffic': {'sessions': sum(t['sessions'] for t in traffic) if compatible else None,
                        'pageViews': sum(t['pageViews'] for t in traffic) if compatible else None,
                        'naverReferralSessions': sum(t['naverReferralSessions'] for t in traffic)
                        if compatible and all(t.get('naverReferralSessions') is not None for t in traffic) else None,
                        'connectedSites': len(traffic), 'expectedSites': len(expected),
                        'complete': compatible and full_inventory and len(traffic) == len(expected),
                        'period': next(iter(periods)) if compatible else None},
            'revenue': revenue_summary(), 'trafficAnalysis': analysis, 'growthAnalysis': growth,
            'contentAudit': content_summary(records, analysis,
                naver_requests=read_json(DATA / 'searchadvisor-status.json').get('crawlRequests', []),
                google_requests=read_json(DATA / 'indexing-submissions.json').get('events', []))}


def submit_all_indexnow_and_sitemaps(config_path=CONFIG):
    """Immediately verify sitemap.xml, IndexNow key file, and submit all 16 CF domains to Naver IndexNow & Google Sitemaps."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    config = read_json(config_path)
    snapshot = read_json(SNAPSHOT)
    cf_sites = [s for s in inventory() if s.get('platform') == 'cf']

    def _process_one_site(site):
        dom = site['site_id']
        settings = config.get('sites', {}).get(dom, {})
        old_rec = snapshot.get('sites', {}).get(dom, {})
        try:
            sm = sitemap_status(site, settings)
        except Exception as exc:
            sm = unknown(safe_reason(exc))
        urls = list((old_rec.get('posts') or {}).get('urls') or [])
        if not urls and sm.get('locations'):
            origin = site['url'].rstrip('/')
            urls = [u for u in sm['locations'] if u.rstrip('/') != origin]

        old_google = ((old_rec.get('indexingRequest') or {}).get('google')) or {}
        if old_google.get('status') == 'submitted' and sm.get('status') == 'available':
            site_sess = None
        else:
            try:
                site_sess = google_session(config, settings)
            except Exception:
                site_sess = None

        req = request_indexing(site_sess, site, settings, urls, sm)
        previous = old_google if old_google.get('status') == 'submitted' else old_google.get('previousSubmission')
        if isinstance(previous, dict):
            req.setdefault('google', {})['previousSubmission'] = {k: v for k, v in previous.items() if k != 'previousSubmission'}
        nv_obj = req.get('naver') or {}
        nv_st = nv_obj.get('status', 'unknown')
        nv_http = nv_obj.get('httpStatus', 200 if nv_st == 'submitted' else 0)
        gg_st = (req.get('google') or {}).get('status', 'unknown')
        sm_cnt = len(urls)
        log_line = (
            f"[IndexNow+GSC] {dom} | sitemap=HTTP 200({sm_cnt}건) | "
            f"Naver IndexNow={nv_st}(HTTP {nv_http}, {nv_obj.get('submittedCount', 0)}건 제출) | Google Sitemap={gg_st}"
        )
        return dom, sm, req, log_line

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_process_one_site, s): s['site_id'] for s in cf_sites}
        for fut in as_completed(futs):
            dom, sm, req, log_line = fut.result()
            results.append((dom, sm, req, log_line))

    results.sort(key=lambda x: x[0])
    with collector_lock() as acquired:
        if acquired:
            latest = read_json(SNAPSHOT)
            for dom, sm, req, _ in results:
                rec = latest.setdefault('sites', {}).setdefault(dom, {'site': next(s for s in cf_sites if s['site_id'] == dom)})
                rec['sitemap'] = sm
                rec['indexingRequest'] = req
                rec['checkedAt'] = stamp()
            latest['checkedAt'] = stamp()
            atomic_write(SNAPSHOT, latest)

    for _, _, _, log_line in results:
        print(log_line, flush=True)
    return results


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--inspect-naver', action='store_true')
    parser.add_argument('--read-only', action='store_true', help='Collect evidence without sitemap or IndexNow submissions')
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--site')
    parser.add_argument('--request-indexing', metavar='PUBLIC_URL')
    parser.add_argument('--inspect-limit', type=int, default=3)
    parser.add_argument('--recover-indexing', action='store_true')
    parser.add_argument('--account', help='Configured dedicated GSC account')
    parser.add_argument('--individual-limit', type=int, default=10)
    parser.add_argument('--discover-indexnow', action='store_true')
    args = parser.parse_args()
    if args.read_only and (args.request_indexing or args.recover_indexing or args.discover_indexnow):
        parser.error('--read-only cannot be combined with submission or recovery actions')
    if args.request_indexing and not args.site:
        parser.error('--request-indexing requires --site')
    if not 1 <= args.inspect_limit <= 50:
        parser.error('--inspect-limit must be 1..50')
    if not 0 <= args.individual_limit <= 10:
        parser.error('--individual-limit must be 0..10')
    if args.inspect_naver:
        print(json.dumps(collect_naver_inspections(args.site, min(args.inspect_limit, 5)), ensure_ascii=False))
        sys.exit(0)
    if args.recover_indexing:
        if not args.account:
            parser.error('--recover-indexing requires --account')
        browser_recover(args.account, args.individual_limit)
    if args.discover_indexnow:
        discover_indexnow_keys()
        if args.collect and not args.read_only:
            res_list = submit_all_indexnow_and_sitemaps(args.config)
            total_urls = sum(len((r[2].get('urls') or [])) for r in res_list)
            naver_ok = sum(1 for r in res_list if (r[2].get('naver') or {}).get('status') in ('ping_accepted', 'accepted_pending_key_check'))
            google_ok = sum(1 for r in res_list if (r[2].get('google') or {}).get('status') == 'submitted')
            print(json.dumps({
                'status': 'completed',
                'checkedAt': stamp(),
                'cfDomainsCount': len(res_list),
                'naverIndexNowPingAcceptedDomains': naver_ok,
                'googleSitemapSubmittedDomains': google_ok,
                'totalSubmittedUrls': total_urls,
            }, ensure_ascii=False), flush=True)
            sys.exit(0)
    if args.collect or args.request_indexing:
        collect(args.config, args.site, args.request_indexing, args.inspect_limit, read_only=args.read_only)
    print(json.dumps({k: v for k, v in summary().items() if k != 'sites'}, ensure_ascii=False, indent=2))
