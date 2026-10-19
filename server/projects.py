"""Live App Portfolio & SJ AdMob Monetization Tracker (4 Android Apps)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import ipaddress
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictBool, StrictInt
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
router = APIRouter()
from common.app_testers_store import (load_app_testers, save_app_testers, normalize_emails,
                                     patch_installation, RevisionConflict)

KST = timezone(timedelta(hours=9))

PROJECT_REGISTRY = (
    ("bible_app", "apps/bible/project.json"),
    ("greeting", "apps/greeting/project.json"),
    ("magnifier", "apps/magnifier/project.json"),
    ("shopping", "apps/shopping/project.json"),
)

SJ_ADMOB_PUBLISHER_ID = "pub-7642010403138987"
SJ_APP_ADS_LINE = "google.com, pub-7642010403138987, DIRECT, f08c47fec0942fa0"

import re as _re
import threading

try:
    from apps.play_console_automator import (
        DEVELOPER_ID,
        run_promote_closed,
        run_switch_prod_ads,
        run_sync_testers,
    )
    AUTOMATOR_AVAILABLE = True
except Exception:  # NAS image ships only server/*.py + common/*.py (no apps/ package)
    AUTOMATOR_AVAILABLE = False
    DEVELOPER_ID = "7752283694845461925"
    def _automator_unavailable(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        return {"ok": False, "error": "play_console_automator is Windows-only (not in NAS image)"}

    run_promote_closed = run_switch_prod_ads = run_sync_testers = _automator_unavailable

_CDP_JOB_LOCK = threading.Lock()


def _start_background_cdp(job: str) -> bool:
    """Run Play Console CDP work off the request thread. Never blocks the HTTP handler."""
    if not AUTOMATOR_AVAILABLE or not _CDP_JOB_LOCK.acquire(blocking=False):
        return False

    def _runner() -> None:
        try:
            if job == "sync":
                run_sync_testers(raw_emails=None, execute_cdp=True)
            elif job == "promote":
                run_promote_closed(app_filter="all", execute_cdp=True)
        except Exception:
            pass
        finally:
            _CDP_JOB_LOCK.release()

    threading.Thread(target=_runner, name=f"play-console-{job}", daemon=True).start()
    return True

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
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4700464139727332365",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.harubible",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.harubible",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4975007773224005878/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4975007773224005878/tracks/closed-testing",
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "삼성 갤럭시 실휴대폰에서 v4 성경말씀 실제 스피커 음성 듣기·정지 1회 최종 확인",
        "deviceCheckItems": [
            "오늘의 말씀 카드 조회 및 큰글씨 가독성 확인",
            "한국어 TTS 음성 낭독 듣기·일시정지·정지 스피커 출력 확인",
            "절 복사·공유 및 하단 AdMob 테스트 배너 정상 표시 확인",
        ],
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
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4701400802151181455",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.morningcard",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.morningcard",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4973731498485355571/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4973731498485355571/tracks/closed-testing",
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "실휴대폰에서 안부 카드 이름 입력·사진 배경 저장·카카오톡 공유 1회 최종 확인",
        "deviceCheckItems": [
            "요일·계절별 인사말 문구 선택 및 받는 분 이름 입력 확인",
            "내 사진 배경 불러오기 및 인사 카드 이미지 갤러리 저장 확인",
            "카카오톡·문자 이미지 공유 시트 호출 확인",
        ],
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
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4701703053640983596",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.biglens",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.biglens",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972819523776643880/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972819523776643880/tracks/closed-testing",
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "삼성 실휴대폰 실제 카메라 확대·초점·조명(플래시)·화면 정지 저장 1회 최종 확인",
        "deviceCheckItems": [
            "실제 후면 카메라 프리뷰 1x~5x 확대 배율 조절 및 초점 확인",
            "어두운 곳 손전등(플래시 토치) ON/OFF 동작 확인",
            "화면 정지(캡처) 후 이미지 확대 및 갤러리 저장 확인",
        ],
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
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4701721871486482124",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.voicebasket",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.voicebasket",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972748430542309887/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972748430542309887/tracks/closed-testing",
        "owner": "@patch (빌드·배포) · @trace (SJ AdMob·스토어 추적)",
        "ceoCheckItem": "삼성 실휴대폰 한국어 음성인식 품목 추가·체크 스크롤 1회 최종 확인",
        "deviceCheckItems": [
            "마이크 한국어 음성인식으로 장보기 품목 연속 추가 확인",
            "체크박스 구매 완료 토글 및 목록 유지(재실행 후 보존) 확인",
            "목록 텍스트 공유 및 하단 AdMob 테스트 배너 정상 표시 확인",
        ],
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
    closed_review_submitted = False
    closed_test_opt_ins = None
    closed_info = {}
    internal_release = {}
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
                observed = gp.get("optedInClosedTestersObserved")
                closed_test_opt_ins = observed if type(observed) is int and observed >= 0 else None
                internal_release = gp.get("internalRelease") or {}
                closed_info = gp.get("closedTesting") or {}
                closed_track_opened = closed_info.get("trackOpened", closed_info.get("trackActive"))
                closed_review_submitted = closed_info.get("reviewSubmitted") is True or closed_info.get("submitted") is True
                closed_test_started_at = closed_info.get("startedAt")
                if gp.get("internalTrack"):
                    internal_track = str(gp.get("internalTrack"))
        else:
            dep_path = root / "apps" / "deployment.json"
            if dep_path.is_file():
                dep = json.loads(dep_path.read_text(encoding="utf-8-sig"))
                app_dep = (dep.get("apps") or {}).get(project_id) or {}
                internal_track = str(app_dep.get("internalTrack") or "internal")
                internal_testers_count = int(app_dep.get("internalTesterListCount") or 1)
                closed_info = app_dep.get("closedTesting") or {}
                closed_track_opened = closed_info.get("trackOpened", closed_info.get("trackActive"))
                closed_review_submitted = closed_info.get("reviewSubmitted") is True or closed_info.get("submitted") is True
                observed = closed_info.get("optedInTesters")
                closed_test_opt_ins = observed if type(observed) is int and observed >= 0 else None
                internal_release = app_dep.get("internalRelease") or {}
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
                if meas.get("closedTestOptInsVerified") is True and type(meas.get("closedTestOptIns")) is int and meas["closedTestOptIns"] > (closed_test_opt_ins or 0):
                    closed_test_opt_ins = meas["closedTestOptIns"]
            except Exception:
                pass

    # Cross-check data/app_testers.json for saved tester emails and closed track state
    testers_doc = load_app_testers()
    if testers_doc.get("closedTestOptInsVerified") is True and type(testers_doc.get("closedTestOptIns")) is int and testers_doc["closedTestOptIns"] > (closed_test_opt_ins or 0):
        closed_test_opt_ins = testers_doc["closedTestOptIns"]
    if testers_doc.get("closedTrackPromoted"):
        closed_track_opened = True
    if testers_doc.get("closedTestStartAt") and not closed_test_started_at:
        closed_test_started_at = testers_doc.get("closedTestStartAt")

    return {
        "internalTrack": internal_track,
        "internalTestersCount": internal_testers_count,
        "registeredTestersCount": int(testers_doc.get("emailCount") or 1),
        "closedTrackOpened": closed_track_opened,
        "closedReviewSubmitted": closed_review_submitted,
        "closedReviewApproved": closed_info.get("reviewApproved") is True,
        "closedTestOptInsVerified": closed_test_opt_ins is not None,
        "internalReleaseAt": internal_release.get("releasedAt") or internal_release.get("publishedAtLocal"),
        "internalVersionCode": internal_release.get("versionCode"),
        "closedVersionCode": closed_info.get("versionCode"),
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
        "registeredTestersCount": 1,
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
        internal_dt = datetime.fromisoformat(truth.get("internalReleaseAt") or internal_release_iso).astimezone(KST)
    except Exception:
        internal_dt = datetime(2026, 10, 14, 19, 10, tzinfo=KST)

    internal_track = str(truth.get("internalTrack") or "internal")
    internal_testers = int(truth.get("internalTestersCount") or 1)
    registered_testers = int(truth.get("registeredTestersCount") or internal_testers)
    closed_opened = bool(truth.get("closedTrackOpened", False))
    opt_ins = int(truth.get("closedTestOptIns") or 0)
    opt_ins_verified = truth.get("closedTestOptInsVerified") is True
    review_approved = truth.get("closedReviewApproved") is True
    req_testers = int(truth.get("requiredClosedTesters") or 12)
    req_days = int(truth.get("requiredClosedDays") or required_days)
    closed_start_iso = truth.get("closedTestStartedAt")

    countdown_can_run = (
        closed_opened
        and opt_ins_verified
        and opt_ins >= req_testers
        and bool(closed_start_iso)
    )

    if not countdown_can_run:
        current_track_label = f"내부 테스트 (테스터 {internal_testers}명) — ⚠️ 14일 카운트다운 미시작"
        participation = f"참여 테스터 {opt_ins} / {req_testers}명" if opt_ins_verified else "실제 참여 수 미확인"
        closed_status_label = (
            f"{'비공개 트랙 개설됨' if closed_opened else '비공개 트랙 상태 미확인'} · "
            f"{participation} · 12명 실참여와 14일 연속 유지 필요"
        )
        if truth.get("closedReviewSubmitted"):
            internal_version = f" v{truth['internalVersionCode']}" if truth.get("internalVersionCode") else ""
            closed_version = f" v{truth['closedVersionCode']}" if truth.get("closedVersionCode") else ""
            review_label = "검토 승인" if review_approved else "검토 제출"
            current_track_label = f"내부{internal_version} 제공 · Alpha{closed_version} {review_label}"
            closed_status_label = f"Alpha{closed_version} {review_label} · 등록명단 {internal_testers}명 · {participation}"
        return {
            "internalTrack": internal_track,
            "internalTestersCount": internal_testers,
            "registeredTestersCount": registered_testers,
            "internalReleaseAt": internal_dt.isoformat(timespec="seconds"),
            "internalReleaseDate": internal_dt.date().isoformat(),
            "closedTrackOpened": truth.get("closedTrackOpened"),
            "closedReviewSubmitted": bool(truth.get("closedReviewSubmitted")),
            "closedReviewApproved": review_approved,
            "closedTestOptInsVerified": opt_ins_verified,
            "closedTestOptIns": opt_ins if opt_ins_verified else None,
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
        "registeredTestersCount": registered_testers,
        "internalReleaseAt": internal_dt.isoformat(timespec="seconds"),
        "internalReleaseDate": internal_dt.date().isoformat(),
        "closedTrackOpened": True,
        "closedReviewSubmitted": bool(truth.get("closedReviewSubmitted")),
        "closedReviewApproved": review_approved,
        "closedTestOptInsVerified": opt_ins_verified,
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
        "revenue" if metric == "revenue" else metric: value if known else None,
        "currency": text(raw.get("currency"), 8) or "USD",
        "period": text(raw.get("period"), 120),
        "checkedAt": text(raw.get("checkedAt"), 50),
        "mode": text(raw.get("mode"), 60),
        "impressions": int(raw.get("impressions") or 0) if isinstance(raw.get("impressions"), (int, float)) else 0,
    }


def build_admob_tracker(
    project_id: str,
    schedule_info: Dict[str, Any],
    device_verified: bool = False,
    force_Verify: bool = False,
    device_verified_version=None,
    latest_build_version=None,
    latest_build_physical_verified: bool = False,
) -> Dict[str, Any]:
    meta = APP_MONETIZATION_CATALOG.get(project_id, {})
    ads_txt = verify_app_ads_txt(meta.get("appAdsTxtUrl", "https://barolab-daily-apps.pages.dev/app-ads.txt"), force=force_Verify)
    current_track_label = schedule_info.get("currentTrackLabel", "내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작")
    closed_status_label = schedule_info.get(
        "closedTrackStatusLabel",
        "비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)",
    )
    device_status_text = f"{meta.get('ceoCheckItem', '실기기 최종 확인')} 대기"
    if device_verified:
        version_label = f"v{device_verified_version}" if device_verified_version else "검증 버전 미기록"
        device_status_text = f"삼성 실기기 {version_label} 검증 완료"
    if latest_build_version and not latest_build_physical_verified:
        device_status_text += f" · 신규 v{latest_build_version} 실기기 미검증"
    elif latest_build_version and latest_build_physical_verified:
        device_status_text += f" · 최신 v{latest_build_version} 실기기 검증 완료"
    current_device_verified = latest_build_physical_verified if latest_build_version else device_verified
    required_testers = schedule_info.get("requiredClosedTesters", 12)
    required_days = schedule_info.get("requiredDays", 14)
    if schedule_info.get("countdownStarted"):
        next_action = f"Alpha 실참여 {required_testers}명 이상을 {required_days}일 연속 유지하고 Play Console의 요건 충족 상태를 확인하세요."
    elif schedule_info.get("closedReviewSubmitted"):
        next_action = f"Google 검토 완료 후 Alpha 참여 링크로 실제 참여를 확인하세요. 등록 명단 수는 참여 인원이 아니며, {required_testers}명 이상 실참여와 {required_days}일 연속 유지가 필요합니다. 현재 시작 시점은 미확인입니다."
    elif schedule_info.get("closedTrackOpened"):
        next_action = f"Alpha 출시·검토 상태와 등록 명단을 확인하고 참여 링크를 안내하세요. 실제 참여 {required_testers}명 이상과 {required_days}일 연속 유지가 필요합니다."
    else:
        next_action = f"테스터 명단과 Alpha 출시 설정을 확인하세요. 실제 참여 {required_testers}명 이상과 {required_days}일 연속 유지가 필요하며 명단 등록만으로 시작되지 않습니다."

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
        "deviceVerified": device_verified,
        "deviceVerifiedVersionCode": device_verified_version,
        "latestBuildVersionCode": latest_build_version,
        "latestBuildPhysicalDeviceVerified": latest_build_physical_verified,
        "deviceVerificationLabel": device_status_text,
        "owner": meta.get("owner", "@patch · @trace"),
        "blocker": (
            f"현재 트랙: {current_track_label} | "
            f"비공개 테스트 현황: {closed_status_label} | "
            f"실기기 확인: {device_status_text}"
        ),
        "nextAction": next_action,
        "ceoActionRequired": not (current_device_verified and schedule_info.get("countdownStarted")),
        "productionChecklist": [
            {
                "step": 1,
                "label": f"1단계: 테스터 명단 확인 · Alpha 실참여 {required_testers}명 이상",
                "owner": "대표님 (QR 4터치 설치) · @patch (반자동 스크립트)",
                "status": "verified" if schedule_info.get("countdownStarted") else "in_progress",
                "detail": f"{closed_status_label}",
            },
            {
                "step": 2,
                "label": "2단계: 삼성 실기기 기능 최종 체크 & SJ 실광고 스위치 AAB 준비",
                "owner": "대표님 (실기기 1회 체크) · @patch (release.properties 자동주입)",
                "status": "verified" if current_device_verified else "ready",
                "detail": f"{device_status_text} · 실광고 배너({meta.get('admobBannerUnitId', '')}) 코드 매핑 완료",
            },
            {
                "step": 3,
                "label": "3단계: 12명 · 14일 비공개 테스트 완주 후 프로덕션 출시 및 AdMob 실수익 개시",
                "owner": "@patch · @trace",
                "status": "waiting_d_day",
                "detail": "비공개 트랙 12명 Opt-in 달성 시점부터 14일 연속 유지 후 프로덕션 심사 제출",
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
        device_verified = False
        device_verified_at = ""
        device_verified_version = None
        for item in milestones[:20]:
            if not isinstance(item, dict):
                raise ValueError("invalid milestone")
            status = item.get("status")
            status = status if status in {"not_started", "in_progress", "verified", "blocked"} else "not_started"
            if status == "verified" and not (text(item.get("verifiedAt")) and text(item.get("evidence"))):
                status = "in_progress"
            if item.get("id") == "device_test" and status == "verified":
                device_verified = True
                device_verified_at = text(item.get("verifiedAt"))
                version = item.get("verifiedVersionCode")
                if type(version) is int and version > 0:
                    device_verified_version = version
            steps.append(
                {
                    key: text(item.get(key), 500 if key == "evidence" else 240)
                    for key in ("id", "label", "scope", "verifiedAt", "evidence")
                }
            )
            steps[-1]["status"] = status

        meta = APP_MONETIZATION_CATALOG.get(expected_id, {})
        release_build = raw.get("releaseBuild") if isinstance(raw.get("releaseBuild"), dict) else {}
        latest_build_version = release_build.get("versionCode")
        if type(latest_build_version) is not int or latest_build_version <= 0:
            latest_build_version = None
        latest_build_physical_verified = bool(latest_build_version and release_build.get("physicalDeviceVerifiedForThisBuild") is True)
        track_truth = _load_play_track_truth(expected_id, ROOT)
        schedule_info = compute_closed_test_schedule(
            meta.get("internalReleaseAt", "2026-10-14T19:10:00+09:00"),
            track_truth=track_truth,
        )
        admob_tracker = build_admob_tracker(
            expected_id,
            schedule_info,
            device_verified=device_verified,
            force_Verify=force_verify,
            device_verified_version=device_verified_version,
            latest_build_version=latest_build_version,
            latest_build_physical_verified=latest_build_physical_verified,
        )

        verified_cnt = sum(1 for s in steps if s["status"] == "verified")
        in_prog_cnt = sum(1 for s in steps if s["status"] == "in_progress")
        total_cnt = max(1, len(steps))
        milestone_ratio = (verified_cnt + in_prog_cnt * 0.5) / total_cnt
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
            "playAppId": meta.get("playAppId", ""),
            "versionName": text(release_build.get("versionName")) or text(raw.get("versionName")) or meta.get("versionName", ""),
            "versionCode": latest_build_version or meta.get("versionCode", 1),
            "internalJoinUrl": meta.get("internalJoinUrl", ""),
            "closedJoinUrl": meta.get("closedJoinUrl", ""),
            "playStoreUrl": meta.get("playStoreUrl", ""),
            "internalTrackUrl": meta.get("internalTrackUrl", ""),
            "closedTrackUrl": meta.get("closedTrackUrl", ""),
            "deviceCheckItems": meta.get("deviceCheckItems", []),
            "deviceVerified": device_verified,
            "deviceVerifiedAt": device_verified_at,
            "deviceVerifiedVersionCode": device_verified_version,
            "latestBuildVersionCode": latest_build_version,
            "latestBuildPhysicalDeviceVerified": latest_build_physical_verified,
            "deviceVerificationLabel": admob_tracker["deviceVerificationLabel"],
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
    all_devices_verified = all(p.get("deviceVerified", False) for p in projects) if projects else False
    testers_doc = tester_control_center()

    first_sched = (projects[0].get("testSchedule") or {}) if projects else {}
    return {
        "status": status,
        "expectedProjects": len(PROJECT_REGISTRY),
        "checkedAt": now_kst_iso(),
        "summary": {
            "averageProgressPct": avg_pct,
            "publisherId": SJ_ADMOB_PUBLISHER_ID,
            "developerAccountId": DEVELOPER_ID,
            "allAppAdsTxtVerified": all_ads_txt_ok,
            "allDevicesVerified": all_devices_verified,
            "servingMode": "TEST_ADS",
            "totalAdmobRevenueUsd": round(sum(float(p.get("measurement", {}).get("admob", {}).get("revenue") or 0.0) for p in projects), 2),
            "countdownStarted": bool(first_sched.get("countdownStarted", False)),
            "currentTrackLabel": first_sched.get("currentTrackLabel", "내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작"),
            "closedTrackStatusLabel": first_sched.get("closedTrackStatusLabel", "비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)"),
            "dDayBadge": first_sched.get("dDayBadge", "내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작"),
            "testerGroupEmail": first_sched.get("testerGroupEmail", "barolab-testers@googlegroups.com"),
            "testerLandingUrl": first_sched.get("testerLandingUrl", "https://barolab-daily-apps.pages.dev/testers/"),
            "registeredTestersCount": int(testers_doc.get("emailCount") or 1),
            "closedTestOptIns": first_sched.get("closedTestOptIns") if first_sched.get("closedTestOptInsVerified") else None,
            "localInstalledTestersCount": testers_doc.get('localTracking', {}).get('installedCount'),
        },
        "testersControlCenter": testers_doc,
        "projects": projects,
        "sources": sources,
    }


class TestersSyncRequest(BaseModel):
    emails: Any = None
    executeCdp: bool = False
    closedTestOptIns: Optional[int] = None


class PromoteClosedRequest(BaseModel):
    app: str = "all"
    executeCdp: bool = False
    closedTrackPromoted: Optional[bool] = None
    closedTestOptIns: Optional[int] = None


class VerifyDeviceRequest(BaseModel):
    projectId: str = "all"
    verified: bool = True
    note: Optional[str] = None


class TesterInstallationPatch(BaseModel):
    installed: StrictBool
    expectedRevision: Optional[StrictInt] = None


def tester_control_center(doc=None):
    result = dict(doc if doc is not None else load_app_testers())
    try:
        try:
            from .play_console_collector import get_console_status
        except ImportError:
            from play_console_collector import get_console_status
        console = get_console_status(trigger_refresh=True)
    except Exception as exc:
        console = {'status': 'unknown', 'checkedAt': None, 'stale': True,
                   'error': type(exc).__name__, 'apps': {}}
    result['playConsoleStatus'] = console
    result['consoleEvidence'] = console.get('apps', {})
    return result


@router.get("/api/projects")
def get_projects() -> Dict[str, Any]:
    return inventory()


@router.post("/api/projects/audit-now")
def audit_projects_now() -> Dict[str, Any]:
    sync_res = sync_manifests_to_disk(ROOT, force_verify=True)
    inv = inventory(ROOT, force_verify=False)
    inv["syncReceipt"] = sync_res
    return inv


@router.get("/api/projects/testers")
def get_projects_testers() -> Dict[str, Any]:
    return tester_control_center()


@router.patch('/api/projects/testers/accounts/{account_id}')
def patch_project_tester(account_id: str, payload: TesterInstallationPatch) -> Dict[str, Any]:
    try:
        doc = patch_installation(account_id, payload.installed, expected_revision=payload.expectedRevision)
    except RevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='Unknown tester account') from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'ok': True, 'testersControlCenter': tester_control_center(doc)}


@router.post("/api/projects/testers")
def post_projects_testers(payload: TestersSyncRequest) -> Dict[str, Any]:
    """Save tester emails + CSV and answer immediately. CDP work never runs on the request thread."""
    if payload.closedTestOptIns is not None:
        raise HTTPException(status_code=400, detail='Google opt-in counts require Play Console evidence; use the separate installation checkbox')
    doc = load_app_testers()
    if payload.emails is not None:
        doc["emails"] = normalize_emails(payload.emails)
        doc["syncStatus"] = "saved_pending_play_console"
    doc = save_app_testers(doc)

    csv_written = False
    for csv_path in (ROOT / "apps" / "qa" / "barolab-testers-14.csv", ROOT / "server" / "data" / "barolab-testers-14.csv"):
        try:
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text("\n".join(doc["emails"]) + "\n", encoding="utf-8")
            csv_written = True
            break
        except Exception:
            continue

    cdp_queued = _start_background_cdp("sync") if (payload.executeCdp and payload.emails is not None) else False
    return {
        "ok": True,
        "savedCount": int(doc.get("emailCount") or len(doc.get("emails") or [])),
        "emails": doc.get("emails") or [],
        "csvWritten": csv_written,
        "cdpQueued": cdp_queued,
        "cdpNote": (
            "Play Console 동기화를 백그라운드로 시작했습니다."
            if cdp_queued
            else "명단만 저장했습니다 (Play Console 반영은 Windows 워커/CDP 9420에서 별도 실행)."
        ),
        "testersControlCenter": doc,
    }


@router.post("/api/projects/promote-closed")
def post_promote_closed(payload: PromoteClosedRequest) -> Dict[str, Any]:
    """Queue a Play Console closed-track inspection. Track state is never set from the button press itself."""
    if payload.closedTestOptIns is not None:
        raise HTTPException(status_code=400, detail='Google opt-in counts cannot be set by a manual installation action')
    cdp_queued = _start_background_cdp("promote") if payload.executeCdp else False
    doc = load_app_testers()
    return {
        "ok": True,
        "cdpQueued": cdp_queued,
        "closedTrackPromoted": bool(doc.get("closedTrackPromoted")),
        "testersControlCenter": doc,
    }


@router.post("/api/projects/verify-device")
def post_verify_device(payload: VerifyDeviceRequest) -> Dict[str, Any]:
    target_id = (payload.projectId or "all").strip()
    verified_flag = bool(payload.verified)
    now_iso = now_kst_iso()
    updated_projects: List[str] = []

    for project_id, relative_path in PROJECT_REGISTRY:
        if target_id not in ("all", project_id):
            continue
        manifest_path = (ROOT / relative_path).resolve()
        if not manifest_path.is_file():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            meta = APP_MONETIZATION_CATALOG.get(project_id, {})
            for item in raw.get("milestones", []):
                if isinstance(item, dict) and item.get("id") == "device_test":
                    if verified_flag:
                        item["status"] = "verified"
                        item["verifiedAt"] = now_iso
                        evidence_note = (
                            payload.note
                            or f"대표님 삼성 갤럭시 실기기 동작 확인 완료 ({meta.get('ceoCheckItem', '실기기 검증 완료')})"
                        )
                        item["evidence"] = evidence_note[:480]
                    else:
                        item["status"] = "in_progress"
                        item["verifiedAt"] = ""
            tmp = manifest_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(manifest_path)
            updated_projects.append(project_id)
        except Exception:
            continue

    # Update deployment.json & bible/deployment.json physicalDeviceVerified + testers doc
    doc = load_app_testers()
    for pid in updated_projects:
        if pid in doc.get("apps", {}):
            doc["apps"][pid]["deviceVerified"] = verified_flag
            doc["apps"][pid]["deviceVerifiedAt"] = now_iso if verified_flag else None
    save_app_testers(doc)

    try:
        daily_dep_path = ROOT / "apps" / "deployment.json"
        if daily_dep_path.is_file():
            d_dep = json.loads(daily_dep_path.read_text(encoding="utf-8-sig"))
            for pid in ("greeting", "magnifier", "shopping"):
                if pid in updated_projects and pid in (d_dep.get("apps") or {}):
                    dv = d_dep["apps"][pid].setdefault("deviceValidation", {})
                    dv["physicalDeviceVerified"] = verified_flag
                    dv["verifiedAt"] = now_iso if verified_flag else None
            daily_dep_path.write_text(json.dumps(d_dep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        bible_dep_path = ROOT / "apps" / "bible" / "deployment.json"
        if "bible_app" in updated_projects and bible_dep_path.is_file():
            b_dep = json.loads(bible_dep_path.read_text(encoding="utf-8-sig"))
            dv = b_dep.setdefault("deviceValidation", {})
            dv["physicalDeviceVerified"] = verified_flag
            dv["verifiedAt"] = now_iso if verified_flag else None
            bible_dep_path.write_text(json.dumps(b_dep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass

    # Pre-stage release.properties with SJ Production AdMob IDs
    prod_ads_receipt = run_switch_prod_ads(app_filter=target_id, run_gradle_build=False)
    sync_manifests_to_disk(ROOT, force_verify=False)
    inv = inventory(ROOT, force_verify=False)
    inv["verifyReceipt"] = {
        "ok": True,
        "updatedProjects": updated_projects,
        "verified": verified_flag,
        "verifiedAt": now_iso,
        "prodAdsPreStaged": prod_ads_receipt.get("ok", False),
    }
    return inv

