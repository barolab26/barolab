import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import project_autonomy as a
from server import agent_tools as tools


class ProjectAutonomyTests(unittest.TestCase):
    def test_owner_and_arguments_are_host_registered(self):
        for project in a.COMMANDS:
            owner = 'doctor' if project == 'legacy_remodel' else 'publi'
            action = {'agent': owner, 'tool': 'run_project_cycle', 'args': {'project': project}}
            self.assertEqual(tools.validate_staff_actions([action]), [action])
            tools.staff_instruction(action)
            with self.assertRaises(ValueError):
                tools.validate_staff_actions([{**action, 'agent': 'radar'}])
        with self.assertRaises(ValueError):
            tools.validate_staff_actions([{'agent': 'publi', 'tool': 'run_project_cycle',
                                          'args': {'project': 'cf_blog', 'force': True}}])

    def test_child_identity_and_exit_do_not_prove_publication(self):
        with tempfile.TemporaryDirectory() as td, patch.object(tools, 'EGO_PROCESS_DIR', Path(td)):
            path = Path(td) / 'child' / 'receipt.json'
            path.parent.mkdir()
            result = {'receiptPath': str(path), 'pid': 123, 'project': 'threads'}
            receipt = {'pid': 123, 'status': 'running', 'action': {'tool': 'run_project_cycle',
                       'argumentsComplete': True, 'args': {'project': 'threads'}}}
            path.write_text(json.dumps(receipt))
            self.assertIsNone(a.terminal_result(result))
            receipt.update(status='exited', exitCode=0)
            path.write_text(json.dumps(receipt))
            terminal, _ = a.terminal_result(result)
            self.assertTrue(terminal['ok'])
            self.assertFalse(terminal['publicationVerified'])
            receipt.update(status='unknown', exitCode=None)
            path.write_text(json.dumps(receipt))
            terminal, _ = a.terminal_result(result)
            self.assertEqual(terminal['status'], 'unknown')
            self.assertFalse(terminal['ok'])
            with self.assertRaises(ValueError):
                a.terminal_result({**result, 'project': 'naver_blog'})

    def test_queued_execution_rechecks_disable_switch(self):
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / 'config.json'
            config.write_text('{"enabled": false}')
            with patch.object(a, 'CONFIG', config), patch.object(tools, '_ego_popen') as launch:
                self.assertEqual(a.run_project_cycle('cf_blog')['status'], 'held')
                launch.assert_not_called()

    def test_executable_failure_keeps_exact_traceback_receipt(self):
        from common import repair_workflow as repair
        with tempfile.TemporaryDirectory() as td, patch.object(tools, 'EGO_PROCESS_DIR', Path(td)):
            folder = Path(td) / 'child'; folder.mkdir()
            action = {'agent': 'publi', 'tool': 'run_project_cycle', 'args': {'project': 'threads'}}
            original = {'taskId': 'task', 'requestId': 'request', 'actions': [action]}
            raw = json.dumps(original).encode(); (folder / 'request.json').write_bytes(raw)
            receipt = folder / 'receipt.json'
            receipt.write_text(json.dumps({'status': 'failed', 'action': {**action, 'argumentsComplete': True},
                'originalTaskRef': {'taskId': 'task', 'requestId': 'request',
                                    'requestSha256': hashlib.sha256(raw).hexdigest()}}))
            request = Path(td) / 'terminal.json'
            request.write_text(json.dumps({**original, 'status': 'failed',
                'results': [{'result': {'receiptPath': str(receipt)}}]}))
            path, evidence = repair._original_recovery_request({}, request)
            self.assertEqual(path, request)
            self.assertEqual(evidence['path'], str(receipt))
            self.assertEqual(evidence['sha256'], hashlib.sha256(receipt.read_bytes()).hexdigest())

    def test_fairness_pending_guard_and_failed_cycle_recovery_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); config = root / 'config.json'; state = root / 'state.json'
            queue = root / 'queue'; queue.mkdir()
            config.write_text(json.dumps({'enabled': True, 'projects': ['cf_blog', 'threads']}))
            projects = [{'id': key, 'status': 'attention', 'counts': {'failed': 1}}
                        for key in ('cf_blog', 'threads')]
            def enqueue(request_id, actions):
                path = queue / (hashlib.sha256(request_id.encode()).hexdigest() + '.json')
                if not path.exists():
                    path.write_text(json.dumps({'taskId': request_id, 'requestId': request_id,
                                               'actions': actions, 'status': 'queued'}))
                return {'taskId': request_id, 'requestId': request_id}
            with patch.object(a, 'CONFIG', config), patch.object(a, 'STATE', state), \
                    patch.object(tools, 'STAFF_REQUEST_DIR', queue), \
                    patch.object(tools, 'enqueue_staff_request', side_effect=enqueue), \
                    patch('server.project_health.observed_projects', return_value=projects), \
                    patch('common.recovery_evidence.failure_targets', return_value=[]), \
                    patch('server.project_monitor.INCIDENTS', root / 'incidents'), \
                    patch.object(a.time, 'time', return_value=1000), \
                    patch.object(Path, 'home', return_value=root):
                self.assertTrue(a.process_project_autonomy_once())
                self.assertFalse(a.process_project_autonomy_once())
                first = next(queue.glob('*.json')); request = json.loads(first.read_bytes())
                request['status'] = 'failed'; first.write_text(json.dumps(request))
                self.assertTrue(a.process_project_autonomy_once())
                saved = json.loads(state.read_bytes())['projects']
                self.assertIn('threads', saved)
                incident = json.loads(next((root / 'incidents').glob('*.json')).read_bytes())
                self.assertEqual(incident['dispatch']['requestId'], request['requestId'])
                self.assertEqual(incident['taskId'], request['taskId'])
                self.assertGreater(saved['cf_blog']['nextRunAt'], 1000)


if __name__ == '__main__':
    unittest.main()
