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

    def exercise(self, result, references, expected_error=ValueError):
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
             patch('common.runtime_locks.runtime_lock_path',side_effect=lambda path:Path(directory)/path.name), \
             patch('common.llm_client.generate_json', side_effect=decide):
            with self.assertRaises(expected_error):
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
            {'kind': 'press', 'value': 'Alt+F4', 'x': 480, 'y': 480}]}, [],expected_error=TimeoutError)

    def test_unrelated_system_clipboard_is_never_read_or_pasted(self):
        with patch('common.ego_screen.subprocess.check_output') as clipboard:
            self.exercise({'message': 'paste', 'done': False, 'observations': [], 'actions': [
                {'kind': 'press', 'value': 'Control+V', 'x': 480, 'y': 480}]}, [],expected_error=TimeoutError)
        clipboard.assert_not_called()

    def test_enter_cannot_trigger_a_focused_registration_button(self):
        self.exercise({'message':'press','done':False,'observations':[],'actions':[
            {'kind':'press','value':'Enter','x':480,'y':480}]},[])

    def test_clipboard_uses_verified_browser_display_and_redacts_process_output(self):
        import subprocess
        from common.ego_screen import clipboard_text
        window={'status':'observed','display':':11','browserPid':123}
        with patch('common.ubuntu_naver_browser.inspect_workflow_window',return_value=window), \
             patch('common.ego_screen.subprocess.check_output',return_value=b'approved') as read:
            self.assertEqual(clipboard_text(9334),'approved')
            self.assertEqual(read.call_args.kwargs['env']['DISPLAY'],':11')
        with patch('common.ubuntu_naver_browser.inspect_workflow_window',return_value=window), \
             patch('common.ego_screen.subprocess.check_output',side_effect=subprocess.CalledProcessError(1,['xclip'],output=b'PRIVATE',stderr=b'PRIVATE')):
            with self.assertRaises(RuntimeError) as raised:clipboard_text(9334)
        self.assertNotIn('PRIVATE',str(raised.exception)+str(raised.exception.clipboard_diagnostic))
        self.assertEqual(raised.exception.clipboard_diagnostic['display'],':11')

    def interrupted_clipboard(self, actual='one three', key='Control+X'):
        from common.ego_screen import reconcile_interrupted_clipboard
        page=Mock();page.frame.return_value=page
        page.context.new_cdp_session.return_value.send.return_value={'targetInfo':{'targetId':'owned'}}
        def component(text):return {'@ctype':'text','value':[{'@ctype':'paragraph','nodes':[{'value':text}]}]}
        page.evaluate.return_value={'document':{'components':[component('Title'),component(actual)]}}
        state={'editorTargetId':'owned','written':['title','block-0'],'turns':[{'turn':1,'completedActions':0,'actions':[{'kind':'press','value':key},{'kind':'press','value':'Control+V'}]}]}
        refs=[{'ref':'title','kind':'write','text':'Title'},{'ref':'block-0','kind':'write','text':'one two three'}]
        return reconcile_interrupted_clipboard,page,state,refs

    def test_interrupted_cut_reconciles_real_missing_text_without_cut_or_paste_replay(self):
        reconcile,page,state,refs=self.interrupted_clipboard()
        with patch('common.ego_screen.clipboard_text',return_value='two'):
            self.assertTrue(reconcile(page,state,refs,9334))
        self.assertEqual(state['turns'][0]['completedActions'],1)
        self.assertEqual(len(state['turns'][0]['rejectedActions']),1)
        self.assertIn('clipboardTextSha256',state)
        page.keyboard.press.assert_not_called()

    def test_interrupted_cut_with_unrelated_clipboard_never_modifies_editor(self):
        reconcile,page,state,refs=self.interrupted_clipboard()
        with patch('common.ego_screen.clipboard_text',return_value='PRIVATE'):
            with self.assertRaises(RuntimeError):reconcile(page,state,refs,9334)
        page.keyboard.press.assert_not_called()

    def test_interrupted_copy_without_editor_change_is_discarded_safely(self):
        reconcile,page,state,refs=self.interrupted_clipboard(actual='one two three',key='Control+C')
        self.assertTrue(reconcile(page,state,refs,9334))
        self.assertEqual(len(state['turns'][0]['rejectedActions']),2)
        self.assertNotIn('clipboardTextSha256',state)
        page.keyboard.press.assert_not_called()

    def test_editor_selection_reads_focused_input_buffer_and_ignores_editor_caret_markers(self):
        from common.ego_screen import focused_editor_selection
        page=Mock();page.url='https://blog.naver.com/owned'
        outer=Mock();inner=Mock();inner.url='https://blog.naver.com/PostWriteForm.naver'
        page.frame.return_value=outer
        outer.evaluate_handle.return_value.as_element.return_value.evaluate.return_value='IFRAME'
        outer.evaluate_handle.return_value.as_element.return_value.content_frame.return_value=inner
        inner.evaluate_handle.return_value.as_element.return_value.evaluate.return_value='BODY'
        inner.evaluate.return_value='\ufeffapproved\ufeff'
        self.assertEqual(focused_editor_selection(page),'approved')
        self.assertTrue(approved_clipboard_text('\ufeffapproved\ufeff',[{'text':'approved'}]))
        inner.url='https://unrelated.example/frame'
        with self.assertRaises(RuntimeError):focused_editor_selection(page)
