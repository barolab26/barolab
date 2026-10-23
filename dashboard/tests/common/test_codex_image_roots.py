"""Exercise the actual CLI image guard without starting a provider or reading credentials."""
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from common import codex_cli


class AcceptedImage(Exception):pass


class CodexImageRootTests(unittest.TestCase):
    def test_all_four_channel_outputs_are_accepted_but_external_and_symlink_escapes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'project';root.mkdir();outside=Path(temp)/'outside.png';Image.new('RGB',(4,4)).save(outside)
            paths=[]
            for channel in ('cf_posting','naver_blog_posting','naver_kin','threads_posting'):
                image=root/channel/'output'/'screen.png';image.parent.mkdir(parents=True);Image.new('RGB',(4,4)).save(image);paths.append(image)
            escaped=root/'naver_kin/output/escape.png';escaped.symlink_to(outside)
            core=inspect.unwrap(codex_cli.generate_local)
            with patch.object(codex_cli,'local_config',return_value={'executable':'unused'}),patch.object(codex_cli,'runtime',return_value={'models':[{'id':'fixture'}]}),patch.object(codex_cli,'configured_reasoning_effort',return_value='low'),patch.object(codex_cli,'is_wsl',return_value=False),patch.object(codex_cli.jobs,'ROOT',root),patch.object(Path,'home',return_value=Path(temp)):
                for image in paths:
                    with self.subTest(channel=image.parts[-3]),patch.object(codex_cli,'_prepare_cli_image',side_effect=AcceptedImage) as prepare:
                        with self.assertRaises(AcceptedImage):core('fixture','fixture',images=[str(image)],reasoning_effort='low')
                        prepare.assert_called_once()
                for image in (outside,escaped):
                    with self.subTest(rejected=image.name),patch.object(codex_cli,'_prepare_cli_image') as prepare:
                        with self.assertRaisesRegex(RuntimeError,'검증된 작업 산출물'):core('fixture','fixture',images=[str(image)],reasoning_effort='low')
                        prepare.assert_not_called()
