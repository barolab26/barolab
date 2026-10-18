"""Regression coverage for the four-layer memory safety and persistence contracts."""
import concurrent.futures
import json
import sqlite3
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from common.hermes_memory import HermesMemory, MemoryConflict, ENTRY_DELIMITER, revision, safe_path
from server import memory_graph as graph
from fastapi import HTTPException


class HermesMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = HermesMemory(Path(self.temp.name) / "memories")
        self.store.initialize()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_bounded_patch_overflow_preserves_exact_original(self):
        s = self.store
        s.memory("memory", "add", "First entry with  two spaces\nline")
        s.memory("memory", "add", "Second entry")
        old = s.bounded("memory")
        with self.assertRaises(ValueError):
            s.memory("memory", "add", "x" * 2200)
        self.assertEqual(old, s.bounded("memory"))
        s.memory("memory", "patch", "updated", "two spaces", old["revision"])
        self.assertEqual(s.bounded("memory")["content"], "First entry with  updated\nline" + ENTRY_DELIMITER + "Second entry")
        with self.assertRaises(MemoryConflict):
            s.memory("memory", "patch", "stale", "updated", old["revision"])
        s.memory("memory", "remove", old_text="Second")
        self.assertNotIn("Second", s.bounded("memory")["content"])

    def test_user_limit_and_ambiguous_span_preserve(self):
        self.store.memory("user", "add", "x" * 1375)
        before = self.store.bounded("user")
        with self.assertRaises(ValueError):
            self.store.memory("user", "add", "y")
        with self.assertRaises(MemoryConflict):
            self.store.memory("user", "patch", "z", "x")
        self.assertEqual(before, self.store.bounded("user"))

    def test_explicit_consolidation_capacity_and_failure_preservation(self):
        self.store.memory("user", "add", "long " + "x" * 1360)
        before = self.store.bounded("user")
        def failure(payload):
            raise RuntimeError("model unavailable")
        with self.assertRaises(RuntimeError):
            self.store.memory("user", "add", content="new confirmed preference", consolidator=failure)
        self.assertEqual(before, self.store.bounded("user"))
        self.store.memory("user", "add", content="new confirmed preference", consolidator=lambda p:[{"old_text":"x"*1360,"new_text":"compact confirmed statement"}])
        self.assertIn("new confirmed preference", self.store.bounded("user")["content"])
        self.assertLessEqual(self.store.bounded("user")["chars"],1375)

    def test_catalog_only_names_descriptions_and_new_skill_next_session(self):
        self.store.skill_manage("create","first",content='---\ndescription: first topic\n---\n# First\nsecret body')
        frozen = self.store.frozen_session_context("session")
        self.assertIn("first: first topic", frozen)
        self.assertNotIn("secret body", frozen)
        self.assertNotIn('"revision"', frozen)
        self.store.skill_manage("create","second",content='---\ndescription: second topic\n---\n# Second\nnew body')
        self.assertEqual(self.store.skill_context("second",session_id="session"), "")
        self.assertIn("new body",self.store.skill_context("second",session_id="next"))

    def test_audit_failure_rolls_back_file_mutation(self):
        self.store.memory("memory", "add", "keep original")
        with patch.object(self.store, "_audit", side_effect=OSError("database unavailable")):
            with self.assertRaises(OSError):
                self.store.memory("memory", "patch", "changed", "original")
        self.assertEqual(self.store.bounded("memory")["content"], "keep original")

    def test_session_and_skill_frozen_across_scopes_and_instances(self):
        s = self.store
        s.memory("memory", "add", "old")
        s.skill_manage("create", "repair", content="# Repair\nrepair old")
        frozen = s.frozen_session_context("run-1", "a")
        skill = s.skill_context("repair", session_id="run-1")
        s.memory("memory", "patch", "new", "old")
        s.skill_manage("patch", "repair", old_text="old", new_text="new")
        self.assertEqual(frozen, s.frozen_session_context("run-1", "b"))
        self.assertEqual(skill, s.skill_context("repair", session_id="run-1"))
        other = HermesMemory(s.root)
        self.assertEqual(frozen, other.frozen_session_context("run-1"))
        self.assertIn("new", other.frozen_session_context("run-2"))

    def test_fts_korean_quotes_and_idempotency(self):
        s = self.store
        s.record_episode("e", "repair", "대시보드 연결 확인 API 오류", {"status": 200}, messages=[{"role": "assistant", "content": "실제 원문 확인"}])
        self.assertFalse(s.record_episode("e", "repair", "duplicate")["inserted"])
        self.assertEqual(s.session_search('"대시보드" 연결')[0]["event_id"], "e")
        self.assertEqual(s.session_search("원문")[0]["event_id"], "e")
        self.assertEqual(s.session_search(""), [])
        self.assertEqual(s.session_search('" OR DROP TABLE episodes --'), [])
        self.assertEqual(len(s.session_search("대시보드")), 1)

    def test_path_escape_and_skill_patch_conflicts(self):
        for rel in ("../secret", "C:/secret", "/etc/passwd", "folder/../../secret", "a:stream"):
            with self.assertRaises(ValueError):
                safe_path(self.store.root, rel)
        self.store.skill_manage("create", "test", content="# Test\nunchanged old")
        with self.assertRaises(MemoryConflict):
            self.store.skill_manage("patch", "test", old_text="old", new_text="new", expected_revision="stale")
        self.assertIn("old", self.store.skill_view("test")["content"])

    def test_concurrent_adds_do_not_lose_entries(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda i: self.store.memory("memory", "add", f"entry {i}"), range(20)))
        self.assertEqual(len(self.store.bounded("memory")["content"].split(ENTRY_DELIMITER)), 20)

    def _review(self, event_id, reviewer):
        self.store.record_episode(event_id, "repair", "Verified API repair", {"response": 200})
        self.store.enqueue_review(event_id, reviewer)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            with self.store.db() as db:
                row = db.execute("SELECT status FROM reviews WHERE event_id=?", (event_id,)).fetchone()
                queue = db.execute("SELECT state FROM review_queue WHERE event_id=?", (event_id,)).fetchone()
            if queue and queue[0] in ("done", "failed"):
                return row[0]
            time.sleep(.01)
        self.fail("Review did not finish")

    def test_reviewer_rejects_unknown_tool_without_writes(self):
        state = self._review("bad", lambda p: {"shell": "do something", "memory": []})
        self.assertEqual(state, "failed")
        self.assertEqual(self.store.bounded("memory")["content"], "")

    def test_review_all_operations_validated_before_writing(self):
        def reviewer(p):
            return {"memory": [{"target": "memory", "action": "add", "text": "valid", "expected_revision": p["memory"]["revision"]}],
                    "skills": [{"action": "patch", "name": "missing", "old_text": "old", "new_text": "new", "expected_revision": "wrong"}]}
        self.assertEqual(self._review("invalid-later", reviewer), "conflict")
        self.assertEqual(self.store.bounded("memory")["content"], "")

    def test_review_success_durable_idempotent_and_audited(self):
        def reviewer(p):
            return {"memory": [{"target": "memory", "action": "add", "text": "evidenced lesson", "expected_revision": p["memory"]["revision"]}]}
        self.assertEqual(self._review("good", reviewer), "applied")
        self.assertFalse(self.store.enqueue_review("good", reviewer)["queued"])
        with self.store.db() as db:
            audit = db.execute("SELECT * FROM audit WHERE source='review:good'").fetchone()
        self.assertEqual(audit["after_hash"], revision("evidenced lesson"))
        self.assertIn("response", audit["evidence"])


class GraphMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [patch.object(graph, "DATA_DIR", root), patch.object(graph, "LOCAL_VAULT_DIR", root / "vault"), patch.object(graph, "DB_PATH", root / "graph.sqlite3"), patch.object(graph, "hermes_store", HermesMemory(root / "memories"))]
        for item in self.patches:
            item.start()
        graph.reset_to_clean_slate()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_all_filter_includes_real_orphans(self):
        docs = [{"rel": "notes/a.md", "title": "A", "links": []}, {"rel": "notes/b.md", "title": "B", "links": ["notes/a"]}, {"rel": "notes/c.md", "title": "C", "links": []}]
        actual = graph.build_graph_2d(docs, [])
        self.assertEqual(len(actual["nodes"]), 3)
        self.assertEqual(actual["edges"], [[1, 0]])
        self.assertEqual(actual["stats"]["isolated"], 1)

    def test_existing_wal_connection_does_not_block_graph_read(self):
        # Isolated fixture only: production journal modes must never be changed.
        other = sqlite3.connect(graph.DB_PATH)
        try:
            other.execute("PRAGMA journal_mode=WAL")
            other.execute("BEGIN")
            other.execute("SELECT * FROM docs").fetchone()
            self.assertGreater(len(graph.load_all_docs()), 0)
            with graph.connect_db() as db:
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            other.close()

    def test_patch_conflict_raw_content_and_protected_hub(self):
        rel = graph.CLEAN_SEED_HUBS[0]["rel"]
        doc = graph.get_memory_doc(rel)
        updated = doc["content"] + "\nverified new line\n"
        result = graph.patch_memory_doc(graph.PatchMemoryDoc(content=updated, expectedRevision=doc["revision"]), rel)
        self.assertEqual(Path(result["doc"]["sourcePath"]).read_text(encoding="utf8"), updated)
        with self.assertRaises(HTTPException) as conflict:
            graph.patch_memory_doc(graph.PatchMemoryDoc(content="stale", expectedRevision=doc["revision"]), rel)
        self.assertEqual(conflict.exception.status_code, 409)
        deleted = graph.delete_memory_doc(rel, result["doc"]["revision"])
        graph.sync_argo_vault_and_growth(True)
        with self.assertRaises(HTTPException):
            graph.get_memory_doc(rel)
        graph.restore_memory_doc(deleted["trashId"])
        self.assertEqual(graph.get_memory_doc(rel)["content"], updated)

    def test_trash_restore_no_sync_resurrection(self):
        item = graph.register_synapse_memory("temporary test", "Verified API response evidence", category="meeting")
        doc = graph.get_memory_doc(item["rel"])
        deleted = graph.delete_memory_doc(item["rel"], doc["revision"])
        self.assertTrue(Path(doc["sourcePath"]).exists())
        graph.sync_argo_vault_and_growth(True)
        with self.assertRaises(HTTPException):
            graph.get_memory_doc(item["rel"])
        self.assertEqual(graph.restore_memory_doc(deleted["trashId"])["doc"]["content"], doc["content"])

    def test_bounded_doc_overflow_preserves_and_paths_rejected(self):
        doc = graph.get_memory_doc("hermes/USER.md")
        with self.assertRaises(HTTPException) as exc:
            graph.patch_memory_doc(graph.PatchMemoryDoc(content="x"*1376, expectedRevision=doc["revision"]), "hermes/USER.md")
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(graph.get_memory_doc("hermes/USER.md")["content"], "")
        with self.assertRaises(HTTPException):
            graph.get_memory_doc("../secret.md")

    def test_procedural_skill_trash_restore_changes_actual_file(self):
        graph.hermes_store.skill_manage("create", "test-skill", content="# Test skill\nreal original")
        rel = "procedural/test-skill/SKILL.md"
        doc = graph.get_memory_doc(rel)
        path = Path(doc["sourcePath"])
        deleted = graph.delete_memory_doc(rel, doc["revision"])
        self.assertFalse(path.exists())
        self.assertNotIn(rel, [d["rel"] for d in graph.load_all_docs()])
        result = graph.restore_memory_doc(deleted["trashId"])
        self.assertEqual(path.read_text(encoding="utf8"), "# Test skill\nreal original")
        self.assertEqual(result["doc"]["revision"], doc["revision"])

    def test_explicit_skill_edges_and_audit_links_are_real(self):
        hub = graph.CLEAN_SEED_HUBS[0]["rel"].removesuffix(".md")
        graph.hermes_store.skill_manage("create","linked",content=f"# Linked\nSee [[{hub}]]")
        graph.hermes_store.record_episode("verified-repair","repair","actual verified repair",{"status":200})
        graph.hermes_store._audit("review:verified-repair","patch","skill:linked","before","after",{"status":200})
        docs = graph.load_all_docs()
        skill = graph.get_memory_doc("procedural/linked/SKILL.md")
        self.assertEqual(skill["parents"],[hub])
        self.assertTrue(skill["updated"])
        self.assertEqual(len(skill["backlinks"]),1)
        self.assertTrue(any(d["rel"].startswith("episodes/") and "procedural/linked/SKILL" in d["links"] for d in docs))


if __name__ == "__main__":
    unittest.main()
