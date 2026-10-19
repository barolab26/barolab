"""No-network submission safety and receipt truth regressions."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from dashboard import metrics, traffic
from dashboard import indexing_submissions as indexing

SITE = {'site_id': 'example.com', 'url': 'https://www.example.com/', 'platform': 'cf'}
URL = SITE['url']+'article'


class SubmissionTests(unittest.TestCase):
    def test_naver_registration_requires_exact_www_ui_proof_not_ping(self):
        ledger=Path(self.temp.name)/'naver-registry.json'
        observed={'site':SITE['url'].rstrip('/'),'registration':{'status':'registered','evidence':'UI'},
                  'ownership':{'status':'verified','evidence':'UI','checkedAt':'2026-10-19T12:00:00+09:00'},
                  'rss':{'status':'blocked_captcha'}}
        metrics.atomic_write(ledger,{'sites':{SITE['site_id']:observed}})
        result=metrics.searchadvisor_registration(SITE,ledger)
        self.assertTrue(result['registered']);self.assertIsNone(result['indexed'])
        self.assertEqual(result['rss']['status'],'blocked_captcha')
        observed['site']='https://example.com'
        metrics.atomic_write(ledger,{'sites':{SITE['site_id']:observed}})
        self.assertIsNone(metrics.searchadvisor_registration(SITE,ledger)['registered'])
        metrics.atomic_write(ledger,{'sites':{SITE['site_id']:{'status':'ping_accepted'}}})
        self.assertIsNone(metrics.searchadvisor_registration(SITE,ledger)['registered'])
    def test_authorized_regular_mode_and_cap_zero_no_browser(self):
        config={'url_inspection':{'mode':'authorized_request_owner_ui','request_indexing_authorized':True,
                                 'request_indexing_accounts':['sj'],'browser_accounts':['sj']}}
        self.assertFalse(metrics.authorized_gsc_request_mode({}))
        self.assertTrue(metrics.authorized_gsc_request_mode(config))
        self.assertFalse(metrics.authorized_gsc_request_mode(config,requested=False))
        with self.assertRaises(ValueError): metrics.authorized_gsc_request_mode({},requested=True)
        with patch.object(indexing,'gsc_budget',return_value={'remaining':0}), patch.object(metrics,'browser_fallback_sites') as fallback:
            result=metrics.collect_browser_inspections(config,[])
        self.assertEqual(result['status'],'daily_budget_exhausted');fallback.assert_not_called()

    def test_queue_dedup_and_cap_exhausted_keeps_pending(self):
        config={'url_inspection':{'mode':'authorized_request_owner_ui','request_indexing_authorized':True,
                                 'request_indexing_accounts':['sj']}}
        original=metrics.read_json
        with patch.object(metrics,'read_json',wraps=original) as read, patch.object(metrics,'inventory',return_value=[SITE]):
            read.side_effect=lambda path,*args:config if path==metrics.CONFIG else original(path,*args)
            one=indexing.enqueue_gsc_request('all',ledger=self.ledger)
            two=indexing.enqueue_gsc_request('all',ledger=self.ledger)
        self.assertEqual(one['runId'],two['runId']);self.assertFalse(one['started'])
        indexing.record_gsc_queue_cycle([SITE['site_id']],{'status':'daily_budget_exhausted'},ledger=self.ledger)
        self.assertEqual(indexing._load(self.ledger)['gscQueue'][0]['status'],'queued')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.temp.name)/'submissions.json'
        self.data = patch.object(metrics, 'DATA', Path(self.temp.name)); self.data.start()
        self.now = datetime(2026, 10, 19, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.data.stop(); self.temp.cleanup()

    def test_gsc_requires_authorization_exact_evidence_and_canonical(self):
        with self.assertRaisesRegex(ValueError, 'EXPLICIT'):
            indexing.reserve_gsc_request('sj', SITE, URL, ledger=self.ledger)
        for url in ('https://example.com/article', SITE['url']+'index-rescue-test', URL+'?a=1'):
            with self.assertRaises(ValueError):
                indexing.reserve_gsc_request('sj', SITE, url, authorized=True, evidence={'url':url,'indexed':False},ledger=self.ledger)
        with self.assertRaisesRegex(ValueError, 'EVIDENCE'):
            indexing.reserve_gsc_request('sj', SITE, URL, authorized=True, evidence={'url':URL,'indexed':True},ledger=self.ledger)

    def test_gsc_daily_limit_dedup_and_unknown_consumes_budget(self):
        for i in range(10):
            url = URL+str(i)
            result = indexing.reserve_gsc_request('sj',SITE,url,authorized=True,evidence={'url':url,'indexed':False},ledger=self.ledger,now=self.now)
            self.assertEqual(result['status'],'reserved')
        self.assertEqual(indexing.gsc_budget('sj',ledger=self.ledger,now=self.now)['remaining'],0)
        self.assertEqual(indexing.reserve_gsc_request('sj',SITE,URL+'10',authorized=True,evidence={'url':URL+'10','indexed':False},ledger=self.ledger,now=self.now)['status'],'daily_budget_exhausted')
        self.assertEqual(indexing.reserve_gsc_request('sj',SITE,URL+'0',authorized=True,evidence={'url':URL+'0','indexed':False},ledger=self.ledger,now=self.now)['status'],'duplicate_suppressed')

    def test_gsc_kst_day_and_history_union(self):
        metrics.atomic_write(metrics.DATA/'indexing-recovery.json',{'events':[{'url':URL,'account':'sj','at':'2026-10-18T16:00:00+00:00','outcome':'requested'}]})
        self.assertEqual(indexing.gsc_budget('sj',ledger=self.ledger,now=self.now)['used'],1)

    def test_gsc_complete_requires_proof_and_never_sets_indexed(self):
        e=indexing.reserve_gsc_request('sj',SITE,URL,authorized=True,evidence={'url':URL,'indexed':False},ledger=self.ledger)
        with self.assertRaises(ValueError): indexing.complete_gsc_request(e['id'],'requested',ledger=self.ledger)
        done=indexing.complete_gsc_request(e['id'],'requested',evidence={'dialog':'requested'},ledger=self.ledger)
        self.assertIsNone(done['indexed'])
        self.assertEqual(indexing.complete_gsc_request(e['id'],'requested',evidence=True,ledger=self.ledger),done)

    def test_provider_quota_stops_remaining_requests_for_day(self):
        e=indexing.reserve_gsc_request('sj',SITE,URL,authorized=True,evidence={'url':URL,'indexed':False},ledger=self.ledger,now=self.now)
        indexing.complete_gsc_request(e['id'],'quota_exceeded',evidence={'dialog':'quota'},ledger=self.ledger)
        self.assertEqual(indexing.gsc_budget('sj',ledger=self.ledger,now=self.now)['remaining'],0)

    def test_indexnow_two_receipts_and_no_duplicate_transport(self):
        client=Mock();client.get.return_value=SimpleNamespace(status_code=200,text='test-key-123')
        client.post.side_effect=[SimpleNamespace(status_code=200),SimpleNamespace(status_code=202)]
        args=dict(providers=('global','bing'),ledger=self.ledger,client=client)
        result=indexing.submit_indexnow(SITE,{'indexnow_key':'test-key-123'},[URL],**args)
        self.assertEqual(result['global']['status'],'ping_accepted');self.assertIsNone(result['global']['registered'])
        self.assertEqual(result['bing']['status'],'accepted_pending_key_check')
        self.assertEqual(client.post.call_count,2)
        again=indexing.submit_indexnow(SITE,{'indexnow_key':'test-key-123'},[URL],**args)
        self.assertEqual(again['global']['status'],'duplicate_suppressed');self.assertEqual(client.post.call_count,2)
        self.assertNotIn('test-key-123',self.ledger.read_text())

    def test_indexnow_timeout_keeps_intent_and_blocks_repeat(self):
        client=Mock();client.get.return_value=SimpleNamespace(status_code=200,text='test-key-123');client.post.side_effect=RuntimeError('secret-url')
        result=indexing.submit_indexnow(SITE,{'indexnow_key':'test-key-123'},[URL],providers=('bing',),ledger=self.ledger,client=client)
        self.assertEqual(result['bing']['status'],'submission_unconfirmed')
        indexing.submit_indexnow(SITE,{'indexnow_key':'test-key-123'},[URL],providers=('bing',),ledger=self.ledger,client=client)
        self.assertEqual(client.post.call_count,1);self.assertNotIn('secret-url',self.ledger.read_text())

    def test_bing_only_documented_success_and_quota_shapes(self):
        client=Mock();client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':None})
        self.assertIsNone(traffic.bing_submission_request('SubmitUrlBatch',SITE['url'],{'key':'private'},[URL],client)[1])
        client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{'error':'fail'})
        self.assertEqual(traffic.bing_submission_request('SubmitUrlBatch',SITE['url'],{'key':'private'},[URL],client)[1],'BING_RESPONSE_INVALID')
        for method in ('DeleteSite','SubmitUrl','GetUserSites'):
            with self.assertRaises(ValueError):traffic.bing_submission_request(method,SITE['url'],{},client=client)
        with self.assertRaises(ValueError):traffic.bing_submission_request('SubmitUrlBatch',SITE['url'],{'key':'private'},[URL]*501,client)
        client.get.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':{'DailyQuota':True,'MonthlyQuota':9}})
        self.assertEqual(traffic.bing_submission_request('GetUrlSubmissionQuota',SITE['url'],{'key':'private'},client=client)[1],'BING_QUOTA_INVALID')

    def test_bing_quota_caps_batch_and_requires_actual_property(self):
        client=Mock();client.get.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':{'DailyQuota':1,'MonthlyQuota':2}})
        client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':None})
        blocked=indexing.submit_bing(SITE,SITE['url'],[URL],{'key':'private'},verified_properties=set(),ledger=self.ledger,client=client)
        self.assertEqual(blocked['status'],'property_unverified');client.get.assert_not_called()
        result=indexing.submit_bing(SITE,SITE['url'],[URL,URL+'2'],{'key':'private'},verified_properties={SITE['url']},ledger=self.ledger,client=client)
        self.assertEqual(result['submittedCount'],1);self.assertIsNone(result['indexed'])
        self.assertNotIn('private',self.ledger.read_text())

    def test_bing_registration_is_authorized_inventory_scoped_and_exact_response(self):
        client=Mock();client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':None})
        with patch.object(traffic,'inventory',return_value=[SITE]):
            with self.assertRaises(ValueError): traffic.bing_site_registration('AddSite',SITE['url'],{},client=client)
            for method,url in [('DeleteSite',SITE['url']),('AddSite','https://www.unowned.test/')]:
                with self.assertRaises(ValueError):traffic.bing_site_registration(method,url,{},authorized=True,client=client)
            client.post.assert_not_called()
            result=traffic.bing_site_registration('AddSite',SITE['url'],{'key':'private'},authorized=True,client=client)
            self.assertEqual(result['status'],'added');self.assertFalse(result['verified'])
            client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':'true'})
            self.assertFalse(traffic.bing_site_registration('VerifySite',SITE['url'],{'key':'private'},authorized=True,client=client)['verified'])
            client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':True})
            self.assertTrue(traffic.bing_site_registration('VerifySite',SITE['url'],{'key':'private'},authorized=True,client=client)['verified'])
            client.post.side_effect=RuntimeError('private request credential')
            failed=traffic.bing_site_registration('VerifySite',SITE['url'],{'key':'private'},authorized=True,client=client)
            self.assertEqual(failed['status'],'request_unconfirmed');self.assertNotIn('private',str(failed))

    def test_bing_verification_material_selects_only_exact_configured_site(self):
        rows=[{'Url':SITE['url'],'IsVerified':False,'AuthenticationCode':'public-code','DnsVerificationCode':'public-dns'},
              {'Url':'https://www.other.test/','AuthenticationCode':'other-code'}]
        client=Mock();client.get.return_value=SimpleNamespace(status_code=200,json=lambda:{'d':rows})
        with patch.object(traffic,'inventory',return_value=[SITE]):
            material,error=traffic.bing_verification_material(SITE['url'],{'key':'private'},client)
            self.assertIsNone(error);self.assertEqual(material['authenticationCode'],'public-code')
            self.assertNotIn('other-code',str(material))
            with self.assertRaises(ValueError):traffic.bing_verification_material('https://example.com/',{},client)

    def test_bing_dns_exact_zone_reuses_matching_record_and_rejects_conflict(self):
        name='a'*32+'.example.com'
        record={'id':'record','name':name,'type':'CNAME','content':'verify.bing.com','proxied':False}
        def response(data):return SimpleNamespace(status_code=200,json=lambda:{'success':True,'result':data})
        zone={'name':'example.com','status':'active','account':{'id':'account'}}
        client=Mock();client.get.side_effect=[response(zone),response([record]),response(record)]
        with patch.object(traffic,'inventory',return_value=[SITE]):
            result=traffic.ensure_bing_verification_cname('example.com',name,'zone',{},authorized=True,client=client)
            self.assertEqual(result['action'],'reused');client.post.assert_not_called()
            client.get.side_effect=[response(zone),response([{**record,'content':'unrelated.example'}])]
            with self.assertRaisesRegex(ValueError,'CONFLICT'):
                traffic.ensure_bing_verification_cname('example.com',name,'zone',{},authorized=True,client=client)
            client.post.assert_not_called()
            with self.assertRaises(ValueError):traffic.ensure_bing_verification_cname('example.com','bad.other.test','zone',{},authorized=True,client=client)
            client.get.side_effect=[response(zone),response([]),response(record)]
            client.post.return_value=response(record)
            created=traffic.ensure_bing_verification_cname('example.com',name,'zone',{},authorized=True,client=client)
            self.assertEqual(created['action'],'created')
            self.assertFalse(client.post.call_args.kwargs['json']['proxied'])
            client.put.assert_not_called();client.delete.assert_not_called()

    def test_google_empty_successful_list_is_not_submitted(self):
        sitemap={'status':'available','url':SITE['url']+'sitemap.xml'}
        with patch.object(metrics,'api',side_effect=[ValueError('denied'),{'sitemap':[]} ]):
            result=metrics.request_indexing(object(),SITE,{},[URL],sitemap,indexnow=False)
        self.assertNotEqual(result['google']['status'],'submitted')

    def test_public_http_redirect_wrong_canonical_noindex_rejected(self):
        client=Mock()
        for code,body in [(301,''),(200,'<link rel="canonical" href="https://example.com/article">'),(200,f'<link rel="canonical" href="{URL}"><meta name="robots" content="noindex">')]:
            client.get.return_value=SimpleNamespace(status_code=code,text=body,headers={})
            self.assertFalse(indexing.validate_public_url(SITE,URL,client)['valid'])
        client.get.return_value=SimpleNamespace(status_code=200,text=f'<link rel="canonical" href="{URL}">',headers={})
        self.assertTrue(indexing.validate_public_url(SITE,URL,client)['valid'])

    def test_daum_search_absence_never_proves_no_registration(self):
        client=Mock();client.get.return_value=SimpleNamespace(status_code=200,text='<html>empty</html>')
        state=indexing.observe_daum(SITE,client)
        self.assertIsNone(state['registrationVerified']);self.assertIsNone(state['searchResultObserved'])
        self.assertEqual(state['registrationUrl'],'https://register.search.daum.net/index.daum')

    def test_auto_indexer_queues_verified_urls_without_claiming_ui_submission(self):
        from common import auto_indexer
        from cf_posting import searchadvisor
        url='https://www.must-good.com/real-article'
        reports=[{'domain':'must-good.com','_validatedCandidates':[url],
                  '_publicValidations':[{'url':url,'valid':True,'httpStatus':200,'canonical':url}]}]
        real_queue=searchadvisor.queue_crawl_candidates
        with patch.object(auto_indexer,'SERVER_DATA_DIR',Path(self.temp.name)), \
                patch.object(searchadvisor,'queue_crawl_candidates',side_effect=lambda urls,**kw:real_queue(urls,**kw,path=Path(self.temp.name)/'naver.json')), \
                patch.object(auto_indexer.requests,'post') as post:
            result=auto_indexer._queue_searchadvisor_candidates(reports)
            again=auto_indexer._queue_searchadvisor_candidates(reports)
        self.assertEqual(result['status'],'blocked_ui_required')
        self.assertEqual(result['queued'],1);self.assertEqual(again['duplicate'],1)
        post.assert_not_called()


if __name__=='__main__':unittest.main()
