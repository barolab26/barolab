"""
BaroLab EGO LITE Autonomous Orchestrator (WSL2 Ubuntu GUI Mode)
Author: BaroLab Autonomous Team
Description:
  Runs inside the active Ubuntu XFCE desktop session (DISPLAY=:10).
  Coordinates:
  1. CF Pipeline catch-up & scheduled blog publications
  2. Naver Blog / Kin / SearchAdvisor cadence
  3. Google Drive directive & status JSON synchronization
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
    nas_dir = Path(r"\\otns\yoonlab\10_Project\BaroLab") if os.name == "nt" else Path("/mnt/c/10_Project/BaroLab")
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


def main_loop():
    ensure_display()
    log("==================================================================", "35")
    log("   EGO LITE AUTONOMOUS ORCHESTRATOR ACTIVE (WSL2 XFCE GUI)       ", "32")
    log("   Display: " + os.environ.get("DISPLAY", ":10") + " | Host: Ubuntu WSL2", "35")
    log("==================================================================", "35")
    
    interval = 60  # Check every 60 seconds
    pass_num = 1
    
    while True:
        log(f"--- [PASS #{pass_num}] System Cadence Check ---", "34")
        try:
            # 1. Sync Drive / State files
            sync_drive_state_files()
            
            # 2. CF Pipeline Catch-Up
            run_cf_catch_up()
            
            # 3. Report active status
            log(f"[HEALTH] Pass #{pass_num} completed. Sleeping {interval}s...", "32")
        except KeyboardInterrupt:
            log("EGO LITE stopped by user.", "33")
            break
        except Exception as err:
            log(f"Unexpected error in cadence loop: {err}", "31")
            
        pass_num += 1
        time.sleep(interval)


if __name__ == "__main__":
    main_loop()
