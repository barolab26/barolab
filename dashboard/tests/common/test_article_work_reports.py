"""Exact article links and truthful progress, without touching remote content."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import content_maintenance as maintenance


class ArticleWorkReportTests(unittest.TestCase):
    def test_reports_exact_article_once_per_stage_and_only_verifies_at_end(self):
        job = {'id': 'a' * 32, 'domain': 'example.com', 'url': 'https://www.example.com/the-actual-article'}
        reply = {'reply': '@팀장 대상 글의 수정안을 작성 중입니다.', 'route': {'events': [{'actualModel': 'observed-model'}]}}
        with tempfile.TemporaryDirectory() as folder, patch.object(maintenance, 'BACKUPS', Path(folder)), patch('agents.agent_tools.staff_tool_reply', return_value=reply) as model, patch('common.crew_chat_bridge.emit_work_event', return_value='observed-event') as event:
            for stage in ('prepare', 'apply', 'verified'):
                maintenance.report_article_work(job, {'title': '실제 대상 제목'}, stage)
                facts = model.call_args.args[3]
                self.assertEqual(facts['title'], '실제 대상 제목')
                self.assertEqual(facts['url'], job['url'])
                self.assertEqual(facts['publicVerified'], stage == 'verified')
                self.assertEqual(event.call_args.kwargs['deliverable_url'], job['url'])
                self.assertEqual(event.call_args.kwargs['message_kind'], 'staff_reply')
                self.assertEqual(event.call_args.kwargs['deliverable_label'], '실제 대상 제목')
                maintenance.report_article_work(job, {'title': '실제 대상 제목'}, stage)
            self.assertEqual(model.call_count, 3)
            self.assertEqual(event.call_count, 3)

    def test_bad_identity_or_chat_failure_does_not_block_article_work(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(maintenance, 'BACKUPS', Path(folder)), patch('agents.agent_tools.staff_tool_reply', side_effect=RuntimeError('unavailable')) as model:
            job = {'id': 'a' * 32, 'domain': 'example.com', 'url': 'https://other.example/article'}
            self.assertIsNone(maintenance.report_article_work(job, {'title': '실제 제목'}, 'prepare'))
            model.assert_not_called()
            job['url'] = 'https://example.com/article'
            self.assertIsNone(maintenance.report_article_work(job, {'title': '실제 제목'}, 'prepare'))
