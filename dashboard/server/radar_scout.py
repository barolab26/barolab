"""Evidence-first Radar scouting and durable Windows growth-queue dispatch.

The durable claim is shared by HTTP, natural-language tools and the KST loop.
Missed slots are not replayed. A proposal is never a publication or revenue result.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
import uuid
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))
HOURS = (9, 14, 20)
PRIORITY_DOMAINS = ("woorinote.kr", "must-good.com", "must-pick.com")
SOURCES = (
    {"id": "blokey_golden", "track": "A", "url": "https://blokey.co.kr/golden", "kind": "blokey_cdp"},
    {"id": "policy", "track": "A", "url": "https://www.korea.kr/main.do", "kind": "policy_html"},
    {"id": "google_trends", "track": "A", "url": "https://trends.google.com/trending/rss?geo=KR", "kind": "feed"},
    {"id": "naver_datalab", "track": "A", "url": "https://news.google.com/rss/search?q=%ED%99%98%EA%B8%89%EA%B8%88+OR+%EC%A7%80%EC%9B%90%EA%B8%88+OR+%EC%8B%A4%EC%86%90%EB%B3%B4%ED%97%98+OR+%EC%B2%AD%EC%95%BD+OR+%EB%8C%80%EC%B6%9C&hl=ko&gl=KR&ceid=KR:ko", "kind": "feed"},
    {"id": "google_search_updates", "track": "marketing", "url": "https://developers.google.com/search/updates/search_docs_updates.rss", "kind": "feed"},
    {"id": "product_hunt", "track": "B", "url": "https://www.producthunt.com/feed", "kind": "feed"},
    {"id": "indie_hackers", "track": "B", "url": "https://hnrss.org/frontpage?points=100", "kind": "feed"},
    {"id": "app_store", "track": "B", "url": "https://itunes.apple.com/search?term=medication%20reminder&entity=software&country=kr&limit=8", "kind": "app_store"},
    {"id": "youtube_outliers", "track": "B", "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ko&gl=KR&ceid=KR:ko", "kind": "feed"},
)


def reported_keyword(row, now=None):
    """Accept collector-backed metrics, never legacy or model-generated estimates."""
    if not isinstance(row, dict):
        return None
    evidence = row.get("metricEvidence") or {}
    if not isinstance(evidence, dict):
        return None
    raw = evidence.get("raw") or {}
    if not isinstance(raw, dict):
        return None
    try:
        checked = datetime.fromisoformat(evidence["checkedAt"])
        age = ((now or datetime.now(KST)) - checked).total_seconds()
        total, docs = raw["total"], raw["doc"]
        valid = (row.get("measurementStatus") == "reported"
                 and evidence.get("sourceId") == "blokey_golden"
                 and evidence.get("sourceUrl") in ("https://blokey.co.kr/api/golden?period=year",
                                                   "https://blokey.co.kr/api/golden/total")
                 and raw.get("keyword") == row.get("keyword") and 0 <= age <= 7 * 86400
                 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                         and math.isfinite(v) and v > 0 for v in (total, docs))
                 and row.get("totalSearch", row.get("searchVolume")) == total
                 and row.get("docCount") == docs)
    except (KeyError, TypeError, ValueError):
        return None
    if not valid:
        return None
    rate = total / docs
    return {"keyword": row["keyword"], "searchVolume": total, "totalSearch": total,
            "docCount": docs, "goldenRate": round(rate, 1),
            "grade": "S" if rate >= 100 else "A" if rate >= 30 else "B",
            "gradeBasis": "local_search_to_document_ratio; not a revenue forecast",
            "measurementStatus": "reported", "metricEvidence": evidence}


def revenue_leaders(document, now=None):
    """Summarize observed source rows, preserving missing days and currencies."""
    from decimal import Decimal, InvalidOperation
    from dashboard.collectors.revenue import period
    now = (now or datetime.now(KST)).astimezone(KST)
    today, yesterday = now.date(), now.date() - timedelta(days=1)
    start = today.replace(day=1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    months = document.get("months") or {}

    def sources(month):
        result = {}
        for source in (months.get(month, {}).get("sources") or []):
            if source.get("aggregationEligible") is False or source.get("status") == "duplicate_source":
                continue
            if not source.get("id") or not source.get("currency"):
                continue
            rows = {}
            for day, value in (source.get("daily") or {}).items():
                try:
                    if datetime.fromisoformat(day).date().isoformat() != day or not day.startswith(month + '-'):
                        continue
                    amount = Decimal(str(value))
                    if amount.is_finite() and amount >= 0 and not isinstance(value, bool):
                        rows[day] = str(amount)
                except (InvalidOperation, ValueError, TypeError):
                    pass
            result[(source["id"], source["currency"])] = {**source, "daily": rows}
        return result

    current, previous = sources(start.strftime("%Y-%m")), sources(prev_start.strftime("%Y-%m"))
    leaders = []
    for identity in sorted(current.keys() | previous.keys()):
        cur, prev = current.get(identity), previous.get(identity)
        source = cur or prev
        currency = source["currency"]
        periods = {}
        for name, record, a, b in (("yesterday", prev if yesterday < start else cur, yesterday, yesterday),
                                   ("throughYesterday", cur, start, yesterday),
                                   ("previousMonth", prev, prev_start, prev_end)):
            value = period([record] if record else [], a, b)
            value["amount"] = value.get("amounts", {}).get(currency)
            value["valueKind"] = record.get("valueKind", "unknown") if record else "unknown"
            value["estimated"] = True if value["valueKind"] == "estimated" else None
            value["checkedAt"] = record.get("checkedAt") if record else None
            value["scope"] = record.get("scope") if record else None
            periods[name] = value
        observed = {day: amount for record in (prev, cur) if record
                    for day, amount in record["daily"].items() if day <= yesterday.isoformat()}
        latest = max(observed, default=None)
        leaders.append({"id": source["id"], "category": source.get("category"),
                        "label": source.get("label", source["id"]), "currency": currency,
                        "scope": source.get("scope"), "valueKind": source.get("valueKind", "unknown"),
                        "collectionStatus": cur.get("status") if cur else "not_collected",
                        "lastCollectedAt": source.get("checkedAt"), "reportSource": source.get("reportSource"),
                        "periods": periods, "latestObservedCompletedDate": latest,
                        "latestObservedCompletedAmount": observed.get(latest),
                        "yesterdayAmount": periods["yesterday"]["amount"],
                        "previousMonthAmount": periods["previousMonth"]["amount"],
                        "evidenceScope": "observed source reports; not company total or settled cash"})
    return leaders


def fetch_blokey_golden(cdp_port=9440, min_search=300, max_docs=220):
    """Fetch verified S/A-grade Golden Keywords from the authenticated Blokey Pro session on CDP 9440."""
    import websocket
    receipt = {
        "sourceId": "blokey_golden",
        "sourceUrl": "https://blokey.co.kr/golden",
        "track": "A",
        "fetchedAt": now_iso(),
        "status": "failed",
        "items": [],
        "naverAssignments": {},
        "cfAssignments": {},
        "pairedBridgeSets": [],
    }
    try:
        live_rows, total_rows = [], []
        cookies_list = []
        ws_url = ""
        try:
            tabs_resp = requests.get(f"http://127.0.0.1:{cdp_port}/json/list", timeout=2.0)
            tabs_resp.raise_for_status()
            tabs = [t for t in tabs_resp.json() if isinstance(t, dict) and t.get("type") == "page"]
            blokey_tab = next((t for t in tabs if "blokey.co.kr" in str(t.get("url", ""))), None)
            if blokey_tab and blokey_tab.get("webSocketDebuggerUrl"):
                ws_url = blokey_tab["webSocketDebuggerUrl"]
                ws = websocket.create_connection(ws_url, timeout=8)
                try:
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Network.getCookies",
                        "params": {"urls": ["https://blokey.co.kr"]}
                    }))
                    cookie_msg = json.loads(ws.recv())
                    cookies_list = ((cookie_msg.get("result") or {}).get("cookies")) or []
                finally:
                    ws.close()
        except Exception:
            pass

        if not cookies_list and os.name == "nt":
            try:
                from common.ego_taskspace import extract_profile_cookies
                cookies_list = [
                    c for c in extract_profile_cookies("cf-flow", default_url="https://blokey.co.kr/golden", include_default_profile=True)
                    if "blokey.co.kr" in str(c.get("domain") or "")
                ]
            except Exception:
                cookies_list = []

        if not cookies_list and not ws_url:
            receipt["reason"] = f"CDP {cdp_port} 또는 EGO Lite 세션에 blokey.co.kr 로그인 쿠키가 없음"
            return receipt

        if cookies_list:
            sess = requests.Session()
            for c in cookies_list:
                if c.get("name") and c.get("value"):
                    sess.cookies.set(c["name"], c["value"], domain=c.get("domain") or "blokey.co.kr")
            hdrs = {"User-Agent": "Mozilla/5.0", "Referer": "https://blokey.co.kr/golden"}
            try:
                r_live = sess.get("https://blokey.co.kr/api/golden?period=year", headers=hdrs, timeout=6)
                if r_live.status_code == 200:
                    live_rows = (r_live.json().get("rows") or [])[:5000]
            except Exception:
                pass
            try:
                r_tot = sess.get("https://blokey.co.kr/api/golden/total", headers=hdrs, timeout=6)
                if r_tot.status_code == 200:
                    total_rows = (r_tot.json().get("rows") or [])[:5000]
            except Exception:
                pass

        if not live_rows and not total_rows and ws_url:
            js_expr = """(async () => {
              const [liveRes, totalRes] = await Promise.all([
                fetch('/api/golden?period=year', {credentials: 'include'}).then(r => r.json()).catch(() => ({})),
                fetch('/api/golden/total', {credentials: 'include'}).then(r => r.json()).catch(() => ({}))
              ]);
              return {
                liveRows: (liveRes && liveRes.rows) ? liveRes.rows.slice(0, 1500) : [],
                totalRows: (totalRes && totalRes.rows) ? totalRes.rows.slice(0, 1500) : [],
                dateKey: (liveRes && liveRes.dateKey) || (totalRes && totalRes.dateKey) || ''
              };
            })()"""
            ws = websocket.create_connection(ws_url, timeout=12)
            try:
                ws.send(json.dumps({
                    "id": 2,
                    "method": "Runtime.evaluate",
                    "params": {"expression": js_expr, "awaitPromise": True, "returnByValue": True}
                }))
                raw_msg = json.loads(ws.recv())
            finally:
                ws.close()
            payload = (((raw_msg.get("result") or {}).get("result") or {}).get("value")) or {}
            live_rows = payload.get("liveRows") or []
            total_rows = payload.get("totalRows") or []

        if not live_rows and not total_rows:
            receipt["status"] = "unverified"
            receipt["reason"] = "Blokey API 응답 비어 있음 (로그인 확인 필요)"
            return receipt

        # Merge live (trend+related) and cumulative golden keywords, filtering out celebrity gossip, sports, politics, clickbait sentences, or unspaced noise
        merged = []
        seen_kw = set()
        stale_or_game_re = re.compile(
            r"(?:[1-9]|12)월\s*\d{1,2}일|[1-9]월출산|힛카드|발\s*로란트|몬스터헌터|몬헌|LoL|선성권|왕옌청|트레이드|이닝|투구|포스트시즌|"
            r"모친상|부친상|별세|논란|카광|이호선|박근수|이은샘|우지원|신지원|문동주|김도영|오선우|양의지|노시환|이정후|오승환|손혁|"
            r"김종국|김고은|김소현|손예진|장승조|엄태웅|오인혜|하현승|백재호|남편|이혼|열애|결혼|근황|비주얼|눈매|성형|미코|시사회|"
            r"태움|야구|청룡영화상|음바페|맨시티|치어리더|란제리|학폭|통역사|유튜버\s*갤|중보갤|포챔스|"
            r"중간선거|대통령|트럼프|탄핵|국회의원|정당|지지율|주가|주식시세|배당금|맥그리거|할러웨이|최화정|지디|온병원|정이한|포에버송|메차|메챠|"
            r"나무위키|타이거즈|라이온즈|트윈스|베어스|자이언츠|이글스|위즈|랜더스|다이노스|히어로즈|고딩엄빠|나는솔로|나혼자산다|돌싱글즈|미우새|"
            r"박신혜|손연재|엄지원|여에스더|박위|정용진|최지\s*만|메이저리그|오케이징|진화\s*조건|곽빈|안우진|성적\s*비교|베타신청|퀴즈|정답|우승|결승|중계|엉뽕|D라인|출산\s*임박|잔류\s*이유|"
            r"의\s*결과|신형\s*정체|물어본|취향저격|품절대란|마성의|꼭\s*사야|\d+\s*가지|추천템|총정리|반한"
        )
        for bucket_name, rows in (("live_trend", live_rows), ("cumulative", total_rows)):
            for r in rows:
                kw = str(r.get("keyword") or "").strip()
                norm_kw = re.sub(r"\s+", "", kw).lower()
                if not kw or norm_kw in seen_kw or len(kw) > 18:
                    continue
                if (" " not in kw and len(kw) >= 11) or stale_or_game_re.search(kw):
                    continue
                total_vol = int(r.get("total") or 0)
                doc_cnt = int(r.get("doc") or 0)
                if total_vol < min_search or total_vol > 40000 or doc_cnt > max_docs or doc_cnt < 1:
                    continue
                rate = total_vol / doc_cnt
                if rate < 25:
                    continue
                seen_kw.add(norm_kw)
                cats = (r.get("origins") or {}).get("categories") or []
                demos = (r.get("origins") or {}).get("demos") or []
                grade = "S" if rate >= 100 else ("A" if rate >= 30 else "B")
                merged.append({
                    "keyword": kw,
                    "totalSearch": total_vol,
                    "pcSearch": int(r["pc"]) if r.get("pc") is not None else None,
                    "mobileSearch": int(r["mobile"]) if r.get("mobile") is not None else None,
                    "docCount": doc_cnt,
                    "goldenRate": round(rate, 1),
                    "grade": grade,
                    "bucket": bucket_name,
                    "sourceLabel": str(r.get("sourceLabel") or ("실시간트렌드" if bucket_name == "live_trend" else "누적황금")),
                    "categories": cats,
                    "demos": demos,
                    "measurementStatus": "reported",
                    "metricEvidence": {
                        "sourceId": "blokey_golden",
                        "sourceUrl": "https://blokey.co.kr/api/golden?period=year" if bucket_name == "live_trend" else "https://blokey.co.kr/api/golden/total",
                        "checkedAt": receipt["fetchedAt"],
                        "searchPeriod": "provider_reported_unspecified",
                        "raw": {"keyword": kw, "total": total_vol, "doc": doc_cnt},
                    },
                })

        # Classification rules aligned with high-CPC AdSense & AdPost commercial search intent (strict C-Rank topic purity)
        re_spam_offtopic = re.compile(r"동물병원|심페리카|넥스가드|심장사상충|강아지|고양이|들깨|좌대|낚시|리드코프|대부|일수|작업대출|폐점|운세|사주|타로|먹튀|토토")
        re_policy_welfare = re.compile(r"지원금|장려금|연금|수당|복지|보조금|노인|시니어|환급|산정특례|실업급여|내일배움|육아|출산|돌봄|바우처|노란우산")
        re_finance_tax = re.compile(r"세금|상속|증여|취득세|양도세|연말정산|주택담보대출|전세대출|금리|적금|예금|청약|전세|월세|부동산|신용카드|보험|실비|실손|퇴직금|IRP")
        re_health_issue = re.compile(r"건강검진|혈당|혈압|당뇨|당화혈색소|콜레스테롤|고지혈증|보청기|임플란트|백내장|도수치료|내시경|용종|수면무호흡|관절염|연골주사|대상포진")
        re_living_review = re.compile(r"아이오닉|기아|카니발|제네시스|전기차|하이브리드|자동차보험|갤럭시|아이폰|노트북|보일러|제습기|식기세척기|로봇청소기|으뜸효율|숙소|호텔|항공권|수하물|트래블로그")

        def score_for_cpc(row):
            kw = row["keyword"]
            if re_spam_offtopic.search(kw):
                return -9999
            cats = set(row["categories"])
            grade_score = 3000 if row["grade"] == "S" else (1500 if row["grade"] == "A" else 0)
            live_bonus = 1200 if row["bucket"] == "live_trend" else 0
            niche_bonus = 0
            if re_policy_welfare.search(kw) or re_finance_tax.search(kw) or re_health_issue.search(kw):
                niche_bonus = 5500
            elif re_living_review.search(kw):
                niche_bonus = 4000
            elif cats & {"비즈니스·경제", "건강·의학", "교육·학문", "IT·컴퓨터", "상품리뷰", "자동차"}:
                niche_bonus = 2500
            doc_bonus = 1000 if 2 <= row["docCount"] <= 80 else 0
            return grade_score + live_bonus + niche_bonus + doc_bonus + min(row["goldenRate"], 1500)

        merged.sort(key=score_for_cpc, reverse=True)

        # Assign top tailored Golden Keywords to Naver 5 accounts (up to 4 distinct keywords per account so multi-slot days never collide)
        naver_rules = {
            "soul5373": lambda r: bool(not re_spam_offtopic.search(r["keyword"]) and re_health_issue.search(r["keyword"])),
            "yoon_master": lambda r: bool(not re_spam_offtopic.search(r["keyword"]) and re_living_review.search(r["keyword"])),
            "soultin": lambda r: bool(not re_spam_offtopic.search(r["keyword"]) and re_policy_welfare.search(r["keyword"])),
            "stone0747": lambda r: bool(not re_spam_offtopic.search(r["keyword"]) and re_policy_welfare.search(r["keyword"])),
            "adinfo0905": lambda r: bool(not re_spam_offtopic.search(r["keyword"]) and re_finance_tax.search(r["keyword"])),
        }
        from common.asset_map import (
            collect_used_naver_topics,
            is_duplicate_naver_topic,
            query_naver_blog_doc_count,
        )
        used_naver = set()
        naver_assignments = {}
        for acc, pred in naver_rules.items():
            recent_14d = collect_used_naver_topics(acc, days=14)
            picks = []
            for r in merged:
                kw_cand = r["keyword"]
                if not pred(r) or kw_cand in used_naver:
                    continue
                if is_duplicate_naver_topic(kw_cand, recent_14d + list(used_naver)):
                    continue
                live_docs = query_naver_blog_doc_count(kw_cand)
                if live_docs is not None and live_docs > 5000:
                    continue
                picks.append(r)
                if len(picks) >= 4:
                    break
            for p in picks[:4]:
                used_naver.add(p["keyword"])
            if picks:
                naver_assignments[acc] = picks

        # Assign top high-CPC Golden Keywords to all 16 CF domains (list of 3 per domain) + build 10 Paired CF Pillar × Naver Bridge Sets
        cf_domains = (
            "woorinote.kr", "must-good.com", "must-pick.com", "baronote.kr",
            "healthcox.com", "justinfo.co.kr", "topnote.kr", "daynote.kr",
            "meganote.kr", "smilenote.kr", "maxnote.kr", "must-joy.com",
            "tripmarvel.com", "nolplace.com", "soulnote.kr", "joynote.kr",
        )
        cf_domain_rules = {
            "woorinote.kr": re.compile(r"청약|전세|월세|보증금|분양|주거|든든전세|등기|취득세|재산세|부동산"),
            "must-good.com": re.compile(r"지원금|환급|복지|수당|장려금|민원|발급|건강보험|부모급여"),
            "must-pick.com": re.compile(r"가전|청소기|식기세척기|제습기|보일러|노트북|아이폰|갤럭시|폴더블|비교|스펙"),
            "baronote.kr": re.compile(r"연금|기초연금|국민연금|대출|금리|카드|실손|실비|보험|연말정산|절세"),
            "healthcox.com": re.compile(r"건강|관절|통증|검진|내시경|혈압|혈당|당뇨|영양|단백질|산정특례|수술|치료"),
            "justinfo.co.kr": re.compile(r"실업급여|퇴직금|주휴수당|양도세|증여세|상속|위약금|환불|과태료|증명서|세이브텍스"),
            "topnote.kr": re.compile(r"윈도우|맥북|아이폰|갤럭시|프린터|알뜰폰|eSIM|엑셀|PDF|인증|오류|설정"),
            "daynote.kr": re.compile(r"보관|청소|세탁기|배수구|에어컨청소|분리수거|과태료|전기세|가스비|관리비|살림|절약"),
            "meganote.kr": re.compile(r"자동차|전기차|보조금|하이브리드|자동차보험|특약|과태료|온누리|마트|아우디|카니발|제네시스"),
            "smilenote.kr": re.compile(r"연금|은퇴|시니어|노인|임플란트|보청기|장기요양|돌봄|바우처"),
            "maxnote.kr": re.compile(r"알뜰폰|요금제|AI|챗GPT|노션|엑셀|단축키|모바일신분증|통신비"),
            "must-joy.com": re.compile(r"맛집|웨이팅|주차|카페|전시|공연|예매|특산물|식당|베이커리"),
            "tripmarvel.com": re.compile(r"여행|항공권|수하물|보조배터리|호텔|숙소|환전|트래블|KTX|큐패스"),
            "nolplace.com": re.compile(r"수목원|휴양림|캠핑장|나들이|축제|전시|주차|예약|명소|박물관"),
            "soulnote.kr": re.compile(r"내일배움|국비|자격증|시험|이직|취업|훈련|수당"),
            "joynote.kr": re.compile(r"강아지|고양이|심페리카|넥스가드|사상충|동물병원|펫보험|예방접종|애견|식물|화분"),
        }
        cf_candidates = [
            r for r in merged
            if re_policy_welfare.search(r["keyword"]) or re_finance_tax.search(r["keyword"])
            or re_health_issue.search(r["keyword"]) or re_living_review.search(r["keyword"])
            or (set(r["categories"]) & {"비즈니스·경제", "건강·의학", "교육·학문", "IT·컴퓨터", "상품리뷰", "인테리어·DIY", "자동차"})
        ] or merged[:32]
        cf_assignments = {}
        used_cf_all = set()
        for idx, dom in enumerate(cf_domains):
            dom_re = cf_domain_rules.get(dom)
            dom_picks = [r for r in cf_candidates if dom_re and dom_re.search(r["keyword"]) and r["keyword"] not in used_cf_all][:3]
            for p in dom_picks:
                used_cf_all.add(p["keyword"])
            if dom_picks:
                cf_assignments[dom] = dom_picks

        naver_bridge_cycle = ("soul5373", "yoon_master", "soultin", "adinfo0905", "stone0747")
        paired_sets = []
        for idx, dom in enumerate(cf_domains[:10]):
            dom_list = cf_assignments.get(dom) or []
            if not dom_list:
                continue
            r = dom_list[0]
            nv_acc = naver_bridge_cycle[idx % len(naver_bridge_cycle)]
            kw = r["keyword"]
            paired_sets.append({
                "metricEvidence": r["metricEvidence"],
                "measurementStatus": "reported",
                "setIndex": len(paired_sets) + 1,
                "keyword": kw,
                "grade": r["grade"],
                "searchVolume": r["totalSearch"],
                "docCount": r["docCount"],
                "goldenRate": r["goldenRate"],
                "cfPillarDomain": dom,
                "cfPillarFormat": f"[{kw}] 심층 비용·조건 비교표 & 3초 자격/실구매 판독기 본진 글",
                "naverBridgeAccount": nv_acc,
                "naverBridgeFormat": f"[{kw}] 핵심 체크포인트 3가지 정리 + {dom} 상세 판독표 브릿지 연결",
            })
        receipt["pairedBridgeSets"] = paired_sets

        # Build receipt items for RadarScout track A
        for r in (cf_candidates[:15] or merged[:15]):
            kw = r["keyword"]
            cat_str = ", ".join(r["categories"]) if r["categories"] else r["sourceLabel"]
            summary_txt = (
                f"[블로키 {r['grade']}등급 💎{r['goldenRate']}] 총검색량 {r['totalSearch']:,}회 "
                f"(PC {r['pcSearch'] if r['pcSearch'] is not None else '미측정'} / "
                f"모바일 {r['mobileSearch'] if r['mobileSearch'] is not None else '미측정'}) · 문서수 {r['docCount']:,}건 · 분류: {cat_str}"
            )
            q_url = f"https://blokey.co.kr/golden?kw={urlencode({'q': kw})[2:]}"
            receipt["items"].append({
                "metricEvidence": r["metricEvidence"],
                "measurementStatus": "reported",
                "title": kw,
                "keyword": kw,
                "url": q_url,
                "summary": summary_txt,
                "publishedAt": now_iso(),
                "sourceId": "blokey_golden",
                "sourceUrl": "https://blokey.co.kr/golden",
                "fetchedAt": receipt["fetchedAt"],
                "freshness": "published_within_7_days",
                "searchVolume": r["totalSearch"],
                "pcSearch": r["pcSearch"],
                "mobileSearch": r["mobileSearch"],
                "competition": r["docCount"],
                "goldenRate": r["goldenRate"],
                "grade": r["grade"],
                "categories": r["categories"],
            })

        receipt["naverAssignments"] = naver_assignments
        receipt["cfAssignments"] = cf_assignments
        receipt["status"] = "collected" if receipt["items"] else "unverified"
        receipt["sha256"] = hashlib.sha256(json.dumps(receipt["items"], ensure_ascii=False).encode()).hexdigest()

        # Persist Blokey Golden Keyword ledger & inject QueryRecipe hints into Synapse
        out_dir = ROOT / "dashboard/data/radar"
        out_dir.mkdir(parents=True, exist_ok=True)
        ledger_payload = {
            "checkedAt": receipt["fetchedAt"],
            "cdpPort": cdp_port,
            "criteria": {"minSearchVolume": min_search, "maxDocCount": max_docs, "minGoldenRate": 15},
            "totalQualified": len(merged),
            "topKeywords": merged[:30],
            "naverAssignments": naver_assignments,
            "cfAssignments": cf_assignments,
            "pairedBridgeSets": paired_sets,
        }
        (out_dir / "blokey-golden.json").write_text(json.dumps(ledger_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _sync_blokey_to_synapse_recipes(naver_assignments, cf_assignments, receipt["fetchedAt"])
        build_daily_winning_topics(ledger_payload)
    except Exception as exc:
        receipt["reason"] = f"{type(exc).__name__}: {exc}"
    return receipt


def _sync_blokey_to_synapse_recipes(naver_assignments, cf_assignments, checked_at):
    """Register verified Blokey S/A-grade Golden Keywords as QueryRecipe hints in memory_graph.json & synapse-recipes.json."""
    naver_assignments = {key: [measured for row in (rows if isinstance(rows, list) else [rows])
                               if (measured := reported_keyword(row)) is not None]
                         for key, rows in (naver_assignments or {}).items()}
    cf_assignments = {key: [measured for row in (rows if isinstance(rows, list) else [rows])
                            if (measured := reported_keyword(row)) is not None]
                      for key, rows in (cf_assignments or {}).items()}
    try:
        mg_path = ROOT / "dashboard/data/memory_graph.json"
        sr_path = ROOT / "dashboard/data/synapse-recipes.json"
        default_topics = {
            "soultin": "5060 국민연금, 기초연금, 노후재정, 시니어 지원금",
            "soul5373": "5060 중장년 건강, 건기식 성분 팩트체크, 혈당/혈압 식단 관리",
            "yoon_master": "5060 우아한 데일리룩, 프리미엄 가전·리빙, 힐링 여행",
            "adinfo0905": "직장인 연말정산 소득공제, 엑셀 무료 서식, 업무 생산성, 절세",
            "stone0747": "정부 소상공인 정책자금, 지자체 지원금 마감속보, 생활세무 혜택",
        }
        hints = []
        for acc, picks in (naver_assignments or {}).items():
            if not picks:
                continue
            top = picks[0] if isinstance(picks, list) else picks
            all_kws = [p["keyword"] for p in picks if isinstance(p, dict) and p.get("keyword")] if isinstance(picks, list) else [top.get("keyword")]
            orig = default_topics.get(acc, acc)
            hints.append({
                "account": acc,
                "originalQuery": orig,
                "preferredQuery": top["keyword"],
                "slotKeywords": all_kws[:4],
                "searchVolume": top["totalSearch"],
                "docCount": top["docCount"],
                "goldenRate": top["goldenRate"],
                "grade": top["grade"],
                "checkedAt": checked_at,
                "measurementStatus": "reported",
                "metricEvidence": top["metricEvidence"],
            })
        if sr_path.is_file():
            sr = json.loads(sr_path.read_text(encoding="utf-8-sig"))
            existing = [h for h in sr.get("queryHints", []) if h.get("account") not in naver_assignments]
            sr["queryHints"] = hints + existing
            sr["blokeyGolden"] = {
                "checkedAt": checked_at,
                "naver": {acc: [p["keyword"] for p in picks[:4]] for acc, picks in naver_assignments.items() if picks},
                "cf": {dom: ([p["keyword"] for p in picks[:3]] if isinstance(picks, list) else [picks.get("keyword")]) for dom, picks in cf_assignments.items() if picks},
            }
            sr_path.write_text(json.dumps(sr, ensure_ascii=False, indent=2), encoding="utf-8")
        if mg_path.is_file():
            mg = json.loads(mg_path.read_text(encoding="utf-8-sig"))
            nodes = mg.setdefault("nodes", {})
            for h in hints:
                nid = f"query_recipe:blokey:{h['account']}"
                nodes[nid] = {
                    "type": "QueryRecipe",
                    **h,
                    "source": "blokey.co.kr/golden",
                }
            mg_path.write_text(json.dumps(mg, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def build_daily_winning_topics(blokey_ledger=None):
    """Synthesize measured revenue/traffic winners + Blokey S/A Golden Keywords into daily_winning_topics.json for all 6 Crew & channels."""
    from urllib.parse import unquote
    data_dir = ROOT / "dashboard/data"
    radar_dir = data_dir / "radar"
    radar_dir.mkdir(parents=True, exist_ok=True)
    if blokey_ledger is None:
        bg_path = radar_dir / "blokey-golden.json"
        blokey_ledger = json.loads(bg_path.read_text(encoding="utf-8")) if bg_path.is_file() else {}

    # 1. Extract proven traffic winners & low-CTR remodel targets from traffic.json
    proven_winners = []
    ctr_remodel_targets = []
    try:
        tr_path = data_dir / "traffic.json"
        if tr_path.is_file():
            tr = json.loads(tr_path.read_text(encoding="utf-8"))
            for row in sorted((tr.get("pagePerformance") or {}).get("pages") or [], key=lambda r: float(r.get("pageViews") or 0), reverse=True)[:12]:
                pv = int(float(row.get("pageViews") or 0))
                if pv < 3:
                    continue
                u = str(row.get("url") or row.get("page") or "")
                slug = unquote(u.rstrip("/").rsplit("/", 1)[-1]).replace("-", " ")
                proven_winners.append({
                    "source": "ga4_top_pv",
                    "url": u,
                    "domain": (urlsplit(u).hostname or "").removeprefix("www."),
                    "slugTopic": slug,
                    "pageViews": pv,
                    "sessions": int(float(row.get("sessions") or 0)),
                })
            for dom, site in (tr.get("sites") or {}).items():
                month_p = ((site.get("google") or {}).get("periods") or {}).get("month") or {}
                for p in (month_p.get("pages") or []):
                    clicks = int(float(p.get("clicks") or 0))
                    imps = int(float(p.get("impressions") or 0))
                    u = str(p.get("url") or p.get("page") or "")
                    slug = unquote(u.rstrip("/").rsplit("/", 1)[-1]).replace("-", " ")
                    if clicks >= 2:
                        proven_winners.append({
                            "source": "gsc_top_clicks",
                            "url": u,
                            "domain": dom,
                            "slugTopic": slug,
                            "clicks": clicks,
                            "impressions": imps,
                        })
                    elif imps >= 15 and clicks <= 1:
                        ctr_remodel_targets.append({
                            "domain": dom,
                            "url": u,
                            "slugTopic": slug,
                            "impressions": imps,
                            "clicks": clicks,
                            "ctrPct": round((clicks / max(1, imps)) * 100, 2),
                            "doctorAction": "노출 대비 클릭 저조(CTR<3%) — 자청 4대 결핍 제목·도입부 3초 후킹 및 판독기 표 즉시 리모델링",
                        })
    except Exception:
        pass

    ctr_remodel_targets.sort(key=lambda x: x.get("impressions", 0), reverse=True)

    # 2. Read the same observed source rows as the revenue dashboard.
    revenue_path = data_dir / "revenue.json"
    revenue_document = json.loads(revenue_path.read_text(encoding="utf-8")) if revenue_path.is_file() else {}
    measured_revenue = revenue_leaders(revenue_document)

    # 3. Map Blokey S/A-grade Golden Keywords per Naver account (multi-slot) & CF domain
    from common.asset_map import (
        CF_DOMAINS,
        CF_NICHE_VERIFIED_POOLS,
        NAVER_NICHE_VERIFIED_POOLS,
        collect_used_cf_topics,
        collect_used_naver_topics,
        is_duplicate_naver_topic,
    )
    re_spam_offtopic = re.compile(r"동물병원|심페리카|넥스가드|심장사상충|강아지|고양이|들깨|좌대|낚시|리드코프|대부|일수|작업대출|폐점|운세|사주|타로|먹튀|토토")
    crank_domain_rules = {
        "soul5373": re.compile(r"건강검진|혈당|혈압|당뇨|당화혈색소|콜레스테롤|고지혈증|보청기|임플란트|백내장|도수치료|내시경|용종|수면무호흡|관절염|연골주사|대상포진|환급금|병원비"),
        "yoon_master": re.compile(r"아이오닉|기아|카니발|제네시스|전기차|하이브리드|자동차보험|갤럭시|아이폰|노트북|보일러|제습기|식기세척기|로봇청소기|으뜸효율|숙소|호텔|항공권|수하물|트래블로그"),
        "soultin": re.compile(r"지원금|장려금|연금|수당|복지|보조금|노인|시니어|환급|산정특례|실업급여|내일배움|육아|출산|돌봄|바우처|노란우산"),
        "stone0747": re.compile(r"지원금|장려금|연금|수당|복지|보조금|노인|시니어|환급|산정특례|실업급여|내일배움|육아|출산|돌봄|바우처|노란우산"),
        "adinfo0905": re.compile(r"세금|상속|증여|취득세|양도세|연말정산|주택담보대출|전세대출|금리|적금|예금|청약|전세|월세|부동산|신용카드|보험|실비|실손|퇴직금|IRP|든든전세"),
    }
    unverified = []

    def assign(items, pool, used, limit, predicate=None):
        items = items if isinstance(items, list) else [items] if isinstance(items, dict) else []
        selected = []
        for row in items:
            if not isinstance(row, dict) or not row.get("keyword"):
                continue
            measured = reported_keyword(row)
            if measured is None:
                unverified.append({"keyword": row["keyword"], "measurementStatus": "unverified",
                                   "source": "legacy_or_unverified_ledger", "searchVolume": None,
                                   "docCount": None, "grade": None})
                continue
            keyword = measured["keyword"]
            if (re_spam_offtopic.search(keyword) or (predicate and not predicate.search(keyword))
                    or is_duplicate_naver_topic(keyword, used + [r["keyword"] for r in selected])):
                continue
            if measured["grade"] in ("S", "A") and len(selected) < limit:
                selected.append(measured)
        for keyword in pool:
            if keyword not in [r["keyword"] for r in selected]:
                unverified.append({"keyword": keyword, "measurementStatus": "unverified",
                                   "source": "editorial_pool", "searchVolume": None,
                                   "docCount": None, "grade": None})
        return selected

    naver_accounts = {
        acc: assign((blokey_ledger.get("naverAssignments") or {}).get(acc),
                    NAVER_NICHE_VERIFIED_POOLS.get(acc, []), collect_used_naver_topics(acc, days=14),
                    4, crank_domain_rules.get(acc))
        for acc in ("soul5373", "yoon_master", "soultin", "adinfo0905", "stone0747")
    }
    cf_domains = {
        dom: assign((blokey_ledger.get("cfAssignments") or {}).get(dom),
                    CF_NICHE_VERIFIED_POOLS.get(dom, []), collect_used_cf_topics(dom, days=14), 4)
        for dom in CF_DOMAINS
    }
    flat_golden = []
    for channel, groups in (("CF", cf_domains), ("네이버", naver_accounts)):
        for target, rows in groups.items():
            for row in rows[:2]:
                flat_golden.append({**row, "reportedSearchVolume": row["searchVolume"],
                                    "blogTotal": row["docCount"], "saturation": row["goldenRate"],
                                    "recommendedChannel": f"{channel}({target})"})
    reported_pairs = [pair for pair in (blokey_ledger.get("pairedBridgeSets") or [])
                      if reported_keyword(pair) is not None]

    payload = {
        "updatedAt": now_iso(),
        "date": datetime.now(KST).date().isoformat(),
        "northStarGoalUsd": 100.0,
        "revenueLeaders": measured_revenue,
        "provenTrafficWinners": proven_winners[:15],
        "doctorCtrRemodelTargets": ctr_remodel_targets[:10],
        "goldenKeywords": flat_golden[:15],
        "naverAccountSlotKeywords": naver_accounts,
        "cfDomainKeywords": cf_domains,
        "pairedBridgeSets": reported_pairs[:10],
        "unverifiedCandidates": list({r["keyword"]: r for r in unverified}.values()),
    }
    (radar_dir / "daily_winning_topics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        from common.knowledge_policy import sync_second_brain_guides
        sync_second_brain_guides(ROOT)
    except Exception:
        pass
    return payload


def now_iso():
    return datetime.now(KST).isoformat(timespec="seconds")


def clean_text(value, limit=400):
    return re.sub(r"\s+", " ", BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True))[:limit]


def public_url(url):
    p = urlparse(str(url))
    return p.scheme == "https" and bool(p.hostname) and not p.username and not p.password


def source_freshness(published, observed=None):
    try:
        try:
            stamp = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
        except ValueError:
            stamp = parsedate_to_datetime(str(published))
        if stamp.tzinfo is None:
            return "publication_timezone_unknown"
        days = ((observed or datetime.now(KST)) - stamp).total_seconds() / 86400
        return "future_timestamp_unverified" if days < 0 else "published_within_7_days" if days <= 7 else "older_source_collected_today"
    except (ValueError, TypeError, OverflowError):
        return "publication_date_unknown_collected_today"


def fetch_source(spec):
    """Only fetch fixed, reviewed endpoints; never execute remote instructions."""
    if spec.get("kind") == "blokey_cdp":
        return fetch_blokey_golden()
    receipt = {"sourceId": spec["id"], "sourceUrl": spec["url"], "track": spec["track"],
               "fetchedAt": now_iso(), "status": "failed", "items": []}
    try:
        with requests.get(spec["url"], timeout=(5, 15), stream=True,
                          headers={"User-Agent": "BaroLab-Radar/1.0 (source research)"}) as response:
            receipt["httpStatus"] = response.status_code
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(32768):
                size += len(chunk)
                if size > 1500000:
                    raise ValueError("Source exceeds bounded response size")
                chunks.append(chunk)
            raw = b"".join(chunks)
        receipt["sha256"] = hashlib.sha256(raw).hexdigest()
        kind = spec["kind"]
        items = []
        if kind == "availability":
            receipt.update(status="unverified", reason=("공개 페이지 HTTP 응답만 확인. 급상승 검색량/경쟁도 또는 영상별 조회수·채널 기준선이 없어 outlier 판정 불가"))
            return receipt
        if kind == "app_store":
            for item in json.loads(raw).get("results", []):
                items.append({"title": clean_text(item.get("trackName")), "url": item.get("trackViewUrl"),
                              "summary": clean_text(item.get("description"), 450), "publishedAt": item.get("currentVersionReleaseDate"),
                              "price": item.get("price"), "currency": item.get("currency"),
                              "ratingCount": item.get("userRatingCount"), "revenueVerified": False})
        elif kind == "policy_html":
            soup = BeautifulSoup(raw, "html.parser")
            for link in soup.select('a[href*="policyNewsView.do"], a[href*="policyBriefingView.do"]'):
                title = clean_text(link.get_text(" ", strip=True))
                url = urljoin(spec["url"], link.get("href", ""))
                if len(title) > 8 and urlparse(url).hostname == "www.korea.kr":
                    items.append({"title": title, "url": url, "summary": "정책브리핑 현재 목록에서 수집. 상세 자격·기한은 원문 추가 검증 필요", "publishedAt": None})
        else:
            root = ET.fromstring(raw)
            def field(node, name):
                for child in node:
                    if child.tag.rsplit("}", 1)[-1] == name:
                        return child.text or child.get("href", "")
                return ""
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
                    continue
                item = {"title": clean_text(field(node, "title")), "url": field(node, "link"),
                        "summary": clean_text(field(node, "description") or field(node, "summary") or field(node, "content")),
                        "publishedAt": field(node, "pubDate") or field(node, "published") or field(node, "updated")}
                if spec["id"] == "google_trends":
                    item["trendTrafficLabel"] = field(node, "approx_traffic")
                items.append(item)
        seen = set()
        for item in items:
            if spec["id"] == "policy":
                u = urlsplit(item["url"])
                item["url"] = urlunsplit((u.scheme, u.netloc, u.path, urlencode([(k,v) for k,v in parse_qsl(u.query) if k == "newsId"]), ""))
            key = (item.get("url"), item.get("title")) if spec["id"] == "google_trends" else item.get("url")
            if not item.get("title") or not public_url(item.get("url")) or key in seen:
                continue
            seen.add(key)
            receipt["items"].append({**item, "sourceId": spec["id"], "sourceUrl": spec["url"], "fetchedAt": receipt["fetchedAt"],
                                     "freshness": source_freshness(item.get("publishedAt"))})
        receipt["items"] = receipt["items"][:25]
        receipt["status"] = "collected" if receipt["items"] else "unverified"
        if not receipt["items"]:
            receipt["reason"] = "HTTP 성공이나 파싱 가능한 후보가 없어 발굴 완료로 집계하지 않음"
    except Exception as exc:
        receipt["reason"] = type(exc).__name__
    return receipt


def build_proposals(receipts):
    candidates = [item for source in receipts if source["track"] == "A" for item in source["items"]]
    relevant = re.compile(r"지원|연금|금융|보험|대출|건강|의료|주거|청년|복지|신청|수당|세금|장려|소득|예금|노인|시니어|위약금|소비복권|온누리|치료제|구급차|가격|할인|조건|병원|출산|일정")
    actionable = re.compile(r"신청|대상|위약금|온누리|소비복권|치료제|준비|환급|요금|예약|구급차|지원금|장려금|가격|할인|조건|세금")
    candidates = [i for i in candidates if i.get("sourceId") == "blokey_golden" or relevant.search(i["title"])]
    candidates.sort(key=lambda i: (
        i.get("sourceId") != "blokey_golden",
        -(i.get("goldenRate") or 0),
        -len(actionable.findall(i["title"])),
        i["sourceId"] != "policy",
        -len(relevant.findall(i["title"])),
    ))
    track_a, seen = [], set()
    for item in candidates:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        is_blokey = item.get("sourceId") == "blokey_golden"
        sv = item.get("searchVolume")
        comp = item.get("competition")
        gr = item.get("goldenRate")
        grade = item.get("grade")
        track_a.append({
            **item,
            "keyword": item["title"],
            "target": PRIORITY_DOMAINS[len(track_a) % 3],
            "proposal": (
                f"블로키 {grade}등급(💎{gr}) 황금키워드 즉시 선점 — 총검색량 {sv:,}회 대비 문서수 {comp:,}건 빈집 타깃"
                if is_blokey and sv is not None
                else "원문 대상·신청 조건을 확인해 독자가 실행할 수 있는 안내/계산 도구로 구성"
            ),
            "searchVolume": sv,
            "competition": comp,
            "goldenRate": gr,
            "grade": grade,
            "keywordRpm": None,
            "status": "verified_golden" if is_blokey else "hypothesis",
            "evidenceScope": (
                f"블로키(Blokey Pro) 실측 검증 완료: 총검색량 {sv:,}회 · 문서수 {comp:,}건 · 황금지수 💎{gr} ({grade}등급)"
                if is_blokey and sv is not None
                else "출처 제목/피드 확인; 빈집·고단가·월검색량 미검증"
            ),
        })
        if len(track_a) == 5:
            break
    track_b = []
    ordered = sorted(receipts, key=lambda s: (s.get("sourceId") != "app_store", s.get("sourceId") != "product_hunt"))
    for source in ordered:
        if source["track"] != "B" or not source["items"]:
            continue
        selected = source["items"]
        if source["sourceId"] == "product_hunt":
            selected = sorted(selected, key=lambda i: not re.search(r"presentation|reminder|checklist|calendar|print", i.get("summary", ""), re.I))
        for item in selected[:1]:
            app = source["sourceId"] == "app_store"
            presentation = bool(re.search(r"presentation", item.get("summary", ""), re.I))
            track_b.append({**item, "idea": "큰글씨 복약·생활 일정 인쇄 카드" if app else "부모님용 3장 생활 안내 슬라이드 제작기" if presentation else f"{item['title']}의 단일 기능 검증 후보",
                            "observedProblem": "반복 일정 입력과 확인 부담" if app else "설명을 듣고 다시 확인할 간단한 자료 필요" if presentation else item.get("summary", ""),
                            "mvp": "브라우저 로컬 저장·큰글씨 입력·인쇄 1화면, 로그인/결제/의료판단 제외" if app else "제목과 3단계를 입력하면 큰글씨 HTML 카드·인쇄 생성; AI 라이브 발표/계정/결제는 제외" if presentation else "원문 기능 확인 후 하루 범위로 축소; 현재 구현 범위 미확정",
                            "buildEstimate": "1일 가설; 구현·사용자 검증 전", "businessModel": "광고/유료 인쇄 양식 가능성 검증" if app else "무료 체험 후 단건 유료 기능 가능성 검증",
                            "revenueEvidence": {"kind": "listed_price" if app else "product_listing_only", "value": item.get("price"), "currency": item.get("currency"), "actualRevenue": None},
                            "status": "hypothesis", "target": "must-pick.com" if app else "woorinote.kr"})
    return track_a, track_b[:4]


def _fetch_live_korean_serp_hits(keyword, limit=6):
    """Fetch real top-ranking Korean blog/view posts from Naver SERP and Google News KR RSS."""
    hits = []
    try:
        q = urlencode({"where": "nexearch", "query": keyword})
        r = requests.get(f"https://search.naver.com/search.naver?{q}", headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            seen = set()
            for a in soup.select("a.title_link, a.api_txt_lines.total_tit, a.news_tit"):
                title = clean_text(a.get_text(" ", strip=True), 160)
                href = str(a.get("href") or "")
                if len(title) >= 8 and href.startswith("https://") and href not in seen:
                    seen.add(href)
                    hits.append({"title": title, "url": href, "source": "naver_serp_top"})
                    if len(hits) >= limit:
                        break
    except Exception:
        pass
    if len(hits) < 3:
        try:
            from common.content_improvement import search_results
            sr = search_results(keyword)
            raw_list = sr.get("results", []) if isinstance(sr, dict) else (sr if isinstance(sr, list) else [])
            for item in raw_list:
                if isinstance(item, dict) and item.get("url") and "support.google.com" not in str(item.get("url")):
                    hits.append({"title": item.get("title", ""), "url": item.get("url", ""), "source": "web_search"})
                    if len(hits) >= limit:
                        break
        except Exception:
            pass
    return hits[:limit]


def autonomous_knowhow_study(track_a):
    """Radar autonomously explores live web results for top-ranking blog/monetization patterns, fact-checks, and records into the Synapse Vault."""
    try:
        from common.llm_client import generate_json
        from common.knowledge_policy import record_knowhow
        from common.crew_chat_bridge import emit_work_event
        seed_kw = (track_a[0].get("keyword") if track_a else "정부지원금 환급금 신청방법 조건 비교")
        hits = _fetch_live_korean_serp_hits(seed_kw, limit=6)
        if not hits and track_a:
            hits = [{"title": r.get("title", ""), "url": r.get("url", ""), "source": r.get("sourceId", "radar")} for r in track_a[:4]]
        if not hits:
            return None
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 2, "maxLength": 160},
                "factCheckSummary": {"type": "string", "minLength": 10, "maxLength": 800},
                "method": {"type": "string", "minLength": 10, "maxLength": 1000},
                "whenToUse": {"type": "string", "minLength": 5, "maxLength": 400},
                "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            },
            "required": ["title", "factCheckSummary", "method", "whenToUse", "tags"],
            "additionalProperties": False,
        }
        prompt = (
            "당신은 자율 순찰 중인 @레이더(스카우터)다. 독립적인 닥터 검수가 있었다고 주장하지 않는다. "
            "검색 자료에서 도출하는 내용은 실험 전 가설이다. 순위·수익·계정 수명 효과가 검증됐다고 표현하지 않는다. "
            "실시간 네이버 검색 상위 노출 블로그/뉴스 문서들과 황금키워드·정책 데이터를 대조·분석하여, "
            "[하루 수익 $100 달성]을 위해 우리 블로그(네이버·CF)·지식iN·Threads·브런치가 즉시 적용할 수 있는 "
            "1) 상위 1등 문서의 제목 후킹·도입부 3초 체류 공식, 2) 자청 4대 결핍(손실회피·비교우위) 자극 비교표 설계법, 3) 파생 고단가 아이템 확장 절차 중 가장 실용적인 노하우 1건을 구체적인 실행 절차(method)로 도출하라.\n"
            + json.dumps({"keyword": seed_kw, "searchHits": hits, "officialCandidates": track_a[:3]}, ensure_ascii=False)
        )
        res = generate_json(prompt, agent_slot="radar", response_schema=schema, timeout_seconds=90, memory_read_only=True, crew_actor="radar", crew_actor_label="레이더", crew_stage="radar-autonomous-study")
        saved = record_knowhow(
            title=res["title"],
            method=res["method"],
            when_to_use=res["whenToUse"],
            fact_check_summary=res["factCheckSummary"],
            source_url=(hits[0].get("url") if isinstance(hits[0], dict) else ""),
            source_type="radar_autonomous_study",
            tags=res.get("tags") or [],
            recorded_by="radar",
            external_sources=hits,
        )
        emit_work_event(actor="radar", actor_label="레이더", task_id="radar-study:" + str(int(time.time())), phase="completed", stage="radar-autonomous-study", output_kind=f"[자율 노하우 습득·벤치마킹] {res['title']} — {res['method'][:180]}")
        return saved
    except Exception:
        return None


class RadarScout:
    def __init__(self, state_dir=None):
        self.state_dir = Path(state_dir or ROOT / "dashboard/data/radar")
        self.db_path = self.state_dir / "scout.sqlite3"
        self.stop_event = threading.Event()
        self.thread = None

    def db(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, slot TEXT UNIQUE, status TEXT, started REAL, finished REAL, result TEXT, error TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)")
        db.commit()
        return db

    def enabled(self):
        with closing(self.db()) as db:
            row = db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()
        return row is None or row[0] == "true"

    def set_enabled(self, enabled):
        with closing(self.db()) as db, db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('enabled',?)", (json.dumps(bool(enabled)),))

    @staticmethod
    def due_slot(now=None):
        now = (now or datetime.now(KST)).astimezone(KST)
        # Startup/restart never floods missed slots. Only the current 15m window.
        if now.hour in HOURS and now.minute < 15:
            return now.strftime("%Y-%m-%dT%H:00+09:00")
        return None

    def claim(self, slot=None):
        now = time.time()
        # Manual clicks and natural-language commands share a 5-minute dedup key.
        slot = slot or f"manual:{int(now // 300)}"
        with closing(self.db()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE runs SET status='interrupted',finished=?,error='Lease expired; no automatic replay' WHERE status='running' AND started<?", (now, now - 1800))
            active = db.execute("SELECT run_id FROM runs WHERE status='running'").fetchone()
            if active:
                return {"started": False, "runId": active[0], "reason": "already_running"}
            existing = db.execute("SELECT run_id,status FROM runs WHERE slot=?", (slot,)).fetchone()
            if existing:
                return {"started": False, "runId": existing[0], "reason": "deduplicated", "status": existing[1]}
            run_id = uuid.uuid4().hex
            db.execute("INSERT INTO runs VALUES(?,?,'running',?,NULL,NULL,NULL)", (run_id, slot, now))
        return {"started": True, "runId": run_id, "slot": slot}

    def latest(self):
        empty = {"enabled": None, "scheduleKst": ["09:00", "14:00", "20:00"], "catchup": False, "latest": {}}
        if not self.db_path.is_file():
            return {**empty, "status": "not_collected"}
        try:
            with closing(sqlite3.connect(self.db_path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                db.row_factory = sqlite3.Row
                row = db.execute("SELECT * FROM runs ORDER BY started DESC LIMIT 1").fetchone()
                setting = db.execute("SELECT value FROM settings WHERE key='enabled'").fetchone()
        except sqlite3.Error:
            return {**empty, "status": "unavailable"}
        result = dict(row) if row else {}
        if result.get("result"):
            result["result"] = json.loads(result["result"])
            action = result['result'].get('growthAction') or {}
            if action.get('id'):
                from common import dashboard_jobs
                try:
                    observed = dashboard_jobs.load(action['id'])
                    result['result']['growthAction'] = dashboard_jobs.public(observed)
                    result['result']['growthActionResult'] = observed.get('result')
                except (OSError, ValueError):
                    result['result']['growthActionObservation'] = 'unavailable'
        return {**empty, "enabled": setting is None or setting[0] == "true", "latest": result}

    def run_claimed(self, claim, publisher=None, fetcher=fetch_source):
        if not claim.get("started"):
            return claim
        run_id = claim["runId"]
        try:
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="radar-source") as pool:
                receipts = list(pool.map(fetcher, SOURCES))
            track_a, track_b = build_proposals(receipts); learned_knowhow = autonomous_knowhow_study(track_a)
            # External trends are supplementary. The Windows worker derives the
            # actionable queue from verified local page-performance evidence.
            from common import dashboard_jobs
            growth_job = dashboard_jobs.enqueue('growth-radar', {'requestedBy': 'radar', 'runId': run_id})
            result = {"runId": run_id, "slot": claim["slot"], "checkedAt": now_iso(), "sources": receipts,
                      "trackA": track_a, "trackB": track_b, "priorityDomains": list(PRIORITY_DOMAINS),
                      "historicalUserRpm": {"woorinote.kr": 6.33, "must-good.com": 6.28, "must-pick.com": 3.93},
                      "rpmNote": "사용자 제공 과거 값; 기간/통화/현재 순위 미검증. 키워드 RPM으로 대입 금지",
                      "marketing": [s for s in receipts if s["track"] == "marketing"],
                      "status": "growth_action_queued", "publishedExternally": False,
                      "growthAction": dashboard_jobs.public(growth_job),
                      "growthActionNote": "Windows 실행 대기. 큐 등록·원고 생성·발행·수익 성과는 작업 결과로 별도 확인합니다.",
                      "sourceStatus": "collected" if track_a or track_b else "no_verified_candidates"}
            # Save the evidence before chat side effects. Stable message IDs make replay idempotent.
            with closing(self.db()) as db, db:
                db.execute("UPDATE runs SET result=? WHERE run_id=?", (json.dumps(result, ensure_ascii=False), run_id))
            if publisher:
                result["chat"] = publisher(result)
            with closing(self.db()) as db, db:
                db.execute("UPDATE runs SET status='completed',finished=?,result=? WHERE run_id=?", (time.time(), json.dumps(result, ensure_ascii=False), run_id))
            return result
        except Exception as exc:
            with closing(self.db()) as db, db:
                db.execute("UPDATE runs SET status='failed',finished=?,error=? WHERE run_id=?", (time.time(), type(exc).__name__, run_id))
            raise

    def trigger(self, publisher=None, slot=None, background=True):
        from common import work_agenda as agendas
        if agendas.enabled() and not agendas.current():
            key=slot or now_iso()[:10]
            identity=agendas.propose('radar',key,title='레이더 시장 조사 · '+str(key),project='collections',
                source={'slot':slot},completion='실제 조회한 출처와 확인·미확인 사항을 구분한 조사 보고',priority=30)
            return {'started':False,'status':'queued','businessAgendaId':identity}
        claim = self.claim(slot)
        if not claim["started"]:
            return claim
        if not background:
            return self.run_claimed(claim, publisher)
        def work():
            try:
                self.run_claimed(claim, publisher)
            except Exception:
                pass  # Durable failed status is returned by the status endpoint.
        threading.Thread(target=work, daemon=True, name="radar-scout-run").start()
        return claim

    def start(self, publisher):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                try:
                    slot = self.due_slot()
                    if self.enabled() and slot:
                        self.trigger(publisher, slot)
                except Exception:
                    pass
                self.stop_event.wait(30)
        self.thread = threading.Thread(target=loop, daemon=True, name="radar-kst-scheduler")
        self.thread.start()


SCOUT = RadarScout()
