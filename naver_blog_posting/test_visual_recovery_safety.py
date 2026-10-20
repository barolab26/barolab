import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from naver_blog_posting import material_assets as visuals
from naver_blog_posting import recovery_context as recovery

class VisualRecoveryTests(unittest.TestCase):
    def test_generated_alt_preserves_complete_korean_example_description(self):
        from naver_blog_posting.pipeline_runner import complete_image_alt
        caption = "로퍼와 양말 색상 조합을 설명하기 위한 인공지능 생성 예시이며, 바지 밑단 아래로 드러나는 양말의 높이와 신발 색상이 서로 어떻게 연결되는지 비교하도록 만든 그림입니다."
        self.assertEqual(complete_image_alt({}, caption, "generated"), caption)
        supplied = "양말 색상 차이를 설명하는 생성 예시입니다."
        self.assertEqual(complete_image_alt({"alt": supplied}, caption, "generated"), supplied)

    def test_actual_pixels_and_exact_plan_are_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "image.png"
            Image.new("RGB", (8, 8), "red").save(image)
            plan = {"source": "generated", "filename": "image.png", "caption": "Illustration"}
            calls = []
            def judge(request, paths, schema):
                calls.append(paths)
                return {"passed": True, "issues": [], "observation": "A red image"}
            records = visuals.review_visual_groups([plan], [image], judge, {}, root / "reviews", "group")
            self.assertEqual(calls, [[str(image.resolve())]])
            self.assertTrue(Path(records[0]["file"]).is_file())
            self.assertTrue(visuals.verify_visual_records([plan], [image], records))
            with self.assertRaises(ValueError):
                visuals.verify_visual_records([plan], [image], [])
            with self.assertRaises(ValueError):
                visuals.verify_visual_records([{**plan, "caption": "Actual screenshot"}], [image], records)
            Image.new("RGB", (8, 8), "blue").save(image)
            with self.assertRaises(ValueError):
                visuals.verify_visual_records([plan], [image], records)

    def test_rejected_or_fake_images_never_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "image.png"
            Image.new("RGB", (8, 8)).save(path)
            with self.assertRaises(ValueError):
                visuals.review_visual_groups([{}], [path], lambda *a: {"passed": False, "issues": ["mismatch"], "observation": "wrong"}, {}, root, "g")
            rejected = json.loads((root / "g_0.json").read_text())
            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(rejected["review"]["issues"], ["mismatch"])
            with self.assertRaises(ValueError):
                visuals.verify_visual_records([{}], [path], [rejected])
            path.write_text("not an image")
            with self.assertRaises(OSError):
                visuals.review_visual_groups([{}], [path], lambda *a: self.fail("should not call model"), {}, root, "g")
            with self.assertRaises(visuals.MaterialRequired):
                visuals.load_material_manifest("supplied.json", "account", [root])
            with self.assertRaises(visuals.MaterialRequired):
                visuals.bind_material_plans([{"source": "capture"}])

    def test_retry_budget_keeps_unchanged_and_unknown_context(self):
        context = recovery.build_recovery_context("a", {"topic_seed": "one"}, content_quality_sha="a" * 64)
        attempt = {"recoveryContext": context, "runMode": "daily"}
        self.assertFalse(recovery.attempt_context_changed(attempt, context))
        unknown = {"runMode": "catch_up"}
        self.assertEqual(recovery.scoped_automatic_attempts([attempt, unknown, {"runMode": "manual"}], context), [attempt, unknown])
        changed = recovery.build_recovery_context("a", {"topic_seed": "two"}, content_quality_sha="a" * 64)
        self.assertTrue(recovery.attempt_context_changed(attempt, changed))
        self.assertTrue(recovery.question_context_ready(attempt, changed))
        self.assertFalse(recovery.question_context_ready({}, changed))
        self.assertFalse(recovery.material_context_ready(attempt, changed))
        self.assertFalse(recovery.valid_hash("abcdefgh"))
        with self.assertRaises(ValueError):
            recovery.make_planning_reclassification({})

    def test_new_material_requires_known_previous_and_valid_hashes(self):
        before = recovery.build_recovery_context("a")
        packet = {"readerQuestion": "what", "materials": [{"sha256": "f" * 64}]}
        after = recovery.build_recovery_context("a", packet=packet)
        self.assertTrue(recovery.material_context_ready({"recoveryContext": before}, after))
        self.assertFalse(recovery.material_context_ready({}, after))
        self.assertFalse(recovery.material_context_ready({"recoveryContext": after}, after))

if __name__ == "__main__":
    unittest.main()
