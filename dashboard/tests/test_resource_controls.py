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

    def test_advisory_routine_usage_keeps_counts_and_explicit_experiment_guard(self):
        state={'byModel':{'model':{'calls':20000,'inputTokens':300000000}},
               'byAgenda':{self.agenda:{'modelCalls':1000,'modelLatencyMs':90000000}}}
        before=json.dumps(state,sort_keys=True)
        policy={**usage.DEFAULT_BUDGET,'routineLimits':'advisory'}
        usage.check_budget(state,self.call('one'),policy,self.root)
        self.assertEqual(json.dumps(state,sort_keys=True),before)
        self.plan({'maxModelCalls':21})
        with self.assertRaisesRegex(usage.UsageBudgetExceeded,'agenda_call_budget_exhausted'):
            usage.check_budget(state,self.call('two'),policy,self.root)

    def test_policy_change_rechecks_admission_without_clearing_any_usage(self):
        from common.collection_observability import write
        ledger=self.data/'llm_usage_ledger.json'
        state={'date':self.now.date().isoformat(),'byModel':{'model':{'inputTokens':300000000}},'byAgenda':{self.agenda:{'modelCalls':900}}}
        write(ledger,state);before=ledger.read_bytes()
        self.assertFalse(usage.budget_admission(self.agenda,self.root,self.now)['ready'])
        write(self.data/'llm-settings.json',{'resourceBudget':{'routineLimits':'advisory'}})
        self.assertTrue(usage.budget_admission(self.agenda,self.root,self.now)['ready'])
        self.assertEqual(ledger.read_bytes(),before)

    def test_manager_resumes_exact_goal_after_readiness_without_replaying_tools(self):
        from agents import crew_reasoning as crew
        row={'id':'c'*64,'status':'blocked','origin':'company-manager','decisions':17,
             'observations':[{'tool':'resource_hold','result':{'errorType':'UsageBudgetExceeded','reason':'daily_token_budget_exhausted'}}],
             'pendingConference':{'agendaId':'unchanged-native-submission'},'timings':{'modelActiveSeconds':900}}
        with patch.object(crew,'GOALS',self.data/'goals'),patch.object(crew,'save'),patch.object(usage,'budget_admission',return_value={'ready':True,'reason':None}),patch.object(crew,'tool_call') as tool:
            self.assertTrue(crew.resource_continuation(row))
        self.assertEqual(row['status'],'ready');self.assertEqual(row['decisions'],17)
        self.assertEqual(row['pendingConference'],{'agendaId':'unchanged-native-submission'})
        self.assertEqual(row['timings']['modelActiveSeconds'],900);tool.assert_not_called()
        self.assertTrue((self.data/'goals/pending'/row['id']).exists())

    def test_manager_resource_wait_preserves_explicit_hold_and_route_retry_time(self):
        from agents import crew_reasoning as crew
        row={'id':'c'*64,'status':'waiting_resource','resourceWait':{'errorType':'UsageBudgetExceeded','reason':'experiment_call_budget_exhausted'}}
        with patch.object(crew,'save'),patch.object(usage,'budget_admission',return_value={'ready':False,'reason':'experiment_call_budget_exhausted'}):
            self.assertFalse(crew.resource_continuation(row))
        self.assertEqual(row['status'],'waiting_resource')
        row['resourceWait']={'errorType':'RouteCoolingDown','retryAt':10**12}
        with patch.object(crew,'save'),patch.object(usage,'budget_admission',return_value={'ready':True,'reason':None}):
            self.assertFalse(crew.resource_continuation(row))
        self.assertEqual(row['nextCheckAt'],10**12)

    def test_manager_manual_stop_or_nonresource_failure_is_never_reopened(self):
        from agents import crew_reasoning as crew
        for row in ({'status':'blocked','manualStop':True,'resourceWait':{'reason':'daily_token_budget_exhausted'}},
                    {'status':'blocked','observations':[{'tool':'resource_hold','result':{'errorType':'UsageBudgetExceeded'}},{'tool':'decision_error'}]}):
            with patch.object(crew,'save') as save:
                self.assertFalse(crew.resource_continuation(row));save.assert_not_called()

    def test_current_manager_runs_before_old_undelivered_terminal_reports(self):
        from agents import crew_reasoning as crew
        from common import operating_plan, work_agenda
        from common.collection_observability import write
        from contextlib import nullcontext
        import os
        goals=self.data/'goals';pending=goals/'pending';pending.mkdir(parents=True)
        old='a'*64;current='b'*64
        for identity,status in [(old,'blocked'),(current,'ready')]:
            write(goals/(identity+'.json'),{'id':identity,'origin':'company-manager','status':status})
            (pending/identity).touch()
        os.utime(pending/old,(1,1));write(self.data/'operating-plan.json',{'manager':{'goalId':current}})
        with patch.object(crew,'GOALS',goals),patch.object(operating_plan,'STATE',self.data/'operating-plan.json'),patch.object(work_agenda,'enabled',return_value=False),patch.object(crew,'claim',return_value=nullcontext(True)),patch.object(crew,'advance') as advance,patch.object(crew,'deliver') as deliver:
            self.assertTrue(crew.resume_once('manager'))
        self.assertEqual(advance.call_args.args[0]['id'],current);deliver.assert_not_called()
        self.assertTrue((pending/old).exists())

    def test_company_evidence_batch_collects_requested_sources_and_isolates_missing_one(self):
        from agents import crew_reasoning as crew
        names=['revenue','traffic','metrics','kin','threads','editorial:one','editorial:missing']
        def read(args):
            if args['name']=='editorial:missing':raise ValueError('unavailable registered record')
            return {'available':True,'source':args['name']}
        row={'actor':'jarvis','origin':'company-manager'}
        with patch.object(crew,'read_evidence',side_effect=read) as reader:
            result=crew.tool_call(row,'evidence_batch',{'names':names})
        self.assertEqual(reader.call_count,7);self.assertEqual(set(result),set(names))
        self.assertTrue(result['revenue']['available']);self.assertFalse(result['editorial:missing']['available'])

    def test_shared_memory_snapshot_acquires_file_lock_before_database_transaction(self):
        from common import hermes_memory as memory
        from contextlib import contextmanager
        store=memory.HermesMemory(self.data/'memory',self.data/'skills');store.initialize()
        original_db=store.db;original_lock=memory.file_lock;inside={'db':False}
        @contextmanager
        def database():
            inside['db']=True
            try:
                with original_db() as db:yield db
            finally:inside['db']=False
        @contextmanager
        def lock(path):
            self.assertFalse(inside['db'],'SQLite transaction must not wait for the writer file lock')
            with original_lock(path):yield
        with patch.object(store,'db',database),patch.object(memory,'file_lock',lock):
            first=store.frozen_session_context('exact-session')
        other=memory.HermesMemory(self.data/'memory',self.data/'skills')
        self.assertEqual(other.frozen_session_context('exact-session'),first)

    def test_worker_retries_memory_contention_but_preserves_configuration_errors(self):
        from dashboard.server import memory_worker as worker
        from unittest.mock import Mock
        import sqlite3
        store=Mock();store.initialize.side_effect=[OSError(36,'Resource deadlock avoided'),sqlite3.OperationalError('database is locked'),None]
        stopped=Mock();stopped.is_set.return_value=False;busy=Mock()
        self.assertTrue(worker.initialize_memory(store,stopped,busy))
        self.assertEqual(store.initialize.call_count,3);self.assertEqual(busy.call_count,2)
        store.initialize.side_effect=sqlite3.OperationalError('no such table: broken_schema')
        with self.assertRaises(sqlite3.OperationalError):worker.initialize_memory(store,stopped)

    def test_native_draft_formats_existing_tags_without_rewriting_or_inventing_them(self):
        from naver_blog_posting.posting import basic_writer_document
        article={'title':'Original title','intro':'Original intro','closing':'Original closing','tags':['existing','#already','existing'],
                 'sections':[],'summary':'Original summary'}
        document=basic_writer_document(article)
        self.assertEqual(document['blocks'][-1],{'type':'tags','text':'#existing #already'})
        self.assertEqual(article['tags'],['existing','#already','existing'])
        self.assertEqual(document['title'],'Original title')

    def test_tag_format_recovery_does_not_admit_other_image_or_evidence_failures(self):
        from common.editorial_recovery import repairable_diagnostic
        prefix='editorial_images_held: image_document_format_mismatch: '
        self.assertTrue(repairable_diagnostic(prefix+json.dumps([{'code':'TAGS'}])))
        self.assertFalse(repairable_diagnostic(prefix+json.dumps([{'code':'TAGS'},{'code':'IMAGE_SOURCE'}])))
        self.assertFalse(repairable_diagnostic('editorial_images_held: source_provenance_missing'))


if __name__ == '__main__':
    unittest.main()
