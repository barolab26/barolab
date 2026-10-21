"""Offline recovery contracts; no browser, generation, or publication calls."""
import copy
import hashlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from naver_blog_posting import pipeline_runner as r

class CompletedVisualRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)/'output'/'soultin'/'run';(self.folder/'images').mkdir(parents=True)
        self.plan={'filename':'scene.jpg','source':'generated','prompt':'actual prompt'}
        Image.new('RGB',(300,300),'green').save(self.folder/'images/scene.jpg')
        self.digest=r.sha(self.folder/'images/scene.jpg')
        self.row={'filename':'scene.jpg','status':'downloaded','submittedAt':'t','completedAt':'t2',
            'sha256':'a'*64,'promptSha256':hashlib.sha256(b'actual prompt').hexdigest()}
        self.fake=types.ModuleType('cf_posting.pipeline_runner');self.fake.flow_image_prompt=lambda p:p['prompt']
        self.patch=patch.dict('sys.modules',{'cf_posting.pipeline_runner':self.fake});self.patch.start();self.addCleanup(self.patch.stop)

    def test_completed_asset_and_explicit_postprocessing_hash(self):
        result=r.validate_completed_flow_assets(self.folder,[self.plan],[self.row],{'images/scene.jpg':self.digest})
        self.assertEqual(result['scene.jpg']['currentFileSha256'],self.digest)
        self.assertTrue(result['scene.jpg']['postprocessingChangedBytes'])

    def test_changed_missing_unsafe_unknown_or_prompt_mismatch_rejected(self):
        cases=[({'images/scene.jpg':'b'*64},self.plan,self.row),
            (None,{**self.plan,'filename':'../scene.jpg'},self.row),
            (None,{**self.plan,'filename':'missing.jpg'},self.row),
            (None,self.plan,{**self.row,'status':'unconfirmed'}),
            (None,{**self.plan,'prompt':'changed'},self.row)]
        for hashes,plan,row in cases:
            with self.subTest(plan=plan,row=row),self.assertRaises(RuntimeError):
                r.validate_completed_flow_assets(self.folder,[plan],[row],hashes)

    def test_saved_production_attempt_never_enters_preparation(self):
        (self.folder/'preparation-context.json').write_text(json.dumps({'publicationAttempt':True}),encoding='utf-8')
        with patch.object(r,'BASE_DIR',Path(self.tmp.name)),patch.object(r,'_prepare_content') as prepare:
            with self.assertRaises(RuntimeError):r.resume_completed_visual_assets('soultin',self.folder)
            prepare.assert_not_called()

    def test_evidence_tampering_fails_before_resume(self):
        (self.folder/'writer.json').write_text('original',encoding='utf-8')
        backup=self.folder/'backup';backup.mkdir();(backup/'writer.json').write_text('original',encoding='utf-8')
        stage=[{'agent':'keyword-selector'},{'agent':'researcher'},{'agent':'writer'}]
        handoff=types.SimpleNamespace(folder=self.folder,data={'stages':stage},check=lambda:stage)
        scope={'folder':str(self.folder.resolve()),'audit':{'acceptedStages':copy.deepcopy(stage),
            'backupDirectory':'backup','backupHashes':{'writer.json':r.sha(self.folder/'writer.json')}}}
        r.require_visual_acquisition_resume(handoff,scope)
        (self.folder/'writer.json').write_text('changed',encoding='utf-8')
        with self.assertRaises(RuntimeError):r.require_visual_acquisition_resume(handoff,scope)

if __name__=='__main__':unittest.main()
