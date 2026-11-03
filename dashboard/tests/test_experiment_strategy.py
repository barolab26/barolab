"""Target-specific strategy controls; fixtures never publish or call a model."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import sqlite3
import hashlib
from contextlib import nullcontext
from unittest.mock import patch, Mock

from common import work_agenda as agenda
from common import conference_dispatch as conference
from server.growth import _business_page_evidence


class ExperimentStrategyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = dt.datetime.now(dt.timezone.utc)
        self.target = 'https://www.example.com/observed'
        self.base = {'url': self.target, 'domain': 'example.com', 'source': 'GA4 Data API',
                     'timezone': 'UTC', 'complete': True, 'checkedAt': self.now.isoformat(),
                     'start': str(self.now.date()-dt.timedelta(days=7)),
                     'end': str(self.now.date()-dt.timedelta(days=1)),
                     'pageViews': 100, 'sessions': 80}
        self.business = {'pageObservations': [self.base]}
        self.proposal = {'targetUrl': self.target, 'hypothesis': 'Improve reader navigation',
                         'measurementDate': str(self.now.date()), 'evidenceConfidence': 'low',
                         'maxModelCalls': 12, 'primaryMetric': 'pageViews', 'measurementWindowDays': 7,
                         'minimumSample': 50, 'successMetric': 'observed increase',
                         'stopCondition': 'stop after a fully observed window without increase'}
        for field, value in [('DATA', self.root), ('STATE', self.root/'state.json'), ('ROWS', self.root/'operations')]:
            p = patch.object(agenda, field, value); p.start(); self.addCleanup(p.stop)
        self.exp = agenda.bind_business_experiment(self.proposal, self.business, ['cf_blog', 'threads', 'legacy_remodel'], self.now.timestamp())
        self.state = {'enabled': True, 'activeExperiment': self.exp}
        agenda.write(agenda.STATE, self.state)

    def post(self, **changes):
        checked = dt.datetime.fromisoformat(self.exp['observationEnd']).replace(tzinfo=dt.timezone.utc)+dt.timedelta(days=1)
        return {**self.base, 'start': self.exp['observationStart'], 'end': self.exp['observationEnd'],
                'checkedAt': checked.isoformat(), 'pageViews': 150, **changes}, checked.timestamp()

    def test_currency_scope_and_missing_are_not_usd_or_zero(self):
        result = agenda.compute_reverse_funnel_gap({'priorDayRevenue': [
            {'source': 'krw', 'amount': 1380, 'currency': 'KRW', 'status': 'collected'},
            {'source': 'missing', 'amount': None, 'currency': 'USD', 'status': 'not_collected'}]})
        self.assertIsNone(result['observedDailyRevenueUsd'])
        self.assertIsNone(result['requiredDailyPv'])
        self.assertEqual(result['revenueByCurrency'], {'KRW': 1380})
        self.assertEqual(result['revenueScope']['missingSources'], ['missing'])

    def test_required_pv_uses_measured_scoped_rpm(self):
        report = {'matched': True, 'complete': True, 'currency': 'USD', 'revenue': 2,
                  'pageViews': 1000, 'start': self.base['start'], 'end': self.base['end'],
                  'timezone': 'UTC', 'source': 'AdSense', 'scope': 'one eligible page',
                  'checkedAt': self.now.isoformat()}
        result = agenda.compute_reverse_funnel_gap({'matchedRevenuePv': [report]})
        self.assertEqual(result['measuredRpmUsd'], 2)
        self.assertEqual(result['requiredDailyPv'], 50000)
        self.assertEqual(result['rpmEvidence']['scope'], 'one eligible page')
        self.assertIsNone(agenda.compute_reverse_funnel_gap({'matchedRevenuePv': [{**report, 'complete': False}]})['requiredDailyPv'])
        self.assertIsNone(agenda.compute_reverse_funnel_gap({'matchedRevenuePv': [{**report, 'revenue': 0}]})['requiredDailyPv'])

    def test_baseline_is_bound_to_host_evidence(self):
        result = agenda.bind_business_experiment({**self.proposal, 'baseline': {'pageViews': 999999}}, self.business, ['cf_blog'])
        self.assertEqual(result['baseline']['pageViews'], 100)
        with self.assertRaises(ValueError):
            agenda.bind_business_experiment({**self.proposal, 'targetUrl': 'https://example.com/invented'}, self.business, ['cf_blog'])
        with self.assertRaises(ValueError):
            agenda.bind_business_experiment({**self.proposal, 'measurementWindowDays': 14}, self.business, ['cf_blog'])

    def test_only_exact_target_comparable_window_can_show_gain(self):
        post, now = self.post()
        result = agenda.evaluate_business_experiment(self.exp, {'pageObservations': [post]}, now)
        self.assertEqual(result['status'], 'observed_gain')
        self.assertFalse(result['causalClaim'])
        for changes in ({'url': self.target+'?utm_campaign=other'}, {'complete': False},
                        {'currency': 'KRW'}, {'source': 'another source'},
                        {'start': str(dt.date.fromisoformat(post['start'])+dt.timedelta(days=1))},
                        {'checkedAt': (dt.datetime.fromtimestamp(now,dt.timezone.utc)-dt.timedelta(days=2)).isoformat()}):
            self.assertEqual(agenda.evaluate_business_experiment(self.exp, {'pageObservations': [{**post, **changes}]}, now)['status'], 'inconclusive')

    def test_sparse_missing_and_fully_observed_no_gain_are_distinct(self):
        post, now = self.post(pageViews=2)
        self.assertEqual(agenda.evaluate_business_experiment(self.exp, {'pageObservations': [post]}, now)['reason'], 'insufficient_sample')
        self.assertEqual(agenda.evaluate_business_experiment(self.exp, {}, now)['reason'], 'target_measurement_missing')
        post['pageViews'] = 100
        self.assertEqual(agenda.evaluate_business_experiment(self.exp, {'pageObservations': [post]}, now)['status'], 'no_observed_gain')

    def test_captured_exact_window_survives_rolling_report_replacement(self):
        post, now = self.post()
        agenda.capture_experiment_observation(self.exp, {'pageObservations':[post]}, now)
        result = agenda.evaluate_business_experiment(self.exp, {}, now+86400*3)
        self.assertEqual(result['status'], 'observed_gain')
        self.assertEqual(result['observation']['start'], self.exp['observationStart'])

    def test_small_valid_baseline_does_not_make_sufficient_followup_permanently_inconclusive(self):
        self.exp['baseline'] = {**self.base, 'pageViews':13}
        post, now = self.post(pageViews=60)
        self.assertEqual(agenda.evaluate_business_experiment(self.exp, {'pageObservations':[post]}, now)['status'], 'observed_gain')

    def test_new_autonomous_orders_are_focused_and_deduplicated(self):
        self.assertIsNone(agenda._queue_autonomous_work_order('cro_widget_retrofit', target_domain='other.com'))
        first = agenda._queue_autonomous_work_order('cro_widget_retrofit', target_domain='example.com', hour_bucket='first')
        second = agenda._queue_autonomous_work_order('cro_widget_retrofit', target_domain='example.com', hour_bucket='later')
        self.assertEqual(first, second)
        self.assertEqual(agenda.get(first)['businessExperiment']['id'], self.exp['id'])
        self.assertEqual(len(list(agenda.ROWS.glob('*.json'))), 1)

    def test_missing_experiment_budget_and_expiry_fail_closed(self):
        self.assertFalse(agenda.autonomous_experiment_allows('cf_blog', domain='example.com', state={}))
        self.assertFalse(agenda.autonomous_experiment_allows('cf_blog', domain='other.com', state=self.state))
        agenda.write(self.root/'llm_usage_ledger.json', {'byExperiment': {self.exp['id']: {'modelCalls': 12}}})
        self.assertFalse(agenda.autonomous_experiment_allows('cf_blog', domain='example.com', state=self.state))
        agenda.write(self.root/'llm_usage_ledger.json', {})
        expired = {**self.state, 'activeExperiment': {**self.exp, 'observationEnd': '2000-01-01'}}
        self.assertFalse(agenda.autonomous_experiment_allows('cf_blog', domain='example.com', state=expired))

    def test_explicit_work_and_already_active_work_survive_policy_changes(self):
        explicit = agenda.propose('goal', {'request': 'ceo'}, title='Explicit task', project='cf_blog', source={'origin': 'ceo'}, completion='review')
        agenda.write(agenda.STATE, {**agenda.load(agenda.STATE), 'activeExperiment': {}})
        token = agenda.admit(explicit)
        self.assertIsNotNone(token)
        self.assertIsNotNone(agenda.admit(explicit))

    def test_pending_automatic_work_is_held_without_discarding_it(self):
        identity = agenda._queue_autonomous_work_order('cro_widget_retrofit', target_domain='example.com')
        agenda.write(agenda.STATE, {**agenda.load(agenda.STATE), 'activeExperiment': {}})
        self.assertIsNone(agenda.admit(identity))
        self.assertEqual(agenda.get(identity)['status'], 'queued')

    def test_publication_cap_counts_tool_only_work_and_keeps_reserved_admission(self):
        source={'autonomousExperiment':True,'experimentId':self.exp['id'],'targetUrl':self.target}
        first=agenda.propose('conference',{'slot':1},title='First',project='threads',source=source,completion='verify')
        second=agenda.propose('conference',{'slot':2},title='Second',project='threads',source=source,completion='verify')
        third=agenda.propose('conference',{'slot':3},title='Third',project='threads',source=source,completion='verify')
        self.assertTrue(first); self.assertTrue(second); self.assertIsNone(third)
        self.assertIsNotNone(agenda.admit(first))
        self.assertEqual(len(agenda.load(agenda.STATE)['activeExperiment']['newPublicationAgendaIds']),2)

    def test_reactivation_cannot_reset_clock_baseline_or_budget(self):
        original=agenda.load(agenda.STATE)['activeExperiment']
        changed={**self.exp,'startedAt':self.exp['startedAt']+999,'maxModelCalls':40}
        result=agenda.activate_experiment_preview(changed)
        self.assertEqual(result,original)
        with self.assertRaises(ValueError):
            agenda.activate_experiment_preview({**changed,'id':'replacement'})

    def test_view_separates_draft_contract_from_allowlisted_observed_evidence(self):
        experiment={**self.exp,'baseline':{**self.base,'credential':'must-not-leak'},
                    'evaluation':{'status':'inconclusive','reason':'insufficient_sample','rawResponse':'must-not-leak'},
                    'newPublicationAgendaIds':['reserved']}
        agenda.write(agenda.STATE,{'enabled':True,'activeExperiment':experiment,
                                 'experimentHistory':[experiment],'reverseFunnel':{'status':'measurement_required'}})
        before=agenda.STATE.read_bytes()
        result=agenda.view()
        summary=result['activeExperiment']
        self.assertEqual(summary['draft']['targetUrl'],self.target)
        self.assertEqual(summary['measured']['baseline']['pageViews'],100)
        self.assertEqual(summary['measured']['evaluation']['status'],'inconclusive')
        self.assertEqual(summary['publicationReservations'],1)
        self.assertFalse(summary['causalClaim'])
        self.assertNotIn('must-not-leak',json.dumps(result))
        self.assertEqual(len(result['recentExperiments']),1)
        self.assertEqual(agenda.STATE.read_bytes(),before)

    def test_unknown_owned_request_keeps_lane_until_terminal_receipt(self):
        goal = {'pendingAction': {'requestId':'owned'}}
        self.assertTrue(agenda._pending_owned_work(goal))
        receipt = self.root/'staff-requests'/(hashlib.sha256(b'owned').hexdigest()+'.json')
        agenda.write(receipt, {'status':'completed'})
        self.assertFalse(agenda._pending_owned_work(goal))
        agenda.write(receipt, {'status':'completed','pendingEffect':True})
        self.assertTrue(agenda._pending_owned_work(goal))

    def test_scheduler_blocks_new_unfocused_work_but_preserves_existing_attempts(self):
        with patch.object(conference, 'concrete_requests', return_value=[{'action':'cf-prepare','account':'other.com','date':'2026-11-03'}]), \
             patch.object(conference, '_existing_concrete_work', return_value=False), \
             patch.object(conference, '_request_single', return_value={'status':'conference_requested'}) as submit:
            self.assertEqual(conference.request('parameters', {'action':'prepare'}, automatic=True)['status'], 'held')
            submit.assert_not_called()
            conference.request('parameters', {'action':'prepare'}, automatic=False)
            self.assertEqual(submit.call_count, 1)
            with patch.object(conference, '_existing_concrete_work', return_value=True):
                conference.request('parameters', {'action':'prepare'}, automatic=True)
            self.assertEqual(submit.call_count, 2)

    def test_page_evidence_does_not_promote_partial_domains_or_join_different_periods(self):
        traffic = {'pagePerformance': {**self.base, 'pages': [self.base], 'sites': [{'domain':'example.com','complete':False}]}}
        money = {'pagePerformance': {**self.base, 'source':'AdSense', 'currency':'USD', 'pages':[
            {'url':self.target,'domain':'example.com','estimatedRevenue':1}]}}
        rows, rpm = _business_page_evidence(traffic, money)
        self.assertFalse(rows[0]['complete'])
        self.assertEqual(rpm, [])
        traffic['pagePerformance']['sites'] = []
        money['pagePerformance']['start'] = '2000-01-01'
        rows, rpm = _business_page_evidence(traffic, money)
        self.assertEqual(rpm, [])

    def test_same_report_adsense_pv_is_preserved_and_join_provenance_is_explicit(self):
        traffic={'pagePerformance':{**self.base,'pages':[self.base]}}
        money={'pagePerformance':{**self.base,'source':'AdSense','currency':'USD','pages':[
            {'url':self.target,'domain':'example.com','estimatedRevenue':1,'pageViews':8}]}}
        rows,rpm=_business_page_evidence(traffic,money)
        self.assertEqual(rpm[0]['pageViews'],8)
        self.assertEqual(rpm[0]['scope']['trafficSource'],'AdSense')
        self.assertEqual(rows[-1]['trafficSource'],'AdSense')
        del money['pagePerformance']['pages'][0]['pageViews']
        rows,rpm=_business_page_evidence(traffic,money)
        self.assertEqual(rpm[0]['pageViews'],100)
        self.assertEqual(rpm[0]['scope']['trafficSource'],'GA4 Data API')
        self.assertEqual(rows[-1]['trafficSource'],'GA4 Data API')

    def test_observation_merge_preserves_concurrent_reservations_and_replacement(self):
        state=agenda.load(agenda.STATE)
        state['activeExperiment']['newPublicationAgendaIds']=['reserved-during-observation']
        agenda.write(agenda.STATE,state)
        self.assertTrue(agenda._merge_experiment_observation(self.exp['id'],finalObservation={'row':self.base}))
        self.assertEqual(agenda.load(agenda.STATE)['activeExperiment']['newPublicationAgendaIds'],['reserved-during-observation'])
        state=agenda.load(agenda.STATE);state['activeExperiment']['id']='new-owner';agenda.write(agenda.STATE,state)
        self.assertFalse(agenda._merge_experiment_observation(self.exp['id'],status='inconclusive'))
        self.assertEqual(agenda.load(agenda.STATE)['activeExperiment']['status'],'active')

    def test_final_inconclusive_allows_a_distinct_followup_without_resetting_original(self):
        post,now=self.post(pageViews=2)
        agenda.capture_experiment_observation(self.exp,{'pageObservations':[post]},now)
        result=agenda.evaluate_business_experiment(self.exp,{'pageObservations':[post]},now)
        self.assertTrue(agenda.experiment_observation_closed(self.exp,result,now))
        self.exp.update(status='inconclusive',observationClosed=True,evaluation=result)
        agenda.write(agenda.STATE,{'activeExperiment':self.exp})
        next_business={'pageObservations':[post]}
        next_exp=agenda.bind_business_experiment(self.proposal,next_business,['threads'],now)
        self.assertNotEqual(next_exp['id'],self.exp['id'])
        agenda.activate_experiment_preview(next_exp)
        state=agenda.load(agenda.STATE)
        self.assertEqual(state['experimentHistory'][0]['id'],self.exp['id'])
        self.assertEqual(state['experimentHistory'][0]['baseline'],self.base)
        self.assertEqual(state['experimentHistory'][0]['finalObservation'],self.exp['finalObservation'])
        with self.assertRaises(ValueError):
            agenda.activate_experiment_preview({**self.exp,'status':'active','startedAt':now+1})

    def test_missing_exact_window_has_bounded_grace_without_a_success_claim(self):
        result={'status':'inconclusive','reason':'target_measurement_missing'}
        due=dt.datetime.fromisoformat(self.exp['measurementDate']).replace(tzinfo=dt.timezone.utc).timestamp()
        self.assertFalse(agenda.experiment_observation_closed(self.exp,result,due))
        self.assertTrue(agenda.experiment_observation_closed(self.exp,result,due+3*86400))

    def test_unrelated_company_traffic_and_revenue_winners_cannot_adopt_a_case(self):
        from agents import crew_reasoning as crew
        goals = self.root/'goals'; goals.mkdir()
        agenda.write(goals/'recent-cases.json', {'cases':[{'evaluationStatus':'pending','evaluateAfter':0,
            'resolution':{'status':'verified_resolved'},'businessBaseline':{},'goalId':'test'}]})
        with patch.object(crew,'GOALS',goals), patch.object(crew,'overview',return_value={
            'reverseFunnel':{'observedDailyPv':99999},'businessEvidence':{'revenueWinners':[{'estimatedRevenue':100}]}}):
            self.assertTrue(crew.evaluate_case_once())
        case = agenda.load(goals/'recent-cases.json')['cases'][0]
        self.assertEqual(case['evaluationStatus'],'inconclusive')
        self.assertEqual(case['kpiScore'],0)

    def test_direct_kin_timer_does_not_reserve_new_authoring_without_owned_agenda(self):
        from naver_kin import posting as kin
        db = sqlite3.connect(':memory:'); self.addCleanup(db.close); db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE operating_cadence(id INTEGER,active_run_id TEXT)')
        db.execute('INSERT INTO operating_cadence VALUES(1,NULL)')
        db.execute('CREATE TABLE questions(account TEXT,state TEXT,send_day TEXT,updated_at TEXT)'); db.commit()
        status={'nextEligibleAt':(self.now-dt.timedelta(minutes=1)).isoformat(),'globalRemainingRuns':20,'nextAccount':'acct'}
        config={'enabled':True,'continuousMode':True,'globalDailyCap':20}
        with patch.object(kin,'_naver_scheduler_initialize_cadence'), \
             patch.object(kin,'_naver_scheduler_cadence_status',return_value=status), \
             patch.object(kin,'_naver_scheduler__is_account_blog_busy',return_value=False), \
             patch.object(agenda,'new_authoring_allowed',return_value=False):
            result=kin._naver_scheduler_reserve_run(db,config,self.now)
        self.assertEqual(result['reason'],'new_authoring_requires_focused_agenda')
        self.assertIsNone(db.execute('SELECT active_run_id FROM operating_cadence').fetchone()[0])

    def test_direct_threads_timer_reconciles_but_never_claims_unfocused_new_slot(self):
        from threads_posting import posting as threads
        db=sqlite3.connect(':memory:'); self.addCleanup(db.close); db.row_factory=sqlite3.Row
        db.execute('CREATE TABLE parts(part_id TEXT,state TEXT,publication_date TEXT,slot TEXT,kind TEXT,attempt_id TEXT,created_at TEXT,document TEXT)')
        db.execute('CREATE TABLE authoring_slots(account_key TEXT,day TEXT,slot TEXT,state TEXT,reason TEXT,updated_at TEXT)')
        config={'enabled':True,'connection':{'connected':True},'mainDailyCap':4,'account_key':'acct'}
        with patch.object(threads,'_threads_scheduler_lock',side_effect=lambda:nullcontext()), \
             patch.object(threads,'_threads_config_load',return_value=config), \
             patch.object(threads,'_threads_scheduler_ego_action',side_effect=lambda *a:nullcontext()), \
             patch.object(threads,'_threads_pipeline_recover_unknown') as recover, \
             patch.object(threads,'_threads_pipeline_reconcile') as reconcile, \
             patch.object(threads,'_threads_pipeline_connect',return_value=db), \
             patch.object(threads._namespace_measurement,'should_collect',return_value=False), \
             patch.object(threads,'_threads_pipeline__gate',return_value=str(self.now.date())), \
             patch.object(threads,'_threads_scheduler_current_slot',return_value='09:00'), \
             patch.object(threads,'_threads_pipeline_snapshot'), \
             patch.object(threads,'_threads_authoring_prepare_next') as author, \
             patch.object(agenda,'new_authoring_allowed',return_value=False), \
             patch.object(conference,'request',return_value={'status':'held','reason':'new_automatic_work_requires_focused_experiment'}):
            result=threads._threads_scheduler_tick()
        self.assertEqual(result['state'],'held')
        recover.assert_called_once(); reconcile.assert_called_once(); author.assert_not_called()
        self.assertEqual(db.execute('SELECT count(*) FROM authoring_slots').fetchone()[0],0)

    def test_cro_holds_unreviewed_medical_experience_before_any_write(self):
        from common.cf_tables import retrofit_cro_widgets_and_tables
        from cf_posting import posting
        response=Mock()
        response.json.return_value={'post':{'id':1,'slug':'observed','title':'재활 병원 비교',
            'content':'<p>제가 병원을 직접 방문했습니다. 보험 적용률은 80%입니다.</p>'}}
        with patch.object(posting,'cleaner_lock',side_effect=lambda **kw:nullcontext(True)), \
             patch.object(posting,'published_inventory',return_value=[{'id':1,'slug':'observed','status':'published'}]), \
             patch('requests.get',return_value=response),patch('requests.put') as put,patch('time.sleep'):
            result=retrofit_cro_widgets_and_tables(domains=['example.com'],root=self.root,target_urls=[self.target])
        put.assert_not_called()
        self.assertEqual(result['status'],'held')
        self.assertEqual(result['holds'][0]['reason'],'independent_factual_review_required')
        self.assertEqual(result['factualReviewStatus'],'not_assessed')

    def test_cro_never_updates_a_different_article_on_the_same_domain(self):
        from common.cf_tables import retrofit_cro_widgets_and_tables
        from cf_posting import posting
        with patch.object(posting,'cleaner_lock',side_effect=lambda **kw:nullcontext(True)), \
             patch.object(posting,'published_inventory',return_value=[{'id':2,'slug':'other','status':'published'}]), \
             patch('requests.get') as get,patch('requests.put') as put,patch('time.sleep'):
            result=retrofit_cro_widgets_and_tables(domains=['example.com'],root=self.root,target_urls=[self.target])
        get.assert_not_called(); put.assert_not_called()
        self.assertEqual(result['status'],'no_matching_target')


if __name__ == '__main__':
    unittest.main()
