"""Google owner operations share the logged-in account's existing report tab."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from common.browser_session import PageScope, reusable_search_console_page


@pytest.mark.parametrize('path', [
    '/search-console?resource_id=https%3A%2F%2Fexample.com',
    '/search-console/performance/search-analytics', '/search-console/sitemaps',
])
def test_existing_report_tab_is_borrowed_and_survives_cleanup(path):
    page = Mock(url='https://search.google.com' + path)
    context = Mock(pages=[page])
    with patch('common.browser_session._deny_downloads_sync'):
        with PageScope() as scope:
            assert scope.acquire(context, reusable_search_console_page) is page
            assert not scope.owns(page)
    context.new_page.assert_not_called()
    page.close.assert_not_called()


@pytest.mark.parametrize('url', [
    'https://search.google.com/search-console/inspect?resource_id=example.com',
    'https://search.google.com.evil.test/search-console',
    'https://blog.naver.com/editor', 'https://accounts.google.com/',
])
def test_pending_inspections_and_other_user_tabs_are_preserved(url):
    assert not reusable_search_console_page(SimpleNamespace(url=url))


def test_missing_report_creates_only_one_owned_tab_and_cleans_up_on_failure():
    existing = Mock(url='https://blog.naver.com/editor')
    context = Mock(pages=[existing])
    with patch('common.browser_session._deny_downloads_sync'):
        with pytest.raises(RuntimeError), PageScope() as scope:
            page = scope.acquire(context, reusable_search_console_page)
            assert scope.owns(page)
            raise RuntimeError('report unavailable')
    context.new_page.assert_called_once_with()
    page.close.assert_called_once_with()
    existing.close.assert_not_called()
