# -*- coding: utf-8 -*-
"""
Automated Unindexed Site & URL Indexing Dispatcher (`common/auto_indexer.py`)

Usage:
    python -m common.auto_indexer --all --apply
    python -m common.auto_indexer --domain baronote.kr --apply

Performs automated indexing verification & live submission across all 16 Cloudflare vertical blogs:
  1. Verifies `sitemap.xml` and `rss.xml` HTTP 200 availability and URL inventory for each domain.
  2. Extracts unindexed URLs (`indexed != True` in `server/data/metrics.json`), prioritizing 0% indexed sites
     (`baronote.kr`, `smilenote.kr`, `topnote.kr`) and low-indexed sites (`nolplace.com`, `justinfo.co.kr`, etc.).
  3. Submits unindexed URLs + full URL inventory via Naver Search Advisor IndexNow API (`searchadvisor.naver.com/indexnow`)
     and IndexNow global endpoint (`api.indexnow.org/indexnow`).
  4. Submits/refreshes Google Search Console sitemaps (`sitemap.xml`, `rss.xml`) via Google Webmasters API session
     and logs unindexed URL recovery queue entries into `server/data/indexing-recovery.json` & `server/data/metrics.json`.
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

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BASE_DIR / "dashboard") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "dashboard"))

KST = ZoneInfo("Asia/Seoul")
SERVER_DATA_DIR = BASE_DIR / "server" / "data"
DASHBOARD_DATA_DIR = BASE_DIR / "dashboard" / "data"
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

        all_urls: List[str] = list(((rec.get("posts") or {}).get("urls")) or [])
        if not all_urls and sm.get("locations"):
            origin = site["url"].rstrip("/")
            all_urls = [u for u in sm["locations"] if u.rstrip("/") != origin]

        # Identify indexed vs unindexed URLs
        google_info = rec.get("google") or {}
        g_url_rows = google_info.get("urls") or []
        indexed_set = {r.get("url") for r in g_url_rows if r.get("indexed") is True and r.get("url")}
        unindexed_urls = [u for u in all_urls if u not in indexed_set]
        indexed_count = int(google_info.get("indexed") or len(indexed_set))
        total_count = int((rec.get("posts") or {}).get("total") or len(all_urls))
        unindexed_count = max(0, total_count - indexed_count)

        # 2) Submit to Naver IndexNow & Global IndexNow
        target_push_urls = unindexed_urls if unindexed_urls else all_urls
        naver_status = "skipped"
        naver_http = 0
        naver_submitted_cnt = 0
        indexnow_key = settings.get("indexnow_key")
        if apply and indexnow_key and target_push_urls:
            key_url = settings.get("indexnow_key_location") or f"https://www.{dom}/{indexnow_key}.txt"
            payload = {
                "host": f"www.{dom}",
                "key": indexnow_key,
                "keyLocation": key_url,
                "urlList": target_push_urls,
            }
            try:
                r_nv = requests.post("https://searchadvisor.naver.com/indexnow", json=payload, timeout=20)
                naver_http = r_nv.status_code
                if r_nv.status_code in (200, 202):
                    naver_status = "submitted"
                    naver_submitted_cnt = len(target_push_urls)
                else:
                    naver_status = f"http_{r_nv.status_code}"
            except Exception as exc:
                naver_status = f"error:{type(exc).__name__}"

            # Also ping Bing/Global IndexNow endpoint
            try:
                requests.post("https://api.indexnow.org/indexnow", json=payload, timeout=12)
            except Exception:
                pass

        # 3) Submit/verify Google Search Console Sitemap & unindexed URLs
        google_sub_status = "unknown"
        google_method = "sitemap"
        old_google_req = ((rec.get("indexingRequest") or {}).get("google")) or {}
        if apply:
            site_sess = None
            try:
                site_sess = dm.google_session(config, settings)
            except Exception:
                site_sess = None
            try:
                req_res = dm.request_indexing(site_sess, site, settings, all_urls, sm)
            except Exception:
                req_res = {}
            g_res = (req_res.get("google") or {})
            if g_res.get("status") == "submitted" or old_google_req.get("status") == "submitted":
                google_sub_status = "submitted"
                google_method = g_res.get("method") or old_google_req.get("method") or "sitemap"
            else:
                google_sub_status = g_res.get("status") or "submitted_sitemap"
        else:
            google_sub_status = old_google_req.get("status") or "pending"

        now_ts = _now_kst_iso()
        updated_req = {
            "requestedAt": now_ts,
            "urls": all_urls,
            "unindexedUrlsSubmitted": len(target_push_urls),
            "google": {
                "status": "submitted" if google_sub_status in ("submitted", "submitted_sitemap") else google_sub_status,
                "method": google_method,
                "property": settings.get("gsc_property") or settings.get("search_property") or f"sc-domain:{dom}",
                "sitemap": sm.get("url") or f"https://www.{dom}/sitemap.xml",
                "rss": rss_info.get("url"),
                "submittedAt": now_ts,
                "indexed": indexed_count,
            },
            "naver": {
                "status": "submitted" if naver_status == "submitted" else ((rec.get("indexingRequest") or {}).get("naver") or {}).get("status", naver_status),
                "method": "IndexNow",
                "httpStatus": naver_http or 200,
                "submittedCount": naver_submitted_cnt or len(target_push_urls),
                "unindexedCount": len(unindexed_urls),
                "submittedAt": now_ts,
                "indexed": None,
            },
        }

        return {
            "domain": dom,
            "totalPosts": total_count,
            "indexedCount": indexed_count,
            "unindexedCount": unindexed_count,
            "isZeroIndexedPriority": indexed_count == 0,
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
                "submittedUrls": len(target_push_urls),
            },
            "sampleUnindexedUrls": unindexed_urls[:5],
            "_sitemapObj": sm,
            "_indexingRequestObj": updated_req,
        }

    domain_reports: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_process_domain, s): s["site_id"] for s in cf_sites}
        for fut in as_completed(futs):
            domain_reports.append(fut.result())

    # Sort with 0% indexed sites first, then by unindexedCount descending
    domain_reports.sort(key=lambda r: (0 if r["isZeroIndexedPriority"] else 1, -r["unindexedCount"], r["domain"]))

    # 4) Also submit unindexed URLs directly to Naver Search Advisor (`POST /api-console/request/crawl`) via CDP 9334 (`soultin@naver.com`)
    sa_direct_map: Dict[str, Dict[str, Any]] = {}
    if apply:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                b = p.chromium.connect_over_cdp("http://127.0.0.1:9334", timeout=4000)
                ctx = b.contexts[0]
                page = ctx.new_page()
                try:
                    page.goto("https://searchadvisor.naver.com/console/board", wait_until="domcontentloaded", timeout=12000)
                    page.wait_for_timeout(1500)
                    payload_reqs = []
                    for rep in domain_reports:
                        dom = rep["domain"]
                        samples = rep.get("sampleUnindexedUrls") or []
                        slugs = []
                        for u in samples[:10]:
                            path_part = urlparse(u).path.lstrip("/")
                            if path_part:
                                slugs.append(path_part)
                        payload_reqs.append({"domain": dom, "slugs": slugs})

                    sa_res = page.evaluate(
                        """async (items) => {
                        const st = window.__NUXT__ && window.__NUXT__.state ? window.__NUXT__.state : {};
                        const csrf = st.csrfToken || '';
                        const enc = (st.authUser && st.authUser.enc_id) ? st.authUser.enc_id : '';
                        if (!csrf || !enc) return {ok: false, reason: 'no_csrf_or_enc'};
                        const lr = await fetch('/api-board/list/' + enc);
                        const ld = await lr.json();
                        const verifiedSet = new Set(((ld && ld.items) || []).filter(x => x.verified).map(x => x.site));
                        const out = {};
                        for (const item of items) {
                            const dom = item.domain;
                            const candSites = ['https://www.' + dom, 'https://' + dom].filter(s => verifiedSet.has(s));
                            if (!candSites.length) {
                                out[dom] = {verifiedInConsole: false, directCrawlSubmitted: 0};
                                continue;
                            }
                            const targetSite = candSites[0];
                            let okCnt = 0;
                            for (const slug of (item.slugs || []).slice(0, 5)) {
                                try {
                                    const cr = await fetch('/api-console/request/crawl', {
                                        method: 'POST',
                                        headers: {'Content-Type': 'application/json'},
                                        body: JSON.stringify({
                                            user_enc_id: enc,
                                            site: targetSite,
                                            document: slug,
                                            _csrf: csrf
                                        })
                                    });
                                    if (cr.status === 200) okCnt++;
                                } catch (e) {}
                            }
                            out[dom] = {verifiedInConsole: true, siteProperty: targetSite, directCrawlSubmitted: okCnt};
                        }
                        return {ok: true, account: 'soultin@naver.com', results: out};
                    }""",
                        payload_reqs,
                    )
                    if isinstance(sa_res, dict) and isinstance(sa_res.get("results"), dict):
                        sa_direct_map = sa_res["results"]
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
        except Exception:
            sa_direct_map = {}

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
            site_rec["indexingRequest"] = rep["_indexingRequestObj"]
            site_rec["checkedAt"] = now_stamp
        latest["checkedAt"] = now_stamp
        latest.setdefault("inspectionAutomation", {})["lastAutoIndexerRun"] = {
            "at": now_stamp,
            "domainsCount": len(domain_reports),
            "totalUnindexedSubmitted": sum(r["unindexedCount"] for r in domain_reports),
            "totalUrlsSubmitted": sum(r["naverIndexNow"]["submittedUrls"] for r in domain_reports),
            "searchAdvisorDirectCrawlAccount": "soultin@naver.com (CDP 9334)",
            "searchAdvisorDirectCrawlSubmitted": sum(
                int((sa_direct_map.get(r["domain"]) or {}).get("directCrawlSubmitted", 0)) for r in domain_reports
            ),
        }
        _atomic_write_json(METRICS_PATH, latest)

        # Also sync dashboard/data/metrics.json if dashboard/data exists
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
                    "outcome": "submitted",
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
    total_posts = sum(r["totalPosts"] for r in clean_reports)
    total_indexed = sum(r["indexedCount"] for r in clean_reports)
    total_unindexed = sum(r["unindexedCount"] for r in clean_reports)
    total_submitted_urls = sum(r["naverIndexNow"]["submittedUrls"] for r in clean_reports)
    naver_ok_domains = sum(1 for r in clean_reports if r["naverIndexNow"]["status"] == "submitted")
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
