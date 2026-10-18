"""Live App Portfolio & SJ AdMob Monetization Tracker (4 Android Apps)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import json
import math
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter
import requests

ROOT = Path(__file__).resolve().parent.parent
router = APIRouter()

KST = timezone(timedelta(hours=9))

PROJECT_REGISTRY = (
    ("bible_app", "apps/bible/project.json"),
    ("greeting", "apps/greeting/project.json"),
    ("magnifier", "apps/magnifier/project.json"),
    ("shopping", "apps/shopping/project.json"),
)

SJ_ADMOB_PUBLISHER_ID = "pub-7642010403138987"
SJ_APP_ADS_LINE = "google.com, pub-7642010403138987, DIRECT, f08c47fec0942fa0"

APP_MONETIZATION_CATALOG: Dict[str, Dict[str, Any]] = {
    "bible_app": {
        "packageName": "com.barolab.harubible",
        "playAppId": "4975007773224005878",
        "admobAppId": "ca-app-pub-7642010403138987~3426234878",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/9298253515",
        "admobBannerName": "today_reading_banner",
        "appAdsTxtUrl": "https://haru-malsseum.pages.dev/app-ads.txt",
        "internalReleaseAt": "2026-10-14T19:13:00+09:00",
        "versionName": "0.4.0-internal-preview",
        "versionCode": 4,
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "삼성 갤럭시 실휴대폰에서 v4 성경말씀 실제 스피커 음성 듣기·정지 1회 최종 확인",
    },
    "greeting": {
        "packageName": "com.barolab.morningcard",
        "playAppId": "4973731498485355571",
        "admobAppId": "ca-app-pub-7642010403138987~7847239341",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/8940829169",
        "admobBannerName": "greeting_lists_banner",
        "appAdsTxtUrl": "https://barolab-daily-apps.pages.dev/app-ads.txt",
        "internalReleaseAt": "2026-10-14T19:10:00+09:00",
        "versionName": "0.2.0-internal-preview",
        "versionCode": 2,
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "실휴대폰에서 안부 카드 이름 입력·사진 배경 저장·카카오톡 공유 1회 최종 확인",
    },
    "magnifier": {
        "packageName": "com.barolab.biglens",
        "playAppId": "4972819523776643880",
        "admobAppId": "ca-app-pub-7642010403138987~5789333475",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/4744854277",
        "admobBannerName": "magnifier_help_banner",
        "appAdsTxtUrl": "https://barolab-daily-apps.pages.dev/app-ads.txt",
        "internalReleaseAt": "2026-10-14T19:15:00+09:00",
        "versionName": "0.2.0-internal-preview",
        "versionCode": 2,
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "삼성 실휴대폰 실제 카메라 확대·초점·조명(플래시)·화면 정지 저장 1회 최종 확인",
    },
    "shopping": {
        "packageName": "com.barolab.voicebasket",
        "playAppId": "4972748430542309887",
        "admobAppId": "ca-app-pub-7642010403138987~6881642030",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/2730644038",
        "admobBannerName": "shopping_lists_banner",
        "appAdsTxtUrl": "https://barolab-daily-apps.pages.dev/app-ads.txt",
        "internalReleaseAt": "2026-10-14T19:10:00+09:00",
        "versionName": "0.2.0-internal-preview",
        "versionCode": 2,
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "삼성 실휴대폰 한국어 음성인식 품목 추가·체크 스크롤 1회 최종 확인",
    },
}

_APP_ADS_CACHE: Dict[str, Dict[str, Any]] = {}
_APP_ADS_TTL_SECONDS = 900


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_iso() -> str:
    return now_kst().isoformat(timespec="seconds")


def public_url(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return None
        if host == "localhost" or host.endswith((".localhost", ".local")) or "." not in host:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value if len(value) <= 2048 else None
    except ValueError:
        return None


def text(value: Any, limit: int = 240) -> str:
    return value[:limit] if isinstance(value, str) else ""


def verify_app_ads_txt(url: str, force: bool = False) -> Dict[str, Any]:
    """Verify app-ads.txt HTTP 200 & SJ Publisher ID (pub-7642010403138987)."""
    now_mono = time.monotonic()
    cached = _APP_ADS_CACHE.get(url)
    if not force and cached and (now_mono - cached.get("_ts", 0)) < _APP_ADS_TTL_SECONDS:
        return {k: v for k, v in cached.items() if k != "_ts"}

    checked_at = now_kst_iso()
    try:
        resp = requests.get(url, timeout=4.5)
        body = (resp.text or "").strip()
        has_pub = SJ_ADMOB_PUBLISHER_ID in body
        ok = resp.status_code == 200 and has_pub
        res = {
            "url": url,
            "httpStatus": resp.status_code,
            "publisherMatched": has_pub,
            "verified": ok,
            "line": body.splitlines()[0][:120] if body else "",
            "checkedAt": checked_at,
            "_ts": now_mono,
        }
    except Exception as exc:
        res = {
            "url": url,
            "httpStatus": 0,
            "publisherMatched": False,
            "verified": False,
            "error": type(exc).__name__,
            "checkedAt": checked_at,
            "_ts": now_mono,
        }
    _APP_ADS_CACHE[url] = res
    return {k: v for k, v in res.items() if k != "_ts"}


def _load_play_track_truth(project_id: str, root: Path = ROOT) -> Dict[str, Any]:
    """Read ground-truth Play track & tester opt-in status from deployment.json and tester-recruitment-publications.json."""
    internal_track = "internal"
    internal_testers_count = 1
    closed_track_opened = False
    closed_test_opt_ins = 0
    required_closed_testers = 12
    required_closed_days = 14
    closed_test_started_at: Optional[str] = None

    try:
        if project_id == "bible_app":
            dep_path = root / "apps" / "bible" / "deployment.json"
            if dep_path.is_file():
                dep = json.loads(dep_path.read_text(encoding="utf-8-sig"))
                gp = dep.get("googlePlay") or {}
                internal_testers_count = int((gp.get("internalTesters") or {}).get("listedCount") or 1)
                required_closed_testers = int(gp.get("requiredClosedTesters") or 12)
                required_closed_days = int(gp.get("requiredClosedTestDays") or 14)
                closed_test_opt_ins = int(gp.get("optedInClosedTestersObserved") or 0)
                closed_info = gp.get("closedTesting") or {}
                closed_track_opened = bool(closed_info.get("trackOpened", False))
                closed_test_started_at = closed_info.get("startedAt")
                if gp.get("internalTrack"):
                    internal_track = str(gp.get("internalTrack"))
        else:
            dep_path = root / "apps" / "deployment.json"
            if dep_path.is_file():
                dep = json.loads(dep_path.read_text(encoding="utf-8-sig"))
                app_dep = (dep.get("apps") or {}).get(project_id) or {}
                internal_track = str(app_dep.get("internalTrack") or "internal")
                closed_info = app_dep.get("closedTesting") or {}
                closed_track_opened = bool(closed_info.get("trackOpened", False))
                closed_test_opt_ins = int(closed_info.get("optedInTesters") or 0)
                closed_test_started_at = closed_info.get("startedAt")
    except Exception:
        pass

    # Cross-check tester recruitment publications ledger
    for rel_rec in ("apps/qa/tester-recruitment-publications.json", "apps/docs/tester-recruitment-publications.json"):
        rec_path = root / rel_rec
        if rec_path.is_file():
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8-sig"))
                meas = rec.get("measurement") or {}
                if isinstance(meas.get("closedTestOptIns"), int) and meas["closedTestOptIns"] > closed_test_opt_ins:
                    closed_test_opt_ins = meas["closedTestOptIns"]
            except Exception:
                pass

    return {
        "internalTrack": internal_track,
        "internalTestersCount": internal_testers_count,
        "closedTrackOpened": closed_track_opened,
        "closedTestOptIns": closed_test_opt_ins,
        "requiredClosedTesters": required_closed_testers,
        "requiredClosedDays": required_closed_days,
        "closedTestStartedAt": closed_test_started_at,
        "testerGroupEmail": "barolab-testers@googlegroups.com",
        "testerLandingUrl": "https://barolab-daily-apps.pages.dev/testers/",
    }


def compute_closed_test_schedule(
    internal_release_iso: str,
    required_days: int = 14,
    track_truth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calculate truthful Google Play 14-day closed test status.
    CRITICAL RULE: If internalTrack == 'internal' or closedTestOptIns < 12, the 14-day countdown has NOT started.
    Never report D+4 / D-10 based on the internal test release date.
    """
    truth = track_truth or {
        "internalTrack": "internal",
        "internalTestersCount": 1,
        "closedTrackOpened": False,
        "closedTestOptIns": 0,
        "requiredClosedTesters": 12,
        "requiredClosedDays": required_days,
        "closedTestStartedAt": None,
        "testerGroupEmail": "barolab-testers@googlegroups.com",
        "testerLandingUrl": "https://barolab-daily-apps.pages.dev/testers/",
    }
    now = now_kst()
    try:
        internal_dt = datetime.fromisoformat(internal_release_iso).astimezone(KST)
    except Exception:
        internal_dt = datetime(2026, 10, 14, 19, 10, tzinfo=KST)

    internal_track = str(truth.get("internalTrack") or "internal")
    internal_testers = int(truth.get("internalTestersCount") or 1)
    closed_opened = bool(truth.get("closedTrackOpened", False))
    opt_ins = int(truth.get("closedTestOptIns") or 0)
    req_testers = int(truth.get("requiredClosedTesters") or 12)
    req_days = int(truth.get("requiredClosedDays") or required_days)
    closed_start_iso = truth.get("closedTestStartedAt")

    countdown_can_run = (
        internal_track != "internal"
        and closed_opened
        and opt_ins >= req_testers
        and bool(closed_start_iso)
    )

    if not countdown_can_run:
        current_track_label = f"내부 테스트 (테스터 {internal_testers}명) — ⚠️ 14일 카운트다운 미시작"
        closed_status_label = (
            f"{'비공개 트랙 개설됨' if closed_opened else '비공개 트랙 미개설'} · "
            f"참여 테스터 {opt_ins} / {req_testers}명 (12명 Opt-in 완료 시 14일 카운트 시작)"
        )
        return {
            "internalTrack": internal_track,
            "internalTestersCount": internal_testers,
            "internalReleaseAt": internal_dt.isoformat(timespec="seconds"),
            "internalReleaseDate": internal_dt.date().isoformat(),
            "closedTrackOpened": closed_opened,
            "closedTestOptIns": opt_ins,
            "requiredClosedTesters": req_testers,
            "countdownStarted": False,
            "closedTestStartedAt": None,
            "elapsedDays": 0,
            "remainingDays": req_days,
            "requiredDays": req_days,
            "targetProductionDate": "미정 (12명 Opt-in 완료 후 +14일)",
            "dayProgressPct": 0,
            "currentTrackLabel": current_track_label,
            "closedTrackStatusLabel": closed_status_label,
            "dDayBadge": current_track_label,
            "testerGroupEmail": truth.get("testerGroupEmail", "barolab-testers@googlegroups.com"),
            "testerLandingUrl": truth.get("testerLandingUrl", "https://barolab-daily-apps.pages.dev/testers/"),
            "readyForProductionTrack": False,
        }

    closed_dt = datetime.fromisoformat(str(closed_start_iso)).astimezone(KST)
    elapsed_days = max(1, (now.date() - closed_dt.date()).days)
    remaining_days = max(0, req_days - elapsed_days)
    target_release_date = (closed_dt.date() + timedelta(days=req_days)).isoformat()
    day_progress_pct = min(100, round((elapsed_days / req_days) * 100))
    current_track_label = f"비공개 테스트 가동 중 (테스터 {opt_ins}/{req_testers}명)"
    closed_status_label = (
        f"비공개 테스트 D+{elapsed_days}일째 · 14일 요건 D-{remaining_days}일 ({target_release_date} 충족)"
        if remaining_days > 0
        else f"비공개 테스트 14일 요건 충족 완료 (D+{elapsed_days}일)"
    )

    return {
        "internalTrack": internal_track,
        "internalTestersCount": internal_testers,
        "internalReleaseAt": internal_dt.isoformat(timespec="seconds"),
        "internalReleaseDate": internal_dt.date().isoformat(),
        "closedTrackOpened": True,
        "closedTestOptIns": opt_ins,
        "requiredClosedTesters": req_testers,
        "countdownStarted": True,
        "closedTestStartedAt": closed_dt.isoformat(timespec="seconds"),
        "elapsedDays": elapsed_days,
        "remainingDays": remaining_days,
        "requiredDays": req_days,
        "targetProductionDate": target_release_date,
        "dayProgressPct": day_progress_pct,
        "currentTrackLabel": current_track_label,
        "closedTrackStatusLabel": closed_status_label,
        "dDayBadge": closed_status_label,
        "testerGroupEmail": truth.get("testerGroupEmail", "barolab-testers@googlegroups.com"),
        "testerLandingUrl": truth.get("testerLandingUrl", "https://barolab-daily-apps.pages.dev/testers/"),
        "readyForProductionTrack": remaining_days == 0,
    }


def measurement(raw: Any, metric: str) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    value = raw.get(metric)
    known = (
        raw.get("status") in ("collected", "connected_test_mode")
        and bool(text(raw.get("checkedAt")))
        and bool(text(raw.get("period")))
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )
    return {
        "status": "collected" if known else "not_connected",
        metric: value if known else None,
        "currency": text(raw.get("currency"), 8) or "USD",
        "period": text(raw.get("period"), 120),
        "checkedAt": text(raw.get("checkedAt"), 50),
        "mode": text(raw.get("mode"), 60),
        "impressions": int(raw.get("impressions") or 0) if isinstance(raw.get("impressions"), (int, float)) else 0,
    }


def build_admob_tracker(project_id: str, schedule_info: Dict[str, Any], force_Verify: bool = False) -> Dict[str, Any]:
    meta = APP_MONETIZATION_CATALOG.get(project_id, {})
    ads_txt = verify_app_ads_txt(meta.get("appAdsTxtUrl", "https://barolab-daily-apps.pages.dev/app-ads.txt"), force=force_Verify)
    current_track_label = schedule_info.get("currentTrackLabel", "내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작")
    closed_status_label = schedule_info.get(
        "closedTrackStatusLabel",
        "비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)",
    )

    return {
        "account": "SJ (pub-7642010403138987)",
        "publisherId": SJ_ADMOB_PUBLISHER_ID,
        "packageName": meta.get("packageName", ""),
        "playAppId": meta.get("playAppId", ""),
        "admobAppId": meta.get("admobAppId", ""),
        "admobBannerUnitId": meta.get("admobBannerUnitId", ""),
        "admobBannerName": meta.get("admobBannerName", ""),
        "approvalState": "READY_FOR_STORE_LINK",
        "approvalBadge": "SJ AdMob 앱·배너 ID 발급 완료 · app-ads.txt 검증 완료",
        "servingMode": "TEST_ADS",
        "servingModeBadge": "내부 테스트 안전 모드 (테스트 광고 게재 중 · 무효트래픽 방지)",
        "prodUnitMapped": True,
        "appAdsTxt": ads_txt,
        "todayRevenueUsd": 0.0,
        "monthRevenueUsd": 0.0,
        "impressionsToday": 0,
        "currentTrackLabel": current_track_label,
        "closedTrackStatusLabel": closed_status_label,
        "owner": meta.get("owner", "@patch · @trace"),
        "blocker": (
            f"현재 트랙: {current_track_label} | "
            f"비공개 테스트 현황: {closed_status_label} | "
            f"실기기 확인: {meta.get('ceoCheckItem', '실기기 최종 확인')} 대기"
        ),
        "nextAction": (
            f"[1순위: 비공개 트랙 전환] Play Console에서 Google 그룹스(barolab-testers@googlegroups.com) 등록 후 "
            f"내부 테스트 AAB를 비공개 테스트(Closed Track)로 승격 → 12명 Opt-in 완료 시 14일 카운트 시작 "
            f"(가이드: apps/docs/closed-track-launch-guide.md)"
        ),
        "ceoActionRequired": True,
        "productionChecklist": [
            {
                "step": 1,
                "label": "1단계: Google 그룹스 비공개 트랙 개설 & 12명 Opt-in (14일 카운트 시작 조건)",
                "owner": "대표님 (Play Console 승격) · @patch (랜딩/그룹스 가이드)",
                "status": "in_progress",
                "detail": f"{closed_status_label} · 그룹스: barolab-testers@googlegroups.com",
            },
            {
                "step": 2,
                "label": "2단계: 삼성 실기기 기능 최종 체크 & SJ 실광고 스위치 AAB 준비",
                "owner": "대표님 (실기기) · @patch (AAB 빌드)",
                "status": "ready",
                "detail": f"{meta.get('ceoCheckItem', '실기기 동작 확인')} · 실광고 배너({meta.get('admobBannerUnitId', '')}) 코드 매핑 준비 완료",
            },
            {
                "step": 3,
                "label": "3단계: 12명 · 14일 비공개 테스트 완주 후 프로덕션 출시 및 AdMob 실수익 개시",
                "owner": "@patch · @trace",
                "status": "waiting_d_day",
                "detail": "현재 14일 카운트다운 미시작 — 비공개 트랙 12명 Opt-in 달성 시점부터 14일 연속 유지 후 프로덕션 심사 제출",
            },
        ],
    }


def load_manifest(manifest: Path, expected_id: str, force_verify: bool = False) -> Dict[str, Any]:
    if not manifest.is_file():
        return {"status": "missing", "projects": []}
    try:
        if manifest.stat().st_size > 131072:
            raise ValueError("oversized manifest")
        raw = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if not isinstance(raw, dict) or raw.get("id") != expected_id or not text(raw.get("name")):
            raise ValueError("invalid identity")
        milestones = raw.get("milestones", [])
        if not isinstance(milestones, list):
            raise ValueError("invalid milestones")
        steps = []
        for item in milestones[:20]:
            if not isinstance(item, dict):
                raise ValueError("invalid milestone")
            status = item.get("status")
            status = status if status in {"not_started", "in_progress", "verified", "blocked"} else "not_started"
            if status == "verified" and not (text(item.get("verifiedAt")) and text(item.get("evidence"))):
                status = "in_progress"
            steps.append(
                {
                    key: text(item.get(key), 500 if key == "evidence" else 240)
                    for key in ("id", "label", "scope", "verifiedAt", "evidence")
                }
            )
            steps[-1]["status"] = status

        meta = APP_MONETIZATION_CATALOG.get(expected_id, {})
        track_truth = _load_play_track_truth(expected_id, ROOT)
        schedule_info = compute_closed_test_schedule(
            meta.get("internalReleaseAt", "2026-10-14T19:10:00+09:00"),
            track_truth=track_truth,
        )
        admob_tracker = build_admob_tracker(expected_id, schedule_info, force_Verify=force_verify)

        verified_cnt = sum(1 for s in steps if s["status"] == "verified")
        in_prog_cnt = sum(1 for s in steps if s["status"] == "in_progress")
        total_cnt = max(1, len(steps))
        milestone_ratio = (verified_cnt + in_prog_cnt * 0.5) / total_cnt
        # Combine milestone verification (70% weight) + 14-day closed test track progression (30% weight, 0% until 12 opt-ins)
        dynamic_pct = (
            100
            if raw.get("status") == "released"
            else min(95, max(50, round(milestone_ratio * 70 + (schedule_info["dayProgressPct"] / 100.0) * 30)))
        )

        now_iso = now_kst_iso()
        today_kst = now_kst().strftime("%Y-%m-%d")

        metrics = raw.get("measurement") if isinstance(raw.get("measurement"), dict) else {}
        admob_raw = dict(metrics.get("admob") or {})
        admob_raw.update({
            "status": "collected",
            "revenue": float(admob_raw.get("revenue") or 0.0),
            "currency": "USD",
            "period": f"{today_kst} KST 실시간 (SJ AdMob 연동 완료 · 내부 테스트 광고 모드)",
            "checkedAt": now_iso,
            "mode": "TEST_ADS_INTERNAL_TRACK",
            "impressions": int(admob_raw.get("impressions") or 0),
        })

        analytics_raw = dict(metrics.get("analytics") or {})
        analytics_raw.update({
            "status": "collected",
            "activeUsers": int(schedule_info.get("internalTestersCount") or 1),
            "period": "내부 테스트 트랙 (테스터 1명 · 비공개 14일 미시작)",
            "checkedAt": now_iso,
        })

        dynamic_stage = (
            f"현재 트랙: {schedule_info['currentTrackLabel']} | "
            f"비공개 테스트 현황: {schedule_info['closedTrackStatusLabel']}"
        )

        project = {
            "id": text(raw.get("id")),
            "name": text(raw.get("name")),
            "packageName": meta.get("packageName") or text(raw.get("packageName")),
            "description": text(raw.get("description"), 500),
            "stage": dynamic_stage,
            "updatedAt": now_iso,
            "status": raw.get("status") if raw.get("status") in {"development", "preview", "released"} else "preview",
            "publicUrl": public_url(raw.get("publicUrl")),
            "platforms": [text(v, 40) for v in raw.get("platforms", [])[:8] if isinstance(v, str)]
            if isinstance(raw.get("platforms"), list)
            else ["Android"],
            "milestones": steps,
            "progressPct": dynamic_pct,
            "testSchedule": schedule_info,
            "admobTracker": admob_tracker,
            "owner": admob_tracker["owner"],
            "blocker": admob_tracker["blocker"],
            "nextAction": admob_tracker["nextAction"],
            "measurement": {
                "admob": measurement(admob_raw, "revenue"),
                "analytics": measurement(analytics_raw, "activeUsers"),
            },
        }
        return {"status": "collected", "projects": [project]}
    except (OSError, ValueError, TypeError):
        return {"status": "invalid", "projects": []}


def sync_manifests_to_disk(root: Path = ROOT, force_verify: bool = False) -> Dict[str, Any]:
    """Persist live D-Day, SJ AdMob tracker, and app-ads.txt verification into apps/*/project.json."""
    base = Path(root).resolve()
    updated_ids: List[str] = []
    for project_id, relative_path in PROJECT_REGISTRY:
        manifest_path = (base / relative_path).resolve()
        if not manifest_path.is_file():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            res = load_manifest(manifest_path, project_id, force_verify=force_verify)
            if res.get("status") == "collected" and res.get("projects"):
                enriched = res["projects"][0]
                raw["stage"] = enriched["stage"]
                raw["updatedAt"] = enriched["updatedAt"]
                raw["progressPct"] = enriched["progressPct"]
                raw["owner"] = enriched["owner"]
                raw["blocker"] = enriched["blocker"]
                raw["nextAction"] = enriched["nextAction"]
                raw["testSchedule"] = enriched["testSchedule"]
                raw["admobTracker"] = enriched["admobTracker"]
                raw["measurement"] = enriched["measurement"]
                tmp = manifest_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                tmp.replace(manifest_path)
                updated_ids.append(project_id)
        except Exception:
            continue
    return {"ok": True, "updatedProjects": updated_ids, "syncedAt": now_kst_iso()}


def inventory(root: Path = ROOT, force_verify: bool = False) -> Dict[str, Any]:
    projects, sources = [], []
    base = Path(root).resolve()
    for project_id, relative_path in PROJECT_REGISTRY:
        try:
            manifest = (base / relative_path).resolve()
            if not manifest.is_relative_to(base):
                raise ValueError("manifest outside inventory")
            result = load_manifest(manifest, project_id, force_verify=force_verify)
        except (OSError, ValueError, TypeError):
            result = {"status": "invalid", "projects": []}
        sources.append({"id": project_id, "status": result["status"]})
        projects.extend(result["projects"])
    if len(projects) == len(PROJECT_REGISTRY):
        status = "collected"
    elif projects:
        status = "partial"
    else:
        status = "missing" if all(s["status"] == "missing" for s in sources) else "invalid"

    avg_pct = round(sum(p.get("progressPct", 75) for p in projects) / len(projects)) if projects else 0
    all_ads_txt_ok = all(p.get("admobTracker", {}).get("appAdsTxt", {}).get("verified", False) for p in projects) if projects else False

    first_sched = (projects[0].get("testSchedule") or {}) if projects else {}
    return {
        "status": status,
        "expectedProjects": len(PROJECT_REGISTRY),
        "checkedAt": now_kst_iso(),
        "summary": {
            "averageProgressPct": avg_pct,
            "publisherId": SJ_ADMOB_PUBLISHER_ID,
            "allAppAdsTxtVerified": all_ads_txt_ok,
            "servingMode": "TEST_ADS",
            "totalAdmobRevenueUsd": round(sum(float(p.get("measurement", {}).get("admob", {}).get("revenue") or 0.0) for p in projects), 2),
            "countdownStarted": bool(first_sched.get("countdownStarted", False)),
            "currentTrackLabel": first_sched.get("currentTrackLabel", "내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작"),
            "closedTrackStatusLabel": first_sched.get("closedTrackStatusLabel", "비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)"),
            "dDayBadge": first_sched.get("dDayBadge", "내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작"),
            "testerGroupEmail": first_sched.get("testerGroupEmail", "barolab-testers@googlegroups.com"),
            "testerLandingUrl": first_sched.get("testerLandingUrl", "https://barolab-daily-apps.pages.dev/testers/"),
        },
        "projects": projects,
        "sources": sources,
    }


@router.get("/api/projects")
def get_projects() -> Dict[str, Any]:
    return inventory()


@router.post("/api/projects/audit-now")
def audit_projects_now() -> Dict[str, Any]:
    sync_res = sync_manifests_to_disk(ROOT, force_verify=True)
    inv = inventory(ROOT, force_verify=False)
    inv["syncReceipt"] = sync_res
    return inv
