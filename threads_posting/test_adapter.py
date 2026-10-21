import os
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from . import adapter as a

def setUpModule():
    directory=tempfile.TemporaryDirectory();unittest.addModuleCleanup(directory.cleanup)
    guard=patch('common.ego_telemetry.DIRECTORY',Path(directory.name));guard.start();unittest.addModuleCleanup(guard.stop)


def response(value,status=200):
    item=Mock();item.status_code=status;item.json.return_value=value;return item


class AdapterTests(unittest.TestCase):
    def test_api_action_tracks_real_return_and_failure_without_payload(self):
        from common import ego_telemetry as t
        events=[]
        with patch.object(t,'_record',side_effect=lambda *args:events.append(args)),patch.object(a.requests,'request',return_value=response({'id':'1'})):
            a.Client(self.config).request('GET','me',{'secret':'private-payload'})
        self.assertEqual([e[3] for e in events],['before','after'])
        self.assertTrue(all(e[1]=='threads-api-read' for e in events))
        self.assertNotIn('private-payload',str(events))
        events.clear()
        with patch.object(t,'_record',side_effect=lambda *args:events.append(args)),patch.object(a.requests,'request',side_effect=requests.RequestException('private')):
            with self.assertRaises(a.AdapterError):a.Client(self.config).request('POST','me/threads',{})
        self.assertEqual([e[3] for e in events],['before','failed'])
    def setUp(self):
        self.env=patch.dict(os.environ,{'THREADS_ACCESS_TOKEN':'private-test-token'});self.env.start()
        self.config={'account_key':'mustpickinfo','api':{}}
        self.part={'kind':'main','text':'Useful standalone answer','part_id':'part1','attempt_id':'try1','outbound_url':None}

    def tearDown(self):self.env.stop()

    def test_wsl_windows_token_reference_uses_existing_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / 'token.json'
            token.write_text('{"access_token":"fixture-token"}', encoding='utf-8')
            filename = r'C:\Users\example\.barolab\secrets\threads.json'
            with patch.dict(os.environ, {}, clear=True), \
                    patch.object(a, 'is_wsl', return_value=True), \
                    patch.object(a, 'to_wsl_path', return_value=str(token)) as convert:
                self.assertEqual(a._token({'api': {'token_file': filename}}), 'fixture-token')
                convert.assert_called_once_with(filename)

    def test_missing_wsl_token_fails_without_network(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {}, clear=True), \
                patch.object(a, 'is_wsl', return_value=True), \
                patch.object(a, 'to_wsl_path', return_value=str(Path(directory) / 'missing.json')), \
                patch.object(a.requests, 'request') as request:
            result = a.connection_status({'api': {'token_file': r'C:\missing.json'}})
            self.assertEqual(result['reason'], 'needs_connection')
            request.assert_not_called()

    def test_native_host_never_maps_windows_token_reference(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(a, 'is_wsl', return_value=False), \
                patch.object(a, 'to_wsl_path') as convert:
            with self.assertRaises(a.AdapterError):
                a._token({'api': {'token_file': r'C:\missing-test-token.json'}})
            convert.assert_not_called()

    def sequence(self):
        return [response({'id':'123','username':'mustpickinfo'}),
                response({'data':[{'quota_usage':0,'config':{'quota_total':250},'reply_quota_usage':0,'reply_config':{'quota_total':1000}}]}),
                response({'id':'100'}),response({'status':'FINISHED'}),response({'id':'200'}),
                response({'permalink':'https://www.threads.com/@mustpickinfo/post/ABC','timestamp':'2026-10-15T10:00:00+0000'})]

    @patch.object(a.requests,'request')
    def test_missing_connection_never_calls_network(self,request):
        with patch.dict(os.environ,{},clear=True):
            result=a.connection_status(self.config)
        self.assertFalse(result['connected']);self.assertEqual(result['reason'],'needs_connection');request.assert_not_called()

    @patch.object(a.requests,'request',return_value=response({'id':'123','username':'other'}))
    def test_wrong_identity_prevents_any_publish(self,request):
        callback=Mock()
        with self.assertRaises(a.AdapterError) as ctx:a.submit_part(self.config,self.part,callback)
        self.assertEqual(ctx.exception.code,'account_identity_mismatch');callback.assert_not_called();self.assertEqual(request.call_count,1)

    @patch.object(a.requests,'request')
    def test_two_phase_callback_and_no_auto_publish(self,request):
        request.side_effect=self.sequence();calls=[]
        def callback():calls.append(request.call_count)
        result=a.submit_part(self.config,self.part,callback)
        self.assertEqual(calls,[4]);self.assertEqual(result['platform_id'],'200')
        self.assertEqual(result['published_at'],'2026-10-15T10:00:00+00:00')
        create=request.call_args_list[2].kwargs['data'];self.assertNotIn('auto_publish_text',create)
        self.assertTrue(all(call.kwargs['verify'] and call.kwargs['allow_redirects'] is False for call in request.call_args_list))

    @patch.object(a.requests,'request')
    def test_create_transport_failure_is_not_a_publication(self,request):
        request.side_effect=self.sequence()[:2]+[requests.Timeout('private-test-token')];callback=Mock()
        with self.assertRaises(a.AdapterError) as ctx:a.submit_part(self.config,self.part,callback)
        self.assertFalse(ctx.exception.uncertain);self.assertEqual(ctx.exception.stage,'create');callback.assert_not_called();self.assertNotIn('private-test-token',str(ctx.exception))

    @patch.object(a.requests,'request')
    def test_publish_timeout_is_uncertain_and_never_retried(self,request):
        request.side_effect=self.sequence()[:4]+[requests.Timeout('private-test-token')];callback=Mock()
        with self.assertRaises(a.AdapterError) as ctx:a.submit_part(self.config,self.part,callback)
        self.assertTrue(ctx.exception.uncertain);callback.assert_called_once();self.assertEqual(request.call_count,5)

    @patch.object(a.time,'sleep')
    @patch.object(a.requests,'request')
    def test_processing_container_uses_same_id_bounded(self,request,sleep):
        request.side_effect=self.sequence()[:3]+[response({'status':'IN_PROGRESS'})]*4
        with self.assertRaises(a.AdapterError) as ctx:a.submit_part(self.config,self.part,Mock())
        self.assertEqual(ctx.exception.container_id,'100');self.assertEqual(sleep.call_count,3)
        self.assertEqual(sum(call.args[0]=='POST' for call in request.call_args_list),1)

    @patch.object(a.requests,'request')
    def test_public_read_shell_stays_unverified(self,request):
        request.side_effect=[self.sequence()[0],response({'id':'200','username':'mustpickinfo','text':self.part['text'],'permalink':'https://www.threads.com/@mustpickinfo/post/ABC','timestamp':'2026-10-15T10:00:00Z'})]
        html=Mock(status_code=200,content=b'<html>Login</html>',text='<html>Login</html>')
        with patch.object(a.requests,'get',return_value=html):result=a.verify_public(self.config,self.part,{'platform_id':'200'})
        self.assertFalse(result['verified']);self.assertFalse(result['public']);self.assertEqual(result['reason'],'anonymous_public_body_unmatched')
        self.assertEqual(result['published_at'],'2026-10-15T10:00:00+00:00')

    @patch.object(a.requests,'request')
    def test_public_owner_body_and_permalink_match(self,request):
        request.side_effect=[self.sequence()[0],response({'id':'200','username':'mustpickinfo','text':self.part['text'],'permalink':'https://www.threads.com/@mustpickinfo/post/ABC'})]
        html=Mock(status_code=200,content=b'body',text='<html><body>Useful standalone answer</body></html>')
        with patch.object(a.requests,'get',return_value=html):result=a.verify_public(self.config,self.part,{'platform_id':'200'})
        self.assertTrue(result['verified']);self.assertTrue(result['public'])

    def test_public_static_token_paths_forbidden(self):
        for directory in ('dashboard','cf_posting','naver_blog_posting'):
            with patch.dict(os.environ,{},clear=True):
                with self.assertRaises(a.AdapterError) as ctx:a._token({'api':{'token_file':str(a.ROOT/directory/'secret.json')}})
            self.assertEqual(ctx.exception.code,'public_token_reference_forbidden')

    def test_reply_requires_exact_parent(self):
        with self.assertRaises(a.AdapterError):a.submit_part(self.config,{**self.part,'kind':'followup'},Mock())

    def test_oauth_requirements_and_authorization_url(self):
        config={'oauth':{'redirect_uri':'https://example.com/threads/callback'}}
        with patch.dict(os.environ,{'THREADS_APP_ID':'123','THREADS_APP_SECRET':'private-secret'}):
            self.assertTrue(a.authorization_requirements(config)['ready'])
            url=a.build_authorization_url(config,'a'*40)
            self.assertIn('state=',url);self.assertNotIn('private-secret',url)
        self.assertFalse(a.authorization_requirements({'oauth':{'redirect_uri':'http://localhost/cb'}})['ready'])


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'THREADS_ACCESS_TOKEN':'private-readiness-token'});self.env.start()
        self.config={'account_key':'mustpickinfo','maxFollowups':1,'api':{}}

    def tearDown(self):self.env.stop()

    def replies(self,**changes):
        metadata={'user_id':'123','is_valid':True,'scopes':sorted(a.REQUIRED_SCOPES),
                  'expires_at':int((datetime.now(timezone.utc)+timedelta(days=60)).timestamp())}
        metadata.update(changes)
        quota={'quota_usage':1,'config':{'quota_total':250},'reply_quota_usage':1,'reply_config':{'quota_total':1000}}
        return [response({'id':'123','username':'mustpickinfo'}),response({'data':metadata}),response({'data':[quota]})]

    @patch.object(a.requests,'request')
    def test_verified_scopes_expiry_identity_and_quota(self,request):
        request.side_effect=self.replies();value=a.readiness_status(self.config)
        self.assertTrue(value['connected']);self.assertTrue(value['publishReady']);self.assertTrue(value['ready'])
        self.assertEqual(value['expiryStatus'],'verified');self.assertTrue(value['expiresAtUTC'].endswith('+00:00'))
        self.assertEqual(value['quota']['posts']['remaining'],249)
        self.assertNotIn('private-readiness-token',str(value));self.assertEqual(request.call_count,3)
        self.assertEqual(request.call_args_list[1].args[0],'GET');self.assertNotIn('client_secret',request.call_args_list[1].kwargs['params'])

    @patch.object(a.requests,'request')
    def test_missing_grant_connected_but_not_ready(self,request):
        request.side_effect=self.replies(scopes=['threads_basic']);value=a.readiness_status(self.config)
        self.assertTrue(value['connected']);self.assertFalse(value['publishReady'])
        self.assertIn('threads_content_publish',value['missingScopes']);self.assertEqual(value['scopesStatus'],'missing')

    @patch.object(a.requests,'request')
    def test_unknown_expiry_never_verified(self,request):
        request.side_effect=self.replies(expires_at=0);value=a.readiness_status(self.config)
        self.assertEqual(value['expiryStatus'],'unknown');self.assertIsNone(value['expiresAtUTC']);self.assertFalse(value['publishReady'])

    @patch.object(a.requests,'request')
    def test_expired_or_different_token_identity_blocked(self,request):
        request.side_effect=self.replies(user_id='999',expires_at=1);value=a.readiness_status(self.config)
        self.assertFalse(value['tokenUserMatches']);self.assertEqual(value['expiryStatus'],'expired');self.assertFalse(value['ready'])

    @patch.object(a.requests,'request')
    def test_debug_transport_redacted_keeps_grants_unknown(self,request):
        rows=self.replies();request.side_effect=[rows[0],requests.Timeout('https://graph.threads.com/debug_token?input_token=private-readiness-token'),rows[2]]
        value=a.readiness_status(self.config)
        self.assertTrue(value['connected']);self.assertEqual(value['scopesStatus'],'unknown');self.assertFalse(value['publishReady'])
        self.assertNotIn('private-readiness-token',str(value));self.assertNotIn('debug_token?',str(value))


if __name__=='__main__':unittest.main()


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.url='https://www.must-pick.com/article?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge&utm_content=unique1'
        text='Useful answer '+self.url
        self.part={'account_key':'mustpickinfo','text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'outbound_url':self.url,'intent_at':'2026-10-15T11:00:00+00:00'}
        self.row={'id':'200','username':'mustpickinfo','text':text,'timestamp':'2026-10-15T11:01:00+0000','permalink':'https://www.threads.com/@mustpickinfo/post/ABC'}
    def run_rows(self,rows,paging=None):
        with patch.object(a,'Client') as factory,patch.object(a,'_identity'):
            client=factory.return_value
            client.request.return_value={'data':rows,**({'paging':paging} if paging else {})}
            result=a.recover_unknown({},self.part)
            self.assertTrue(all(call.args[0]=='GET' for call in client.request.call_args_list))
            self.assertLessEqual(client.request.call_count,2)
            return result
    def test_unique_exact_match_evidence_contract(self):
        value=self.run_rows([self.row]);self.assertTrue(value['matched']);self.assertEqual(value['match_count'],1)
        for key in ('account_key','text_sha256','outbound_url'):self.assertEqual(value[key],self.part[key])
    def test_zero_multiple_earlier_and_mismatch_stay_unknown(self):
        for rows in ([],[self.row,{**self.row,'id':'201'}],[{**self.row,'timestamp':'2026-10-15T10:59:59+0000'}],[{**self.row,'text':self.row['text']+' '}],[{**self.row,'username':'someoneelse'}]):
            self.assertFalse(self.run_rows(rows)['matched'])
    def test_partial_or_malformed_paging_never_adopt(self):
        self.assertFalse(self.run_rows([self.row],{'next':'https://provider/?token=never-follow','cursors':{'after':'cursor1'}})['matched'])
        self.assertFalse(self.run_rows([self.row],{'next':'unsafe','cursors':['wrong']})['matched'])
    def test_invalid_ledger_never_queries(self):
        for change in ({'text_sha256':'wrong'},{'account_key':'someoneelse'},{'intent_at':None},{'outbound_url':self.url+'&utm_content=second'}):
            with patch.object(a,'Client') as client:
                self.assertFalse(a.recover_unknown({},{**self.part,**change})['matched']);client.assert_not_called()
