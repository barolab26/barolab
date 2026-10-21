"""Patch role receipts are reported without running tools or claiming production repair."""
import ast
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import unittest


class PatchChatTests(unittest.TestCase):
    def setUp(self):
        source=(Path(__file__).parent/'chat_room.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('coding_job_report','synthesize_agent_reply','normalize_staff_calls')]
        self.scope=dict(re=re,Any=Any,Dict=Dict,List=List,Optional=Optional,Tuple=Tuple)
        self.scope['_extract_mentioned_slugs']=lambda text:['patch'] if '@patch' in text or '@패치' in text else []
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<patch-chat>','exec'),self.scope)

    def test_staff_requests_are_marked_without_rewriting_reports_or_code(self):
        normalize=self.scope['normalize_staff_calls']
        self.assertEqual(normalize('패치, 오류를 확인해 주세요.\n퍼블리에게 결과 확인을 부탁합니다.'),
                         '@패치, 오류를 확인해 주세요.\n@퍼블리에게 결과 확인을 부탁합니다.')
        text='@패치, 확인해주세요. 패치가 검토했습니다.\n`패치 확인해주세요`\n```\npatch 확인해주세요\n```\nhttps://host/patch\n[패치 확인해주세요](https://host)'
        self.assertEqual(normalize(text),text)
        self.assertEqual(normalize('패치가 수정했습니다. 레이더의 결과입니다.'),'패치가 수정했습니다. 레이더의 결과입니다.')
        self.assertEqual(normalize('패치 결과를 확인해주세요.'),'패치 결과를 확인해주세요.')
        self.assertEqual(normalize(normalize('patch: 검토해주세요.')),'@patch: 검토해주세요.')
        self.assertEqual(normalize('패치, 이 코드 수정해줘.\n퍼블리, 작업을 재개하라.\n닥터, 확인해 줘.\n레이더, 조사를 바랍니다.'),
                         '@패치, 이 코드 수정해줘.\n@퍼블리, 작업을 재개하라.\n@닥터, 확인해 줘.\n@레이더, 조사를 바랍니다.')

    def test_receipt_scopes_do_not_claim_production_repair(self):
        report=self.scope['coding_job_report']
        self.assertIn('아직 하지 않았습니다',report({'status':'proposed','productionApplied':False,'testsRun':False}))
        self.assertIn('운영 코드에는 적용하지 않았',report({'status':'isolated_verified','productionApplied':False,'testsRun':True}))
        self.assertIn('실패',report({'status':'validation_failed'}))
        self.assertIn('시작하지 않았',report({'status':'needs_input'}))
        self.assertIn('지원 범위를 벗어난',report({'status':'isolated_verified','productionApplied':True}))
        result=report({'status':'proposed','jobDir':'/private/root/'+'b'*32,'candidateSha256':'a'*64})
        self.assertIn('job:'+'b'*32+' sha:'+'a'*64,result)
        self.assertNotIn('/private',result)
        self.assertNotIn('작업 ID:',report({'status':'proposed','jobId':'<unsafe>'}))

    def test_code_receipt_short_circuits_model_and_generic_status(self):
        result={'tool':'propose_coding_job','status':'proposed','candidateSha256':'a'*64,'productionApplied':False,'testsRun':False}
        self.scope['maybe_execute_tools_for_message']=lambda *args:[result]
        # Other dependencies are intentionally absent: no status/model or URL
        # fallback may run after a real coding job receipt.
        text,artifacts,tools=self.scope['synthesize_agent_reply']('patch','@patch 코드 수정',[],{})
        self.assertIn('a'*64,text)
        self.assertEqual(artifacts,[])
        self.assertEqual(tools,[result])
        text,artifacts,tools=self.scope['synthesize_agent_reply']('patch','@patch 코드 수정',[],{},
            is_followup=True,prior_replies=[{'executionBadges':['unrelated tool']}])
        self.assertEqual(tools,[result])
