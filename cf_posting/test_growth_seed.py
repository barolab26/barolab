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

if __name__=='__main__':unittest.main()
