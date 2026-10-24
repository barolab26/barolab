"""Resume verified discovery and visible crawl requests within provider budgets."""
import json
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from dashboard import metrics
from dashboard.collectors import searchadvisor
from dashboard.collectors.searchadvisor_ui import run as crawl_visible
from dashboard.indexing_submissions import run_discovery_submissions, validate_public_url


def refresh_candidates(site, state, limit=50):
    reserved = {row['url'] for row in state.get('crawlRequests', [])}
    urls = [row['url'] for row in state.get('crawlQueue', [])
            if row['url'] not in reserved and urlsplit(row['url']).hostname == urlsplit(site['url']).hostname]
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda url: validate_public_url(site, url), urls))
    proof = metrics.DATA / 'searchadvisor-public-validation.json'
    metrics.atomic_write(proof, {'checkedAt': metrics.stamp(), 'domains': [
        {'domain': site['site_id'], 'validations': rows}]})
    valid = [row['url'] for row in rows if row['valid']][:limit]
    if valid:
        searchadvisor.queue_crawl_candidates(valid, evidence={
            'checkedAt': metrics.stamp(), 'source': str(proof)})
    return valid


def submit_google_sitemaps(config):
    results = []
    for site in metrics.inventory():
        if site.get('platform') != 'cf':
            continue
        previous = metrics.read_json(metrics.SNAPSHOT).get('sites', {}).get(site['site_id'], {})
        receipt = previous.get('indexingRequest', {}).get('google', {})
        checked = metrics.inspection_time(receipt.get('checkedAt'))
        if receipt.get('status') == 'submitted' and checked and timedelta(0) <= datetime.now(timezone.utc) - checked < timedelta(days=1):
            continue
        settings = config.get('sites', {}).get(site['site_id'], {})
        try:
            with metrics.google_session(config, settings) as session:
                outcome = metrics.request_indexing(session, site, settings, [],
                    metrics.sitemap_status(site, settings), indexnow=False)['google']
        except Exception as exc:
            outcome = {'status': 'unavailable', 'errorType': type(exc).__name__}
        outcome['checkedAt'] = metrics.stamp()
        results.append({'domain': site['site_id'], **outcome})
        with metrics.collector_lock() as held:
            if held:
                snapshot = metrics.read_json(metrics.SNAPSHOT)
                snapshot.setdefault('sites', {}).setdefault(site['site_id'], {}).setdefault(
                    'indexingRequest', {})['google'] = outcome
                metrics.atomic_write(metrics.SNAPSHOT, snapshot)
    return results


def run():
    with metrics.collector_lock(metrics.DATA / 'indexing-dispatch.lock') as held:
        if not held:
            return {'status': 'already_running'}
        result = {'checkedAt': metrics.stamp(), 'naver': [], 'indexed': None}
        try:
            result['discovery'] = run_discovery_submissions(apply=True)
        except Exception as exc:
            result['discovery'] = {'status': 'unavailable', 'errorType': type(exc).__name__}
        config = metrics.read_json(metrics.CONFIG)
        result['googleSitemaps'] = submit_google_sitemaps(config)
        policy = config.get('searchadvisor', {})
        if policy.get('request_authorized') is True and policy.get('mode') == 'authorized_visible_ui':
            for site in metrics.inventory():
                if site.get('platform') != 'cf':
                    continue
                origin = site['url'].rstrip('/')
                budget = searchadvisor.crawl_budget(site=origin)
                if budget.get('remaining') == 0:
                    result['naver'].append({'site': origin, **budget})
                    continue
                # Seed newly published URLs; a queue entry alone cannot authorize a click.
                urls = metrics.read_json(metrics.SNAPSHOT).get('sites', {}).get(site['site_id'], {}).get('posts', {}).get('urls', [])
                state = metrics.read_json(searchadvisor.LEDGER)
                known = {row['url'] for row in state.get('crawlQueue', []) + state.get('crawlRequests', [])}
                searchadvisor.queue_crawl_candidates([url for url in urls if url not in known], evidence={
                    'checkedAt': '1970-01-01T00:00:00+00:00', 'source': 'inventory awaiting live validation'})
                state = metrics.read_json(searchadvisor.LEDGER)
                candidates = refresh_candidates(site, state, budget.get('remaining') or 50)
                if not candidates:
                    continue
                outcome = crawl_visible(apply=True, domain=origin, batch_size=50, candidate_urls=candidates)
                result['naver'].append(outcome)
                metrics.atomic_write(metrics.DATA / 'indexing-dispatch.json', result)
                if outcome.get('status') != 'completed':
                    break
        try:
            result['google'] = metrics.collect_browser_inspections(config, metrics.inventory(), request_mode=None)
        except Exception as exc:
            result['google'] = {'status': 'unavailable', 'errorType': type(exc).__name__}
        result['finishedAt'] = metrics.stamp()
        metrics.atomic_write(metrics.DATA / 'indexing-dispatch.json', result)
        return result


if __name__ == '__main__':
    outcome = run()
    print(json.dumps({'status': outcome.get('status', 'finished'),
                      'naverSites': len(outcome.get('naver', [])), 'indexed': None}))
