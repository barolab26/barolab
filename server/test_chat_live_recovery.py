"""Transport/UI contracts without importing live room writers or emitting messages."""
import ast
from pathlib import Path
import subprocess
import hashlib
import json
import logging
import re
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChatLiveRecoveryTests(unittest.TestCase):
    def test_execution_receipt_missing_exit_is_unknown_not_success(self):
        html = (ROOT/'dashboard/chat.html').read_text(encoding='utf-8')
        start = html.index('  function buildExecutionReceiptBoxHtml(')
        function = html[start:html.index('\n  function buildStatusLineHtml', start)]
        code = "const assert=require('node:assert/strict');const escapeHtml=String;\n" + function + """
const render=receipt=>buildExecutionReceiptBoxHtml({who:'patch',executionReceipts:[{cmd:'bounded-check',...receipt}]});
assert.ok(render({}).includes('Exit Code: unknown'));
assert.ok(render({exit_code:null}).includes('Exit Code: unknown'));
assert.ok(render({exit_code:0}).includes('Exit Code: 0'));
assert.ok(render({exit_code:1}).includes('Exit Code: 1'));
"""
        result = subprocess.run(['node','-e',code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_main_is_actual_conversation_and_records_are_separate(self):
        html=(ROOT/'dashboard/chat.html').read_text(encoding='utf-8')
        def grab(name,end):
            start=html.index('  function '+name+'(')
            return html[start:html.index(end,start)]
        code="const assert=require('node:assert/strict');const AGENT_STYLE={publi:{name:'퍼블리',color:'green',short:'P'},patch:{name:'패치',color:'orange',short:'X'}};const escapeHtml=String,getAgentBrainBadge=()=>'',isMessageWorkstream=m=>!!m.eventType,formatTime=()=>'',formatBodyText=String,buildExecutionReceiptBoxHtml=()=>'',buildStatusLineHtml=m=>'META:'+m.taskId;const extractMentionsFromText=()=>[];"
        code+=grab('workActorDisplay','\n  function doesMessageInvolveAgent')
        code+=grab('doesMessageInvolveAgent','\n  function recomputeUserReplyLinks')
        code+=grab('crewConversationText','\n  function buildMessageRowHtml')
        code+=grab('buildMessageRowHtml','\n  function upsertMessageToDom')
        code+="""
const actual={id:'reply',who:'patch',eventType:'crew_work_event',stage:'staff-response',phase:'completed',model:'actual-model',outputKind:'실제 상태를 확인했습니다.',text:'generic',taskId:'private-task',ts:1};
for(const stage of ['staff-response','staff-terminal-response','staff-report-format-followup']) {
 const response={...actual,stage};
 assert.ok(buildMessageRowHtml(response).includes(actual.outputKind));
 assert.ok(!buildMessageRowHtml(response).includes('private-task'));
 assert.ok(!buildMessageRowHtml(response).includes('<details'));
 for(const change of [{who:'common-runner'},{phase:'failed'},{model:''},{outputKind:'x'.repeat(121)}]) assert.equal(buildMessageRowHtml({...response,...change}),'');
}
const records=[
 {...actual,who:'cf-image-maker',stage:'model-call'},
 {...actual,phase:'failed'},
 {...actual,stage:'read_agent_status',phase:'requested',messageKind:'host_instruction'},
 {...actual,stage:'read_agent_status',phase:'progress',messageKind:'host_ack'},
 {...actual,who:'jarvis',stage:'project-result-reviewed',outputKind:'needs_attention; checked'},
 {who:'jarvis',eventType:'project_health_briefing',text:'host'},
 {who:'publi',eventType:'pipeline_workstream',text:'host'},
 {who:'common-runner',text:'host'},
 {who:'unknown-tool',text:'host'}
];
for(const record of records) {assert.equal(buildMessageRowHtml(record),'');assert.equal(doesMessageMatchFilters(record,'all',false),false);}
const review={...actual,who:'jarvis',stage:'project-result-reviewed',messageKind:'staff_reply',outputKind:'직원 보고를 검토했습니다.'};
assert.ok(buildMessageRowHtml(review).includes(review.outputKind));
assert.ok(buildMessageRowHtml({...review,stage:'project-instruction-issued'}).includes(review.outputKind));
assert.ok(isConversationMessage({who:'user',text:'Original user text'}));
assert.ok(buildMessageRowHtml({who:'patch',text:'Actual chat',ts:1}).includes('Actual chat'));
const messageStore=new Map([...records,actual].map((m,i)=>[i,m]));
const list={innerHTML:''};let selected='publi';
const document={getElementById:id=>id==='work-records-agent'?{value:selected}:list};
const chronologicalMessages=values=>[...values];
renderWorkRecords();assert.ok(list.innerHTML.includes('model-call'));
assert.ok(!list.innerHTML.includes('staff-response'));
selected='patch';renderWorkRecords();assert.ok(list.innerHTML.includes('private-task'));
assert.equal(actual.text,'generic');
"""
        result=subprocess.run(['node','-e',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('<dialog id="work-records-dialog"',html)
        self.assertNotIn('show-execution-records',html)
        self.assertNotIn('<dialog open',html)

    def test_canonical_projection_dedupe_and_outbox_preserve_malformed(self):
        tree = ast.parse((ROOT/'server/chat_room.py').read_text(encoding='utf-8'))
        names = {'project_work_event','receive_work_event','drain_work_event_outbox','_is_noise_or_fake_loop_message','_enrich_legacy_message'}
        nodes = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
        messages = []
        with tempfile.TemporaryDirectory() as tmp:
            scope = dict(Dict=dict, Any=object,List=list,re=re,hashlib=hashlib,json=json,logging=logging,
                time=time,HTTPException=RuntimeError,_ROOM_LOCK=threading.RLock(),CHATS_DIR=Path(tmp),_OUTBOX_OFFSET=0,_OUTBOX_LAST_SCAN=0,
                load_room_data=lambda:{'messages':messages},append_or_update_room_message=messages.append)
            exec(compile(ast.Module(body=nodes,type_ignores=[]),'<work-event>','exec'),scope)
            event = dict(id='crew-'+'a'*32,eventId='crew-'+'a'*32,eventType='crew_work_event',taskId='task',
                phase='completed',who='common-runner',actorLabel='공통 실행기',ts=1,model='',stage='model-call',
                text='Untrusted success claim',taskTracker={'status':'completed','synapseLinked':True})
            receive=scope['receive_work_event']
            self.assertFalse(receive(event)['duplicate']);self.assertTrue(receive(event)['duplicate'])
            self.assertEqual(len(messages),1)
            self.assertNotIn('Untrusted',messages[0]['text'])
            self.assertEqual(messages[0]['taskTracker']['status'],'status_only')
            self.assertFalse(scope['_is_noise_or_fake_loop_message'](messages[0]))
            self.assertEqual(scope['_enrich_legacy_message'](messages[0],0,messages)['brain']['badge'],'모델 미관측')
            with self.assertRaises(ValueError):receive({**event,'phase':'failed'})
            with self.assertRaises(ValueError):receive({**event,'model':'api_key=unsafe'})
            project=scope['project_work_event']
            self.assertEqual(project({**event,'messageKind':'host_instruction'})['messageKind'],'host_instruction')
            with self.assertRaises(ValueError):project({**event,'messageKind':'invented'})
            tool=project({**event,'who':'cf-image-maker','ownerAgent':'publi','toolActor':'cf-image-maker'})
            self.assertEqual((tool['who'],tool['ownerAgent'],tool['toolActor']),('cf-image-maker','publi','cf-image-maker'))
            for bad in ({'ownerAgent':'outsider'},{'toolActor':'forged'},{'who':'patch','ownerAgent':'publi'}):
                with self.assertRaises(ValueError):project({**event,**bad})
            out=Path(tmp)/'crew-outbox';out.mkdir()
            malformed=out/'000.json';malformed.write_text('{bad')
            second={**event,'id':'crew-'+'b'*32,'eventId':'crew-'+'b'*32}
            good=out/(hashlib.sha256(second['id'].encode()).hexdigest()+'.json')
            good.write_text(json.dumps(second),encoding='utf-8')
            scope['drain_work_event_outbox']()
            self.assertTrue(malformed.exists());self.assertFalse(good.exists());self.assertEqual(len(messages),2)
            legacy_calls=[]
            scope['receive_pipeline_autonomous_event']=legacy_calls.append
            legacy=out/'legacy';legacy.mkdir()
            old={'id':'legacy-id','who':'patch','text':'existing legacy payload'}
            old_path=legacy/(hashlib.sha256(old['id'].encode()).hexdigest()+'.json')
            old_path.write_text(json.dumps(old),encoding='utf-8')
            # A legacy-shaped payload in the canonical directory must stay rejected.
            wrong=out/(hashlib.sha256(old['id'].encode()).hexdigest()+'.json')
            wrong.write_text(json.dumps(old),encoding='utf-8')
            scope['_OUTBOX_LAST_SCAN']=0
            scope['drain_work_event_outbox']()
            self.assertEqual(legacy_calls,[old]);self.assertFalse(old_path.exists());self.assertTrue(wrong.exists())

    def test_restart_resets_old_cursor_without_inventing_events(self):
        tree = ast.parse((ROOT/'server/chat_room.py').read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'room_event_resume')
        scope = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<resume>', 'exec'), scope)
        resume = scope['room_event_resume']
        self.assertEqual(resume(200, 'old', 1, 'new'), {'seq':1,'epoch':'new','reset':True})
        self.assertTrue(resume(200, '', 1, 'new')['reset'])
        self.assertEqual(resume(1, 'same', 3, 'same')['seq'], 1)
        queued = [{'seq':2}, {'seq':3}]
        cursor = resume(1, 'same', 3, 'same')['seq']
        self.assertEqual([e['seq'] for e in queued if e['seq'] > cursor], [2, 3])

    def test_ui_cursor_reconnect_unknown_actor_and_linkage(self):
        html = (ROOT/'dashboard/chat.html').read_text(encoding='utf-8')
        def function(name, end):
            return html[html.index('  function '+name+'('):html.index(end, html.index('  function '+name+'('))]
        code = """
const assert=require('node:assert/strict');
let lastEventSeq=70,eventEpoch='old',eventReconnectTimer=null,sseSource=null,resolvedApiBase='';
let reloads=0;const loadRoom=async()=>{reloads++};
const clearTimeout=()=>{};const setTimeout=()=>1;
class EventSource { constructor(url){this.url=url;this.handlers={}} addEventListener(n,fn){this.handlers[n]=fn} close(){this.closed=true} }
const escapeHtml=s=>String(s).replaceAll('<','&lt;');
const AGENT_STYLE={},agentBrainBadgeMap=new Map();
const activeTypingMap=new Map();const renderTypingIndicators=()=>{};const upsertMessageToDom=()=>{};
"""
        code += function('workActorDisplay', '\n  function doesMessageInvolveAgent')
        code += function('connectEventStream', '\n  function insertMention')
        code += function('getAgentBrainBadge', '\n  function buildMessageRowHtml')
        code += function('buildStatusLineHtml', '\n  document.addEventListener')
        code += function('isNoiseMessage', '\n  function getAgentBrainBadge')
        code += function('chronologicalMessages', '\n  function renderTypingIndicators')
        code += """
connectEventStream();
sseSource.handlers.connected({data:JSON.stringify({epoch:'new',seq:0,reset:true})});
assert.equal(reloads,1);assert.equal(sseSource.closed,true);
eventEpoch='new';lastEventSeq=0;connectEventStream();
sseSource.handlers.connected({data:JSON.stringify({epoch:'new',seq:0,reset:false})});
assert.equal(lastEventSeq,0);
sseSource.handlers.message({lastEventId:'new:4',data:'{"id":"x"}'});
assert.equal(lastEventSeq,4);sseSource.onerror();connectEventStream();
assert.ok(sseSource.url.includes('since_seq=4'));
assert.equal(getAgentBrainBadge({who:'unscoped'}),'모델 미관측');
const legacyTool={who:'cf-image-maker',eventType:'crew_work_event'};
assert.deepEqual(workActorDisplay(legacyTool),{owner:'publi',tool:'cf-image-maker',historical:true});
assert.equal(legacyTool.who,'cf-image-maker');
for (const who of ['kin-pipeline','threads-pipeline']) {
  const event={who,eventType:'crew_work_event'};
  assert.equal(workActorDisplay(event).owner,'publi');
  assert.equal(workActorDisplay(event).tool,who);
  assert.equal(event.who,who);
}
assert.equal(workActorDisplay({who:'naver-keyword-selector',eventType:'crew_work_event'}).owner,'radar');
assert.equal(workActorDisplay({who:'common-runner',eventType:'crew_work_event'}).owner,'');
assert.equal(workActorDisplay({who:'common-runner',ownerAgent:'patch'}).owner,'patch');
assert.equal(workActorDisplay({who:'patch'}).tool,'');
assert.ok(buildStatusLineHtml(legacyTool).includes('실행 도구: cf-image-maker'));
assert.ok(buildStatusLineHtml(legacyTool).includes('과거 기록 역할 분류'));

const row=buildStatusLineHtml({who:'unscoped',taskId:'<task>',requestedTo:'patch',parentRequestId:'req'});
assert.ok(!row.includes('✅'));assert.ok(row.includes('&lt;task>'));assert.ok(row.includes('req'));
for(const [slug,label] of Object.entries({jarvis:'자비스',patch:'패치',publi:'퍼블리',trace:'트레이스',radar:'레이더',doctor:'닥터'})) {
  const message={who:'unscoped',requestedTo:slug};
  assert.ok(buildStatusLineHtml(message).includes('요청 대상: @'+label));
  assert.equal(message.requestedTo,slug);
}
for(const target of ['cf-pipeline','configured-model-runner']) {
  assert.ok(buildStatusLineHtml({who:'unscoped',requestedTo:target}).includes('요청 대상: '+target));
}
assert.equal(isNoiseMessage({who:'system',id:'sys-new',text:'10월 22일 실제 작업',eventType:'crew_work_event',taskId:'t',eventId:'e'}),false);
assert.equal(isNoiseMessage({who:'system',id:'sys-legacy',text:'legacy'}),true);
const original=[{id:'done',parentRequestId:'request',ts:20},{id:'request',ts:10}];
assert.deepEqual(chronologicalMessages(original).map(m=>m.id),['request','done']);
assert.equal(original[0].id,'done');
assert.deepEqual(chronologicalMessages([{id:'done',parentRequestId:'request',ts:10},{id:'other',ts:10},{id:'request',ts:10}]).map(m=>m.id),['request','done','other']);
const messageStore=new Map([['done',original[0]]]);let rows=[{id:'done'},{id:'request'}];
const CSS={escape:x=>x};
const streamEl={querySelector:selector=>rows.find(r=>selector.includes('"'+r.id+'"')),appendChild:row=>{rows=rows.filter(r=>r!==row);rows.push(row)}};
messageStore.set('request',original[1]);sortVisibleMessages();
assert.deepEqual(rows.map(r=>r.id),['request','done']);
"""
        result = subprocess.run(['node','-e',code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
