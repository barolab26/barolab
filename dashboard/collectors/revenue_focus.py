"""Read-only, bounded URL acquisition observations. Never publishes or calls a model."""
import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'dashboard') not in sys.path:
    sys.path.insert(0, str(ROOT / 'dashboard'))
from dashboard.collectors import traffic as traffic

STATE = ROOT / 'dashboard/data/revenue-focus.json'
KST = ZoneInfo('Asia/Seoul')
SOURCE = 'GA4 Data API: exact page, reconciled session acquisition'


def observation_windows(start):
    start = date.fromisoformat(start)
    return [{'days': days, 'start': start.isoformat(),
             'end': (start + timedelta(days=days-1)).isoformat(),
             'reviewDate': (start + timedelta(days=days)).isoformat(),
             'finalCollectionDate': (start + timedelta(days=days+2)).isoformat()}
            for days in (7, 14, 28)]


def qualify(source, medium, domain):
    if traffic.external_exclusion(source, domain) or source.lower() in ('barolab_audit', 'barolab_qa', 'qa') or medium.lower() in ('qa', 'audit', 'internal'):
        return 'excluded'
    if source in ('(direct)', '(not set)', '') or medium == '(not set)':
        return 'unattributed'
    return 'attributed'


def summarize(rows, totals, limited, domain):
    groups = {key: {'sessions': 0, 'pageViews': 0} for key in ('attributed', 'excluded', 'unattributed')}
    for row in rows:
        key = qualify(row['source'], row['medium'], domain)
        row['classification'] = key
        for metric in ('sessions', 'pageViews'):
            groups[key][metric] += row[metric]
    reconciled = all(sum(g[m] for g in groups.values()) == totals[m] for m in ('sessions', 'pageViews'))
    complete = not limited and reconciled
    return {'complete': complete, 'status': 'collected' if complete else 'partial',
            'reconciled': reconciled, 'limited': limited, 'totals': totals, 'breakdown': groups,
            'qualifiedSessions': groups['attributed']['sessions'] if complete else None,
            'qualifiedPageViews': groups['attributed']['pageViews'] if complete else None,
            'rows': rows, 'qualification': 'Known operational sources excluded; direct/unset separate. Attribution does not establish human identity or causality.'}


def collect_window(client, property_id, target, start, end):
    parsed = urlsplit(target)
    domain = parsed.hostname.removeprefix('www.')
    if parsed.scheme != 'https' or parsed.query or parsed.fragment or parsed.username or not traffic.is_article_path(parsed.path):
        raise ValueError('Exact clean HTTPS article required')
    body = {'dateRanges': [{'startDate': start, 'endDate': end}], 'limit': 100000,
            'dimensionFilter': {'andGroup': {'expressions': [
                {'filter': {'fieldName': 'hostName', 'inListFilter': {'values': [domain, 'www.'+domain]}}},
                {'filter': {'fieldName': 'pagePath', 'stringFilter': {'matchType': 'EXACT', 'value': parsed.path, 'caseSensitive': True}}}]}},
            'metrics': [{'name': 'sessions'}, {'name': 'screenPageViews'}]}
    totals, limited_total = traffic.ga_report(client, property_id, body, [])
    if len(totals) > 1:
        raise ValueError('Ambiguous target totals')
    total = dict(zip(('sessions', 'pageViews'), totals[0][1] if totals else (0, 0)))
    dimensions = ['sessionSource', 'sessionMedium', 'sessionManualAdContent']
    raw, limited = traffic.ga_report(client, property_id,
        {**body, 'dimensions': [{'name': d} for d in dimensions]}, dimensions)
    rows = [{'source': source, 'medium': medium, 'utmContent': content, 'sessions': sessions, 'pageViews': views,
             'channel': traffic.canonical_source(source) or ('search' if medium == 'organic' else 'other')}
            for (source, medium, content), (sessions, views) in raw]
    return {'url': target, 'domain': domain, 'start': start, 'end': end, 'timezone': 'Asia/Seoul',
            'checkedAt': traffic.stamp(), 'source': SOURCE,
            **summarize(rows, total, limited or limited_total, domain),
            'requestSha256': hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}


def matched_revenue(document, target, observation):
    report = document.get('pagePerformance') or {}
    if any(report.get(k) != observation.get(k) for k in ('start', 'end', 'timezone')):
        return {'amount': None, 'reason': 'exact_period_revenue_unavailable'}
    rows = [r for r in report.get('pages', []) if r.get('url') == target]
    if len(rows) != 1 or not report.get('currency') or not rows[0].get('complete', report.get('complete')):
        return {'amount': None, 'reason': 'eligible_exact_page_revenue_unavailable'}
    row = rows[0]
    value = row.get('estimatedRevenue')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return {'amount': None, 'reason': 'unverified_revenue_value'}
    try:
        age = (datetime.now(KST) - datetime.fromisoformat(report['checkedAt'])).total_seconds()
        if not 0 <= age <= 26*3600:
            raise ValueError('stale')
    except (KeyError, TypeError, ValueError):
        return {'amount': None, 'reason': 'revenue_source_stale_or_undated'}
    return {'amount': value, 'currency': report['currency'], 'source': report.get('source'),
            'scope': 'URL total only; never allocate this revenue to referring channels', 'checkedAt': report.get('checkedAt')}


def evaluate(baseline, observation, minimum, days):
    result = {'status': 'inconclusive', 'causalClaim': False, 'revenueSuccess': False,
              'reason': 'measurement_incomplete', 'action': 'hold_expansion'}
    if not baseline.get('complete') or not observation.get('complete'):
        return result
    try:
        same_scope = all(baseline.get(k) == observation.get(k) and baseline.get(k) for k in ('url', 'timezone', 'source'))
        same_length = all((date.fromisoformat(r['end']) - date.fromisoformat(r['start'])).days + 1 == days for r in (baseline, observation))
        if not same_scope or not same_length or baseline['end'] >= observation['start'] or observation.get('provisional'):
            raise ValueError('scope mismatch')
    except (KeyError, TypeError, ValueError):
        result['reason'] = 'target_or_window_mismatch'
        return result
    a, b = baseline.get('qualifiedSessions'), observation.get('qualifiedSessions')
    if type(a) is not int or type(b) is not int:
        return result
    if b < minimum:
        result.update(reason='insufficient_sample', action='stop_new_spend' if days == 28 or (days >= 14 and b == 0) else 'continue_observation_only')
        return result
    status = ('initial_acquisition_observed' if a == 0 else 'observed_gain') if b > a else 'no_observed_gain'
    result.update(status=status, reason='matched_descriptive_windows',
                  before=a, after=b, delta=b-a, statisticalSignificance='not_established',
                  baselineSampleLimited=a < minimum,
                  action='review_revenue_and_reader_value' if b > a else 'stop_new_spend')
    return result


def collect_exact_revenue(cfg, target, row):
    from dashboard.collectors import revenue
    domain = row['domain']
    account = next((a for a in cfg.get('adsense_accounts', {}).values() if domain in a.get('sites', [])), None)
    if not account:
        return {'amount': None, 'reason': 'account_not_configured', 'manualResolutionRequired': True}
    try:
        pages = revenue.adsense_page_performance(revenue.revenue_config(), date.fromisoformat(row['start']),
            date.fromisoformat(row['end']), [domain], account.get('env_prefix', 'SJ_GOOGLE_ADSENSE'))
        match = next((p for p in pages if p['url'] == target), None)
        return {'amount': match['estimatedRevenue'] if match else None, 'currency': 'USD',
                'reason': 'eligible_exact_url_row' if match else 'eligible_exact_page_revenue_unavailable',
                'start': row['start'], 'end': row['end'], 'timezone': row['timezone'],
                'checkedAt': traffic.stamp(), 'source': 'AdSense Management API v2 PAGE_URL',
                'scope': 'Entire URL earnings only; never attributed to a referring channel'}
    except Exception as exc:
        manual = isinstance(exc, (KeyError, FileNotFoundError)) or any(s in str(exc).lower() for s in ('401', '403', 'credential', 'invalid_grant'))
        return {'amount': None, 'reason': getattr(exc, 'status', type(exc).__name__),
                'checkedAt': traffic.stamp(), 'manualResolutionRequired': manual,
                'source': 'AdSense Management API v2 PAGE_URL'}


def _parse_tz_dt(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _observation_fresh_and_valid(item, url, domain, start, end, now_kst):
    if not isinstance(item, dict):
        return False
    if (item.get('url') != url or item.get('domain') != domain
            or item.get('start') != start or item.get('end') != end
            or item.get('timezone') != 'Asia/Seoul' or item.get('source') != SOURCE):
        return False
    if (item.get('complete') is not True or item.get('reconciled') is not True
            or item.get('limited') is not False or item.get('provisional')
            or item.get('collectionError') or item.get('budgetHold')
            or item.get('status') in ('held', 'failed', 'partial', 'unknown')):
        return False
    if not isinstance(item.get('breakdown'), dict) or type(item.get('qualifiedSessions')) is not int or type(item.get('qualifiedPageViews')) is not int:
        return False
    try:
        checked_dt = datetime.fromisoformat(str(item.get('checkedAt') or '').replace('Z', '+00:00'))
        if checked_dt.tzinfo is None:
            return False
        age = (now_kst - checked_dt).total_seconds()
        if not 0 <= age <= 26 * 3600:
            return False
        if item.get('expiresAt'):
            exp_dt = datetime.fromisoformat(str(item['expiresAt']).replace('Z', '+00:00'))
            if exp_dt.tzinfo is None or now_kst > exp_dt:
                return False
    except (TypeError, ValueError):
        return False
    return True


def inspect_url_acquisition(url, start, end, *, path=None, config_path=None, revenue_path=None, cache_path=None, now=None):
    """Read-only, bounded exact-URL GA4 acquisition query reusing collect_window."""
    if not isinstance(url, str) or not isinstance(start, str) or not isinstance(end, str):
        raise ValueError('Exact URL and ISO start/end dates required')
    start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError('start must not be after end')
    parsed = urlsplit(url)
    domain = (parsed.hostname or '').lower().removeprefix('www.')
    if parsed.scheme != 'https' or parsed.query or parsed.fragment or parsed.username or parsed.password or not domain or not traffic.is_article_path(parsed.path):
        raise ValueError('Exact clean HTTPS article required')
    now_kst = now.astimezone(KST) if isinstance(now, datetime) else datetime.now(KST)
    path = Path(path or STATE)
    cfg = traffic.read_json(Path(config_path) if config_path else traffic.CONFIG)
    sites = cfg.get('sites') or {}
    if domain not in sites:
        raise ValueError('URL domain outside configured GA4 site scope')
    cache_file = Path(cache_path) if cache_path else (path.parent / 'url-acquisition-cache.json')
    base_hold = {'ok': False, 'tool': 'inspect_url_acquisition', 'status': 'held', 'url': url, 'domain': domain,
                 'start': start, 'end': end, 'complete': False, 'qualifiedSessions': None, 'qualifiedPageViews': None,
                 'articleRevenue': None, 'domainRevenueAllocated': False,
                 'revenueScope': 'Exact URL pagePerformance only when complete; domain revenue is never allocated to an article.',
                 'publicationVerified': False, 'businessOutcomeVerified': False}
    with traffic.collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            return {**base_hold, 'status': 'busy', 'reason': 'collector_lock_busy'}
        state = traffic.read_json(path) if path.is_file() else {}
        rev_doc = traffic.read_json(Path(revenue_path) if revenue_path else (traffic.DATA / 'revenue.json'))
        cache_doc = traffic.read_json(cache_file) if cache_file.is_file() else {'entries': {}, 'domainHolds': {}}
        entries = cache_doc.setdefault('entries', {})
        domain_holds = cache_doc.setdefault('domainHolds', {})
        state_checked = str(state.get('checkedAt') or '').strip()
        prev_used = int(cache_doc.get('apiReportCallsUsed', 0))
        prev_period = str(cache_doc.get('budgetPeriod') or '').strip() or None
        prev_exp = str(cache_doc.get('budgetExpiresAt') or cache_doc.get('expiresAt') or '').strip() or None
        prev_exp_dt = _parse_tz_dt(prev_exp)
        prev_hold = cache_doc.get('budgetHold')
        raw_state_period = state.get('budgetPeriod') or state.get('runId')
        raw_state_exp = state.get('budgetExpiresAt')
        state_period = str(raw_state_period).strip() if isinstance(raw_state_period, str) and raw_state_period.strip() else None
        state_exp = str(raw_state_exp).strip() if isinstance(raw_state_exp, str) and raw_state_exp.strip() else None
        state_exp_dt = _parse_tz_dt(state_exp)
        valid_state_scope = bool(state_period and state_exp_dt is not None and state_exp_dt > now_kst)
        partial_or_invalid_state_scope = bool((raw_state_period is not None or raw_state_exp is not None) and not valid_state_scope)
        if prev_used == 0 and not prev_hold and not prev_period and prev_exp_dt is None:
            cache_doc['apiReportCallsUsed'] = 0
            if valid_state_scope:
                cache_doc['budgetPeriod'] = state_period
                cache_doc['budgetExpiresAt'] = state_exp
                cache_doc['expiresAt'] = state_exp
                cache_doc['hasBudgetPeriodOrExpiry'] = True
            elif not partial_or_invalid_state_scope:
                init_period = f'state:{state_checked}' if state_checked else f'initial:{now_kst.date().isoformat()}'
                init_exp = (now_kst + timedelta(hours=24)).isoformat()
                cache_doc['budgetPeriod'] = init_period
                cache_doc['budgetExpiresAt'] = init_exp
                cache_doc['expiresAt'] = init_exp
                cache_doc['hasBudgetPeriodOrExpiry'] = True
            else:
                cache_doc['hasBudgetPeriodOrExpiry'] = False
        elif (prev_period and prev_exp_dt is not None and now_kst >= prev_exp_dt
                and valid_state_scope and state_period != prev_period
                and state_exp_dt > prev_exp_dt
                and not state.get('budgetHold') and not cache_doc.get('manualResolutionRequired')):
            if prev_used > 0 or prev_hold:
                cache_doc.setdefault('budgetHistory', []).append({
                    'budgetPeriod': prev_period, 'budgetExpiresAt': prev_exp,
                    'apiReportCallsUsed': prev_used, 'budgetHold': prev_hold})
                cache_doc['budgetHistory'] = cache_doc['budgetHistory'][-24:]
            cache_doc.pop('budgetHold', None)
            cache_doc['apiReportCallsUsed'] = 0
            cache_doc['budgetPeriod'] = state_period
            cache_doc['budgetExpiresAt'] = state_exp
            cache_doc['expiresAt'] = state_exp
            cache_doc['hasBudgetPeriodOrExpiry'] = True
        else:
            has_scope = bool(prev_period and prev_exp_dt is not None)
            cache_doc['hasBudgetPeriodOrExpiry'] = has_scope
            if has_scope:
                cache_doc['budgetPeriod'] = prev_period
                cache_doc['budgetExpiresAt'] = prev_exp
                cache_doc['expiresAt'] = prev_exp
        budget_meta = {
            'budgetPeriod': cache_doc.get('budgetPeriod'),
            'budgetExpiresAt': cache_doc.get('budgetExpiresAt'),
            'expiresAt': cache_doc.get('budgetExpiresAt'),
            'hasBudgetPeriodOrExpiry': bool(cache_doc.get('hasBudgetPeriodOrExpiry')),
        }
        base_hold.update(budget_meta)
        if state.get('budgetHold'):
            return {**base_hold, 'reason': state['budgetHold'], 'budgetHold': state['budgetHold']}
        window_key = f'{url}|{start}|{end}'
        for target in state.get('targets', []):
            t_domain = (urlsplit(str(target.get('url') or '')).hostname or '').lower().removeprefix('www.')
            if target.get('url') == url or t_domain == domain:
                if (target.get('collectionError') or {}).get('manualResolutionRequired'):
                    return {**base_hold, 'reason': (target['collectionError'].get('type') or 'auth_or_config_hold'),
                            'collectionError': target['collectionError'], 'manualResolutionRequired': True}
                if target.get('budgetHold'):
                    return {**base_hold, 'reason': target['budgetHold'], 'budgetHold': target['budgetHold']}
            if target.get('url') == url:
                candidates = [target.get('selectionReport'), target.get('progress'),
                              *(target.get('baselines') or {}).values(), *(target.get('observations') or {}).values()]
                for item in candidates:
                    if _observation_fresh_and_valid(item, url, domain, start, end, now_kst):
                        rev = item.get('revenue') or matched_revenue(rev_doc, url, item)
                        return {**item, **budget_meta, 'ok': True, 'tool': 'inspect_url_acquisition', 'cached': True,
                                'status': 'collected', 'complete': True,
                                'qualifiedSessions': item['qualifiedSessions'],
                                'qualifiedPageViews': item['qualifiedPageViews'],
                                'revenue': rev, 'articleRevenue': rev.get('amount'),
                                'domainRevenueAllocated': False,
                                'revenueScope': 'Exact URL pagePerformance only when complete; domain revenue is never allocated to an article.',
                                'publicationVerified': False, 'businessOutcomeVerified': False}
        if domain in domain_holds and domain_holds[domain].get('manualResolutionRequired'):
            return {**base_hold, **domain_holds[domain], **budget_meta}
        cached = entries.get(window_key)
        if isinstance(cached, dict):
            if cached.get('status') == 'held' and cached.get('manualResolutionRequired'):
                return {**base_hold, **cached, **budget_meta}
            if _observation_fresh_and_valid(cached, url, domain, start, end, now_kst):
                return {**cached, **budget_meta, 'cached': True}
        budget_limit = min(12, int((state.get('policy') or {}).get('apiReportBudgetPerRun', 12)))
        state_used = int(state.get('lastApiReportBudgetUsed', 0))
        budget_used = state_used + int(cache_doc.get('apiReportCallsUsed', 0))
        if cache_doc.get('budgetHold') or budget_limit - budget_used < 2:
            hold_reason = str(cache_doc.get('budgetHold') or 'shared_api_report_budget_exhausted')
            cache_doc['budgetHold'] = hold_reason
            traffic.atomic_write(cache_file, cache_doc)
            return {**base_hold, 'reason': hold_reason,
                    'budgetHold': hold_reason,
                    'budgetLimit': budget_limit, 'budgetUsed': budget_used}
        settings = sites[domain]
        calls_spent = 0
        orig_ga_report = traffic.ga_report
        def _counted_ga_report(*g_args, **g_kwargs):
            nonlocal calls_spent
            calls_spent += 1
            return orig_ga_report(*g_args, **g_kwargs)
        try:
            with traffic.session(settings, cfg['analytics_readers'], 'https://www.googleapis.com/auth/analytics.readonly') as client:
                traffic.ga_report = _counted_ga_report
                try:
                    row = collect_window(client, settings['ga4_property'], url, start, end)
                finally:
                    traffic.ga_report = orig_ga_report
        except Exception as exc:
            if calls_spent > 0:
                cache_doc['apiReportCallsUsed'] = int(cache_doc.get('apiReportCallsUsed', 0)) + calls_spent
            manual = isinstance(exc, (KeyError, FileNotFoundError)) or any(s in str(exc).lower() for s in ('401', '403', 'credential', 'permission', 'invalid_grant'))
            hold_row = {**base_hold, 'status': 'held' if manual else 'failed', 'reason': type(exc).__name__,
                        'manualResolutionRequired': manual, 'apiReportCallsSpent': calls_spent,
                        'collectionError': {'type': type(exc).__name__, 'at': traffic.stamp(), 'status': 'unknown', 'manualResolutionRequired': manual}}
            if manual:
                domain_holds[domain] = {'reason': type(exc).__name__, 'manualResolutionRequired': True, 'collectionError': hold_row['collectionError']}
                entries[window_key] = hold_row
            if manual or calls_spent > 0:
                traffic.atomic_write(cache_file, cache_doc)
            return hold_row
        complete = bool(row.get('complete'))
        row['qualifiedSessions'] = row['breakdown']['attributed']['sessions'] if complete else None
        row['qualifiedPageViews'] = row['breakdown']['attributed']['pageViews'] if complete else None
        rev = matched_revenue(rev_doc, url, row)
        checked_str = str(row.get('checkedAt') or traffic.stamp()).replace('Z', '+00:00')
        try:
            checked_dt = datetime.fromisoformat(checked_str)
        except ValueError:
            checked_dt = now_kst
        entry_expires_at = (checked_dt + timedelta(hours=26)).isoformat()
        result = {**row, **budget_meta, 'expiresAt': entry_expires_at, 'ok': True, 'tool': 'inspect_url_acquisition', 'cached': False,
                  'status': 'collected' if complete else 'partial', 'complete': complete,
                  'revenue': rev, 'articleRevenue': rev.get('amount') if complete else None,
                  'domainRevenueAllocated': False,
                  'revenueScope': 'Exact URL pagePerformance only when complete; domain revenue is never allocated to an article.',
                  'publicationVerified': False, 'businessOutcomeVerified': False}
        cache_doc['apiReportCallsUsed'] = int(cache_doc.get('apiReportCallsUsed', 0)) + max(2, calls_spent)
        entries[window_key] = result
        if len(entries) > 64:
            cache_doc['entries'] = dict(list(entries.items())[-64:])
        traffic.atomic_write(cache_file, cache_doc)
        return result


def collect(path=STATE, now=None):
    now = now or datetime.now(KST)
    path = Path(path)
    with traffic.collector_lock(path.with_suffix('.lock')) as acquired:
        if not acquired:
            return {'status': 'busy'}
        state = traffic.read_json(path)
        if state.get('schema') != 'revenue-focus-v1' or not 1 <= len(state.get('targets', [])) <= 2:
            raise ValueError('One or two explicit measurement targets required')
        cfg = traffic.read_json(traffic.CONFIG)
        revenue = traffic.read_json(traffic.DATA / 'revenue.json')
        remaining_calls = min(12, int(state.get('policy', {}).get('apiReportBudgetPerRun', 12)))
        if remaining_calls < 2:
            raise ValueError('Invalid shared API budget')
        for target in state['targets']:
            if (target['checkpoints'] != observation_windows(target['observationStart'])
                    or target['baselineEnd'] >= target['observationStart']
                    or type(target['minimumSessions']) is not int or not 1 <= target['minimumSessions'] <= 100000):
                raise ValueError('Invalid target observation contract')
            for group in ('baselines', 'observations', 'preliminary'):
                target.setdefault(group, {})
            if (target.get('collectionError') or {}).get('manualResolutionRequired'):
                continue
            domain = urlsplit(target['url']).hostname.removeprefix('www.')
            jobs = []
            if not target.get('selectionReport'):
                end = now.date() - timedelta(days=1)
                jobs.append(('selection', '', (end-timedelta(days=6)).isoformat(), end.isoformat()))
            for horizon in target['checkpoints']:
                days = horizon['days']; key = str(days)
                if key not in target.setdefault('baselines', {}):
                    end = date.fromisoformat(target['baselineEnd'])
                    jobs.append(('baseline', key, (end-timedelta(days=days-1)).isoformat(), end.isoformat()))
                if now.date().isoformat() >= horizon['finalCollectionDate'] and key not in target.setdefault('observations', {}):
                    jobs.append(('observation', key, horizon['start'], horizon['end']))
                elif now.date().isoformat() >= horizon['reviewDate'] and key not in target.setdefault('preliminary', {}) and key not in target['observations']:
                    jobs.append(('preliminary', key, horizon['start'], horizon['end']))
            mature_end = min(now.date() - timedelta(days=3), date.fromisoformat(target['observationStart']) + timedelta(days=27))
            if mature_end >= date.fromisoformat(target['observationStart']) and (target.get('progress') or {}).get('end') != mature_end.isoformat():
                jobs.append(('progress', '', target['observationStart'], mature_end.isoformat()))
            if jobs:
                settings = cfg['sites'][domain]
                try:
                    with traffic.session(settings, cfg['analytics_readers'], 'https://www.googleapis.com/auth/analytics.readonly') as client:
                        for kind, key, start, end in jobs:
                            if remaining_calls < 2:
                                target['budgetHold'] = 'shared_api_report_budget_exhausted'
                                break
                            remaining_calls -= 2
                            row = collect_window(client, settings['ga4_property'], target['url'], start, end)
                            row['revenue'] = matched_revenue(revenue, target['url'], row)
                            if row['complete']:
                                if kind == 'progress':
                                    target['progress'] = row
                                elif kind == 'selection':
                                    row['provisional'] = True
                                    target['selectionReport'] = row
                                elif kind == 'preliminary':
                                    row['provisional'] = True
                                    target['preliminary'][key] = row
                                else:
                                    target['baselines' if kind == 'baseline' else 'observations'][key] = row
                            else:
                                target['lastIncompleteReport'] = row
                    target.pop('collectionError', None)
                except Exception as exc:
                    manual = isinstance(exc, (KeyError, FileNotFoundError)) or any(s in str(exc).lower() for s in ('401', '403', 'credential', 'permission', 'invalid_grant'))
                    target['collectionError'] = {'type': type(exc).__name__, 'at': traffic.stamp(), 'status': 'unknown',
                                                 'manualResolutionRequired': manual}
            for row in [r for group in ('baselines', 'observations', 'preliminary') for r in target.get(group, {}).values()]:
                if row.get('windowRevenueAttempted') or target.get('revenueCollectionHold') or remaining_calls < 2:
                    continue
                remaining_calls -= 2
                row['revenue'] = collect_exact_revenue(cfg, target['url'], row)
                row['windowRevenueAttempted'] = True
                if row['revenue'].get('manualResolutionRequired'):
                    target['revenueCollectionHold'] = row['revenue']
            for key, row in target.get('observations', {}).items():
                target.setdefault('evaluations', {})[key] = evaluate(target['baselines'].get(key, {}), row, target['minimumSessions'], int(key))
            due = [h['finalCollectionDate'] for h in target['checkpoints'] if str(h['days']) not in target.get('observations', {})]
            due += [h['reviewDate'] for h in target['checkpoints'] if str(h['days']) not in target.get('preliminary', {}) and str(h['days']) not in target.get('observations', {})]
            target['nextCollectionDate'] = min(due) if due else None
        state['checkedAt'] = traffic.stamp()
        state['lastApiReportBudgetUsed'] = min(12, int(state.get('policy', {}).get('apiReportBudgetPerRun', 12))) - remaining_calls
        state['status'] = 'observing' if all(len(t.get('baselines', {})) == 3 and not t.get('collectionError') for t in state['targets']) else 'measurement_held'
        if all(len(t.get('observations', {})) == 3 for t in state['targets']):
            state['status'] = 'observation_complete'
        traffic.atomic_write(path, state)
        return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collect', action='store_true', required=True)
    parser.parse_args()
    result = collect()
    print(json.dumps({'status': result.get('status'), 'checkedAt': result.get('checkedAt'),
                      'targets': [{k: r.get(k) for k in ('url', 'nextCollectionDate', 'collectionError')} for r in result.get('targets', [])]}))
