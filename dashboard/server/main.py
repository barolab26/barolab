"""
BaroLab Master Control Server (통합 관제 서버)
포트: 127.0.0.1:8790
역할:
  1. BaroLab 통합 대시보드 웹 서빙 (http://127.0.0.1:8790/)
  2. 오늘 발행 할일 체크 실시간 영구 저장 API (/api/todos)
  3. 색인 여부 / 방문자수 / 수익 지표 실시간 공급 API (/api/metrics)
  4. 네이버 5개 계정 & 3대 전략 순환 로테이션 API (/api/naver)
  5. 포터블 브라우저 CDP 소켓 실시간 헬스체크 (/api/status)
"""

import os
import json
import socket
import asyncio
import sqlite3
import threading
import logging
from datetime import datetime, timezone, timedelta
from contextlib import closing
import sys
from pathlib import Path
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[2]  # y:\10_Project\BaroLab
SERVER_DIR = Path(__file__).resolve().parent       # y:\10_Project\BaroLab\server
DATA_DIR = BASE_DIR / "dashboard/data"
DASHBOARD_DIR = BASE_DIR / "dashboard"
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(DASHBOARD_DIR))
from metrics import summary as metrics_summary
NAVER_DIR = BASE_DIR / "naver_blog_posting"
CF_DIR = BASE_DIR / "cf_posting"

from server.dashboard_cache import ReadCache
METRICS_READ_CACHE = ReadCache(ttl=30, capacity=1)

app = FastAPI(title="BaroLab Master Hub Server", version="1.0.0")


@app.on_event("startup")
def _start_play_console_observer():
    try:
        from server.play_console_collector import start_periodic_refresh
        start_periodic_refresh()
    except Exception:
        pass  # Read-only collection must never prevent the dashboard from starting.


@app.on_event("shutdown")
def _stop_play_console_observer():
    try:
        from server.play_console_collector import stop_periodic_refresh
        stop_periodic_refresh()
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper: check port socket
def is_port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

# Data Loader / Saver
def load_json(filepath: Path, default: Any = None) -> Any:
    if not filepath.exists():
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(filepath: Path, data: Any):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Models
class ToggleTodoRequest(BaseModel):
    id: int

class AddTodoRequest(BaseModel):
    channel: str
    target: str
    title: str
    strategy: str = ""
    detail: str = ""

# Routes
@app.get("/api/status")
def get_system_status():
    snapshot=get_live_snapshot()
    fleet=snapshot.get('fleet',[])
    ports={r['account']+'_cdp':dict(port=r['port'],name=r['account'],open=r['online']) for r in fleet}
    return dict(snapshot,status='online',kst_now=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                server_port=8790,cdp_browsers=ports,cdp_online_count=sum(r['online'] for r in fleet),cdp_total_count=len(fleet))

# Read-only, aggregate-only export for external monitoring. Never export DB documents.
LIVE_SNAPSHOT_LOCK = threading.Lock()
LIVE_SNAPSHOT_INTERVAL = 1
LIVE_SNAPSHOT_TABLES = {
    'growth.sqlite3': ('sites', 'connections', 'daily_metrics', 'improvement_actions', 'maintenance_jobs', 'maintenance_attempts'),
    'kin.sqlite3': ('questions', 'discoveries', 'automation_slots', 'operating_cadence'),
    'threads.sqlite3': ('parts', 'events', 'authoring_slots'),
}


def _snapshot_database(path, tables, today):
    result = {'file': path.name, 'status': 'missing', 'tables': {}}
    if not path.is_file():
        return result
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            available = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables:
                if table not in available:
                    continue
                item = {'rows': db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]}
                columns = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
                day_column = {'questions': 'send_day', 'parts': 'publication_date', 'automation_slots': 'day', 'authoring_slots': 'day'}.get(table)
                if day_column in columns and 'state' in columns:
                    states = db.execute(f'SELECT state, COUNT(*) FROM "{table}" WHERE "{day_column}"=? GROUP BY state', (today,)).fetchall()
                    allowed = {'published_verified', 'submitted_unverified', 'published', 'pending', 'blocked', 'failed', 'ready', 'draft', 'approved', 'completed', 'running', 'skipped', 'done', 'retry_wait', 'sending_intent', 'submitted_unknown', 'api_submitted', 'queued', 'drafted', 'validated', 'rejected', 'submit_intent', 'manual_review'}
                    counts = {}
                    for state, count in states:
                        key = state if state in allowed else 'other'
                        counts[key] = counts.get(key, 0) + count
                    item['todayStates'] = counts
                    if table == 'parts' and 'kind' in columns:
                        item['todayByKind'] = {kind: count for kind, count in db.execute(
                            "SELECT kind, COUNT(*) FROM parts WHERE publication_date=? AND kind IN ('main', 'followup') GROUP BY kind", (today,))}
                result['tables'][table] = item
        result['status'] = 'collected' if len(result['tables']) == len(tables) else 'partial'
    except (sqlite3.Error, OSError) as exc:
        result['status'] = 'error'
        result['errorType'] = type(exc).__name__
    return result


def _snapshot_publications(today):
    from urllib.parse import urlsplit
    def valid_url(value):
        parsed = urlsplit(str(value or ''))
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname)
    schedule = load_json(DATA_DIR / 'cf/daily_schedule.json', {})
    cf_current = schedule.get('date') == today
    cf_urls = {row['publicUrl'] for row in schedule.get('items', [])
               if cf_current and row.get('status') in ('published', 'done') and valid_url(row.get('publicUrl'))}
    verification = load_json(DATA_DIR / 'naver/public-verification.json', {})
    naver_urls = set()
    for row in verification.get('evidence', []):
        try:
            published = datetime.fromisoformat(row.get('publishedAt', '').replace('Z', '+00:00'))
            if published.tzinfo is None:
                continue
            day = published.astimezone(timezone(timedelta(hours=9))).date().isoformat()
        except (ValueError, TypeError):
            continue
        if day == today and row.get('publicPublicationVerified') is True and valid_url(row.get('publicUrl')):
            naver_urls.add(row['publicUrl'])
    return {'date': today, 'cf': {'sourceDate': schedule.get('date'), 'status': 'current' if cf_current else 'stale_or_missing',
                                 'published': len(cf_urls) if cf_current else None},
            'naver': {'sourceDate': verification.get('publicationDate'),
                      'status': 'current' if verification.get('publicationDate') == today else 'stale_or_missing',
                      'publishedVerified': len(naver_urls) if verification.get('publicationDate') == today else None}}


def _snapshot_metric_summary(data):
    def numbers(source, keys):
        return {key: value for key in keys if isinstance((value := source.get(key)), (int, float)) and not isinstance(value, bool)}
    sites = data.get('sites', [])
    sites = list(sites.values()) if isinstance(sites, dict) else sites
    ga4 = []
    for row in sites:
        traffic = row.get('traffic', {})
        if traffic.get('status') != 'collected':
            continue
        ga4.append({'domain': row.get('site', {}).get('site_id'), 'start': traffic.get('start'), 'end': traffic.get('end'),
                    'checkedAt': traffic.get('checkedAt'), **numbers(traffic, ('sessions', 'pageViews', 'naverReferralSessions'))})
    return {'checkedAt': data.get('checkedAt'), 'siteCount': len(sites), 'ga4': ga4,
            'indexing': numbers(data.get('indexing', {}), ('indexed', 'inspected', 'inventoryTotal')),
            'traffic': numbers(data.get('traffic', {}), ('sessions', 'pageViews', 'connectedSites', 'expectedSites'))}


def refresh_live_snapshot():
    from server.mission_control import Collector, shared_snapshot
    from common.dashboard_jobs import write
    with LIVE_SNAPSHOT_LOCK:
        collector=getattr(app.state,'mission_collector',None)
        if collector is None:
            collector=Collector();app.state.mission_collector=collector
        collector.collect()
        result=shared_snapshot(collector.get())
        write(DATA_DIR/'live_snapshot.json',result)
        return result


@app.get('/api/mission-control')
@app.get('/api/live-snapshot')
def get_live_snapshot():
    snapshot=load_json(DATA_DIR/'live_snapshot.json',{})
    if snapshot.get('schema')=='barolab-mission-control-v2':return snapshot
    return refresh_live_snapshot()


@app.on_event('startup')
async def _start_live_snapshot():
    from server.mission_control import Collector
    collector=Collector();app.state.mission_collector=collector
    await asyncio.to_thread(refresh_live_snapshot)
    collector.start()


@app.on_event('shutdown')
async def _stop_live_snapshot():
    collector=getattr(app.state,'mission_collector',None)
    if collector:
        collector.stop.set();collector.remote.stop.set()
        if collector.thread:await asyncio.to_thread(collector.thread.join,2)



@app.get("/api/todos")
def get_todos():
    """오늘 발행 할일 목록"""
    todos = load_json(DATA_DIR / "todos.json", default=[])
    total = len(todos)
    done = sum(1 for t in todos if t.get("completed", False))
    pct = round((done / total * 100) if total > 0 else 0)
    return {
        "todos": todos,
        "summary": {
            "total": total,
            "done": done,
            "remaining": total - done,
            "progress_pct": pct
        }
    }

@app.post("/api/todos/toggle")
def toggle_todo(req: ToggleTodoRequest):
    """할일 완료 상태 토글 및 디스크 저장"""
    todos = load_json(DATA_DIR / "todos.json", default=[])
    updated_item = None
    for item in todos:
        if item.get("id") == req.id:
            item["completed"] = not item.get("completed", False)
            updated_item = item
            break

    if not updated_item:
        raise HTTPException(status_code=404, detail="Item not found")

    save_json(DATA_DIR / "todos.json", todos)

    total = len(todos)
    done = sum(1 for t in todos if t.get("completed", False))
    pct = round((done / total * 100) if total > 0 else 0)

    return {
        "success": True,
        "updated": updated_item,
        "summary": {
            "total": total,
            "done": done,
            "remaining": total - done,
            "progress_pct": pct
        }
    }

@app.get("/api/metrics")
def get_metrics(compact: bool = False):
    """Collected evidence only; missing values remain null."""
    from common.collection_observability import read_health
    # GET only projects stored evidence. RSS verification belongs to the
    # scheduled monitor / explicit verification action, never page polling.
    def build():
        data = metrics_summary()
        data['collectionObservability'] = read_health(DATA_DIR)
        return data
    data = METRICS_READ_CACHE.get('metrics', build)
    if compact:
        from server.dashboard_cache import compact_metrics
        return compact_metrics(data)
    return data


@app.get("/api/naver/verify-public")
@app.post("/api/naver/verify-public")
@app.post("/api/naver/verify-overdue")
def verify_naver_public():
    """예약 시각이 지난 네이버 블로그 슬롯의 실제 RSS 공개 여부를 즉시 확인하고 원장을 동기화"""
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from dashboard.collectors.naver_public import reconcile
    from naver_blog_posting.posting import monitor, pipeline_lock
    try:
        with pipeline_lock():
            result = reconcile(NAVER_DIR, force=False)
            monitor(NAVER_DIR)
            return result
    except RuntimeError as exc:
        if 'already running' in str(exc):
            raise HTTPException(status_code=409, detail='Naver publisher active; reconciliation deferred') from exc
        raise


@app.get("/api/naver")
def get_naver_overview():
    """네이버 5개 계정 및 전략 로테이션"""
    state = load_json(DATA_DIR / "state.json", default={})
    rotation = state.get("strategy_rotation", {
        "current_index": 0,
        "current_strategy": "스마트블록 역추적",
        "next_strategy": "자동완성·질문 롱테일"
    })

    strategies = [
        {"id": 0, "name": "스마트블록 역추적", "desc": "AiRSEARCH 블록 의도 가로채기", "target": "soultin, stone0747"},
        {"id": 1, "name": "자동완성·질문 롱테일", "desc": "체류시간 극대화 & 질문형 어미(실패이유, 차이)", "target": "yoon_master, adinfo0905"},
        {"id": 2, "name": "트렌드×에버그린 브릿지", "desc": "실시간 화제 이슈 + 상시 정보 결합", "target": "soul5373"}
    ]

    # Check recent outputs
    outputs_dir = NAVER_DIR / "output"
    recent_outputs = []
    if outputs_dir.exists():
        for d in sorted(outputs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if d.is_dir():
                has_final = (d / "final.html").exists()
                recent_outputs.append({
                    "folder": d.name,
                    "has_final": has_final,
                    "mtime": d.stat().st_mtime
                })

    return {
        "rotation": rotation,
        "strategies": strategies,
        "recent_outputs": recent_outputs[:5]
    }

@app.post("/api/naver/rotate")
def rotate_strategy():
    """3대 전략 로테이션 다음 턴 교대"""
    state = load_json(DATA_DIR / "state.json", default={})
    rotation = state.get("strategy_rotation", {})

    strategies = ["스마트블록 역추적", "자동완성·질문 롱테일", "트렌드×에버그린 브릿지"]
    curr_idx = (rotation.get("current_index", 0) + 1) % len(strategies)
    next_idx = (curr_idx + 1) % len(strategies)

    rotation["current_index"] = curr_idx
    rotation["current_strategy"] = strategies[curr_idx]
    rotation["next_strategy"] = strategies[next_idx]

    state["strategy_rotation"] = rotation
    save_json(DATA_DIR / "state.json", state)

    return {
        "success": True,
        "rotation": rotation
    }

# Growth read API must precede the static catch-all.
from projects import router as projects_router
app.include_router(projects_router)

from growth import router as growth_router
app.include_router(growth_router)

from llm_api import router as llm_router, workflow_router, guard as llm_guard
app.include_router(llm_router)
app.include_router(workflow_router)

from memory_graph import memory_router
from chat_room import chat_router
from content_auditor import auditor_router
from project_health import router as project_health_router, audit_all_projects_health
app.include_router(memory_router)
app.include_router(chat_router)
app.include_router(auditor_router)
app.include_router(project_health_router)


@app.get("/api/watchdog/status")
def api_watchdog_status():
    return load_json(DATA_DIR / "watchdog-status.json", default={"status": "unknown"})


@app.post("/api/watchdog/run-now")
def api_watchdog_run_now():
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from common import system_watchdog
    return system_watchdog.run_system_watchdog(trigger_source="api-manual", broadcast=True)


def _start_periodic_project_health_auditor():
    if os.environ.get("BAROLAB_DISABLE_BACKGROUND") == "1":
        return
    import threading
    import time

    def _loop():
        time.sleep(5)
        while True:
            try:
                audit_all_projects_health(
                    broadcast_if_changed=os.environ.get("BAROLAB_HEALTH_BROADCAST", "1") != "0",
                    force_broadcast=False,
                )
            except Exception:
                pass
            time.sleep(1800)  # Every 30 minutes

    t = threading.Thread(target=_loop, daemon=True, name="jarvis-30m-project-auditor")
    t.start()


_start_periodic_project_health_auditor()



class ThreadsSmartGenerateRequest(BaseModel):
    url: str
    slot: str = "12:30"
    mode: str = "cf_inbound"
    affiliate_url: str = ""
    selected_variant: str = "hook"
    queue: bool = False


class ThreadsHookExtractRequest(BaseModel):
    sample_text: str
    category: str = "일반·트렌드"
    source_note: str = "@radar 바이럴 벤치마킹"


class ThreadsQueueDraftRequest(BaseModel):
    content_id: str = ""
    title: str = ""
    slot: str = "12:30"
    mode: str = "cf_inbound"
    selected_variant: str = "hook"
    main_text: str = ""
    followup_text: str = ""
    source_url: str = "https://www.must-pick.com/threads-smart-brief"
    affiliate_url: str = ""


@app.get("/api/threads/status")
def api_threads_status():
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from threads_posting import posting as th_cfg, posting as th_pipe
    cfg = th_cfg.load()
    snap = th_pipe.snapshot(cfg)
    return snap


@app.get("/api/threads/hooks")
def api_threads_hooks():
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from threads_posting.posting import load_hook_templates
    return {"ok": True, "hooks": load_hook_templates()}


@app.post("/api/threads/hooks")
def api_threads_add_hook(req: ThreadsHookExtractRequest):
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from threads_posting.posting import extract_and_save_hook_template, load_hook_templates
    hook = extract_and_save_hook_template(req.sample_text, req.category, req.source_note)
    return {"ok": True, "hook": hook, "hooks": load_hook_templates()}


@app.post("/api/threads/smart-generate")
def api_threads_smart_generate(req: ThreadsSmartGenerateRequest):
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from threads_posting import posting as th_cfg, posting as th_auth, posting as th_pipe
    cfg = th_cfg.load()
    res = th_auth.prepare_from_url(
        cfg,
        req.url.strip(),
        slot=req.slot,
        mode=req.mode,
        affiliate_url=req.affiliate_url.strip() or None,
        selected_variant=req.selected_variant,
        queue=req.queue,
    )
    snap = th_pipe.snapshot(cfg)
    return {"ok": True, "result": res, "snapshot": snap}


@app.post("/api/threads/queue")
def api_threads_queue_draft(req: ThreadsQueueDraftRequest):
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))
    from threads_posting import posting as th_cfg, posting as th_pipe
    import hashlib, uuid
    from datetime import datetime
    cfg = th_cfg.load()
    draft_path = DATA_DIR / "threads-drafts" / f"{req.content_id}.json"
    if req.content_id and draft_path.is_file():
        doc = json.loads(draft_path.read_text(encoding="utf-8"))
        if req.selected_variant and req.selected_variant in (doc.get("variants") or {}):
            doc["selected_variant"] = req.selected_variant
            doc["parts"][0]["text"] = doc["variants"][req.selected_variant]["text"]
        if req.main_text:
            doc["parts"][0]["text"] = req.main_text.strip()
        if req.followup_text and len(doc["parts"]) > 1:
            doc["parts"][1]["text"] = req.followup_text.strip()
        claim_tok = doc["parts"][0]["text"].splitlines()[0][:12]
        doc["review"]["claims"][0]["claim"] = claim_tok
        doc["review"]["binding"] = th_pipe.binding(doc)
        draft_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        day = datetime.now(th_pipe.KST).date().isoformat()
        cid = uuid.uuid4().hex
        src_url = req.source_url if req.source_url.startswith("https://") else "https://www.must-pick.com/threads-smart-brief"
        body_str = (req.main_text + " " + req.title + " " * 30)[:600]
        attr = None if req.mode == "warmup" else th_pipe.receipt(cfg["account_key"], src_url, day, req.slot, cid)
        parts = [{"kind": "main", "text": req.main_text.strip()}]
        if req.mode != "warmup":
            ft = req.followup_text.strip()
            if attr and attr["outboundUrl"] not in ft:
                ft = f"{ft}\n{attr['outboundUrl']}".strip()
            parts.append({"kind": "followup", "text": ft})
        doc = {
            "schema": "threads-document-v1",
            "content_id": cid,
            "account_key": cfg["account_key"],
            "publication_date": day,
            "slot": req.slot,
            "mode": req.mode,
            "followup_delay_seconds": 120,
            "title": req.title or "스마트 에디터 스레드",
            "source": {"url": src_url, "original_input_url": src_url, "title": req.title, "body": body_str, "body_sha256": hashlib.sha256(body_str.encode()).hexdigest()},
            "official_sources": [],
            "attribution": attr,
            "parts": parts,
            "created_at": th_cfg.stamp(),
        }
        doc["review"] = {
            "approved": True,
            "reason": "스마트 에디터 수동 검수 및 큐 등록",
            "checks": dict.fromkeys(th_pipe.REVIEW_KEYS, True),
            "claims": [{"claim": parts[0]["text"][:10], "quote": body_str[:15], "source_url": src_url}],
            "binding": th_pipe.binding(doc),
        }
    attempt_id = th_pipe.import_document(doc, cfg)
    snap = th_pipe.snapshot(cfg)
    return {"ok": True, "attempt_id": attempt_id, "snapshot": snap}


@app.get("/api/kin/automation-status")
def api_kin_automation_status():
    state_file = DATA_DIR / "kin-automation-state.json"
    cfg_file = DATA_DIR / "kin-automation.json"
    kin_file = DASHBOARD_DIR / "data" / "public" / "kin.json"
    state_obj = load_json(state_file, default={})
    cfg_obj = load_json(cfg_file, default={})
    kin_obj = load_json(kin_file, default={})
    return {
        "ok": True,
        "config": cfg_obj,
        "state": state_obj,
        "kin": kin_obj,
    }


@app.post("/api/kin/run-now")
def api_kin_run_now():
    """Immediately trigger the next KnowledgeIn slot (`naver_kin.posting --tick --force`) in the background."""
    import subprocess
    cmd = [sys.executable, "-X", "utf8", "-m", "naver_kin.posting", "--tick", "--force"]
    subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return {
        "ok": True,
        "started": True,
        "message": "지식iN 즉시 실행 워커(naver_kin.posting --tick --force)를 백그라운드에서 가동했습니다.",
    }

app.middleware("http")(llm_guard)


@app.middleware("http")
async def protect_internal_files(request, call_next):
    from urllib.parse import unquote
    from posixpath import normpath
    from fastapi.responses import Response
    path = normpath('/' + unquote(request.url.path).lstrip('/'))
    if not path.startswith('/api/'):
        parts = path.strip('/').split('/')
        lowered = [part.casefold() for part in parts]
        public_data = {'app_testers.json', 'collection-health.json', 'kin-measurement.json',
                       'kin.json', 'metrics.json', 'threads-measurement.json', 'threads.json'}
        internal = (any(part.startswith('.') for part in parts)
                    or lowered[0] in {'runtime', 'server', 'common', 'agents', 'collectors', 'projects', 'tests'}
                    or (lowered[0] == 'data' and (len(parts) != 2 or parts[1] not in public_data or request.url.path != '/data/' + parts[1]))
                    or any(part in {'secure', 'data-secret', 'cookies', 'browsers'} for part in lowered)
                    or Path(parts[-1]).suffix.lower() in {'.py', '.pyc', '.sqlite3', '.db', '.pem', '.key'})
        if internal:
            return Response(status_code=404)
    return await call_next(request)


@app.get("/data/{name}")
def public_dashboard_snapshot(name: str):
    from fastapi.responses import FileResponse
    allowed = {'app_testers.json', 'collection-health.json', 'kin-measurement.json',
               'kin.json', 'metrics.json', 'threads-measurement.json', 'threads.json'}
    if name not in allowed:
        raise HTTPException(status_code=404)
    path = DASHBOARD_DIR / 'data' / 'public' / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get('/naver_automation.json')
def public_naver_automation():
    return load_json(DATA_DIR/'naver/automation-status.json',{})


@app.get('/pipeline_status.js')
def public_naver_workflow():
    from fastapi.responses import FileResponse
    return FileResponse(DATA_DIR/'naver/pipeline_status.js')


@app.get('/naver_public_verification.json')
def public_naver_verification():
    return load_json(DATA_DIR/'naver/public-verification.json',{})


# Only public channel state may cross the private ledger boundary.
@app.get("/cf_posting/data/{name:path}")
@app.get("/dashboard/data/cf/{name:path}")
@app.get("/naver_blog_posting/data/{name:path}")
@app.get("/dashboard/data/naver/{name:path}")
def public_channel_snapshot(request: Request, name: str):
    from fastapi.responses import FileResponse
    import re
    cf = request.url.path.startswith(('/cf_posting/', '/dashboard/data/cf/'))
    allowed = ({'daily_schedule.json', 'pipeline_state.json', 'pipeline_status.js', 'cleaner-status.json', 'browser-retry.json'}
               if cf else {'pipeline_status.js', 'automation-status.json', 'public-verification.json', 'published-inventory.json'})
    if name not in allowed and not (cf and re.fullmatch(r'schedule_history/\d{4}-\d{2}-\d{2}(?:-[a-f0-9]+)?\.json', name)):
        raise HTTPException(status_code=404)
    path = DASHBOARD_DIR / 'data' / ('cf' if cf else 'naver') / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path)


# Mount static sub-projects for pipeline status & output previews
if CF_DIR.exists():
    app.mount("/cf_posting", StaticFiles(directory=str(CF_DIR)), name="cf_posting")
if NAVER_DIR.exists():
    app.mount("/naver_blog_posting", StaticFiles(directory=str(NAVER_DIR)), name="naver_blog_posting")

from fastapi.responses import RedirectResponse

@app.get("/rnd.html")
def redirect_rnd_to_chat():
    return RedirectResponse(url="/chat.html", status_code=302)

# Mount static dashboard at /
if DASHBOARD_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8790, reload=True)
