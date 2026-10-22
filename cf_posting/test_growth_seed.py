import ast
import datetime
import re
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SOURCE=Path(__file__).with_name('pipeline_runner.py').read_text(encoding='utf-8')
NODES=ast.Module(body=[n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name in {'growth_editorial_seed','select_keyword_with_demand','keyword_demand_evidence'}],type_ignores=[])

class GrowthSeedTests(unittest.TestCase):
    def setUp(self):
        self.ns={'datetime':datetime,'_news':Mock(return_value=([],None)),'_norm':lambda x:re.sub(r'\s+','',str(x)).lower()}
        exec(compile(NODES,'production-growth-seed','exec'),self.ns)

    def test_editorial_title_does_not_become_measured_query(self):
        title='아이와 주말 수목원 나들이, 예약과 현장 발권부터 동선까지 — 취소 조건'
        result=self.ns['growth_editorial_seed']({'topicSlug':'family-trip'}, {'keyword':title})
        self.assertNotIn('mainKeyword',result)
        self.assertEqual(result['seedTitle'],title)
        class StopProposal(Exception):pass
        def proposal(prompt,response_schema=None):
            self.assertNotIn('enum',response_schema['properties']['candidates']['items']['properties']['mainKeyword'])
            raise StopProposal()
        with self.assertRaises(StopProposal):
            self.ns['select_keyword_with_demand']('instruction',{},proposal,result)

    def test_explicit_or_approved_query_is_preserved(self):
        fixed={'mainKeyword':'수목원 예약','mode':'held_plan','topicSlug':'known'}
        result=self.ns['growth_editorial_seed'](fixed,{'keyword':'long editorial title'})
        self.assertEqual(result['mainKeyword'],'수목원 예약')
        self.assertEqual(result['mode'],'held_plan')
        self.assertEqual(fixed,{'mainKeyword':'수목원 예약','mode':'held_plan','topicSlug':'known'})

    def _observe_selector_queries(self, fixed, expected):
        class BoundaryObserved(Exception): pass
        candidates=[{'mainKeyword':word,'question':word+' 확인 방법은?', 'category':'여행',
                     'title':word+' 준비 방법','topicSlug':'family-trip-'+str(index)}
                    for index,word in enumerate(['수목원 예약','수목원 주차','수목원 준비물'])]
        def measured(rows):
            self.assertEqual([row['mainKeyword'] for row in rows],expected)
            raise BoundaryObserved()
        self.ns['keyword_demand_evidence']=measured
        with self.assertRaises(BoundaryObserved):
            self.ns['select_keyword_with_demand']('instruction',{},lambda *args,**kwargs:{'candidates':candidates},fixed)

    def test_selector_passes_independent_queries_to_demand_boundary(self):
        fixed=self.ns['growth_editorial_seed'](None,{'keyword':'아이와 주말 수목원 나들이 예약과 발권 확인부터 가족 동선까지'})
        self._observe_selector_queries(fixed,['수목원 예약','수목원 주차','수목원 준비물'])

    def test_selector_preserves_explicit_fixed_query_at_measurement_boundary(self):
        fixed=self.ns['growth_editorial_seed']({'mainKeyword':'수목원 입장료'}, {'keyword':'long editorial title'})
        self._observe_selector_queries(fixed,['수목원 입장료']*3)

    def test_controlled_low_demand_fixture_is_rejected_by_real_threshold_logic(self):
        self.ns.update(os=os,BASE_DIR=Path('unused'),_volume=Mock(return_value={'status':'ok','monthlyLowerBound':18,'monthlyUpperBound':18}),
                       _trend=Mock(return_value={'status':'unknown'}))
        with patch('dotenv.load_dotenv'),patch.dict(os.environ,{'CF_MIN_MONTHLY_SEARCHES':'100'}):
            evidence=self.ns['keyword_demand_evidence']([{'mainKeyword':'controlled fixture','question':'fixture'}])
        self.assertEqual(evidence['threshold'],100)
        self.assertFalse(evidence['candidates'][0]['eligible'])

class DemandRecoveryTests(unittest.TestCase):
    def setUp(self):GrowthSeedTests.setUp(self)
    def test_rejected_held_keyword_is_released_on_second_round(self):
        class Observed(Exception):pass
        rounds=[]
        def propose(prompt,response_schema=None):
            props=response_schema['properties']['candidates']['items']['properties']['mainKeyword']
            rounds.append(dict(props))
            if len(rounds)==2:
                self.assertNotIn('enum',props);raise Observed()
            return {'candidates':[{'mainKeyword':'긴 고정 검색어','question':'질문 확인 방법','category':'여행','title':'예약 확인','topicSlug':'booking-check'}]}
        self.ns['keyword_demand_evidence']=lambda rows:{'threshold':100,'candidates':[{'mainKeyword':r['mainKeyword'],'volume':{'status':'ok','monthlyLowerBound':12},'eligible':False,'currentIssue':False} for r in rows]}
        with self.assertRaises(Observed):self.ns['select_keyword_with_demand']('instruction',{},propose,{'mainKeyword':'긴 고정 검색어'},require_current_issue=False)
        self.assertEqual(rounds[0]['enum'],['긴 고정 검색어'])

    def test_evergreen_monthly_demand_reaches_final_plan_without_news(self):
        class PlanReached(Exception):pass
        def propose(prompt,response_schema=None):
            if 'candidates' not in response_schema['properties']:raise PlanReached()
            return {'candidates':[{'mainKeyword':'수목원','question':'예약 확인 방법','category':'여행','title':'예약 확인','topicSlug':'booking-check'}]}
        self.ns['keyword_demand_evidence']=lambda rows:{'threshold':100,'candidates':[{'mainKeyword':r['mainKeyword'],'volume':{'status':'ok','monthlyLowerBound':200},'eligible':False,'currentIssue':False,'issueSignals':[],'news':[]} for r in rows]}
        with self.assertRaises(PlanReached):self.ns['select_keyword_with_demand']('instruction',{},propose,require_current_issue=False)


if __name__=='__main__':unittest.main()


class PromptContextIdentityTests(unittest.TestCase):
    def test_invalid_source_context_rejected_without_mutating_response(self):
        import json,copy,uuid
        from contextlib import nullcontext
        node=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='generate_with_prompt_budget')
        ns={'json':json,'copy':copy,'uuid':uuid,'provider_prompt_prefix':lambda *a:'','serialized_prompt_bytes':lambda s:len(s),'rebudget_prompt':lambda p,b:p,'PROMPT_BYTE_LIMIT':100000,'ReviewRequired':RuntimeError}
        exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-prompt-boundary','exec'),ns)
        result={'answerBrief':{'questionBasis':{'contextId':'wrong','quote':'original'}}}
        original=copy.deepcopy(result)
        with patch('common.llm_client.generate_json',return_value=result),patch('common.llm_client.memory_call',side_effect=lambda f:f),patch('common.llm_client.memory_session',side_effect=lambda *a:nullcontext()):
            with self.assertRaisesRegex(RuntimeError,'no identity substitution'):ns['generate_with_prompt_budget'](json.dumps({'questionContext':[{'id':'real'}]}),'codex')
        self.assertEqual(result,original)


class RepairedStageObservationTests(unittest.TestCase):
    def test_real_keyword_stage_acceptance_not_legacy_slug_or_later_stages(self):
        import json,hashlib,tempfile,copy
        node=next(n for n in ast.parse(SOURCE).body if isinstance(n,ast.FunctionDef) and n.name=='observe_repaired_keyword_stage')
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);folder=base/'output'/'actual-topic'/'run';folder.mkdir(parents=True)
            keywords={'topicSlug':'actual-topic','mainKeyword':'arboretum booking'}
            (folder/'keywords.md').write_text(json.dumps(keywords),encoding='utf-8')
            row={'agent':'keyword-selector','status':'accepted','inputs':[],'inputHashes':{},'model':{'status':'returned','actualModel':'observed'},'acceptedAt':'2026-10-21T14:59:00+09:00','fileHashes':{'keywords.md':hashlib.sha256((folder/'keywords.md').read_bytes()).hexdigest()}}
            data={'domain':'tripmarvel.com','slug':'actual-topic','runId':'a'*32,'stages':[row,{'agent':'researcher','status':'invalid'}]}
            path=folder/'handoff.json';path.write_text(json.dumps(data),encoding='utf-8')
            ns={'BASE_DIR':base,'re':re,'json':json,'datetime':datetime,'hashlib':hashlib,'read_document':lambda path:json.loads(path.read_text())}
            exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-stage-observer','exec'),ns)
            item={'domain':'tripmarvel.com','slug':'legacy-placeholder','artifactFolder':'output/actual-topic/run','attemptStartedAt':'2026-10-21T14:58:00+09:00','repairContinuationUsed':{'taskId':'task','approvedQuery':'arboretum booking'}}
            result=ns['observe_repaired_keyword_stage'](item,'task');self.assertTrue(result['failureStagePassed']);self.assertIn('only',result['scope'])
            for mutation in ('domain','query','earlier','bytes'):
                current=copy.deepcopy(item)
                if mutation=='domain':current['domain']='other.com'
                if mutation=='query':current['repairContinuationUsed']['approvedQuery']='hotel'
                if mutation=='earlier':current['attemptStartedAt']='2026-10-21T15:00:00+09:00'
                if mutation=='bytes':(folder/'keywords.md').write_text(json.dumps({**keywords,'extra':True}),encoding='utf-8')
                with self.assertRaises(ValueError):ns['observe_repaired_keyword_stage'](current,'task')
