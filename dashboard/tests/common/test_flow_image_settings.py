import unittest
from unittest.mock import AsyncMock,Mock
from common.flow_images import open_generation_settings


class FlowImageSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_korean_prompt_settings_are_used_instead_of_global_settings(self):
        scoped=Mock(count=AsyncMock(return_value=1),click=AsyncMock())
        page=Mock();page.locator.return_value.get_by_role.return_value=scoped
        await open_generation_settings(page)
        names=page.locator.return_value.get_by_role.call_args.kwargs['name']
        self.assertIsNotNone(names.fullmatch('설정'))
        self.assertIsNotNone(names.fullmatch('Settings'))
        scoped.click.assert_awaited_once_with(timeout=5000)
        page.get_by_role.assert_not_called()

    async def test_legacy_unique_settings_button_is_supported(self):
        scoped=Mock(count=AsyncMock(return_value=0))
        legacy=Mock(count=AsyncMock(return_value=1),click=AsyncMock())
        page=Mock();page.locator.return_value.get_by_role.return_value=scoped;page.get_by_role.return_value=legacy
        await open_generation_settings(page)
        legacy.click.assert_awaited_once_with(timeout=5000)

    async def test_ambiguous_global_controls_are_not_clicked(self):
        scoped=Mock(count=AsyncMock(return_value=0))
        global_controls=Mock(count=AsyncMock(return_value=2),click=AsyncMock())
        page=Mock();page.locator.return_value.get_by_role.return_value=scoped;page.get_by_role.return_value=global_controls
        with self.assertRaisesRegex(RuntimeError,'ambiguous'):
            await open_generation_settings(page)
        global_controls.click.assert_not_called()
