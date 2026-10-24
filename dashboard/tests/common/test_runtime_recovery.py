import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import runtime_recovery as recovery
from dashboard.server import memory_worker


class RuntimeRecoveryTests(unittest.TestCase):
    def test_active_jobs_disabled_timers_and_unknown_units_are_preserved(self):
        rows = [
            {'unit': 'barolab-metrics.timer', 'LoadState': 'loaded', 'ActiveState': 'active'},
            {'unit': 'barolab-metrics.service', 'LoadState': 'loaded', 'ActiveState': 'activating'},
            {'unit': 'barolab-revenue-refresh.timer', 'LoadState': 'loaded', 'ActiveState': 'inactive', 'UnitFileState': 'disabled'},
            {'unit': 'barolab-indexing.timer', 'LoadState': 'not-found', 'ActiveState': 'inactive'}]
        with tempfile.TemporaryDirectory() as root, patch.object(recovery.Path, 'home', return_value=Path(root)), \
                patch.object(recovery, 'runtime_state', return_value=rows), patch.object(recovery.subprocess, 'run') as run:
            self.assertEqual(recovery.recover_project_runtime('collections')['startRequested'], [])
            run.assert_not_called()
            with self.assertRaises(ValueError):
                recovery.recover_project_runtime('arbitrary-command')

    def test_idle_collector_is_started_once_without_restart_or_success_inference(self):
        rows = [{'unit': 'barolab-metrics.timer', 'LoadState': 'loaded', 'ActiveState': 'active'},
                {'unit': 'barolab-metrics.service', 'LoadState': 'loaded', 'ActiveState': 'inactive'}]
        with tempfile.TemporaryDirectory() as root, patch.object(recovery.Path, 'home', return_value=Path(root)), \
                patch.object(recovery, 'runtime_state', return_value=rows), patch.object(recovery.subprocess, 'run') as run:
            result = recovery.recover_project_runtime('collections')
        self.assertEqual(run.call_args.args[0], ['systemctl', '--user', 'start', '--no-block', 'barolab-metrics.service'])
        self.assertFalse(result['recoveryVerified'])

    def test_worker_stall_guard_preserves_nested_publication_children_and_browsers(self):
        with tempfile.TemporaryDirectory() as root:
            proc = Path(root)
            for pid, ppid, command in [(10, 1, 'python3'), (11, 10, '/opt/google/chrome/chrome'),
                                       (12, 11, '/opt/google/chrome/chrome_crashpad_handler')]:
                entry = proc / str(pid); entry.mkdir()
                (entry / 'stat').write_text(f'{pid} (test) S {ppid} 0 0')
                (entry / 'cmdline').write_bytes(command.encode() + b'\0')
            self.assertFalse(memory_worker.has_active_jobs(proc, 10))
            entry = proc / '13'; entry.mkdir()
            (entry / 'stat').write_text('13 (publisher) S 11 0 0')
            (entry / 'cmdline').write_bytes(b'python3\0posting.py\0')
            self.assertTrue(memory_worker.has_active_jobs(proc, 10))
        self.assertEqual(memory_worker.stalled_actions({'staff-executor': {'at': 0},
                         'memory-refresh': {'at': 0}, 'project-observer': {'at': 990}}, 1000), ['staff-executor'])
