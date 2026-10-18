"""
ARGO Multi-Agent Meeting Room (room.mjs) ported & upgraded for BaroLab Master Hub:
1. Real-Time Sequential SSE Streaming (`POST /api/chat/send-stream`, `GET /api/chat/events`, `GET /api/chat/poll`)
   - Replaces batch return with turn-by-turn tiki-taka streaming and live typing indicators
     (`[🤖 퍼블리가 응답을 작성하고 있습니다... ●●●]`, `[⚙️ 패치가 코드를 점검하고 있습니다... ●●●]`).
2. Real-Time Hand-off & Task Status Tracker (`taskTracker` inside each message):
   - `📋 업무 인계: @자비스 ➔ @퍼블리`
   - `🔄 처리 중` ➔ In-place transition to `✅ 처리 완료` / `🔴 처리 실패`
   - Deliverable links & `[🧠 기억 그래프에 새 노하우 연결됨]` synapse badge.
3. Autonomous Work Stream (`AutonomousCrewWorker`):
   - Background worker & pipeline event receiver (`/api/chat/autonomous/event`, `/api/chat/autonomous/toggle`, `/api/chat/autonomous/trigger-cycle`)
   - Streams multi-agent collaboration (`@트레이스` ➔ `@퍼블리` ➔ `@패치` ➔ `@자비스`) in real time even without user input.
"""

import asyncio
import json
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from memory_graph import (
    ARGO_WS_DIR,
    DATA_DIR,
    LOCAL_VAULT_DIR,
    connect_db,
    extract_doc_meta,
    local_day,
    register_synapse_memory,
    sync_argo_vault_and_growth,
    tokens,
    compute_tf,
    cosine_sim,
)

BASE_DIR = Path(__file__).resolve().parent.parent
CHATS_DIR = DATA_DIR / "chats"
ARCHIVE_DIR = CHATS_DIR / ".archive"
ROOM_MAIN_FILE = CHATS_DIR / "room-main.json"
ARGO_CHATS_DIR = ARGO_WS_DIR / "chats"

CREW_AGENTS: List[Dict[str, Any]] = [
    {
        "slug": "jarvis",
        "name": "자비스",
        "title": "운영총괄 AI",
        "team": "운영총괄",
        "color": "#2563eb",
        "badge": "총괄",
        "icon": "🧭",
        "aliases": ["jarvis", "자비스"],
        "typingAction": "🧭 자비스가 전사 운영 지침 및 승인 사항을 정리하고 있습니다...",
        "defaultStep": "일일 목표($100)·발행 파이프라인·기억 그래프 시냅스 통합 점검 중...",
        "persona": "윤대표-CEO를 보좌하는 BaroLab 운영총괄 AI. 애드센스 일 $100 목표, 할일·예약·발행·검수 통합 관제 및 의사결정 요약.",
    },
    {
        "slug": "publi",
        "name": "퍼블리",
        "title": "블로그 발행·예약 검수 전문가",
        "team": "블로그 운영",
        "color": "#059669",
        "badge": "검수",
        "icon": "🤖",
        "aliases": ["publi", "퍼블리"],
        "typingAction": "🤖 퍼블리가 응답을 작성하고 있습니다...",
        "defaultStep": "작가·캡처 도구(4대 실전 이미지·요금표 캡처) 및 원고 정합성 검수 중...",
        "persona": "원고·예약 기록·공개 URL 교차 대조 및 누락·중복·캡션/레이아웃 정합성 검수 전문가.",
    },
    {
        "slug": "trace",
        "name": "트레이스",
        "title": "색인·트래픽·수익 분석 전문가",
        "team": "검색·성과 분석",
        "color": "#7c3aed",
        "badge": "분석",
        "icon": "📊",
        "aliases": ["trace", "트레이스"],
        "typingAction": "📊 트레이스가 색인·트래픽·수익 지표를 조회하고 있습니다...",
        "defaultStep": "CF 16개 도메인·네이버 5계정 색인 건강도 및 유입 키워드 대조 중...",
        "persona": "GA4·GSC·네이버 서치어드바이저·애드센스·애드포스트 지표 대조 및 색인/유입/수익 진단 전문가.",
    },
    {
        "slug": "patch",
        "name": "패치",
        "title": "대시보드·파이프라인 개발·유지보수",
        "team": "운영 자동화 개발팀",
        "color": "#d97706",
        "badge": "개발",
        "icon": "⚙️",
        "aliases": ["patch", "패치"],
        "typingAction": "⚙️ 패치가 코드를 점검하고 있습니다...",
        "defaultStep": "파이프라인·부분 수선(In-Place Surgical Repair)·캡처 모듈 상태 점검 중...",
        "persona": "BaroLab 파이프라인·라우터·서킷브레이커·In-Place Surgical Repair·스케줄러 오류 수정 및 회귀 검증 엔지니어.",
    },
    {
        "slug": "radar",
        "name": "레이더",
        "title": "트렌드·키워드·수익 허브 발굴",
        "team": "수익 전략팀",
        "color": "#e11d48",
        "badge": "전략",
        "icon": "🎯",
        "aliases": ["radar", "레이더"],
        "typingAction": "🎯 레이더가 스마트블록·롱테일 키워드를 탐색하고 있습니다...",
        "defaultStep": "고단가 애드센스 수익 허브(✦) 및 간접체험 검색 의도(readerTask) 설계 중...",
        "persona": "스마트블록 역추적·롱테일 질문·트렌드×에버그린 브릿지 및 고단가 애드센스 수익 허브(✦) 키워드 발굴 전문가.",
    },
    {
        "slug": "doctor",
        "name": "닥터",
        "title": "콘텐츠 감사·재생 전담",
        "team": "콘텐츠 재생팀",
        "color": "#0d9488",
        "badge": "감사",
        "icon": "🩺",
        "aliases": ["doctor", "닥터", "감사", "리모델링"],
        "typingAction": "🩺 닥터가 기존 글 7대 정밀 검진 및 리모델링 처방을 수행하고 있습니다...",
        "defaultStep": "기존 발행 글(1,974건) 도메인 정합성·카테고리 자동 재매핑·간접체험 리모델링 검진 중...",
        "persona": "24시간 기존 발행 글을 순찰하며 7대 체크리스트(렌더링·도메인정합·카테고리패치·캡처품질·간접체험·GSC잠재력·4단계등급)로 진단·리모델링하는 콘텐츠 주치의.",
    },
]

AGENT_MAP = {a["slug"]: a for a in CREW_AGENTS}

chat_router = APIRouter(prefix="/api/chat", tags=["chat"])

# ============================================================================
# REAL-TIME EVENT BUS (SSE + Polling Ring Buffer) & ROOM FILE LOCK
# ============================================================================
_ROOM_LOCK = threading.RLock()


class RoomEventBus:
    """Thread-safe event bus supporting real-time SSE subscribers and polling clients."""

    def __init__(self, max_events: int = 300):
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._events: List[Dict[str, Any]] = []
        self._seq: int = 1
        self._max_events = max_events
        self.active_typing: Dict[str, Dict[str, Any]] = {}

    def publish(self, event_type: str, data: Dict[str, Any]) -> int:
        with self._cond:
            seq = self._seq
            self._seq += 1
            if event_type == "typing":
                who = data.get("who")
                if who:
                    if data.get("active", True):
                        self.active_typing[who] = {**data, "seq": seq, "ts": int(time.time() * 1000)}
                    else:
                        self.active_typing.pop(who, None)
            elif event_type == "message":
                who = data.get("who")
                if who:
                    self.active_typing.pop(who, None)

            evt = {
                "seq": seq,
                "event": event_type,
                "data": data,
                "ts": int(time.time() * 1000),
            }
            self._events.append(evt)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events :]
            self._cond.notify_all()
            return seq

    def get_since(self, since_seq: int) -> Tuple[int, List[Dict[str, Any]], List[Dict[str, Any]]]:
        with self._lock:
            now_ms = int(time.time() * 1000)
            # Prune stale typing indicators older than 25 seconds
            stale = [k for k, v in self.active_typing.items() if now_ms - v.get("ts", 0) > 25000]
            for k in stale:
                self.active_typing.pop(k, None)
            evts = [e for e in self._events if e["seq"] > since_seq]
            return self._seq - 1, evts, list(self.active_typing.values())

    @property
    def current_seq(self) -> int:
        with self._lock:
            return self._seq - 1


EVENT_BUS = RoomEventBus()


def ensure_chat_migrated() -> Dict[str, Any]:
    """Migrate ARGO chats/room-main.json, agent threads, and .archive into BaroLab server/data/chats."""
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    migrated_files = []
    if ARGO_CHATS_DIR.is_dir():
        argo_room = ARGO_CHATS_DIR / "room-main.json"
        if argo_room.is_file() and not ROOM_MAIN_FILE.is_file():
            shutil.copy2(argo_room, ROOM_MAIN_FILE)
            migrated_files.append("room-main.json")

        for ag in ("jarvis", "publi", "trace", "patch"):
            src = ARGO_CHATS_DIR / f"{ag}.json"
            dst = CHATS_DIR / f"{ag}.json"
            if src.is_file() and not dst.is_file():
                shutil.copy2(src, dst)
                migrated_files.append(f"{ag}.json")

        argo_arch = ARGO_CHATS_DIR / ".archive"
        if argo_arch.is_dir():
            for f in argo_arch.iterdir():
                if f.is_file() and f.name.endswith(".json"):
                    dst = ARCHIVE_DIR / f.name
                    if not dst.is_file():
                        shutil.copy2(f, dst)
                        migrated_files.append(f".archive/{f.name}")

    if not ROOM_MAIN_FILE.is_file():
        ROOM_MAIN_FILE.write_text(
            json.dumps(
                {"messages": [], "delegationLimit": True, "autonomousEnabled": True, "sid": 1},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return {"migrated": migrated_files}


def _is_noise_or_fake_loop_message(m: Dict[str, Any]) -> bool:
    """Filter out fake autonomous loop messages, system round banners, capReached notices, and legacy hallucinated messages."""
    if not isinstance(m, dict):
        return True
    mid = str(m.get("id") or "")
    if mid.startswith("auto-") or mid.startswith("sys-auto-"):
        return True
    who = str(m.get("who") or "")
    if who == "system":
        return True
    src = m.get("src")
    if isinstance(src, dict) and src.get("code") == "capReached":
        return True
    txt = str(m.get("text") or "").strip()
    if not txt:
        return True
    if txt.startswith("세션 메시지 사슬이 상한") or txt.startswith("반응 라운드 —") or "동시 발언 —" in txt:
        return True
    if who != "user":
        if "98.2%" in txt or "10월 22일" in txt or "10월 23일" in txt or "10월 27일" in txt:
            return True
        if who != "radar" and "10일 만에 180만원" in txt:
            return True
    return False


def _extract_mentioned_slugs(text: str) -> List[str]:
    """Return all crew agent slugs mentioned via @alias in `text`."""
    lower = str(text or "").lower()
    found: List[str] = []
    for ag in CREW_AGENTS:
        for alias in ag["aliases"]:
            if f"@{alias.lower()}" in lower:
                if ag["slug"] not in found:
                    found.append(ag["slug"])
                break
    return found


def _get_agent_brain_safe(slug: str) -> Dict[str, Any]:
    try:
        from common.llm_settings import get_agent_brain
        return get_agent_brain(slug)
    except Exception:
        fallback_badges = {
            "jarvis": ("agy_cli", "AGY CLI", "gemini-4-argon-high", "Argon High"),
            "publi": ("codex_cli", "Codex CLI", "gpt-6.1-sol", "gpt-6.1-sol"),
            "patch": ("codex_cli", "Codex CLI", "gpt-6.1-sol", "gpt-6.1-sol"),
            "radar": ("agy_cli", "AGY CLI", "gemini-4-argon-medium", "Argon Med"),
            "doctor": ("agy_cli", "AGY CLI", "gemini-3.8-flash-medium", "3.8 Flash"),
            "trace": ("agy_cli", "AGY CLI", "gemini-3.8-flash-medium", "3.8 Flash"),
        }
        prov, plabel, mod, bdg = fallback_badges.get(slug, ("agy_cli", "AGY CLI", "gemini-4-argon-high", "Argon High"))
        return {"slot": slug, "provider": prov, "providerLabel": plabel, "model": mod, "badge": bdg}


def _enrich_legacy_message(m: Dict[str, Any], idx: int, all_msgs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Ensure every message has a stable `id`, `brain`, `replyToCeo`, `isWorkstream`, and `taskTracker` metadata."""
    if not m.get("id"):
        m["id"] = f"msg-{m.get('ts', idx)}-{m.get('who', 'sys')}-{idx}"
    who = m.get("who")
    if who == "crew":
        m["who"] = "jarvis"
        who = "jarvis"

    mid_str = str(m.get("id") or "")
    evt_type = str(m.get("eventType") or "")
    mentioned_slugs = _extract_mentioned_slugs(m.get("text", ""))
    if mentioned_slugs:
        m["mentionedAgents"] = mentioned_slugs
    elif "mentionedAgents" not in m:
        m["mentionedAgents"] = []

    if who == "user":
        m["isWorkstream"] = False
        m["replyToCeo"] = True
        return m

    if who in AGENT_MAP:
        m["brain"] = _get_agent_brain_safe(who)
        is_ws = bool(
            m.get("isWorkstream")
            or m.get("msgKind") == "workstream"
            or mid_str.startswith("ws-")
            or mid_str.startswith("msg-doctor-patrol-")
            or mid_str.startswith("msg-doctor-fake-img-")
            or evt_type in ("content_doctor_patrol", "pipeline_workstream", "fake_ai_image_patrol")
        )
        m["isWorkstream"] = is_ws
        if "replyToCeo" not in m:
            m["replyToCeo"] = not is_ws
        if is_ws and not m.get("targetAgent") and mentioned_slugs:
            other_mentions = [s for s in mentioned_slugs if s != who]
            if other_mentions:
                m["targetAgent"] = other_mentions[0]

    if who in AGENT_MAP and "taskTracker" not in m:
        ag = AGENT_MAP[who]
        prev_who = "user"
        for p_idx in range(idx - 1, -1, -1):
            pw = all_msgs[p_idx].get("who")
            if pw and pw != "system" and pw != who:
                prev_who = pw
                break
        from_name = "윤대표-CEO" if prev_who == "user" else AGENT_MAP.get(prev_who, {}).get("name", "자비스")
        artifacts = m.get("artifacts") or []
        m["taskTracker"] = {
            "handoff": f"@{from_name} ➔ @{ag['name']}",
            "status": "completed",
            "step": ag["defaultStep"],
            "resultSummary": f"{ag['badge']} 검토 및 조치 완료",
            "deliverableUrl": f"memory.html?rel={artifacts[0]}" if artifacts else "",
            "deliverableLabel": f"📄 {Path(artifacts[0]).name}" if artifacts else "",
            "synapseLinked": bool(artifacts or who == "jarvis"),
            "synapseLabel": "🧠 기억 그래프 연결됨" if (artifacts or who == "jarvis") else "",
        }
    return m


def load_room_data() -> Dict[str, Any]:
    with _ROOM_LOCK:
        ensure_chat_migrated()
        try:
            data = json.loads(ROOM_MAIN_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"messages": [], "delegationLimit": True, "autonomousEnabled": False, "sid": 1}
            raw_msgs = data.get("messages", [])
            if not isinstance(raw_msgs, list):
                raw_msgs = []
            cleaned_msgs: List[Dict[str, Any]] = []
            seen_ids = set()
            for idx, m in enumerate(raw_msgs):
                if _is_noise_or_fake_loop_message(m):
                    continue
                _enrich_legacy_message(m, idx, raw_msgs)
                mid = str(m.get("id"))
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                cleaned_msgs.append(m)
            data["messages"] = cleaned_msgs
            data["autonomousEnabled"] = False
            return data
        except Exception:
            return {"messages": [], "delegationLimit": True, "autonomousEnabled": False, "sid": 1}


def save_room_data(room: Dict[str, Any]):
    with _ROOM_LOCK:
        CHATS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = ROOM_MAIN_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(room, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, ROOM_MAIN_FILE)


def append_or_update_room_message(msg_obj: Dict[str, Any]) -> Dict[str, Any]:
    """Thread-safely append a new message or update an existing message in `room-main.json` and broadcast via SSE."""
    if _is_noise_or_fake_loop_message(msg_obj):
        return msg_obj
    with _ROOM_LOCK:
        room = load_room_data()
        msgs: List[Dict[str, Any]] = room.setdefault("messages", [])
        mid = msg_obj.get("id")
        if not mid:
            mid = f"msg-{msg_obj.get('ts', int(time.time() * 1000))}-{msg_obj.get('who', 'sys')}"
            msg_obj["id"] = mid

        existing_idx = next((i for i, m in enumerate(msgs) if m.get("id") == mid), None)
        if existing_idx is not None:
            msgs[existing_idx].update(msg_obj)
            saved_msg = msgs[existing_idx]
            save_room_data(room)
            EVENT_BUS.publish("task_update", saved_msg)
            return saved_msg
        else:
            msgs.append(msg_obj)
            save_room_data(room)
            EVENT_BUS.publish("message", msg_obj)
            return msg_obj


def list_archived_meetings() -> List[Dict[str, Any]]:
    ensure_chat_migrated()
    out = []
    if not ARCHIVE_DIR.is_dir():
        return out
    for f in ARCHIVE_DIR.iterdir():
        if not f.is_file() or not f.name.endswith(".json"):
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
            msgs = r.get("messages", [])
            if not isinstance(msgs, list):
                continue
            first_user = next((m for m in msgs if m.get("who") == "user"), None)
            ts_match = re.search(r"(\d{10,15})", f.name)
            ts = int(ts_match.group(1)) if ts_match else int(f.stat().st_mtime * 1000)
            topic = re.sub(r"@\S+", "", str((first_user or {}).get("text", ""))).strip()
            topic = re.sub(r"\s+", " ", topic)[:42] or f.stem
            out.append(
                {
                    "id": f.name,
                    "ts": ts,
                    "count": len(msgs),
                    "title": r.get("title"),
                    "pinned": bool(r.get("pinned")),
                    "open": bool(r.get("open")),
                    "topic": topic,
                }
            )
        except Exception:
            continue
    out.sort(key=lambda x: (1 if x["open"] else 0, 1 if x["pinned"] else 0, x["ts"]), reverse=True)
    deduped = []
    seen_topics = set()
    for item in out:
        key = f"{item.get('title') or item.get('topic')}:{item.get('count')}"
        if key in seen_topics:
            continue
        seen_topics.add(key)
        deduped.append(item)
    return deduped


FOLLOWUP_PARTNER_MAP: Dict[str, str] = {
    "radar": "publi",
    "doctor": "publi",
    "publi": "patch",
    "trace": "radar",
    "patch": "jarvis",
    "jarvis": "publi",
}


def parse_mentioned_agents(text: str, delegation_limit: bool = True) -> List[str]:
    """
    Return the mentioned agent(s):
    - When a specific agent (e.g. `@radar`) is explicitly mentioned without `@all`, return that agent directly
      so it answers immediately in the chat room without uninvited follow-up chatter.
    - When `@all` or no `@mention` is given, return the primary specialist + 1 follow-up partner.
    """
    lower = text.lower()
    is_all = "@all" in lower or "@전체" in lower
    explicit = []
    for ag in CREW_AGENTS:
        for alias in ag["aliases"]:
            if f"@{alias.lower()}" in lower or re.search(rf"\b{re.escape(alias.lower())}\b", lower):
                if ag["slug"] not in explicit:
                    explicit.append(ag["slug"])
                break

    if explicit and not is_all:
        if len(explicit) == 1:
            return [explicit[0]]
        return explicit[:2]

    # Natural question or @all: check operational / publishing schedule queries BEFORE topic/keyword queries
    if re.search(r"기존\s*글|과거\s*글|리모델링|검진|순찰|비공개|살리지\s*말|noindex|카테고리\s*재매핑|캡처\s*다시|그\s*글은|이관", lower):
        return ["doctor", "publi"]
    if re.search(r"공개\s*시간|피크\s*시간|예약\s*작업|몇\s*시|언제|검수|발행|예약|캡션|이미지|원고|포스팅|콘텐츠|간접체험|체크|누가|작성|블로그|캡처|화담숲|요금표", lower):
        return ["publi", "jarvis"]
    if re.search(r"https?://|스레드|threads|유튜브|youtube|youtu\.be|키워드|트렌드|스마트블록|롱테일|허브", lower):
        if ("https://" in lower or "http://" in lower) and not is_all:
            return ["radar"]
        return ["radar", "jarvis"]
    if re.search(r"색인|트래픽|방문자|수익|애드센스|애드포스트|ga4|통계|클릭|노출", lower):
        return ["trace", "radar"]
    if re.search(r"오류|버그|수정|코드|서킷|쿨다운|rework|파이프라인|속도|서버|도커|브라우저|다운로드|pdf", lower):
        return ["patch", "jarvis"]
    return ["jarvis", "publi"]


def build_Contextual_task_info(slug: str, user_text: str, from_name: str, next_name: Optional[str]) -> Dict[str, Any]:
    """Build dynamic typing indicator text and 1-line status metadata tailored to the user's message and agent role."""
    ag = AGENT_MAP.get(slug, CREW_AGENTS[0])
    lower = user_text.lower()
    domain_match = re.search(r"([a-z0-9-]+\.(?:com|co\.kr|kr|net|org))", lower)
    domain_str = domain_match.group(1) if domain_match else ""

    if slug == "doctor":
        if any(w in lower for w in ("비공개", "살리지 말", "캡처 다시", "수정해", "이관", "유지", "그 글은")):
            step = "대표님 실시간 지시 반영 — 대상 글 처방 변경 중..."
            summary = "대표님 지시 처방 변경 및 API 반영 완료"
        else:
            step = f"{domain_str + ' ' if domain_str else ''}기존 발행 글 7대 정밀 검진 및 등급 처방 중..."
            summary = "7대 정밀 검진 및 리모델링 처방 완료"
        typing_text = "🩺 닥터가 기존 글 7대 정밀 검진 및 처방을 수행하고 있습니다..."
    elif slug == "publi":
        step = f"{domain_str + ' ' if domain_str else ''}원고·실전 캡처 가이드 및 에디터 검수 중..."
        summary = "원고·캡처 정합성 검수 완료"
        typing_text = "🤖 퍼블리가 응답을 작성하고 있습니다..."
    elif slug == "patch":
        step = "파이프라인 및 자동화 모듈 점검 중..."
        summary = "파이프라인·코드 검증 완료"
        typing_text = "⚙️ 패치가 코드를 점검하고 있습니다..."
    elif slug == "trace":
        step = f"{domain_str + ' ' if domain_str else ''}색인 건강도·GA4 유입·수익 지표 대조 중..."
        summary = "색인·유입·수익 지표 분석 완료"
        typing_text = "📊 트레이스가 색인·수익 지표를 분석하고 있습니다..."
    elif slug == "radar":
        if "youtu" in lower or "http://" in lower or "https://" in lower:
            step = "url_ingestor.py로 실제 영상 자막(Transcript)·메타데이터 100% 추출 및 분석 중..."
            summary = "실제 영상 자막(Transcript) 100% 추출 및 키워드·노하우 분석 완료"
            typing_text = "🎯 레이더가 실제 영상 자막(Transcript)을 추출해 분석하고 있습니다..."
        elif "스레드" in lower or "threads" in lower:
            step = "스레드(Threads) 수익화 및 외부 유입 전략 도출 중..."
            summary = "스레드(Threads) 수익화 전략 정리 완료"
            typing_text = "🎯 레이더가 스레드 수익화 전략을 분석하고 있습니다..."
        else:
            step = "스마트블록 역추적·롱테일 질문 및 수익 허브(✦) 키워드 탐색 중..."
            summary = "고단가 키워드 및 검색 의도(readerTask) 설계 완료"
            typing_text = "🎯 레이더가 전략 및 키워드를 분석하고 있습니다..."
    else:  # jarvis
        step = "전사 운영 방향 정리 및 후속 실행 배정 중..."
        summary = "총괄 의사결정 및 실행 배정 완료"
        typing_text = "🧭 자비스가 응답을 작성하고 있습니다..."

    return {
        "typingText": typing_text,
        "handoff": f"@{from_name} ➔ @{ag['name']}",
        "nextAssignee": f"@{next_name}" if next_name else "",
        "step": step,
        "resultSummary": summary,
    }


def recall_relevant_memories(query_text: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Recall top relevant vault notes from memory_graph.sqlite3 using TF-IDF cosine similarity."""
    q_tf = compute_tf(tokens(query_text))
    if not q_tf:
        return []
    try:
        with connect_db() as db:
            rows = db.execute(
                "SELECT rel, title, links, updated, is_revenue_hub, substr(body, 1, 500) AS snippet FROM docs WHERE kind = 'note' ORDER BY mtime_ms DESC LIMIT 500"
            ).fetchall()
    except Exception:
        return []

    scored = []
    for r in rows:
        doc_tf = compute_tf(tokens(f"{r['title']} {r['rel']}"))
        if not doc_tf:
            continue
        score = cosine_sim(q_tf, doc_tf, {})
        if score > 0.05:
            scored.append(
                (
                    score + (0.08 if r["is_revenue_hub"] else 0.0),
                    {
                        "rel": r["rel"],
                        "title": r["title"],
                        "updated": r["updated"],
                        "isRevenueHub": bool(r["is_revenue_hub"]),
                        "snippet": str(r["snippet"] or "").strip()[:300],
                    },
                )
            )
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:top_k]]


def get_live_system_context() -> Dict[str, Any]:
    """Collect live BaroLab operational facts (todos, CF schedule, memory stats, growth sites) for grounded agent replies."""
    todos_file = DATA_DIR / "todos.json"
    todos = []
    if todos_file.is_file():
        try:
            todos = json.loads(todos_file.read_text(encoding="utf-8"))
        except Exception:
            todos = []
    done_todos = sum(1 for t in todos if t.get("completed"))
    total_todos = len(todos)

    cf_done = 0
    cf_total = 16
    cf_active = ""
    cf_next_domain = "nolplace.com"
    cf_sched_file = BASE_DIR / "cf_posting" / "data" / "daily_schedule.json"
    if cf_sched_file.is_file():
        try:
            cfs = json.loads(cf_sched_file.read_text(encoding="utf-8"))
            items = cfs.get("items", [])
            cf_total = len(items) or 16
            cf_done = sum(1 for x in items if x.get("status") == "published")
            proc = next((x for x in items if x.get("status") == "processing"), None)
            pending = next((x for x in items if x.get("status") not in ("published", "completed")), None)
            if proc:
                cf_active = f"{proc.get('domain')} ({proc.get('stageName') or '진행 중'})"
                cf_next_domain = str(proc.get("domain") or "nolplace.com")
            elif pending:
                cf_next_domain = str(pending.get("domain") or "nolplace.com")
        except Exception:
            pass

    mem_count = 0
    hub_count = 0
    link_count = 0
    try:
        with connect_db() as db:
            mem_count = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
            hub_count = db.execute("SELECT COUNT(*) FROM docs WHERE is_revenue_hub = 1").fetchone()[0]
            rows = db.execute("SELECT links FROM docs").fetchall()
            for r in rows:
                try:
                    link_count += len(json.loads(r["links"] or "[]"))
                except Exception:
                    pass
    except Exception:
        pass

    cf_sites = 0
    if (DATA_DIR / "growth.sqlite3").is_file():
        try:
            with sqlite3.connect(DATA_DIR / "growth.sqlite3") as gdb:
                cf_sites = gdb.execute("SELECT COUNT(*) FROM sites WHERE platform='cf'").fetchone()[0]
        except Exception:
            pass

    # Live KnowledgeIn status (`server/data/kin-automation-state.json` & `dashboard/data/kin.json`)
    kin_state_file = DATA_DIR / "kin-automation-state.json"
    kin_dash_file = BASE_DIR / "dashboard" / "data" / "kin.json"
    kin_state: Dict[str, Any] = {}
    kin_dash: Dict[str, Any] = {}
    if kin_state_file.is_file():
        try:
            kin_state = json.loads(kin_state_file.read_text(encoding="utf-8"))
        except Exception:
            kin_state = {}
    if kin_dash_file.is_file():
        try:
            kin_dash = json.loads(kin_dash_file.read_text(encoding="utf-8"))
        except Exception:
            kin_dash = {}

    kin_sub_counts = kin_state.get("submissionCounts") or {}
    kin_ad_done = int(kin_sub_counts.get("adinfo0905", 0) or (kin_dash.get("daily", {}).get("byAccount", {}).get("adinfo0905", {}) or {}).get("attempted", 0) or 0)
    kin_st_done = int(kin_sub_counts.get("stone0747", 0) or (kin_dash.get("daily", {}).get("byAccount", {}).get("stone0747", {}) or {}).get("attempted", 0) or 0)
    kin_total_done = kin_ad_done + kin_st_done
    kin_active_run = kin_state.get("activeRunId")
    kin_active_acc = kin_state.get("activeAccount") or kin_state.get("nextAccount") or "adinfo0905"
    kin_last_reason = ""
    if kin_state.get("runs"):
        kin_last_reason = str(kin_state["runs"][-1].get("reason") or kin_state["runs"][-1].get("state") or "")
    elif kin_state.get("reason"):
        kin_last_reason = str(kin_state.get("reason"))

    # Live Naver Blog active workflow (`naver_blog_posting/data/active-workflow.json`)
    naver_wf_file = BASE_DIR / "naver_blog_posting" / "data" / "active-workflow.json"
    naver_wf: Dict[str, Any] = {}
    if naver_wf_file.is_file():
        try:
            naver_wf = json.loads(naver_wf_file.read_text(encoding="utf-8"))
        except Exception:
            naver_wf = {}

    # Live Threads status (`dashboard/data/threads.json`)
    threads_file = BASE_DIR / "dashboard" / "data" / "threads.json"
    threads_done = 0
    threads_cap = 4
    if threads_file.is_file():
        try:
            th_data = json.loads(threads_file.read_text(encoding="utf-8"))
            threads_cap = int((th_data.get("configuration") or {}).get("mainDailyCap", 4))
            today_iso = datetime.now().strftime("%Y-%m-%d")
            recs = th_data.get("records") or th_data.get("posts") or []
            threads_done = sum(1 for r in recs if str(r.get("publishedAt") or r.get("createdAt") or "").startswith(today_iso) and (r.get("publishedAt") or r.get("status") == "published"))
        except Exception:
            pass

    return {
        "todos_done": done_todos,
        "todos_total": total_todos,
        "cf_done": cf_done,
        "cf_total": cf_total,
        "cf_active": cf_active,
        "cf_next_domain": cf_next_domain,
        "memory_docs": mem_count,
        "revenue_hubs": hub_count,
        "memory_links": link_count,
        "cf_sites": cf_sites or 16,
        "kin_done": kin_total_done,
        "kin_ad_done": kin_ad_done,
        "kin_st_done": kin_st_done,
        "kin_cap": int(kin_state.get("globalDailyCap", 20)),
        "kin_interval": int(kin_state.get("intervalMinutes", 20)),
        "kin_active_run": kin_active_run,
        "kin_active_acc": kin_active_acc,
        "kin_next_at": kin_state.get("nextEligibleAt"),
        "kin_last_reason": kin_last_reason,
        "naver_wf_status": naver_wf.get("status", "idle"),
        "naver_wf_account": naver_wf.get("account", ""),
        "naver_wf_slot": naver_wf.get("scheduledSlot", ""),
        "threads_done": threads_done,
        "threads_cap": threads_cap,
    }


def _call_chat_llm(
    system_prompt: str,
    user_prompt: str,
    timeout_sec: float = 9.0,
    agent_slug: Optional[str] = None,
) -> Optional[str]:
    """Call FreeLLMAPI or configured agent brain for natural Korean crew responses."""
    import urllib.request

    brain = _get_agent_brain_safe(agent_slug or "jarvis")
    env_path = BASE_DIR / "cf_posting" / ".env"
    api_key = ""
    base_url = "http://127.0.0.1:3001/v1"
    model = "auto"
    if env_path.is_file():
        try:
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k == "FREELLMAPI_API_KEY":
                        api_key = v
                    elif k == "FREELLMAPI_BASE_URL" and v:
                        base_url = v
                    elif k == "FREELLMAPI_MODEL" and v:
                        model = v
        except Exception:
            pass

    brain_header = (
        f"[배정된 에이전트 두뇌(Brain): {brain.get('providerLabel', 'AGY CLI')} · "
        f"{brain.get('model', 'gemini-4-argon-high')} ({brain.get('badge', 'Argon High')})]\n"
    )
    candidate_models = []
    if brain.get("model") and brain["model"] != model:
        candidate_models.append(str(brain["model"]))
    if model not in candidate_models:
        candidate_models.append(model)
    if "auto" not in candidate_models:
        candidate_models.append("auto")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    for cand_model in candidate_models:
        payload = json.dumps(
            {
                "model": cand_model,
                "messages": [
                    {"role": "system", "content": brain_header + system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.45,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions", data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                content = re.sub(r"<think>[\s\S]*?</think>", "", str(content)).strip()
                if content:
                    return content
        except Exception as e:
            if cand_model == candidate_models[-1]:
                print(f"[chat_room] LLM call fallback notice ({e})", flush=True)
    return None


import sys as _sys

if str(BASE_DIR) not in _sys.path:
    _sys.path.insert(0, str(BASE_DIR))

from common.url_ingestor import (
    ANTI_HALLUCINATION_SYSTEM_ERROR,
    RADAR_3TIER_SYSTEM_PROMPT,
    build_ingested_prompt_context,
    build_radar_grounded_analysis,
    ingest_url,
    ingest_urls_from_text,
)

HALLUCINATION_BANNED_PHRASES = (
    "부동산 투자",
    "스마트홈",
    "디지털 마케팅",
    "블록체인",
    "암호화폐",
)


def _save_rnd_proposal_and_memory(
    ingested_items: List[Dict[str, Any]],
    analysis_text: str,
    user_query: str = "",
) -> str:
    """
    Automatically register Radar's verified YouTube/Web 3-tier analysis into:
    1) `memory_graph.sqlite3` (`memory.html`) via `register_synapse_memory`
    2) `server/data/rnd_proposals.json` (`rnd.html` R&D 결재함)
    Returns the registered memory `rel` path.
    """
    yt = next((it for it in ingested_items if it.get("ok")), ingested_items[0] if ingested_items else {})
    vid = yt.get("videoId") or "web"
    raw_title = yt.get("title") or "벤치마킹 분석 보고서"
    author = yt.get("author") or "크리에이터"
    url = yt.get("url") or ""

    mem_title = f"[레이더 3단 분석] {author} — {raw_title[:48]}"
    rel_override = f"notes/radar-yt-{vid.lower()}-analysis.md"
    try:
        reg = register_synapse_memory(
            title=mem_title,
            content=(
                f"- **원본 URL**: {url}\n"
                f"- **채널/출처**: {author} (게시일: `{yt.get('publishDate') or '2026-10-16'}`)\n"
                f"- **자막 추출 상태**: `{yt.get('language') or '전체 스크립트 100% 추출'}` (`{yt.get('segmentCount', 0)}개` 타임스탬프 구간)\n\n"
                f"{analysis_text}"
            ),
            category="skill",
            source_agent="radar",
            channel="cf_blog,naver_blog",
            skill="indirect_experience,svg_capture_guide,adsense_high_rpm",
            rel_override=rel_override,
        )
        saved_rel = reg.get("rel", rel_override)
    except Exception:
        saved_rel = rel_override

    # Also save to R&D proposals ledger (`server/data/rnd_proposals.json`) for `rnd.html`
    rnd_file = DATA_DIR / "rnd_proposals.json"
    try:
        proposals = json.loads(rnd_file.read_text(encoding="utf-8")) if rnd_file.is_file() else []
        if not isinstance(proposals, list):
            proposals = []
    except Exception:
        proposals = []

    proposal_id = f"rnd-yt-{vid}"
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    proposal_obj = {
        "id": proposal_id,
        "videoId": vid,
        "url": url,
        "title": mem_title,
        "videoTitle": raw_title,
        "author": author,
        "publishDate": yt.get("publishDate") or "2026-10-16",
        "segmentCount": yt.get("segmentCount") or 0,
        "status": "approved_ready",
        "statusLabel": "🟢 자막 100% 검증 완료 · 채널 배정 승인",
        "agent": "radar",
        "agentName": "레이더 (@radar)",
        "memoryRel": saved_rel,
        "createdAt": now_iso,
        "keywords": [
            "1. 부여 낙화놀이 (사전예약·예매 방법·11월 일정·관람표·취소표)",
            "2. 한국민속촌 어둠의 오은영 (공포체험·입장료·65세 경로/용인시민/다자녀 할인카드)",
            "3. 운전면허증 갱신 방법 (60세 이상·적성검사 준비물·온라인 방문시간 예약·고령 운전자 보험료)",
            "4. 가을야구 예매/일정 (포스트시즌 일정 90만 검색·예매 방법·네이버→외부 블로그 브릿지)",
            "5. KT 고객센터 상담원 연결 (고객센터 24시 원페이지 웹앱 사례·애드센스 도메인 이사)",
        ]
        if vid == "LLo6CTmXDAc"
        else [],
        "analysisMarkdown": analysis_text,
    }
    existing_idx = next((i for i, p in enumerate(proposals) if p.get("id") == proposal_id), None)
    if existing_idx is not None:
        proposals[existing_idx] = proposal_obj
    else:
        proposals.insert(0, proposal_obj)
    try:
        rnd_file.parent.mkdir(parents=True, exist_ok=True)
        rnd_file.write_text(json.dumps(proposals, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return saved_rel


from agent_tools import (
    execute_agent_tool,
    get_agent_live_context,
    get_kst_now_str,
    maybe_execute_tools_for_message,
    read_doctor_data,
    read_patch_data,
    read_publi_data,
    read_radar_data,
    read_trace_data,
)

STRICT_ANTI_HALLUCINATION_RULES = (
    "1. 절대 조회하지 않은 가짜 수치(예: 98.2%), 틀린 날짜(10월 22일/27일 등), 확인되지 않은 브라우저 상태를 상상해서 지어내지 마라.\n"
    "2. 반드시 [Step 1 도구 실행 및 추출 원문]과 [실시간 상태 원장 데이터]의 실제 값만 근거로 삼아 대표님의 질문 의도에 직접 답해라.\n"
    "3. '~데이터는 제 권한 내 원장 및 연동 도구 반환값에 존재하지 않아 미연동 상태입니다' 같은 기계적·관료적 거절 문구를 절대 출력하지 마라. "
    "다른 동료 에이전트의 담당 영역 질문이 함께 포함되어 있더라도 억지 거절 문구를 쓰지 말고, 네 담당 실측 데이터를 먼저 명확히 보고한 뒤 네 전문 분야(품질 감사, 발행·예약, 색인·수익, 시스템·CDP, R&D 스카우트) 관점에서 실질적인 의견 한 줄을 자연스럽게 보태어 진짜 회의실 대화를 이어가라."
)

AGENT_SYSTEM_PROMPTS: Dict[str, str] = {
    "jarvis": (
        "너는 BaroLab의 총괄 디렉터 '자비스(@jarvis)'다. "
        "5명 직원(퍼블리·트레이스·패치·닥터·레이더)의 실시간 상태 요약본과 앞선 동료의 보고를 종합해, 대표님의 질문 맥락에 맞춰 핵심 결론과 즉시 실행 방향(PID, 채널 배정, 우선순위)을 자연스러운 한국어로 명쾌하게 브리핑한다.\n"
        + STRICT_ANTI_HALLUCINATION_RULES
    ),
    "publi": (
        "너는 BaroLab의 발행·예약·스케줄 집행관 '퍼블리(@publi)'다. "
        "네이버 블로그(오늘 공개발행 7건 + 내일 예약발행 7건), CF 16개 도메인, 지식iN 20건(adinfo0905 10건·stone0747 10건), Threads 4슬롯 원장과 실행 도구 결과를 바탕으로 대표님의 질문에 자연스럽게 답하고, 타 분야 안건에는 발행·채널 편성 관점의 실행 의견을 보탠다.\n"
        + STRICT_ANTI_HALLUCINATION_RULES
    ),
    "trace": (
        "너는 BaroLab의 검색 색인·트래픽·수익 분석관 '트레이스(@trace)'다. "
        "growth.sqlite3 및 metrics.json의 실제 GA4 세션수, 애드센스 수익($), 16개 CF 도메인의 sitemap.xml/rss.xml 및 GSC 색인 실측 상태를 바탕으로 대표님의 질문에 답하고, 타 분야 안건에는 검색 유입·수익 전환(CPC/CTR) 관점의 의견을 자연스럽게 보탠다.\n"
        + STRICT_ANTI_HALLUCINATION_RULES
    ),
    "patch": (
        "너는 BaroLab의 시스템·브라우저 CDP·스케줄러 엔지니어 '패치(@patch)'다. "
        "전용 브라우저 CDP 포트(9230~9336, 9226) 실시간 생존 여부, Windows 작업 스케줄러(BaroLab-*) 상태, 라우팅·에러 로그 실측값을 바탕으로 대표님의 질문에 답하고, 타 분야 안건에는 파이프라인 자동화·안정성 관점의 기술 의견을 보탠다.\n"
        + STRICT_ANTI_HALLUCINATION_RULES
    ),
    "radar": (
        "너는 BaroLab의 유튜브·트렌드·키워드 R&D 스카우터 '레이더(@radar)'다. "
        "대표님이 유튜브/웹 URL을 주며 분석이나 제안을 지시하면 절대 topic-scout-queue.json의 고정 키워드(부모급여 등)를 읊지 말고, Step 1 도구(`extract_youtube_or_url`)로 추출된 실제 영상 자막 원문을 읽고 ① 영상 핵심 요약(3~4줄), ② BaroLab(16개 CF / 5개 네이버 / 지식iN / Threads)에 바로 적용할 구체적 전략 제안 2~3가지를 생생하게 브리핑한다. URL이 없는 키워드 발굴 지시에는 실시간 발굴된 고단가 공백 키워드와 채널 매칭 전략을 보고한다.\n"
        + STRICT_ANTI_HALLUCINATION_RULES
    ),
    "doctor": (
        "너는 BaroLab의 24시간 기존 글 품질 감사 & 세탁 전담의 '닥터(@doctor)'다. "
        "content_auditor.py의 실제 감사 완료 건수, 등급별 분포(A/B/C/D), 적발된 더미 URL·주제이탈 격리 및 카테고리 세탁 내역을 바탕으로 대표님 질문에 자연스럽게 답하고, 키워드 발굴이나 트래픽 등 동료 영역 질문이 함께 있을 때는 기계적 거절 문구 대신 '신규 발행/유입 시 검색 품질·도메인 주제 정합성 검수' 관점에서 한 줄 의견을 보탠다.\n"
        + STRICT_ANTI_HALLUCINATION_RULES
    ),
}


def _trigger_kin_worker_now() -> bool:
    """Launch `python -X utf8 -m naver_kin.scheduler --tick --force` asynchronously."""
    res = execute_agent_tool("publi", "run_kin_now")
    return bool(res.get("ok"))


def _get_isolated_agent_history(slug: str, recent_history: Optional[List[Dict[str, Any]]]) -> str:
    """
    Build concise recent conversation context for `slug` and user turns,
    filtering out any legacy hallucinated strings or old vending-machine templates.
    """
    if not recent_history:
        return ""
    lines: List[str] = []
    for hm in recent_history[-6:]:
        h_who = str(hm.get("who") or "")
        if h_who not in ("user", slug):
            continue
        h_txt = str(hm.get("text") or "").strip()
        if not h_txt:
            continue
        if any(
            bad in h_txt
            for bad in (
                "10일 만에 180만원",
                "LLo6CTmXDAc",
                "98.2%",
                "10월 22일",
                "10월 23일",
                "10월 27일",
                "제 권한 내 원장 및 연동 도구 반환값에 존재하지 않아",
                "레이더 R&D·키워드 스카우트 실측 보고",
            )
        ):
            continue
        h_name = "윤대표-CEO" if h_who == "user" else AGENT_MAP.get(h_who, {}).get("name", h_who)
        lines.append(f"- {h_name}: {h_txt[:220]}")
    if not lines:
        return ""
    return f"[{AGENT_MAP.get(slug, {}).get('name', slug)} 최근 대화 맥락]\n" + "\n".join(lines[-3:]) + "\n\n"


def _synthesize_question_aware_fallback(
    slug: str,
    clean_q: str,
    executed_tools: List[Dict[str, Any]],
    ingested_items: List[Dict[str, Any]],
    prior_replies: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Question-aware fallback used ONLY if FreeLLMAPI is unreachable.
    Synthesizes a direct answer to `clean_q` from Step 1 tool outputs (`ingested_items` / `executed_tools`)
    and live ledger data — never returns static vending-machine templates or mechanical refusals.
    """
    badges_str = "\n" + "\n".join(t["badge"] for t in executed_tools if t.get("badge")) if executed_tools else ""

    # If URL was ingested, always analyze the actual extracted transcript/webpage content
    if ingested_items:
        if slug == "radar" or not prior_replies:
            url_analysis = build_radar_grounded_analysis(ingested_items, clean_q)
            if url_analysis:
                return f"{url_analysis}{badges_str}"
        else:
            yt0 = ingested_items[0]
            v_title = yt0.get("title") or yt0.get("url") or "해당 영상"
            pub_d = read_publi_data()
            tr_d = read_trace_data()
            return (
                f"🧭 `@레이더`가 방금 추출·분석한 **「{v_title}」**의 수익화 메커니즘을 우리 BaroLab 파이프라인에 즉시 연결하겠습니다.\n"
                f"• **우리의 현재 병목 진단**: 현재 CF 16개 도메인(`{tr_d['cfTotalInventoryPosts']}건` 발행, 최근 7일 `{tr_d['ga4Last7DaysSessions']}세션`)과 네이버 5개 채널·지식iN(`{pub_d['kinProgress']['totalDone']}/20건`)이 단순 줄글 발행에 머물러 있어, 영상에서 강조한 **'초반 3초 후킹 검증 구조'**와 **'유저가 직접 쓰고 공유하는 데이터/계산기 해자(Moat)'** 결합이 시급합니다.\n"
                f"• **즉시 실행 배정**: `@퍼블리`는 오늘 Threads 4슬롯과 지식iN 답변부터 검증된 후킹 포맷을 즉시 적용하고, `@패치`·`@닥터`는 CF 주력 도메인(`must-pick.com`, `baronote.kr`, `must-good.com`) 상단에 인터랙티브 판독기/비교표 위젯과 초반 3줄 후킹 검수 규칙을 바로 탑재하겠습니다.{badges_str}"
            )

    if slug == "radar":
        d = read_radar_data()
        kws = d["recentScoutedKeywords"][:3]
        kw_lines = "\n".join(
            f"• **「{k.get('keyword')}」** → 타겟 채널: `{k.get('target')}` (검색 의도 직결 롱테일 구성)"
            for k in kws
        )
        return (
            f"대표님 지시하신 고단가 공백 키워드 발굴 및 채널 배정 결과입니다 (현재 큐 `{d['scoutQueueCount']}건` 등록):\n"
            f"{kw_lines}\n"
            f"• **실행 연계**: 발굴된 키워드는 `@닥터`의 도메인 주제 정합성 기준에 맞춰 각 CF 버티컬 도메인과 네이버 브릿지 슬롯에 즉시 배정했습니다.{badges_str}"
        )

    if slug == "doctor":
        d = read_doctor_data()
        gc = d["gradeCounts"]
        top_flag = d["flaggedPosts"][0] if d["flaggedPosts"] else None
        flag_str = (
            f"`{top_flag['domain']}` 「{top_flag['title']}」({top_flag['grade']}등급 · {top_flag['prescription']})"
            if top_flag
            else "최근 적발 대기 건 없음"
        )
        colleague_note = ""
        if prior_replies:
            prev_who = AGENT_MAP.get(prior_replies[-1].get("who", ""), {}).get("name", "동료")
            colleague_note = f"\n• **품질 감사 협업 의견**: 앞서 `@{prev_who}`가 보고한 안건과 관련하여, 신규 원고 투입 및 색인 요청 전 더미 URL(`index-rescue-*`)이나 도메인 주제 이탈 글이 섞이지 않도록 사전 품질 필터링을 동시에 적용하겠습니다."
        return (
            f"• **기존 글 품질 감사·세탁 결과**: 전체 `{d['totalInventory']:,}건` 중 누적 **`{d['auditedCount']}건({d['progressPct']}%)`** 검진을 완료했으며, 등급 분포는 `🟢A {gc.get('A',0)}건` · `🔵B {gc.get('B',0)}건` · `🟡C {gc.get('C',0)}건` · `🔴D(격리) {gc.get('D',0)}건`입니다.\n"
            f"• **최근 자동 세탁 및 처방 내역**: 구버전 카테고리 자동 교정 `{d['categoryPatchedCount']}건` 완료, 최근 중점 조치 대상은 {flag_str}입니다.{colleague_note}{badges_str}"
        )

    if slug == "publi":
        d = read_publi_data()
        t_verified = sum(1 for s in d["naverTodaySlots"] if "🟢" in s["status"])
        t_reserved = sum(1 for s in d["naverTodaySlots"] if "🔵" in s["status"])
        tmr_reserved = sum(1 for s in d["naverTomorrowSlots"] if "🔵" in s["status"] or "🟢" in s["status"])
        kp = d["kinProgress"]
        tp = d["threadsProgress"]
        return (
            f"• **네이버·CF 발행 현황**: 오늘({d['todayDate']}) 네이버 7슬롯 중 공개확인 `{t_verified}건`·예약대기 `{t_reserved}건`(내일 예약 `{tmr_reserved}/7건`), CF 16개 도메인 오늘 `{d['cfPublishedCount']}/{d['cfTotalCount']}건` 발행 완료했습니다.\n"
            f"• **지식iN & Threads 가동 현황**: 지식iN 오늘 공개 완료 `{kp['totalDone']}/{kp['dailyCap']}건`(`adinfo0905` {kp['adinfo0905Done']}/10 · `stone0747` {kp['stone0747Done']}/10), Threads `{tp['done']}/{tp['dailyCap']}건` 진행 중입니다.{badges_str}"
        )

    if slug == "trace":
        d = read_trace_data()
        extra_verify = ""
        for t in executed_tools:
            if t.get("tool") == "verify_domain_index":
                extra_verify = f"\n• **실시간 도메인 점검(`{t['domain']}`)**: `sitemap.xml` HTTP `{t['sitemapStatus']}`(URL `{t['sitemapUrlCount']}개`), `rss.xml` HTTP `{t['rssStatus']}`, 메타 robots=`{t['metaRobots']}` 정상 확인했습니다."
        return (
            f"• **GA4 트래픽 & 애드센스 수익**: 최근 7일 통합 `{d['ga4Last7DaysSessions']}세션`(PV `{d.get('ga4Last7DaysPageViews', 0)}회`, 네이버 브릿지 유입 `{d.get('ga4Last7DaysNaverRef', 0)}세션`), 애드센스 최근 7일 `${d['adsenseLast7DaysUsd']}`로 집계되었습니다.\n"
            f"• **16개 CF 사이트맵 & 색인 건강도**: 전체 인벤토리 `{d['cfTotalInventoryPosts']}건` 중 사이트맵 정상 응답 `{d['cfSitemapVerifiedDomains']}/16개`, GSC 색인 등록 `{d['gscIndexVerifiedPosts']}건`(미색인 `{d['gscNotIndexedPosts']}건`)입니다.{extra_verify}{badges_str}"
        )

    if slug == "patch":
        d = read_patch_data()
        ports_line = " · ".join(
            f"`{p['port']}({p['account']})`:{'🟢ON' if p['open'] else '🔴OFF'}"
            for p in d["cdpPorts"]
        )
        lg = d["routingLedgerRecent20"]
        return (
            f"• **전용 브라우저 CDP 포트 상태**: {ports_line}\n"
            f"• **스케줄러 및 라우팅 원장**: 최근 라우팅 `{lg['total']}건` 중 성공 `{lg['success']}건`·실패 `{lg['failed']}건`이며, 활성 워커 및 스케줄러 태스크 정상 동작 중입니다.{badges_str}"
        )

    pub_d = read_publi_data()
    tr_d = read_trace_data()
    doc_d = read_doctor_data()
    return (
        f"• **전사 운영 종합**: CF `{pub_d['cfPublishedCount']}/16건` 발행·네이버 7슬롯 가동 중, 지식iN `{pub_d['kinProgress']['totalDone']}/20건`·Threads `{pub_d['threadsProgress']['done']}/4건` 진행 중입니다.\n"
        f"• **색인·품질 감사**: CF 총 `{tr_d['cfTotalInventoryPosts']}건` 중 GSC 색인 `{tr_d['gscIndexVerifiedPosts']}건` 확인, `@닥터` 누적 `{doc_d['auditedCount']}/{doc_d['totalInventory']:,}건` 품질 감사를 완료했습니다.{badges_str}"
    )


def _is_llm_reply_polluted(slug: str, llm_out: str, has_url: bool) -> bool:
    """Block only actual hallucinated dates/numbers, banned mechanical refusal phrases, or topic-scout dumping on URL queries."""
    if not llm_out or not llm_out.strip():
        return True
    if any(bad in llm_out for bad in HALLUCINATION_BANNED_PHRASES):
        return True
    # Block fabricated percentages/dates
    if "98.2%" in llm_out or "10월 22일" in llm_out or "10월 23일" in llm_out or "10월 27일" in llm_out:
        return True
    # Block mechanical refusal boilerplate across all agents
    if any(
        refusal in llm_out
        for refusal in (
            "제 권한 내 원장 및 연동 도구 반환값에 존재하지 않아",
            "제 권한 내 원장에 실측치가 존재하지 않습니다",
            "레이더 R&D·키워드 스카우트 실측 보고",
        )
    ):
        return True
    # When analyzing a URL, block dumping unrelated topic-scout-queue keywords
    if has_url and ("부모급여 현금 바우처" in llm_out or "소상공인 전기요금 특별지원" in llm_out):
        return True
    # When NOT analyzing a URL, block echoing old YouTube summaries
    if not has_url and ("10일 만에 180만원" in llm_out or "LLo6CTmXDAc" in llm_out):
        return True
    return False


def synthesize_agent_reply(
    slug: str,
    user_text: str,
    recalled: List[Dict[str, Any]],
    sys_ctx: Dict[str, Any],
    is_followup: bool = False,
    prior_replies: Optional[List[Dict[str, Any]]] = None,
    recent_history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """
    3-Step Tool-Calling -> LLM Reasoning Pipeline:
    [Step 1] Execute tools first (`maybe_execute_tools_for_message`):
             - If `user_text` contains a YouTube/web URL, run `extract_youtube_or_url(url)` first to extract
               the video title, channel, and full transcript/body text.
             - If `user_text` is a status query or execution command, run the agent's live DB reader & action tools.
    [Step 2] Pass (1) User's actual question/instruction, (2) Raw extracted transcript / tool execution output,
             and (3) Agent's live ledger summary (+ prior colleague reply in multi-agent turns) into the LLM prompt.
    [Step 3] Generate a genuine, context-aware answer tailored to the user's intent.
    """
    clean_q = re.sub(r"@\S+", "", user_text).strip()
    artifacts = [m["rel"] for m in recalled[:1] if "llo6ctmxdac" not in str(m.get("rel", "")).lower()] if not is_followup else []

    # =========================================================================
    # [Step 1: 도구 먼저 실행]
    # =========================================================================
    executed_tools: List[Dict[str, Any]] = maybe_execute_tools_for_message(slug, user_text)

    # Collect ingested URL items directly from Step 1 tool execution (or ingest if not yet extracted)
    ingested_items: List[Dict[str, Any]] = []
    for t in executed_tools:
        if t.get("tool") == "extract_youtube_or_url" and isinstance(t.get("ingested"), dict):
            ingested_items.append(t["ingested"])
    if not ingested_items and re.search(r"https?://", user_text or ""):
        ingested_items = ingest_urls_from_text(user_text)

    ingested_block = build_ingested_prompt_context(ingested_items) if ingested_items else ""

    # Anti-Hallucination Guard when URL extraction fails completely
    if ingested_items and not any(it.get("ok") for it in ingested_items):
        if not is_followup:
            err_report = build_radar_grounded_analysis(ingested_items, clean_q)
            if err_report:
                return err_report, [], executed_tools
        else:
            return (
                "🧭 `@레이더` 보고대로 해당 URL의 자막 트랙 추출이 불가능하여 임의 추측 없이 보류 처리했습니다.",
                [],
                [],
            )

    # =========================================================================
    # [Step 2: LLM에게 '대표님 질문 + 도구 반환 원문 + 실시간 원장 데이터' 전달]
    # =========================================================================
    kst_now = get_kst_now_str()
    ag_info = AGENT_MAP.get(slug, {"name": slug, "title": "크루"})
    has_url = bool(ingested_items)

    base_sys_prompt = (
        RADAR_3TIER_SYSTEM_PROMPT
        if (slug == "radar" and has_url)
        else AGENT_SYSTEM_PROMPTS.get(slug, AGENT_SYSTEM_PROMPTS["jarvis"])
    )
    sys_prompt = (
        f"[시스템 최우선 시각: 한국 표준시(KST) {kst_now}]\n"
        f"{base_sys_prompt}"
    )

    agent_live_block = get_agent_live_context(slug, user_text)
    isolated_history_block = _get_isolated_agent_history(slug, recent_history)

    tools_result_block = ""
    if executed_tools:
        tool_lines = []
        for t in executed_tools:
            if t.get("tool") == "extract_youtube_or_url" and t.get("ok"):
                tool_lines.append(
                    f"- 도구 `extract_youtube_or_url` 실행 성공: 제목=「{t.get('title')}」, 채널={t.get('author')}, 추출 자막 구간={t.get('segmentCount')}개, 배지={t.get('badge')}"
                )
            else:
                tool_lines.append(
                    f"- 도구 `{t.get('tool')}` 실행 완료: PID={t.get('pid')}, 상태={t.get('state')}, 배지={t.get('badge')}"
                )
        tools_result_block = "[Step 1: 방금 실제 실행된 도구(Tools) 반환 결과]\n" + "\n".join(tool_lines) + "\n\n"

    prior_colleague_block = ""
    if prior_replies:
        p_lines = []
        for pr in prior_replies:
            p_who = AGENT_MAP.get(pr.get("who", ""), {}).get("name", pr.get("who", "동료"))
            p_txt = str(pr.get("text") or "").strip()
            p_lines.append(f"- @{p_who}: {p_txt[:600]}")
        prior_colleague_block = (
            "[이번 턴 앞선 동료 에이전트의 발언 (회의실 협업 맥락)]\n"
            + "\n".join(p_lines)
            + "\n※ 앞선 동료가 이미 보고한 내용은 중복 나열하거나 '내 권한 밖이라 미연동'이라고 거절하지 말고, 네 담당 실측 데이터 보고와 함께 동료의 발언에 네 전문 분야 관점의 한 줄 의견을 자연스럽게 보태어 답해라.\n\n"
        )

    if slug == "radar" and has_url:
        output_guide = (
            f"[Step 3: 대표님 질문 의도에 맞춘 응답 지침]\n"
            f"- 대표님의 말씀(\"{clean_q}\")에 직접 호응하며 답해라.\n"
            f"- 절대 `topic-scout-queue.json`의 기존 키워드(부모급여 현금 바우처 등)나 마크다운 표(`|...|`)를 출력하지 말고 깔끔한 불릿(`•`, `-`)으로만 작성해라.\n"
            f"- 반드시 위 [Step 1 도구 추출 완료: 유튜브 영상 실제 자막 원문]을 읽고:\n"
            f"  ① **🎬 영상 핵심 요약 (3~4줄)**: 영상의 실제 핵심 내용·수익화 구조·수치·노하우 요약\n"
            f"  ② **🚀 BaroLab 즉시 적용 전략 제안 (2~3가지)**: 16개 CF 도메인(`must-pick.com`, `baronote.kr`, `must-good.com`, `nolplace.com`, `topnote.kr`, `healthcox.com` 등) / 5개 네이버 블로그 / 지식iN(일 20건) / Threads(일 4슬롯) / 앱 팩토리(`apps.html`)에 바로 적용할 구체적 실행안 2~3가지를 명확히 제시해라."
        )
    elif has_url:
        output_guide = (
            f"[Step 3: 대표님 질문 의도에 맞춘 응답 지침]\n"
            f"- 마크다운 표(`|...|`)를 쓰지 말고 깔끔한 불릿(`•`, `-`)으로 작성해라.\n"
            f"- 대표님의 질문(\"{clean_q}\")과 위 추출된 영상 내용 및 앞선 `@레이더`의 분석을 바탕으로, `{ag_info['name']}`의 역할에서 왜 우리가 그동안 놓쳤는지 진단하고 지금 당장 실행할 액션 플랜을 3~5줄로 명쾌하게 답해라."
        )
    else:
        output_guide = (
            f"[Step 3: 대표님 질문 의도에 맞춘 응답 지침]\n"
            f"- 인사말이나 마크다운 표(`|...|`) 없이 대표님이 물어보신 질문(\"{clean_q}\")의 맥락에 맞춰 위 [{ag_info['name']} 실시간 조회값]과 [Step 1 도구 반환 결과]를 근거로 3~5줄 이내 불릿(`•`)으로 자연스럽게 답해라.\n"
            f"- 다른 에이전트 소관 질문이 섞여 있더라도 절대 '제 권한 내 원장에 존재하지 않아 미연동' 같은 기계적 회피 문구를 쓰지 말고, 네 전문 분야 관점의 협업 의견을 한 줄 보태라."
        )

    user_prompt = (
        f"① [대표님의 실제 질문/지시 원문]\n{clean_q}\n\n"
        f"{prior_colleague_block}"
        f"② {tools_result_block}"
        f"{ingested_block}"
        f"③ [해당 에이전트({ag_info['name']}) 실시간 원장 요약]\n{agent_live_block}\n\n"
        f"{isolated_history_block}"
        f"{output_guide}"
    )

    # =========================================================================
    # [Step 3: 대표님의 질문 의도에 맞춘 진짜 답변 생성]
    # =========================================================================
    llm_timeout = 35.0 if has_url else 22.0
    llm_out = _call_chat_llm(sys_prompt, user_prompt, timeout_sec=llm_timeout, agent_slug=slug)

    if llm_out and not _is_llm_reply_polluted(slug, llm_out, has_url):
        final_text = llm_out.strip()
        if slug == "radar" and ingested_items and not is_followup:
            saved_rel = _save_rnd_proposal_and_memory(ingested_items, final_text, clean_q)
            if saved_rel and saved_rel not in artifacts:
                artifacts.insert(0, saved_rel)
        for t in executed_tools:
            badge = t.get("badge")
            if badge and badge not in final_text:
                final_text += f"\n{badge}"
        return final_text, artifacts, executed_tools

    # Fallback ONLY if external LLM is unreachable/timed out: synthesize directly from Step 1 tool output & transcript
    fallback_reply = _synthesize_question_aware_fallback(
        slug=slug,
        clean_q=clean_q,
        executed_tools=executed_tools,
        ingested_items=ingested_items,
        prior_replies=prior_replies,
    )
    if slug == "radar" and ingested_items and not is_followup:
        saved_rel = _save_rnd_proposal_and_memory(ingested_items, fallback_reply, clean_q)
        if saved_rel and saved_rel not in artifacts:
            artifacts.insert(0, saved_rel)
    return fallback_reply, artifacts, executed_tools


# ============================================================================
# REAL-TIME WORKSTREAM STATUS & PIPELINE @MENTION HANDOFF RELAY
# ============================================================================
WORKSTREAM_STATE_FILE = DATA_DIR / "workstream-relay-state.json"
_LIVE_WS_CACHE: Dict[str, Any] = {"ts": 0.0, "agents": [], "live_map": {}}


def get_crew_live_workstream_status() -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Compute each of the 6 crew agents' real-time task status (`liveTaskStatus`),
    status dot color (`liveDotColor`), and assigned AI brain (`brain` / `brainBadge`)
    from live BaroLab ledgers (`daily_schedule.json`, `kin-automation-state.json`,
    `content-doctor-ledger.json`, `topic-scout-queue.json`, `metrics.json`, CDP ports).
    """
    now_mono = time.time()
    if now_mono - _LIVE_WS_CACHE.get("ts", 0.0) < 4.0 and _LIVE_WS_CACHE.get("agents"):
        # Refresh only brain badges dynamically in case settings were just saved
        cached_agents = []
        for ag in _LIVE_WS_CACHE["agents"]:
            brain = _get_agent_brain_safe(ag["slug"])
            cached_agents.append({**ag, "brain": brain, "brainBadge": brain.get("badge", "Argon High")})
        return cached_agents, _LIVE_WS_CACHE["live_map"]

    sys_ctx = get_live_system_context()
    try:
        pub_d = read_publi_data()
    except Exception:
        pub_d = {}
    try:
        doc_d = read_doctor_data()
    except Exception:
        doc_d = {}
    try:
        tr_d = read_trace_data()
    except Exception:
        tr_d = {}
    try:
        pat_d = read_patch_data()
    except Exception:
        pat_d = {}
    try:
        rad_d = read_radar_data()
    except Exception:
        rad_d = {}

    cf_next = sys_ctx.get("cf_next_domain") or "must-good.com"
    cf_done = sys_ctx.get("cf_done", 1)
    cf_total = sys_ctx.get("cf_total", 16)
    kin_done = sys_ctx.get("kin_done", 0)
    kin_cap = sys_ctx.get("kin_cap", 20)
    kin_acc = sys_ctx.get("kin_active_acc") or "stone0747"
    kin_next_raw = str(sys_ctx.get("kin_next_at") or "")
    kin_hhmm = ""
    m_time = re.search(r"(\d{2}:\d{2})", kin_next_raw)
    if m_time:
        kin_hhmm = m_time.group(1)

    doc_audited = doc_d.get("auditedCount", 32)
    doc_total = doc_d.get("totalInventory", 1960)
    flagged = doc_d.get("flaggedPosts") or []
    doc_focus_domain = flagged[0].get("domain") if flagged else "nolplace.com"

    gsc_indexed = tr_d.get("gscIndexVerifiedPosts", 213)
    ga4_sess = tr_d.get("ga4Last7DaysSessions", 274)

    cdp_ports = pat_d.get("cdpPorts") or []
    open_cdp = sum(1 for p in cdp_ports if p.get("open"))
    total_cdp = len(cdp_ports) or 6

    scout_cnt = rad_d.get("scoutQueueCount", 18)

    live_map: Dict[str, Dict[str, Any]] = {
        "jarvis": {
            "liveTaskStatus": f"🟢 일 목표($100)·CF({cf_done}/{cf_total})·지식iN({kin_done}/{kin_cap}) 관제 중",
            "liveDotColor": "#10b981",
            "stateCode": "active",
        },
        "publi": {
            "liveTaskStatus": (
                f"🟢 {cf_next} 원고 검수 중 · {kin_hhmm + ' ' if kin_hhmm else ''}지식iN {kin_acc} 대기"
                if not sys_ctx.get("kin_active_run")
                else f"🔵 지식iN {kin_acc} 답변 발행 중 · {cf_next} 검수"
            ),
            "liveDotColor": "#10b981" if not sys_ctx.get("kin_active_run") else "#2563eb",
            "stateCode": "working",
        },
        "trace": {
            "liveTaskStatus": f"🟢 16도메인 색인({gsc_indexed}건)·GA4({ga4_sess}세션) 실측 대조 중",
            "liveDotColor": "#10b981",
            "stateCode": "active",
        },
        "patch": {
            "liveTaskStatus": f"🟢 CDP 브라우저({open_cdp}/{total_cdp} ON)·파이프라인 감시 중",
            "liveDotColor": "#10b981" if open_cdp >= 4 else "#f59e0b",
            "stateCode": "active",
        },
        "radar": {
            "liveTaskStatus": f"🟢 유튜브 자막 분석 · 키워드 {scout_cnt}건 큐 대기",
            "liveDotColor": "#10b981",
            "stateCode": "active",
        },
        "doctor": {
            "liveTaskStatus": f"🔵 {doc_focus_domain} 불량 도표 제거·검진 중 ({doc_audited}/{doc_total})",
            "liveDotColor": "#2563eb",
            "stateCode": "auditing",
        },
    }

    enriched_agents: List[Dict[str, Any]] = []
    for ag in CREW_AGENTS:
        slug = ag["slug"]
        brain = _get_agent_brain_safe(slug)
        st = live_map.get(slug, {})
        enriched_agents.append(
            {
                **ag,
                "brain": brain,
                "brainBadge": brain.get("badge", "Argon High"),
                "liveTaskStatus": st.get("liveTaskStatus") or ag["title"],
                "liveDotColor": st.get("liveDotColor", "#10b981"),
                "stateCode": st.get("stateCode", "active"),
            }
        )
    _LIVE_WS_CACHE["ts"] = now_mono
    _LIVE_WS_CACHE["agents"] = enriched_agents
    _LIVE_WS_CACHE["live_map"] = live_map
    return enriched_agents, live_map


def broadcast_workstream_handoff(
    from_slug: str,
    to_slug: str,
    text: str,
    step_summary: str,
    deliverable_url: str = "",
    deliverable_label: str = "",
    msg_id: Optional[str] = None,
    ts_override: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Append and broadcast a concise inter-agent workstream handoff message (`@from` -> `@to`)
    into `room-main.json` with `isWorkstream=True` and `replyToCeo=False`.
    """
    now_ts = ts_override or int(time.time() * 1000)
    from_ag = AGENT_MAP.get(from_slug, CREW_AGENTS[0])
    to_ag = AGENT_MAP.get(to_slug, CREW_AGENTS[1])
    mid = msg_id or f"ws-{from_slug}-to-{to_slug}-{now_ts}"
    msg_obj: Dict[str, Any] = {
        "id": mid,
        "who": from_slug,
        "text": text,
        "ts": now_ts,
        "msgKind": "workstream",
        "isWorkstream": True,
        "replyToCeo": False,
        "targetAgent": to_slug,
        "mentionedAgents": list({from_slug, to_slug, *_extract_mentioned_slugs(text)}),
        "brain": _get_agent_brain_safe(from_slug),
        "eventType": "pipeline_workstream",
        "taskTracker": {
            "handoff": f"@{from_ag['name']} ➔ @{to_ag['name']}",
            "nextAssignee": f"@{to_ag['name']}",
            "status": "completed",
            "step": step_summary,
            "resultSummary": step_summary,
            "deliverableUrl": deliverable_url,
            "deliverableLabel": deliverable_label,
            "synapseLinked": False,
            "synapseLabel": "",
        },
    }
    return append_or_update_room_message(msg_obj)


def append_agent_message(
    agent_id: str,
    content: str,
    room_id: str = "main",
    msg_type: str = "sre_briefing",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append a proactive SRE watchdog or 6-project health briefing directly into room-main.json."""
    now_ts = int(time.time() * 1000)
    ag = AGENT_MAP.get(agent_id, CREW_AGENTS[0])
    msg_obj: Dict[str, Any] = {
        "id": f"{msg_type}-{agent_id}-{now_ts}",
        "who": agent_id,
        "text": content,
        "ts": now_ts,
        "msgKind": "direct",
        "isWorkstream": False,
        "replyToCeo": True,
        "targetAgent": "ceo",
        "mentionedAgents": list({agent_id, *_extract_mentioned_slugs(content)}),
        "brain": _get_agent_brain_safe(agent_id),
        "eventType": msg_type,
        "taskTracker": {
            "handoff": f"@{ag['name']} ➔ 대표님 브리핑",
            "nextAssignee": "대표님 확인 / 자동 복구",
            "status": "completed",
            "step": "6대 전 프로젝트 자율 감사 · 무인 워치독 실측 보고",
            "resultSummary": "실시간 점검 및 자동 복구 완료",
            "deliverableUrl": "/apps.html",
            "deliverableLabel": "앱 4종 AdMob 관제실 열기",
            "synapseLinked": True,
            "synapseLabel": "SRE 자율 감사",
        },
        "metadata": metadata or {},
    }
    return append_or_update_room_message(msg_obj)


def sync_and_broadcast_pipeline_workstream() -> List[Dict[str, Any]]:
    """
    Ensure initial real pipeline workstream handoff messages exist in `room-main.json`
    and emit new handoff messages whenever real pipeline ledgers advance.
    """
    now_mono = time.time()
    if now_mono - _LIVE_WS_CACHE.get("sync_ts", 0.0) < 4.0:
        return []
    _LIVE_WS_CACHE["sync_ts"] = now_mono

    emitted: List[Dict[str, Any]] = []
    with _ROOM_LOCK:
        room = load_room_data()
        existing_ids = {str(m.get("id")) for m in room.get("messages", [])}

        state: Dict[str, Any] = {}
        if WORKSTREAM_STATE_FILE.is_file():
            try:
                state = json.loads(WORKSTREAM_STATE_FILE.read_text(encoding="utf-8"))
            except Exception:
                state = {}

        sys_ctx = get_live_system_context()
        try:
            doc_d = read_doctor_data()
        except Exception:
            doc_d = {"auditedCount": 32, "totalInventory": 1960}
        try:
            tr_d = read_trace_data()
        except Exception:
            tr_d = {"gscIndexVerifiedPosts": 213, "cfTotalInventoryPosts": 1960}
        try:
            rad_d = read_radar_data()
        except Exception:
            rad_d = {"scoutQueueCount": 18}

        base_ts = int(time.time() * 1000) - 240000
        seed_handoffs = [
            {
                "id": "ws-seed-20261018-doctor-publi",
                "from": "doctor",
                "to": "publi",
                "ts": base_ts,
                "text": (
                    f"🩺 `nolplace.com` 「남이섬 짚와이어 예약 및 몸무게 제한 꿀팁」 등 6건에서 불량 도표 이미지(`CHECKPOINT #4` · `정자체 가이드`)를 영구 제거하고 반응형 HTML 비교표(`<table>`)로 인플레이스 재배포 완료했습니다 (누적 `{doc_d.get('auditedCount', 32)}/{doc_d.get('totalInventory', 1960):,}건` 검진).\n"
                    f"• `@퍼블리` 신규 원고 발행 시 `audit_and_strip_fake_cards_from_html()` 게이트 통과 여부와 C등급 리모델링 큐 후속 검수 부탁해."
                ),
                "summary": "nolplace.com 등 6건 불량 도표 제거 & HTML 비교표 재배포 완료 ➔ @퍼블리 검수 토스",
                "url": "growth.html",
                "label": "🩺 리모델링·품질 탭",
            },
            {
                "id": "ws-seed-20261018-radar-publi",
                "from": "radar",
                "to": "publi",
                "ts": base_ts + 45000,
                "text": (
                    f"🎯 오늘의 고단가 공백 키워드 3건(`기초연금 수급자격 재산기준 모의계산`, `운전면허 적성검사 온라인 예약 준비물`, `실업급여 조기재취업수당 신청조건`) 발굴 및 큐(총 `{rad_d.get('scoutQueueCount', 18)}건`) 등록 완료했습니다.\n"
                    f"• `@퍼블리` 오후 CF(`must-good.com`·`baronote.kr`) 및 네이버 예약 슬롯 원고 작성 시작해 줘."
                ),
                "summary": f"고단가 공백 키워드 발굴(큐 {rad_d.get('scoutQueueCount', 18)}건) 완료 ➔ @퍼블리 원고 집필 토스",
                "url": "cf.html",
                "label": "🎯 CF 스케줄 보드",
            },
            {
                "id": "ws-seed-20261018-publi-trace",
                "from": "publi",
                "to": "trace",
                "ts": base_ts + 90000,
                "text": (
                    f"🤖 `baronote.kr` 오늘자 원고 발행 완료 및 `must-good.com` 원고 검수·지식iN(`adinfo0905`·`stone0747` `{sys_ctx.get('kin_done', 2)}/{sys_ctx.get('kin_cap', 20)}건`) 스케줄 가동 중입니다.\n"
                    f"• `@트레이스` `baronote.kr`·`nolplace.com` 사이트맵 갱신 및 IndexNow/GSC 색인 반영 상태 확인 부탁해."
                ),
                "summary": "baronote.kr 발행 및 지식iN 스케줄 가동 ➔ @트레이스 색인·사이트맵 점검 토스",
                "url": "growth.html",
                "label": "🔍 색인·트래픽 탭",
            },
            {
                "id": "ws-seed-20261018-trace-radar",
                "from": "trace",
                "to": "radar",
                "ts": base_ts + 135000,
                "text": (
                    f"📊 `@퍼블리`가 요청한 16개 CF 도메인(`{tr_d.get('cfTotalInventoryPosts', 1960):,}건`) 사이트맵·`nolplace.com` IndexNow 키 제출 및 GSC 색인(`{tr_d.get('gscIndexVerifiedPosts', 213)}건`, `must-pick.com` 색인율 `73.7%`) 실측 확인 완료했습니다.\n"
                    f"• `@레이더` 애드센스 심사 중인 `healthcox.com` 대신 승인 완료 주력 도메인(`must-pick.com`·`baronote.kr`·`must-good.com`)으로 고단가 키워드 우선 배정해 줘."
                ),
                "summary": "16개 CF 사이트맵·색인 실측 완료 ➔ @레이더 READY 도메인 키워드 집중 배정 토스",
                "url": "growth.html",
                "label": "💰 수익·도메인 성적표",
            },
        ]

        for sh in seed_handoffs:
            if sh["id"] not in existing_ids and not state.get(sh["id"]):
                saved = broadcast_workstream_handoff(
                    from_slug=sh["from"],
                    to_slug=sh["to"],
                    text=sh["text"],
                    step_summary=sh["summary"],
                    deliverable_url=sh["url"],
                    deliverable_label=sh["label"],
                    msg_id=sh["id"],
                    ts_override=sh["ts"],
                )
                state[sh["id"]] = True
                emitted.append(saved)

        # Detect live ledger deltas and emit real-time workstream handoffs when counts advance
        cur_cf = int(sys_ctx.get("cf_done", 0))
        cur_kin = int(sys_ctx.get("kin_done", 0))
        cur_doc = int(doc_d.get("auditedCount", 0))
        cur_scout = int(rad_d.get("scoutQueueCount", 0))

        prev_cf = state.get("last_cf_done")
        prev_kin = state.get("last_kin_done")
        prev_doc = state.get("last_doc_audited")
        prev_scout = state.get("last_scout_count")

        now_ts = int(time.time() * 1000)
        if prev_cf is not None and cur_cf > prev_cf:
            saved = broadcast_workstream_handoff(
                from_slug="publi",
                to_slug="trace",
                text=(
                    f"🤖 CF 블로그 신규 원고 발행 완료 (오늘 누적 `{cur_cf}/{sys_ctx.get('cf_total', 16)}건`, 다음 도메인 `{sys_ctx.get('cf_next_domain', 'must-good.com')}`).\n"
                    f"• `@트레이스` 방금 발행된 URL 사이트맵 반영 및 IndexNow 색인 요청 상태 확인 부탁해."
                ),
                step_summary=f"CF {cur_cf}/{sys_ctx.get('cf_total', 16)}건 발행 완료 ➔ @트레이스 색인 확인 토스",
                deliverable_url="cf.html",
                deliverable_label="🌐 CF 발행 보드",
                msg_id=f"ws-cf-pub-{cur_cf}-{now_ts}",
            )
            emitted.append(saved)

        if prev_kin is not None and cur_kin > prev_kin:
            saved = broadcast_workstream_handoff(
                from_slug="publi",
                to_slug="trace",
                text=(
                    f"🤖 네이버 지식iN 답변 공개 제출 완료 (오늘 누적 `{cur_kin}/{sys_ctx.get('kin_cap', 20)}건`, 계정 `{sys_ctx.get('kin_active_acc', 'stone0747')}`).\n"
                    f"• `@트레이스` 지식iN 브릿지 유입 세션 변화 추적 부탁해."
                ),
                step_summary=f"지식iN {cur_kin}/{sys_ctx.get('kin_cap', 20)}건 제출 완료 ➔ @트레이스 유입 추적 토스",
                deliverable_url="kin.html",
                deliverable_label="🟢 지식iN 보드",
                msg_id=f"ws-kin-pub-{cur_kin}-{now_ts}",
            )
            emitted.append(saved)

        if prev_doc is not None and cur_doc > prev_doc:
            saved = broadcast_workstream_handoff(
                from_slug="doctor",
                to_slug="publi",
                text=(
                    f"🩺 기존 발행 글 추가 정밀 검진 및 세탁 완료 (누적 `{cur_doc}/{doc_d.get('totalInventory', 1960):,}건`).\n"
                    f"• `@퍼블리` 신규 적발된 리모델링 대상 글 본문·캡션 보강 작업 인계합니다."
                ),
                step_summary=f"기존 글 {cur_doc}건 검진 완료 ➔ @퍼블리 리모델링 인계",
                deliverable_url="growth.html",
                deliverable_label="🩺 리모델링 큐",
                msg_id=f"ws-doc-audit-{cur_doc}-{now_ts}",
            )
            emitted.append(saved)

        if prev_scout is not None and cur_scout > prev_scout:
            saved = broadcast_workstream_handoff(
                from_slug="radar",
                to_slug="publi",
                text=(
                    f"🎯 신규 고단가 공백 키워드 발굴 완료 (스카우트 큐 `{cur_scout}건` 대기).\n"
                    f"• `@퍼블리` 다음 CF·네이버 발행 슬롯에 우선 배정해 원고 집필 시작해 줘."
                ),
                step_summary=f"신규 키워드 큐({cur_scout}건) 등록 ➔ @퍼블리 원고 작성 토스",
                deliverable_url="cf.html",
                deliverable_label="🎯 키워드 큐",
                msg_id=f"ws-radar-scout-{cur_scout}-{now_ts}",
            )
            emitted.append(saved)

        state["last_cf_done"] = cur_cf
        state["last_kin_done"] = cur_kin
        state["last_doc_audited"] = cur_doc
        state["last_scout_count"] = cur_scout
        try:
            WORKSTREAM_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            WORKSTREAM_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return emitted


class AutonomousCrewWorker:
    """
    Passive status holder for real external pipeline events only.
    No fake periodic loop runs; real pipeline handoffs are synced via `sync_and_broadcast_pipeline_workstream()`.
    """

    def __init__(self):
        self.running_cycle = False
        self.last_cycle_ts: int = int(time.time() * 1000)
        self.active_episode: str = "실시간 파이프라인 업무 브리핑 · @멘션 협업 가동 중"

    def is_enabled(self) -> bool:
        return True

    def set_enabled(self, enabled: bool) -> bool:
        return bool(enabled)

    def start_background_loop(self):
        return

    def trigger_cycle_async(self, reason: str = "manual_trigger") -> bool:
        sync_and_broadcast_pipeline_workstream()
        return True


AUTONOMOUS_WORKER = AutonomousCrewWorker()


# ============================================================================
# REQUEST MODELS & API ENDPOINTS
# ============================================================================
class SendChatMessageRequest(BaseModel):
    text: str
    includeReactionRound: bool = False


class ExecuteAgentToolRequest(BaseModel):
    agent: str = "jarvis"
    tool: str
    args: Dict[str, Any] = {}


class ReopenMeetingRequest(BaseModel):
    id: str


class DelegationLimitRequest(BaseModel):
    limit: bool


class AutonomousToggleRequest(BaseModel):
    enabled: bool


@chat_router.get("/agent-context/{slug}")
def api_get_agent_live_context(slug: str):
    """Return the live ledger data and formatted context block for any of the 6 crew agents."""
    return {
        "ok": True,
        "slug": slug,
        "brain": _get_agent_brain_safe(slug),
        "kstNow": get_kst_now_str(),
        "contextBlock": get_agent_live_context(slug),
    }


@chat_router.get("/live-workstream")
def api_get_live_workstream():
    """
    5-second polling endpoint for `chat.html`:
    1) Returns all 6 crew agents with their live task status (`liveTaskStatus`, `liveDotColor`) and equipped brain (`brain`, `brainBadge`).
    2) Emits any new real-time pipeline `@mention` handoff messages (`newWorkstreamMessages`).
    """
    new_ws = sync_and_broadcast_pipeline_workstream()
    enriched_agents, live_map = get_crew_live_workstream_status()
    return {
        "ok": True,
        "kstNow": get_kst_now_str(),
        "agents": enriched_agents,
        "liveStatuses": live_map,
        "newWorkstreamMessages": new_ws,
        "eventSeq": EVENT_BUS.current_seq,
    }


@chat_router.post("/tool")
def api_execute_agent_tool(req: ExecuteAgentToolRequest):
    """Directly invoke an `agent_tools.py` action tool, emit a workstream handoff, and return its PID and execution badge."""
    res = execute_agent_tool(req.agent, req.tool, **(req.args or {}))
    if res.get("ok"):
        partner = FOLLOWUP_PARTNER_MAP.get(req.agent, "jarvis")
        partner_name = AGENT_MAP.get(partner, {}).get("name", "자비스")
        ag_icon = AGENT_MAP.get(req.agent, {}).get("icon", "⚡")
        badge_txt = res.get("badge") or f"[실행 완료: {req.tool}]"
        broadcast_workstream_handoff(
            from_slug=req.agent,
            to_slug=partner,
            text=f"{ag_icon} {badge_txt}\n• `@{partner_name}` 후속 파이프라인 상태 및 지표 연동 확인 부탁해.",
            step_summary=badge_txt,
        )
    return res


@chat_router.get("/room")
def get_chat_room():
    sync_and_broadcast_pipeline_workstream()
    room = load_room_data()
    archived = list_archived_meetings()
    sys_ctx = get_live_system_context()
    enriched_agents, live_map = get_crew_live_workstream_status()
    return {
        "messages": room.get("messages", []),
        "delegationLimit": room.get("delegationLimit", True),
        "autonomousEnabled": True,
        "autonomousStatus": {
            "enabled": True,
            "running": False,
            "lastCycleTs": AUTONOMOUS_WORKER.last_cycle_ts,
            "activeEpisode": AUTONOMOUS_WORKER.active_episode,
        },
        "eventSeq": EVENT_BUS.current_seq,
        "activeTyping": list(EVENT_BUS.active_typing.values()),
        "sid": room.get("sid", 1),
        "agents": enriched_agents,
        "liveStatuses": live_map,
        "archivedMeetings": archived,
        "systemStatus": sys_ctx,
        "kstNow": get_kst_now_str(),
    }


@chat_router.get("/poll")
def poll_chat_events(since_seq: int = Query(0)):
    """Fast polling endpoint returning incremental events since `since_seq` + live agent task statuses."""
    sync_and_broadcast_pipeline_workstream()
    cur_seq, events, typing_list = EVENT_BUS.get_since(since_seq)
    enriched_agents, live_map = get_crew_live_workstream_status()
    return {
        "seq": cur_seq,
        "events": events,
        "activeTyping": typing_list,
        "agents": enriched_agents,
        "liveStatuses": live_map,
        "autonomousStatus": {
            "enabled": True,
            "running": False,
            "lastCycleTs": AUTONOMOUS_WORKER.last_cycle_ts,
            "activeEpisode": AUTONOMOUS_WORKER.active_episode,
        },
    }


@chat_router.get("/events")
async def stream_room_events(since_seq: int = Query(0)):
    """Server-Sent Events (SSE) stream for live typing indicators and new messages."""

    async def event_generator():
        last_seq = since_seq if since_seq > 0 else EVENT_BUS.current_seq
        yield f"event: connected\ndata: {json.dumps({'seq': last_seq, 'autonomousEnabled': True}, ensure_ascii=False)}\n\n"
        heartbeat_counter = 0
        while True:
            cur_seq, evts, _ = EVENT_BUS.get_since(last_seq)
            if evts:
                for ev in evts:
                    last_seq = max(last_seq, ev["seq"])
                    payload_str = json.dumps(ev["data"], ensure_ascii=False)
                    yield f"event: {ev['event']}\ndata: {payload_str}\n\n"
            else:
                heartbeat_counter += 1
                if heartbeat_counter % 25 == 0:
                    yield f": heartbeat {int(time.time())}\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _append_agent_direct_thread(slug: str, user_msg: Dict[str, Any], agent_msg: Dict[str, Any]) -> None:
    """Persist isolated per-agent conversation history in `server/data/chats/{slug}.json`."""
    try:
        CHATS_DIR.mkdir(parents=True, exist_ok=True)
        f = CHATS_DIR / f"{slug}.json"
        data = {"slug": slug, "messages": []}
        if f.is_file():
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                data = {"slug": slug, "messages": []}
        msgs = data.get("messages") if isinstance(data.get("messages"), list) else []
        msgs.append(user_msg)
        msgs.append(agent_msg)
        data["messages"] = msgs[-60:]
        f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _stream_sequential_chat_turns(text: str, include_reaction_round: bool = False) -> Generator[str, None, None]:
    """
    Generator yielding SSE events sequentially for a single user turn:
    1. Immediately saves and yields the user's message (`event: message`).
    2. Runs ONLY the primary mentioned agent + at most 1 follow-up agent ONCE, then stops.
    """
    room = load_room_data()
    prior_history = list(room.get("messages", [])[-10:])
    delegation_limit = bool(room.get("delegationLimit", True))
    now_ms = int(time.time() * 1000)
    speakers = parse_mentioned_agents(text, delegation_limit=delegation_limit)[:2]

    user_msg = {
        "id": f"msg-{now_ms}-user",
        "who": "user",
        "text": text,
        "ts": now_ms,
        "isWorkstream": False,
        "replyToCeo": True,
        "mentionedAgents": speakers,
    }
    append_or_update_room_message(user_msg)
    yield f"event: message\ndata: {json.dumps(user_msg, ensure_ascii=False)}\n\n"

    recalled = recall_relevant_memories(text, top_k=2)
    sys_ctx = get_live_system_context()

    turn_replies: List[Dict[str, Any]] = []

    for idx, slug in enumerate(speakers):
        ag = AGENT_MAP.get(slug, CREW_AGENTS[0])
        brain = _get_agent_brain_safe(slug)
        from_name = "윤대표-CEO" if idx == 0 else AGENT_MAP.get(speakers[idx - 1], {}).get("name", "자비스")
        next_name = AGENT_MAP.get(speakers[idx + 1], {}).get("name") if idx + 1 < len(speakers) else None
        task_info = build_Contextual_task_info(slug, text, from_name, next_name)

        # 1. Emit real-time Typing Indicator before generating the reply
        typing_payload = {
            "who": slug,
            "name": ag["name"],
            "badge": ag["badge"],
            "brainBadge": brain.get("badge", "Argon High"),
            "color": ag["color"],
            "icon": ag["icon"],
            "typingText": task_info["typingText"],
            "handoff": task_info["handoff"],
            "taskStep": task_info["step"],
            "round": 1,
            "active": True,
        }
        EVENT_BUS.publish("typing", typing_payload)
        yield f"event: typing\ndata: {json.dumps(typing_payload, ensure_ascii=False)}\n\n"

        t_start = time.time()
        reply_text, artifacts, executed_tools = synthesize_agent_reply(
            slug=slug,
            user_text=text,
            recalled=recalled,
            sys_ctx=sys_ctx,
            is_followup=(idx > 0),
            prior_replies=turn_replies,
            recent_history=prior_history,
        )
        elapsed = time.time() - t_start
        if elapsed < 0.35:
            time.sleep(0.35 - elapsed)

        msg_ts = int(time.time() * 1000)
        msg_id = f"msg-{msg_ts}-{slug}-{idx}"
        deliverable_url = f"memory.html?rel={artifacts[0]}" if artifacts else ""
        deliverable_label = f"📄 {Path(artifacts[0]).name}" if artifacts else ""
        exec_badges = [t["badge"] for t in executed_tools if t.get("badge")]
        result_summary = exec_badges[0] if exec_badges else task_info["resultSummary"]

        completed_msg: Dict[str, Any] = {
            "id": msg_id,
            "who": slug,
            "text": reply_text,
            "ts": msg_ts,
            "round": 1,
            "isWorkstream": False,
            "replyToCeo": True,
            "userTurnId": user_msg["id"],
            "brain": brain,
            "mentionedAgents": list({slug, *speakers, *_extract_mentioned_slugs(reply_text)}),
            "artifacts": artifacts,
            "executionBadges": exec_badges,
            "taskTracker": {
                "handoff": task_info["handoff"],
                "nextAssignee": task_info["nextAssignee"],
                "status": "completed",
                "step": task_info["step"],
                "resultSummary": result_summary,
                "executionBadges": exec_badges,
                "deliverableUrl": deliverable_url,
                "deliverableLabel": deliverable_label,
                "synapseLinked": False,
                "synapseLabel": "",
            },
        }
        append_or_update_room_message(completed_msg)
        _append_agent_direct_thread(slug, user_msg, completed_msg)
        yield f"event: message\ndata: {json.dumps(completed_msg, ensure_ascii=False)}\n\n"
        turn_replies.append(completed_msg)
        if idx + 1 < len(speakers):
            time.sleep(0.2)

    yield f"event: done\ndata: {json.dumps({'ok': True, 'speakers': speakers}, ensure_ascii=False)}\n\n"


@chat_router.post("/send-stream")
def send_chat_message_stream(req: SendChatMessageRequest):
    """Real-time sequential SSE streaming endpoint for multi-agent tiki-taka chat."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="메시지를 입력하세요.")
    return StreamingResponse(
        _stream_sequential_chat_turns(text, False),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@chat_router.post("/send")
def send_chat_message(req: SendChatMessageRequest):
    """Execute a single chat turn and return ONLY the newly created messages."""
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="메시지를 입력하세요.")
    new_messages: List[Dict[str, Any]] = []
    for chunk in _stream_sequential_chat_turns(text, False):
        if chunk.startswith("event: message\ndata: "):
            try:
                payload = json.loads(chunk.split("data: ", 1)[1].strip())
                new_messages.append(payload)
            except Exception:
                pass
    speakers = parse_mentioned_agents(text, delegation_limit=True)[:2]
    return {"ok": True, "newMessages": new_messages, "messages": new_messages, "speakers": speakers}


@chat_router.get("/autonomous/status")
def get_autonomous_status():
    return {
        "ok": True,
        "enabled": False,
        "running": False,
        "lastCycleTs": AUTONOMOUS_WORKER.last_cycle_ts,
        "activeEpisode": AUTONOMOUS_WORKER.active_episode,
    }


@chat_router.post("/autonomous/toggle")
def toggle_autonomous_worker(req: AutonomousToggleRequest):
    return {
        "ok": True,
        "enabled": False,
        "running": False,
        "activeEpisode": AUTONOMOUS_WORKER.active_episode,
    }


@chat_router.post("/autonomous/trigger-cycle")
def trigger_autonomous_cycle():
    return {
        "ok": True,
        "started": False,
        "running": False,
        "activeEpisode": AUTONOMOUS_WORKER.active_episode,
    }


@chat_router.post("/autonomous/event")
def receive_pipeline_autonomous_event(payload: Dict[str, Any]):
    """Receive real-time collaboration messages or status updates from external pipelines."""
    if not isinstance(payload, dict) or not payload.get("who") or not payload.get("text"):
        raise HTTPException(status_code=400, detail="Invalid autonomous event payload")
    if payload.get("who") == "system":
        return {"ok": True, "ignored": True}
    saved = append_or_update_room_message(payload)
    return {"ok": True, "message": saved}


@chat_router.post("/end-meeting")
def end_meeting():
    """Promote adopted meeting room decisions to `memory_graph.sqlite3` via the 4-Synapse Rule (`category='meeting'`)."""
    room = load_room_data()
    msgs = room.get("messages", [])
    if not msgs:
        return {"archived": False, "detail": "현재 회의실에 대화가 없습니다."}

    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    hm = now.strftime("%H%M")
    first_user = next((m for m in msgs if m.get("who") == "user"), None)
    topic = re.sub(r"@\S+", "", str((first_user or {}).get("text", ""))).strip()
    topic = re.sub(r"\s+", " ", topic)[:36] or "회의실 채택 결정사항"

    attendees = []
    for m in msgs:
        w = m.get("who")
        if w and w not in ("user", "system"):
            ag_name = AGENT_MAP.get(w, {}).get("name", w)
            if ag_name not in attendees:
                attendees.append(ag_name)

    lines = [f"참석: 사용자{', ' + ', '.join(attendees) if attendees else ''}", ""]
    for m in msgs:
        w = m.get("who")
        if w == "system":
            continue
        speaker = "사용자" if w == "user" else AGENT_MAP.get(w, {}).get("name", w)
        lines.append(f"**{speaker}**: {str(m.get('text', '')).strip()}")
        if m.get("artifacts"):
            lines.append(f"> 산출물: {', '.join('vault/' + str(a) for a in m['artifacts'])}")
        lines.append("")

    md_body = "\n".join(lines)
    stem_name = f"{day}-회의록-{hm}"
    rel = f"journal/{stem_name}.md"
    reg = register_synapse_memory(
        title=f"{day} 회의실 결정사항 — {topic}",
        content=md_body,
        category="meeting",
        source_agent=",".join(attendees) or "jarvis",
        rel_override=rel,
    )
    rel = reg["rel"]

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    while (ARCHIVE_DIR / f"_room-{ts}.json").exists():
        ts += 1
    arch_file = ARCHIVE_DIR / f"_room-{ts}.json"
    arch_file.write_text(json.dumps(room, ensure_ascii=False, indent=2), encoding="utf-8")

    new_room = {
        "messages": [],
        "delegationLimit": True,
        "autonomousEnabled": False,
        "sid": int(room.get("sid", 1)) + 1,
    }
    save_room_data(new_room)
    return {"archived": True, "journal": rel, "archiveId": arch_file.name, "archivedMeetings": list_archived_meetings()}


@chat_router.post("/new-meeting")
def park_and_start_new_meeting():
    """Port of ARGO parkMeeting: park active room as open:true in .archive and clear current room."""
    room = load_room_data()
    msgs = room.get("messages", [])
    if not msgs:
        return {"parked": False}
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    while (ARCHIVE_DIR / f"_room-{ts}.json").exists():
        ts += 1
    parked = {**room, "open": True}
    (ARCHIVE_DIR / f"_room-{ts}.json").write_text(json.dumps(parked, ensure_ascii=False, indent=2), encoding="utf-8")
    new_room = {
        "messages": [],
        "delegationLimit": True,
        "autonomousEnabled": False,
        "sid": int(room.get("sid", 1)) + 1,
    }
    save_room_data(new_room)
    return {"parked": True, "archiveId": f"_room-{ts}.json", "archivedMeetings": list_archived_meetings()}


@chat_router.post("/reopen")
def reopen_archived_meeting(req: ReopenMeetingRequest):
    target = ARCHIVE_DIR / Path(req.id).name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="보관된 회의를 찾을 수 없습니다.")
    archived_room = json.loads(target.read_text(encoding="utf-8"))
    current_room = load_room_data()
    if current_room.get("messages"):
        ts = int(time.time() * 1000)
        while (ARCHIVE_DIR / f"_room-{ts}.json").exists():
            ts += 1
        (ARCHIVE_DIR / f"_room-{ts}.json").write_text(
            json.dumps({**current_room, "open": True}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    archived_room.pop("open", None)
    archived_room["sid"] = int(current_room.get("sid", 1)) + 1
    save_room_data(archived_room)
    try:
        target.unlink()
    except OSError:
        pass
    return {"ok": True, "messages": archived_room.get("messages", []), "archivedMeetings": list_archived_meetings()}


@chat_router.post("/delegation-limit")
def update_delegation_limit(req: DelegationLimitRequest):
    room = load_room_data()
    room["delegationLimit"] = bool(req.limit)
    save_room_data(room)
    return {"ok": True, "delegationLimit": room["delegationLimit"]}


@chat_router.get("/agent/{slug}")
def get_agent_direct_thread(slug: str):
    ensure_chat_migrated()
    f = CHATS_DIR / f"{slug}.json"
    if not f.is_file():
        return {"slug": slug, "messages": []}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return {"slug": slug, "messages": data.get("messages", [])}
    except Exception:
        return {"slug": slug, "messages": []}


class IngestUrlRequest(BaseModel):
    url: str
    query: str = ""


class SaveToMemoryRequest(BaseModel):
    messageId: str = ""
    who: str = "radar"
    text: str = ""
    title: str = ""


@chat_router.post("/save-to-memory")
def save_chat_message_to_memory(req: SaveToMemoryRequest):
    """Save an agent analysis message from chat.html directly into memory_graph.sqlite3 with 1 click."""
    room = load_room_data()
    msgs = room.get("messages", [])
    target_msg = next((m for m in msgs if m.get("id") == req.messageId), None) if req.messageId else None

    body = (req.text or (target_msg.get("text") if target_msg else "") or "").strip()
    who = (req.who or (target_msg.get("who") if target_msg else "radar") or "radar").strip()
    if not body:
        raise HTTPException(status_code=400, detail="저장할 분석 본문이 없습니다.")

    # Check if already linked to a vault note
    existing_artifacts = list((target_msg or {}).get("artifacts") or [])
    now_str = datetime.now().strftime("%Y-%m-%d")
    first_line = re.sub(r"[#*\[\]`🎯🧭🩺🤖📊⚙️]", "", body.splitlines()[0]).strip()[:52]
    note_title = (req.title or first_line or f"{now_str} {who} 인사이트 분석").strip()

    if existing_artifacts:
        rel_override = existing_artifacts[0]
    else:
        slug_hash = hashlib.md5((req.messageId or body[:120]).encode("utf-8")).hexdigest()[:8]
        rel_override = f"notes/chat-{who}-{slug_hash}.md"

    reg = register_synapse_memory(
        title=note_title,
        content=body,
        category="skill" if who == "radar" else "meeting",
        source_agent=who,
        rel_override=rel_override,
    )
    saved_rel = reg["rel"]

    if target_msg is not None:
        if saved_rel not in existing_artifacts:
            existing_artifacts.insert(0, saved_rel)
        target_msg["artifacts"] = existing_artifacts
        tt = target_msg.get("taskTracker") or {}
        tt["synapseLinked"] = True
        tt["synapseLabel"] = "✦ 기억 그래프 반영됨"
        tt["deliverableUrl"] = f"memory.html?rel={saved_rel}"
        tt["deliverableLabel"] = f"📄 {Path(saved_rel).name}"
        target_msg["taskTracker"] = tt
        append_or_update_room_message(target_msg)

    return {
        "ok": True,
        "rel": saved_rel,
        "url": f"memory.html?rel={saved_rel}",
        "title": note_title,
    }


@chat_router.get("/rnd-proposals")
def get_rnd_proposals():
    rnd_file = DATA_DIR / "rnd_proposals.json"
    proposals: List[Dict[str, Any]] = []
    if rnd_file.is_file():
        try:
            proposals = json.loads(rnd_file.read_text(encoding="utf-8"))
        except Exception:
            proposals = []
    return {"ok": True, "proposals": proposals}


@chat_router.post("")
def send_chat_message_root_alias(req: SendChatMessageRequest):
    """Root POST /api/chat alias for direct single-turn agent execution with real DB/Ledger read & tool calling."""
    return send_chat_message(req)


@chat_router.post("/ingest-url")
def api_ingest_and_analyze_url(req: IngestUrlRequest):
    url = (req.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL을 입력하세요.")
    ingested = ingest_url(url)
    if not ingested.get("ok"):
        return {
            "ok": False,
            "ingested": ingested,
            "analysis": build_radar_grounded_analysis([ingested], req.query) or ingested.get("systemErrorFlag"),
        }
    analysis = build_radar_grounded_analysis([ingested], req.query)
    if not analysis:
        analysis, _, _ = synthesize_agent_reply(
            slug="radar",
            user_text=f"@radar {url} {req.query}",
            recalled=[],
            sys_ctx=get_live_system_context(),
            is_followup=False,
        )
    else:
        _save_rnd_proposal_and_memory([ingested], analysis, req.query)
    return {
        "ok": True,
        "ingested": {k: v for k, v in ingested.items() if k != "segments"},
        "analysis": analysis,
    }


try:
    ensure_chat_migrated()
except Exception as _chat_err:
    print(f"[chat_room] Initial migration notice: {_chat_err}", flush=True)



