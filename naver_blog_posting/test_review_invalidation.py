import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from naver_blog_posting import pipeline_runner as r


class ReviewInvalidationTests(unittest.TestCase):
    def test_original_backup_and_image_hashes_required(self):
        with TemporaryDirectory() as temp:
            folder=Path(temp); backup=folder/'audit-backup';backup.mkdir();(folder/'images').mkdir();(backup/'images').mkdir()
            plans={'imagePlans':[{'filename':'one.jpg'}]}
            values={'handoff.json':'{}','image-maker.json':'{}','image-plan.json':json.dumps(plans),
                    'assembler.json':'{"issues":["no pixel evidence"]}','images/one.jpg':'original-bytes'}
            hashes={}
            for name,value in values.items():
                (folder/name).write_text(value);(backup/name).write_text(value);hashes[name]=r.sha(backup/name)
            (folder/'reused-photo-source.json').write_text(json.dumps(plans))
            audit={'reason':'stub visual review invalidated; fresh actual pixels required','backupDirectory':'audit-backup','backupHashes':hashes}
            (folder/'review-invalidation.json').write_text(json.dumps(audit))
            handoff=SimpleNamespace(folder=folder,check=lambda:[{}, {}, {}],file=lambda name:folder/name)
            r.require_review_invalidation(handoff)
            (folder/'images/one.jpg').write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'image changed'):
                r.require_review_invalidation(handoff)
            (folder/'images/one.jpg').write_text('original-bytes')
            (backup/'assembler.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'backup changed'):
                r.require_review_invalidation(handoff)

    def test_uninvalidated_stage_sequence_rejected(self):
        with self.assertRaises(RuntimeError):
            r.require_review_invalidation(SimpleNamespace(check=lambda:[{}, {}, {}, {}]))
