from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import requests
from . import auth
from .adapter import AdapterError
from . import config as settings,pipeline


class TokenReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'private/token.json'
        self.receiver=auth.Receiver({'account_key':'mustpickinfo'},token_path=self.path,ttl_seconds=30)
        self.thread=threading.Thread(target=self.receiver.serve,daemon=True);self.thread.start()

    def tearDown(self):
        self.receiver.done=True
        self.thread.join(timeout=4)
        self.receiver.server.server_close();self.tmp.cleanup()

    def post(self,**kwargs):
        data=kwargs.pop('data',{'token':'private-test-token','state':self.receiver.csrf})
        headers=kwargs.pop('headers',{'Origin':self.receiver.origin})
        return requests.post(self.receiver.url,data=data,headers=headers,timeout=3,**kwargs)

    def test_loopback_only_password_form_no_caching(self):
        self.assertEqual(self.receiver.server.server_address[0],'127.0.0.1')
        response=requests.get(self.receiver.url,timeout=3)
        self.assertIn('type="password"',response.text);self.assertIn('autocomplete="off"',response.text)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])
        self.assertNotIn('private-test-token',response.text)

    def test_wrong_origin_csrf_and_size_do_not_store(self):
        self.assertEqual(self.post(headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.post(data={'token':'private-test-token','state':'wrong'}).status_code,403)
        self.assertEqual(self.post(data='x'*20000,headers={'Origin':self.receiver.origin,'Content-Type':'application/x-www-form-urlencoded'}).status_code,413)
        self.assertFalse(self.path.exists());self.assertFalse(self.receiver.done)

    def test_public_storage_and_wrong_host_rejected(self):
        with self.assertRaises(ValueError):auth.Receiver({},token_path=auth.ROOT/'dashboard/data/token.json')
        response=requests.get(self.receiver.url,headers={'Host':'evil.example'},timeout=3)
        self.assertEqual(response.status_code,404);self.assertFalse(self.path.exists())

    @patch.object(auth,'Client')
    @patch.object(auth,'_identity',side_effect=AdapterError('account_identity_mismatch'))
    def test_wrong_api_identity_consumes_without_saving(self,identity,client):
        response=self.post();self.thread.join(timeout=4)
        self.assertEqual(response.status_code,400);self.assertFalse(self.path.exists());self.assertTrue(self.receiver.done)
        self.assertNotIn('private-test-token',response.text);self.assertFalse(self.receiver.result['connected'])

    @patch.object(auth,'Client')
    @patch.object(auth,'_identity',return_value={'id':'123','username':'mustpickinfo'})
    def test_verified_single_use_import_is_private_and_redacted(self,identity,client):
        response=self.post();self.thread.join(timeout=4)
        self.assertEqual(response.status_code,200);self.assertTrue(self.path.exists())
        self.assertTrue(self.receiver.result['connected']);self.assertNotIn('access_token',self.receiver.result)
        self.assertNotIn('private-test-token',response.text);identity.assert_called_once()
        self.assertTrue(self.receiver.done);self.assertFalse(self.thread.is_alive())

    def test_expired_capability_rejected(self):
        self.receiver.deadline=time.monotonic()-1
        response=requests.get(self.receiver.url,timeout=3)
        self.assertEqual(response.status_code,410);self.assertFalse(self.path.exists())


class PrivateHandoffTests(unittest.TestCase):
    def test_identity_failure_consumes_handoff_without_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);source=home/'.barolab/secrets/threads-mustpickinfo-import.tmp'
            source.parent.mkdir(parents=True);source.write_text('private-test-token',encoding='utf-8')
            target=source.with_name('threads-mustpickinfo.json')
            with patch.object(auth.Path,'home',return_value=home),patch.object(auth,'TOKEN_PATH',target),patch.object(settings,'load',return_value=settings.defaults()),patch.object(auth,'Client'),patch.object(auth,'_identity',side_effect=AdapterError('account_identity_mismatch')):
                value=auth.import_private_token()
            self.assertFalse(source.exists());self.assertFalse(target.exists());self.assertFalse(value['connected'])
            self.assertNotIn('private-test-token',str(value))

    def test_success_preserves_disabled_state_and_deletes_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);source=home/'.barolab/secrets/threads-mustpickinfo-import.tmp'
            source.parent.mkdir(parents=True);source.write_text('private-test-token',encoding='utf-8')
            target=source.with_name('threads-mustpickinfo.json');config=settings.defaults()
            with patch.object(auth.Path,'home',return_value=home),patch.object(auth,'TOKEN_PATH',target),patch.object(settings,'load',return_value=config),patch.object(settings,'save') as save,patch.object(pipeline,'snapshot'),patch.object(auth,'Client'),patch.object(auth,'_identity',return_value={'id':'123','username':'mustpickinfo'}):
                value=auth.import_private_token()
            self.assertTrue(value['connected']);self.assertFalse(source.exists());self.assertTrue(target.exists())
            self.assertFalse(save.call_args.args[0]['enabled']);self.assertIsNone(save.call_args.args[0]['activatedAt'])
            self.assertNotIn('private-test-token',str(value))


if __name__=='__main__':unittest.main()


class PrivateStorageTests(unittest.TestCase):
    def test_acl_hardened_before_secret_and_each_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'token.json';observed=[]
            def protect(path):
                self.assertEqual(Path(path).read_bytes(),b'');observed.append(path)
            with patch.object(auth,'_harden_private_acl',side_effect=protect):
                auth.save_private_token('first',target);auth.save_private_token('second',target)
            self.assertEqual(len(observed),2);self.assertIn('second',target.read_text())
            self.assertEqual(list(target.parent.glob('*.tmp')),[])
    def test_acl_failure_preserves_old_secret_and_removes_empty_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'token.json';target.write_text('old')
            with patch.object(auth,'_harden_private_acl',side_effect=OSError('denied')):
                with self.assertRaises(OSError):auth.save_private_token('new',target)
            self.assertEqual(target.read_text(),'old');self.assertEqual(list(target.parent.glob('*.tmp')),[])
