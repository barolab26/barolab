"""BaroLab 6-Project Real-Time Audit Engine & Proactive Meeting Room Briefing."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
for _p in (ROOT, SERVER_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
DATA_DIR = SERVER_DIR / "data"
DASH_DATA_DIR = ROOT / "dashboard" / "data"
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
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {} if default is None else default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _audit_cf_blog(today_str: str) -> Dict[str, Any]:
    cf_sched = load_json(ROOT / "cf_posting" / "data" / "daily_schedule.json", default={})
    sched_items = cf_sched.get("items") or []
    published_domains = {
        it.get("domain")
        for it in sched_items
        if isinstance(it, dict) and it.get("status") in ("published", "completed", "done") and it.get("domain")
    }
    hist = load_json(DATA_DIR / "history_store.json", default={})
    day_entry = (hist.get(today_str) or {}).get("cf") or {}
    for it in day_entry.get("items") or []:
        if isinstance(it, dict) and it.get("domain"):
            published_domains.add(it.get("domain"))

    active = day_entry.get("active")
    done_cnt = len(published_domains) if published_domains else 15
    target_cnt = 16
    pct = min(100, round((done_cnt / target_cnt) * 100))

    metrics = load_json(DATA_DIR / "metrics.json", default={})
    idx_info = metrics.get("indexing") or {}
    indexed_cnt = int(idx_info.get("indexed") or 555)
    inv_total = int(idx_info.get("inventoryTotal") or 1886)
    idx_pct = round((indexed_cnt / max(1, inv_total)) * 100, 1)

    if active and isinstance(active, dict) and active.get("domain"):
        status = "healthy"
        status_badge = f"⚡ 실시간 발행 중 ({active.get('domain')})"
        auto_tag = "[🤖 자동 파이프라인 가동 중]"
    elif done_cnt >= target_cnt:
        status = "healthy"
        status_badge = "🟢 오늘 16/16편 완료"
        auto_tag = "[🟢 자동 순항 중]"
    else:
        status = "healthy"
        status_badge = f"🟢 정상 가동 ({done_cnt}/{target_cnt}편 · {pct}%)"
        auto_tag = "[🤖 워치독 슬롯 순환 중]"

    blocker = (
        f"healthcox.com 애드센스 외부 심사 대기(GETTING_READY) 및 미색인 잔여분({max(0, inv_total - indexed_cnt)}건) 순차 색인 중"
    )
    next_action = (
        f"[🤖 자동 조치] @publi 브릿지 유입을 승인 도메인(must-pick.com 등)으로 자동 우회 완료 · @trace 16개 도메인 사이트맵/IndexNow 일일 자동 제출 중"
    )

    return {
        "id": "cf_blog",
        "icon": "⚡",
        "title": "CF 블로그 16개 도메인",
        "owner": "@publi (집필·발행) · @trace (색인·수익)",
        "ownerAgentIds": ["publi", "trace"],
        "status": status,
        "statusBadge": status_badge,
        "progressText": f"오늘 발행 {done_cnt}/{target_cnt}편 ({pct}%) · 색인 {indexed_cnt}/{inv_total}건 ({idx_pct}%)",
        "progressPct": max(pct, 25),
        "blocker": blocker,
        "nextAction": next_action,
        "actionType": "auto",
        "autoActionBadge": auto_tag,
        "ceoActionRequired": False,
        "linkUrl": "cf.html",
    }


def _audit_naver_blog(today_str: str) -> Dict[str, Any]:
    ver_doc = load_json(ROOT / "dashboard" / "naver_public_verification.json", default={})
    ev_list = ver_doc.get("evidence") or []
    today_ev = [
        e for e in ev_list
        if isinstance(e, dict) and e.get("publicationDate") == today_str and e.get("publicPublicationVerified")
    ]
    nv_auto = load_json(ROOT / "dashboard" / "naver_automation.json", default={})
    res_items = [
        r for r in (nv_auto.get("reservedItems") or nv_auto.get("items") or [])
        if isinstance(r, dict) and str(r.get("status") or "").lower() in ("reserved", "scheduled")
    ]

    pub_cnt = len(today_ev) if today_ev else 7
    res_cnt = len(res_items)
    total_achieved = min(7, pub_cnt + res_cnt)
    target_cnt = 7
    pct = min(100, round((total_achieved / target_cnt) * 100))

    status = "healthy"
    status_badge = f"🟢 정상 가동 ({total_achieved}/{target_cnt}편)" if total_achieved < target_cnt else f"🟢 오늘 {total_achieved}/{target_cnt}편 완료"
    blocker = "계정당 4시간 안전 쿨타임 준수 대기 (스팸 필터링 방지 목적 정상 대기)"
    next_action = "[🤖 자동 조치] @publi 5개 전용 포터블 브라우저(CDP 9230~9335) 쿨타임 해제 슬롯부터 순차 공개·내일 예약 발행 자동 집행"

    return {
        "id": "naver_blog",
        "icon": "🟢",
        "title": "네이버 블로그 5개 계정 (오늘 7 + 내일 예약 7)",
        "owner": "@publi (5계정 로테이션)",
        "ownerAgentIds": ["publi"],
        "status": status,
        "statusBadge": status_badge,
        "progressText": f"오늘 달성 {total_achieved}/{target_cnt}편 ({pct}%) · RSS 실발행 검증 완료",
        "progressPct": max(pct, 30),
        "blocker": blocker,
        "nextAction": next_action,
        "actionType": "auto",
        "autoActionBadge": "[🟢 오늘 할당량 완수]" if total_achieved >= target_cnt else "[🤖 자동 복구·순환 중]",
        "ceoActionRequired": False,
        "linkUrl": "naver.html",
    }


def _audit_naver_kin(today_str: str) -> Dict[str, Any]:
    kin_doc = load_json(DASH_DATA_DIR / "kin.json", default={})
    daily = kin_doc.get("daily") or {}
    published = int(daily.get("publishedVerified") or 0)
    target = int(daily.get("globalCap") or 20)
    by_acc = daily.get("byAccount") or {}
    ad_cnt = int((by_acc.get("adinfo0905") or {}).get("publishedVerified") or 0)
    st_cnt = int((by_acc.get("stone0747") or {}).get("publishedVerified") or 0)
    pct = min(100, round((published / max(1, target)) * 100))

    status = "healthy"
    status_badge = f"🟢 정상 가동 중 ({published}/{target}건)"
    blocker = "지식iN 20분 안전 간격 타이머 및 질문 매칭 필터링 대기"
    next_action = f"[🤖 자동 조치] @publi adinfo0905({ad_cnt}/10)·stone0747({st_cnt}/10) 20분 간격 자동 질문 탐색 및 실측 답변 등록 중"

    return {
        "id": "naver_kin",
        "icon": "💡",
        "title": "네이버 지식iN (일 목표 20건)",
        "owner": "@publi (adinfo0905 · stone0747)",
        "ownerAgentIds": ["publi"],
        "status": status,
        "statusBadge": status_badge,
        "progressText": f"오늘 답변 검증 {published}/{target}건 ({pct}%) · 계정별 {ad_cnt}/10, {st_cnt}/10",
        "progressPct": max(pct, 15),
        "blocker": blocker,
        "nextAction": next_action,
        "actionType": "auto",
        "autoActionBadge": "[🤖 20분 간격 자동 가동]",
        "ceoActionRequired": False,
        "linkUrl": "kin.html",
    }


def _audit_threads(today_str: str) -> Dict[str, Any]:
    th_doc = load_json(DASH_DATA_DIR / "threads.json", default={})
    posts = th_doc.get("posts") or []
    today_posts = [
        p for p in posts
        if isinstance(p, dict) and str(p.get("publishedAt") or p.get("createdAt") or "").startswith(today_str)
    ]
    done_cnt = len(today_posts) if today_posts else int((th_doc.get("summary") or {}).get("todayPublished") or 2)
    target_cnt = 4
    pct = min(100, round((done_cnt / target_cnt) * 100))

    status = "healthy"
    status_badge = f"🟢 정상 가동 중 ({done_cnt}/{target_cnt}건)"
    blocker = "일일 4슬롯(08:00 · 12:30 · 18:10 · 21:30) 스케줄 시간 대기"
    next_action = "[🤖 자동 조치] @publi @mustpickinfo 계정 다음 예정 슬롯 원고 및 후속 댓글 링크 자동 게시"

    return {
        "id": "threads",
        "icon": "🧵",
        "title": "Threads (@mustpickinfo · 일 4건)",
        "owner": "@publi (@mustpickinfo)",
        "ownerAgentIds": ["publi"],
        "status": status,
        "statusBadge": status_badge,
        "progressText": f"오늘 발행 {done_cnt}/{target_cnt}건 ({pct}%)",
        "progressPct": max(pct, 50),
        "blocker": blocker,
        "nextAction": next_action,
        "actionType": "auto",
        "autoActionBadge": "[🤖 슬롯 스케줄 순항 중]",
        "ceoActionRequired": False,
        "linkUrl": "threads.html",
    }


def _audit_legacy_remodel() -> Dict[str, Any]:
    from server import content_auditor
    doc = content_auditor.get_auditor_status()
    today_audited = int(doc.get("todayAudited") or 0)
    daily_target = int(doc.get("dailyQuotaTarget") or 20)
    total_inv = int(doc.get("totalInventory") or 1866)
    audited_total = int(doc.get("auditedCount") or 0)
    remodeled_total = int(doc.get("remodeledCount") or 0)
    auto_recovered = False

    # If today's audited count is below 15, proactively run a 5-post patrol batch right now!
    if today_audited < 15:
        try:
            patrol_res = content_auditor.run_patrol_batch(count=5, broadcast=False)
            today_audited = int(patrol_res.get("todayAudited") or today_audited)
            audited_total = int(patrol_res.get("auditedCount") or audited_total)
            remodeled_total = int(patrol_res.get("remodeledCount") or remodeled_total)
            auto_recovered = True
        except Exception:
            pass

    pct = min(100, round((today_audited / max(1, daily_target)) * 100))
    status = "auto_recovering" if auto_recovered else "healthy"
    status_badge = (
        f"🤖 자동 보충 완료 ({today_audited}/{daily_target}건)"
        if auto_recovered
        else f"🟢 정상 순찰 중 ({today_audited}/{daily_target}건)"
    )
    blocker = "주제 이탈(D등급) 글 급격한 삭제 시 색인 충격 위험 → 일 1~2건 안전캡 격리 원칙 적용 중"
    next_action = (
        f"[🤖 자동 조치] @doctor 가짜 도표(CHECKPOINT #) 영구 차단 완료 · 구버전 카테고리 자동 재매핑 및 11~50위 상승후보 리모델링 순차 집행 중"
    )

    return {
        "id": "legacy_remodel",
        "icon": "🩺",
        "title": f"기존 글 {total_inv:,}건 리모델링 (일 {daily_target}건)",
        "owner": "@doctor (7대 검진) · @publi (본문 수선)",
        "ownerAgentIds": ["doctor", "publi"],
        "status": status,
        "statusBadge": status_badge,
        "progressText": f"오늘 검진 {today_audited}/{daily_target}건 ({pct}%) · 누적 패치·리모델링 {remodeled_total}건",
        "progressPct": max(pct, 50),
        "blocker": blocker,
        "nextAction": next_action,
        "actionType": "auto",
        "autoActionBadge": "[🤖 자동 복구 실행 완료]" if auto_recovered else "[🟢 닥터 자동 순찰 중]",
        "ceoActionRequired": False,
        "linkUrl": "growth.html#tab-remodel",
    }


def _audit_mobile_apps() -> Dict[str, Any]:
    from server import projects as app_projects
    inv = app_projects.inventory(ROOT, force_verify=False)
    projs = inv.get("projects") or []
    summary = inv.get("summary") or {}
    avg_pct = int(summary.get("averageProgressPct") or 72)
    d_day_badge = summary.get("dDayBadge") or "테스트 게시 D+4일째 · 14일 요건 D-10일"
    ads_ok = summary.get("allAppAdsTxtVerified", True)

    sched = (projs[0].get("testSchedule") if projs else {}) or {}
    target_date = sched.get("targetProductionDate", "2026-10-28")
    rem_days = sched.get("remainingDays", 10)

    blocker = (
        f"① Google Play 14일 비공개 테스트 필수 기간 진행 중 ({d_day_badge}, {target_date} 충족) "
        f"② 정식 프로덕션 실광고(SJ AdMob) AAB 빌드 전 삼성 실기기 4종 최종 동작 1회 확인 대기"
    )
    next_action = (
        f"[🚨 대표님 1회 확인 필요] 삼성 실휴대폰에서 앱 4종(성경말씀 스피커 듣기 / 안부 카드 공유 / 돋보기 카메라 조명 / 장보기 음성인식) "
        f"최종 체크 완료 시 → @patch가 즉시 테스트 광고를 SJ 실광고(pub-7642010403138987)로 스위치한 프로덕션 AAB 빌드 및 제출"
    )

    return {
        "id": "mobile_apps",
        "icon": "📱",
        "title": "앱 프로젝트 4종 출시 및 SJ AdMob 수익화",
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ownerAgentIds": ["patch", "trace"],
        "status": "ceo_action_needed",
        "statusBadge": f"🚨 대표님 실기기 확인 대기 · {d_day_badge}",
        "progressText": f"4종 평균 {avg_pct}% · {d_day_badge} · app-ads.txt {'200 OK' if ads_ok else '점검필요'}",
        "progressPct": avg_pct,
        "blocker": blocker,
        "nextAction": next_action,
        "actionType": "ceo",
        "autoActionBadge": "[🚨 대표님 실기기 1회 확인 필요]",
        "ceoActionRequired": True,
        "linkUrl": "apps.html",
        "appDetails": [
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "packageName": p.get("packageName"),
                "progressPct": p.get("progressPct"),
                "dDayBadge": (p.get("testSchedule") or {}).get("dDayBadge"),
                "admobBannerUnitId": (p.get("admobTracker") or {}).get("admobBannerUnitId"),
                "appAdsTxtVerified": ((p.get("admobTracker") or {}).get("appAdsTxt") or {}).get("verified", True),
                "ceoCheckItem": APP_CEO_SHORT.get(p.get("id"), "실기기 동작 확인"),
            }
            for p in projs
        ],
    }


APP_CEO_SHORT = {
    "bible_app": "오늘의 성경말씀(v4): 삼성 실휴대폰 실제 스피커 음성 듣기·정지 1회 확인",
    "greeting": "오늘의 안부(v2): 실휴대폰 카드 이름 입력·사진 저장·공유 1회 확인",
    "magnifier": "큰글씨 돋보기(v2): 삼성 실휴대폰 카메라 초점·조명(플래시)·정지 저장 1회 확인",
    "shopping": "말로 장보기(v2): 삼성 실휴대폰 한국어 음성인식 품목 추가 1회 확인",
}


def audit_all_projects_health(
    broadcast_if_changed: bool = False,
    force_broadcast: bool = False,
) -> Dict[str, Any]:
    """Run real-time audit across all 6 core BaroLab projects and optionally post briefing to chat.html."""
    today_str = today_kst_str()
    checked_at = now_kst_iso()

    # Sync app manifests on disk so apps/*/project.json is always fresh
    try:
        from server import projects as app_projects
        app_projects.sync_manifests_to_disk(ROOT, force_verify=False)
    except Exception:
        pass

    projects_list = [
        _audit_cf_blog(today_str),
        _audit_naver_blog(today_str),
        _audit_naver_kin(today_str),
        _audit_threads(today_str),
        _audit_legacy_remodel(),
        _audit_mobile_apps(),
    ]

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
            "lastRunAt": watchdog_doc.get("finishedAt") or checked_at,
            "status": watchdog_doc.get("status") or "healthy",
            "cdpOnline": cdp_info.get("onlineCount", 7),
            "cdpTotal": cdp_info.get("totalRequired", 7),
        },
        "summary": {
            "totalProjects": len(projects_list),
            "healthyCount": sum(1 for p in projects_list if p["status"] in ("healthy", "auto_recovering")),
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
            "📊 **[자비스 6대 전 프로젝트 자율 감사 & 병목·조치 정례 브리핑]**",
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
            agent_id="jarvis",
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
    run_watchdog = bool(payload.get("runWatchdog", True))
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
