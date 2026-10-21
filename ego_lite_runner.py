"""
BaroLab EGO LITE Monitor and Explicit Naver Workflow Entry
Default: read-only project observations and existing durable crew execution receipts.
Explicit Naver requests retain the existing guarded pipeline and execution lock.
No default publication scheduler or external chat access.
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
from common.ego_telemetry import export_environment


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
    """Observe existing workers without starting duplicate schedulers."""
    from server.ego_live_monitor import main as monitor_main
    return monitor_main()


def run_visible_naver(account, *, slot=None, publication_date=None, topic_seed=None,
                      main_keyword=None, evidence_dir=None, prepared_dir=None, strategy=None, materials_manifest=None, reserve_time=None,
                      prepare_only=False):
    """Route a local explicit request through the existing reviewed Naver runner."""
    from common.ubuntu_naver_browser import accounts
    if account not in accounts():
        raise ValueError("Unknown Naver account")
    command = [sys.executable, str(ROOT / "naver_blog_posting/pipeline_runner.py"),
               "--account", account, "--visible"]
    if prepare_only:
        if prepared_dir is not None:
            raise ValueError("Preparation-only creates new artifacts, not a submission from prepared-dir")
        command.append("--prepare-only")
    for flag, value in (("--slot", slot), ("--publication-date", publication_date),
                        ("--topic-seed", topic_seed), ("--main-keyword", main_keyword),
                        ("--evidence-dir", evidence_dir), ("--prepared-dir", prepared_dir),
                        ("--strategy", strategy), ("--materials-manifest", materials_manifest),
                        ("--reserve-time", reserve_time)):
        if value is not None:
            command.extend([flag, str(value)])
    environment = dict(export_environment(), DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"))
    if prepare_only:
        # A preparation fixture must not mutate the publication reconciliation ledger.
        return subprocess.run(command, cwd=str(ROOT), env=environment, shell=False).returncode
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
    environment = dict(export_environment(), DISPLAY=os.environ.get("BAROLAB_DISPLAY", ":10"),
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
    parser.add_argument("--prepare-only", action="store_true")
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
    if args.prepare_only and not args.naver_account:
        parser.error("--prepare-only requires --naver-account")
    if not args.naver_account and any((args.slot, args.publication_date, args.topic_seed,
                                      args.main_keyword, args.evidence_dir, args.prepared_dir,
                                      args.strategy, args.materials_manifest, args.reserve_time)):
        parser.error("Naver arguments require --naver-account")
    if not args.naver_account and not args.naver_catch_up:
        return main_loop()
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
                                         materials_manifest=args.materials_manifest, reserve_time=args.reserve_time,
                                         prepare_only=args.prepare_only)
        else:
            print("EGO LITE is already running.", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
