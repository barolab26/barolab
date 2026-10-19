import unittest

from cf_posting.card_layout import CARD_CSS, STYLE_ID, patch_card_head, patch_mustpick_cards
from cf_posting.domain_themes import DOMAIN_IDENTITY_SPECS, DOMAIN_WORKER_NAMES, generate_domain_css


class CardLayoutTests(unittest.TestCase):
    def test_head_preserves_ads_verification_and_scripts(self):
        original = '<meta name="naver-site-verification" content="public-proof"><script src="ads.js"></script><style>.custom{color:red}</style>'
        patched = patch_card_head(original)
        self.assertTrue(patched.startswith(original))
        self.assertEqual(patched.count(f'id="{STYLE_ID}"'), 1)

    def test_owned_style_is_replaced_idempotently(self):
        source = f'<script>safe()</script><style id="{STYLE_ID}">old</style>'
        first = patch_card_head(source)
        self.assertNotIn('>old<', first)
        self.assertEqual(first, patch_card_head(first))
        self.assertEqual(first.count(f'id="{STYLE_ID}"'), 1)

    def test_existing_duplicate_owned_blocks_collapse(self):
        source = f"<style id='{STYLE_ID}'>one</style><meta name='google-site-verification' content='proof'><style id=\"{STYLE_ID}\">two</style>"
        patched = patch_card_head(source)
        self.assertEqual(patched.count(STYLE_ID), 1)
        self.assertIn("content='proof'", patched)

    def test_all_sixteen_generated_themes_end_with_same_contract(self):
        self.assertEqual(len(DOMAIN_IDENTITY_SPECS), 16)
        self.assertEqual(set(DOMAIN_WORKER_NAMES), set(DOMAIN_IDENTITY_SPECS))
        for domain in DOMAIN_IDENTITY_SPECS:
            with self.subTest(domain=domain):
                self.assertTrue(generate_domain_css(domain).endswith(CARD_CSS))

    def test_all_card_variants_override_horizontal_and_hidden_thumb_rules(self):
        self.assertIn(':is(#postGrid, .guide-layout .grid) .card:first-child .card-link', CARD_CSS)
        self.assertIn(':is(#postGrid, .guide-layout .grid) .card.no-image .card-link', CARD_CSS)
        self.assertIn(':is(#postGrid, .guide-layout .grid) .card.no-image .thumb', CARD_CSS)
        self.assertIn('grid-template-columns: none !important', CARD_CSS)
        self.assertIn('aspect-ratio: 16 / 9 !important', CARD_CSS)
        self.assertIn('object-fit: cover !important', CARD_CSS)

    def test_exact_responsive_contract_and_clamps(self):
        for value in ['repeat(3, minmax(0, 1fr))', '(min-width: 640px) and (max-width: 1023px)',
                      'repeat(2, minmax(0, 1fr))', '(max-width: 639px)', 'max-width: 1120px',
                      'gap: 24px', 'gap: 20px', 'gap: 16px', '-webkit-line-clamp: 2', '-webkit-line-clamp: 3']:
            self.assertIn(value, CARD_CSS)

    def test_article_body_and_ad_selectors_are_not_changed(self):
        self.assertNotIn('article.content', CARD_CSS)
        self.assertNotIn('adsbygoogle', CARD_CSS)
        self.assertNotIn('display: none', CARD_CSS)
        self.assertNotIn('position: fixed', CARD_CSS)

    def test_exact_readability_values(self):
        for value in ['padding: 18px 20px', 'gap: 8px', 'font-size: 1.125rem', 'font-weight: 700',
                      'line-height: 1.45', 'max-height: 2.9em', 'font-size: .925rem',
                      'line-height: 1.6', 'color: #475569', 'max-height: 4.8em',
                      'overflow-wrap: break-word', 'border-radius: 12px 12px 0 0', 'flex-shrink: 0']:
            self.assertIn(value, CARD_CSS)
        self.assertNotIn('overflow-wrap: anywhere', CARD_CSS)

    def test_mustpick_unknown_renderer_refuses_changes(self):
        with self.assertRaises(ValueError):
            patch_mustpick_cards('function renderHomePage() {}\n__name(renderHomePage, "renderHomePage");')

    def test_mustpick_patch_does_not_repeat(self):
        original = '/* BAROLAB_MUSTPICK_VERTICAL_CARDS_V1 */\nprotected_auth_and_post_renderer'
        self.assertEqual(patch_mustpick_cards(original), original)

    def test_featured_grid_uses_same_card_and_breakpoint_rules(self):
        self.assertIn(':is(#postGrid, .guide-layout .grid) .card .card-body', CARD_CSS)
        self.assertEqual(CARD_CSS.count(':is(#postGrid.grid, .guide-layout .grid:has(> .card))'), 3)
        self.assertIn('.guide-layout:has(#postGrid) { display: block', CARD_CSS)


if __name__ == '__main__':
    unittest.main()
