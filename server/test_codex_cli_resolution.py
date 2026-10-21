"""Offline executable rollover checks: python -m unittest server.test_codex_cli_resolution."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common import codex_cli


class CodexExecutableResolutionTests(unittest.TestCase):
    def setUp(self):
        self.platform = patch.object(codex_cli, 'is_wsl', return_value=False)
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.temporary = tempfile.TemporaryDirectory(prefix='codex-resolution-test-')
        self.root = Path(self.temporary.name)
        self.install = self.root / 'AppData/Local/OpenAI/Codex/bin'
        self.auth = self.root / 'existing-account-home'
        self.auth.mkdir()
        self.old = self.install / '1111111111111111/codex.exe'
        self.config = {'executable': str(self.old), 'home': str(self.auth), 'model': 'preserved-model'}
        self.config_path = self.root / '.barolab/codex-worker.json'
        self.config_path.parent.mkdir()
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')
        self.home = patch.object(Path, 'home', return_value=self.root)
        self.home.start()

    def tearDown(self):
        self.home.stop()
        self.temporary.cleanup()

    def executable(self, version):
        path = self.install / version / 'codex.exe'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'OFFLINE TEST FIXTURE; NEVER EXECUTED')
        return path

    def test_existing_configured_executable_needs_no_discovery(self):
        self.executable('1111111111111111')
        with patch.object(codex_cli, '_verified_installed_codex') as verify:
            result = codex_cli.local_config()
        self.assertEqual(result, self.config)
        verify.assert_not_called()

    def test_missing_old_unique_verified_new_preserves_account_and_file(self):
        new = self.executable('2222222222222222')
        original = self.config_path.read_bytes()
        with patch.object(codex_cli, '_verified_installed_codex', return_value=True):
            result = codex_cli.local_config()
        self.assertEqual(result, {**self.config, 'executable': str(new.resolve())})
        self.assertEqual(self.config_path.read_bytes(), original)

    def test_multiple_verified_candidates_are_rejected(self):
        self.executable('2222222222222222')
        self.executable('3333333333333333')
        with patch.object(codex_cli, '_verified_installed_codex', return_value=True):
            with self.assertRaisesRegex(RuntimeError, '정확히 1개'):
                codex_cli.local_config()

    def test_unsigned_candidate_is_rejected(self):
        self.executable('2222222222222222')
        with patch.object(codex_cli, '_verified_installed_codex', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '정확히 1개'):
                codex_cli.local_config()

    def test_no_replacement_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '정확히 1개'):
            codex_cli.local_config()

    def test_missing_external_executable_never_searches_install(self):
        self.config['executable'] = str(self.root / 'unrelated/codex.exe')
        with patch.object(codex_cli, '_verified_installed_codex') as verify:
            with self.assertRaises(RuntimeError):
                codex_cli._resolve_executable(self.config)
        verify.assert_not_called()

    def test_missing_home_does_not_discover_or_change_account(self):
        self.auth.rmdir()
        with patch.object(codex_cli, '_resolve_executable') as resolve:
            with self.assertRaises(RuntimeError):
                codex_cli.local_config()
        resolve.assert_not_called()

    def test_signature_must_be_valid_openai_before_version_runs(self):
        for evidence in ({'status': 'NotSigned', 'publisher': 'OpenAI OpCo, LLC'},
                         {'status': 'Valid', 'publisher': 'Unrelated Publisher'}):
            with self.subTest(evidence=evidence), patch.object(codex_cli.subprocess, 'run', return_value=
                    subprocess.CompletedProcess([], 0, json.dumps(evidence), '')) as run:
                self.assertFalse(codex_cli._verified_installed_codex(self.old, self.config))
                self.assertEqual(run.call_count, 1)

    def test_valid_signature_then_codex_version_is_accepted(self):
        responses = [subprocess.CompletedProcess([], 0, json.dumps({'status':'Valid','publisher':'OpenAI OpCo, LLC'}), ''),
                     subprocess.CompletedProcess([], 0, 'codex-cli 0.162.0-alpha.17.2\n', '')]
        with patch.object(codex_cli.subprocess, 'run', side_effect=responses) as run:
            self.assertTrue(codex_cli._verified_installed_codex(self.old, self.config))
        self.assertEqual(run.call_args_list[1].args[0], [str(self.old), '--version'])
        self.assertTrue(run.call_args_list[0].kwargs['env']['PSModulePath'].endswith('WindowsPowerShell\\v1.0\\Modules')
                        or run.call_args_list[0].kwargs['env']['PSModulePath'].endswith('WindowsPowerShell/v1.0/Modules'))

    def test_non_codex_version_is_rejected(self):
        responses = [subprocess.CompletedProcess([], 0, json.dumps({'status':'Valid','publisher':'OpenAI OpCo, LLC'}), ''),
                     subprocess.CompletedProcess([], 0, 'other-tool 1.0.0', '')]
        with patch.object(codex_cli.subprocess, 'run', side_effect=responses):
            self.assertFalse(codex_cli._verified_installed_codex(self.old, self.config))

    def test_wsl_stale_windows_install_resolves_without_mutating_config(self):
        new=self.executable('2222222222222222')
        windows_old=r'C:\Users\fixture\AppData\Local\OpenAI\Codex\bin\1111111111111111\codex.exe'
        windows_new=windows_old.replace('1111111111111111','2222222222222222')
        config={**self.config,'executable':windows_old,'home':r'C:\Users\fixture\auth'}
        self.config_path.write_text(json.dumps(config),encoding='utf-8')
        before=self.config_path.read_bytes()
        def mounted(value):
            return {windows_old:str(self.old),config['home']:str(self.auth),windows_new:str(new)}.get(str(value),str(value))
        with patch.object(codex_cli,'is_wsl',return_value=True), patch.object(codex_cli,'to_wsl_path',side_effect=mounted), patch.object(codex_cli,'to_win_path',return_value=windows_new), patch.object(codex_cli,'_verified_installed_codex',return_value=True) as verify:
            resolved=codex_cli.local_config()
        self.assertEqual(resolved['executable'],windows_new)
        self.assertEqual(resolved['wsl_executable'],str(new))
        self.assertEqual(resolved['home'],config['home'])
        self.assertEqual(resolved['model'],config['model'])
        self.assertEqual(self.config_path.read_bytes(),before)
        verify.assert_called_once()
        self.assertEqual(verify.call_args.args[0],new.resolve())

    def test_wsl_external_stale_path_never_discovers(self):
        with patch.object(codex_cli,'is_wsl',return_value=True), patch.object(codex_cli,'_verified_installed_codex') as verify:
            with self.assertRaises(RuntimeError):
                codex_cli._resolve_executable({'executable':r'C:\unrelated\codex.exe','home':'preserved'})
        verify.assert_not_called()

    def test_wsl_signature_environment_uses_windows_paths_before_version(self):
        exe='/mnt/c/Users/fixture/AppData/Local/OpenAI/Codex/bin/2222222222222222/codex.exe'
        responses=[subprocess.CompletedProcess([],0,json.dumps({'status':'Valid','publisher':'OpenAI OpCo, LLC'}),''),subprocess.CompletedProcess([],0,'codex-cli 0.162.0','')]
        with patch.object(codex_cli,'is_wsl',return_value=True), patch.dict(codex_cli.os.environ,{'WSLENV':'KEEP/w:BAROLAB_CODEX_VERIFY_PATH/p:PSModulePath/p:CODEX_HOME/p'}), patch.object(codex_cli.subprocess,'run',side_effect=responses) as run:
            self.assertTrue(codex_cli._verified_installed_codex(exe,{'home':r'C:\Users\fixture\auth'}))
        first=run.call_args_list[0]
        env=first.kwargs['env']
        self.assertEqual(env['BAROLAB_CODEX_VERIFY_PATH'],r'C:\Users\fixture\AppData\Local\OpenAI\Codex\bin\2222222222222222\codex.exe')
        self.assertIn('BAROLAB_CODEX_VERIFY_PATH/w',env['WSLENV'])
        self.assertNotIn('BAROLAB_CODEX_VERIFY_PATH/p',env['WSLENV'])
        self.assertNotIn('PSModulePath',env['WSLENV'])
        self.assertIn("Join-Path $PSHOME 'Modules'",first.args[0][-1])
        self.assertTrue(first.args[0][0].startswith('/mnt/c/'))
        self.assertEqual(run.call_args_list[1].args[0],[exe,'--version'])
        self.assertNotIn('shell',first.kwargs)

    def test_error_detail_keeps_error_not_thread_or_model_response(self):
        stdout = '{"type":"thread.started","thread_id":"private-thread"}\n{"type":"item.completed","item":{"text":"PRIVATE MODEL RESPONSE"}}'
        message = 'Error: turn/start: turn/start failed: Input should be a valid value; ' + 'details ' * 30
        detail = codex_cli._cli_error_detail(stdout, message)
        self.assertEqual(detail, message.rstrip())
        self.assertNotIn('PRIVATE MODEL', detail)
        self.assertNotIn('private-thread', detail)

    def test_error_detail_structured_event_and_secret_redaction(self):
        message = 'denied api_key=secret123 Bearer sensitive_token sk-abcdefghijklmnopqrst input_value=PRIVATE PROMPT'
        stdout = json.dumps({'type':'turn.failed','error':{'message':message}})
        detail = codex_cli._cli_error_detail(stdout, '')
        for private in ('secret123','sensitive_token','sk-abcdefghijklmnopqrst','PRIVATE PROMPT'):
            self.assertNotIn(private, detail)
        self.assertIn('[redacted]', detail)

    def test_error_detail_does_not_fallback_to_full_stream(self):
        self.assertEqual(codex_cli._cli_error_detail('PRIVATE RESPONSE', 'PRIVATE PROMPT'), '구조화 오류 메시지 없음')
        self.assertLessEqual(len(codex_cli._cli_error_detail('', 'Error: ' + 'x' * 5000)), 1600)


if __name__ == '__main__':
    unittest.main()
