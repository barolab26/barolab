import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import host_failure


class HostFailureTests(unittest.TestCase):
    def test_only_private_reference_and_hash_persist_no_source_body_is_emitted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(host_failure,'ROOT',Path(tmp)), patch('common.crew_chat_bridge.emit_work_event') as emit:
            host_failure.report_host_failure(actor='kin-pipeline',task_key='private-task',state='submission_unknown',
                evidence_ref='/private/ledger.db',source_record={'body':'must not leak'},error_type='TimeoutError')
            kwargs=emit.call_args.kwargs
            self.assertEqual(kwargs['phase'],'failed')
            self.assertNotIn('private',kwargs['task_id'])
            self.assertNotIn('must not leak',str(kwargs))
            self.assertIn('no automatic resume',kwargs['output_kind'])
            files=list(Path(tmp).glob('*.json'));self.assertEqual(len(files),1)
            raw=files[0].read_bytes();receipt=json.loads(raw)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),kwargs['evidence_id'])
            self.assertNotIn('must not leak',raw.decode())
            self.assertFalse(receipt['automaticResumeAllowed'])

    def test_reporting_failure_never_propagates_into_channel(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(host_failure,'ROOT',Path(tmp)), patch('common.crew_chat_bridge.emit_work_event',side_effect=OSError):
            self.assertIsNone(host_failure.report_host_failure(actor='naver-pipeline',task_key='t',state='host_execution_failed',evidence_ref='ledger',source_record={'phase':'failed'}))
