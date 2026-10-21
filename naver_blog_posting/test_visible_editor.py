import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from naver_blog_posting import visible_editor as editor


def paragraph(text, link=None):
    node = {'value': text}
    if link:
        node['link'] = {'@ctype': 'urlLink', 'url': link}
    return {'nodes': [node]}


class VisibleEditorTests(unittest.TestCase):
    def setUp(self):
        from common import ego_telemetry
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        guard = patch.object(ego_telemetry, 'DIRECTORY', Path(temporary.name))
        guard.start(); self.addCleanup(guard.stop)

    def test_ordered_content_links_and_image_captions_must_match(self):
        blocks = [{'kind': 'heading', 'paragraphs': [[{'text': '제목'}]]},
                  {'kind': 'source', 'paragraphs': [[{'text': '공식 근거', 'url': 'https://example.org/source'}]]}]
        plans = [{'afterBlock': 0, 'filename': 'screen.png', 'caption': '실제 공식 화면'}]
        document = {'document': {'components': [
            {'@ctype': 'documentTitle', 'title': [paragraph('승인 제목')]},
            {'@ctype': 'text', 'value': [paragraph('제목'), paragraph('')]},
            {'@ctype': 'image', 'fileName': 'screen.png', 'caption': [paragraph('실제 공식 화면')]},
            {'@ctype': 'text', 'value': [paragraph('공식 근거', 'https://example.org/source')]}]}}
        editor.verify_visible_content(document, '승인 제목', blocks, plans)
        for field in ('caption', 'link', 'order'):
            bad = copy.deepcopy(document)
            if field == 'caption':
                bad['document']['components'][2]['caption'] = [paragraph('다른 캡션')]
            elif field == 'link':
                bad['document']['components'][3]['value'][0]['nodes'][0]['link']['url'] = 'https://example.org/wrong'
            else:
                bad['document']['components'][1:3] = reversed(bad['document']['components'][1:3])
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                editor.verify_visible_content(bad, '승인 제목', blocks, plans)

    def test_sticker_is_allowlisted_ordered_and_plan_is_hash_bound(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'visible-decoration-plan.json'
            value = {'version': 1, 'stickers': [{'afterBlock': 0, 'packCode': 'motion2d_01', 'seq': 19}]}
            path.write_text(json.dumps(value), encoding='utf-8')
            decorations, digest = editor.load_decoration_plan(folder, 1)
            editor.require_decoration_hash(folder, digest)
            doc = {'document': {'components': [
                {'@ctype': 'documentTitle', 'title': [paragraph('제목')]},
                {'@ctype': 'text', 'value': [paragraph('확인')]},
                {'@ctype': 'sticker', 'packCode': 'motion2d_01', 'seq': 19,
                 'thumbnail': {'src': 'https://storep-phinf.pstatic.net/motion2d_01/original_19.png'}}]}}
            blocks = [{'kind': 'paragraph', 'paragraphs': [[{'text': '확인'}]]}]
            editor.verify_visible_content(doc, '제목', blocks, [], decorations)
            with self.assertRaises(RuntimeError):
                editor.verify_visible_content(doc, '제목', blocks, [], [])
            value['stickers'][0]['seq'] = 20
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                editor.load_decoration_plan(folder, 1)
            with self.assertRaises(RuntimeError):
                editor.require_decoration_hash(folder, digest)
            value['stickers'][0]['seq'] = 19
            value['stickers'][0]['url'] = 'https://untrusted.example/'
            path.write_text(json.dumps(value), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                editor.load_decoration_plan(folder, 1)

    def test_repeated_palette_color_selects_first_visible_enabled_exact_value(self):
        frame = Mock()
        frame.locator.return_value.get_attribute.return_value = ''
        profile = {'fontFamily': 'nanumgothic', 'headingSize': 19, 'bodySize': 16,
                   'lineHeight': 2.0, 'headingColor': '#245b12', 'textColor': '#333333'}
        with patch.object(editor, '_option'):
            editor._style(frame, profile, False)
            editor._style(frame, profile, False)
        palette = frame.locator.return_value
        self.assertIn('button.se-color-palette:visible:not(:disabled)',
                      [call.args[0] for call in frame.locator.call_args_list])
        for call in palette.filter.call_args_list:
            pattern = call.kwargs['has_text']
            self.assertIsNotNone(pattern.fullmatch('#333333'))
            self.assertIsNone(pattern.fullmatch('#333334'))
        self.assertEqual(palette.filter.return_value.first.click.call_count, 2)
        palette.filter.return_value.click.assert_not_called()

    def test_visible_typing_is_sequential_and_document_api_is_read_only(self):
        blocks = [{'kind': 'heading', 'paragraphs': [[{'text': '먼저 확인'}]]},
                  {'kind': 'paragraph', 'paragraphs': [[{'text': '한글 본문 확인'}]]}]
        page, frame = Mock(), Mock()
        frame.evaluate.return_value = {'document': {'components': [
            {'@ctype': 'documentTitle', 'title': [paragraph('글 제목')]},
            {'@ctype': 'text', 'value': [paragraph('먼저 확인'), paragraph('한글 본문 확인')]}]}}
        profile = {'headingGapLines': 2, 'paragraphGapLines': 1}
        with tempfile.TemporaryDirectory() as folder, patch.object(editor, '_style') as style:
            editor.write_visible_editor(page, frame, '글 제목', blocks, [], Path(folder), profile)
            self.assertEqual([call.args[0] for call in page.keyboard.type.call_args_list],
                             ['글 제목', '먼저 확인', '한글 본문 확인'])
            self.assertTrue(all(call.kwargs['delay'] == 25 for call in page.keyboard.type.call_args_list))
            self.assertEqual([call.args[2] for call in style.call_args_list], [True, False])
            frame.evaluate.assert_called_once_with(editor.READ_DOCUMENT)
            self.assertTrue((Path(folder) / 'visible-editor-progress.json').exists())
            page.keyboard.insert_text.assert_not_called()

    def test_last_keyboard_commit_is_reobserved_without_retyping(self):
        blocks = [{'kind': 'paragraph', 'paragraphs': [[{'text': '한글 본문'}]]}]
        ready = {'document': {'components': [
            {'@ctype': 'documentTitle', 'title': [paragraph('제목')]},
            {'@ctype': 'text', 'value': [paragraph('한글 본문')]}]}}
        page, frame = Mock(), Mock()
        frame.evaluate.side_effect = [{'document': {'components': []}}, ready]
        with tempfile.TemporaryDirectory() as folder, patch.object(editor, '_style'):
            editor.write_visible_editor(page, frame, '제목', blocks, [], folder, {})
        self.assertEqual(frame.evaluate.call_count, 2)
        self.assertEqual([call.args[0] for call in page.keyboard.type.call_args_list], ['제목', '한글 본문'])
        page.wait_for_timeout.assert_called_once_with(500)
        frame.evaluate.side_effect = None
        frame.evaluate.return_value = {'document': {'components': []}}
        with tempfile.TemporaryDirectory() as folder, patch.object(editor, '_style'):
            with self.assertRaises(RuntimeError):
                editor.write_visible_editor(page, frame, '제목', blocks, [], folder, {})
            self.assertTrue((Path(folder) / 'visible-editor-mismatch.json').exists())
        self.assertEqual(frame.evaluate.call_count, 13)

    def test_image_caption_and_link_follow_approved_top_down_order(self):
        from unittest.mock import MagicMock
        blocks = [{'kind': 'paragraph', 'paragraphs': [[{'text': '사진 앞 본문'}]]},
                  {'kind': 'source', 'paragraphs': [[{'text': '공식 근거', 'url': 'https://example.org/source'}, {'text': ' 다음 설명'}]]}]
        plans = [{'afterBlock': 0, 'filename': 'screen.png', 'caption': '실제 공식 화면'}]
        page, frame = MagicMock(), MagicMock()
        frame.get_by_text.return_value.count.return_value = 0
        frame.evaluate.return_value = {'document': {'components': [
            {'@ctype': 'documentTitle', 'title': [paragraph('글 제목')]},
            {'@ctype': 'text', 'value': [paragraph('사진 앞 본문')]},
            {'@ctype': 'image', 'fileName': 'screen.png', 'caption': [paragraph('실제 공식 화면')]},
            {'@ctype': 'text', 'value': [{'nodes': [
                {'value': '공식 근거', 'link': {'@ctype': 'urlLink', 'url': 'https://example.org/source'}},
                {'value': ' 다음 설명'}]}]}]}}
        profile = {'headingGapLines': 2, 'paragraphGapLines': 1}
        with tempfile.TemporaryDirectory() as folder, patch.object(editor, '_style'):
            editor.write_visible_editor(page, frame, '글 제목', blocks, plans, Path(folder), profile)
        self.assertEqual([call.args[0] for call in page.keyboard.type.call_args_list],
                         ['글 제목', '사진 앞 본문', '실제 공식 화면', '공식 근거', 'https://example.org/source', ' 다음 설명'])
        presses = [call.args[0] for call in page.keyboard.press.call_args_list]
        self.assertEqual(presses[1:4], ['ArrowDown', 'End', 'Enter'])
        self.assertEqual(presses.count('Shift+ArrowLeft'), len('공식 근거'))
        self.assertIn('ArrowRight', presses)
        frame.evaluate.assert_called_once_with(editor.READ_DOCUMENT)
        page.keyboard.insert_text.assert_not_called()


if __name__ == '__main__':
    unittest.main()
