import copy
import tempfile
import unittest
from pathlib import Path
from naver_blog_posting import pipeline_runner as runner


class NativeChecklistTests(unittest.TestCase):
    def test_checklist_survives_preview_native_and_saved_body_hash(self):
        article = {"title": "Socks checklist", "tags": ["#one", "#two", "#three", "#four", "#five"],
            "blocks": [{"kind": "heading", "text": "Before leaving"},
                       {"kind": "checklist", "text": "Check sock height.\n2. Check trouser hem.\n- Check color."},
                       {"kind": "paragraph", "text": "Normal prose remains unchanged."},
                       {"kind": "paragraph", "text": "#one #two #three #four #five"}], "imageSlots": [2]}
        before = copy.deepcopy(article)
        plans = [{"filename": "example.jpg", "source": "generated", "prompt": "socks illustration",
                  "caption": "Illustrative shoe and sock colors", "afterBlock": 2}]
        document = {"document": {"components": [{"@ctype": "documentTitle"},
            {"@ctype": "image", "fileName": "example.jpg"}]}}
        native = runner.native_document(document, article, plans)
        check = native["document"]["components"][2]["value"]
        values = [''.join(n['value'] for n in paragraph['nodes']) for paragraph in check]
        values = [value for value in values if value]
        self.assertEqual(values, ["\u2022 Check sock height.", "2. Check trouser hem.", "- Check color."])
        self.assertEqual(article, before)
        with tempfile.TemporaryDirectory() as temp:
            runner.render_preview(article, plans, Path(temp))
            html = (Path(temp) / "final.html").read_text(encoding="utf-8")
            self.assertIn("<p>\u2022 Check sock height.</p>", html)
            self.assertIn("<p>Normal prose remains unchanged.</p>", html)
        saved = copy.deepcopy(native)
        saved['document']['documentId'] = 'server-assigned'
        self.assertEqual(runner.editor_review_hash(native), runner.editor_review_hash(saved))
        for paragraph in saved['document']['components'][2]['value']:
            for node in paragraph['nodes']:
                node['value'] = node['value'].removeprefix('\u2022 ')
        self.assertNotEqual(runner.editor_review_hash(native), runner.editor_review_hash(saved))

if __name__ == "__main__":
    unittest.main()
