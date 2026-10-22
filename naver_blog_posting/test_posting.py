"""Canonical publishing entry point and legacy import compatibility."""
import importlib
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class PostingEntryPointTests(unittest.TestCase):
    def test_canonical_entry_point_compiles(self):
        path = Path(__file__).with_name("posting.py")
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_legacy_import_forwards_without_running_publication(self):
        legacy = importlib.import_module("naver_blog_posting.pipeline_runner")
        canonical = importlib.import_module("naver_blog_posting.posting")
        self.assertIs(legacy, canonical)



import copy, hashlib, os, tempfile, json
from contextlib import contextmanager
from naver_blog_posting.posting import validate_document, validate_editor, render_document, document_fingerprint

RAW = b"\xff\xd8\xfffixture"

SHA = hashlib.sha256(RAW).hexdigest()

@contextmanager
def env():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "one.jpg")
        with open(p, "wb") as f: f.write(RAW)
        plan = {"version": 1, "main_keyword": "고윤정 파리 사복", "signoff": "오늘도 읽어주셔서 감사해요 :)", "representative_file": "one.jpg", "assets": [{"id": 0, "file": "one.jpg", "description": "낮의 코디", "credit": "고윤정 SNS", "sha256": SHA}]}
        doc = {"title": "고윤정 파리 사복 분석", "published": False, "blocks": [{"type": "text", "text": "도입"}, {"type": "heading", "text": "▼ 낮의 코디"}, {"type": "image", "id": 0, "file": "one.jpg", "alt": "전신 사진", "caption": "낮의 코디｜고윤정 SNS"}, {"type": "text", "text": "A & B 분석"}, {"type": "text", "text": "마무리"}, {"type": "signoff", "text": "오늘도 읽어주셔서 감사해요 :)"}, {"type": "tags", "text": "#고윤정 #파리사복"}]}
        paras = ["도입", "", "▼ 낮의 코디", "", "A & B 분석", "", "마무리", "", "오늘도 읽어주셔서 감사해요 :)", "", "#고윤정 #파리사복"]
        obs = {"title": doc["title"], "paragraphs": [{"text": t, "center": True} for t in paras], "images": [{"file": "one.jpg", "caption": doc["blocks"][2]["caption"], "center": True, "caption_center": True, "complete": True, "uploaded": True, "representative": True}], "saved": True, "publish_button_clicked": False}
        yield td, plan, doc, obs

def test_document_and_render_valid(env):
    td, plan, doc, obs = env
    rep = validate_document(doc, plan, td)
    assert rep["ok"] and not rep["errors"]
    html = render_document(doc, plan, td)
    assert html == render_document(doc, plan, td)
    assert "A &amp; B 분석" in html and html.count('class="gap"') == len(doc["blocks"]) - 1
    assert "<script" not in html and "@font-face" not in html and len(getattr(rep, "review_required", ["rev"])) > 0
    e_rep = validate_editor(obs, doc, plan)
    assert e_rep["ok"] and not e_rep["errors"]

def test_document_mutations(env):
    td, plan, doc, _ = env
    def err(d, p, code, base=td):
        r = validate_document(d, p, base)
        assert not r["ok"] and code in {e if isinstance(e, str) else e["code"] for e in r["errors"]}

    err("not_a_dict", plan, "DOCUMENT")
    bad_plan = copy.deepcopy(plan); bad_plan["version"] = "bad"; err(doc, bad_plan, "PLAN")
    d = copy.deepcopy(doc); d["published"] = "false"; err(d, plan, "PUBLISHED")
    d = copy.deepcopy(doc); d["title"] = " "; err(d, plan, "TITLE")
    d = copy.deepcopy(doc); d["blocks"][0]["text"] = "도입\n \n본문"; err(d, plan, "BLANK_LINES")
    d = copy.deepcopy(doc); d["blocks"][0]["align"] = "diag"; err(d, plan, "BLOCK_FIELDS")
    d = copy.deepcopy(doc); d["blocks"][2]["caption"] = "고윤정 SNS｜고윤정 SNS"; err(d, plan, "CAPTION")
    d = copy.deepcopy(doc); d["blocks"][2]["caption"] = None; err(d, plan, "BLOCK_TEXT")
    d = copy.deepcopy(doc); d["blocks"].append(copy.deepcopy(d["blocks"][2])); err(d, plan, "IMAGE_ORDER")
    d = copy.deepcopy(doc); d["blocks"][2]["file"] = "../one.jpg"; err(d, plan, "IMAGE_ORDER")
    d = copy.deepcopy(doc); d["blocks"].pop(-2); err(d, plan, "CLOSING")
    d = copy.deepcopy(doc); d["blocks"].insert(2, {"type": "heading", "text": "▼ 섹션2"}); err(d, plan, "EMPTY_SECTION")
    d = copy.deepcopy(doc); d["blocks"][0]["text"] = "낮의 코디｜고윤정 SNS 본문"; err(d, plan, "BODY_CAPTION")
    d = copy.deepcopy(doc); d["blocks"][0]["text"] = "<script>alert(1)</script>"; err(d, plan, "UNSAFE_TEXT")

    p = os.path.join(td, "one.jpg")
    with open(p, "wb") as f: f.write(b"corrupt")
    r = validate_document(doc, plan, td)
    assert not r["ok"] and ({"ASSET_HASH", "ASSET_FORMAT"} & {e if isinstance(e, str) else e["code"] for e in r["errors"]})
    os.remove(p)
    err(doc, plan, "ASSET_MISSING")
    with open(p, "wb") as f: f.write(RAW)

def test_editor_mutations(env):
    td, plan, doc, obs = env
    def err(o, code):
        r = validate_editor(o, doc, plan)
        assert not r["ok"] and code in {e if isinstance(e, str) else e["code"] for e in r["errors"]}

    o = copy.deepcopy(obs); o["title"] = "다른 제목"; err(o, "EDITOR_TITLE")
    o = copy.deepcopy(obs); o["paragraphs"][0]["center"] = False; err(o, "TEXT_ALIGN")
    o = copy.deepcopy(obs); o["images"][0]["center"] = False; err(o, "IMAGE_ALIGN")
    o = copy.deepcopy(obs); o["images"][0]["caption_center"] = False; err(o, "CAPTION_ALIGN")
    o = copy.deepcopy(obs); o["images"][0]["file"] = "two.jpg"; err(o, "EDITOR_IMAGES")
    o = copy.deepcopy(obs); o["images"] = []; err(o, "EDITOR_IMAGES")
    o = copy.deepcopy(obs); o["images"][0]["caption"] = "틀린 캡션"; err(o, "EDITOR_CAPTION")
    for flag, code in [("complete", "IMAGE_LOADED"), ("uploaded", "IMAGE_UPLOADED"), ("representative", "REPRESENTATIVE")]:
        o = copy.deepcopy(obs); o["images"][0][flag] = False; err(o, code)
    o = copy.deepcopy(obs); o["saved"] = False; err(o, "NOT_SAVED")
    o = copy.deepcopy(obs); o["publish_button_clicked"] = True; err(o, "PUBLISH_BOUNDARY")
    o = copy.deepcopy(obs); o["paragraphs"].insert(8, {"text": "", "center": True}); o["paragraphs"].insert(8, {"text": "", "center": True}); err(o, "ENDING_GAP")
    o = copy.deepcopy(obs); o["paragraphs"] = [p for p in o["paragraphs"] if p["text"] != ""]; err(o, "ENDING_GAP")
    o = copy.deepcopy(obs); o["paragraphs"][0]["text"] = doc["blocks"][2]["caption"]; err(o, "EDITOR_TEXT")

    for mal in [{"title": doc["title"], "paragraphs": [{"text": None}], "images": obs["images"], "saved": True, "publish_button_clicked": False},
                {"title": doc["title"], "paragraphs": [{"text": {"obj": 1}}], "images": obs["images"], "saved": True, "publish_button_clicked": False},
                {"title": doc["title"], "paragraphs": obs["paragraphs"], "images": [{"file": None}], "saved": True, "publish_button_clicked": False}]:
        r = validate_editor(mal, doc, plan)
        assert not r["ok"] and "OBSERVATION" in {e["code"] for e in r["errors"]}

class PostingChecksTests(unittest.TestCase):
    def test_valid_and_deterministic_render(self):
        with env() as values: test_document_and_render_valid(values)

    def test_invalid_document_and_assets(self):
        with env() as values: test_document_mutations(values)

    def test_invalid_editor_observations(self):
        with env() as values: test_editor_mutations(values)

    def test_different_wording_is_allowed(self):
        with env() as (td, plan, doc, _):
            other = copy.deepcopy(doc)
            other['title'] = '고윤정 파리 사복, 제 눈에 남은 디테일'
            other['blocks'][3]['text'] = '색이 나뉘는 부분이\n저는 먼저 눈에 들어왔어요.'
            self.assertTrue(validate_document(other, plan, td)['ok'])
            self.assertNotEqual(render_document(doc, plan, td), render_document(other, plan, td))

    def test_missing_evidence_fails_closed(self):
        with env() as (_, plan, doc, obs):
            for field, code in [('saved', 'NOT_SAVED'), ('publish_button_clicked', 'PUBLISH_BOUNDARY')]:
                bad = copy.deepcopy(obs); bad.pop(field)
                self.assertIn(code, {e['code'] for e in validate_editor(bad, doc, plan)['errors']})
            for field, code in [('complete', 'IMAGE_LOADED'), ('uploaded', 'IMAGE_UPLOADED'), ('representative', 'REPRESENTATIVE')]:
                bad = copy.deepcopy(obs); bad['images'][0].pop(field)
                self.assertIn(code, {e['code'] for e in validate_editor(bad, doc, plan)['errors']})


class BasicEditorBindingTests(unittest.TestCase):
    def test_standard_blocks_bind_without_review_metadata(self):
        from naver_blog_posting.posting import basic_native_document
        with env() as (_, _, doc, _):
            original = {'document': {'components': [
                {'@ctype': 'documentTitle', 'title': []},
                {'@ctype': 'image', 'fileName': 'server-renamed-upload', 'src': 'https://img.pstatic.net/one.jpg'}]}}
            result = basic_native_document(original, doc)
            components = result['document']['components']
            self.assertEqual(components[0]['title'][0]['nodes'][0]['value'], doc['title'])
            images = [c for c in components if c['@ctype'] == 'image']
            self.assertEqual(len(images), 1)
            self.assertTrue(images[0]['represent'])
            self.assertEqual(images[0]['caption'][0]['nodes'][0]['value'], doc['blocks'][2]['caption'])
            self.assertEqual(len(original['document']['components']), 2)

    def test_missing_upload_is_a_format_error(self):
        from naver_blog_posting.posting import basic_native_document
        with env() as (_, _, doc, _):
            with self.assertRaises(ValueError):
                basic_native_document({'document': {'components': [{'@ctype': 'documentTitle', 'title': []}]}}, doc)

class MidnightReservationTests(unittest.TestCase):
    def test_clock_uses_actual_option_value_for_zero_padded_hours(self):
        from unittest.mock import Mock
        from naver_blog_posting.posting import select_clock_value
        locator=Mock()
        locator.locator.return_value.evaluate_all.return_value=['00','01','02']
        locator.input_value.return_value='00'
        select_clock_value(locator,0)
        locator.select_option.assert_called_once_with('00')
        with self.assertRaises(RuntimeError):select_clock_value(locator,23)

if __name__ == "__main__":
    unittest.main()
