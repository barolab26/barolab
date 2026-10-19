"""Project-scoped four-layer memory, inspired by NousResearch Hermes.

MEMORY/USER are bounded curated text; skills are progressively disclosed;
episodes are SQLite FTS5 searchable; review is asynchronous and tool-whitelisted.
No personal Codex memory paths are read or written by this module.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENTRY_DELIMITER = "\n§\n"
LIMITS = {"memory": 2200, "user": 1375}
_THREAD_LOCK = threading.RLock()


def _operational_source(summary="", source="", title="", source_path=""):
    """Operational records remain searchable logs, never permanent knowledge."""
    blocked = r"(?:ledger|circuit(?:[-_]breaker)?|model[-_]events?|scheduler|errors?|preparation|naver[-_]automation)"
    forbidden_file = (r"(?:ledger\.jsonl?|(?:freellm[-_])?circuit(?:[-_]breaker)?\.json|"
                      r"(?:.*[-_])?model[-_]events?\.jsonl?|scheduler\.log|(?:.*[-_])?errors?\.log|"
                      r"preparation\.json|naver[-_]automation\.json)")
    for value in (source, source_path):
        path = str(value or "").lower().replace("\\", "/").split("?", 1)[0].split("#", 1)[0]
        if re.fullmatch(forbidden_file, path.rsplit("/", 1)[-1]):
            return "operational_source"
    first_line = next((line for line in str(summary or "").splitlines() if line.strip()), "")
    for value in (title, first_line):
        heading = str(value or "").strip().lower().lstrip("# [")
        if re.match(blocked + r"(?:$|[:\]]|[ _-]+(?:status|completed|failed|event|log|state|상태|완료)(?:$|[\s:._-]))", heading):
            return "operational_title"
        if re.match(r"(?:pipeline[_ -]preparation|llm[_ -]call|chat[_ -]turn|예약\s*완료|스케줄러\s*상태|단순\s*실패)", heading):
            return "operational_status"
        if re.match(r"(?:provider\s+return|naver\s+preparation|naver\s+reservation|knowledgein\s+publ|cf\s+content\s+and\s+p|timeouterror|http\s+500|status\s*:\s*invalid)", heading):
            return "operational_status"
    return None


def memorization_decision(event_type, summary="", evidence=None, success=True, source="", *, title="", source_path=""):
    """Pure, fail-closed promotion gate. This does not govern session-log storage.

    Structured evidence must establish a reusable verified procedure, comparable
    measurement, or an explicit user decision. A label or generic success is not
    evidence. Metadata checks precede every allow path, including manual labels.
    """
    evidence = evidence if isinstance(evidence, dict) else {}
    reason = _operational_source(summary, source, title, source_path) or _operational_source(title=event_type)
    if reason:
        return {"allowed": False, "reason": reason, "kind": None}
    for key in ("source", "sourceRef", "sourcePath", "source_path", "path"):
        reason = _operational_source(source_path=evidence.get(key, ""))
        if reason:
            return {"allowed": False, "reason": reason, "kind": None}
    if _operational_source(title=evidence.get("title", "")):
        return {"allowed": False, "reason": "operational_title", "kind": None}
    if success is not True and success != 1:
        return {"allowed": False, "reason": "unsuccessful_episode", "kind": None}
    knowledge = evidence.get("knowledge", evidence)
    if not isinstance(knowledge, dict):
        return {"allowed": False, "reason": "structured_evidence_required", "kind": None}
    for key in ("source", "sourceRef", "sourcePath", "source_path", "path"):
        reason = _operational_source(source_path=knowledge.get(key, ""))
        if reason:
            return {"allowed": False, "reason": reason, "kind": None}
    if _operational_source(title=knowledge.get("title", "")):
        return {"allowed": False, "reason": "operational_title", "kind": None}
    kind = knowledge.get("kind") or {"growth_measured_increase": "measured_insight",
                                    "verified_skill": "verified_skill",
                                    "meeting_decision": "meeting_decision"}.get(str(event_type))
    snapshot = kind == "measured_snapshot" or knowledge.get("measurementType") == "measured_snapshot"
    if kind == "measured_snapshot":
        kind = "measured_insight"
    ref = knowledge.get("sourceRef")
    verification = knowledge.get("verification", {})
    if isinstance(verification, dict) and _operational_source(source_path=verification.get("evidence", "")):
        return {"allowed": False, "reason": "operational_source", "kind": None}
    verified = (isinstance(verification, dict) and verification.get("passed") is True
                and isinstance(verification.get("evidence"), str) and bool(verification["evidence"].strip()))
    allowed = False
    if kind == "verified_skill":
        steps = knowledge.get("steps")
        allowed = (knowledge.get("reusable") is True and verified and isinstance(ref, str) and bool(ref.strip())
                   and isinstance(knowledge.get("lesson"), str) and bool(knowledge["lesson"].strip())
                   and isinstance(steps, list) and bool(steps)
                   and all(isinstance(s, str) and bool(s.strip()) for s in steps))
    elif kind == "meeting_decision":
        decision, quote = knowledge.get("decisionText"), knowledge.get("userQuote")
        meeting_ref = str(ref or "").replace("\\", "/")
        archive = evidence.get("archive", knowledge.get("archive", ""))
        meeting_origin = (str(event_type) in ("meeting_decision", "chat_decision", "ceo_correction_conversation_ended")
                          and (bool(re.match(r"^(?:meetings/|(?:server/data/|data/)?chats/\.archive/)", meeting_ref))
                               or bool(re.fullmatch(r"_room-\d+\.json", str(archive)))
                               and (meeting_ref == archive or meeting_ref == evidence.get("journal"))))
        allowed = (meeting_origin and knowledge.get("userConfirmed") is True and isinstance(decision, str) and bool(decision.strip())
                   and isinstance(quote, str) and decision.strip() in quote
                   and isinstance(knowledge.get("sourceMessageId"), str) and bool(knowledge["sourceMessageId"].strip())
                   and isinstance(ref, str) and bool(ref.strip()))
        consensus = knowledge.get("consensus")
        if not allowed and meeting_origin and isinstance(decision, str) and decision.strip() and isinstance(consensus, list) and len(consensus) >= 2:
            valid_votes = [v for v in consensus if isinstance(v, dict) and v.get("agrees") is True
                           and isinstance(v.get("participantId"), str) and v["participantId"].strip()
                           and isinstance(v.get("sourceMessageId"), str) and v["sourceMessageId"].strip()
                           and isinstance(v.get("quote"), str) and decision.strip() in v["quote"]]
            allowed = (len(valid_votes) == len(consensus) and verified and isinstance(ref, str) and bool(ref.strip())
                       and len({v["participantId"] for v in valid_votes}) == len(consensus)
                       and len({v["sourceMessageId"] for v in valid_votes}) == len(consensus))
    elif kind == "measured_insight":
        def number(value):
            try:
                return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            except (OverflowError, ValueError):
                return False
        previous, current = evidence.get("previous"), evidence.get("current")
        if snapshot:
            period = knowledge.get("period", {})
            try:
                valid_period = (datetime.strptime(period["start"], "%Y-%m-%d").date()
                                <= datetime.strptime(period["end"], "%Y-%m-%d").date())
            except (KeyError, TypeError, ValueError):
                valid_period = False
            numerator, denominator, value = (knowledge.get(k) for k in ("numerator", "denominator", "value"))
            allowed = (verified and isinstance(ref, str) and bool(ref.strip()) and valid_period
                       and knowledge.get("sourceStatus") == "complete"
                       and isinstance(knowledge.get("domain"), str)
                       and bool(re.fullmatch(r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}", knowledge["domain"]))
                       and knowledge.get("metric") in ("rpm", "page_rpm", "impression_rpm")
                       and knowledge.get("numeratorMetric") == "revenue"
                       and knowledge.get("denominatorMetric") in ("pageviews", "impressions")
                       and (knowledge["metric"] != "page_rpm" or knowledge["denominatorMetric"] == "pageviews")
                       and (knowledge["metric"] != "impression_rpm" or knowledge["denominatorMetric"] == "impressions")
                       and bool(knowledge.get("currency")) and bool(knowledge.get("sourceTimezone"))
                       and isinstance(knowledge.get("analysis"), str) and bool(knowledge["analysis"].strip())
                       and number(numerator) and number(denominator) and number(value)
                       and numerator >= 0 and denominator > 0
                       and math.isclose(value, numerator / denominator * 1000, rel_tol=1e-6, abs_tol=1e-6))
        elif str(event_type) == "growth_measured_increase" and isinstance(previous, dict) and isinstance(current, dict):
            signature = ("currency", "source_timezone", "value_kind", "revenue_scope")
            try:
                dates = [datetime.strptime(period[key], "%Y-%m-%d").date()
                         for period in (previous, current) for key in ("start", "end")]
                valid_periods = (dates[0] <= dates[1] < dates[2] <= dates[3]
                                 and dates[1] - dates[0] == dates[3] - dates[2])
            except (KeyError, TypeError, ValueError):
                valid_periods = False
            allowed = (previous.get("status") == current.get("status") == "complete"
                       and number(previous.get("total")) and number(current.get("total"))
                       and current["total"] > previous["total"] >= 0
                       and all(previous.get(k) == current.get(k) for k in signature)
                       and bool(previous.get("source_timezone")) and bool(previous.get("value_kind"))
                       and valid_periods
                       and evidence.get("service") in ("adsense", "ga4", "naver_blog")
                       and isinstance(evidence.get("metric"), str) and bool(evidence["metric"].strip())
                       and bool(evidence.get("siteId")))
        else:
            allowed = (verified and knowledge.get("comparable") is True and bool(knowledge.get("metric"))
                       and isinstance(ref, str) and bool(ref.strip())
                       and number(knowledge.get("baseline")) and number(knowledge.get("current")))
    return {"allowed": bool(allowed), "reason": "verified_knowledge" if allowed else "structured_knowledge_evidence_required",
            "kind": kind if allowed else None}


def should_memorize(event_type, summary="", evidence=None, success=True, source="", *, title="", source_path=""):
    return memorization_decision(event_type, summary, evidence, success, source, title=title, source_path=source_path)["allowed"]


def _review_skill_document(name, content, episode):
    """Resolve evidence-based parents before a reviewer can write any skill."""
    from server.memory_graph import auto_link_synapses, validate_synapse_hubs
    evidence = episode["evidence"]
    knowledge = evidence.get("knowledge", evidence)
    relation = auto_link_synapses(name, content, source_agent=knowledge.get("sourceAgent"),
                                 channel=knowledge.get("channel"))
    links = relation.get("links", [])
    if not relation.get("crew") or not relation.get("channel"):
        raise ValueError("Reviewed skill needs a verified owner and channel")
    validate_synapse_hubs(relation)
    # Model-supplied metadata is never its own evidence. Preserve only the
    # episode's already-validated provenance and normalize parent references.
    content = re.sub(r"<!--\s*barolab-knowledge\s+.*?\s*-->", "", content, flags=re.S).rstrip()
    current_links = set(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content))
    missing = [str(link).removesuffix(".md") for link in links
               if str(link).removesuffix(".md") not in current_links]
    if missing:
        content += "\n\n" + " ".join("[[" + link + "]]" for link in missing)
    provenance = {**evidence, "eventType": episode["event_type"], "sourceEventId": episode["event_id"]}
    content += "\n\n<!-- barolab-knowledge " + json.dumps(provenance, ensure_ascii=False, separators=(",", ":")) + " -->\n"
    if len(content) > 60000:
        raise ValueError("Reviewed skill including provenance exceeds the size limit")
    return content


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    """Reject absolute paths, traversal, Windows ADS and symlink escapes."""
    value = str(relative).replace("\\", "/")
    if not value or value.startswith("/") or ":" in value or any(p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("Invalid project-relative path")
    root = root.resolve()
    result = (root / value).resolve()
    if not result.is_relative_to(root):
        raise ValueError("Path escapes the project memory directory")
    return result


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".memory-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def file_lock(path: Path):
    """Serialize writers across threads and processes on Windows and POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _THREAD_LOCK, open(path, "a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class MemoryConflict(ValueError):
    pass


class HermesMemory:
    def __init__(self, root: Path | str | None = None, skills_root: Path | str | None = None, project_skills_root: Path | str | None = None):
        self.root = Path(root) if root is not None else Path(os.environ.get("BAROLAB_MEMORY_DIR", str(PROJECT_ROOT / "data" / "memories")))
        self.skills_root = Path(skills_root) if skills_root is not None else Path(os.environ.get("BAROLAB_SKILLS_DIR", str(self.root.parent / "skills")))
        # Only the approved repository root joins the production catalog. Temp
        # stores remain isolated unless a test explicitly supplies another root.
        self.project_skills_root = (Path(project_skills_root) if project_skills_root is not None else
                                   PROJECT_ROOT / "skills" if root is None and skills_root is None else None)
        self.db_path = self.root / "state.sqlite3"
        self.lock_path = self.root / ".memory.lock"
        self._initialized = False
        self._snapshots = {}
        self._pending = set()
        self._worker = None
        self._callbacks = {}
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._default_reviewer = None

    def initialize(self):
        if self._initialized:
            return
        with file_lock(self.lock_path):
            self.root.mkdir(parents=True, exist_ok=True)
            self.skills_root.mkdir(parents=True, exist_ok=True)
            for name in ("MEMORY.md", "USER.md"):
                path = self.root / name
                if not path.exists():
                    atomic_write(path, "")
            with closing(sqlite3.connect(self.db_path, timeout=15)) as db:
                # DELETE journal works across the mapped SMB project drive; WAL does not.
                db.execute("PRAGMA journal_mode=DELETE")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS skill_snapshots (
                        session_id TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL,
                        PRIMARY KEY(session_id,name));
                    CREATE TABLE IF NOT EXISTS session_catalog (
                        session_id TEXT PRIMARY KEY, catalog TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS episodes (
                        event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, event_type TEXT NOT NULL,
                        summary TEXT NOT NULL, evidence TEXT NOT NULL, success INTEGER NOT NULL,
                        messages TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                        event_id UNINDEXED, session_id UNINDEXED, summary, messages, tokenize='unicode61');
                    CREATE TABLE IF NOT EXISTS reviews (
                        event_id TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT NOT NULL,
                        updated_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS audit (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
                        action TEXT NOT NULL, target TEXT NOT NULL, before_hash TEXT NOT NULL,
                        after_hash TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS review_queue (
                        event_id TEXT PRIMARY KEY, state TEXT NOT NULL, lease_until REAL NOT NULL DEFAULT 0,
                        attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
                """)
                # Migrate by copying source episodes. Existing episode_fts is retained,
                # never dropped, so upgrades preserve both source data and old indexes.
                db.execute("INSERT INTO sessions_fts(event_id,session_id,summary,messages) SELECT e.event_id,e.session_id,e.summary,e.messages FROM episodes e WHERE NOT EXISTS(SELECT 1 FROM sessions_fts f WHERE f.event_id=e.event_id)")
                db.commit()
            self._initialized = True

    @contextmanager
    def db(self):
        self.initialize()
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def bounded(self, target: str) -> dict:
        if target not in LIMITS:
            raise ValueError("target must be memory or user")
        self.initialize()
        text = (self.root / ("MEMORY.md" if target == "memory" else "USER.md")).read_text(encoding="utf-8")
        return {"target": target, "content": text, "chars": len(text), "limit": LIMITS[target], "revision": revision(text)}

    @staticmethod
    def _memory_change(raw, target, action, text="", old_text="", enforce_limit=True):
        # Preserve untouched entries and whitespace exactly; no automatic clipping.
        entries = raw.split(ENTRY_DELIMITER) if raw else []
        if action == "add":
            if not isinstance(text, str) or not text.strip() or ENTRY_DELIMITER in text:
                raise ValueError("add requires one non-empty entry")
            if text in entries:
                return raw
            entries.append(text)
        elif action in ("patch", "remove"):
            if not old_text or ENTRY_DELIMITER in old_text:
                raise ValueError("old_text must select one entry")
            matches = [i for i, entry in enumerate(entries) if old_text in entry]
            if len(matches) != 1:
                raise MemoryConflict("old_text must match exactly one entry")
            i = matches[0]
            if action == "remove":
                entries.pop(i)
            else:
                if entries[i].count(old_text) != 1 or ENTRY_DELIMITER in text:
                    raise MemoryConflict("patch requires a unique span within one entry")
                entries[i] = entries[i].replace(old_text, text, 1)
        else:
            raise ValueError("Only add, patch and remove are allowed")
        result = ENTRY_DELIMITER.join(entries)
        if len(result) > LIMITS[target]:
            # Lossless consolidation only: exact duplicate entries carry no new fact.
            result = ENTRY_DELIMITER.join(dict.fromkeys(entries))
        if enforce_limit and len(result) > LIMITS[target]:
            raise ValueError(f"{target} exceeds {LIMITS[target]} characters; nothing was written")
        return result

    def _audit(self, source, action, target, before, after, evidence=None):
        with self.db() as db:
            db.execute("INSERT INTO audit(source,action,target,before_hash,after_hash,evidence,created_at) VALUES(?,?,?,?,?,?,?)",
                       (source, action, target, revision(before), revision(after), json.dumps(evidence or {}, ensure_ascii=False), utc_now()))

    def memory(self, target: str, action: str, text: str = "", old_text: str = "", expected_revision: str | None = None, source="manual", evidence=None, content=None, consolidator=None):
        if content is not None:
            if text and text != content:
                raise ValueError("Specify only one of text/content")
            text = content
        self.initialize()
        with file_lock(self.lock_path):
            current = self.bounded(target)
            if expected_revision is not None and current["revision"] != expected_revision:
                raise MemoryConflict("Memory changed; reload before editing")
            updated = self._memory_change(current["content"], target, action, text, old_text, enforce_limit=False)
            if len(updated) > LIMITS[target]:
                if consolidator is None:
                    raise ValueError(f"{target} exceeds {LIMITS[target]} characters; provide a bounded patch or consolidation callback; original preserved")
                operations = consolidator({**current, "candidate": updated})
                if not isinstance(operations, list) or not 1 <= len(operations) <= 8:
                    raise ValueError("Consolidation must propose 1..8 exact partial patches")
                for op in operations:
                    if not isinstance(op, dict) or set(op) != {"old_text", "new_text"}:
                        raise ValueError("Consolidation allows only old_text/new_text patches")
                    updated = self._memory_change(updated, target, "patch", op["new_text"], op["old_text"], enforce_limit=False)
                if len(updated) > LIMITS[target]:
                    raise ValueError("Consolidation still exceeds capacity; original preserved")
            path = self.root / ("MEMORY.md" if target == "memory" else "USER.md")
            atomic_write(path, updated)
            try:
                self._audit(source, action, target, current["content"], updated, evidence)
            except Exception:
                atomic_write(path, current["content"])
                raise
        return {"ok": True, **self.bounded(target)}

    def skill_list(self):
        self.initialize()
        result = []
        paths = {}
        # The explicit repository procedure wins a name collision; one body is
        # indexed, viewed, frozen and edited, never a stale duplicate or shim.
        for root in (self.skills_root, self.project_skills_root):
            if root is None:
                continue
            for candidate in sorted(root.glob("*/SKILL.md")):
                path = safe_path(root, candidate.relative_to(root).as_posix())
                if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", candidate.parent.name):
                    paths[candidate.parent.name] = path
        for name, path in sorted(paths.items()):
            raw = path.read_text(encoding="utf-8")
            title = re.search(r"^#\s+(.+)$", raw, re.M)
            description = re.search(r"^description:\s*(.+)$", raw, re.M)
            result.append({"name": name, "title": title.group(1) if title else name,
                           "description": description.group(1).strip('"\'') if description else next((x.strip() for x in raw.splitlines() if x.strip() and not x.startswith(("#", "---", "name:"))), "")[:240],
                           "revision": revision(raw)})
        return result

    def _skill_path(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", name):
            raise ValueError("Invalid skill name")
        if self.project_skills_root is not None:
            candidate = safe_path(self.project_skills_root, f"{name}/SKILL.md")
            if candidate.is_file() or candidate.parent.is_dir():
                return candidate
        return safe_path(self.skills_root, f"{name}/SKILL.md")

    def skill_view(self, name):
        path = self._skill_path(name)
        if not path.is_file():
            raise FileNotFoundError(name)
        content = path.read_text(encoding="utf-8")
        return {"name": name, "content": content, "revision": revision(content)}

    def skill_manage(self, action, name, content="", old_text="", new_text="", expected_revision=None, source="manual", evidence=None):
        self.initialize()
        path = self._skill_path(name)
        with file_lock(self.lock_path):
            exists = path.exists()
            old = path.read_text(encoding="utf-8") if exists else ""
            if expected_revision is not None and revision(old) != expected_revision:
                raise MemoryConflict("Skill changed; reload before editing")
            if action == "create":
                if exists:
                    raise MemoryConflict("Skill already exists")
                updated = content
            elif action == "patch":
                if not exists or not old_text or old.count(old_text) != 1:
                    raise MemoryConflict("Skill patch requires one exact unique span")
                updated = old.replace(old_text, new_text, 1)
            else:
                raise ValueError("Only skill create and patch are allowed")
            if not updated.strip() or len(updated) > 60000:
                raise ValueError("Skill must contain 1..60000 characters")
            atomic_write(path, updated)
            try:
                self._audit(source, action, f"skill:{name}", old, updated, evidence)
            except Exception:
                if exists:
                    atomic_write(path, old)
                else:
                    path.unlink(missing_ok=True)
                raise
        return {"ok": True, **self.skill_view(name)}

    def frozen_session_context(self, session_id: str, agent_scope="common"):
        if not session_id or len(session_id) > 240:
            raise ValueError("A bounded non-empty session_id is required")
        key = session_id
        if key in self._snapshots:
            return self._snapshots[key]
        with self.db() as db:
            row = db.execute("SELECT snapshot FROM sessions WHERE session_id=?", (key,)).fetchone()
            if row:
                value = row[0]
            else:
                # The serialized snapshot remains immutable for this session even after writes.
                with file_lock(self.lock_path):
                    catalog = self.skill_list()
                    index = "\n".join(f"{s['name']}: {' '.join(s['description'].split())}" for s in catalog)
                    value = "<project-memory>\n" + self.bounded("memory")["content"] + "\n</project-memory>\n<user-profile>\n" + self.bounded("user")["content"] + "\n</user-profile>\n<available-skills>\n" + index + "\n</available-skills>"
                    db.execute("INSERT OR IGNORE INTO session_catalog VALUES(?,?)", (key,json.dumps(catalog,ensure_ascii=False)))
                    for skill in catalog:
                        db.execute("INSERT OR IGNORE INTO skill_snapshots VALUES(?,?,?)", (key,skill["name"],self.skill_view(skill["name"])["content"]))
                db.execute("INSERT OR IGNORE INTO sessions VALUES(?,?,?)", (key, value, utc_now()))
                value = db.execute("SELECT snapshot FROM sessions WHERE session_id=?", (key,)).fetchone()[0]
        if len(self._snapshots) >= 512:
            self._snapshots.pop(next(iter(self._snapshots)))
        self._snapshots[key] = value
        return value

    def skill_context(self, query: str, max_skills=2, session_id=""):
        terms = set(re.findall(r"[\w-]+", query.lower()))
        ranked = []
        if session_id:
            snapshot = self.frozen_session_context(session_id)
            with self.db() as db:
                row = db.execute("SELECT catalog FROM session_catalog WHERE session_id=?", (session_id,)).fetchone()
                if row:
                    skills = json.loads(row[0])
                else:
                    # Compatibility with earlier persisted JSON-index snapshots.
                    old_index = snapshot.split("<available-skills>\n", 1)[1].split("\n</available-skills>", 1)[0]
                    skills = json.loads(old_index) if old_index.startswith("[") else []
                    db.execute("INSERT OR IGNORE INTO session_catalog VALUES(?,?)", (session_id,json.dumps(skills,ensure_ascii=False)))
        else:
            skills = self.skill_list()
        for skill in skills:
            hay = f"{skill['name']} {skill['title']} {skill['description']}".lower()
            score = sum(1 for t in terms if len(t) > 1 and t in hay)
            if skill["name"].lower() in terms:
                score += 10000  # Explicitly requested procedure precedes fuzzy topics.
            if score:
                ranked.append((score, skill["name"]))
        selected = []
        for _, name in sorted(ranked, reverse=True)[:max(0, min(max_skills, 4))]:
            if session_id:
                with self.db() as db:
                    saved = db.execute("SELECT content FROM skill_snapshots WHERE session_id=? AND name=?", (session_id,name)).fetchone()
                    if saved:
                        content = saved[0]
                    else:
                        content = self.skill_view(name)["content"]
                        db.execute("INSERT OR IGNORE INTO skill_snapshots VALUES(?,?,?)", (session_id,name,content))
            else:
                content = self.skill_view(name)["content"]
            selected.append(f"<skill name='{name}'>\n{content}\n</skill>")
        return "\n".join(selected)

    def record_episode(self, event_id, event_type, summary, evidence=None, success=True, session_id="", messages=None):
        if not event_id or not summary or len(event_id) > 240:
            raise ValueError("event_id and summary are required")
        evidence_json = json.dumps(evidence or {}, ensure_ascii=False)
        messages_json = json.dumps(messages or [], ensure_ascii=False)
        with self.db() as db:
            cursor = db.execute("INSERT OR IGNORE INTO episodes VALUES(?,?,?,?,?,?,?,?)", (event_id, session_id, event_type, summary, evidence_json, int(success), messages_json, utc_now()))
            inserted = cursor.rowcount == 1
            if inserted:
                db.execute("INSERT INTO sessions_fts VALUES(?,?,?,?)", (event_id, session_id, summary, messages_json))
        return {"ok": True, "event_id": event_id, "inserted": inserted}

    def session_search(self, query, limit=10):
        terms = re.findall(r"\w+", query, flags=re.UNICODE)
        if not terms:
            return []
        safe_query = " AND ".join('"' + term.replace('"', '""') + '"' for term in terms[:20])
        with self.db() as db:
            rows = db.execute("SELECT e.*,bm25(sessions_fts) AS rank FROM sessions_fts JOIN episodes e ON e.event_id=sessions_fts.event_id WHERE sessions_fts MATCH ? ORDER BY rank LIMIT ?", (safe_query, max(1, min(int(limit), 50)))).fetchall()
        return [{**dict(row), "evidence": json.loads(row["evidence"]), "messages": json.loads(row["messages"]), "success": bool(row["success"])} for row in rows]

    def _review_status(self, event_id, status, detail):
        with self.db() as db:
            db.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?)", (event_id, status, json.dumps(detail, ensure_ascii=False), utc_now()))

    def _run_review(self, event_id, reviewer):
        try:
            with self.db() as db:
                row = db.execute("SELECT * FROM episodes WHERE event_id=?", (event_id,)).fetchone()
            episode = dict(row)
            episode["evidence"] = json.loads(episode["evidence"])
            episode["messages"] = json.loads(episode["messages"])
            decision = memorization_decision(episode["event_type"], episode["summary"], episode["evidence"], episode["success"], source=event_id)
            if not decision["allowed"]:
                self._review_status(event_id, "skipped", decision)
                return
            self._review_status(event_id, "running", {})
            payload = {"episode": episode, "memory": self.bounded("memory"), "user": self.bounded("user"), "skills": self.skill_list()}
            selected_context = self.skill_context(episode["summary"], max_skills=2)
            payload["skill_details"] = [self.skill_view(name) for name in re.findall(r"<skill name='([^']+)'>", selected_context)]
            plan = reviewer(payload)
            if not isinstance(plan, dict) or set(plan) - {"memory", "skills", "reason"}:
                raise ValueError("Reviewer must return only a declared memory/skills plan")
            memory_ops, skill_ops = plan.get("memory", []), plan.get("skills", [])
            if not isinstance(memory_ops, list) or not isinstance(skill_ops, list) or len(memory_ops) + len(skill_ops) > 8:
                raise ValueError("Invalid or oversized review plan")
            if skill_ops and decision["kind"] != "verified_skill":
                raise ValueError("Procedural skill promotion needs verified reusable procedure evidence")
            # Validate the entire plan before any operation; all targets use a snapshot revision.
            for op in memory_ops:
                if not isinstance(op, dict) or set(op) - {"target", "action", "text", "content", "old_text", "expected_revision"}:
                    raise ValueError("Invalid memory operation fields")
                target = op.get("target")
                if _operational_source(op.get("text", op.get("content", ""))):
                    raise ValueError("Operational status cannot become permanent memory")
                if target not in LIMITS or op.get("action") not in ("add", "patch"):
                    raise ValueError("Background review cannot remove memory")
                if op.get("expected_revision") != payload[target]["revision"]:
                    raise MemoryConflict("Review must cite the observed memory revision")
                self._memory_change(payload[target]["content"], target, op["action"], op.get("text", op.get("content", "")), op.get("old_text", ""))
            for op in skill_ops:
                if not isinstance(op, dict) or set(op) - {"action", "name", "content", "old_text", "new_text", "expected_revision"} or op.get("action") not in ("create", "patch"):
                    raise ValueError("Invalid skill operation")
                self._skill_path(op.get("name", ""))
                if _operational_source(op.get("content", op.get("new_text", "")), title=op.get("name", "")):
                    raise ValueError("Operational status cannot become a procedural skill")
                if op["action"] == "patch" and not op.get("expected_revision"):
                    raise MemoryConflict("Review skill patch needs a revision")
            applied = []
            # All operations are prepared under the same lock, then atomically replaced.
            # Rollback restores every original if a later file/database operation fails.
            with file_lock(self.lock_path):
                changes = {}
                def stage(path, original, updated, action, target):
                    changes[path] = {"old": original, "new": updated, "exists": path.exists(), "action": action, "target": target}
                for op in memory_ops:
                    target = op["target"]
                    path = self.root / ("MEMORY.md" if target == "memory" else "USER.md")
                    original = path.read_text(encoding="utf-8")
                    if revision(original) != op["expected_revision"]:
                        raise MemoryConflict("Memory changed after review snapshot")
                    current = changes[path]["new"] if path in changes else original
                    updated = self._memory_change(current, target, op["action"], op.get("text", op.get("content", "")), op.get("old_text", ""))
                    stage(path, original, updated, op["action"], target)
                for op in skill_ops:
                    path = self._skill_path(op["name"])
                    original = path.read_text(encoding="utf-8") if path.exists() else ""
                    current = changes[path]["new"] if path in changes else original
                    if op["action"] == "create":
                        if path.exists() or path in changes:
                            raise MemoryConflict("Skill already exists")
                        updated = op.get("content", "")
                    else:
                        if revision(original) != op["expected_revision"] or not op.get("old_text") or current.count(op["old_text"]) != 1:
                            raise MemoryConflict("Skill patch no longer matches")
                        if op["old_text"].strip() == original.strip():
                            raise ValueError("Background review must patch a part of the skill, not rewrite the entire file")
                        updated = current.replace(op["old_text"], op.get("new_text", ""), 1)
                    if not updated.strip() or len(updated) > 60000:
                        raise ValueError("Invalid skill content size")
                    updated = _review_skill_document(op["name"], updated, episode)
                    stage(path, original, updated, op["action"], "skill:" + op["name"])
                written = []
                try:
                    with self.db() as db:
                        for path, change in changes.items():
                            if change["old"] == change["new"]:
                                continue
                            atomic_write(path, change["new"])
                            written.append(path)
                            db.execute("INSERT INTO audit(source,action,target,before_hash,after_hash,evidence,created_at) VALUES(?,?,?,?,?,?,?)", ("review:"+event_id, change["action"], change["target"], revision(change["old"]), revision(change["new"]), json.dumps(episode["evidence"],ensure_ascii=False), utc_now()))
                            applied.append(change["target"])
                except Exception:
                    for path in reversed(written):
                        if changes[path]["exists"]:
                            atomic_write(path, changes[path]["old"])
                        else:
                            path.unlink(missing_ok=True)
                    raise
            self._review_status(event_id, "applied" if applied else "skipped", {"operations": len(applied), "reason": plan.get("reason", "")})
        except Exception as exc:
            self._review_status(event_id, "conflict" if isinstance(exc, MemoryConflict) else "failed", {"error": str(exc), "type": type(exc).__name__})
        finally:
            with _THREAD_LOCK:
                self._pending.discard(event_id)

    def _review_loop(self):
        while not self._closed.is_set():
            self._wake.clear()
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                item = db.execute("SELECT event_id FROM review_queue WHERE state='queued' OR (state='running' AND lease_until<?) ORDER BY updated_at LIMIT 1", (time.time(),)).fetchone()
                if item:
                    event_id = item["event_id"]
                    db.execute("UPDATE review_queue SET state='running',lease_until=?,attempts=attempts+1,updated_at=? WHERE event_id=?", (time.time()+1800,utc_now(),event_id))
            if not item:
                self._wake.wait(timeout=60)
                continue
            try:
                callback = self._callbacks.pop(event_id, None) or self._default_reviewer
                if callback is None:
                    from common.llm_client import _memory_review
                    callback = _memory_review
                self._run_review(event_id, callback)
            except Exception as exc:
                self._review_status(event_id, "failed", {"error": str(exc), "type": type(exc).__name__})
            with self.db() as db:
                status = db.execute("SELECT status FROM reviews WHERE event_id=?", (event_id,)).fetchone()
                state = "failed" if status and status[0] == "failed" else "done"
                db.execute("UPDATE review_queue SET state=?,lease_until=0,updated_at=? WHERE event_id=?", (state,utc_now(),event_id))

    def resume_reviews(self):
        # A daemon cannot hold CLI shutdown hostage. Queued/running events survive
        # in SQLite and are reclaimed after their lease on the next worker start.
        with _THREAD_LOCK:
            if self._closed.is_set():
                return
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._review_loop, name="memory-review", daemon=True)
                self._worker.start()
            self._wake.set()

    def enqueue_review(self, event_id, reviewer=None):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            episode = db.execute("SELECT * FROM episodes WHERE event_id=?", (event_id,)).fetchone()
            if not episode:
                raise ValueError("Unknown episode")
            decision = memorization_decision(episode["event_type"], episode["summary"], json.loads(episode["evidence"]), episode["success"], source=event_id)
            if not decision["allowed"]:
                db.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?)", (event_id, "skipped", json.dumps(decision), utc_now()))
                return {"queued": False, **decision}
            prior = db.execute("SELECT state,attempts FROM review_queue WHERE event_id=?", (event_id,)).fetchone()
            retry = prior and prior["state"] == "failed" and prior["attempts"] < 3
            if prior and not retry:
                return {"queued": False, "reason": "already_reviewed_or_pending"}
            if db.execute("SELECT COUNT(*) FROM review_queue WHERE state IN ('queued','running')").fetchone()[0] >= 32:
                return {"queued": False, "reason": "queue_full"}
            if retry:
                db.execute("UPDATE review_queue SET state='queued',lease_until=0,updated_at=? WHERE event_id=?", (utc_now(),event_id))
            else:
                db.execute("INSERT INTO review_queue(event_id,state,updated_at) VALUES(?, 'queued', ?)", (event_id,utc_now()))
        if reviewer:
            self._callbacks[event_id] = reviewer
        self._review_status(event_id, "queued", {})
        self.resume_reviews()
        return {"queued": True, "event_id": event_id}

    def set_default_reviewer(self, reviewer):
        self._default_reviewer = reviewer
        self.resume_reviews()

    def close(self):
        self._closed.set()
        self._wake.set()
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout=2)


_store = HermesMemory()


def frozen_session_context(session_id: str, agent_scope: str = "common") -> str:
    _store.resume_reviews()
    return _store.frozen_session_context(session_id, agent_scope)


def skill_context(query: str, max_skills: int = 2, session_id: str = "") -> str:
    return _store.skill_context(query, max_skills, session_id)


def record_episode(event_id, event_type, summary, evidence=None, success=True, session_id="", messages=None):
    return _store.record_episode(event_id, event_type, summary, evidence, success, session_id, messages)


def enqueue_review(event_id, reviewer=None):
    return _store.enqueue_review(event_id, reviewer)


def spawn_background_review(event_id, reviewer=None):
    """Queue an already recorded episode; never invent or rewrite episode evidence."""
    return _store.enqueue_review(event_id, reviewer)


def set_default_reviewer(reviewer):
    _store.set_default_reviewer(reviewer)


def skill_view(name):
    return _store.skill_view(name)


def skill_manage(**kwargs):
    return _store.skill_manage(**kwargs)


def session_search(query, limit=10):
    return _store.session_search(query, limit)


def memory(action, target="memory", old_text="", content=None, text="", expected_revision=None, consolidator=None):
    return _store.memory(target, action, text, old_text, expected_revision, content=content, consolidator=consolidator)
