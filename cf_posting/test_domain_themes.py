"""Regression contracts for the generated list-layout CSS.

Selector matching uses the actual list/article DOM shapes. Browser checks verify
rendering; these tests guard regeneration and cascade.
"""

import json
import re
import shutil
import subprocess
import unittest

from bs4 import BeautifulSoup

from cf_posting.domain_themes import (
    DOMAIN_IDENTITY_SPECS,
    build_live_cf_head_injection,
    defer_ad_push_until_layout_ready,
    generate_domain_css,
)


class SidebarListLayoutTests(unittest.TestCase):
    DOMAINS = {
        "must-good.com": "300px minmax(0, 1fr)",
        "daynote.kr": "minmax(0, 1fr) 300px",
        "topnote.kr": "250px minmax(0, 1fr) 250px",
        "maxnote.kr": "250px minmax(0, 1fr) 250px",
    }
    MARKER = "/* BAROLAB_SIDEBAR_LIST_LAYOUT_V1:"

    @classmethod
    def setUpClass(cls):
        cls.styles = {
            domain: generate_domain_css(domain) for domain in DOMAIN_IDENTITY_SPECS
        }

    def override(self, domain):
        css = self.styles[domain]
        self.assertEqual(css.count(self.MARKER), 1)
        override = css[css.index(self.MARKER):]
        media = re.search(r"@media\s*\(min-width:\s*(\d+)px\)\s*\{", override)
        self.assertIsNotNone(media)
        rule = re.search(r"([^{}]+)\{([^{}]+)\}", override[media.end():])
        self.assertIsNotNone(rule)
        self.assertRegex(rule[2], r"^\s*display:\s*grid\s*!important;\s*$")
        return int(media[1]), rule[1].strip()

    def test_only_sidebar_lists_match_across_all_domain_themes(self):
        for domain, spec in DOMAIN_IDENTITY_SPECS.items():
            _, selector = self.override(domain)
            for page_type, content in (
                # Home, category and search use this same #postGrid shell.
                ("home", '<section id="postGrid" class="grid"></section>'),
                ("article", '<article class="content">Article</article>'),
            ):
                with self.subTest(domain=domain, page_type=page_type):
                    soup = BeautifulSoup(
                        f'<html><body data-domain="{domain}" '
                        f'data-shell-family="{spec["shellFamily"]}" '
                        f'data-page-type="{page_type}">'
                        '<div class="layout"><aside></aside>'
                        f'<main class="main-area">{content}</main></div>'
                        '</body></html>',
                        "html.parser",
                    )
                    self.assertEqual(
                        bool(soup.select(selector)),
                        domain in self.DOMAINS and page_type == "home",
                    )

    def test_grid_override_wins_over_later_shared_card_block_rule(self):
        # These selectors all have specificity (1 ID, 3 classes/attrs, 2 tags).
        # The later equally-important rule must win, not only exist earlier.
        for domain in self.DOMAINS:
            with self.subTest(domain=domain):
                css = self.styles[domain]
                _, selector = self.override(domain)
                for item in selector.split(","):
                    self.assertEqual(item.count("#postGrid"), 1)
                    self.assertEqual(item.count("["), 2)
                    self.assertEqual(item.count(".layout"), 1)
                    self.assertTrue(item.strip().startswith("html body["))
                shared_start = css.index("/* BAROLAB_VERTICAL_CARDS_V3:")
                shared_end = css.index(self.MARKER)
                self.assertGreater(shared_end, shared_start)
                shared = css[shared_start:shared_end]
                self.assertRegex(
                    shared,
                    r'html body\[data-shell-family\]\[data-domain\] '
                    r'\.layout:has\(#postGrid\),[\s\S]*?'
                    r'\{\s*display:\s*block\s*!important;',
                )
                # No subsequent block display may undo the repair.
                self.assertNotRegex(css[shared_end:], r"display:\s*block")

    def test_desktop_keeps_original_column_order_and_widths(self):
        for domain, columns in self.DOMAINS.items():
            with self.subTest(domain=domain):
                css = self.styles[domain]
                self.assertIn(f"grid-template-columns: {columns} !important;", css)
                self.override(domain)

    def test_mobile_boundary_preserves_single_column_and_hidden_sidebars(self):
        for domain in self.DOMAINS:
            with self.subTest(domain=domain):
                minimum, _ = self.override(domain)
                self.assertEqual(minimum, 1061)
                for width in (375, 639, 1023, 1060):
                    self.assertLess(width, minimum)
                self.assertGreaterEqual(1061, minimum)
                css = self.styles[domain]
                mobile = css[css.index("@media (max-width: 1060px)"):]
                self.assertRegex(
                    mobile,
                    r"html body\[data-shell-family\] \.layout\s*\{\s*"
                    r"display:\s*block\s*!important;\s*"
                    r"grid-template-columns:\s*minmax\(0, 1fr\)\s*!important;",
                )
                self.assertRegex(
                    mobile,
                    r"\.wt-share-col, \.wt-ranking-col, [^{]+"
                    r"\.msdocs-tree-sidebar, \.msdocs-minimap-aside, [^{]+"
                    r"\.layout > aside\s*\{\s*display:\s*none\s*!important;",
                )


class AdLayoutTimingTests(unittest.TestCase):
    SNIPPET = (
        '<script async src="https://example.invalid/adsbygoogle.js"></script>\n'
        '<!-- existing responsive slot -->\n'
        '<ins class="adsbygoogle" style="display:block" data-ad-client="ca-pub-123" '
        'data-ad-slot="456" data-ad-format="auto" data-full-width-responsive="true"></ins>\n'
        '<script>\n     (adsbygoogle = window.adsbygoogle || []).push({});\n</script>'
    )

    def test_preserves_original_ad_code_and_is_idempotent(self):
        wrapped = defer_ad_push_until_layout_ready(self.SNIPPET)
        self.assertEqual(defer_ad_push_until_layout_ready(wrapped), wrapped)
        before = BeautifulSoup(self.SNIPPET, "html.parser")
        after = BeautifulSoup(wrapped, "html.parser")
        self.assertEqual(str(before.ins), str(after.ins))
        self.assertEqual(str(before.script), str(after.script))
        original_push = before.find_all("script")[-1].string
        self.assertIn("function requestAd() {" + original_push + "}", wrapped)
        # Everything outside the single inline push script remains byte-for-byte.
        self.assertEqual(
            self.SNIPPET[:self.SNIPPET.rindex("<script>")],
            wrapped[:wrapped.rindex("<script>")],
        )

    def test_unknown_adsense_push_fails_closed_and_non_ad_code_is_unchanged(self):
        unknown = "<script>window.adsbygoogle.push(customConfiguration);</script>"
        for snippet in (unknown, self.SNIPPET + unknown):
            with self.subTest(mixed=snippet != unknown):
                with self.assertRaisesRegex(ValueError, "Unsupported AdSense"):
                    defer_ad_push_until_layout_ready(snippet)
        with self.assertRaisesRegex(ValueError, "Malformed AdSense"):
            defer_ad_push_until_layout_ready(
                "<script>(adsbygoogle = window.adsbygoogle || []).push({});"
            )
        ordinary = "<script>analytics.push({event:'view'});</script>"
        self.assertEqual(defer_ad_push_until_layout_ready(ordinary), ordinary)

    @unittest.skipUnless(shutil.which("node"), "Node is needed for JavaScript execution")
    def test_actual_generated_listeners_request_each_ad_once_after_layout(self):
        head = BeautifulSoup(build_live_cf_head_injection("must-good.com", ""), "html.parser")
        enhancer = head.find_all("script")[-1].string
        registration = re.search(
            r"if \(document.readyState === 'loading'\) \{\s*"
            r"document.addEventListener\('DOMContentLoaded', applyBaro8ArchitectureDOM\);"
            r"\s*\} else \{\s*applyBaro8ArchitectureDOM\(\);\s*\}",
            enhancer,
        )
        self.assertIsNotNone(registration)
        script = BeautifulSoup(
            defer_ad_push_until_layout_ready(self.SNIPPET), "html.parser"
        ).find_all("script")[-1].string
        harness = r"""
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const order = [], listeners = [];
const context = {
  document: {
    readyState: input.state,
    addEventListener: (type, callback, options) => listeners.push({type, callback, options})
  },
  window: {adsbygoogle: {push: () => order.push('ad')}},
  applyBaro8ArchitectureDOM: () => order.push('layout')
};
vm.runInNewContext(input.registration, context);
for (let i = 0; i < input.count; i++) vm.runInNewContext(input.script, context);
const beforeReady = order.slice();
if (input.state === 'loading') {
  for (const listener of listeners) listener.callback();
}
process.stdout.write(JSON.stringify({
  beforeReady, order,
  adListenersOnce: listeners.slice(1).every(x => x.type === 'DOMContentLoaded' && x.options.once)
}));
"""
        for state in ("loading", "complete"):
            for count in (2, 3):  # Two list slots, plus the article's middle slot.
                with self.subTest(state=state, count=count):
                    result = subprocess.run(
                        [shutil.which("node"), "-e", harness],
                        input=json.dumps({
                            "state": state, "count": count, "script": script,
                            "registration": registration[0],
                        }),
                        encoding="utf-8", capture_output=True, check=True,
                    )
                    observed = json.loads(result.stdout)
                    self.assertEqual(observed["order"], ["layout"] + ["ad"] * count)
                    self.assertTrue(observed["adListenersOnce"])
                    if state == "loading":
                        self.assertEqual(observed["beforeReady"], [])


class MobileNewsHeaderTests(unittest.TestCase):
    def test_mobile_brand_spans_controls_and_search_can_shrink(self):
        fixture = BeautifulSoup(
            '<div class="wt-header-main"><div id="menu"><button>☰ 전체섹션</button></div>'
            '<div class="wt-brand-center"><a class="wt-brand-logo">머스트굿 정책뉴스</a>'
            '<span class="wt-brand-sub">MUSTGOOD POLICY NEWS</span></div>'
            '<form><div><input style="width:110px"><button>🔍</button></div></form></div>',
            "html.parser",
        )
        expected = {
            ".wt-header-main": ("div", ("grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)",)),
            ".wt-header-main > .wt-brand-center": ("div", ("grid-column: 1 / -1", "grid-row: 1")),
            ".wt-header-main > :first-child": ("div", ("grid-column: 1", "grid-row: 2")),
            ".wt-header-main > form": ("form", ("grid-column: 2", "grid-row: 2", "min-width: 0")),
            ".wt-header-main .wt-brand-logo": ("a", ("white-space: nowrap", "font-size: clamp(")),
            ".wt-header-main form > div": ("div", ("max-width: 100%", "box-sizing: border-box")),
            ".wt-header-main input": ("input", ("min-width: 0",)),
        }
        for domain in ("must-good.com", "daynote.kr"):
            with self.subTest(domain=domain):
                css = generate_domain_css(domain)
                mobile = css[css.index("/* BAROLAB_MOBILE_NEWS_HEADER_V1:"):]
                self.assertIn("@media (max-width: 760px)", mobile)
                rules = dict(re.findall(r"([^{}]+)\{([^{}]+)\}", mobile))
                rules = {selector.strip(): declarations for selector, declarations in rules.items()}
                for selector, (tag, declarations) in expected.items():
                    matches = fixture.select(selector)
                    self.assertEqual(len(matches), 1)
                    self.assertEqual(matches[0].name, tag)
                    for declaration in declarations:
                        self.assertIn(declaration, rules[selector])

    def test_desktop_and_other_header_families_keep_existing_rules(self):
        for domain, spec in DOMAIN_IDENTITY_SPECS.items():
            with self.subTest(domain=domain):
                css = generate_domain_css(domain)
                mobile = css[css.index("/* BAROLAB_MOBILE_NEWS_HEADER_V1:"):]
                self.assertEqual(mobile.count("@media"), 1)
                self.assertTrue(mobile.rstrip().endswith("}"))
                if spec["shellFamily"] == "arch1-wikitree":
                    self.assertIn("grid-template-columns: 160px 1fr 220px;", css)
                for selector in (".msdocs-header", ".msdocs-header-in", ".layout"):
                    self.assertNotIn(selector, mobile)


@unittest.skipUnless(shutil.which("node"), "Node is needed for JavaScript execution")
class PublishedArticleLinkTests(unittest.TestCase):
    def execute(self, payload):
        enhancer = BeautifulSoup(
            build_live_cf_head_injection("must-good.com", ""), "html.parser"
        ).find_all("script")[-1].string
        functions = enhancer[
            enhancer.index("/* BAROLAB_PUBLISHED_ARTICLE_LINKS_V1 */"):
            enhancer.index("  function cleanHeadingText")
        ]
        payload.update(functions=functions, enhancer=enhancer)
        harness = r"""
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
new vm.Script(input.enhancer);
const calls = [];
const containers = (input.containers || []).map(attrs => ({
  attrs, innerHTML: '', textContent: '',
  getAttribute(key) { return this.attrs[key] || null; },
  hasAttribute(key) { return key in this.attrs; },
  setAttribute(key, value) { this.attrs[key] = value; }
}));
const context = {
  CFG: {h2IconBadge: '✨'}, window: {location: {pathname: input.path || '/current'}},
  document: {querySelectorAll: () => containers},
  fetch: async (url, options) => {
    calls.push({url, options});
    if (input.networkError) throw new Error('offline');
    return {ok: true, json: async () => {
      if (!input.response || !Array.isArray(input.response.posts)) return input.response;
      const limit = Number(new URL(url, 'https://example.test').searchParams.get('limit'));
      return {...input.response, posts: input.response.posts.slice(0, limit)};
    }};
  }
};
vm.createContext(context);
vm.runInContext(input.functions, context);
(async () => {
  await context.hydratePublishedArticleLists();
  await context.hydratePublishedArticleLists();
  process.stdout.write(JSON.stringify({calls, containers}));
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", harness], input=json.dumps(payload),
            encoding="utf-8", capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def response(self, posts):
        return {"success": True, "sort": "views", "posts": posts}

    def test_renders_real_safe_links_and_escapes_titles_in_every_list_style(self):
        title = '<img src=x onerror="bad()"> Actual & "title"'
        posts = [
            {"status": "published", "slug": "current", "title": "Current"},
            {"status": "published", "slug": "real-guide", "title": title, "category": "<svg>"},
            {"status": "scheduled", "slug": "already-due", "title": "Public due scheduled"},
        ]
        result = self.execute({
            "response": self.response(posts),
            "containers": [
                {"data-published-article-list": kind, "data-article-category": "Guide"}
                for kind in ("top10", "columns", "docs", "health", "cards")
            ],
        })
        for container in result["containers"]:
            kind = container["attrs"]["data-published-article-list"]
            soup = BeautifulSoup(container["innerHTML"], "html.parser")
            self.assertIsNone(soup.find("img"))
            self.assertIsNone(soup.find("svg"))
            self.assertEqual(soup.select_one('a[href="/real-guide"]').get_text(strip=True).count(title), 1)
            hrefs = [a["href"] for a in soup.find_all("a")]
            self.assertIn("/already-due", hrefs)
            self.assertEqual("/current" in hrefs, kind == "top10")
            self.assertTrue(all(h.startswith("/") and not any(c in h for c in "?#") for h in hrefs))
        self.assertEqual(len(result["calls"]), 2)  # Shared global list plus the docs category.
        self.assertTrue(all(c["options"] == {"credentials": "omit"} for c in result["calls"]))

    def test_invalid_missing_external_slugs_and_nonpublic_rows_are_excluded(self):
        posts = [
            {"status": "published", "slug": slug, "title": "Invalid"}
            for slug in ("", None, "../evil", "//evil.test", "https://evil.test", "foo?q=x", "foo#bar", "..")
        ] + [
            {"status": "draft", "slug": "draft", "title": "Draft"},
            {"status": "published", "slug": "valid", "title": ""},
        ]
        result = self.execute({
            "response": self.response(posts), "containers": [{"data-published-article-list": "top10"}],
        })
        self.assertEqual(result["containers"][0]["innerHTML"], "")
        self.assertEqual(result["containers"][0]["attrs"]["data-article-load-state"], "empty")

    def test_api_failure_or_unsupported_sort_has_no_fabricated_fallback(self):
        for data in (
            {"networkError": True},
            {"response": {"success": True, "sort": "recent", "posts": []}},
            {"response": {"success": True, "sort": "views", "posts": None}},
        ):
            result = self.execute({
                **data, "containers": [{"data-published-article-list": "top10"}],
            })
            self.assertEqual(result["containers"][0]["innerHTML"], "")
            self.assertEqual(result["containers"][0]["attrs"]["data-article-load-state"], "error")

    def test_docs_keep_display_counts_when_current_article_ranks_first(self):
        posts = [
            {"status": "published", "slug": slug, "title": slug}
            for slug in ("current", "other-one", "other-two", "other-three")
        ]
        result = self.execute({
            "response": self.response(posts),
            "containers": [
                {"data-published-article-list": "docs", "data-article-category": category}
                for category in ("", "Guide")
            ],
        })
        for container, expected in zip(result["containers"], (["/other-one"], ["/other-one", "/other-two"])):
            soup = BeautifulSoup(container["innerHTML"], "html.parser")
            self.assertEqual([a["href"] for a in soup.find_all("a")], expected)
            self.assertEqual(container["attrs"]["data-article-load-state"], "loaded")

    def test_category_tree_requests_are_bounded_encoded_and_deduplicated(self):
        category = "윈도우·맥 설정"
        result = self.execute({
            "response": self.response([]),
            "containers": [
                {"data-published-article-list": "docs", "data-article-category": cat}
                for cat in ("", category, category)
            ],
        })
        self.assertEqual(len(result["calls"]), 2)
        self.assertIn("limit=2", result["calls"][0]["url"])
        self.assertIn("limit=3", result["calls"][1]["url"])
        from urllib.parse import parse_qs, urlsplit
        self.assertEqual(parse_qs(urlsplit(result["calls"][1]["url"]).query)["cat"], [category])
        absent = self.execute({"response": self.response([]), "containers": []})
        self.assertEqual(absent["calls"], [])


if __name__ == "__main__":
    unittest.main()
