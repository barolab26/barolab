"""Audited closure/restart failures using isolated receipts; never invoke live workers."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch, Mock

from common import work_agenda as agenda


class AgendaOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'dashboard/data'
        for field, value in [('DATA', self.data), ('STATE', self.data/'active-agenda.json'),
                             ('ROWS', self.data/'publication-conferences/operations')]:
            patched = patch.object(agenda, field, value)
            patched.start(); self.addCleanup(patched.stop)
        from common import operating_plan, llm_usage
        for module,field,value in [(operating_plan,'ROOT',self.root),(operating_plan,'DATA',self.data),
                                   (operating_plan,'STATE',self.data/'operating-plan.json'),(llm_usage,'ROOT',self.root)]:
            mocked=patch.object(module,field,value);mocked.start();self.addCleanup(mocked.stop)
        self.now = dt.datetime.now(dt.timezone.utc)
        self.url = 'https://example.com/article'
        agenda.write(agenda.STATE, {'enabled': True})
        from common import crew_chat_bridge as bridge
        for field, value in [('CEO_PROPOSALS_FILE', self.data/'ceo-proposals.json')]:
            mocked = patch.object(bridge, field, value); mocked.start(); self.addCleanup(mocked.stop)
        mocked = patch.object(bridge, '_deliver'); mocked.start(); self.addCleanup(mocked.stop)

    def row(self, kind='cro_widget_retrofit', source=None):
        identity = agenda.propose(kind, str(kind)+str(source), title='Scoped task', project='legacy_remodel',
            source={'targetUrl': self.url, **(source or {})}, completion='Exact requested scope', inherit=False)
        row = agenda.get(identity)
        row['createdAt'] = self.now.timestamp()-10
        agenda._save(row)
        return row

    def receipt(self, **result):
        return {'verified': True, 'source': 'receipt.json', 'result': {'status': 'completed',
            'posts': [{'url': self.url, 'apiStatus': 200, 'verifiedAt': self.now.isoformat(),
                       'durableSuccess': True, 'publicContentMatched': True}], **result}}

    def held(self):
        row = self.row()
        row.update(auxiliaryResult={'status': 'held', 'updatedCount': 0,
            'holds': [{'reason': 'independent_factual_review_required'}]})
        agenda._save(row)
        return row

    def test_doctor_held_never_closes_and_followup_is_deduplicated(self):
        row = self.held()
        for _ in range(2):
            agenda.close_and_advance(row['id'])
        saved = agenda.get(row['id'])
        self.assertEqual(saved['status'], 'blocked')
        self.assertEqual(saved['outcome']['status'], 'held')
        self.assertEqual(saved['nextAction'], 'independent_factual_review')
        followups = agenda.load(agenda.STATE)['unresolvedWork']
        self.assertEqual(len(followups), 1)
        self.assertEqual(next(iter(followups.values()))['owner'], 'doctor')
        self.assertFalse(next(iter(followups.values()))['autoRetry'])

    def test_radar_nested_name_error_wins_over_completed_flag(self):
        row = self.row('radar')
        evidence = self.receipt(posts=[], blokeyCount=0, scout={'status': 'completed',
            'sources': [{'errorType': 'NameError', 'status': 'failed'}]})
        self.assertFalse(agenda.verified(row['id'], evidence))
        self.assertEqual(agenda.get(row['id'])['outcome']['status'], 'error')

    def test_brunch_idle_ok_is_not_publication(self):
        row = self.row('brunch_publish')
        outcome = agenda.task_outcome(row, self.receipt(posts=[], ok=True, status='idle'))
        self.assertEqual(outcome['status'], 'idle')
        self.assertIn('publication_receipt', outcome['missingScope'])

    def test_submission_success_is_not_broad_directive_completion(self):
        row = self.row('indexnow_unindexed_push', {'directive': 'Investigate all domains, CTR and indexing causes'})
        evidence = self.receipt(posts=[], pingedUrls=[{'url': self.url, 'accepted': True,
            'results': [{'httpStatus': 202}]}])
        self.assertEqual(agenda.task_outcome(row, evidence)['status'], 'partial')
        self.assertIn('requested_directive', agenda.task_outcome(row, evidence)['missingScope'])
        narrow = self.row('indexnow_unindexed_push')
        self.assertEqual(agenda.task_outcome(narrow, evidence)['status'], 'completed')

    def test_valid_result_and_all_explicit_acceptance_complete(self):
        row = self.row(source={'acceptanceRequirements': ['target_intervention', 'factual_review']})
        proof = self.receipt()
        self.assertEqual(agenda.task_outcome(row, proof)['status'], 'partial')
        receipt_path = self.data/'host-review.json'
        agenda.write(receipt_path, {'producer': 'barolab-host-acceptance-v1', 'agendaId': row['id'],
            'scope': row['completionCriteria'], 'verifiedAt': self.now.timestamp(), 'requirements': {'factual_review': True}})
        proof['acceptanceResults'] = {'factual_review': {'source': str(receipt_path),
            'sha256': hashlib.sha256(receipt_path.read_bytes()).hexdigest()}}
        self.assertTrue(agenda.verified(row['id'], proof))
        self.assertEqual(agenda.get(row['id'])['outcome']['status'], 'completed')

    def test_null_errors_do_not_fail_and_unrelated_target_cannot_pass(self):
        row = self.row()
        self.assertEqual(agenda.task_outcome(row, self.receipt(error=None))['status'], 'completed')
        self.assertNotEqual(agenda.task_outcome(row, self.receipt(posts=[
            {'url': self.url+'/other', 'apiStatus': 200, 'verifiedAt': self.now.isoformat()}]))['status'], 'completed')

    def test_pending_external_effect_never_replays_after_restart(self):
        row = self.row()
        row.update(status='meeting', auxiliaryStartedAt=self.now.timestamp()-86400,
                   events={'opening': {'receivedAt': 1}})
        agenda._save(row)
        with patch.object(agenda, 'flush_events'), patch.object(agenda, 'execution') as execute:
            agenda._step_single_agenda(row)
            execute.assert_not_called()
        self.assertEqual(agenda.get(row['id'])['blocker'], 'external_effect_unknown')

    def experiment(self):
        base = {'url': self.url, 'source': 'GA4', 'timezone': 'UTC', 'complete': True,
                'checkedAt': self.now.isoformat(), 'start': str(self.now.date()-dt.timedelta(days=7)),
                'end': str(self.now.date()-dt.timedelta(days=1)), 'pageViews': 30}
        return agenda.bind_business_experiment({'targetUrl': self.url, 'hypothesis': 'Improve navigation',
            'measurementDate': str(self.now.date()), 'evidenceConfidence': 'low', 'maxModelCalls': 4,
            'primaryMetric': 'pageViews', 'measurementWindowDays': 7, 'minimumSample': 30,
            'successMetric': 'observed increase', 'stopCondition': 'one observation window'},
            {'pageObservations': [base]}, ['legacy_remodel'], now=self.now.timestamp())

    def test_observation_waits_for_exact_intervention_receipt_and_survives_reload(self):
        experiment = self.experiment()
        self.assertIsNone(experiment['observationStart'])
        self.assertEqual(agenda.evaluate_business_experiment(experiment, {})['reason'], 'waiting_intervention')
        self.assertFalse(agenda.experiment_observation_closed(experiment, {'status': 'inconclusive'}, self.now.timestamp()+86400*40))
        row = self.row(source={'experimentId': experiment['id']})
        agenda.write(agenda.STATE, {'activeExperiment': experiment})
        self.assertTrue(agenda.verified(row['id'], self.receipt()))
        saved = agenda.load(agenda.STATE)['activeExperiment']
        self.assertEqual(saved['observationStart'], str(self.now.date()+dt.timedelta(days=1)))
        self.assertEqual(saved['nextMeasureDate'], str(self.now.date()+dt.timedelta(days=8)))
        self.assertEqual(agenda.start_experiment_observation(saved, row, self.receipt()), saved)
        self.assertEqual(saved['maxModelCalls'], 4)

    def test_dry_run_reconcile_is_read_only_and_changed_input_rejected(self):
        row = self.held(); row['status'] = 'closed'; row['closedAt'] = 12; agenda._save(row)
        before = agenda.path(row['id']).read_bytes()
        preview = agenda.reconcile_task_outcomes([row['id']])
        self.assertEqual(agenda.path(row['id']).read_bytes(), before)
        self.assertEqual(preview['changes'][0]['outcome']['status'], 'held')
        agenda.write(agenda.STATE, {'changed': True})
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            agenda.reconcile_task_outcomes([row['id']], apply=True, expected_fingerprint=preview['fingerprint'])
        preview = agenda.reconcile_task_outcomes([row['id']])
        agenda.reconcile_task_outcomes([row['id']], apply=True, expected_fingerprint=preview['fingerprint'])
        corrected = agenda.get(row['id'])
        self.assertEqual(corrected['closedAt'], 12)
        self.assertEqual(corrected['auxiliaryResult'], row['auxiliaryResult'])
        self.assertEqual(corrected['outcomeCorrections'][0]['previousStatus'], 'closed')

    def test_executive_health_runs_before_future_observation_without_model(self):
        from agents import crew_reasoning as crew
        from common import llm_client
        from server import growth
        experiment = self.experiment()
        agenda.write(agenda.STATE, {'activeExperiment': experiment})
        row = self.held()
        with patch.object(agenda, 'prune_stale_runtime_data'), patch.object(agenda, '_top_up_channel_lanes'), \
             patch.object(agenda, '_build_live_executive_diagnostics', return_value={}), \
             patch('server.radar_scout.build_daily_winning_topics'), \
             patch.object(crew, 'overview', return_value={'projects': [], 'businessEvidence': {}}), \
             patch.object(growth, 'measurement_followups', return_value=[]), \
             patch.object(agenda, 'dispatch_evidence_review_once'), patch.object(llm_client, 'generate_json') as model:
            self.assertTrue(agenda.company_executive_check_once(force=True))
        model.assert_not_called()
        saved = agenda.load(agenda.STATE)
        self.assertEqual(saved['activeExperiment'], experiment)
        self.assertEqual(saved['executiveHealth']['decisions'][0]['judgment'], 'review_unresolved')
        self.assertEqual(agenda.get(row['id'])['responsibleCrew'], 'doctor')

    def test_review_assignment_dedup_source_proof_and_original_resolution(self):
        from agents import crew_reasoning as crew
        row = self.held(); row['businessExperiment'] = {'id': 'shared-budget', 'maxModelCalls': 4}
        agenda._save(row); agenda.close_and_advance(row['id'])
        goal_id = 'c'*64
        goal_path = self.data/'goals'/f'{goal_id}.json'
        with patch.object(crew, 'reason_request', return_value={'id': goal_id}) as assign, \
             patch.object(crew, 'goal_path', return_value=goal_path), patch.object(crew, 'ROOT', self.root):
            self.assertTrue(agenda.dispatch_evidence_review_once())
            self.assertFalse(agenda.dispatch_evidence_review_once())
            self.assertEqual(assign.call_count, 1)
            self.assertFalse(assign.call_args.kwargs['execute'])
            self.assertFalse(assign.call_args.kwargs['repair'])
            self.assertEqual(assign.call_args.kwargs['max_steps'], 4)
            agenda.write(goal_path, {'id': goal_id, 'status': 'answered', 'answer': 'status healthy',
                'observations': [{'tool': 'project_status', 'result': {'sha256': 'status-hash'}}]})
            agenda.dispatch_evidence_review_once()
            followup = agenda.load(agenda.STATE)['unresolvedWork']['agenda:'+row['id']]
            self.assertEqual(followup['reviewOutcome']['status'], 'missing_source_evidence')
            self.assertNotEqual(followup['status'], 'resolved')
            source_proof = crew.tool_call({'origin': 'evidence-review', 'permissions': {'execute': False, 'repair': False}},
                                         'evidence', {'name': 'agenda:'+row['id']})
            self.assertEqual(source_proof['sha256'], hashlib.sha256(agenda.path(row['id']).read_bytes()).hexdigest())
            agenda.write(goal_path, {'id': goal_id, 'status': 'answered', 'observations': [
                {'tool': 'evidence', 'result': source_proof}]})
            agenda.dispatch_evidence_review_once()
            self.assertEqual(agenda.load(agenda.STATE)['unresolvedWork']['agenda:'+row['id']]['reviewOutcome']['status'], 'reviewed_unresolved')
            # A trusted adapter subsequently supplies the missing actual operation receipt.
            original = agenda.get(row['id']); original['verification'] = self.receipt(); agenda._save(original)
            agenda.dispatch_evidence_review_once()
            self.assertEqual(agenda.load(agenda.STATE)['unresolvedWork']['agenda:'+row['id']]['status'], 'resolved')

    def measurement_fixture(self):
        from server.growth import measurement_followups
        from agents import crew_reasoning as crew
        folder = self.root/'cf_posting/output/scheduled/2026-11-03/soulnote.kr'
        agenda.write(folder/'publication-receipt.json', {'state': 'published', 'publicUrl': self.url,
                                                       'verifiedAt': self.now.isoformat()})
        agenda.write(folder/'planning.json', {'keyword': 'insurance refund'})
        agenda.write(folder/'research.json', {'keyword': 'insurance refund', 'requestedKeyword': 'insurance refund'})
        agenda.write(folder/'article.json', {'mainKeyword': 'unrelated tax service', 'title': 'Tax service'})
        followup = next(f for f in measurement_followups(self.data, self.now) if f['key'].startswith('review:cf-topic:'))
        followup['key'] = 'measurement:' + followup['key']
        agenda.write(agenda.STATE, {'enabled': True, 'unresolvedWork': {followup['key']: followup},
            'activeExperiment': {'id': 'shared-existing-experiment', 'maxModelCalls': 12}})
        for field, value in [('ROOT', self.root), ('GOALS', self.data/'crew-goals')]:
            mocked = patch.object(crew, field, value)
            mocked.start(); self.addCleanup(mocked.stop)
        def assign(request_id, question, **kwargs):
            goal = {'id': hashlib.sha256(request_id.encode()).hexdigest(), 'goal': question,
                'businessAgendaId': kwargs['agenda_id'], 'origin': kwargs['origin'],
                'permissions': {'execute': kwargs['execute'], 'repair': kwargs['repair']},
                'status': 'ready', 'decisions': 0, 'maxSteps': kwargs['max_steps'], 'observations': []}
            crew.save(goal)
            return goal
        mocked = patch.object(crew, 'reason_request', side_effect=assign)
        assign_mock = mocked.start(); self.addCleanup(mocked.stop)
        return crew, followup['key'], folder/'research.json', assign_mock

    def test_real_measurement_source_registered_preload_and_scope_validation(self):
        crew, key, source, assign = self.measurement_fixture()
        self.assertTrue(agenda.dispatch_evidence_review_once())
        item = agenda.load(agenda.STATE)['unresolvedWork'][key]
        goal = agenda.load(crew.goal_path(item['reviewGoalId']))
        proof = goal['observations'][0]['result']
        self.assertEqual(proof['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(proof['source'], str(source.relative_to(self.root)))
        self.assertEqual(proof['evidenceName'], crew.measurement_evidence_name(key))
        self.assertEqual(proof['data']['keyword'], 'insurance refund')
        self.assertIn(proof['sha256'], goal['goal'])
        self.assertEqual(agenda._scoped_review_reads(item, {}, goal, crew), [])
        agenda.dispatch_evidence_review_once()
        self.assertEqual(assign.call_count, 1)
        goal.update(status='answered', decisions=1, answer='Original source read; further claims and public page remain unverified')
        self.assertEqual(agenda._scoped_review_reads(item, {}, goal, crew), [])
        goal['evidenceIds'] = [goal['observations'][0]['id']]
        self.assertEqual(agenda._scoped_review_reads(item, {}, {**goal, 'answerSource': 'host'}, crew), [])
        crew.save(goal)
        agenda.dispatch_evidence_review_once()
        saved = agenda.load(agenda.STATE)['unresolvedWork'][key]
        self.assertEqual(saved['reviewOutcome']['status'], 'reviewed_unresolved')
        self.assertFalse(saved['reviewOutcome']['businessOutcomeVerified'])
        self.assertEqual(saved['reviewOutcome']['sourceReads'][0]['coverage'], 'returned_page')
        self.assertEqual(saved['status'], 'blocked')
        for field, value in [('source', 'dashboard/data/live_snapshot.json'), ('evidenceName', 'execution'),
                             ('followupKey', 'measurement:other'), ('sha256', '0'*64)]:
            with self.subTest(field=field):
                bad = json.loads(json.dumps(goal)); bad['observations'][0]['result'][field] = value
                self.assertEqual(agenda._scoped_review_reads(item, {}, bad, crew), [])
        batch = {**goal, 'observations': [{'tool': 'evidence_batch', 'result': proof}]}
        self.assertEqual(agenda._scoped_review_reads(item, {}, batch, crew), [])
        actual = crew.tool_call(goal, 'evidence', {'name': crew.measurement_evidence_name(key)})
        model_read = {**goal, 'observations': [{'id': 'e-model-read', 'actor': 'doctor', 'tool': 'evidence', 'result': actual}]}
        self.assertEqual(agenda._scoped_review_reads(item, {}, model_read, crew), [])
        model_read['evidenceIds'] = ['e-model-read']
        self.assertEqual(len(agenda._scoped_review_reads(item, {}, model_read, crew)), 1)
        partial = json.loads(json.dumps(goal['observations'][0]))
        partial['result']['data'] = {'sources': {'detailRequired': True, 'readWith': {'select': ['sources']}}}
        self.assertEqual(agenda._review_source_coverage(partial)['coverage'], 'partial')
        partial['result']['data'] = {}; partial['result']['pagination']['truncated'] = True
        self.assertEqual(agenda._review_source_coverage(partial)['coverage'], 'partial')
        agenda.write(source, {'keyword': 'new material input'})
        self.assertEqual(agenda._scoped_review_reads(item, {}, goal, crew), [])

    def test_generic_execution_evidence_corrected_without_false_completion(self):
        crew, key, source, assign = self.measurement_fixture()
        agenda.dispatch_evidence_review_once()
        state = agenda.load(agenda.STATE); item = state['unresolvedWork'][key]
        agenda.write(self.data/'live_snapshot.json', {'generatedAt': 'now', 'panels': []})
        goal = agenda.load(crew.goal_path(item['reviewGoalId']))
        generic = crew.tool_call(goal, 'evidence', {'name': 'execution'})
        goal.update(status='answered', decisions=3, observations=[{'actor': 'doctor', 'tool': 'evidence', 'result': generic}])
        crew.save(goal)
        item['reviewOutcome'] = {'status': 'reviewed_unresolved', 'evidenceHashes': [generic['sha256']]}
        agenda.write(agenda.STATE, state)
        agenda.dispatch_evidence_review_once()
        saved = agenda.load(agenda.STATE)['unresolvedWork'][key]
        self.assertEqual(saved['reviewOutcome']['status'], 'scoped_source_review_missing')
        self.assertEqual(saved['reviewOutcomeCorrections'][0]['previous']['status'], 'reviewed_unresolved')
        self.assertEqual(saved['reviewGoalId'], goal['id'])
        self.assertEqual(agenda.load(crew.goal_path(goal['id']))['decisions'], 3)
        self.assertEqual(assign.call_count, 1)

    def test_exhausted_measurement_correction_retains_budget_history_and_cap(self):
        crew, key, source, assign = self.measurement_fixture()
        agenda.dispatch_evidence_review_once()
        state = agenda.load(agenda.STATE); item = state['unresolvedWork'][key]
        old_goal = agenda.load(crew.goal_path(item['reviewGoalId']))
        old_goal.update(status='answered', decisions=4, observations=[], resolution={'status': 'advice_only'})
        crew.save(old_goal)
        old_bytes = crew.goal_path(old_goal['id']).read_bytes()
        state['activeExperiment'] = {'id': 'different-new-experiment', 'maxModelCalls': 50}
        agenda.write(agenda.STATE, state)
        from common import llm_usage
        with patch.object(llm_usage, 'check_budget', side_effect=llm_usage.UsageBudgetExceeded('agenda_call_budget_exhausted')):
            agenda.dispatch_evidence_review_once()
        self.assertEqual(agenda.load(agenda.STATE)['unresolvedWork'][key]['reviewGoalId'], old_goal['id'])
        agenda.dispatch_evidence_review_once()
        corrected = agenda.load(agenda.STATE)['unresolvedWork'][key]
        self.assertEqual(corrected['reviewHistory'][0]['reviewGoalId'], old_goal['id'])
        self.assertEqual(corrected['reviewHistory'][0]['reviewOutcome']['status'], 'scoped_source_review_missing')
        self.assertEqual(crew.goal_path(old_goal['id']).read_bytes(), old_bytes)
        self.assertTrue(agenda.dispatch_evidence_review_once())
        new = agenda.load(agenda.STATE)['unresolvedWork'][key]
        self.assertNotEqual(new['reviewGoalId'], old_goal['id'])
        self.assertEqual(agenda.get(new['reviewAgendaId'])['businessExperiment']['id'], 'shared-existing-experiment')
        self.assertEqual(assign.call_count, 2)
        new_goal = agenda.load(crew.goal_path(new['reviewGoalId']))
        new_goal.update(status='answered', decisions=4, observations=[])
        crew.save(new_goal)
        agenda.dispatch_evidence_review_once()
        self.assertEqual(agenda.load(agenda.STATE)['unresolvedWork'][key]['reviewGoalId'], new_goal['id'])
        self.assertEqual(assign.call_count, 2)
        capped = agenda.load(agenda.STATE); capped['unresolvedWork'][key].pop('sourceReviewCapability')
        capped['unresolvedWork'][key]['reviewHistory'] *= 2
        agenda.write(agenda.STATE, capped)
        agenda.dispatch_evidence_review_once()
        self.assertEqual(agenda.load(agenda.STATE)['unresolvedWork'][key]['reviewGoalId'], new_goal['id'])

    def test_shared_budget_exhaustion_holds_different_followups_and_deduplicates_ceo(self):
        crew, key, source, assign = self.measurement_fixture()
        state = agenda.load(agenda.STATE)
        experiment = {'id': 'shared-existing-experiment', 'maxModelCalls': 20,
                      'targetUrl': 'https://example.com/shared-experiment'}
        state['activeExperiment'] = experiment
        other = 'measurement:review:second-target'
        state['unresolvedWork'][other] = {**state['unresolvedWork'][key], 'key': other,
                                         'target': 'https://different.example/article'}
        agenda.write(agenda.STATE, state)
        ledger = {'byExperiment': {experiment['id']: {'modelCalls': 20}}}
        agenda.write(self.data/'llm_usage_ledger.json', ledger)
        before_rows = list(agenda.ROWS.glob('*.json'))
        for _ in range(2):
            self.assertFalse(agenda.dispatch_evidence_review_once())
        saved = agenda.load(agenda.STATE)
        for identity in (key, other):
            item = saved['unresolvedWork'][identity]
            self.assertEqual(item['reviewBudgetHold']['reasonCode'], 'experiment_call_budget_exhausted')
            self.assertEqual(item['reviewBudgetHold']['owner'], 'doctor')
            self.assertEqual(item['nextAction'], 'await_budget_decision')
            self.assertNotIn('reviewGoalId', item)
        proposals = agenda.load(self.data/'ceo-proposals.json')['proposals']
        self.assertEqual(len(proposals), 1); self.assertEqual(len(proposals[0]['originalWorkRefs']), 2)
        self.assertFalse(proposals[0]['resumeAuthorized'])
        self.assertEqual(list(agenda.ROWS.glob('*.json')), before_rows); assign.assert_not_called()
        # A later unrelated active experiment cannot silently replace the held resource budget.
        saved['activeExperiment'] = {'id': 'new-unrelated', 'maxModelCalls': 100}
        agenda.write(agenda.STATE, saved)
        self.assertFalse(agenda.dispatch_evidence_review_once()); assign.assert_not_called()
        self.assertEqual(len(agenda.load(self.data/'ceo-proposals.json')['proposals']), 1)
        self.assertEqual(agenda.load(self.data/'llm_usage_ledger.json'), ledger)

    def test_shared_review_budget_counts_inflight_and_underbudget_dispatch_preserves_limit(self):
        crew, key, source, assign = self.measurement_fixture()
        experiment = agenda.load(agenda.STATE)['activeExperiment']
        ledger = {'byExperiment': {experiment['id']: {'modelCalls': 11}},
                  'active': {'inflight': {'experimentId': experiment['id']}}}
        agenda.write(self.data/'llm_usage_ledger.json', ledger)
        self.assertFalse(agenda.dispatch_evidence_review_once()); assign.assert_not_called()
        ledger['active'] = {}; agenda.write(self.data/'llm_usage_ledger.json', ledger)
        self.assertTrue(agenda.dispatch_evidence_review_once()); self.assertEqual(assign.call_count, 1)
        item = agenda.load(agenda.STATE)['unresolvedWork'][key]
        self.assertEqual(agenda.get(item['reviewAgendaId'])['businessExperiment'], experiment)
        self.assertEqual(agenda.load(self.data/'llm_usage_ledger.json'), ledger)

    def test_unreachable_measurement_source_never_dispatches_model(self):
        crew, key, source, assign = self.measurement_fixture()
        source.unlink()
        self.assertFalse(agenda.dispatch_evidence_review_once())
        saved = agenda.load(agenda.STATE)['unresolvedWork'][key]
        self.assertEqual(saved['nextAction'], 'establish_registered_scoped_source_access')
        assign.assert_not_called()

    def test_read_only_staff_acceptance_requires_every_requested_action(self):
        row = self.row('staff', {'actions': [{'tool': 'read_agent_status'}, {'tool': 'read_agent_status'}]})
        evidence = {'verified': True, 'source': 'staff.json', 'results': [{'ok': True}]}
        self.assertNotEqual(agenda.task_outcome(row, evidence)['status'], 'completed')
        evidence['results'].append({'ok': True})
        self.assertEqual(agenda.task_outcome(row, evidence)['status'], 'completed')

    def test_api_only_receipt_and_fabricated_acceptance_do_not_complete(self):
        row = self.row(source={'directive': 'Verify factual scope'})
        proof = self.receipt()
        proof['result']['posts'][0].pop('publicContentMatched')
        proof['acceptanceResults'] = {'requested_directive': {'verified': True, 'source': 'pretend.json',
                                                             'scope': 'Verify factual scope'}}
        self.assertNotEqual(agenda.task_outcome(row, proof)['status'], 'completed')
        self.assertIn('target_intervention', agenda.task_outcome(row, proof)['missingScope'])

    def test_zero_candidate_scan_can_complete_only_its_explicit_scan_scope(self):
        row = self.row('radar', {'acceptanceRequirements': ['source_scan'], 'scanScope': ['official-feed']})
        proof = self.receipt(posts=[], candidates=[], scanScope=['official-feed'], sources=[
            {'status': 'collected', 'fetchedAt': self.now.isoformat()}])
        self.assertEqual(agenda.task_outcome(row, proof)['status'], 'completed')
        proof['result']['sources'][0]['fetchedAt'] = (self.now-dt.timedelta(days=3)).isoformat()
        self.assertNotEqual(agenda.task_outcome(row, proof)['status'], 'completed')

    def test_stale_baseline_blocks_new_work_without_discarding_existing(self):
        experiment = self.experiment()
        experiment['baseline']['checkedAt'] = (self.now-dt.timedelta(days=3)).isoformat()
        self.assertFalse(agenda.autonomous_experiment_allows('legacy_remodel', domain='example.com',
                                                           state={'activeExperiment': experiment}))

    def test_explicit_acceptance_cannot_drop_original_directive(self):
        row = self.row(source={'directive': 'Review all requested claims', 'acceptanceRequirements': ['target_intervention']})
        evidence = self.receipt()
        self.assertEqual(agenda.task_outcome(row, evidence)['status'], 'partial')
        self.assertIn('requested_directive', agenda.task_outcome(row, evidence)['required'])
        host_receipt = self.data/'host-acceptance.json'
        agenda.write(host_receipt, {'producer': 'barolab-host-acceptance-v1', 'agendaId': row['id'],
            'scope': row['source']['directive'], 'verifiedAt': self.now.timestamp(), 'requirements': {'requested_directive': True}})
        evidence['acceptanceResults'] = {'requested_directive': {'source': str(host_receipt),
            'sha256': hashlib.sha256(host_receipt.read_bytes()).hexdigest()}}
        self.assertEqual(agenda.task_outcome(row, evidence)['status'], 'completed')
        host_receipt.write_text('{}', encoding='utf-8')
        self.assertEqual(agenda.task_outcome(row, evidence)['status'], 'partial')

    def test_measurement_clock_only_changes_dedup_and_material_change_gets_bounded_review(self):
        from server import growth
        followup = {'key': 'source:account', 'owner': 'trace', 'target': 'account', 'status': 'blocked',
            'sourceRef': str(self.data/'revenue.json'), 'sourceCheckedAt': self.now.isoformat(),
            'dueAt': self.now.timestamp(), 'reason': 'auth_required', 'acceptance': ['source report']}
        key = 'measurement:source:account'
        with patch.object(growth, 'measurement_followups', return_value=[followup]), \
             patch.object(agenda, 'dispatch_evidence_review_once'):
            agenda.executive_health_check({})
            state = agenda.load(agenda.STATE)
            state['unresolvedWork'][key].update(reviewGoalId='old', reviewOutcome={'status': 'reviewed_unresolved'})
            agenda.write(agenda.STATE, state)
            followup['sourceCheckedAt'] = (self.now+dt.timedelta(minutes=5)).isoformat()
            followup['dueAt'] += 300
            agenda.executive_health_check({})
            self.assertEqual(agenda.load(agenda.STATE)['unresolvedWork'][key]['reviewGoalId'], 'old')
            followup['reason'] = 'missing_report_dates'
            agenda.executive_health_check({})
            saved = agenda.load(agenda.STATE)['unresolvedWork'][key]
            self.assertNotIn('reviewGoalId', saved)
            self.assertEqual(len(saved['reviewHistory']), 1)
            followup.update(status='resolved', reason=None)
            agenda.executive_health_check({})
            saved = agenda.load(agenda.STATE)['unresolvedWork'][key]
            self.assertEqual(saved['status'], 'resolved')
            self.assertIsNone(saved['blocker'])

    def test_legacy_budget_is_never_reset_by_new_review_identity(self):
        from agents import crew_reasoning as crew
        row = self.held(); row['businessExperiment'] = {'maxModelCalls': 20}
        agenda._save(row); agenda.close_and_advance(row['id'])
        with patch.object(crew, 'reason_request') as dispatch:
            self.assertFalse(agenda.dispatch_evidence_review_once())
        dispatch.assert_not_called()
        self.assertEqual(agenda.load(agenda.STATE)['unresolvedWork']['agenda:'+row['id']]['nextAction'],
                         'host_review_required_missing_shared_budget')

    def test_reconcile_never_reactivates_explicitly_stopped_experiment(self):
        row = self.held()
        row['source']['experimentId'] = 'stopped'; agenda._save(row)
        experiment = {'id': 'stopped', 'status': 'stopped', 'observationStart': '2026-11-04'}
        agenda.write(agenda.STATE, {'activeExperiment': experiment})
        plan = agenda.reconcile_task_outcomes([row['id']])
        self.assertFalse(plan['resetObservationClock'])
        agenda.reconcile_task_outcomes([row['id']], apply=True, expected_fingerprint=plan['fingerprint'])
        self.assertEqual(agenda.load(agenda.STATE)['activeExperiment'], experiment)

    def run_real_cro_producer(self, public_matches=True, additional_requirements=(), public_timeout=False):
        from common import cf_tables
        from cf_posting import posting
        experiment = self.experiment()
        agenda.write(agenda.STATE, {'enabled': True, 'activeExperiment': experiment})
        identity = agenda._queue_autonomous_work_order('cro_widget_retrofit', target_domain='example.com',
            rationale='Improve existing navigation', additional_requirements=additional_requirements)
        row = agenda.get(identity)
        original = {'id': 1, 'slug': 'article', 'title': 'Desk organization', 'status': 'published',
            'content': '<h2>Sort the desk</h2><p>Place supplies together.</p><h2>Store papers</h2><p>Use a folder.</p>'}
        stored = dict(original)
        def put(url, **kwargs):
            stored.update(kwargs['json'])
            return Mock(status_code=200)
        def get(url, **kwargs):
            if '/api/posts/' in url:
                return Mock(status_code=200, json=lambda: {'post': dict(stored)})
            if public_timeout:
                raise TimeoutError('public read timed out after accepted PUT')
            html = stored['content'] if public_matches else original['content']
            return Mock(status_code=200, text='<h1>Desk organization</h1><article class="content">'+html+'</article>')
        with patch.object(posting, 'cleaner_lock', return_value=nullcontext(True)), \
             patch.object(posting, 'published_inventory', return_value=[original]), \
             patch.object(posting, 'get_api_key', return_value='test-key'), \
             patch.object(cf_tables, 'purge_repaired_posts', return_value={}), \
             patch('requests.put', side_effect=put) as update, patch('requests.get', side_effect=get), patch('time.sleep'):
            result = cf_tables.retrofit_cro_widgets_and_tables(root=self.root, domains=['example.com'], target_urls=[self.url])
        self.assertEqual(update.call_count, 1)
        return row, result

    def test_real_cro_producer_completes_typed_executive_scope_and_starts_clock(self):
        row, result = self.run_real_cro_producer()
        self.assertIsNotNone(agenda.admit(row['id']))
        agenda.record_plan(row['id'], ['Verify the exact stored and public replacement'])
        self.assertEqual(row['acceptanceRequirements'], ['target_intervention'])
        self.assertEqual(row['source']['executionContract']['targetUrl'], self.url)
        self.assertEqual(row['source']['directive'], '')
        self.assertTrue(result['posts'][0]['durableSuccess'])
        receipt_file = Path(result['reportDir'])/'example.com/1/receipt.json'
        self.assertTrue(agenda.load(receipt_file)['publicContentMatched'])
        self.assertTrue(agenda.verified(row['id'], {'verified': True, 'source': str(receipt_file), 'result': result}))
        saved = agenda.load(agenda.STATE)['activeExperiment']
        self.assertEqual(saved['observationState'], 'observing')
        self.assertEqual(saved['interventionReceipt']['contentSha256'], result['posts'][0]['contentSha256'])
        self.assertEqual(agenda.get(row['id'])['outcome']['status'], 'completed')
        def acknowledge_reports(identity):
            current = agenda.get(identity)
            for event in current['events'].values():
                event['receivedAt'] = self.now.timestamp()
            agenda._save(current)
            return True
        with patch.object(agenda, 'flush_events', side_effect=acknowledge_reports):
            self.assertTrue(agenda.finish_reports(row['id']))
        self.assertEqual(agenda.get(row['id'])['status'], 'closed')

    def test_real_cro_api_success_with_old_public_body_cannot_start_clock(self):
        row, result = self.run_real_cro_producer(public_matches=False)
        self.assertFalse(result['posts'][0]['durableSuccess'])
        self.assertFalse(agenda.verified(row['id'], {'verified': True, 'source': result['reportDir'], 'result': result}))
        self.assertEqual(agenda.load(agenda.STATE)['activeExperiment']['observationState'], 'waiting_intervention')

    def test_accepted_put_then_public_timeout_preserves_pending_receipt_without_replay(self):
        row, result = self.run_real_cro_producer(public_timeout=True)
        receipt = agenda.load(Path(result['reportDir'])/'example.com/1/receipt.json')
        self.assertTrue(receipt['apiAccepted'])
        self.assertEqual(receipt['apiStatus'], 200)
        self.assertTrue(receipt['pendingEffect'])
        self.assertEqual(receipt['nextAction'], 'verify_existing_external_receipt')
        self.assertEqual(result['status'], 'held')
        self.assertFalse(agenda.verified(row['id'], {'verified': True, 'source': result['reportDir'], 'result': result}))
        self.assertEqual(agenda.get(row['id'])['nextAction'], 'verify_existing_external_receipt')
        self.assertEqual(agenda.load(agenda.STATE)['activeExperiment']['observationState'], 'waiting_intervention')

    def test_unknown_extra_scope_is_held_before_execution_and_not_erased(self):
        experiment = self.experiment()
        agenda.write(agenda.STATE, {'enabled': True, 'activeExperiment': experiment})
        identity = agenda._queue_autonomous_work_order('cro_widget_retrofit', target_domain='example.com',
            rationale='Good reason', additional_requirements=['Verify every government claim and all domain traffic'])
        row = agenda.get(identity)
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['blocker'], 'unsupported_requested_scope')
        self.assertIn('requested_directive', row['acceptanceRequirements'])
        self.assertIn('government', row['source']['directive'])
        self.assertIsNone(agenda.admit(identity))
        with patch.object(agenda, 'execution') as execute:
            self.assertFalse(agenda._step_single_agenda(row))
        execute.assert_not_called()

    def test_actual_doctor_public_receipt_shape_is_consumed_without_fabricated_proof(self):
        from server import doctor
        row = self.row()
        post = {'id': '1', 'title': 'Real title', 'content': '<p>Replacement body</p>',
                'thumbnail': 'https://example.com/image.jpg'}
        with patch.object(doctor, 'DOCTOR_LEDGER_PATH', self.data/'doctor.json'), \
             patch.object(doctor, 'find_live_cf_post', return_value=post), \
             patch.object(doctor, 'find_local_output_runs', return_value=[]), \
             patch.object(doctor, '_get_cf_headers', return_value={}), \
             patch.object(doctor, '_infer_cf_post_search_keyword', return_value=''), \
             patch('dashboard.common.cf_tables.style_tables', side_effect=lambda x, **kw: x), \
             patch('dashboard.common.cf_tables.inject_interactive_widget', side_effect=lambda x, **kw: x), \
             patch.object(doctor.requests, 'put', return_value=Mock(status_code=200)), \
             patch.object(doctor.requests, 'get', return_value=Mock(status_code=200,
                 text='<h1>Real title</h1><article class="content">Replacement body</article>')), \
             patch('cf_posting.posting.ping_indexnow'), patch('common.llm_client.memory_event'):
            result = doctor.remodel_cf_post_by_url(self.url)
        self.assertEqual(result['httpStatus'], 200)
        self.assertTrue(result['durableSuccess'])
        self.assertTrue(agenda.verified(row['id'], {'verified': True, 'source': 'doctor-runtime-receipt', 'result': result}))

    def test_real_index_producer_filters_exact_target_and_preserves_legacy_broad_call(self):
        from common import cf_tables
        from cf_posting import posting
        experiment = self.experiment()
        agenda.write(agenda.STATE, {'enabled': True, 'activeExperiment': experiment})
        identity = agenda._queue_autonomous_work_order('indexnow_unindexed_push', target_domain='example.com',
                                                      rationale='Test submission acceptance only')
        waiting = dict(experiment)
        inventory = [{'id': 1, 'slug': 'unrelated', 'status': 'published'},
                     {'id': 2, 'slug': 'article', 'status': 'published'}]
        with patch.object(posting, 'DATA_DIR', self.data), patch.object(posting, 'published_inventory', return_value=inventory), \
             patch('requests.get', return_value=Mock(status_code=200)), \
             patch.object(posting, 'ping_indexnow', return_value=[{'httpStatus': 202}]) as submit:
            result = cf_tables.push_unindexed_cf_posts(domains=['example.com'], target_urls=[self.url])
            submit.assert_called_once_with('example.com', 'https://www.example.com/article')
            self.assertTrue(agenda.verified(identity, {'verified': True, 'source': 'index-runtime-receipt', 'result': result}))
            experiment = agenda.load(agenda.STATE)['activeExperiment']
            self.assertEqual(experiment['observationState'], 'observing')
            self.assertEqual(experiment['interventionReceipt']['verificationScope'], 'submission_only')
            self.assertEqual(experiment['interventionType'], 'submission')
            self.assertFalse(experiment['interventionReceipt']['indexedVerified'])
            for change in ({'url': self.url+'/other'}, {'verifiedAt': (self.now-dt.timedelta(days=1)).isoformat()},
                           {'results': [{'httpStatus': 403}], 'accepted': False}):
                invalid = {**result, 'pingedUrls': [{**result['pingedUrls'][0], **change}]}
                kept = agenda.start_experiment_observation(waiting, agenda.get(identity),
                    {'verified': True, 'source': 'index-runtime-receipt', 'result': invalid})
                self.assertEqual(kept['observationState'], 'waiting_intervention')
            submit.reset_mock()
            cf_tables.push_unindexed_cf_posts(domains=['example.com'], target_urls=[])
            submit.assert_not_called()
            cf_tables.push_unindexed_cf_posts(domains=['example.com'])
            self.assertEqual(submit.call_count, 2)

    def test_unsupported_original_planner_choices_are_owned_capability_reviews(self):
        experiment = self.experiment()
        agenda.write(agenda.STATE, {'enabled': True, 'activeExperiment': experiment})
        for choice in ('content_audit_patrol', 'radar_high_cpc_scout', 'brunch_daily_publish'):
            identity = agenda._queue_autonomous_work_order(choice, target_domain='example.com', rationale='Inspect capability')
            self.assertTrue(identity)
            row = agenda.get(identity)
            self.assertEqual(row['kind'], 'capability_review')
            self.assertEqual(row['status'], 'blocked')
            self.assertEqual(row['source']['requestedWorkType'], choice)
            self.assertEqual(row['responsibleCrew'], 'patch')
            self.assertEqual(row['businessExperiment']['id'], experiment['id'])
            self.assertEqual(agenda._queue_autonomous_work_order(choice, target_domain='example.com'), identity)
            with patch.object(agenda, 'execution') as execute:
                self.assertFalse(agenda._step_single_agenda(row))
            execute.assert_not_called()

    def test_verified_account_narrows_same_project_recovery_while_preserving_uncertain_and_unverified_locks(self):
        binding_soultin = {'project': 'naver_blog', 'date': '2026-11-08', 'identity': 'soultin', 'slot': '09:00'}
        wid_soultin = hashlib.sha256(json.dumps(binding_soultin, sort_keys=True).encode()).hexdigest()
        binding_adinfo = {'project': 'naver_blog', 'date': '2026-11-08', 'identity': 'adinfo0905', 'slot': '10:00'}
        wid_adinfo = hashlib.sha256(json.dumps(binding_adinfo, sort_keys=True).encode()).hexdigest()
        agenda.write(self.data / 'naver/automation-journal.json', {'attempts': [
            {'account': 'soultin', 'publicationDate': '2026-11-08', 'scheduledSlot': '09:00', 'status': 'failed', 'lastError': 'timeout'},
            {'account': 'adinfo0905', 'publicationDate': '2026-11-08', 'scheduledSlot': '10:00', 'status': 'failed', 'lastError': 'timeout'},
        ]})
        existing_conf = {'id': '1'*64, 'kind': 'conference', 'project': 'naver_blog', 'status': 'recovering',
                         'workTarget': {'arguments': {'action': 'naver', 'account': 'adinfo0905', 'date': '2026-11-08', 'slot': '10:00'}}}
        chosen_soultin = {'id': '2'*64, 'kind': 'staff', 'project': 'naver_blog', 'status': 'queued',
                          'source': {'actions': [{'agent': 'publi', 'tool': 'recover_project_work', 'args': {'project': 'naver_blog', 'work_id': wid_soultin}}]}}
        chosen_adinfo = {'id': '3'*64, 'kind': 'staff', 'project': 'naver_blog', 'status': 'queued',
                         'source': {'actions': [{'agent': 'publi', 'tool': 'recover_project_work', 'args': {'project': 'naver_blog', 'work_id': wid_adinfo}}]}}
        chosen_unknown = {'id': '4'*64, 'kind': 'staff', 'project': 'naver_blog', 'status': 'queued',
                          'source': {'actions': [{'agent': 'publi', 'tool': 'recover_project_work', 'args': {'project': 'naver_blog', 'work_id': 'f'*64}}]}}
        with patch.object(agenda, 'running', return_value=False):
            # Verified distinct account in same project does not collide
            self.assertFalse(agenda.shares_execution_lane(existing_conf, chosen_soultin))
            # Verified same account in same project collides
            self.assertTrue(agenda.shares_execution_lane(existing_conf, chosen_adinfo))
            # Unverified work_id keeps the project lane locked
            self.assertTrue(agenda.shares_execution_lane(existing_conf, chosen_unknown))
            # Uncertain submission state (submitting/unknown/pendingEffect) keeps the project lane locked
            for uncertain in ({**existing_conf, 'status': 'submitting'}, {**existing_conf, 'status': 'unknown'}, {**existing_conf, 'pendingEffect': True}):
                self.assertTrue(agenda.shares_execution_lane(uncertain, chosen_soultin))

    def test_operating_plan_separates_lifecycle_stages_and_binds_decision_verification_fields(self):
        from common import operating_plan as operating
        from agents import crew_reasoning as crew
        now = self.now.timestamp()
        future_iso = (self.now + dt.timedelta(hours=2)).replace(second=0, microsecond=0).isoformat()
        self.assertEqual(operating.lifecycle_stage('preparation_queued'), 'preparing')
        self.assertEqual(operating.lifecycle_stage('preparation_running'), 'preparing')
        self.assertEqual(operating.lifecycle_stage('preparation_failed'), 'preparation_failed')
        self.assertEqual(operating.lifecycle_stage('preparation_unknown'), 'uncertain_or_protected_hold')
        self.assertEqual(operating.lifecycle_stage('preparation_held'), 'uncertain_or_protected_hold')
        self.assertEqual(operating.lifecycle_stage('review_required'), 'preparation_failed')
        self.assertEqual(operating.lifecycle_stage('needs_source_repair'), 'preparation_failed')
        self.assertEqual(operating.lifecycle_stage('prepared'), 'prepared')
        with patch.object(operating, 'ROOT', self.root), patch.object(operating, 'DATA', self.data), \
             patch.object(operating, 'STATE', self.data / 'operating-plan.json'):
            agenda.write(self.data / 'daily_schedule.json', {'operatingMode': 'adaptive', 'cf': {'must-pick.com': {}}, 'naver': {'soultin': {'slots': []}}})
            agenda.write(self.data / 'crew-goals/g1.json', {'id': 'g1', 'observations': [{'id': 'e0'}, {'id': 'e2'}]})
            res = operating.allocate({
                'publications': [{'project': 'cf_blog', 'account': 'must-pick.com', 'publishAt': future_iso,
                                  'topic': '청년월세 지원 절차', 'why': 'Must-pick observed 28d revenue leader',
                                  'expectedOutcome': 'qualified_acquisition_above_baseline',
                                  'verificationMethod': 'cf_publication_receipt_and_inspect_url_acquisition',
                                  'nextCheckAt': future_iso,
                                  'evidenceIds': ['e0', 'e2']}],
                'accounts': [{'project': 'cf_blog', 'account': 'must-pick.com', 'mode': 'expand',
                              'why': 'Observed 28d revenue 0.81 USD', 'reviewAt': future_iso,
                              'expectedOutcome': 'verify_7d_qualified_sessions',
                              'verificationMethod': 'operating_plan_account_review',
                              'evidenceIds': ['e2']}]
            }, actor='jarvis', goal_id='g1', now=now)
            self.assertTrue(res['ok'])
            self.assertFalse(res['publicationVerified'])
            alloc_id = res['allocationIds'][0]
            saved = operating.load(self.data / 'operating-plan.json')['publications'][alloc_id]
            self.assertEqual(saved['owner'], 'publi')
            self.assertEqual(saved['exactTarget']['account'], 'must-pick.com')
            self.assertEqual(saved['evidenceIds'], ['e0', 'e2'])
            self.assertTrue(saved['observationsValidated'])
            self.assertTrue(saved['rationaleBound'])
            self.assertEqual(saved['lifecycleStage'], 'queued_or_accepted')
            self.assertFalse(saved['publicationVerified'])
            self.assertFalse(saved['businessOutcomeVerified'])
            with self.assertRaisesRegex(ValueError, 'Unknown allocation observation'):
                operating.allocate({
                    'publications': [{'project': 'cf_blog', 'account': 'must-pick.com', 'publishAt': future_iso,
                                      'topic': '청년월세 지원 절차', 'why': 'Invalid evidence check', 'evidenceIds': ['nonexistent']}]
                }, actor='jarvis', goal_id='g1', now=now)
            # Verify cf-prepare conference states are never misclassified as 'prepared'
            prep_args = {'action': 'cf-prepare', 'date': saved['day'], 'account': 'must-pick.com', 'slot': saved['slot']}
            prep_id = hashlib.sha256(json.dumps(['parameters', prep_args], sort_keys=True).encode()).hexdigest()
            for p_status, expected_stage in (('running', 'preparing'), ('failed', 'preparation_failed'), ('unknown', 'uncertain_or_protected_hold')):
                agenda.write(self.data / 'publication-conferences' / (prep_id + '.json'),
                             {'kind': 'parameters', 'arguments': prep_args, 'status': p_status, 'failureReason': 'check'})
                exec_state = operating.allocation_execution(saved, now=now)
                self.assertEqual(exec_state['status'], 'preparation_' + p_status)
                self.assertEqual(exec_state['lifecycleStage'], expected_stage)
            (self.data / 'publication-conferences' / (prep_id + '.json')).unlink()
            # Verify track_operating_action binds cited evidenceIds and due nextCheckAt routes to followup_verification_due
            req_id = 'goal:g1:act1'
            stem = hashlib.sha256(req_id.encode()).hexdigest()
            receipt_file = self.data / 'chats/staff-requests' / (stem + '.json')
            agenda.write(receipt_file, {'requestId': req_id, 'taskId': 't1', 'status': 'queued', 'results': []})
            mgr = {'id': 'g1', 'actor': 'jarvis', 'origin': 'company-manager', 'observations': [{'id': 'e0'}, {'id': 'e2'}, {'id': 'e9'}],
                   'pendingNextAction': {'evidenceIds': ['e2'], 'expectedResult': 'Verify CF slot',
                                         'verificationMethod': 'staff_request:' + stem + '+inspect_url_acquisition'},
                   'pendingAction': {'requestId': req_id, 'action': {'agent': 'publi', 'tool': 'run_project_cycle', 'args': {'project': 'cf_blog'}},
                                     'nextCheckAt': now + 30}}
            with patch('server.agent_tools.STAFF_REQUEST_DIR', self.data / 'chats/staff-requests'), \
                 patch.object(crew, 'save'):
                crew.track_operating_action(mgr, {'taskId': 't1', 'status': 'queued'})
                tracked = mgr['operatingActions'][0]
                self.assertEqual(tracked['evidenceIds'], ['e2'])
                self.assertTrue(tracked['observationsValidated'])
                self.assertTrue(tracked['rationaleBound'])
                # Complete receipt and advance clock past nextCheckAt -> surfaces in refresh_operating_actions and execution_board
                agenda.write(receipt_file, {'requestId': req_id, 'taskId': 't1', 'status': 'completed',
                                            'results': [{'result': {'ok': True, 'publicationVerified': True}}]})
                with patch.object(crew.time, 'time', return_value=now + 60):
                    crew.refresh_operating_actions(mgr)
            self.assertTrue(mgr['operatingActions'][0]['followupDue'])
            self.assertEqual(mgr['operatingActions'][0]['lifecycleStage'], 'published_verified')
            board_due = operating.execution_board(now=now + 8000)
            due_ids = {w['id']: w for w in board_due['work']}
            self.assertIn('followup:' + req_id, due_ids)
            self.assertEqual(due_ids['followup:' + req_id]['state'], 'followup_verification_due')
            self.assertEqual(due_ids['followup:' + req_id]['evidenceIds'], ['e2'])
            self.assertIn('account-review-due:cf_blog:must-pick.com', due_ids)
            self.assertEqual(due_ids['account-review-due:cf_blog:must-pick.com']['state'], 'account_review_due')
            # Reviewing URL A must NEVER close URL B, broader account actions, or held actions under the same project/account
            url_a = 'https://must-pick.com/entry/article-a'
            url_b = 'https://must-pick.com/entry/article-b'
            rec_a = self.data / 'chats/staff-requests' / ('a' * 64 + '.json')
            rec_b = self.data / 'chats/staff-requests' / ('b' * 64 + '.json')
            rec_broad = self.data / 'chats/staff-requests' / ('c' * 64 + '.json')
            for r_path, r_url in ((rec_a, url_a), (rec_b, url_b)):
                agenda.write(r_path, {'status': 'completed', 'results': [{'result': {'ok': True, 'publicationVerified': True, 'publicUrl': r_url}}]})
            agenda.write(rec_broad, {'status': 'completed', 'results': [{'result': {'ok': True, 'publicationVerified': True}}]})
            plan_state = operating.load(self.data / 'operating-plan.json')
            plan_state['actions']['act_a'] = {'requestId': 'act_a', 'receiptPath': str(rec_a), 'nextCheckAt': now + 10,
                'exactTarget': {'project': 'cf_blog', 'account': 'must-pick.com', 'url': url_a}}
            plan_state['actions']['act_b'] = {'requestId': 'act_b', 'receiptPath': str(rec_b), 'nextCheckAt': now + 10,
                'exactTarget': {'project': 'cf_blog', 'account': 'must-pick.com', 'url': url_b}}
            plan_state['actions']['act_broad'] = {'requestId': 'act_broad', 'receiptPath': str(rec_broad), 'nextCheckAt': now + 10,
                'exactTarget': {'project': 'cf_blog', 'account': 'must-pick.com'}}
            plan_state['actions']['act_held_a'] = {'requestId': 'act_held_a', 'status': 'held', 'nextCheckAt': now + 10,
                'exactTarget': {'project': 'cf_blog', 'account': 'must-pick.com', 'url': url_a}}
            operating.write(self.data / 'operating-plan.json', plan_state)
            with patch.object(operating, 'publication_inventory', return_value=[
                {'url': url_a, 'project': 'cf_blog', 'account': 'must-pick.com'},
                {'url': url_b, 'project': 'cf_blog', 'account': 'must-pick.com'}
            ]):
                # 1) Unvalidated evidence without goal record records review assessment but NEVER closes followupVerified
                rev_unval = operating.review_publication({
                    'url': url_a, 'assessment': 'Initial unvalidated note',
                    'nextAction': 'Measure article A in 7d', 'nextReviewAt': future_iso,
                    'evidenceIds': ['unvalidated-evidence']
                }, actor='jarvis')
                self.assertFalse(rev_unval['observationsValidated'])
                self.assertEqual(rev_unval['matchedActionIds'], [])
                self.assertFalse(bool(operating.load(self.data / 'operating-plan.json')['actions']['act_a'].get('followupVerified')))
                # 2) Unrelated observation, failed inspection with URL in arguments, or URL only in arguments must NEVER validate or close followupVerified
                for bad_obs in (
                    [{'id': 'e0', 'tool': 'inspect_url', 'arguments': {}, 'result': {'ok': False, 'reason': 'inspection_failed'}}],
                    [{'id': 'e0', 'tool': 'inspect_url', 'arguments': {'url': url_a}, 'result': {'ok': False, 'reason': 'inspection_failed'}}],
                    [{'id': 'e0', 'tool': 'inspect_url', 'arguments': {'url': url_a}, 'result': {'ok': True, 'status': 'collected', 'url': url_b, 'complete': True, 'reconciled': True, 'limited': False, 'qualifiedSessions': 4}}],
                ):
                    rev_bad = operating.review_publication({
                        'url': url_a, 'assessment': 'Attempt review with failed/mismatched obs',
                        'nextAction': 'Retry measurement', 'nextReviewAt': future_iso,
                        'evidenceIds': ['e0']
                    }, actor='jarvis', goal_id='g1', observations=bad_obs)
                    self.assertFalse(rev_bad['observationsValidated'])
                    self.assertEqual(rev_bad['matchedActionIds'], [])
                    self.assertFalse(bool(operating.load(self.data / 'operating-plan.json')['actions']['act_a'].get('followupVerified')))
                # 3) Valid successful observation for URL A closes ONLY act_a while preserving reviewHistory, act_b, act_broad, and act_held_a
                valid_obs = [{'id': 'e_ok', 'tool': 'inspect_url_acquisition', 'arguments': {'url': url_a},
                              'result': {'ok': True, 'status': 'collected', 'url': url_a, 'complete': True,
                                         'reconciled': True, 'limited': False, 'qualifiedSessions': 6, 'qualifiedPageViews': 10}}]
                rev_res = operating.review_publication({
                    'url': url_a, 'assessment': 'Verified article A acquisition',
                    'nextAction': 'Re-evaluate article A in 7d', 'nextReviewAt': future_iso,
                    'evidenceIds': ['e_ok']
                }, actor='jarvis', goal_id='g1', observations=valid_obs)
                self.assertTrue(rev_res['observationsValidated'])
                self.assertEqual(rev_res['matchedActionIds'], ['act_a'])
            saved_plan = operating.load(self.data / 'operating-plan.json')
            self.assertGreaterEqual(len(saved_plan.get('reviewHistory', [])), 4)
            after_rev = saved_plan['actions']
            self.assertTrue(after_rev['act_a'].get('followupVerified'))
            self.assertFalse(bool(after_rev['act_b'].get('followupVerified')))
            self.assertFalse(bool(after_rev['act_broad'].get('followupVerified')))
            self.assertFalse(bool(after_rev['act_held_a'].get('followupVerified')))
            board_after = operating.execution_board(now=now + 8000)
            after_ids = {w['id'] for w in board_after['work']}
            self.assertNotIn('followup:act_a', after_ids)
            self.assertIn('followup:act_b', after_ids)
            self.assertIn('followup:act_broad', after_ids)

    def test_reconcile_action_receipt_preserves_protected_and_verifies_identity(self):
        from common import operating_plan as operating
        action = {}
        receipt = {
            'status': 'completed',
            'pendingEffect': True,
            'results': [{'result': {'publicationVerified': True}}],
        }
        changed = operating.reconcile_action_receipt(action, receipt, now=1)
        self.assertTrue(changed)
        self.assertEqual(action['lifecycleStage'], 'uncertain_or_protected_hold')
        self.assertFalse(action['publicationVerified'])
        self.assertFalse(action['reservationVerified'])
        self.assertEqual(action['status'], 'held')
        self.assertTrue(action.get('pendingEffect'))

        for child_res in (
            {'status': 'submitting', 'publicationVerified': True},
            {'status': 'unknown', 'reservationVerified': True},
            {'status': 'completed', 'reason': 'auth_required', 'publicationVerified': True},
            {'status': 'completed', 'reason': 'user_takeover', 'publicationVerified': True},
            {'status': 'completed', 'manualResolutionRequired': True, 'publicationVerified': True},
        ):
            act = {'requestId': 'req-1', 'taskId': 'staff:1', 'status': 'queued'}
            rec = {'requestId': 'req-1', 'taskId': 'staff:1', 'status': 'completed', 'results': [{'result': child_res}]}
            operating.reconcile_action_receipt(act, rec, now=2)
            self.assertEqual(act['lifecycleStage'], 'uncertain_or_protected_hold')
            self.assertFalse(act['publicationVerified'])
            self.assertFalse(act['reservationVerified'])

        held_action = {
            'requestId': 'req-held',
            'taskId': 'staff:held',
            'status': 'held',
            'lifecycleStage': 'uncertain_or_protected_hold',
            'publicationVerified': False,
        }
        completed_rec = {
            'requestId': 'req-held',
            'taskId': 'staff:held',
            'status': 'completed',
            'results': [{'result': {'publicationVerified': True}}],
        }
        operating.reconcile_action_receipt(held_action, completed_rec, now=3)
        self.assertEqual(held_action['status'], 'held')
        self.assertEqual(held_action['lifecycleStage'], 'uncertain_or_protected_hold')
        self.assertFalse(held_action['publicationVerified'])

        mismatch_act = {'requestId': 'req-a', 'taskId': 'staff:a', 'status': 'queued'}
        other_rec = {'requestId': 'req-b', 'taskId': 'staff:a', 'status': 'completed', 'results': [{'result': {'publicationVerified': True}}]}
        self.assertFalse(operating.reconcile_action_receipt(mismatch_act, other_rec, now=4))
        self.assertEqual(mismatch_act['status'], 'queued')
        self.assertFalse(bool(mismatch_act.get('publicationVerified')))

        mismatch_task = {'requestId': 'req-a', 'taskId': 'staff:a', 'status': 'queued'}
        other_task_rec = {'requestId': 'req-a', 'taskId': 'staff:b', 'status': 'completed', 'results': [{'result': {'publicationVerified': True}}]}
        self.assertFalse(operating.reconcile_action_receipt(mismatch_task, other_task_rec, now=5))
        self.assertEqual(mismatch_task['status'], 'queued')

        anon_act = {'status': 'queued'}
        named_rec = {'requestId': 'req-other', 'status': 'completed', 'results': [{'result': {'publicationVerified': True}}]}
        self.assertFalse(operating.reconcile_action_receipt(anon_act, named_rec, now=6))
        self.assertEqual(anon_act['status'], 'queued')


if __name__ == '__main__':
    unittest.main()
