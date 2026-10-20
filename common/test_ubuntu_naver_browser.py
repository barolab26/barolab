import tempfile
import unittest
import io
import json
import shlex
from pathlib import Path
from unittest.mock import patch

from common import ubuntu_naver_browser as browser


class UbuntuNaverBrowserTests(unittest.TestCase):
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
