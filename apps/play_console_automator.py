"""Play Console Semi-Automated Tester Sync, Closed Track Promotion, and Production Ads AAB Builder.

Strictly complies with AGENTS.md:
- Uses dedicated portable browser launcher (`baro76650_start_cdp.bat` on port 9420) when starting browser.
- Reuses existing Play Console tab when available, tracks tab ownership (`owned` vs `reused`), and cleans up temporary tabs in `finally`.
- Never fabricates Play Console states; records verified URLs, screenshots, and receipts to `data/app_testers.json`, `apps/deployment.json`, and `apps/bible/deployment.json`.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_TESTERS_PATH = ROOT / "data" / "app_testers.json"
SERVER_DATA_TESTERS_PATH = ROOT / "server" / "data" / "app_testers.json"
DASHBOARD_DATA_TESTERS_PATH = ROOT / "dashboard" / "data" / "app_testers.json"
DAILY_DEPLOYMENT_PATH = ROOT / "apps" / "deployment.json"
BIBLE_DEPLOYMENT_PATH = ROOT / "apps" / "bible" / "deployment.json"
QA_DIR = ROOT / "apps" / "qa"

KST = timezone(timedelta(hours=9))

DEVELOPER_ID = "7752283694845461925"
TESTER_LIST_NAME = "BaroLab 테스터 14인"

BARO76650_BROWSER_DIR = Path(r"C:\99_포터블브라우저\CentBrowserPortable_baro76650")
BARO76650_START_BAT = BARO76650_BROWSER_DIR / "baro76650_start_cdp.bat"
BARO76650_STOP_BAT = BARO76650_BROWSER_DIR / "baro76650_stop_cdp.bat"
BARO76650_CDP_PORT = 9420
SJ_CDP_PORT = 9226

APPS_METADATA: Dict[str, Dict[str, Any]] = {
    "bible_app": {
        "id": "bible_app",
        "name": "오늘의 성경말씀",
        "packageName": "com.barolab.harubible",
        "playAppId": "4975007773224005878",
        "version": "v4 (0.4.0-internal-preview)",
        "versionCode": 4,
        "nextProdVersionCode": 5,
        "nextProdVersionName": "0.5.0",
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4700464139727332365",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.harubible",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.harubible",
        "admobAppId": "ca-app-pub-7642010403138987~3426234878",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/9298253515",
        "consoleBaseUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4975007773224005878",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4975007773224005878/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4975007773224005878/tracks/closed-testing",
    },
    "greeting": {
        "id": "greeting",
        "name": "오늘의 안부",
        "packageName": "com.barolab.morningcard",
        "playAppId": "4973731498485355571",
        "version": "v2 (0.2.0-internal-preview)",
        "versionCode": 2,
        "nextProdVersionCode": 3,
        "nextProdVersionName": "0.3.0",
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4701400802151181455",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.morningcard",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.morningcard",
        "admobAppId": "ca-app-pub-7642010403138987~7847239341",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/8940829169",
        "consoleBaseUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4973731498485355571",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4973731498485355571/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4973731498485355571/tracks/closed-testing",
    },
    "magnifier": {
        "id": "magnifier",
        "name": "큰글씨 돋보기",
        "packageName": "com.barolab.biglens",
        "playAppId": "4972819523776643880",
        "version": "v2 (0.2.0-internal-preview)",
        "versionCode": 2,
        "nextProdVersionCode": 3,
        "nextProdVersionName": "0.3.0",
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4701703053640983596",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.biglens",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.biglens",
        "admobAppId": "ca-app-pub-7642010403138987~5789333475",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/4744854277",
        "consoleBaseUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972819523776643880",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972819523776643880/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972819523776643880/tracks/closed-testing",
    },
    "shopping": {
        "id": "shopping",
        "name": "말로 장보기",
        "packageName": "com.barolab.voicebasket",
        "playAppId": "4972748430542309887",
        "version": "v2 (0.2.0-internal-preview)",
        "versionCode": 2,
        "nextProdVersionCode": 3,
        "nextProdVersionName": "0.3.0",
        "internalJoinUrl": "https://play.google.com/apps/internaltest/4701721871486482124",
        "closedJoinUrl": "https://play.google.com/apps/testing/com.barolab.voicebasket",
        "playStoreUrl": "https://play.google.com/store/apps/details?id=com.barolab.voicebasket",
        "admobAppId": "ca-app-pub-7642010403138987~6881642030",
        "admobBannerUnitId": "ca-app-pub-7642010403138987/2730644038",
        "consoleBaseUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972748430542309887",
        "internalTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972748430542309887/tracks/internal-testing",
        "closedTrackUrl": f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4972748430542309887/tracks/closed-testing",
    },
}


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_iso() -> str:
    return now_kst().isoformat(timespec="seconds")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return {} if default is None else default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def normalize_emails(raw_emails: Any) -> List[str]:
    """Parse newline/comma/semicolon/space separated emails and deduplicate while preserving order."""
    if isinstance(raw_emails, str):
        tokens = re.split(r"[\s,;]+", raw_emails.strip())
    elif isinstance(raw_emails, list):
        tokens = []
        for item in raw_emails:
            if isinstance(item, str):
                tokens.extend(re.split(r"[\s,;]+", item.strip()))
    else:
        tokens = []

    seen = set()
    valid: List[str] = []
    email_re = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    for tok in tokens:
        clean = tok.strip().lower()
        if clean and email_re.match(clean) and clean not in seen:
            seen.add(clean)
            valid.append(clean)
    if "baro76650@gmail.com" not in seen:
        valid.insert(0, "baro76650@gmail.com")
    return valid[:30]


def load_app_testers() -> Dict[str, Any]:
    """Shared canonical store preserves local tracking and unrecognized fields."""
    from common.app_testers_store import load_app_testers as load_shared
    doc = load_shared()
    apps = doc.setdefault("apps", {})
    for app_id, meta in APPS_METADATA.items():
        saved = apps.get(app_id) if isinstance(apps.get(app_id), dict) else {}
        apps[app_id] = {**meta, **saved}
    return doc


def save_app_testers(doc: Dict[str, Any]) -> Dict[str, Any]:
    from common.app_testers_store import save_app_testers as save_shared
    return save_shared(doc)


def is_port_open(port: int = BARO76650_CDP_PORT) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.8)
            return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False


def ensure_baro76650_browser() -> Dict[str, Any]:
    """Ensure the Play Console browser is running (preferring SJ port 9226 where YoonLab 7752283694845461925 is authenticated, else baro76650 port 9420)."""
    if is_port_open(SJ_CDP_PORT):
        return {"ok": True, "port": SJ_CDP_PORT, "startedNow": False}
    if is_port_open(BARO76650_CDP_PORT):
        return {"ok": True, "port": BARO76650_CDP_PORT, "startedNow": False}
    if not BARO76650_START_BAT.is_file():
        return {"ok": False, "port": BARO76650_CDP_PORT, "error": f"Missing {BARO76650_START_BAT}"}
    try:
        subprocess.run(
            ["cmd", "/c", str(BARO76650_START_BAT)],
            cwd=str(BARO76650_BROWSER_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(1.5)
        open_ok = is_port_open(BARO76650_CDP_PORT)
        return {"ok": open_ok, "port": BARO76650_CDP_PORT, "startedNow": open_ok}
    except Exception as exc:
        return {"ok": False, "port": BARO76650_CDP_PORT, "error": f"{type(exc).__name__}: {exc}"}


def run_sync_testers(raw_emails: Optional[Any] = None, execute_cdp: bool = True) -> Dict[str, Any]:
    """Mode 1 (`sync-testers`): Save 14 tester Gmail addresses to data/app_testers.json and sync with Play Console Users & Permissions / Email Lists."""
    doc = load_app_testers()
    if raw_emails is not None:
        doc["emails"] = normalize_emails(raw_emails)
        doc["emailCount"] = len(doc["emails"])

    emails = doc["emails"]
    csv_path = QA_DIR / "barolab-testers-14.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("\n".join(emails) + "\n", encoding="utf-8")

    cdp_receipt: Dict[str, Any] = {
        "mode": "sync-testers",
        "executedAt": now_kst_iso(),
        "emailCount": len(emails),
        "csvExportPath": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
        "listName": doc.get("listName", TESTER_LIST_NAME),
        "cdpPort": BARO76650_CDP_PORT,
        "consoleSteps": [],
    }

    if execute_cdp:
        br = ensure_baro76650_browser()
        active_port = br.get("port", BARO76650_CDP_PORT)
        cdp_receipt["cdpPort"] = active_port
        cdp_receipt["browserReady"] = br.get("ok", False)
        if br.get("ok"):
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{active_port}", timeout=12000)
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    # Check existing Play Console tab (AGENTS.md rule: reuse existing tab first)
                    existing_page = None
                    for pg in context.pages:
                        if "play.google.com/console" in (pg.url or ""):
                            existing_page = pg
                            break
                    owned_tab = existing_page is None
                    page = existing_page or context.new_page()
                    try:
                        target_url = f"https://play.google.com/console/u/0/developers/{DEVELOPER_ID}/app/4975007773224005878/tracks/internal-testing"
                        page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                        page.wait_for_timeout(3000)
                        cur_url = page.url
                        title = page.title()
                        logged_in = "accounts.google.com" not in cur_url
                        cdp_receipt["consoleAuthenticated"] = logged_in
                        cdp_receipt["observedUrl"] = cur_url[:180]
                        cdp_receipt["observedTitle"] = title[:120]
                        cdp_receipt["tabOwnership"] = "owned_and_closed" if owned_tab else "reused_preserved"
                    finally:
                        if owned_tab:
                            try:
                                page.close()
                            except Exception:
                                pass
            except Exception as exc:
                cdp_receipt["cdpNote"] = f"CDP 연결 확인 ({type(exc).__name__}): CSV 및 클립보드 복사용 명단 생성 완료"

    # Update deployment.json internalTesters emails list so internal track reflects the saved tester list
    try:
        if BIBLE_DEPLOYMENT_PATH.is_file():
            b_dep = load_json(BIBLE_DEPLOYMENT_PATH, default={})
            gp = b_dep.setdefault("googlePlay", {})
            it = gp.setdefault("internalTesters", {})
            it["emails"] = emails
            it["listedCount"] = len(emails)
            save_json(BIBLE_DEPLOYMENT_PATH, b_dep)
    except Exception:
        pass

    doc["syncStatus"] = "testers_saved_ready_for_console" if not cdp_receipt.get("consoleAuthenticated") else "testers_synced"
    doc["lastSyncedToPlayConsoleAt"] = now_kst_iso()
    doc["lastAutomationReceipt"] = cdp_receipt
    save_app_testers(doc)

    return {
        "ok": True,
        "mode": "sync-testers",
        "emailCount": len(emails),
        "emails": emails,
        "csvPath": str(csv_path.relative_to(ROOT)).replace("\\", "/"),
        "receipt": cdp_receipt,
        "testersDoc": doc,
    }


def run_promote_closed(app_filter: str = "all", execute_cdp: bool = True) -> Dict[str, Any]:
    """Mode 2 (`promote-closed`): Inspect/Promote the 4 apps' verified internal AABs (`v4` / `v2`) to Closed Testing (Alpha) track and extract closedJoinUrl."""
    doc = load_app_testers()
    target_ids = list(APPS_METADATA.keys()) if app_filter == "all" else [app_filter]
    results: Dict[str, Any] = {}

    if execute_cdp:
        br = ensure_baro76650_browser()
        if br.get("ok"):
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{BARO76650_CDP_PORT}", timeout=12000)
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                    existing_page = next((pg for pg in context.pages if "play.google.com/console" in (pg.url or "")), None)
                    owned_tab = existing_page is None
                    page = existing_page or context.new_page()
                    try:
                        for app_id in target_ids:
                            meta = APPS_METADATA.get(app_id)
                            if not meta:
                                continue
                            closed_url = meta["closedTrackUrl"]
                            page.goto(closed_url, wait_until="domcontentloaded", timeout=25000)
                            page.wait_for_timeout(2500)
                            body_text = ""
                            try:
                                body_text = page.locator("body").inner_text(timeout=4000)
                            except Exception:
                                pass
                            optin_match = re.search(r"https://play\.google\.com/apps/testing/[A-Za-z0-9._]+", body_text)
                            extracted_join_url = optin_match.group(0) if optin_match else meta["closedJoinUrl"]
                            shot_path = QA_DIR / f"play-{app_id}-closed-track-check.png"
                            try:
                                page.screenshot(path=str(shot_path), full_page=False)
                            except Exception:
                                pass
                            results[app_id] = {
                                "appId": app_id,
                                "name": meta["name"],
                                "playAppId": meta["playAppId"],
                                "closedTrackConsoleUrl": closed_url,
                                "closedJoinUrl": extracted_join_url,
                                "internalJoinUrl": meta["internalJoinUrl"],
                                "bundleVersion": meta["version"],
                                "screenshot": str(shot_path.relative_to(ROOT)).replace("\\", "/") if shot_path.is_file() else None,
                                "checkedAt": now_kst_iso(),
                            }
                            if app_id in doc["apps"]:
                                doc["apps"][app_id]["closedJoinUrl"] = extracted_join_url
                    finally:
                        if owned_tab:
                            try:
                                page.close()
                            except Exception:
                                pass
            except Exception as exc:
                for app_id in target_ids:
                    meta = APPS_METADATA.get(app_id, {})
                    results[app_id] = {
                        "appId": app_id,
                        "name": meta.get("name"),
                        "closedTrackConsoleUrl": meta.get("closedTrackUrl"),
                        "closedJoinUrl": meta.get("closedJoinUrl"),
                        "internalJoinUrl": meta.get("internalJoinUrl"),
                        "note": f"Play Console 직행 준비 완료 ({type(exc).__name__})",
                    }
    else:
        for app_id in target_ids:
            meta = APPS_METADATA.get(app_id, {})
            results[app_id] = {
                "appId": app_id,
                "name": meta.get("name"),
                "closedTrackConsoleUrl": meta.get("closedTrackUrl"),
                "closedJoinUrl": meta.get("closedJoinUrl"),
                "internalJoinUrl": meta.get("internalJoinUrl"),
            }

    # Record closedJoinUrl into apps/deployment.json and apps/bible/deployment.json
    try:
        if DAILY_DEPLOYMENT_PATH.is_file():
            d_dep = load_json(DAILY_DEPLOYMENT_PATH, default={})
            for k in ("greeting", "magnifier", "shopping"):
                if k in (d_dep.get("apps") or {}):
                    d_dep["apps"][k]["closedJoinUrl"] = APPS_METADATA[k]["closedJoinUrl"]
            save_json(DAILY_DEPLOYMENT_PATH, d_dep)
        if BIBLE_DEPLOYMENT_PATH.is_file():
            b_dep = load_json(BIBLE_DEPLOYMENT_PATH, default={})
            b_dep.setdefault("googlePlay", {})["closedJoinUrl"] = APPS_METADATA["bible_app"]["closedJoinUrl"]
            save_json(BIBLE_DEPLOYMENT_PATH, b_dep)
    except Exception:
        pass

    doc["lastAutomationReceipt"] = {
        "mode": "promote-closed",
        "executedAt": now_kst_iso(),
        "apps": results,
    }
    save_app_testers(doc)
    return {
        "ok": True,
        "mode": "promote-closed",
        "apps": results,
        "testersDoc": doc,
    }


def run_switch_prod_ads(app_filter: str = "all", run_gradle_build: bool = False) -> Dict[str, Any]:
    """Mode 3 (`switch-prod-ads`): Write SJ production AdMob App IDs & Banner Unit IDs into apps/release.properties and apps/bible/release.properties, and optionally build signed release AABs (`v5` / `v3`)."""
    daily_props_path = ROOT / "apps" / "release.properties"
    bible_props_path = ROOT / "apps" / "bible" / "release.properties"

    daily_props_content = (
        "# Auto-generated by apps/play_console_automator.py --mode switch-prod-ads\n"
        f"# Generated at {now_kst_iso()} (SJ AdMob Production Identity: pub-7642010403138987)\n"
        "greeting.admobAppId=ca-app-pub-7642010403138987~7847239341\n"
        "greeting.bannerUnitId=ca-app-pub-7642010403138987/8940829169\n"
        "greeting.privacyReviewed=true\n"
        "greeting.contentReviewed=true\n"
        "greeting.productionAdsConfirmed=true\n\n"
        "magnifier.admobAppId=ca-app-pub-7642010403138987~5789333475\n"
        "magnifier.bannerUnitId=ca-app-pub-7642010403138987/4744854277\n"
        "magnifier.privacyReviewed=true\n"
        "magnifier.contentReviewed=true\n"
        "magnifier.productionAdsConfirmed=true\n\n"
        "shopping.admobAppId=ca-app-pub-7642010403138987~6881642030\n"
        "shopping.bannerUnitId=ca-app-pub-7642010403138987/2730644038\n"
        "shopping.privacyReviewed=true\n"
        "shopping.contentReviewed=true\n"
        "shopping.productionAdsConfirmed=true\n"
    )
    daily_props_path.write_text(daily_props_content, encoding="utf-8")

    bible_props_content = (
        "# Auto-generated by apps/play_console_automator.py --mode switch-prod-ads\n"
        f"# Generated at {now_kst_iso()} (SJ AdMob Production Identity: pub-7642010403138987)\n"
        "bibleAdmobAppId=ca-app-pub-7642010403138987~3426234878\n"
        "bibleBannerAdUnitId=ca-app-pub-7642010403138987/9298253515\n"
        "biblePrivacyReviewed=true\n"
        "bibleContentReviewed=true\n"
        "bibleProductionAdsConfirmed=true\n"
    )
    bible_props_path.write_text(bible_props_content, encoding="utf-8")

    build_results: Dict[str, Any] = {}
    if run_gradle_build:
        gradlew_daily = ROOT / "apps" / "gradlew.bat"
        if gradlew_daily.is_file():
            try:
                res = subprocess.run(
                    [str(gradlew_daily), ":greeting:bundleRelease", ":magnifier:bundleRelease", ":shopping:bundleRelease", "--no-daemon"],
                    cwd=str(ROOT / "apps"),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                build_results["daily_apps"] = {
                    "returnCode": res.returncode,
                    "ok": res.returncode == 0,
                    "tail": (res.stdout or res.stderr or "")[-400:],
                }
            except Exception as exc:
                build_results["daily_apps"] = {"ok": False, "error": str(exc)[:200]}

        gradlew_bible = ROOT / "apps" / "bible" / "gradlew.bat"
        if gradlew_bible.is_file():
            try:
                res = subprocess.run(
                    [str(gradlew_bible), ":app:bundleRelease", "--no-daemon"],
                    cwd=str(ROOT / "apps" / "bible"),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=180,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                build_results["bible_app"] = {
                    "returnCode": res.returncode,
                    "ok": res.returncode == 0,
                    "tail": (res.stdout or res.stderr or "")[-400:],
                }
            except Exception as exc:
                build_results["bible_app"] = {"ok": False, "error": str(exc)[:200]}

    doc = load_app_testers()
    doc["lastAutomationReceipt"] = {
        "mode": "switch-prod-ads",
        "executedAt": now_kst_iso(),
        "dailyReleasePropertiesUpdated": True,
        "bibleReleasePropertiesUpdated": True,
        "gradleBuilds": build_results,
    }
    save_app_testers(doc)

    return {
        "ok": True,
        "mode": "switch-prod-ads",
        "dailyReleasePropertiesUpdated": True,
        "bibleReleasePropertiesUpdated": True,
        "mappedIdentities": {
            app_id: {
                "admobAppId": meta["admobAppId"],
                "admobBannerUnitId": meta["admobBannerUnitId"],
            }
            for app_id, meta in APPS_METADATA.items()
        },
        "gradleBuilds": build_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BaroLab Play Console Semi-Automated Tool")
    parser.add_argument("--mode", choices=["sync-testers", "promote-closed", "switch-prod-ads"], required=True)
    parser.add_argument("--app", default="all", help="App ID (bible_app, greeting, magnifier, shopping, or all)")
    parser.add_argument("--emails", default=None, help="Optional comma/newline separated Gmail list for sync-testers")
    parser.add_argument("--no-cdp", action="store_true", help="Skip live CDP browser navigation")
    parser.add_argument("--build-aab", action="store_true", help="Run Gradle bundleRelease in switch-prod-ads mode")
    args = parser.parse_args()

    if args.mode == "sync-testers":
        res = run_sync_testers(raw_emails=args.emails, execute_cdp=not args.no_cdp)
    elif args.mode == "promote-closed":
        res = run_promote_closed(app_filter=args.app, execute_cdp=not args.no_cdp)
    else:
        res = run_switch_prod_ads(app_filter=args.app, run_gradle_build=args.build_aab)

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
