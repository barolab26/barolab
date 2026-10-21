"""Offline visible-workflow routing and external-response boundaries."""
from types import SimpleNamespace
import os
import copy
import hashlib
from datetime import timedelta
import subprocess
import unittest
from unittest.mock import Mock, patch

from bs4 import BeautifulSoup
from common import ubuntu_naver_browser
from naver_blog_posting import pipeline_runner as runner
import ego_lite_runner as ego


class VisibleWorkflowTests(unittest.TestCase):
    def test_preparation_only_skips_publication_reconciliation(self):
        with patch.object(ego.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(ego.run_visible_naver('soultin', prepare_only=True), 0)
        self.assertEqual(run.call_count, 1)
        self.assertIn('--prepare-only', run.call_args.args[0])
        self.assertIn('--visible', run.call_args.args[0])
        self.assertNotIn('--refresh', run.call_args.args[0])
        with patch.object(ego.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                ego.run_visible_naver('soultin', prepare_only=True, prepared_dir='/prior/publication')
            run.assert_not_called()

    def test_catch_up_dry_run_only_reads_existing_plan(self):
        with patch.object(runner, 'recovery_plan', return_value={'eligible': []}) as plan, \
                patch.object(ego.subprocess, 'run') as run, patch('builtins.print'):
            self.assertEqual(ego.run_visible_naver_catch_up(dry_run=True), 0)
            plan.assert_called_once_with()
            run.assert_not_called()

    def test_catch_up_routes_existing_visible_bounded_scheduler(self):
        with patch.object(ego.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(ego.run_visible_naver_catch_up(), 0)
        self.assertEqual(run.call_args.args[0][-2:], ['--catch-up', '--visible'])
        self.assertEqual(run.call_args.kwargs['env']['BAROLAB_UBUNTU_NAVER_CATCH_UP'], '1')

    def test_daily_refresh_is_opt_in_and_preserves_exact_active_worker(self):
        with patch.object(runner, 'os', SimpleNamespace(name='nt', environ={'BAROLAB_UBUNTU_NAVER_CATCH_UP': '1'})), \
                patch.object(runner.subprocess, 'run') as run:
            runner.refresh_ubuntu_daily_account('yoon_master')
            run.assert_not_called()
        with patch.object(runner, 'os', SimpleNamespace(name='posix', environ={})), \
                patch.object(runner.subprocess, 'run') as run:
            runner.refresh_ubuntu_daily_account('yoon_master')
            run.assert_not_called()
        with patch.object(runner, 'os', SimpleNamespace(name='posix', environ={'BAROLAB_UBUNTU_NAVER_CATCH_UP': '1'})), \
                patch.object(runner.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'refresh')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                runner.refresh_ubuntu_daily_account('yoon_master', 'exact-worker-id')
            self.assertEqual(run.call_args.args[0][-2:], ['--worker-id', 'exact-worker-id'])
            self.assertTrue(run.call_args.kwargs['check'])

    def test_daily_submission_cannot_renew_without_exact_worker(self):
        with patch.object(runner, 'os', SimpleNamespace(name='posix', environ={'BAROLAB_UBUNTU_NAVER_CATCH_UP': '1'})), \
                patch.object(runner, 'RUN_OPTIONS', {}), patch.object(runner, 'refresh_ubuntu_daily_account') as refresh:
            with self.assertRaisesRegex(RuntimeError, 'exact active worker'):
                runner.renew_ubuntu_daily_before_submission('yoon_master')
            refresh.assert_not_called()
            runner.RUN_OPTIONS['worker_id'] = 'bound-active-worker'
            runner.renew_ubuntu_daily_before_submission('yoon_master')
            refresh.assert_called_once_with('yoon_master', 'bound-active-worker')

    def test_explicit_ego_entry_routes_only_to_canonical_visible_runner(self):
        with patch.object(ego.subprocess, "run", side_effect=[subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 7)]) as run:
            code = ego.run_visible_naver("yoon_master", slot="09:00", publication_date="2026-10-22",
                                        topic_seed="reader task", main_keyword="loafers socks",
                                        evidence_dir="/private/evidence folder", prepared_dir="/private/prepared folder")
            self.assertEqual(code, 7)
            self.assertEqual(run.call_args_list[0].args[0][2:], ["naver_blog_posting.account_reconciliation", "--account", "yoon_master", "--refresh"])
            command = run.call_args.args[0]
            self.assertEqual(command[:4], [ego.sys.executable, str(ego.ROOT / "naver_blog_posting/pipeline_runner.py"),
                                          "--account", "yoon_master"])
            self.assertIn("--visible", command)
            self.assertEqual(command[-2:], ["--prepared-dir", "/private/prepared folder"])
            self.assertFalse(run.call_args.kwargs["shell"])
            self.assertEqual(run.call_args.kwargs["cwd"], str(ego.ROOT))

    def test_prepared_materials_and_strategy_forward_exactly_without_shell(self):
        with patch.object(ego.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(ego.run_visible_naver("soultin", prepared_dir="/private/prepared folder",
                             strategy=2, materials_manifest="/private/official screens.json"), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[-6:], ["--prepared-dir", "/private/prepared folder",
                             "--strategy", "2", "--materials-manifest", "/private/official screens.json"])
            self.assertFalse(run.call_args.kwargs["shell"])
        with patch.object(ego, "run_visible_naver") as launch:
            with self.assertRaises(SystemExit):
                ego.main(["--naver-account", "soultin", "--strategy", "5"])
            with self.assertRaises(SystemExit):
                ego.main(["--materials-manifest", "/private/official screens.json"])
            launch.assert_not_called()

    def test_reserve_time_uses_existing_explicit_custom_time_contract(self):
        from datetime import datetime
        with patch.object(ego.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(ego.run_visible_naver('soultin', publication_date='2026-10-21',
                             prepared_dir='/private/prepared', reserve_time='2026-10-21 11:00'), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ['--reserve-time', '2026-10-21 11:00'])
        self.assertNotIn('--slot', command)
        self.assertFalse(run.call_args.kwargs['shell'])
        now = datetime(2026, 10, 21, 9, 0, tzinfo=runner.KST)
        target = runner.slot_target('soultin', '11:00', now=now,
                                    publication_date='2026-10-21', allow_custom=True)
        self.assertEqual(target.strftime('%Y-%m-%d %H:%M'), '2026-10-21 11:00')
        with self.assertRaisesRegex(ValueError, 'Unknown publication slot'):
            runner.slot_target('soultin', '11:15', now=now, publication_date='2026-10-21')

    def test_failed_refresh_does_not_launch_pipeline(self):
        with patch.object(ego.subprocess, "run", return_value=subprocess.CompletedProcess([], 9)) as run:
            self.assertEqual(ego.run_visible_naver("yoon_master"), 9)
            self.assertEqual(run.call_count, 1)
            self.assertIn("--refresh", run.call_args.args[0])

    def test_explicit_ego_entry_rejects_unknown_account_before_subprocess(self):
        with patch.object(ego.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                ego.run_visible_naver("unexpected")
            run.assert_not_called()

    def test_exact_fresh_visible_packet_reused_but_changed_or_unverifiable_fetches(self):
        body = "Actual observed competitor article body. " * 8
        packet = {"account": "yoon_master", "query": "loafers socks", "serp": {"text": "results"},
                  "searchSurface":"naver_blog", "sort":"relevance", "observedAt":runner.now_kst().isoformat(),
                  "recentTitles": ["prior"], "recent60DaysComplete": True,
                  "competitors": [{"url": f"https://blog.naver.com/example/{123+i}", "observedRank":i+1,
                    "excerpt": {"url": f"https://m.blog.naver.com/example/{123+i}", "text": body,
                                "bodySha256": hashlib.sha256(body.encode()).hexdigest(),
                                "collectionMethod": "visible_browser_article",
                                "collectedAt": runner.now_kst().isoformat()}} for i in range(3)]}
        with patch.object(runner, "collect_evidence", return_value={"actual": "fetch"}) as collect:
            self.assertIs(runner.selected_keyword_evidence("yoon_master", "loafers socks", packet), packet)
            collect.assert_not_called()
            variants = []
            for field, value in (("bodySha256", "bad"), ("collectionMethod", "search_snippet"),
                                 ("collectedAt", (runner.now_kst() - timedelta(hours=25)).isoformat())):
                bad = copy.deepcopy(packet)
                bad["competitors"][0]["excerpt"][field] = value
                variants.append(bad)
            variants += [{**packet, "query": "different"}, {**packet, "account": "soultin"}]
            for bad in variants:
                self.assertEqual(runner.selected_keyword_evidence("yoon_master", "loafers socks", bad),
                                 {"actual": "fetch"})
            self.assertEqual(collect.call_count, len(variants))

    def test_external_directives_never_execute_code_or_writer(self):
        if not hasattr(ego, "dispatch_command"):
            # The clean repository daemon has no external directive dispatcher.
            self.assertFalse(hasattr(ego, "poll_and_execute_gemini_command"))
            return
        with patch.object(ego, "_run") as run:
            for command in ({"directiveId": "x", "python_code": "raise AssertionError"},
                            {"directiveId": "x", "shell_cmd": "false"},
                            {"directiveId": "x", "action": "NAVER_SMARTEDITOR_WRITE"}):
                self.assertFalse(ego.dispatch_command(command)[0])
            run.assert_not_called()

    def test_local_events_never_send_external_messages(self):
        with patch("common.gemini_chat_controller.send_gemini_message_sync") as send:
            self.assertFalse(ego.send_gemini_message_sync("local event", "publication"))
            self.assertFalse(ego.send_gemini_message_sync("local event", "command_done"))
            send.assert_not_called()

    def test_failed_competitor_bodies_cannot_promote_search_snippet(self):
        with patch('naver_blog_posting.visible_research.collect_blog_evidence', return_value={
                'query':'actual query','searchSurface':'naver_blog','sort':'relevance',
                'observedAt':runner.now_kst().isoformat(),'competitors':[]}) as collect, \
                patch.object(runner, "public_post_inventory") as inventory:
            with self.assertRaisesRegex(RuntimeError, "All three observed"):
                runner.collect_evidence(runner.ACCOUNT_MAP["soultin"], "actual query")
            collect.assert_called_once_with('soultin','actual query')
            inventory.assert_not_called()

    def test_visible_focus_targets_only_verified_process_window(self):
        rows = '0x01 0 999 host other\n0x02 0 123 host selected\n'
        with patch("common.browser_session._runtime", return_value={"ProcessId": 123}), \
                patch.object(ubuntu_naver_browser.subprocess, "run",
                             return_value=subprocess.CompletedProcess([], 0, rows)) as run:
            ubuntu_naver_browser.focus_workflow_window(9334)
            self.assertEqual(run.call_args.args[0], ["wmctrl", "-ia", "0x02"])
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_visible_stage_routes_images_to_flow_and_editor_to_account(self):
        for stage, port in ((4, 9440), (6, 9335)):
            with self.subTest(stage=stage), \
                    patch.object(runner, "os", SimpleNamespace(name="posix",
                                 environ={"BAROLAB_VISIBLE_WORKFLOW": "1"})), \
                    patch.object(ubuntu_naver_browser, "focus_workflow_window",
                                 side_effect=RuntimeError("stop before state writes")) as focus:
                with self.assertRaisesRegex(RuntimeError, "stop before"):
                    runner.update_pipeline_status({"cdp_port": 9335}, stage, "stage", 0, "detail")
                focus.assert_called_once_with(port)


if __name__ == "__main__":
    unittest.main()
