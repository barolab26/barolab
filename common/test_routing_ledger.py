"""Host acceptance contract; expected to fail before the actual Patch proposal."""
import json
import tempfile
import unittest
from pathlib import Path
from common.routing_ledger import read_routing_summary, format_routing_summary

class RoutingLedgerTests(unittest.TestCase):
    def read(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ledger.jsonl'
            path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
            return read_routing_summary(path)

    def test_historical_records_are_not_current_failures_or_unique_tasks(self):
        rows = [{'status': status, 'provider': 'agy', 'time_utc': '2026-10-16T03:31:56Z'}
                for status in ['ok']*10+['invalid']*8+['failed']*2]
        summary = self.read(rows)
        self.assertEqual(summary['total'], 20)
        self.assertEqual(summary['countUnit'], 'records')
        self.assertEqual(summary['success'], 10)
        self.assertEqual(summary['invalid'], 8)
        self.assertEqual(summary['failed'], 2)
        self.assertIsNone(summary['currentFailureCount'])
        self.assertEqual(summary['sourcePeriod'], {'first': '2026-10-16T03:31:56Z', 'last': '2026-10-16T03:31:56Z'})
        self.assertEqual(summary['providers'], ['agy'])
        text = format_routing_summary(summary)
        for word in ('과거', '2026-10-16', 'agy', '기록', '미관측', 'invalid', 'failed', '원인 미상'):
            self.assertIn(word, text)
        self.assertNotIn('20개 작업', text)

    def test_pending_missing_unknown_are_not_failed(self):
        summary = self.read([{'status':'pending'}, {}, {'status':'unknown'}])
        self.assertEqual(summary['failed'], 0)
        self.assertEqual(summary['unknown'], 3)
        self.assertIsNone(summary['currentFailureCount'])
        self.assertEqual(summary['sourcePeriod'], {'first': None, 'last': None})
        self.assertIn('시점 미상', format_routing_summary(summary))

    def test_empty_or_malformed_is_unobserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'ledger.jsonl'
            for contents in ('', 'not JSON'):
                path.write_text(contents, encoding='utf-8')
                summary = read_routing_summary(path)
                self.assertEqual(summary['total'], 0)
                self.assertIsNone(summary['currentFailureCount'])
                self.assertIn('미관측', format_routing_summary(summary))

if __name__ == '__main__': unittest.main()
