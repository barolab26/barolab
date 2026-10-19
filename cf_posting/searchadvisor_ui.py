"""Explicit future visible-UI consumer. Never uses private SearchAdvisor APIs.

Run only on the dedicated soultin host after the current UI operator releases it:
    python -m cf_posting.searchadvisor_ui --apply
CAPTCHA/authentication and incomplete history pause the run; no model solves them.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from cf_posting import searchadvisor as ledger
from common.browser_session import PageScope, _runtime
from dashboard.metrics import collector_lock

BOARD = 'https://searchadvisor.naver.com/console/board'
PROFILE = Path('C:/99_포터블브라우저/CentBrowserPotable_soultin')


def parse_visible_history(rows, text, today):
    """Recent-50 UI proves completeness only if its lower boundary is older."""
    parsed = []
    for row in rows:
        urls = re.findall(r'https?://[^\s<>]+', row)
        date = re.search(r'(?<!\d)(20\d{2}|\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})(?!\d)', row)
        if urls and date:
            # Actual SearchAdvisor uses YY.MM.DD (e.g. 26.10.19).
            # Its one-month history is contemporary: explicit 2000..2099 pivot.
            year = int(date[1]) + (2000 if len(date[1]) == 2 else 0)
            day = datetime(year, int(date[2]), int(date[3])).date().isoformat()
            parsed.append((urls[0], day))
        elif urls:
            raise ValueError('history_date_unconfirmed')
    if not parsed and '데이터가 없습니다' not in text:
        raise ValueError('history_empty_state_unconfirmed')
    if len(parsed) >= 50 and min(day for _, day in parsed) >= today:
        raise ValueError('history_recent_50_truncated')
    return sorted(url for url, day in parsed if day == today)


def paused_reason(text, url=''):
    if '프로그램을 이용한 자동등록을 방지' in text or re.search('captcha', text, re.I):
        return 'blocked_captcha'
    if 'nid.naver.com' in url or ('로그인' in text and '사이트 목록' not in text and '수집 요청' not in text):
        return 'auth_required'
    return None


def _text(page):
    return page.locator('body').inner_text(timeout=15000)


def _check(page):
    reason = paused_reason(_text(page), page.url)
    if reason:
        raise ValueError(reason)


def _history(page, origin):
    page.goto('https://searchadvisor.naver.com/console/site/request/crawl?site=' + quote(origin, safe=''),
              wait_until='domcontentloaded', timeout=45000)
    page.get_by_text('수집 요청 내역', exact=True).wait_for(timeout=20000)
    _check(page)
    text = _text(page)
    rows = page.get_by_role('row').all_inner_texts()
    return parse_visible_history(rows, text, ledger.now()[:10])


def submit_visible(page, url, *, path=ledger.LEDGER, timeout=45):
    """Reservation precedes click. Uncertain clicks retain their daily slot."""
    origin = 'https://' + urlsplit(url).netloc
    _history(page, origin)
    box = page.get_by_role('textbox', name=origin, exact=True)
    box.fill(url)
    _check(page)
    ledger.reserve_crawl(url, path=path)
    try:
        page.get_by_role('button', name='확인', exact=True).click(timeout=15000)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reason = paused_reason(_text(page), page.url)
            if reason:
                ledger.complete_crawl(url, status='blocked_captcha' if reason == 'blocked_captcha' else 'unknown',
                    evidence={'source': 'visible UI', 'reason': reason}, path=path)
                return reason
            rows = page.get_by_role('row').all_inner_texts()
            today_urls = parse_visible_history(rows, _text(page), ledger.now()[:10])
            if url in today_urls:
                ledger.complete_crawl(url, status='request_received', evidence={
                    'source': 'visible request-history row', 'url': url, 'dayKST': ledger.now()[:10]}, path=path)
                return 'request_received'
            page.wait_for_timeout(500)
        raise TimeoutError('visible_result_unconfirmed')
    except Exception as exc:
        ledger.complete_crawl(url, status='unknown', evidence={
            'source': 'visible UI', 'errorType': type(exc).__name__}, path=path)
        return 'unknown'


def run(*, apply=False, path=ledger.LEDGER):
    if not apply:
        return {'status': 'explicit_apply_required', 'submitted': 0}
    with collector_lock(Path(path).with_suffix('.ui.lock')) as acquired:
        if not acquired:
            return {'status': 'account_ui_busy', 'submitted': 0}
        budget = ledger.crawl_budget(path=path)
        if budget['remaining'] == 0:
            return {**budget, 'submitted': 0, 'browserConnected': False}
        # Only attach to a verified existing dedicated profile. Lifecycle startup
        # remains the account's soultin_start_cdp.bat, never arbitrary Chrome.
        _runtime(9334, str(PROFILE / 'chrome.exe'), str(PROFILE / 'User Data'))
        from playwright.sync_api import sync_playwright
        result = {'status': 'paused', 'submitted': 0, 'indexed': None}
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp('http://127.0.0.1:9334')
            if len(browser.contexts) != 1:
                return {**result, 'reason': 'dedicated_context_unconfirmed'}
            with PageScope(on_warning=lambda _: None) as scope:
                page = scope.acquire(browser.contexts[0], lambda p: p.url.rstrip('/') == BOARD)
                result['tabOwned'] = scope.owns(page)
                try:
                    page.goto(BOARD, wait_until='domcontentloaded', timeout=45000)
                    _check(page)
                    text = _text(page)
                    origins = sorted(set(s.strip().rstrip('/') for s in
                        page.get_by_role('link').all_inner_texts() if re.fullmatch(r'https?://[^/\s]+/?', s.strip())))
                    board_rows = page.get_by_role('row').all_inner_texts()
                    all_sites = [u for row in board_rows for u in re.findall(r'https?://[^/\s]+/?', row)]
                    next_buttons = page.get_by_role('button', name=re.compile(r'다음|Next', re.I))
                    has_more = any(next_buttons.nth(i).is_enabled() for i in range(next_buttons.count()))
                    # Board shows up to 100 registrations, with verified sites as
                    # links and unverified sites as plain rows. No fabricated count.
                    if ('사이트 목록' not in text or '100' not in text or not origins
                            or not all_sites or len(all_sites) >= 100 or has_more
                            or not set(origins) <= {x.rstrip('/') for x in all_sites}):
                        raise ValueError('entire_account_site_list_unconfirmed')
                    today_urls = []
                    for origin in origins:
                        today_urls.extend(_history(page, origin))
                    ledger.record_history_baseline(today_urls, scope_sites=origins, complete=True, evidence={
                        'source': 'visible account board and every site history', 'checkedAt': ledger.now(),
                        'siteListComplete': True, 'allHistoryPagesComplete': True}, path=path)
                    state = json.loads(Path(path).read_text(encoding='utf-8'))
                    reserved = {x['url'] for x in state['crawlRequests']}
                    for item in state.get('crawlQueue', []):
                        budget = ledger.crawl_budget(path=path)
                        if budget['remaining'] == 0:
                            return {**result, **budget}
                        url = item['url']
                        if url in reserved or 'https://' + urlsplit(url).netloc not in origins or url in today_urls:
                            continue
                        outcome = submit_visible(page, url, path=path)
                        if outcome != 'request_received':
                            scope.retain(page, 'Submission started; CAPTCHA or result needs review')
                            return {**result, 'reason': outcome}
                        result['submitted'] += 1
                    result['status'] = 'completed'
                except ValueError as exc:
                    # Controlled symbolic reasons only, never raw page/credentials.
                    budget = ledger.crawl_budget(path=path)
                    if budget['remaining'] == 0:
                        result.update(budget)
                    else:
                        result['reason'] = str(exc) if re.fullmatch(r'[a-z_]+', str(exc)) else 'ledger_gate_paused'
                except Exception as exc:
                    result['reason'] = type(exc).__name__
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    print(json.dumps(run(apply=parser.parse_args().apply), ensure_ascii=False))
