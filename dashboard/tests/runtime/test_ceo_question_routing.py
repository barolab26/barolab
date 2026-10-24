import ast
import hashlib
import json
import re
import types
from pathlib import Path
from typing import Optional, List, Dict, Any
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[3]


def functions(*names, **scope):
    tree=ast.parse((ROOT/'dashboard/agents/chat_room.py').read_text())
    scope.update(Optional=Optional,List=List,Dict=Dict,Any=Any,re=re,json=json,hashlib=hashlib)
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<chat>','exec'),scope)
    return scope


def test_kin_question_fallback_does_not_answer_with_cf_totals(tmp_path):
    p=tmp_path/'dashboard/data/kin-automation-state.json';p.parent.mkdir(parents=True)
    p.write_text(json.dumps({'reason':'minimum_interval_not_elapsed','operationCounts':{'adinfo0905':30,'stone0747':30},'submissionCounts':{'adinfo0905':0,'stone0747':0}}))
    scope=functions('_question_project_context','_synthesize_question_aware_fallback',BASE_DIR=tmp_path)
    rows=[{'id':'cf_blog','title':'CF 블로그','status':'attention'}, {'id':'naver_kin','title':'네이버 지식iN','activity':{'reason':'daily_limit_or_account_unavailable'}}]
    with patch('server.project_health.observed_projects',return_value=rows):
        reply=scope['_synthesize_question_aware_fallback']('jarvis','지식인 답변작업 왜 안하냐고?',[],[])
    assert '지식iN' in reply and 'daily_limit_or_account_unavailable' in reply
    assert 'operationCounts' in reply and 'submissionCounts' in reply
    assert 'CF 블로그' not in reply
    assert '완료하지 못했습니다' in reply
    assert '실행된 작업은 없습니다' in reply


def test_cycle_actions_require_explicit_execution_authorization():
    scope=functions('_call_chat_llm');enqueue=Mock(return_value={'status':'queued','taskId':'task','requestId':'turn'})
    tools=types.ModuleType('agent_tools');tools.enqueue_staff_request=enqueue
    response={'reply':'스레드 실행을 퍼블리에게 배정합니다.','actions':[{'agent':'publi','tool':'run_project_cycle','domain':'','project':'threads','work_id':''}]}
    with patch.dict('sys.modules',{'agent_tools':tools}), patch('common.llm_client.generate_json',return_value=response):
        assert scope['_call_chat_llm']('system','스레드 실행해',agent_slug='jarvis',staff_request_id='turn',allow_project_cycle=True)
        enqueue.assert_called_once_with('turn',[{'agent':'publi','tool':'run_project_cycle','args':{'project':'threads'}}])
        enqueue.reset_mock()
        assert scope['_call_chat_llm']('system','왜 멈췄어?',agent_slug='jarvis',staff_request_id='question') is None
        enqueue.assert_not_called()


def test_terminal_result_is_reviewed_for_original_ceo_question_once(tmp_path):
    from unittest.mock import patch
    data=tmp_path/'data';(data/'chats').mkdir(parents=True)
    (data/'chats/room-main.json').write_text(json.dumps({'messages':[{'id':'msg-123-user','who':'user','text':'지식인 작업 실행해'}]}))
    tree=ast.parse((ROOT/'dashboard/agents/agent_tools.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_review_ceo_request')
    reply=Mock(return_value={'reply':'대표님, 지식iN은 오늘 작업 시도 한도로 대기 중입니다. 제출 성공은 확인되지 않았습니다.','route':{'events':[{'actualModel':'actual'}]}})
    scope={'re':re,'DATA_DIR':data,'staff_tool_reply':reply}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<review>','exec'),scope)
    row={'requestId':'msg-123-user:jarvis','taskId':'staff:'+'a'*64,'status':'completed','results':[{'agent':'publi','tool':'run_project_cycle','result':{'ok':True,'status':'no_work','publicationVerified':False,'eligibility':{'reason':'daily_limit_or_account_unavailable'}}}]}
    with patch('common.crew_chat_bridge.emit_work_event',return_value='review-event') as emit:
        scope['_review_ceo_request'](tmp_path/'request.json',row)
        scope['_review_ceo_request'](tmp_path/'request.json',row)
    reply.assert_called_once();emit.assert_called_once()
    assert reply.call_args.args[2]['originalQuestion']=='지식인 작업 실행해'
    assert reply.call_args.args[3]['terminalResults'][0]['result']['publicationVerified'] is False
    assert row['ceoReview']['userTurnId']=='msg-123-user'
    assert row['ceoReview']['eventId']=='review-event'


def test_agy_reply_envelope_keeps_structured_actions_and_original_text():
    import subprocess
    from common import agy_cli
    inner={'reply':'지식iN은 오늘 시도 한도로 대기 중입니다.','actions':[]}
    payload=[{'event':'init','init':{'model':'gemini-4-argon-high'}},{'event':'result','result':{'status':'SUCCESS','structured_output':{'reply':json.dumps(inner,ensure_ascii=False),'actions':[]}}}]
    schema={'type':'object','properties':{'reply':{'type':'string'},'actions':{'type':'array'}},'required':['reply','actions']}
    with patch('common.llm_settings.resolve_agy_executable',return_value='/native/agy'), \
         patch.object(agy_cli.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'\n'.join(json.dumps(p) for p in payload),'')), \
         patch('common.llm_client.record_provider_memory_delivery'):
        result,_=agy_cli.generate('test','gemini-4-argon-high',response_schema=schema)
    assert result==inner


def test_ceo_review_event_binds_only_its_original_question(tmp_path):
    import pytest
    chats=tmp_path/'chats';(chats/'staff-requests').mkdir(parents=True)
    task='staff:'+'a'*64;reply='대표님, 지식iN은 실행 시도 한도로 대기 중입니다.'
    row={'taskId':task,'requestId':'msg-123-user:jarvis','ceoReview':{'userTurnId':'msg-123-user','reply':reply}}
    (chats/'staff-requests'/('a'*64+'.json')).write_text(json.dumps(row))
    scope=functions('project_work_event',CHATS_DIR=chats)
    event='crew-'+'b'*32
    payload={'id':event,'eventId':event,'eventType':'crew_work_event','who':'jarvis','taskId':task,'phase':'completed','stage':'ceo-result-review','outputKind':reply,'messageKind':'staff_reply','model':'actual','ts':123}
    projected=scope['project_work_event'](payload)
    assert projected['replyToCeo'] is True and projected['userTurnId']=='msg-123-user'
    with pytest.raises(ValueError):scope['project_work_event']({**payload,'outputKind':'다른 요청의 답변입니다.'})


def test_interval_kin_channel_is_not_reported_as_unscheduled():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from server.project_health import publication_quota
    quota=publication_quota('naver_kin',{},datetime.now(ZoneInfo('Asia/Seoul')),True)
    assert quota['status']=='interval_managed'
    assert quota['verified'] is None


def test_asking_why_execution_stopped_does_not_authorize_a_publication_cycle():
    scope=functions('_project_cycle_requested')
    for text in ('왜 실행을 안 해?', '스레드 실행 상태가 왜 이래?', '스레드 실행하지 마'):
        assert not scope['_project_cycle_requested'](text)
    for text in ('지식인 작업 실행해줘', '스레드 다시 진행해', 'CF 발행해'):
        assert scope['_project_cycle_requested'](text)
    from server.agent_tools import has_imperative_action_intent
    assert not has_imperative_action_intent('지식인 실행을 왜 안하냐고?')
    assert has_imperative_action_intent('원인 확인하고 지식인 실행해줘')
