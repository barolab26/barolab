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

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
HOURS = (9, 14, 20)
PRIORITY_DOMAINS = ("woorinote.kr", "must-good.com", "must-pick.com")
SOURCES = (
    {"id": "policy", "track": "A", "url": "https://www.korea.kr/main.do", "kind": "policy_html"},
    {"id": "google_trends", "track": "A", "url": "https://trends.google.com/trending/rss?geo=KR", "kind": "feed"},
    {"id": "naver_datalab", "track": "A", "url": "https://datalab.naver.com/keyword/realtimeList.naver", "kind": "availability"},
    {"id": "google_search_updates", "track": "marketing", "url": "https://developers.google.com/search/updates/search_docs_updates.rss", "kind": "feed"},
    {"id": "product_hunt", "track": "B", "url": "https://www.producthunt.com/feed", "kind": "feed"},
    {"id": "indie_hackers", "track": "B", "url": "https://www.indiehackers.com/feed.xml", "kind": "feed"},
    {"id": "app_store", "track": "B", "url": "https://itunes.apple.com/search?term=medication%20reminder&entity=software&country=kr&limit=8", "kind": "app_store"},
    {"id": "youtube_outliers", "track": "B", "url": "https://www.youtube.com/feed/trending", "kind": "availability"},
)


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
    relevant = re.compile(r"지원|연금|금융|보험|대출|건강|의료|주거|청년|복지|신청|수당|세금|장려|소득|예금|노인|시니어|위약금|소비복권|온누리|치료제|구급차")
    actionable = re.compile(r"신청|대상|위약금|온누리|소비복권|치료제|준비|환급|요금|예약|구급차|지원금")
    candidates = [i for i in candidates if relevant.search(i["title"])]
    candidates.sort(key=lambda i: (-len(actionable.findall(i["title"])), i["sourceId"] != "policy", -len(relevant.findall(i["title"]))))
    track_a, seen = [], set()
    for item in candidates:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        track_a.append({**item, "keyword": item["title"], "target": PRIORITY_DOMAINS[len(track_a) % 3],
                        "proposal": "원문 대상·신청 조건을 확인해 독자가 실행할 수 있는 안내/계산 도구로 구성",
                        "searchVolume": None, "competition": None, "keywordRpm": None,
                        "status": "hypothesis", "evidenceScope": "출처 제목/피드 확인; 빈집·고단가·월검색량 미검증"})
        if len(track_a) == 3:
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


class RadarScout:
    def __init__(self, state_dir=None):
        self.state_dir = Path(state_dir or ROOT / "server/data/radar")
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
        with closing(self.db()) as db:
            row = db.execute("SELECT * FROM runs ORDER BY started DESC LIMIT 1").fetchone()
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
        return {"enabled": self.enabled(), "scheduleKst": ["09:00", "14:00", "20:00"], "catchup": False, "latest": result}

    def run_claimed(self, claim, publisher=None, fetcher=fetch_source):
        if not claim.get("started"):
            return claim
        run_id = claim["runId"]
        try:
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="radar-source") as pool:
                receipts = list(pool.map(fetcher, SOURCES))
            track_a, track_b = build_proposals(receipts)
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
