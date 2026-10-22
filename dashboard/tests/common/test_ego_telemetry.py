import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import ego_telemetry as t


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        p = patch.object(t, 'DIRECTORY', self.directory); p.start(); self.addCleanup(p.stop)
        p = patch.dict(os.environ, {t.ENV_KEY:''}); p.start(); self.addCleanup(p.stop)

    def read(self):
        return json.loads(next(self.directory.glob('*.json')).read_text())

    def test_actual_action_start_finish_failure_and_bounded(self):
        with t.execution_context(task_id='staff:one', request_id='request', requester='jarvis', actor='publi'):
            with t.action('click', 'naver-toolbar'):
                self.assertEqual(self.read()['latest']['phase'], 'before')
            self.assertEqual(self.read()['latest']['phase'], 'after')
            self.assertEqual(self.read()['recent'][0]['actionId'],self.read()['recent'][1]['actionId'])
            with self.assertRaises(RuntimeError):
                with t.action('type', 'naver-body', 5): raise RuntimeError('private input')
            self.assertEqual(self.read()['latest']['phase'], 'failed')
            for _ in range(20):
                with t.action('click','naver-toolbar'): pass
        self.assertEqual(len(self.read()['recent']),16)
        self.assertNotIn('private input',str(self.read()))
        self.assertEqual(t.current_context()['requester'],'unknown')

    def test_bad_context_does_not_stop_operation_or_infer_queue(self):
        with t.execution_context(task_id='https://bad',request_id='r'):
            self.assertEqual(t.current_context()['source'],'direct')
            self.assertTrue(t.current_context()['taskId'].startswith('direct:'))

    def test_nested_operation_preserves_request_but_scopes_project(self):
        @t.observed_operation('threads','threads-scheduler')
        def operation(): return t.current_context()
        with t.execution_context(task_id='staff:parent',requester='jarvis',actor='publi',project='metrics'):
            value=operation()
            self.assertEqual(value['project'],'threads')
            self.assertEqual(value['taskId'],'staff:parent')
            self.assertEqual(value['requester'],'jarvis')
            self.assertEqual(t.current_context()['project'],'metrics')

    def test_export_preserves_environment_and_rejects_untrusted_shape(self):
        with t.execution_context(task_id='staff:two',request_id='r',requester='jarvis'):
            env=t.export_environment({'DISPLAY':':10'})
        self.assertEqual(env['DISPLAY'],':10')
        with patch.dict(os.environ,env): self.assertEqual(t.current_context()['taskId'],'staff:two')
        with patch.dict(os.environ,{t.ENV_KEY:'{"taskId":"https://private/?token=x"}'}):
            self.assertEqual(t.current_context()['requester'],'unknown')

    def test_async_context_isolation(self):
        async def one(key):
            with t.execution_context(task_id=key):
                async with t.async_action('click','kin-editor'):
                    await asyncio.sleep(0)
                    self.assertEqual(t.current_context()['taskId'],key)
        async def run(): await asyncio.gather(one('a'),one('b'))
        asyncio.run(run())
        self.assertEqual(len(list(self.directory.glob('*.json'))),2)

    def test_observation_failure_never_changes_operation(self):
        with patch.object(t,'DIRECTORY',self.directory/'missing'/'file'),patch.object(Path,'mkdir',side_effect=OSError('secret')):
            with t.action('click','naver-toolbar'): result=4
        self.assertEqual(result,4)

    def test_dynamic_target_is_not_written(self):
        with t.action('type','https://private/?token=abc',4): pass
        self.assertEqual(list(self.directory.iterdir()),[])

    def test_registered_subprocess_inherits_context_not_extra_command(self):
        from server.agent_tools import _ego_popen
        with t.execution_context(task_id='staff:child',requester='jarvis',actor='patch',source='staff_queue'):
            with patch('server.agent_tools.subprocess.Popen') as spawn:
                spawn.return_value.pid=99999999
                spawn.return_value.wait.return_value=0
                _ego_popen(['python','safe.py'],env={'DISPLAY':':10'})
        self.assertEqual(spawn.call_args.args, (['python','safe.py'],))
        env=spawn.call_args.kwargs['env']
        self.assertEqual(env['DISPLAY'],':10')
        self.assertEqual(json.loads(env[t.ENV_KEY])['taskId'],'staff:child')

    def test_direct_tool_keeps_result_and_unknown_requester(self):
        from server.agent_tools import execute_agent_tool
        with patch('server.agent_tools._execute_agent_tool',return_value={'ok':True,'status':'observed'}) as tool:
            result=execute_agent_tool('patch','read_agent_status')
        tool.assert_called_once_with('patch','read_agent_status')
        self.assertEqual(result,{'ok':True,'status':'observed'})
        self.assertEqual(self.read()['context']['requester'],'unknown')
        self.assertEqual(self.read()['context']['actor'],'patch')
