import sqlite3
import unittest
from unittest.mock import Mock,patch
from dashboard.server import memory_worker

class MemoryWorkerResilienceTests(unittest.TestCase):
    def test_busy_learning_database_does_not_terminate_publication_supervisor(self):
        stopped=Mock();stopped.is_set.side_effect=[False,True]
        with patch.object(memory_worker.threading,'Event',return_value=stopped),patch.object(memory_worker.threading,'Thread'),patch.object(memory_worker.signal,'signal'),patch('common.hermes_memory._store') as store,patch('common.llm_client.process_verified_work_once',side_effect=sqlite3.OperationalError('database is locked')),patch('server.project_monitor.sample_project_health_once'),patch('server.agent_tools.process_staff_request_once'),patch('common.project_autonomy.process_project_autonomy_once'),patch('dashboard.agents.synapse.refresh_once'),patch('dashboard.agents.style_strategy.review_once'),patch('common.conference_dispatch.process_once') as conferences,patch.object(memory_worker.logging,'exception'):
            memory_worker.main()
            created = memory_worker.threading.Thread.call_args_list
        conferences.assert_called_once()
        stopped.wait.assert_called_once_with(30)
        store.close.assert_called_once()
        loops = {call.kwargs['name']: call.kwargs.get('args', ([],))[0] for call in created}
        self.assertEqual(len(loops['project-observer']), 1)
        self.assertEqual([action.__name__ for action in loops['project-supervisor']],
                         ['process_project_monitor_once', 'process_project_feedback_once'])
