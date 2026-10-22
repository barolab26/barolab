import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import ego_growth as ego
from common import content_maintenance as maintenance


class EgoGrowthTests(unittest.TestCase):
    def test_disabled_never_collects_or_publishes(self):
        with patch.object(maintenance, 'state', return_value={'policy': {'enabled': False}}), \
             patch('dashboard.runtime.worker.run_metrics') as collect, \
             patch.object(maintenance, 'run_once') as run:
            self.assertEqual(ego.growth_cycle()['status'], 'paused')
            collect.assert_not_called()
            run.assert_not_called()

    def test_restart_respects_persisted_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {'policy': {'enabled': True, 'cycleIntervalMinutes': 30},
                      'runtime': {'egoLastCycleAt': maintenance.stamp()}}
            with patch.object(maintenance, 'DATA', Path(folder)), \
                 patch.object(maintenance, 'state', return_value=config), \
                 patch.object(ego, 'EXEC_KILL_SWITCH', Path(folder) / 'disabled'), \
                 patch('dashboard.runtime.worker.run_metrics') as collect, \
                 patch.object(maintenance, 'run_once') as run:
                self.assertEqual(ego.growth_cycle()['status'], 'waiting')
                collect.assert_not_called()
                run.assert_not_called()

    def test_collect_then_maintenance_with_source_status(self):
        with tempfile.TemporaryDirectory() as folder:
            config = {'policy': {'enabled': True, 'cycleIntervalMinutes': 30}, 'runtime': {}}
            calls = []
            with patch.object(maintenance, 'DATA', Path(folder)), \
                 patch.object(maintenance, 'state', return_value=config), \
                 patch.object(maintenance, 'runtime'), \
                 patch.object(ego, 'EXEC_KILL_SWITCH', Path(folder) / 'disabled'), \
                 patch('dashboard.runtime.worker.run_metrics', side_effect=lambda *_: calls.append('collect')), \
                 patch.object(maintenance, 'run_once', side_effect=lambda: (
                     calls.append('maintain') or {'runtime': {'status': 'waiting'}})):
                result = ego.growth_cycle()
                self.assertEqual(calls, ['collect', 'maintain'])
                self.assertEqual(result['sourceStatus'], 'unknown')
                self.assertEqual(result['dailyTargetUsd'], 100)


if __name__ == '__main__':
    unittest.main()
