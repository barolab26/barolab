"""Growth read API and explicit local import. No publisher or credential access."""
import argparse
import json
import math
import os
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
        # Company goal: all listed CF sites must have complete, compatible USD data.
        eligible = [s for s in sites if s['platform'] == 'cf']
        targets = [series(db, s['site_id'], 'adsense', end, 30) for s in eligible]
        ready = [t for t in targets if t['total'] is not None and t['currency'] == 'USD'
                 and t['revenue_scope'] == 'excludes_arbitrage']
        full = bool(targets) and len(ready) == len(targets)
        full = full and len({(t['source_timezone'], t['value_kind']) for t in targets}) == 1
        average = sum(t['total'] for t in targets) / 30 if full else None
        goal = {'scope': '등록 CF 도메인 전체', 'site_count': len(eligible),
                'complete_sites': len(ready),
                'start': dates(end, 30)[0], 'end': end.isoformat(), 'currency': 'USD',
                'daily_target': 100, 'daily_average': average,
                'achievement_pct': average if average is not None else None,
                'source_timezone': targets[0]['source_timezone'] if full else None}
    for observation in result:
        _record_metric_increase(site_id, observation)
    return {'site': site, 'sites': sites, 'days': days, 'end': end.isoformat(),
            'requested_timezone': 'Asia/Seoul', 'services': result, 'goal': goal,
            'queried_at': datetime.now(timezone.utc).isoformat()}


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
    if row['completed_at']:
        completed = date.fromisoformat(row['completed_at'])
        start, end = completed + timedelta(days=1), completed + timedelta(days=28)
        through = now.astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
        ready = end <= through
        item['observation'] = {'status': 'ready' if ready else 'observing',
                               'start': start.isoformat(), 'end': end.isoformat(),
                               'availableThrough': through.isoformat(),
                               'completionTimezone': 'Asia/Seoul', 'sourceTimezone': 'America/Los_Angeles',
                               'reason': 'KST 완료일을 기준 날짜로 사용 · Pacific 보고서의 당일 제외 전후 28일 · 시각별 인과관계 판정 아님 · Google 보고 지연 3일 반영'}
        item['followup'] = action_evidence(row['domain'], row['url'], start.isoformat(), end.isoformat()) if ready else {
            'status': 'observing', 'start': start.isoformat(), 'end': end.isoformat(),
            'reason': '관측 기간이 끝나지 않아 성과를 판정하지 않음'}
        before, after = item['baseline'] or {}, item['followup']
        comparable = all(p.get('status') == 'collected' and all(p.get(k) is not None for k in ('clicks', 'impressions', 'ctr', 'position')) for p in (before, after))
        item['verification'] = {'status': 'observed_change' if comparable else ('awaiting_evidence' if ready else 'observing'),
                                'causalProof': False, 'clicksDelta': after['clicks'] - before['clicks'] if comparable else None,
                                'impressionsDelta': after['impressions'] - before['impressions'] if comparable else None,
                                'ctrPoints': (after['ctr'] - before['ctr']) * 100 if comparable else None,
                                'positionChange': before['position'] - after['position'] if comparable else None,
                                'reason': '완료 전후 정확한 28일 관측 변화 · 개선의 인과효과를 입증하지 않음' if comparable else '정확한 전후 보고서가 모두 확보될 때까지 미확인'}
    return item


def action_records(path):
    with connect(path) as db:
        records = []
        for original in db.execute('SELECT * FROM improvement_actions ORDER BY created_at DESC,id').fetchall():
            row = dict(original)
            old = json.loads(row['baseline']) if row['baseline'] else {}
            if row['completed_at'] and old.get('status') not in ('collected', 'complete'):
                day = date.fromisoformat(row['completed_at'])
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
    parser.add_argument('--port', type=int, default=8791)
    args = parser.parse_args()
    for filename, importer in ((args.inventory, import_inventory), (args.import_daily, import_daily)):
        if filename:
            importer(args.db, json.loads(filename.read_text(encoding='utf-8-sig')))
    if args.serve:
        import uvicorn
        uvicorn.run(preview_app(args.db), host='127.0.0.1', port=args.port)
