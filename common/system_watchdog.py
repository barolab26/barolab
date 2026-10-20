"""BaroLab 100% Unmanned System Watchdog (Browser CDP, Zombie Locks, Missed Slot Catch-up)."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT / "server"
for _p in (ROOT, SERVER_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DATA_DIR = SERVER_DIR / "data"
WATCHDOG_STATUS_PATH = DATA_DIR / "watchdog-status.json"
BROWSER_STATUS_PATH = DATA_DIR / "browser-status.json"

KST = timezone(timedelta(hours=9))

PORTABLE_BROWSER_ROOT = Path(r"C:\99_포터블브라우저")
CDP_SCRIPT_PATH = PORTABLE_BROWSER_ROOT / "_cdp_browser.ps1"

CDP_PORT_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "stone0747_cdp",
        "port": 9230,
        "name": "stone0747 (CF 브릿지·지식iN)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_stone0747",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_stone0747" / "stone0747_start_cdp.bat",
        "windowSize": "1280,900",
        "required": True,
    },
    {
        "id": "adinfo0905_cdp",
        "port": 9231,
        "name": "adinfo0905 (CF 브릿지·지식iN)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_adinfo0905",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_adinfo0905" / "adinfo0905_start_cdp.bat",
        "windowSize": "1280,900",
        "required": True,
    },
    {
        "id": "soul5373_cdp",
        "port": 9333,
        "name": "soul5373 (mustinfo)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPortable_soul5373",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPortable_soul5373" / "soul5373_start_cdp.bat",
        "windowSize": "1280,900",
        "required": True,
    },
    {
        "id": "soultin_cdp",
        "port": 9334,
        "name": "soultin (mustpickinfo)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_soultin",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_soultin" / "soultin_start_cdp.bat",
        "windowSize": "1280,900",
        "required": True,
    },
    {
        "id": "yoon_master_cdp",
        "port": 9335,
        "name": "yoon_master (yoonviews)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_yoon_master",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_yoon_master" / "yoon_master_start_cdp.bat",
        "windowSize": "1280,900",
        "required": True,
    },
    {
        "id": "cf_preparer_cdp",
        "port": 9336,
        "name": "cf_preparer (CF 준비·Flow)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPortable_cf_preparer",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPortable_cf_preparer" / "cf_preparer_start_cdp.bat",
        "windowSize": None,
        "required": True,
    },
    {
        "id": "sj_cdp",
        "port": 9226,
        "name": "sj (서치어드바이저·스레드·AdMob)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_sj",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_sj" / "sj_start_cdp.bat",
        "windowSize": None,
        "required": True,
    },
    {
        "id": "baro76650_cdp",
        "port": 9420,
        "name": "baro76650 (CF 블로그·Flow 생성)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPortable_baro76650",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPortable_baro76650" / "baro76650_start_cdp.bat",
        "windowSize": None,
        "required": True,
    },
    {
        "id": "aaa10291028_cdp",
        "port": 9260,
        "name": "aaa10291028 (GSC·애드센스 보조)",
        "folder": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_aaa10291028",
        "launcher": PORTABLE_BROWSER_ROOT / "CentBrowserPotable_aaa10291028" / "aaa10291028_start_cdp.bat",
        "windowSize": None,
        "proxy": "http://49.254.163.44:20339",
        "required": False,
    },
]


def now_kst() -> datetime:
    return datetime.now(KST)


def now_kst_iso() -> str:
    return now_kst().isoformat(timespec="seconds")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {} if default is None else default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.8) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False


def is_pid_alive(pid: Optional[int]) -> bool:
    if not pid or not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return str(pid) in (res.stdout or "")
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_process_running_match(pattern: str) -> bool:
    if os.name == "nt":
        try:
            res = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"@((Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {{ $_.CommandLine -match '{pattern}' }})).Count",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            count = int((res.stdout or "0").strip())
            return count > 0
        except Exception:
            return False
    return False


def parse_iso_age_seconds(iso_str: Optional[str]) -> Optional[float]:
    if not iso_str or not isinstance(iso_str, str):
        return None
    try:
        cleaned = iso_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return (now_kst() - dt.astimezone(KST)).total_seconds()
    except Exception:
        return None


def check_and_recover_server() -> Dict[str, Any]:
    """Ensure FastAPI dashboard server (port 8790) is listening."""
    port_8790 = is_port_open(8790)
    port_8791 = is_port_open(8791)
    recovered = False
    detail = "정상 가동 중"
    if not port_8790:
        python_exe = str(Path(sys.executable).with_name("python.exe"))
        try:
            subprocess.Popen(
                [python_exe, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8790"],
                cwd=str(SERVER_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(1.8)
            port_8790 = is_port_open(8790)
            recovered = port_8790
            detail = "8790 대시보드 서버 자동 재기동 완료" if recovered else "8790 서버 기동 시도 완료"
        except Exception as exc:
            detail = f"8790 서버 자동 기동 실패: {type(exc).__name__}"
    return {
        "port8790": port_8790,
        "port8791": port_8791,
        "recovered": recovered,
        "detail": detail,
    }


def check_and_recover_cdp_browsers(auto_start: bool = True) -> Dict[str, Any]:
    """Check all dedicated CDP browser ports and automatically start any closed required port."""
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    results: Dict[str, Any] = {}
    recovered_ports: List[int] = []
    failed_ports: List[int] = []

    for item in CDP_PORT_CATALOG:
        port = int(item["port"])
        open_now = is_port_open(port)
        was_recovered = False
        if not open_now and auto_start and item.get("required", True):
            launcher_path = Path(item["launcher"]) if item.get("launcher") else None
            folder_path = Path(item["folder"]) if item.get("folder") else None
            if launcher_path and launcher_path.exists():
                try:
                    subprocess.run(
                        ["cmd.exe", "/c", str(launcher_path)],
                        cwd=str(launcher_path.parent),
                        capture_output=True,
                        timeout=15,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    time.sleep(2.0)
                    open_now = is_port_open(port)
                    if open_now:
                        was_recovered = True
                        recovered_ports.append(port)
                    else:
                        failed_ports.append(port)
                except Exception:
                    failed_ports.append(port)
            elif CDP_SCRIPT_PATH.exists() and folder_path and folder_path.exists():
                cmd = [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(CDP_SCRIPT_PATH),
                    "-Action",
                    "Start",
                    "-BrowserFolder",
                    str(folder_path),
                    "-Port",
                    str(port),
                    "-Launcher",
                    str(launcher_path or ""),
                ]
                if item.get("windowSize"):
                    cmd.extend(["-WindowSize", str(item["windowSize"])])
                if item.get("proxy"):
                    cmd.extend(["-Proxy", str(item["proxy"])])
                try:
                    subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=20,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    time.sleep(1.0)
                    open_now = is_port_open(port)
                    if open_now:
                        was_recovered = True
                        recovered_ports.append(port)
                    else:
                        failed_ports.append(port)
                except Exception:
                    failed_ports.append(port)

        results[item["id"]] = {
            "port": port,
            "name": item["name"],
            "open": open_now,
            "recovered": was_recovered,
            "required": bool(item.get("required", True)),
        }

    required_items = [v for v in results.values() if v.get("required", True)]
    online_required = sum(1 for v in required_items if v.get("open"))
    # Keep the NAS monitor contract; loopback is not the Windows host identity.
    host_address = 'unknown'
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect((os.getenv('BAROLAB_NAS_HOST', '192.168.45.190'), 445))
            host_address = route.getsockname()[0]
    except OSError:
        pass
    browser_snapshot = {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "kstCheckedAt": now_kst_iso(),
        "host": host_address,
        "ports": {str(value['port']): value['open'] for value in results.values()},
        "browsers": results,
        "onlineCount": online_required,
        "totalRequired": len(required_items),
        "recoveredPorts": recovered_ports,
        "failedPorts": failed_ports,
    }
    try:
        save_json(BROWSER_STATUS_PATH, browser_snapshot)
    except Exception:
        pass
    return browser_snapshot


def clean_zombie_locks_and_recover(stale_minutes: int = 15) -> List[Dict[str, Any]]:
    """Detect zombie locks or running states stuck for >15 minutes and clean/re-trigger them."""
    stale_seconds = stale_minutes * 60
    actions: List[Dict[str, Any]] = []
    python_exe = str(Path(sys.executable).with_name("python.exe"))

    # 1. Flow generation lock (~/.barolab/runtime/flow-generation.lock)
    flow_lock = Path.home() / ".barolab" / "runtime" / "flow-generation.lock"
    if flow_lock.exists():
        try:
            age = time.time() - flow_lock.stat().st_mtime
            if age > stale_seconds:
                flow_lock.unlink(missing_ok=True)
                actions.append({
                    "channel": "flow_lock",
                    "owner": "@patch",
                    "action": "Flow 이미지 생성 좀비 락 자동 해제",
                    "detail": f"flow-generation.lock ({int(age // 60)}분 경과) 제거 완료",
                })
        except Exception:
            pass

    # 2. CF Blog pipeline state & lock
    cf_state_path = ROOT / "cf_posting" / "data" / "pipeline_state.json"
    cf_state = load_json(cf_state_path, default={})
    if isinstance(cf_state, dict) and cf_state.get("status") in ("running", "processing"):
        pid = cf_state.get("pid") or cf_state.get("helperPid")
        if not pid and isinstance(cf_state.get("browserRuntime"), dict):
            pid = cf_state["browserRuntime"].get("pid")
        age = parse_iso_age_seconds(cf_state.get("updatedAt") or cf_state.get("startedAt"))
        if age is None and cf_state.get("timestamp"):
            try:
                age = time.time() - float(cf_state["timestamp"])
            except Exception:
                pass
        if age is None and cf_state_path.exists():
            age = time.time() - cf_state_path.stat().st_mtime

        worker_alive = is_process_running_match("pipeline_runner.py")
        pid_dead = bool(pid and not is_pid_alive(int(pid)))
        is_stale = bool((age is not None and age > stale_seconds) or (not worker_alive))
        if pid_dead or is_stale:
            cf_state["status"] = "idle"
            cf_state["recoveredAt"] = now_kst_iso()
            cf_state["recoveryReason"] = (
                "작업 프로세스 미실행 감지" if not worker_alive
                else ("PID 종료 감지" if pid_dead else f"{int((age or 0) // 60)}분 무응답 좀비 상태 복구")
            )
            save_json(cf_state_path, cf_state)
            try:
                subprocess.Popen(
                    [python_exe, "-u", "-B", "-X", "utf8", str(ROOT / "cf_posting" / "pipeline_runner.py"), "--catch-up-once"],
                    cwd=str(ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass
            actions.append({
                "channel": "cf_blog",
                "owner": "@publi",
                "action": "CF 파이프라인 좀비 상태 초기화 및 재가동",
                "detail": cf_state["recoveryReason"],
            })

    # 3. Naver Blog active-workflow.json
    nv_active_path = ROOT / "naver_blog_posting" / "data" / "active-workflow.json"
    nv_active = load_json(nv_active_path, default={})
    if isinstance(nv_active, dict) and nv_active.get("status") in ("running", "processing", "in_progress"):
        pid = nv_active.get("pid")
        age = parse_iso_age_seconds(nv_active.get("updatedAt") or nv_active.get("startedAt"))
        pid_dead = bool(pid and not is_pid_alive(int(pid)))
        is_stale = bool(age is not None and age > stale_seconds)
        if pid_dead or is_stale:
            nv_active["status"] = "idle"
            nv_active["recoveredAt"] = now_kst_iso()
            nv_active["recoveryReason"] = "PID 종료 감지" if pid_dead else f"{int((age or 0) // 60)}분 무응답 좀비 상태 복구"
            save_json(nv_active_path, nv_active)
            try:
                subprocess.Popen(
                    [python_exe, "-u", "-B", "-X", "utf8", str(ROOT / "naver_blog_posting" / "pipeline_runner.py"), "--catch-up"],
                    cwd=str(ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass
            actions.append({
                "channel": "naver_blog",
                "owner": "@publi",
                "action": "네이버 블로그 좀비 워크플로 해제 및 즉시 재가동",
                "detail": nv_active["recoveryReason"],
            })

    # 4. Content Maintenance / Doctor lock
    maint_lock = DATA_DIR / "content-maintenance.lock"
    if maint_lock.exists():
        try:
            age = time.time() - maint_lock.stat().st_mtime
            if age > stale_seconds:
                maint_lock.unlink(missing_ok=True)
                actions.append({
                    "channel": "legacy_remodel",
                    "owner": "@doctor",
                    "action": "콘텐츠 유지보수 좀비 락 자동 해제",
                    "detail": f"content-maintenance.lock ({int(age // 60)}분 경과) 제거 완료",
                })
        except Exception:
            pass

    return actions


def trigger_missed_slot_catchup() -> List[Dict[str, Any]]:
    """Calculate missed slots for today (KST) across channels and trigger catch-up runs."""
    catchups: List[Dict[str, Any]] = []
    now = now_kst()
    today_str = now.strftime("%Y-%m-%d")
    current_hour = now.hour + now.minute / 60.0

    # 1. Content Doctor daily 20 remodeling quota catch-up
    try:
        from server import content_auditor
        doc_status = content_auditor.get_auditor_status()
        today_audited = int(doc_status.get("todayAudited") or 0)
        daily_target = int(doc_status.get("dailyQuotaTarget") or 20)
        # Expected progress by current hour (between 07:00 and 22:00)
        expected_by_now = min(daily_target, max(5, int(((max(0.0, current_hour - 7.0)) / 15.0) * daily_target)))
        if today_audited < expected_by_now:
            batch_size = min(5, daily_target - today_audited)
            if batch_size > 0:
                patrol_res = content_auditor.run_patrol_batch(count=batch_size, broadcast=False)
                audited_now = int(patrol_res.get("auditedNow") or 0)
                if audited_now > 0:
                    catchups.append({
                        "channel": "legacy_remodel",
                        "owner": "@doctor",
                        "action": f"기존 글 리모델링 미달 슬롯 {audited_now}건 즉시 자동 검진·패치",
                        "detail": f"오늘 누적 {patrol_res.get('todayAudited', today_audited + audited_now)}/{daily_target}건 달성",
                    })
    except Exception:
        pass

    # 2. Check Windows Scheduled Tasks health (ensure BaroLab-Naver-Daily, BaroLab-Kin-Seven-Day-Pilot, BaroLab-Threads-Pilot, BaroLab-CF-Cleaner are Enabled)
    if os.name == "nt":
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        for task_name, channel, owner in [
            ("BaroLab-Naver-Daily", "naver_blog", "@publi"),
            ("BaroLab-Kin-Seven-Day-Pilot", "naver_kin", "@publi"),
            ("BaroLab-Threads-Pilot", "threads", "@publi"),
            ("BaroLab-CF-Cleaner", "cf_blog", "@publi"),
        ]:
            try:
                res = subprocess.run(
                    [
                        str(powershell),
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        f"$t = Get-ScheduledTask -TaskName '{task_name}' -ErrorAction SilentlyContinue; if ($t -and $t.State -eq 'Disabled') {{ Enable-ScheduledTask -TaskName '{task_name}' | Out-Null; Write-Output 'RE_ENABLED' }}",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if "RE_ENABLED" in (res.stdout or ""):
                    catchups.append({
                        "channel": channel,
                        "owner": owner,
                        "action": f"비활성화된 스케줄러({task_name}) 자동 활성화 완료",
                        "detail": f"{today_str} KST 기준 자동 복구",
                    })
            except Exception:
                pass

    # 3. CF blog overdue slot auto catch-up
    try:
        cf_sched_path = ROOT / "cf_posting" / "data" / "daily_schedule.json"
        if cf_sched_path.exists():
            cf_sched = load_json(cf_sched_path, default={})
            items = cf_sched.get("items", [])
            overdue_items = [
                it for it in items
                if it.get("status") in ("waiting", "retry_wait", "failed")
                and it.get("scheduledTime", "99:99") <= now.strftime("%H:%M")
            ]
            python_exe = str(Path(sys.executable).with_name("python.exe"))
            if overdue_items and not is_process_running_match("pipeline_runner.py"):
                subprocess.Popen(
                    [python_exe, "-u", "-B", "-X", "utf8", str(ROOT / "cf_posting" / "pipeline_runner.py"), "--catch-up-once"],
                    cwd=str(ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                catchups.append({
                    "channel": "cf_blog",
                    "owner": "@publi",
                    "action": f"CF 블로그 지연 슬롯 {len(overdue_items)}건 감지 및 자동 캐치업 기동",
                    "detail": f"대기/재시도 {len(overdue_items)}건 자동 발행 프로세스 실행",
                })
    except Exception:
        pass

    return catchups


def broadcast_watchdog_events(
    server_res: Dict[str, Any],
    cdp_res: Dict[str, Any],
    zombie_actions: List[Dict[str, Any]],
    catchup_actions: List[Dict[str, Any]],
) -> bool:
    """Post a concise recovery briefing to chat.html if any recovery or catch-up occurred."""
    recovered_ports = cdp_res.get("recoveredPorts") or []
    server_recovered = bool(server_res.get("recovered"))
    if not recovered_ports and not server_recovered and not zombie_actions and not catchup_actions:
        return False

    try:
        from server import chat_room
        lines = ["🛠️ **[시스템 워치독 무인 자가 복구 & 슬롯 캐치업 완료 보고]**"]
        if server_recovered:
            lines.append(f"- **대시보드 서버**: `{server_res.get('detail')}`")
        if recovered_ports:
            port_str = ", ".join(str(p) for p in recovered_ports)
            lines.append(f"- **전용 브라우저 CDP 포트 자동 기동**: `{port_str}` 포트 백그라운드 복구 완료 (현재 {cdp_res.get('onlineCount')}/{cdp_res.get('totalRequired')} 가동)")
        for act in zombie_actions:
            lines.append(f"- **[{act['channel']}] 좀비 락 청소 ({act['owner']})**: {act['action']} — _{act['detail']}_")
        for cat in catchup_actions:
            lines.append(f"- **[{cat['channel']}] 미실행 슬롯 캐치업 ({cat['owner']})**: {cat['action']} — _{cat['detail']}_")

        chat_room.append_agent_message(
            agent_id="patch",
            content="\n".join(lines),
            room_id="main",
            msg_type="watchdog_recovery",
            metadata={
                "recoveredPorts": recovered_ports,
                "zombieCount": len(zombie_actions),
                "catchupCount": len(catchup_actions),
                "kstTime": now_kst_iso(),
            },
        )
        return True
    except Exception:
        return False


def audit_and_guard_app_closed_test_truth() -> Dict[str, Any]:
    """Ensure apps/*/project.json never claims a 14-day closed test countdown when internalTrack == 'internal' or closedTestOptIns < 12."""
    try:
        from server import projects as app_projects
        sync_res = app_projects.sync_manifests_to_disk(ROOT, force_verify=False)
        inv = app_projects.inventory(ROOT, force_verify=False)
        summary = inv.get("summary") or {}
        return {
            "ok": True,
            "updatedProjects": sync_res.get("updatedProjects", []),
            "countdownStarted": bool(summary.get("countdownStarted", False)),
            "currentTrackLabel": summary.get("currentTrackLabel", "내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작"),
            "closedTrackStatusLabel": summary.get("closedTrackStatusLabel", "비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)"),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


def run_system_watchdog(trigger_source: str = "scheduled", broadcast: bool = True) -> Dict[str, Any]:
    """Execute full SRE watchdog pass: Server -> CDP Browsers -> Zombie Locks -> Missed Slot Catch-up -> App/Project Audit."""
    started_at = now_kst_iso()
    server_res = check_and_recover_server()
    cdp_res = check_and_recover_cdp_browsers(auto_start=False)
    zombie_actions = clean_zombie_locks_and_recover(stale_minutes=15)
    catchup_actions = trigger_missed_slot_catchup()
    app_track_truth = audit_and_guard_app_closed_test_truth()

    # Also refresh 4 mobile apps & 6-project health snapshot
    project_audit_summary = {}
    try:
        from server import project_health
        health_data = project_health.audit_all_projects_health(broadcast_if_changed=broadcast)
        project_audit_summary = {
            "totalProjects": len(health_data.get("projects") or []),
            "ceoActionCount": len(health_data.get("ceoActionItems") or []),
            "autoRecoveringCount": sum(
                1 for p in (health_data.get("projects") or []) if p.get("status") == "auto_recovering"
            ),
            "appTrackTruth": app_track_truth,
        }
    except Exception as exc:
        project_audit_summary = {"error": str(exc)[:200], "appTrackTruth": app_track_truth}

    broadcasted = False
    if broadcast:
        broadcasted = broadcast_watchdog_events(server_res, cdp_res, zombie_actions, catchup_actions)

    report = {
        "schema": "barolab-system-watchdog-v1",
        "triggerSource": trigger_source,
        "startedAt": started_at,
        "finishedAt": now_kst_iso(),
        "status": "healthy" if not cdp_res.get("failedPorts") else "degraded",
        "server": server_res,
        "cdpBrowsers": {
            "onlineCount": cdp_res.get("onlineCount", 0),
            "totalRequired": cdp_res.get("totalRequired", 7),
            "recoveredPorts": cdp_res.get("recoveredPorts", []),
            "failedPorts": cdp_res.get("failedPorts", []),
        },
        "zombieRecoveries": zombie_actions,
        "missedSlotCatchups": catchup_actions,
        "appTrackTruth": app_track_truth,
        "projectHealthSummary": project_audit_summary,
        "broadcastedToChat": broadcasted,
    }
    try:
        save_json(WATCHDOG_STATUS_PATH, report)
    except Exception:
        pass

    # Mirror real-time state files to NAS directory so NAS dashboard stays 100% updated
    try:
        nas_sync = sync_data_to_nas()
        report["nasDashboardSync"] = nas_sync
    except Exception:
        pass

    if cdp_res.get('recoveredPorts') or server_res.get('recovered'):
        from common.llm_client import memory_event
        memory_event('watchdog:' + started_at, 'infrastructure_repair',
                     'Infrastructure probe recovered; this does not establish pipeline publication success.',
                     evidence={'recoveredPorts': cdp_res.get('recoveredPorts', []),
                               'serverRecovered': bool(server_res.get('recovered'))}, review=False)
    return report


def sync_data_to_nas() -> Dict[str, Any]:
    """Mirror real-time local state files to NAS directory so the NAS dashboard stays up to date."""
    nas_root = Path(r"\\otns\yoonlab\10_Project\BaroLab")
    if not nas_root.exists() or ROOT.drive.lower() != 'c:':
        return {"synced": False, "reason": "NAS path inaccessible or not on local C:"}
    synced_files = []
    # NAS settings, commands, credentials and its live_snapshot are server-owned.
    # Only Windows observation files may cross this mirror; never deploy source.
    worker_observations = {
        'browser-status.json', 'watchdog-status.json', 'metrics.json', 'traffic.json',
        'revenue.json', 'collection-health.json', 'collection-watchdog.json',
        'metrics-runtime.json', 'kin-automation-state.json', 'kin-measurement.json',
        'threads-measurement.json', 'cf-retry-runtime.json', 'codex-runtime.json',
    }
    try:
        import shutil
        for folder in ("cf_posting/data", "server/data"):
            src_dir = ROOT / folder
            dst_dir = nas_root / folder
            if not src_dir.exists():
                continue
            dst_dir.mkdir(parents=True, exist_ok=True)
            for file_path in src_dir.glob("*.json"):
                if folder == 'server/data' and file_path.name not in worker_observations:
                    continue
                dst_file = dst_dir / file_path.name
                if not dst_file.exists() or file_path.stat().st_mtime > dst_file.stat().st_mtime:
                    try:
                        shutil.copy2(file_path, dst_file)
                        synced_files.append(f"{folder}/{file_path.name}")
                    except Exception:
                        pass
            for file_path in src_dir.glob("*.js"):
                if folder == 'server/data':
                    continue
                dst_file = dst_dir / file_path.name
                if not dst_file.exists() or file_path.stat().st_mtime > dst_file.stat().st_mtime:
                    try:
                        shutil.copy2(file_path, dst_file)
                        synced_files.append(f"{folder}/{file_path.name}")
                    except Exception:
                        pass
        return {"synced": True, "count": len(synced_files), "files": synced_files}
    except Exception as exc:
        return {"synced": False, "error": str(exc)}


def register_watchdog_scheduled_task() -> Dict[str, Any]:
    """Register BaroLab-System-Watchdog in Windows Task Scheduler (every 10m) + Windows Startup folder (AtLogon)."""
    if os.name != "nt":
        return {"ok": False, "reason": "Windows only"}
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    script_path = Path(__file__).resolve()
    task_name = "BaroLab-System-Watchdog"
    tr_cmd = f'"{pythonw}" -B -X utf8 "{script_path}" --run --source task-scheduler'

    # 1. Register 10-minute recurring task via schtasks (works without admin elevation)
    create_res = subprocess.run(
        [
            "schtasks",
            "/Create",
            "/TN",
            task_name,
            "/TR",
            tr_cmd,
            "/SC",
            "MINUTE",
            "/MO",
            "10",
            "/F",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )

    # 2. Also create AtLogon / Startup launcher in user's Windows Startup folder
    startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_cmd_path = startup_dir / "BaroLab-System-Watchdog-Boot.cmd"
    startup_installed = False
    try:
        if startup_dir.exists():
            startup_content = (
                "@echo off\r\n"
                f'start "" "{pythonw}" -B -X utf8 "{script_path}" --run --source logon-startup\r\n'
            )
            startup_cmd_path.write_text(startup_content, encoding="utf-8")
            startup_installed = True
    except Exception:
        pass

    return {
        "ok": create_res.returncode == 0,
        "taskName": task_name,
        "schedule": "Every 10 minutes + Windows Logon Startup",
        "startupScript": str(startup_cmd_path) if startup_installed else None,
        "stdout": (create_res.stdout or "").strip()[:300],
        "stderr": (create_res.stderr or "").strip()[:300],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BaroLab Unmanned System Watchdog")
    parser.add_argument("--run", action="store_true", help="Run a full watchdog pass")
    parser.add_argument("--heal-now", action="store_true", help="Immediate self-healing pass across ports, locks, slots, and apps")
    parser.add_argument("--register-task", action="store_true", help="Register Windows Scheduled Task")
    parser.add_argument("--source", default="cli", help="Trigger source label")
    args = parser.parse_args()

    if args.register_task:
        reg = register_watchdog_scheduled_task()
        print(json.dumps(reg, ensure_ascii=False, indent=2))
        if not (args.run or args.heal_now):
            return 0 if reg.get("ok") else 1

    src = "heal-now" if args.heal_now and args.source == "cli" else args.source
    report = run_system_watchdog(trigger_source=src, broadcast=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
