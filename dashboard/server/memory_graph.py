# -*- coding: utf-8 -*-
"""Non-destructive BaroLab memory graph and source document API.

Legacy vault documents remain intact. Project MEMORY/USER, procedural SKILL.md
files and SQLite episode evidence are overlaid with explicit source links and
review audit edges. Reads never reset, purge or reconnect stored documents.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from functools import wraps
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from common.hermes_memory import _store as hermes_store, atomic_write, safe_path, file_lock, revision, MemoryConflict
from common.hermes_memory import memorization_decision
import uuid

BASE_DIR = Path(__file__).resolve().parents[2]
SERVER_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(__file__).resolve().parents[2] / 'dashboard/data'
DB_PATH = DATA_DIR / "memory_graph.sqlite3"
GROWTH_DB_PATH = DATA_DIR / "growth.sqlite3"
METRICS_JSON_PATH = DATA_DIR / "metrics.json"
LOCAL_VAULT_DIR = DATA_DIR / "vault"
LEGACY_BACKUP_DIR = DATA_DIR / "legacy_argo_backup"

ARGO_WS_DIR = Path(r"C:\Users\baro7\AppData\Local\com.beyondworks.argo\workspaces\barolab-unl1")
ARGO_INDEX_DB = ARGO_WS_DIR / ".index.sqlite"
ARGO_VAULT_DIR = ARGO_WS_DIR / "vault"

CLEAN_SLATE_VERSION = "clean-slate-v2-20261017"
GUIDE_NOTE = "기억-안내.md"
LINK_SECTIONS = ("근거", "관련")
BOSS_PROFILE_REL = "notes/사장-프로필.md"
BOSS_SECTIONS = ("취향", "결정", "금지")

DEFAULT_AGENTS = [
    {"slug": "jarvis", "name": "팀장(총괄)", "shortName": "팀장", "role": "전사 총괄 디렉터 & OSMU 지휘", "team": "총괄", "hubRel": "hubs/crew-jarvis.md"},
    {"slug": "patch", "name": "패치(개발/스킬)", "shortName": "패치", "role": "플랫폼 자동화 & 미디어 도구 엔지니어", "team": "자동화/도구", "hubRel": "hubs/crew-patch.md"},
    {"slug": "publi", "name": "퍼블리(제작/발행)", "shortName": "퍼블리", "role": "멀티채널 크리에이터 & 퍼블리셔", "team": "제작/발행", "hubRel": "hubs/crew-publi.md"},
    {"slug": "trace", "name": "트레이스(퍼널/수익)", "shortName": "트레이스", "role": "멀티채널 유입 퍼널·도달률·수익 분석", "team": "퍼널/수익", "hubRel": "hubs/crew-trace.md"},
    {"slug": "radar", "name": "레이더(트렌드/소싱)", "shortName": "레이더", "role": "전 채널 트렌드·바이럴·외부유입 스카우터", "team": "트렌드/소싱", "hubRel": "hubs/crew-radar.md"},
]

# ── Clean Slate (Zero Pre-seeded Hubs; Autonomous Growth) ──
CLEAN_SEED_HUBS: List[Dict[str, Any]] = []
LEGACY_SKILL_HUBS = []
CORE_HUB_REL_SET = set()
BOUNDED_CORE_RELS = set()
FIXED_CORE_RELS = set()
CORE_HUB_STEM_MAP = {}

# Prohibited deprecated / legacy project keywords (never allowed into Clean Slate graph)
DEPRECATED_PROJECT_PATTERNS = re.compile(
    r"youtube-coupang|biz-down|new-item|kphotogi|argo-legacy|conflict-",
    re.I,
)

# 16 CF Domains + 5 Naver Accounts mapping to Operating Channel Hubs
CF_DOMAINS_LIST = [
    "must-good.com", "baronote.kr", "justinfo.co.kr", "topnote.kr",
    "meganote.kr", "smilenote.kr", "healthcox.com", "maxnote.kr",
    "must-joy.com", "tripmarvel.com", "must-pick.com", "woorinote.kr",
    "daynote.kr", "nolplace.com", "soulnote.kr", "joynote.kr",
]
NAVER_ACCOUNTS_LIST = ["soultin", "soul5373", "yoon_master", "adinfo0905", "stone0747", "mustpickinfo", "mustinfo", "yoonviews"]

memory_router = APIRouter(prefix="/api/memory", tags=["memory"])


def local_day(epoch_ms: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp((epoch_ms / 1000.0) if epoch_ms else time.time())
    return dt.strftime("%Y-%m-%d")


def stem(rel: str) -> str:
    return re.sub(r"\.md$", "", str(rel or "").replace("\\", "/"))


def note_slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9가-힣]+", "-", (title or "").strip().lower()).strip("-")[:48]
    return s or "note"


# ── TF-IDF Tokenizer & Similarity (Retained for chat_room.py compatibility & semantic linking) ──

def tokens(text: str) -> List[str]:
    out: List[str] = []
    cleaned = re.sub(r"\[\[.*?\]\]", " ", (text or "").lower())
    out.extend(re.findall(r"[a-z0-9]{2,}", cleaned))
    for run in re.findall(r"[가-힣]+", cleaned):
        for i in range(len(run) - 1):
            out.append(run[i : i + 2])
    return out


def compute_tf(toks: List[str]) -> Dict[str, int]:
    m: Dict[str, int] = {}
    for t in toks:
        m[t] = m.get(t, 0) + 1
    return m


def cosine_sim(a: Dict[str, int], b: Dict[str, int], idf: Dict[str, float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for t, w in a.items():
        wa = w * idf.get(t, 1.0)
        na += wa * wa
        if t in b:
            dot += wa * (b[t] * idf.get(t, 1.0))
    for t, w in b.items():
        wb = w * idf.get(t, 1.0)
        nb += wb * wb
    return (dot / (math.sqrt(na) * math.sqrt(nb))) if (na > 0 and nb > 0) else 0.0


def extract_doc_meta(rel: str, text: str, mtime_ms: int, size: int = 0) -> Dict[str, Any]:
    rel = rel.replace("\\", "/")
    base_no_ext = re.sub(r"\.md$", "", rel.split("/")[-1])
    title_match = re.search(r"^#\s*(.+)$", text, re.M)
    title = title_match.group(1).strip() if title_match else base_no_ext
    links = [m.group(1).strip() for m in re.finditer(r"\[\[(.+?)\]\]", text) if m.group(1).strip()]
    return {
        "rel": rel,
        "kind": "skill" if rel.startswith("skills/") else ("hub" if rel.startswith("hubs/") else ("journal" if rel.startswith("journal/") else "note")),
        "title": title,
        "links": links,
        "updated": local_day(mtime_ms),
        "updated_exact": 1,
        "mtime_ms": int(mtime_ms),
        "size": int(size or len(text.encode("utf-8"))),
    }


class _ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15.0, factory=_ClosingConnection)
    db.row_factory = sqlite3.Row
    # Preserve the existing journal mode. Switching WAL -> DELETE on every read
    # requires an exclusive lock and fails while an existing service is connected.
    # New databases use SQLite's default DELETE journal without a mode change.
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS docs (
            rel TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'core_hub',
            sub_group TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            links TEXT NOT NULL,
            updated TEXT NOT NULL,
            updated_exact INTEGER NOT NULL DEFAULT 1,
            mtime_ms INTEGER NOT NULL DEFAULT 0,
            size INTEGER NOT NULL DEFAULT 0,
            body TEXT DEFAULT '',
            revenue_usd REAL DEFAULT 0.0,
            revenue_krw REAL DEFAULT 0.0,
            sessions INTEGER DEFAULT 0,
            is_revenue_hub INTEGER DEFAULT 0,
            is_core_hub INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS meta (
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        );
        """
    )
    # Ensure new columns exist if migrating an older schema before reset
    cols = {r["name"] for r in db.execute("PRAGMA table_info(docs)").fetchall()}
    if "category" not in cols:
        db.execute("ALTER TABLE docs ADD COLUMN category TEXT NOT NULL DEFAULT 'core_hub'")
    if "sub_group" not in cols:
        db.execute("ALTER TABLE docs ADD COLUMN sub_group TEXT NOT NULL DEFAULT ''")
    if "is_core_hub" not in cols:
        db.execute("ALTER TABLE docs ADD COLUMN is_core_hub INTEGER NOT NULL DEFAULT 0")
    db.execute("CREATE TABLE IF NOT EXISTS memory_trash (trash_id TEXT PRIMARY KEY, rel TEXT NOT NULL, payload TEXT NOT NULL, deleted_at TEXT NOT NULL, restored_at TEXT)")
    return db


# ── Step 1: Isolate Legacy ARGO Data into `dashboard/data/legacy_argo_backup/` ──

def isolate_legacy_argo_data() -> Dict[str, Any]:
    """
    Safely move/copy all legacy ARGO notes, journals, `.index.sqlite`, and old `memory_graph.sqlite3`
    into `dashboard/data/legacy_argo_backup/` without deleting any user history, while completely
    removing them from the active graph loading path.
    """
    LEGACY_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    moved_items: List[str] = []

    # 1. Copy ARGO workspace `.index.sqlite` and markdown notes into `legacy_argo_backup/argo_workspace/` if not backed up yet
    argo_backup_target = LEGACY_BACKUP_DIR / "argo_workspace"
    if not (argo_backup_target / ".index.sqlite").exists():
        argo_backup_target.mkdir(parents=True, exist_ok=True)
        if ARGO_INDEX_DB.is_file():
            shutil.copy2(ARGO_INDEX_DB, argo_backup_target / ".index.sqlite")
            moved_items.append("argo:.index.sqlite")
        if ARGO_VAULT_DIR.is_dir():
            for md_file in ARGO_VAULT_DIR.rglob("*.md"):
                try:
                    rel_md = md_file.relative_to(ARGO_VAULT_DIR).as_posix()
                    dest_md = argo_backup_target / "vault" / rel_md
                    dest_md.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(md_file, dest_md)
                except Exception:
                    pass
            moved_items.append("argo:vault/*.md")

    # 2. Move any pre-Clean-Slate files in `dashboard/data/vault/` into `legacy_argo_backup/local_vault_pre_clean/`
    if LOCAL_VAULT_DIR.is_dir():
        legacy_local_target = LEGACY_BACKUP_DIR / "local_vault_pre_clean"
        for item in list(LOCAL_VAULT_DIR.rglob("*.md")):
            rel = item.relative_to(LOCAL_VAULT_DIR).as_posix()
            if rel in CORE_HUB_REL_SET:
                continue
            dest = legacy_local_target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(item), str(dest))
            moved_items.append(f"local_vault:{rel}")

    # 3. Backup old `memory_graph.sqlite3` if it hasn't been backed up
    old_db_backup = LEGACY_BACKUP_DIR / "memory_graph_legacy_1924.sqlite3"
    if DB_PATH.is_file() and not old_db_backup.exists():
        try:
            shutil.copy2(DB_PATH, old_db_backup)
            moved_items.append("db:memory_graph_legacy_1924.sqlite3")
        except Exception:
            pass

    return {"backupDir": str(LEGACY_BACKUP_DIR), "isolatedItems": moved_items}


# ── Step 2: 4-Synapse Rule Engine ('0 Orphan Nodes' Enforcement) ──

def resolve_synapse_parents(
    title: str,
    content: str,
    source_agent: Optional[str] = None,
    channel: Optional[str] = None,
    skill: Optional[str] = None,
    category: str = "note",
) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Enforce the 4-Synapse Rule so that EVERY memory node connects to >= 2 core parent hubs:
    1. [출처 연결 (Source Crew)]: `@팀장`, `@패치`, `@퍼블리`, `@트레이스`, `@레이더`
    2. [적용 채널/도메인 연결 (Channel)]: `네이버 블로그(5개 계정)`, `CF 블로그(16개 도메인)`, `네이버 지식iN`, `Threads`
    3. [스킬 연결 (Skill)]: `간접체험 4단계 집필법`, `SVG 캡처 가이드`, `부분 수선(In-Place Repair)`, `애드센스 고수익 배치`
    4. [성과(Growth) 연결]: Validated category (`revenue`, `skill`, `meeting`, `core_hub`, `published_post`).
    """
    probe = f"{title} {content} {source_agent or ''} {channel or ''} {skill or ''}".lower()

    crew_hubs: List[str] = []
    channel_hubs: List[str] = []
    skill_hubs: List[str] = []

    # 1. Source Crew resolution
    crew_Patterns = [
        ("hubs/crew-jarvis", ["jarvis", "팀장", "총괄", "회의록", "결정"]),
        ("hubs/crew-patch", ["patch", "패치", "개발", "스킬", "수선", "테마", "렌더러", "css", "capture_guide", "repair"]),
        ("hubs/crew-publi", ["publi", "퍼블리", "발행", "검수", "간접체험", "캡처", "200 ok", "verify"]),
        ("hubs/crew-trace", ["trace", "트레이스", "수익", "성과", "ga4", "애드센스", "애드포스트", "색인", "rpm", "ctr", "세션"]),
        ("hubs/crew-radar", ["radar", "레이더", "키워드", "스마트블록", "롱테일", "브릿지", "발굴", "수요"]),
        ("hubs/crew-doctor", ["doctor", "닥터", "감사", "remodel"]),
    ]
    for hub_stem, kws in crew_Patterns:
        if any(k in probe for k in kws):
            crew_hubs.append(hub_stem)

    # 2. Operating Channel / Domain resolution
    if str(channel or "").strip().lower() == "project":
        channel_hubs.append("hubs/channel-project")
    if any(d in probe for d in CF_DOMAINS_LIST) or re.search(r"\bcf\b|cf_blog|cf_posting|cloudflare|애드센스|adsense", probe):
        channel_hubs.append("hubs/channel-cf-blog")
    if any(a in probe for a in NAVER_ACCOUNTS_LIST) or any(k in probe for k in ["네이버 블로그", "스마트블록", "애드포스트", "naver_blog"]):
        channel_hubs.append("hubs/channel-naver-blog")
    if re.search(r"지식in|지식인|지식i n|\bkin\b|naver_kin|질문 답변", probe):
        channel_hubs.append("hubs/channel-naver-kin")
    if any(k in probe for k in ["threads", "스레드", "숏폼"]):
        channel_hubs.append("hubs/channel-threads")
    if re.search(r"play_console|play console|앱 팩토리|android|\baab\b|channel-apps", probe):
        channel_hubs.append("hubs/channel-apps")

    # 3. Core Skill resolution
    if any(k in probe for k in ["간접체험", "readergoal", "readertask", "4단계", "집필", "발행", "포스팅"]):
        skill_hubs.append("skills/skill-indirect-experience")
    if any(k in probe for k in ["캡처", "svg", "capture_guide", "#1646b7", "#8c4500", "390px", "가이드"]):
        skill_hubs.append("skills/skill-svg-capture-guide")
    if any(k in probe for k in ["부분 수선", "surgical", "repair", "수선", "재검수", "handoff"]):
        skill_hubs.append("skills/skill-inplace-repair")
    if any(k in probe for k in ["애드센스", "adsense", "슬롯", "rpm", "ctr", "수익", "배치", "테마", "300x600"]):
        skill_hubs.append("skills/skill-adsense-high-rpm")

    combined: List[str] = []
    for h in crew_hubs + channel_hubs + skill_hubs:
        if h not in combined:
            combined.append(h)

    breakdown = {
        "crew": crew_hubs,
        "channel": channel_hubs,
        "skill": skill_hubs,
    }
    return combined, breakdown


def auto_link_synapses(title, content, source_agent=None, channel=None, links=None):
    """Resolve real ownership; missing channel evidence never defaults to CF."""
    explicit = list(links or []) + re.findall(r"\[\[(.*?)\]\]", content)
    explicit = list(dict.fromkeys(stem(value) for value in explicit))
    known = [value for value in explicit if value in CORE_HUB_STEM_MAP]
    crews = [value for value in known if value.startswith("hubs/crew-")]
    channels = [value for value in known if value.startswith("hubs/channel-")]
    if crews and channels:
        return {"crew": crews, "channel": channels,
                "skill": [value for value in explicit if value.startswith("skills/")],
                "parentHubs": known, "links": explicit}
    parents, groups = resolve_synapse_parents(title, content, source_agent, channel)
    for link in explicit:
        target = stem(link)
        if target not in CORE_HUB_STEM_MAP and target not in {stem(h["rel"]) for h in LEGACY_SKILL_HUBS}:
            continue
        group = "crew" if target.startswith("hubs/crew-") else "channel" if target.startswith("hubs/channel-") else "skill"
        if target not in groups[group]:
            groups[group].append(target)
        if target not in parents:
            parents.append(target)
    if not groups["crew"] or not groups["channel"]:
        raise ValueError("기억은 근거 있는 담당 에이전트와 적용 채널 연결이 각각 필요합니다.")
    return {**groups, "parentHubs": parents, "links": list(dict.fromkeys(parents + [stem(x) for x in explicit]))}


def validate_synapse_hubs(ownership):
    with connect_db() as db:
        live = {stem(row[0]) for row in db.execute("SELECT rel FROM docs WHERE is_core_hub=1")}
        trash = {stem(row[0]) for row in db.execute("SELECT rel FROM memory_trash WHERE restored_at IS NULL")}
    for group in ("crew", "channel"):
        if not set(ownership[group]).intersection(live - trash):
            raise ValueError("실제 저장소에 살아 있는 담당 에이전트·채널 허브가 필요합니다.")


OPERATIONAL_PREFIXES = ("provider return", "naver preparation", "naver reservation", "knowledgein publ",
                        "cf content and p", "timeouterror", "http 500", "status: invalid")


def operational_memory_prefix(title, body=""):
    return any(str(value or "").lstrip().casefold().startswith(prefix)
               for value in (title, body) for prefix in OPERATIONAL_PREFIXES)


def _document_evidence(content):
    match = re.search(r"<!-- barolab-knowledge\s+(.+?)\s+-->", content, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(1))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _validated_knowledge(title, content, category, evidence=None, source="", event_type=None, success=True):
    evidence = evidence or _document_evidence(content)
    event = {"skill": "verified_skill", "revenue": "measured_insight", "insight": "measured_insight",
             "decision": "meeting_decision", "meeting": "meeting_decision"}.get(category, category)
    if operational_memory_prefix(title, content):
        raise ValueError("운영 실행 로그는 지식 노드로 저장할 수 없습니다.")
    result = memorization_decision(event_type or event, content, evidence, success, title=title, source=source)
    if not result["allowed"]:
        raise ValueError("검증된 지식 근거가 필요합니다: " + result["reason"])
    return evidence, result


def _append_parent_links(content, links):
    present = set(stem(x) for x in re.findall(r"\[\[(.*?)\]\]", content))
    missing = [x for x in links if x not in present]
    return content + ("\n\n## 적용 연결\n" + "\n".join(f"- [[{x}]]" for x in missing) + "\n" if missing else "")


def load_growth_revenue_signals() -> Dict[str, Dict[str, Any]]:
    """Read real revenue & traffic signals from `growth.sqlite3` and `metrics.json`."""
    signals: Dict[str, Dict[str, Any]] = {}
    if GROWTH_DB_PATH.is_file():
        try:
            with sqlite3.connect(GROWTH_DB_PATH) as gdb:
                gdb.row_factory = sqlite3.Row
                for row in gdb.execute(
                    "SELECT site_id, service, metric, currency, SUM(value) as total_val "
                    "FROM daily_metrics WHERE value IS NOT NULL GROUP BY site_id, service, metric, currency"
                ):
                    sid = row["site_id"]
                    entry = signals.setdefault(
                        sid,
                        {"site_id": sid, "revenue_usd": 0.0, "revenue_krw": 0.0, "sessions": 0},
                    )
                    val = float(row["total_val"] or 0.0)
                    if row["metric"] == "revenue":
                        if row["currency"] == "KRW":
                            entry["revenue_krw"] += val
                        else:
                            entry["revenue_usd"] += val
                    elif row["metric"] in ("sessions", "visitors"):
                        entry["sessions"] += int(val)
        except Exception:
            pass

    if METRICS_JSON_PATH.is_file():
        try:
            mdata = json.loads(METRICS_JSON_PATH.read_text(encoding="utf-8-sig"))
            for sid, s_info in (mdata.get("sites") or {}).items():
                if not isinstance(s_info, dict):
                    continue
                entry = signals.setdefault(
                    sid,
                    {"site_id": sid, "revenue_usd": 0.0, "revenue_krw": 0.0, "sessions": 0},
                )
                ga4 = s_info.get("ga4") or s_info.get("traffic") or {}
                if isinstance(ga4, dict) and isinstance(ga4.get("sessions"), (int, float)):
                    entry["sessions"] = max(entry["sessions"], int(ga4["sessions"]))
                ads = s_info.get("adsense") or {}
                if isinstance(ads, dict) and isinstance(ads.get("revenue"), (int, float)):
                    entry["revenue_usd"] = max(entry["revenue_usd"], float(ads["revenue"]))
        except Exception:
            pass
    return signals


def promote_growth_insights_to_nodes(db: sqlite3.Connection) -> int:
    """
    Synapse Rule #4 (Growth Promotion):
    Scan `growth.sqlite3` for verified revenue/traffic sites and promote a consolidated,
    multi-hub-connected insight node ONLY when real revenue or traffic exists.
    Never creates orphan nodes.
    """
    signals = load_growth_revenue_signals()
    total_usd = sum(v.get("revenue_usd", 0.0) for v in signals.values())
    total_krw = sum(v.get("revenue_krw", 0.0) for v in signals.values())
    total_sessions = sum(v.get("sessions", 0) for v in signals.values())

    active_cf = [
        (sid, v) for sid, v in signals.items()
        if (v.get("revenue_usd", 0) > 0 or v.get("sessions", 0) > 0) and "." in sid
    ]
    active_cf.sort(key=lambda x: (x[1].get("revenue_usd", 0.0), x[1].get("sessions", 0)), reverse=True)

    # Update revenue stats on `CF 블로그(16개 도메인)` and `트레이스(성과/수익)` core hubs
    db.execute(
        "UPDATE docs SET revenue_usd = ?, revenue_krw = ?, sessions = ? WHERE rel IN ('hubs/channel-cf-blog.md', 'hubs/crew-trace.md')",
        (round(total_usd, 2), round(total_krw, 0), int(total_sessions)),
    )

    if not active_cf:
        return 0

    top_lines = [
        f"- **{sid}**: 누적 수익 `${v.get('revenue_usd', 0.0):.2f}` / 유입 `{v.get('sessions', 0):,} 세션`"
        for sid, v in active_cf[:8]
    ]
    rel = "notes/growth-verified-revenue-insight.md"
    title = "Growth 검증 수익·유입 상위 도메인 인사이트"
    links = [
        "hubs/crew-trace",
        "hubs/crew-jarvis",
        "hubs/channel-cf-blog",
        "hubs/channel-naver-blog",
        "skills/skill-adsense-high-rpm",
        "skills/skill-indirect-experience",
    ]
    body = (
        f"# {title}\n\n"
        f"- **출처 크루**: [[hubs/crew-trace]] (`@트레이스`), [[hubs/crew-jarvis]] (`@팀장`)\n"
        f"- **적용 채널**: [[hubs/channel-cf-blog]], [[hubs/channel-naver-blog]]\n"
        f"- **적용 스킬**: [[skills/skill-adsense-high-rpm]], [[skills/skill-indirect-experience]]\n\n"
        f"## 실측 성과 요약 (`growth.sqlite3`)\n"
        + "\n".join(top_lines)
        + "\n"
    )
    now_ms = int(time.time() * 1000)
    note_file = LOCAL_VAULT_DIR / rel
    note_file.parent.mkdir(parents=True, exist_ok=True)
    note_file.write_text(body, encoding="utf-8")

    db.execute(
        """
        INSERT INTO docs (rel, kind, category, sub_group, title, links, updated, updated_exact, mtime_ms, size, body, revenue_usd, revenue_krw, sessions, is_revenue_hub, is_core_hub)
        VALUES (?, 'note', 'revenue', 'growth', ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 1, 0)
        ON CONFLICT(rel) DO UPDATE SET
            category='revenue', title=excluded.title, links=excluded.links, updated=excluded.updated,
            mtime_ms=excluded.mtime_ms, size=excluded.size, body=excluded.body,
            revenue_usd=excluded.revenue_usd, revenue_krw=excluded.revenue_krw, sessions=excluded.sessions, is_revenue_hub=1
        """,
        (
            rel,
            title,
            json.dumps(links, ensure_ascii=False),
            local_day(now_ms),
            now_ms,
            len(body.encode("utf-8")),
            body,
            round(total_usd, 2),
            round(total_krw, 0),
            int(total_sessions),
        ),
    )
    return 1


def reset_to_clean_slate(force: bool = False) -> Dict[str, Any]:
    """Compatibility entry point: initialize missing hubs without deleting any data."""
    with file_lock(DATA_DIR / ".graph.lock"), connect_db() as db:
        for hub in LEGACY_SKILL_HUBS:
            db.execute("UPDATE docs SET is_core_hub=0 WHERE rel=?", (hub["rel"],))
        existing = {r[0] for r in db.execute("SELECT rel FROM docs")}
        tombstones = {r[0] for r in db.execute("SELECT rel FROM memory_trash WHERE restored_at IS NULL")}
        seeded = 0
        for hub in CLEAN_SEED_HUBS:
            rel = hub["rel"]
            if rel in existing or rel in tombstones:
                continue
            path = safe_path(LOCAL_VAULT_DIR, rel)
            if path.exists():
                raw = path.read_text(encoding="utf-8")
            else:
                raw = hub["body"].strip() + "\n\n" + "\n".join(f"- [[{link}]]" for link in hub["links"]) + "\n"
                atomic_write(path, raw)
            meta = extract_doc_meta(rel, raw, path.stat().st_mtime_ns // 1000000, len(raw.encode("utf-8")))
            db.execute("INSERT OR IGNORE INTO docs(rel,kind,category,sub_group,title,links,updated,mtime_ms,size,body,is_revenue_hub,is_core_hub) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (rel, hub["kind"], hub["category"], hub["sub_group"], meta["title"], json.dumps(meta["links"],ensure_ascii=False), meta["updated"], meta["mtime_ms"], meta["size"], raw, int(hub["is_revenue_hub"]), 1))
            seeded += 1
    return {"status": "initialized_preserving_existing", "seeded": seeded}


def sync_argo_vault_and_growth(force: bool = False) -> Dict[str, Any]:
    """Non-destructive explicit synchronization. Read APIs never rewrite documents."""
    result = reset_to_clean_slate()
    with connect_db() as db:
        count = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    return {**result, "synced_docs": count}


def _serialized_graph_write(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with file_lock(DATA_DIR / ".graph.lock"):
            return function(*args, **kwargs)
    return wrapped


@_serialized_graph_write
def register_synapse_memory(
    title: str,
    content: str,
    category: str = "meeting",
    source_agent: Optional[str] = None,
    channel: Optional[str] = None,
    skill: Optional[str] = None,
    revenue_usd: float = 0.0,
    revenue_krw: float = 0.0,
    sessions: int = 0,
    rel_override: Optional[str] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Register a knowledge document without excluding unlinked records.
    - Rejects deprecated projects or empty/temporary failure logs.
    - Retains the established source/channel/skill metadata resolver for note registration.
    - Backlinks are derived from source links at read time.
    """
    clean_title = (title or "").strip()
    clean_body = (content or "").strip()
    if not clean_title or len(clean_body) < 10:
        raise ValueError("지식 노드는 유효한 제목과 핵심 내용을 포함해야 합니다.")
    if DEPRECATED_PROJECT_PATTERNS.search(f"{clean_title} {clean_body}"):
        raise ValueError("폐기된 레거시 프로젝트(youtube-coupang, biz-down, new-item, kphotogi 등)는 등록할 수 없습니다.")

    category = {"insight": "revenue", "decision": "meeting"}.get(category, category)
    if category not in ("revenue", "skill", "meeting"):
        raise ValueError("새 core 정체성을 만들거나 알 수 없는 지식 유형을 저장할 수 없습니다.")
    evidence, _ = _validated_knowledge(clean_title, clean_body, category, evidence)
    breakdown = auto_link_synapses(clean_title, clean_body, source_agent, channel)
    validate_synapse_hubs(breakdown)
    parent_hubs = breakdown["parentHubs"]

    now_ms = int(time.time() * 1000)
    today_str = local_day(now_ms)

    if rel_override:
        rel = rel_override.replace("\\", "/")
        safe_path(LOCAL_VAULT_DIR, rel)
        if not rel.endswith(".md"):
            rel += ".md"
    else:
        sub = "journal" if category == "meeting" else ("skills" if category == "skill" else "notes")
        slug = note_slug(clean_title)
        rel = f"{sub}/{today_str}-{slug}.md"
    if rel in CORE_HUB_REL_SET:
        raise ValueError("고정 core 허브는 신규 기억으로 덮어쓸 수 없습니다.")

    # Extract any explicit [[wiki-links]] in content and merge with parent_hubs
    explicit_links = [m.group(1).strip() for m in re.finditer(r"\[\[(.+?)\]\]", clean_body) if m.group(1).strip()]
    all_links: List[str] = []
    for lk in parent_hubs + explicit_links:
        lk_stem = stem(lk)
        if lk_stem != stem(rel) and lk_stem not in all_links:
            all_links.append(lk_stem)

    synapse_footer = (
        "\n\n## 4대 시냅스 연결 허브 (Synapse Links)\n"
        f"- **출처 크루**: {', '.join(f'[[{h}]]' for h in breakdown['crew'])}\n"
        f"- **적용 채널**: {', '.join(f'[[{h}]]' for h in breakdown['channel'])}\n"
        f"- **적용 스킬**: {', '.join(f'[[{h}]]' for h in breakdown['skill'])}\n"
    )
    full_md = (
        f"---\nupdated: {today_str}\ncategory: {category}\n---\n"
        f"# {clean_title}\n\n"
        f"{clean_body}"
        f"{synapse_footer}"
        f"\n<!-- barolab-knowledge {json.dumps(evidence, ensure_ascii=False)} -->\n"
    )

    disk_file = safe_path(LOCAL_VAULT_DIR, rel)
    with connect_db() as db:
        if db.execute("SELECT 1 FROM memory_trash WHERE rel=? AND restored_at IS NULL", (rel,)).fetchone():
            raise ValueError("Document is in trash; restore it explicitly before replacing")
    atomic_write(disk_file, full_md)

    kind = "skill" if category == "skill" else ("journal" if category == "meeting" else "note")
    is_rev = 1 if (category == "revenue" or revenue_usd > 0 or revenue_krw > 0) else 0

    with connect_db() as db:
        db.execute(
            """
            INSERT INTO docs (
                rel, kind, category, sub_group, title, links, updated, updated_exact,
                mtime_ms, size, body, revenue_usd, revenue_krw, sessions, is_revenue_hub, is_core_hub
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(rel) DO UPDATE SET
                kind=excluded.kind, category=excluded.category, title=excluded.title,
                links=excluded.links, updated=excluded.updated, mtime_ms=excluded.mtime_ms,
                size=excluded.size, body=excluded.body, revenue_usd=excluded.revenue_usd,
                revenue_krw=excluded.revenue_krw, sessions=excluded.sessions, is_revenue_hub=excluded.is_revenue_hub
            """,
            (
                rel,
                kind,
                category,
                breakdown["channel"][0].split("/")[-1] if breakdown["channel"] else "",
                clean_title,
                json.dumps(all_links, ensure_ascii=False),
                today_str,
                now_ms,
                len(full_md.encode("utf-8")),
                full_md,
                round(float(revenue_usd or 0.0), 2),
                round(float(revenue_krw or 0.0), 0),
                int(sessions or 0),
                is_rev,
            ),
        )
        db.commit()

    return {
        "ok": True,
        "rel": rel,
        "title": clean_title,
        "category": category,
        "parentHubs": parent_hubs,
        "links": all_links,
    }


def load_all_docs(include_unqualified: bool = False) -> List[Dict[str, Any]]:
    with connect_db() as db:
        rows = db.execute(
            "SELECT rel, kind, category, sub_group, title, links, updated, updated_exact, mtime_ms, size, "
            "revenue_usd, revenue_krw, sessions, is_revenue_hub, is_core_hub, body FROM docs"
        ).fetchall()
    if not rows:
        reset_to_clean_slate()
        with connect_db() as db:
            rows = db.execute(
                "SELECT rel, kind, category, sub_group, title, links, updated, updated_exact, mtime_ms, size, "
                "revenue_usd, revenue_krw, sessions, is_revenue_hub, is_core_hub, body FROM docs"
            ).fetchall()
    result = []
    for r in rows:
        rel = r["rel"]
        try:
            links = json.loads(r["links"]) if r["links"] else []
        except Exception:
            links = []
        dir_prefix = rel.split("/")[0] if "/" in rel else "notes"
        raw = read_doc_file(rel)
        result.append(
            {
                "rel": rel,
                "dir": dir_prefix,
                "kind": r["kind"],
                "category": r["category"] or "core_hub",
                "subGroup": r["sub_group"] or "",
                "title": r["title"],
                "links": links if isinstance(links, list) else [],
                "updated": r["updated"],
                "updatedExact": bool(r["updated_exact"]),
                "mtimeMs": r["mtime_ms"],
                "size": r["size"],
                "revenueUsd": float(r["revenue_usd"] or 0.0),
                "revenueKrw": float(r["revenue_krw"] or 0.0),
                "sessions": int(r["sessions"] or 0),
                "isRevenueHub": bool(r["is_revenue_hub"]),
                "isCoreHub": bool(r["is_core_hub"]),
                "revision": revision(raw if raw is not None else r["body"]),
                "sourceKind": "vault_markdown" if raw is not None else "sqlite_document",
                "sourcePath": str(LOCAL_VAULT_DIR / rel) if raw is not None else f"{DB_PATH}#docs/{rel}",
                "content": raw if raw is not None else r["body"],
            }
        )
    docs = result + _hermes_documents()
    return docs if include_unqualified else qualify_graph_documents(docs)[0]


def qualify_graph_documents(docs):
    admitted, quarantined = [], []
    live_hubs = {stem(d["rel"]) for d in docs if d["rel"] in CORE_HUB_REL_SET}
    for item in docs:
        doc = dict(item)
        if doc["rel"] in CORE_HUB_REL_SET:
            doc["isCoreHub"] = True
            admitted.append(doc)
            continue
        doc["isCoreHub"] = False
        if doc["rel"] in ("hermes/MEMORY.md", "hermes/USER.md") and doc.get("sourceKind") == "bounded_memory" and Path(doc.get("sourcePath", "")).resolve() == (hermes_store.root / doc["rel"].split("/")[1]).resolve():
            doc["isCoreHub"] = True
            admitted.append(doc)
            continue
        content = doc.get("content", "")
        try:
            evidence = doc.get("evidence") or _document_evidence(content)
            _, decision = _validated_knowledge(doc["title"], content, doc.get("category", ""), evidence,
                                               source=(doc.get("sourcePath", "") + " " + doc["rel"]).replace("\\", "/"),
                                               event_type=doc.get("eventType"), success=doc.get("success", True))
            metadata = evidence.get("knowledge", evidence) if isinstance(evidence, dict) else {}
            ownership = auto_link_synapses(doc["title"], content, metadata.get("sourceAgent"), metadata.get("channel"), doc.get("links"))
            if not set(ownership["crew"]).intersection(live_hubs) or not set(ownership["channel"]).intersection(live_hubs):
                raise ValueError("실제 그래프에 담당 에이전트·채널 허브가 없습니다.")
            # A projection may only display links present in the authoritative
            # source. New verified episode projections persist their evidence.
            if doc.get("sourceKind") == "sqlite_episode":
                doc["links"] = ownership["links"]
            elif not set(ownership["crew"]).intersection(doc.get("links", [])) or not set(ownership["channel"]).intersection(doc.get("links", [])):
                raise ValueError("원본에 에이전트·채널 연결이 저장되어 있지 않습니다.")
            doc.update(verifiedKnowledge=True, knowledgeStatus="curated_procedure" if metadata.get("provenance") == "curated_procedure" else "verified_knowledge")
            # Expose only source-bound learning identifiers, never raw work receipts.
            receipt_hash = metadata.get("workReceiptSha256", "")
            verifier_hash = metadata.get("verifierReceiptSha256", "")
            if all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in (receipt_hash, verifier_hash)):
                doc["learningEvidence"] = {
                    "sourceEventId": evidence.get("sourceEventId", doc.get("eventId", "")),
                    "workReceiptSha256": receipt_hash,
                    "verifierReceiptSha256": verifier_hash,
                    "sourceAgent": metadata.get("sourceAgent", ""),
                    "channel": metadata.get("channel", ""),
                    "skillRevision": doc.get("revision", ""),
                }
            admitted.append(doc)
        except ValueError as exc:
            quarantined.append({"rel": doc["rel"], "title": doc["title"], "sourceKind": doc.get("sourceKind"), "reason": str(exc)})
    return admitted, quarantined


def contamination_candidates(docs):
    """Use real undirected edges; never the declared or UI-adjusted degree."""
    graph = build_graph_2d(docs, DEFAULT_AGENTS)
    degree = {node["rel"]: 0 for node in graph["nodes"]}
    for a, b in graph["edges"]:
        degree[graph["nodes"][a]["rel"]] += 1
        degree[graph["nodes"][b]["rel"]] += 1
    candidates = []
    admitted_rels = {d["rel"] for d in qualify_graph_documents(docs)[0]}
    for doc in docs:
        if doc["rel"] in CORE_HUB_REL_SET:
            continue
        prefix = operational_memory_prefix(doc["title"], doc.get("content", ""))
        orphan = doc.get("category") in ("meeting", "decision") and degree.get(doc["rel"], 0) == 0
        if prefix or orphan:
            # A concurrent, genuinely evidenced decision must not be discarded
            # merely because its graph projection has not yet been requested.
            if not prefix and doc["rel"] in admitted_rels:
                continue
            candidates.append({"rel": doc["rel"], "eventId": doc.get("eventId"), "title": doc["title"],
                               "degree": degree.get(doc["rel"], 0), "prefix": prefix,
                               "orphanDecision": orphan, "sourceKind": doc.get("sourceKind")})
    return candidates


def purge_contaminated_memories(*, apply=False, backup_dir=None):
    """Explicit maintenance only. Never called by reads or an API request.

    The copied episode/FTS records are purgeable; original operational ledgers,
    session snapshots, review/audit history and procedural sources are preserved.
    """
    hermes_store.initialize()
    with file_lock(DATA_DIR / ".graph.lock"), file_lock(hermes_store.lock_path):
        docs = load_all_docs(include_unqualified=True)
        candidates = contamination_candidates(docs)
        event_ids = [x["eventId"] for x in candidates if x["eventId"]]
        graph_rels = [x["rel"] for x in candidates if x["sourceKind"] in ("vault_markdown", "sqlite_document")]
        result = {"applied": False, "candidates": candidates, "candidateCount": len(candidates),
                  "episodeCandidates": len(event_ids), "graphRowCandidates": len(graph_rels)}
        if not apply:
            return result
        if graph_rels:
            raise ValueError("Persistent vault candidates require explicit archival/tombstones; no partial purge performed")
        if not backup_dir:
            raise ValueError("An external backup directory is required")
        destination = Path(backup_dir).resolve()
        if destination == BASE_DIR.resolve() or BASE_DIR.resolve() in destination.parents:
            raise ValueError("Backups must be outside the repository")
        destination.mkdir(parents=True, exist_ok=True)
        with hermes_store.db() as db:
            active = {r[0] for r in db.execute("SELECT event_id FROM review_queue WHERE state='running'")}
            if active.intersection(event_ids):
                raise MemoryConflict("Target review is running; purge postponed")
        backups = []
        for path in (DB_PATH, hermes_store.db_path):
            target = destination / (path.stem + "-before-purge-" + uuid.uuid4().hex[:8] + ".sqlite3")
            with closing(sqlite3.connect(path, timeout=15)) as source, closing(sqlite3.connect(target)) as copied:
                source.execute("PRAGMA query_only=ON")
                source.backup(copied)
                if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed")
            backups.append({"source": str(path), "backup": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        atomic_write(destination / "purge-targets.json", json.dumps(result, ensure_ascii=False, indent=2))
        with hermes_store.db() as db:
            db.execute("BEGIN IMMEDIATE")
            active = {r[0] for r in db.execute("SELECT event_id FROM review_queue WHERE state='running'")}
            if active.intersection(event_ids):
                raise MemoryConflict("Target review was claimed during backup; purge postponed")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            deleted = {table: 0 for table in ("sessions_fts", "episode_fts", "review_queue", "episodes")}
            for event_id in event_ids:
                for table in ("sessions_fts", "episode_fts", "review_queue", "episodes"):
                    if table in tables:
                        deleted[table] += db.execute(f"DELETE FROM {table} WHERE event_id=?", (event_id,)).rowcount
        vacuum = {}
        for path in (hermes_store.db_path, DB_PATH):
            try:
                with closing(sqlite3.connect(path, timeout=15)) as db:
                    db.execute("PRAGMA busy_timeout=15000")
                    db.execute("VACUUM")
                    vacuum[str(path)] = db.execute("PRAGMA integrity_check").fetchone()[0]
            except sqlite3.OperationalError as exc:
                vacuum[str(path)] = "deferred: " + str(exc)
        with hermes_store.db() as db:
            remaining = {table: sum(db.execute(f"SELECT COUNT(*) FROM {table} WHERE event_id=?", (event_id,)).fetchone()[0] for event_id in event_ids)
                         for table in ("episodes", "sessions_fts", "episode_fts") if table in tables}
        result.update(applied=True, backups=backups, deletedEpisodes=deleted["episodes"], deletedGraphRows=0,
                      deletedRows=deleted, targetRowsRemaining=remaining, vacuum=vacuum)
        atomic_write(destination / "purge-result.json", json.dumps(result, ensure_ascii=False, indent=2))
        return result


def build_graph_2d(
    docs: List[Dict[str, Any]],
    agents: List[Dict[str, Any]],
    category_filter: str = "all",
    query: str = "",
) -> Dict[str, Any]:
    """
    Build the graph from every real document and valid explicit link.
    Supports category_filter in ('all', 'core_hub', 'revenue', 'skill', 'meeting').
    When a filter is active, matching nodes AND their connected parent hubs are kept so
    connected context remains available. Unlinked documents remain visible in all.
    """
    nodes: List[Dict[str, Any]] = []
    idx: Dict[str, int] = {}
    by_base: Dict[str, str] = {}
    by_title: Dict[str, str] = {}

    for d in docs:
        node_id = stem(d["rel"])
        idx[node_id] = len(nodes)
        nodes.append(
            {
                "id": node_id,
                "type": "hub" if d.get("isCoreHub") else ("skill" if d.get("category") == "skill" else "note"),
                "kind": d.get("kind", "note"),
                "category": d.get("category", "core_hub"),
                "subGroup": d.get("subGroup", ""),
                "label": d["title"],
                "rel": d["rel"],
                "updated": d.get("updated", ""),
                "revenueUsd": d.get("revenueUsd", 0.0),
                "revenueKrw": d.get("revenueKrw", 0.0),
                "sessions": d.get("sessions", 0),
                "isRevenueHub": bool(d.get("isRevenueHub", False)),
                "isCoreHub": bool(d.get("isCoreHub", False)),
                "layer": d.get("layer", "semantic"),
                "sourceKind": d.get("sourceKind", "vault_markdown"),
                "sourcePath": d.get("sourcePath", str(LOCAL_VAULT_DIR / d["rel"])),
                "readOnly": d.get("readOnly", False),
                "revision": d.get("revision", ""),
                "skillName": d.get("skillName", ""),
                "verifiedKnowledge": d.get("verifiedKnowledge", False),
                "knowledgeStatus": d.get("knowledgeStatus", "core_identity" if d.get("isCoreHub") else "profile"),
                "learningEvidence": d.get("learningEvidence"),
            }
        )
        by_base[node_id.split("/")[-1]] = node_id
        by_title[d["title"]] = node_id

    def resolve(link_target: str) -> Optional[str]:
        if link_target in idx:
            return link_target
        if link_target in by_base:
            return by_base[link_target]
        if link_target in by_title:
            return by_title[link_target]
        return None

    edges: List[List[int]] = []
    seen_edges = set()
    for d in docs:
        from_id = stem(d["rel"])
        if from_id not in idx:
            continue
        for l in d.get("links") or []:
            to_id = resolve(l)
            if not to_id or to_id == from_id or to_id not in idx:
                continue
            pair = sorted([from_id, to_id])
            key = f"{pair[0]}→{pair[1]}"
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append([idx[from_id], idx[to_id]])

    deg = [0] * len(nodes)
    for a_idx, b_idx in edges:
        deg[a_idx] += 1
        deg[b_idx] += 1

    for i, n in enumerate(nodes):
        n["deg"] = deg[i]

    # Category counts before filter
    cat_counts = {
        "core_hub": sum(1 for n in nodes if n.get("isCoreHub") or n.get("category") == "core_hub"),
        "revenue": sum(1 for n in nodes if n.get("category") == "revenue" or n.get("revenueUsd", 0) > 0 or n.get("revenueKrw", 0) > 0),
        "skill": sum(1 for n in nodes if n.get("category") == "skill" or n.get("subGroup") == "skill"),
        "meeting": sum(1 for n in nodes if n.get("category") == "meeting"),
    }

    q_clean = (query or "").strip().lower()
    cat_clean = (category_filter or "all").strip().lower()

    def matches_filter(i: int, n: Dict[str, Any]) -> bool:
        if cat_clean == "core_hub":
            if not (n.get("isCoreHub") or n.get("category") == "core_hub"):
                return False
        elif cat_clean == "revenue":
            if not (n.get("category") == "revenue" or n.get("revenueUsd", 0) > 0 or n.get("revenueKrw", 0) > 0 or n.get("subGroup") in ("channel", "crew")):
                return False
        elif cat_clean == "skill":
            if not (n.get("category") == "skill" or n.get("subGroup") == "skill"):
                return False
        elif cat_clean == "meeting":
            if not (n.get("category") == "meeting"):
                return False

        if q_clean:
            hay = f"{n.get('label', '')} {n.get('rel', '')} {n.get('id', '')} {n.get('subGroup', '')}".lower()
            if q_clean not in hay:
                return False
        return True

    keep = [matches_filter(i, n) for i, n in enumerate(nodes)]

    # Include immediate connected parent hubs for kept nodes so filtered view never produces visual orphans
    if any(keep):
        matched_indices = {i for i, k in enumerate(keep) if k}
        if len(matched_indices) == 1 or cat_clean in ("revenue", "skill", "meeting") or q_clean:
            for a_idx, b_idx in edges:
                if a_idx in matched_indices and deg[b_idx] > 0:
                    keep[b_idx] = True
                if b_idx in matched_indices and deg[a_idx] > 0:
                    keep[a_idx] = True

    remap: Dict[int, int] = {}
    nodes2: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        if keep[i]:
            remap[i] = len(nodes2)
            nodes2.append(n)

    edges2 = [[remap[a], remap[b]] for a, b in edges if keep[a] and keep[b]]
    neighbours = {i: set() for i in range(len(nodes))}
    for a, b in edges:
        neighbours[a].add(nodes[b]["id"])
        neighbours[b].add(nodes[a]["id"])
    missing_ownership = []
    for i, node in enumerate(nodes):
        if node.get("isCoreHub") or node.get("category") not in ("skill", "revenue", "insight", "meeting", "decision"):
            continue
        if not any(x.startswith("hubs/crew-") for x in neighbours[i]) or not any(x.startswith("hubs/channel-") for x in neighbours[i]):
            missing_ownership.append(node["rel"])

    return {
        "nodes": nodes2,
        "edges": edges2,
        "hiddenOrphans": 0,
        "stats": {
            "total": len(nodes),
            "links": len(edges),
            "linked": sum(1 for d in deg if d > 0),
            "isolated": sum(1 for d in deg if d == 0),
            "coreHubs": cat_counts["core_hub"],
            "revenueMemories": cat_counts["revenue"],
            "skillNodes": cat_counts["skill"],
            "proceduralSkills": sum(1 for n in nodes if n.get("sourceKind") == "project_skill"),
            "meetingDecisions": cat_counts["meeting"],
            "revenueHubs": sum(1 for n in nodes if n.get("isRevenueHub")),
            "integrity": {"formula": "100 * nodes_with_real_edge / exposed_nodes", "denominator": len(nodes),
                          "connectedNodes": sum(d > 0 for d in deg), "percent": round(100 * sum(d > 0 for d in deg) / len(nodes), 2) if nodes else 0,
                          "danglingEdges": sum(a >= len(nodes) or b >= len(nodes) for a, b in edges),
                          "knowledgeMissingOwnership": missing_ownership},
        },
    }


def read_doc_file(rel: str) -> Optional[str]:
    candidate = safe_path(LOCAL_VAULT_DIR, rel)
    return candidate.read_text(encoding="utf-8") if candidate.is_file() else None


class SaveNoteRequest(BaseModel):
    title: str
    content: str
    category: str = "skill"
    sourceAgent: Optional[str] = None
    channel: Optional[str] = None
    skill: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    merge: bool = True
    create: bool = False


from server.dashboard_cache import ReadCache
_GRAPH_READ_CACHE = ReadCache(ttl=30, capacity=8)


@memory_router.get("/synapses")
def get_synapse_summary():
    from dashboard.agents.synapse import summary
    return summary()


def _synapse_graph(query='', category='all'):
    """Read-only view of the same central graph used by the cockpit; no inferred links."""
    path=DATA_DIR/'memory_graph.json'
    def build():
        graph=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'nodes':{},'edges':[]}
        nodes=[];lookup={}
        for identity,node in graph.get('nodes',{}).items():
            kind=node.get('type','note');hub=kind=='MemoryHub'
            lookup[identity]=len(nodes)
            nodes.append(dict(id=identity,label=str(node.get('title') or node.get('displayName') or node.get('brand') or node.get('account') or node.get('domain') or {'MemoryHub':'공용 기억 허브','AudienceStrategy':'독자 전략'}.get(kind,kind)),
                type='hub' if hub else 'note',kind=kind,category='core_hub' if hub else 'insight',
                rel='',readOnly=True,sourceKind='synapse_memory',sourcePath='dashboard/data/memory_graph.json',
                isCoreHub=hub,verifiedKnowledge=False,deg=0))
        edges=[]
        for edge in graph.get('edges',[]):
            a=lookup.get(edge.get('source'));b=lookup.get(edge.get('target'))
            if a is not None and b is not None:
                edges.append([a,b]);nodes[a]['deg']+=1;nodes[b]['deg']+=1
        stats=dict(total=len(nodes),links=len(edges),linked=sum(n['deg']>0 for n in nodes),isolated=sum(n['deg']==0 for n in nodes),
            coreHubs=sum(n['isCoreHub'] for n in nodes),skillNodes=sum(n['category']=='skill' for n in nodes),
            revenueMemories=sum(n['category']=='revenue' for n in nodes),revenueHubs=0)
        return dict(contractVersion='memory-knowledge-gate-v1',nodes=nodes,edges=edges,stats=stats,
            quarantine=dict(count=0,items=[],bySourceKind={}),coreHubs=[],agents=[],recentNotes=[],recentJournals=[],
            source='dashboard/data/memory_graph.json')
    signature=path.stat().st_mtime_ns if path.is_file() else 0
    result=_GRAPH_READ_CACHE.get(('synapse-graph',str(path),signature),build)
    if query:
        matched={i for i,n in enumerate(result['nodes']) if str(query).casefold() in n['label'].casefold()}
        keep=matched|{i for i,n in enumerate(result['nodes']) if n['isCoreHub']}
        order=sorted(keep);remap={old:new for new,old in enumerate(order)}
        return {**result,'nodes':[result['nodes'][i] for i in order],
                'edges':[[remap[a],remap[b]] for a,b in result['edges'] if a in keep and b in keep]}
    return result


@memory_router.get("/summary")
def get_memory_summary():
    graph = _synapse_graph()
    return {"contractVersion": graph["contractVersion"], "stats": graph["stats"]}


@memory_router.get("/graph")
def get_memory_graph(
    request: Request = None,
    category: str = Query("all", description="Filter: all | core_hub | revenue | skill | meeting"),
    revenue_only: bool = Query(False),
    q: str = Query(""),
    source: str = Query("synapses"),
):
    # Direct internal callers retain immediate source validation; HTTP readers
    # share a short-lived projection without duplicating proof scans.
    if request is None:
        return _build_memory_graph(category, revenue_only, q)
    if source=="synapses":return _synapse_graph(q,category)
    return _GRAPH_READ_CACHE.get((category, revenue_only, q),
        lambda: _build_memory_graph(category, revenue_only, q))


def _build_memory_graph(category="all", revenue_only=False, q=""):
    cat_str = category if isinstance(category, str) else "all"
    rev_bool = revenue_only if isinstance(revenue_only, bool) else False
    q_str = q if isinstance(q, str) else ""
    docs, quarantined = qualify_graph_documents(load_all_docs(include_unqualified=True))
    effective_cat = "revenue" if (rev_bool and cat_str == "all") else cat_str
    graph = build_graph_2d(
        docs=docs,
        agents=DEFAULT_AGENTS,
        category_filter=effective_cat,
        query=q_str,
    )
    graph["quarantine"] = {"count": len(quarantined), "items": quarantined,
                           "bySourceKind": {kind: sum(x["sourceKind"] == kind for x in quarantined)
                                            for kind in sorted({x["sourceKind"] or "unknown" for x in quarantined})}}
    graph["stats"]["quarantined"] = len(quarantined)
    core_hub_list = [d for d in docs if d.get("isCoreHub") or d.get("category") == "core_hub"]
    skill_and_revenue_list = [
        d for d in docs if d.get("category") in ("skill", "revenue")
    ]
    meeting_list = sorted(
        [d for d in docs if d.get("category") == "meeting" or d.get("kind") == "journal"],
        key=lambda x: (x.get("updated", ""), x.get("mtimeMs", 0)),
        reverse=True,
    )[:30]
    return {
        "contractVersion": "memory-knowledge-gate-v1",
        **graph,
        "agents": DEFAULT_AGENTS,
        "coreHubs": core_hub_list,
        "recentNotes": skill_and_revenue_list + core_hub_list,
        "recentJournals": meeting_list,
    }


@memory_router.get("/doc")
def get_memory_doc(rel: str = Query(...)):
    try:
        return _read_document(rel)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@memory_router.post("/note")
def save_memory_note(req: SaveNoteRequest):
    try:
        res = register_synapse_memory(
            title=req.title,
            content=req.content,
            category=req.category or "skill",
            evidence=req.evidence,
            source_agent=req.sourceAgent,
            channel=req.channel,
            skill=req.skill,
        )
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@memory_router.post("/sync")
def trigger_memory_sync(reset: bool = Query(False)):
    if reset is True:
        raise HTTPException(409, "Destructive reset is disabled; use document trash/restore")
    res = sync_argo_vault_and_growth(force=True)
    docs = load_all_docs()
    graph = build_graph_2d(docs, DEFAULT_AGENTS, category_filter="all")
    return {"ok": True, **res, "stats": graph["stats"]}


@memory_router.get("/boss-profile")
def get_boss_profile():
    md = read_doc_file(BOSS_PROFILE_REL) or ""
    items = []
    for section in BOSS_SECTIONS:
        m = re.search(rf"## {section}\s*\n([\s\S]*?)(?=\n## |\Z)", md)
        if not m:
            continue
        for line in m.group(1).split("\n"):
            txt = re.sub(r"^[-*]\s*", "", line).strip()
            if txt and not txt.startswith("("):
                items.append({"section": section, "text": txt})
    return {"rel": BOSS_PROFILE_REL, "md": md, "items": items}


def _hermes_documents():
    docs = []
    for target, filename, title in (("memory", "MEMORY.md", "핵심 기억 (MEMORY)"), ("user", "USER.md", "사용자 프로필 (USER)")):
        item = hermes_store.bounded(target)
        path = hermes_store.root / filename
        # Every agent run receives these frozen documents through the shared
        # memory integration. These are explicit system-context consumer edges,
        # not an inferred topic/channel claim or a fabricated success metric.
        context_consumers = [stem(agent["hubRel"]) for agent in DEFAULT_AGENTS]
        docs.append({"rel": f"hermes/{filename}", "title": title, "kind": "memory", "category": "memory",
                     "layer": "semantic" if target == "memory" else "profile", "links": list(dict.fromkeys(re.findall(r"\[\[(.*?)\]\]",item["content"]) + context_consumers)), "isCoreHub": True,
                     "relationEvidence": "dashboard/common/llm_client.py frozen agent-session context (read only; unchanged)",
                     "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(), "sourceKind": "bounded_memory",
                     "sourcePath": str(path), "revision": item["revision"], "content": item["content"], "limit": item["limit"]})
    for skill in hermes_store.skill_list():
        path = hermes_store._skill_path(skill["name"])
        body = hermes_store.skill_view(skill["name"])["content"]
        docs.append({"rel": f"procedural/{skill['name']}/SKILL.md", "title": skill["title"], "kind": "skill", "category": "skill", "skillName": skill["name"],
                     "layer": "procedural", "links": re.findall(r"\[\[(.*?)\]\]",body), "sourceKind": "project_skill", "sourcePath": str(path),
                     "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(), "mtimeMs": path.stat().st_mtime_ns//1000000,
                     "revision": skill["revision"], "content": body})
    with hermes_store.db() as db:
        episodes = db.execute("SELECT * FROM episodes ORDER BY created_at").fetchall()
        audits = db.execute("SELECT source,target FROM audit WHERE source LIKE 'review:%'").fetchall()
    for item in episodes:
        # Full event IDs remain data, never a filesystem path.
        key = revision(item["event_id"])
        targets = [r["target"] for r in audits if r["source"] == "review:" + item["event_id"]]
        links = []
        for target in targets:
            if target in ("memory", "user"):
                links.append("hermes/" + ("MEMORY" if target == "memory" else "USER"))
            elif target.startswith("skill:"):
                links.append("procedural/" + target.split(":",1)[1] + "/SKILL")
        evidence = json.loads(item["evidence"] or "{}")
        verdict = memorization_decision(item["event_type"], item["summary"], evidence, bool(item["success"]))
        category = {"verified_skill": "skill", "measured_insight": "revenue", "meeting_decision": "meeting"}.get(verdict["kind"], "meeting")
        docs.append({"rel": f"episodes/{key}.md", "eventId": item["event_id"], "title": item["summary"][:100], "kind": "episode",
                     "category": category, "layer": "episodic", "links": list(dict.fromkeys(links)), "sourceKind": "sqlite_episode",
                     "content": item["summary"], "evidence": evidence, "eventType": item["event_type"], "success": bool(item["success"]),
                     "sourcePath": f"{hermes_store.db_path}#episodes/{item['event_id']}", "updated": item["created_at"], "readOnly": True,
                     "revision": revision(json.dumps(dict(item),ensure_ascii=False,indent=2))})
    return docs


def _read_document(rel):
    rel = str(rel).replace("\\", "/")
    safe_path(LOCAL_VAULT_DIR, rel)
    if rel.startswith(("hermes/", "procedural/", "episodes/")):
        doc = next((d for d in _hermes_documents() if d["rel"] == rel), None)
        if doc is None:
            raise HTTPException(404, "Memory document not found")
        if doc["sourceKind"] == "project_skill":
            doc.update(hermes_store.skill_view(rel.split("/")[1]))
        elif doc["sourceKind"] == "sqlite_episode":
            with hermes_store.db() as db:
                row = db.execute("SELECT * FROM episodes WHERE event_id=?", (doc["eventId"],)).fetchone()
            doc["content"] = json.dumps(dict(row), ensure_ascii=False, indent=2)
            doc["revision"] = revision(doc["content"])
        all_docs = load_all_docs()
        aliases = {rel,stem(rel),stem(rel).split("/")[-1],doc["title"]}
        backlinks = [{"rel": d["rel"],"title":d["title"],"updated":d.get("updated","")} for d in all_docs if d["rel"] != rel and aliases.intersection(d.get("links",[]))]
        candidates = [{"rel":d["rel"],"title":d["title"],"id":stem(d["rel"])} for d in all_docs if d["rel"] != rel]
        doc.update({"editable": not doc.get("readOnly", False), "deletable": doc["sourceKind"] == "project_skill", "backlinks": backlinks, "parents": doc.get("links",[]), "parentCandidates": candidates, "readOnlyReason": "Immutable episode evidence" if doc.get("readOnly") else ""})
        return doc
    with connect_db() as db:
        row = db.execute("SELECT * FROM docs WHERE rel=?", (rel,)).fetchone()
        if row is None:
            raise HTTPException(404, "Memory document not found")
        rows = db.execute("SELECT rel,title,links,updated,is_core_hub FROM docs").fetchall()
    path = safe_path(LOCAL_VAULT_DIR, rel)
    raw = read_doc_file(rel)
    content = raw if raw is not None else row["body"]
    links = json.loads(row["links"] or "[]")
    aliases = {stem(rel), stem(rel).split("/")[-1], row["title"], rel}
    backlinks = [{"rel": r["rel"], "title": r["title"], "updated": r["updated"]} for r in rows if r["rel"] != rel and aliases.intersection(json.loads(r["links"] or "[]"))]
    candidates = [{"rel": r["rel"], "title": r["title"], "id": stem(r["rel"])} for r in rows if r["rel"] != rel]
    for extra in _hermes_documents():
        candidates.append({"rel":extra["rel"],"title":extra["title"],"id":stem(extra["rel"])})
        if aliases.intersection(extra.get("links",[])):
            backlinks.append({"rel":extra["rel"],"title":extra["title"],"updated":extra.get("updated","")})
    return {"rel": rel, "title": row["title"], "kind": row["kind"], "category": row["category"], "subGroup": row["sub_group"],
            "content": content, "links": links, "parents": links, "backlinks": backlinks, "parentCandidates": candidates,
            "revision": revision(content), "updated": row["updated"], "isCoreHub": bool(row["is_core_hub"]),
            "sourceKind": "vault_markdown" if raw is not None else "sqlite_document", "sourcePath": str(path) if raw is not None else f"{DB_PATH}#docs/{rel}",
            "readOnly": False, "editable": True, "deletable": rel not in FIXED_CORE_RELS,
            "readOnlyReason": "고정 core 정체성: 본문 편집 가능, 삭제 불가" if rel in FIXED_CORE_RELS else ""}


class PatchMemoryDoc(BaseModel):
    expectedRevision: str
    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    links: Optional[List[str]] = None


@memory_router.patch("/doc")
def patch_memory_doc(req: PatchMemoryDoc, rel: str = Query(...)):
    try:
        lock = hermes_store.lock_path if rel.startswith(("hermes/", "procedural/")) else DATA_DIR / ".graph.lock"
        with file_lock(lock):
            current = _read_document(rel)
            if not current["editable"]:
                raise HTTPException(409, "This source is immutable")
            if current["revision"] != req.expectedRevision:
                raise HTTPException(409, "Document changed; reload before editing")
            content = req.content if req.content is not None else current["content"]
            title = req.title if req.title is not None else current["title"]
            if not title.strip() or len(title) > 240 or len(content) > 1000000:
                raise ValueError("Invalid document title or content size")
            if rel.startswith("hermes/"):
                limit = current["limit"]
                if len(content) > limit:
                    raise ValueError(f"Bounded memory exceeds {limit} characters; nothing was written")
                path = hermes_store.root / rel.split("/")[1]
                atomic_write(path, content)
                hermes_store._audit("dashboard", "patch", rel, current["content"], content)
            elif rel.startswith("procedural/"):
                if not content.strip() or len(content) > 60000:
                    raise ValueError("Skill must contain 1..60000 characters")
                evidence, _ = _validated_knowledge(title, content, "skill", req.evidence or _document_evidence(current["content"]))
                metadata = evidence.get("knowledge", evidence)
                ownership = auto_link_synapses(title, content, metadata.get("sourceAgent"), metadata.get("channel"))
                validate_synapse_hubs(ownership)
                content = _append_parent_links(content, ownership["links"])
                path = hermes_store._skill_path(rel.split("/")[1])
                atomic_write(path, content)
                hermes_store._audit("dashboard", "patch", rel, current["content"], content)
            else:
                links = req.links if req.links is not None else current["links"]
                if not all(isinstance(link, str) and len(link) <= 300 for link in links):
                    raise ValueError("Invalid links")
                category = req.category or current["category"]
                category = {"decision": "meeting", "insight": "revenue"}.get(category, category)
                if category not in ("core_hub", "revenue", "skill", "meeting"):
                    raise ValueError("Invalid category")
                # Raw content is authoritative; metadata links also persist visibly in the source.
                if req.title is not None and title != current["title"]:
                    content = re.sub(r"^#\s+.+$", lambda _: "# " + title, content, count=1, flags=re.M) if re.search(r"^#\s+", content, re.M) else "# " + title + "\n\n" + content
                if req.links is not None:
                    content = re.sub(r"\[\[(.*?)\]\]", lambda m: m.group(0) if m.group(1).strip() in links else m.group(1), content)
                    existing = set(re.findall(r"\[\[(.*?)\]\]", content))
                    missing = [link for link in links if link not in existing]
                    if missing:
                        content += "\n\n## 연결\n" + "\n".join(f"- [[{link}]]" for link in missing) + "\n"
                else:
                    links = list(dict.fromkeys(re.findall(r"\[\[(.*?)\]\]", content)))
                if rel not in CORE_HUB_REL_SET:
                    evidence, _ = _validated_knowledge(title, content, category, req.evidence or _document_evidence(current["content"]))
                    metadata = evidence.get("knowledge", evidence)
                    ownership = auto_link_synapses(title, content, metadata.get("sourceAgent"), metadata.get("channel"), links)
                    validate_synapse_hubs(ownership)
                    links = ownership["links"]
                    content = _append_parent_links(content, links)
                    if not _document_evidence(content):
                        content += f"\n<!-- barolab-knowledge {json.dumps(evidence, ensure_ascii=False)} -->\n"
                elif category != current["category"]:
                    raise ValueError("고정 core 허브의 유형은 변경할 수 없습니다.")
                path = safe_path(LOCAL_VAULT_DIR, rel)
                old_exists = path.exists()
                try:
                    with connect_db() as db:
                        db.execute("BEGIN IMMEDIATE")
                        atomic_write(path, content)
                        db.execute("UPDATE docs SET title=?,category=?,links=?,body=?,updated=?,mtime_ms=?,size=? WHERE rel=?", (title, category, json.dumps(links, ensure_ascii=False), content, datetime.now().isoformat(), int(time.time()*1000), len(content.encode("utf-8")), rel))
                except Exception:
                    if old_exists:
                        atomic_write(path, current["content"])
                    elif path.exists():
                        path.unlink()
                    raise
        return {"ok": True, "doc": _read_document(rel)}
    except MemoryConflict as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@memory_router.delete("/doc")
def delete_memory_doc(rel: str = Query(...), expected_revision: str = Query(...)):
    if str(rel).replace("\\", "/") in FIXED_CORE_RELS:
        raise HTTPException(409, "고정 core 정체성은 삭제할 수 없습니다.")
    try:
        with file_lock(DATA_DIR / ".graph.lock"):
            current = _read_document(rel)
            if not current["deletable"]:
                raise HTTPException(409, "Protected source; use an exact content patch")
            if current["revision"] != expected_revision:
                raise HTTPException(409, "Document changed; reload before deleting")
            trash_id = uuid.uuid4().hex
            if rel.startswith("procedural/"):
                path = hermes_store._skill_path(rel.split("/")[1])
                with file_lock(hermes_store.lock_path), connect_db() as db:
                    if revision(path.read_text(encoding="utf-8")) != expected_revision:
                        raise HTTPException(409, "Skill changed; reload before deleting")
                    payload = {"sourceKind": "project_skill", "content": current["content"], "name": rel.split("/")[1]}
                    db.execute("INSERT INTO memory_trash VALUES(?,?,?,?,NULL)", (trash_id, rel, json.dumps(payload,ensure_ascii=False), datetime.now().isoformat()))
                    # The full source is durably saved in the trash transaction first.
                try:
                    with file_lock(hermes_store.lock_path):
                        if revision(path.read_text(encoding="utf-8")) != expected_revision:
                            raise HTTPException(409, "Skill changed before deletion; reload")
                        path.unlink()
                except Exception:
                    with connect_db() as db:
                        db.execute("DELETE FROM memory_trash WHERE trash_id=?", (trash_id,))
                    raise
                return {"ok": True, "rel": rel, "trashId": trash_id, "removedEdges": 0, "restorable": True}
            path = safe_path(LOCAL_VAULT_DIR, rel)
            with connect_db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = dict(db.execute("SELECT * FROM docs WHERE rel=?", (rel,)).fetchone())
                payload = {"row": row, "content": current["content"], "hadFile": path.exists()}
                db.execute("INSERT INTO memory_trash VALUES(?,?,?,?,NULL)", (trash_id, rel, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()))
                db.execute("DELETE FROM docs WHERE rel=?", (rel,))
            # Leave the source file intact as the recoverable original. The tombstone excludes it.
        return {"ok": True, "rel": rel, "trashId": trash_id, "removedEdges": len(current["links"]) + len(current["backlinks"]), "restorable": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@memory_router.get("/trash")
def list_memory_trash():
    with connect_db() as db:
        return {"items": [dict(r) for r in db.execute("SELECT trash_id AS trashId,rel,deleted_at AS deletedAt FROM memory_trash WHERE restored_at IS NULL ORDER BY deleted_at DESC")]}


@memory_router.post("/trash/{trash_id}/restore")
def restore_memory_doc(trash_id: str):
    with file_lock(DATA_DIR / ".graph.lock"), connect_db() as db:
        item = db.execute("SELECT * FROM memory_trash WHERE trash_id=? AND restored_at IS NULL", (trash_id,)).fetchone()
        if not item:
            raise HTTPException(404, "Trash entry not found")
        payload = json.loads(item["payload"])
        if payload.get("sourceKind") == "project_skill":
            try:
                evidence, _ = _validated_knowledge(payload["name"], payload["content"], "skill")
                metadata = evidence.get("knowledge", evidence)
                ownership = auto_link_synapses(payload["name"], payload["content"], metadata.get("sourceAgent"), metadata.get("channel"))
                validate_synapse_hubs(ownership)
                payload["content"] = _append_parent_links(payload["content"], ownership["links"])
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            path = hermes_store._skill_path(payload["name"])
            with file_lock(hermes_store.lock_path):
                if path.exists():
                    raise HTTPException(409, "A skill already occupies this path")
                atomic_write(path, payload["content"])
            db.execute("UPDATE memory_trash SET restored_at=? WHERE trash_id=?", (datetime.now().isoformat(),trash_id))
            return {"ok": True, "rel": item["rel"], "doc": _read_document(item["rel"])}
        row = payload["row"]
        if row["rel"] not in CORE_HUB_REL_SET:
            try:
                evidence, _ = _validated_knowledge(row["title"], payload["content"], row["category"], source=row["rel"])
                metadata = evidence.get("knowledge", evidence)
                ownership = auto_link_synapses(row["title"], payload["content"], metadata.get("sourceAgent"), metadata.get("channel"), json.loads(row["links"]))
                validate_synapse_hubs(ownership)
                payload["content"] = _append_parent_links(payload["content"], ownership["links"])
                row.update(links=json.dumps(ownership["links"], ensure_ascii=False), body=payload["content"])
            except ValueError as exc:
                raise HTTPException(400, str(exc))
        if db.execute("SELECT 1 FROM docs WHERE rel=?", (row["rel"],)).fetchone():
            raise HTTPException(409, "A document already occupies this path")
        path = safe_path(LOCAL_VAULT_DIR, row["rel"])
        if path.exists() and revision(path.read_text(encoding="utf-8")) != revision(payload["content"]):
            raise HTTPException(409, "Original source changed while in trash")
        if not path.exists() and payload["hadFile"]:
            atomic_write(path, payload["content"])
        columns = list(row)
        db.execute(f"INSERT INTO docs({','.join(columns)}) VALUES({','.join('?' for _ in columns)})", [row[c] for c in columns])
        db.execute("UPDATE memory_trash SET restored_at=? WHERE trash_id=?", (datetime.now().isoformat(), trash_id))
    return {"ok": True, "rel": row["rel"], "doc": _read_document(row["rel"])}


@memory_router.get("/sessions/search")
def search_memory_sessions(q: str = Query(""), limit: int = Query(10)):
    return {"results": hermes_store.session_search(q, limit)}


@memory_router.get("/skills")
def list_memory_skills():
    return {"skills": hermes_store.skill_list()}


@memory_router.get("/reviews")
def list_memory_reviews():
    with hermes_store.db() as db:
        return {"reviews": [dict(r) for r in db.execute("SELECT * FROM reviews ORDER BY updated_at DESC LIMIT 50")]}


class BoundedMemoryOperation(BaseModel):
    target: str
    action: str
    text: str = ""
    old_text: str = ""
    expected_revision: str


@memory_router.get("/bounded")
def read_bounded_memory():
    return {target: hermes_store.bounded(target) for target in ("memory", "user")}


@memory_router.post("/bounded")
def mutate_bounded_memory(req: BoundedMemoryOperation):
    try:
        return hermes_store.memory(**req.model_dump())
    except MemoryConflict as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@memory_router.get("/skill")
def view_memory_skill(name: str = Query(...)):
    try:
        return hermes_store.skill_view(name)
    except FileNotFoundError:
        raise HTTPException(404, "Skill not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
