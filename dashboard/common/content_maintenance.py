"""Bounded existing-URL maintenance. New-post creation is deliberately unavailable."""
import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urlsplit, quote
import uuid
from zoneinfo import ZoneInfo
from common.content_quality import content_quality_sha256

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'dashboard/data'
DB = DATA / 'growth.sqlite3'
STATE = DATA / 'content-maintenance.json'
POLICY = DATA / 'content-maintenance-policy.json'
BACKUPS = DATA / 'maintenance-backups'
DEFAULT_POLICY = {'enabled': False, 'maxPerCycle': 1, 'maxUpdatesPerDay': 1,
                  'maxResearchPerDay': 4, 'cooldownHours': 672,
                  'cycleIntervalMinutes': 30, 'publishingLookaheadMinutes': 10,
                  'auditIntervalMinutes': 2, 'auditBatchSize': 10, 'auditBudgetSeconds': 40,
                  'jevEnabled': False}
REVIEW_CHECKS = ('factsSupported', 'originalMeaningPreserved', 'searchIntentImproved',
                'mediaPreserved', 'noFabricatedExperience', 'newClaimsComplete', 'changedClaimsPrimarySupported')


from common.ego_telemetry import observed_operation


def now():
    return datetime.now(timezone.utc)


def stamp():
    return now().isoformat()


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {} if default is None else default


def atomic(path, value):
    from common.dashboard_jobs import write
    write(Path(path), value)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def version_digest(article):
    return digest({k: v for k, v in article.items() if k not in ('views', 'updated_at')})


def day_bounds():
    local = now().astimezone(ZoneInfo('Asia/Seoul')).replace(hour=0, minute=0, second=0, microsecond=0)
    return local.astimezone(timezone.utc).isoformat(), (local + timedelta(days=1)).astimezone(timezone.utc).isoformat()


@contextmanager
def database():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS maintenance_jobs (
      id TEXT PRIMARY KEY,domain TEXT NOT NULL,url TEXT NOT NULL UNIQUE,issue TEXT NOT NULL,
      status TEXT NOT NULL,stage TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
      last_attempt_at TEXT,next_retry_at TEXT,completed_at TEXT,action_id TEXT,
      proof TEXT NOT NULL DEFAULT '{}',reason TEXT,updated_at TEXT NOT NULL)''')
    db.execute('CREATE TABLE IF NOT EXISTS maintenance_attempts(id TEXT PRIMARY KEY,job_id TEXT,started_at TEXT,kind TEXT)')
    columns = {r[1] for r in db.execute('PRAGMA table_info(maintenance_jobs)')}
    for column in ('audit_at', 'content_sha256', 'audit_json', 'apply_attempt_at', 'deep_review_at', 'deep_json'):
        if column not in columns:
            db.execute('ALTER TABLE maintenance_jobs ADD COLUMN ' + column + ' TEXT')
    try:
        with db:
            yield db
    finally:
        db.close()


def state():
    raw = read(STATE)
    authoritative = read(POLICY) if POLICY.exists() else raw.get('policy', {})
    return {**raw, 'policy': {**DEFAULT_POLICY, **authoritative}, 'runtime': raw.get('runtime', {})}


def operation_enabled():
    return state()['policy']['enabled'] and not (Path.home() / 'EGO_EXEC_DISABLED').exists()


def cooldown_active(job, policy=None, moment=None):
    if not job.get('completed_at'):
        return False
    moment = moment or now()
    policy = policy or state()['policy']
    completed = datetime.fromisoformat(job['completed_at'].replace('Z', '+00:00'))
    pacific = ZoneInfo('America/Los_Angeles')
    # The source's final follow-up day must finish before another change.
    return (moment - completed < timedelta(hours=policy['cooldownHours'])
            or moment.astimezone(pacific).date() <= completed.astimezone(pacific).date() + timedelta(days=28))


def runtime(**fields):
    latest = state()
    latest['runtime'].update(fields, checkedAt=stamp())
    latest.pop('policy', None)
    atomic(STATE, latest)


def policy_update(payload):
    if set(payload) - {'enabled', 'jevEnabled', 'maxPerCycle', 'cooldownHours'}:
        raise ValueError('지원하지 않는 운영 정책 항목입니다.')
    for key in ('enabled', 'jevEnabled'):
        if key in payload and type(payload[key]) is not bool:
            raise ValueError(key + ' must be boolean')
    if 'maxPerCycle' in payload and (type(payload['maxPerCycle']) is not int or payload['maxPerCycle'] != 1):
        raise ValueError('현재 검증된 회차 상한은 1개입니다.')
    if 'cooldownHours' in payload and (type(payload['cooldownHours']) is not int or not 672 <= payload['cooldownHours'] <= 2160):
        raise ValueError('후속 측정을 위해 재수정 간격은 672~2160시간입니다.')
    raw = state()
    raw['policy'].update(payload)
    raw['policy']['updatedAt'] = stamp()
    atomic(POLICY, raw['policy'])
    return public_summary()


def sync_inventory():
    source = read(DATA / 'metrics.json')
    with database() as db:
        known = 0
        for record in source.get('sites', {}).values():
            site = record.get('site', {})
            if site.get('platform') != 'cf':
                continue
            domain = site.get('site_id')
            for url in record.get('posts', {}).get('urls', []):
                if not valid_url(domain, url):
                    continue
                known += 1
                db.execute('INSERT OR IGNORE INTO maintenance_jobs(id,domain,url,issue,status,stage,updated_at) VALUES (?,?,?,?,?,?,?)',
                           (uuid.uuid4().hex, domain, url, 'existing_content_unassessed', 'queued', 'queued', stamp()))
        return known


def valid_url(domain, url):
    try:
        u = urlsplit(url)
        return bool(domain and re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', domain) and u.scheme == 'https'
                    and u.hostname in (domain, 'www.' + domain) and not u.username and not u.password
                    and not u.port and not u.fragment and not u.query and u.path not in ('', '/'))
    except (ValueError, TypeError):
        return False


def public_job(row):
    item = dict(row)
    proof = read(BACKUPS / item['id'] / 'receipt.json') or json.loads(item.get('proof') or '{}')
    return {'id': item['id'], 'domain': item['domain'], 'url': item['url'], 'issue': item['issue'],
            'status': item['status'], 'stage': item['stage'], 'reason': item['reason'],
            'nextRetryAt': item['next_retry_at'], 'lastAttemptAt': item['last_attempt_at'],
            'completedAt': item['completed_at'], 'actionId': item['action_id'],
            'review': proof.get('review'), 'publicVerification': proof.get('publicVerification'),
            'jevSelection': proof.get('jevSelection'), 'jevReview': proof.get('jevReview'),
            'jevEscalation': proof.get('jevEscalation'),
            'experiment': proof.get('experiment'),
            'researchEvidence': proof.get('evidence'),
            'hashes': proof.get('hashes'), 'diffText': proof.get('diffText', '')[:4000],
            'evidence': json.loads(item.get('audit_json') or '{}'), 'lastAuditAt': item.get('audit_at'),
            'lastDeepReviewAt': item.get('deep_review_at'),
            'deepStatus': 'sources_reviewed' if item.get('deep_review_at') else 'evidence_review_due',
            'deepEvidence': json.loads(item.get('deep_json') or '{}'),
            'backupRef': item['id'] if proof.get('hashes') else None,
            'followup': {'status': 'observing', 'reason': '실제 수정 완료 후 성장 개선 기록의 전후 28일 관측'} if item['completed_at'] else None}


def public_summary():
    raw = state()
    with database() as db:
        counts = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) n FROM maintenance_jobs GROUP BY status')}
        audited = db.execute('SELECT COUNT(*) FROM maintenance_jobs WHERE audit_at IS NOT NULL').fetchone()[0]
        oldest = db.execute('SELECT MIN(audit_at) FROM maintenance_jobs').fetchone()[0]
        deep = db.execute('SELECT COUNT(*) FROM maintenance_jobs WHERE deep_review_at IS NOT NULL').fetchone()[0]
        queue = [public_job(r) for r in db.execute("SELECT * FROM maintenance_jobs WHERE status NOT IN ('completed','no_change') ORDER BY CASE status WHEN 'applying' THEN 0 WHEN 'ready' THEN 1 WHEN 'issues_found' THEN 2 WHEN 'retry_wait' THEN 3 WHEN 'blocked' THEN 4 ELSE 9 END,updated_at,id LIMIT 100")]
        recent = [public_job(r) for r in db.execute('SELECT * FROM maintenance_jobs WHERE attempts>0 ORDER BY updated_at DESC LIMIT 20')]
    return {'policy': raw['policy'], 'runtime': raw['runtime'], 'writeReadiness': write_readiness(), 'coverage': {'known': sum(counts.values()),
            'expected': sum(counts.values()), 'excludedUnknown': sum(counts.get(s, 0) for s in ('queued', 'inconclusive')),
            'audited': audited, 'neverAudited': sum(counts.values()) - audited, 'oldestAuditAt': oldest, 'byStatus': counts,
            'basicAudited': audited, 'deepReviewed': deep, 'deepReviewPending': sum(counts.values()) - deep,
            'reason': '기본점검은 구조·접근 확인 · 사실·답변 완전성 확인과 별도 · 미평가 글을 문제로 판정하지 않음'},
            'queue': queue, 'recentActions': recent, 'growth': raw.get('growth')}


def refresh_growth_state():
    from server.growth import autonomy_summary
    latest = state()
    latest['growth'] = autonomy_summary(DB, now())
    latest.pop('policy', None)
    atomic(STATE, latest)
    return latest['growth']


def canary_verified():
    with database() as db:
        for row in db.execute("SELECT id FROM maintenance_jobs WHERE status='completed'"):
            receipt = read(BACKUPS / row['id'] / 'receipt.json')
            if (receipt.get('canary') is True and receipt.get('publicVerification', {}).get('status') == 'verified'
                    and receipt.get('review', {}).get('status') == 'passed' and receipt.get('review', {}).get('rulesPassed') is True):
                return True
    return False


def write_readiness():
    policy = state()['policy']
    status, reason = 'ready', '검증된 기존 URL 수정 가능 · 글별 검수·해시·발행 우선 조건은 적용 직전 재확인'
    if not operation_enabled():
        status, reason = 'disabled', '자동 운영 비활성'
    else:
        start, end = day_bounds()
        with database() as db:
            used = db.execute('SELECT COUNT(*) FROM maintenance_jobs WHERE apply_attempt_at>=? AND apply_attempt_at<?', (start, end)).fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM maintenance_jobs WHERE status='applying'").fetchone()[0]
            ready = db.execute("SELECT COUNT(*) FROM maintenance_jobs WHERE status='ready'").fetchone()[0]
        wait = idle_reason()
        if pending:
            status, reason = 'reconciliation_wait', '중단된 수정 반영 상태 확인 중 · 다음 원격 수정 보류'
        elif used >= policy['maxUpdatesPerDay']:
            status, reason = 'daily_limit', '일일 원격 수정 시도 상한 도달 · 전체 점검은 계속'
        elif wait:
            status, reason = 'publishing_wait', wait
        elif not canary_verified():
            status, reason = ('first_canary', '독립 검수 통과 첫 기존 글 1건 자동 검증 · 성공 후 자격 확인') if ready else ('awaiting_canary', '전체 자동 점검·조사 중 · 실측 문제와 검수 통과 첫 후보 대기')
    return {'status': status, 'canApply': status in ('ready', 'first_canary'), 'reason': reason, 'canaryVerified': canary_verified()}


def idle_reason(moment=None):
    moment = moment or now()
    policy = state()['policy']
    # Runtime JSON can lag direct collectors; owned OS locks are authoritative.
    for name in ('metrics-worker.lock', 'metrics-run.lock'):
        if not lock_available(DATA / name):
            return '통계 수집 실제 잠금 보유 · 기존 수집 우선'
    live = read(DATA / 'metrics-runtime.json')
    if live.get('status') == 'running':
        return '통계 수집 실행 중 · 기존 수집 우선'
    cf = read(ROOT / 'dashboard/data/cf/pipeline_state.json')
    cleaner = read(ROOT / 'dashboard/data/cf/cleaner-status.json')
    if cf.get('executionState') == 'running' or cleaner.get('activeJob'):
        if not lock_available(ROOT / 'dashboard/data/cf/cleaner.lock'):
            return 'CF 신규 발행 실행 중 · 발행 우선'
        # A crashed writer can leave a JSON marker. Only the actual owned lock releases it.
        try:
            ended = datetime.fromisoformat(cleaner.get('finishedAt') or '')
            if not ended.tzinfo or not 0 <= (moment - ended).total_seconds() < 600:
                return 'CF 발행 상태 표시 미확인 · 실제 완료 기록 대기'
        except (ValueError, TypeError):
            return 'CF 발행 상태 표시 미확인 · 실제 완료 기록 대기'
    naver = read(ROOT / 'dashboard/data/naver/automation-journal.json')
    for attempt in naver.get('attempts', []):
        if attempt.get('phase') in ('running', 'research', 'draft', 'design', 'review', 'reserve', 'publishing'):
            try:
                age = (moment - datetime.fromisoformat(attempt.get('updatedAt') or attempt['startedAt'])).total_seconds()
                if 0 <= age < 6 * 3600:
                    return '네이버 발행 준비 실행 중 · 발행 우선'
            except (ValueError, KeyError, TypeError):
                return '네이버 실행 상태 미확인 · 수정 보류'
    slots = []
    for path in [ROOT / 'dashboard/data/cf/daily_schedule.json'] + list((ROOT / 'dashboard/data/cf/schedule_history').glob('*.json')):
        schedule = read(path)
        for row in schedule.get('items', []):
            if row.get('status') in ('published', 'review_required', 'failed'):
                continue
            try:
                due = datetime.fromisoformat(schedule['date'] + 'T' + row['scheduledTime']).replace(tzinfo=ZoneInfo('Asia/Seoul'))
                if -60 <= (due - moment).total_seconds() <= policy['publishingLookaheadMinutes'] * 60:
                    return 'CF 발행 예정 시간 임박 · 신규 발행 우선'
            except (ValueError, KeyError, TypeError):
                continue
    monitor = read(ROOT / 'dashboard/data/naver/automation-status.json')
    for account in monitor.get('accounts', []):
        slots.extend(s.get('scheduledSlot') for s in account.get('slots', []) if s.get('status') not in ('verified', 'published'))
    slots.append(monitor.get('startTime'))
    for slot in filter(None, slots):
        try:
            due = datetime.fromisoformat(monitor['date'] + 'T' + slot).replace(tzinfo=ZoneInfo('Asia/Seoul'))
            if -60 <= (due - moment).total_seconds() <= policy['publishingLookaheadMinutes'] * 60:
                return '네이버 준비·공개 예정 임박 · 신규 발행 우선'
        except (ValueError, KeyError, TypeError):
            continue
    return None


def preparation_window(moment=None, seconds=300):
    """Reserve enough preflight headroom; never overrides active writer/metrics gates."""
    moment=moment or now()
    policy=state()['policy']
    needed=policy['publishingLookaheadMinutes']*60+seconds
    upcoming=[]
    for path in [ROOT/'dashboard/data/cf/daily_schedule.json']+list((ROOT/'dashboard/data/cf/schedule_history').glob('*.json')):
        schedule=read(path)
        for row in schedule.get('items',[]):
            if row.get('status') in ('published','review_required','failed'):
                continue
            try:
                due=datetime.fromisoformat(schedule['date']+'T'+row['scheduledTime']).replace(tzinfo=ZoneInfo('Asia/Seoul'))
                if 0<=(due-moment).total_seconds()<=needed:
                    upcoming.append(due)
            except (ValueError,KeyError,TypeError):
                continue
    monitor=read(ROOT/'dashboard/data/naver/automation-status.json')
    slots=[s.get('scheduledSlot') for a in monitor.get('accounts',[]) for s in a.get('slots',[]) if s.get('status') not in ('verified','published')]
    slots.append(monitor.get('startTime'))
    for slot in filter(None,slots):
        try:
            due=datetime.fromisoformat(monitor['date']+'T'+slot).replace(tzinfo=ZoneInfo('Asia/Seoul'))
            if 0<=(due-moment).total_seconds()<=needed:
                upcoming.append(due)
        except (ValueError,KeyError,TypeError):
            continue
    if upcoming:
        due=min(upcoming)
        return {'available':False,'reason':'심층 준비 예산과 발행 우선 간격 부족 · 새 조사 시작 보류',
                'nextRetryAt':(due+timedelta(minutes=1)).astimezone(timezone.utc).isoformat(),
                'requiredSeconds':needed,'nextPublicationAt':due.isoformat()}
    return {'available':True,'requiredSeconds':needed}


def lock_available(path):
    sys.path.insert(0, str(ROOT / 'dashboard'))
    from metrics import collector_lock
    with collector_lock(path) as acquired:
        return acquired


def api_key(domain):
    from dotenv import dotenv_values
    key = dotenv_values(ROOT / '.env').get(domain.split('.')[0].replace('-', '').upper() + '_CF_API_KEY')
    key = key or read(ROOT / 'dashboard/data/cf/secure/cf_blog_keys.json').get(domain)
    if not key:
        raise ValueError('기존 CF 관리 인증 미확인')
    return key


def cache_binding(domain):
    """Existing Cloudflare credentials; read only the exact site's zone."""
    from dotenv import dotenv_values
    import requests
    cfg = dotenv_values(ROOT / '.env')
    suffixes = ['_aaa', '', '_baro'] if domain == 'nolplace.com' else ['', '_baro']
    for suffix in suffixes:
        email, key = cfg.get('CLOUDFLARE_API_EMAIL' + suffix), cfg.get('CLOUDFLARE_GLOBAL_API_KEY' + suffix)
        if not email or not key:
            continue
        headers = {'X-Auth-Email': email, 'X-Auth-Key': key, 'Content-Type': 'application/json'}
        response = requests.get('https://api.cloudflare.com/client/v4/zones', params={'name': domain}, headers=headers, timeout=(3, 5), allow_redirects=False)
        if response.status_code != 200:
            continue
        result = response.json()
        matches = [z for z in result.get('result', []) if z.get('name') == domain and z.get('status') == 'active']
        if result.get('success') and len(matches) == 1:
            return matches[0]['id'], headers
    raise ValueError('해당 도메인 정확한 캐시 무효화 권한 미확인 · 적용 전 보류')


def deployed_cache_urls(domain, urls, binding):
    """Resolve exact article URLs against the live Worker's versioned cache key."""
    import requests
    from dashboard.server.cf_themes import DOMAIN_WORKER_NAMES
    if not urls or any(not valid_url(domain, url) for url in urls):
        raise ValueError('Exact article cache URLs required')
    zone, headers = binding
    response = requests.get(f'https://api.cloudflare.com/client/v4/zones/{zone}',
                            headers=headers, timeout=(3, 5), allow_redirects=False)
    response.raise_for_status()
    info = response.json()
    if not info.get('success') or info['result'].get('name') != domain:
        raise RuntimeError('Exact cache zone verification failed')
    account = info['result']['account']['id']
    worker = DOMAIN_WORKER_NAMES[domain]
    response = requests.get(f'https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/{worker}',
                            headers=headers, timeout=(3, 5), allow_redirects=False)
    response.raise_for_status()
    versions = set(re.findall(r'_baro_v=[A-Za-z0-9_]+', response.text))
    if len(versions) != 1:
        raise RuntimeError('Deployed article cache key is ambiguous')
    version = next(iter(versions))
    canonical = [requests.Request('GET', url).prepare().url for url in urls]
    return list(dict.fromkeys(value for url in canonical for value in (url, url + '?' + version)))


@observed_operation('content_maintenance', 'maintenance-apply')
def purge_exact(domain, url, slug, binding):
    import requests
    if not operation_enabled():
        raise ValueError('자동 운영 중지 상태')
    zone, headers = binding
    urls = deployed_cache_urls(domain, [url, f'https://www.{domain}/posts/{slug}', f'https://{domain}/{slug}'], binding)
    if not operation_enabled():
        raise ValueError('자동 운영 중지 상태')
    response = requests.post(f'https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache',
                             json={'files': urls}, headers=headers, timeout=(3, 5), allow_redirects=False)
    if response.status_code != 200 or not response.json().get('success'):
        raise ValueError('해당 글 URL 캐시 갱신 미확인')
    return {'status': 'confirmed', 'urls': urls, 'checkedAt': stamp(), 'scope': 'exact_article_urls_only'}


def load_article(domain, url, catalog_cache=None):
    import requests
    if not valid_url(domain, url):
        raise ValueError('등록 도메인의 기존 글 URL만 지원합니다.')
    slug = urlsplit(url).path.strip('/')
    if catalog_cache is not None and domain in catalog_cache:
        found = next((p for p in catalog_cache[domain] if p.get('slug') == slug), None)
        if not found:
            raise ValueError('기존 글 목록에서 URL 확인 안 됨')
        response = requests.get(f'https://www.{domain}/api/posts/{int(found["id"])}', timeout=8)
        response.raise_for_status()
        return response.json()['post']
    collected = []
    # Read full existing catalog; never call the create endpoint.
    for page in range(1, 101):
        result = requests.get(f'https://www.{domain}/api/posts', params={'page': page, 'limit': 40}, timeout=12)
        result.raise_for_status()
        data = result.json()
        posts = data.get('posts', [])
        collected.extend(posts)
        found = next((p for p in posts if p.get('slug') == slug), None)
        if found:
            if catalog_cache is not None:
                # Catalog cache is complete only after all pages have been traversed.
                catalog_cache.setdefault(domain + ':partial', []).extend(collected)
            response = requests.get(f'https://www.{domain}/api/posts/{int(found["id"])}', timeout=12)
            response.raise_for_status()
            article = response.json()['post']
            if article.get('slug') != slug or article.get('status') != 'published':
                raise ValueError('이미 공개된 동일 URL 글만 수정합니다.')
            return article
        total = data.get('pagination', {}).get('totalPages', data.get('totalPages'))
        if not posts or len(posts) < 40 or (total and page >= int(total)):
            break
    raise ValueError('기존 글 ID를 공개 목록에서 확인하지 못했습니다.')


@observed_operation('content_maintenance', 'maintenance-audit')
def audit_batch():
    from common.content_improvement import audit_article
    import requests
    policy = state()['policy']
    start = time.monotonic()
    with database() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM maintenance_jobs ORDER BY audit_at IS NOT NULL,audit_at,updated_at,id')]
    picked, domains = [], set()
    for row in rows:
        if row['domain'] not in domains:
            picked.append(row)
            domains.add(row['domain'])
            if len(picked) >= policy['auditBatchSize']:
                break
    checked = 0
    stop_reason = None
    for job in picked:
        stop_reason = idle_reason()
        if time.monotonic() - start > policy['auditBudgetSeconds'] or stop_reason:
            break
        try:
            original = load_article(job['domain'], job['url'])
            response = requests.get(job['url'], timeout=6)
            response.raise_for_status()
            audit = audit_article(original, response.text)
            result = audit.get('status', 'inconclusive')
            if result not in ('issues_found', 'audit_checked', 'inconclusive'):
                result = 'inconclusive'
            content_hash = digest(original)
            preserve = job['status'] in ('completed', 'processing', 'applying', 'ready', 'blocked', 'rolled_back', 'retry_wait') or (job['status'] == 'no_change' and job.get('content_sha256') == version_digest(original))
            changed_source = job.get('content_sha256') and job['content_sha256'] != version_digest(original)
            if changed_source and job['status'] not in ('processing', 'applying'):
                preserve = False
            if job['status'] == 'completed' and job.get('completed_at'):
                preserve = cooldown_active(job, policy)
            with database() as db:
                if changed_source:
                    db.execute('UPDATE maintenance_jobs SET deep_review_at=NULL,deep_json=? WHERE id=?',
                               (json.dumps({'status': 'evidence_review_due', 'reason': '원문 버전 변경 · 이전 심층 근거는 새 원문에 적용하지 않음'}, ensure_ascii=False), job['id']))
                db.execute('UPDATE maintenance_jobs SET audit_at=?,content_sha256=?,audit_json=?,status=?,reason=?,updated_at=? WHERE id=?',
                           (stamp(), version_digest(original), json.dumps(audit, ensure_ascii=False), job['status'] if preserve else result,
                            job['reason'] if preserve else ('공개 원문 점검 결과 · 미확인은 정상으로 판정하지 않음'), stamp(), job['id']))
        except Exception:
            audit = {'status': 'inconclusive', 'reason': '공개 원문 또는 점검 근거 미확인 · 다음 순회 재점검'}
            with database() as db:
                db.execute('UPDATE maintenance_jobs SET audit_at=?,audit_json=?,status=?,reason=?,updated_at=? WHERE id=?',
                           (stamp(), json.dumps(audit, ensure_ascii=False), job['status'] if job['status'] not in ('queued','audit_checked','inconclusive') else 'inconclusive',
                            audit['reason'], stamp(), job['id']))
        checked += 1
    runtime(lastAuditAt=stamp(), lastAuditCount=checked, auditCoverage='rotating_never_then_oldest_domain_balanced',
            lastAuditStopReason=stop_reason or ('회차 시간 상한' if time.monotonic() - start > policy['auditBudgetSeconds'] else None))
    return checked


def save_job(job_id, **fields):
    allowed = {'status', 'stage', 'attempts', 'last_attempt_at', 'next_retry_at', 'completed_at', 'action_id', 'proof', 'reason', 'apply_attempt_at', 'deep_review_at', 'deep_json', 'content_sha256'}
    if set(fields) - allowed:
        raise ValueError('invalid job field')
    fields['updated_at'] = stamp()
    with database() as db:
        db.execute('UPDATE maintenance_jobs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', (*fields.values(), job_id))


def choose_growth_job(jobs):
    from common.jev import choose_candidates
    from server.growth import maintenance_candidates
    candidates = maintenance_candidates(jobs, moment=now())
    result = choose_candidates(candidates) if candidates else {'status': 'no_fresh_candidates', 'ranking': []}
    eligible = {c['id']: c for c in candidates}
    selected = next((entry for entry in result.get('ranking', [])
                     if result.get('status') == 'ok' and entry.get('candidateId') in eligible
                     and entry.get('score', 0) >= 0.65 and entry.get('evidenceSupport', 0) >= 0.6), None)
    receipt = {**result, 'checkedAt': stamp(), 'candidateCount': len(candidates),
               'thresholds': {'score': 0.65, 'evidenceSupport': 0.6},
               'selected': eligible[selected['candidateId']] if selected else None}
    runtime(jevSelection=receipt, lastAttemptAt=stamp())
    if not selected:
        return None
    job = next(job for job in jobs if job['id'] == selected['candidateId'])
    proof = json.loads(job.get('proof') or '{}')
    proof['jevSelection'] = receipt
    save_job(job['id'], proof=json.dumps(proof, ensure_ascii=False))
    return {**job, 'proof': json.dumps(proof, ensure_ascii=False)}


def validate_jev_receipt(job, original, draft, receipt):
    selection, review = receipt.get('jevSelection') or {}, receipt.get('jevReview') or {}
    selected = selection.get('selected') or {}
    if (selection.get('status') != 'ok' or selected.get('id') != job['id']
            or selected.get('domain') != job['domain'] or selected.get('url') != job['url']
            or review.get('status') != 'ok' or review.get('decision') not in ('pass', 'review')
            or review.get('originalSha256') != digest(original) or review.get('draftSha256') != digest(draft)
            or review.get('evidenceSha256') != digest(receipt.get('evidence') or {})):
        raise ValueError('JEV 후보 선별·수정안 검수 영수증 또는 해시 미확인 · 적용 차단')
    if review['decision'] == 'review':
        escalation = receipt.get('jevEscalation') or {}
        if (escalation.get('status') != 'passed' or escalation.get('issues')
                or any(escalation.get('checks', {}).get(key) is not True for key in REVIEW_CHECKS)
                or escalation.get('reviewer') != 'independent_reasoning_reviewer'
                or escalation.get('jevReviewSha256') != digest(review)
                or any(escalation.get(key) != review[key] for key in ('originalSha256', 'draftSha256', 'evidenceSha256'))):
            raise ValueError('JEV 불확실성 후 독립 재검수 근거 미확인 · 적용 차단')
    try:
        source_at = datetime.fromisoformat(selected['evidence']['checkedAt'].replace('Z', '+00:00'))
        review_at = datetime.fromisoformat(review['checkedAt'].replace('Z', '+00:00'))
        if not timedelta(0) <= now() - source_at <= timedelta(hours=26) or not timedelta(0) <= now() - review_at <= timedelta(hours=24):
            raise ValueError('stale')
        if review['decision'] == 'review':
            escalated_at = datetime.fromisoformat(escalation['checkedAt'].replace('Z', '+00:00'))
            if escalated_at < review_at or not timedelta(0) <= now() - escalated_at <= timedelta(hours=24):
                raise ValueError('stale escalation')
    except (KeyError, TypeError, ValueError):
        raise ValueError('JEV 선별 원천 또는 검수 날짜 미확인·만료 · 재선별 필요') from None


def escalate_jev_review(original, draft, evidence, jev_review):
    """One bounded reasoning review after uncertainty; never override rejection."""
    if jev_review.get('status') != 'ok' or jev_review.get('decision') != 'review':
        raise ValueError('JEV review 결정만 독립 재검수 가능')
    from common.content_improvement import article_payload, model_json, original_text
    original_view, draft_view = article_payload(original), draft
    unchanged = {}
    body = original.get('content') or original.get('contentHtml') or ''
    if body and body == draft.get('contentHtml'):
        original_view = {k: v for k, v in original_view.items() if k not in ('content', 'contentHtml')}
        original_view['bodyText'] = original_text(body)
        draft_view = {k: v for k, v in draft.items() if k != 'contentHtml'}
        unchanged = {'bodyAndEmbeddedMediaBytesEqual': True, 'sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
                     'projection': 'unchanged HTML body represented once as complete reader text; no text truncation'}
    decision, metadata = model_json(
        'reviewer',
        'JEV의 불확실성 후 독립 재검수. 이전 reviewer 승인을 따르지 말고 원문·수정안·원천 근거와 '
        'JEV 점수를 직접 대조한다. {status:passed|changes_required,issues:[문자열],notes:[문자열],'
        'checks:{factsSupported,originalMeaningPreserved,searchIntentImproved,mediaPreserved,'
        'noFabricatedExperience,newClaimsComplete,changedClaimsPrimarySupported}} 반환. '
        '7개 checks 모두 실제 근거로 확인되고 issues가 없을 때만 passed. JEV 확률은 사실·허가가 아니다. '
        'searchIntentImproved는 발행 전 편집 검수 항목이다: 실제 관측 검색어 또는 명시된 독자 과제와 '
        '수정 제목·본문의 답이 맞으며 독자가 대상과 답을 찾기 쉬워졌는지 원문과 비교해 판단한다. '
        '아직 측정할 수 없는 향후 CTR·순위·트래픽·수익 상승의 입증을 이 항목의 통과 조건으로 삼지 않는다. '
        '검색어 표본이 적으면 대표·지배 검색 의도 또는 기존 CTR 저하의 원인이라고 추론하지 않는다. '
        '단순히 관련 단어를 넣었다는 이유나 JEV 점수만으로 통과시키지 말고, 실제 편집상 개선이 없거나 '
        '제목이 본문·1차 원천보다 넓은 답을 약속하면 changes_required로 판정한다. '
        '변경되지 않은 본문·미디어는 재생성하지 않는다. 수익이나 검색 상승을 보장하지 않는다.',
        {'original': original_view, 'draft': draft_view, 'evidence': evidence,
         'verifiedUnchanged': unchanged, 'jevReview': jev_review}, time.monotonic() + 180)
    return {**decision, 'reviewer': 'independent_reasoning_reviewer', 'checkedAt': stamp(),
            'originalSha256': digest(original), 'draftSha256': digest(draft), 'evidenceSha256': digest(evidence),
            'jevReviewSha256': digest(jev_review), 'reviewContractVersion': 'editorial-intent-v1',
            'modelReceipt': metadata}


@observed_operation('content_maintenance', 'maintenance-prepare')
def prepare_job(job, inspect_only=False, limits=None, proposal=None):
    from common.content_improvement import prepare_improvement
    sys.path.insert(0, str(ROOT / 'dashboard'))
    import growth_analysis
    original = load_article(job['domain'], job['url'])
    folder = BACKUPS / job['id']
    folder.mkdir(parents=True, exist_ok=True)
    atomic(folder / 'original.json', original)
    report = growth_analysis.summary()
    diagnostic = next((r for r in report.get('diagnosis', {}).get('domains', []) if r['domain'] == job['domain']), None)
    from dashboard.agents.synapse import doctor_context
    diagnostic = {**(diagnostic or {}), 'synapsePlan': doctor_context(job['url'], ROOT)}
    selection = json.loads(job.get('proof') or '{}').get('jevSelection')
    def observe(event, detail=None):
        if not operation_enabled():
            raise ValueError('자동 운영 중지 상태')
        if idle_reason():
            raise ValueError('발행 또는 통계 수집 우선 · 준비 작업 양보')
        runtime(status='running', stage=event.get('stage', 'research') if isinstance(event, dict) else str(event), activeJob=job['id'])
    if proposal is None:
        proposal = prepare_improvement(job['domain'], job['url'], original, diagnosis=diagnostic,
                                       limits={**(limits or {}), 'seconds': 300,
                                               'forceResearch': inspect_only or bool(selection) or (limits or {}).get('forceResearch') is True,
                                               'inspectOnly': inspect_only}, observer=observe)
    if not proposal.get('providerFailure') and any(
            any(a.get('status')=='ok' for a in receipt.get('routingAttempts',[]))
            for receipt in proposal.get('stageReceipts',[])):
        runtime(providerBackoff={},nextRetryAt=None,providerStatus='ready')
    if inspect_only:
        evidence = proposal.get('evidence') or {}
        complete = evidence.get('coverage', {}).get('deepReviewed') is True
        fields = {'deep_json': json.dumps(evidence, ensure_ascii=False), 'status': job['status'], 'stage': 'evidence_review',
                  'reason': '심층 근거 점검 완료 · 수정안은 만들지 않음' if complete else '심층 원천 또는 공급자 미확인 · 정상으로 판정하지 않음'}
        if complete:
            fields['deep_review_at'] = stamp()
        if complete and proposal.get('status') == 'issues_found':
            fields['status'] = 'issues_found'
        save_job(job['id'], **fields)
        failure = proposal.get('providerFailure')
        if failure:
            runtime(providerBackoff=failure, nextRetryAt=failure.get('nextRetryAt'))
        return 'inspected' if complete else 'inconclusive'
    atomic(folder / 'proposal.json', proposal)
    draft = proposal.get('draft') or {}
    atomic(folder / 'draft.json', draft)
    diff = '\n'.join(difflib.unified_diff(json.dumps(original, ensure_ascii=False, indent=2).splitlines(),
                                         json.dumps(draft, ensure_ascii=False, indent=2).splitlines(), fromfile='original', tofile='reviewed_draft'))
    (folder / 'diff.txt').write_text(diff, encoding='utf-8')
    receipt = {'contentQualitySha256': proposal.get('contentQualitySha256'),
               'hashes': {'originalSha256': digest(original), 'draftSha256': digest(draft),
                         'diffSha256': hashlib.sha256(diff.encode('utf-8')).hexdigest()},
               'review': proposal.get('review'), 'evidence': proposal.get('evidence'),
               'stageReceipts': proposal.get('stageReceipts', []), 'diffText': diff,
               'diagnosisSnapshot': {'capturedAt': stamp(), 'sourceCheckedAt': report.get('checkedAt'),
                                     'domain': job['domain'], 'url': job['url'], 'diagnosis': diagnostic, 'causalProof': False}}
    receipt['jevSelection'] = selection
    from server.growth import action_evidence
    end = now().astimezone(ZoneInfo('America/Los_Angeles')).date() - timedelta(days=3)
    receipt['planningBaseline'] = action_evidence(job['domain'], job['url'], (end - timedelta(days=27)).isoformat(), end.isoformat())
    outcome = 'ready' if proposal.get('status') == 'ready' else proposal.get('status', 'blocked')
    if state()['policy']['jevEnabled'] and outcome == 'ready':
        from common.jev import review_revision
        revision = {'title': draft.get('title'), 'content': draft.get('contentHtml'),
                    'excerpt': draft.get('summary'), 'description': draft.get('metaDescription')}
        receipt['jevReview'] = {**review_revision(original, revision, proposal.get('evidence') or {}),
                                'checkedAt': stamp(), 'originalSha256': digest(original), 'draftSha256': digest(draft),
                                'evidenceSha256': digest(proposal.get('evidence') or {})}
        if receipt['jevReview'].get('status') == 'ok' and receipt['jevReview'].get('decision') == 'review':
            try:
                observe('jev_escalation')
                receipt['jevEscalation'] = escalate_jev_review(original, draft, receipt['evidence'] or {}, receipt['jevReview'])
            except Exception:
                receipt['jevEscalation'] = {'status': 'unavailable', 'checkedAt': stamp()}
        try:
            validate_jev_receipt(job, original, draft, receipt)
        except ValueError:
            unavailable = receipt['jevReview'].get('status') != 'ok' or (receipt.get('jevEscalation') or {}).get('status') == 'unavailable'
            outcome = 'retry_wait' if unavailable else 'blocked'
            if unavailable:
                save_job(job['id'], next_retry_at=(now() + timedelta(hours=1)).isoformat())
            proposal = {**proposal, 'reason': 'JEV 근거·의도 검수 미통과 또는 공급자 미확인 · 원격 수정 보류'}
    atomic(folder / 'receipt.json', receipt)
    provider_failure = proposal.get('providerFailure')
    if provider_failure:
        pause = provider_failure.get('nextRetryAt') or (now() + timedelta(hours=1)).isoformat()
        outcome = 'retry_wait'
        runtime(providerBackoff=provider_failure, nextRetryAt=pause)
        save_job(job['id'], next_retry_at=pause)
    save_job(job['id'], status=outcome, stage='review', proof=json.dumps(receipt, ensure_ascii=False), reason=proposal.get('reason'))
    return outcome


@observed_operation('content_maintenance', 'maintenance-audit')
def verify_public(domain, url, expected):
    import requests
    from bs4 import BeautifulSoup
    api = requests.get(f'https://www.{domain}/api/posts/{int(expected["id"])}', timeout=(3, 5), allow_redirects=False)
    api.raise_for_status()
    actual = api.json()['post']
    if version_digest(actual) != version_digest(expected):
        return False
    response = requests.get(url, timeout=(3, 5), headers={'Cache-Control': 'no-cache'}, allow_redirects=False)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    article = soup.select_one('article.gs-article') or soup.select_one('article')
    if not article or not any(h.get_text(' ', strip=True) == expected['title'] for h in soup.select('h1')):
        return False
    for ad in article.select('aside.ad-slot,script,style'):
        ad.decompose()
    text = lambda value: re.sub(r'\s+', ' ', BeautifulSoup(value, 'html.parser').get_text(' ', strip=True)).strip()
    return text(expected['content']) in text(str(article))


@observed_operation('content_maintenance', 'maintenance-apply')
def apply_job(job_id, canary=False):
    sys.path.insert(0, str(ROOT / 'dashboard'))
    from metrics import collector_lock
    with collector_lock(DATA / 'content-maintenance.lock') as acquired:
        if not acquired:
            raise ValueError('다른 유지보수 회차 실행 중 · 중복 적용 차단')
        return _apply_job(job_id, canary)


@observed_operation('content_maintenance', 'maintenance-apply')
def _apply_job(job_id, canary=False):
    import requests
    sys.path.insert(0, str(ROOT / 'dashboard'))
    from metrics import collector_lock
    folder = BACKUPS / job_id
    original, draft, proposal, receipt = (read(folder / name) for name in ('original.json', 'draft.json', 'proposal.json', 'receipt.json'))
    quality_hash = content_quality_sha256()
    policy_artifacts = [proposal, proposal.get('review') or {}, receipt]
    for artifact in (proposal, receipt):
        stages = artifact.get('stageReceipts')
        if not isinstance(stages, list) or not stages:
            raise ValueError('공통 콘텐츠 정책 인계 누락 · 재조사·검수 후 적용 필요')
        policy_artifacts.extend(stages)
    if any(not isinstance(artifact, dict) or artifact.get('contentQualitySha256') != quality_hash for artifact in policy_artifacts):
        raise ValueError('공통 콘텐츠 정책 변경 또는 해시 누락 · 재조사·검수 후 적용 필요')
    with database() as db:
        row = db.execute('SELECT * FROM maintenance_jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise ValueError('unknown maintenance job')
        job = dict(row)
    review = proposal.get('review') or {}
    hashes = receipt.get('hashes', {})
    diff_bytes = (folder / 'diff.txt').read_bytes() if (folder / 'diff.txt').is_file() else b''
    if (hashes.get('draftSha256') != digest(draft) or hashes.get('diffSha256') != hashlib.sha256(diff_bytes).hexdigest()
            or digest(receipt.get('review')) != digest(review)):
        raise ValueError('수정안·차이·검수 백업 영수증 무결성 불일치')
    try:
        reviewed = datetime.fromisoformat(review.get('checkedAt') or proposal.get('checkedAt') or '')
        source_hours = 6 if proposal.get('evidence', {}).get('coverage', {}).get('highStakes') else 24
        if not reviewed.tzinfo or not timedelta(0) <= now() - reviewed <= timedelta(hours=source_hours):
            raise ValueError('수정안 원천·독립 검수 24시간 경과 · 재조사 필요')
    except (TypeError, ValueError):
        save_job(job_id, status='retry_wait', stage='research', next_retry_at=stamp(), reason='독립 검수 날짜 미확인 또는 만료 · 재조사 필요')
        raise ValueError('독립 검수 날짜 미확인 또는 만료 · 재조사 필요') from None
    if original.get('publish_at'):
        raise ValueError('기존 API가 예약 발행 시각을 보존하지 못하므로 해당 글 자동 수정 보류')
    if (proposal.get('status') != 'ready' or review.get('status') != 'passed' or review.get('rulesPassed') is not True
            or review.get('issues') or any(review.get('checks', {}).get(key) is not True for key in REVIEW_CHECKS)
            or proposal.get('originalSha256') != digest(original) or proposal.get('draftSha256') != digest(draft)
            or review.get('draftSha256') != digest(draft) or receipt.get('hashes', {}).get('originalSha256') != digest(original)):
        raise ValueError('원본·수정안 해시 또는 독립 검수 영수증 불일치 · 적용 차단')
    if state()['policy']['jevEnabled']:
        validate_jev_receipt(job, original, draft, receipt)
    if not operation_enabled():
        raise ValueError('자동 운영 중지 상태')
    if not canary and not canary_verified():
        raise ValueError('최초 기존 글은 검증 canary 회차로 처리해야 합니다.')
    if job['status'] != 'ready' or idle_reason():
        raise ValueError('검수 완료 상태 또는 발행 우선 조건 미충족')
    if cooldown_active(job):
        raise ValueError('이전 실제 수정의 28일 관측 기간 · 재수정 보류')
    binding = cache_binding(job['domain'])
    with ExitStack() as stack:
        for lock in (ROOT / 'dashboard/data/cf/cleaner.lock', ROOT / 'dashboard/data/naver/pipeline-run.lock'):
            if not stack.enter_context(collector_lock(lock)):
                raise ValueError('발행 잠금 실행 중 · 수정 양보')
        if idle_reason():
            raise ValueError('발행·통계 수집 우선 · 적용 양보')
        start_day, end_day = day_bounds()
        with database() as db:
            used = db.execute('SELECT COUNT(*) FROM maintenance_jobs WHERE apply_attempt_at>=? AND apply_attempt_at<?', (start_day, end_day)).fetchone()[0]
            unresolved = db.execute("SELECT COUNT(*) FROM maintenance_jobs WHERE status='applying' AND id!=?", (job_id,)).fetchone()[0]
        if unresolved:
            raise ValueError('다른 중단된 수정 반영 확인 중 · 새 원격 수정 보류')
        if used >= state()['policy']['maxUpdatesPerDay']:
            raise ValueError('일일 실제 수정 상한 도달')
        endpoint = f'https://www.{job["domain"]}/api/posts/{int(original["id"])}'
        current_response = requests.get(endpoint, timeout=(3, 5), allow_redirects=False)
        current_response.raise_for_status()
        current = current_response.json()['post']
        if version_digest(current) != version_digest(original) or current.get('updated_at') != original.get('updated_at'):
            raise ValueError('원본이 다른 작업에서 변경됨 · 덮어쓰기 차단')
        from common.cf_tables import style_tables, VERSION as table_style_version
        payload = {'title': draft['title'], 'slug': original['slug'], 'content': style_tables(draft['contentHtml']).strip()}
        if isinstance(original.get('meta_description'), str) and draft.get('summary', '').strip():
            payload['meta_description'] = draft.get('metaDescription') or draft['summary']
        if isinstance(original.get('excerpt'), str) and draft.get('summary', '').strip():
            payload['excerpt'] = draft['summary']
        expected = {**original, **payload}
        key = api_key(job['domain'])
        headers = {'x-api-key': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
        save_job(job_id, status='applying', stage='apply', apply_attempt_at=stamp())
        runtime(status='running', stage='apply', activeJob=job_id)
        receipt['intent'] = {'endpoint': endpoint, 'method': 'PUT', 'postId': original['id'],
                             'tableStyleVersion': table_style_version,
                             'originalVersionSha256': version_digest(original),
                             'expectedVersionSha256': version_digest(expected), 'expected': expected,
                             'checkedAt': stamp(), 'canary': bool(canary), 'writerScope': 'shared_managed_writer_locks; remote API has no atomic CAS'}
        atomic(folder / 'receipt.json', receipt)
        if not operation_enabled():
            receipt['intent']['cancelledAt'] = stamp()
            atomic(folder / 'receipt.json', receipt)
            save_job(job_id, status='ready', stage='apply', apply_attempt_at=None, reason='자동 운영 중지 · 원격 수정 요청 전 취소')
            raise ValueError('자동 운영 중지 상태')
        applied = False
        try:
            if not operation_enabled():
                raise ValueError('자동 운영 중지 상태')
            response = requests.put(endpoint, json=payload, headers=headers, timeout=(3, 8), allow_redirects=False)
            response.raise_for_status()
            applied = True
            receipt['cachePurge'] = purge_exact(job['domain'], job['url'], original['slug'], binding)
            if not verify_public(job['domain'], job['url'], expected):
                raise ValueError('공개 URL·제목·본문 검증 불일치')
        except Exception:
            if not operation_enabled():
                save_job(job_id, status='applying', stage='verify', next_retry_at=(now() + timedelta(minutes=30)).isoformat(), reason='자동 운영 중지 · 반영 조회만 가능하며 캐시·롤백 쓰기는 재활성화까지 보류')
                atomic(folder / 'receipt.json', receipt)
                raise ValueError('자동 운영 중지 상태') from None
            latest_response = requests.get(endpoint, timeout=(3, 5), allow_redirects=False)
            latest_response.raise_for_status()
            latest = latest_response.json()['post']
            changed = version_digest(latest) == version_digest(expected)
            unchanged = version_digest(latest) == version_digest(original)
            if changed:
                rollback = {k: original.get(k) for k in payload}
                if not operation_enabled():
                    raise ValueError('자동 운영 중지 상태')
                restored = requests.put(endpoint, json=rollback, headers=headers, timeout=(3, 8), allow_redirects=False)
                restored.raise_for_status()
                receipt['rollbackCachePurge'] = purge_exact(job['domain'], job['url'], original['slug'], binding)
                rollback_ok = verify_public(job['domain'], job['url'], original)
                receipt['rollback'] = {'status': 'verified' if rollback_ok else 'unconfirmed', 'checkedAt': stamp()}
                save_job(job_id, status='rolled_back' if rollback_ok else 'blocked', stage='rollback', reason='공개 확인 실패 · 원본 복구 결과 기록')
            elif unchanged:
                save_job(job_id, status='retry_wait', stage='apply', next_retry_at=(now() + timedelta(hours=6)).isoformat(), reason='수정 반영 안 됨 · 기존 원문 유지')
            else:
                save_job(job_id, status='blocked', stage='verify', reason='동시 수정 또는 반영 상태 미확인 · 다른 작업 원문을 덮어쓰지 않음')
            atomic(folder / 'receipt.json', receipt)
            raise ValueError('수정 또는 공개 검증 실패 · 복구 영수증 확인') from None
    receipt['publicVerification'] = {'status': 'verified', 'url': job['url'], 'checkedAt': stamp(),
                                     'postId': original['id'], 'title': expected['title'], 'contentSha256': hashlib.sha256(expected['content'].encode('utf-8')).hexdigest()}
    receipt['canary'] = bool(canary)
    action_id = register_completed_action(job, receipt)
    atomic(folder / 'receipt.json', receipt)
    archive_receipt(job_id, receipt)
    save_job(job_id, status='completed', stage='monitor', completed_at=stamp(), action_id=action_id,
             proof=json.dumps(receipt, ensure_ascii=False), content_sha256=version_digest(expected), reason='동일 기존 URL 수정·공개 확인 완료')
    runtime(status='completed', stage='monitor', lastSuccessAt=stamp(), activeJob=None)
    refresh_growth_state()
    return public_summary()


def register_completed_action(job, receipt):
    from server.growth import connect, action_evidence, diagnosis_snapshot
    implemented = (receipt.get('intent') or {}).get('checkedAt') or receipt['publicVerification']['checkedAt']
    implemented_at = datetime.fromisoformat(implemented.replace('Z', '+00:00'))
    day = implemented_at.astimezone(ZoneInfo('America/Los_Angeles')).date()
    completed_day = implemented_at.astimezone(ZoneInfo('Asia/Seoul')).date()
    baseline = action_evidence(job['domain'], job['url'], (day - timedelta(days=28)).isoformat(), (day - timedelta(days=1)).isoformat())
    planning = receipt.get('planningBaseline') or {'status': 'not_collected', 'reason': '계획 당시 정확한 원천 미수집'}
    # Freeze the actual pre-change source window; never relabel a lagged report.
    if baseline.get('status') != 'collected' and planning.get('status') == 'collected':
        try:
            begin, end = (datetime.fromisoformat(planning[k]).date() for k in ('start', 'end'))
            if (end - begin).days == 27 and end < day:
                baseline = {**planning, 'windowPolicy': 'latest_completed_source_window_before_implementation'}
        except (ValueError, TypeError, KeyError):
            pass
    receipt['experiment'] = {
        'status': 'implemented', 'performanceStatus': 'observing', 'implementedAt': implemented,
        'measurementDate': day.isoformat(), 'measurementTimezone': 'America/Los_Angeles',
        'goal': {'dailyUsd': 100, 'averagingDays': 30, 'scope': 'all_registered_cf_sites'},
        'baseline': baseline, 'followupStart': (day + timedelta(days=1)).isoformat(),
        'followupEnd': (day + timedelta(days=28)).isoformat(),
        'measurementDueAt': datetime.combine(day + timedelta(days=31), datetime.min.time(),
                                             tzinfo=ZoneInfo('America/Los_Angeles')).isoformat(),
        'causalProof': False, 'revenueOutcome': {'status': 'unknown', 'amountUsd': None},
        'jevSelection': receipt.get('jevSelection'), 'jevReview': receipt.get('jevReview'),
        'jevEscalation': receipt.get('jevEscalation')}
    captured = receipt.get('diagnosisSnapshot') or diagnosis_snapshot(job['domain'], job['url'])
    captured['maintenance'] = {'jobId': job['id'], 'actor': 'maintenance', 'hashes': receipt['hashes'], 'publicVerification': receipt['publicVerification']}
    captured['experiment'] = receipt['experiment']
    identifier = hashlib.sha256((job['id'] + ':' + receipt['hashes']['draftSha256']).encode('utf-8')).hexdigest()[:32]
    with connect(DB) as db:
        db.execute('INSERT OR IGNORE INTO improvement_actions (id,domain,url,action,note,status,created_at,updated_at,completed_at,planning_baseline,baseline,diagnosis_snapshot) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier, job['domain'], job['url'], '기존 콘텐츠 자동 개선', '독립 검수·원본 백업·동일 URL 공개 확인 완료', 'done', stamp(), stamp(), completed_day.isoformat(),
                    json.dumps(planning, ensure_ascii=False), json.dumps(baseline, ensure_ascii=False), json.dumps(captured, ensure_ascii=False)))
        existing = db.execute('SELECT domain,url,status,diagnosis_snapshot FROM improvement_actions WHERE id=?', (identifier,)).fetchone()
        if (existing['domain'] != job['domain'] or existing['url'] != job['url'] or existing['status'] != 'done'
                or json.loads(existing['diagnosis_snapshot']).get('maintenance', {}).get('hashes') != receipt['hashes']):
            raise ValueError('공유 개선 기록 중복 ID의 무결성 불일치')
    return identifier


def archive_receipt(job_id, receipt):
    folder = BACKUPS / job_id
    version = receipt['hashes']['draftSha256']
    if not re.fullmatch(r'[a-f0-9]{64}', version):
        raise ValueError('invalid version hash')
    destination = folder / 'verified-versions' / version
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('original.json', 'draft.json', 'proposal.json', 'receipt.json', 'diff.txt'):
        source = folder / name
        if source.is_file():
            (destination / name).write_bytes(source.read_bytes())


def recover_jobs():
    """An interrupted PUT is resolved by evidence, never by replaying a write."""
    import requests
    with database() as db:
        pending = [dict(r) for r in db.execute("SELECT * FROM maintenance_jobs WHERE status IN ('applying','processing') AND (next_retry_at IS NULL OR next_retry_at<=?)", (stamp(),))]
    for job in pending:
        folder = BACKUPS / job['id']
        receipt = read(folder / 'receipt.json')
        if job['status'] == 'processing':
            save_job(job['id'], status='retry_wait', stage='research', next_retry_at=(now() + timedelta(minutes=30)).isoformat(), reason='중단된 준비 회차 · 원본 변경 없이 재점검')
            continue
        original = read(folder / 'original.json')
        intent = receipt.get('intent', {})
        expected = intent.get('expected')
        if (not expected or digest(original) != receipt.get('hashes', {}).get('originalSha256')
                or version_digest(expected) != intent.get('expectedVersionSha256')):
            save_job(job['id'], status='blocked', stage='verify', reason='중단된 적용 영수증 무결성 미확인 · 원격 수정 재시도 안 함')
            continue
        try:
            endpoint = f'https://www.{job["domain"]}/api/posts/{int(original["id"])}'
            response = requests.get(endpoint, timeout=(3, 5), allow_redirects=False)
            response.raise_for_status()
            actual = response.json()['post']
            if version_digest(actual) == version_digest(expected):
                binding = cache_binding(job['domain'])
                receipt['cachePurge'] = purge_exact(job['domain'], job['url'], original['slug'], binding)
                if not verify_public(job['domain'], job['url'], expected):
                    raise ValueError('현재 공개 내용 확인 대기')
                receipt['canary'] = bool(intent.get('canary'))
                receipt['publicVerification'] = {'status': 'verified', 'url': job['url'], 'postId': original['id'], 'checkedAt': stamp(), 'recoveredInterruptedApply': True}
                identifier = job['action_id'] or register_completed_action(job, receipt)
                atomic(folder / 'receipt.json', receipt)
                archive_receipt(job['id'], receipt)
                save_job(job['id'], status='completed', stage='monitor', completed_at=stamp(), action_id=identifier,
                         proof=json.dumps(receipt, ensure_ascii=False), reason='중단된 적용의 실제 동일 URL 반영 확인 완료')
            elif version_digest(actual) == version_digest(original):
                save_job(job['id'], status='retry_wait', stage='research', next_retry_at=(now() + timedelta(hours=6)).isoformat(), reason='중단된 적용 반영 없음 · 원문 보존 확인')
            else:
                save_job(job['id'], status='blocked', stage='verify', reason='중단 후 다른 수정 내용 확인 · 덮어쓰기·롤백 안 함')
        except Exception:
            save_job(job['id'], status='applying', stage='verify', next_retry_at=(now() + timedelta(hours=6)).isoformat(), reason='반영 상태 미확인 · 원격 PUT 재시도 없이 조회만 대기')


@observed_operation('content_maintenance', 'maintenance-run')
def run_once(force_prepare=False):
    sys.path.insert(0, str(ROOT / 'dashboard'))
    from metrics import collector_lock
    with collector_lock(DATA / 'content-maintenance.lock') as acquired:
        if not acquired:
            return {'status': 'already_running'}
        sync_inventory()
        recover_jobs()
        refresh_growth_state()
        config = state()
        if (Path.home() / 'EGO_EXEC_DISABLED').exists() or (not operation_enabled() and not force_prepare):
            runtime(status='paused', stage='idle', reason='자동 점검 운영 비활성')
            return public_summary()
        wait = idle_reason()
        if wait:
            runtime(status='waiting', stage='idle', reason=wait, publishingPriorityWait=True)
            return public_summary()
        runtime(status='running', stage='audit', reason='전체 기존 글 미점검·오래된 순으로 분산 점검')
        audit_batch()
        wait = idle_reason()
        if wait:
            runtime(status='waiting', stage='audit', reason=wait, publishingPriorityWait=True)
            return public_summary()
        provider = config['runtime'].get('providerBackoff') or {}
        if provider.get('provider') == 'shared_agent_router' and provider.get('nextRetryAt') and not force_prepare:
            try:
                if now() < datetime.fromisoformat(provider['nextRetryAt']):
                    runtime(status='waiting', stage='research', reason='기존 공급자 제한 대기 · 전체 저비용 점검은 계속', nextRetryAt=provider['nextRetryAt'])
                    return public_summary()
            except (ValueError, TypeError):
                runtime(status='waiting', stage='research', reason='공급자 대기 날짜 미확인 · 조사 보류')
                return public_summary()
        previous = config['runtime'].get('lastAttemptAt')
        if previous and not force_prepare:
            try:
                if now() - datetime.fromisoformat(previous) < timedelta(minutes=config['policy']['cycleIntervalMinutes']):
                    runtime(status='idle', stage='audit', reason='전체 점검 진행 · 심층 조사 회차 간격 대기')
                    return public_summary()
            except (ValueError, TypeError):
                pass
        start_day, end_day = day_bounds()
        with database() as db:
            used = db.execute('SELECT COUNT(*) FROM maintenance_jobs WHERE apply_attempt_at>=? AND apply_attempt_at<?', (start_day, end_day)).fetchone()[0]
            attempted = db.execute("SELECT COUNT(*) FROM maintenance_attempts WHERE kind IN ('research','deep_review') AND started_at>=? AND started_at<?", (start_day, end_day)).fetchone()[0]
            deep_used = db.execute("SELECT COUNT(*) FROM maintenance_attempts WHERE kind='deep_review' AND started_at>=? AND started_at<?", (start_day, end_day)).fetchone()[0]
            ready_rows = [dict(r) for r in db.execute("SELECT * FROM maintenance_jobs WHERE status='ready' AND (next_retry_at IS NULL OR next_retry_at<=?) ORDER BY updated_at,id", (stamp(),))]
            if ready_rows and used >= config['policy']['maxUpdatesPerDay']:
                runtime(status='waiting',stage='idle',reason='일일 원격 수정 시도 상한 · 검수 후보 보존')
                return public_summary()
            if not ready_rows and attempted >= config['policy']['maxResearchPerDay']:
                runtime(status='waiting', stage='idle', reason='검증된 일일 수정·조사 상한 도달')
                return public_summary()
            if config['policy']['jevEnabled']:
                cutoff = (now() - timedelta(hours=config['policy']['cooldownHours'])).isoformat()
                rows = ready_rows or [dict(r) for r in db.execute(
                    """SELECT * FROM maintenance_jobs WHERE status IN ('issues_found','retry_wait','queued','audit_checked','inconclusive')
                    AND (next_retry_at IS NULL OR next_retry_at<=?) AND (completed_at IS NULL OR completed_at<=?)
                    ORDER BY attempts,updated_at,id""", (stamp(), cutoff))]
            else:
                rows = ready_rows or [dict(r) for r in db.execute("SELECT * FROM maintenance_jobs WHERE status IN ('issues_found','retry_wait') AND (next_retry_at IS NULL OR next_retry_at<=?) ORDER BY attempts,updated_at,id", (stamp(),))]
            inspect_only = not config['policy']['jevEnabled'] and not ready_rows and deep_used == 0 and (attempted >= config['policy']['maxResearchPerDay'] - 1 or not rows or used >= config['policy']['maxUpdatesPerDay'])
            if inspect_only:
                rows = [dict(r) for r in db.execute("SELECT * FROM maintenance_jobs WHERE status IN ('audit_checked','inconclusive','no_change') ORDER BY deep_review_at IS NOT NULL,deep_review_at,audit_at,id")]
            elif used >= config['policy']['maxUpdatesPerDay']:
                runtime(status='waiting', stage='idle', reason='일일 수정 시도 상한 · 기본점검은 계속')
                return public_summary()
            if not rows:
                runtime(status='idle', stage='idle', reason='처리 가능한 기존 글 없음')
                return public_summary()
        last_domain = config['runtime'].get('lastDomain')
        rows = [row for row in rows if not cooldown_active(row, config['policy'])]
        if not rows:
            runtime(status='waiting', stage='monitor', reason='기존 글의 마지막 Pacific 관측일까지 재수정 보류')
            return public_summary()
        from dashboard.agents.synapse import winner_jobs
        rows = winner_jobs(rows, ROOT)
        if not rows:
            runtime(status='waiting', stage='monitor', reason='실측 상위 유망 글 대기 · 발행 엔진과 독립')
            return public_summary()
        job = next((r for r in rows if r['domain'] != last_domain), rows[0])
        if job['status'] != 'ready':
            window=preparation_window()
            if not window['available']:
                runtime(status='waiting',stage='research',reason=window['reason'],nextRetryAt=window['nextRetryAt'],preparationWindow=window)
                return public_summary()
            with database() as db:
                db.execute('INSERT INTO maintenance_attempts VALUES (?,?,?,?)', (uuid.uuid4().hex, job['id'], stamp(), 'deep_review' if inspect_only else 'research'))
        runtime(status='running', stage='research', lastAttemptAt=stamp(), activeJob=job['id'], lastDomain=job['domain'], reason=None)
        save_job(job['id'], attempts=job['attempts'] + 1, last_attempt_at=stamp(),
                 status='ready' if job['status'] == 'ready' else 'processing',
                 stage='apply' if job['status'] == 'ready' else 'research')
        try:
            result = prepare_job(job, inspect_only) if job['status'] != 'ready' else 'ready'
            if result == 'ready' and not force_prepare:
                return _apply_job(job['id'], canary=not canary_verified())
            runtime(status={'ready': 'prepared', 'blocked': 'blocked', 'retry_wait': 'waiting'}.get(result, 'completed'),
                    stage='review', activeJob=None, reason='검수 결과 기록 · 적용 전 조건 재확인')
        except Exception as exc:
            reason = str(exc) if type(exc) is ValueError else '유지보수 원천 또는 엔진 실행 실패 · 키·원문 오류 응답은 공개하지 않음'
            with database() as db:
                current = db.execute('SELECT status FROM maintenance_jobs WHERE id=?', (job['id'],)).fetchone()[0]
            if current in ('processing', 'ready'):
                if reason == '자동 운영 중지 상태':
                    save_job(job['id'], status='ready', stage='apply', next_retry_at=None, reason=reason)
                else:
                    save_job(job['id'], status='retry_wait', stage='research', next_retry_at=(now() + timedelta(hours=6)).isoformat(), reason=reason)
            runtime(status='paused' if reason == '자동 운영 중지 상태' else 'partial_failure', stage='idle', activeJob=None, reason=reason, nextRetryAt=(now() + timedelta(hours=6)).isoformat())
        return public_summary()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--apply-job')
    args = parser.parse_args()
    result = apply_job(args.apply_job, canary=True) if args.apply_job else run_once(args.prepare_only)
    print(json.dumps({'status': result.get('runtime', {}).get('status'), 'known': result.get('coverage', {}).get('known')}, ensure_ascii=True))
