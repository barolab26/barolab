import json
import tempfile
import unittest
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

    def test_symlink_input_is_rejected(self):
        linked=self.root/'linked.py'
        try: linked.symlink_to(self.root/'sample.py')
        except OSError: self.skipTest('Host cannot create symlinks')
        with self.assertRaises(ValueError): jobs.propose_coding_job(self.root,['linked.py'],['test_sample.py'],'fix')

if __name__=='__main__': unittest.main()
