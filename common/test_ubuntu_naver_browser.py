import tempfile
import unittest
import io
import json
import shlex
import asyncio
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock, AsyncMock
from types import SimpleNamespace

from common import ubuntu_naver_browser as browser


class UbuntuNaverBrowserTests(unittest.TestCase):
    def setUp(self):
        gc=patch.object(browser,"gc_blank_tabs",return_value=0);gc.start();self.addCleanup(gc.stop)

    def test_naver_search_and_images_connect_to_same_cf_browser(self):
        from naver_blog_posting import pipeline_runner
        from common import browser_session
        runtime = SimpleNamespace(CDP_URL="http://127.0.0.1:9440",
                                  BROWSER_EXE="/opt/google/chrome/chrome",
                                  BROWSER_USER_DATA="/existing/shared/profile",
                                  gather_sources=AsyncMock(),
                                  generate_flow_images_in_browser=AsyncMock(),
                                  ensure_isolated_browser_ready=Mock())
        class StopBeforeBrowserInteraction(Exception):
            pass
        with patch.dict("sys.modules", {"cf_posting.pipeline_runner": runtime}), \
                patch.object(pipeline_runner, "os", SimpleNamespace(name="posix")), \
                patch("playwright.async_api.async_playwright", return_value=MagicMock()), \
                patch("common.source_discovery.search_urls", return_value=[]), \
                patch.object(browser_session, "connect_async",
                             new=AsyncMock(side_effect=StopBeforeBrowserInteraction)) as connect:
            for make_call in (lambda: pipeline_runner.search_primary_sources("example"),
                              lambda: pipeline_runner.generate_photos([], Path("/unused"), "soultin", "example")):
                with self.assertRaises(StopBeforeBrowserInteraction):
                    asyncio.run(make_call())
                self.assertEqual(connect.call_args.args[1:],
                                 (runtime.CDP_URL, runtime.BROWSER_EXE, runtime.BROWSER_USER_DATA))
            runtime.ensure_isolated_browser_ready.assert_called_once()

    def test_source_browser_always_uses_observed_native_flow_session(self):
        from naver_blog_posting import pipeline_runner
        endpoint,executable,profile=pipeline_runner.source_browser_paths()
        self.assertEqual(endpoint,'http://127.0.0.1:9440')
        self.assertEqual(executable,'/opt/google/chrome/chrome')
        self.assertEqual(profile,str(Path.home()/'.config/cdp_gui_9440'))

    def test_shared_flow_runtime_verifies_actual_linux_profile(self):
        from common import browser_session
        profile = Path.home() / ".config/cdp_gui_9440"
        with patch.object(browser_session, "os", SimpleNamespace(name="posix")), \
                patch.object(browser, "process_identity", return_value=456) as identity, \
                patch.object(browser, "listener_owner") as listener:
            result = browser_session._runtime(9440, "/opt/google/chrome/chrome", str(profile))
            self.assertEqual(result["ProcessId"], 456)
            identity.assert_called_once_with(9440, profile)
            self.assertTrue(all(c.args==(9440,456) for c in listener.call_args_list))

    def test_naver_pipeline_routes_linux_to_account_launcher(self):
        from naver_blog_posting import pipeline_runner
        with patch.object(pipeline_runner, "os", SimpleNamespace(name="posix")), \
                patch.object(browser, "ensure_account") as ensure, \
                patch.object(pipeline_runner.subprocess, "Popen") as popen:
            account = pipeline_runner.ACCOUNT_MAP["soultin"]
            pipeline_runner.start_browser(account)
            ensure.assert_called_once_with(9334)
            popen.assert_not_called()
            executable, profile, _ = browser.account_paths(9334)
            self.assertEqual(pipeline_runner.account_browser_paths(account), (str(executable), str(profile)))

    def test_kin_linux_account_uses_verified_naver_profile(self):
        from naver_kin import browser as kin_browser
        with patch.object(kin_browser, "os", SimpleNamespace(name="posix")):
            config = kin_browser.account_config("stone0747")
            executable, profile, _ = browser.account_paths(9230)
            self.assertEqual((config["exe"], config["profile"]), (str(executable), str(profile)))

    def test_ensure_reuses_verified_process_without_launch(self):
        with patch.object(browser, "process_identity", return_value=123), \
                patch.object(browser, "listener_owner") as owner, \
                patch.object(browser.subprocess, "run") as run:
            self.assertEqual(browser.ensure_account(9334), 123)
            owner.assert_called_once_with(9334, 123)
            run.assert_not_called()

    def test_ensure_starts_only_dedicated_script_and_rechecks_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(Path, "home", return_value=home):
                _, _, script = browser.account_paths(9334)
                script.parent.mkdir(parents=True)
                script.write_text("#!/bin/sh\n")
                with patch.object(browser, "process_identity", side_effect=[None, 123]), \
                        patch.object(browser, "listener_owner") as owner, \
                        patch.object(browser.subprocess, "run") as run:
                    self.assertEqual(browser.ensure_account(9334), 123)
                    self.assertEqual(run.call_args.args[0], [str(script)])
                    owner.assert_called_once_with(9334, 123)

    def test_ensure_missing_script_never_launches(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(Path, "home", return_value=Path(directory)), \
                patch.object(browser, "process_identity", return_value=None), \
                patch.object(browser.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "launcher missing"):
                browser.ensure_account(9334)
            run.assert_not_called()

    def test_unknown_account_port_never_launches(self):
        with patch.object(browser.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Unknown Naver account port"):
                browser.ensure_account(9999)
            run.assert_not_called()

    def test_existing_unrelated_listener_never_triggers_relaunch(self):
        with patch.object(browser, "process_identity", return_value=123), \
                patch.object(browser, "listener_owner", side_effect=RuntimeError("wrong listener")), \
                patch.object(browser.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "wrong listener"):
                browser.ensure_account(9334)
            run.assert_not_called()

    def test_session_requires_real_account_identity(self):
        from common import browser_session
        executable, profile, _ = browser.account_paths(9334)
        with patch.object(browser_session, "os", SimpleNamespace(name="posix")), \
                patch.object(browser, "process_identity", return_value=123), \
                patch.object(browser, "listener_owner") as owner:
            result = browser_session._runtime(9334, str(executable), str(profile))
            self.assertEqual(result["ProcessId"], 123)
            owner.assert_called_once_with(9334, 123)
            with self.assertRaisesRegex(RuntimeError, "paths do not match"):
                browser_session._runtime(9334, str(executable), "/other/profile")
            with self.assertRaisesRegex(RuntimeError, "paths do not match"):
                browser_session._runtime(9334, "/other/chrome", str(profile))

    def test_failed_native_heal_cannot_use_http_fast_path(self):
        from common import browser_session
        executable,profile,_=browser.account_paths(9334)
        with patch.object(browser,'ensure_account',side_effect=RuntimeError('native launch failed')),patch('requests.get') as request:
            with self.assertRaisesRegex(RuntimeError,'native launch failed'):browser_session._runtime(9334,str(executable),str(profile))
            request.assert_not_called()

    def test_account_map_matches_expected_ports(self):
        self.assertEqual({key: value["cdp_port"] for key, value in browser.accounts().items()},
                         {"soultin": 9334, "soul5373": 9333, "yoon_master": 9335,
                          "adinfo0905": 9231, "stone0747": 9230})

    def test_install_creates_dedicated_private_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = browser.install(Path(directory))
            scripts = list(root.glob("*/*_start_cdp.sh"))
            self.assertEqual(len(scripts), 5)
            self.assertIn("--account soultin", (root / "soultin/soultin_start_cdp.sh").read_text())
            self.assertNotIn("google-chrome", scripts[0].read_text())

    def test_different_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            (proc / "123").mkdir()
            (proc / "123/cmdline").write_bytes(
                b"/opt/google/chrome/chrome\0--remote-debugging-port=9334\0--user-data-dir=/wrong\0")
            with self.assertRaisesRegex(RuntimeError, "different Chrome profile"):
                browser.process_identity(9334, Path("/expected"), proc)

    def test_rewritten_chrome_title_ignores_renderer_and_unrelated_process(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            expected = Path("/expected")
            main = ["/opt/google/chrome/chrome", "--remote-debugging-port=9334",
                    f"--user-data-dir={expected}"]
            for pid, command in [
                ("123", shlex.join(main).encode() + b"\0"),
                ("124", shlex.join(main + ["--type=renderer"]).encode() + b"\0"),
                ("125", b"unrelated \xff 'broken\0"),
            ]:
                (proc / pid).mkdir()
                (proc / pid / "cmdline").write_bytes(command)
            original = Path.resolve
            with patch.object(Path, "resolve", lambda p: Path("/opt/google/chrome/chrome")
                              if p.name == "exe" else original(p)):
                self.assertEqual(browser.process_identity(9334, expected, proc), 123)

    def test_existing_browser_reuse_preserves_preferences_and_creates_no_browser(self):
        from subprocess import CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            preferences = home / ".config/cdp_naver_soultin/Default/Preferences"
            preferences.parent.mkdir(parents=True)
            preferences.write_text('{"profile":{"name":"existing"}}')
            with patch.object(Path, "home", return_value=home), \
                 patch.object(browser, "process_identity", return_value=123), \
                 patch.object(browser, "listener_owner"), \
                 patch.object(browser, "urlopen", side_effect=[
                     io.StringIO('{"Browser":"Chrome/1"}'),
                     io.StringIO('[{"type":"page","url":"https://nid.naver.com/nidlogin.login"}]')]), \
                 patch.object(browser.subprocess, "run", return_value=CompletedProcess([], 0, "")), \
                 patch.object(browser.subprocess, "Popen") as spawn:
                browser.launch("soultin")
            spawn.assert_not_called()
            self.assertEqual(preferences.read_text(), '{"profile":{"name":"existing"}}')
            receipt = json.loads((home / ".barolab/browsers/soultin/launch-receipt.json").read_text())
            self.assertTrue(receipt["reused"])

    def test_listener_must_be_loopback_and_expected_pid(self):
        from subprocess import CompletedProcess
        for address, pid in [("0.0.0.0:9334", 12), ("127.0.0.1:9334", 99)]:
            output = f'State Recv-Q Send-Q Local Peer Process\nLISTEN 0 10 {address} 0.0.0.0:* users:(("chrome",pid={pid},fd=3))\n'
            with patch.object(browser.subprocess, "run", return_value=CompletedProcess([], 0, output)):
                with self.assertRaises(RuntimeError):
                    browser.listener_owner(9334, 12)


if __name__ == "__main__":
    unittest.main()


class NativeTabGcTests(unittest.TestCase):
    def test_gc_closes_only_unfocused_empty_blank_and_retains_login_and_editor(self):
        response=Mock();response.json.return_value=[
            {'id':'login','type':'page','url':'https://nid.naver.com/login'},
            {'id':'editor','type':'page','url':'https://blog.naver.com/editor'},
            {'id':'blank','type':'page','url':'about:blank','webSocketDebuggerUrl':'ws://127.0.0.1:9334/devtools/page/blank'}]
        closed=Mock(status_code=200);ws=Mock();ws.recv.return_value='{"id":1,"result":{"result":{"value":true}}}'
        with patch('requests.get',side_effect=[response,closed]) as get,patch('websocket.create_connection',return_value=ws):
            self.assertEqual(browser.gc_blank_tabs(9334),1)
        self.assertTrue(get.call_args.args[0].endswith('/blank'));ws.close.assert_called_once()
