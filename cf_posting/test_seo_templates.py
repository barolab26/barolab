import unittest

from cf_posting.seo_templates import ROBOTS, patch_post_template, preserved_metadata, verify_worker_route


TEMPLATE = '''const privatePage = '<meta name="robots" content="noindex" />';
const cache = "_baro_v=old";
function renderPostPage(settings, post) {
return `<head><meta name="viewport" content="width=device-width, initial-scale=1" />
${JSON.stringify({"@type": "BlogPosting", "headline": post.title})}</head>`;
}
__name(renderPostPage, "renderPostPage");
'''


class PostSeoTests(unittest.TestCase):
    def test_domain_identity_and_deployment_routes_agree(self):
        from cf_posting.domain_themes import DOMAIN_IDENTITY_SPECS, DOMAIN_WORKER_NAMES
        self.assertEqual(DOMAIN_WORKER_NAMES['must-pick.com'], 'mustpick')
        self.assertEqual(DOMAIN_WORKER_NAMES['nolplace.com'], 'panda-01')
        for domain, worker in DOMAIN_WORKER_NAMES.items():
            self.assertEqual(DOMAIN_IDENTITY_SPECS[domain]['workerName'], worker)

    def test_patch_is_scoped_and_idempotent(self):
        patched = patch_post_template(TEMPLATE)
        self.assertIn('content="noindex"', patched)
        self.assertIn(ROBOTS, patched)
        self.assertEqual(patched, patch_post_template(patched))
        self.assertEqual(patched.count('"@type": "BlogPosting"'), 1)
        self.assertNotIn('"@type": "FAQPage"', patched)

    def test_intentional_noindex_post_refused(self):
        source = TEMPLATE.replace('</head>', '<meta name="robots" content="noindex" /></head>')
        with self.assertRaisesRegex(ValueError, "noindex"):
            patch_post_template(source)

    def test_both_existing_public_post_variants(self):
        source = TEMPLATE.replace('</head>', '</head><meta name="viewport" content="width=device-width, initial-scale=1" />')
        patched = patch_post_template(source)
        self.assertEqual(patched.count(ROBOTS), 2)
        self.assertEqual(patched, patch_post_template(patched))

    def test_unknown_renderer_refused(self):
        with self.assertRaises(ValueError):
            patch_post_template(TEMPLATE.replace('"BlogPosting"', '"Product"'))

    def test_unbundled_worker_retains_compact_schema_and_busts_cache(self):
        source = TEMPLATE.replace('__name(renderPostPage, "renderPostPage");',
                                  'function injectMidAd(content) { return content; }')
        source = source.replace('"@type": "BlogPosting"', '"@type":"BlogPosting"')
        source += '\nconst key = new Request(url.toString(), { method: "GET" });'
        patched = patch_post_template(source)
        self.assertIn(ROBOTS, patched)
        self.assertIn('url.search ? "&" : "?"', patched)
        self.assertEqual(patched, patch_post_template(patched))

    def test_wrong_worker_route_fails_before_deployment(self):
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return {"result": [{"id": "zone", "pattern": "www.must-pick.com/*", "script": "mustpick"}]}
        class Session:
            def get(self, *args, **kwargs):
                return Response()
        with self.assertRaisesRegex(ValueError, "differs"):
            verify_worker_route('must-pick.com', 'shopbest', session=Session(), account='account')
        self.assertTrue(verify_worker_route('must-pick.com', 'mustpick', session=Session(), account='account')["verified"])

    def test_bindings_and_runtime_preserved_without_secret_values(self):
        result = preserved_metadata({"compatibility_date": "2025-10-01",
            "compatibility_flags": ["nodejs_compat"], "bindings": [
                {"type": "secret_text", "name": "SECRET", "text": "never-copy"},
                {"type": "d1", "id": "db"}]})
        self.assertEqual(result["keep_bindings"], ["d1", "secret_text"])
        self.assertEqual(result["compatibility_flags"], ["nodejs_compat"])
        self.assertNotIn("never-copy", str(result))


if __name__ == "__main__":
    unittest.main()
