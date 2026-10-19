"""Graph admission, real parent edges and purge safety, using temporary stores only."""
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

from fastapi import HTTPException
from common.hermes_memory import HermesMemory

if os.environ.get("BAROLAB_GRAPH_CANDIDATE"):
    spec = importlib.util.spec_from_file_location("memory_graph_gate_candidate", os.environ["BAROLAB_GRAPH_CANDIDATE"])
    graph = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = graph
    spec.loader.exec_module(graph)
else:
    from server import memory_graph as graph


def proof():
    return {"knowledge": {"kind": "verified_skill", "reusable": True,
        "lesson": "Check the rendered CF result before accepting a repair",
        "steps": ["Inspect source", "Verify rendered result"],
        "sourceAgent": "patch", "channel": "cf",
        "sourceRef": "qa/verified-result.json",
        "verification": {"passed": True, "evidence": "qa/verified-result.json"}}}


class MemoryGraphGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.data = self.root / "data"
        self.store = HermesMemory(self.root / "memories")
        values = {"BASE_DIR": self.root, "SERVER_DIR": self.root, "DATA_DIR": self.data,
            "DB_PATH": self.data / "graph.sqlite3", "GROWTH_DB_PATH": self.data / "growth.sqlite3",
            "METRICS_JSON_PATH": self.data / "metrics.json", "LOCAL_VAULT_DIR": self.data / "vault",
            "LEGACY_BACKUP_DIR": self.data / "legacy", "ARGO_WS_DIR": self.root / "argo",
            "ARGO_INDEX_DB": self.root / "argo/index.sqlite", "ARGO_VAULT_DIR": self.root / "argo/vault",
            "hermes_store": self.store}
        self.patcher = patch.multiple(graph, **values)
        self.patcher.start()
        self.store.initialize()
        graph.reset_to_clean_slate()

    def tearDown(self):
        self.store.close()
        self.patcher.stop()
        self.temp.cleanup()

    def create(self, **kwargs):
        args = dict(title="CF verified repair", content="Reusable repair verified against rendered output.",
                    category="skill", source_agent="patch", channel="cf", evidence=proof())
        args.update(kwargs)
        return graph.register_synapse_memory(**args)

    def assert_real_parents(self, rel):
        result = graph.get_memory_graph(category="all", revenue_only=False, q="")
        index = next(i for i, node in enumerate(result["nodes"]) if node["rel"] == rel)
        adjacent = {b if a == index else a for a, b in result["edges"] if index in (a, b)}
        parents = {result["nodes"][i]["rel"] for i in adjacent}
        self.assertIn("hubs/crew-patch.md", parents)
        self.assertIn("hubs/channel-cf-blog.md", parents)
        return result

    def test_create_patch_and_restore_keep_real_agent_channel_edges(self):
        created = self.create()
        self.assert_real_parents(created["rel"])
        current = graph.get_memory_doc(created["rel"])
        graph.patch_memory_doc(graph.PatchMemoryDoc(expectedRevision=current["revision"], links=[]), created["rel"])
        self.assert_real_parents(created["rel"])
        current = graph.get_memory_doc(created["rel"])
        deleted = graph.delete_memory_doc(created["rel"], current["revision"])
        graph.restore_memory_doc(deleted["trashId"])
        self.assert_real_parents(created["rel"])

    def test_unknown_channel_is_rejected_without_default_cf(self):
        evidence = proof()
        evidence["knowledge"].pop("channel")
        with self.assertRaises(ValueError):
            self.create(title="Reusable procedure", content="Inspect a result and preserve the verified procedure.", channel=None, evidence=evidence)
        self.assertFalse(any(d.get("verifiedKnowledge") for d in graph.load_all_docs(include_unqualified=True)))

    def test_missing_proof_operational_prefix_and_blocked_source_are_rejected(self):
        with self.assertRaises(ValueError):
            self.create(evidence={})
        for title in ("Provider return: accepted", "Naver preparation done", "HTTP 500 retry fixed"):
            with self.subTest(title=title), self.assertRaises(ValueError):
                self.create(title=title)
        for path in ("data/model-events.jsonl", "logs/scheduler.log", "runs/preparation.json"):
            evidence = proof()
            evidence["knowledge"]["sourceRef"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.create(evidence=evidence)

    def test_core_identity_cannot_be_created_or_retyped(self):
        with self.assertRaises(ValueError):
            self.create(category="core_hub")
        with self.assertRaises(ValueError):
            self.create(rel_override="hubs/crew-patch.md")
        current = graph.get_memory_doc("hubs/crew-patch.md")
        with self.assertRaises(HTTPException):
            graph.patch_memory_doc(graph.PatchMemoryDoc(expectedRevision=current["revision"], category="meeting"), current["rel"])

    def test_core_identity_set_is_six_crew_five_channels_and_two_bounded_files(self):
        actual = graph.get_memory_graph(category="all", revenue_only=False, q="")
        self.assertEqual(actual["contractVersion"], "memory-knowledge-gate-v1")
        self.assertIsInstance(actual["quarantine"]["count"], int)
        expected = {f"hubs/crew-{name}.md" for name in ("jarvis", "patch", "publi", "trace", "radar", "doctor")}
        expected |= {f"hubs/channel-{name}.md" for name in ("cf-blog", "naver-blog", "naver-kin", "threads", "apps")}
        expected |= {"hermes/USER.md", "hermes/MEMORY.md"}
        self.assertEqual({n["rel"] for n in actual["nodes"] if n.get("isCoreHub")}, expected)

    def test_missing_authoritative_parents_cannot_create_a_visual_orphan(self):
        for rel in ("hubs/crew-patch.md", "hubs/channel-cf-blog.md"):
            current = graph.get_memory_doc(rel)
            with self.assertRaises(HTTPException):
                graph.delete_memory_doc(rel, current["revision"])
        # Simulate a damaged/missing authoritative identity row, not a normal UI delete.
        with graph.connect_db() as db:
            db.execute("DELETE FROM docs WHERE rel IN ('hubs/crew-patch.md','hubs/channel-cf-blog.md')")
        with self.assertRaises((ValueError, HTTPException)):
            self.create()

    def test_contaminated_trash_cannot_be_restored(self):
        created = self.create()
        current = graph.get_memory_doc(created["rel"])
        deleted = graph.delete_memory_doc(created["rel"], current["revision"])
        with graph.connect_db() as db:
            row = db.execute("SELECT payload FROM memory_trash WHERE trash_id=?", (deleted["trashId"],)).fetchone()
            payload = json.loads(row[0])
            payload["row"]["title"] = "Provider return: output"
            payload["content"] = "Provider return: output with no reusable knowledge"
            db.execute("UPDATE memory_trash SET payload=? WHERE trash_id=?", (json.dumps(payload), deleted["trashId"]))
        with self.assertRaises(HTTPException):
            graph.restore_memory_doc(deleted["trashId"])
        with graph.connect_db() as db:
            self.assertIsNone(db.execute("SELECT rel FROM docs WHERE rel=?", (created["rel"],)).fetchone())

    def test_episode_failures_do_not_gain_decision_status_and_quarantine_uses_real_edges(self):
        self.store.record_episode("raw-error", "llm_call", "Generic execution completed", {"status": 200})
        self.store.record_episode("failed-proof", "verified_skill", "CF verified repair failed", proof(), success=False)
        result = graph.get_memory_graph(category="all", revenue_only=False, q="")
        self.assertFalse(any(n.get("sourceKind") == "sqlite_episode" for n in result["nodes"]))
        self.assertEqual(result["quarantine"]["count"], 2)
        degrees = [0] * len(result["nodes"])
        for a, b in result["edges"]:
            degrees[a] += 1
            degrees[b] += 1
        self.assertEqual(result["stats"]["isolated"], degrees.count(0))

    def test_purge_removes_episode_and_both_fts_preserves_sessions_reviews_and_core(self):
        self.store.record_episode("operational", "llm_call", "Provider return: raw output", {"status": 200}, session_id="s")
        self.store.frozen_session_context("s")
        with self.store.db() as db:
            db.execute("CREATE VIRTUAL TABLE episode_fts USING fts5(event_id UNINDEXED, summary)")
            db.execute("INSERT INTO episode_fts VALUES('operational','Provider return')")
            db.execute("INSERT INTO reviews VALUES('operational','skipped','operational record','2026-10-19')")
            db.execute("INSERT INTO review_queue(event_id,state,updated_at) VALUES('operational','skipped','2026-10-19')")
        ledger = self.data / "original-operational-ledger.jsonl"
        ledger.write_text('{"event":"operational"}\n', encoding="utf-8")
        before = ledger.read_bytes()
        preview = graph.purge_contaminated_memories()
        self.assertFalse(preview["applied"])
        self.assertEqual(preview["episodeCandidates"], 1)
        result = graph.purge_contaminated_memories(apply=True, backup_dir=Path(self.temp.name) / "backups")
        self.assertEqual(result["deletedEpisodes"], 1)
        for backup in result["backups"]:
            with closing(sqlite3.connect(backup["backup"])) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        with self.store.db() as db:
            for table in ("episodes", "episode_fts", "sessions_fts"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table} WHERE event_id='operational'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions WHERE session_id='s'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT status FROM reviews WHERE event_id='operational'").fetchone()[0], "skipped")
        self.assertEqual(ledger.read_bytes(), before)
        graph.sync_argo_vault_and_growth(True)
        all_docs = graph.load_all_docs(include_unqualified=True)
        self.assertEqual(sum(bool(d.get("isCoreHub")) for d in graph.get_memory_graph()["nodes"]), 13)
        self.assertFalse(any(d.get("eventId") == "operational" for d in all_docs))


class MemoryServiceCorsTests(unittest.TestCase):
    def test_only_trusted_dashboard_origins_can_read_and_preflight(self):
        from fastapi.testclient import TestClient
        from server.memory_service import create_app
        with TestClient(create_app(8792)) as client:
            for origin in ("http://127.0.0.1:8790", "http://localhost:8790", "http://192.168.45.190:8790"):
                with self.subTest(origin=origin):
                    response = client.get("/api/status", headers={"Origin": origin})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers.get("Access-Control-Allow-Origin"), origin)
                    self.assertNotIn("Access-Control-Allow-Credentials", response.headers)
                    preflight = client.options("/api/memory/graph", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
                    self.assertEqual(preflight.status_code, 200)
                    self.assertEqual(preflight.headers.get("Access-Control-Allow-Origin"), origin)
            for method in ("GET", "OPTIONS"):
                response = client.request(method, "/api/status", headers={"Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET"})
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("Access-Control-Allow-Origin", response.headers)


if __name__ == "__main__":
    unittest.main()
