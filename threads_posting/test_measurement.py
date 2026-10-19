from datetime import datetime,timezone,timedelta
import unittest
from unittest.mock import Mock,patch
import sys

from . import measurement as m
from .adapter import AdapterError
if str(m.ROOT/'dashboard') not in sys.path:sys.path.insert(0,str(m.ROOT/'dashboard'))
import traffic


class MeasurementTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,16,3,tzinfo=timezone.utc)
        self.post={'part_id':'part1','attempt_id':'try1','account_key':'mustpickinfo','platform_id':'200',
                   'published_at':(self.now-timedelta(hours=25)).isoformat(),'outbound_url':None}

    @patch.object(m,'Client',side_effect=AdapterError('needs_connection'))
    def test_disconnected_is_unknown_not_zero(self,client):
        value=m.collect({},[self.post],self.now,persist=False)
        self.assertIsNone(value['account_metrics']['clicks']);self.assertIsNone(value['revenue'])
        snap=value['posts'][0]['snapshots']['24h'];self.assertIsNone(snap['platform']['metrics']['views']);self.assertIsNone(snap['ga4']['sessions'])
        self.assertEqual(value['windows']['24h']['status'],'partial')

    @patch.object(m,'Client',side_effect=AdapterError('needs_connection'))
    def test_checkpoint_not_due_does_not_query_ga(self,client):
        with patch.object(m,'_ga4') as ga:
            value=m.collect({},[{**self.post,'published_at':self.now.isoformat()}],self.now,persist=False)
        ga.assert_not_called();self.assertEqual(value['windows']['24h']['status'],'not_due');self.assertEqual(value['posts'][0]['snapshots'],{})

    @patch.object(m,'Client',side_effect=AdapterError('needs_connection'))
    def test_capture_lag_is_explicit(self,client):
        value=m.collect({},[self.post],self.now,persist=False)
        snap=value['posts'][0]['snapshots']['24h'];self.assertEqual(snap['actual_age_hours'],25);self.assertEqual(snap['capture_lag_hours'],1)

    def test_platform_missing_metric_remains_null(self):
        client=Mock();client.request.return_value={'data':[{'name':'views','values':[{'value':0}]}]}
        value=m._insights(client,'200/insights',m.PLATFORM_METRICS)
        self.assertEqual(value['metrics']['views'],0);self.assertIsNone(value['metrics']['likes']);self.assertEqual(value['status'],'partial')

    def test_utm_mismatch_never_queries_ga(self):
        value=m._ga4({**self.post,'outbound_url':'https://www.must-good.com/article?utm_source=naver_kin'},self.now)
        self.assertIsNone(value['sessions']);self.assertEqual(value['reason'],'attribution_url_unverified')

    def test_today_ga_is_pending_not_zero(self):
        value=m._ga4({**self.post,'published_at':self.now.isoformat(),'outbound_url':'https://www.must-good.com/article?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge&utm_content=part1'},self.now)
        self.assertEqual(value['status'],'pending_reporting');self.assertIsNone(value['sessions'])

    @patch.object(m,'Client',side_effect=AdapterError('needs_connection'))
    def test_foreign_account_and_future_publication_excluded(self,client):
        value=m.collect({},[{**self.post,'account_key':'other'},{**self.post,'published_at':(self.now+timedelta(hours=1)).isoformat()}],self.now,persist=False)
        self.assertEqual(value['posts'],[]);self.assertFalse(value['complete'])

    @patch.object(traffic,'session')
    @patch.object(traffic,'ga_report',return_value=([([], [0,0,0])],False))
    def test_exact_ga_filter_and_successful_zero(self,report,session):
        config={'sites':{'must-good.com':{'ga4_property':'123','analytics_reader':'existing'}},'analytics_readers':{}}
        post={**self.post,'outbound_url':'https://www.must-good.com/article?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge&utm_content=part1'}
        with patch.object(m,'_read',return_value=config):value=m._ga4(post,self.now)
        self.assertEqual(value['sessions'],0);self.assertTrue(value['complete'])
        body=report.call_args.args[2];filters=body['dimensionFilter']['andGroup']['expressions']
        self.assertEqual([row['filter']['stringFilter']['value'] for row in filters[:4]],['threads','social','cf_bridge','part1'])
        self.assertNotIn('dimensions',body)

    @patch.object(traffic,'session')
    @patch.object(traffic,'ga_report',return_value=([],True))
    def test_limited_ga_never_becomes_zero(self,report,session):
        config={'sites':{'must-good.com':{'ga4_property':'123','analytics_reader':'existing'}}}
        post={**self.post,'outbound_url':'https://www.must-good.com/article?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge&utm_content=part1'}
        with patch.object(m,'_read',return_value=config):value=m._ga4(post,self.now)
        self.assertIsNone(value['sessions']);self.assertFalse(value['complete'])

    @patch.object(m,'Client',side_effect=AdapterError('needs_connection'))
    @patch.object(m,'write')
    def test_successful_checkpoint_preserved_without_requery(self,write,client):
        snapshot={'captured_at':'original','actual_age_hours':24.1,'platform':{'status':'collected','metrics':{'views':5}},'ga4':{'complete':True,'sessions':1}}
        with patch.object(m,'_read',return_value={'posts':[{'part_id':'part1','snapshots':{'24h':snapshot}}]}),patch.object(m,'_ga4') as ga:
            value=m.collect({},[self.post],self.now)
        ga.assert_not_called();self.assertEqual(value['posts'][0]['snapshots']['24h']['captured_at'],'original')

    def observation(self,part,*,sessions=0,engaged=0,views=200,format='guide'):
        return {'part_id':part,'format':format,'topic':'topic','snapshots':{'24h':{'capture_lag_hours':0,
                'platform':{'status':'collected','metrics':{'views':views}},
                'ga4':{'complete':True,'sessions':sessions,'engaged_sessions':engaged,'page_views':sessions,
                       'start_date':'2026-10-15','end_date':'2026-10-15','provisional':True}}}}

    def test_feedback_small_sample_never_scales(self):
        value=m.feedback([self.observation('one',sessions=1000,engaged=900)],self.now)
        self.assertEqual(value['status'],'insufficient_data');self.assertEqual(value['authoringHints'],[])

    def test_feedback_cta_and_landing_include_observed_evidence(self):
        value=m.feedback([self.observation('one'),self.observation('two',sessions=10,engaged=1),self.observation('three')],self.now)
        self.assertEqual(value['status'],'diagnostic');self.assertEqual(len(value['evidence']),3)
        self.assertEqual(value['checkpoint'],'24h');self.assertTrue(value['authoringHints']);self.assertIn('computedAt',value)

    def test_feedback_format_requires_repeated_comparable_posts(self):
        posts=[self.observation(str(i),sessions=10,engaged=5,format='guide') for i in range(3)]
        posts += [self.observation(str(i+3),sessions=10,engaged=3,format='checklist') for i in range(3)]
        value=m.feedback(posts,self.now)
        self.assertTrue(any(row.startswith('format guide:') for row in value['recommendations']))

    def test_scheduler_gate_avoids_five_minute_measurement_calls(self):
        with patch.object(m,'_read',return_value={'collected_at':(self.now-timedelta(minutes=5)).isoformat()}):
            self.assertFalse(m.should_collect([self.post],self.now))
        with patch.object(m,'_read',return_value={}):self.assertTrue(m.should_collect([self.post],self.now))
        with patch.object(m,'_read',return_value={}):self.assertFalse(m.should_collect([{**self.post,'published_at':self.now.isoformat()}],self.now))

    @patch.object(m,'Client',side_effect=AdapterError('needs_connection'))
    def test_missing_actual_publication_time_stays_unknown(self,client):
        value=m.collect({},[{**self.post,'published_at':None}],self.now,persist=False)
        self.assertEqual(value['posts'][0]['status'],'publication_time_unverified')
        self.assertIsNone(value['posts'][0]['published_at']);self.assertEqual(value['posts'][0]['snapshots'],{})
        self.assertEqual(value['status'],'unmeasured');self.assertEqual(value['unmeasured_reason'],'publication_time_unverified')

    @patch.object(m,'Client',side_effect=AdapterError('needs_connection'))
    def test_observed_submission_time_is_not_actual_publication_time(self,client):
        value=m.collect({},[{**self.post,'publication_time_basis':'api_received_observed'}],self.now,persist=False)
        self.assertIsNone(value['posts'][0]['published_at']);self.assertEqual(value['unmeasured_reason'],'publication_time_unverified')


if __name__=='__main__':unittest.main()
