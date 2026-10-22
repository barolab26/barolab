import hashlib
import json
import tempfile
import sqlite3
from contextlib import nullcontext
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from common import hermes_memory as h
from common import llm_client as llm

class VerifiedWorkTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = h.HermesMemory(self.root / 'memory')
        self.addCleanup(self.store.close)
        self.patch = patch.object(h, '_store', self.store)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        from server import memory_graph
        graph_db = sqlite3.connect(':memory:')
        graph_db.executescript("CREATE TABLE docs(rel TEXT,is_core_hub INTEGER); CREATE TABLE memory_trash(rel TEXT,restored_at TEXT); INSERT INTO docs VALUES('hubs/crew-patch.md',1),('hubs/channel-project.md',1);")
        self.addCleanup(graph_db.close)
        graph_patch = patch.object(memory_graph, 'connect_db', side_effect=lambda: nullcontext(graph_db))
        graph_patch.start()
        self.addCleanup(graph_patch.stop)
        self.diff = self.root / 'source.diff'
        self.diff.write_text('Use same-origin graph API', encoding='utf-8')
        digest = hashlib.sha256(self.diff.read_bytes()).hexdigest()
        self.proof_file = self.root / 'result.json'
        self.proof_file.write_text(json.dumps({'http': {'status': 200}, 'dbReadOnlyCheck': {'unchanged': True, 'before': {'rows': 1}, 'after': {'rows': 1}}, 'previousFailureEvidence': 'loopback unavailable', 'sourceDiffPath': str(self.diff), 'sourceDiffSha256': digest}), encoding='utf-8')
        self.artifacts = [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (self.diff, self.proof_file)]
        self.kw = dict(work_type='verified_work_receipt_v1', channel='project', outcome='maintenance_verified', scope='maintenance_verified', source_agent='patch', evidence_text='Same-origin graph repair passed HTTP and unchanged database checks.', artifacts=self.artifacts, checks=[{'type': t, 'passed': True, 'evidenceRef': str(self.diff if t == 'source_diff' else self.proof_file)} for t in ('source_diff', 'http_response', 'read_only_state')])
        self.candidate = {'title': 'Same-origin graph recovery', 'lesson': 'Use the dashboard origin for its graph API.', 'steps': ['Verify the same-origin graph contract', 'Check unchanged stored data'], 'applicability': 'Dashboard graph migration'}
        self.verdict = dict(supported=True, reusable=True, scopePreserved=True, noSensitiveData=True, reason='supported')

    def proof(self):
        return h.write_verified_work_receipt(self.root / 'receipt.json', **self.kw)

    def test_recovery_requires_actual_original_work_beyond_code_and_tests(self):

        def save(name, value):
            path = self.root / name
            path.write_text(json.dumps(value), encoding='utf-8')
            return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        original = self.proof()
        candidate = save('candidate.json', {'changes': [{'path': 'example.py', 'content': 'fixed'}]})
        manifest = save('manifest.json', {'files': ['example.py'], 'sourceHashes': {'example.py': 'before'}})
        validation = save('validation.json', {'status': 'isolated_verified', 'candidateSha256': candidate['sha256'], 'manifestSha256': manifest['sha256'], 'reviewSha256': 'pre-review', 'sandbox': {'enforced': True}, 'results': [{'returncode': 0, 'summary': {'executed': 3}}]})
        review = save('final-review.json', {'candidateSha256': candidate['sha256'], 'manifestSha256': manifest['sha256'], 'validationSha256': validation['sha256'], 'verdict': {k: True for k in ('fixSupported', 'scopeRespected', 'gatesPreserved', 'testsRelevant', 'safeToApply')}, 'route': {'state': 'returned', 'actualModel': 'configured-model'}})
        application = save('application.json', {'status': 'applied', 'productionApplied': True, 'candidateSha256': candidate['sha256'], 'reviewSha256': 'pre-review', 'finalReviewSha256': review['sha256'], 'validationSha256': validation['sha256'], 'before': {'example.py': 'before'}})
        controller = save('controller.json', {'taskId': 'task', 'planSha256': 'plan', 'plan': {'failure': [{'status': 'failed'}]}, 'resumeAttempted': True, 'application': {'evidenceSha256': application['sha256']}, 'resumeResult': {'ok': True, 'verifiedWorkProof': original}})
        bound = {'type': 'project_recovery_completion_v1', 'taskId': 'task', 'planSha256': 'plan', 'candidateSha256': candidate['sha256'], 'candidate': candidate, 'manifest': manifest, 'application': application, 'validation': validation, 'finalReview': review, 'controller': controller, 'originalWork': {'path': original['sourceRef'], 'sha256': original['sourceSha256']}}
        completion = save('completion.json', bound)
        receipt = {'schemaVersion': 1, 'type': 'verified_work_receipt_v1', 'channel': 'project', 'outcome': 'recovery_verified', 'sourceAgent': 'patch', 'evidenceText': 'The exact repaired task was independently verified.', 'artifactHashes': [candidate, manifest, application, validation, review, controller, bound['originalWork'], completion], 'verification': {'scope': 'recovery_verified', 'checks': [{'type': kind, 'passed': True, 'evidenceRef': completion['path']} for kind in ('source_diff', 'tests_passed', 'original_task_verified')]}}
        h.validate_work_receipt(receipt)
        receipt['artifactHashes'] = [item for item in receipt['artifactHashes'] if item != bound['originalWork']]
        with self.assertRaises(ValueError):
            h.validate_work_receipt(receipt)
        invalid = json.loads(Path(original['sourceRef']).read_bytes())
        invalid['verification']['checks'] = [c for c in invalid['verification']['checks'] if c['type'] != 'read_only_state']
        with self.assertRaises(ValueError):
            h.validate_work_receipt(invalid)

    def process(self, verdict=None):
        reviewer = llm._memory_review
        with patch.object(self.store, 'enqueue_review', side_effect=lambda eid, cb: self.store._run_review(eid, cb)):
            return self.store.process_verified_work_once(lambda e: self.candidate, lambda e: verdict or self.verdict, reviewer)

    def test_nonblocking_idempotent_verified_review_then_next_task_retrieval(self):
        proof = self.proof()
        self.assertTrue(llm.record_verified_work('repair', proof)['queued'])
        self.assertFalse(llm.record_verified_work('repair', proof)['queued'])
        self.assertEqual(self.store.experience_context('graph migration', 'before')['selected'], [])
        self.assertTrue(self.process())
        self.assertFalse(self.process())
        self.assertEqual(self.store.experience_context('graph migration', 'before')['selected'], [])
        result = self.store.experience_context('graph migration', 'after')
        self.assertEqual(result['selected'][0]['eventId'], 'learned:repair')
        self.assertIn('not instructions', result['text'])
        self.assertIn(self.candidate['lesson'], self.store.skill_view(self.store.skill_list()[0]['name'])['content'])

    def test_record_tag_reinterpretation_reuses_exact_raw_without_extraction(self):
        proof = self.proof()
        llm.record_verified_work('syntax-old', proof)
        raw = json.dumps({'decision': 'record', **self.candidate}, ensure_ascii=False, indent=2)
        with self.store.db() as db:
            db.execute("UPDATE learning_candidates SET state='rejected',detail='ValueError',candidate=? WHERE event_id='syntax-old'", (raw,))
            original = tuple(db.execute("SELECT * FROM learning_candidates WHERE event_id='syntax-old'").fetchone())
        event = 'syntax-old:parser:' + h.LEARNING_PARSER_REVISION
        self.assertTrue(llm.record_verified_work(event, proof, reinterpret_event_id='syntax-old')['queued'])
        self.assertFalse(llm.record_verified_work(event, proof, reinterpret_event_id='syntax-old')['queued'])
        extractor = Mock(side_effect=AssertionError('No new extraction permitted'))
        verifier = Mock(return_value=self.verdict)
        with patch.object(self.store, 'enqueue_review', side_effect=lambda eid, cb: self.store._run_review(eid, cb)):
            self.store.process_verified_work_once(extractor, verifier, llm._memory_review)
        extractor.assert_not_called()
        verifier.assert_called_once()
        with self.store.db() as db:
            self.assertEqual(tuple(db.execute("SELECT * FROM learning_candidates WHERE event_id='syntax-old'").fetchone()), original)
            row = db.execute('SELECT state,candidate,proof FROM learning_candidates WHERE event_id=?', (event,)).fetchone()
            self.assertEqual(row[0], 'approved')
            self.assertEqual(row[1], raw)
            self.assertEqual(json.loads(row[2])['cachedCandidateSha256'], h.revision(raw))
        with self.assertRaises(ValueError):
            h.validated_work_candidate({**self.candidate, 'decision': 'publish'})
        with self.assertRaises(ValueError):
            h.validated_work_candidate({**self.candidate, 'decision': 'record', 'extra': 'not allowed'})
        with self.assertRaises(ValueError):
            llm.record_verified_work(event + ':parser:' + h.LEARNING_PARSER_REVISION, proof, reinterpret_event_id=event)

    def test_parser_continuation_accepts_schema_stage_only(self):
        proof = self.proof()
        raw = json.dumps({'decision': 'record', **self.candidate})
        for index, detail in enumerate(('candidate_schema:ValueError', 'host_evidence:ValueError', 'independent_verifier:ValueError')):
            old = 'stage-' + str(index)
            llm.record_verified_work(old, proof)
            with self.store.db() as db:
                db.execute("UPDATE learning_candidates SET state='rejected',detail=?,candidate=? WHERE event_id=?", (detail, raw, old))
            event = old + ':parser:' + h.LEARNING_PARSER_REVISION
            if detail == 'candidate_schema:ValueError':
                self.assertTrue(llm.record_verified_work(event, proof, reinterpret_event_id=old)['queued'])
            else:
                with self.assertRaises(ValueError):
                    llm.record_verified_work(event, proof, reinterpret_event_id=old)

    def test_policy_reevaluation_is_once_and_original_skip_immutable(self):
        proof = self.proof()
        llm.record_verified_work('old-work', proof)
        old_candidate = json.dumps({'decision': 'skip', 'reason': 'No cross-environment rule shown'})
        with self.store.db() as db:
            db.execute("UPDATE learning_candidates SET state='skipped',proof=?,candidate=? WHERE event_id='old-work'", (json.dumps(proof), old_candidate))
            old = tuple(db.execute("SELECT * FROM learning_candidates WHERE event_id='old-work'").fetchone())
        event = 'old-work:policy:' + h.LEARNING_POLICY_REVISION
        self.assertTrue(llm.record_verified_work(event, proof, reevaluate_event_id='old-work')['queued'])
        self.assertFalse(llm.record_verified_work(event, proof, reevaluate_event_id='old-work')['queued'])
        with self.assertRaises(ValueError):
            llm.record_verified_work('another-id', proof, reevaluate_event_id='old-work')
        self.process()
        with self.store.db() as db:
            self.assertEqual(tuple(db.execute("SELECT * FROM learning_candidates WHERE event_id='old-work'").fetchone()), old)
            knowledge = json.loads(db.execute('SELECT evidence FROM episodes WHERE event_id=?', ('learned:' + event,)).fetchone()[0])['knowledge']
            self.assertEqual(knowledge['previousCandidateSha256'], h.revision(old_candidate))
            self.assertEqual(knowledge['learningPolicyRevision'], h.LEARNING_POLICY_REVISION)
            db.execute("UPDATE learning_candidates SET state='skipped' WHERE event_id=?", (event,))
        with self.assertRaises(ValueError):
            llm.record_verified_work(event + ':policy:' + h.LEARNING_POLICY_REVISION, proof, reevaluate_event_id=event)

    def test_posting_artifact_body_is_not_sent_to_learning_model(self):
        private = 'PRIVATE_ARTICLE_BODY_MUST_NOT_REACH_MODEL'
        self.proof_file.write_text(json.dumps({'submissionStatus': 'verified_reserved', 'documentSha256': 'a' * 64, 'reserveTime': '2026-10-22 11:00', 'document': private}), encoding='utf-8')
        self.kw.update(channel='naver_blog', outcome='reservation_verified', scope='reservation_verified', evidence_text='Native visual review confirmed two explanatory captures beside matching sections.', artifacts=[{'path': str(self.proof_file), 'sha256': hashlib.sha256(self.proof_file.read_bytes()).hexdigest()}], checks=[{'type': kind, 'passed': True, 'evidenceRef': str(self.proof_file)} for kind in ('reservation_identity', 'reservation_content')])
        llm.record_verified_work('posting-private', self.proof())
        captured = []

        def extract(evidence):
            captured.append(evidence)
            return {'decision': 'skip', 'reason': 'No reusable lesson'}
        self.store.process_verified_work_once(extract, Mock(), Mock())
        self.assertNotIn(private, json.dumps(captured))
        self.assertEqual(captured[0]['artifactEvidence'], [])
        self.assertIn('two explanatory captures', captured[0]['evidenceText'])

    def test_new_work_without_prior_matches_is_not_required_to_skip(self):
        llm.record_verified_work('new-without-prior', self.proof())
        with patch.object(llm, 'generate_json', side_effect=[self.candidate, self.verdict]) as model, patch.object(self.store, 'enqueue_review', return_value={'queued': True}):
            self.assertTrue(llm.process_verified_work_once())
        self.assertEqual(model.call_count, 2)
        prompt = model.call_args_list[0].args[0]
        self.assertIn('neither blocks a new evidenced lesson nor proves novelty', prompt)
        self.assertIn('"relatedVerifiedLessons": []', prompt)
        self.assertTrue(all((call.kwargs['_skip_memory'] for call in model.call_args_list)))
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM learning_candidates').fetchone()[0], 'approved')

    def test_no_new_lesson_skip_preserves_original_and_never_verifies(self):
        llm.record_verified_work('skip', self.proof())
        original = {'decision': 'skip', 'reason': 'Ordinary success with no reusable new lesson'}
        verifier = Mock(side_effect=AssertionError('skip must not verify'))
        self.store.process_verified_work_once(lambda e: original, verifier, Mock())
        with self.store.db() as db:
            row = db.execute('SELECT state,candidate FROM learning_candidates').fetchone()
            self.assertEqual(row[0], 'skipped')
            self.assertEqual(json.loads(row[1]), original)
        verifier.assert_not_called()
        self.assertFalse(self.store.process_verified_work_once(Mock(), Mock(), Mock()))

    def test_invalid_hash_false_check_and_sensitive_text_rejected(self):
        self.kw['checks'][0]['passed'] = False
        with self.assertRaises(ValueError):
            self.proof()
        self.kw['checks'][0]['passed'] = True
        self.kw['evidence_text'] = 'contact person@example.com'
        with self.assertRaises(ValueError):
            self.proof()
        self.kw['evidence_text'] = 'actual verified repair'
        proof = self.proof()
        self.diff.write_text('changed', encoding='utf-8')
        with self.assertRaises(ValueError):
            llm.record_verified_work('bad', proof)

    def test_new_verified_work_rejects_memory_only_promotion(self):
        llm.record_verified_work('memory-only', self.proof())
        reviewer = lambda payload: {'memory': [{'target': 'memory', 'action': 'add', 'text': 'lesson', 'expected_revision': payload['memory']['revision']}], 'skills': []}
        with patch.object(self.store, 'enqueue_review', side_effect=lambda eid, cb: self.store._run_review(eid, cb)):
            self.store.process_verified_work_once(lambda e: self.candidate, lambda e: self.verdict, reviewer)
        with self.store.db() as db:
            self.assertEqual(db.execute("SELECT status FROM reviews WHERE event_id='learned:memory-only'").fetchone()[0], 'failed')
        self.assertEqual(self.store.bounded('memory')['content'], '')

    def test_independent_rejection_never_promotes_or_retries(self):
        llm.record_verified_work('reject', self.proof())
        verdict = {**self.verdict, 'supported': False}
        self.process(verdict)
        self.assertFalse(llm.record_verified_work('reject', self.proof())['queued'])
        self.assertEqual(self.store.bounded('memory')['content'], '')
        self.assertEqual(self.store.experience_context('graph', 'new')['selected'], [])

    def test_artifact_changed_between_candidate_and_verifier_rejected(self):
        llm.record_verified_work('changed', self.proof())

        def verify(data):
            self.diff.write_text('tampered', encoding='utf-8')
            return self.verdict
        self.store.process_verified_work_once(lambda e: self.candidate, verify, Mock())
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT state FROM learning_candidates').fetchone()[0], 'rejected')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes').fetchone()[0], 0)

    def test_expired_worker_reuses_saved_candidate_and_verdict_once(self):
        llm.record_verified_work('interrupted', self.proof())
        with self.store.db() as db:
            db.execute("UPDATE learning_candidates SET state='processing',lease_until=0,attempts=1,candidate=?,verdict=?", (json.dumps(self.candidate), json.dumps(self.verdict)))
        extract, verify = (Mock(side_effect=AssertionError('candidate already durable')), Mock(side_effect=AssertionError('verdict already durable')))
        with patch.object(self.store, 'enqueue_review', return_value={'queued': True}):
            self.assertTrue(self.store.process_verified_work_once(extract, verify, Mock()))
        extract.assert_not_called()
        verify.assert_not_called()
        with self.store.db() as db:
            self.assertEqual(tuple(db.execute('SELECT state,attempts FROM learning_candidates').fetchone()), ('approved', 2))
        self.assertEqual(self.store.experience_context('graph', 'not-yet-applied')['selected'], [])

    def test_experience_budget_and_boilerplate_query(self):
        proof = self.proof()
        llm.record_verified_work('bounded', proof)
        self.process()
        result = self.store.experience_context('Return JSON only with required fields object properties string type schema. graph migration', 'bounded-query')
        self.assertEqual(len(result['selected']), 1)
        self.assertLess(len(result['text']), 12000)
        with self.store.db() as db:
            evidence = json.loads(db.execute("SELECT evidence FROM episodes WHERE event_id='learned:bounded'").fetchone()[0])
            evidence['knowledge']['lesson'] = 'graph ' * 2000
            db.execute("UPDATE episodes SET evidence=? WHERE event_id='learned:bounded'", (json.dumps(evidence),))
        self.assertEqual(self.store.experience_context('graph', 'oversized')['selected'], [])

    def test_prompt_trace_matches_actual_delivery_and_skip_is_empty(self):
        llm.record_verified_work('trace', self.proof())
        self.process()
        actual = []

        @llm.memory_call
        def provider(prompt):
            actual.append(prompt)
            return llm.record_provider_memory_delivery('provider header ' + prompt, 'test', 'test-model', status='completed')
        row = provider('graph migration', memory_session_id='next')
        self.assertTrue(row['memoryPrefixPresent'])
        self.assertEqual(row['actualPromptSha256'], h.revision('provider header ' + actual[0]))
        self.assertEqual(row['episodeRefs'][0]['eventId'], 'learned:trace')
        self.assertIsNone(provider('review', _skip_memory=True))

def setUpModule():
    import tempfile
    from pathlib import Path
    from unittest.mock import patch
    from common import repair_workflow
    global _isolated_crew_temp, _isolated_crew_patches
    _isolated_crew_temp = tempfile.TemporaryDirectory()
    root = Path(_isolated_crew_temp.name)
    _isolated_crew_patches = [patch('common.crew_chat_bridge._deliver', return_value=True), patch('common.crew_chat_bridge.OUTBOX_DIR', root / 'outbox'), patch.object(repair_workflow, 'ROOT', root / 'repairs')]
    for guard in _isolated_crew_patches:
        guard.start()

def tearDownModule():
    for guard in reversed(_isolated_crew_patches):
        guard.stop()
    _isolated_crew_temp.cleanup()
if __name__ == '__main__':
    unittest.main()
