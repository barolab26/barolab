import json
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from common import source_discovery as sources, ego_taskspace as ego
from server.memory_worker import action_outcome


class CompanyRuntimeRecovery(unittest.TestCase):
    def test_threads_reply_recovery_uses_parent_conversation_and_exact_match(self):
        import hashlib
        from threads_posting import posting as threads
        url='https://www.example.org/a?utm_source=threads&utm_medium=social&utm_campaign=cf_bridge&utm_content=unique'
        text='Observed answer '+url
        part={'account_key':'mustpickinfo','kind':'followup','parent_platform_id':'123','text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'outbound_url':url,'intent_at':'2026-11-07T00:00:00+00:00'}
        actual={'id':'456','username':'mustpickinfo','text':text,'timestamp':'2026-11-07T00:01:00+00:00','permalink':'https://www.threads.com/@mustpickinfo/post/Observed','is_reply':True,'replied_to':{'id':'123'}}
        client=MagicMock();client.request.return_value={'data':[actual]}
        with patch.object(threads,'_threads_adapter_Client',return_value=client),patch.object(threads,'_threads_adapter__identity'):
            found=threads._threads_adapter_recover_unknown({},part)
            self.assertTrue(found['matched']);self.assertEqual(found['platform_id'],'456')
            self.assertEqual(client.request.call_args.args[:2],('GET','123/conversation'))
            client.request.return_value={'data':[{**actual,'replied_to':{'id':'999'}}]}
            self.assertFalse(threads._threads_adapter_recover_unknown({},part)['matched'])
            client.request.return_value={'data':[actual,{**actual,'id':'457'}]}
            self.assertEqual(threads._threads_adapter_recover_unknown({},part)['reason'],'recovery_ambiguous_matches')
            client.request.reset_mock();self.assertFalse(threads._threads_adapter_recover_unknown({},{**part,'parent_platform_id':None})['matched']);client.request.assert_not_called()

    def test_threads_conversation_endpoint_is_read_only_and_numeric(self):
        from threads_posting import posting as threads
        response=MagicMock();response.status_code=200;response.json.return_value={'data':[]}
        client=threads._threads_adapter_Client({'account_key':'mustpickinfo'},token_override='test-token')
        with patch.object(threads._threads_adapter_requests,'request',return_value=response) as request:
            self.assertEqual(client._request('GET','123/conversation'),{'data':[]})
            for method,endpoint in [('POST','123/conversation'),('GET','me/conversation'),('GET','123/conversation?x=1')]:
                request.reset_mock()
                with self.assertRaises(threads._threads_adapter_AdapterError):client._request(method,endpoint)
                request.assert_not_called()

    def test_host_pressure_is_observed_without_claiming_publication_or_stopping_workers(self):
        from common.runtime_recovery import resource_observation
        row=resource_observation(32000,500,96000,1500,500000,80000)
        self.assertEqual(row['status'],'critical');self.assertEqual(row['physicalAvailableBytes'],500)
        self.assertFalse(row['automaticProcessTermination']);self.assertFalse(row['publicationVerified'])
        self.assertEqual(resource_observation(32000,16000,96000,60000,500000,80000)['status'],'normal')
        with self.assertRaises(ValueError):resource_observation(32000,-1,96000,1500,500000,80000)

    def test_stale_or_missing_host_observation_is_unknown_not_healthy_container(self):
        import tempfile
        from pathlib import Path
        from common import runtime_recovery as runtime
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);module=root/'dashboard/common/runtime_recovery.py';module.parent.mkdir(parents=True)
            target=root/'dashboard/data/host-resources.json';target.parent.mkdir(parents=True)
            with patch.object(runtime,'__file__',str(module)):
                self.assertEqual(runtime.host_resource_evidence(100)['status'],'unknown')
                target.write_text(json.dumps({'checkedAt':50,'status':'critical'}))
                self.assertEqual(runtime.host_resource_evidence(100)['status'],'critical')
                self.assertEqual(runtime.host_resource_evidence(300)['status'],'unknown')
                self.assertEqual(runtime.host_resource_evidence(20)['status'],'unknown')

    def test_large_company_observation_retains_failures_and_marks_partial_metrics(self):
        from agents import crew_reasoning as crew
        original={'projects':[{'id':'brunch','failures':[{'reason':'uncertain_submission',
            'sourceLocation':'brunch_posting/posting.py:612'}],
            'runtimeOutcome':{'status':'blocked','publicationVerified':False}}],
            'businessEvidence':{'pageObservations':[{'url':f'https://example.org/{i}',
                'detail':'x'*2000} for i in range(40)],'api_key':'private-value'}}
        row={'observations':[]}
        with patch.object(crew,'save'):
            event=crew.observe(row,'jarvis','projects',{},original)
        result=event['result']
        self.assertEqual(result['projects'],original['projects'])
        self.assertNotIn('truncated',result)
        self.assertEqual(result['businessEvidence']['excerptCoverage']['pageObservations'],
            {'shown':16,'total':40,'complete':False})
        self.assertEqual(result['businessEvidence']['api_key'],'[redacted]')
        self.assertEqual(len(original['businessEvidence']['pageObservations']),40)
        self.assertEqual(result['businessEvidence']['detailReaders']['naverPublication'],'naver_public')

    def test_strategy_model_receives_failure_cause_and_publication_scope(self):
        from agents import crew_reasoning as crew
        project={'id':'brunch','failures':[{'reason':'uncertain_submission'}],
            'runtimeOutcome':{'sourceLocation':'brunch_posting/posting.py:612','publicationVerified':False},
            'verifiedPublicCount':0,'reservedCount':1,'source':{'fresh':True},
            'nextAction':'reconcile_existing_submission'}
        row={'id':'a'*64,'goal':'Assess actual company results','observations':[
            {'tool':'projects','result':{'projects':[project],'businessEvidence':{}}}]}
        with patch('common.llm_client.generate_json',side_effect=RuntimeError('test stop')) as model, \
             patch('common.staff_capabilities.capability_catalog',return_value=[]),patch.object(crew,'save'):
            crew.answer_strategy(row)
        prompt=model.call_args.args[0]
        data=json.loads(prompt.split('\n',1)[1])
        self.assertEqual(data['projects'][0]['runtimeOutcome'],project['runtimeOutcome'])
        self.assertEqual(data['projects'][0]['failures'],project['failures'])
        self.assertEqual(data['projects'][0]['reservedCount'],1)
        self.assertEqual(data['projects'][0]['verifiedPublicCount'],0)

    def test_live_worker_exposes_blocked_input_without_claiming_publication(self):
        held=action_outcome({'ok':True,'action':'held','reason':'no_reviewed_prepared_article'})
        self.assertTrue(held['requiresRepair'])
        self.assertFalse(held['publicationVerified'])
        self.assertEqual(action_outcome({'ok':True,'action':'all_topics_published'})['status'],'awaiting_content_input')
        try:
            raise TypeError('unsupported call')
        except TypeError as error:
            result=action_outcome(error=error)
        self.assertEqual(result['errorType'],'TypeError')
        self.assertIn('test_company_runtime_recovery.py:',result['sourceLocation'])

    def test_public_source_error_pages_are_not_research_and_client_is_identified(self):
        response=MagicMock(status_code=200,headers={'Content-Type':'text/html'})
        response.__enter__.return_value=response
        response.iter_content.return_value=[b'<main>page content</main>']
        with patch.object(sources.socket,'getaddrinfo',return_value=[(2,1,6,'',('93.184.215.14',443))]), \
             patch.object(sources.requests,'get',return_value=response) as request:
            self.assertEqual(sources.public_text('https://example.org/help')['text'],'page content')
            self.assertIn('BaroLab-SourceReader',request.call_args.kwargs['headers']['User-Agent'])
            response.iter_content.return_value=['<main>페이지를 찾을 수가 없어요</main>'.encode()]
            with self.assertRaisesRegex(ValueError,'HTTP 200'):
                sources.public_text('https://example.org/missing')

    def test_brunch_click_timeout_reconciles_observed_effect_without_replaying(self):
        scripts=[]
        with patch.object(ego,'run_ego_mjs',side_effect=lambda script,**kw:scripts.append(script) or {}):
            ego.native_publish_brunch_column('복지용구','조건 확인',['첫 본문','둘째 본문'])
        harness=r'''
let url='about:blank',opened=false,first=0,final=0;
const fields={};
const words=['가족','복지','돌봄'].map(text=>({innerText:text,selected:false,click(){this.selected=true;}}));
globalThis.location={pathname:'/write'};
globalThis.document={querySelector(s){
 if(s==='h1.cover_title')return {innerText:fields[s]||''};
 if(s==='div.cover_sub_title'||s==='div.wrap_body')return {innerText:fields[s]||''};
 if(s==='button.be_header_button_publish')return {};
 if(s==='button.save.button.mint')return opened?{getBoundingClientRect:()=>({width:52})}:null;
 return null;
},querySelectorAll(s){if(s==='button.keyword.selected')return words.filter(w=>w.selected);
 if(s==='button.keyword:not(.selected)')return words.filter(w=>!w.selected);return [];},
 body:{get innerText(){return fields['h1.cover_title']+' '+fields['div.wrap_body'];}}};
const page={label:'p2',url:async()=>url,goto:async u=>{url=u;},waitForTimeout:async()=>{},
 evaluate:async(fn,arg)=>fn(arg),fill:async(s,v)=>{fields[s]=v;},
 waitForFunction:async fn=>{if(!fn())throw Error('condition unverified');},
 click:async s=>{if(s==='button.be_header_button_publish'){first++;opened=true;throw Error('target covered after click');}
 if(s==='button.save.button.mint'){final++;url='https://brunch.co.kr/@31d1f5fb288c4fc/11';location.pathname='/@31d1f5fb288c4fc/11';throw Error('old target disappeared after navigation');}}};
globalThis.listTaskSpaces=async()=>[{id:1,name:'barolab-soultin',ownership:'agent'}];
globalThis.taskSpace=async()=>({spaceId:1,ownership:'agent',newPage:async()=>page});
'''
        code=harness+'\nasync function run(){'+scripts[0]+'}\nawait run();console.log("COUNTS:"+JSON.stringify({first,final,url}));'
        result=subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,encoding='utf-8',timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(next(x.split(':',1)[1] for x in result.stdout.splitlines() if x.startswith('BAROLAB_EGO_JSON:')))
        counts=json.loads(next(x.split(':',1)[1] for x in result.stdout.splitlines() if x.startswith('COUNTS:')))
        self.assertTrue(output['publicBodyMatched'],output)
        self.assertEqual((counts['first'],counts['final']),(1,1))
        self.assertEqual(counts['url'],output['url'])


if __name__=='__main__':
    unittest.main()
