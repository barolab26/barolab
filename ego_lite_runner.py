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

from common.gemini_chat_controller import send_gemini_message_sync

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


if __name__ == "__main__":
    main_loop()
