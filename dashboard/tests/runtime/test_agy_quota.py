"""Subscription quota uses only the CLI's structured /usage result."""
import copy
import json
import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from server import cockpit_telemetry as probe, cockpit_panels as panels


class AgyQuotaTests(unittest.TestCase):
    def payload(self):
        return {'status': 'SUCCESS', 'account': 'private-account', 'command': {'name': 'usage', 'data': {'groups': [
            {'name': name, 'buckets': [{'window': 'weekly', 'remaining_fraction': fraction, 'reset_time': '2026-10-30T22:00:00Z'},
                                      {'window': '5h', 'remaining_fraction': 1, 'reset_time': '2026-10-24T12:49:00Z'}]}
            for name, fraction in [('Gemini Models', .986), ('Claude and GPT models', .247)]
        ]}}}

    def collect(self, payload):
        with patch.object(probe.Path, 'is_file', return_value=True), patch.object(probe.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), 'private-output')) as run:
            result = probe.agy_quota()
        command = run.call_args.args[0]
        self.assertEqual(command[1:], ['-p', '/usage', '--output-format', 'json', '--print-timeout', '15s'])
        self.assertEqual(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs['timeout'], 20)
        self.assertNotIn('private', json.dumps(result))
        return result

    def test_separate_pools_and_windows_are_preserved_and_rendered(self):
        result = self.collect(self.payload())
        self.assertEqual(result['status'], 'collected')
        now = datetime(2026, 10, 24, 8, tzinfo=timezone.utc)
        result['checkedAt'] = now.timestamp()
        display = panels.brain_display({'remote': {'agy': result}}, now)
        self.assertEqual(len(display['rows']), 4)
        self.assertIn('Gemini 98.6%/100%', display['rows'][1])
        self.assertIn('Claude/GPT 24.7%/100%', display['rows'][1])
        self.assertIn('다음 리셋 10-24 21:49', display['rows'][1])
        result['checkedAt'] -= 181
        self.assertIn('조회 미확인', panels.brain_display({'remote': {'agy': result}}, now)['rows'][1])

    def test_invalid_or_missing_evidence_never_becomes_zero_remaining(self):
        for value in (True, -1, 1.1, None, '0', float('nan')):
            payload = self.payload()
            payload['command']['data']['groups'][0]['buckets'][0]['remaining_fraction'] = value
            result = self.collect(payload)
            self.assertNotEqual(result['status'], 'collected')
            self.assertNotIn('groups', result)
        payload = self.payload()
        payload['command']['data']['groups'] = []
        self.assertNotEqual(self.collect(payload)['status'], 'collected')
        payload = self.payload();payload['command']['name'] = 'model-response'
        self.assertNotEqual(self.collect(payload)['status'], 'collected')

    def test_uninstalled_and_timeout_do_not_leak_auth_or_block_forever(self):
        with patch.object(probe.Path, 'is_file', return_value=False), patch.object(probe.subprocess, 'run') as run:
            self.assertEqual(probe.agy_quota()['status'], 'CLI 미설치')
            run.assert_not_called()
        with patch.object(probe.Path, 'is_file', return_value=True), patch.object(probe.subprocess, 'run', side_effect=subprocess.TimeoutExpired('agy', 20, output='private-code')):
            result = probe.agy_quota()
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('remainingPercent', result)
