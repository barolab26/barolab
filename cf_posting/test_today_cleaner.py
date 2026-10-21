import ast
import datetime
import json
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

source = Path(__file__).with_name('pipeline_runner.py').read_text(encoding='utf-8')
module = ast.Module(body=[n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in {'catch_up_today_once', 'select_due_items', 'schedule_failed_attempt', 'publication_may_be_inflight'}], type_ignores=[])

class TodayCleanerTests(unittest.TestCase):
    def setup_run(self, items, day=None, acquired=True):
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        schedule = {'date': day or now.date().isoformat(), 'items': items}
        schedule_path = Mock(read_text=lambda **kw: json.dumps(schedule))
        ns = dict(json=json, datetime=datetime, KST=now.tzinfo, cleaner_lock=lambda: nullcontext(acquired),
                  load_or_get_schedule=Mock(return_value=schedule), log_scheduler=Mock(),
                  publication_receipt=lambda item: Mock(is_file=lambda: item.get('receipt', False), exists=lambda: item.get('receipt', False)),
                  DATA_DIR=Path('unused'), SCHEDULE_JSON=schedule_path,
                  save_schedule_file=Mock(), sync_dashboard_status=Mock(), repair_failed_schedule_item=Mock(),
                  reconcile_item=Mock(return_value=False), run_publisher_for_item=Mock(return_value=False))
        exec(compile(module, 'production-today-cleaner', 'exec'), ns)
        return ns

    def item(self, name, status='waiting', **kw):
        return dict(domain=name, status=status, scheduledTime='00:00', order=1, **kw)

    def test_only_one_due_and_no_unknown_or_receipt(self):
        items = [self.item('processing', 'processing'), self.item('unknown', 'verification_pending'),
                 self.item('receipt', receipt=True), self.item('a'), self.item('b'),
                 self.item('started', 'failed', submissionStarted=True),
                 self.item('started-at', 'failed', submissionStartedAt='now'),
                 self.item('submitted-at', 'failed', submittedAt='now')]
        ns = self.setup_run(items)
        ns['catch_up_today_once']()
        ns['run_publisher_for_item'].assert_called_once()
        self.assertEqual(ns['run_publisher_for_item'].call_args.args[0]['domain'], 'a')
        self.assertEqual(items[0]['status'], 'processing')
        self.assertEqual(ns['save_schedule_file'].call_args.args[1]['eligibleCount'], 2)
        ns['reconcile_item'].assert_called_once_with(items[3], ns['load_or_get_schedule']()['date'], strict=True)

    def test_wrong_date_and_lock_stop(self):
        ns = self.setup_run([self.item('a')], '2000-01-01')
        with self.assertRaises(RuntimeError): ns['catch_up_today_once']()
        ns['run_publisher_for_item'].assert_not_called()
        ns = self.setup_run([self.item('a')], acquired=False)
        ns['catch_up_today_once']()
        ns['load_or_get_schedule'].assert_not_called()

    def test_public_duplicate_and_read_failure_never_submit(self):
        ns = self.setup_run([self.item('a')])
        ns['reconcile_item'].return_value = True
        ns['catch_up_today_once']()
        ns['run_publisher_for_item'].assert_not_called()
        ns['reconcile_item'].side_effect = RuntimeError('public check unavailable')
        with self.assertRaises(RuntimeError): ns['catch_up_today_once']()
        ns['run_publisher_for_item'].assert_not_called()
        self.assertIsNone(ns['save_schedule_file'].call_args.args[1]['activeJob'])

    def test_dashboard_reads_child_updated_schedule(self):
        ns = self.setup_run([self.item('a')])
        child = dict(ns['load_or_get_schedule'](), items=[self.item('a', 'published')])
        ns['run_publisher_for_item'].side_effect = lambda *a: setattr(ns['SCHEDULE_JSON'], 'read_text', lambda **kw: json.dumps(child))
        ns['catch_up_today_once']()
        self.assertEqual(ns['sync_dashboard_status'].call_args.args[0]['items'][0]['status'], 'published')

    def test_failed_or_timed_out_submission_is_never_retryable(self):
        ns = self.setup_run([])
        for fields in ({'receipt': True}, {'submissionStarted': True}, {'submissionStartedAt': 'now'}, {'submittedAt': 'now'}, {'status': 'publishing'}):
            item = dict(status='failed', nextRetryAt='later', **{k:v for k,v in fields.items() if k != 'status'})
            item.update(fields)
            self.assertTrue(ns['publication_may_be_inflight'](item))
            ns['schedule_failed_attempt'](item, -3)
            self.assertEqual(item['status'], 'verification_pending')
            self.assertFalse(item['retryable'])
            self.assertNotIn('nextRetryAt', item)

    def test_stopped_schedule_not_reset(self):
        ns = self.setup_run([self.item('a')])
        ns['load_or_get_schedule'].return_value['executionState'] = 'stopped'
        ns['catch_up_today_once']()
        ns['run_publisher_for_item'].assert_not_called()
        self.assertEqual(ns['load_or_get_schedule']()['executionState'], 'stopped')

if __name__ == '__main__':
    unittest.main()
