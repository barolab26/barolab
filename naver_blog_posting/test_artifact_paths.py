from pathlib import Path
import tempfile
import unittest
import hashlib
import json

from naver_blog_posting.artifact_paths import resolve_artifact_folder


class ArtifactPathsTests(unittest.TestCase):
    def test_symlink_outside_account_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            account = base / 'output/soultin'
            account.mkdir(parents=True)
            outside = base / 'outside'
            outside.mkdir()
            try:
                (account / 'escape').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation unavailable for this user')
            self.assertIsNone(resolve_artifact_folder(str(account / 'escape'), 'soultin', base))

    def test_known_prefix_requires_existing_matching_account(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            folder = base / 'output/soultin/example'
            folder.mkdir(parents=True)
            legacy = r'\\otns\yoonlab\10_Project\BaroLab\naver_blog_posting\output\soultin\example'
            self.assertIsNone(resolve_artifact_folder(legacy, 'soultin', base))
            receipt = b'{"verified":true}'
            (folder / 'reservation-evidence.json').write_bytes(receipt)
            (folder / 'migration-evidence.json').write_text(json.dumps({
                'schema': 'naver-evidence-migration-v1', 'source': legacy,
                'files': {'reservation-evidence.json': hashlib.sha256(receipt).hexdigest()}}))
            self.assertEqual(resolve_artifact_folder(legacy, 'soultin', base), folder.resolve())
            self.assertIsNone(resolve_artifact_folder(legacy, 'stone0747', base))
            self.assertIsNone(resolve_artifact_folder(legacy + '-missing', 'soultin', base))
            self.assertIsNone(resolve_artifact_folder(legacy + r'\..\example', 'soultin', base))
            self.assertIsNone(resolve_artifact_folder(legacy.replace('otns', 'other'), 'soultin', base))
            self.assertEqual(resolve_artifact_folder(str(folder), 'soultin', base), folder.resolve())
            (folder / 'reservation-evidence.json').write_bytes(b'changed')
            self.assertIsNone(resolve_artifact_folder(legacy, 'soultin', base))


if __name__ == '__main__':
    unittest.main()
