import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from common import work_agenda as agenda


class PublicationReconciliation(unittest.TestCase):
    def test_exact_public_receipt_resolves_only_its_publication_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / 'dashboard/data'
            data.joinpath('cf').mkdir(parents=True)
            folder = root / 'cf_posting/output/scheduled/2026-11-06/example.com'
            folder.mkdir(parents=True)
            url = 'https://www.example.com/reader-task'
            receipt = dict(state='published', publicPublicationVerified=True, httpStatus=200,
                           domain='example.com', publicUrl=url,
                           verifiedAt=datetime.now(timezone.utc).isoformat())
            folder.joinpath('publication-receipt.json').write_text(json.dumps(receipt))
            data.joinpath('cf/daily_schedule.json').write_text(json.dumps(dict(date='2026-11-06', items=[
                dict(domain='example.com', scheduledTime='20:00', status='published', publicUrl=url)])))
            row = dict(id='incident', kind='conference', status='blocked', createdAt=time.time()-60,
                       events={'opening':{'id':'observed-opening','receivedAt':time.time()}},
                       source=dict(kind='parameters', arguments=dict(action='cf', date='2026-11-06',
                                                                   account='example.com', slot='20:00')))
            with patch.object(agenda, 'DATA', data), patch.object(agenda, 'verified', return_value=True) as verify:
                self.assertTrue(agenda.reconcile_publication_agenda(row))
                proof = verify.call_args.args[1]
                self.assertEqual(agenda.task_outcome(row, proof)['status'], 'completed')
                self.assertEqual(proof['businessOutcome'], 'not_evaluated')
                verify.reset_mock()
                row['source']['arguments']['slot'] = '20:10'
                self.assertFalse(agenda.reconcile_publication_agenda(row))
                row['source']['arguments']['slot'] = '20:00'
                row['source']['directive'] = 'Also verify search traffic'
                self.assertFalse(agenda.reconcile_publication_agenda(row))
                row['source'].pop('directive')
                row['status'] = 'suspended'
                self.assertFalse(agenda.reconcile_publication_agenda(row))
                verify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
