import unittest
from common.knowledge_policy import usable_knowhow


class KnowledgeCandidatePolicyTests(unittest.TestCase):
    def test_quote_scope_conditions_and_limits_are_required_without_claiming_verified_success(self):
        node={'type':'PracticalKnowHow','active':True,'sourceType':'ceo_conversation','optional':True,
              'causalClaim':False,'measurementStatus':'not_measured','title':'선택적 방법','originalText':'대표의 원문',
              'method':'구체적 방법','whenToUse':'활용 조건','limits':'한계','recordedAt':'2026-10-23','roles':['radar']}
        self.assertTrue(usable_knowhow(node))
        for key in ('originalText','whenToUse','limits','recordedAt','roles'):
            candidate=dict(node);candidate.pop(key)
            self.assertFalse(usable_knowhow(candidate),key)
        for change in ({'optional':False},{'causalClaim':True},{'measurementStatus':'verified_success'},{'sourceType':'operational_log'}):
            self.assertFalse(usable_knowhow({**node,**change}))
