"""Run with PYTHONPATH=dashboard:. python -m unittest discover -s dashboard/tests."""
import datetime as dt
import functools
import hashlib
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from common import knowledge_policy as knowledge, llm_usage as usage
from dashboard.agents import synapse
from dashboard.collectors import revenue
from server.growth import page_performance_evidence


class BusinessControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'dashboard/data'
        self.data.mkdir(parents=True)
        self.now = dt.datetime.now(dt.timezone.utc)
        self.agenda = 'a' * 64

    def call(self, identity='one'):
        return dict(id=identity, provider='test', model='model', agendaId=self.agenda,
                    startedAt=self.now.isoformat(), inputTokens=100, outputTokens=20,
                    usageReports=1, latencyMs=2000, rateLimitHeaders={})

    def proof(self):
        from common.hermes_memory import write_verified_work_receipt
        document = self.root / 'publication.json'
        document.write_text(json.dumps({'status': 'verified', 'postId': '1', 'publicUrl': 'https://example.com/post',
                                        'publication': 'verified', 'verifiedAt': self.now.isoformat()}))
        return write_verified_work_receipt(self.root / 'receipt.json', work_type='verified_work_receipt_v1',
            channel='cf_blog', outcome='public_verified', scope='public_verified', source_agent='publi',
            evidence_text='Submitted article and matched public content to the saved document.',
            artifacts=[{'path': str(document), 'sha256': hashlib.sha256(document.read_bytes()).hexdigest()}],
            checks=[{'type': k, 'passed': True, 'evidenceRef': str(document)} for k in ('public_identity', 'public_content')])

    def test_summary_and_source_url_cannot_certify_knowledge(self):
        node = dict(type='PracticalKnowHow', active=True, title='Claim', method='Revenue doubled',
                    whenToUse='Always', measurementStatus='verified_fact_checked',
                    sourceUrl='https://example.com', factCheckSummary='Doctor agrees')
        self.assertFalse(knowledge.usable_knowhow(node))
        node['measurementStatus'] = 'observed_procedure'
        self.assertFalse(knowledge.usable_knowhow(node))

    def test_receipt_excerpt_and_changed_evidence(self):
        proof = self.proof()
        node = dict(type='PracticalKnowHow', active=True, title='Public verification',
                    method='matched public content to the saved document', whenToUse='After submission',
                    measurementStatus='observed_procedure', verifiedWorkProof=proof)
        self.assertTrue(knowledge.usable_knowhow(node))
        node['method'] = 'Revenue doubled'
        self.assertFalse(knowledge.usable_knowhow(node))
        node['method'] = 'matched public content to the saved document'
        (self.root / 'publication.json').write_text('{}')
        self.assertFalse(knowledge.usable_knowhow(node))

    def test_stale_cached_knowledge_is_filtered_at_delivery(self):
        (self.data / 'synapse-recipes.json').write_text(json.dumps({'knowledgeNotes': [
            dict(type='PracticalKnowHow', title='False promise', method='Guaranteed revenue', whenToUse='Always')]}))
        self.assertNotIn('Guaranteed revenue', synapse.recipe('draft', 'publi', self.root))

    def test_usage_attribution_and_admission(self):
        usage.record_call(self.call(), 'started', root=self.root, now=self.now)
        usage.record_call(self.call(), 'completed', root=self.root, now=self.now)
        state = json.loads((self.data / 'llm_usage_ledger.json').read_text())
        row = state['byAgenda'][self.agenda]
        self.assertEqual((row['inputTokens'], row['outputTokens'], row['modelCalls']), (100, 20, 1))
        policy = {**usage.DEFAULT_BUDGET, 'agendaTokens': 120}
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'agenda_token'):
            usage.check_budget(state, self.call('two'), policy, self.root)
        self.assertIsNone(usage.resource_summary(self.root)['actualCostUsd'])

    def test_active_calls_and_experiment_limit_are_enforced(self):
        folder = self.data / 'publication-conferences/operations'
        folder.mkdir(parents=True)
        (folder / (self.agenda + '.json')).write_text(json.dumps({'businessExperiment': {'maxModelCalls': 1}}))
        usage.record_call(self.call(), 'started', root=self.root, now=self.now)
        with self.assertRaisesRegex(usage.UsageBudgetExceeded, 'agenda_call'):
            usage.record_call(self.call('two'), 'started', root=self.root, now=self.now)
        state = json.loads((self.data / 'llm_usage_ledger.json').read_text())
        self.assertEqual(len(state['active']), 1)

    def test_metered_rejection_never_calls_provider(self):
        (self.data / 'llm-settings.json').write_text(json.dumps({'resourceBudget': {'dailyCalls': 1}}))
        provider = MagicMock(return_value={'ok': True})
        metered = usage.metered(provider)
        recorder = functools.partial(usage.record_call, root=self.root)
        with patch.object(usage, 'record_call', side_effect=recorder), \
             patch.object(usage, 'agenda_identity', return_value=None), \
             patch('common.crew_chat_bridge.current_model_identity', return_value=(None, None)):
            metered(provider='test', model='model')
            with self.assertRaises(usage.UsageBudgetExceeded):
                metered(provider='test', model='model')
        self.assertEqual(provider.call_count, 1)
        self.assertIsNone(usage._CURRENT.get())

    def test_midnight_preserves_agenda_budget_and_route_health(self):
        usage.record_call(self.call(), 'started', root=self.root, now=self.now)
        usage.record_call(self.call(), 'completed', root=self.root, now=self.now)
        tomorrow = self.now + dt.timedelta(days=1)
        usage.record_call({**self.call('two'), 'startedAt': tomorrow.isoformat()}, 'started', root=self.root, now=tomorrow)
        state = json.loads((self.data / 'llm_usage_ledger.json').read_text())
        self.assertEqual(state['byModel'], {})
        self.assertEqual(state['byAgenda'][self.agenda]['inputTokens'], 100)

    def test_direct_cli_calls_use_the_same_route_circuit(self):
        provider = MagicMock(side_effect=RuntimeError('failed'))
        provider.__module__ = 'common.codex_cli'
        metered = usage.metered(provider)
        recorder = functools.partial(usage.record_call, root=self.root)
        route = functools.partial(usage.route_attempt, root=self.root)
        with patch.object(usage, 'record_call', side_effect=recorder), \
             patch.object(usage, 'route_attempt', side_effect=route), \
             patch.object(usage, 'agenda_identity', return_value=None), \
             patch('common.crew_chat_bridge.current_model_identity', return_value=(None, None)):
            for _ in range(3):
                with self.assertRaises(RuntimeError):
                    metered(model='bad')
            with self.assertRaises(usage.RouteCoolingDown):
                metered(model='bad')
        self.assertEqual(provider.call_count, 3)

    def test_repeated_failures_open_route_and_one_probe_recovers(self):
        clock = [1000]
        for _ in range(3):
            with self.assertRaises(ValueError), usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
                raise ValueError('provider failed')
        with self.assertRaises(usage.RouteCoolingDown), usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
            self.fail('Cooling route must not run')
        with usage.route_attempt('test', 'other', root=self.root, now=lambda: clock[0]):
            pass
        clock[0] += 301
        with usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
            with self.assertRaises(usage.RouteCoolingDown), usage.route_attempt('test', 'bad', root=self.root, now=lambda: clock[0]):
                self.fail('Only one probe is allowed')
        self.assertEqual(json.loads((self.data / 'llm_usage_ledger.json').read_text())['routeHealth']['test:bad']['failures'], 0)

    def page_report(self, rows=None):
        return {'complete': True, 'checkedAt': self.now.isoformat(), 'currency': 'USD',
                'source': 'AdSense Management API v2', 'dimension': 'PAGE_URL',
                'start': (self.now.date() - dt.timedelta(days=7)).isoformat(),
                'end': (self.now.date() - dt.timedelta(days=1)).isoformat(),
                'timezone': 'Asia/Seoul', 'pages': rows or []}

    def test_actual_revenue_field_reaches_learning_and_partial_domains(self):
        address = 'https://www.example.com/post'
        node = {'type': 'Post', 'url': address, 'measurements': {}, 'publishedAt': self.now.isoformat()}
        graph = {'nodes': {synapse.key('post', synapse.url(address)): node}}
        report = self.page_report([{'url': address, 'estimatedRevenue': 1.25}])
        report.update(complete=False, sites=[{'domain': 'example.com', 'complete': True}, {'domain': 'other.com', 'complete': False}])
        synapse.observe(graph, report, 'adsense', ['revenue'])
        self.assertEqual(node['measurements']['adsense']['revenue'], 1.25)
        node['measurements'] = {}
        report['checkedAt'] = (self.now - dt.timedelta(hours=27)).isoformat()
        synapse.observe(graph, report, 'adsense', ['revenue'])
        self.assertEqual(node['measurements'], {})

    def test_missing_page_revenue_is_not_a_zero_or_winner(self):
        result = page_performance_evidence(now=self.now, metrics={'pagePerformance': self.page_report()},
                    revenue={'pagePerformance': {**self.page_report(), 'complete': False}}, traffic_source={}, domains=[])
        self.assertFalse(result['coverage']['revenueComplete'])
        self.assertEqual(result['revenueWinners'], [])

    def test_page_report_filters_content_product_and_preserves_missingness(self):
        cfg = {f'TEST_{k}': 'dummy' for k in ('ACCOUNT_ID', 'CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN')}
        client = MagicMock()
        meta = {'state': 'READY', 'timeZone': {'id': 'Asia/Seoul'}}
        report = {'headers': [{'name': 'PAGE_URL'}, {'name': 'ESTIMATED_EARNINGS', 'currencyCode': 'USD'}]}
        with patch('google.auth.transport.requests.AuthorizedSession') as session:
            session.return_value.__enter__.return_value = client
            client.get.side_effect = [MagicMock(ok=True, json=lambda: meta), MagicMock(ok=True, json=lambda: report)]
            with self.assertRaisesRegex(revenue.RevenueSourceError, 'No eligible page rows'):
                revenue.adsense_page_performance(cfg, self.now.date(), self.now.date(), ['example.com'], 'TEST')
            self.assertEqual(client.get.call_args.kwargs['params']['filters'], ['PRODUCT_CODE==AFC'])

    def test_frequent_refresh_collects_pages_once_and_refreshes_feedback(self):
        from common.revenue_refresh import collect_once
        backend = MagicMock()
        backend.read_json.side_effect = lambda p: json.loads(p.read_text()) if p.exists() else {}
        backend.collector_lock.side_effect = lambda p: nullcontext(True)
        backend.revenue_config.return_value = {}
        backend.ADPOST_ACCOUNTS = []
        backend.RevenueSourceError = revenue.RevenueSourceError
        backend.source = revenue.source
        backend.affiliate_configuration.return_value = {}
        backend.coupang.return_value = {'status': 'collected', 'daily': {}}
        backend.collect_page_revenue.return_value = {'complete': False, 'pages': [], 'sites': []}
        with patch('common.crew_chat_bridge.emit_work_event'), \
             patch('server.growth.refresh_performance_feedback', return_value={'status': 'partial'}) as refresh:
            collect_once(root=self.root, now=self.now, backend=backend)
            collect_once(root=self.root, now=self.now + dt.timedelta(seconds=60), backend=backend)
        self.assertEqual(backend.collect_page_revenue.call_count, 1)
        self.assertEqual(refresh.call_count, 2)
        self.assertFalse(json.loads((self.data / 'revenue.json').read_text())['pagePerformance']['complete'])

    def test_fallback_calls_have_separate_usage_and_correct_error(self):
        from common import llm_client
        config = {'active': 'codex', 'providers': {'codex': {'model': 'primary'}}}
        call = self.call()
        def respond(*args):
            usage.report_response(data={'usage': {'input_tokens': 30, 'output_tokens': 5}})
            return {'ok': True}, 'fallback'
        def generate(*args):
            if args[1] == 'codex':
                usage.report_response(data={'usage': {'input_tokens': 10, 'output_tokens': 2}})
                raise RuntimeError('exceeded its hard timeout')
            return respond(*args)
        token = usage._CURRENT.set(call)
        self.addCleanup(usage._CURRENT.reset, token)
        with patch.object(llm_client.settings, 'load', return_value=config), \
             patch.object(llm_client, '_generate_json', side_effect=generate), \
             patch('common.crew_chat_bridge.record_model_route'), \
             patch.object(usage, '_safe_record') as record:
            result = llm_client.generate_json.__wrapped__.__wrapped__('prompt', provider='codex', reasoning_effort='low')
        self.assertEqual(result, {'ok': True})
        rejected = record.call_args_list[0].args[0]
        self.assertEqual(rejected['errorType'], 'RuntimeError')
        self.assertNotEqual(rejected['id'], call['id'])
        self.assertEqual((rejected['inputTokens'], call['inputTokens']), (110, 30))

    def test_experiment_requires_measurement_and_bounded_resources(self):
        from common.work_agenda import validate_business_experiment
        value = dict(hypothesis='Link improves acquisition', targetUrl='https://example.com/post',
                     measurementDate='2026-11-02', evidenceConfidence='low', maxModelCalls=4,
                     successMetric='Measured UTM sessions', stopCondition='Stop after observation with no acquisition')
        self.assertEqual(validate_business_experiment(value), value)
        with self.assertRaises(ValueError):
            validate_business_experiment({**value, 'maxModelCalls': 0})
        with self.assertRaises(ValueError):
            validate_business_experiment({**value, 'measurementDate': 'soon'})


if __name__ == '__main__':
    unittest.main()
