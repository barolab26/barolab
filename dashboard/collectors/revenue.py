"""Monthly revenue evidence. Run --collect on the browser host; NAS only reads it.

Money is kept in its original currency. Only complete, successful report ranges
may establish zero activity for missing historical days.
Credentials and snapshots live outside the public dashboard directory.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import time
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode, urlparse, urljoin, parse_qs, urlunparse
from zoneinfo import ZoneInfo

import requests

from dashboard.collectors.metrics import ROOT, DATA, CONFIG, read_json, atomic_write, collector_lock, stamp, inventory

KST = timezone(timedelta(hours=9))
SNAPSHOT = DATA / 'revenue.json'
CATEGORIES = [('adsense', '구글 애드센스'), ('adpost', '네이버 애드포스트'),
              ('affiliate', '제휴마케팅')]
ADPOST_ACCOUNTS = (('soul5373', 9333), ('soultin', 9334), ('yoon_master', 9335))


class RevenueSourceError(ValueError):
    """Controlled, credential-free reason suitable for the public snapshot."""
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status = status


from common.ego_telemetry import observed_operation, action as ego_action


def revenue_config():
    from dotenv import dotenv_values
    # Preserve project-specific NAVER_<account>_ID/PW keys, then allow explicit
    # environment overrides. Neither keys' values nor authentication responses log.
    cfg = dict(dotenv_values(ROOT / 'cf_posting' / '.env'))
    allowed = ('COUPANG_', 'TOSS_', 'REPLYALBA_', 'TRIP_', 'NAVER_',
               'SJ_GOOGLE_ADSENSE_', 'AAA10291028_GOOGLE_ADSENSE_')
    cfg.update({k: v for k, v in os.environ.items() if k in cfg or k.startswith(allowed)})
    return cfg


def adsense_scope(email, domains, states):
    labels = {'READY': 'READY', 'GETTING_READY': '심사 중',
              'REQUIRES_REVIEW': '검토 필요', 'NEEDS_ATTENTION': '조치 필요',
              'STATE_UNSPECIFIED': '상태 미확인', 'not_registered': '미등록'}
    groups = defaultdict(list)
    for domain in domains:
        groups[states.get(domain, 'STATE_UNSPECIFIED')].append(domain)
    parts = [f'{email} · CF 조회 대상 {len(domains)}개']
    for state, members in groups.items():
        label = labels.get(state, '상태 미확인')
        parts.append(f'{label} {len(members)}개' + (f" ({', '.join(members)})" if state != 'READY' else ''))
    return ' · '.join(parts)


def money(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('유효하지 않은 수익 값')
    return result


def report_day(value):
    text = str(value)
    return datetime.strptime(text, '%Y%m%d' if len(text) == 8 else '%Y-%m-%d').date().isoformat()


def source(key, category, label, currency, scope, **extra):
    return dict(id=key, category=category, label=label, currency=currency,
                scope=scope, daily={}, checkedAt=stamp(), valueKind='estimated',
                status='not_collected', reason='수익 보고서 미연결', **extra)


def response_json(response):
    if not response.ok:
        raise ValueError(f'원천 보고서 HTTP {response.status_code}')
    return response.json()


@observed_operation('metrics', 'revenue-collection')
def adsense(cfg, start, end, sites, prefix='SJ_GOOGLE_ADSENSE'):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    account = cfg[prefix + '_ACCOUNT_ID']
    creds = Credentials(token=None, refresh_token=cfg[prefix + '_REFRESH_TOKEN'],
                        token_uri='https://oauth2.googleapis.com/token',
                        client_id=cfg[prefix + '_CLIENT_ID'],
                        client_secret=cfg[prefix + '_CLIENT_SECRET'])
    with AuthorizedSession(creds) as session:
        base = 'https://adsense.googleapis.com/v2/' + account
        metadata = response_json(session.get(base, timeout=25))
        if metadata.get('timeZone', {}).get('id') != 'Asia/Seoul' or metadata.get('state') != 'READY':
            raise ValueError('애드센스 계정 시간대 또는 활성 상태 불일치')
        params = {'dateRange': 'CUSTOM', 'dimensions': ['DATE', 'DOMAIN_NAME'],
                  'metrics': ['ESTIMATED_EARNINGS'], 'currencyCode': 'USD',
                  'reportingTimeZone': 'ACCOUNT_TIME_ZONE', 'limit': 10000}
        for prefix, day in [('startDate', start), ('endDate', end)]:
            params.update({prefix + '.year': day.year, prefix + '.month': day.month,
                           prefix + '.day': day.day})
        data = response_json(session.get(base + '/reports:generate', params=params, timeout=30))
        registered, next_token = {}, None
        while True:
            page = response_json(session.get(base + '/sites', params={'pageSize': 100, **({'pageToken': next_token} if next_token else {})}, timeout=25))
            for item in page.get('sites', []):
                domain = item.get('domain', '').lower().removeprefix('www.')
                registered[domain] = item.get('state', 'STATE_UNSPECIFIED')
            next_token = page.get('nextPageToken')
            if not next_token:
                break
    headers = data.get('headers', [])
    if [h.get('name') for h in headers] != ['DATE', 'DOMAIN_NAME', 'ESTIMATED_EARNINGS'] or headers[-1].get('currencyCode') != 'USD':
        raise ValueError('애드센스 보고서 열 또는 통화 불일치')
    if int(data.get('totalMatchedRows', 0)) != len(data.get('rows', [])):
        raise ValueError('애드센스 보고서 잘림; 전체 행 재수집 필요')
    values, details, seen = defaultdict(Decimal), [], set()
    for row in data.get('rows', []):
        day, domain, value = [c.get('value') for c in row['cells']]
        domain = domain.lower().removeprefix('www.')
        if domain not in sites:
            continue
        key = (report_day(day), domain)
        if key in seen:
            raise ValueError('애드센스 일별 도메인 행 중복')
        seen.add(key)
        values[key[0]] += money(value)
        details.append({'date': key[0], 'domain': domain, 'amount': str(money(value))})
    return {'daily': {d: str(v) for d, v in values.items()}, 'details': details,
            'status': 'collected',
            'reportSource': 'AdSense Management API v2 · DATE/DOMAIN_NAME',
            'siteStatus': {d: registered.get(d, 'not_registered') for d in sites},
            'registeredDomains': [d for d in sites if d in registered],
            'reason': f'조회 대상 {len(sites)}개 · 계정 등록 {sum(d in registered for d in sites)}개 · 수익 행 있는 날짜만 집계'}


def adsense_page_performance(cfg, start, end, sites, prefix='SJ_GOOGLE_ADSENSE'):
    """Measured AdSense PAGE_URL earnings; never allocate domain totals to pages."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    account = cfg[prefix + '_ACCOUNT_ID']
    creds = Credentials(token=None, refresh_token=cfg[prefix + '_REFRESH_TOKEN'],
                        token_uri='https://oauth2.googleapis.com/token',
                        client_id=cfg[prefix + '_CLIENT_ID'], client_secret=cfg[prefix + '_CLIENT_SECRET'])
    params = {'dateRange': 'CUSTOM', 'dimensions': ['PAGE_URL'],
              'metrics': ['ESTIMATED_EARNINGS'], 'currencyCode': 'USD',
              'reportingTimeZone': 'ACCOUNT_TIME_ZONE', 'limit': 100000}
    for key, day in [('startDate', start), ('endDate', end)]:
        params.update({key + '.year': day.year, key + '.month': day.month, key + '.day': day.day})
    with AuthorizedSession(creds) as client:
        base = 'https://adsense.googleapis.com/v2/' + account
        meta = response_json(client.get(base, timeout=25))
        if meta.get('timeZone', {}).get('id') != 'Asia/Seoul' or meta.get('state') != 'READY':
            raise ValueError('AdSense account timezone/state mismatch')
        data = response_json(client.get(base + '/reports:generate', params=params, timeout=30))
    headers = data.get('headers', [])
    if ([h.get('name') for h in headers] != ['PAGE_URL', 'ESTIMATED_EARNINGS']
            or headers[-1].get('currencyCode') != 'USD'):
        raise ValueError('AdSense page report columns/currency mismatch')
    if int(data.get('totalMatchedRows', -1)) != len(data.get('rows', [])) or data.get('warnings'):
        raise ValueError('AdSense page report incomplete')
    pages, seen = [], set()
    for row in data.get('rows', []):
        url, amount = [c.get('value') for c in row['cells']]
        parsed = urlparse(url)
        domain = (parsed.hostname or '').lower().removeprefix('www.')
        if domain not in sites or parsed.scheme not in ('http', 'https') or parsed.path in ('', '/'):
            continue
        # Query-bearing URLs can denote distinct content: do not merge their earnings.
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            continue
        canonical = 'https://www.' + domain + parsed.path
        if canonical in seen:
            raise ValueError('AdSense canonical page duplicate')
        seen.add(canonical)
        pages.append({'domain': domain, 'url': canonical, 'estimatedRevenue': float(money(amount))})
    return pages


@observed_operation('metrics', 'revenue-collection')
def collect_page_revenue(cfg, accounts, now):
    end = now.astimezone(KST).date() - timedelta(days=1)
    start = end - timedelta(days=6)
    pages, sites = [], []
    for account_key, account in accounts.items():
        domains = account.get('sites', [])
        if not domains:
            continue
        prefix = account.get('env_prefix', 'SJ_GOOGLE_ADSENSE' if account_key == 'sj' else 'AAA10291028_GOOGLE_ADSENSE')
        try:
            rows = adsense_page_performance(cfg, start, end, domains, prefix)
            pages.extend(rows)
            sites.extend({'domain': d, 'complete': True, 'status': 'collected'} for d in domains)
        except Exception:
            sites.extend({'domain': d, 'complete': False, 'status': 'not_collected',
                          'reason': 'AdSense PAGE_URL report unavailable; no page revenue inferred'} for d in domains)
    return {'start': start.isoformat(), 'end': end.isoformat(), 'timezone': 'Asia/Seoul',
            'checkedAt': stamp(), 'currency': 'USD', 'source': 'AdSense Management API v2', 'dimension': 'PAGE_URL',
            'complete': bool(sites) and all(s['complete'] for s in sites), 'pages': pages, 'sites': sites}


def growth_windows(now=None):
    """Two complete, equal Google reporting periods, excluding three recent days."""
    now = now or datetime.now(timezone.utc)
    end = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
    recent_start = end - timedelta(days=27)
    return {'recent': {'start': recent_start.isoformat(), 'end': end.isoformat()},
            'previous': {'start': (recent_start - timedelta(days=28)).isoformat(),
                         'end': (recent_start - timedelta(days=1)).isoformat()}}


def parse_growth_report(data, sites, start, end):
    """Validate a complete account report; retain real zero rows and host detail."""
    headers = data.get('headers', [])
    names = ['DATE', 'DOMAIN_CODE', 'ESTIMATED_EARNINGS', 'PAGE_VIEWS']
    if [h.get('name') for h in headers] != names or headers[2].get('currencyCode') != 'USD':
        raise ValueError('growth revenue report columns/currency mismatch')
    rows = data.get('rows', [])
    if int(data.get('totalMatchedRows', 0)) != len(rows) or data.get('warnings'):
        raise ValueError('growth revenue report incomplete')
    result, seen = [], set()
    for row in rows:
        cells = [c.get('value') for c in row.get('cells', [])]
        if len(cells) != 4:
            raise ValueError('growth revenue invalid row')
        day, host, amount, views = cells
        day = report_day(day)
        if not start <= day <= end:
            raise ValueError('growth revenue date outside requested range')
        host = str(host).lower().rstrip('.')
        domain = host.removeprefix('www.')
        if domain not in sites:
            continue
        key = (day, host)
        if key in seen:
            raise ValueError('growth revenue duplicate date/host')
        seen.add(key)
        views = money(views)
        if views < 0 or views != views.to_integral_value():
            raise ValueError('growth revenue invalid page views')
        result.append({'date': day, 'domain': domain, 'host': host,
                       'revenue': str(money(amount)), 'pageViews': int(views)})
    return result


def adsense_growth(cfg, start, end, sites, prefix='SJ_GOOGLE_ADSENSE'):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    account = cfg[prefix + '_ACCOUNT_ID']
    creds = Credentials(token=None, refresh_token=cfg[prefix + '_REFRESH_TOKEN'],
                        token_uri='https://oauth2.googleapis.com/token',
                        client_id=cfg[prefix + '_CLIENT_ID'],
                        client_secret=cfg[prefix + '_CLIENT_SECRET'])
    a, b = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    params = {'dateRange': 'CUSTOM', 'dimensions': ['DATE', 'DOMAIN_CODE'],
              'metrics': ['ESTIMATED_EARNINGS', 'PAGE_VIEWS'], 'currencyCode': 'USD',
              'reportingTimeZone': 'GOOGLE_TIME_ZONE', 'limit': 10000}
    for field, day in [('startDate', a), ('endDate', b)]:
        params.update({field + '.year': day.year, field + '.month': day.month,
                       field + '.day': day.day})
    with AuthorizedSession(creds) as session:
        data = response_json(session.get('https://adsense.googleapis.com/v2/' + account + '/reports:generate',
                                         params=params, timeout=45))
    return parse_growth_report(data, sites, start, end)


def growth_domain_period(rows, window, complete=True):
    observed = [r for r in rows if window['start'] <= r['date'] <= window['end']]
    revenue = sum((money(r['revenue']) for r in observed), Decimal(0))
    views = sum(r['pageViews'] for r in observed)
    observed_days = len({r['date'] for r in observed})
    complete = complete and observed_days == 28
    return dict(window, revenue=float(revenue) if complete else None,
                pageViews=views if complete else None,
                rpm=float(revenue * 1000 / views) if views and complete else None,
                accountRevenue=float(revenue) if observed else None, accountPageViews=views if observed else None,
                accountRpm=float(revenue * 1000 / views) if views else None,
                observedDays=observed_days, expectedDays=28, complete=complete,
                status='collected' if complete else 'partial',
                noRows=not observed)


def growth_cache_hours(result):
    failed = result.get('dailyImport', {}).get('status') == 'error'
    return 0.5 if failed or any(s.get('status') == 'error' for s in result.get('sources', {}).values()) else 12


def import_growth_daily(result):
    """Import observed dates only; account reports do not prove arbitrage exclusion."""
    from server.growth import import_daily
    allowed = {s['site_id'] for s in inventory() if s['platform'] == 'cf'}
    amounts, owners = defaultdict(Decimal), {}
    for account, source in result.get('sources', {}).items():
        if source.get('status') != 'collected':
            continue
        for row in source.get('rows', []):
            domain, day = row['domain'], row['date']
            if domain not in allowed or domain not in source.get('domains', []):
                continue
            key = (domain, day)
            if key in owners and owners[key] != account:
                raise ValueError('multiple AdSense accounts for one domain/date')
            owners[key] = account
            amounts[key] += money(row['revenue'])
    rows = []
    for (domain, day), amount in sorted(amounts.items()):
        account = owners[(domain, day)]
        source = result['sources'][account]
        migrated = domain in ('healthcox.com', 'tripmarvel.com') and account == 'sj'
        rows.append({'site_id': domain, 'service': 'adsense', 'metric': 'revenue',
                     'day': day, 'value': float(amount), 'currency': 'USD',
                     'source_timezone': 'America/Los_Angeles',
                     'source_ref': f'AdSense Management API v2 DATE/DOMAIN_CODE · {account}',
                     'collected_at': source['checkedAt'],
                     'complete': not migrated or day >= '2026-10-13',
                     'value_kind': 'estimated', 'revenue_scope': 'unknown'})
    count = import_daily(DATA / 'growth.sqlite3', {'schema_version': 'growth-daily-v1', 'rows': rows}) if rows else 0
    return {'status': 'imported', 'rows': count, 'checkedAt': stamp(), 'revenueScope': 'unknown'}


@observed_operation('metrics', 'revenue-collection')
def collect_growth_revenue(start=None, end=None, force=False, windows=None):
    """Read-only AdSense growth evidence; no missing credentials become zero."""
    if isinstance(start, dict):
        windows = start
    elif start and end:
        a, b = (datetime.fromisoformat(str(v)).date() for v in (start, end))
        if (b - a).days != 55:
            raise ValueError('growth revenue needs exactly 56 days')
        windows = {'previous': {'start': a.isoformat(), 'end': (a + timedelta(days=27)).isoformat()},
                   'recent': {'start': (a + timedelta(days=28)).isoformat(), 'end': b.isoformat()}}
    windows = windows or growth_windows()
    if 'current' in windows:
        windows = {'recent': windows['current'], 'previous': windows['previous']}
    for key in ('recent', 'previous'):
        a, b = (datetime.fromisoformat(windows[key][k]).date() for k in ('start', 'end'))
        if (b - a).days != 27:
            raise ValueError('growth revenue windows must each contain 28 days')
    if datetime.fromisoformat(windows['previous']['end']).date() + timedelta(days=1) != datetime.fromisoformat(windows['recent']['start']).date():
        raise ValueError('growth revenue windows must be adjacent')
    with collector_lock(DATA / 'revenue.lock') as acquired:
        if not acquired:
            return read_json(SNAPSHOT).get('growth', {'status': 'busy'})
        document = read_json(SNAPSHOT)
        old = document.get('growth', {})
        if not force and old.get('windows') == windows and old.get('status') in ('collected', 'partial'):
            checked = datetime.fromisoformat(old.get('checkedAt', '2000-01-01T00:00:00+00:00'))
            if timedelta(0) <= datetime.now(timezone.utc) - checked < timedelta(hours=growth_cache_hours(old)):
                return old
        cfg = revenue_config()
        accounts = read_json(CONFIG).get('adsense_accounts', {})
        sources, domains = {}, {}
        for account_key, config in accounts.items():
            prefix = config.get('env_prefix', '')
            sites = config.get('sites', [])
            record = {'account': account_key, 'accountEmail': config.get('email'),
                      'currency': 'USD', 'timezone': 'America/Los_Angeles',
                      'valueKind': 'estimated', 'status': 'not_connected', 'domains': sites}
            connected = prefix and all(cfg.get(prefix + '_' + key) for key in ('ACCOUNT_ID', 'CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN'))
            rows = None
            if connected:
                record['attemptedAt'] = stamp()
                try:
                    rows = adsense_growth(cfg, windows['previous']['start'], windows['recent']['end'], sites, prefix)
                    record.update(status='collected', checkedAt=stamp(), rows=rows,
                                  reportSource='AdSense Management API v2 DATE/DOMAIN_CODE ESTIMATED_EARNINGS/PAGE_VIEWS')
                except Exception:
                    record.update(status='error', attemptedAt=stamp(), reason='AdSense growth source failed; missing values remain unknown')
            else:
                record['reason'] = 'AdSense OAuth not connected; GA4/GSC credentials cannot read revenue'
            sources[account_key] = record
            for domain in sites:
                # These domains joined SJ in October 2026. Old account reports are unavailable.
                migrated = domain in ('healthcox.com', 'tripmarvel.com') and account_key == 'sj'
                item = {'domain': domain, 'account': account_key, 'currency': 'USD',
                        'timezone': 'America/Los_Angeles', 'valueKind': 'estimated',
                        'sourceCoverage': 'account_only' if migrated else 'configured_account',
                        'status': record['status'], 'checkedAt': record.get('checkedAt'),
                        'reason': 'SJ 전환 이전 계정 수익 미연결 · 전체 도메인 수익 비교 불가' if migrated else record.get('reason')}
                if rows is not None:
                    own = [r for r in rows if r['domain'] == domain]
                    item.update({k: growth_domain_period(own, w, not migrated or w['start'] >= '2026-10-13') for k, w in windows.items()})
                    item['status'] = 'partial_account_scope' if migrated and any(w['start'] < '2026-10-13' for w in windows.values()) else ('collected' if all(item[k]['complete'] for k in windows) else 'partial')
                    if not all(item[k]['complete'] for k in windows) and not migrated:
                        item['reason'] = '보고서에 없는 날짜는 미확인 · 확인된 날짜의 수익과 광고 페이지뷰만 표시'
                else:
                    item.update({k: dict(w, revenue=None, pageViews=None, rpm=None, status=record['status']) for k, w in windows.items()})
                domains[domain] = item
        result = {'schema': 'dashboard-growth-revenue-v1', 'windows': windows, 'sources': sources,
                  'domains': domains, 'timezone': 'America/Los_Angeles', 'currency': 'USD',
                  'checkedAt': stamp(), 'status': 'partial' if any(r['status'] != 'collected' for r in sources.values()) else 'collected'}
        # On failure preserve the prior successful evidence explicitly as stale, never restamp it.
        for key, record in sources.items():
            if record['status'] == 'error' and old.get('windows') == windows:
                prior = old.get('sources', {}).get(key, {})
                successful = prior if prior.get('status') == 'collected' else prior.get('lastSuccessful', {})
                if successful:
                    record['lastSuccessful'] = successful
                    for domain in record['domains']:
                        previous_domain = old.get('domains', {}).get(domain, {})
                        evidence = previous_domain if previous_domain.get('checkedAt') else previous_domain.get('lastSuccessful')
                        if evidence:
                            domains[domain]['lastSuccessful'] = evidence
        try:
            result['dailyImport'] = import_growth_daily(result)
        except Exception:
            result['dailyImport'] = {'status': 'error', 'attemptedAt': stamp(),
                                     'reason': 'Local daily import failed; source evidence retained'}
        document['growth'] = result
        atomic_write(SNAPSHOT, document)
        return result


def growth_revenue_summary(periods, path=SNAPSHOT):
    """Expose observed account income without treating omitted report days as zero."""
    growth = read_json(path).get('growth', {})
    expected = {'recent': periods.get('current', periods.get('recent')), 'previous': periods['previous']}
    valid = growth.get('windows') == expected
    domains = {}
    for domain, row in growth.get('domains', {}).items():
        item = {k: row.get(k) for k in ('domain', 'account', 'currency', 'sourceCoverage', 'reason')}
        try:
            collected = datetime.fromisoformat(row.get('checkedAt') or '')
            fresh = collected.tzinfo is not None and timedelta(0) <= datetime.now(timezone.utc) - collected <= timedelta(hours=26)
        except (ValueError, TypeError):
            fresh = False
        for target, origin in [('current', 'recent'), ('previous', 'previous')]:
            part = row.get(origin, {}) if valid else {}
            amount = part.get('accountRevenue')
            item[target] = {'amounts': {'USD': amount} if amount is not None else {},
                            'status': 'stale' if part.get('accountRevenue') is not None and not fresh else part.get('status', 'not_collected'),
                            'complete': bool(part.get('complete')) and valid and fresh,
                            'observedDays': part.get('observedDays', 0), 'expectedDays': 28,
                            'pageViews': part.get('accountPageViews'), 'rpm': part.get('accountRpm'),
                            'sourceTimezone': row.get('timezone', 'America/Los_Angeles'),
                            'checkedAt': row.get('checkedAt'),
                            'reason': '수익 원천 수집 후 26시간 경과 · 마지막 확인분이며 증감 비교 제외' if part.get('accountRevenue') is not None and not fresh else row.get('reason'),
                            **expected[origin]}
        domains[domain] = item
        item['decomposition'] = revenue_decomposition(item['current'], item['previous'])
    health = {}
    for key, record in growth.get('sources', {}).items():
        successful = record if record.get('status') == 'collected' else record.get('lastSuccessful', {})
        checked = successful.get('checkedAt')
        retry = None
        if growth.get('checkedAt'):
            try:
                retry = (datetime.fromisoformat(growth['checkedAt']) + timedelta(hours=growth_cache_hours(growth))).isoformat()
            except ValueError:
                pass
        health[key] = {'status': record.get('status', 'not_collected'),
                       'lastAttemptAt': record.get('attemptedAt'), 'lastSuccessAt': checked,
                       'nextRetryAt': retry if record.get('status') != 'not_connected' else None,
                       'cacheHours': growth_cache_hours(growth), 'rows': len(successful.get('rows', [])),
                       'domains': len(record.get('domains', [])),
                       'sourceTimezone': record.get('timezone', 'America/Los_Angeles'),
                       'reason': record.get('reason'), 'windowsMatch': valid}
    return {'status': growth.get('status', 'not_collected') if valid else 'period_mismatch',
            'checkedAt': growth.get('checkedAt'), 'domains': domains,
            'sourceTimezone': 'America/Los_Angeles', 'valueKind': 'estimated',
            'collection': {'accounts': health, 'cacheHours': growth_cache_hours(growth), 'periodsMatch': valid}}


def collection_health(collection, now=None):
    """Read-time cadence health. Cached source success is not a worker heartbeat."""
    now = now or datetime.now(timezone.utc)
    def age(value):
        if value is None:
            return None, False
        try:
            moment = datetime.fromisoformat(value)
            seconds = (now - moment).total_seconds() if moment.tzinfo else -1
            return (seconds, True) if seconds >= 0 else (None, False)
        except (ValueError, TypeError):
            return None, False
    runtime = collection.get('runtime') or {}
    heartbeat, heartbeat_valid = age(runtime.get('checkedAt'))
    attempt, attempt_valid = age(collection.get('lastAttemptAt'))
    if not runtime:
        runtime_status, runtime_reason = 'not_started', '수집 작업 런타임 기록 없음'
    elif not heartbeat_valid:
        runtime_status, runtime_reason = 'unknown', '런타임 heartbeat 날짜가 없거나 잘못되었거나 미래임'
    elif runtime.get('status') == 'running' and heartbeat > 120:
        runtime_status, runtime_reason = 'stalled', '실행 중 heartbeat가 120초 넘게 갱신되지 않음 · 중단 여부 확인 필요'
    else:
        runtime_status, runtime_reason = runtime.get('status', 'unknown'), '실행 상태와 원천 수집 성공은 별도'
    if collection.get('lastAttemptAt') is None:
        traffic_status, traffic_reason = 'not_started', '성장 수집 시도 기록 없음'
    elif not attempt_valid:
        traffic_status, traffic_reason = 'unknown', '성장 수집 시도 날짜가 잘못되었거나 미래임'
    elif attempt > 45 * 60:
        traffic_status, traffic_reason = 'collection_delayed', '30분 수집 주기에서 마지막 시도 후 45분 초과 · 스케줄러 확인 필요'
    else:
        traffic_status, traffic_reason = 'on_schedule', '최근 45분 안에 수집 시도 확인 · 캐시 적중이나 원천 대기와 구분'
    status, reason = 'on_schedule', traffic_reason
    for candidate, detail in ((runtime_status, runtime_reason), (traffic_status, traffic_reason)):
        if candidate in ('stalled', 'unknown', 'collection_delayed'):
            status, reason = candidate, detail
            break
    else:
        if runtime_status == 'not_started' and traffic_status == 'not_started':
            status, reason = 'not_started', '아직 연속 수집을 확인할 기록이 없음'
        elif runtime_status == 'partial_failure':
            status, reason = 'partial_failure', '일부 수집 단계 실패 · 개별 원천 상태 확인'
        elif runtime_status == 'running':
            status, reason = 'running', '수집 작업 실행 중 · heartbeat 정상 갱신'
    return {'status': status, 'reason': reason, 'checkedAt': now.isoformat(),
            'runtime': {'status': runtime_status, 'reason': runtime_reason, 'heartbeatAgeSeconds': heartbeat},
            'traffic': {'status': traffic_status, 'reason': traffic_reason, 'lastAttemptAgeSeconds': attempt},
            'heartbeatThresholdSeconds': 120, 'attemptThresholdSeconds': 45 * 60}


def revenue_decomposition(current, previous):
    """Symmetric arithmetic attribution, not a causal estimate of an intervention."""
    result = {'status': 'not_comparable', 'revenueDelta': None, 'pageViewEffect': None,
              'rpmEffect': None, 'residual': None, 'currency': None, 'causalProof': False,
              'reason': '양쪽 28일 전체·같은 통화·신선한 원천과 RPM이 확인되어야 분해 가능'}
    if not current.get('complete') or not previous.get('complete'):
        return result
    currencies = set(current.get('amounts', {})) & set(previous.get('amounts', {}))
    if (len(currencies) != 1 or current.get('sourceTimezone') != previous.get('sourceTimezone')
            or any(p.get('rpm') is None or p.get('pageViews') is None for p in (current, previous))):
        return result
    currency = next(iter(currencies))
    a, b = current['amounts'][currency], previous['amounts'][currency]
    pa, pb, ra, rb = current['pageViews'], previous['pageViews'], current['rpm'], previous['rpm']
    pv_effect = (pa - pb) * (ra + rb) / 2000
    rpm_effect = (ra - rb) * (pa + pb) / 2000
    return {**result, 'status': 'comparable', 'currency': currency, 'revenueDelta': a - b,
            'pageViewEffect': pv_effect, 'rpmEffect': rpm_effect,
            'residual': (a - b) - pv_effect - rpm_effect,
            'reason': '수익=광고 페이지뷰×RPM/1000의 대칭 산술 분해 · 원인이나 개선의 인과효과를 입증하지 않음'}


def browser_json(page, url):
    result = page.evaluate("""async url => {
      const r = await fetch(url, {credentials:'include', signal:AbortSignal.timeout(15000)});
      return {http:r.status, data:r.ok ? await r.json() : null};
    }""", url)
    if result['http'] != 200:
        raise ValueError(f"애드포스트 보고서 HTTP {result['http']}")
    return result['data']


def _adpost_identity(channels, publisher, account, configured_blog=None):
    if not isinstance(channels, list):
        raise RevenueSourceError('error', '애드포스트 미디어 목록 형식 불일치')
    own = [c for c in channels if str(c.get('publisherId')) == str(publisher)]
    if len(own) != len(channels):
        raise RevenueSourceError('auth_required', '애드포스트 publisher 식별 불일치 · 로그인 계정 확인 필요')
    blogs = [c for c in own if str(c.get('alias', '')).startswith('nblog.')]
    if not blogs:
        raise RevenueSourceError('not_enrolled', '로그인 계정의 등록된 블로그 미디어 없음')
    expected = {f'nblog.{account}'}
    if configured_blog:
        parsed = urlparse(str(configured_blog))
        blog_id = parsed.path.strip('/').split('/')[0] if parsed.hostname == 'blog.naver.com' else str(configured_blog).strip()
        if re.fullmatch(r'[A-Za-z0-9_-]+', blog_id):
            expected.add('nblog.' + blog_id)
    if not any(c.get('alias') in expected for c in blogs):
        raise RevenueSourceError('auth_required', '애드포스트 로그인 계정과 대상 블로그 미디어 불일치')
    return blogs


def _adpost_login(page, cfg, account):
    host = urlparse(page.url).hostname
    if host != 'nid.naver.com':
        return False
    username, password = cfg.get(f'NAVER_{account}_ID'), cfg.get(f'NAVER_{account}_PW')
    if not username or not password:
        raise RevenueSourceError('auth_required', '네이버 로그인 자격증명 미설정')
    if page.locator('#id').count() != 1 or page.locator('#pw').count() != 1:
        raise RevenueSourceError('auth_required', '네이버 추가 인증 또는 로그인 화면 확인 필요')
    with ego_action('type', 'metrics-auth'):
        page.locator('#id').fill(username)
    with ego_action('type', 'metrics-auth'):
        page.locator('#pw').fill(password)
    button = page.get_by_role('button', name='로그인', exact=True)
    if button.count() != 1:
        raise RevenueSourceError('auth_required', '네이버 로그인 제출 버튼 확인 필요')
    with ego_action('click', 'metrics-auth'):
        button.click()
    try:
        page.wait_for_url(lambda url: urlparse(str(url)).hostname == 'adpost.naver.com', timeout=15000)
    except Exception:
        # CAPTCHA/2FA is deliberately not automated or bypassed.
        raise RevenueSourceError('auth_required', '네이버 CAPTCHA·2단계 인증 또는 로그인 확인 필요') from None
    return True


def _adpost_report(page, cfg, account, start, end):
    with ego_action('navigate', 'metrics-browser'):
        page.goto('https://adpost.naver.com/main', wait_until='domcontentloaded', timeout=30000)
    if _adpost_login(page, cfg, account):
        with ego_action('navigate', 'metrics-browser'):
            page.goto('https://adpost.naver.com/main', wait_until='domcontentloaded', timeout=30000)
    # /main does not request channels. Its observed /api/logins response is the
    # account/publisher source of truth; fetch channels only after verifying it.
    login = browser_json(page, '/api/logins')
    if not isinstance(login, dict) or not login.get('isLoggedIn'):
        links = page.locator('a[href*="nid.naver.com"]').all()
        if len(links) == 1:
            with ego_action('click', 'metrics-browser'):
                links[0].click()
            _adpost_login(page, cfg, account)
            with ego_action('navigate', 'metrics-browser'):
                page.goto('https://adpost.naver.com/main', wait_until='domcontentloaded', timeout=30000)
            login = browser_json(page, '/api/logins')
    if not isinstance(login, dict) or not login.get('isNaverLoggedIn'):
        raise RevenueSourceError('auth_required', 'AdPost Naver authentication required')
    expected = str(cfg.get(f'NAVER_{account}_ID') or account).split('@')[0].lower()
    if str(login.get('naverId', '')).lower() != expected:
        raise RevenueSourceError('auth_required', 'AdPost authenticated account mismatch')
    publisher = str(login.get('publisherId', ''))
    # The live NORMAL primary has isRegistered=false. That field cannot serve
    # as enrollment truth; authenticated publisher and its real channels can.
    if not login.get('isLoggedIn') and not login.get('publisherId'):
        raise RevenueSourceError('not_enrolled', '로그인 계정에 애드포스트 publisher 등록 없음')
    if not login.get('isLoggedIn') or not publisher.isdigit():
        raise RevenueSourceError('auth_required', 'AdPost publisher authentication required')
    channels = browser_json(page, f'/api/publishers/{publisher}/channels')
    if not isinstance(channels, list) or any(str(c.get('publisherId')) != publisher for c in channels):
        raise RevenueSourceError('auth_required', 'AdPost publisher/channel identity mismatch')
    blogs = [c for c in channels if str(c.get('alias', '')).startswith('nblog.')]
    if not blogs:
        raise RevenueSourceError('not_enrolled', 'Authenticated AdPost publisher has no registered blog media')
    query = urlencode({'startDate': start.strftime('%Y%m%d'), 'endDate': end.strftime('%Y%m%d'),
                       'publisherId': publisher, 'clipRequired': 'true'})
    rows = browser_json(page, '/api/report/revenue?' + query)
    return rows, publisher, blogs


@observed_operation('metrics', 'revenue-collection')
def adpost(start, end, cfg=None, account='soul5373', port=9333):
    from playwright.sync_api import sync_playwright
    cfg = cfg if cfg is not None else revenue_config()
    owned = False
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', timeout=10000)
        except Exception:
            # Only the existing account-specific lifecycle manager may start it.
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from naver_blog_posting.posting import ACCOUNT_MAP, start_browser
            settings = ACCOUNT_MAP.get(account)
            if not settings or int(settings.get('cdp_port', 0)) != port:
                raise RevenueSourceError('error', '계정 전용 CDP 시작 배치 설정 없음') from None
            start_browser(settings)
            try:
                browser = p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', timeout=10000)
            except Exception:
                raise RevenueSourceError('error', '계정 전용 시작 배치 실행 후 CDP 연결 실패') from None
        context = browser.contexts[0]
        page = next((tab for tab in context.pages if urlparse(tab.url).hostname == 'adpost.naver.com'
                     and urlparse(tab.url).path.rstrip('/') in ('/main', '/report', '/report/revenue')), None)
        if page is None:
            page, owned = context.new_page(), True
        try:
            rows, publisher, blogs = _adpost_report(page, cfg, account, start, end)
        finally:
            # Existing publication/editor/user tabs and the CDP browser stay open.
            if owned:
                page.close()
    result = parse_adpost_rows(rows, start, end)
    result.update(publisherId=str(publisher), publisherVerified=True,
                  mediaAliases=[b['alias'] for b in blogs], account=account,
                  tabOwnership={'ownedTemporary': owned, 'reusedExisting': not owned},
                  reason=f'{account} 로그인 · 실제 publisher의 블로그 보고서 · 미집계 날짜는 집계 중')
    return result


def parse_adpost_rows(rows, start, end):
    if not isinstance(rows, list):
        raise ValueError('애드포스트 수입 보고서 형식 불일치')
    values, details, seen, pending = defaultdict(Decimal), [], set(), set()
    for row in rows:
        day = report_day(row['date'])
        if not start.isoformat() <= day <= end.isoformat():
            raise ValueError('애드포스트 조회 기간 밖의 수익 행')
        if row.get('mediaTypeName') != 'nblog':
            if not row.get('mediaTypeName'):
                pending.add(day)  # Report placeholders contain zero; these are not observations.
            continue
        key = (day, row['mediaId'], row.get('targetDeviceTypeName'))
        if key in seen:
            raise ValueError('애드포스트 미디어/기기별 행 중복')
        seen.add(key)
        value = money(row['revenueAmount'])
        values[day] += value
        details.append({'date': day, 'media': row['mediaName'], 'mediaId': row['mediaId'],
                        'device': row.get('targetDeviceTypeName'), 'amount': str(value)})
    # A partly generated day must not appear as a complete daily amount.
    for day in pending:
        values.pop(day, None)
    return {'daily': {d: str(v) for d, v in values.items()}, 'details': details,
            'pendingDates': sorted(pending), 'status': 'collected',
            'reason': '실제 publisher의 블로그 보고서 · 미집계 날짜는 집계 중',
            'reportSource': '네이버 애드포스트 수입 보고서'}


@observed_operation('metrics', 'revenue-collection')
def coupang(cfg, start, end, now=None):
    path = '/v2/providers/affiliate_open_api/apis/openapi/v1/reports/commission'
    query = urlencode({'startDate': start.strftime('%Y%m%d'), 'endDate': end.strftime('%Y%m%d')})
    signed = datetime.now(timezone.utc).strftime('%y%m%dT%H%M%SZ')
    signature = hmac.new(cfg['COUPANG_SECRET_KEY'].encode(),
                         (signed + 'GET' + path + query).encode(), hashlib.sha256).hexdigest()
    auth = f"CEA algorithm=HmacSHA256, access-key={cfg['COUPANG_ACCESS_KEY']}, signed-date={signed}, signature={signature}"
    data = response_json(requests.get('https://api-gateway.coupang.com' + path + '?' + query,
                                     headers={'Authorization': auth}, timeout=25))
    if str(data.get('rCode')) != '0' or not isinstance(data.get('data'), list):
        raise ValueError('쿠팡 수수료 보고서 오류; 인증 또는 조회 기간 확인 필요')
    # A successful report without continuation/truncation evidence covers the
    # requested range. Do not invent zeros for an incomplete/paginated response.
    if (data.get('hasNext') is True or data.get('hasNextPage') is True
            or data.get('nextCursor') or data.get('nextPage') is not None
            or data.get('truncated') is True):
        raise RevenueSourceError('partial', '쿠팡 보고서 페이지 지속 또는 잘림 확인 필요 · 누락일 0원 처리 중단')
    values, details, seen = defaultdict(Decimal), [], set()
    for row in data['data']:
        day = report_day(row['date'])
        if not start.isoformat() <= day <= end.isoformat():
            raise ValueError('쿠팡 조회 기간 밖의 수익 행')
        key = (day, row.get('trackingCode'), row.get('subId', ''))
        if key in seen:
            raise ValueError('쿠팡 수수료 보고서 행 중복')
        seen.add(key)
        value = money(row['commission'])  # GMV is sales volume, never revenue.
        values[day] += value
        details.append({'date': day, 'channel': row.get('subId') or '기본 채널', 'amount': str(value)})
    today = (now or datetime.now(KST)).astimezone(KST).date()
    zero_dates = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day < today and day.isoformat() not in values:
            values[day.isoformat()] = Decimal(0)
            zero_dates.append(day.isoformat())
    # Commission reports are D+1. Even a provider placeholder for today is not
    # a completed current-day commission report.
    pending = [today.isoformat()] if start <= today <= end else []
    values.pop(today.isoformat(), None)
    return {'daily': {d: str(v) for d, v in values.items()}, 'details': details,
            'pendingDates': pending, 'zeroActivityDates': zero_dates, 'queryComplete': True,
            'status': 'collected', 'reason': '계정 전체 · 성공한 전체 조회에서 과거 누락일은 실적 0 · 오늘은 D+1 보고서 집계 대기',
            'reportSource': '쿠팡 파트너스 Open API · commission'}


def affiliate_configuration(cfg, key):
    fields = {
        'toss': ('TOSS_ACCESS_KEY', 'TOSS_SECRET_KEY', 'TOSS_SHARE_LINK_ID', 'TOSS_SHARE_LINK_PW'),
        'replyalba': ('', '', 'REPLYALBA_ID', 'REPLYALBA_PW'),
        'trip': ('', '', '', ''),
    }
    access, secret, login, password = fields[key]
    presence = {'apiKey': bool(cfg.get(access)), 'apiSecret': bool(cfg.get(secret)),
                'login': bool(cfg.get(login) and cfg.get(password)),
                'affiliateIds': bool(cfg.get('TRIP_AID') and cfg.get('TRIP_SID')) if key == 'trip' else False}
    configured = any(presence.values())
    capability = 'api_report' if key == 'toss' and presence['apiKey'] and presence['apiSecret'] else 'login_only' if presence['login'] else 'affiliate_tracking_only' if presence['affiliateIds'] else 'unverified'
    return {'credentialPresence': presence, 'configurationStatus': 'configured' if configured else 'missing',
            'reportCapability': capability, 'status': 'configured_no_report_api' if configured else 'not_configured',
            'reason': '정산서 미확인 · 설정됨' if configured else '수익 보고서 인증 미설정'}


def _toss_access_token(cfg, session, cache_path=None):
    if not cfg.get('TOSS_ACCESS_KEY') or not cfg.get('TOSS_SECRET_KEY'):
        raise RevenueSourceError('not_configured', '토스 쉐어링크 API Access/Secret 설정 필요')
    cache_path = cache_path or DATA / 'secure' / 'toss-sharelink-token.json'
    fingerprint = hashlib.sha256((cfg['TOSS_ACCESS_KEY'] + '\0' + cfg['TOSS_SECRET_KEY']).encode()).hexdigest()
    cached = read_json(cache_path)
    if cached.get('credentialFingerprint') == fingerprint and cached.get('expiresAt', 0) > time.time() + 60 and cached.get('accessToken'):
        return cached['accessToken']
    response = session.post('https://oauth2.cert.toss.im/token', data={
        'grant_type': 'client_credentials', 'client_id': cfg['TOSS_ACCESS_KEY'],
        'client_secret': cfg['TOSS_SECRET_KEY'], 'scope': 'sharelink:read'}, timeout=25)
    if response.status_code in (400, 401, 403):
        raise RevenueSourceError('auth_required', f'토스 쉐어링크 OAuth 인증 실패 HTTP {response.status_code} · 키 종류·스코프·등록 IP 확인 필요')
    data = response_json(response)
    if not data.get('access_token') or str(data.get('token_type', '')).lower() != 'bearer' or int(data.get('expires_in', 0)) <= 60:
        raise RevenueSourceError('auth_required', '토스 OAuth 토큰 응답 검증 실패')
    if 'scope' in data and 'sharelink:read' not in str(data['scope']).split():
        raise RevenueSourceError('auth_required', '토스 토큰의 sharelink:read 권한 미확인')
    atomic_write(cache_path, {'credentialFingerprint': fingerprint, 'accessToken': data['access_token'],
                              'expiresAt': time.time() + int(data['expires_in'])})
    return data['access_token']


def parse_toss_performance(data, day):
    if not isinstance(data, dict) or data.get('resultType') != 'SUCCESS' or not isinstance(data.get('success'), dict):
        raise RevenueSourceError('auth_required' if isinstance(data, dict) and (data.get('error') or {}).get('errorCode') == 'SHARELINK_OPENAPI_ACCESS_DENIED' else 'error',
                                 '토스 실적 보고서 성공 응답 미확인 · API 권한·등록 IP·조회 조건 확인 필요')
    result = data['success']
    if result.get('fromDate') != day or result.get('toDate') != day:
        raise RevenueSourceError('error', '토스 실적 응답의 조회 날짜 불일치')
    summary = result.get('summary')
    if not isinstance(summary, dict) or 'expectedCommissionAmount' not in summary or not isinstance(result.get('items'), list):
        raise RevenueSourceError('error', '토스 실적 보고서 열 또는 항목 형식 불일치')
    value = money(summary['expectedCommissionAmount'])
    return {'date': day, 'amount': str(value), 'confirmedAmount': str(money(summary['confirmedCommissionAmount'])) if 'confirmedCommissionAmount' in summary else None,
            'lastUpdatedAt': summary.get('lastUpdatedAt'), 'detailPagesRemaining': bool(result.get('hasNext'))}


def toss(cfg, start, end):
    """Official Sharelink read API; summary is the full query total, not a page sum."""
    daily, details = {}, []
    with requests.Session() as session:
        token = _toss_access_token(cfg, session)
        for offset in range((end - start).days + 1):
            day = (start + timedelta(days=offset)).isoformat()
            response = session.get('https://sharelink.toss.im/openapi/performance',
                                   headers={'Authorization': 'Bearer ' + token},
                                   params={'fromDate': day, 'toDate': day, 'size': 50}, timeout=25)
            if response.status_code in (401, 403):
                raise RevenueSourceError('auth_required', f'토스 실적 조회 HTTP {response.status_code} · 토큰·스코프·등록 IP 확인 필요')
            row = parse_toss_performance(response_json(response), day)
            daily[day] = row['amount']
            details.append(row)
    return {'daily': daily, 'details': details, 'pendingDates': [], 'status': 'collected',
            'valueKind': 'estimated', 'queryComplete': True, 'pagination': 'summary_is_full_query_total',
            'reportCapability': 'api_report', 'reportSource': '토스 쉐어링크 공식 Open API · performance.summary.expectedCommissionAmount',
            'reportDocumentation': 'https://sharelink-docs.toss.im/developers/open-api/api/performance',
            'reason': '결제일별 전체 잠정 수익금(KRW·세전) · 구매확정월 정산액/실입금액과 별개'}


def deduplicate_adpost_sources(sources):
    seen = {}
    candidates = [s for s in sources if s.get('category') == 'adpost']
    # Prefer a newly verified source over an old cached copy of the same publisher.
    for record in sorted(candidates, key=lambda r: r.get('status') != 'collected'):
        publisher = record.get('publisherId')
        if not publisher:
            if record.get('daily') and any(s.get('publisherId') for s in candidates):
                record.update(previousObservedDaily=record.get('daily') or record.get('previousObservedDaily', {}), daily={},
                              aggregationEligible=False, aggregateExclusionReason='이전 수익의 publisher 미확인 · 중복 합산 방지')
            continue
        key = str(publisher)
        if key in seen:
            record.update(status='duplicate_source', aggregationEligible=False, duplicateOf=seen[key],
                          previousObservedDaily=record.get('daily') or record.get('previousObservedDaily', {}), daily={},
                          reason='동일 publisher의 계정 전체 보고서 · 중복 합산 제외')
        else:
            seen[key] = record['id']
            record.update(aggregationEligible=True, aggregationKey='adpost-publisher-' + key)


def _reply_url(base, link):
    url = urljoin(base, link)
    if urlparse(url).scheme != 'https' or urlparse(url).hostname not in (
            'replyalba.co.kr', 'www.replyalba.co.kr', 'replyalba.com', 'www.replyalba.com'):
        raise RevenueSourceError('auth_required', '쉐어알바 공식 도메인 밖 리다이렉트 차단')
    return url


def _reply_report_url(url, start, end):
    parsed = urlparse(_reply_url(url, url))
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.update(sdate=[start.isoformat()], edate=[end.isoformat()])
    return urlunparse(parsed._replace(query=urlencode(sorted(query.items()), doseq=True), fragment=''))


def parse_reply_report(html, url, start, end):
    """Parse the observed server-rendered partner report, never wallet balance."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    if not any('logout' in a.get('href', '').lower() or '로그아웃' in a.get_text()
               for a in soup.select('a[href]')):
        raise RevenueSourceError('auth_required', '쉐어알바 인증된 보고서 확인 실패')
    for key, value in (('sdate', start.isoformat()), ('edate', end.isoformat())):
        field = soup.select_one('input[name="' + key + '"]')
        if field is None or field.get('value') != value:
            raise RevenueSourceError('error', '쉐어알바 조회 기간 확인 실패')
    tables = [t for t in soup.select('table') if
              [re.sub(r'\s+', '', x.get_text()) for x in t.select('th')]
              == ['번호', '광고명', '신청일자', '수익금', '보기']]
    if len(tables) != 1:
        raise RevenueSourceError('error', '쉐어알바 수익금/신청일자 보고서 형식 불일치')
    rows = []
    for tr in tables[0].select('tr'):
        cells = tr.find_all('td', recursive=False)
        if not cells:
            continue
        if len(cells) != 5:
            raise RevenueSourceError('partial', '쉐어알바 보고서 행 형식 미확인')
        values = [c.get_text(' ', strip=True) for c in cells]
        match = re.search(r'\d{4}-\d{2}-\d{2}', values[2])
        if not match or not start.isoformat() <= match.group() <= end.isoformat():
            raise RevenueSourceError('error', '쉐어알바 보고서 신청일자 불일치')
        amount = re.sub(r'[\s,원]', '', values[3])
        if not re.fullmatch(r'-?\d+(?:\.\d+)?', amount):
            raise RevenueSourceError('partial', '쉐어알바 수익금 숫자 미확인')
        rows.append({'rowId': values[0], 'date': match.group(), 'amount': str(money(amount))})
    pages = set()
    for a in soup.select('a[href]'):
        candidate = urljoin(url, a['href'])
        parsed = urlparse(candidate)
        if parsed.path == urlparse(url).path and any(
                k.lower() in ('page', 'pageno', 'p', 'page_no') for k in parse_qs(parsed.query)):
            pages.add(_reply_report_url(_reply_url(url, a['href']), start, end))
    return rows, pages


def replyalba(cfg, start, end, now=None):
    from bs4 import BeautifulSoup
    if not cfg.get('REPLYALBA_ID') or not cfg.get('REPLYALBA_PW'):
        raise RevenueSourceError('not_configured', '쉐어알바 로그인 설정 없음')
    values, details, seen = defaultdict(Decimal), [], set()
    with requests.Session() as session:
        configured = _reply_url('https://replyalba.co.kr/', cfg.get('REPLYALBA_URL') or 'https://replyalba.co.kr/')
        login = session.get(_reply_url(configured, '/mobile/main/login.partner.php'), timeout=25)
        login.raise_for_status()
        _reply_url(login.url, login.url)
        soup = BeautifulSoup(login.text, 'html.parser')
        form = soup.select_one('#loginFrm')
        # This endpoint must still be declared by the official login page.
        if form is None or '../../proc/member.php' not in login.text:
            raise RevenueSourceError('auth_required', '쉐어알바 공식 로그인 양식 변경')
        payload = {i['name']: i.get('value', '') for i in form.select('input[name]')
                   if i.get('type') == 'hidden' or i.get('type') == 'radio' and i.has_attr('checked')}
        payload.update(id=cfg['REPLYALBA_ID'], pw=cfg['REPLYALBA_PW'])
        response = session.post(_reply_url(login.url, '../../proc/member.php'), data=payload,
                                headers={'Referer': login.url}, timeout=25)
        result = response_json(response)
        if result.get('res') is not True or not isinstance(result.get('url'), str):
            raise RevenueSourceError('auth_required', '쉐어알바 로그인 실패 또는 추가 인증 필요')
        landing = session.get(_reply_url(login.url, result['url']), timeout=25)
        landing.raise_for_status()
        _reply_url(landing.url, landing.url)
        links = [a['href'] for a in BeautifulSoup(landing.text, 'html.parser').select('a[href]')
                 if urlparse(urljoin(landing.url, a['href'])).path == '/mobile/partner/stat.php']
        if not links:
            raise RevenueSourceError('auth_required', '쉐어알바 로그인 후 실적 메뉴 미확인')
        report_url = _reply_report_url(_reply_url(landing.url, links[0]), start, end)
        queue, visited = [report_url], set()
        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            if len(visited) >= 50:
                raise RevenueSourceError('partial', '쉐어알바 전체 페이지 조회 제한 도달')
            visited.add(url)
            response = session.get(url, timeout=25)
            response.raise_for_status()
            _reply_url(response.url, response.url)
            rows, pages = parse_reply_report(response.text, response.url, start, end)
            for row in rows:
                key = row['rowId']
                if key in seen:
                    continue
                seen.add(key)
                values[row['date']] += money(row['amount'])
                details.append({k: row[k] for k in ('date', 'amount')})
            queue.extend(sorted(pages - visited))
    today = (now or datetime.now(KST)).astimezone(KST).date()
    zero_dates = []
    for n in range((end - start).days + 1):
        day = start + timedelta(days=n)
        if day < today and day.isoformat() not in values:
            values[day.isoformat()] = Decimal(0)
            zero_dates.append(day.isoformat())
    values.pop(today.isoformat(), None)
    return {'daily': {d: str(v) for d, v in values.items()}, 'details': details,
            'pendingDates': [today.isoformat()] if start <= today <= end else [],
            'zeroActivityDates': zero_dates, 'queryComplete': True, 'pagesRead': len(visited),
            'status': 'collected', 'valueKind': 'estimated', 'identityEvidence': 'fresh_credential_login',
            'reportCapability': 'authenticated_html_report', 'reportSource': '쉐어알바 실적/수익 · 신청일자별 수익금',
            'reason': '공식 로그인 후 전체 실적 표 조회 · 표시 수익금이며 정산/출금액과 별개 · 오늘은 집계 대기'}


@observed_operation('metrics', 'revenue-collection')
def collect(now=None):
    now = now or datetime.now(KST)
    today, month = now.date(), now.strftime('%Y-%m')
    start = today.replace(day=1)
    with collector_lock(DATA / 'revenue.lock') as acquired:
        if not acquired:
            return {'status': 'busy'}
        config = read_json(CONFIG)
        accounts = config.get('adsense_accounts', {})
        owned = accounts.get('sj', {}).get('sites', [])
        expected = sum(s['platform'] == 'cf' for s in inventory())
        sources = [source('adsense-sj', 'adsense', 'SJ · CF 애드센스', 'USD',
                          f'SJ 수익 조회 대상 CF {len(owned)}/{expected}개 · 등록/승인 별도 확인', domains=owned)]
        sources += [source('adpost-' + account, 'adpost', account + ' · 애드포스트', 'KRW',
                           account + ' 로그인으로 확인한 publisher 블로그 미디어', browserPort=port,
                           optional=account != 'soul5373') for account, port in ADPOST_ACCOUNTS]
        sources.append(source('coupang', 'affiliate', '쿠팡 파트너스', 'KRW', '쿠팡 계정 전체 · 모든 subId'))
        cfg = revenue_config()
        previous = read_json(SNAPSHOT)
        old_sources = {s['id']: s for s in previous.get('months', {}).get(month, {}).get('sources', [])}
        jobs = [lambda: adsense(cfg, start, today, owned, accounts.get('sj', {}).get('env_prefix', 'SJ_GOOGLE_ADSENSE'))]
        jobs += [lambda account=account, port=port: adpost(start, today, cfg, account, port) for account, port in ADPOST_ACCOUNTS]
        jobs.append(lambda: coupang(cfg, start, today, now=now))
        for record, job in zip(sources, jobs):
            try:
                if record['id'] == 'adsense-sj' and not owned:
                    raise ValueError('CF 소유 도메인 목록 미설정')
                record.update(job())
                for day, value in record['daily'].items():
                    if not start.isoformat() <= day <= today.isoformat():
                        raise ValueError('조회 기간 밖의 수익 행')
                    money(value)
                record.update(checkedAt=stamp(), reportStart=start.isoformat(), reportEnd=today.isoformat())
            except Exception as exc:
                # Exceptions can contain tokens/URLs. Persist only our controlled validation text.
                reason = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError) else '원천 연결 실패; 이전 수집값 유지'
                old = old_sources.get(record['id'])
                if old and (old.get('daily') or old.get('previousObservedDaily')):
                    record.update(old)
                else:
                    record.update(daily={}, details=[], pendingDates=[])
                record.update(status=getattr(exc, 'status', 'error'), reason=reason, attemptedAt=stamp())
        deduplicate_adpost_sources(sources)
        family = accounts.get('aaa10291028', {})
        family_record = source('adsense-aaa10291028', 'adsense', '가족 aaa · 애드센스', 'USD', 'nolplace.com · 가족 계정 별도 수집', domains=family.get('sites', []))
        family_prefix = family.get('env_prefix', 'AAA10291028_GOOGLE_ADSENSE')
        if family.get('sites') and all(cfg.get(family_prefix + '_' + key) for key in ('ACCOUNT_ID', 'CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN')):
            try:
                family_record.update(adsense(cfg, start, today, family['sites'], family_prefix), reportStart=start.isoformat(), reportEnd=today.isoformat(), checkedAt=stamp())
            except Exception:
                if old_sources.get(family_record['id']):
                    family_record.update(old_sources[family_record['id']])
                family_record.update(status='error', reason='가족 계정 원천 연결 실패; 이전 수집값 유지', attemptedAt=stamp())
        else:
            family_record['reason'] = '가족 계정 AdSense OAuth 미연결 · GA4/Search Console 조회 인증과 별개'
        sources.append(family_record)
        for record in sources:
            if record['id'].startswith('adsense-'):
                account_key = 'sj' if record['id'] == 'adsense-sj' else 'aaa10291028'
                account = accounts.get(account_key, {})
                record.update(accountEmail=account.get('email'), plannedDomains=account.get('sites', []))
                record.setdefault('siteStatus', account.get('site_status', {}))
                if record['id'] == 'adsense-sj':
                    states = record.get('siteStatus', {})
                    absent = [d for d in account.get('sites', []) if states.get(d) == 'not_registered']
                    record['scope'] = adsense_scope(account.get('email', 'sj@must.biz'), account.get('sites', []), states)
                    if absent and account.get('pending_reason'):
                        record['reason'] += ' · ' + account['pending_reason']
        for key, label in [('toss', '토스 쉐어링크'), ('trip', 'Trip.com'), ('replyalba', '제휴알바')]:
            record = source(key, 'affiliate', label, 'KRW', label)
            record.update(affiliate_configuration(cfg, key))
            if (key == 'toss' and record['reportCapability'] == 'api_report') or (key == 'replyalba' and record['credentialPresence']['login']):
                try:
                    result = toss(cfg, start, today) if key == 'toss' else replyalba(cfg, start, today, now=now)
                    record.update(result, reportStart=start.isoformat(),
                                  reportEnd=today.isoformat(), checkedAt=stamp())
                except Exception as exc:
                    old = old_sources.get(key)
                    if old and old.get('daily'):
                        record['lastSuccessful'] = {k: old.get(k) for k in ('daily', 'details', 'checkedAt', 'reportSource')}
                        record.update(daily=old['daily'], details=old.get('details', []), checkedAt=old.get('checkedAt'))
                    record.update(status=getattr(exc, 'status', 'error'), attemptedAt=stamp(),
                                  reason=str(exc) if isinstance(exc, RevenueSourceError) else '토스 원천 연결 실패 · 확인된 이전 수익만 유지')
            elif key == 'trip' and record['configurationStatus'] == 'configured':
                record['reason'] = 'AID/SID 설정됨 · 추적용 식별자이며 정산서·수익 보고 API 미확인'
            elif key == 'replyalba' and record['configurationStatus'] == 'configured':
                record['reason'] = '로그인 설정됨 · 정산서·공식 수익 보고 API 미확인'
            sources.append(record)
        previous.setdefault('months', {})[month] = {'sources': sources, 'checkedAt': stamp()}
        previous.update(schema='dashboard-revenue-v1', checkedAt=stamp())
        previous['pagePerformance'] = collect_page_revenue(cfg, accounts, now)
        atomic_write(SNAPSHOT, previous)
    collect_growth_revenue()
    return summary(now=now)


def period(sources, start, end):
    if end < start:
        return {'amounts': {}, 'status': 'not_applicable', 'observedDays': 0}
    dates = [(start + timedelta(days=n)).isoformat() for n in range((end - start).days + 1)]
    totals, observed, pending = defaultdict(Decimal), set(), False
    for record in sources:
        if record.get('aggregationEligible') is False or record.get('status') == 'duplicate_source':
            continue
        rows = record.get('daily', {})
        for day in dates:
            if day in rows:
                totals[record['currency']] += money(rows[day])
                observed.add(day)
            if day in record.get('pendingDates', []):
                pending = True
    eligible = [s for s in sources if s.get('aggregationEligible') is not False and s.get('status') != 'duplicate_source']
    completeness_sources = [s for s in eligible if not (s.get('optional') is True and s.get('status') == 'not_enrolled')]
    complete = bool(completeness_sources) and all(all(day in s.get('daily', {}) for day in dates) and s.get('status') == 'collected' for s in completeness_sources)
    status = ('collected' if complete else 'partial') if totals else 'pending' if pending else 'not_collected'
    reason = None
    if status == 'pending':
        reason = 'D+1 보고서 집계 대기' if any(s.get('id') == 'coupang' and set(dates).intersection(s.get('pendingDates', [])) for s in eligible) else '원천 보고서 집계 대기'
    elif not totals and eligible and all(s.get('status') == 'configured_no_report_api' for s in eligible):
        status, reason = 'configured_no_report_api', '정산서 미확인 · 설정됨'
    elif not totals and eligible and len(eligible) == 1 and eligible[0].get('status') in ('auth_required', 'not_enrolled', 'not_configured', 'error', 'partial'):
        status, reason = eligible[0]['status'], eligible[0].get('reason')
    elif not eligible and sources:
        status, reason = 'duplicate_source', '동일 원천의 중복 합산 제외'
    return {'amounts': {c: str(v) for c, v in totals.items()}, 'status': status,
            'observedDays': len(observed), 'expectedDays': len(dates),
            'start': start.isoformat(), 'end': end.isoformat(), 'estimated': True,
            'complete': complete, 'reason': reason}


def summary(path=SNAPSHOT, now=None):
    now = now or datetime.now(KST)
    today, month = now.date(), now.strftime('%Y-%m')
    start, yesterday = today.replace(day=1), today - timedelta(days=1)
    document = read_json(path)
    selected = document.get('months', {}).get(month, {})
    sources = selected.get('sources', [])
    previous_sources = document.get('months', {}).get(yesterday.strftime('%Y-%m'), {}).get('sources', []) if yesterday.month != today.month else []
    if not sources and previous_sources:
        sources = [dict(s, daily={}, pendingDates=[]) for s in previous_sources]
    # Older measurements remain visible with their original timestamp and stale badge.
    for record in sources:
        try:
            record['stale'] = now.astimezone(timezone.utc) - datetime.fromisoformat(record['checkedAt']) > timedelta(hours=2)
        except (ValueError, KeyError, TypeError):
            record['stale'] = True
    windows = [('throughYesterday', start, yesterday), ('yesterday', yesterday, yesterday),
               ('today', today, today), ('month', start, today)]
    def amounts(records):
        ids = {s['id'] for s in records}
        return {key: period([s for s in previous_sources if s['id'] in ids]
                            if key == 'yesterday' and previous_sources else records, a, b)
                for key, a, b in windows}
    categories = [{'id': key, 'label': label, 'sources': [s for s in sources if s['category'] == key],
                   'periods': amounts([s for s in sources if s['category'] == key])}
                  for key, label in CATEGORIES]
    daily = []
    for offset in range(today.day):
        day = start + timedelta(days=offset)
        daily.append({'date': day.isoformat(), 'categories': {
            key: period([s for s in sources if s['category'] == key], day, day)
            for key, _ in CATEGORIES}})
    for record in sources:
        record['periods'] = amounts([record])
        record['lastReportDay'] = max(record.get('daily', {}), default=None)
    return {'status': 'partial' if any(s.get('daily') for s in sources) else 'not_collected',
            'timezone': 'Asia/Seoul', 'month': month, 'today': today.isoformat(),
            'yesterday': yesterday.isoformat(), 'checkedAt': selected.get('checkedAt'),
            'categories': categories, 'totals': amounts(sources), 'daily': daily,
            'note': '확인된 수익만 표시 · 미연결 계정/업체 제외 · 예상 수익이며 정산액과 다를 수 있음'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args()
    result = collect() if args.collect else summary()
    print(json.dumps({k: v for k, v in result.items() if k not in ('categories', 'daily')}, ensure_ascii=False, indent=2))
