"""Permanent knowledge is narrower than searchable operational history."""
import copy
import ast
import hashlib
import json
import re
import sys
import tempfile
import time
import typing
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import HTTPException
from common.hermes_memory import HermesMemory, memorization_decision, should_memorize

def verified_skill():
    return {'knowledge': {'kind': 'verified_skill', 'reusable': True, 'lesson': 'Verify rendered output after changing source', 'steps': ['Inspect source', 'Verify output'], 'sourceRef': 'qa/verified-output.json', 'verification': {'passed': True, 'evidence': 'qa/verified-output.json'}}}

class PromotionGateTests(unittest.TestCase):

    def test_generic_success_and_event_labels_are_not_knowledge(self):
        for event in ('repair', 'decision', 'meeting_decision', 'ceo_correction_conversation_ended', 'pipeline_recovery_success', 'doctor_republish_verified', 'pipeline_publication_verified'):
            self.assertFalse(should_memorize(event, 'Completed successfully', {'status': 200, 'verified': True}))

    def test_operational_provenance_overrides_verified_labels(self):
        for path in ('.agent-routing/ledger.jsonl', 'data/freellm-circuit.json', 'data/topic-model-events.json', 'logs/scheduler.log', 'logs/pipeline-errors.log', 'runs/preparation.json', 'data/naver_automation.json'):
            for key in ('source', 'source_path'):
                self.assertFalse(should_memorize('verified_skill', evidence=verified_skill(), **{key: path}), path)
        for prefix in ('ledger', 'circuit', 'model-events', 'scheduler', 'errors', 'preparation', 'naver_automation'):
            self.assertFalse(should_memorize('verified_skill', evidence=verified_skill(), title=prefix + ': latest status'))
            self.assertFalse(should_memorize(prefix + '_completed', evidence=verified_skill()))
        evidence = verified_skill()
        evidence['knowledge']['sourceRef'] = 'data/model-events.jsonl'
        self.assertFalse(should_memorize('verified_skill', evidence=evidence))

    def test_verified_procedure_paths_are_not_confused_with_operational_files(self):
        for path in ('skills/error-handling/SKILL.md', 'skills/scheduler-recovery/SKILL.md', 'skills/preparation-validation/SKILL.md', 'skills/model-events-analysis/SKILL.md'):
            evidence = verified_skill()
            evidence['knowledge']['sourceRef'] = path
            evidence['knowledge']['verification']['evidence'] = path
            self.assertTrue(should_memorize('verified_skill', evidence=evidence, source_path=path), path)
        for title in ('Error handling procedure', 'Scheduler recovery procedure', 'scheduler-recovery'):
            self.assertTrue(should_memorize('verified_skill', title=title, evidence=verified_skill()), title)

    def test_verified_reusable_skill_requires_each_evidence_field(self):
        self.assertTrue(should_memorize('verified_skill', 'A verified recovery procedure', verified_skill()))
        for key in ('reusable', 'steps', 'lesson', 'sourceRef', 'verification'):
            data = verified_skill()
            del data['knowledge'][key]
            self.assertFalse(should_memorize('verified_skill', evidence=data), key)
        self.assertFalse(should_memorize('verified_skill', evidence=verified_skill(), success=False))

    def test_explicit_operational_prefixes_win_over_structured_evidence(self):
        for prefix in ('Provider return', 'Naver preparation', 'Naver reservation', 'KnowledgeIn publ', 'CF content and p', 'TimeoutError', 'HTTP 500', 'status: invalid'):
            for text in (prefix + ' completed', '  ' + prefix.upper() + ' completed'):
                self.assertFalse(should_memorize('verified_skill', title=text, evidence=verified_skill()), text)
                self.assertFalse(should_memorize('verified_skill', summary='\n \n' + text, evidence=verified_skill()), text)

    def test_meeting_requires_explicit_quoted_user_decision(self):
        evidence = {'knowledge': {'kind': 'meeting_decision', 'decisionText': 'Keep unknown revenue unknown', 'userQuote': 'Decision: Keep unknown revenue unknown', 'userConfirmed': True, 'sourceMessageId': 'message-17', 'sourceRef': 'meetings/approved-decision.json'}}
        self.assertTrue(should_memorize('meeting_decision', evidence=evidence))
        self.assertFalse(should_memorize('pipeline_recovery_success', evidence=evidence))
        wrong_origin = copy.deepcopy(evidence)
        wrong_origin['knowledge']['sourceRef'] = 'pipeline/claimed-decision.json'
        self.assertFalse(should_memorize('meeting_decision', evidence=wrong_origin))
        chat = copy.deepcopy(evidence)
        chat['archive'] = '_room-123456789.json'
        chat['knowledge']['sourceRef'] = chat['archive']
        self.assertTrue(should_memorize('ceo_correction_conversation_ended', evidence=chat))
        for key in ('userQuote', 'userConfirmed', 'sourceMessageId', 'sourceRef'):
            changed = copy.deepcopy(evidence)
            del changed['knowledge'][key]
            self.assertFalse(should_memorize('meeting_decision', evidence=changed))
        evidence['knowledge']['userQuote'] = 'An assistant guessed this was approved'
        self.assertFalse(should_memorize('meeting_decision', evidence=evidence))

    def test_measured_increase_requires_complete_comparable_periods(self):
        previous = dict(status='complete', total=10, start='2026-10-01', end='2026-10-07', currency='KRW', source_timezone='Asia/Seoul', value_kind='estimated', revenue_scope='account')
        current = dict(previous, total=12, start='2026-10-08', end='2026-10-14')
        evidence = dict(previous=previous, current=current, service='adsense', siteId='site', metric='revenue')
        self.assertTrue(should_memorize('growth_measured_increase', evidence=evidence))
        for change in ({'status': 'partial'}, {'currency': 'USD'}, {'total': float('nan')}, {'start': '2026-10-07'}, {'start': ['invalid']}, {'end': 'not-a-date'}, {'total': 10 ** 400}):
            changed = copy.deepcopy(evidence)
            changed['current'].update(change)
            self.assertFalse(should_memorize('growth_measured_increase', evidence=changed))

    def test_consensus_needs_distinct_referenced_verified_agreement(self):
        evidence = {'knowledge': {'kind': 'meeting_decision', 'decisionText': 'Preserve unknown amounts', 'sourceRef': 'meetings/consensus.json', 'verification': {'passed': True, 'evidence': 'meetings/consensus-verification.json'}, 'consensus': [{'participantId': 'agent-a', 'sourceMessageId': 'm1', 'agrees': True, 'quote': 'I agree: Preserve unknown amounts'}, {'participantId': 'agent-b', 'sourceMessageId': 'm2', 'agrees': True, 'quote': 'Agreed: Preserve unknown amounts'}]}}
        self.assertTrue(should_memorize('meeting_decision', evidence=evidence))
        for key, value in (('participantId', 'agent-a'), ('sourceMessageId', 'm1'), ('agrees', False), ('quote', 'unclear')):
            changed = copy.deepcopy(evidence)
            changed['knowledge']['consensus'][1][key] = value
            self.assertFalse(should_memorize('meeting_decision', evidence=changed))
        del evidence['knowledge']['verification']
        self.assertFalse(should_memorize('meeting_decision', evidence=evidence))

    def test_complete_domain_rpm_snapshot_without_baseline_is_supported(self):
        data = {'knowledge': {'kind': 'measured_snapshot', 'sourceRef': 'server/data/revenue.json', 'verification': {'passed': True, 'evidence': 'qa/domain-rpm-verification.json'}, 'sourceStatus': 'complete', 'domain': 'example.org', 'metric': 'page_rpm', 'period': {'start': '2026-10-01', 'end': '2026-10-18'}, 'sourceTimezone': 'Asia/Seoul', 'currency': 'USD', 'numeratorMetric': 'revenue', 'denominatorMetric': 'pageviews', 'numerator': 1.5, 'denominator': 500, 'value': 3.0, 'analysis': 'Observed revenue per thousand pageviews for this complete period; causality unproved.'}}
        self.assertEqual(memorization_decision('analysis', evidence=data)['kind'], 'measured_insight')
        for key, value in (('sourceStatus', 'partial'), ('denominator', 0), ('value', 99), ('domain', ''), ('analysis', ''), ('denominatorMetric', 'impressions')):
            changed = copy.deepcopy(data)
            changed['knowledge'][key] = value
            self.assertFalse(should_memorize('analysis', evidence=changed), key)
        self.assertFalse(should_memorize('analysis', 'Top accumulated revenues', {'sourceRef': 'server/data/revenue.json'}))

    def test_rejected_log_still_searchable_and_no_reviewer_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = HermesMemory(Path(tmp) / 'memories', skills_root=Path(tmp) / 'skills')
            try:
                store.record_episode('scheduler:sample', 'scheduler_completed', 'Scheduler completed operational sample', {'status': 200})
                reviewer = Mock()
                self.assertFalse(store.enqueue_review('scheduler:sample', reviewer)['queued'])
                store._run_review('scheduler:sample', reviewer)
                reviewer.assert_not_called()
                self.assertEqual(len(store.session_search('operational sample')), 1)
                self.assertEqual(store.bounded('memory')['content'], '')
                with store.db() as db:
                    self.assertEqual(db.execute('SELECT status FROM reviews').fetchone()[0], 'skipped')
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM episodes').fetchone()[0], 1)
            finally:
                store.close()

    def test_curated_channel_procedure_has_real_sources_and_no_execution_claim(self):
        root = Path(__file__).resolve().parents[3]
        text = (root / 'data/skills/channel-verification/SKILL.md').read_text(encoding='utf-8')
        evidence = json.loads(re.search('<!-- barolab-knowledge (.*?) -->', text).group(1))
        knowledge = evidence['knowledge']
        self.assertEqual(knowledge['provenance'], 'curated_procedure')
        self.assertFalse(knowledge['executionVerified'])
        self.assertFalse(knowledge['verification']['executionVerified'])
        for rel in [knowledge['sourceRef'], *knowledge['implementationSources']]:
            self.assertTrue((root / rel).is_file(), rel)
        self.assertTrue(should_memorize('verified_skill', title='Channel verification', evidence=evidence))

    def test_reviewer_requires_meaningful_skill_parents_and_preserves_real_provenance(self):
        for accepted in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                store = HermesMemory(Path(tmp) / 'memories', skills_root=Path(tmp) / 'skills')
                try:
                    store.record_episode('verified-procedure', 'verified_skill', 'Verified recovery procedure', verified_skill())
                    resolver = Mock(return_value={'crew': ['hubs/crew-patch'], 'channel': ['hubs/channel-cf-blog'], 'links': ['hubs/crew-patch', 'hubs/channel-cf-blog']})
                    if not accepted:
                        resolver.side_effect = ValueError('No verified channel')
                    fake_graph = SimpleNamespace(auto_link_synapses=resolver, validate_synapse_hubs=Mock())
                    with patch.dict(sys.modules, {'server.memory_graph': fake_graph}):
                        store._run_review('verified-procedure', lambda _: {'skills': [{'action': 'create', 'name': 'verified-procedure', 'content': '# Procedure\nInspect output.\n<!-- barolab-knowledge {"forged":true} -->'}]})
                    with store.db() as db:
                        status = db.execute('SELECT status FROM reviews').fetchone()[0]
                    self.assertEqual(status, 'applied' if accepted else 'failed')
                    if accepted:
                        content = store.skill_view('verified-procedure')['content']
                        self.assertIn('[[hubs/crew-patch]]', content)
                        self.assertIn('[[hubs/channel-cf-blog]]', content)
                        self.assertNotIn('"forged"', content)
                        self.assertIn('"sourceEventId":"verified-procedure"', content)
                    else:
                        self.assertEqual(store.skill_list(), [])
                finally:
                    store.close()

class ChatPromotionFailureTests(unittest.TestCase):
    """Load only the three functions: no live chat workers, database or provider."""

    def load_function(self, name, root):
        source = (Path(__file__).resolve().parents[2] / 'agents/chat_room.py').read_text(encoding='utf-8')
        node = next((n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name))
        node.decorator_list = []
        env = dict(json=json, re=re, time=time, datetime=datetime, Path=Path, hashlib=hashlib, List=typing.List, Dict=typing.Dict, Any=typing.Any, Optional=typing.Optional, SaveToMemoryRequest=object, HTTPException=HTTPException, DATA_DIR=root, ARCHIVE_DIR=root / 'chats/.archive', AGENT_MAP={}, register_synapse_memory=Mock(side_effect=ValueError('structured_knowledge_evidence_required')), load_room_data=Mock(return_value={'sid': 3, 'messages': [{'id': 'm1', 'who': 'user', 'text': 'Original meeting content'}]}), save_room_data=Mock(), list_archived_meetings=Mock(return_value=[]), append_or_update_room_message=Mock())
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'chat-promotions', 'exec'), env)
        return (env[name], env)

    def test_rnd_proposal_preserved_without_fake_saved_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fn, env = self.load_function('_save_rnd_proposal_and_memory', root)
            result = fn([{'ok': True, 'videoId': 'example', 'title': 'Analysis', 'url': 'https://example.org'}], 'Original analysis')
            self.assertIsNone(result)
            record = json.loads((root / 'rnd_proposals.json').read_text(encoding='utf-8'))[0]
            self.assertEqual(record['analysisMarkdown'], 'Original analysis')
            self.assertIsNone(record['memoryRel'])
            self.assertEqual(record['memoryPromotion']['status'], 'skipped')

    def test_meeting_archive_survives_rejected_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fn, env = self.load_function('end_meeting', root)
            with patch.dict(sys.modules, {'common.llm_client': SimpleNamespace(memory_event=Mock())}):
                result = fn()
            self.assertTrue(result['archived'])
            self.assertIsNone(result['journal'])
            self.assertEqual(result['memoryPromotion']['status'], 'skipped')
            archive = json.loads((env['ARCHIVE_DIR'] / result['archiveId']).read_text(encoding='utf-8'))
            self.assertEqual(archive, env['load_room_data'].return_value)
            env['save_room_data'].assert_called_once()

    def test_explicit_save_validation_failure_is_400_without_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            fn, env = self.load_function('save_chat_message_to_memory', Path(tmp))
            req = SimpleNamespace(messageId='m1', who='radar', text='', title='')
            with self.assertRaises(HTTPException) as cm:
                fn(req)
            self.assertEqual(cm.exception.status_code, 400)
            self.assertEqual(cm.exception.detail, 'structured_knowledge_evidence_required')
            env['append_or_update_room_message'].assert_not_called()
if __name__ == '__main__':
    unittest.main()
