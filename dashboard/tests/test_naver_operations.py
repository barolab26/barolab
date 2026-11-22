"""Recovered Naver artifacts remain bound to account and actual reserved content."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from dashboard.collectors.naver_public import resolve_artifact_folder


class NaverOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)/'naver_blog_posting'
        self.folder = self.base/'output/recovery-20261106/soultin-0740'
        self.folder.mkdir(parents=True)
        self.saved = {'document': {'components': [{'text': 'exact reserved content'}]}}
        digest = hashlib.sha256(json.dumps(self.saved['document']['components'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        for name, value in [('identity.json', {'account':'soultin','blogId':'mustpickinfo'}),
                            ('reservation-evidence.json', {'account':'soultin','blogId':'mustpickinfo','submissionStatus':'verified_reserved','documentSha256':digest}),
                            ('reserved-server-document.json',self.saved)]:
            (self.folder/name).write_text(json.dumps(value),encoding='utf-8')

    def test_native_and_known_windows_mount_resolve_same_bound_artifact(self):
        self.assertEqual(resolve_artifact_folder(str(self.folder),'soultin',self.base),self.folder.resolve())
        windows=r'C:\10_Project\BaroLab\naver_blog_posting\output\recovery-20261106\soultin-0740'
        self.assertEqual(resolve_artifact_folder(windows,'soultin',self.base),self.folder.resolve())

    def test_other_account_or_mutated_document_is_rejected(self):
        self.assertIsNone(resolve_artifact_folder(str(self.folder),'soul5373',self.base))
        self.saved['document']['components'][0]['text']='changed'
        (self.folder/'reserved-server-document.json').write_text(json.dumps(self.saved),encoding='utf-8')
        self.assertIsNone(resolve_artifact_folder(str(self.folder),'soultin',self.base))

    def test_unknown_windows_root_is_not_a_mount_alias(self):
        value=r'D:\OtherProject\naver_blog_posting\output\recovery-20261106\soultin-0740'
        self.assertIsNone(resolve_artifact_folder(value,'soultin',self.base))

    def test_legacy_submission_gate_absent_disabled_malformed_and_cf_unaffected(self):
        from unittest.mock import patch
        from dashboard.common import naver_ownership, channel_parameters, system_watchdog
        import naver_blog_posting.posting as posting

        root = Path(self.temp.name)
        marker = root / 'dashboard/data/naver/execution-owner.json'
        marker.parent.mkdir(parents=True, exist_ok=True)

        # 1. Absent marker preserves compatibility
        self.assertTrue(naver_ownership.legacy_naver_submission_allowed(root))
        naver_ownership.require_legacy_naver_submission_allowed(root)

        # 2. Malformed marker fails closed
        marker.write_text('{bad json', encoding='utf-8')
        self.assertFalse(naver_ownership.legacy_naver_submission_allowed(root))
        with self.assertRaises(RuntimeError):
            naver_ownership.require_legacy_naver_submission_allowed(root)

        # 3. Disabled marker refuses legacy Naver submission across entrypoints
        marker.write_text(json.dumps({
            'schema': 'naver-execution-owner-v1',
            'legacy_submission_enabled': False,
            'new_submission_enabled': False,
            'status': 'handoff_preflight',
            'target_owner': 'BaroLab_rust',
        }), encoding='utf-8')
        self.assertFalse(naver_ownership.legacy_naver_submission_allowed(root))

        with patch.object(posting, 'BASE', root / 'naver_blog_posting'):
            with self.assertRaises(RuntimeError):
                posting.run_basic_pipeline('soul5373', prepare_only=False)
            with self.assertRaises(RuntimeError):
                posting.basic_daily(1)
            with self.assertRaises(RuntimeError):
                posting.revise_existing_reservation(None, 'soul5373', {}, {}, {}, '2026-11-09 19:30', self.folder, {})

        with patch.object(channel_parameters, 'ROOT', root):
            for naver_action in (['naver', '--account', 'soul5373'], ['naver-cycle'], ['conference', '--account', 'soul5373']):
                with self.assertRaises(RuntimeError):
                    channel_parameters.main(naver_action)

            # Unrelated CF action in _prepare_all runs CF while skipping Naver
            cf_called = []
            with patch.object(channel_parameters, 'policy', return_value={
                'effectiveDate': '2026-11-01',
                'timezone': 'Asia/Seoul',
                'naver': {'soul5373': {'slots': ['15:00']}},
                'cf': {'must-pick.com': '10:00'},
            }), patch.object(channel_parameters, 'DATA', root / 'dashboard/data'), \
                 patch('common.work_agenda.enabled', return_value=False), \
                 patch.object(channel_parameters, 'prepare_cf', side_effect=lambda d, dom: cf_called.append((d, dom)) or {'state': 'prepared', 'folder': 'cf_out'}):
                state = channel_parameters._prepare_all('2026-11-09')
                self.assertEqual(state['naver'], {})
                self.assertEqual(cf_called, [('2026-11-09', 'must-pick.com')])

        # Watchdog skips Naver --catch-up and BaroLab-Naver-Daily re-enable when disabled
        nv_active = root / 'dashboard/data/naver/active-workflow.json'
        nv_active.write_text(json.dumps({'status': 'running', 'pid': 99999999, 'updatedAt': '2026-11-01T00:00:00+09:00'}), encoding='utf-8')
        popens = []
        ps_cmds = []
        with patch.object(system_watchdog, 'ROOT', root), \
             patch('common.work_agenda.enabled', return_value=False), \
             patch.object(system_watchdog, 'ensure_daily_4portal_indexing', return_value=None), \
             patch.object(system_watchdog, 'is_process_running_match', return_value=False), \
             patch.object(system_watchdog, 'is_pid_alive', return_value=False), \
             patch('subprocess.Popen', side_effect=lambda *a, **kw: popens.append(a[0])), \
             patch('subprocess.run', side_effect=lambda *a, **kw: ps_cmds.append(a[0]) or type('R', (), {'stdout': 'RE_ENABLED', 'returncode': 0})()):
            actions = system_watchdog.clean_zombie_locks_and_recover()
            self.assertFalse(any(a.get('channel') == 'naver_blog' for a in actions))
            self.assertFalse(any('naver_blog_posting' in ' '.join(map(str, cmd)) for cmd in popens))
            catchups = system_watchdog.trigger_missed_slot_catchup()
            self.assertFalse(any(c.get('channel') == 'naver_blog' for c in catchups))
            self.assertFalse(any('BaroLab-Naver-Daily' in ' '.join(map(str, cmd)) for cmd in ps_cmds))
            self.assertTrue(any('BaroLab-CF-Cleaner' in ' '.join(map(str, cmd)) for cmd in ps_cmds))


