import unittest
from common.knowledge_links import connect_explicit_context


class ExplicitKnowledgeLinkTests(unittest.TestCase):
    def test_only_explicit_roles_and_accounts_are_connected_and_repeated_runs_are_stable(self):
        graph={'nodes':{'rule':{'type':'CEOOperatingDirective','roles':['jarvis','radar']},
                        'profile':{'type':'AccountProfile','account':'soultin'},
                        'draft':{'type':'EditorialPlanningSession','account':'soultin'},
                        'similar':{'type':'Post','title':'팀장 레이더 soultin 관련 제목'},
                        'unknown':{'type':'PracticalKnowHow','roles':['invented-role']}},'edges':[]}
        added=connect_explicit_context(graph)
        self.assertEqual({(e['source'],e['target'],e['type']) for e in added},
                         {('rule','staff:jarvis','applies_to_role'),('rule','staff:radar','applies_to_role'),('draft','profile','account_context')})
        self.assertEqual(connect_explicit_context(graph),[])
        self.assertTrue(all(e['source'] in graph['nodes'] and e['target'] in graph['nodes'] for e in graph['edges']))
        self.assertFalse(any(e['source'] in ('similar','unknown') for e in graph['edges']))
