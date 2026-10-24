"""Unresolved incidents must remain actionable without replaying pending work."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from server import project_monitor as monitor, project_health as health
from dashboard.server import worker


class ProjectSupervisionTests(unittest.TestCase):
    def test_retry_retains_history_and_waits_for_cooldown_or_pending_work(self):
        project = {'id': 'collections', 'status': 'stale', 'ownerAgentIds': ['trace']}
        with tempfile.TemporaryDirectory() as root:
            state = Path(root) / 'state.json'
            incidents = Path(root) / 'incidents'
            incidents.mkdir()
            fingerprint = monitor.incident_key(project)
            path = incidents / (fingerprint + '.json')
            with patch.object(monitor, 'STATE', state), patch.object(monitor, 'INCIDENTS', incidents), \
                 patch.object(monitor, 'observed_projects', return_value=[project]), \
                 patch.object(monitor, 'report_project_incident_once'), \
                 patch.object(monitor, 'emit_triage_reason'), \
                 patch.object(monitor.time, 'time', return_value=10000), \
                 patch.object(monitor, '_triage', return_value={'decision': 'inspect', 'domain': '', 'reason': '점검합니다.'}) as triage, \
                 patch('server.agent_tools.enqueue_staff_request', return_value={'requestId': 'new'}) as enqueue:
                for status, stamp in [('dispatched', 1), ('held', 1), ('needs_attention', 9900)]:
                    state.unlink(missing_ok=True)
                    path.write_text(json.dumps({'status': status, 'observedAt': stamp}))
                    self.assertFalse(monitor.process_project_monitor_once())
                state.unlink(missing_ok=True)
                path.write_text(json.dumps({'status': 'needs_attention', 'observedAt': 1,
                    'recheckDate': '1970-01-01', 'recheckCount': monitor.RECHECKS_PER_DAY}))
                self.assertFalse(monitor.process_project_monitor_once())
                triage.assert_not_called()
                state.write_text(json.dumps({'upgradeBaseline': [fingerprint]}))
                previous = {'status': 'needs_attention', 'observedAt': 1, 'staffResultSha256': 'preserved'}
                path.write_text(json.dumps(previous))
                self.assertTrue(monitor.process_project_monitor_once())
                self.assertEqual(json.loads((incidents / 'history' / (fingerprint + '-1.json')).read_text()), previous)
                self.assertTrue(enqueue.call_args.args[0].endswith(':recheck:2'))
                self.assertEqual(enqueue.call_args.args[1][0]['tool'], 'read_agent_status')

    def test_current_manifest_policy_without_retired_aliases(self):
        from datetime import datetime
        moment = datetime(2026, 10, 24, 10, tzinfo=health.KST)
        with patch.object(health, 'schedule_constants', return_value={'DAILY_SLOTS': {'one': ['09:00']}}), \
             patch.object(health, 'load_json', side_effect=[{}, {'checkedAt': moment.isoformat(), 'evidence': []}]):
            quota = health.publication_quota('naver_blog', {}, moment, True)
        self.assertEqual(quota['status'], 'observed')
        self.assertEqual(quota['missing'], 1)

    def test_all_inventory_sources_and_missing_fourth_app_are_checked(self):
        from datetime import datetime
        moment = datetime(2026, 10, 24, 10, tzinfo=health.KST)
        with tempfile.TemporaryDirectory() as root, patch.object(health, 'ROOT', Path(root)), patch.object(health, 'now_kst', return_value=moment):
            for name in ('bible', 'greeting', 'magnifier'):
                path = Path(root) / 'apps' / name / 'project.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({'updatedAt': moment.isoformat(), 'stage': 'testing'}))
            rows = health.observed_projects()
        apps = next(row for row in rows if row['id'] == 'mobile_apps')
        self.assertEqual(apps['status'], 'unknown')
        self.assertEqual(len(apps['source']['supportingManifests']), 4)

    def test_scheduled_full_collection_keeps_indexing_read_only(self):
        with patch.object(worker, 'run_metrics', return_value=0) as run:
            self.assertEqual(worker.run_task('metrics'), 0)
        commands = dict(run.call_args.args[1])
        self.assertIn('dashboard/traffic.py', commands)
        self.assertEqual(commands['dashboard/metrics.py'], ['--collect', '--read-only'])
