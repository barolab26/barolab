"""Source-reviewed, complete Naver Cafe posting and evidence-scoped status."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any
import re
from urllib.parse import unquote, urlsplit

ROOT_DIR = Path(__file__).resolve().parents[1]
CAFE_STATUS_PATH = ROOT_DIR / "dashboard" / "data" / "cafe" / "status.json"
CAFE_PUBLIC_JSON_PATH = ROOT_DIR / "dashboard" / "data" / "public" / "cafe.json"
TRAFFIC_JSON_PATH = ROOT_DIR / "dashboard" / "data" / "traffic.json"

KST = dt.timezone(dt.timedelta(hours=9))


def now_kst_str() -> str:
    return dt.datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M:%S")


CAFE_POLICIES: dict[str, dict[str, Any]] = {
    "boutiqueinfo": {"cafeId":"boutiqueinfo", "clubId":"31608088", "menuId":"4", "account":"soul5373",
        "tier":"완결형 정보 포스팅", "policyMode":"reader_complete", "requiredNoLinkStreak":0,
        "topicTags":["finance","tax","welfare","health"], "externalLinksAllowed":True,
        "boardMenus":{"4":"[경제정보]","5":"[금융/대출정보실]","7":"[정부지원혜택]","9":"[기타정보]"},
        "ratioLabel":"링크는 추가 가치가 검증된 경우에만 선택", "defenseRule":"본문만으로 질문 해결 · 정확한 근거 · 문단/표 · 게시판 규칙 준수"},
    "dekilab": {"cafeId":"dekilab", "clubId":"31529204", "menuId":"18", "account":"yoon_master",
        "tier":"AI/테크 독자용 완결형 포스팅", "policyMode":"suspended_banned", "restrictionUntil":"2026-11-24", "restrictionEvidence":"dashboard/data/repair-workflows/company-20261106/dekilab-restriction.json", "requiredNoLinkStreak":0,
        "topicTags":["ai","automation","coding"], "externalLinksAllowed":False, "boardMenus":{"18":"AI 정보 & 팁 공유"},
        "ratioLabel":"횟수로 링크를 해금하지 않음", "defenseRule":"AI/테크 주제 적합성 필수 · 링크 규칙 확인 전 외부 링크 제외"},
    "loveshake1": {"cafeId":"loveshake1", "clubId":"19858249", "menuId":"164", "account":"soul5373",
        "tier":"활동 제한 기록 보존", "policyMode":"suspended_banned", "requiredNoLinkStreak":0,
        "topicTags":[], "externalLinksAllowed":False, "ratioLabel":"송출 중단", "defenseRule":"우회 발행·계정 교체·삭제 글 재발행 금지"},
}


def evaluate_cafe_safety_quota(cafe_id: str, published_articles: list[dict[str, Any]]) -> dict[str, Any]:
    policy = CAFE_POLICIES.get(cafe_id, CAFE_POLICIES["loveshake1"])
    pubs = [a for a in published_articles if a.get("cafeId") == cafe_id]
    no_link = sum(a.get("hasExternalLink") is False for a in pubs)
    suspended = policy["policyMode"] == "suspended_banned"
    return {**policy, "nextPostMode":"held" if suspended else "reader_complete",
        "nextPostModeBadge":"송출 중단" if suspended else "근거 검수된 완결형 포스팅",
        "noLinkStreak":0, "remainingNoLinkNeeded":0, "bridgeUnlocked":False,
        "totalCount":len(pubs), "noLinkCount":no_link, "bridgeCount":len(pubs)-no_link,
        "safetyStatus":"활동 제한 · 재발행 금지" if suspended else "원고별 품질·주제·링크 검수 필요"}


def _extract_ga4_channel_referrals(channel_keywords: list[str]) -> dict[str, Any]:
    """Read `dashboard/data/traffic.json` and aggregate GA4 sessions/pageviews matching `channel_keywords`.

    Uses `periods.get('week')` (7-day window) and `periods.get('month')` (30-day window) from `traffic.json`,
    and preserves `None` when traffic data or period sources are missing instead of coercing missing sources to `0`.
    """
    total_today_sessions: int | None = None
    total_7d_sessions: int | None = None
    total_30d_sessions: int | None = None
    domain_breakdown: list[dict[str, Any]] = []
    if TRAFFIC_JSON_PATH.exists():
        try:
            tdata = json.loads(TRAFFIC_JSON_PATH.read_text(encoding="utf-8"))
            sites = tdata.get("sites") or {}
            for dom, sinfo in sites.items():
                ga4_info = sinfo.get("ga4") if isinstance(sinfo, dict) else None
                periods = (ga4_info.get("periods") if isinstance(ga4_info, dict) else None) or {}
                if not isinstance(periods, dict) or not periods:
                    domain_breakdown.append({
                        "domain": dom,
                        "todaySessions": None,
                        "weekSessions": None,
                        "monthSessions": None,
                        "last7DaysSessions": None,
                        "last28DaysSessions": None,
                        "totalPageViewsToday": None,
                    })
                    continue

                def _sum_period_sources(p_obj: Any) -> int | None:
                    if not isinstance(p_obj, dict) or not isinstance(p_obj.get("sources"), list):
                        return None
                    acc = 0
                    for src in p_obj["sources"]:
                        if not isinstance(src, dict):
                            continue
                        s_name = str(src.get("source") or "").lower()
                        c_name = str(src.get("channel") or "").lower()
                        if any(k in s_name or k in c_name for k in channel_keywords):
                            raw_sess = src.get("sessions")
                            if isinstance(raw_sess, (int, float)):
                                acc += int(raw_sess)
                    return acc

                dom_today = _sum_period_sources(periods.get("today"))
                dom_7d = _sum_period_sources(periods.get("week"))
                dom_30d = _sum_period_sources(periods.get("month"))

                if dom_today is not None:
                    total_today_sessions = (total_today_sessions or 0) + dom_today
                if dom_7d is not None:
                    total_7d_sessions = (total_7d_sessions or 0) + dom_7d
                if dom_30d is not None:
                    total_30d_sessions = (total_30d_sessions or 0) + dom_30d

                today_obj = periods.get("today") if isinstance(periods.get("today"), dict) else None
                raw_pv_today = today_obj.get("pageViews") if today_obj else None
                pv_today = int(raw_pv_today) if isinstance(raw_pv_today, (int, float)) else None

                domain_breakdown.append({
                    "domain": dom,
                    "todaySessions": dom_today,
                    "weekSessions": dom_7d,
                    "monthSessions": dom_30d,
                    "last7DaysSessions": dom_7d,
                    "last28DaysSessions": dom_30d,
                    "totalPageViewsToday": pv_today,
                })
        except Exception:
            pass
    domain_breakdown.sort(
        key=lambda x: (
            x["monthSessions"] if x["monthSessions"] is not None else -1,
            x["totalPageViewsToday"] if x["totalPageViewsToday"] is not None else -1,
        ),
        reverse=True,
    )
    return {
        "windowMetadata": {
            "today": {"sourcePeriod": "today", "windowDays": 1},
            "week": {"sourcePeriod": "week", "windowDays": 7},
            "month": {
                "sourcePeriod": "month",
                "windowDays": 30,
                "note": "GA4 month period covers 30 days; last28DaysSessions aliases monthSessions for UI compatibility",
            },
        },
        "todaySessions": total_today_sessions,
        "weekSessions": total_7d_sessions,
        "monthSessions": total_30d_sessions,
        "last7DaysSessions": total_7d_sessions,
        "last28DaysSessions": total_30d_sessions,
        "topDomains": domain_breakdown[:8],
    }


DEFAULT_CAFE_PUBLISHED_ARTICLES: list[dict[str, Any]] = [
    {
        "id": "boutiqueinfo-2305",
        "part": 6,
        "cafeId": "boutiqueinfo",
        "cafeName": "고급지식의 모든 것",
        "boardName": "지식 아카이브 (menuId 4)",
        "members": 1722,
        "account": "soul5373",
        "postType": "direct_bridge",
        "postTypeBadge": "🔗 Tier 1 다이렉트 브릿지",
        "hasExternalLink": True,
        "title": "[핵심정리] 희망리턴패키지 점포철거비 지원금·폐업 부가세 신고 (점포철거비 지원 조건과 폐업 부가세·잔존재화 과세)",
        "articleUrl": "https://cafe.naver.com/boutiqueinfo/2305",
        "bridgeDomain": "meganote.kr",
        "bridgeUrl": "https://www.meganote.kr/simplified-to-general-vat-inventory-check",
        "publishedAt": "2026-11-02 17:41 KST",
        "status": "published_verified",
        "statusLabel": "🟢 실측 발행 영수증 검증 완료 (#2305)",
    },
    {
        "id": "loveshake1-162878",
        "part": 5,
        "cafeId": "loveshake1",
        "cafeName": "[금융꿀팁] 직장인/주부/서민/아파트론/대환/저금리",
        "boardName": "자유게시판·금융꿀팁 (menuId 164)",
        "members": 28495,
        "account": "soul5373",
        "postType": "direct_bridge",
        "postTypeBadge": "🔗 브릿지 발행 (이후 3편 무링크 잠금)",
        "hasExternalLink": True,
        "title": "2026 주택연금 가입조건 공시가격 12억 기준 및 월 수령액·우대형 계산 핵심정리",
        "articleUrl": "https://cafe.naver.com/loveshake1/162878",
        "bridgeDomain": "smilenote.kr",
        "bridgeUrl": "https://www.smilenote.kr/",
        "publishedAt": "2026-11-02 14:22 KST",
        "status": "published_verified",
        "statusLabel": "🟢 실측 발행 영수증 검증 완료 (#162878)",
    },
    {
        "id": "boutiqueinfo-2302",
        "part": 5,
        "cafeId": "boutiqueinfo",
        "cafeName": "고급지식의 모든 것",
        "boardName": "지식 아카이브 (menuId 4)",
        "members": 1722,
        "account": "soul5373",
        "postType": "direct_bridge",
        "postTypeBadge": "🔗 Tier 1 다이렉트 브릿지",
        "hasExternalLink": True,
        "title": "2026 주택연금 가입조건 공시가격 12억 기준 및 월 수령액·우대형 계산 핵심정리",
        "articleUrl": "https://cafe.naver.com/boutiqueinfo/2302",
        "bridgeDomain": "smilenote.kr",
        "bridgeUrl": "https://www.smilenote.kr/",
        "publishedAt": "2026-11-02 14:23 KST",
        "status": "published_verified",
        "statusLabel": "🟢 실측 발행 영수증 검증 완료 (#2302)",
    },
    {
        "id": "loveshake1-162877",
        "part": 1,
        "cafeId": "loveshake1",
        "cafeName": "[금융꿀팁] 직장인/주부/서민/아파트론/대환/저금리",
        "boardName": "자유게시판·금융꿀팁 (menuId 164)",
        "members": 28495,
        "account": "soul5373",
        "postType": "direct_bridge",
        "postTypeBadge": "🔗 브릿지 발행",
        "hasExternalLink": True,
        "title": "국민연금 기초연금 중복수령 감액 기준과 A급여액 산식·소득인정액 계산법",
        "articleUrl": "https://cafe.naver.com/loveshake1/162877",
        "bridgeDomain": "must-good.com",
        "bridgeUrl": "https://www.must-good.com/parent-benefit-home-care-allowance-application-payment-date",
        "publishedAt": "2026-11-02 13:55 KST",
        "status": "published_verified",
        "statusLabel": "🟢 실측 발행 영수증 검증 완료 (#162877)",
    },
]


def load_cafe_status() -> dict[str, Any]:
    if CAFE_STATUS_PATH.exists():
        try:
            return json.loads(CAFE_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_cafe_status(data: dict[str, Any]) -> dict[str, Any]:
    from naver_cafe_posting.editorial import write
    write(CAFE_STATUS_PATH, data)
    write(CAFE_PUBLIC_JSON_PATH, data)
    return data


def normalize_articles(articles):
    """Count canonical posts once; preserve encoded/legacy receipts as aliases."""
    records = {}
    for index, original in enumerate(articles):
        row = dict(original)
        url = str(row.get('articleUrl') or '')
        for _ in range(4):
            url = unquote(url)
        club = (CAFE_POLICIES.get(row.get('cafeId')) or {}).get('clubId')
        match = re.search(r'/cafes/(\d+)/articles/(\d+)', url)
        short = re.fullmatch(r'/([^/]+)/(\d+)', urlsplit(url).path)
        query_id = re.search(r'(?:[?&])articleid=(\d+)', url)
        actual_club = match[1] if match else club
        article_id = match[2] if match else (short[2] if short and short[1] == row.get('cafeId') else query_id[1] if query_id else None)
        valid = urlsplit(url).hostname == 'cafe.naver.com' and club and actual_club == club and article_id
        key = (club, article_id) if valid else ('unresolved', index)
        if valid:
            row['articleUrl'] = f'https://cafe.naver.com/ca-fe/cafes/{club}/articles/{article_id}'
        if key not in records:
            records[key] = row
            continue
        previous = records[key]
        rank = lambda a: ({'body_verified':3,'body_observed':2,'unavailable':1}.get(a.get('publicState'),0),a.get('publicCheckedAt',''))
        preferred, other = (row, previous) if rank(row) > rank(previous) else (previous, row)
        aliases = list(preferred.get('legacyRecordAliases') or []) + list(other.get('legacyRecordAliases') or [])
        alias = {k:v for k,v in other.items() if k != 'legacyRecordAliases'}
        if alias not in aliases:
            aliases.append(alias)
        preferred['legacyRecordAliases'] = aliases
        records[key] = preferred
    return list(records.values())


def sync_cafe_live_state() -> dict[str, Any]:
    """Refresh metadata only; never claim that cached receipts prove current public state."""
    from brunch_posting.posting import BRUNCHBOOK_CURRICULUM
    prev = load_cafe_status()
    articles = normalize_articles(list(prev.get("publishedArticles") or DEFAULT_CAFE_PUBLISHED_ARTICLES))
    for article in articles:
        article.setdefault("legacyPublicationStatus", article.get("status"))
        state = article.get("publicState", "not_rechecked")
        article["status"] = "body_verified" if state == "body_verified" else state
        article["statusLabel"] = {"body_verified":"본문·문단·표·링크 검증 완료",
            "body_observed":"현재 본문 열람 확인 · 기존 글 유지", "unavailable":"현재 접근 불가 · 삭제 원인 미확인"}.get(state,"기존 발행 기록 · 현재 본문 미검증")
        article["postTypeBadge"] = "완결형 정보 포스팅" if state == "body_verified" else "기존 기록 보존"
    quotas = {c:evaluate_cafe_safety_quota(c,articles) for c in CAFE_POLICIES}
    names = {"boutiqueinfo":"고급지식의 모든 것", "dekilab":"AI 커뮤니티 - 데키랩", "loveshake1":"금융꿀팁 (활동 제한 기록)"}
    cafes = []
    for cafe_id in ("boutiqueinfo","dekilab"):
        q = quotas[cafe_id]
        cafes.append({**q,"name":names[cafe_id],"shortName":names[cafe_id],"members":None,
            "account":CAFE_POLICIES[cafe_id]["account"],"cafeUrl":f"https://cafe.naver.com/{cafe_id}",
            "grade":"회원수·등급은 발행 품질/노출 증거가 아님", "writeMode":"검수된 완결형 포스팅",
            "targetTopics":"금융·세금·복지·건강" if cafe_id=="boutiqueinfo" else "AI·자동화·코딩",
            "publishedCount":q["totalCount"],"status":"review_required","statusBadge":q["safetyStatus"],
            "latestArticleUrl":next((a["articleUrl"] for a in articles if a.get("cafeId")==cafe_id),"")})
    queue = []
    for item in BRUNCHBOOK_CURRICULUM:
        found = [a for a in articles if a.get("cafeId")=="boutiqueinfo" and a.get("part")==item["part"]]
        queue.append({"part":item["part"],"title":item["title"],"subtitle":item["subtitle"],
            "category":item["category"],"targetCafes":"고급지식 · 주제 적합성 확인 후 검수",
            "bridgeDomain":"원고별 선택","bridgeUrl":"", "loveshakeUrl":"",
            "loveshakePlanMode":"out_of_scope","loveshakePlanLabel":"데키랩: 이 금융/복지 커리큘럼 배포 제외",
            "boutiqueUrl":found[0]["articleUrl"] if found else "",
            "boutiquePlanLabel":"기존 기록 보존" if found else "완결 원고·근거·검수 필요",
            "status":"existing_record" if found else "queued",
            "statusLabel":"기존 글 관측 · 중복 발행 제외" if found else "완결형 포스팅 준비 대기"})
    cafe_ga4 = _extract_ga4_channel_referrals(["cafe.naver","m.cafe.naver","naver_cafe"])
    naver_ga4 = _extract_ga4_channel_referrals(["naver"])
    payload = {**prev,"ok":True,"updatedAt":now_kst_str(),
        "account":{"naverId":"soul5373 + yoon_master","autoReclaimEnabled":False,
            "operatingRule":"완결된 정보 포스팅 · 현재 근거 · 독자 적합성 · 선택 링크 · 발행 후 독립 확인"},
        "antiBanStrategy":{"tier1Rule":"카페 글 자체에서 독자 질문을 해결 · 관련 링크만 선택",
            "tier2Rule":"활동 횟수로 링크를 허용하지 않음 · AI 카페에 금융/건강 글 배포 제외",
            "warmupRule":"활동 제한 보존 · 사용자 공간 자동 회수/불확실한 제출 재시도 금지",
            "boutiqueQuota":quotas["boutiqueinfo"],"dekilabQuota":quotas["dekilab"],"loveshakeQuota":quotas["loveshake1"]},
        "kpi":{"cafeCount":2,"totalMembers":None,"publishedArticleCount":len(articles),
            "bodyVerifiedCount":sum(a.get("publicState")=="body_verified" for a in articles),
            "unavailableCount":sum(a.get("publicState")=="unavailable" for a in articles),
            "pendingQueueCount":sum(q["status"]=="queued" for q in queue),
            "cafeGa4Sessions7d":cafe_ga4["weekSessions"],"cafeGa4Sessions30d":cafe_ga4["monthSessions"],
            "naverTotalSessions7d":naver_ga4["weekSessions"],"naverTotalSessions30d":naver_ga4["monthSessions"],
            "ga4WindowNote":"출처별 합계 · 개별 카페 글 성과/수익 귀속 아님", "dekilabNextMode":"AI/테크 원고만 검토"},
        "cafes":cafes,"publishedArticles":articles,"plannedQueue":queue,
        "measurement":{"totalMembersReach":None,"publishedTotalCount":len(articles),
            "completedQueueCount":0,"pendingQueueCount":sum(q["status"]=="queued" for q in queue),
            "cafeDirectReferrals":cafe_ga4,"naverEcosystemReferrals":naver_ga4,
            "cafeBreakdown":[],"attributedRevenue":None,"causalClaim":False}}
    return save_cafe_status(payload)


def _build_cafe_post_payload(cafe_slug, target_item, bridge_url=None, quota=None):
    """Legacy callers cannot silently turn truncated curriculum prose into a post."""
    from naver_cafe_posting.editorial import validate_document, render
    document = target_item.get("document")
    research = target_item.get("research")
    if not document or not research:
        raise ValueError("Complete source-reviewed Cafe document required; curriculum snippets are not publishable")
    validate_document(document, research, cafe_slug)
    return {"title":document["title"], "document":document, "contentHtml":render(document),
            "postType":"reader_complete", "hasExternalLink":bool(document.get("lineLinks"))}


def acquire_cafe_browser_lease(cafe_id: str) -> dict[str, Any]:
    """Use only the registered, agent-owned account space and visibly verify its login."""
    policy = CAFE_POLICIES[cafe_id]
    if policy.get('policyMode') == 'suspended_banned' or policy.get('restrictionUntil'):
        raise ValueError('Existing Cafe restriction requires its original resolution')
    status = load_cafe_status()
    if any(status.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold','pendingEffect')):
        raise ValueError('Protected Cafe work requires its original resume condition')
    from dashboard.common.ego_taskspace import run_ego_mjs, resolve_ego_profile
    account = policy['account']
    script = '''
const spaces=await listTaskSpaces();
const found=spaces.find(s=>s.name===SPACE);
if(found && found.ownership!=="agent")throw Error("account_space_unavailable_or_user_takeover");
const task=found?await taskSpace(found.id):await taskSpace(SPACE,{profileId:PROFILE});
if(task.ownership!=="agent")throw Error("user_takeover");
const prior=LEASE;
if(found && (prior.space!==task.spaceId || !prior.page))throw Error("account_page_lease_requires_reconciliation");
const page=task.page(found?prior.page:"p1");
const path=new URL(await page.url()).pathname;
if(path.endsWith('/write') || path.endsWith('/modify'))throw Error("existing_editor_requires_reconciliation");
let verified=false;
try {
 await page.goto("https://www.naver.com");
 const emails=await page.evaluate(()=>document.body.innerText.match(/[a-zA-Z0-9_.+-]+@naver\\.com/g)||[]);
 if(!emails.includes(ACCOUNT+"@naver.com"))throw Error("visible_logged_in_account_mismatch");
 verified=true;
 console.log("BAROLAB_EGO_JSON:"+JSON.stringify({space:task.spaceId,page:page.label,account:ACCOUNT,cafeId:CAFE,accountVerified:true}));
} finally {/* Preserve the exact page for inspection on authentication or navigation failure. */}
'''.replace('SPACE',json.dumps('barolab-'+account)).replace('PROFILE',json.dumps(resolve_ego_profile(account))).replace('LEASE',json.dumps(status.get('browserLease') or {})).replace('ACCOUNT',json.dumps(account)).replace('CAFE',json.dumps(cafe_id))
    lease = run_ego_mjs(script, timeout=60)
    if not isinstance(lease,dict) or lease.get('accountVerified') is not True:
        raise ValueError('Visible account verification failed; no browser lease granted')
    lease['expiresAt'] = (dt.datetime.now(dt.timezone.utc)+dt.timedelta(minutes=20)).isoformat()
    current = load_cafe_status()
    if any(current.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold','pendingEffect')):
        raise ValueError('Cafe control changed during account verification')
    current['browserLease']=lease
    save_cafe_status(current)
    return lease


def publish_cafe_bridge_part(part_no: int = 6) -> dict[str, Any]:
    from common import runtime_locks
    output=Path(__file__).resolve().parent/'output';output.mkdir(parents=True,exist_ok=True)
    with (output/'publisher.lock').open('a+b') as handle:
        try:runtime_locks.flock(handle,runtime_locks.LOCK_EX|runtime_locks.LOCK_NB)
        except BlockingIOError:return {'ok':False,'status':'busy','reason':'existing_cafe_publisher_preserved','publicationVerified':False}
        try:return _publish_cafe_bridge_part(part_no)
        finally:runtime_locks.flock(handle,runtime_locks.LOCK_UN)


def settle_cafe_preparation(cafe_id, part_no, folder):
    """Settle only an exact verified write receipt, without another browser write."""
    from naver_cafe_posting.editorial import read,digest
    from common.collection_observability import locked,write
    folder=Path(folder)
    try:
        doc=read(folder/'document.json');prepared=read(folder/'prepared.json')
        intent=read(folder/'intent.json');evidence=read(folder/'public-evidence.json')
    except (OSError,ValueError):return None
    sha=digest(doc);url=intent.get('url')
    if (intent.get('status')!='verified_published' or evidence.get('status')!='verified_published'
            or not url or evidence.get('url')!=url or prepared.get('cafeId')!=cafe_id
            or any(x.get('documentSha256')!=sha for x in (prepared,intent,evidence))
            or any(intent.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold','pendingEffect'))):return None
    receipt={'ok':True,'status':'verified_published','publicationVerified':True,
             'url':url,'documentSha256':sha,'verifiedAt':evidence.get('checkedAt'),
             'reusedExistingReceipt':True,'submissionDispatched':False}
    index=ROOT_DIR/'dashboard/data/cafe/preparation-jobs.json'
    with locked(index.with_suffix('.lock')):
        jobs=read(index) if index.exists() else {};job=jobs.get('jobs',{}).get(f'{cafe_id}:{part_no}')
        if job and (job.get('prepared') or {}).get('documentSha256')==sha:
            job.update(status='published_verified',publicationVerified=True,receipt=receipt,
                       nextAction='Observe public content and measure traffic and revenue separately')
            write(index,jobs)
    st=load_cafe_status()
    if st.get('approvedPreparedPart')==part_no:
        st.pop('approvedPreparedPart');st['updatedAt']=now_kst_str();save_cafe_status(st)
    return receipt


def _publish_cafe_bridge_part(part_no: int = 6) -> dict[str, Any]:
    """Only an explicitly prepared article and active browser lease may be submitted.

    Old records/parts are never reused as proof of public content or retried.
    Creating source/reviewed drafts is an explicit bounded preparation step.
    """
    from naver_cafe_posting.editorial import OUTPUT, read, browser_operation, write
    st = load_cafe_status()
    results = []
    if any(st.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold','pendingEffect')):
        return {'ok':False,'status':'held','reason':'original_resume_condition_required'}
    lease = st.get("browserLease") or {}
    try:
        active = dt.datetime.fromisoformat(lease["expiresAt"]) > dt.datetime.now(dt.timezone.utc)
    except (KeyError, ValueError, TypeError):
        active = False
    for cafe_id in ("boutiqueinfo", "dekilab"):
        existing = [a for a in st.get("publishedArticles", []) if a.get("cafeId")==cafe_id and int(a.get("part") or 0)==int(part_no)]
        if existing:
            receipt=settle_cafe_preparation(cafe_id,int(part_no),OUTPUT/'prepared'/f'part-{int(part_no)}'/cafe_id)
            if receipt:
                results.append({'cafe':cafe_id,**receipt});continue
            results.append({"cafe":cafe_id,"status":"existing_record_preserved","publicState":existing[0].get("publicState","not_rechecked")})
            continue
        folder = OUTPUT / "prepared" / f"part-{int(part_no)}" / cafe_id
        if not (folder / "prepared.json").is_file():
            results.append({"cafe":cafe_id,"status":"held","reason":"reviewed_article_and_explicit_browser_lease_required","autoRetry":False})
            continue
        intent = read(folder / "intent.json") if (folder / "intent.json").is_file() else {}
        if intent.get("status") in ("submitting","submission_unknown","verified_published","verified_updated") or any(intent.get(k) for k in ('manualStop','userTakeover','reviewBudgetHold','pendingEffect')):
            results.append({"cafe":cafe_id,"status":"held","reason":"reconcile_existing_write","autoRetry":False})
            continue
        if not active or lease.get('cafeId')!=cafe_id or lease.get('accountVerified') is not True:
            lease=acquire_cafe_browser_lease(cafe_id)
            active=True
        write(folder / "intent.json", {"status":"prepared","revisionAuthorized":False})
        browser_operation(lease["space"],lease["page"],folder,mode="stage")
        result = browser_operation(lease["space"],lease["page"],folder,mode="submit")
        document = read(folder / "document.json")
        row = {"id":f"{cafe_id}-{part_no}","cafeId":cafe_id,"part":int(part_no),
               "account":CAFE_POLICIES[cafe_id]["account"],"title":document["title"],"articleUrl":result["url"],
               "postType":"reader_complete","hasExternalLink":bool(document.get("lineLinks")),
               "publishedAt":now_kst_str(),"status":"published_verified","publicState":"body_verified",
               "statusLabel":"본문·문단·표·링크 확인 완료","evidencePath":str(folder / "public-evidence.json")}
        st=load_cafe_status()
        st.setdefault("publishedArticles",[]).insert(0,row)
        save_cafe_status(st)
        settle_cafe_preparation(cafe_id,int(part_no),folder)
        results.append({"cafe":cafe_id,**result})
    verified=any(r.get("status")=="verified_published" for r in results)
    return {"ok":verified,"publicationVerified":verified,"part":part_no,"receipts":results}


def process_cafe_autonomy_once() -> dict[str, Any]:
    """Consume only reviewed, explicitly leased work; no daily post-count target."""
    now = dt.datetime.now(KST)
    if now.hour < 9:
        return {"ok":True,"action":"waiting_for_slot"}
    st = load_cafe_status()
    part = st.get("approvedPreparedPart")
    if part is None:
        return {"ok":True,"action":"held","reason":"no_reviewed_prepared_article","autoRetry":False}
    return publish_cafe_bridge_part(int(part))


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    out = sync_cafe_live_state()
    print(json.dumps({"ok": out.get("ok"), "kpi": out.get("kpi"), "antiBanStrategy": out.get("antiBanStrategy")}, ensure_ascii=False, indent=2))
