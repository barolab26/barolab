import unittest
from unittest.mock import AsyncMock, Mock
from common.flow_images import existing_project_page


class FlowProjectRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_reuses_saved_project_without_new_tab_or_submission(self):
        home = Mock(url='https://flow.google.com/', goto=AsyncMock())
        home.locator.return_value.wait_for = AsyncMock()
        context = Mock(pages=[home])
        target = 'https://flow.google.com/project/saved-project'
        self.assertIs(await existing_project_page(context, {'projectUrl': target}), home)
        home.goto.assert_awaited_once_with(target, wait_until='domcontentloaded', timeout=30000)
        context.new_page.assert_not_called()

    async def test_invalid_saved_target_and_user_project_are_preserved(self):
        home = Mock(url='https://flow.google.com/', goto=AsyncMock())
        other = Mock(url='https://flow.google.com/project/user-project')
        context = Mock(pages=[home, other])
        self.assertIsNone(await existing_project_page(context, {'projectUrl': 'https://other.test/project/x'}))
        home.goto.assert_not_awaited()
        other.goto.assert_not_called()
        self.assertIs(await existing_project_page(context, {}), other)

    async def test_first_existing_home_project_is_reused(self):
        home = Mock(url='https://flow.google.com/', goto=AsyncMock())
        links = home.locator.return_value
        links.count = AsyncMock(return_value=1)
        links.first.get_attribute = AsyncMock(return_value='/project/existing-id')
        links.wait_for = AsyncMock()
        self.assertIs(await existing_project_page(Mock(pages=[home]), {}), home)
        self.assertEqual(home.goto.call_args.args[0], 'https://flow.google.com/project/existing-id')
