"""Offline regressions for call admission and stable CEO blocker updates."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import crew_chat_bridge as bridge, llm_usage as usage


class ResourceControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'dashboard/data'
        self.rows = self.data / 'publication-conferences/operations'
        self.rows.mkdir(parents=True)
        self.agenda = 'a' * 64
        self.now = dt.datetime.now(usage.KST)

    def plan(self, value, agenda=None):
        (self.rows / ((agenda or self.agenda) + '.json')).write_text(json.dumps({'businessExperiment': value}))

    def call(self, identity, agenda=None, now=None):
        return dict(id=identity, provider='offline', model='fixture', agendaId=agenda or self.agenda,
                    startedAt=(now or self.now).isoformat(), inputTokens=1, outputTokens=1,
                    usageReports=1, latencyMs=1, rateLimitHeaders={})

    def test_missing_plan_uses_policy_and_zero_blocks(self):
        usage.check_budget({}, self.call('one'), usage.DEFAULT_BUDGET, self.root)
        self.plan({'maxModelCalls': 0})
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'agenda_call_budget_exhausted'):
            usage.record_call(self.call('one'), 'started', root=self.root, now=self.now)
        self.assertEqual(json.loads((self.data / 'llm_usage_ledger.json').read_text())['active'], {})

    def test_invalid_explicit_limits_fail_closed(self):
        for invalid in (None, True, False, -1, 1.5, '20', []):
            with self.subTest(invalid=invalid):
                self.plan({'maxModelCalls': invalid})
                with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'experiment_call_budget_invalid'):
                    usage.check_budget({}, self.call('one'), usage.DEFAULT_BUDGET, self.root)

    def test_shared_experiment_counts_other_agendas_inflight_and_across_midnight(self):
        other = 'b' * 64
        for agenda in (self.agenda, other):
            self.plan({'id': 'trial-one', 'maxModelCalls': 2}, agenda)
        one = self.call('one')
        usage.record_call(one, 'started', root=self.root, now=self.now)
        usage.record_call(one, 'completed', root=self.root, now=self.now)
        tomorrow = self.now + dt.timedelta(days=1)
        two = self.call('two', other, tomorrow)
        usage.record_call(two, 'started', root=self.root, now=tomorrow)
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'experiment_call_budget_exhausted'):
            usage.record_call(self.call('three', now=tomorrow), 'started', root=self.root, now=tomorrow)
        usage.record_call(two, 'completed', root=self.root, now=tomorrow)
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'experiment_call_budget_exhausted'):
            usage.record_call(self.call('four', now=tomorrow), 'started', root=self.root, now=tomorrow)
        state = json.loads((self.data / 'llm_usage_ledger.json').read_text())
        self.assertEqual(state['byExperiment']['trial-one']['modelCalls'], 2)
        self.assertEqual(state['active'], {})

    def test_experiment_cannot_increase_policy_limit(self):
        self.plan({'id': 'trial-one', 'maxModelCalls': 100})
        state = {'byExperiment': {'trial-one': {'modelCalls': 3}}}
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'experiment_call_budget_exhausted'):
            usage.check_budget(state, self.call('one'), {**usage.DEFAULT_BUDGET, 'agendaCalls': 3}, self.root)

    def test_blocker_updates_across_actors_and_days_without_resetting_approval(self):
        path = self.data / 'ceo-proposals.json'
        context = dict(project='naver_blog', account='account-a', reasonCode='auth_required', resumeCondition='session_verified')
        with patch.object(bridge, 'CEO_PROPOSALS_FILE', path), patch.object(bridge, '_deliver') as deliver:
            first = bridge.emit_ceo_proposal('jarvis', 'Session unavailable', 'Observed logout', 'Restore session', ['Login support'], blocker_context=context)
            state = json.loads(path.read_text(encoding='utf-8'))
            state['proposals'][0].update(status='approved', createdAt=1, approvalEvidence={'id': 'ceo-reply'})
            state['executionPackages'] = {'keep': {'state': 'approved_not_verified'}}
            path.write_text(json.dumps(state), encoding='utf-8')
            second = bridge.emit_ceo_proposal('patch', 'Same blocker, new wording', 'Still logged out', 'Restore session', ['Login support'], blocker_context=context)
            self.assertEqual(first['proposal']['id'], second['proposal']['id'])
            self.assertEqual(second['proposal']['status'], 'approved')
            self.assertEqual(second['proposal']['occurrences'], 2)
            self.assertEqual(second['proposal']['approvalEvidence'], {'id': 'ceo-reply'})
            self.assertFalse(second['proposal'].get('followupReviewRequired'))
            self.assertEqual(second['proposal']['latestObservation']['currentReality'], 'Still logged out')
            stored = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(len(stored['proposals']), 1)
            self.assertIn('executionPackages', stored)
            deliver.assert_called_once()

    def test_distinct_blockers_do_not_merge_even_with_identical_wording(self):
        path = self.data / 'ceo-proposals.json'
        base = dict(project='naver_blog', account='a', reasonCode='auth_required', resumeCondition='session_verified')
        with patch.object(bridge, 'CEO_PROPOSALS_FILE', path), patch.object(bridge, '_deliver') as deliver:
            for context in (base, {**base, 'account': 'b'}, {**base, 'reasonCode': 'submission_unknown'}, {**base, 'resumeCondition': 'receipt_verified'}):
                bridge.emit_ceo_proposal('jarvis', 'Support', 'Blocked', 'Restore', ['Support'], blocker_context=context)
            self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['proposals']), 4)
            self.assertEqual(deliver.call_count, 4)

    def test_legacy_pending_key_survives_six_hour_window_and_new_scope_is_unapproved(self):
        path = self.data / 'ceo-proposals.json'
        with patch.object(bridge, 'CEO_PROPOSALS_FILE', path), patch.object(bridge, '_deliver') as deliver:
            bridge.emit_ceo_proposal('jarvis', 'Request', 'Blocked', 'One post', ['One post'], request_key='scope-one')
            state = json.loads(path.read_text(encoding='utf-8'))
            state['proposals'][0]['createdAt'] = 1
            path.write_text(json.dumps(state), encoding='utf-8')
            result = bridge.emit_ceo_proposal('jarvis', 'Request revised', 'Blocked', 'Two posts', ['Two posts'], request_key='scope-one')
            self.assertEqual(result['proposal']['requiredApprovals'], ['One post'])
            self.assertEqual(result['proposal']['followups'][0]['status'], 'requires_scope_review')
            self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['proposals']), 1)
            deliver.assert_called_once()

    def test_legacy_fingerprint_remains_compatible(self):
        path = self.data / 'ceo-proposals.json'
        fingerprint = hashlib.sha256(b'jarvis|Request|Restore|Support').hexdigest()[:16]
        path.write_text(json.dumps({'proposals': [{'id': 'legacy', 'fingerprint': fingerprint,
            'actor': 'jarvis', 'status': 'pending_ceo', 'createdAt': 1}]}), encoding='utf-8')
        with patch.object(bridge, 'CEO_PROPOSALS_FILE', path), patch.object(bridge, '_deliver') as deliver:
            result = bridge.emit_ceo_proposal('jarvis', 'Request', 'Current observation', 'Restore', ['Support'])
            self.assertEqual(result['proposal']['id'], 'legacy')
            self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['proposals']), 1)
            deliver.assert_not_called()

    def test_matching_legacy_request_key_backfills_context_without_losing_followups(self):
        path = self.data / 'ceo-proposals.json'
        context = dict(project='threads', account='a', reasonCode='submission_unknown', resumeCondition='receipt_verified')
        path.write_text(json.dumps({'proposals': [{'id': 'legacy', 'actor': 'jarvis', 'requestKey': 'stable',
            'status': 'pending_ceo', 'createdAt': 1, 'followups': [{'fingerprint': 'historical'}]}]}), encoding='utf-8')
        with patch.object(bridge, 'CEO_PROPOSALS_FILE', path), patch.object(bridge, '_deliver'):
            result = bridge.emit_ceo_proposal('jarvis', 'Request', 'Current observation', 'Restore', ['Support'],
                                              request_key='stable', blocker_context=context)
            self.assertEqual(result['proposal']['id'], 'legacy')
            self.assertEqual(result['proposal']['blockerContext'], context)
            self.assertEqual(result['proposal']['followups'][0]['fingerprint'], 'historical')


if __name__ == '__main__':
    unittest.main()
