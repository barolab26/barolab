"""Regression checks for native worker identity and preserving live lock inodes."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import system_watchdog as watchdog


class NativeWatchdogTests(unittest.TestCase):
    def test_old_lock_files_and_active_workers_are_never_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'dashboard/data';data.mkdir(parents=True)
            flow=root/'.barolab/runtime/flow-generation.lock';flow.parent.mkdir(parents=True)
            maintenance=data/'content-maintenance.lock'
            for path in (flow,maintenance):path.write_text('0');os.utime(path,(1,1))
            identities={path:path.stat().st_ino for path in (flow,maintenance)}
            state=root/'dashboard/data/cf/pipeline_state.json';state.parent.mkdir(parents=True)
            state.write_text(json.dumps({'status':'processing','updatedAt':'2020-01-01T00:00:00+09:00','pid':999}))
            with patch.object(watchdog,'ROOT',root),patch.object(watchdog,'DATA_DIR',data), \
                    patch.object(watchdog.Path,'home',return_value=root), \
                    patch.object(watchdog,'is_process_running_match',return_value=True), \
                    patch.object(watchdog,'is_pid_alive',return_value=False),patch.object(watchdog.subprocess,'Popen') as launch:
                self.assertEqual(watchdog.clean_zombie_locks_and_recover(),[])
            for path,inode in identities.items():self.assertEqual(path.stat().st_ino,inode)
            self.assertEqual(json.loads(state.read_text())['status'],'processing')
            launch.assert_not_called()

    def test_native_worker_match_requires_python_and_exact_script_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);process=root/'123';process.mkdir()
            script='/repo/cf_posting/posting.py'
            cmd=process/'cmdline';cmd.write_bytes(b'/venv/python3\0-u\0'+script.encode()+b'\0baronote.kr\0')
            self.assertTrue(watchdog.is_process_running_match(script,root))
            self.assertFalse(watchdog.is_process_running_match('/repo/naver_blog_posting/posting.py',root))
            cmd.write_bytes(b'/bin/bash\0-c\0'+script.encode())
            self.assertFalse(watchdog.is_process_running_match(script,root))

    def test_relative_cli_worker_is_the_same_publisher_as_its_absolute_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);process=root/'123';process.mkdir()
            workspace=root/'workspace';workspace.mkdir()
            (process/'cwd').symlink_to(workspace,target_is_directory=True)
            (process/'cmdline').write_bytes(b'/venv/python3\0-u\0cf_posting/posting.py\0--catch-up-today-once\0')
            self.assertTrue(watchdog.is_process_running_match(str(workspace/'cf_posting/posting.py'),root))
            self.assertFalse(watchdog.is_process_running_match(str(workspace/'naver_blog_posting/posting.py'),root))

if __name__=='__main__':unittest.main()
