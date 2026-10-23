import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from common.ego_screen import approved_clipboard_text, run, screen_point


class EgoScreenTests(unittest.TestCase):
    def test_padded_vision_coordinates_map_to_observed_viewport(self):
        self.assertEqual(screen_point(480, 480, 1280, 960), (640, 480))
        with self.assertRaises(ValueError):
            screen_point(480, 1, 1280, 960)

    def test_only_approved_editor_text_or_trial_can_become_pasteable(self):
        refs = [{'ref': 'block-0', 'text': '목차\n1. 신청 대상\n2. 신청 방법'}]
        self.assertTrue(approved_clipboard_text('목차\r\n1. 신청 대상', refs))
        self.assertTrue(approved_clipboard_text('목차\n목차', refs))
        self.assertFalse(approved_clipboard_text('unrelated-secret-token', refs))
        self.assertFalse(approved_clipboard_text('', refs))

    def exercise(self, result, references):
        from PIL import Image
        page = Mock()
        page.url = 'https://blog.naver.com/mustpickinfo?Redirect=Write'
        page.context.pages = [page]
        page.context.new_cdp_session.return_value.send.return_value = {'targetInfo': {'targetId': 'fixture-target'}}
        page.screenshot.side_effect = lambda path: Image.new('RGB', (1280, 960)).save(path)
        def decide(*args, **kwargs):
            self.assertTrue(Path(kwargs['images'][0]).is_file())
            kwargs['observer']('codex', 'test-model', 'returned', actual_model='observed-test-model')
            return result
        with tempfile.TemporaryDirectory() as directory, \
             patch('common.ubuntu_naver_browser.focus_workflow_window'), \
             patch('common.llm_client.generate_json', side_effect=decide):
            with self.assertRaises(ValueError):
                run(page, port=9334, folder=directory, goal='test', references=references, max_turns=1)
        page.keyboard.type.assert_not_called()
        page.keyboard.press.assert_not_called()

    def test_model_cannot_type_unapproved_or_duplicate_reference(self):
        self.exercise({'message': 'type', 'done': False, 'observations': [], 'actions': [
            {'kind': 'write', 'value': 'wrong', 'x': 480, 'y': 480}]},
            [{'kind': 'write', 'ref': 'title', 'text': 'Approved title'}])

    def test_model_cannot_claim_completion_before_all_inputs(self):
        self.exercise({'message': 'done', 'done': True, 'observations': [], 'actions': []},
                      [{'kind': 'write', 'ref': 'title', 'text': 'Approved title'}])

    def test_arbitrary_shortcuts_are_rejected(self):
        self.exercise({'message': 'press', 'done': False, 'observations': [], 'actions': [
            {'kind': 'press', 'value': 'Alt+F4', 'x': 480, 'y': 480}]}, [])

    def test_unrelated_system_clipboard_is_never_read_or_pasted(self):
        with patch('common.ego_screen.subprocess.check_output') as clipboard:
            self.exercise({'message': 'paste', 'done': False, 'observations': [], 'actions': [
                {'kind': 'press', 'value': 'Control+V', 'x': 480, 'y': 480}]}, [])
        clipboard.assert_not_called()

    def test_enter_cannot_trigger_a_focused_registration_button(self):
        self.exercise({'message':'press','done':False,'observations':[],'actions':[
            {'kind':'press','value':'Enter','x':480,'y':480}]},[])
