import json
import subprocess
import unittest
from datetime import datetime
from unittest.mock import patch,Mock
from common import agy_cli, llm_settings as settings, llm_client, crew_chat_bridge as bridge
from server import cockpit_panels, mission_control


class ModelIdentityTests(unittest.TestCase):
    def test_codex_badge_has_effective_effort_and_gemini_keeps_level(self):
        c={'agentBrains':{'publi':{'provider':'codex','model':'gpt-6.1-sol','reasoningEffort':'high'}}}
        self.assertEqual(settings.get_agent_brain('publi',c)['badge'],'gpt-6.1-sol · High')
        self.assertEqual(settings.format_brain_badge('codex','gpt-6.1-sol'),'gpt-6.1-sol · Low')
        self.assertEqual(settings.format_brain_badge('agy','gemini-3.8-flash-medium'),'3.8 Flash Med')

    def test_native_agy_checks_actual_model_and_schema_without_tools(self):
        payload=[{'event':'init','init':{'model':'gemini-4-argon-high'}},{'event':'result','result':{'status':'SUCCESS','structured_output':{'ok':True},'usage':{'input_tokens':4,'output_tokens':2}}}]
        with patch('common.llm_settings.resolve_agy_executable',return_value='/native/agy'), \
             patch.object(agy_cli.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'\n'.join(json.dumps(p) for p in payload),'')) as run, \
             patch('common.llm_client.record_provider_memory_delivery'):
            self.assertEqual(agy_cli.generate('private task','gemini-4-argon-high',response_schema={'type':'object'}),({'ok':True},'gemini-4-argon-high'))
            args=run.call_args.args[0]
            self.assertNotIn('private task',args)
            self.assertIn('stream-json',args)
            self.assertNotIn('--dangerously-skip-permissions',args)
            payload[0]['init']['model']='different-model'
            run.return_value.stdout='\n'.join(json.dumps(p) for p in payload)
            with self.assertRaises(RuntimeError):agy_cli.generate('task','gemini-4-argon-high')

    def test_call_event_and_later_staff_reply_keep_actual_effort_not_current_config(self):
        @bridge.model_crew_call
        def model(prompt,**kwargs):
            bridge.record_model_route('codex','actual-model','high')
            return {'ok':True}
        with patch.object(bridge,'_deliver') as deliver:
            model('task',crew_actor='patch',crew_task_id='fixture')
            event=deliver.call_args.args[0]
            self.assertEqual((event['model'],event['reasoningEffort'],event['modelBadge']),('actual-model','high','actual-model · High'))
            bridge.emit_work_event(actor='patch',actor_label='패치',task_id='fixture',phase='completed',model='actual-model')
            self.assertEqual(deliver.call_args.args[0]['reasoningEffort'],'high')
            bridge.emit_work_event(actor='patch',actor_label='패치',task_id='other-task',phase='completed',model='actual-model')
            self.assertEqual(deliver.call_args.args[0]['reasoningEffort'],'')

    def test_current_cockpit_mapping_shows_effort(self):
        now=datetime.now(cockpit_panels.KST)
        brains={'patch':{'provider':'codex','model':'gpt-6.1-sol','badge':'gpt-6.1-sol · High'}}
        rows=mission_control.crew_rows([],[],brains,now)
        self.assertEqual(next(r for r in rows if r['role']=='patch')['configuredModel'],'gpt-6.1-sol · High')
        display=cockpit_panels.brain_display({'agentBrains':brains},now)
        self.assertIn('gpt-6.1-sol · High',next(row for row in display['rows'] if row.startswith('[직원 매핑]')))

    def test_javascript_badges_show_effort_and_never_relabel_historical_model(self):
        from pathlib import Path
        settings_js=(Path(__file__).resolve().parents[2]/'llm-settings.js').read_text()
        source=settings_js[settings_js.index('function formatBrainBadge('):settings_js.index('function badgeClassFor(')]
        chat=(Path(__file__).resolve().parents[2]/'chat.html').read_text()
        start=chat.index('  function getAgentBrainBadge(')
        source+='\nconst agentBrainBadgeMap=new Map([["jarvis","Argon High"]]);\n'+chat[start:chat.index('  function crewConversationText',start)]
        source+='\nconst assert=require("node:assert/strict");\nassert.equal(formatBrainBadge("codex","gpt-6.1-sol","high"),"gpt-6.1-sol · High");\nassert.equal(formatBrainBadge("codex","gpt-6.1-sol"),"gpt-6.1-sol · Low");\nassert.equal(getAgentBrainBadge({who:"jarvis",brain:{badge:"gpt-6.1-sol"}}),"gpt-6.1-sol · 추론 미기록");\nassert.equal(getAgentBrainBadge({who:"jarvis",brain:{badge:"gpt-6.1-sol · High"}}),"gpt-6.1-sol · High");'
        result=subprocess.run(['node','-e',source],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_korean_staff_sentence_without_ascii_period_keeps_original_text(self):
        from server import agent_tools
        text='@팀장 조회 수집은 부분 완료 상태입니다. 미수집 원천을 확인하겠습니다'
        def response(*args,**kwargs):
            kwargs['observer']('agy','gemini-3.8-flash-medium','returned',actual_model='gemini-3.8-flash-medium')
            return {'reply':text}
        with patch('common.llm_client.generate_json',side_effect=response), \
             patch('common.llm_settings.get_agent_brain',return_value={'provider':'agy','model':'gemini-3.8-flash-medium'}):
            actual=agent_tools.staff_tool_reply('trace','fixture',{'tool':'read_agent_status'},{'status':'observed'})
        self.assertEqual(actual['reply'],text)


def test_missing_effort_uses_only_explicit_role_defaults():
    from common.llm_settings import ensure_agent_brains
    config={'agentBrains':{'patch':{'provider':'codex','model':'gpt-6.1-sol','reasoningEffort':None},'publi':{'provider':'codex','model':'gpt-6.1-sol'},'threads_pipeline':{'provider':'codex','model':'gpt-6.1-sol'}}}
    brains=ensure_agent_brains(config)
    assert brains['patch']['reasoningEffort']=='high' and brains['publi']['reasoningEffort']=='medium'
    assert brains['threads_pipeline']['reasoningEffort'] is None
    assert brains['patch']['badge'].endswith('High')
    config['agentBrains']['publi']['reasoningEffort']='high'
    assert ensure_agent_brains(config)['publi']['reasoningEffort']=='high'
