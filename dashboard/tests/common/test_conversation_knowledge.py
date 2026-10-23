import unittest
from unittest.mock import patch
from dashboard.agents.synapse import build_index, recipe


class ConversationKnowledgeTests(unittest.TestCase):
    def test_optional_unmeasured_knowledge_reaches_relevant_staff_without_becoming_a_rule(self):
        node={'type':'PracticalKnowHow','active':True,'title':'지식인 키워드 수요 조사','tags':['키워드','지식인'],
              'roles':['radar','jarvis'],'method':'질문 수요에서 글감을 찾는 선택적 방법',
              'whenToUse':'기존 글과 질문 연결 방식과 비교해 선택','limits':'질문 수는 검색량의 증명이 아니다',
              'measurementStatus':'not_measured','optional':True,'causalClaim':False}
        graph={'nodes':{'knowhow:test':node},'edges':[]}
        index=build_index(graph)
        self.assertEqual(index['knowledgeNotes'][0]['id'],'knowhow:test')
        index['operatingDirectives']=[{'active':True,'guidance':'우선 운영 지시 '+str(i)} for i in range(20)]
        with patch('dashboard.agents.synapse.cached_index',return_value=index):
            result=recipe('지식인 키워드 조사','radar')
            self.assertIn('필수 지시 아님',result)
            self.assertIn('not_measured',result)
            self.assertIn('질문 수는 검색량의 증명이 아니다',result)
            self.assertNotIn('선택적 방법',recipe('지식인 키워드 조사','publi'))
            self.assertNotIn('선택적 방법',recipe('브라우저 포트 진단','radar'))
        self.assertTrue(node['optional'])
        self.assertFalse(node['causalClaim'])
