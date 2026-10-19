"""Evidence ledger and daily budget for visible SearchAdvisor operations.

The browser executor must use the supported UI. This module never scrapes
session tokens, calls private Naver endpoints, or treats submission as indexing.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from cf_posting.domain_themes import DOMAIN_WORKER_NAMES
from common.channel_attribution import is_dummy_rescue_url
from dashboard.metrics import collector_lock, atomic_write

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "server/data/searchadvisor-status.json"
KST = ZoneInfo("Asia/Seoul")
DAILY_CAP = 50


def now():
    return datetime.now(KST).isoformat()


def canonical_candidate(url):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname in
                {"www." + domain for domain in DOMAIN_WORKER_NAMES} and
                not parsed.query and not parsed.fragment and not parsed.username and
                not parsed.password and not parsed.port and parsed.path not in ("", "/") and
                not is_dummy_rescue_url(url))
    except (ValueError, TypeError):
        return False


def queue_crawl_candidates(urls, *, evidence, path=LEDGER):
    """Queue URLs whose public HTTP/canonical/inventory checks passed upstream.

    An accepted API inventory is not an indexing observation. No UI submission
    occurs here; the CUA executor reserves its daily slot immediately before it.
    """
    if not isinstance(evidence, dict) or not evidence.get("checkedAt") or not evidence.get("source"):
        raise ValueError("Timestamped public validation evidence is required")
    counts = {"queued": 0, "duplicate": 0, "rejected": 0}
    with locked_ledger(path) as state:
        queue = state.setdefault("crawlQueue", [])
        known = {x["url"] for x in queue + state["crawlRequests"]}
        for url in urls:
            if not canonical_candidate(url):
                counts["rejected"] += 1
            elif url in known:
                counts["duplicate"] += 1
                pending = next((item for item in queue if item['url'] == url), None)
                if pending and not any(x['url'] == url for x in state['crawlRequests']):
                    pending['publicValidation'] = evidence
            else:
                queue.append({"url": url, "status": "queued", "queuedAt": now(),
                              "publicValidation": evidence, "indexed": None})
                known.add(url)
                counts["queued"] += 1
    return {"status": "blocked_ui_required", **counts, "ledgerPath": str(path)}


@contextmanager
def locked_ledger(path=LEDGER):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    for _ in range(50):
        with collector_lock(lock) as acquired:
            if acquired:
                state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
                    "schemaVersion": 1, "sites": {}, "crawlRequests": [], "dailyCap": DAILY_CAP}
                yield state
                state["checkedAt"] = now()
                atomic_write(path, state)
                return
        time.sleep(.1)
    raise RuntimeError('SearchAdvisor ledger busy')


def record_history_baseline(urls, *, scope_sites, complete, evidence, path=LEDGER):
    """Account-wide visible history; never infer an empty history from missing UI.

    Caller must enumerate every site in the account's visible site list and all
    today's history pages. External URLs exclude today's own ledger requests.
    """
    if complete is not True or not scope_sites or not isinstance(evidence, dict) or not all(
            evidence.get(k) for k in ('source', 'checkedAt', 'siteListComplete', 'allHistoryPagesComplete')):
        raise ValueError('Complete account-wide visible history evidence required')
    if not isinstance(urls, list) or any(not isinstance(u, str) or urlsplit(u).scheme not in ('http','https')
            or urlsplit(u).username or urlsplit(u).password for u in urls):
        raise ValueError('Visible public history URLs required')
    today = now()[:10]
    checked = datetime.fromisoformat(evidence['checkedAt'])
    if checked.tzinfo is None or checked.astimezone(KST).date() != datetime.now(KST).date():
        raise ValueError('Today timezone-aware history evidence required')
    with locked_ledger(path) as state:
        own = {x['url'] for x in state['crawlRequests'] if x['reservedAt'][:10] == today}
        previous = state.get('historyBaseline', {})
        occurrences = Counter(urls)
        if previous.get('dayKST') == today:
            occurrences |= Counter(previous.get('urlOccurrences', {u: 1 for u in previous.get('observedUrls', [])}))
        # Every visible request row consumes quota, even repeated URLs. A single
        # own ledger reservation can account for at most one visible occurrence.
        external_count = sum(max(0, count - (1 if url in own else 0)) for url, count in occurrences.items())
        baseline = {'dayKST': today, 'scope': 'entire_visible_account_site_list', 'scopeSites': sorted(set(scope_sites)),
                    'complete': True, 'observedUrls': sorted(occurrences), 'urlOccurrences': dict(occurrences),
                    'observedRequestCount': sum(occurrences.values()), 'externalCount': max(external_count,
                        previous.get('externalCount', 0) if previous.get('dayKST') == today else 0),
                    'evidence': evidence, 'checkedAt': now()}
        state['historyBaseline'] = baseline
        return baseline


def record_site(domain, *, registration=None, ownership=None, sitemap=None,
                rss=None, evidence=None, path=LEDGER):
    if domain not in DOMAIN_WORKER_NAMES:
        raise ValueError('Site is outside the configured domain inventory')
    with locked_ledger(path) as state:
        site = state["sites"].setdefault(domain, {"site": "https://www." + domain,
            "indexed": None, "indexingStatus": "not_verified"})
        for key, value in (("registration", registration), ("ownership", ownership),
                           ("sitemap", sitemap), ("rss", rss)):
            if value is not None:
                site[key] = {"status": value, "checkedAt": now(), "evidence": evidence}
        site["checkedAt"] = now()


def reserve_crawl(url, *, external_today_count=0, path=LEDGER):
    """Reserve before UI submission; unknown outcomes consume the daily budget.

    Caller must inspect today's visible history first and pass requests already
    submitted outside this ledger. Cap is conservative across this account.
    """
    if not canonical_candidate(url):
        raise ValueError("A configured public canonical URL is required")
    if type(external_today_count) is not int or external_today_count < 0:
        raise ValueError("Visible-history baseline must be a nonnegative count")
    today = now()[:10]
    with locked_ledger(path) as state:
        baseline = state.get('historyBaseline', {})
        if baseline.get('dayKST') != today or baseline.get('complete') is not True:
            raise ValueError('Account-wide history unconfirmed; crawl submission paused')
        candidate = next((item for item in state.get("crawlQueue", []) if item["url"] == url), None)
        proof = (candidate or {}).get("publicValidation", {})
        if not proof.get("checkedAt") or not proof.get("source"):
            raise ValueError("URL has no validated public inventory queue evidence")
        checked = datetime.fromisoformat(proof["checkedAt"])
        if checked.tzinfo is None:
            raise ValueError('Public validation timezone is unknown')
        age = datetime.now(KST) - checked
        if age.total_seconds() < -60 or age.total_seconds() > 86400:
            raise ValueError("Public validation is stale; revalidate before submission")
        if any(item["url"] == url for item in state["crawlRequests"]):
            raise ValueError("URL already reserved or submitted; inspect before retrying")
        if url in baseline.get('observedUrls', []):
            raise ValueError('URL already in visible history; duplicate suppressed')
        used = sum(item["reservedAt"][:10] == today for item in state["crawlRequests"])
        external_today_count = max(external_today_count, baseline.get('externalCount', 0))
        baseline['externalCount'] = external_today_count
        if used + external_today_count >= DAILY_CAP:
            raise ValueError("Daily SearchAdvisor crawl request cap reached")
        state["crawlRequests"].append({"url": url, "reservedAt": now(),
            "status": "reserved", "indexed": None})


def crawl_budget(*, path=LEDGER):
    state = json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else {}
    baseline = state.get('historyBaseline', {})
    if baseline.get('complete') is not True or baseline.get('dayKST') != now()[:10]:
        return {'status': 'history_unconfirmed', 'remaining': None, 'limit': DAILY_CAP}
    own = sum(x['reservedAt'][:10] == now()[:10] for x in state.get('crawlRequests', []))
    used = own + baseline.get('externalCount', 0)
    return {'status': 'daily_budget_exhausted' if used >= DAILY_CAP else 'available',
            'used': used, 'remaining': max(0, DAILY_CAP-used), 'limit': DAILY_CAP}


def complete_crawl(url, *, status, evidence, path=LEDGER):
    if status not in ("requested", "request_received", "blocked_captcha", "failed", "unknown"):
        raise ValueError("A visible submission outcome is required")
    if not evidence:
        raise ValueError("Evidence is required")
    with locked_ledger(path) as state:
        item = next(item for item in state["crawlRequests"] if item["url"] == url)
        if item["status"] != "reserved":
            if item["status"] == status:
                return
            raise ValueError("Conflicting finalized request outcome requires review")
        item.update(status=status, checkedAt=now(), evidence=evidence, indexed=None)


def install_verification(domain, value, *, session, api_key):
    """Deploy only the public verification meta setting through the site's API."""
    import re
    if domain not in DOMAIN_WORKER_NAMES:
        raise ValueError("Site is outside the configured domain inventory")
    if not re.fullmatch(r"[a-fA-F0-9]{32,64}", value):
        raise ValueError("Unexpected verification meta format")
    origin = "https://www." + domain
    response = session.put(origin + "/api/settings", headers={"x-api-key": api_key},
                           json={"naver_verification": value}, timeout=30)
    response.raise_for_status()
    page = session.get(origin + "/", timeout=30)
    page.raise_for_status()
    if not re.search(r'naver-site-verification[^>]+' + re.escape(value), page.text):
        raise RuntimeError("Public verification meta not visible yet")
    return {"domain": domain, "verificationMetaPublished": True, "checkedAt": now()}
