"""BaroLab 6-Project Real-Time Audit Engine & Proactive Meeting Room Briefing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body

ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = ROOT / 'dashboard' / 'server'
for _p in (ROOT, SERVER_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
DATA_DIR = Path(__file__).resolve().parents[2] / 'dashboard/data'
DASH_DATA_DIR = ROOT / "dashboard" / "data" / "public"
HEALTH_SNAPSHOT_PATH = DATA_DIR / "project-health.json"
WATCHDOG_STATUS_PATH = DATA_DIR / "watchdog-status.json"

KST = timezone(timedelta(hours=9))
router = APIRouter()


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_iso() -> str:
    return now_kst().isoformat(timespec="seconds")


def today_kst_str() -> str:
    return now_kst().strftime("%Y-%m-%d")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            parsed = json.loads(path.read_text(encoding="utf-8-sig"))
            return parsed if isinstance(parsed, dict) else ({} if default is None else default)
    except Exception:
        pass
    return {} if default is None else default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# Snapshot readers must never trigger publishing, patrols, or manifest writes.
SOURCES = (
    ('cf_blog', 'CF 블로그', 'dashboard/data/cf/daily_schedule.json', 'publi', 'cf.html'),
    ('naver_blog', '네이버 블로그', 'dashboard/data/naver/automation-status.json', 'publi', 'naver.html'),
    ('naver_kin', '네이버 지식iN', 'dashboard/data/kin-automation-state.json', 'publi', 'kin.html'),
    ('threads', 'Threads', 'dashboard/data/public/threads.json', 'publi', 'threads.html'),
    ('legacy_remodel', '콘텐츠 유지보수', 'dashboard/data/content-maintenance.json', 'doctor', 'growth.html'),
    ('mobile_apps', '앱 프로젝트', 'apps/bible/project.json', 'patch', 'apps.html'),
    ('collections', '조회·수집', 'dashboard/data/collection-health.json', 'trace', 'growth.html'),
)


def schedule_constants(relative, names):
    """Read scheduler literal policy without importing modules that load secrets or write."""
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[2] / relative).read_text(encoding='utf-8-sig'))
    return {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names}


def publication_quota(key, doc, now, fresh):
    try:
        return _publication_quota(key, doc, now, fresh)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SyntaxError):
        return {'status': 'unknown', 'date': now.date().isoformat(), 'due': None,
                'verified': None, 'missing': None, 'reason': 'invalid_or_unavailable_quota_source'}


def _publication_quota(key, doc, now, fresh):
    """Due slots lacking public evidence; never equate absence with failed submission."""
    from urllib.parse import urlsplit
    import re
    day = now.date().isoformat()
    unknown = {'status': 'unknown', 'date': day, 'due': None, 'verified': None, 'missing': None}
    if not fresh:
        return unknown
    def url_ok(value, naver=False):
        try:
            u = urlsplit(str(value or ''))
            return u.scheme in ('http', 'https') and bool(u.hostname) and not u.username and not u.password and (
                not naver or u.scheme == 'https' and u.hostname in ('blog.naver.com', 'm.blog.naver.com')
                and bool(re.fullmatch(r'/[A-Za-z0-9_-]+/\d+/?', u.path)))
        except ValueError:
            return False
    def due(slot):
        return bool(re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(slot or ''))) and slot <= now.strftime('%H:%M')
    expected, completed = set(), set()
    if key == 'cf_blog':
        if doc.get('date') != day or not isinstance(doc.get('items'), list) or not doc['items']:
            return unknown
        domains = schedule_constants('cf_posting/posting.py', ('ALL_DOMAINS',))['ALL_DOMAINS']
        if {r.get('domain') for r in doc['items'] if isinstance(r, dict)} != set(domains):
            return {**unknown, 'reason': 'incomplete_schedule'}
        for row in doc['items']:
            if not isinstance(row, dict) or not row.get('domain') or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(row.get('scheduledTime') or '')):
                return unknown
            identity = row['domain']
            if due(row['scheduledTime']):
                expected.add(identity)
                if row.get('status') == 'published' and url_ok(row.get('publicUrl')):
                    completed.add(identity)
    elif key == 'naver_blog':
        policy = schedule_constants('naver_blog_posting/posting.py',
                                    ('DAILY_SLOTS', 'LEGACY_SLOT_ALIASES', 'LEGACY_SINGLE_SLOTS'))
        DAILY_SLOTS = policy['DAILY_SLOTS']
        schedule_plan = load_json(DATA_DIR / 'daily_schedule.json')
        if schedule_plan.get('effectiveDate') and day >= schedule_plan['effectiveDate']:
            DAILY_SLOTS = {account: row['slots'] for account,row in schedule_plan['naver'].items()}
        def slot_matches(account, candidate, target):
            return (candidate == target or candidate in policy.get('LEGACY_SLOT_ALIASES', {}).get(account, {}).get(target, ())
                    or len(DAILY_SLOTS[account]) == 1 and candidate in policy.get('LEGACY_SINGLE_SLOTS', {}).get(account, ()))
        evidence = load_json(ROOT / 'dashboard/data/naver/public-verification.json')
        stamp = evidence.get('checkedAt') or evidence.get('reportReceivedAt')
        try:
            age = (now - datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))).total_seconds()
        except (ValueError, TypeError):
            return unknown
        if not 0 <= age <= 7200 or not isinstance(evidence.get('evidence'), list):
            return unknown
        used_urls = set()
        for account, slots in DAILY_SLOTS.items():
            for slot in slots:
                if not due(slot):
                    continue
                identity = account + ':' + slot
                expected.add(identity)
                for row in evidence['evidence']:
                    if not isinstance(row, dict):
                        continue
                    publication_day = row.get('publicationDate') or str(row.get('reserveTime') or '')[:10]
                    if (row.get('account') == account and publication_day == day
                            and slot_matches(account, row.get('scheduledSlot') or str(row.get('reserveTime') or '')[-5:], slot)
                            and row.get('status', 'done') == 'done' and row.get('publicPublicationVerified') is True
                            and row.get('verified') is True and url_ok(row.get('publicUrl'), True)
                            and row['publicUrl'] not in used_urls):
                        completed.add(identity); used_urls.add(row['publicUrl']); break
    elif key == 'threads':
        config = doc.get('configuration')
        today = doc.get('today')
        if not isinstance(config, dict) or not isinstance(today, dict):
            return unknown
        if config.get('enabled') is not True:
            return {**unknown, 'status': 'disabled'}
        if today.get('date') != day or doc.get('countsComplete') is not True:
            return unknown
        slots = config.get('preferredTimes')
        if not isinstance(slots, list) or not slots or any(not isinstance(s, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', s) for s in slots):
            return unknown
        expected = {slot for slot in slots if due(slot)}
        # recent may be truncated: use exact today aggregate only when every due slot
        # has evidence; otherwise report unavailable attribution, not invented failures.
        for row in doc.get('recent') or []:
            if (isinstance(row, dict) and row.get('publication_date') == day and row.get('kind') == 'main'
                    and row.get('state') == 'published_verified' and url_ok(row.get('permalink'))
                    and row.get('slot') in expected):
                completed.add(row['slot'])
        total = sum(r.get('n', 0) for r in today.get('counts', []) if r.get('kind') == 'main' and r.get('state') == 'published_verified')
        if total > len(completed):
            return unknown
    elif key == 'naver_kin':
        return {**unknown, 'status':'interval_managed'}
    else:
        return {**unknown, 'status': 'not_scheduled'}
    return {'status': 'observed', 'date': day, 'due': len(expected), 'verified': len(completed),
            'missing': len(expected - completed), 'missingSlots': sorted(expected - completed)}


def kin_activity(doc, now):
    try:
        return _kin_activity(doc, now)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return {'status': 'unknown', 'reason': 'invalid_activity_source'}


def _kin_activity(doc, now):
    """Actual attempts, including no-candidate outcomes, establish hourly liveness."""
    import sqlite3
    from contextlib import closing
    def parse(value):
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            return dt if dt.tzinfo is not None else None
        except (ValueError, TypeError):
            return None
    unknown = {'status': 'unknown', 'reason': 'activity_evidence_unavailable'}
    checked = parse(doc.get('checkedAt'))
    today = now.date().isoformat()
    current = checked is not None and checked.astimezone(KST).date() == now.date() and 0 <= (now - checked).total_seconds() <= 7200
    if current and doc.get('enabled') is False:
        return {'status': 'held', 'reason': 'automation_disabled'}
    if current and not doc.get('continuousMode') and isinstance(doc.get('endDate'), str) and today > doc['endDate']:
        return {'status': 'held', 'reason': 'outside_publication_window'}
    if current and doc.get('cadenceState') in ('daily_limit_or_account_unavailable', 'accounts_suspended', 'experiment_completed'):
        held = doc['cadenceState'] == 'experiment_completed' or (
            doc['cadenceState'] == 'daily_limit_or_account_unavailable' and doc.get('globalRemainingRuns') == 0)
        return {'status': 'held' if held else 'blocked', 'reason': doc['cadenceState']}
    if doc.get('enabled') is not True:
        return unknown
    latest = parse(doc.get('lastRunAt'))
    outcome = 'completed'
    db_path = ROOT / 'dashboard/data/kin.sqlite3'
    try:
        if not db_path.is_file():
            return unknown
        with closing(sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            row = db.execute('SELECT state,updated_at FROM automation_slots ORDER BY julianday(updated_at) DESC LIMIT 1').fetchone()
        if row:
            actual = parse(row[1])
            if actual and (latest is None or actual >= latest):
                latest, outcome = actual, row[0]
    except (sqlite3.Error, OSError, ValueError):
        return unknown
    active = parse(doc.get('activeStartedAt')) if doc.get('activeRunId') else None
    if active and (latest is None or active > latest):
        latest, outcome = active, 'running'
    if latest is None or latest > now:
        return unknown
    interval = doc.get('intervalMinutes', 60)
    jitter = doc.get('intervalJitterMinutes') or []
    if not isinstance(jitter, list):
        return unknown
    minutes = max([60] + [v for v in [interval, *jitter] if type(v) in (int, float) and 0 < v <= 1440])
    expected = latest + timedelta(minutes=minutes + 15)
    eligible = parse(doc.get('nextEligibleAt'))
    # A stale prior-day hold cannot indefinitely move today's inactivity deadline.
    if current and eligible and eligible.astimezone(KST).date() == now.date():
        expected = max(expected, eligible + timedelta(minutes=15))
    status = ('stalled' if active else 'overdue') if now > expected else 'recent'
    return {'status': status, 'lastAttemptAt': latest.astimezone(KST).isoformat(),
            'expectedAt': expected.astimezone(KST).isoformat(),
            'lastOutcome': outcome if outcome in ('skipped', 'blocked', 'running', 'started', 'published_verified', 'submitted_unverified', 'completed') else 'observed',
            'reason': 'no_recent_attempt' if status == 'overdue' else 'active_run_stalled' if status == 'stalled' else 'attempt_observed'}


def observed_projects():
    now = now_kst()
    result = []
    autonomy = load_json(ROOT / 'dashboard/data/project-autonomy-state.json', {})
    work_rows = autonomy.get('projects', {}) if isinstance(autonomy.get('projects'),dict) else {}
    for key, title, relative, owner, link in SOURCES:
        path = ROOT / relative
        error_type = None
        try:
            raw = path.read_bytes() if path.is_file() else b''
        except OSError as exc:
            raw = b''
            error_type = type(exc).__name__
        supporting = []
        if key == 'mobile_apps':
            for app_name in ('bible', 'greeting', 'magnifier', 'shopping'):
                app_path = ROOT / 'apps' / app_name / 'project.json'
                try:
                    app_raw = app_path.read_bytes()
                    app = json.loads(app_raw.decode('utf-8-sig'))
                    if not isinstance(app, dict):
                        raise ValueError('Invalid app manifest')
                    supporting.append({'path': str(app_path.relative_to(ROOT)),
                        'sha256': hashlib.sha256(app_raw).hexdigest(),
                        'stage': app.get('stage'), 'updatedAt': app.get('updatedAt'),
                        'blocker': app.get('blocker'), 'nextAction': app.get('nextAction')})
                except (OSError, ValueError, UnicodeError) as exc:
                    error_type = type(exc).__name__
                    supporting.append({'path': str(app_path.relative_to(ROOT)), 'errorType': error_type})
        try:
            doc = json.loads(raw.decode('utf-8-sig')) if raw else {}
            if not isinstance(doc, dict):
                raise ValueError('Source document is not an object')
        except (ValueError, UnicodeError) as exc:
            doc = {}
            error_type = type(exc).__name__
        runtime = doc.get('runtime') or {}
        if not isinstance(runtime, dict):
            runtime = {}
            error_type = 'InvalidRuntimeType'
        stamp = doc.get('checkedAt') or doc.get('updatedAt') or runtime.get('checkedAt') or doc.get('createdAt')
        age = None
        try:
            dt = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            age = (now - dt).total_seconds()
        except (TypeError, ValueError):
            pass
        source_date = doc.get('date') or doc.get('workDate')
        fresh = (source_date == now.date().isoformat()) if key == 'cf_blog' else age is not None and 0 <= age <= 7200 and (not source_date or source_date == now.date().isoformat())
        rows = doc.get('sources') or [] if key == 'collections' else doc.get('items') or doc.get('reservedItems') or doc.get('accounts') or []
        if not isinstance(rows, list):
            rows = []
        counts = {}
        for row in rows:
            if isinstance(row, dict):
                status = str(row.get('status') or 'unknown')
                counts[status] = counts.get(status, 0) + 1
        failures = []
        for row in rows:
            if isinstance(row, dict) and row.get('status') in ('failed', 'error', 'review_required', 'unknown', 'partial', 'backoff', 'stale'):
                failures.append({'identity': str(row.get('domain') or row.get('account') or row.get('source') or row.get('taskId') or row.get('id') or 'unidentified'),
                    'status': row.get('status'), 'reasonCode': row.get('reasonCode'), 'stage': row.get('currentStage') or row.get('stage'),
                    'failureAt': row.get('lastErrorAt') or row.get('failedAt'),
                    'errorSha256': hashlib.sha256(str(row.get('lastError') or row.get('errorCode') or '').encode()).hexdigest()})
        public_count = None
        reserved_count = None
        if key in ('cf_blog', 'naver_blog') and source_date == now.date().isoformat():
            def valid_url(value):
                from urllib.parse import urlsplit
                parsed = urlsplit(str(value or ''))
                return parsed.scheme in ('http', 'https') and bool(parsed.hostname)
            verified = [r for r in rows if isinstance(r, dict) and valid_url(r.get('publicUrl'))
                        and (r.get('status') == 'published' if key == 'cf_blog' else
                             r.get('status') == 'done' and r.get('publicPublicationVerified') is True
                             and r.get('publicationDate') == now.date().isoformat())]
            public_count = len({r.get('domain') if key == 'cf_blog' else r['publicUrl'] for r in verified}) if key == 'cf_blog' else None
            reserved_count = sum(1 for r in rows if isinstance(r, dict) and r.get('status') in ('reserved', 'scheduled'))
        state = str(doc.get('collectionStatus') if key == 'collections' else doc.get('state') or runtime.get('status') or 'not_reported')
        failed = sum(counts.get(k, 0) for k in ('failed', 'error', 'review_required', 'unknown'))
        status = 'unknown' if error_type or not raw or (age is None and key != 'cf_blog') else 'stale' if not fresh else 'attention' if failed or state in ('failed', 'error', 'unknown', 'partial', 'backoff', 'stale') else 'observed'
        quota = publication_quota(key, doc, now, fresh and (age is not None or key == 'cf_blog') and not error_type)
        activity = kin_activity(doc, now) if key == 'naver_kin' else None
        if activity and activity['status'] in ('overdue', 'stalled', 'blocked'):
            status = 'attention'
        elif activity and activity['status'] == 'unknown' and status == 'observed':
            status = 'unknown'
        if quota.get('missing') and status == 'observed':
            status = 'attention'
        elif quota.get('status') == 'unknown' and key in ('cf_blog', 'naver_blog', 'threads') and status == 'observed':
            status = 'unknown'
        from common.project_autonomy import recoverable_work
        work = [{k:t.get(k) for k in ('workId','identity','date','slot','status','stage')} for t in recoverable_work(key)] if key in ('cf_blog','naver_blog') else []
        if work:status='attention'
        result.append({'recoverableWork':work,'id': key, 'icon': '•', 'title': title, 'owner': '@' + owner, 'quota': quota, 'activity': activity,
            'ownerAgentIds': [owner], 'status': status, 'statusBadge': status,
            'progressText': json.dumps(counts, ensure_ascii=False) if counts else '관측 상태: ' + state,
            'progressPct': 0, 'counts': counts, 'failures': failures, 'verifiedPublicCount': public_count,
            'reservedCount': reserved_count, 'observedState': state,
            'blocker': '원천 자료가 오래되었거나 불완전함' if status in ('unknown', 'stale') else '실제 원장 상태 확인 필요' if status == 'attention' else '현재 원천 상태 관측; 작업 성공 여부 별도 검증',
            'nextAction': '담당 직원 읽기 전용 점검', 'actionType': 'observe',
            'autoActionBadge': '조치 실행 증거 없음', 'ceoActionRequired': False, 'linkUrl': link,
            'source': {'errorType': error_type, 'supportingManifests': supporting, 'path': relative, 'sha256': hashlib.sha256(raw).hexdigest() if raw else None,
                       'observedAt': now.isoformat(), 'sourceCheckedAt': stamp, 'sourceDate': source_date,
                       'fresh': fresh, 'ageSeconds': round(age) if age is not None else None}})
        active = work_rows.get(key, {}).get('failureWork') if isinstance(work_rows.get(key),dict) else None
        if isinstance(active,dict) and active.get('status') != 'public_verified':
            row = result[-1]
            target = active.get('target') or {}
            row['activeWork'] = {field: active.get(field) for field in
                ('workId','status','recoveryStatus','step','assignedRole')}
            row['activeWork']['identity'] = target.get('identity')
            row['activeWork']['publicationDate'] = target.get('date')
            row.update(status='attention',statusBadge='attention',actionType='repair_original',
                nextAction='원작업 담당 직원이 누락 자료·반려 사유를 보완한 뒤 동일 건 재검수',
                blocker='미완료 원작업 유지 · 새 주제 전환 중지 · 공개 검증 전 완료 처리 금지',
                autoActionBadge='원작업 복구 단계: '+str(active.get('step') or '담당자 진단 대기'))
    return result


def audit_all_projects_health(
    broadcast_if_changed: bool = False,
    force_broadcast: bool = False,
) -> Dict[str, Any]:
    """Run real-time audit across registered BaroLab projects and optionally post briefing to chat.html."""
    today_str = today_kst_str()
    checked_at = now_kst_iso()

    projects_list = observed_projects()

    ceo_items: List[Dict[str, Any]] = []
    for p in projects_list:
        if p.get("ceoActionRequired"):
            ceo_items.append({
                "projectId": p["id"],
                "projectTitle": p["title"],
                "owner": p["owner"],
                "badge": p["statusBadge"],
                "blocker": p["blocker"],
                "requiredAction": p["nextAction"],
                "linkUrl": p["linkUrl"],
                "checklist": [
                    f"📱 {d['name']}: {d['ceoCheckItem']}"
                    for d in (p.get("appDetails") or [])
                ],
            })

    watchdog_doc = load_json(WATCHDOG_STATUS_PATH, default={})
    cdp_info = watchdog_doc.get("cdpBrowsers") or {}

    # Compute state fingerprint to avoid duplicate chat broadcasts
    fp_source = json.dumps(
        [(p["id"], p["status"], p["statusBadge"], p["ceoActionRequired"]) for p in projects_list],
        ensure_ascii=False,
    )
    fingerprint = hashlib.sha256(fp_source.encode("utf-8")).hexdigest()[:16]

    prev_snapshot = load_json(HEALTH_SNAPSHOT_PATH, default={})
    prev_fp = prev_snapshot.get("fingerprint")
    prev_broadcast_date = prev_snapshot.get("lastBroadcastDate")

    should_broadcast = force_broadcast or (
        broadcast_if_changed and (fingerprint != prev_fp or prev_broadcast_date != today_str)
    )

    broadcasted = False
    if should_broadcast:
        broadcasted = broadcast_health_briefing_to_chat(projects_list, ceo_items)

    snapshot = {
        "schema": "barolab-project-health-v1",
        "checkedAt": checked_at,
        "todayKst": today_str,
        "fingerprint": fingerprint,
        "lastBroadcastDate": today_str if (broadcasted or prev_broadcast_date == today_str) else prev_broadcast_date,
        "watchdog": {
            "lastRunAt": watchdog_doc.get("finishedAt"),
            "status": watchdog_doc.get("status") or "unknown",
            "cdpOnline": cdp_info.get("onlineCount"),
            "cdpTotal": cdp_info.get("totalRequired"),
        },
        "summary": {
            "totalProjects": len(projects_list),
            "healthyCount": sum(1 for p in projects_list if p["status"] == "healthy"),
            "ceoActionCount": len(ceo_items),
        },
        "ceoActionItems": ceo_items,
        "projects": projects_list,
    }
    try:
        save_json(HEALTH_SNAPSHOT_PATH, snapshot)
    except Exception:
        pass
    return snapshot


def broadcast_health_briefing_to_chat(
    projects_list: List[Dict[str, Any]],
    ceo_items: List[Dict[str, Any]],
) -> bool:
    """Have @jarvis and @patch/@trace post a proactive 6-project & SJ AdMob status briefing into chat.html."""
    try:
        from server import chat_room

        lines = [
            "📊 **[호스트 원천 상태 관측 — 모델 판단 및 조치 실행 아님]**",
            "",
        ]
        for idx, p in enumerate(projects_list, start=1):
            lines.append(
                f"{idx}. **{p['icon']} {p['title']}** — `{p['statusBadge']}` | 전담: **{p['owner']}**\n"
                f"   - 진행률: {p['progressText']}\n"
                f"   - 병목/대기 사유: {p['blocker']}\n"
                f"   - 다음 조치: {p['nextAction']}"
            )

        if ceo_items:
            lines.append("")
            lines.append("🚨 **[지금 대표님 확인이 필요한 항목 (에이전트 자동 처리 불가 영역)]**")
            for item in ceo_items:
                lines.append(f"- **{item['projectTitle']}** ({item['owner']}): {item['requiredAction']}")
                for chk in item.get("checklist") or []:
                    lines.append(f"  · {chk}")

        chat_room.append_agent_message(
            agent_id="common-runner",
            content="\n".join(lines),
            room_id="main",
            msg_type="project_health_briefing",
            metadata={
                "kstTime": now_kst_iso(),
                "ceoActionCount": len(ceo_items),
            },
        )
        return True
    except Exception:
        return False


@router.get("/api/project-health")
def get_project_health() -> Dict[str, Any]:
    return audit_all_projects_health(broadcast_if_changed=False, force_broadcast=False)


@router.post("/api/project-health/run-audit")
def run_project_health_audit(payload: Optional[Dict[str, Any]] = Body(default=None)) -> Dict[str, Any]:
    payload = payload or {}
    broadcast = bool(payload.get("broadcast", True))
    run_watchdog = bool(payload.get("runWatchdog", False))
    watchdog_res = None
    if run_watchdog:
        try:
            from common import system_watchdog
            watchdog_res = system_watchdog.run_system_watchdog(trigger_source="dashboard-manual", broadcast=False)
        except Exception as exc:
            watchdog_res = {"error": str(exc)[:200]}
    health = audit_all_projects_health(broadcast_if_changed=broadcast, force_broadcast=broadcast)
    if watchdog_res:
        health["watchdogReceipt"] = watchdog_res
    return health
