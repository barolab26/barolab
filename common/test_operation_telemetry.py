"""Offline operation-boundary observations: no collection or maintenance writes."""
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dashboard'))
from common import ego_telemetry as telemetry
from common import content_maintenance as maintenance
from dashboard import revenue, traffic
from server import windows_worker

@contextmanager
def busy(*args, **kwargs):
    yield False

class OperationTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.patch = patch.object(telemetry, 'DIRECTORY', self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def records(self):
        return [json.loads(p.read_text(encoding='utf-8')) for p in self.directory.glob('*.json')]

    def test_direct_collectors_keep_busy_and_unique_identity(self):
        for module in (revenue, traffic):
            with patch.object(module, 'collector_lock', busy):
                self.assertEqual(module.collect(), {'status':'busy'})
        records = self.records()
        self.assertEqual(len(records), 2)
        for row in records:
            self.assertEqual(row['context']['requester'], 'unknown')
            self.assertEqual(row['context']['actor'], 'unknown')
            self.assertEqual(row['context']['project'], 'metrics')
            self.assertEqual([e['phase'] for e in row['recent']], ['before','after'])

    def test_maintenance_failure_keeps_parent_and_private_error_out(self):
        failure = RuntimeError('private-key-and-body')
        with telemetry.execution_context(task_id='staff:original',request_id='request:original',requester='jarvis',actor='patch',project='content_maintenance'):
            with patch.object(maintenance, 'state', side_effect=failure):
                with self.assertRaises(RuntimeError) as caught:
                    maintenance.audit_batch()
            self.assertIs(caught.exception, failure)
        row = self.records()[0]
        self.assertEqual(row['context']['taskId'], 'staff:original')
        self.assertEqual(row['context']['requester'], 'jarvis')
        self.assertEqual(row['latest']['phase'], 'failed')
        self.assertNotIn('private-key', json.dumps(row))

    def test_auth_boundary_has_no_secret_or_character_count(self):
        page = MagicMock()
        page.url = 'https://nid.naver.com/nidlogin.login'
        page.locator.return_value.count.return_value = 1
        page.get_by_role.return_value.count.return_value = 1
        with telemetry.execution_context(task_id='metrics:test-auth', project='metrics'):
            self.assertTrue(revenue._adpost_login(page, {'NAVER_demo_ID':'private-user', 'NAVER_demo_PW':'private-password'}, 'demo'))
        row = self.records()[0]
        self.assertEqual([e['action'] for e in row['recent'] if e['phase']=='after'], ['type','type','click'])
        self.assertTrue(all('count' not in e for e in row['recent']))
        raw = json.dumps(row)
        for secret in ('private-user','private-password','nid.naver.com','#pw'):
            self.assertNotIn(secret, raw)
        page.get_by_role.return_value.click.assert_called_once_with()

    def test_windows_metrics_busy_never_launches_child(self):
        with patch('dashboard.metrics.collector_lock', busy), patch.object(windows_worker.subprocess,'Popen') as launch:
            self.assertEqual(windows_worker.run_metrics('python', []), 0)
        launch.assert_not_called()
        self.assertEqual(self.records()[0]['latest']['target'], 'metrics-collection')

if __name__ == '__main__':
    unittest.main()
