"""Offline worker singleton checks for Linux and Windows; no jobs are launched."""
from pathlib import Path
import os
import subprocess
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from dashboard import metrics
from server import windows_worker as worker


class StopWorker(BaseException):
    pass


class WorkerLockTests(unittest.TestCase):
    def test_linux_tasks_reuse_running_python(self):
        with patch.object(worker, 'os', SimpleNamespace(name='posix', environ=os.environ)), \
                patch.object(worker.sys, 'executable', '/existing/venv/bin/python3'), \
                patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run, \
                patch.object(worker, 'run_metrics', return_value=0) as metrics_run:
            for task in ('maintenance', 'naver-monitor', 'naver-daily'):
                with self.subTest(task=task):
                    self.assertEqual(worker.run_task(task), 0)
                    self.assertEqual(run.call_args.args[0][0], '/existing/venv/bin/python3')
            self.assertEqual(worker.run_task('metrics'), 0)
            self.assertEqual(metrics_run.call_args.args[0], '/existing/venv/bin/python3')

    @unittest.skipUnless(os.name == 'nt', 'Windows pythonw path semantics')
    def test_windows_tasks_use_console_python_sibling(self):
        with patch.object(worker.sys, 'executable', r'C:\existing\pythonw.exe'), \
                patch.object(worker.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            worker.run_task('naver-monitor')
            self.assertEqual(run.call_args.args[0][0], r'C:\existing\python.exe')

    def check_worker(self, platform, busy):
        locking = Mock(side_effect=OSError('busy') if busy else None)
        module = (SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
                  if platform == 'nt' else
                  SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=locking))
        module_name = 'msvcrt' if platform == 'nt' else 'fcntl'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(Path, 'home', return_value=root), \
                    patch.object(metrics, 'DATA', root / 'data'), \
                    patch.object(metrics, 'os', SimpleNamespace(name=platform)), \
                    patch.dict('sys.modules', {module_name: module}), \
                    patch.object(worker.threading, 'Thread') as thread, \
                    patch.object(worker.codex_cli, 'refresh_runtime', side_effect=StopWorker) as refresh, \
                    patch.object(worker.time, 'monotonic', return_value=100):
                if busy:
                    worker.serve()
                    thread.assert_not_called()
                    refresh.assert_not_called()
                else:
                    with self.assertRaises(StopWorker):
                        worker.serve()
                    self.assertEqual(thread.call_count, 5)
                    refresh.assert_called_once()
            self.assertTrue((root / '.barolab/dashboard-worker.lock').is_file())
        self.assertEqual(locking.call_count, 1 if busy else 2)
        calls = locking.call_args_list
        self.assertEqual(calls[0].args[1], 1 if platform == 'nt' else 6)
        if not busy:
            self.assertEqual(calls[1].args[1], 2 if platform == 'nt' else 8)
            self.assertEqual(calls[0].args[0], calls[1].args[0])

    def test_linux_singleton_acquires_and_releases_on_exit(self):
        self.check_worker('posix', False)

    def test_linux_busy_worker_does_not_start_jobs(self):
        self.check_worker('posix', True)

    def test_windows_singleton_acquires_and_releases_on_exit(self):
        self.check_worker('nt', False)

    def test_windows_busy_worker_does_not_start_jobs(self):
        self.check_worker('nt', True)


if __name__ == '__main__':
    unittest.main()
