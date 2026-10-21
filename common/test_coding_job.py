import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from common import coding_job as jobs


class CodingJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)/'source';self.root.mkdir()
        (self.root/'sample.py').write_text('def status(row):\n    return "ok" if row.get("exit_code",0)==0 else "failed"\n')
        (self.root/'test_sample.py').write_text('import unittest\nfrom sample import status\nclass TestStatus(unittest.TestCase):\n    def test_missing(self): self.assertEqual(status({}),"unknown")\n')
        self.candidate={'changes':[{'path':'sample.py','content':'def status(row):\n    if "exit_code" not in row: return "unknown"\n    return "ok" if row["exit_code"]==0 else "failed"\n'}]}
        self.out=patch.object(jobs,'JOB_ROOT',Path(self.temp.name)/'jobs');self.out.start()
        self.model=patch('common.llm_client.generate_json',return_value=self.candidate);self.model.start()
    def tearDown(self):
        self.model.stop();self.out.stop();self.temp.cleanup()
    def propose(self):
        return jobs.propose_coding_job(self.root,['sample.py'],['test_sample.py'],'Missing exit code is unknown')
    def test_proposal_never_edits_or_runs_and_reviewed_copy_is_verified(self):
        before=(self.root/'sample.py').read_bytes()
        with patch.object(jobs.subprocess,'run') as run:
            receipt=self.propose();run.assert_not_called()
        self.assertEqual((self.root/'sample.py').read_bytes(),before)
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'])
        self.assertEqual(result['status'],'isolated_verified')
        self.assertFalse(result['productionApplied'])
        self.assertEqual((self.root/'sample.py').read_bytes(),before)
    def test_changed_source_or_candidate_fails_before_execution(self):
        receipt=self.propose()
        (self.root/'sample.py').write_text('changed')
        with patch.object(jobs.subprocess,'run') as run:
            with self.assertRaises(ValueError): jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'])
            run.assert_not_called()
        with self.assertRaises(ValueError): jobs.validate_coding_job(receipt['jobDir'],'wrong-sha')
    def test_traversal_and_outside_job_are_rejected(self):
        with self.assertRaises(ValueError): jobs.propose_coding_job(self.root,['../sample.py'],['test_sample.py'],'fix')
        with self.assertRaises(ValueError): jobs.validate_coding_job(self.root,'sha')
    def test_model_cannot_change_tests_and_failed_tests_preserve_source(self):
        self.candidate['changes'][0]['path']='test_sample.py'
        with self.assertRaises(ValueError): self.propose()
        self.candidate['changes'][0]['path']='sample.py'
        self.candidate['changes'][0]['content']='def status(row): return "bad"\n'
        receipt=self.propose();before=(self.root/'sample.py').read_bytes()
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'])
        self.assertEqual(result['status'],'validation_failed')
        self.assertEqual((self.root/'sample.py').read_bytes(),before)
    def test_status_receipt_excludes_source_and_test_output(self):
        receipt=self.propose()
        public=jobs.read_coding_job_status(Path(receipt['jobDir']).name,receipt['candidateSha256'])
        self.assertEqual(public['status'],'proposed')
        self.assertNotIn('jobDir',public)
        self.assertNotIn('results',public)
        with self.assertRaises(ValueError): jobs.read_coding_job_status('../bad',receipt['candidateSha256'])
        with self.assertRaises(ValueError): jobs.read_coding_job_status(Path(receipt['jobDir']).name,'wrong')

    def test_host_node_test_runs_only_reviewed_isolated_source(self):
        if not jobs.shutil.which('node'): self.skipTest('Node unavailable')
        (self.root/'target.js').write_text('exports.exitCode = value => value == null ? 0 : value;')
        (self.root/'test_target.js').write_text("const {test}=require('node:test'); const assert=require('node:assert/strict'); const {exitCode}=require('./target'); test('unknown remains unknown',()=>{assert.equal(exitCode(null),'unknown'); assert.equal(exitCode(0),0); assert.equal(exitCode(1),1);});")
        self.candidate['changes']=[{'path':'target.js','content':"exports.exitCode = value => value == null ? 'unknown' : value;"}]
        receipt=jobs.propose_coding_job(self.root,['target.js'],['test_target.js'],'Missing exit code must be unknown')
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'])
        self.assertEqual(result['status'],'isolated_verified')
        self.assertIn('? 0 :',(self.root/'target.js').read_text())

    def test_proposal_uses_configured_patch_and_records_actual_route(self):
        def model(prompt, **kwargs):
            self.assertEqual(kwargs['agent_slot'], 'patch')
            self.assertNotIn('provider', kwargs)
            self.assertTrue(kwargs['memory_read_only'])
            self.assertTrue(kwargs['memory_session_id'].startswith('coding:'))
            self.assertTrue(kwargs['crew_task_id'].startswith('coding:'))
            self.assertNotIn('audit_directory', kwargs)
            kwargs['observer']('codex', 'configured-patch', 'calling')
            kwargs['observer']('codex', 'configured-patch', 'returned', actual_model='actual-patch')
            return self.candidate
        with patch('common.llm_client.generate_json', side_effect=model):
            receipt = self.propose()
        route = json.loads((Path(receipt['jobDir'])/'model-route.json').read_text())
        self.assertEqual(route['actualModel'], 'actual-patch')
        self.assertEqual(route['provider'], 'codex')
        self.assertEqual(route['phase'], 'returned')

    def test_symlink_input_is_rejected(self):
        linked=self.root/'linked.py'
        try: linked.symlink_to(self.root/'sample.py')
        except OSError: self.skipTest('Host cannot create symlinks')
        with self.assertRaises(ValueError): jobs.propose_coding_job(self.root,['linked.py'],['test_sample.py'],'fix')

    def review(self,receipt,validation_sha256=None):
        def model(prompt,**kwargs):
            self.assertEqual(kwargs['agent_slot'],'jarvis')
            self.assertIn('actualValidation',prompt)
            kwargs['observer']('codex','configured-jarvis','returned',actual_model='actual-jarvis')
            return {**{key:True for key in kwargs['response_schema']['required'] if key!='reason'},'reason':'Controlled test verdict; actual source and frozen tests examined.'}
        with patch('common.llm_client.generate_json',side_effect=model):
            return jobs.review_coding_job(receipt['jobDir'],receipt['candidateSha256'],{'fixture':True},validation_sha256=validation_sha256)

    def test_large_policy_file_uses_unique_bounded_edit_and_preserves_other_bytes(self):
        text='# policy\n'+'stable\n'*15000+'old requirement\n'
        (self.root/'policy.md').write_bytes(text.encode('utf-8'))
        self.candidate['changes']=[{'path':'policy.md','content':'correct requirement\n'}]
        receipt=jobs.propose_coding_job(self.root,['policy.md'],['test_sample.py'],'Fix wording',edit_regions={'policy.md':'old requirement\n'})
        candidate=json.loads((Path(receipt['jobDir'])/'candidate.json').read_text(encoding='utf-8'))
        self.assertEqual(candidate['changes'][0]['content'],text.replace('old requirement','correct requirement'))
        self.assertEqual((self.root/'policy.md').read_text(encoding='utf-8'),text)

    def test_traceback_scope_excludes_secrets_outside_and_approval_infrastructure(self):
        (self.root/'secret.py').write_text('secret')
        found=jobs.derive_coding_scope(self.root,f'File "{self.root / "sample.py"}"\nFile "{self.root / "secret.py"}"\nFile "/outside.py"')
        self.assertEqual(found,['sample.py'])
        with self.assertRaises(ValueError):jobs.propose_coding_job(self.root,['secret.py'],['test_sample.py'],'fix')

    def test_readonly_registry_is_hash_bound_in_both_model_inputs_and_not_editable(self):
        (self.root/'registry.py').write_text('REGISTERED = {"first": ["a", "b"], "second": ["c", "d"]}\n',encoding='utf-8')
        def model(prompt,**kwargs):
            self.assertIn('readOnlyContext',prompt)
            self.assertIn('REGISTERED',prompt)
            self.assertIn('second',prompt)
            if kwargs['agent_slot']=='patch':return self.candidate
            kwargs['observer']('codex','configured-jarvis','returned',actual_model='actual-jarvis')
            return {**{k:True for k in kwargs['response_schema']['required'] if k!='reason'},'reason':'Controlled fixture review'}
        with patch('common.llm_client.generate_json',side_effect=model):
            receipt=jobs.propose_coding_job(self.root,['sample.py'],['test_sample.py'],'Fix general behavior',context_files=['registry.py'])
            jobs.review_coding_job(receipt['jobDir'],receipt['candidateSha256'],{'fixture':True})
        manifest=json.loads((Path(receipt['jobDir'])/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['sourceHashes']['registry.py'],jobs.digest((self.root/'registry.py').read_bytes()))
        with self.assertRaises(ValueError):jobs._validate_candidate({'changes':[{'path':'registry.py','content':'changed'}]},manifest)

    def test_review_rejects_false_and_cannot_be_repeated(self):
        receipt=self.propose()
        with self.assertRaises(ValueError):jobs.review_coding_job(receipt['jobDir'],receipt['candidateSha256'],{})
        with self.assertRaises(ValueError):self.review(receipt)

    @unittest.skipUnless(sys.platform=='linux' and jobs.shutil.which('bwrap'),'Real Linux sandbox required')
    def test_real_sandbox_denies_host_files_credentials_network_and_test_mutation(self):
        secret=Path(self.temp.name)/'host-private.json';secret.write_text('private')
        code=f'''import os,socket,unittest
from pathlib import Path
class Isolation(unittest.TestCase):
 def test_boundary(self):
  self.assertFalse(Path({str(secret)!r}).exists())
  self.assertFalse(Path('/home/baro7/.barolab').exists())
  self.assertFalse(Path('/mnt/c/10_Project/BaroLab/server/data').exists())
  self.assertIsNone(os.environ.get('OPENAI_API_KEY'))
  with self.assertRaises(OSError):Path(__file__).write_text('changed')
  with self.assertRaises(OSError):socket.create_connection(('1.1.1.1',443),timeout=0.2)
'''
        (self.root/'test_boundary.py').write_text(code,encoding='utf-8')
        receipt=jobs.propose_coding_job(self.root,['sample.py'],['test_boundary.py'],'Bounded fixture')
        review=self.review(receipt)
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'],sandbox=True,review_sha256=review['reviewSha256'])
        self.assertEqual(result['status'],'isolated_verified',result['results'])
        self.assertTrue(result['sandbox']['enforced'])
        self.assertEqual(secret.read_text(),'private')

    @unittest.skipUnless(sys.platform=='linux' and jobs.shutil.which('bwrap'),'Real Linux sandbox required')
    def test_review_sandbox_final_review_cas_apply_and_guarded_rollback(self):
        (self.root/'sample.py').chmod(0o755)
        receipt=self.propose();original=(self.root/'sample.py').read_bytes();review=self.review(receipt)
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'],sandbox=True,review_sha256=review['reviewSha256'])
        self.assertEqual(result['status'],'isolated_verified',result['results'])
        final=self.review(receipt,result['validationSha256'])
        applied=jobs.apply_coding_job(receipt['jobDir'],receipt['candidateSha256'],review['reviewSha256'],result['validationSha256'],final['reviewSha256'])
        self.assertTrue(applied['productionApplied'])
        self.assertNotEqual((self.root/'sample.py').read_bytes(),original)
        self.assertEqual(jobs.stat.S_IMODE((self.root/'sample.py').stat().st_mode),0o755)
        jobs.rollback_coding_job(receipt['jobDir'],applied['evidenceSha256'])
        self.assertEqual((self.root/'sample.py').read_bytes(),original)
        self.assertEqual(jobs.stat.S_IMODE((self.root/'sample.py').stat().st_mode),0o755)
        with self.assertRaises(ValueError):jobs.rollback_coding_job(receipt['jobDir'],applied['evidenceSha256'])

    @unittest.skipUnless(sys.platform=='linux' and jobs.shutil.which('bwrap'),'Real Linux sandbox required')
    def test_cas_refuses_newer_source_without_overwriting(self):
        receipt=self.propose();review=self.review(receipt)
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'],sandbox=True,review_sha256=review['reviewSha256'])
        final=self.review(receipt,result['validationSha256'])
        (self.root/'sample.py').write_text('newer edit',encoding='utf-8')
        with self.assertRaises(ValueError):jobs.apply_coding_job(receipt['jobDir'],receipt['candidateSha256'],review['reviewSha256'],result['validationSha256'],final['reviewSha256'])
        self.assertEqual((self.root/'sample.py').read_text(encoding='utf-8'),'newer edit')

    def test_sandbox_unavailable_fails_closed_without_legacy_execution(self):
        with patch.object(jobs.sys,'platform','win32'),patch.object(jobs.subprocess,'run') as run:
            with self.assertRaises(RuntimeError):jobs._sandbox_run(self.root,'test_sample.py')
            run.assert_not_called()

    def test_all_skipped_or_unknown_summaries_fail_closed(self):
        (self.root/'test_sample.py').write_text('import unittest\n@unittest.skip("fixture")\nclass T(unittest.TestCase):\n def test_nothing(self): pass\n',encoding='utf-8')
        receipt=self.propose()
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'])
        self.assertEqual(result['status'],'validation_failed')
        self.assertEqual(result['results'][0]['summary']['executed'],0)
        self.assertIsNone(jobs._test_summary('Ran 1 test in 0s\nnot a summary','.py'))
        self.assertIsNone(jobs._test_summary('Ran 1 test in 0s\nFAILED (errors=1)','.py'))
        tap='\n'.join(['# tests 1','# pass 0','# fail 0','# cancelled 0','# skipped 1','# todo 0','# duration_ms 2'])
        self.assertEqual(jobs._test_summary(tap,'.js')['executed'],0)
        self.assertIsNone(jobs._test_summary('# tests 1','.js'))

    def test_frozen_test_change_blocks_validation(self):
        receipt=self.propose();review=self.review(receipt)
        (self.root/'test_sample.py').write_text('import unittest',encoding='utf-8')
        with patch.object(jobs,'_sandbox_run') as run:
            with self.assertRaises(ValueError):jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'],sandbox=True,review_sha256=review['reviewSha256'])
            run.assert_not_called()

    @unittest.skipUnless(sys.platform=='linux' and jobs.shutil.which('bwrap'),'Real Linux sandbox required')
    def test_pipeline_can_import_frozen_protected_source_dependency_without_edit_permission(self):
        (self.root/'common').mkdir();(self.root/'cf_posting').mkdir()
        (self.root/'common/codex_cli.py').write_text('def available(): return True\n',encoding='utf-8')
        (self.root/'cf_posting/pipeline_runner.py').write_text('from common.codex_cli import available\ndef ready(): return False\n',encoding='utf-8')
        (self.root/'test_pipeline.py').write_text('import unittest\nfrom cf_posting.pipeline_runner import ready\nclass T(unittest.TestCase):\n def test_ready(self): self.assertTrue(ready())\n',encoding='utf-8')
        self.candidate['changes']=[{'path':'cf_posting/pipeline_runner.py','content':'from common.codex_cli import available\ndef ready(): return available()\n'}]
        receipt=jobs.propose_coding_job(self.root,['cf_posting/pipeline_runner.py'],['test_pipeline.py'],'Controlled pipeline dependency fixture',context_files=['common/codex_cli.py'])
        review=self.review(receipt)
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'],sandbox=True,review_sha256=review['reviewSha256'])
        self.assertEqual(result['status'],'isolated_verified',result['results'])
        with self.assertRaises(ValueError):jobs.propose_coding_job(self.root,['common/codex_cli.py'],['test_pipeline.py'],'Disallowed edit')

    @unittest.skipUnless(sys.platform=='linux' and jobs.shutil.which('bwrap'),'Real Linux sandbox required')
    def test_rollback_rejects_newer_edit(self):
        receipt=self.propose();review=self.review(receipt)
        result=jobs.validate_coding_job(receipt['jobDir'],receipt['candidateSha256'],sandbox=True,review_sha256=review['reviewSha256'])
        final=self.review(receipt,result['validationSha256'])
        applied=jobs.apply_coding_job(receipt['jobDir'],receipt['candidateSha256'],review['reviewSha256'],result['validationSha256'],final['reviewSha256'])
        (self.root/'sample.py').write_text('another editor',encoding='utf-8')
        with self.assertRaises(ValueError):jobs.rollback_coding_job(receipt['jobDir'],applied['evidenceSha256'])
        self.assertEqual((self.root/'sample.py').read_text(encoding='utf-8'),'another editor')


class TracebackRegionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def source(self,body):
        path=self.root/'target.py'
        path.write_bytes((body+'# padding '+('x'*100001)+'\r\n').encode('utf-8'))
        return path
    def test_last_frame_smallest_function_decorators_utf8_exact(self):
        body='def outer():\r\n    @decorate("한글")\r\n    async def inner():\r\n        return "값"\r\n    return inner\r\n'
        path=self.source(body);before=path.read_bytes()
        trace=f'File "{path}", line 5\nFile "{path}", line 4'
        result=jobs.derive_edit_regions(self.root,['target.py'],trace)
        self.assertEqual(result['target.py'],''.join(body.splitlines(keepends=True)[1:4]))
        self.assertEqual(path.read_bytes(),before)
    def test_small_file_whole_mode_and_mixed_scope(self):
        (self.root/'small.py').write_bytes(b'x=1\n')
        self.assertIsNone(jobs.derive_edit_regions(self.root,['small.py'],''))
        path=self.source('def f():\n    return 1\n')
        result=jobs.derive_edit_regions(self.root,['small.py','target.py'],f'File "{path}", line 2')
        self.assertEqual(result['small.py'],'x=1\n')
    def test_missing_outside_and_nonfunction_frames_hold(self):
        path=self.source('x=1\n')
        for trace in ('', 'File "/outside/target.py", line 1',f'File "{path}", line 1'):
            with self.assertRaises(ValueError):jobs.derive_edit_regions(self.root,['target.py'],trace)
    def test_duplicate_and_oversize_functions_hold(self):
        body='def f():\n    return 1\n'
        path=self.source(body+body)
        with self.assertRaises(ValueError):jobs.derive_edit_regions(self.root,['target.py'],f'File "{path}", line 2')
        path=self.source('def f():\n    return "'+('x'*20001)+'"\n')
        with self.assertRaises(ValueError):jobs.derive_edit_regions(self.root,['target.py'],f'File "{path}", line 2')

if __name__=='__main__': unittest.main()
