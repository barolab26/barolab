"""Canonical Ubuntu workflow delegates; never launch a real publisher in tests."""
import unittest
from pathlib import Path
from unittest.mock import patch
from dashboard.server import ego
class WorkflowTests(unittest.TestCase):
    def test_default_ego_starts_the_single_dispatcher(self):
        with patch('sys.argv',['ego.py']),patch.object(ego.subprocess,'run') as run:
            run.return_value.returncode=0
            self.assertEqual(ego.main(),0)
            self.assertEqual(run.call_args.args[0],['systemctl','--user','start','barolab-memory-review.service'])
    def test_explicit_catch_up_is_one_bounded_canonical_worker(self):
        with patch('sys.argv',['ego.py','--cf-catch-up']),patch.object(ego.subprocess,'run') as run:
            run.return_value.returncode=0
            self.assertEqual(ego.main(),0)
            self.assertEqual(run.call_args.args[0][-3:],['--catch-up-today-once','--limit','1'])
            self.assertTrue(run.call_args.args[0][2].endswith('/cf_posting/posting.py'))
