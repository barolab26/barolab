import ast
import asyncio
import time
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Compile the production helpers without importing live pipeline clients.
source = Path(__file__).with_name('pipeline_runner.py').read_text(encoding='utf-8')
names = {'ensure_flow_single_output', 'wait_flow_submit_ready', 'submit_flow_once', 'require_flow_reentry_safe'}
module = ast.Module(body=[node for node in ast.parse(source).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names], type_ignores=[])
namespace = {'asyncio': asyncio, 'time': time, 're': re, 'stamp': lambda: 'observed-now'}
exec(compile(module, 'flow-production-helpers', 'exec'), namespace)

class FlowReadinessTests(unittest.IsolatedAsyncioTestCase):
    def page(self, texts, enabled=True):
        class Locator:
            first = None
        editor = Locator()
        editor.inner_text = AsyncMock(side_effect=texts)
        button = Locator()
        button.first = button
        button.count = AsyncMock(return_value=1)
        button.is_visible = AsyncMock(return_value=True)
        button.is_enabled = AsyncMock(return_value=enabled)
        button.bounding_box = AsyncMock(return_value=dict(x=1,y=2,width=3,height=4))
        page = Locator()
        page.locator = lambda selector: editor if selector == 'div.ProseMirror' else button
        return page, button

    async def test_delayed_enabled_exact_prompt_then_single_submission(self):
        page, button = self.page(['prompt', 'prompt', ''])
        button.is_enabled.side_effect = [False, True]
        row, saves = {'outputCount':1}, []
        persist = lambda: saves.append(dict(row))
        client = type('Client', (), {'send': AsyncMock()})()
        with patch.object(asyncio, 'sleep', AsyncMock()):
            ready = await namespace['wait_flow_submit_ready'](page, 'prompt', row, persist)
            await namespace['submit_flow_once'](page, client, ready, row, persist)
        self.assertEqual([c.args[1]['type'] for c in client.send.call_args_list], ['mousePressed', 'mouseReleased'])
        self.assertEqual(saves[-2]['status'], 'submission_started')
        self.assertEqual(row['status'], 'submitted')

    async def test_timeout_or_observation_error_never_submits(self):
        for texts, enabled in [(['wrong'], True), (['prompt'], False), ([RuntimeError('observation')], True)]:
            page, button = self.page(texts, enabled)
            client = type('Client', (), {'send': AsyncMock()})()
            with self.assertRaises(RuntimeError):
                ready = await namespace['wait_flow_submit_ready'](page, 'prompt', {}, lambda: None, timeout=0)
                await namespace['submit_flow_once'](page, client, ready, {}, lambda: None)
            client.send.assert_not_awaited()

    async def test_uncertain_ack_has_no_second_click_and_blocks_reentry(self):
        page, button = self.page(['prompt'] * 18)
        row = {'filename': 'one.jpg', 'outputCount':1}
        client = type('Client', (), {'send': AsyncMock()})()
        with patch.object(asyncio, 'sleep', AsyncMock()), self.assertRaises(RuntimeError):
            await namespace['submit_flow_once'](page, client, button, row, lambda: None)
        self.assertEqual(client.send.await_count, 2)
        self.assertEqual(row['status'], 'unconfirmed')
        with self.assertRaises(RuntimeError):
            namespace['require_flow_reentry_safe']([row], ['one.jpg'])

    async def test_single_output_changes_only_scoped_image_radio_and_confirms(self):
        class Locator:
            def filter(self, **kwargs):
                self.filter_args=kwargs;return self
        radios={count:Locator() for count in (1,2,3,4)}
        state={1:'false',2:'true',3:'false',4:'false'}
        for count,radio in radios.items():
            radio.count=AsyncMock(return_value=1)
            radio.get_attribute=AsyncMock(side_effect=lambda key,c=count:state[c])
        async def select_one(**kwargs):state.update({1:'true',2:'false',3:'false',4:'false'})
        radios[1].click=AsyncMock(side_effect=select_one)
        section=Locator();section.count=AsyncMock(return_value=1);section.is_visible=AsyncMock(return_value=False);section.wait_for=AsyncMock()
        calls=[]
        def get_radio(role,name,exact):
            calls.append((role,name,exact));return radios[int(name[1:])]
        section.get_by_role=get_radio
        settings=Locator();settings.count=AsyncMock(return_value=1);settings.click=AsyncMock()
        page=Locator();page.locator=lambda selector:section if selector=='.settings-section' else settings
        page.keyboard=Locator();page.keyboard.press=AsyncMock()
        self.assertEqual(await namespace['ensure_flow_single_output'](page),1)
        self.assertEqual(section.filter_args,{'has_text':'이미지 생성 기본값'})
        self.assertTrue(all(role=='radio' and exact for role,name,exact in calls))
        radios[1].click.assert_awaited_once();page.keyboard.press.assert_awaited_once_with('Escape')
        radios[1].click.reset_mock()
        self.assertEqual(await namespace['ensure_flow_single_output'](page),1)
        radios[1].click.assert_not_awaited()
        state[2]='true'
        with patch.object(asyncio,'sleep',AsyncMock()),self.assertRaises(RuntimeError):
            await namespace['ensure_flow_single_output'](page)

    async def test_missing_single_output_proof_prevents_any_submit(self):
        page,button=self.page(['prompt'])
        client=type('Client',(),{'send':AsyncMock()})()
        with self.assertRaises(RuntimeError):await namespace['submit_flow_once'](page,client,button,{},lambda:None)
        client.send.assert_not_awaited();button.bounding_box.assert_not_awaited()

    async def test_completed_or_inflight_cannot_repeat_but_missing_plan_can(self):
        for status in ('submission_started', 'submitted', 'unconfirmed', 'downloaded'):
            row = {'filename': 'one.jpg', 'status': status}
            with self.assertRaises(RuntimeError):
                namespace['require_flow_reentry_safe']([row], ['one.jpg'])
            namespace['require_flow_reentry_safe']([row], ['two.jpg'])
        namespace['require_flow_reentry_safe']([{'filename':'two.jpg','status':'prepared'}], ['two.jpg'])

if __name__ == '__main__':
    unittest.main()
