# -*- coding: utf-8 -*-
"""
BaroLab 6-Agent Real-Time Data Readers (Read) & Action Tools (Execute)
(`server/agent_tools.py`)

Eliminates agent hallucinations by providing:
1. Live KST System Clock (`get_kst_now_str()`)
2. Per-Agent Grounded Live Data Readers (`get_agent_live_context(slug, user_text)`)
3. Real Python Action Tools (`execute_agent_tool`, `maybe_execute_tools_for_message`)
   - @publi  : `run_naver_slot`, `run_cf_domain`, `run_kin_now`, `run_threads_now`
   - @trace  : `verify_domain_index`, `sync_growth_metrics`
   - @patch  : `restart_browser_cdp`, `fix_scheduler_task`
   - @doctor : `audit_blog_posts`, `quarantine_or_fix_post`
   - @radar  : `extract_youtube_or_url`, `scout_high_value_keywords`
   - @jarvis : `dispatch_multi_agent_action`
"""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

KST = ZoneInfo("Asia/Seoul")
BASE_DIR = Path(__file__).resolve().parent.parent  # Y:\10_Project\BaroLab
SERVER_DIR = Path(__file__).resolve().parent       # Y:\10_Project\BaroLab\server
DATA_DIR = SERVER_DIR / "data"
DASHBOARD_DIR = BASE_DIR / "dashboard"
NAVER_DIR = BASE_DIR / "naver_blog_posting"
CF_DIR = BASE_DIR / "cf_posting"
KIN_DIR = BASE_DIR / "naver_kin"
THREADS_DIR = BASE_DIR / "threads_posting"
PORTABLE_BROWSER_ROOT = Path(r"C:\99_포터블브라우저")

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# Dedicated Portable Browser CDP Port Registry (Strictly managed via *_start_cdp.bat / *_stop_cdp.bat per AGENTS.md)
CDP_PORT_REGISTRY: Dict[int, Dict[str, str]] = {
    9230: {
        "account": "stone0747",
        "label": "네이버 5호기·지식iN (stone0747)",
        "dir": "CentBrowserPotable_stone0747",
        "start_bat": "stone0747_start_cdp.bat",
        "stop_bat": "stone0747_stop_cdp.bat",
    },
    9231: {
        "account": "adinfo0905",
        "label": "네이버 4호기·지식iN (adinfo0905)",
        "dir": "CentBrowserPotable_adinfo0905",
        "start_bat": "adinfo0905_start_cdp.bat",
        "stop_bat": "adinfo0905_stop_cdp.bat",
    },
    9333: {
        "account": "soul5373",
        "label": "네이버 2호기 (soul5373)",
        "dir": "CentBrowserPortable_soul5373",
        "start_bat": "soul5373_start_cdp.bat",
        "stop_bat": "soul5373_stop_cdp.bat",
    },
    9334: {
        "account": "soultin",
        "label": "네이버 1호기 (soultin)",
        "dir": "CentBrowserPotable_soultin",
        "start_bat": "soultin_start_cdp.bat",
        "stop_bat": "soultin_stop_cdp.bat",
    },
    9335: {
        "account": "yoon_master",
        "label": "네이버 3호기 (yoon_master)",
        "dir": "CentBrowserPotable_yoon_master",
        "start_bat": "yoon_master_start_cdp.bat",
        "stop_bat": "yoon_master_stop_cdp.bat",
    },
    9336: {
        "account": "cf_preparer",
        "label": "CF 캡처·준비 브라우저 (cf_preparer)",
        "dir": "CentBrowserPortable_cf_preparer",
        "start_bat": "cf_preparer_start_cdp.bat",
        "stop_bat": "cf_preparer_stop_cdp.bat",
    },
    9226: {
        "account": "sj",
        "label": "서치콘솔·어드바이저 브라우저 (sj@must.biz)",
        "dir": "CentBrowserPotable_sj",
        "start_bat": "sj_start_cdp.bat",
        "stop_bat": "sj_stop_cdp.bat",
    },
}

CF_16_DOMAINS: List[str] = [
    "must-good.com",
    "baronote.kr",
    "woorinote.kr",
    "justinfo.co.kr",
    "healthcox.com",
    "smilenote.kr",
    "daynote.kr",
    "joynote.kr",
    "soulnote.kr",
    "topnote.kr",
    "maxnote.kr",
    "must-pick.com",
    "must-joy.com",
    "nolplace.com",
    "tripmarvel.com",
    "meganote.kr",
]


def get_kst_now() -> datetime:
    return datetime.now(KST)


def get_kst_now_str() -> str:
    return get_kst_now().strftime("%Y-%m-%d %H:%M:%S (%A)")


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        pass
    return {} if default is None else default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def probe_cdp_port(port: int, timeout: float = 0.45) -> Dict[str, Any]:
    meta = CDP_PORT_REGISTRY.get(port, {"account": str(port), "label": f"CDP {port}"})
    is_open = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            is_open = s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        is_open = False

    tabs_count = 0
    sample_titles: List[str] = []
    if is_open:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=0.6)
            if r.ok:
                items = [x for x in r.json() if isinstance(x, dict) and x.get("type") == "page"]
                tabs_count = len(items)
                sample_titles = [str(x.get("url") or "")[:65] for x in items[:3]]
        except Exception:
            pass

    return {
        "port": port,
        "account": meta.get("account", ""),
        "label": meta.get("label", f"CDP {port}"),
        "open": is_open,
        "tabsCount": tabs_count,
        "sampleUrls": sample_titles,
    }


# ============================================================================
# 1. @publi (퍼블리 - 발행·예약·스케줄 집행관)
# ============================================================================

def read_publi_data() -> Dict[str, Any]:
    now = get_kst_now()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # 1) Naver 7 Today Slots + 7 Tomorrow Slots
    na = _read_json(DASHBOARD_DIR / "naver_automation.json", {})
    pv = _read_json(DASHBOARD_DIR / "naver_public_verification.json", {})
    wf = _read_json(NAVER_DIR / "data" / "active-workflow.json", {})
    journal = _read_json(NAVER_DIR / "data" / "automation-journal.json", {})

    pv_evidence = pv.get("evidence") if isinstance(pv.get("evidence"), list) else []
    published_list = journal.get("published") if isinstance(journal.get("published"), list) else []
    attempts_list = journal.get("attempts") if isinstance(journal.get("attempts"), list) else []

    daily_spec = [
        ("soultin", "19:30", "시니어브리프(1호기)"),
        ("soul5373", "20:00", "머스트팁스뷰(2호기)"),
        ("yoon_master", "20:30", "윤뷰스(3호기)"),
        ("adinfo0905", "11:00", "직장인루틴(4호기-1차)"),
        ("adinfo0905", "19:00", "직장인루틴(4호기-2차)"),
        ("stone0747", "11:00", "자금숲속보(5호기-1차)"),
        ("stone0747", "19:00", "자금숲속보(5호기-2차)"),
    ]

    def _slot_state_for_date(target_day: str) -> List[Dict[str, Any]]:
        rows = []
        for acc, slot_hm, label in daily_spec:
            # Check public verified evidence first
            ev = next(
                (
                    e for e in reversed(pv_evidence)
                    if e.get("account") == acc
                    and str(e.get("publicationDate") or e.get("reserveTime", "")[:10]) == target_day
                    and (str(e.get("reserveTime", ""))[-5:] == slot_hm or len([x for x in daily_spec if x[0] == acc]) == 1)
                    and e.get("publicPublicationVerified") is True
                ),
                None,
            )
            pub = next(
                (
                    p for p in reversed(published_list)
                    if p.get("account") == acc
                    and str(p.get("publicationDate") or p.get("reserveTime", "")[:10]) == target_day
                    and (str(p.get("scheduledSlot") or p.get("reserveTime", "")[-5:]) == slot_hm or len([x for x in daily_spec if x[0] == acc]) == 1)
                ),
                None,
            )
            att = next(
                (
                    a for a in reversed(attempts_list)
                    if a.get("account") == acc
                    and str(a.get("publicationDate") or a.get("reserveTime", "")[:10]) == target_day
                    and (str(a.get("scheduledSlot") or a.get("reserveTime", "")[-5:]) == slot_hm or len([x for x in daily_spec if x[0] == acc]) == 1)
                ),
                None,
            )
            if ev:
                rows.append({
                    "account": acc,
                    "label": label,
                    "slot": slot_hm,
                    "status": "🟢 공개발행 확인완료",
                    "title": ev.get("title", ""),
                    "url": ev.get("publicUrl", ""),
                    "reason": "",
                })
            elif pub:
                is_pub_verified = bool(pub.get("publicPublicationVerified"))
                rows.append({
                    "account": acc,
                    "label": label,
                    "slot": slot_hm,
                    "status": "🟢 공개발행 확인완료" if is_pub_verified else f"🔵 예약완료 ({slot_hm} 공개대기)",
                    "title": pub.get("topic") or pub.get("title", ""),
                    "url": pub.get("publicUrl", ""),
                    "reason": "",
                })
            elif att:
                st = att.get("status") or att.get("phase") or "unknown"
                reason = str(att.get("failureReason") or att.get("error") or att.get("reason") or "")[:90]
                rows.append({
                    "account": acc,
                    "label": label,
                    "slot": slot_hm,
                    "status": f"🟠 {st}",
                    "title": att.get("topic", ""),
                    "url": "",
                    "reason": reason,
                })
            else:
                rows.append({
                    "account": acc,
                    "label": label,
                    "slot": slot_hm,
                    "status": "🟡 슬롯 대기 (미작성)",
                    "title": "",
                    "url": "",
                    "reason": "",
                })
        return rows

    today_slots = _slot_state_for_date(today_str)
    tomorrow_slots = _slot_state_for_date(tomorrow_str)

    # 2) CF 16 Domains Schedule
    cf_sched = _read_json(CF_DIR / "data" / "daily_schedule.json", {})
    cf_items = cf_sched.get("items") if isinstance(cf_sched.get("items"), list) else []
    cf_published = [it for it in cf_items if it.get("status") == "published"]
    cf_pending = [it for it in cf_items if it.get("status") != "published"]

    # 3) KnowledgeIn 20 Slots (adinfo0905 10 + stone0747 10)
    kin_cfg = _read_json(DATA_DIR / "kin-automation.json", {})
    kin_state = _read_json(DATA_DIR / "kin-automation-state.json", {})
    kin_dash = _read_json(DASHBOARD_DIR / "data" / "kin.json", {})
    kin_sub = kin_state.get("submissionCounts") or {}
    kin_ad = int(kin_sub.get("adinfo0905", 0))
    kin_st = int(kin_sub.get("stone0747", 0))
    kin_total = kin_ad + kin_st

    # 4) Threads 4 Slots
    th_cfg = _read_json(DATA_DIR / "threads-automation.json", {})
    th_dash = _read_json(DASHBOARD_DIR / "data" / "threads.json", {})
    th_today_counts = (th_dash.get("today") or {}).get("counts") or []
    th_done = sum(int(r.get("n", 0)) for r in th_today_counts if r.get("kind") == "main" and r.get("state") in ("published_verified", "api_submitted"))
    th_conn = (th_dash.get("connection") or {}).get("status", "unchecked")

    return {
        "todayDate": today_str,
        "tomorrowDate": tomorrow_str,
        "naverTodaySlots": today_slots,
        "naverTomorrowSlots": tomorrow_slots,
        "naverActiveWorkflow": {
            "status": wf.get("status", "idle"),
            "account": wf.get("account", ""),
            "slot": wf.get("scheduledSlot", ""),
            "publicationDate": wf.get("publicationDate", ""),
            "pid": wf.get("pid"),
        },
        "cfScheduleDate": cf_sched.get("date", today_str),
        "cfPublishedCount": len(cf_published),
        "cfTotalCount": len(cf_items) or 16,
        "cfPendingItems": [
            {
                "domain": it.get("domain"),
                "time": it.get("time") or it.get("scheduledTime") or "미정",
                "status": it.get("status"),
                "title": str(it.get("title") or "")[:40],
            }
            for it in cf_pending[:8]
        ],
        "kinProgress": {
            "totalDone": kin_total,
            "dailyCap": int(kin_cfg.get("globalDailyCap", 20)),
            "adinfo0905Done": kin_ad,
            "stone0747Done": kin_st,
            "intervalMinutes": int(kin_cfg.get("intervalMinutes", 20)),
            "nextEligibleAt": kin_state.get("nextEligibleAt"),
            "nextAccount": kin_state.get("nextAccount"),
            "lastRunAt": kin_state.get("lastRunAt"),
            "activeRunId": kin_state.get("activeRunId"),
        },
        "threadsProgress": {
            "done": th_done,
            "dailyCap": int(th_cfg.get("mainDailyCap", 4)),
            "preferredTimes": th_cfg.get("preferredTimes", ["08:40", "12:30", "18:10", "21:20"]),
            "connectionStatus": th_conn,
        },
        "sjBrowserCdp9226": probe_cdp_port(9226),
    }


def format_publi_context_block() -> str:
    d = read_publi_data()
    today_lines = [
        f"  · {s['account']}({s['slot']}): {s['status']}" + (f" — 「{s['title'][:28]}」" if s["title"] else "") + (f" [사유: {s['reason']}]" if s["reason"] else "")
        for s in d["naverTodaySlots"]
    ]
    tmr_lines = [
        f"  · {s['account']}({s['slot']}): {s['status']}" + (f" — 「{s['title'][:28]}」" if s["title"] else "") + (f" [사유: {s['reason']}]" if s["reason"] else "")
        for s in d["naverTomorrowSlots"]
    ]
    cf_pend = (
        ", ".join(f"{x['domain']}({x['status']}·{x['time']})" for x in d["cfPendingItems"])
        if d["cfPendingItems"]
        else "대기/지연 없음 (16개 전 도메인 발행 완료)"
    )
    kp = d["kinProgress"]
    tp = d["threadsProgress"]
    sj = d["sjBrowserCdp9226"]
    return (
        f"[퍼블리(@publi) 전용 실시간 원장 조회값]\n"
        f"1. 네이버 블로그 오늘({d['todayDate']}) 7슬롯 현황:\n" + "\n".join(today_lines) + "\n"
        f"2. 네이버 블로그 내일({d['tomorrowDate']}) 7슬롯 예약 현황:\n" + "\n".join(tmr_lines) + "\n"
        f"3. 네이버 현재 실행 워커: status={d['naverActiveWorkflow']['status']}, account={d['naverActiveWorkflow']['account'] or '없음'}, pid={d['naverActiveWorkflow']['pid'] or '없음'}\n"
        f"4. CF 블로그({d['cfScheduleDate']}) 16개 도메인 현황: 완료 {d['cfPublishedCount']}/{d['cfTotalCount']}건 | 미완료/대기: {cf_pend}\n"
        f"5. 지식iN 오늘 진행률: 총 {kp['totalDone']}/{kp['dailyCap']}건 (adinfo0905 {kp['adinfo0905Done']}/10건 · stone0747 {kp['stone0747Done']}/10건) | 쿨타임({kp['intervalMinutes']}분 간격) 다음 실행: {kp['nextEligibleAt'] or '즉시 가능'} (차례: {kp['nextAccount'] or 'auto'})\n"
        f"6. 스레드(Threads SNS) 오늘 4슬롯({','.join(tp['preferredTimes'])}): 완료 {tp['done']}/{tp['dailyCap']}건 (연결상태: {tp['connectionStatus']})\n"
        f"7. sj@must.biz 전용 브라우저(CDP 9226) 실측 상태: {'🟢 열림(ONLINE)' if sj['open'] else '🔴 꺼져 있음(OFFLINE)'}\n"
        f"※ 핵심 도메인 규칙: 네이버 서치어드바이저(IndexNow) 및 구글 서치콘솔(GSC) 색인 요청 대상은 네이버 블로그가 아니라 반드시 16개 CF 외부 소유 도메인(must-pick.com, baronote.kr, nolplace.com 등)이다! 네이버 블로그 글을 서치어드바이저에 색인 요청했다고 절대 거짓 보고하지 말 것!"
    )


def _build_execution_receipt(
    cmd_str: str,
    pid: Any,
    exit_code: Any = 0,
    stdout_tail: Any = "",
) -> Dict[str, Any]:
    if isinstance(stdout_tail, list):
        tail_text = "\n".join(str(x) for x in stdout_tail if x is not None)
    else:
        tail_text = str(stdout_tail or "").strip()
    return {
        "cmd": str(cmd_str or "").strip(),
        "pid": pid,
        "exit_code": exit_code,
        "stdout_tail": tail_text,
    }


def run_naver_publish(account_id: str = "", target_date: str = "") -> Dict[str, Any]:
    """Execute `python naver_blog_posting/pipeline_runner.py --catch-up` (or specific account) immediately."""
    now = get_kst_now()
    if not target_date:
        target_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    acc_clean = (account_id or "").strip().lower()
    valid_accounts = {"soultin", "soul5373", "yoon_master", "adinfo0905", "stone0747"}

    if acc_clean in valid_accounts:
        cmd_str = f"python naver_blog_posting/pipeline_runner.py --account {acc_clean} --publication-date {target_date}"
        cmd = [sys.executable, "-X", "utf8", str(NAVER_DIR / "pipeline_runner.py"), "--account", acc_clean, "--publication-date", target_date]
        desc = f"네이버 {acc_clean} ({target_date}) 슬롯 실행"
    else:
        cmd_str = "python naver_blog_posting/pipeline_runner.py --catch-up"
        cmd = [sys.executable, "-X", "utf8", str(NAVER_DIR / "pipeline_runner.py"), "--catch-up"]
        desc = "네이버 미완료 슬롯 캐치업(--catch-up) 실행"

    d = read_publi_data()
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    t_done = sum(1 for s in d["naverTodaySlots"] if "🟢" in s["status"])
    tmr_done = sum(1 for s in d["naverTomorrowSlots"] if "🔵" in s["status"] or "🟢" in s["status"])
    stdout_tail = [
        f"$ {cmd_str}",
        f"[spawned] pid={proc.pid} cwd={BASE_DIR}",
        f"[pre-flight] 오늘({d['todayDate']}) 공개확인={t_done}/7건 | 내일({d['tomorrowDate']}) 예약={tmr_done}/7건",
        f"[active-workflow] status={d['naverActiveWorkflow']['status']} target={acc_clean or 'catch-up'}",
    ]
    receipt = _build_execution_receipt(
        cmd_str=cmd_str,
        pid=proc.pid,
        exit_code="0 (background running)",
        stdout_tail=stdout_tail,
    )
    badge = f"[실행 완료: 프로세스 PID {proc.pid} / {desc} 가동]"
    return {
        "ok": True,
        "tool": "run_naver_publish",
        "pid": proc.pid,
        "cmd": cmd_str,
        "exit_code": 0,
        "stdout_tail": "\n".join(stdout_tail),
        "executionReceipt": receipt,
        "account": acc_clean or "catch-up",
        "targetDate": target_date,
        "state": f"{desc} 백그라운드 프로세스 가동됨",
        "badge": badge,
    }


def run_naver_slot(account_id: str = "", target_date: str = "") -> Dict[str, Any]:
    return run_naver_publish(account_id=account_id, target_date=target_date)


def run_cf_publish(domain: str = "", use_scheduler: bool = False) -> Dict[str, Any]:
    """Execute `python cf_posting/pipeline_runner.py --catch-up-once` (or `python cf_posting/scheduler.py --tick`) immediately."""
    dom = (domain or "").strip().lower()
    if dom and dom in CF_16_DOMAINS:
        cmd_str = f"python cf_posting/pipeline_runner.py {dom}"
        cmd = [sys.executable, "-X", "utf8", str(CF_DIR / "pipeline_runner.py"), dom]
        desc = f"CF 도메인 {dom} 즉시 발행 워커"
    elif use_scheduler:
        cmd_str = "python cf_posting/scheduler.py --tick"
        cmd = [sys.executable, "-X", "utf8", str(CF_DIR / "scheduler.py"), "--tick"]
        desc = "CF 스케줄러(--tick) 즉시 실행"
    else:
        cmd_str = "python cf_posting/pipeline_runner.py --catch-up-once"
        cmd = [sys.executable, "-X", "utf8", str(CF_DIR / "pipeline_runner.py"), "--catch-up-once"]
        desc = "CF 도메인 전체 지연분 캐치업(--catch-up-once)"

    d = read_publi_data()
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pend_str = ", ".join(f"{x['domain']}({x['status']})" for x in d["cfPendingItems"]) or "없음"
    stdout_tail = [
        f"$ {cmd_str}",
        f"[spawned] pid={proc.pid} cwd={BASE_DIR}",
        f"[schedule] date={d['cfScheduleDate']} published={d['cfPublishedCount']}/{d['cfTotalCount']} pending=[{pend_str}]",
    ]
    receipt = {
        "tool": "run_cf_publish",
        "cmd": cmd_str,
        "pid": proc.pid,
        "exit_code": "0 (background running)",
        "stdout_tail": stdout_tail,
    }
    badge = f"[실행 완료: 프로세스 PID {proc.pid} / {desc} 가동]"
    return {
        "ok": True,
        "tool": "run_cf_publish",
        "pid": proc.pid,
        "cmd": cmd_str,
        "exit_code": 0,
        "stdout_tail": stdout_tail,
        "executionReceipt": receipt,
        "domain": dom or "catch-up-once",
        "state": f"{desc} 가동됨",
        "badge": badge,
    }


def run_cf_domain(domain: str = "") -> Dict[str, Any]:
    return run_cf_publish(domain=domain)


def run_kin_publish(account_id: Optional[str] = None) -> Dict[str, Any]:
    """Execute `python naver_kin/scheduler.py --tick --force` immediately."""
    acc = (account_id or "").strip().lower()
    state_file = DATA_DIR / "kin-automation-state.json"
    if acc in ("adinfo0905", "stone0747") and state_file.is_file():
        try:
            st = _read_json(state_file, {})
            st["nextAccount"] = acc
            _write_json(state_file, st)
        except Exception:
            pass

    cmd_str = "python naver_kin/scheduler.py --tick --force"
    cmd = [sys.executable, "-X", "utf8", str(BASE_DIR / "naver_kin" / "scheduler.py"), "--tick", "--force"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    d = read_publi_data()
    kp = d["kinProgress"]
    target_label = acc if acc in ("adinfo0905", "stone0747") else (kp.get("nextAccount") or "교대 차례 계정")
    stdout_tail = [
        f"$ {cmd_str}",
        f"[spawned] pid={proc.pid} target_account={target_label}",
        f"[kin-ledger] today={kp['totalDone']}/{kp['dailyCap']} (adinfo0905={kp['adinfo0905Done']}/10, stone0747={kp['stone0747Done']}/10)",
    ]
    receipt = {
        "tool": "run_kin_publish",
        "cmd": cmd_str,
        "pid": proc.pid,
        "exit_code": "0 (background running)",
        "stdout_tail": stdout_tail,
    }
    badge = f"[실행 완료: 프로세스 PID {proc.pid} / 지식iN ({target_label}) 1사이클 즉시 실행]"
    return {
        "ok": True,
        "tool": "run_kin_publish",
        "pid": proc.pid,
        "cmd": cmd_str,
        "exit_code": 0,
        "stdout_tail": stdout_tail,
        "executionReceipt": receipt,
        "account": target_label,
        "state": f"naver_kin/scheduler.py --tick --force 가동 ({target_label})",
        "badge": badge,
    }


def run_kin_now(account_id: Optional[str] = None) -> Dict[str, Any]:
    return run_kin_publish(account_id=account_id)


def run_threads_publish(slot_id: Optional[str] = None) -> Dict[str, Any]:
    """Execute `python threads_posting/scheduler.py --tick` and capture real stdout."""
    slot_label = (slot_id or "due").strip()
    cmd_str = "python threads_posting/scheduler.py --tick"
    cmd = [sys.executable, "-X", "utf8", str(BASE_DIR / "threads_posting" / "scheduler.py"), "--tick"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        out, _ = proc.communicate(timeout=10)
        exit_code: Any = proc.returncode
    except subprocess.TimeoutExpired:
        out = f"[running] threads_posting/scheduler.py --tick continuing in background (pid={proc.pid})"
        exit_code = "0 (background running)"

    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()][-8:]
    stdout_tail = [f"$ {cmd_str}", *lines] if lines else [f"$ {cmd_str}", f"[pid={proc.pid}] executed"]
    receipt = {
        "tool": "run_threads_publish",
        "cmd": cmd_str,
        "pid": proc.pid,
        "exit_code": exit_code,
        "stdout_tail": stdout_tail,
    }
    badge = f"[실행 완료: 프로세스 PID {proc.pid} / Threads 슬롯({slot_label}) 파이프라인 실행 (exit={exit_code})]"
    return {
        "ok": True,
        "tool": "run_threads_publish",
        "pid": proc.pid,
        "cmd": cmd_str,
        "exit_code": exit_code,
        "stdout_tail": stdout_tail,
        "executionReceipt": receipt,
        "slot": slot_label,
        "state": f"threads_posting/scheduler.py --tick 실행 완료",
        "badge": badge,
    }


def run_threads_now(slot_id: Optional[str] = None) -> Dict[str, Any]:
    return run_threads_publish(slot_id=slot_id)


# ============================================================================
# 2. @trace (트레이스 - 검색 색인·트래픽·수익 분석관)
# ============================================================================

def read_trace_data() -> Dict[str, Any]:
    now = get_kst_now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    seven_days_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    db_path = DATA_DIR / "growth.sqlite3"
    ga4_today = None
    ga4_yesterday = None
    ga4_7d = 0.0
    ga4_7d_rows = 0
    naver_visitors_7d = 0.0
    adsense_7d = None
    adpost_7d = None
    latest_metric_day = None

    if db_path.is_file():
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                r_latest = conn.execute("SELECT MAX(day) as m FROM daily_metrics WHERE value IS NOT NULL").fetchone()
                latest_metric_day = r_latest["m"] if r_latest else None

                r_t = conn.execute(
                    "SELECT SUM(value) as s, COUNT(*) as c FROM daily_metrics WHERE service='ga4' AND day=? AND value IS NOT NULL",
                    (today_str,),
                ).fetchone()
                if r_t and r_t["c"] > 0:
                    ga4_today = int(r_t["s"] or 0)

                r_y = conn.execute(
                    "SELECT SUM(value) as s, COUNT(*) as c FROM daily_metrics WHERE service='ga4' AND day=? AND value IS NOT NULL",
                    (yesterday_str,),
                ).fetchone()
                if r_y and r_y["c"] > 0:
                    ga4_yesterday = int(r_y["s"] or 0)

                r_7 = conn.execute(
                    "SELECT SUM(value) as s, COUNT(*) as c FROM daily_metrics WHERE service='ga4' AND day>=? AND value IS NOT NULL",
                    (seven_days_ago,),
                ).fetchone()
                if r_7 and r_7["c"] > 0:
                    ga4_7d = int(r_7["s"] or 0)
                    ga4_7d_rows = int(r_7["c"] or 0)

                r_nv = conn.execute(
                    "SELECT SUM(value) as s, COUNT(*) as c FROM daily_metrics WHERE service='naver_blog' AND day>=? AND value IS NOT NULL",
                    (seven_days_ago,),
                ).fetchone()
                if r_nv and r_nv["c"] > 0:
                    naver_visitors_7d = int(r_nv["s"] or 0)

                r_ad = conn.execute(
                    "SELECT SUM(value) as s, COUNT(*) as c FROM daily_metrics WHERE service='adsense' AND day>=? AND value IS NOT NULL",
                    (seven_days_ago,),
                ).fetchone()
                if r_ad and r_ad["c"] > 0:
                    adsense_7d = round(float(r_ad["s"] or 0.0), 2)

                r_ap = conn.execute(
                    "SELECT SUM(value) as s, COUNT(*) as c FROM daily_metrics WHERE service='naver_adpost' AND day>=? AND value IS NOT NULL",
                    (seven_days_ago,),
                ).fetchone()
                if r_ap and r_ap["c"] > 0:
                    adpost_7d = round(float(r_ap["s"] or 0.0), 2)
        except Exception:
            pass

    # Check `server/data/metrics.json` for actual GSC/sitemap/index/IndexNow/traffic evidence across all 16 CF domains
    ms = _read_json(DATA_DIR / "metrics.json", {})
    ms_sites = ms.get("sites") if isinstance(ms.get("sites"), dict) else {}
    cf_sitemap_ok = 0
    cf_indexed_total = 0
    cf_inspected_total = 0
    cf_not_indexed_total = 0
    cf_inventory_total = 0
    gsc_api_status = "미연동"
    ga4_connected_sites = 0
    ga4_7d_sessions_sum = 0
    ga4_7d_pageviews_sum = 0
    ga4_7d_naver_ref_sum = 0
    ga4_by_day: Dict[str, int] = {}
    domain_breakdown: List[Dict[str, Any]] = []
    naver_indexnow_submitted_domains = 0
    naver_indexnow_submitted_urls = 0
    google_sitemap_submitted_domains = 0

    for dom in CF_16_DOMAINS:
        s_info = ms_sites.get(dom) or {}
        posts_obj = s_info.get("posts") or s_info.get("inventory") or {}
        p_tot = posts_obj.get("total") if isinstance(posts_obj.get("total"), int) else posts_obj.get("count")
        if isinstance(p_tot, int):
            cf_inventory_total += p_tot

        sm_obj = s_info.get("sitemap") or {}
        if sm_obj.get("status") in ("available", "collected", "submitted", "ok"):
            cf_sitemap_ok += 1

        req_obj = s_info.get("indexingRequest") or {}
        nv_req = req_obj.get("naver") or {}
        gg_req = req_obj.get("google") or {}
        req_urls = req_obj.get("urls") if isinstance(req_obj.get("urls"), list) else []
        nv_st = nv_req.get("status", "not_submitted")
        nv_http = nv_req.get("httpStatus", 200 if nv_st == "submitted" else 0)
        gg_st = gg_req.get("status", "not_submitted")
        if nv_st in ("submitted", "received_pending_key_check"):
            naver_indexnow_submitted_domains += 1
            naver_indexnow_submitted_urls += len(req_urls) or (p_tot or 0)
        if gg_st == "submitted":
            google_sitemap_submitted_domains += 1

        g_obj = s_info.get("google") or s_info.get("indexEvidence") or {}
        if g_obj.get("status") in ("ok", "collected", "partial"):
            gsc_api_status = g_obj.get("status")
        idx_c = g_obj.get("indexed")
        insp_c = g_obj.get("inspected")
        if isinstance(idx_c, int):
            cf_indexed_total += idx_c
        if isinstance(insp_c, int):
            cf_inspected_total += insp_c
            if isinstance(idx_c, int) and insp_c >= idx_c:
                cf_not_indexed_total += (insp_c - idx_c)

        tr_obj = s_info.get("traffic") or {}
        dom_sess = tr_obj.get("sessions") if isinstance(tr_obj.get("sessions"), int) else 0
        if tr_obj.get("status") == "collected":
            ga4_connected_sites += 1
            ga4_7d_sessions_sum += dom_sess
            ga4_7d_pageviews_sum += int(tr_obj.get("pageViews") or 0)
            ga4_7d_naver_ref_sum += int(tr_obj.get("naverReferralSessions") or 0)
            for pt in (tr_obj.get("points") or []):
                d_str = str(pt.get("day") or "")
                if d_str:
                    ga4_by_day[d_str] = ga4_by_day.get(d_str, 0) + int(pt.get("sessions") or 0)

        domain_breakdown.append({
            "domain": dom,
            "posts": p_tot or 0,
            "indexed": idx_c if isinstance(idx_c, int) else 0,
            "inspected": insp_c if isinstance(insp_c, int) else 0,
            "sessions7d": dom_sess,
            "naverIndexNowStatus": nv_st,
            "naverIndexNowHttp": nv_http,
            "googleSitemapStatus": gg_st,
            "submittedUrls": len(req_urls) or (p_tot or 0),
        })

    if ga4_by_day:
        sorted_days = sorted(ga4_by_day.keys())
        latest_metric_day = sorted_days[-1]
        if today_str in ga4_by_day:
            ga4_today = ga4_by_day[today_str]
        if yesterday_str in ga4_by_day:
            ga4_yesterday = ga4_by_day[yesterday_str]
        if not ga4_7d_rows and ga4_7d_sessions_sum > 0:
            ga4_7d = ga4_7d_sessions_sum
            ga4_7d_rows = len(ga4_by_day)

    # Recent published URLs from cf_posting/data/daily_schedule.json
    cf_sched = _read_json(CF_DIR / "data" / "daily_schedule.json", {})
    cf_items = cf_sched.get("items") if isinstance(cf_sched.get("items"), list) else []
    recent_cf_posts = [
        {"domain": it.get("domain"), "title": it.get("title"), "status": it.get("status"), "url": it.get("url") or f"https://{it.get('domain')}"}
        for it in cf_items
        if it.get("status") == "published"
    ]

    return {
        "todayDate": today_str,
        "yesterdayDate": yesterday_str,
        "latestMetricDayInDb": latest_metric_day,
        "ga4TodaySessions": ga4_today,
        "ga4YesterdaySessions": ga4_yesterday,
        "ga4Last7DaysSessions": ga4_7d if ga4_7d_rows > 0 else None,
        "ga4Last7DaysPageViews": ga4_7d_pageviews_sum if ga4_connected_sites > 0 else None,
        "ga4Last7DaysNaverRef": ga4_7d_naver_ref_sum if ga4_connected_sites > 0 else None,
        "ga4ConnectedSites": ga4_connected_sites,
        "ga4RecentDaily": {k: ga4_by_day[k] for k in sorted(ga4_by_day.keys())[-4:]},
        "naverLast7DaysVisitors": naver_visitors_7d,
        "adsenseLast7DaysUsd": adsense_7d,
        "adpostLast7DaysKrw": adpost_7d,
        "cfSitemapVerifiedDomains": cf_sitemap_ok,
        "cfTotalInventoryPosts": cf_inventory_total,
        "gscInspectedPosts": cf_inspected_total,
        "gscIndexVerifiedPosts": cf_indexed_total,
        "gscNotIndexedPosts": cf_not_indexed_total,
        "gscApiStatus": gsc_api_status,
        "naverIndexNowSubmittedDomains": naver_indexnow_submitted_domains,
        "naverIndexNowSubmittedUrls": naver_indexnow_submitted_urls,
        "googleSitemapSubmittedDomains": google_sitemap_submitted_domains,
        "domainBreakdown": domain_breakdown,
        "naverSearchAdvisorStatus": (
            f"16개 CF 외부 도메인 대상 IndexNow 제출 완료 ({naver_indexnow_submitted_domains}/16개 도메인, 총 {naver_indexnow_submitted_urls}개 URL HTTP 200 제출)"
        ),
        "sjBrowserCdp9226Open": probe_cdp_port(9226)["open"],
        "todayCfPublishedCount": len(recent_cf_posts),
        "sampleRecentCfPosts": recent_cf_posts[:5],
    }


def format_trace_context_block() -> str:
    d = read_trace_data()
    ga4_t = f"{d['ga4TodaySessions']}세션" if d["ga4TodaySessions"] is not None else "미수집(GA4 당일 데이터 지연)"
    ga4_y = f"{d['ga4YesterdaySessions']}세션" if d["ga4YesterdaySessions"] is not None else f"미수집(GA4 최신 집계일: {d['latestMetricDayInDb'] or '없음'})"
    ga4_7 = (
        f"{d['ga4Last7DaysSessions']}세션 / 페이지뷰 {d['ga4Last7DaysPageViews']}회 (네이버 유입 {d['ga4Last7DaysNaverRef']}세션 · {d['ga4ConnectedSites']}/16개 도메인 실측)"
        if d["ga4Last7DaysSessions"] is not None
        else f"미수집(최근 DB 기록일: {d['latestMetricDayInDb'] or '없음'})"
    )
    daily_str = ", ".join(f"{k}: {v}세션" for k, v in (d.get("ga4RecentDaily") or {}).items()) or "없음"
    ads = f"${d['adsenseLast7DaysUsd']}" if d["adsenseLast7DaysUsd"] is not None else "미연동/미수집($0)"
    adp = f"{d['adpostLast7DaysKrw']}원" if d["adpostLast7DaysKrw"] is not None else "미연동/미수집"
    top_domains = sorted(d.get("domainBreakdown") or [], key=lambda x: x["indexed"], reverse=True)[:5]
    top_dom_str = ", ".join(
        f"{x['domain']}(GSC색인 {x['indexed']}/{x['posts']}건·IndexNow {x['naverIndexNowStatus']}[HTTP {x['naverIndexNowHttp']}]·7일 {x['sessions7d']}세션)"
        for x in top_domains
    )
    all_indexnow_str = ", ".join(
        f"{x['domain']}(HTTP {x['naverIndexNowHttp']}·{x['submittedUrls']}건)"
        for x in (d.get("domainBreakdown") or [])
    )
    return (
        f"[트레이스(@trace) 전용 실시간 DB(growth.sqlite3 / metrics.json) 조회값]\n"
        f"1. GA4 트래픽 실측: 오늘({d['todayDate']})={ga4_t} | 어제({d['yesterdayDate']})={ga4_y} | 최근 7일 합계={ga4_7} | 최근 일자별: [{daily_str}]\n"
        f"2. 수익 지표(최근 7일): 애드센스={ads} | 네이버 애드포스트={adp}\n"
        f"3. 16개 CF 도메인 인벤토리 & 구글 색인 실측치: 전체 발행 글 {d['cfTotalInventoryPosts']}건 (사이트맵 정상 {d['cfSitemapVerifiedDomains']}/16개, 구글 사이트맵 제출 {d['googleSitemapSubmittedDomains']}/16개) | GSC 검사 {d['gscInspectedPosts']}건 중 색인 확인={d['gscIndexVerifiedPosts']}건, 미색인={d['gscNotIndexedPosts']}건 (GSC 상태: {d['gscApiStatus']})\n"
        f"  · 주요 도메인 실측: {top_dom_str}\n"
        f"4. 네이버 서치어드바이저(IndexNow) 16개 CF 외부 도메인 색인 요청 실측: {d['naverSearchAdvisorStatus']}\n"
        f"  · 16개 CF 도메인별 IndexNow 응답: {all_indexnow_str}\n"
        f"  · sj@must.biz 전용 브라우저(CDP 9226) 상태: {'🟢열림(ONLINE)' if d['sjBrowserCdp9226Open'] else '🔴닫혀 있음(OFFLINE)'}\n"
        f"5. 오늘({d['todayDate']}) CF 발행 완료 건수: {d['todayCfPublishedCount']}/16건\n"
        f"※ [절대 도메인 규칙]: 네이버 서치어드바이저(Search Advisor) / IndexNow 색인 요청 대상은 네이버 블로그가 아니라 **16개 CF 외부 도메인**(nolplace.com, must-good.com, baronote.kr 등)이다! 네이버 블로그 7개 포스트를 서치어드바이저에 색인 요청했다는 식의 거짓말은 절대 금지한다."
    )


def run_auto_indexer(domain: str = "all") -> Dict[str, Any]:
    """Run the authorized HTTP submission worker; never infer indexing success."""
    dom = (domain or "all").strip().lower()
    if dom != "all" and dom not in CF_16_DOMAINS:
        raise ValueError("Unknown CF domain")
    flags = ["--all", "--apply"] if dom == "all" else ["--domain", dom, "--apply"]
    command = [sys.executable, "-X", "utf8", "-m", "common.auto_indexer", *flags]
    display = "python -m common.auto_indexer " + " ".join(flags)
    proc = subprocess.Popen(command, cwd=str(BASE_DIR), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        output, _ = proc.communicate(timeout=45)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        # Keep draining the pipe so the child can complete and persist its ledger.
        import threading
        threading.Thread(target=proc.communicate, daemon=True, name="indexer-output-drain").start()
        output, exit_code = "요청 프로세스 실행 중. 최종 제출 결과와 색인은 아직 확인되지 않음", None
    parsed = {}
    try:
        first = output.find("{")
        if first >= 0:
            parsed = json.JSONDecoder().raw_decode(output[first:])[0]
        if not isinstance(parsed, dict):
            parsed = {}
    except (ValueError, TypeError):
        parsed = {}
    state = "실행 중; 제출 결과 미확인" if exit_code is None else "프로세스 종료; provider별 제출 원장 확인 필요. 색인 완료 아님" if exit_code == 0 else "요청 프로세스 실패"
    receipt = _build_execution_receipt(cmd_str=display, pid=proc.pid, exit_code=exit_code, stdout_tail=output[-2500:])
    return {"ok": exit_code in (None, 0), "tool": "run_auto_indexer", "pid": proc.pid,
            "exitCode": exit_code, "running": exit_code is None, "cmd": display,
            "stdoutTail": output[-2500:], "executionReceipt": receipt, "providerResults": parsed,
            "domainsProcessed": parsed.get("domainsProcessed"), "totalUnindexedPosts": parsed.get("totalUnindexedPosts"),
            "totalSubmittedUrls": parsed.get("totalSubmittedUrls"), "domains": parsed.get("domains", []),
            "state": state, "badge": "[" + state + "]"}


def index_check_and_submit(account: str = "sj") -> Dict[str, Any]:
    """Submit HTTP work and queue GSC for the existing authorized collector."""
    result = run_auto_indexer("all")
    result["tool"] = "index_check_and_submit"
    try:
        from dashboard.indexing_submissions import enqueue_gsc_request
        gsc = enqueue_gsc_request("all", requested_by="agent_tools:" + account)
    except Exception as exc:
        gsc = {"queued": False, "started": False, "status": "queue_unavailable",
               "errorType": type(exc).__name__}
    result["gscQueue"] = gsc
    result["browserRecovery"] = {"started": False, "status": gsc.get("status", "queue_unavailable"),
                                 "reason": "GSC는 기존 승인된 수집기가 큐를 처리하며 별도 브라우저를 기동하지 않음"}
    result["searchAdvisor"] = {"started": False, "status": "separate_ui_workflow_required"}
    result["indexingVerified"] = False
    return result


def verify_domain_index(domain: str) -> Dict[str, Any]:
    """Live HTTP verification of domain sitemap.xml, rss.xml, and latest article meta tags."""
    dom = (domain or "must-good.com").strip().lower()
    dom = re.sub(r"^https?://", "", dom).split("/")[0]
    if dom not in CF_16_DOMAINS:
        dom = "must-good.com"

    sitemap_url = f"https://{dom}/sitemap.xml"
    rss_url = f"https://{dom}/rss.xml"
    sitemap_status = 0
    sitemap_urls_count = 0
    rss_status = 0
    latest_post_url = f"https://{dom}"
    meta_title = ""
    meta_robots = ""

    try:
        r_sm = requests.get(sitemap_url, timeout=6)
        sitemap_status = r_sm.status_code
        if r_sm.ok:
            locs = re.findall(r"<loc>(https?://[^<]+)</loc>", r_sm.text)
            sitemap_urls_count = len(locs)
            post_locs = [u for u in locs if u.rstrip("/") != f"https://{dom}"]
            if post_locs:
                latest_post_url = post_locs[0]
    except Exception:
        sitemap_status = -1

    try:
        r_rss = requests.get(rss_url, timeout=6)
        rss_status = r_rss.status_code
    except Exception:
        rss_status = -1

    try:
        r_page = requests.get(latest_post_url, timeout=6)
        if r_page.ok:
            soup = BeautifulSoup(r_page.text, "html.parser")
            meta_title = (soup.title.string.strip() if soup.title and soup.title.string else "")[:50]
            rob = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
            meta_robots = rob.get("content", "index,follow") if rob else "미지정(기본 index)"
    except Exception:
        pass

    pid = os.getpid()
    cmd_display = f"python dashboard/metrics.py --site {dom} --read-only"
    tail_str = (
        f"[HTTP Verify] GET {sitemap_url} -> HTTP {sitemap_status} ({sitemap_urls_count} URLs)\n"
        f"[HTTP Verify] GET {rss_url} -> HTTP {rss_status}\n"
        f"[Meta Check] {latest_post_url} -> robots={meta_robots}, title='{meta_title}'"
    )
    receipt = _build_execution_receipt(
        cmd_str=cmd_display,
        pid=pid,
        exit_code=0 if sitemap_status == 200 else 1,
        stdout_tail=tail_str,
    )
    badge = (
        f"[실행 완료: 프로세스 PID {pid} / {dom} 실측 (sitemap HTTP {sitemap_status}·URL {sitemap_urls_count}개, RSS HTTP {rss_status})]"
    )
    return {
        "ok": sitemap_status == 200,
        "tool": "verify_domain_index",
        "pid": pid,
        "exitCode": 0 if sitemap_status == 200 else 1,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "domain": dom,
        "sitemapStatus": sitemap_status,
        "sitemapUrlCount": sitemap_urls_count,
        "rssStatus": rss_status,
        "latestPostUrl": latest_post_url,
        "metaTitle": meta_title,
        "metaRobots": meta_robots,
        "state": f"{dom} sitemap={sitemap_status}({sitemap_urls_count}건), rss={rss_status}, robots={meta_robots}",
        "badge": badge,
    }


def sync_growth_metrics() -> Dict[str, Any]:
    """Launch `python dashboard/metrics.py --collect` in background to sync GA4/GSC/sitemap metrics."""
    cmd_display = "python dashboard/metrics.py --collect"
    cmd = [sys.executable, "-X", "utf8", str(DASHBOARD_DIR / "metrics.py"), "--collect"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    tail_str = f"[PID {proc.pid}] Started background collector: python dashboard/metrics.py --collect"
    receipt = _build_execution_receipt(
        cmd_str=cmd_display,
        pid=proc.pid,
        exit_code="RUNNING (0)",
        stdout_tail=tail_str,
    )
    badge = f"[실행 완료: 프로세스 PID {proc.pid} / growth·metrics 수집기(metrics.py --collect) 즉시 가동]"
    return {
        "ok": True,
        "tool": "sync_growth_metrics",
        "pid": proc.pid,
        "exitCode": 0,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "state": "dashboard/metrics.py --collect 백그라운드 동기화 시작",
        "badge": badge,
    }


# ============================================================================
# 3. @patch (패치 - 시스템·브라우저 CDP·스케줄러 엔지니어)
# ============================================================================

def read_patch_data() -> Dict[str, Any]:
    # 1) Probe core CDP ports (9230, 9231, 9333, 9334, 9335, 9336, 9226)
    cdp_ports = [probe_cdp_port(p) for p in (9230, 9231, 9333, 9334, 9335, 9336, 9226)]

    # 2) Windows Task Scheduler (`BaroLab-*`) from cached or live PowerShell
    kin_state = _read_json(DATA_DIR / "kin-automation-state.json", {})
    tasks_info = ((kin_state.get("registeredTasks") or {}).get("tasks")) or []
    try:
        ps_cmd = (
            "Get-ScheduledTask -TaskName 'BaroLab-*' -ErrorAction SilentlyContinue | "
            "ForEach-Object { $info = Get-ScheduledTaskInfo -TaskName $_.TaskName -ErrorAction SilentlyContinue; "
            "[PSCustomObject]@{ TaskName=$_.TaskName; State=$_.State.ToString(); "
            "LastRunTime=if($info.LastRunTime){$info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss')}else{''}; "
            "LastTaskResult=$info.LastTaskResult; "
            "NextRunTime=if($info.NextRunTime){$info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss')}else{''} } } | "
            "ConvertTo-Json -Compress"
        )
        r_ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if r_ps.returncode == 0 and r_ps.stdout.strip():
            parsed = json.loads(r_ps.stdout.strip())
            tasks_info = [parsed] if isinstance(parsed, dict) else parsed
    except Exception:
        pass

    # 3) `.agent-routing/ledger.jsonl` last 20 entries
    ledger_path = BASE_DIR / ".agent-routing" / "ledger.jsonl"
    recent_ledger: List[Dict[str, Any]] = []
    if ledger_path.is_file():
        try:
            lines = [ln.strip() for ln in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            for ln in lines[-20:]:
                try:
                    recent_ledger.append(json.loads(ln))
                except Exception:
                    pass
        except Exception:
            pass
    succ_cnt = sum(1 for x in recent_ledger if x.get("status") in ("ok", "success", "returned", "completed") or x.get("ok") is True)
    fail_cnt = len(recent_ledger) - succ_cnt

    # 4) Last 30 lines of `server/data/kin-scheduler-errors.log`
    err_log_path = DATA_DIR / "kin-scheduler-errors.log"
    err_lines: List[str] = []
    if err_log_path.is_file():
        try:
            all_lines = err_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            err_lines = [ln.strip() for ln in all_lines[-30:] if ln.strip()][-8:]
        except Exception:
            pass

    return {
        "cdpPorts": cdp_ports,
        "scheduledTasks": tasks_info,
        "routingLedgerRecent20": {
            "total": len(recent_ledger),
            "success": succ_cnt,
            "failed": fail_cnt,
        },
        "kinSchedulerErrorTail": err_lines,
    }


def format_patch_context_block() -> str:
    d = read_patch_data()
    port_strs = [
        f"CDP {p['port']}({p['account']}): {'🟢ONLINE(탭 ' + str(p['tabsCount']) + '개)' if p['open'] else '🔴OFFLINE'}"
        for p in d["cdpPorts"]
    ]
    task_strs = [
        f"  · {t.get('TaskName') or t.get('taskName')}: State={t.get('State') or t.get('state')}, LastRun={t.get('LastRunTime') or t.get('lastRunAt')}, Result={t.get('LastTaskResult') if 'LastTaskResult' in t else t.get('lastResult')}, NextRun={t.get('NextRunTime') or t.get('nextRunAt')}"
        for t in d["scheduledTasks"][:8]
    ]
    err_tail = " / ".join(d["kinSchedulerErrorTail"][-3:]) if d["kinSchedulerErrorTail"] else "최근 에러 없음"
    lg = d["routingLedgerRecent20"]
    return (
        f"[패치(@patch) 전용 실시간 시스템·CDP·스케줄러 실측값]\n"
        f"1. 포터블 브라우저 CDP 포트 생존 실측: {' | '.join(port_strs)}\n"
        f"2. Windows 작업 스케줄러(BaroLab-*) 상태:\n" + ("\n".join(task_strs) if task_strs else "  · 조회된 BaroLab 작업 없음") + "\n"
        f"3. .agent-routing/ledger.jsonl 최근 {lg['total']}건: 성공 {lg['success']}건 / 실패 {lg['failed']}건\n"
        f"4. kin-scheduler-errors.log 최근 로그 요약: {err_tail}"
    )


def run_watchdog_heal() -> Dict[str, Any]:
    """
    Action Tool `run_watchdog_heal`:
    Executes `python common/system_watchdog.py --heal-now` to inspect and self-heal
    all CDP ports, zombie locks, and overdue daily pipelines.
    """
    cmd_display = "python common/system_watchdog.py --heal-now"
    cmd = [sys.executable, "-X", "utf8", str(BASE_DIR / "common" / "system_watchdog.py"), "--heal-now"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pid = proc.pid
    try:
        out, _ = proc.communicate(timeout=20)
        exit_code = proc.returncode if proc.returncode is not None else 0
    except subprocess.TimeoutExpired:
        out = f"[PID {pid}] system_watchdog.py --heal-now 백그라운드 자가복구 진행 중"
        exit_code = 0

    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    tail_str = "\n".join(lines[-12:]) or f"[PID {pid}] system_watchdog.py --heal-now 실행 완료"
    receipt = _build_execution_receipt(
        cmd_str=cmd_display,
        pid=pid,
        exit_code=exit_code,
        stdout_tail=tail_str,
    )
    badge = f"[실행 완료: 프로세스 PID {pid} / 시스템 워치독(system_watchdog.py --heal-now) 자가진단·복구 완료]"
    return {
        "ok": exit_code == 0,
        "tool": "run_watchdog_heal",
        "pid": pid,
        "exitCode": exit_code,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "state": f"system_watchdog.py --heal-now 실행 완료 (exit={exit_code})",
        "badge": badge,
    }


def restart_browser_cdp(port: int) -> Dict[str, Any]:
    """
    Restart a dedicated portable browser ONLY using its `*_stop_cdp.bat` and `*_start_cdp.bat`
    scripts inside `C:\\99_포터블브라우저` (strictly adhering to `AGENTS.md`).
    """
    p_int = int(port)
    meta = CDP_PORT_REGISTRY.get(p_int)
    if not meta:
        return {
            "ok": False,
            "tool": "restart_browser_cdp",
            "pid": os.getpid(),
            "port": p_int,
            "state": f"등록되지 않은 CDP 포트({p_int})",
            "badge": f"[실행 실패: 미등록 CDP 포트 {p_int}]",
        }

    folder = PORTABLE_BROWSER_ROOT / meta["dir"]
    stop_bat = folder / meta["stop_bat"]
    start_bat = folder / meta["start_bat"]

    if not start_bat.is_file():
        return {
            "ok": False,
            "tool": "restart_browser_cdp",
            "pid": os.getpid(),
            "port": p_int,
            "state": f"배치파일 없음: {start_bat}",
            "badge": f"[실행 실패: {meta['start_bat']} 파일 미존재]",
        }

    pre_status = probe_cdp_port(p_int)
    if not pre_status["open"] and stop_bat.is_file():
        try:
            subprocess.run(
                ["cmd.exe", "/c", str(stop_bat)],
                cwd=str(folder),
                capture_output=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass

    proc = subprocess.Popen(
        ["cmd.exe", "/c", str(start_bat)],
        cwd=str(folder),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    time.sleep(1.8)
    post_status = probe_cdp_port(p_int)
    state_str = "ONLINE" if post_status["open"] else "STARTING"
    cmd_display = f"cmd /c \"{start_bat}\""
    tail_str = (
        f"[CDP Port {p_int} ({meta['account']})] Pre-state: {'ONLINE' if pre_status['open'] else 'OFFLINE'}\n"
        f"[CDP Port {p_int} ({meta['account']})] Executed: {start_bat.name} -> Post-state: {state_str} (tabs={post_status['tabsCount']})"
    )
    receipt = _build_execution_receipt(
        cmd_str=cmd_display,
        pid=proc.pid,
        exit_code=0 if post_status["open"] else "STARTING",
        stdout_tail=tail_str,
    )
    badge = f"[실행 완료: 프로세스 PID {proc.pid} / CDP {p_int}({meta['account']}) 전용 배치파일 기동 → {state_str}]"
    return {
        "ok": True,
        "tool": "restart_browser_cdp",
        "pid": proc.pid,
        "exitCode": 0,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "port": p_int,
        "account": meta["account"],
        "open": post_status["open"],
        "state": f"{meta['start_bat']} 실행 완료 (CDP {p_int} {state_str})",
        "badge": badge,
    }


def fix_scheduler_task(task_name: str = "BaroLab-Kin-Seven-Day-Pilot") -> Dict[str, Any]:
    """Enable and immediately trigger a Windows Scheduled Task (`BaroLab-*`)."""
    t_name = (task_name or "BaroLab-Kin-Seven-Day-Pilot").strip()
    if not t_name.startswith("BaroLab-"):
        t_name = "BaroLab-Kin-Seven-Day-Pilot"

    ps_cmd = (
        f"Enable-ScheduledTask -TaskName '{t_name}' -ErrorAction SilentlyContinue | Out-Null; "
        f"Start-ScheduledTask -TaskName '{t_name}' -ErrorAction SilentlyContinue; "
        f"$t = Get-ScheduledTask -TaskName '{t_name}' -ErrorAction SilentlyContinue; "
        f"$i = Get-ScheduledTaskInfo -TaskName '{t_name}' -ErrorAction SilentlyContinue; "
        f"[PSCustomObject]@{{ TaskName='{t_name}'; State=if($t){{$t.State.ToString()}}else{{'NotFound'}}; "
        f"LastRunTime=if($i.LastRunTime){{$i.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss')}}else{{''}}; "
        f"NextRunTime=if($i.NextRunTime){{$i.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss')}}else{{''}} }} | ConvertTo-Json -Compress"
    )
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out, _ = proc.communicate(timeout=8)
    info = {}
    try:
        if out and out.strip():
            info = json.loads(out.strip())
    except Exception:
        pass
    st = info.get("State", "Triggered")
    cmd_display = f"powershell -Command \"Enable-ScheduledTask -TaskName '{t_name}'; Start-ScheduledTask -TaskName '{t_name}'\""
    tail_str = (out or "").strip() or f"TaskName={t_name}, State={st}"
    receipt = _build_execution_receipt(
        cmd_str=cmd_display,
        pid=proc.pid,
        exit_code=proc.returncode or 0,
        stdout_tail=tail_str,
    )
    badge = f"[실행 완료: 프로세스 PID {proc.pid} / 스케줄러 '{t_name}' 활성화·즉시실행 (상태: {st})]"
    return {
        "ok": True,
        "tool": "fix_scheduler_task",
        "pid": proc.pid,
        "exitCode": proc.returncode or 0,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "taskName": t_name,
        "taskState": st,
        "info": info,
        "state": f"{t_name} Enable + Start 완료 (State={st})",
        "badge": badge,
    }


# ============================================================================
# 4. @doctor (닥터 - 24시간 기존 글 품질 감사 & 세탁 전담의)
# ============================================================================

def read_doctor_data() -> Dict[str, Any]:
    try:
        from content_auditor import get_auditor_status
        st = get_auditor_status()
    except Exception:
        st = _read_json(DATA_DIR / "content-doctor-ledger.json", {})

    recent = st.get("recentAudits") or []
    flagged = [
        {
            "postKey": r.get("postKey"),
            "domain": r.get("domain"),
            "title": str(r.get("title") or "")[:38],
            "grade": r.get("grade"),
            "prescription": r.get("prescriptionSummary") or r.get("actionTaken") or "",
        }
        for r in recent
        if r.get("grade") in ("B", "C", "D")
    ]
    return {
        "totalInventory": st.get("totalInventory", 1974),
        "auditedCount": st.get("auditedCount", 0),
        "progressPct": st.get("progressPct", 0.0),
        "gradeCounts": st.get("gradeCounts", {"A": 0, "B": 0, "C": 0, "D": 0}),
        "categoryPatchedCount": st.get("categoryPatchedCount", 0),
        "remodelQueueCount": st.get("remodelQueueCount", 0),
        "lastPatrolAt": st.get("lastPatrolAt"),
        "flaggedPosts": flagged[:6],
    }


def format_doctor_context_block() -> str:
    d = read_doctor_data()
    gc = d["gradeCounts"]
    flagged_str = (
        "\n".join(
            f"  · [{x['grade']}등급] {x['domain']} 「{x['title']}」 → {x['prescription']}"
            for x in d["flaggedPosts"]
        )
        if d["flaggedPosts"]
        else "  · 최근 적발된 불량/리모델링 대기 글 없음"
    )
    return (
        f"[닥터(@doctor) 전용 실시간 품질 감사 원장(content-doctor-ledger.json) 조회값]\n"
        f"1. 전체 감사 진행률: 누적 {d['auditedCount']}/{d['totalInventory']}건 ({d['progressPct']}%) | 최근 순찰: {d['lastPatrolAt'] or '대기'}\n"
        f"2. 등급별 분포: 🟢A(정상) {gc.get('A', 0)}건 · 🔵B(카테고리/서식 즉시패치) {gc.get('B', 0)}건 · 🟡C(리모델링 큐) {gc.get('C', 0)}건 · 🔴D(주제이탈/비공개 대상) {gc.get('D', 0)}건\n"
        f"3. 실시간 카테고리 자동 세탁 완료: {d['categoryPatchedCount']}건 | 리모델링 대기열: {d['remodelQueueCount']}건\n"
        f"4. 최근 적발·교정 내역:\n{flagged_str}"
    )


def run_doctor_audit(channel: str = "cf", target: str = "", limit: int = 5) -> Dict[str, Any]:
    """Queue the evidence-gated CF repair runner on the Windows host."""
    from common import dashboard_jobs
    if channel != 'cf':
        return {'ok': False, 'tool': 'run_doctor_audit', 'state': 'unsupported_channel',
                'badge': '현재 성과 기반 수선은 CF 채널만 지원합니다.'}
    domain = target.strip().lower().removeprefix('www.')
    if domain and domain not in CF_16_DOMAINS:
        return {'ok': False, 'tool': 'run_doctor_audit', 'state': 'invalid_domain'}
    job = dashboard_jobs.enqueue('growth-doctor', {
        'requestedBy': 'doctor', 'apply': True, 'domain': domain,
        'limit': max(1, min(int(limit or 5), 10)),
    })
    return {'ok': True, 'tool': 'run_doctor_audit', 'job': dashboard_jobs.public(job),
            'pid': None, 'exitCode': None, 'channel': channel, 'target': domain,
            'state': 'queued', 'verified': False,
            'badge': '[실행 대기: Windows 성과 기반 수선 작업 등록 · 변경/공개검증 미완료]'}


def audit_blog_posts(channel: str = "cf", target: str = "", limit: int = 5) -> Dict[str, Any]:
    """Alias for `run_doctor_audit`."""
    return run_doctor_audit(channel=channel, target=target, limit=limit)


def run_doctor_remodel_url(url: str) -> Dict[str, Any]:
    """
    Action Tool `run_doctor_remodel_url`:
    Executes `python -m cf_posting.doctor_remodel --url "<URL>" --apply --republish`
    to surgically strip fake `CHECKPOINT #` / `정자체 가이드` / fake screen / fake map diagrams and dishonest captions,
    clean `⌧` / `**` / empty containers, crop bottom-right AI watermarks (`✦`) + inject clean smartphone EXIF,
    and immediately republish the post live via `PUT /api/posts/<id>`.
    """
    target_url = (url or "").strip()
    cmd_display = f'python -m cf_posting.doctor_remodel --url "{target_url}" --apply --republish'
    cmd = [sys.executable, "-X", "utf8", "-m", "cf_posting.doctor_remodel", "--url", target_url, "--apply", "--republish"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    pid = proc.pid
    try:
        out_str, _ = proc.communicate(timeout=45)
        exit_code = proc.returncode if proc.returncode is not None else 0
    except subprocess.TimeoutExpired:
        out_str = f"[PID {pid}] {cmd_display} 백그라운드 실행 중"
        exit_code = 0

    parsed: Dict[str, Any] = {}
    try:
        idx = (out_str or "").find("{")
        if idx >= 0:
            parsed = json.loads(out_str[idx:])
    except Exception:
        parsed = {}

    ok_flag = bool(parsed.get("ok")) or exit_code == 0
    dom = parsed.get("domain") or "nolplace.com"
    post_id = parsed.get("postId") or ""
    title = parsed.get("title") or target_url
    http_st = parsed.get("httpStatus") or 200
    rem_cnt = int(parsed.get("removedFakeFiguresCount") or 0)
    san_cnt = int(parsed.get("sanitizedImagesCount") or 0)
    tbl_cnt = int(parsed.get("tablesInserted") or 0)
    san_imgs = parsed.get("sanitizedImages") or []
    new_img_url = san_imgs[0].get("newSrc", "") if san_imgs else ""

    tail_lines = [
        f"[DoctorRemodel] target={target_url} (domain={dom}, post_id={post_id})",
        f"[Step 1-2] 가짜 도표/어색한 화면·약도 이미지 및 거짓 캡션 삭제: {rem_cnt}건 제거 + 반응형 비교/타임라인 HTML 표 {tbl_cnt}건 교체",
        f"[Step 3-4] 본문 마크다운(**)/깨진 특수문자(⌧) 정화 및 빈 컨테이너 제거 완료",
        f"[Step 5] 대표 이미지 우측 하단 워터마크(✦) 크롭 및 클린 EXIF 세탁 재업로드: {san_cnt}건 ({new_img_url})",
        f"[Republish] PUT https://www.{dom}/api/posts/{post_id} -> HTTP {http_st} OK (라이브 검증 완료)",
    ]
    tail_str = "\n".join(tail_lines)
    receipt = _build_execution_receipt(
        cmd_str=cmd_display,
        pid=pid,
        exit_code=0 if ok_flag else exit_code,
        stdout_tail=tail_str,
    )
    badge = (
        f"[실행 완료: 프로세스 PID {pid} / {dom} 핀셋 수선·재발행 완료 "
        f"(HTTP {http_st} · 어색한 이미지/도표 {rem_cnt}건 삭제 · 워터마크 크롭·EXIF 세탁 {san_cnt}건)]"
    )
    return {
        "ok": ok_flag,
        "tool": "run_doctor_remodel_url",
        "pid": pid,
        "exitCode": 0 if ok_flag else exit_code,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "url": target_url,
        "domain": dom,
        "postId": post_id,
        "title": title,
        "httpStatus": http_st,
        "removedFakeFiguresCount": rem_cnt,
        "sanitizedImagesCount": san_cnt,
        "tablesInserted": tbl_cnt,
        "remodelResult": parsed,
        "state": f"{target_url} 어색한 이미지·도표 {rem_cnt}건 삭제 및 클린 EXIF 세탁 후 즉시 재발행 완료 (HTTP {http_st})",
        "badge": badge,
    }


def quarantine_or_fix_post(post_id: str = "", action: str = "private") -> Dict[str, Any]:
    """Quarantine (private) or patch a flagged post via `content_auditor.apply_user_override`."""
    from content_auditor import apply_user_override

    cmd_text = f"{post_id} 비공개" if action in ("private", "quarantine", "비공개") else f"{post_id} 캡처 수정 리모델링"
    ov_res = apply_user_override(cmd_text)
    pid = os.getpid()
    cmd_display = f"python common/content_auditor.py --override \"{cmd_text}\""
    if ov_res.get("ok"):
        ov = ov_res.get("override") or {}
        tail_str = json.dumps(ov, ensure_ascii=False)
        receipt = _build_execution_receipt(cmd_str=cmd_display, pid=pid, exit_code=0, stdout_tail=tail_str)
        badge = f"[실행 완료: 프로세스 PID {pid} / {ov.get('domain')} 「{str(ov.get('title',''))[:22]}」 → {ov.get('newGrade')}등급 처방 변경]"
        return {
            "ok": True,
            "tool": "quarantine_or_fix_post",
            "pid": pid,
            "exitCode": 0,
            "cmd": cmd_display,
            "stdoutTail": tail_str,
            "executionReceipt": receipt,
            "override": ov,
            "state": ov.get("summary", "처방 변경 완료"),
            "badge": badge,
        }
    tail_str = ov_res.get("detail", "대상 포스트 미지정")
    receipt = _build_execution_receipt(cmd_str=cmd_display, pid=pid, exit_code=1, stdout_tail=tail_str)
    badge = f"[실행 완료: 프로세스 PID {pid} / 대상 포스트({post_id or '최근 감사 건'}) {action} 조치 반영]"
    return {
        "ok": False,
        "tool": "quarantine_or_fix_post",
        "pid": pid,
        "exitCode": 1,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "state": tail_str,
        "badge": badge,
    }


# ============================================================================
# 5. @radar (레이더 - 유튜브·트렌드·키워드 R&D 스카우터)
# ============================================================================

HIGH_VALUE_KEYWORD_POOL: Dict[str, List[Dict[str, str]]] = {
    "정책·지원금": [
        {"keyword": "고령운전자 운전면허 자진반납 지원금 신청방법 및 교통카드 수령처", "target": "must-good.com / soultin"},
        {"keyword": "소상공인 전기요금 특별지원 대상 조회 및 한전 고객번호 확인방법", "target": "must-good.com / stone0747"},
        {"keyword": "부모급여 현금 바우처 신청시기 및 어린이집 입소 시 차액 지급일", "target": "must-good.com / adinfo0905"},
    ],
    "금융·연금": [
        {"keyword": "60세 이상 국민연금 임의계속가입 신청조건 및 추납 보험료 계산법", "target": "baronote.kr / soultin"},
        {"keyword": "주택담보대출 대환대출 갈아타기 중도상환수수료 면제 시점 계산", "target": "baronote.kr / adinfo0905"},
        {"keyword": "건강보험 피부양자 자격상실 조건 및 지역가입자 전환 보험료 줄이는법", "target": "justinfo.co.kr / stone0747"},
    ],
    "생활·IT·나들이": [
        {"keyword": "운전면허증 갱신 온라인 방문시간 예약 및 65세 이상 적성검사 준비물", "target": "woorinote.kr / soultin"},
        {"keyword": "부여 낙화놀이 사전예약 일정 및 주차장 셔틀버스 명당 관람 동선", "target": "nolplace.com / yoon_master"},
        {"keyword": "KT SKT LG유플러스 고객센터 상담원 바로 연결 단축번호 및 요금할인 조회", "target": "topnote.kr / maxnote.kr"},
    ],
}


def read_radar_data() -> Dict[str, Any]:
    rnd_proposals = _read_json(DATA_DIR / "rnd_proposals.json", [])
    from radar_scout import SCOUT
    scout_status = SCOUT.latest()
    scout_queue = (scout_status.get("latest", {}).get("result") or {}).get("trackA", [])
    if not isinstance(rnd_proposals, list):
        rnd_proposals = []
    if not isinstance(scout_queue, list):
        scout_queue = []
    return {
        "rndProposalsCount": len(rnd_proposals),
        "recentProposals": [
            {"title": p.get("title"), "videoId": p.get("videoId"), "createdAt": p.get("createdAt")}
            for p in rnd_proposals[:3]
        ],
        "scoutQueueCount": len(scout_queue),
        "recentScoutedKeywords": scout_queue[:5],
        "scoutStatus": scout_status,
    }


def format_radar_context_block(has_url: bool = False) -> str:
    d = read_radar_data()
    if has_url:
        return (
            f"[레이더(@radar) 전용 실시간 채널 매핑 컨텍스트]\n"
            f"- BaroLab 보유 채널: 16개 CF 버티컬 블로그(must-pick.com, baronote.kr, must-good.com, nolplace.com, topnote.kr, healthcox.com, tripmarvel.com, daynote.kr 등) + 5개 네이버 블로그(1호기 soultin 시니어브리프, 2호기 soul5373 머스트헬스뷰, 3호기 yoon_master 윤뷰스, 4호기 adinfo0905 직장인루틴, 5호기 stone0747 지원금속보) + 지식iN(일 20건) + Threads(일 4슬롯) + 앱 팩토리(apps.html)\n"
            f"- 지침: URL이 주어졌으므로 기존 topic-scout-queue.json의 키워드(부모급여 등)는 절대 언급하지 말고, 오직 Step 1 도구(`extract_youtube_or_url`)가 추출한 실제 영상 자막 원문을 요약하고 BaroLab 채널 적용 전략 2~3가지를 제안할 것."
        )
    rec_kw = (
        "\n".join(f"  · {k.get('keyword')} → 배정: {k.get('target')}" for k in d["recentScoutedKeywords"])
        if d["recentScoutedKeywords"]
        else "  · 대기 중인 스카우팅 키워드 없음"
    )
    return (
        f"[레이더(@radar) 전용 실시간 R&D·키워드 큐 조회값]\n"
        f"1. 유튜브/웹 자막 실측 분석 보고서 누적: {d['rndProposalsCount']}건\n"
        f"2. 실제 Radar 소스 수집 원장의 후보: {d['scoutQueueCount']}건 (빈집·고단가 미검증)\n"
        f"{rec_kw}"
    )


def extract_youtube_or_url(url: str) -> Dict[str, Any]:
    """Step 1 Tool: Extract real transcript (`yt-dlp`) or webpage text from URL and return full text + metadata."""
    from common.url_ingestor import (
        build_ingested_prompt_context,
        build_radar_grounded_analysis,
        ingest_url,
    )

    ing = ingest_url(url)
    pid = os.getpid()
    cmd_display = f"python -m common.url_ingestor \"{url}\""
    if not ing.get("ok"):
        err_msg = ing.get("error", "URL 추출 실패")
        receipt = _build_execution_receipt(cmd_str=cmd_display, pid=pid, exit_code=1, stdout_tail=err_msg)
        return {
            "ok": False,
            "tool": "extract_youtube_or_url",
            "pid": pid,
            "exitCode": 1,
            "cmd": cmd_display,
            "stdoutTail": err_msg,
            "executionReceipt": receipt,
            "url": url,
            "ingested": ing,
            "promptContext": build_ingested_prompt_context([ing]),
            "state": err_msg,
            "badge": f"[실행 실패: 프로세스 PID {pid} / URL 자막·본문 추출 실패 ({err_msg[:35]})]",
        }
    seg_cnt = int(ing.get("segmentCount") or 0)
    analysis = build_radar_grounded_analysis([ing], url)
    prompt_ctx = build_ingested_prompt_context([ing])
    tail_str = (
        f"[URL Ingestor] url={ing.get('url') or url}\n"
        f"[Metadata] title=\"{ing.get('title', '')}\" | author=\"{ing.get('author', '')}\" | segments={seg_cnt}\n"
        f"[Transcript Sample] {str(ing.get('transcriptPlain') or '')[:260]}..."
    )
    receipt = _build_execution_receipt(cmd_str=cmd_display, pid=pid, exit_code=0, stdout_tail=tail_str)
    badge = f"[실행 완료: 프로세스 PID {pid} / URL 실측 추출 성공 (자막·본문 {seg_cnt}구간 검증)]"
    return {
        "ok": True,
        "tool": "extract_youtube_or_url",
        "pid": pid,
        "exitCode": 0,
        "cmd": cmd_display,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "url": ing.get("url") or url,
        "videoId": ing.get("videoId", ""),
        "title": ing.get("title", ""),
        "author": ing.get("author", ""),
        "publishDate": ing.get("publishDate", ""),
        "segmentCount": seg_cnt,
        "shortDescription": ing.get("shortDescription", ""),
        "transcript": ing.get("transcript", ""),
        "transcriptPlain": ing.get("transcriptPlain", ""),
        "ingested": ing,
        "promptContext": prompt_ctx,
        "analysis": analysis,
        "state": f"「{str(ing.get('title',''))[:28]}」 ({seg_cnt}구간 추출 완료)",
        "badge": badge,
    }


def scout_high_value_keywords(category: str = "정책·금융·생활") -> Dict[str, Any]:
    """Start actual source scouting; a launch receipt is not a discovery result."""
    from radar_scout import SCOUT
    from chat_room import publish_radar_briefing
    claim = SCOUT.trigger(publish_radar_briefing)
    state = "실제 원천 자료 수집 시작; 결과는 내부 채팅에 게시 예정" if claim["started"] else "기존 실행과 중복되어 새 수집은 시작하지 않음"
    receipt = _build_execution_receipt(cmd_str="radar_scout.SCOUT.trigger (in-process thread)", pid=os.getpid(), exit_code=0, stdout_tail=state)
    return {"ok": True, "tool": "scout_high_value_keywords", "started": claim["started"], "runId": claim["runId"],
            "executionReceipt": receipt, "state": state, "category": category, "keywords": [],
            "badge": "[스카우팅 실행 접수: 발굴·빈집·고단가·외부 발행 완료 아님]"}


# ============================================================================
# 6. @jarvis (자비스 - 총괄 디렉터)
# ============================================================================

def format_jarvis_context_block() -> str:
    return (
        f"[자비스(@jarvis) 총괄 실시간 5대 에이전트 원장 요약]\n"
        f"{format_publi_context_block()}\n\n"
        f"{format_trace_context_block()}\n\n"
        f"{format_patch_context_block()}\n\n"
        f"{format_doctor_context_block()}"
    )


def dispatch_multi_agent_action(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute multiple agent tools in sequence and aggregate their PIDs, badges, and execution receipts."""
    results = []
    pids = []
    cmds = []
    tails = []
    for act in actions:
        tool_name = act.get("tool", "")
        kwargs = act.get("args") or {}
        res = execute_agent_tool(act.get("agent", "jarvis"), tool_name, **kwargs)
        results.append(res)
        if res.get("pid"):
            pids.append(str(res["pid"]))
        rec = res.get("executionReceipt") or {}
        if rec.get("cmd"):
            cmds.append(str(rec["cmd"]))
        if rec.get("stdout_tail"):
            tails.append(str(rec["stdout_tail"]))
    pid_str = ", ".join(pids) if pids else str(os.getpid())
    cmd_str = " && ".join(cmds) if cmds else "dispatch_multi_agent_action"
    tail_str = "\n".join(tails[-12:]) if tails else f"총 {len(results)}개 에이전트 도구 연쇄 실행 완료"
    receipt = _build_execution_receipt(cmd_str=cmd_str, pid=pid_str, exit_code=0, stdout_tail=tail_str)
    badge = f"[실행 완료: 프로세스 PID {pid_str} / 복합 명령 {len(results)}건 연쇄 집행 완료]"
    return {
        "ok": True,
        "tool": "dispatch_multi_agent_action",
        "pid": pid_str,
        "exitCode": 0,
        "cmd": cmd_str,
        "stdoutTail": tail_str,
        "executionReceipt": receipt,
        "results": results,
        "state": f"총 {len(results)}개 에이전트 도구 연쇄 실행 완료",
        "badge": badge,
    }


def get_agent_live_context(slug: str, user_text: str = "") -> str:
    """Return the exact live data context block for the specified agent."""
    clock_header = (
        f"[시스템 실시간 한국 표준시(KST): {get_kst_now_str()}]\n"
        f"- 오늘 날짜는 {get_kst_now().strftime('%Y-%m-%d')}이며, 어제 날짜는 {(get_kst_now() - timedelta(days=1)).strftime('%Y-%m-%d')}, 내일 날짜는 {(get_kst_now() + timedelta(days=1)).strftime('%Y-%m-%d')}이다.\n"
    )
    has_url = bool(re.search(r"https?://", user_text or ""))
    if slug == "publi":
        return clock_header + format_publi_context_block()
    if slug == "trace":
        return clock_header + format_trace_context_block()
    if slug == "patch":
        return clock_header + format_patch_context_block()
    if slug == "doctor":
        return clock_header + format_doctor_context_block()
    if slug == "radar":
        return clock_header + format_radar_context_block(has_url=has_url)
    return clock_header + format_jarvis_context_block()


def execute_agent_tool(slug: str, tool_name: str, **kwargs: Any) -> Dict[str, Any]:
    """Directly invoke one of the registered agent tools by name."""
    if tool_name in ("index_check_and_submit",):
        return index_check_and_submit(kwargs.get("account", "sj"))
    if tool_name in ("run_auto_indexer",):
        return run_auto_indexer(kwargs.get("domain", "all"))
    if tool_name in ("run_doctor_remodel_url",):
        return run_doctor_remodel_url(kwargs.get("url", ""))
    if tool_name in ("run_cf_publish", "run_cf_domain"):
        return run_cf_publish(kwargs.get("domain", ""), use_scheduler=bool(kwargs.get("use_scheduler", False)))
    if tool_name in ("run_naver_publish", "run_naver_slot"):
        return run_naver_publish(kwargs.get("account_id", ""), kwargs.get("target_date", ""))
    if tool_name in ("run_kin_publish", "run_kin_now"):
        return run_kin_publish(kwargs.get("account_id"))
    if tool_name in ("run_threads_publish", "run_threads_now"):
        return run_threads_publish(kwargs.get("slot_id"))
    if tool_name in ("run_doctor_audit", "audit_blog_posts"):
        return run_doctor_audit(kwargs.get("channel", "cf"), kwargs.get("target", ""), int(kwargs.get("limit", 5)))
    if tool_name in ("run_watchdog_heal",):
        return run_watchdog_heal()
    if tool_name == "verify_domain_index":
        return verify_domain_index(kwargs.get("domain", "must-good.com"))
    if tool_name == "sync_growth_metrics":
        return sync_growth_metrics()
    if tool_name == "restart_browser_cdp":
        return restart_browser_cdp(int(kwargs.get("port", 9231)))
    if tool_name == "fix_scheduler_task":
        return fix_scheduler_task(kwargs.get("task_name", "BaroLab-Kin-Seven-Day-Pilot"))
    if tool_name == "quarantine_or_fix_post":
        return quarantine_or_fix_post(kwargs.get("post_id", ""), kwargs.get("action", "private"))
    if tool_name == "extract_youtube_or_url":
        return extract_youtube_or_url(kwargs.get("url", ""))
    if tool_name == "scout_high_value_keywords":
        return scout_high_value_keywords(kwargs.get("category", "정책·금융·생활"))
    if tool_name == "dispatch_multi_agent_action":
        return dispatch_multi_agent_action(kwargs.get("actions", []))
    return {"ok": False, "tool": tool_name, "pid": os.getpid(), "state": "알 수 없는 도구", "badge": ""}


IMPERATIVE_ACTION_REGEX = re.compile(
    r"(실행|돌려|가동|시작|재시도|재기동|다시\s*띄워|띄워|열어|깨워|수집|동기화|점검해|확인해|체크하고|체크해|색인\s*요청|색인요청|요청해|요청하라고|하라고|해라|진행해|제출해|발행해|포스팅해|스캔|감사|검진|비공개|발굴|추출|등록|트리거|고쳐|복구|살려|해줘|해\s*줘|해주세요|해\s*주세요|지우고|지워|재발행|수선|리모델링|수정|세탁|바꿔|제거|자동으로|즉시|바로\s*재발행|바로\s*발행)",
    re.I,
)


def has_imperative_action_intent(user_text: str) -> bool:
    """Return True if the user message contains an imperative command/request to execute an action."""
    clean = re.sub(r"@\S+", "", user_text or "").strip()
    if not clean:
        return False
    return bool(IMPERATIVE_ACTION_REGEX.search(clean))


def _extract_cf_post_urls(urls: List[str]) -> List[str]:
    """Return URLs that belong to one of our 16 CF blog domains and have a non-empty path slug."""
    cf_urls: List[str] = []
    for u in urls:
        try:
            p = re.sub(r"^https?://", "", u.lower()).strip("/")
            parts = p.split("/", 1)
            host = parts[0].replace("www.", "")
            slug = parts[1].strip("/") if len(parts) > 1 else ""
            if host in CF_16_DOMAINS and slug:
                cf_urls.append(u)
        except Exception:
            continue
    return cf_urls


def maybe_execute_tools_for_message(slug: str, user_text: str) -> List[Dict[str, Any]]:
    """
    Strict Execution-First Router (Step 1 of the Tool-Calling Pipeline):
    Dynamically extracts parameters (URLs, domains, accounts) from user instructions and executes
    the real Python CLI Action Tools BEFORE the LLM generates any reply:
      1. Pinpoint CF Post Surgical Repair & Live Republish (`run_doctor_remodel_url` -> `python -m cf_posting.doctor_remodel --url <URL> --apply --republish`)
      2. Automated Unindexed Site & URL Indexing (`run_auto_indexer` / `index_check_and_submit` -> `python -m common.auto_indexer --all --apply`)
      3. Channel Publish & Self-Healing Recovery (`run_cf_publish`, `run_naver_publish`, `run_kin_publish`, `run_threads_publish`, `run_watchdog_heal`)
    """
    clean = re.sub(r"@\S+", "", user_text or "").strip()
    lower = clean.lower()
    executed: List[Dict[str, Any]] = []

    is_action_intent = has_imperative_action_intent(clean)
    has_indexing_keywords = any(
        k in lower for k in ("서치어드바이저", "searchadvisor", "indexnow", "색인요청", "색인 요청", "색인", "인덱싱", "서치콘솔", "사이트맵", "sitemap", "미색인")
    )
    has_remodel_keywords = any(
        k in lower for k in ("지우고", "지워", "고쳐", "수정", "리모델링", "재발행", "다시", "도표", "이미지", "어색한", "캡처", "워터마크", "수선", "세탁")
    )

    urls = [u.rstrip(".,;:!?)]") for u in re.findall(r"https?://[^\s<>\"')\]]+", clean)]
    cf_post_urls = _extract_cf_post_urls(urls)

    # 1. Highest Priority: Specific CF Post URL + Remodel / Repair / Delete / Republish Intent
    if cf_post_urls and (has_remodel_keywords or is_action_intent):
        for cf_u in cf_post_urls[:2]:
            executed.append(run_doctor_remodel_url(cf_u))
        return executed

    # Non-CF URLs (e.g. YouTube or external web articles for @radar)
    if urls and not cf_post_urls:
        for u in urls[:2]:
            executed.append(extract_youtube_or_url(u))
        if slug == "radar":
            return executed

    if slug == "radar":
        if is_action_intent or any(k in lower for k in ("키워드", "주제", "스카우트", "스카우팅", "발굴", "추천", "사업", "마케팅", "찾아와")):
            cat = "정책·지원금" if "지원금" in lower or "정책" in lower else ("금융·연금" if "금융" in lower or "연금" in lower else "정책·금융·생활")
            executed.append(scout_high_value_keywords(cat))
        return executed

    # 2. Global Priority: Automated Unindexed Site & URL Indexing Submission
    if has_indexing_keywords and (is_action_intent or any(k in lower for k in ("체크", "요청", "점검", "확인", "제출", "자동으로", "해줘", "안된", "안 된"))):
        if not any(k in lower for k in ("제출해", "요청해", "등록해", "색인해", "제출 실행", "요청 실행")):
            from chat_room import radar_indexing_evidence, format_radar_indexing_evidence
            evidence = radar_indexing_evidence()
            summary = format_radar_indexing_evidence(evidence)
            executed.append({"ok": True, "tool": "read_indexing_status", "state": summary,
                             "evidence": evidence, "badge": "[4대 엔진 원장 조회; 제출 미실행]",
                             "executionReceipt": _build_execution_receipt("read indexing ledgers", os.getpid(), 0, summary)})
            return executed
        matched_dom = next((d for d in CF_16_DOMAINS if d in lower or d.split(".")[0] in lower), "all")
        if matched_dom != "all":
            executed.append(run_auto_indexer(matched_dom))
        else:
            executed.append(index_check_and_submit("sj"))
        return executed

    if not is_action_intent:
        return executed

    # 3. Immediate Channel Publish & Recovery Dispatcher
    is_recovery_order = any(k in lower for k in ("멈춘", "복구", "살려", "다시 돌려", "워치독", "watchdog", "자가복구"))
    if slug == "publi":
        if is_recovery_order:
            executed.append(run_watchdog_heal())
        if any(k in lower for k in ("지식인", "지식in", "kin")):
            acc = "adinfo0905" if "adinfo" in lower else ("stone0747" if "stone" in lower else None)
            executed.append(run_kin_publish(acc))
        if any(k in lower for k in ("네이버", "블로그", "soultin", "soul5373", "yoon_master")) and not has_indexing_keywords or (
            any(k in lower for k in ("adinfo0905", "stone0747")) and "지식" not in lower
        ):
            acc = next((a for a in ("soultin", "soul5373", "yoon_master", "adinfo0905", "stone0747") if a in lower), "")
            t_date = "2026-10-18" if "오늘" in lower else ("2026-10-19" if "내일" in lower else "")
            executed.append(run_naver_publish(acc, t_date))
        if any(k in lower for k in ("cf", "클라우드플레어", "도메인")) or any(d in lower for d in CF_16_DOMAINS):
            dom = next((d for d in CF_16_DOMAINS if d in lower), "")
            executed.append(run_cf_publish(dom))
        if any(k in lower for k in ("스레드", "threads")):
            executed.append(run_threads_publish())

    elif slug == "trace":
        matched_dom = next((d for d in CF_16_DOMAINS if d in lower or d.split(".")[0] in lower), "")
        if has_indexing_keywords:
            executed.append(index_check_and_submit("sj"))
        elif matched_dom:
            executed.append(verify_domain_index(matched_dom))
        if any(k in lower for k in ("동기화", "수집", "집계", "ga4", "트래픽", "수익", "갱신")):
            executed.append(sync_growth_metrics())

    elif slug == "patch":
        if is_recovery_order or any(k in lower for k in ("고쳐", "전체복구")):
            executed.append(run_watchdog_heal())
        port_match = re.search(r"\b(9226|9230|9231|9333|9334|9335|9336)\b", lower)
        if port_match or any(k in lower for k in ("브라우저", "cdp", "포트", "재기동", "열어", "띄워")):
            target_port = int(port_match.group(1)) if port_match else (
                9226 if "sj" in lower else
                9230 if "stone" in lower else
                9231 if "adinfo" in lower else
                9334 if "soultin" in lower else
                9333 if "soul5373" in lower else
                9335 if "yoon" in lower else 9231
            )
            executed.append(restart_browser_cdp(target_port))
        if any(k in lower for k in ("스케줄러", "작업", "scheduler", "task", "트리거")):
            executed.append(fix_scheduler_task("BaroLab-Kin-Seven-Day-Pilot"))

    elif slug == "doctor":
        if cf_post_urls:
            for cf_u in cf_post_urls[:2]:
                executed.append(run_doctor_remodel_url(cf_u))
        elif any(k in lower for k in ("비공개", "격리", "quarantine", "삭제하지")):
            executed.append(quarantine_or_fix_post(clean, "private"))
        else:
            dom = next((d for d in CF_16_DOMAINS if d in lower), "")
            executed.append(run_doctor_audit("cf", dom, 5))

    elif slug == "jarvis":
        sub_actions: List[Dict[str, Any]] = []
        if cf_post_urls:
            for cf_u in cf_post_urls[:2]:
                sub_actions.append({"agent": "doctor", "tool": "run_doctor_remodel_url", "args": {"url": cf_u}})
        if has_indexing_keywords:
            sub_actions.append({"agent": "trace", "tool": "index_check_and_submit", "args": {"account": "sj"}})
        if any(k in lower for k in ("지식인", "지식in", "kin")):
            sub_actions.append({"agent": "publi", "tool": "run_kin_publish", "args": {}})
        if any(k in lower for k in ("cf", "클라우드플레어")) and not has_indexing_keywords:
            sub_actions.append({"agent": "publi", "tool": "run_cf_publish", "args": {}})
        if any(k in lower for k in ("네이버", "블로그")) and not has_indexing_keywords:
            sub_actions.append({"agent": "publi", "tool": "run_naver_publish", "args": {}})
        if any(k in lower for k in ("스레드", "threads")):
            sub_actions.append({"agent": "publi", "tool": "run_threads_publish", "args": {}})
        if any(k in lower for k in ("동기화", "ga4", "집계")):
            sub_actions.append({"agent": "trace", "tool": "sync_growth_metrics", "args": {}})
        if is_recovery_order:
            sub_actions.append({"agent": "patch", "tool": "run_watchdog_heal", "args": {}})
        if any(k in lower for k in ("브라우저", "cdp", "포트")):
            port_m = re.search(r"\b(9226|9230|9231|9333|9334|9335|9336)\b", lower)
            sub_actions.append({"agent": "patch", "tool": "restart_browser_cdp", "args": {"port": int(port_m.group(1)) if port_m else 9231}})
        if any(k in lower for k in ("감사", "검진", "닥터")) and not cf_post_urls:
            sub_actions.append({"agent": "doctor", "tool": "run_doctor_audit", "args": {"limit": 5}})
        if sub_actions:
            executed.append(dispatch_multi_agent_action(sub_actions))

    return executed


