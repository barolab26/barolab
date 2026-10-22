"""Employee reasoning preferences: isolated config, mocked providers and CLI."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from common import codex_cli, llm_client, llm_settings as settings


class AgentReasoningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'active': 'codex', 'providers': {'codex': {'model': 'fixture-model'}},
            'agentBrains': {'patch': {'provider': 'codex', 'model': 'fixture-model', 'reasoningEffort': 'high'}}}
        self.path = self.root / 'settings.json'
        self.path.write_text(json.dumps(self.config))
        self.catalog = [{'id': 'fixture-model', 'label': 'Fixture', 'reasoningEfforts': ['low', 'high', 'xhigh']}]
        for item in (patch.object(settings, 'CONFIG', self.path),
                     patch.object(codex_cli, 'model_catalog', return_value=self.catalog),
                     patch.object(codex_cli, 'runtime', return_value={'models': self.catalog}),
                     patch('common.crew_chat_bridge.emit_work_event', return_value='event')):
            item.start(); self.addCleanup(item.stop)

    def test_save_public_reload_preserve_explicit_and_default(self):
        saved = settings.save_agent_brains({'agentBrains': {'patch': {
            'provider': 'codex', 'model': 'fixture-model', 'reasoningEffort': 'xhigh'}}})
        self.assertEqual(saved['agentBrains']['patch']['reasoningEffort'], 'xhigh')
        settings.save_agent_brains({'agentBrains': {'patch': {'provider': 'codex', 'model': 'fixture-model'}}})
        self.assertEqual(settings.get_agent_brain('patch')['reasoningEffort'], 'xhigh')
        settings.save({'provider': 'codex', 'model': 'fixture-model', 'agentBrains': {'patch': {
            'provider': 'codex', 'model': 'fixture-model', 'reasoningEffort': None}}})
        self.assertIsNone(settings.get_agent_brain('patch')['reasoningEffort'])

    def test_unsupported_effort_or_provider_does_not_write(self):
        original = self.path.read_bytes()
        for provider, effort in [('codex', 'ultra'), ('codex', 'invalid'), ('openai', 'high')]:
            with self.subTest(provider=provider, effort=effort), self.assertRaises(settings.SettingsError):
                settings.save_agent_brains({'agentBrains': {'patch': {'provider': provider,
                    'model': 'fixture-model', 'reasoningEffort': effort}}})
            self.assertEqual(self.path.read_bytes(), original)

    def test_employee_context_and_slot_reach_adapter_without_leaking(self):
        with patch.object(llm_client, '_generate_json', return_value=({'ok': True}, 'fixture-model')) as call:
            llm_client.generate_json('task', provider='codex', model_override='fixture-model',
                crew_actor='patch', _skip_memory=True)
            self.assertEqual(call.call_args.args[6], 'high')
            llm_client.generate_json('task', agent_slot='patch', _skip_memory=True)
            self.assertEqual(call.call_args.args[6], 'high')
            llm_client.generate_json('task', provider='codex', model_override='fixture-model',
                reasoning_effort='low', crew_actor='patch', _skip_memory=True)
            self.assertEqual(call.call_args.args[6], 'low')
            llm_client.generate_json('task', provider='codex', model_override='other-model',
                crew_actor='patch', _skip_memory=True)
            self.assertIsNone(call.call_args.args[6])
            llm_client.generate_json('task', provider='codex', model_override='fixture-model', _skip_memory=True)
            self.assertIsNone(call.call_args.args[6])

    def test_exact_selected_effort_reaches_cli_without_lowering_or_model_switch(self):
        home = self.root / 'codex'; home.mkdir()
        (home / 'models_cache.json').write_text(json.dumps({'models': [{'slug': 'fixture-model',
            'supported_reasoning_levels': [{'effort': 'high'}]}]}))
        cli_config = {'home': str(home), 'executable': 'mock-codex'}
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            output = Path(command[command.index('--output-last-message') + 1])
            output.write_text('{"json":"{\\"ok\\":true}"}')
            return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', '')
        with patch.object(codex_cli, 'local_config', return_value=cli_config), \
                patch.object(codex_cli, 'is_wsl', return_value=False), \
                patch.object(Path, 'home', return_value=self.root), \
                patch.object(codex_cli, '_fallback_candidates', side_effect=AssertionError('must honor choice')), \
                patch.object(codex_cli.subprocess, 'run', side_effect=run):
            result, _ = codex_cli.generate_local('task', 'fixture-model', reasoning_effort='high', _skip_memory=True)
        self.assertEqual(result, {'ok': True})
        self.assertIn('model_reasoning_effort="high"', commands[0])
        self.assertEqual(len(commands), 1)


if __name__ == '__main__':
    unittest.main()
