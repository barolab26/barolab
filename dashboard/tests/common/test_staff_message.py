import json
import subprocess
from pathlib import Path
from common.staff_message import display_message


def test_only_message_envelopes_are_unwrapped_in_emitter_and_existing_chat_display():
    text='이번 안건의 가독성과 실제 연결을 검증합니다.'
    cases=[(text,text),(json.dumps({'message':text}),text),
           (json.dumps({'message':json.dumps({'message':text})}),text),
           ('```json\n'+json.dumps({'message':text})+'\n```',text),
           ('{"message": "unfinished', '{"message": "unfinished'),
           ('{"message":"유지","status":"failed"}','{"message":"유지","status":"failed"}')]
    for value,expected in cases:assert display_message(value)==expected
    html=(Path(__file__).resolve().parents[2]/'chat.html').read_text()
    source=html[html.index('  function staffMessageText('):html.index('  function isConversationMessage(')]
    script=source+'\nconst assert=require("node:assert/strict");\n'
    script+='for(const [input,expected] of '+json.dumps(cases,ensure_ascii=False)+') assert.equal(staffMessageText(input),expected);\n'
    script+='const event={eventType:"crew_work_event",who:"jarvis",stage:"post-style-planning",phase:"completed",messageKind:"staff_reply",model:"real",outputKind:JSON.stringify({message:"실제 회의 메시지"})}; assert.equal(crewConversationText(event),"실제 회의 메시지"); assert.equal(event.outputKind,JSON.stringify({message:"실제 회의 메시지"}));'
    result=subprocess.run(['node','-e',script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
