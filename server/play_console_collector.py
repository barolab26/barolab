"""Read-only Play Console observations, isolated from release/tester mutations.

Only the existing SJ Windows browser is used. One explicitly owned temporary
page is closed in finally; user pages, browser lifecycle and forms are untouched.
No tester count or 14-day progress is inferred from a mailing list or installation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'server/data/play-console-status.json'
TTL_SECONDS = 300
DEVELOPER_ID = '7752283694845461925'
APP_IDS = {
    'bible_app': '4975007773224005878', 'greeting': '4973731498485355571',
    'magnifier': '4972819523776643880', 'shopping': '4972748430542309887',
}
APP_LABELS = {'bible_app': '오늘의 성경말씀', 'greeting': '오늘의 안부',
              'magnifier': '큰글씨 돋보기', 'shopping': '말로 장보기'}
_THREAD_LOCK = threading.Lock()
_PERIODIC_LOCK = threading.Lock()
_STOP = threading.Event()
_PERIODIC_THREAD = None


def atomic_write(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix='play-console-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def collector_lock(path):
    """Nonblocking OS lock; crashes release ownership without stale lock files."""
    with path.open('a+b') as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b'0')
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


def now():
    return datetime.now(timezone.utc).isoformat()


def _age(stamp):
    try:
        parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return float('inf')
        return max(0, (datetime.now(timezone.utc) - parsed).total_seconds())
    except (ValueError, TypeError, AttributeError):
        return float('inf')


def _load(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def empty_app(app):
    return {'appId': app, 'playAppId': APP_IDS[app], 'status': 'never_collected',
            'checkedAt': None, 'lastAttemptAt': None, 'error': None, 'stale': True,
            'alpha': {'reviewStatus': 'unknown', 'trackActive': None, 'released': None,
                      'versionCode': None},
            'internal': {'released': None, 'versionCode': None},
            'googleOptInCount': None, 'googleInstallCount': None,
            'continuousTestDays': None, 'evidence': []}


def _signal(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return match
    return None


def parse_observation(app, pages, checked_at=None):
    """Parse explicit observed statements only, never eligibility requirements.

    pages maps alpha/internal/dashboard/publishing to {url,text}. Text must be
    rendered UI text from the named page, not an API payload or hidden state.
    """
    result = empty_app(app)
    result.update(status='collected', checkedAt=checked_at or now(), stale=False)
    for kind, observation in pages.items():
        target = observation.get('url', '')
        parsed = urlsplit(target)
        expected = f'/developers/{DEVELOPER_ID}/app/{APP_IDS[app]}/'
        if parsed.hostname != 'play.google.com' or expected not in parsed.path:
            raise ValueError('wrong_app_or_authentication_page')
        text = observation.get('text', '')
        if not text.strip():
            raise ValueError('empty_console_page')
        evidence = {'page': kind, 'url': target, 'checkedAt': result['checkedAt'],
                    'textSha256': hashlib.sha256(text.encode()).hexdigest(), 'signals': {}}
        signals = evidence['signals']
        if kind == 'releases':
            # Only the "latest releases" grid, never the adjacent bundle grid.
            # Its installation column may contain percentages, so it is ignored.
            for track, label in [('alpha', '비공개 테스트 - Alpha'), ('internal', '내부 테스트')]:
                rows = [row for row in observation.get('rows', [])
                        if len(row) >= 4 and row[2].strip() == label]
                if len(rows) != 1:
                    continue
                row = rows[0]
                status = row[3].strip()
                result[track]['releaseStatus'] = status
                if re.fullmatch(r'\d+', row[1].strip()):
                    result[track]['versionCode'] = int(row[1].strip())
                available = ('Google Play에서 테스터에게 제공' in status if track == 'alpha'
                             else '내부 테스터에게 제공됨' in status)
                if available:
                    result[track]['released'] = True
                    if track == 'alpha':
                        result[track]['reviewStatus'] = 'approved'
                elif '검토 중' in status:
                    result[track]['released'] = False
                    if track == 'alpha':
                        result[track]['reviewStatus'] = 'in_review'
                signals[track + '.latestRelease'] = ' | '.join(row[:5])
        if kind in ('alpha', 'internal'):
            section = result[kind]
            released = _signal(text, [r'내부 테스터에게 제공됨' if kind == 'internal' else r'비공개 테스터에게 제공됨',
                                      r'Available to internal testers' if kind == 'internal' else r'Available to closed testers'])
            if released:
                section['released'] = True
                signals['released'] = released[0]
            version = _signal(text, [r'^버전 코드\s*[:：]\s*(\d+)\s*$', r'^Version code\s*[:：]\s*(\d+)\s*$'])
            if version:
                section['versionCode'] = int(version[1])
                signals['versionCode'] = version[0]
            if kind == 'alpha':
                active = _signal(text, [r'활성\s*최신 출시 버전[^\n]*', r'^Active\s*(?:Latest release[^\n]*)?$'])
                paused = _signal(text, [r'^일시중지됨\s*$', r'^Paused\s*$'])
                if active or paused:
                    section['trackActive'] = bool(active)
                    signals['trackActive'] = (active or paused)[0]
                for status, patterns in [
                    ('in_review', [r'검토 중', r'In review']),
                    ('rejected', [r'출시가 거부됨', r'Release rejected']),
                    ('approved', [r'게시할 준비가 된 변경사항', r'Changes ready to publish']),
                    ('not_submitted', [r'변경사항이 아직 검토를 위해 제출되지 않음'])]:
                    match = _signal(text, patterns)
                    if match:
                        section['reviewStatus'] = status
                        signals['reviewStatus'] = match[0]
                        break
        # Publishing review status is app-wide, not proof that Alpha is released.
        if kind == 'publishing':
            result['publishing'] = {'reviewStatus': 'unknown'}
            for status, phrase in [('in_review', '검토 중인 변경사항'),
                                   ('approved', '게시할 준비가 된 변경사항'),
                                   ('not_submitted', '변경사항이 아직 검토를 위해 제출되지 않음')]:
                if phrase in text:
                    result['publishing']['reviewStatus'] = status
                    signals['publishingReviewStatus'] = phrase
                    break
        # Exact measurement labels exclude "최소 12명", "14일 이상", list sizes,
        # internal tester capacity, manual installation totals and release dates.
        if kind in ('dashboard', 'alpha'):
            if kind == 'dashboard':
                active = _signal(text, [r'비공개 테스트\s*\n(활성|비활성)\s*\n(?:brightness_1\s*\n)?트랙 1개'])
                if active:
                    result['alpha']['trackActive'] = active[1] == '활성'
                    signals['alpha.trackActive'] = active[0]
            patterns = {
                'googleOptInCount': [r'^(?:현재 참여를 선택한 테스터|현재 참여 중인 테스터|참여 중인 테스터 수|Opted-in testers)\s*[:：]?\s*(\d[\d,]*)\s*(?:명)?\s*$'],
                'googleInstallCount': [r'^(?:현재 설치된 기기|설치된 기기 수|Installed devices)\s*[:：]?\s*(\d[\d,]*)\s*(?:대)?\s*$'],
                'continuousTestDays': [r'^(?:연속 테스트 일수|연속 참여 일수|Continuous testing days)\s*[:：]?\s*(\d+)\s*(?:일|days)?\s*$'],
            }
            for field, expressions in patterns.items():
                match = _signal(text, expressions)
                if match:
                    result[field] = int(match[1].replace(',', ''))
                    signals[field] = match[0]
        result['evidence'].append(evidence)
    return result


def _read_page(page, url, heading, app):
    page.goto(url, wait_until='domcontentloaded', timeout=30000)
    page.get_by_role('button', name=re.compile('^' + re.escape(APP_LABELS[app]))).first.wait_for(timeout=20000)
    page.get_by_role('heading', name=heading, exact=True).first.wait_for(timeout=20000)
    # Authentication redirects and cross-app routing are rejected by the parser.
    return {'url': page.url, 'text': page.locator('body').inner_text(timeout=10000)}


@contextmanager
def owned_console_page(browser):
    if not browser.contexts:
        raise RuntimeError('existing_browser_context_missing')
    context = browser.contexts[0]
    before = [(pg, pg.url) for pg in context.pages]
    digest = hashlib.sha256(json.dumps([(id(pg), url) for pg, url in before]).encode()).hexdigest()
    ownership = {'existingTabCount': len(before), 'existingIdentityUrlSha256': digest,
                 'existingTabsPreserved': None, 'tabOwnership': 'owned'}
    page = context.new_page()
    try:
        yield page, ownership
    finally:
        page.close()
        remaining = context.pages
        ownership['existingTabsPreserved'] = all(pg in remaining and pg.url == url for pg, url in before)
        ownership['ownedPageClosed'] = page not in remaining
        ownership['tabOwnership'] = 'owned_and_closed' if ownership['ownedPageClosed'] else 'owned_cleanup_failed'


def collect_browser():
    """Read an explicitly configured native session; never substitute another account."""
    from common.ubuntu_naver_browser import account_paths
    from common.browser_session import _runtime
    from playwright.sync_api import sync_playwright
    port=int(os.getenv('BAROLAB_PLAY_CONSOLE_CDP_PORT','0'))
    if not port:raise RuntimeError('native_console_session_unconfigured')
    executable,profile,_=account_paths(port)
    identity=_runtime(port,str(executable),str(profile))
    if identity.get('fastPath'):
        raise RuntimeError('browser_identity_unconfirmed')
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', timeout=15000)
        with owned_console_page(browser) as (page, ownership):
            for app, play_id in APP_IDS.items():
                base = f'https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/{play_id}'
                try:
                    pages = {'releases': _read_page(page, base + '/releases/overview', '최신 버전 및 번들', app)}
                    grid = page.get_by_role('grid', name='최신 버전', exact=True)
                    grid.wait_for(timeout=15000)
                    grid.get_by_role('row').filter(has_text=re.compile('비공개 테스트 - Alpha|내부 테스트')).first.wait_for(timeout=15000)
                    pages['releases']['rows'] = [row.get_by_role('gridcell').all_inner_texts()
                        for row in grid.get_by_role('row').all()]
                    pages['dashboard'] = _read_page(page, base + '/app-dashboard', '대시보드', app)
                    page.get_by_text(re.compile(r'현재 참여를 선택한 테스터\s*\d+명')).wait_for(timeout=15000)
                    toggle = page.get_by_role('button', name='테스트 트랙 표시', exact=True)
                    if toggle.count() == 1:
                        toggle.click()  # Read-only disclosure; never a submission control.
                    pages['dashboard']['text'] = page.locator('body').inner_text(timeout=10000)
                    results[app] = parse_observation(app, pages)
                except Exception as exc:
                    results[app] = {'status': 'error', 'error': type(exc).__name__ + ': console_read_unavailable'}
    return results, {'port': 9226, 'profile': 'sj', **ownership}


def refresh_console_status(*, path=CACHE, reader=None, force=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            return False
        previous = _load(path)
        if not force and _age(previous.get('lastAttemptAt')) < TTL_SECONDS:
            return False
        started = now()
        state = copy.deepcopy(previous)
        state.update(schemaVersion=1, status='collecting', lastAttemptAt=started, error=None)
        atomic_write(path, state)
        try:
            observations, browser = (reader or collect_browser)()
            apps = {}
            for app in APP_IDS:
                observed = observations.get(app, {'status': 'error', 'error': 'observation_missing'})
                if observed.get('status') == 'collected':
                    apps[app] = dict(observed, lastAttemptAt=started, error=None)
                else:
                    apps[app] = copy.deepcopy(previous.get('apps', {}).get(app) or empty_app(app))
                    apps[app].update(status='error', lastAttemptAt=started, stale=True,
                                     error=observed.get('error', 'console_read_unavailable'))
            successes = sum(a['status'] == 'collected' for a in apps.values())
            state.update(status='collected' if successes == 4 else 'partial' if successes else 'error',
                         apps=apps, browser=browser, checkedAt=now(), error=None if successes else 'console_read_unavailable')
            if successes == 4:
                state['lastSuccessAt'] = state['checkedAt']
        except Exception as exc:
            state.update(status='error', checkedAt=previous.get('checkedAt'),
                         error=type(exc).__name__ + ': collector_unavailable',
                         apps=copy.deepcopy(previous.get('apps') or {a: empty_app(a) for a in APP_IDS}))
            for app in state['apps'].values():
                app.update(stale=True, lastAttemptAt=started, error=state['error'])
        atomic_write(path, state)
        if path.resolve() == CACHE.resolve() and state.get('status') in ('collected', 'partial'):
            try:
                from common.app_testers_store import save_console_evidence
                save_console_evidence(state)
            except Exception:
                # Collection evidence remains durable even if the optional mirror fails.
                state['testerEvidenceSync'] = 'pending_retry'
                atomic_write(path, state)
        return True


def _schedule(path, force):
    if os.name != 'nt' or not _THREAD_LOCK.acquire(blocking=False):
        return False
    def work():
        try:
            refresh_console_status(path=path, force=force)
        finally:
            _THREAD_LOCK.release()
    threading.Thread(target=work, name='play-console-read-only', daemon=True).start()
    return True


def get_console_status(trigger_refresh=True, force=False, *, path=CACHE):
    state = _load(path) or {'schemaVersion': 1, 'status': 'never_collected',
                           'apps': {app: empty_app(app) for app in APP_IDS}}
    due = _age(state.get('lastAttemptAt')) >= TTL_SECONDS
    state['refreshScheduled'] = bool(trigger_refresh and (due or force) and _schedule(path, force))
    state['stale'] = state.get('status') != 'collected' or _age(state.get('checkedAt')) >= TTL_SECONDS
    state['ttlSeconds'] = TTL_SECONDS
    state['collectorHost'] = 'windows_sj_9226'
    if os.name != 'nt' and (due or force):
        state['refreshPendingReason'] = 'waiting_for_windows_collector'
    for app in state.get('apps', {}).values():
        app['stale'] = bool(app.get('stale') or _age(app.get('checkedAt')) >= TTL_SECONDS)
    return state


def start_periodic_refresh():
    """Attach to an existing Windows server process; NAS only reads shared cache."""
    global _PERIODIC_THREAD
    if os.name != 'nt' or not _PERIODIC_LOCK.acquire(blocking=False):
        return False
    _STOP.clear()
    def loop():
        try:
            while not _STOP.is_set():
                try:
                    get_console_status()
                except Exception:
                    pass  # The server remains available if the cache filesystem fails.
                _STOP.wait(60)
        finally:
            _PERIODIC_LOCK.release()
    _PERIODIC_THREAD = threading.Thread(target=loop, name='play-console-cache-refresh', daemon=True)
    _PERIODIC_THREAD.start()
    return True


def stop_periodic_refresh():
    """Stop this process's timer; no browser or user page is closed here."""
    _STOP.set()
    if _PERIODIC_THREAD is not None:
        _PERIODIC_THREAD.join(timeout=2)


if __name__ == '__main__':
    refresh_console_status(force=True)
    print(json.dumps(get_console_status(trigger_refresh=False), ensure_ascii=False, indent=2))
