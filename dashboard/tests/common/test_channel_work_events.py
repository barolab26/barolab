import unittest
import sqlite3
from unittest.mock import patch

from naver_kin import posting as kin
from threads_posting import posting as threads


class ChannelWorkEvents(unittest.TestCase):
    @patch('threads_posting.posting._threads_pipeline__emit_crew_state')
    def test_rollback_does_not_announce_uncommitted_state(self, emit):
        db = sqlite3.connect(':memory:', isolation_level=None)
        self.addCleanup(db.close)
        db.row_factory = sqlite3.Row
        db.executescript('CREATE TABLE parts(part_id,state,reason,updated_at);'
                        'CREATE TABLE events(part_id,state,at,reason);'
                        "INSERT INTO parts VALUES('part1','queued',NULL,NULL);")
        db.execute('BEGIN')
        threads._threads_pipeline__update(db, 'part1', 'submitted_unknown')
        db.rollback()
        emit.assert_not_called()
        self.assertEqual(db.execute('SELECT state FROM parts').fetchone()[0], 'queued')
        threads._threads_pipeline__update(db, 'part1', 'api_submitted')
        emit.assert_called_once_with('part1', 'api_submitted')

    @patch('common.crew_chat_bridge.emit_work_event')
    def test_kin_unverified_is_not_completed(self, emit):
        kin._naver_pipeline__emit_crew_state('123', 'submitted_unverified')
        self.assertEqual(emit.call_args.kwargs['phase'], 'progress')
        self.assertEqual(emit.call_args.kwargs['task_id'], 'kin:123')
        kin._naver_pipeline__emit_crew_state('123', 'published_verified')
        self.assertEqual(emit.call_args.kwargs['phase'], 'completed')

    @patch('common.crew_chat_bridge.emit_work_event')
    def test_threads_unknown_and_api_submission_are_not_public(self, emit):
        threads._threads_pipeline__emit_crew_state('part1', 'submitted_unknown')
        self.assertEqual(emit.call_args.kwargs['phase'], 'failed')
        threads._threads_pipeline__emit_crew_state('part1', 'api_submitted')
        self.assertEqual(emit.call_args.kwargs['phase'], 'progress')
        threads._threads_pipeline__emit_crew_state('part1', 'published_verified')
        self.assertEqual(emit.call_args.kwargs['phase'], 'completed')

    @patch('common.crew_chat_bridge.emit_work_event', side_effect=RuntimeError('offline'))
    def test_chat_failure_does_not_change_send_control(self, emit):
        kin._naver_pipeline__emit_crew_state('123', 'publishing')
        threads._threads_pipeline__emit_crew_state('part1', 'sending_intent')
        self.assertEqual(emit.call_count, 2)
