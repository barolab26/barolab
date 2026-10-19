"""Durable discovery submissions. Receipt is never crawl/index/registration proof.

Bing contract: learn.microsoft.com/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.submiturlbatch
IndexNow contract: https://www.indexnow.org/documentation
"""
from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlencode
from zoneinfo import ZoneInfo

import requests
from dashboard import metrics
from common.channel_attribution import is_dummy_rescue_url

LEDGER = metrics.DATA / 'indexing-submissions.json'
INDEXNOW_ENDPOINTS = {'global': 'https://api.indexnow.org/indexnow',
                     'bing': 'https://www.bing.com/indexnow',
                     'naver': 'https://searchadvisor.naver.com/indexnow'}
KST = ZoneInfo('Asia/Seoul')


def _now(now=None):
    return now or datetime.now(timezone.utc)


def canonical_url(site, url):
    metrics.owned_url(site, url)
    parsed = urlparse(url)
    if parsed.hostname != urlparse(site['url']).hostname or parsed.query or is_dummy_rescue_url(url):
        raise ValueError('CANONICAL_PUBLIC_URL_REQUIRED')
    return url


def _load(path):
    return metrics.read_json(path, {'version': 1, 'events': []})


def enqueue_gsc_request(scope=None, requested_by='radar', *, ledger=None):
    """Durable wake-up intent consumed by the existing authorized metrics cycle.

    This does not start a second browser process or claim an indexing request.
    """
    config = metrics.read_json(metrics.CONFIG)
    if not metrics.authorized_gsc_request_mode(config):
        return {'status': 'authorization_required', 'queued': False, 'started': False}
    allowed = {s['site_id'] for s in metrics.inventory() if s.get('platform') == 'cf'}
    scopes = sorted(allowed if scope in (None, 'all') else ({scope} if isinstance(scope, str) else set(scope)))
    if not scopes or not set(scopes) <= allowed:
        raise ValueError('Configured CF scope required')
    path = Path(ledger or LEDGER)
    with metrics.collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            return {'status': 'queue_busy', 'queued': False, 'started': False}
        state = _load(path)
        queue = state.setdefault('gscQueue', [])
        prior = next((x for x in queue if x['scope'] == scopes and x['status'] == 'queued'), None)
        if prior:
            return {**prior, 'queued': True, 'started': False, 'duplicate': True}
        item = {'runId': uuid.uuid4().hex, 'scope': scopes, 'requestedBy': str(requested_by)[:80],
                'status': 'queued', 'queuedAt': _now().isoformat(),
                'consumer': 'dashboard.metrics.collect', 'indexed': None}
        queue.append(item)
        metrics.atomic_write(path, state)
        return {**item, 'queued': True, 'started': False, 'reason': 'authorized_scheduled_collector_pending'}


def record_gsc_queue_cycle(scopes, outcome, *, ledger=None):
    path = Path(ledger or LEDGER)
    with metrics.collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            return
        state = _load(path)
        for item in state.get('gscQueue', []):
            if item['status'] == 'queued' and set(item['scope']) <= set(scopes):
                item.update(lastConsumerCheckAt=_now().isoformat(), outcome=outcome or {'status': 'ui_cycle_finished'})
                if (outcome or {}).get('status') != 'daily_budget_exhausted':
                    item['status'] = 'consumer_checked'
        metrics.atomic_write(path, state)


def _date(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.replace(tzinfo=KST)
    except (ValueError, TypeError):
        return None


def _gsc_history(account, path, now):
    events = [e for e in _load(path)['events'] if e.get('provider') == 'gsc' and e.get('account') == account]
    history = metrics.read_json(metrics.DATA / 'indexing-recovery.json', {'events': []})
    legacy = metrics.read_json(history['historicalLog'], []) if history.get('historicalLog') else []
    for e in history.get('events', []) + legacy:
        if e.get('account') == account and e.get('url') and e.get('outcome') in (
                'requested', 'pending', 'already_pending', 'request_unconfirmed'):
            events.append({'url': e['url'], 'at': e.get('at') or e.get('requestedAt'),
                           'status': e['outcome']})
    return events


def gsc_budget(account='sj', *, ledger=None, now=None):
    now = _now(now); path = Path(ledger or LEDGER)
    events = _gsc_history(account, path, now)
    today = now.astimezone(KST).date()
    counted = {e['url'] for e in events if e.get('status') != 'cancelled_before_click'
               and (at := _date(e.get('at'))) and at.astimezone(KST).date() == today}
    provider_exhausted = any(e.get('status') == 'quota_exceeded'
                            and (at := _date(e.get('at'))) and at.astimezone(KST).date() == today
                            for e in events)
    recent = sorted({e['url'] for e in events if e.get('status') != 'cancelled_before_click'
                     and (at := _date(e.get('at'))) and now - at < timedelta(days=7)})
    return {'account': account, 'dayKST': today.isoformat(), 'limit': 10,
            'used': len(counted), 'remaining': 0 if provider_exhausted else max(0, 10-len(counted)),
            'providerQuotaExceeded': provider_exhausted, 'recentUrls': recent}


def reserve_gsc_request(account, site, url, *, authorized=False, evidence=None, ledger=None, now=None):
    """Call immediately BEFORE UI click; unknown/crashed attempts consume budget.

    evidence must be the actual URL-specific not-indexed inspection, not an inferred
    domain count. A reserved URL is not reported as requested or indexed.
    """
    if not authorized:
        raise ValueError('EXPLICIT_REQUEST_MODE_REQUIRED')
    canonical_url(site, url)
    if not isinstance(evidence, dict) or evidence.get('indexed') is not False or evidence.get('url') != url:
        raise ValueError('URL_SPECIFIC_NOT_INDEXED_EVIDENCE_REQUIRED')
    path = Path(ledger or LEDGER); now = _now(now)
    with metrics.collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            raise RuntimeError('SUBMISSION_LEDGER_BUSY')
        budget = gsc_budget(account, ledger=path, now=now)
        if url in budget['recentUrls']:
            return {'status': 'duplicate_suppressed', **budget}
        if not budget['remaining']:
            return {'status': 'daily_budget_exhausted', **budget}
        doc = _load(path)
        event = {'id': uuid.uuid4().hex, 'provider': 'gsc', 'account': account,
                 'domain': site['site_id'], 'url': url, 'at': now.isoformat(),
                 'status': 'reserved', 'indexed': None, 'evidence': evidence}
        doc['events'].append(event); metrics.atomic_write(path, doc)
        return event


def complete_gsc_request(reservation_id, status, *, evidence=None, ledger=None):
    allowed = {'requested', 'request_unconfirmed', 'quota_exceeded', 'cancelled_before_click', 'already_pending'}
    if status not in allowed:
        raise ValueError('INVALID_REQUEST_OUTCOME')
    if status in ('requested', 'already_pending') and not evidence:
        raise ValueError('UI_CONFIRMATION_EVIDENCE_REQUIRED')
    path = Path(ledger or LEDGER)
    with metrics.collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            raise RuntimeError('SUBMISSION_LEDGER_BUSY')
        doc = _load(path)
        event = next(e for e in doc['events'] if e['id'] == reservation_id and e['provider'] == 'gsc')
        if event['status'] != 'reserved':
            if event['status'] == status:
                return event
            raise ValueError('REQUEST_ALREADY_FINALIZED')
        event.update(status=status, completedAt=metrics.stamp(), confirmation=evidence, indexed=None)
        metrics.atomic_write(path, doc)
        return event


def observe_gsc_pending(account, site, url, evidence, *, ledger=None):
    """Existing pending UI: conservative budget hold, never a new request success."""
    reservation = reserve_gsc_request(account, site, url, authorized=True,
        evidence={'url': url, 'indexed': False, 'source': 'existing_pending_ui', 'proof': evidence}, ledger=ledger)
    if reservation['status'] == 'reserved':
        return complete_gsc_request(reservation['id'], 'already_pending', evidence=evidence, ledger=ledger)
    return reservation


def gsc_candidates(account='sj', limit=10):
    config = metrics.read_json(metrics.CONFIG); snapshot = metrics.read_json(metrics.SNAPSHOT)
    domains = config.get('gsc_accounts', {}).get(account, {}).get('sites', [])
    recent = set(gsc_budget(account)['recentUrls']); groups = []
    for site in metrics.inventory():
        if site['site_id'] not in domains or site['platform'] != 'cf':
            continue
        record = snapshot.get('sites', {}).get(site['site_id'], {})
        inventory = set(record.get('posts', {}).get('urls', [])); rows = []
        for row in record.get('google', {}).get('urls', []):
            if row.get('indexed') is not False or row.get('url') not in inventory or row['url'] in recent:
                continue
            try:
                canonical_url(site, row['url'])
            except ValueError:
                continue
            rows.append({'site': site, 'url': row['url'], 'inspection': row})
        groups.append(rows)
    return [group[i] for i in range(max(map(len, groups), default=0)) for group in groups if i < len(group)][:limit]


def daum_state(site, observation=None):
    """Registration and an observed search result are independent evidence axes."""
    observation = observation or {}
    registered = observation.get('registrationVerified') if observation.get('registrationEvidence') else None
    found = observation.get('searchResultObserved') if observation.get('searchEvidence') else None
    return {'status': 'registered' if registered is True else 'not_registered' if registered is False else 'unknown',
            'registrationVerified': registered, 'searchResultObserved': found, 'indexed': None,
            'registrationUrl': 'https://register.search.daum.net/index.daum',
            'searchUrl': 'https://search.daum.net/search?' + urlencode({'w': 'tot', 'q': 'site:'+urlparse(site['url']).hostname}),
            'canonicalUrl': site['url'], 'observation': observation,
            'reason': 'Search-result absence does not prove no registration or no indexing.'}


def _start(provider, site, urls, ledger, run_id, now):
    """Persist intent before transport; a timeout stays uncertain and deduplicated."""
    path = Path(ledger or LEDGER)
    with metrics.collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            raise RuntimeError('SUBMISSION_LEDGER_BUSY')
        doc = _load(path)
        prior = {u for e in doc['events'] if e.get('provider') == provider
                 and e.get('domain') == site['site_id']
                 and (at := _date(e.get('at'))) and now-at < timedelta(days=1)
                 for u in e.get('urls', [])}
        pending = [u for u in dict.fromkeys(urls) if u not in prior]
        if not pending:
            return {'status': 'duplicate_suppressed', 'provider': provider, 'submittedCount': 0,
                    'indexed': None, 'registered': None, 'crawled': None}
        event = {'id': uuid.uuid4().hex, 'runId': run_id, 'provider': provider, 'domain': site['site_id'],
                 'at': now.isoformat(), 'status': 'request_started', 'urls': pending,
                 'submittedCount': 0, 'indexed': None, 'registered': None, 'crawled': None}
        doc['events'].append(event); metrics.atomic_write(path, doc)
        return event


def _finish(event, result, ledger):
    path = Path(ledger or LEDGER)
    for _ in range(50):
        with metrics.collector_lock(path.with_suffix('.lock')) as acquired:
            if acquired:
                doc = _load(path)
                item = next(e for e in doc['events'] if e['id'] == event['id'])
                item.update(result, completedAt=metrics.stamp())
                metrics.atomic_write(path, doc)
                return item
        import time
        time.sleep(.1)
    raise RuntimeError('SUBMISSION_RESULT_PERSISTENCE_BUSY')


def submit_indexnow(site, settings, urls, *, providers=('global', 'bing', 'naver'),
                    ledger=None, client=requests, run_id=None, now=None):
    urls = list(dict.fromkeys(canonical_url(site, u) for u in urls))
    if len(urls) > 10000:
        raise ValueError('INDEXNOW_BATCH_TOO_LARGE')
    if any(p not in INDEXNOW_ENDPOINTS for p in providers):
        raise ValueError('INDEXNOW_ENDPOINT_NOT_ALLOWED')
    if not urls:
        return {p: {'status': 'no_candidates', 'submittedCount': 0, 'indexed': None} for p in providers}
    key = settings.get('indexnow_key', '')
    if not re.fullmatch(r'[a-zA-Z0-9-]{8,128}', key):
        return {p: {'status': 'not_configured', 'submittedCount': 0, 'indexed': None} for p in providers}
    key_url = canonical_url(site, settings.get('indexnow_key_location') or site['url'].rstrip('/')+'/'+key+'.txt')
    try:
        verification = client.get(key_url, timeout=15, allow_redirects=False)
        if verification.status_code != 200 or verification.text.strip() != key:
            raise ValueError('KEY_FILE_UNVERIFIED')
    except Exception:
        return {p: {'status': 'key_unverified', 'submittedCount': 0, 'indexed': None} for p in providers}
    key_scope = urlparse(key_url).path.rsplit('/', 1)[0] + '/'
    if any(not urlparse(u).path.startswith(key_scope) for u in urls):
        raise ValueError('INDEXNOW_KEY_SCOPE_MISMATCH')
    output = {}; path = Path(ledger or LEDGER); now = _now(now)
    for provider in providers:
        with metrics.collector_lock(path.with_name('indexnow-'+provider+'.lock')) as acquired:
            if not acquired:
                output[provider] = {'status': 'collector_busy', 'submittedCount': 0}; continue
            event = _start('indexnow_'+provider, site, urls, path, run_id, now)
            if event['status'] == 'duplicate_suppressed':
                output[provider] = event; continue
            try:
                response = client.post(INDEXNOW_ENDPOINTS[provider], json={
                    'host': urlparse(site['url']).hostname, 'key': key, 'keyLocation': key_url,
                    'urlList': event['urls']}, timeout=25, allow_redirects=False)
                code = response.status_code
                result = {'status': 'ping_accepted' if code == 200 else 'accepted_pending_key_check' if code == 202
                          else 'rejected', 'httpStatus': code,
                          'reason': {400: 'INVALID_FORMAT', 403: 'KEY_VALIDATION_REJECTED',
                                     422: 'HOST_OR_KEY_SCOPE_REJECTED', 429: 'RATE_LIMITED'}.get(code),
                          'submittedCount': len(event['urls']) if code in (200, 202) else 0,
                          'endpoint': INDEXNOW_ENDPOINTS[provider], 'method': 'IndexNow'}
            except Exception:
                result = {'status': 'submission_unconfirmed', 'reason': 'TRANSPORT_ERROR', 'submittedCount': 0}
            output[provider] = _finish(event, result, path)
    return output


def submit_bing(site, property_url, urls, credentials, *, verified_properties,
                ledger=None, client=requests, run_id=None, now=None):
    from dashboard.traffic import bing_submission_request
    urls = list(dict.fromkeys(canonical_url(site, u) for u in urls))
    # An apex property must be explicitly returned by GetUserSites, not guessed.
    prop = urlparse(property_url or '')
    if property_url not in verified_properties or prop.hostname not in (site['site_id'], 'www.'+site['site_id']):
        return {'status': 'property_unverified', 'submittedCount': 0, 'indexed': None}
    path = Path(ledger or LEDGER); now = _now(now)
    with metrics.collector_lock(path.with_name('bing-submission.lock')) as acquired:
        if not acquired:
            return {'status': 'collector_busy', 'submittedCount': 0}
        quota, error = bing_submission_request('GetUrlSubmissionQuota', property_url, credentials, client=client)
        if error:
            return {'status': 'quota_unavailable', 'reason': error, 'submittedCount': 0, 'indexed': None}
        amount = min(500, quota['DailyQuota'], quota['MonthlyQuota'])
        if not amount:
            return {'status': 'quota_exhausted', 'quota': quota, 'submittedCount': 0, 'indexed': None}
        event = _start('bing_url_batch', site, urls[:amount], path, run_id, now)
        if event['status'] == 'duplicate_suppressed':
            return event
        result, error = bing_submission_request('SubmitUrlBatch', property_url, credentials, event['urls'], client)
        outcome = {'status': 'submission_unconfirmed' if error else 'submission_accepted',
                   'reason': error, 'httpStatus': result.get('httpStatus') if result else None,
                   'submittedCount': len(event['urls']) if not error else 0,
                   'quotaBefore': quota, 'property': property_url, 'method': 'SubmitUrlBatch'}
        if error and error.startswith('BING_HTTP_'):
            outcome['status'] = 'rejected'
        return _finish(event, outcome, path)


class _PageEvidence(HTMLParser):
    def __init__(self):
        super().__init__(); self.canonicals = []; self.noindex = False; self.article = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'link' and 'canonical' in values.get('rel', '').lower().split():
            self.canonicals.append(values.get('href'))
        if tag == 'meta' and values.get('name', '').lower() in ('robots', 'googlebot', 'bingbot'):
            self.noindex |= bool(re.search(r'\b(noindex|none)\b', values.get('content', '').lower()))
        self.article |= tag == 'article'


def validate_public_url(site, url, client=requests):
    try:
        canonical_url(site, url)
        response = client.get(url, timeout=20, allow_redirects=False)
        if response.status_code != 200:
            return {'url': url, 'valid': False, 'reason': 'HTTP_'+str(response.status_code)}
        parser = _PageEvidence(); parser.feed(response.text)
        valid = (parser.canonicals == [url] and not parser.noindex
                 and not re.search(r'\b(noindex|none)\b', response.headers.get('X-Robots-Tag', '').lower()))
        return {'url': url, 'valid': bool(valid), 'httpStatus': 200,
                'canonical': parser.canonicals[0] if len(parser.canonicals) == 1 else None,
                'reason': None if valid else 'CANONICAL_OR_NOINDEX_MISMATCH', 'checkedAt': metrics.stamp()}
    except Exception:
        return {'url': url, 'valid': False, 'reason': 'PUBLIC_VALIDATION_FAILED'}


def observe_daum(site, client=requests):
    state = daum_state(site)
    try:
        response = client.get(state['searchUrl'], timeout=20, allow_redirects=False)
        text = response.text
        # HTTP 200 challenge/interstitial is not a valid negative search result.
        blocked = any(v in text.lower() for v in ('captcha', 'access denied', '비정상적인 접근', '자동입력'))
        hrefs = re.findall(r'href=[\"\'](https?://[^\"\']+)', text)
        matches = [u for u in hrefs if urlparse(u).hostname == urlparse(site['url']).hostname]
        evidence = {'httpStatus': response.status_code, 'checkedAt': metrics.stamp(),
                    'sourceUrl': state['searchUrl'], 'matchingResultUrls': sorted(set(matches))[:10]}
        state['observation'] = evidence
        state['searchResultObserved'] = True if response.status_code == 200 and not blocked and matches else None
        state['searchObservationStatus'] = 'result_observed' if state['searchResultObserved'] else 'unconfirmed'
    except Exception:
        state['searchObservationStatus'] = 'unavailable'
    return state


def run_discovery_submissions(*, apply=False, run_id=None, domain=None):
    """One explicit API-only batch; never opens a browser or requests Google indexing."""
    from dashboard.traffic import bing_credentials, bing_sites
    run_id = run_id or 'discovery-'+datetime.now(KST).strftime('%Y%m%dT%H%M%S')
    with metrics.collector_lock(metrics.DATA / 'indexing-discovery-run.lock') as held:
        if not held:
            return {'status': 'collector_busy'}
        with metrics.collector_lock(metrics.DATA / 'metrics-run.lock') as metrics_held:
            if not metrics_held:
                return {'status': 'metrics_collector_busy'}
            config = metrics.read_json(metrics.CONFIG); snapshot = metrics.read_json(metrics.SNAPSHOT)
            sites = [s for s in metrics.inventory() if s['platform'] == 'cf' and (not domain or s['site_id'] == domain)]
            credentials = bing_credentials(config)
            properties, property_error = bing_sites(credentials)
            verified = {r['url'] for r in properties or [] if r['verified']}
            reports = []
            for site in sites:
                record = snapshot.get('sites', {}).get(site['site_id'], {})
                settings = config.get('sites', {}).get(site['site_id'], {})
                indexed = {r['url'] for r in record.get('google', {}).get('urls', []) if r.get('indexed') is True}
                not_indexed = {r['url'] for r in record.get('google', {}).get('urls', []) if r.get('indexed') is False}
                candidates = [u for u in record.get('posts', {}).get('urls', []) if u not in indexed and not is_dummy_rescue_url(u)]
                with ThreadPoolExecutor(max_workers=8) as pool:
                    validations = list(pool.map(lambda u: validate_public_url(site, u), candidates))
                valid = [r['url'] for r in validations if r['valid']]
                property_url = next((p for p in (site['url'], settings.get('bing_property'),
                    'https://'+site['site_id']+'/') if p in verified), None)
                report = {'domain': site['site_id'], 'canonicalSite': site['url'], 'candidateCount': len(candidates),
                          'knownNotIndexedCandidateCount': sum(u in not_indexed for u in candidates),
                          'unknownIndexStateCandidateCount': sum(u not in not_indexed for u in candidates),
                          'validatedCount': len(valid), 'validations': validations, 'daum': observe_daum(site),
                          'indexEvidenceScope': 'Google explicit indexed URLs excluded; other URL index state remains unconfirmed'}
                if apply:
                    report['bing'] = (submit_bing(site, property_url, valid, credentials, verified_properties=verified,
                        run_id=run_id) if not property_error else {'status': 'property_unverified', 'reason': property_error, 'submittedCount': 0})
                    report['indexnow'] = submit_indexnow(site, settings, valid, providers=('global', 'bing'), run_id=run_id)
                reports.append(report)
                print(json.dumps({'domain': site['site_id'], 'valid': len(valid),
                                  'bing': report.get('bing', {}).get('status'),
                                  'indexnow': {k:v['status'] for k,v in report.get('indexnow', {}).items()}}), flush=True)
            result = {'status': 'completed' if apply else 'dry_run', 'runId': run_id,
                      'checkedAt': metrics.stamp(), 'domains': reports}
            if apply:
                with metrics.collector_lock() as acquired:
                    if not acquired:
                        raise RuntimeError('METRICS_RESULT_BUSY_SUBMISSIONS_PRESERVED_IN_LEDGER')
                    current = metrics.read_json(metrics.SNAPSHOT)
                    for r in reports:
                        target = current.setdefault('sites', {}).setdefault(r['domain'], {})
                        request = target.setdefault('indexingRequest', {}) or {}
                        request.update(bing=r['bing'], indexnow=r['indexnow'], discoveryRunId=run_id)
                        naver = request.get('naver') or {}
                        if naver.get('method') == 'IndexNow' and naver.get('httpStatus') in (200,202):
                            naver.update(status='ping_accepted' if naver['httpStatus'] == 200 else 'accepted_pending_key_check',
                                         registered=None, crawled=None, indexed=None)
                            request['naver'] = naver
                        target['indexingRequest'] = request; target['daum'] = r['daum']
                    metrics.atomic_write(metrics.SNAPSHOT, current)
                metrics.atomic_write(metrics.DATA / 'indexing-discovery-latest.json', result)
            return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--domain')
    parser.add_argument('--run-id')
    args = parser.parse_args()
    result = run_discovery_submissions(apply=args.apply, run_id=args.run_id, domain=args.domain)
    print(json.dumps({k:v for k,v in result.items() if k != 'domains'}, ensure_ascii=False))
