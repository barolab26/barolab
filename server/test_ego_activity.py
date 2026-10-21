import json
import tempfile
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from server import ego_activity as a


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.now = 2000000000

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')

    def naver(self, at=None, folder=None):
        base = self.root/'naver_blog_posting'
        folder = folder or base/'output/test/run'
        iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
        self.write(base/'data/automation-journal.json', {'attempts':[{'phase':'started', 'account':'test', 'startedAt':iso(self.now-30), 'artifactFolder':str(folder)}]})
        self.write(folder/'visible-editor-progress.json', {'events':[{'stage':'block','at':iso(at or self.now-2)}]})

    def test_idle_never_reads_old_typing(self):
        self.naver()
        with patch.object(a, 'lock_busy', return_value=False):
            row = a.read_activity(self.root,self.now)['naver']
            self.assertEqual(row['state'],'registered_idle'); self.assertIsNone(row['stage'])

    def test_live_lock_matching_fresh_job_only(self):
        self.naver()
        with patch.object(a, 'lock_busy', return_value=True):
            row=a.read_activity(self.root,self.now)['naver']
            self.assertEqual(row['state'],'active');self.assertEqual(row['stage'],'block')

    def test_old_or_before_current_attempt_actions_not_live(self):
        for at in (self.now-300,self.now-31,self.now+1):
            self.naver(at)
            with patch.object(a,'lock_busy',return_value=True):
                row=a.read_activity(self.root,self.now)['naver'];self.assertEqual(row['state'],'active_unobserved');self.assertIsNone(row['stage'])

    def test_outside_account_folder_rejected(self):
        self.naver(folder=self.root/'outside')
        with patch.object(a,'lock_busy',return_value=True):
            self.assertEqual(a.read_activity(self.root,self.now)['naver']['errorType'],'ValueError')

    def test_cf_stage_needs_processing_domain_and_fresh_timestamp(self):
        base=self.root/'cf_posting/data'
        self.write(base/'pipeline_state.json',{'activeDomain':'a','timestamp':self.now-2,'stageName':'research'})
        with patch.object(a,'lock_busy',return_value=True):
            for status,expected in [('failed','active_unobserved'),('processing','active')]:
                self.write(base/'daily_schedule.json',{'date':datetime.fromtimestamp(self.now,timezone(timedelta(hours=9))).date().isoformat(),'items':[{'domain':'a','status':status}]})
                self.assertEqual(a.read_activity(self.root,self.now)['cf']['state'],expected)

    def test_input_projection_rejects_wrong_identity_and_private_fields(self):
        import hashlib
        context={'taskId':'actual-task','requestId':'request','requester':'user','actor':'codex','project':'naver_search','source':'direct'}
        event={'actionId':'a'*32,'action':'type','target':'naver-search-query','phase':'after','at':datetime.fromtimestamp(self.now-1,timezone.utc).isoformat(),'count':7,'typedText':'PRIVATE'}
        payload={'context':context,'processId':12345,'latest':event,'recent':[event]}
        folder=self.root/'telemetry';key=hashlib.sha256(b'actual-task:12345').hexdigest()
        self.write(folder/(key+'.json'),payload)
        rows=a.read_input_activity(folder,self.now)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['latest']['count'],7)
        self.assertNotIn('PRIVATE',json.dumps(rows))
        (folder/(key+'.json')).rename(folder/('b'*64+'.json'))
        self.assertEqual(a.read_input_activity(folder,self.now),[])

    def test_unknown_input_target_and_old_input_not_live(self):
        import hashlib
        folder=self.root/'telemetry';key=hashlib.sha256(b'task:123').hexdigest()
        event={'actionId':'a'*32,'action':'click','target':'naver-search','phase':'before','at':datetime.fromtimestamp(self.now-300,timezone.utc).isoformat()}
        payload={'context':{'taskId':'task','source':'direct'},'processId':123,'recent':[event]}
        self.write(folder/(key+'.json'),payload)
        self.assertFalse(a.read_input_activity(folder,self.now)[0]['fresh'])
        event['target']='secret-url'
        self.write(folder/(key+'.json'),payload)
        self.assertEqual(a.read_input_activity(folder,self.now),[])

    @unittest.skipUnless(os.name=='posix','Linux passive lock registry')
    def test_passive_lock_registry_detects_child_without_claim(self):
        path=self.root/'lock';path.write_bytes(b'0')
        child=subprocess.Popen([sys.executable,'-c','import fcntl,sys; f=open(sys.argv[1],"r+b"); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.readline()',str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            self.assertTrue(a.lock_busy(path))
        finally:
            child.communicate('\n',timeout=5)
        self.assertFalse(a.lock_busy(path))

    @unittest.skipUnless(os.name=='posix','WSL canonical Windows path mapping')
    def test_windows_canonical_run_maps_with_account_confinement(self):
        base=self.root/'naver_blog_posting'
        path=a.active_folder(r'C:\10_Project\BaroLab\naver_blog_posting\output\soultin\run','soultin',base)
        self.assertEqual(path,base/'output/soultin/run')
        with self.assertRaises(ValueError):
            a.active_folder(r'C:\10_Project\BaroLab\naver_blog_posting\output\other\run','soultin',base)


if __name__=='__main__': unittest.main()
