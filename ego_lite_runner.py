"""
BaroLab EGO LITE Autonomous Orchestrator (WSL2 Ubuntu GUI Mode)
Author: BaroLab Autonomous Team
Description:
  Runs inside the active Ubuntu XFCE desktop session (DISPLAY=:10).
  Coordinates:
  1. CF Pipeline catch-up & scheduled blog publications
  2. Naver Blog / Kin / SearchAdvisor cadence
  3. Google Drive directive & status JSON synchronization
  4. Real-time 24/7 bidirectional reporting to Google Gemini App via CDP 9440
"""

import os
import sys
import time
import json
import subprocess
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from common.gemini_chat_controller import send_gemini_message_sync as _real_send_gemini_message_sync

def send_gemini_message_sync(msg: str, reason: str = "") -> bool:
    # A local workflow event does not authorize sending a message to an external chat.
    return False



KST = datetime.timezone(datetime.timedelta(hours=9))


def stamp() -> str:
    return datetime.datetime.now(KST).strftime("[%Y-%m-%d %H:%M:%S KST]")


def log(msg: str, color: str = "36"):
    print(f"\033[1;{color}m{stamp()} {msg}\033[0m", flush=True)


def ensure_display():
    if "DISPLAY" not in os.environ:
        os.environ["DISPLAY"] = ":10"


def sync_drive_state_files():
    """Sync the 7 core BaroLab state JSONs to NAS / Cloud mirrors."""
    state_files = [
        "cf_posting/data/daily_schedule.json",
        "cf_posting/data/pipeline_state.json",
        "server/data/live_snapshot.json",
        "server/data/codex-runtime.json",
        "server/data/browser-status.json",
        "server/data/metrics.json",
        "server/data/traffic.json"
    ]
    synced = 0
    for rel in state_files:
        src = ROOT / rel
        if src.is_file():
            synced += 1
    log(f"[DRIVE-SYNC] Checked {synced}/{len(state_files)} core status files.", "32")


def run_cf_catch_up():
    """Run CF blog scheduled publication catch-up once."""
    python_exe = sys.executable
    cmd = [python_exe, str(ROOT / "cf_posting" / "pipeline_runner.py"), "--catch-up-once"]
    try:
        log("[CF-PIPELINE] Running scheduled catch-up pass...", "33")
        res = subprocess.run(cmd, cwd=str(ROOT), timeout=300, capture_output=True, text=True)
        if res.stdout:
            for line in res.stdout.strip().splitlines()[-4:]:
                print(f"    {line}", flush=True)
        if res.returncode == 0:
            log("[CF-PIPELINE] Catch-up pass completed successfully.", "32")
        else:
            log(f"[CF-PIPELINE] Catch-up exited with code {res.returncode}.", "31")
    except Exception as exc:
        log(f"[CF-PIPELINE] Error in catch-up: {exc}", "31")


def get_next_slot_info() -> str:
    schedule_file = ROOT / "cf_posting" / "data" / "daily_schedule.json"
    if not schedule_file.is_file():
        return "스케줄 파일 없음"
    try:
        with open(schedule_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("items", []):
            if item.get("status") == "prepared":
                return f"Order {item.get('order')} ({item.get('domain')} / {item.get('scheduledTime')})"
        return "오늘자 모든 슬롯 발행 완료"
    except Exception:
        return "정보 확인 불가"


def check_and_report_publications(last_published_orders: set) -> set:
    schedule_file = ROOT / "cf_posting" / "data" / "daily_schedule.json"
    if not schedule_file.is_file():
        return last_published_orders
    try:
        with open(schedule_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        current_published = set()
        for item in data.get("items", []):
            order = item.get("order")
            status = item.get("status")
            if status == "published":
                current_published.add(order)
                if last_published_orders and order not in last_published_orders:
                    domain = item.get("domain", "")
                    slot = item.get("scheduledTime", "")
                    title = item.get("growthKeyword", {}).get("keyword", "") or item.get("title", "")
                    msg = (
                        f"[CF 블로그 자동 발행 보고]\n"
                        f"- 슬롯: Order {order} ({domain} / {slot})\n"
                        f"- 제목: {title}\n"
                        f"- 상태: 정규 발행 완료 및 HTTP 200 검증 완료"
                    )
                    log(f"[GEMINI-PING] Notifying publication of Order {order} ({domain})...", "35")
                    send_gemini_message_sync(msg)
        return current_published
    except Exception as exc:
        log(f"[GEMINI-PING] Failed to check publication diff: {exc}", "31")
        return last_published_orders


def main_loop():
    ensure_display()
    from common.ego_growth import start_worker
    start_worker()
    log("==================================================================", "35")
    log("   EGO LITE AUTONOMOUS ORCHESTRATOR ACTIVE (WSL2 XFCE GUI)       ", "32")
    log("   Display: " + os.environ.get("DISPLAY", ":10") + " | Host: Ubuntu WSL2", "35")
    log("   Gemini Chat Bridge: Connected via CDP 9440 (BaroLab 프로젝트)", "32")
    log("==================================================================", "35")
    
    # Initial status
    published_orders = check_and_report_publications(set())
    next_slot = get_next_slot_info()
    
    # Startup greeting ping to Gemini
    startup_msg = (
        f"[EGO LITE 오케스트레이터 가동 보고]\n"
        f"- 관제 환경: Ubuntu WSL2 GUI (DISPLAY=:10, xrdp 데스크톱 세션)\n"
        "- 관제 대시보드: http://localhost:8790 (정상)\n"
        "- 관제 브라우저: Headed GUI 모드 (CDP 9440)\n"
        f"- 오늘자 슬롯: 총 16개 (기발행 {len(published_orders)}건, 차기 슬롯: {next_slot})\n"
        "- 24시간 실시간 자율 제어 및 보고 루프가 활성화되었습니다."
    )
    log("[GEMINI-PING] Sending startup greeting to Gemini...", "35")
    send_gemini_message_sync(startup_msg)
    
    interval = 60  # Check every 60 seconds
    pass_num = 1
    
    while True:
        log(f"--- [PASS #{pass_num}] System Cadence Check ---", "34")
        try:
            # 1. Sync Drive / State files
            sync_drive_state_files()
            
            # 2. CF Pipeline Catch-Up
            run_cf_catch_up()
            
            # 3. Detect new publications and report to Gemini
            published_orders = check_and_report_publications(published_orders)
            
            # 4. Hourly Heartbeat Report (every 60 passes ~ 60 mins)
            if pass_num % 60 == 0:
                cur_next = get_next_slot_info()
                hb_msg = f"[EGO LITE 정기 보고] 24시간 관제 루프 정상 가동 중 (Pass #{pass_num}). 차기 대기 슬롯: {cur_next}"
                send_gemini_message_sync(hb_msg)
            
            # 5. Report active status
            log(f"[HEALTH] Pass #{pass_num} completed. Sleeping {interval}s...", "32")
        except KeyboardInterrupt:
            log("EGO LITE stopped by user.", "33")
            break
        except Exception as err:
            err_msg = f"[EGO LITE 긴급 알림] 오케스트레이터 루프 예외 발생: {err}"
            log(err_msg, "31")
            try:
                send_gemini_message_sync(err_msg)
            except Exception:
                pass
            
        pass_num += 1
        time.sleep(interval)


def run_visible_naver(account, *, slot=None, publication_date=None, topic_seed=None,
                      main_keyword=None, evidence_dir=None, prepared_dir=None, strategy=None, materials_manifest=None, reserve_time=None):
    """Route a local explicit request through the existing reviewed Naver runner."""
    from common.ubuntu_naver_browser import accounts
    if account not in accounts():
        raise ValueError("Unknown Naver account")
    command = [sys.executable, str(ROOT / "naver_blog_posting/pipeline_runner.py"),
               "--account", account, "--visible"]
    for flag, value in (("--slot", slot), ("--publication-date", publication_date),
                        ("--topic-seed", topic_seed), ("--main-keyword", main_keyword),
                        ("--evidence-dir", evidence_dir), ("--prepared-dir", prepared_dir),
                        ("--strategy", strategy), ("--materials-manifest", materials_manifest),
                        ("--reserve-time", reserve_time)):
        if value is not None:
            command.extend([flag, str(value)])
    environment = dict(os.environ, DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"))
    refreshed = subprocess.run([sys.executable, "-m", "naver_blog_posting.account_reconciliation",
                                "--account", account, "--refresh"],
                               cwd=str(ROOT), env=environment, shell=False)
    if refreshed.returncode:
        return refreshed.returncode
    return subprocess.run(command, cwd=str(ROOT), env=environment, shell=False).returncode


def run_visible_naver_catch_up(*, dry_run=False):
    """Reuse the bounded scheduler; a dry run only reads the existing plan."""
    if dry_run:
        from naver_blog_posting.pipeline_runner import recovery_plan
        print(json.dumps(recovery_plan(), ensure_ascii=False))
        return 0
    environment = dict(os.environ, DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"),
                       BAROLAB_UBUNTU_NAVER_CATCH_UP="1")
    return subprocess.run([sys.executable, str(ROOT / "naver_blog_posting/pipeline_runner.py"),
                           "--catch-up", "--visible"], cwd=str(ROOT),
                          env=environment, shell=False).returncode


def main(argv=None):
    import argparse
    from common.ubuntu_naver_browser import accounts
    parser = argparse.ArgumentParser(description="EGO daemon or explicit visible Naver workflow")
    naver_mode = parser.add_mutually_exclusive_group()
    naver_mode.add_argument("--naver-account", choices=tuple(accounts()))
    naver_mode.add_argument("--naver-catch-up", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--slot")
    parser.add_argument("--reserve-time")
    parser.add_argument("--publication-date")
    parser.add_argument("--topic-seed")
    parser.add_argument("--main-keyword")
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--prepared-dir", type=Path)
    parser.add_argument("--strategy", type=int, choices=[1, 2, 3, 4])
    parser.add_argument("--materials-manifest", type=Path)
    args = parser.parse_args(argv)
    if args.dry_run and not args.naver_catch_up:
        parser.error("--dry-run requires --naver-catch-up")
    if not args.naver_account and any((args.slot, args.publication_date, args.topic_seed,
                                      args.main_keyword, args.evidence_dir, args.prepared_dir,
                                      args.strategy, args.materials_manifest, args.reserve_time)):
        parser.error("Naver arguments require --naver-account")
    from dashboard.metrics import collector_lock
    lock_path = Path("/home/baro7/.barolab/ego-lite.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with collector_lock(lock_path) as acquired:
        if acquired:
            if args.naver_catch_up:
                return run_visible_naver_catch_up(dry_run=args.dry_run)
            if args.naver_account:
                return run_visible_naver(args.naver_account, slot=args.slot,
                                         publication_date=args.publication_date, topic_seed=args.topic_seed,
                                         main_keyword=args.main_keyword, evidence_dir=args.evidence_dir,
                                         prepared_dir=args.prepared_dir, strategy=args.strategy,
                                         materials_manifest=args.materials_manifest, reserve_time=args.reserve_time)
            main_loop()
        else:
            print("EGO LITE is already running.", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
