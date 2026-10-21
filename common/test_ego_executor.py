import unittest
from unittest.mock import patch

from common.ego_executor import execute_staff_action


class EgoExecutorTests(unittest.TestCase):
    action = {'agent': 'patch', 'tool': 'read_agent_status', 'args': {}}

    def execute(self, action=None):
        return execute_staff_action(action or self.action, task_id='task-1', request_id='request-1')

    def test_exact_registered_action_and_receipt(self):
        with patch('server.agent_tools.execute_agent_tool', return_value={'ok': True, 'status': 'observed', 'data': {'count': 1}}) as tool:
            result = self.execute()
        tool.assert_called_once_with('patch', 'read_agent_status')
        self.assertEqual(result['data'], {'count': 1})
        receipt = result['executorReceipt']
        self.assertEqual((receipt['executor'], receipt['taskId'], receipt['requestId']), ('ego-lite', 'task-1', 'request-1'))
        self.assertTrue(receipt['completed'])

    def test_unknown_action_never_executes(self):
        with patch('server.agent_tools.execute_agent_tool') as tool:
            with self.assertRaises(ValueError):
                self.execute({'agent': 'patch', 'tool': 'shell', 'args': {}})
        tool.assert_not_called()

    def test_start_observed_before_call_and_terminal_after(self):
        events = []
        def tool(*args, **kwargs):
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['status'], 'running')
            self.assertIsNone(events[0]['finishedAt'])
            return {'ok': True, 'status': 'observed'}
        with patch('server.agent_tools.execute_agent_tool', side_effect=tool):
            execute_staff_action(self.action, task_id='task', request_id='request', observer=events.append)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1]['status'], 'observed')
        self.assertTrue(events[1]['completed'])

    def test_started_is_not_completed(self):
        with patch('server.agent_tools.execute_agent_tool', return_value={'ok': True, 'status': 'running', 'pid': 123}):
            result = self.execute()
        self.assertEqual(result['status'], 'running')
        self.assertFalse(result['executorReceipt']['completed'])
        self.assertIsNone(result['executorReceipt']['finishedAt'])
        self.assertTrue(result['executorReceipt']['returnedAt'])

    def test_error_is_not_success_and_no_raw_error(self):
        events = []
        with patch('server.agent_tools.execute_agent_tool', side_effect=RuntimeError('private details')):
            result = execute_staff_action(self.action, task_id='task', request_id='request', observer=events.append)
        self.assertFalse(result['ok'])
        self.assertEqual(result['executorReceipt']['status'], 'failed')
        self.assertNotIn('private details', str(result))
        self.assertEqual([event['status'] for event in events], ['running', 'failed'])

    def test_telemetry_failure_does_not_retry_or_replace_result(self):
        with patch('server.agent_tools.execute_agent_tool', return_value={'ok': True, 'status': 'observed'}) as tool:
            result = execute_staff_action(self.action, task_id='task', request_id='request',
                                          observer=lambda event: (_ for _ in ()).throw(OSError('private')))
        tool.assert_called_once()
        self.assertTrue(result['ok'])
        self.assertTrue(result['executorReceipt']['completed'])
