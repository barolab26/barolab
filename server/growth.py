"""Growth read API and explicit local import. No publisher or credential access."""
import argparse
import json
import math
import os
import shutil
import sys
import ipaddress
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_DB = ROOT / 'server' / 'data' / 'growth.sqlite3'
METRICS = {'ga4': 'sessions', 'naver_blog': 'visitors', 'adsense': 'revenue',
           'naver_adpost': 'revenue', 'affiliate': 'revenue'}


@contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS sites (
        site_id TEXT PRIMARY KEY, url TEXT NOT NULL, platform TEXT NOT NULL,
        inventory_source TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS connections (
        site_id TEXT NOT NULL, service TEXT NOT NULL, metadata TEXT NOT NULL,
        PRIMARY KEY(site_id,service));
      CREATE TABLE IF NOT EXISTS daily_metrics (
        site_id TEXT NOT NULL REFERENCES sites(site_id), service TEXT NOT NULL,
        metric TEXT NOT NULL, day TEXT NOT NULL, value REAL,
        currency TEXT, source_timezone TEXT NOT NULL, source_ref TEXT NOT NULL,
        collected_at TEXT NOT NULL, complete INTEGER NOT NULL,
        value_kind TEXT NOT NULL, revenue_scope TEXT NOT NULL,
        PRIMARY KEY(site_id,service,metric,day));
      CREATE TABLE IF NOT EXISTS improvement_actions (
        id TEXT PRIMARY KEY, domain TEXT NOT NULL, url TEXT NOT NULL,
        action TEXT NOT NULL, note TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
        planning_baseline TEXT NOT NULL, baseline TEXT);
    ''')
    # Additive migration keeps every existing shared improvement record intact.
    action_columns = {r[1] for r in db.execute('PRAGMA table_info(improvement_actions)')}
    if 'diagnosis_snapshot' not in action_columns:
        db.execute('ALTER TABLE improvement_actions ADD COLUMN diagnosis_snapshot TEXT')
    if 'observation_snapshot' not in action_columns:
        db.execute('ALTER TABLE improvement_actions ADD COLUMN observation_snapshot TEXT')
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS improvement_actions_active ON improvement_actions(domain,url,action) WHERE status!='done'")
    except sqlite3.IntegrityError:
        # Older duplicate records are evidence: keep them and serialize future creation.
        pass
    try:
        with db:
            yield db
    finally:
        db.close()


def import_inventory(path, document):
    if document.get('schema_version') != '1.0':
        raise ValueError('unsupported inventory schema')
    with connect(path) as db:
        for s in document['sites']:
            db.execute('INSERT OR IGNORE INTO sites VALUES (?,?,?,?)',
                       (s['site_id'], s['url'], s['platform'], s['inventory_source']))
        for r in document['records']:
            # Availability evidence only: period aggregates are never split into daily facts.
            metadata = {k: r.get(k) for k in ('status', 'reason', 'connection_status',
                        'checked_at', 'collected_at', 'source_timezone', 'currency',
                        'source_data_through', 'data_lag', 'report_url')}
            db.execute('INSERT OR REPLACE INTO connections VALUES (?,?,?)',
                       (r['site_id'], r['service'], json.dumps(metadata, ensure_ascii=False)))


def import_daily(path, document):
    """Import site-attributed daily report exports; reject invalid batches atomically."""
    if document.get('schema_version') != 'growth-daily-v1':
        raise ValueError('expected growth-daily-v1')
    validated = []
    for r in document['rows']:
        service = r['service']
        if service not in METRICS or r['metric'] != METRICS[service]:
            raise ValueError('unsupported service/metric')
        day = date.fromisoformat(r['day'])
        if day.isoformat() != r['day']:
            raise ValueError('day must be YYYY-MM-DD')
        zone = ZoneInfo(r['source_timezone'])
        collected = datetime.fromisoformat(r['collected_at'])
        if collected.tzinfo is None or day >= collected.astimezone(zone).date():
            raise ValueError('only completed source dates with offset-aware collected_at')
        if collected > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('future collection timestamp')
        if type(r['complete']) is not bool or not str(r['source_ref']).strip():
            raise ValueError('complete and source_ref required')
        value = r['value']
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ValueError('value must be finite number or null')
        currency = r.get('currency')
        kind = r.get('value_kind', 'measured' if r['metric'] != 'revenue' else None)
        scope = r.get('revenue_scope', 'unknown')
        if r['metric'] == 'revenue':
            if currency not in ('USD', 'KRW') or kind not in ('estimated', 'final'):
                raise ValueError('explicit currency and estimated/final value_kind required')
            if scope not in ('excludes_arbitrage', 'all', 'unknown'):
                raise ValueError('unsupported revenue scope')
        elif currency is not None or (value is not None and (value < 0 or int(value) != value)):
            raise ValueError('traffic requires nonnegative integer and no currency')
        validated.append((r['site_id'], service, r['metric'], r['day'], value,
                          currency, r['source_timezone'], r['source_ref'],
                          collected.isoformat(), int(r['complete']), kind, scope))
    with connect(path) as db:
        db.executemany('INSERT OR REPLACE INTO daily_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', validated)
    return len(validated)


def dates(end, days):
    return [(end - timedelta(days=i)).isoformat() for i in reversed(range(days))]


def series(db, site_id, service, end, days):
    wanted = dates(end, days)
    rows = {r['day']: dict(r) for r in db.execute(
        'SELECT * FROM daily_metrics WHERE site_id=? AND service=? AND metric=? AND day BETWEEN ? AND ?',
        (site_id, service, METRICS[service], wanted[0], wanted[-1]))}
    points = [rows.get(d, {'day': d, 'value': None, 'complete': 0,
                         'currency': None, 'source_timezone': None,
                         'source_ref': None, 'collected_at': None,
                         'value_kind': None, 'revenue_scope': None}) for d in wanted]
    observed = [p for p in points if p['value'] is not None]
    signatures = {(p['currency'], p['source_timezone'], p['value_kind'], p['revenue_scope']) for p in observed}
    compatible = len(signatures) == 1
    complete = len(observed) == days and all(p['complete'] for p in points) and compatible
    return {'start': wanted[0], 'end': wanted[-1], 'points': points,
            'observed_days': len(observed), 'expected_days': days,
            'status': 'complete' if complete else ('partial' if observed else 'not_collected'),
            'total': sum(p['value'] for p in points) if complete else None,
            'currency': next(iter(signatures))[0] if compatible else None,
            'source_timezone': next(iter(signatures))[1] if compatible else None,
            'value_kind': next(iter(signatures))[2] if compatible else None,
            'revenue_scope': next(iter(signatures))[3] if compatible else None,
            'collected_at': max((p['collected_at'] for p in points if p['collected_at']), default=None)}


def revenue_goal(db, end):
    eligible = db.execute("SELECT site_id FROM sites WHERE platform='cf' ORDER BY site_id").fetchall()
    targets = [series(db, s['site_id'], 'adsense', end, 30) for s in eligible]
    ready = [t for t in targets if t['total'] is not None and t['currency'] == 'USD'
             and t['revenue_scope'] == 'excludes_arbitrage']
    full = bool(targets) and len(ready) == len(targets)
    full = full and len({(t['source_timezone'], t['value_kind']) for t in targets}) == 1
    average = sum(t['total'] for t in targets) / 30 if full else None
    return {'scope': '등록 CF 도메인 전체', 'site_count': len(eligible), 'complete_sites': len(ready),
            'start': dates(end, 30)[0], 'end': end.isoformat(), 'currency': 'USD',
            'daily_target': 100, 'daily_average': average,
            'achievement_pct': average if average is not None else None,
            'status': ('achieved' if average >= 100 else 'in_progress') if full else 'unknown',
            'source_timezone': targets[0]['source_timezone'] if full else None,
            'reason': None if full else '전체 등록 사이트의 동일 기준 30일 USD 수익 미수집'}


def snapshot(path, site_id, days=7, end=None):
    if days not in (7, 28):
        raise ValueError('days must be 7 or 28')
    yesterday = datetime.now(ZoneInfo('Asia/Seoul')).date() - timedelta(days=1)
    end = date.fromisoformat(end) if isinstance(end, str) else end or yesterday
    if end > yesterday:
        raise ValueError('end must be a completed KST date')
    with connect(path) as db:
        sites = [dict(r) for r in db.execute('SELECT * FROM sites ORDER BY platform,site_id')]
        site = next((s for s in sites if s['site_id'] == site_id), None)
        if not site:
            raise KeyError(site_id)
        services = ['ga4' if site['platform'] == 'cf' else 'naver_blog',
                    'adsense', 'naver_adpost', 'affiliate']
        result = []
        for service in services:
            current = series(db, site_id, service, end, days)
            previous = series(db, site_id, service, end - timedelta(days=days), days)
            a, b = current['total'], previous['total']
            matching = all(current[k] == previous[k] for k in ('currency', 'source_timezone', 'value_kind', 'revenue_scope'))
            growth = (a - b) / b * 100 if a is not None and b is not None and b > 0 and matching else None
            raw = db.execute('SELECT metadata FROM connections WHERE site_id=? AND service=?', (site_id, service)).fetchone()
            connection = json.loads(raw[0]) if raw else {'status': 'not_collected', 'connection_status': 'unverified',
                'reason': '사이트별 원천 보고서와 서비스 귀속 미확인', 'checked_at': None}
            result.append({'service': service, 'metric': METRICS[service], 'current': current,
                           'previous': previous, 'growth_pct': growth, 'connection': connection})
        goal = revenue_goal(db, end)
    for observation in result:
        _record_metric_increase(site_id, observation)
    return {'site': site, 'sites': sites, 'days': days, 'end': end.isoformat(),
            'requested_timezone': 'Asia/Seoul', 'services': result, 'goal': goal,
            'queried_at': datetime.now(timezone.utc).isoformat()}


def page_performance_evidence(now=None, metrics=None, revenue=None, traffic_source=None, domains=None):
    """Join exact completed seven-day page reports; never apportion domain earnings."""
    now = now or datetime.now(timezone.utc)
    end = now.astimezone(ZoneInfo('Asia/Seoul')).date() - timedelta(days=1)
    start = end - timedelta(days=6)
    def read(name):
        try:
            return json.loads((ROOT / 'server/data' / name).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}
    metrics = read('metrics.json') if metrics is None else metrics
    revenue = read('revenue.json') if revenue is None else revenue
    traffic_source = read('traffic.json') if traffic_source is None else traffic_source
    result = {'schema': 'page-performance-feedback-v1', 'checkedAt': now.isoformat(),
              'start': start.isoformat(), 'end': end.isoformat(), 'timezone': 'Asia/Seoul',
              'status': 'not_collected', 'complete': False, 'reasonCodes': [],
              'revenueWinners': [], 'zeroViewPages': [], 'highTrafficPages': [],
              'revenueSource': 'AdSense Management API v2', 'revenueMetric': 'ESTIMATED_EARNINGS',
              'selection': 'top_10_percent_of_positive_revenue_and_positive_session_pages'}
    traffic = metrics.get('pagePerformance') or {}
    earnings = revenue.get('pagePerformance') or {}
    def valid_report(report, kind, record_reasons=True):
        reasons = []
        if report.get('start') != str(start) or report.get('end') != str(end) or report.get('timezone') != 'Asia/Seoul':
            reasons.append(kind + '_period_mismatch_or_missing')
        try:
            age = (now - datetime.fromisoformat(report['checkedAt'].replace('Z', '+00:00'))).total_seconds()
            if not 0 <= age <= 26 * 3600:
                reasons.append(kind + '_stale')
        except (KeyError, TypeError, ValueError):
            reasons.append(kind + '_timestamp_missing')
        if report.get('complete') is not True or report.get('status', 'collected') != 'collected':
            reasons.append(kind + '_partial_or_missing')
        if record_reasons:
            result['reasonCodes'].extend(reasons)
        return not reasons
    traffic_valid = valid_report(traffic, 'traffic')
    revenue_valid = valid_report(earnings, 'revenue')
    if earnings.get('source') not in ('AdSense Management API v2', 'AdSense Management API v2 PAGE_URL'):
        revenue_valid = False
        result['reasonCodes'].append('page_adsense_revenue_unverified')
    currency = earnings.get('currency')
    if currency not in ('USD', 'KRW'):
        revenue_valid = False
        result['reasonCodes'].append('revenue_currency_unknown')
    def key(row):
        try:
            value = urlsplit(row.get('url', ''))
            host = (value.hostname or '').lower().removeprefix('www.')
            domain = str(row.get('domain') or host).lower().removeprefix('www.')
            if value.scheme not in ('http', 'https') or not host or host != domain or value.path in ('', '/') or value.query or value.fragment:
                return None
            return (host, value.path.rstrip('/'))
        except (ValueError, TypeError):
            return None
    def number(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    def rows(report, fields):
        mapped = {}
        duplicate = False
        for row in report.get('pages', []):
            identity = key(row)
            if identity is None or not all(number(row.get(field)) for field in fields):
                continue
            if identity in mapped:
                duplicate = True
                continue
            mapped[identity] = row
        return mapped, duplicate
    pages, traffic_duplicate = rows(traffic, ('sessions', 'pageViews'))
    money, revenue_duplicate = rows(earnings, ('estimatedRevenue',))
    if any(row.get('currency', currency) != currency for row in money.values()):
        revenue_valid = False
        result['reasonCodes'].append('mixed_revenue_currency')
    if traffic_duplicate or revenue_duplicate:
        result['reasonCodes'].append('duplicate_canonical_page_rows')
        traffic_valid = revenue_valid = False
    site_reports = traffic.get('sites', [])
    site_reports = list(site_reports.values()) if isinstance(site_reports, dict) else site_reports
    domain_reports = {}
    for site in site_reports:
        domain = str(site.get('domain', '')).removeprefix('www.')
        # A globally complete legacy report may supply missing shared metadata.
        # Partial reports require each domain's own dated collection evidence.
        report = {**traffic, **site} if traffic_valid else site
        if (domain and not traffic_duplicate and valid_report(report, 'traffic_domain', False)
                and (traffic_valid or report.get('fullEnumeration') is True)):
            domain_reports[domain] = report
    valid_domains = set(domain_reports)
    if traffic_valid:
        valid_domains.update(identity[0] for identity in pages)
    if valid_domains:
        for identity, row in pages.items():
            if identity[0] not in valid_domains:
                continue
            item = {'domain': identity[0], 'url': row['url'], 'title': row.get('title', ''),
                    'sessions': row['sessions'], 'pageViews': row['pageViews'],
                    'start': str(start), 'end': str(end), 'complete': True,
                    'checkedAt': (domain_reports.get(identity[0]) or traffic).get('checkedAt')}
            if row['pageViews'] == 0 and row['sessions'] == 0:
                result['zeroViewPages'].append(item)
            if row['sessions'] > 0:
                result['highTrafficPages'].append(item)
        result['highTrafficPages'].sort(key=lambda row: (-row['sessions'], row['url']))
        # Only an explicitly exhaustive, complete report permits missing-row zero.
        # The runner must still require PASS evidence and publication age >= 7 days.
        exhaustive = {domain for domain, report in domain_reports.items()
                      if report.get('fullEnumeration') is True}
        inventory = metrics.get('sites', {})
        inventory = list(inventory.values()) if isinstance(inventory, dict) else inventory
        for record in inventory:
            domain = str(record.get('site', {}).get('site_id', '')).removeprefix('www.')
            if domain not in exhaustive or record.get('posts', {}).get('complete') is not True:
                continue
            for url in record.get('posts', {}).get('urls', []):
                identity = key({'domain': domain, 'url': url})
                if identity and identity not in pages:
                    pages[identity] = {'sessions': 0, 'pageViews': 0, 'url': url}
                    result['zeroViewPages'].append({'domain': domain, 'url': url, 'title': '',
                        'sessions': 0, 'pageViews': 0, 'start': str(start), 'end': str(end),
                        'complete': True, 'zeroBasis': 'complete_inventory_joined_to_exhaustive_ga4_report'})
    if traffic_valid and revenue_valid:
        eligible = []
        for identity in pages.keys() & money.keys():
            visits, income = pages[identity], money[identity]
            if visits['sessions'] <= 0 or income['estimatedRevenue'] <= 0:
                continue
            if income.get('currency', currency) != currency:
                result['reasonCodes'].append('mixed_revenue_currency')
                return result
            eligible.append({'domain': identity[0], 'url': visits['url'], 'title': visits.get('title', ''),
                             'sessions': visits['sessions'], 'pageViews': visits['pageViews'],
                             'estimatedRevenue': income['estimatedRevenue'], 'currency': currency,
                             'start': str(start), 'end': str(end), 'complete': True,
                             'revenueSource': earnings['source']})
        eligible.sort(key=lambda row: (-row['estimatedRevenue'], -row['sessions'], row['url']))
        result.update(complete=True, status='collected', eligiblePageCount=len(eligible),
                      revenueWinners=eligible[:math.ceil(len(eligible) * 0.1)])
        if not eligible:
            result['reasonCodes'].append('no_positive_joined_page_revenue')
    elif traffic_valid or revenue_valid or valid_domains:
        result['status'] = 'partial'
    result['coverage'] = {'trafficPages': len(pages), 'revenuePages': len(money),
                          'joinedPages': len(pages.keys() & money.keys()),
                          'trafficComplete': traffic_valid, 'revenueComplete': revenue_valid,
                          'completeTrafficDomains': sorted(valid_domains),
                          'exhaustiveTrafficDomains': sorted(domain for domain, report in domain_reports.items()
                                                             if report.get('fullEnumeration') is True)}
    # Radar can learn from measured acquisition before monetization is connected.
    # Ranking remains per-domain and names its evidence; revenueWinners stays strict.
    if domains is None:
        domains = list(read('metrics-config.json').get('sites', {}))
        if not domains:
            domains = sorted({row.get('site', {}).get('site_id') for row in
                (metrics.get('sites', {}).values() if isinstance(metrics.get('sites'), dict) else metrics.get('sites', []))
                if row.get('site', {}).get('platform') == 'cf'})
    domains = sorted(set(domains or valid_domains))
    source_sites = traffic_source.get('sites', {})
    source_sites = source_sites if isinstance(source_sites, dict) else {row.get('site', {}).get('site_id'): row for row in source_sites}
    result.update(radarCandidates=[], coldStartDomains=[], domainCoverage=[])
    for domain in domains:
        measured = [row for row in result['highTrafficPages'] if row['domain'] == domain]
        paid = [row for row in result['revenueWinners'] if row['domain'] == domain]
        # Full positive domain earnings may qualify even when another domain is missing.
        income_sites = earnings.get('sites', [])
        income_sites = list(income_sites.values()) if isinstance(income_sites, dict) else income_sites
        income_domain = next((row for row in income_sites if row.get('domain') == domain), {})
        income_report = {**earnings, **income_domain, 'status': income_domain.get('status', earnings.get('status', 'collected'))}
        domain_revenue_valid = (not revenue_duplicate and
            earnings.get('source') in ('AdSense Management API v2', 'AdSense Management API v2 PAGE_URL') and
            currency in ('USD', 'KRW') and valid_report(income_report, 'domain_revenue', False))
        if domain_revenue_valid:
            domain_money = [(identity, row) for identity, row in money.items()
                            if identity[0] == domain and row['estimatedRevenue'] > 0]
            if any(row.get('currency', currency) != currency for _, row in domain_money):
                paid = []
                result['reasonCodes'].append('mixed_revenue_currency:' + domain)
            else:
                paid = [{'domain': domain, 'url': row['url'], 'title': row.get('title', ''),
                         'sessions': pages.get(identity, {}).get('sessions') if domain in valid_domains else None,
                         'pageViews': pages.get(identity, {}).get('pageViews') if domain in valid_domains else None,
                         'estimatedRevenue': row['estimatedRevenue'], 'currency': currency,
                         'start': str(start), 'end': str(end), 'complete': True,
                         'revenueSource': earnings['source']} for identity, row in domain_money]
        candidates, basis = paid, 'adsense_revenue'
        if not candidates:
            candidates, basis = measured, 'ga4_sessions'
        if not candidates:
            google = source_sites.get(domain, {}).get('google', {})
            report = google.get('periods', {}).get('week', {})
            try:
                report_start, report_end = date.fromisoformat(report['start']), date.fromisoformat(report['end'])
                expected_end = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
                collected = datetime.fromisoformat((report.get('checkedAt') or google['checkedAt']).replace('Z', '+00:00'))
                gsc_valid = (report_end == expected_end and (report_end - report_start).days == 6 and
                    0 <= (now - collected).total_seconds() <= 26 * 3600 and
                    google.get('status') in ('collected', 'partial') and not google.get('stale') and
                    not report.get('partialPeriod'))
            except (ValueError, KeyError, TypeError):
                gsc_valid = False
            if gsc_valid:
                observed = {}
                for row in report.get('pages') or report.get('queries', []):
                    address = row.get('page') or row.get('url')
                    identity = key({'domain': domain, 'url': address})
                    if identity and number(row.get('clicks')) and row['clicks'] > 0:
                        entry = observed.setdefault(identity, {'domain': domain, 'url': address, 'title': '',
                            'sessions': None, 'pageViews': None, 'clicks': 0, 'start': report['start'], 'end': report['end'],
                            'timezone': 'America/Los_Angeles', 'complete': False,
                            'rankingScope': 'observed_page_rows_not_all_site_pages'})
                        entry['clicks'] += row['clicks']
                candidates = list(observed.values())
                basis = 'gsc_clicks'
        if candidates:
            metric = {'adsense_revenue': 'estimatedRevenue', 'ga4_sessions': 'sessions', 'gsc_clicks': 'clicks'}[basis]
            candidates.sort(key=lambda row: (-row[metric], row['url']))
            selected = candidates[:max(1, math.ceil(len(candidates) * 0.1))]
            result['radarCandidates'].extend({**row, 'selectionBasis': basis,
                'estimatedRevenue': row.get('estimatedRevenue') if basis == 'adsense_revenue' else None,
                'revenueVerified': basis == 'adsense_revenue', 'eligibleDomainPageCount': len(candidates),
                'rankingScope': row.get('rankingScope', 'domain_positive_pages')} for row in selected)
            result['domainCoverage'].append({'domain': domain, 'mode': 'revenue' if basis == 'adsense_revenue' else 'traffic',
                'selectionBasis': basis, 'selectedPages': len(selected), 'revenueVerified': basis == 'adsense_revenue'})
        else:
            state = 'measured_zero' if domain in result['coverage']['exhaustiveTrafficDomains'] else 'missing'
            cold = {'domain': domain, 'mode': 'cold_start', 'evidenceState': state,
                    'revenueVerified': False, 'reason': 'no_positive_measured_traffic' if state == 'measured_zero' else 'traffic_unavailable_or_incomplete'}
            result['coldStartDomains'].append(cold)
            result['domainCoverage'].append(cold)
    result['radarMode'] = ('revenue' if any(row['revenueVerified'] for row in result['radarCandidates']) else
                           'traffic' if result['radarCandidates'] else 'cold_start')
    return result


def refresh_performance_feedback():
    """Copy the measured page report to metrics after collection and publish feedback."""
    from common.dashboard_jobs import write
    from dashboard.metrics import collector_lock
    folder = ROOT / 'server/data'
    with collector_lock(folder / 'metrics.lock') as acquired:
        if not acquired:
            return {'status': 'busy', 'complete': False}
        def read(name):
            try:
                return json.loads((folder / name).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return {}
        metrics, traffic, revenue = read('metrics.json'), read('traffic.json'), read('revenue.json')
        # Preserve source timestamps and missingness; never upgrade cached data to fresh.
        metrics['pagePerformance'] = traffic.get('pagePerformance') or {'status': 'not_collected', 'complete': False, 'pages': []}
        evidence = page_performance_evidence(metrics=metrics, revenue=revenue)
        metrics['performanceFeedback'] = evidence
        write(folder / 'metrics.json', metrics)
        drive = os.environ.get('BAROLAB_GOOGLE_DRIVE_ROOT')
        if drive:
            target = Path(drive) / 'BaroLab/server/data'; target.mkdir(parents=True, exist_ok=True)
            for name in ('revenue.json', 'metrics.json', 'kin.json', 'threads.json'):
                shutil.copy2((folder if name in ('revenue.json', 'metrics.json') else ROOT / 'dashboard/data') / name, target / name)
        return evidence


def action_analysis():
    import sys
    dashboard = str(ROOT / 'dashboard')
    if dashboard not in sys.path:
        sys.path.insert(0, dashboard)
    import growth_analysis
    return growth_analysis


def action_evidence(domain, url, start, end):
    try:
        return action_analysis().action_evidence(domain, url, start, end)
    except (OSError, ValueError, KeyError, AttributeError):
        return {'status': 'not_collected', 'start': start, 'end': end,
                'reason': '정확한 기간의 원천 데이터 미수집 · 다른 기간 값으로 대체하지 않음'}


def maintenance_candidates(jobs, limit=5, moment=None):
    """Shortlist observed opportunities before paying for semantic ranking."""
    moment = moment or datetime.now(timezone.utc)
    analysis = action_analysis()
    windows = analysis.periods(moment)
    traffic = analysis.read_json(analysis.DATA / 'traffic.json')
    metrics = analysis.read_json(analysis.DATA / 'metrics.json')
    titles = {url: title for site in metrics.get('sites', {}).values()
              for url, title in site.get('posts', {}).get('titles', {}).items()}
    def identity(url):
        parsed = urlsplit(url)
        return ((parsed.hostname or '').removeprefix('www.'), parsed.path.rstrip('/'))
    by_url = {identity(job['url']): job for job in jobs}
    candidates = {}
    for domain, source in traffic.get('sites', {}).items():
        google = source.get('google', {})
        report = google.get('periods', {}).get('current28', {})
        if not analysis.report_valid(report, windows['current'], moment) or report.get('pagesStatus') != 'collected':
            continue
        for page in report.get('pages', []):
            job = by_url.get(identity(page.get('page', '')))
            position = page.get('position')
            if (not job or job['domain'] != domain or not analysis.measured_row(page)
                    or page['impressions'] < 10 or type(position) not in (int, float)
                    or not math.isfinite(position) or not 1 <= position <= 30):
                continue
            queries = [q['query'] for q in report.get('queries', [])
                       if q.get('query') and identity(q.get('page', '')) == identity(job['url'])]
            evidence = {'source': 'Google Search Console', 'start': report['start'], 'end': report['end'],
                        'checkedAt': report['checkedAt'], 'timezone': windows['searchTimezone'],
                        'maxAgeHours': 26, 'scope': 'observed_page_rows_not_all_pages',
                        **{k: page.get(k) for k in ('impressions', 'clicks', 'ctr', 'position')},
                        'revenueVerified': False, 'causalProof': False}
            candidates[job['id']] = {
                'id': job['id'], 'domain': domain, 'url': job['url'],
                'title': titles.get(job['url']) or titles.get(page['page']) or job['url'],
                'query': ' | '.join(queries[:3]),
                'issue': '실측 검색 노출이 있는 기존 글의 검색 의도·제목·답변 완전성 개선 후보; 개선 효과는 아직 미검증',
                'evidence': evidence}
    feedback = page_performance_evidence(now=moment, metrics=metrics, traffic_source=traffic)
    for page in feedback['highTrafficPages']:
        job = by_url.get(identity(page['url']))
        if not job or job['id'] in candidates:
            continue
        candidates[job['id']] = {
            'id': job['id'], 'domain': job['domain'], 'url': job['url'],
            'title': page.get('title') or titles.get(job['url']) or job['url'], 'query': '',
            'issue': '실측 방문이 있는 기존 글의 답변 완전성 점검 후보; 개선 효과는 아직 미검증',
            'evidence': {**page, 'source': 'GA4', 'checkedAt': page.get('checkedAt'),
                         'timezone': 'Asia/Seoul', 'revenueVerified': False, 'causalProof': False}}
    return sorted(candidates.values(), key=lambda c: (-c['evidence'].get('impressions', 0),
                  -c['evidence'].get('sessions', 0), c['url']))[:min(5, max(0, limit))]


def autonomy_goal(db, moment):
    # Match the daily importer; never roll back to an older profitable window.
    end = moment.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
    goal = revenue_goal(db, end)
    endpoints = db.execute("""SELECT d.complete,d.value,d.collected_at,d.source_timezone
        FROM sites s LEFT JOIN daily_metrics d ON d.site_id=s.site_id AND d.service='adsense'
        AND d.metric='revenue' AND d.day=? WHERE s.platform='cf'""", (end.isoformat(),)).fetchall()
    fresh_sites = 0
    for row in endpoints:
        try:
            collected = datetime.fromisoformat(row['collected_at'].replace('Z', '+00:00'))
            if (row['complete'] == 1 and row['value'] is not None
                    and row['source_timezone'] == 'America/Los_Angeles'
                    and timedelta(0) <= moment - collected <= timedelta(hours=26)):
                fresh_sites += 1
        except (AttributeError, TypeError, ValueError):
            pass
    fresh = bool(endpoints) and fresh_sites == len(endpoints)
    goal.update(periodBasis='collector_pacific_completed_dates',
                expectedSourceDataThrough=end.isoformat(), sourceDataThrough=end.isoformat() if fresh else None,
                reportingLagDays=3, freshness={'status': 'fresh' if fresh else 'unconfirmed',
                'freshSites': fresh_sites, 'requiredSites': len(endpoints), 'maxAgeHours': 26})
    if not fresh:
        goal.update(status='unknown', daily_average=None, achievement_pct=None,
                    reason=' · '.join(filter(None, [goal['reason'],
                        '최신 완료 원천일의 전체 사이트 수집 신선도 미확인 · 오래된 기간으로 대체하지 않음'])))
    return goal


def autonomy_summary(path=DEFAULT_DB, moment=None):
    moment = moment or datetime.now(timezone.utc)
    with connect(path) as db:
        goal = autonomy_goal(db, moment)
        actions = []
        for row in db.execute('SELECT * FROM improvement_actions WHERE completed_at IS NOT NULL ORDER BY updated_at DESC LIMIT 50').fetchall():
            item = action_record(row, moment)
            if item['verification']['status'] == 'observed_change' and not row['observation_snapshot']:
                db.execute('UPDATE improvement_actions SET observation_snapshot=? WHERE id=?',
                           (json.dumps({'followup': item['followup'], 'checkedAt': moment.isoformat()}, ensure_ascii=False), row['id']))
            actions.append(item)
    experiments = [item for item in actions if item.get('experiment')]
    return {'checkedAt': moment.isoformat(), 'goal': goal, 'experiments': experiments,
            'note': '공개 반영 완료는 수익 달성 아님 · 비교 가능한 관측 자료가 확보될 때까지 성과 미확인'}


def action_guard(request):
    from llm_api import trusted_settings_client
    host = request.url.hostname
    allowed = os.getenv('BAROLAB_ALLOWED_HOSTS', '127.0.0.1,localhost,::1').split(',')
    origin = request.headers.get('origin')
    expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
    if (host not in allowed or not trusted_settings_client(request.client.host if request.client else '')
            or (origin is not None and origin != expected)
            or request.headers.get('sec-fetch-site') == 'cross-site'):
        raise HTTPException(403, '허용된 대시보드에서만 개선 기록을 변경할 수 있습니다.')
    if (request.headers.get('x-barolab-settings') != '1'
            or request.headers.get('content-type', '').split(';')[0] != 'application/json'):
        raise HTTPException(403, '올바른 개선 기록 요청이 아닙니다.')


def action_target(db, domain, url):
    if not isinstance(domain, str) or not isinstance(url, str) or len(url) > 2048:
        raise ValueError('domain and URL required')
    site = db.execute('SELECT * FROM sites WHERE site_id=? AND platform=?', (domain, 'cf')).fetchone()
    if not site:
        raise ValueError('등록된 CF 도메인만 지원합니다.')
    target = urlsplit(url)
    try:
        ipaddress.ip_address(target.hostname or '')
    except ValueError:
        pass
    else:
        raise ValueError('IP 주소는 개선 대상 URL로 지원하지 않습니다.')
    if (target.scheme != 'https' or target.hostname not in (domain, 'www.' + domain)
            or target.username or target.password or target.port or target.fragment
            or '\\' in url or any(ord(c) < 32 for c in url)):
        raise ValueError('등록 도메인의 HTTPS 정식 URL을 입력하세요.')
    return domain, url


def measurement_date(row):
    experiment = json.loads(row.get('diagnosis_snapshot') or '{}').get('experiment') or {}
    return date.fromisoformat(experiment.get('measurementDate') or row['completed_at'])


def action_record(row, now=None):
    row = dict(row)
    now = now or datetime.now(timezone.utc)
    item = {'id': row['id'], 'domain': row['domain'], 'url': row['url'],
            'action': row['action'], 'note': row['note'], 'status': row['status'],
            'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
            'completedAt': row['completed_at'], 'planningBaseline': json.loads(row['planning_baseline']),
            'baseline': json.loads(row['baseline']) if row['baseline'] else None,
            'followup': None, 'observation': None,
            'diagnosisSnapshot': json.loads(row['diagnosis_snapshot']) if row.get('diagnosis_snapshot') else None,
            'verification': {'status': 'not_completed', 'causalProof': False}}
    experiment = (item.get('diagnosisSnapshot') or {}).get('experiment')
    if row['completed_at']:
        completed = measurement_date(row)
        source_dated = bool((experiment or {}).get('measurementDate'))
        start, end = completed + timedelta(days=1), completed + timedelta(days=28)
        through = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
        ready = end <= through
        item['observation'] = {'status': 'ready' if ready else 'observing',
                               'start': start.isoformat(), 'end': end.isoformat(),
                               'availableThrough': through.isoformat(),
                               'completionTimezone': 'Asia/Seoul', 'sourceTimezone': 'America/Los_Angeles',
                               'measurementDate': completed.isoformat(),
                               'measurementTimezone': 'America/Los_Angeles' if source_dated else 'Asia/Seoul',
                               'reason': ('실제 변경 시각의 Pacific 날짜를 기준으로 변경 당일 제외 전후 28일' if source_dated else
                                          '시각 미기록 기존 작업은 KST 완료일을 기준 날짜로 사용') +
                                         ' · 시각별 인과관계 판정 아님 · Google 보고 지연 3일 반영'}
        item['followup'] = action_evidence(row['domain'], row['url'], start.isoformat(), end.isoformat()) if ready else {
            'status': 'observing', 'start': start.isoformat(), 'end': end.isoformat(),
            'reason': '관측 기간이 끝나지 않아 성과를 판정하지 않음'}
        saved = json.loads(row.get('observation_snapshot') or '{}').get('followup') or {}
        if saved.get('status') == 'collected' and saved.get('start') == start.isoformat() and saved.get('end') == end.isoformat():
            item['followup'] = saved
        before, after = item['baseline'] or {}, item['followup']
        comparable = all(p.get('status') == 'collected' and all(p.get(k) is not None for k in ('clicks', 'impressions', 'ctr', 'position')) for p in (before, after))
        item['verification'] = {'status': 'observed_change' if comparable else ('awaiting_evidence' if ready else 'observing'),
                                'causalProof': False, 'clicksDelta': after['clicks'] - before['clicks'] if comparable else None,
                                'impressionsDelta': after['impressions'] - before['impressions'] if comparable else None,
                                'ctrPoints': (after['ctr'] - before['ctr']) * 100 if comparable else None,
                                'positionChange': before['position'] - after['position'] if comparable else None,
                                'reason': '고정된 사전 28일·완료 후 28일 원천 관측 변화 · 개선의 인과효과를 입증하지 않음' if comparable else '정확한 전후 보고서가 모두 확보될 때까지 미확인'}
    if experiment:
        item['experiment'] = {**experiment, 'measurement': item['observation'],
                              'performanceStatus': item['verification']['status'],
                              'observedChange': item['verification'], 'causalProof': False,
                              'revenueOutcome': {'status': 'unknown', 'amountUsd': None,
                                  'reason': '동일 URL·전후 관측기간의 페이지별 AdSense 수익 근거 미수집; 검색 증가를 수익으로 환산하지 않음'}}
    return item


def action_records(path):
    with connect(path) as db:
        records = []
        for original in db.execute('SELECT * FROM improvement_actions ORDER BY created_at DESC,id').fetchall():
            row = dict(original)
            old = json.loads(row['baseline']) if row['baseline'] else {}
            if row['completed_at'] and old.get('status') not in ('collected', 'complete'):
                day = measurement_date(row)
                candidate = action_evidence(row['domain'], row['url'], (day - timedelta(days=28)).isoformat(),
                                            (day - timedelta(days=1)).isoformat())
                if candidate.get('status') in ('collected', 'complete'):
                    row['baseline'] = json.dumps(candidate, ensure_ascii=False)
                    db.execute('UPDATE improvement_actions SET baseline=? WHERE id=?', (row['baseline'], row['id']))
            item = action_record(row)
            records.append(item)
            _record_growth_observation(item)
        return records


def _record_metric_increase(site_id, observation):
    """Complete source periods establish observed growth, never causal efficacy."""
    if observation.get('service') not in ('adsense', 'ga4', 'naver_blog'):
        return
    current, previous = observation.get('current') or {}, observation.get('previous') or {}
    signature = ('currency', 'source_timezone', 'value_kind', 'revenue_scope')
    values = (current.get('total'), previous.get('total'))
    if (current.get('status') != 'complete' or previous.get('status') != 'complete'
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values)
            or values[0] <= values[1] or values[1] < 0
            or not all(current.get(k) == previous.get(k) for k in signature)):
        return
    from common.llm_client import memory_event
    memory_event(f"growth:{site_id}:{observation['service']}:{previous['start']}:{current['end']}",
                 'growth_measured_increase', 'Complete comparable source periods show increased traffic or revenue; causation is unproved.',
                 evidence={'siteId': site_id, 'service': observation['service'], 'metric': observation.get('metric'),
                           'previous': previous, 'current': current, 'delta': values[0] - values[1],
                           'causalProof': False}, review=True)


def _record_growth_observation(item):
    verification = item.get('verification') or {}
    if (item.get('status') != 'done' or verification.get('status') != 'observed_change'
            or not any(isinstance(verification.get(k), (int, float)) and verification[k] > 0
                       for k in ('clicksDelta', 'impressionsDelta'))):
        return
    from common.llm_client import memory_event
    memory_event(f"growth:{item['id']}:{(item.get('observation') or {}).get('end')}",
                 'growth_measured_increase', 'Comparable source reports show an increase; causation is unproved.',
                 evidence={'actionId': item['id'], 'url': item['url'], 'baseline': item['baseline'],
                           'followup': item['followup'], 'verification': verification}, review=True)


def action_text(value, name, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise ValueError(f'{name} must be text of 1..{maximum} characters' if required else f'{name} must be text up to {maximum} characters')
    return value.strip()


def diagnosis_snapshot(domain, url):
    report = action_analysis().summary()
    diagnoses = report.get('diagnosis', {}).get('domains', [])
    selected = next((r for r in diagnoses if r.get('domain') == domain), None)
    pages = [r for r in report.get('priorities', []) if r.get('domain') == domain and r.get('url') == url]
    return {'capturedAt': datetime.now(timezone.utc).isoformat(), 'sourceCheckedAt': report.get('checkedAt'),
            'domain': domain, 'url': url, 'diagnosis': selected, 'pageEvidence': pages[:2],
            'causalProof': False, 'reason': '등록 시점의 원천 진단 고정 · 가설과 관측을 구분하며 이후 수정하지 않음'}


def make_router(path=DEFAULT_DB):
    router = APIRouter()

    @router.get('/api/growth/page-performance')
    def get_page_performance():
        return page_performance_evidence()

    @router.get('/api/growth/sites')
    def get_sites():
        with connect(path) as db:
            return [dict(r) for r in db.execute('SELECT * FROM sites ORDER BY platform,site_id')]

    @router.get('/api/growth')
    def get_growth(site_id: str = 'baronote.kr', days: int = 7, end: str | None = None):
        try:
            return snapshot(path, site_id, days, end)
        except KeyError:
            raise HTTPException(404, 'Unknown site')
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.get('/api/growth/action-center')
    def get_action_center():
        result = action_analysis().summary()
        from revenue import collection_health
        collection = result.get('diagnosis', {}).get('collection')
        if isinstance(collection, dict):
            collection['health'] = collection_health(collection)
            collection.setdefault('sourceStatus', collection.get('status'))
            collection['status'] = collection['health']['status']
            collection['reason'] = collection['health']['reason']
        return {**result, 'records': action_records(path)}

    @router.get('/api/growth/actions')
    def get_actions():
        return {'records': action_records(path)}

    @router.get('/api/growth/maintenance')
    def get_maintenance():
        from common.content_maintenance import public_summary
        return public_summary()

    @router.patch('/api/growth/maintenance')
    def patch_maintenance(request: Request, payload: dict):
        action_guard(request)
        from common.content_maintenance import policy_update
        try:
            return policy_update(payload)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @router.post('/api/growth/actions', status_code=201)
    def create_action(request: Request, payload: dict):
        action_guard(request)
        try:
            if set(payload) - {'domain', 'url', 'action', 'note'}:
                raise ValueError('unsupported action fields')
            text = action_text(payload.get('action'), 'action', 500, True)
            note = action_text(payload.get('note', ''), 'note', 4000)
            with connect(path) as db:
                db.execute('BEGIN IMMEDIATE')
                domain, url = action_target(db, payload.get('domain'), payload.get('url'))
                existing = db.execute('SELECT id FROM improvement_actions WHERE domain=? AND url=? AND action=? AND status!=?',
                                      (domain, url, text, 'done')).fetchone()
                if existing:
                    raise HTTPException(409, '동일한 진행 중 개선 기록이 이미 있습니다.')
                through = datetime.now(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
                planning = action_evidence(domain, url, (through - timedelta(days=27)).isoformat(), through.isoformat())
                identifier, stamp = uuid.uuid4().hex, datetime.now(timezone.utc).isoformat()
                frozen_diagnosis = diagnosis_snapshot(domain, url)
                db.execute('INSERT INTO improvement_actions (id,domain,url,action,note,status,created_at,updated_at,completed_at,planning_baseline,baseline,diagnosis_snapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (identifier, domain, url, text, note, 'planned', stamp, stamp, None,
                            json.dumps(planning, ensure_ascii=False), None, json.dumps(frozen_diagnosis, ensure_ascii=False)))
                row = db.execute('SELECT * FROM improvement_actions WHERE id=?', (identifier,)).fetchone()
                record = action_record(dict(row))
            return {'record': record, 'records': action_records(path)}
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(409, '동일한 진행 중 개선 기록이 이미 있습니다.')

    @router.patch('/api/growth/actions/{identifier}')
    def update_action(identifier: str, request: Request, payload: dict):
        action_guard(request)
        try:
            if not payload or set(payload) - {'status', 'note', 'completedAt'}:
                raise ValueError('unsupported action fields')
            with connect(path) as db:
                row = db.execute('SELECT * FROM improvement_actions WHERE id=?', (identifier,)).fetchone()
                if not row:
                    raise HTTPException(404, 'Unknown action')
                status = payload.get('status', row['status'])
                if status not in ('planned', 'in_progress', 'done'):
                    raise ValueError('invalid action status')
                if row['status'] == 'done' and status != 'done':
                    raise ValueError('완료된 기록은 재개할 수 없습니다. 후속 개선은 새 기록으로 등록하세요.')
                note = action_text(payload.get('note', row['note']), 'note', 4000)
                completed, baseline = None, None
                if status == 'done':
                    if 'completedAt' in payload and payload['completedAt'] is not None and (
                            not isinstance(payload['completedAt'], str) or not payload['completedAt']):
                        raise ValueError('completedAt must be YYYY-MM-DD or null')
                    completed = payload.get('completedAt', row['completed_at']) or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
                    if not isinstance(completed, str) or date.fromisoformat(completed).isoformat() != completed:
                        raise ValueError('completedAt must be YYYY-MM-DD')
                    day = date.fromisoformat(completed)
                    if day > datetime.now(ZoneInfo('Asia/Seoul')).date():
                        raise ValueError('future completion date is not allowed')
                    # Freeze completed baseline; editing only a note never refreshes historical evidence.
                    baseline = row['baseline'] if row['completed_at'] == completed and row['baseline'] else json.dumps(
                        action_evidence(row['domain'], row['url'], (day - timedelta(days=28)).isoformat(),
                                        (day - timedelta(days=1)).isoformat()), ensure_ascii=False)
                elif payload.get('completedAt') is not None:
                    raise ValueError('completedAt only applies to done actions')
                db.execute('UPDATE improvement_actions SET status=?,note=?,completed_at=?,baseline=?,updated_at=? WHERE id=?',
                           (status, note, completed, baseline, datetime.now(timezone.utc).isoformat(), identifier))
                updated = action_record(db.execute('SELECT * FROM improvement_actions WHERE id=?', (identifier,)).fetchone())
            return {'record': updated, 'records': action_records(path)}
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(409, '동일한 진행 중 개선 기록이 이미 있습니다.')

    return router


router = make_router()


def preview_app(path=DEFAULT_DB):
    app = FastAPI(title='BaroLab growth review preview')
    app.include_router(make_router(path))

    @app.get('/')
    @app.get('/growth.html')
    def page():
        return FileResponse(ROOT / 'dashboard' / 'growth.html')

    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--inventory', type=Path)
    parser.add_argument('--import-daily', type=Path)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--refresh-performance', action='store_true')
    parser.add_argument('--port', type=int, default=8791)
    args = parser.parse_args()
    for filename, importer in ((args.inventory, import_inventory), (args.import_daily, import_daily)):
        if filename:
            importer(args.db, json.loads(filename.read_text(encoding='utf-8-sig')))
    if args.refresh_performance:
        print(json.dumps(refresh_performance_feedback(), ensure_ascii=False))
    if args.serve:
        import uvicorn
        uvicorn.run(preview_app(args.db), host='127.0.0.1', port=args.port)
