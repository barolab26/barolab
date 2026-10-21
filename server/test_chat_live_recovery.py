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
        code += function('connectEventStream', '\n  function insertMention')
        code += function('getAgentBrainBadge', '\n  function buildMessageRowHtml')
        code += function('buildStatusLineHtml', '\n  streamEl.addEventListener')
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
