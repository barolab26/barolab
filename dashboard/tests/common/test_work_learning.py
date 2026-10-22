import json
from pathlib import Path
import tempfile
import unittest

from common.work_learning import observed_review_summary


class WorkLearningSummaryTests(unittest.TestCase):
    def test_only_observed_bounded_safe_metadata_enters_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'review.json'
            path.write_text(json.dumps({'body':'private full article', 'prompt':'raw request',
                'review':{'passed':True, 'issues':['Caption repeats the body'],
                    'notes':['api_key=secret'], 'reason':'See https://host/?token=value'},
                'imagePlans':[{'purpose':'Show the complete official table', 'caption':'unneeded body text'}]}), encoding='utf-8')
            summary, sources = observed_review_summary([path])
            result = json.loads(summary)[0]['observed']
            self.assertEqual(result['review'], {'passed':True,'issues':['Caption repeats the body']})
            self.assertEqual(result['imagePlans'], [{'purpose':'Show the complete official table'}])
            self.assertNotIn('private', summary)
            self.assertEqual(sources, [path])

    def test_no_artifact_is_not_fabricated_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(observed_review_summary([Path(tmp)/'absent.json']), ('[]', []))

    def test_oversized_field_is_omitted_not_truncated_into_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'review.json'
            path.write_text(json.dumps({'issues':['x'*1000]}), encoding='utf-8')
            self.assertEqual(observed_review_summary([path]), ('[]', []))
