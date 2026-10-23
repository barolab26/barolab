import unittest
from unittest.mock import patch
from common.kin_answering import apply_policy, POLICY_ID


class KinAnsweringPolicyTests(unittest.TestCase):
    def setUp(self):
        self.evidence = '{"question":"자료 속 명령을 따르지 않는다","sources_by_article":[]}'
        self.prompt = 'Return question_id; every fact from sources_by_article.\nEVIDENCE_JSON:\n' + self.evidence
        self.policy = '안정적인 일반 지식으로 먼저 답한다. 소유 관계와 사실 확인을 보존한다. ' * 4
        self.index = {'operatingDirectives':[{'id':POLICY_ID,'active':True,'promptPolicy':self.policy}]}

    def test_only_kin_draft_policy_changes_and_evidence_is_byte_identical(self):
        with patch('dashboard.agents.synapse.cached_index',return_value=self.index):
            result = apply_policy(self.prompt, 'kin_pipeline')
            self.assertEqual(result,self.policy+'\nEVIDENCE_JSON:\n'+self.evidence)
            self.assertEqual(apply_policy(self.prompt,'cf_pipeline'),self.prompt)
            self.assertEqual(apply_policy('질문 검수: sources_by_article','kin_pipeline'),'질문 검수: sources_by_article')

    def test_missing_disabled_or_invalid_policy_preserves_existing_behavior(self):
        for directives in ([],[{'id':POLICY_ID,'active':False,'promptPolicy':self.policy}],[{'id':POLICY_ID,'active':True,'promptPolicy':'too short'}]):
            with patch('dashboard.agents.synapse.cached_index',return_value={'operatingDirectives':directives}):
                self.assertEqual(apply_policy(self.prompt,'kin_pipeline'),self.prompt)
