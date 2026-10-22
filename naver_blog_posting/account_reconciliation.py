"""Bound historical failure isolation to fresh account evidence, not journal edits."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

BLOGS = {'soultin': 'mustpickinfo', 'soul5373': 'mustinfo',
         'yoon_master': 'yoonviews', 'adinfo0905': 'adinfo0905', 'stone0747': 'stone0747'}
TTL = timedelta(minutes=10)


def failure_identity(row):
    fields = ('account', 'startedAt', 'workerId', 'phase', 'preSubmissionFailure',
              'submissionStarted', 'artifactFolder', 'topic', 'publicationDate',
              'reserveTime', 'scheduledSlot', 'failureReason')
    return hashlib.sha256(json.dumps({k: row.get(k) for k in fields},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def receipt_path(base, account):
    return Path(base) / 'output' / account / 'current-state-reconciliation.json'


def _fresh(value, now, lifetime=TTL):
    observed = datetime.fromisoformat(value)
    return observed.tzinfo is not None and timedelta(0) <= now - observed <= lifetime


def validated_reservation_rows(reservation, blog, now):
    """Validate the existing collector's two complete modern-editor observations."""
    try:
        count, entries = reservation['reservationCount'], reservation['reservations']
        if (not _fresh(reservation['checkedAt'], now)
                or reservation.get('verificationSource') != 'playwright-reservation-list'
                or reservation.get('reservationListComplete') is not True
                or type(count) is not int or count < 0 or not isinstance(entries, list)
                or len(entries) != count or reservation.get('independentReadings') != 2):
            return None
        seen = set()
        for entry in entries:
            title, when = entry['title'], entry['reserveTime']
            if not isinstance(title, str) or not title.strip() or not isinstance(when, str):
                return None
            parsed = datetime.strptime(when, '%Y-%m-%d %H:%M')
            if parsed.strftime('%Y-%m-%d %H:%M') != when or (title, when) in seen:
                return None
            seen.add((title, when))
        counts = reservation['serverCountEvidence']
        if not isinstance(counts, list) or len(counts) != 4:
            return None
        for pass_no in (1, 2):
            for version in ('2', '4'):
                rows = [r for r in counts if r.get('pass') == pass_no
                        and r.get('requestQuery') == {'blogId': [blog], 'editorVersion': [version]}]
                if len(rows) != 1 or type(rows[0].get('totalCount')) is not int or any(rows[0].get(k) != v for k, v in {
                        'blogId': blog, 'httpStatus': 200, 'path': '/PrePostListCount.naver',
                        'isSuccess': True, 'totalCount': count if version == '4' else 0,
                        'requestMethod': 'GET'}.items()):
                    return None
        return entries
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def validated_failures(receipt, account, attempts, target_day, now):
    """Return only exact old terminal failures; any proof problem returns no exemptions."""
    try:
        blog = BLOGS[account]
        if (receipt.get('schema') != 'naver-account-reconciliation-v1'
                or receipt.get('account') != account or receipt.get('blogId') != blog
                or not _fresh(receipt['checkedAt'], now)):
            return set()
        renewal = receipt.get('renewal')
        if renewal:
            bound = [row for row in attempts if row.get('workerId') == renewal.get('workerId')
                     and row.get('account') == account and row.get('startedAt') == renewal.get('startedAt')
                     and row.get('publicationDate') == target_day]
            if (len(bound) != 1 or bound[0].get('phase') not in ('started', 'verified')
                    or not _fresh(receipt['pipelineIdleObservedAt'], datetime.fromisoformat(bound[0]['startedAt']))):
                return set()
        elif not _fresh(receipt['pipelineIdleObservedAt'], now):
            return set()
        cutoff = datetime.fromisoformat(receipt['historicalCutoff'])
        if cutoff.tzinfo is None or cutoff > now or target_day <= cutoff.date().isoformat():
            return set()
        identity = receipt['identity']
        if (identity.get('schema') != 'naver-authenticated-reservation-preflight-v1'
                or identity.get('account') != account or identity.get('blogId') != blog
                or identity.get('authenticatedAccount') != account
                or identity.get('ownerBlogId') != blog or identity.get('identityVerified') is not True
                or not _fresh(identity['checkedAt'], now)):
            return set()
        reservation = receipt['reservation']
        if validated_reservation_rows(reservation, blog, now) is None:
            return set()
        raw = Path(receipt['inventoryFile']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt['inventorySha256']:
            return set()
        inventory = json.loads(raw)['accounts'][account]
        posts = inventory['posts']
        urls = [p['url'] for p in posts]
        if (inventory.get('fullInventoryComplete') is not True
                or not _fresh(inventory['fullCollectedAt'], now, timedelta(hours=24))
                or len(posts) != inventory['total'] or len(set(urls)) != len(posts)
                or any(not url.startswith('https://blog.naver.com/' + blog + '/') for url in urls)):
            return set()
        head = receipt['publicHead']
        if (head.get('blogId') != blog or not _fresh(head['checkedAt'], now)
                or head.get('total') != len(posts)
                or head.get('ids') != [p['url'].rsplit('/', 1)[1] for p in posts[:30]]):
            return set()
        expected = set(receipt['failureIdentities'])
        allowed = set()
        for row in attempts:
            started = datetime.fromisoformat(row['startedAt'])
            if (row.get('account') == account and row.get('phase') == 'failed'
                    and row.get('preSubmissionFailure') is True
                    and not row.get('submissionStarted') and started.tzinfo is not None
                    and started < cutoff and failure_identity(row) in expected):
                intended = (row.get('publicationDate') or str(row.get('reserveTime') or '')[:10])
                if not intended or intended < target_day:
                    allowed.add(failure_identity(row))
        return allowed
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return set()


def read_current_reconciliation(base, account, attempts, target_day, now):
    try:
        receipt = json.loads(receipt_path(base, account).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return set(), []
    allowed = validated_failures(receipt, account, attempts, target_day, now)
    return allowed, receipt['reservation']['reservations'] if allowed else []


def create_receipt(base, account, attempts, preflight, inventory_file, now, worker_id=None):
    """Called only after actual reservation observation; fetch a fresh public head."""
    import re
    import requests
    from common.dashboard_jobs import atomic_text
    from naver_blog_posting.pipeline_runner import pipeline_busy
    busy = pipeline_busy(base)
    prior, bound = None, None
    if busy:
        if not worker_id or not attempts:
            raise RuntimeError('An active publisher requires its exact worker identity')
        bound = attempts[-1]
        if (bound.get('workerId') != worker_id or bound.get('account') != account
                or bound.get('phase') != 'started'):
            raise RuntimeError('Active worker identity or phase mismatch')
        prior = json.loads(receipt_path(base, account).read_text(encoding='utf-8-sig'))
        started = datetime.fromisoformat(bound['startedAt'])
        if prior.get('renewal') or not validated_failures(
                prior, account, attempts, bound['publicationDate'], started):
            raise RuntimeError('Worker did not start within the original idle receipt lifetime')
        if (datetime.fromisoformat(preflight['checkedAt']) <= datetime.fromisoformat(prior['checkedAt'])
                or datetime.fromisoformat(preflight['inventory']['checkedAt']) <= datetime.fromisoformat(prior['checkedAt'])):
            raise RuntimeError('Renewal requires a newly observed account and reservation list')
    elif worker_id:
        raise RuntimeError('Worker renewal requires an active publishing lock')
    blog = BLOGS[account]
    response = requests.get('https://blog.naver.com/PostTitleListAsync.naver',
                            params={'blogId': blog, 'currentPage': 1, 'categoryNo': '', 'countPerPage': 30},
                            headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
    response.raise_for_status()
    head = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', '', response.text))
    if head.get('resultCode') != 'S':
        raise ValueError('Public inventory head failed')
    # Cutoff is the end of yesterday: only strictly earlier terminal failures.
    cutoff = (datetime.fromisoformat(prior['historicalCutoff']) if prior else
              now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1))
    inventory_file = Path(inventory_file).resolve()
    receipt = {'schema': 'naver-account-reconciliation-v1', 'account': account, 'blogId': blog,
               'checkedAt': now.isoformat(),
               'pipelineIdleObservedAt': prior['pipelineIdleObservedAt'] if prior else now.isoformat(),
               'historicalCutoff': cutoff.isoformat(),
               'identity': {key: preflight.get(key) for key in ('schema', 'account', 'blogId',
                            'authenticatedAccount', 'ownerBlogId', 'identityVerified', 'checkedAt')},
               'reservation': preflight['inventory'], 'inventoryFile': str(inventory_file),
               'inventorySha256': hashlib.sha256(inventory_file.read_bytes()).hexdigest(),
               'publicHead': {'blogId': blog, 'checkedAt': now.isoformat(),
                              'total': int(head['totalCount']),
                              'ids': [str(row['logNo']) for row in head['postList']]},
               'failureIdentities': [failure_identity(row) for row in attempts
                                     if row.get('account') == account and row.get('phase') == 'failed'
                                     and row.get('preSubmissionFailure') is True
                                     and not row.get('submissionStarted')
                                     and datetime.fromisoformat(row['startedAt']) < cutoff]}
    target_day = bound['publicationDate'] if bound else now.date().isoformat()
    if bound:
        if set(receipt['failureIdentities']) != set(prior['failureIdentities']):
            raise RuntimeError('Historical failures changed during the active run')
        receipt['renewal'] = {'workerId': worker_id, 'startedAt': bound['startedAt']}
    allowed = validated_failures(receipt, account, attempts, target_day, now)
    if not allowed:
        raise ValueError('Current account evidence did not validate any historical failures')
    path = receipt_path(base, account)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(path, json.dumps(receipt, ensure_ascii=False, indent=2))
    expires = min(now, datetime.fromisoformat(preflight['checkedAt']),
                  datetime.fromisoformat(preflight['inventory']['checkedAt'])) + TTL
    return {'path': str(path), 'isolatedHistoricalFailures': len(allowed), 'expiresAt': expires.isoformat()}


def collect_full_public_inventory(base, account):
    """Reuse a full one-day catalog only when a live head still matches it."""
    import html
    import re
    import time
    from urllib.parse import unquote_plus
    import requests
    from common.dashboard_jobs import atomic_text
    from naver_blog_posting.pipeline_runner import now_kst, parse_naver_post_date
    blog = BLOGS[account]
    now = now_kst()
    path = Path(base) / 'output' / account / 'current-public-inventory.json'

    def fetch(page):
        response = requests.get('https://blog.naver.com/PostTitleListAsync.naver',
                                params={'blogId': blog, 'currentPage': page, 'categoryNo': '', 'countPerPage': 30},
                                headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        response.raise_for_status()
        data = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', '', response.text))
        if data.get('resultCode') != 'S' or not isinstance(data.get('postList'), list):
            raise ValueError('Invalid public catalog response')
        return int(data['totalCount']), data['postList']

    total, first = fetch(1)
    if total < 0 or total > 30000:
        raise ValueError('Public catalog exceeds bounded collection limit')
    first_ids = [str(row['logNo']) for row in first]
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))['accounts'][account]
        if (cached.get('fullInventoryComplete') is True
                and _fresh(cached['fullCollectedAt'], now, timedelta(hours=24))
                and cached['total'] == total == len(cached['posts'])
                and len({p['url'] for p in cached['posts']}) == total
                and [p['url'].rsplit('/', 1)[1] for p in cached['posts'][:30]] == first_ids):
            return path
    except (OSError, ValueError, KeyError, TypeError):
        pass
    posts, ids = [], set()
    for page in range(1, max(1, (total + 29) // 30) + 1):
        count, rows = (total, first) if page == 1 else fetch(page)
        if count != total or len(rows) > 30:
            raise ValueError('Public catalog changed while collecting')
        for row in rows:
            post_id = str(row['logNo'])
            day = parse_naver_post_date(row['addDate'], now).isoformat()
            if not post_id.isdigit() or post_id in ids or (posts and day > posts[-1]['date']):
                raise ValueError('Public catalog identity/date ordering is inconsistent')
            ids.add(post_id)
            posts.append({'url': f'https://blog.naver.com/{blog}/{post_id}', 'date': day,
                          'title': html.unescape(unquote_plus(row['title']))})
        if page * 30 < total:
            time.sleep(0.4)
    count, final_head = fetch(1)
    if len(posts) != total or count != total or [str(row['logNo']) for row in final_head] != first_ids:
        raise ValueError('Public catalog completeness or final head check failed')
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(path, json.dumps({'accounts': {account: {
        'source': 'https://blog.naver.com/PostTitleListAsync.naver', 'total': total, 'posts': posts,
        'fullInventoryComplete': True, 'fullCollectedAt': now_kst().isoformat()}}}, ensure_ascii=False))
    return path


def refresh_current_state(base, account, worker_id=None):
    """Observe the owned account and reservation list; never publish or invoke models."""
    import re
    from contextlib import nullcontext
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from common.browser_session import connect_sync
    from common.dashboard_jobs import atomic_text
    from naver_blog_posting import pipeline_runner as runner
    inventory_file = collect_full_public_inventory(base, account)
    busy = runner.pipeline_busy(base)
    if busy:
        attempts = runner.read_journal(base)['attempts']
        if (not worker_id or not attempts or attempts[-1].get('workerId') != worker_id
                or attempts[-1].get('account') != account or attempts[-1].get('phase') != 'started'):
            raise RuntimeError('Fresh observation requires the exact active worker identity')
    elif worker_id:
        raise RuntimeError('No active worker to renew')
    acc = runner.ACCOUNT_MAP[account]
    folder = Path(base) / 'output' / account / 'current-reconciliation-observation'
    folder.mkdir(parents=True, exist_ok=True)
    # During renewal only independent owned tabs are used; preserve the worker editor.
    with (nullcontext() if busy else runner.pipeline_lock()), sync_playwright() as playwright:
        runner.start_browser(acc)
        browser = connect_sync(playwright, f"http://127.0.0.1:{acc['cdp_port']}",
                               *runner.account_browser_paths(acc))
        context = browser.contexts[0]
        page = next((p for p in context.pages if p.url.rstrip('/') in
                     ('https://www.naver.com','https://blog.naver.com/MyBlog.naver')),None)
        owned = page is None
        if owned:page = context.new_page()
        try:
            page.goto('https://www.naver.com/', wait_until='domcontentloaded', timeout=30000)
            page.locator('body').filter(has_text=re.compile(r'(?<![\w.])' + re.escape(account) + r'@naver\.com')).wait_for(timeout=15000)
            page.goto('https://blog.naver.com/MyBlog.naver', wait_until='domcontentloaded', timeout=30000)
            page.wait_for_url(lambda url: urlsplit(str(url)).hostname == 'blog.naver.com'
                              and urlsplit(str(url)).path.strip('/') == BLOGS[account], timeout=15000)
        finally:
            if owned:page.close()
        observed = runner.collect_existing_reservations(context, acc, folder)
        proof = {'schema': 'naver-authenticated-reservation-preflight-v1',
                 'checkedAt': runner.now_kst().isoformat(), 'account': account, 'blogId': BLOGS[account],
                 'authenticatedAccount': account, 'ownerBlogId': BLOGS[account], 'identityVerified': True,
                 'tabOwnership':{'account':account,'task':'current-account-reconciliation','owned':owned,'reused':not owned},
                 'entries': observed['reservations'], 'inventory': observed}
        atomic_text(folder / 'proof.json', json.dumps(proof, ensure_ascii=False, indent=2))
    attempts = runner.effective_planning_attempts(runner.read_journal(base)['attempts'], base)
    return create_receipt(base, account, attempts, proof, inventory_file, runner.now_kst(), worker_id)


def main():
    import argparse
    from naver_blog_posting import pipeline_runner
    parser = argparse.ArgumentParser(description='Validate fresh account evidence without editing historical attempts.')
    parser.add_argument('--account', required=True, choices=tuple(BLOGS))
    parser.add_argument('--refresh', action='store_true', help='Collect live account/reservation and full public evidence')
    parser.add_argument('--preflight-file', type=Path)
    parser.add_argument('--inventory-file', type=Path)
    parser.add_argument('--worker-id', help='One renewal for the exact active worker started under the original idle receipt')
    args = parser.parse_args()
    if args.refresh:
        if args.preflight_file or args.inventory_file:
            parser.error('--refresh cannot use supplied evidence files')
        print(json.dumps(refresh_current_state(pipeline_runner.BASE, args.account, args.worker_id), ensure_ascii=False))
        return
    if not args.preflight_file or not args.inventory_file:
        parser.error('Supply --refresh or both evidence files')
    attempts = pipeline_runner.effective_planning_attempts(pipeline_runner.read_journal()['attempts'])
    proof = json.loads(args.preflight_file.read_text(encoding='utf-8-sig'))
    print(json.dumps(create_receipt(pipeline_runner.BASE, args.account, attempts, proof,
                                    args.inventory_file, pipeline_runner.now_kst(), args.worker_id), ensure_ascii=False))


if __name__ == '__main__':
    main()
