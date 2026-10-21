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

    def test_started_is_not_completed(self):
        with patch('server.agent_tools.execute_agent_tool', return_value={'ok': True, 'status': 'running', 'pid': 123}):
            result = self.execute()
        self.assertEqual(result['status'], 'running')
        self.assertFalse(result['executorReceipt']['completed'])

    def test_error_is_not_success_and_no_raw_error(self):
        with patch('server.agent_tools.execute_agent_tool', side_effect=RuntimeError('private details')):
            result = self.execute()
        self.assertFalse(result['ok'])
        self.assertEqual(result['executorReceipt']['status'], 'failed')
        self.assertNotIn('private details', str(result))
