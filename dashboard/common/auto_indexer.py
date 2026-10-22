# -*- coding: utf-8 -*-
"""
Automated Unindexed Site & URL Indexing Dispatcher (`common/auto_indexer.py`)

Usage:
    python -m common.auto_indexer --all --apply
    python -m common.auto_indexer --domain baronote.kr --apply

Performs automated indexing verification & live submission across all 16 Cloudflare vertical blogs:
  1. Verifies `sitemap.xml` and `rss.xml` HTTP 200 availability and URL inventory for each domain.
  2. Extracts unindexed URLs (`indexed != True` in `dashboard/data/metrics.json`), prioritizing 0% indexed sites
     (`baronote.kr`, `smilenote.kr`, `topnote.kr`) and low-indexed sites (`nolplace.com`, `justinfo.co.kr`, etc.).
  3. Submits unindexed URLs + full URL inventory via Naver Search Advisor IndexNow API (`searchadvisor.naver.com/indexnow`)
     and IndexNow global endpoint (`api.indexnow.org/indexnow`).
  4. Submits/refreshes Google Search Console sitemaps (`sitemap.xml`, `rss.xml`) via Google Webmasters API session
     and logs unindexed URL recovery queue entries into `dashboard/data/indexing-recovery.json` & `dashboard/data/metrics.json`.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BASE_DIR / "dashboard") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "dashboard"))

from common.channel_attribution import is_dummy_rescue_url

KST = ZoneInfo("Asia/Seoul")
SERVER_DATA_DIR = BASE_DIR / 'dashboard' / 'data'
DASHBOARD_DATA_DIR = BASE_DIR / "dashboard" / "data" / "public"
METRICS_PATH = SERVER_DATA_DIR / "metrics.json"
CONFIG_PATH = SERVER_DATA_DIR / "metrics-config.json"
RECOVERY_PATH = SERVER_DATA_DIR / "indexing-recovery.json"


def _now_kst_iso() -> str:
    return datetime.datetime.now(KST).isoformat()


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {} if default is None else default


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _check_rss_feed(domain: str) -> Dict[str, Any]:
    for rss_path in ("/rss.xml", "/feed.xml", "/rss"):
        url = f"https://www.{domain}{rss_path}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200 and ("<rss" in r.text[:500] or "<feed" in r.text[:500] or "<?xml" in r.text[:200]):
                return {"status": "available", "httpStatus": 200, "url": url}
        except Exception:
            continue
    return {"status": "unavailable", "httpStatus": 404, "url": f"https://www.{domain}/rss.xml"}


def _validate_candidates(site, urls):
    """Reuse at most one hour of actual public evidence, otherwise recheck HTTP."""
    from dashboard.indexing_submissions import validate_public_url
    report = _read_json(SERVER_DATA_DIR / 'indexing-discovery-latest.json', {})
    domain = next((r for r in report.get('domains', []) if r.get('domain') == site['site_id']), {})
    known = {r['url']: r for r in domain.get('validations', [])}
    output = []
    for url in urls:
        row = known.get(url, {})
        try:
            checked = datetime.datetime.fromisoformat(row['checkedAt'])
            fresh = datetime.timedelta(0) <= datetime.datetime.now(datetime.timezone.utc)-checked < datetime.timedelta(hours=1)
        except (ValueError, KeyError, TypeError):
            fresh = False
        if not fresh or row.get('valid') is not True or row.get('canonical') != url:
            row = validate_public_url(site, url)
        output.append(row)
    return output


def _queue_searchadvisor_candidates(domain_reports):
    from dashboard.collectors.searchadvisor import queue_crawl_candidates
    candidates = [u for rep in domain_reports for u in rep['_validatedCandidates']]
    validation_path = SERVER_DATA_DIR / 'searchadvisor-public-validation.json'
    _atomic_write_json(validation_path, {"checkedAt": _now_kst_iso(),
        "domains": [{"domain": rep['domain'], "validations": rep['_publicValidations']} for rep in domain_reports]})
    return queue_crawl_candidates(candidates, evidence={
        "checkedAt": _now_kst_iso(), "source": str(validation_path),
        "scope": "public inventory, HTTP 200, exact www canonical, no noindex; indexing unconfirmed"})


def _consume_searchadvisor_queue(config, *, apply):
    """Single in-process consumer; no hidden subprocess or private API fallback."""
    policy = config.get('searchadvisor', {})
    if not apply or policy.get('request_authorized') is not True or policy.get('account') != 'soultin':
        return {'status': 'explicit_ui_authorization_required', 'submitted': 0, 'started': False}
    if policy.get('mode') != 'authorized_visible_ui':
        return {'status': 'explicit_ui_authorization_required', 'submitted': 0, 'started': False}
    from dashboard.collectors.searchadvisor_ui import run
    try:
        return run(apply=True)
    except Exception as exc:
        return {'status': 'consumer_unavailable', 'submitted': 0, 'errorType': type(exc).__name__}


def run_auto_indexing(
    target_domain: Optional[str] = None,
    apply: bool = True,
) -> Dict[str, Any]:
    """
    Execute automated sitemap/RSS verification, Naver IndexNow bulk submission, and Google Search Console
    sitemap + unindexed URL submission across all 16 CF domains (or `target_domain`).
    """
    import metrics as dm

    # 1. Discover/verify IndexNow keys first
    if apply:
        try:
            dm.discover_indexnow_keys()
        except Exception:
            pass

    config = _read_json(CONFIG_PATH, {})
    snapshot = _read_json(METRICS_PATH, {})
    cf_sites = [s for s in dm.inventory() if s.get("platform") == "cf"]
    if target_domain and target_domain.lower() != "all":
        clean_t = target_domain.lower().replace("www.", "").strip()
        cf_sites = [s for s in cf_sites if s["site_id"] == clean_t]

    def _process_domain(site: Dict[str, Any]) -> Dict[str, Any]:
        dom = site["site_id"]
        settings = (config.get("sites") or {}).get(dom, {})
        rec = (snapshot.get("sites") or {}).get(dom, {})

        # 1) Verify sitemap.xml & rss.xml
        try:
            sm = dm.sitemap_status(site, settings)
        except Exception as exc:
            sm = {"status": "error", "reason": str(exc)}
        rss_info = _check_rss_feed(dom)

        posts_info = rec.get("posts") or {}
        all_urls: List[str] = list(posts_info.get("urls") or [])
        inventory_complete = posts_info.get("complete") is True
        if not all_urls and sm.get("locations"):
            origin = site["url"].rstrip("/")
            all_urls = [u for u in sm["locations"] if u.rstrip("/") != origin]
            inventory_complete = sm.get("status") == "available" and sm.get("kind") == "urlset"

        excluded_urls = [u for u in all_urls if is_dummy_rescue_url(u)]
        all_urls = [u for u in all_urls if not is_dummy_rescue_url(u)]

        # Identify indexed vs unindexed URLs
        google_info = rec.get("google") or {}
        g_url_rows = google_info.get("urls") or []
        indexed_set = {r.get("url") for r in g_url_rows if r.get("indexed") is True
                       and r.get("url") in all_urls and not is_dummy_rescue_url(r.get("url"))}
        inspected_set = {r.get("url") for r in g_url_rows if isinstance(r.get("indexed"), bool)
                         and r.get("url") in all_urls and not is_dummy_rescue_url(r.get("url"))}
        inspection_complete = bool(all_urls) and set(all_urls) <= inspected_set
        unindexed_urls = [u for u in all_urls if u not in indexed_set]
        indexed_count = len(indexed_set) if inspection_complete and inventory_complete else None
        total_count = len(all_urls) if inventory_complete else None
        unindexed_count = total_count - indexed_count if inventory_complete and inspection_complete else None

        # Discovery receipts are independent of registration, crawling, or indexing.
        from dashboard.indexing_submissions import submit_indexnow, canonical_url
        target_push_urls = []
        for candidate in unindexed_urls:
            try:
                target_push_urls.append(canonical_url(site, candidate))
            except ValueError:
                continue
        validations = _validate_candidates(site, target_push_urls) if apply else []
        if apply:
            target_push_urls = [row['url'] for row in validations if row.get('valid') is True]
        indexnow_results = submit_indexnow(site, settings, target_push_urls) if apply else {}
        naver_result = indexnow_results.get("naver", {})
        naver_status = naver_result.get("status", "not_attempted")
        naver_http = naver_result.get("httpStatus")
        naver_submitted_cnt = naver_result.get("submittedCount", 0)

        # 3) Submit/verify Google Search Console Sitemap & unindexed URLs
        google_sub_status = "unknown"
        google_method = "sitemap"
        old_google_req = ((rec.get("indexingRequest") or {}).get("google")) or {}
        previous_submission = old_google_req if old_google_req.get("status") == "submitted" else old_google_req.get("previousSubmission")
        if isinstance(previous_submission, dict):
            previous_submission = {k: v for k, v in previous_submission.items() if k != "previousSubmission"}
        if apply:
            site_sess = None
            try:
                site_sess = dm.google_session(config, settings)
            except Exception:
                site_sess = None
            try:
                req_res = dm.request_indexing(site_sess, site, settings, [], sm, indexnow=False)
            except Exception:
                req_res = {}
            g_res = (req_res.get("google") or {})
            if g_res.get("status") == "held_dummy_sitemap":
                google_sub_status = "held_dummy_sitemap"
            elif g_res.get("status") == "submitted":
                google_sub_status = "submitted"
                google_method = g_res.get("method") or "sitemap"
            else:
                google_sub_status = g_res.get("status") or "not_confirmed"
        else:
            google_sub_status = "not_attempted"

        now_ts = _now_kst_iso()
        updated_req = {
            "requestedAt": now_ts,
            "urls": all_urls,
            "excludedDummyCount": len(excluded_urls),
            "excludedDummyUrls": excluded_urls,
            "unconfirmedUrlsPinged": naver_submitted_cnt,
            "indexnow": indexnow_results,
            "google": {
                "status": "submitted" if google_sub_status in ("submitted", "submitted_sitemap") else google_sub_status,
                "method": google_method,
                "property": settings.get("gsc_property") or settings.get("search_property") or f"sc-domain:{dom}",
                "sitemap": sm.get("url") or f"https://www.{dom}/sitemap.xml",
                "rss": rss_info.get("url"),
                "submittedAt": now_ts if apply and google_sub_status == "submitted" else None,
                "previousSubmission": previous_submission or None,
                "indexed": indexed_count,
            },
            "naver": {
                "status": naver_status,
                "method": "IndexNow",
                "httpStatus": naver_http or None,
                "submittedCount": naver_submitted_cnt,
                "unconfirmedCandidateCount": len(unindexed_urls),
                "registered": None, "crawled": None,
                "submittedAt": now_ts if naver_submitted_cnt else None,
                "indexed": None,
            },
        }

        return {
            "domain": dom,
            "totalPosts": total_count,
            "excludedDummyCount": len(excluded_urls),
            "indexedCount": indexed_count,
            "unindexedCount": unindexed_count,
            "isZeroIndexedPriority": inventory_complete and inspection_complete and indexed_count == 0,
            "eligibleCandidateCount": len(all_urls),
            "knownIndexedUrlCount": len(indexed_set),
            "inventoryComplete": inventory_complete,
            "inspectionComplete": inspection_complete,
            "countScope": "Filtered complete inventory and explicit URL inspection only; legacy aggregates are not reused",
            "sitemapStatus": sm.get("status", "unknown"),
            "sitemapUrlsCount": len(sm.get("locations") or all_urls),
            "rssStatus": rss_info.get("status", "unknown"),
            "naverIndexNow": {
                "status": updated_req["naver"]["status"],
                "httpStatus": updated_req["naver"]["httpStatus"],
                "submittedUrls": updated_req["naver"]["submittedCount"],
            },
            "googleSearchConsole": {
                "status": updated_req["google"]["status"],
                "method": updated_req["google"]["method"],
                "submittedUrls": 0,
                "discoveryHintUrlCount": len(all_urls) if google_sub_status == "submitted" else 0,
            },
            "sampleUnindexedUrls": unindexed_urls[:5],
            "_sitemapObj": sm,
            "_indexingRequestObj": updated_req,
            "_validatedCandidates": target_push_urls if apply else [],
            "_publicValidations": validations,
        }

    domain_reports: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_process_domain, s): s["site_id"] for s in cf_sites}
        for fut in as_completed(futs):
            domain_reports.append(fut.result())

    # Sort with 0% indexed sites first, then by unindexedCount descending
    domain_reports.sort(key=lambda r: (0 if r["isZeroIndexedPriority"] else 1, -(r["unindexedCount"] or 0), r["domain"]))

    # Direct Search Advisor browser operations require an explicit UI workflow.
    # An IndexNow receipt never establishes console ownership or crawl completion.
    sa_direct_map: Dict[str, Dict[str, Any]] = {}
    searchadvisor_queue = {"status": "not_attempted", "queued": 0}
    if apply:
        searchadvisor_queue = _queue_searchadvisor_candidates(domain_reports)
        searchadvisor_queue['consumer'] = _consume_searchadvisor_queue(config, apply=True)

    now_stamp = _now_kst_iso()
    if apply:
        latest = _read_json(METRICS_PATH, {})
        for rep in domain_reports:
            dom = rep["domain"]
            sa_info = sa_direct_map.get(dom)
            if sa_info:
                rep["naverIndexNow"]["searchAdvisorConsole"] = sa_info
                rep["_indexingRequestObj"]["naver"]["searchAdvisorConsole"] = sa_info
            site_rec = latest.setdefault("sites", {}).setdefault(dom, {})
            site_rec["sitemap"] = rep["_sitemapObj"]
            site_rec["indexingRequest"] = {**(site_rec.get("indexingRequest") or {}), **rep["_indexingRequestObj"]}
            site_rec["checkedAt"] = now_stamp
        latest["checkedAt"] = now_stamp
        latest.setdefault("inspectionAutomation", {})["lastAutoIndexerRun"] = {
            "at": now_stamp,
            "domainsCount": len(domain_reports),
            "totalUnindexedSubmitted": sum(r["naverIndexNow"]["submittedUrls"] for r in domain_reports),
            "totalUrlsSubmitted": sum(r["naverIndexNow"]["submittedUrls"] for r in domain_reports),
            "searchAdvisorDirectCrawlAccount": config.get('searchadvisor', {}).get('account'),
            "searchAdvisorDirectCrawlSubmitted": searchadvisor_queue.get('consumer', {}).get('submitted', 0),
            "searchAdvisorConsumer": searchadvisor_queue.get('consumer'),
        }
        _atomic_write_json(METRICS_PATH, latest)

        # Also sync dashboard/data/public/metrics.json if dashboard/data exists
        if DASHBOARD_DATA_DIR.exists():
            try:
                _atomic_write_json(DASHBOARD_DATA_DIR / "metrics.json", latest)
            except Exception:
                pass

        # Record batch event in indexing-recovery.json
        recovery_doc = _read_json(RECOVERY_PATH, {"events": []})
        for rep in domain_reports:
            recovery_doc.setdefault("events", []).append(
                {
                    "kind": "auto_indexer_batch",
                    "domain": rep["domain"],
                    "outcome": rep["naverIndexNow"]["status"],
                    "unindexedSubmitted": rep["unindexedCount"],
                    "totalSubmitted": rep["naverIndexNow"]["submittedUrls"],
                    "naverHttp": rep["naverIndexNow"]["httpStatus"],
                    "googleStatus": rep["googleSearchConsole"]["status"],
                    "at": now_stamp,
                }
            )
        recovery_doc["events"] = recovery_doc["events"][-400:]
        _atomic_write_json(RECOVERY_PATH, recovery_doc)

    # Strip internal objects before returning JSON
    clean_reports = []
    for rep in domain_reports:
        c = {k: v for k, v in rep.items() if not k.startswith("_")}
        clean_reports.append(c)

    zero_indexed_domains = [r["domain"] for r in clean_reports if r["isZeroIndexedPriority"]]
    def complete_total(field):
        return sum(r[field] for r in clean_reports) if all(r[field] is not None for r in clean_reports) else None
    total_posts = complete_total("totalPosts")
    total_indexed = complete_total("indexedCount")
    total_unindexed = complete_total("unindexedCount")
    total_submitted_urls = sum(r["naverIndexNow"]["submittedUrls"] for r in clean_reports)
    naver_ok_domains = sum(1 for r in clean_reports if r["naverIndexNow"]["status"] == "ping_accepted")
    google_ok_domains = sum(1 for r in clean_reports if r["googleSearchConsole"]["status"] == "submitted")

    return {
        "ok": True,
        "executedAt": now_stamp,
        "domainsProcessed": len(clean_reports),
        "zeroIndexedPriorityDomains": zero_indexed_domains,
        "totalInventoryPosts": total_posts,
        "totalIndexedPosts": total_indexed,
        "totalUnindexedPosts": total_unindexed,
        "totalSubmittedUrls": total_submitted_urls,
        "naverIndexNowSuccessDomains": naver_ok_domains,
        "googleSitemapSuccessDomains": google_ok_domains,
        "searchAdvisorCrawl": searchadvisor_queue,
        "domains": clean_reports,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Automated Unindexed Site & URL Indexing Dispatcher (`@trace` + `@publi`)")
    parser.add_argument("--all", action="store_true", help="Run across all 16 CF domains")
    parser.add_argument("--domain", default="all", help="Target specific CF domain (or 'all')")
    parser.add_argument("--apply", action="store_true", default=True, help="Execute live IndexNow & GSC submissions and update metrics.json")
    args = parser.parse_args()

    target = "all" if args.all else args.domain
    res = run_auto_indexing(target_domain=target, apply=args.apply)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
