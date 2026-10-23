import tempfile
import unittest
from pathlib import Path

from common.collection_observability import load
from common.ego_learning import remember_success


class EgoLearningTests(unittest.TestCase):
    def test_verified_skill_is_deduplicated_and_reaches_next_screen_prompt_index(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before, after = root / 'before.png', root / 'after.png'
            Image.new('RGB', (8, 8)).save(before)
            Image.new('RGB', (8, 8)).save(after)
            turns = [{'message': '구성요소를 선택하고 휴지통을 눌렀습니다.', 'completedActions': 2}]
            key = remember_success('Visible quoteCount: expected 1, observed 3', turns, before, after, 12, root=root)
            same = remember_success('Visible quoteCount: expected 1, observed 2', turns, before, after, 8, root=root)
            self.assertEqual(key, same)
            graph = load(root / 'dashboard/data/memory_graph.json')
            node = graph['nodes'][key]
            self.assertEqual(node['successCount'], 2)
            self.assertEqual([row['elapsedSeconds'] for row in node['measurements']], [12, 8])
            self.assertFalse(node['causalClaim'])
            self.assertIn({'source': 'memory:hub', 'target': key, 'type': 'contains'}, graph['edges'])
            index = load(root / 'dashboard/data/synapse-recipes.json')
            self.assertEqual(index['screenLessons'][0]['status'], 'verified_success')

    def test_missing_screen_evidence_does_not_become_a_verified_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                remember_success('font mismatch', [], root / 'missing.png', root / 'missing2.png', 0, root=root)
            self.assertFalse((root / 'dashboard/data/memory_graph.json').exists())
