"""Collection evidence, not process liveness. Local files contain no report values/secrets."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import os
import re
import subprocess
import time
import uuid

UTC = timezone.utc
INTERVAL = 1800
STALE_AFTER = 5400
ROTATE_BYTES = 5 * 1024 * 1024
CONFIG_KEYS = ('status', 'complete', 'stale', 'scope', 'period', 'reasonCode')


def stamp(now=None):
    return (now or datetime.now(UTC)).isoformat()


def date(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {} if default is None else default


def write(path, value):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'collection-observability.lock').open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        deadline = time.monotonic() + 2
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Observability writer busy')
                time.sleep(.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def records(folder):
    """Archive files are retained. A malformed line never becomes a successful run."""
    seen = set()
    for path in sorted(Path(folder).glob('collection-runs*.jsonl')):
        with path.open(encoding='utf-8', errors='replace') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if row.get('runId') and row['runId'] not in seen:
                        seen.add(row['runId']); yield row
                except (ValueError, TypeError, AttributeError):
                    continue


def append(folder, row, rotate_bytes=ROTATE_BYTES):
    """Caller holds the cross-process lock. Preserve damaged tails in a whole-file archive."""
    path = Path(folder) / 'collection-runs.jsonl'
    if path.exists() and path.stat().st_size:
        with path.open('rb') as stream:
            stream.seek(max(0, path.stat().st_size - 131072))
            tail = stream.read()
        if not tail.endswith(b'\n'):
            path.rename(path.with_name('collection-runs.partial-' + str(time.time_ns()) + '.jsonl'))
        elif path.stat().st_size >= rotate_bytes:
            path.rename(path.with_name('collection-runs.archive-' + str(time.time_ns()) + '.jsonl'))
    with path.open('ab') as stream:
        stream.write((json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8'))
        stream.flush(); os.fsync(stream.fileno())


def normalize(outcome, started, now):
    """Only complete, current-run, fresh evidence can produce a success."""
    row = {k: outcome.get(k) for k in CONFIG_KEYS}
    row['source'] = str(outcome.get('source', 'unknown'))[:160]
    row['scope'] = str(outcome.get('scope', 'unverified'))[:180]
    if row.get('reasonCode') and not re.fullmatch(r'[a-z0-9_:-]{1,64}', str(row['reasonCode'])):
        row['reasonCode'] = 'unclassified_source_status'
    row['required'] = outcome.get('required', True) is True
    row['attemptedAt'] = outcome.get('attemptedAt')
    row['lastSuccessAt'] = outcome.get('lastSuccessAt')
    row['durationSeconds'] = outcome.get('durationSeconds')
    attempted, success = date(row['attemptedAt']), date(row['lastSuccessAt'])
    current = attempted and started and started - timedelta(seconds=5) <= attempted <= now + timedelta(seconds=5)
    fresh = success and timedelta(seconds=-5) <= now - success <= timedelta(seconds=STALE_AFTER)
    status = str(outcome.get('status', 'unknown'))
    needs_period = any(word in row['scope'] for word in ('comparison', 'traffic', 'revenue'))
    def period_ok(period):
        if not isinstance(period, dict) or not period:
            return False
        if 'start' in period and 'end' in period:
            begin, end = date(str(period['start']) + 'T00:00:00+00:00'), date(str(period['end']) + 'T00:00:00+00:00')
            return bool(begin and end and begin <= end <= now + timedelta(days=1))
        return all(period_ok(p) for p in period.values())
    period_valid = not needs_period or period_ok(row.get('period'))
    if status == 'success' and (not current or not fresh or not period_valid or row['complete'] is not True or row['stale']):
        status = 'stale' if success and not fresh else 'unknown'
        row['reasonCode'] = 'not_current_complete_evidence'
    if status not in ('success', 'partial', 'failed', 'backoff', 'unknown', 'skipped', 'stale'):
        status = 'unknown'
    row['status'] = status
    row['stale'] = bool(row['stale'] or (success and not fresh))
    return row


def window_summary(rows, now, days):
    start = now - timedelta(days=days)
    observed = [r for r in rows if date(r.get('finishedAt')) and start <= date(r['finishedAt']) <= now]
    counts = {k: sum(r.get('collectionStatus') == k for r in observed)
              for k in ('success', 'failed', 'partial', 'unknown')}
    known = counts['success'] + counts['failed'] + counts['partial']
    first = min((date(r['startedAt']) for r in rows if date(r.get('startedAt'))), default=None)
    coverage_start = max(start, first) if first else None
    # Runtime starts include import/lock delays and are not scheduler due-time anchors.
    # Without durable enabled/due-time history, unobserved slots cannot be counted.
    expected, missing = None, None
    return {'days': days, 'start': stamp(start), 'end': stamp(now), 'observedRuns': len(observed),
            'counts': counts, 'knownOutcomeDenominator': known,
            'successRate': counts['success'] / known if known else None,
            'coverageStart': stamp(coverage_start) if coverage_start else None,
            'windowStartCovered': bool(first and first <= start),
            'fullWindowObserved': False,
            'scheduleCoverageVerified': False,
            'expectedSlotsSinceCoverageStart': expected,
            'missingSlots': missing,
            'note': '관측된 원천 결과 기준 · 미확인/미실행 구간을 성공으로 채우지 않음'}


def local_notice(events):
    """A local desktop attempt is not a delivery receipt. Never sends network messages."""
    if os.name != 'nt' or not events:
        return 'not_attempted'
    try:
        import base64
        script = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$n=New-Object System.Windows.Forms.NotifyIcon;"
                  "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
                  "$n.ShowBalloonTip(7000,'BaroLab',"
                  "'수집 상태가 변경되었습니다. 대시보드의 원천별 운영 상태를 확인하세요.',"
                  "[System.Windows.Forms.ToolTipIcon]::Info);Start-Sleep -Seconds 8;$n.Dispose()")
        subprocess.Popen(['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                          '-EncodedCommand', base64.b64encode(script.encode('utf-16le')).decode()],
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 'attempted_delivery_unverified'
    except OSError:
        return 'failed_to_launch'


def finish_run(folder, runtime, outcomes, now=None, rotate_bytes=ROTATE_BYTES, desktop=False):
    now = now or datetime.now(UTC)
    folder = Path(folder)
    started = date(runtime.get('startedAt'))
    run_id = runtime.get('runId') or runtime.get('startedAt')
    if not started or not run_id:
        raise ValueError('A stable run identity and offset-aware start are required')
    normalized = [normalize(o, started, now) for o in outcomes]
    statuses = [o['status'] for o in normalized if o['required']]
    process_ok = all(s.get('status') == 'completed' and s.get('exitCode') == 0 for s in runtime.get('stages', [])) and bool(runtime.get('stages'))
    collection = ('failed' if not process_ok or (statuses and all(s in ('failed', 'backoff', 'stale') for s in statuses)) else 'success' if statuses and all(s == 'success' for s in statuses)
                  else 'partial' if any(s in ('success', 'failed', 'partial', 'backoff', 'stale') for s in statuses) else 'unknown')
    row = {'schema': 1, 'runId': run_id, 'startedAt': runtime['startedAt'], 'finishedAt': stamp(now),
           'durationSeconds': max(0, (now - started).total_seconds()),
           'processStatus': 'success' if process_ok else 'failed', 'collectionStatus': collection,
           'sources': normalized}
    with locked(folder):
        previous = load(folder / 'collection-health.json')
        # Rebuild identities from durable lines, including crash-before-health-write records.
        history = list(records(folder))
        if any(r['runId'] == run_id for r in history):
            return {'duplicate': True, 'runId': run_id}
        append(folder, row, rotate_bytes)
        prior_sources = {s['source'] + '|' + s['scope']: s for s in previous.get('sources', [])}
        alert_state = load(folder / 'collection-alert-state.json')
        events = []
        for source in normalized:
            key = source['source'] + '|' + source['scope']
            prior = prior_sources.get(key, {})
            # Failed runs cannot refresh the last verified success from stale cached values.
            source['verifiedLastSuccessAt'] = source['lastSuccessAt'] if source['status'] == 'success' else prior.get('verifiedLastSuccessAt')
            old = alert_state.get(key, {})
            bad = source['required'] and source['status'] in ('failed', 'partial', 'backoff', 'stale', 'unknown')
            recovered = source['status'] == 'success' and old.get('degraded')
            last_alert = date(old.get('lastAlertAt'))
            if recovered or (bad and (not old.get('degraded') or not last_alert or now - last_alert >= timedelta(hours=6))):
                event = {'id': uuid.uuid4().hex, 'at': stamp(now), 'kind': 'recovery' if recovered else 'failure',
                         'source': source['source'], 'scope': source['scope'], 'status': source['status'],
                         'delivery': 'dashboard_recorded', 'externalDelivery': 'not_enabled'}
                events.append(event)
                alert_state[key] = {'degraded': bad, 'lastAlertAt': stamp(now)}
            elif bad:
                source['duplicateAlertSuppressed'] = True
        with (folder / 'collection-alerts.jsonl').open('a', encoding='utf-8') as stream:
            for event in events: stream.write(json.dumps(event, ensure_ascii=False) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        history.append(row)
        delivery = local_notice(events) if desktop else 'dashboard_only'
        health = {'schema': 1, 'checkedAt': stamp(now), 'startedAt': runtime['startedAt'],
                  'runId': run_id, 'processStatus': row['processStatus'], 'collectionStatus': collection,
                  'sources': normalized, 'alerts': events, 'sourceCount': len(normalized),
                  'windows': {str(n): window_summary(history, now, n) for n in (7, 30)},
                  'externalNotifications': 'not_enabled_recipient_not_approved',
                  'excludedSources': [{'source': s['source'], 'scope': s['scope'], 'status': s['status']}
                                      for s in normalized if not s['required']],
                  'localNotifications': delivery,
                  'retention': '5MB archive rotation; no automatic archive deletion'}
        write(folder / 'collection-alert-state.json', alert_state)
        write(folder / 'collection-health.json', health)
        return health


def read_health(folder, now=None):
    now = now or datetime.now(UTC)
    health = load(Path(folder) / 'collection-health.json')
    if not health:
        return {'collectionStatus': 'unknown', 'reason': '새 운영 이력 수집 전 · 과거 성공률 미확인', 'windows': {}}
    # Correct legacy derived estimates in the read view; never rewrite ledger evidence.
    for window in health.get('windows', {}).values():
        if window.get('scheduleCoverageVerified') is not True:
            window.update(expectedSlotsSinceCoverageStart=None, missingSlots=None,
                          scheduleCoverageVerified=False, fullWindowObserved=False)
    error = load(Path(folder) / 'collection-observability-error.json')
    if date(error.get('checkedAt')) and date(health.get('checkedAt')) and date(error['checkedAt']) >= date(health['checkedAt']):
        health.update(collectionStatus='unknown', observabilityError='ledger_write_failed')
    checked = date(health.get('checkedAt'))
    health['heartbeatStale'] = not checked or now - checked > timedelta(seconds=STALE_AFTER)
    if health['heartbeatStale']:
        health['collectionStatus'] = 'stale'
    for source in health.get('sources', []):
        success = date(source.get('verifiedLastSuccessAt'))
        if source['status'] == 'success' and (not success or now - success > timedelta(seconds=STALE_AFTER)):
            source.update(status='stale', stale=True)
            health['collectionStatus'] = 'stale'
    alert_file = Path(folder) / 'collection-alerts.jsonl'
    if alert_file.exists():
        with alert_file.open('rb') as stream:
            stream.seek(max(0, alert_file.stat().st_size - 32768))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()
        alerts = []
        for line in lines:
            try:
                alerts.append(json.loads(line))
            except ValueError:
                continue
        health['recentAlerts'] = alerts[-20:]
    return health


def watchdog_check(folder, now=None, desktop=False):
    """Existing Windows worker calls this even if scheduled collectors stop running."""
    now = now or datetime.now(UTC)
    folder = Path(folder)
    with locked(folder):
        health = read_health(folder, now)
        if not health.get('checkedAt'):
            return None  # No invented pre-install outage or recovery.
        state_path = folder / 'collection-watchdog.json'
        previous = load(state_path)
        stale = health.get('heartbeatStale', False)
        last = date(previous.get('lastAlertAt'))
        emit = (stale and (not previous.get('stale') or not last or now-last >= timedelta(hours=6))) or (not stale and previous.get('stale'))
        event = None
        if emit:
            event = {'id': uuid.uuid4().hex, 'at': stamp(now), 'kind': 'failure' if stale else 'recovery',
                     'source': 'collector-heartbeat', 'scope': 'scheduled-30-minute-run',
                     'status': 'stale' if stale else 'fresh', 'delivery': 'dashboard_recorded',
                     'externalDelivery': 'not_enabled'}
            with (folder / 'collection-alerts.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event) + '\n'); stream.flush(); os.fsync(stream.fileno())
            previous['lastAlertAt'] = stamp(now)
        previous.update(stale=stale, checkedAt=stamp(now), localNotifications=local_notice([event]) if desktop and event else 'not_attempted')
        write(state_path, previous)
        return event


def snapshot_outcomes(root, script):
    """Conservative adapters for existing collectors; explicit future outcomes take precedence."""
    root = Path(root)
    filename = {'dashboard/revenue.py': 'revenue.json', 'dashboard/traffic.py': 'traffic.json',
                'dashboard/metrics.py': 'metrics.json'}[script]
    payload = load(root / 'server/data' / filename)
    if isinstance(payload.get('collectionOutcomes'), list):
        return payload['collectionOutcomes']
    result = []
    config = load(root / 'server/data/metrics-config.json')
    inventory = load(root / 'server/data/metrics.json')
    expected = list(config.get('sites', {}))
    if not expected:
        expected = [s['site_id'] for s in inventory.get('inventorySites', [])
                    if s.get('platform') == 'cf' and s.get('site_id')]
    if not expected:
        expected = list(payload.get('sites', {}))
        result.append({'source': 'configured-inventory', 'scope': 'expected-domain-coverage',
                       'status': 'unknown', 'complete': False, 'required': True,
                       'reasonCode': 'expected_inventory_missing'})

    def add(source, scope, obj, complete=False, period=None, required=True):
        status = {'collected': 'success', 'error': 'failed', 'failed': 'failed', 'backoff': 'backoff',
                  'partial': 'partial', 'stale': 'stale', 'skipped': 'skipped',
                  'not_collected': 'unknown', 'not_connected': 'unknown'}.get(obj.get('status'), 'unknown')
        if status == 'success' and not complete:
            status = 'partial'
        result.append({'source': source, 'scope': scope, 'status': status,
                       'attemptedAt': obj.get('attemptedAt') or obj.get('lastAttemptAt') or obj.get('lastRunAt') or obj.get('checkedAt'),
                       'lastSuccessAt': obj.get('checkedAt') if complete else None,
                       'complete': complete, 'stale': bool(obj.get('stale')), 'period': period,
                       'required': required, 'reasonCode': 'source_' + re.sub('[^a-z_]', '', str(obj.get('status', 'unknown'))),
                       'durationSeconds': obj.get('elapsedSeconds')})

    if script == 'dashboard/traffic.py':
        for domain in expected:
            site = payload.get('sites', {}).get(domain, {})
            for kind in ('ga4', 'google'):
                obj = site.get(kind, {})
                names = ('day', 'week', 'month') if kind == 'ga4' else ('current28', 'previous28')
                periods = [obj.get('periods', {}).get(n, {}) for n in names]
                complete = all(p.get('start') and p.get('end') and not p.get('partialPeriod') and not p.get('limited') for p in periods)
                numeric = ('users', 'sessions', 'pageViews') if kind == 'ga4' else ('clicks', 'impressions', 'ctr', 'position')
                complete = complete and all(all(isinstance(p.get(k), (int, float)) and not isinstance(p.get(k), bool) for k in numeric) for p in periods)
                if kind == 'google':
                    complete = complete and all(p.get('queriesStatus') == 'collected' and p.get('pagesStatus') == 'collected' for p in periods)
                    # Current top-level attempt cannot refresh a cached comparison window.
                    checked = date(obj.get('checkedAt'))
                    complete = complete and checked is not None and all(date(p.get('checkedAt')) and abs((date(p['checkedAt'])-checked).total_seconds()) < 120 for p in periods)
                    current_end = date(str(periods[0].get('end', '')) + 'T00:00:00+00:00')
                    complete = complete and bool(checked and current_end and timedelta(0) <= checked-current_end <= timedelta(days=7))
                add(kind + ':' + domain, 'traffic-day-week-month' if kind == 'ga4' else 'gsc-28d-comparison-toprows',
                    obj, complete, {n: {'start': p.get('start'), 'end': p.get('end')} for n,p in zip(names,periods)})
            add('bing:' + domain, 'historical-provider-toprows-not-exact-window',
                site.get('bing', {}), False, site.get('bing', {}).get('period'))
            naver = site.get('naver', {}) or site.get('naverSearch', {})
            add('naver-search:' + domain, 'search-advisor-partial-rounded-toprows', naver, False, naver.get('period'))
        naver = payload.get('naverBlogs', {})
        entries = naver.items() if isinstance(naver, dict) else enumerate(naver)
        for key, item in entries:
            if not isinstance(item, dict):
                continue
            source = str(item.get('blogId') or item.get('id') or key)
            periods = item.get('periods', {})
            period = {n: {'start': p.get('start'), 'end': p.get('end')} for n,p in periods.items() if isinstance(p,dict)}
            add('naver:' + source, 'blog-traffic-snapshot', item,
                item.get('status') == 'collected' and not item.get('stale') and bool(period), period)
    elif script == 'dashboard/revenue.py':
        month = max(payload.get('months', {}), default=None)
        sources = {s.get('id'): s for s in payload.get('months', {}).get(month, {}).get('sources', [])}
        required_ids = config.get('observability', {}).get('expectedRevenueSources') or ['adsense-sj', 'adsense-aaa10291028', 'adpost-soul5373', 'coupang']
        for source_id in dict.fromkeys([*required_ids, *sources]):
            obj = sources.get(source_id, {'id': source_id})
            start, end = date(str(obj.get('reportStart', '')) + 'T00:00:00+00:00'), date(str(obj.get('reportEnd', '')) + 'T00:00:00+00:00')
            daily = obj.get('daily', {})
            expected = {(start + timedelta(days=n)).date().isoformat() for n in range((end-start).days+1)} if start and end and 0 <= (end-start).days <= 366 else set()
            complete = bool(expected and isinstance(daily, dict) and expected.issubset(daily))
            checked = date(obj.get('checkedAt'))
            complete = complete and bool(checked and end and timedelta(0) <= checked-end <= timedelta(days=2))
            required = source_id in required_ids
            add('revenue:' + str(obj.get('id', 'unknown')), 'revenue-month-to-date-' + str(obj.get('valueKind', 'unknown')),
                obj, complete, {'start': obj.get('reportStart'), 'end': obj.get('reportEnd')}, required)
    else:
        for domain in expected:
            settings = config.get('sites', {}).get(domain, {})
            route = 'api' if settings.get('search_property') else 'owner-ui'
            obj = payload.get('sites', {}).get(domain, {}).get('google', {})
            rows = obj.get('urls', [])
            rows = rows if isinstance(rows, list) else list(rows.values()) if isinstance(rows, dict) else []
            attempts = [r for r in rows if date(r.get('attemptAt'))]
            last_attempt = max((r['attemptAt'] for r in attempts), default=None)
            successful = [r for r in rows if r.get('lastSuccessAt')]
            latest_success = max((r['lastSuccessAt'] for r in successful), default=None)
            summary = obj.get('collection', {})
            complete = bool(rows and summary.get('currentInspected') == len(rows) and not summary.get('failed')
                            and not summary.get('neverInspected') and not summary.get('staleInspected'))
            status = 'collected' if complete else 'partial' if successful else 'error' if summary.get('failed') else 'not_collected'
            inspected = {'status': status, 'attemptedAt': last_attempt, 'checkedAt': latest_success,
                         'reasonCode': 'domain_url_coverage', 'stale': bool(summary.get('staleInspected'))}
            add('url-inspection-' + route + ':' + domain, 'domain-public-url-evidence-not-serp-rank', inspected, complete)
        for account, obj in payload.get('inspectionAutomation', {}).get('accounts', {}).items():
            attempted = obj.get('attempted', 0)
            complete = obj.get('status') in ('collected', 'completed') and isinstance(attempted, int) and attempted > 0 and obj.get('completed') == attempted
            copy = dict(obj)
            if complete:
                copy.update(status='collected', checkedAt=obj.get('finishedAt'))
            add('url-inspection-account:' + account, 'bounded-url-inspection-batch-not-whole-inventory', copy, complete)
    return result or [{'source': script, 'scope': 'collector-outcomes', 'status': 'unknown',
                       'complete': False, 'reasonCode': 'missing_source_evidence'}]


def export_public_health(folder, destination, now=None):
    """Export status only. Private ledger, errors and revenue details remain private."""
    now = now or datetime.now(UTC)
    statuses = {'success', 'partial', 'failed', 'unknown', 'stale', 'backoff', 'skipped'}
    def state(value):
        return value if isinstance(value, str) and value in statuses else 'unknown'
    def timestamp(value):
        return value if isinstance(value, str) and date(value) else None
    def label(value):
        return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_.:/ -]{1,180}', value) else 'unverified'
    def count(value):
        return value if type(value) is int and value >= 0 else None
    def source(row):
        safe = {'source': label(row.get('source')), 'scope': label(row.get('scope')),
                'status': state(row.get('status')), 'stale': row.get('stale') is True,
                'required': row.get('required') is True,
                'duplicateAlertSuppressed': row.get('duplicateAlertSuppressed') is True}
        for key in ('checkedAt', 'attemptedAt', 'lastSuccessAt', 'verifiedLastSuccessAt'):
            safe[key] = timestamp(row.get(key))
        return safe
    def is_public(row):
        return isinstance(row, dict) and not str(row.get('source', '')).startswith('revenue:')
    with locked(folder):
        health = read_health(folder, now)
        rows = health.get('sources', [])
        excluded = health.get('excludedSources', [])
        public = {'schema': 1, 'evidenceMode': 'windows_static_fallback', 'nasBackend': 'pending',
                  'exportedAt': stamp(now), 'checkedAt': timestamp(health.get('checkedAt')),
                  'startedAt': timestamp(health.get('startedAt')), 'runId': label(health.get('runId')),
                  'processStatus': state(health.get('processStatus')),
                  'collectionStatus': state(health.get('collectionStatus')),
                  'sourceCount': count(health.get('sourceCount')),
                  'sources': [source(row) for row in rows if is_public(row)],
                  'redactedSourceCount': sum(not is_public(row) for row in rows),
                  'excludedSourcesCount': len(excluded),
                  'excludedSources': [source(row) for row in excluded if is_public(row)],
                  'localNotifications': health.get('localNotifications') if health.get('localNotifications') in
                      ('attempted_delivery_unverified', 'failed_to_launch', 'dashboard_only') else 'unverified',
                  'externalNotifications': 'disabled_by_user_choice', 'windows': {}, 'recentAlerts': []}
        for days in ('7', '30'):
            window = health.get('windows', {}).get(days)
            if not isinstance(window, dict):
                continue
            safe = {key: count(window.get(key)) for key in
                    ('days', 'observedRuns', 'knownOutcomeDenominator', 'expectedSlotsSinceCoverageStart', 'missingSlots')}
            safe.update({key: timestamp(window.get(key)) for key in ('start', 'end', 'coverageStart')})
            safe.update({key: window.get(key) is True for key in ('fullWindowObserved', 'windowStartCovered', 'scheduleCoverageVerified')})
            safe['counts'] = {key: count(window.get('counts', {}).get(key)) for key in ('success', 'failed', 'partial', 'unknown')}
            public['windows'][days] = safe
        for event in health.get('recentAlerts', [])[-20:]:
            if is_public(event) and event.get('kind') in ('failure', 'recovery'):
                public['recentAlerts'].append({'at': timestamp(event.get('at')), 'kind': event['kind'],
                                              'source': label(event.get('source'))})
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        write(destination, public)
        return public
