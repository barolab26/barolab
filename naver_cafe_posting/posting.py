"""Dedicated Naver Cafe 30,217-Member Bridge & Anti-Ban Engine (`cafe.html` / `/api/cafe`).

Manages:
1. Tier 1 (`direct_bridge` · 100% Link Allowed):
   - `boutiqueinfo` (고급지식의 모든 것 · 1,722명 · clubid 31608088 · menuId 4)
2. Tier 2 (`safe_community_3to1` · 3:1 No-Link Camouflage + Soft Bridge Guardrail):
   - `loveshake1` ([금융꿀팁] 직장인/주부/서민/아파트론/대환/저금리 · 28,495명 · clubid 19858249 · menuId 164)
   - Future general cafes (자동 워밍업 및 3:1 무링크 순수 정보글 강제 비율 적용)
3. Native EGO Lite `Profile 4` (`barolab-soul5373`) FEEditor publishing & GA4 referral tracking.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
CAFE_STATUS_PATH = ROOT_DIR / "dashboard" / "data" / "cafe" / "status.json"
CAFE_PUBLIC_JSON_PATH = ROOT_DIR / "dashboard" / "data" / "public" / "cafe.json"
TRAFFIC_JSON_PATH = ROOT_DIR / "dashboard" / "data" / "traffic.json"

KST = dt.timezone(dt.timedelta(hours=9))


def now_kst_str() -> str:
    return dt.datetime.now(tz=KST).strftime("%Y-%m-%d %H:%M:%S")


CAFE_POLICIES: dict[str, dict[str, Any]] = {
    "boutiqueinfo": {
        "cafeId": "boutiqueinfo",
        "clubId": "31608088",
        "menuId": "4",
        "account": "soul5373",
        "tier": "Tier 1 · 브릿지 특화 카페",
        "policyMode": "direct_bridge",
        "requiredNoLinkStreak": 0,
        "cooldownHours": 4,
        "ratioLabel": "다이렉트 원문 브릿지 100% 허용",
        "defenseRule": "운영자 브릿지 허용 특화 카페 · 모든 글에 4문단 핵심 요약 + CF 고단가 원문 링크 카드 직접 삽입 (네이버 카페탭 통합검색 기지)",
    },
    "dekilab": {
        "cafeId": "dekilab",
        "clubId": "31529204",
        "menuId": "18",
        "account": "yoon_master",
        "tier": "Tier 2 · 일반 AI/테크 커뮤니티 (12,503명)",
        "policyMode": "safe_community_3to1",
        "requiredNoLinkStreak": 3,
        "cooldownHours": 48,
        "ratioLabel": "무링크 순수정보 75% (3편) : 소프트 브릿지 25% (1편)",
        "defenseRule": "금융꿀팁 초기 광고글 강퇴 교훈 반영 · 첫 3편은 외부링크 0개 순수 정보글로만 작성해 [작성글 보기] 진성 회원 위장 완료 후 4번째 글에만 소프트 브릿지 허용",
    },
    "loveshake1": {
        "cafeId": "loveshake1",
        "clubId": "19858249",
        "menuId": "164",
        "account": "soul5373",
        "tier": "Tier 2 · 일반 커뮤니티 (송출 제외 · 초기 링크글 강퇴)",
        "policyMode": "suspended_banned",
        "requiredNoLinkStreak": 3,
        "cooldownHours": 9999,
        "ratioLabel": "송출 중단 (초기 연속 링크글로 인한 활동 제한)",
        "defenseRule": "가입 직후 연속 브릿지 글 작성으로 강퇴됨 · 송출 파이프라인에서 즉시 격리하고 신규 일반 카페는 무조건 '무링크 3편 선행 워밍업' 강제 적용",
    },
}


def evaluate_cafe_safety_quota(cafe_id: str, published_articles: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate whether the next post on `cafe_id` must be a No-Link pure value post or can include a bridge link."""
    policy = CAFE_POLICIES.get(cafe_id, CAFE_POLICIES["loveshake1"])
    cafe_pubs = [a for a in published_articles if a.get("cafeId") == cafe_id]
    total_count = len(cafe_pubs)
    no_link_count = len([a for a in cafe_pubs if a.get("postType") == "no_link_value" or not a.get("hasExternalLink", True)])
    bridge_count = total_count - no_link_count

    if policy["policyMode"] == "direct_bridge":
        return {
            "cafeId": cafe_id,
            "tier": policy["tier"],
            "policyMode": "direct_bridge",
            "nextPostMode": "direct_bridge",
            "nextPostModeBadge": "🔗 100% 원문 링크 카드 송출",
            "noLinkStreak": no_link_count,
            "requiredNoLinkStreak": 0,
            "remainingNoLinkNeeded": 0,
            "bridgeUnlocked": True,
            "totalCount": total_count,
            "noLinkCount": no_link_count,
            "bridgeCount": bridge_count,
            "safetyStatus": "🟢 브릿지 특화 카페 (상시 링크 허용)",
            "ratioLabel": policy["ratioLabel"],
            "defenseRule": policy["defenseRule"],
        }

    # For Tier 2 (`safe_community_3to1`), count consecutive `no_link_value` posts from newest to oldest
    streak = 0
    for art in cafe_pubs:
        is_no_link = art.get("postType") == "no_link_value" or not art.get("hasExternalLink", True)
        if is_no_link:
            streak += 1
        else:
            break

    req_streak = int(policy.get("requiredNoLinkStreak", 3))
    remaining = max(0, req_streak - streak)
    unlocked = remaining == 0

    return {
        "cafeId": cafe_id,
        "tier": policy["tier"],
        "policyMode": "safe_community_3to1",
        "nextPostMode": "soft_bridge" if unlocked else "no_link_value",
        "nextPostModeBadge": (
            "💡 소프트 브릿지 해금 (3:1 충족)"
            if unlocked
            else f"🛡️ 무링크 순수정보 강제 (위장 {streak}/{req_streak}단계 · 링크 자동 차단)"
        ),
        "noLinkStreak": streak,
        "requiredNoLinkStreak": req_streak,
        "remainingNoLinkNeeded": remaining,
        "bridgeUnlocked": unlocked,
        "totalCount": total_count,
        "noLinkCount": no_link_count,
        "bridgeCount": bridge_count,
        "safetyStatus": (
            "🟢 3:1 위장 조건 충족 (다음 1회 소프트 브릿지 가능)"
            if unlocked
            else f"🛡️ 강퇴 방어 위장 가동 중 (앞으로 {remaining}편 연속 무링크 순수정보글 자동 작성)"
        ),
        "ratioLabel": policy["ratioLabel"],
        "defenseRule": policy["defenseRule"],
    }


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
    CAFE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAFE_PUBLIC_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(data, ensure_ascii=False, indent=2)
    CAFE_STATUS_PATH.write_text(txt, encoding="utf-8")
    CAFE_PUBLIC_JSON_PATH.write_text(txt, encoding="utf-8")
    return data


def sync_cafe_live_state() -> dict[str, Any]:
    """Build and sync the dedicated Naver Cafe 30,217-member control room state with Tier 1 / Tier 2 Anti-Ban Guardrails."""
    from brunch_posting.posting import BRUNCHBOOK_CURRICULUM, load_brunch_status

    prev = load_cafe_status()
    published_articles: list[dict[str, Any]] = list(prev.get("publishedArticles") or DEFAULT_CAFE_PUBLISHED_ARTICLES)
    # Ensure default postType fields exist on legacy entries
    for a in published_articles:
        if "postType" not in a:
            a["postType"] = "direct_bridge"
            a["hasExternalLink"] = True
            a["postTypeBadge"] = (
                "🔗 Tier 1 다이렉트 브릿지"
                if a.get("cafeId") == "boutiqueinfo"
                else "🔗 브릿지 발행 (이후 3편 무링크 잠금)"
            )

    seen_urls = {a.get("articleUrl") for a in published_articles if a.get("articleUrl")}

    br_st = load_brunch_status()
    for h in reversed((br_st.get("automation") or {}).get("history") or []):
        for cb in (h.get("cafeBridges") or []):
            u = cb.get("url")
            if u and u not in seen_urls:
                seen_urls.add(u)
                c_slug = cb.get("cafe", "loveshake1")
                published_articles.insert(0, {
                    "id": f"{c_slug}-{len(published_articles) + 1}",
                    "part": h.get("part", 6),
                    "cafeId": c_slug,
                    "cafeName": "[금융꿀팁] 직장인/주부/서민/아파트론/대환/저금리" if c_slug == "loveshake1" else "고급지식의 모든 것",
                    "boardName": "자유게시판·금융꿀팁 (menuId 164)" if c_slug == "loveshake1" else "지식 아카이브 (menuId 4)",
                    "members": 28495 if c_slug == "loveshake1" else 1722,
                    "account": "soul5373",
                    "postType": cb.get("postType", "direct_bridge"),
                    "postTypeBadge": "🛡️ 무링크 순수정보 (위장)" if cb.get("postType") == "no_link_value" else "🔗 다이렉트 브릿지",
                    "hasExternalLink": cb.get("postType") != "no_link_value",
                    "title": f"[핵심정리] {h.get('title', '')}",
                    "articleUrl": u,
                    "bridgeDomain": (h.get("bridgeUrl") or "https://www.meganote.kr").split("/")[2].replace("www.", ""),
                    "bridgeUrl": h.get("bridgeUrl") or "https://www.meganote.kr/",
                    "publishedAt": str(h.get("at") or now_kst_str())[:16].replace("T", " ") + " KST",
                    "status": "published_verified",
                    "statusLabel": "🟢 실측 발행 영수증 검증 완료",
                })

    dekilab_quota = evaluate_cafe_safety_quota("dekilab", published_articles)
    loveshake_quota = evaluate_cafe_safety_quota("loveshake1", published_articles)
    boutique_quota = evaluate_cafe_safety_quota("boutiqueinfo", published_articles)

    cafes = [
        {
            "cafeId": "boutiqueinfo",
            "clubId": "31608088",
            "menuId": "4",
            "name": "고급지식의 모든 것 (Tier 1 브릿지 본진)",
            "shortName": "고급지식의 모든 것",
            "tier": boutique_quota["tier"],
            "policyMode": boutique_quota["policyMode"],
            "ratioLabel": boutique_quota["ratioLabel"],
            "defenseRule": boutique_quota["defenseRule"],
            "nextPostMode": boutique_quota["nextPostMode"],
            "nextPostModeBadge": boutique_quota["nextPostModeBadge"],
            "safetyStatus": boutique_quota["safetyStatus"],
            "noLinkStreak": boutique_quota["noLinkStreak"],
            "requiredNoLinkStreak": boutique_quota["requiredNoLinkStreak"],
            "grade": "가지3단계 (운영자 브릿지 허용 특화 카페)",
            "members": 1739,
            "account": "soul5373 · yoon_master · soultin (3계정 모두 글쓰기 활성)",
            "cafeUrl": "https://cafe.naver.com/boutiqueinfo",
            "writeMode": "🔗 Tier 1 브릿지 특화 (FEEditor + 클립보드 원문 링크카드 100% 직결)",
            "targetTopics": "주택연금 · 대환대출 · 건보료 · 소상공인 지원금 · 절세 · 복지할인 전 분야",
            "publishedCount": boutique_quota["totalCount"],
            "noLinkCount": boutique_quota["noLinkCount"],
            "bridgeCount": boutique_quota["bridgeCount"],
            "latestArticleUrl": next((a["articleUrl"] for a in published_articles if a.get("cafeId") == "boutiqueinfo"), "https://cafe.naver.com/boutiqueinfo/2305"),
            "status": "live",
            "statusBadge": "🔗 Tier 1 · 100% 브릿지 특화 가동 중",
        },
        {
            "cafeId": "dekilab",
            "clubId": "31529204",
            "menuId": "18",
            "name": "AI 커뮤니티 - 데키랩 (Tier 2 · 12,503명 활성 카페)",
            "shortName": "데키랩 (AI 커뮤니티)",
            "tier": dekilab_quota["tier"],
            "policyMode": dekilab_quota["policyMode"],
            "ratioLabel": dekilab_quota["ratioLabel"],
            "defenseRule": dekilab_quota["defenseRule"],
            "nextPostMode": dekilab_quota["nextPostMode"],
            "nextPostModeBadge": dekilab_quota["nextPostModeBadge"],
            "safetyStatus": dekilab_quota["safetyStatus"],
            "noLinkStreak": dekilab_quota["noLinkStreak"],
            "requiredNoLinkStreak": dekilab_quota["requiredNoLinkStreak"],
            "grade": "열매단계 (12,503명 · yoon_master 글쓰기 권한 확인 완료)",
            "members": 12503,
            "account": "yoon_master (Profile 5 · barolab-yoon_master)",
            "cafeUrl": "https://cafe.naver.com/dekilab",
            "writeMode": "🛡️ 3:1 강퇴방어 엔진 (첫 3편 무링크 순수 AI/정보글 워밍업 후 4번째 글 소프트 브릿지)",
            "targetTopics": "AI 에이전트 자동화 · 바이브코딩 · 프롬프트 & 실전 워크플로우 · IT 생산성",
            "publishedCount": dekilab_quota["totalCount"],
            "noLinkCount": dekilab_quota["noLinkCount"],
            "bridgeCount": dekilab_quota["bridgeCount"],
            "latestArticleUrl": next((a["articleUrl"] for a in published_articles if a.get("cafeId") == "dekilab"), "https://cafe.naver.com/dekilab"),
            "status": "live",
            "statusBadge": "🛡️ Tier 2 · 무링크 3편 선행 워밍업 잠금 중",
        },
    ]

    # Build 10-part Planned Queue with simulated 3:1 progression on `dekilab` (Tier 2) + `boutiqueinfo` (Tier 1)
    planned_queue: list[dict[str, Any]] = []
    sim_streak = dekilab_quota["noLinkStreak"]
    req_streak = dekilab_quota["requiredNoLinkStreak"]

    for cur in BRUNCHBOOK_CURRICULUM:
        part_no = int(cur["part"])
        matching_pubs = [a for a in published_articles if int(a.get("part") or 0) == part_no or cur["title"][:8] in str(a.get("title") or "")]
        dekilab_pub = next((a for a in matching_pubs if a.get("cafeId") == "dekilab"), None)
        loveshake_pub = next((a for a in matching_pubs if a.get("cafeId") == "loveshake1"), None)
        boutique_pub = next((a for a in matching_pubs if a.get("cafeId") == "boutiqueinfo"), None)

        if dekilab_pub:
            tier2_plan_mode = dekilab_pub.get("postType", "no_link_value")
            tier2_plan_label = (
                "🟢 데키랩 무링크 순수정보 완료"
                if tier2_plan_mode == "no_link_value"
                else "🟢 데키랩 소프트 브릿지 완료"
            )
            tier2_url = dekilab_pub["articleUrl"]
        elif loveshake_pub:
            tier2_plan_mode = "archived_loveshake"
            tier2_plan_label = "📦 구 금융꿀팁 발행분 (데키랩 3:1 대기)"
            tier2_url = loveshake_pub["articleUrl"]
        else:
            if sim_streak < req_streak:
                sim_streak += 1
                tier2_plan_mode = "no_link_value"
                tier2_plan_label = f"🛡️ 데키랩 무링크 워밍업 ({sim_streak}/{req_streak})"
            else:
                sim_streak = 0
                tier2_plan_mode = "soft_bridge"
                tier2_plan_label = "💡 데키랩 소프트 브릿지 해금 (3:1)"
            tier2_url = ""

        if dekilab_pub and boutique_pub:
            q_status = "completed_both"
            q_label = "🟢 2개 카페 모두 발행 완료"
        elif boutique_pub:
            q_status = "completed_partial"
            q_label = "🟡 고급지식 완료 · 데키랩 무링크 워밍업 대기"
        else:
            q_status = "queued"
            q_label = (
                "🛡️ 데키랩(무링크 워밍업) + 🔗 고급지식(브릿지)"
                if tier2_plan_mode == "no_link_value"
                else "💡 데키랩(3:1 브릿지 해금) + 🔗 고급지식(브릿지)"
            )

        planned_queue.append({
            "part": part_no,
            "title": (
                f"[정보공유] {cur['title']}"
                if tier2_plan_mode == "no_link_value" and not dekilab_pub
                else f"[핵심정리] {cur['title']}"
            ),
            "subtitle": cur["subtitle"],
            "category": cur["category"],
            "targetCafes": "데키랩(Tier 2 · 3:1 무링크 워밍업) + 고급지식(Tier 1 · 100% 브릿지)",
            "bridgeDomain": cur["targetDomain"],
            "bridgeUrl": cur.get("bridgeUrl") or f"https://www.{cur['targetDomain']}/",
            "loveshakeUrl": tier2_url,
            "loveshakePlanMode": tier2_plan_mode,
            "loveshakePlanLabel": tier2_plan_label,
            "boutiqueUrl": boutique_pub["articleUrl"] if boutique_pub else "",
            "boutiquePlanLabel": "🟢 브릿지 발행 완료" if boutique_pub else "🔗 100% 원문 브릿지 예정",
            "status": q_status,
            "statusLabel": q_label,
        })

    cafe_ga4 = _extract_ga4_channel_referrals(["cafe.naver", "m.cafe.naver", "naver_cafe"])
    naver_all_ga4 = _extract_ga4_channel_referrals(["naver"])

    measurement = {
        "totalMembersReach": 14242,
        "publishedTotalCount": len(published_articles),
        "completedQueueCount": len([q for q in planned_queue if q["status"] != "queued"]),
        "pendingQueueCount": len([q for q in planned_queue if q["status"] == "queued"]),
        "cafeDirectReferrals": cafe_ga4,
        "naverEcosystemReferrals": naver_all_ga4,
        "cafeBreakdown": [
            {
                "cafeName": "고급지식의 모든 것 (boutiqueinfo · Tier 1 브릿지 특화카페)",
                "members": 1739,
                "publishedCount": boutique_quota["totalCount"],
                "targetDomains": "100% 다이렉트 브릿지 (meganote.kr · smilenote.kr · healthcox.com)",
                "latestReceipt": next((a["articleUrl"] for a in published_articles if a.get("cafeId") == "boutiqueinfo"), ""),
                "expectedEffect": "운영자 공인 브릿지 기지 · 3계정(soul5373·yoon_master·soultin) 동시 가동으로 카페탭 상위노출 및 원문 직결",
            },
            {
                "cafeName": "AI 커뮤니티 - 데키랩 (dekilab · Tier 2 일반 커뮤니티)",
                "members": 12503,
                "publishedCount": dekilab_quota["totalCount"],
                "targetDomains": "3:1 법칙 (무링크 순수정보 3편 선행 워밍업 → 4번째 글 소프트 브릿지 1회)",
                "latestReceipt": next((a["articleUrl"] for a in published_articles if a.get("cafeId") == "dekilab"), "https://cafe.naver.com/dekilab"),
                "expectedEffect": "금융꿀팁 초기 링크 강퇴 교훈 반영 · 첫 3편 100% 무링크 정보글로 진성 활동 이력 확보 후 안전 유입",
            },
            {
                "cafeName": "[금융꿀팁] 러브쉐이크 (loveshake1 · 🔴 강퇴 격리/송출 중단)",
                "members": 28495,
                "publishedCount": loveshake_quota["totalCount"],
                "targetDomains": "⛔ 송출 영구 차단 (가입 직후 첫 글부터 외부링크 삽입으로 인한 탈퇴 조치)",
                "latestReceipt": next((a["articleUrl"] for a in published_articles if a.get("cafeId") == "loveshake1"), ""),
                "expectedEffect": "교훈 아카이브: 일반 커뮤니티 카페는 가입 직후 외부링크 작성 시 즉시 강퇴됨 → 전 일반 카페 3편 무링크 선행 워밍업 의무화",
            },
        ],
    }

    payload = {
        "ok": True,
        "updatedAt": now_kst_str(),
        "account": {
            "naverId": "soul5373 + yoon_master",
            "egoProfile": "Profile 4 (soul5373) & Profile 5 (yoon_master)",
            "cdpPort": 9440,
            "autoReclaimEnabled": True,
            "operatingRule": "금융꿀팁 초기 링크 강퇴 교훈 반영: Tier 1(고급지식 1,739명)은 100% 브릿지 송출 · Tier 2(데키랩 12,503명 및 신규 카페)는 『무링크 순수정보 3편 선행 워밍업 + 3:1 법칙』을 코드 레벨에서 강제 잠금",
        },
        "antiBanStrategy": {
            "tier1Rule": "Tier 1 (브릿지 특화 카페 · 고급지식의 모든 것 1,739명): 운영자 브릿지 허용 카페 → soul5373·yoon_master·soultin 3계정 100% 원문 링크 직결",
            "tier2Rule": "Tier 2 (일반 커뮤니티 카페 · 데키랩 12,503명 & 신규 카페): 첫 3편 연속 '외부링크 0개 순수 정보글' 달성 전에는 코드에서 URL 삽입 원천 차단 (4번째 글에만 소프트 브릿지 1회 해금)",
            "warmupRule": "🔴 금융꿀팁(loveshake1) 강퇴 사후조치 완료: loveshake1 송출 루프 즉시 격리 차단 + 모든 일반 카페는 가입 직후 첫 3편 무링크 워밍업 100% 강제",
            "dekilabQuota": dekilab_quota,
            "boutiqueQuota": boutique_quota,
            "loveshakeQuota": loveshake_quota,
        },
        "kpi": {
            "cafeCount": 2,
            "totalMembers": 14242,
            "publishedArticleCount": len(published_articles),
            "pendingQueueCount": measurement["pendingQueueCount"],
            "cafeGa4Sessions7d": cafe_ga4["weekSessions"],
            "cafeGa4Sessions30d": cafe_ga4["monthSessions"],
            "cafeGa4Sessions28d": cafe_ga4["last28DaysSessions"],
            "naverTotalSessions7d": naver_all_ga4["weekSessions"],
            "naverTotalSessions30d": naver_all_ga4["monthSessions"],
            "naverTotalSessions28d": naver_all_ga4["last28DaysSessions"],
            "ga4WindowNote": "GA4 month period covers 30 days (week=7d, month=30d)",
            "dekilabNextMode": dekilab_quota["nextPostModeBadge"],
        },
        "cafes": cafes,
        "publishedArticles": published_articles,
        "plannedQueue": planned_queue,
        "measurement": measurement,
    }
    return save_cafe_status(payload)


def _build_cafe_post_payload(
    cafe_slug: str,
    target_item: dict[str, Any],
    bridge_url: str,
    quota: dict[str, Any],
) -> dict[str, Any]:
    """Construct the exact title & paragraphs according to the cafe's Tier and current 3:1 safety quota."""
    post_mode = quota["nextPostMode"]
    raw_paras = [str(p).strip() for p in (target_item.get("paragraphs") or []) if str(p).strip()]

    if post_mode == "no_link_value":
        # Tier 2 Anti-Ban Camouflage Mode: ZERO external links, 100% pure community value post
        clean_title = f"[정보공유] {target_item['title']} 핵심 기준 정리해 봤습니다"
        paras = [
            f"안녕하세요, 요즘 {target_item['title']} 관련해서 헷갈리는 기준들이 많길래 제가 직접 확인하면서 정리해 둔 핵심 체크포인트를 회원님들과 공유해 봅니다.",
            *raw_paras[:5],
            f"✔ 핵심 요약: {target_item['subtitle']}",
            "신청 시기나 세부 요건을 놓치면 불이익이 생길 수 있으니 해당되시는 분들은 미리 조건을 대조해 보시는 걸 추천드립니다. 혹시 올해 직접 신청해 보셨거나 궁금한 점 있으신 분들은 댓글로 함께 이야기 나눠요!",
        ]
        return {
            "postType": "no_link_value",
            "postTypeBadge": f"🛡️ 무링크 순수정보 (위장 {quota['noLinkStreak'] + 1}/{quota['requiredNoLinkStreak']})",
            "hasExternalLink": False,
            "title": clean_title,
            "paragraphs": paras,
            "recordedBridgeDomain": "무링크 순수기여 (강퇴방어 위장)",
            "recordedBridgeUrl": f"https://cafe.naver.com/{cafe_slug}",
        }

    if post_mode == "soft_bridge":
        # Tier 2 Unlocked Soft Bridge Mode (only 1 out of 4 posts)
        soft_title = f"[핵심정리] {target_item['title']} ({target_item['subtitle'][:22]})"
        paras = [
            *raw_paras[:4],
            f"▶ 구간별 상세 비교표 및 계산 기준 참고 출처:",
            bridge_url,
        ]
        return {
            "postType": "soft_bridge",
            "postTypeBadge": "💡 Tier 2 소프트 브릿지 (3:1 해금)",
            "hasExternalLink": True,
            "title": soft_title,
            "paragraphs": paras,
            "recordedBridgeDomain": target_item["targetDomain"],
            "recordedBridgeUrl": bridge_url,
        }

    # Tier 1 Direct Bridge Mode (`boutiqueinfo`)
    direct_title = f"[핵심정리] {target_item['title']} ({target_item['subtitle'][:22]})"
    paras = [
        *raw_paras[:4],
        f"▶ {target_item['title']} 상세 비교표 및 자가진단 원문 보기:",
        bridge_url,
    ]
    return {
        "postType": "direct_bridge",
        "postTypeBadge": "🔗 Tier 1 다이렉트 브릿지",
        "hasExternalLink": True,
        "title": direct_title,
        "paragraphs": paras,
        "recordedBridgeDomain": target_item["targetDomain"],
        "recordedBridgeUrl": bridge_url,
    }


def publish_cafe_bridge_part(part_no: int = 6) -> dict[str, Any]:
    """Publish a specific curriculum part (1~10) to both Naver Cafes enforcing Tier 1 (Direct Bridge) & Tier 2 (3:1 No-Link Anti-Ban)."""
    from brunch_posting.posting import BRUNCHBOOK_CURRICULUM, get_today_cf_bridge_targets
    from dashboard.common.ego_taskspace import native_publish_naver_cafe_article

    target_item = next((c for c in BRUNCHBOOK_CURRICULUM if int(c["part"]) == int(part_no)), BRUNCHBOOK_CURRICULUM[0])
    bridge_targets = get_today_cf_bridge_targets(target_item["title"], allowed_domains=[target_item["targetDomain"]])
    bridge_url = target_item.get("bridgeUrl") or (bridge_targets[0]["url"] if bridge_targets else f"https://www.{target_item['targetDomain']}/")

    st = sync_cafe_live_state()
    published_articles = list(st.get("publishedArticles") or [])
    receipts = []

    for cafe_cfg in [
        {"slug": "boutiqueinfo", "account": "soul5373", "clubid": "31608088", "menuid": "4", "name": "고급지식의 모든 것", "board": "지식 아카이브 (menuId 4)", "members": 1739},
        {"slug": "dekilab", "account": "yoon_master", "clubid": "31529204", "menuid": "18", "name": "AI 커뮤니티 - 데키랩", "board": "AI 정보 & 팁 공유 (menuId 18)", "members": 12503},
    ]:
        already = next((a for a in published_articles if a.get("cafeId") == cafe_cfg["slug"] and int(a.get("part") or 0) == int(target_item["part"])), None)
        if already:
            receipts.append({
                "cafe": cafe_cfg["slug"],
                "url": already["articleUrl"],
                "postType": already.get("postType", "direct_bridge"),
                "reused": True,
            })
            continue

        quota = evaluate_cafe_safety_quota(cafe_cfg["slug"], published_articles)
        post_spec = _build_cafe_post_payload(cafe_cfg["slug"], target_item, bridge_url, quota)

        c_res = native_publish_naver_cafe_article(
            account=cafe_cfg["account"],
            clubid=cafe_cfg["clubid"],
            menuid=cafe_cfg["menuid"],
            title=post_spec["title"],
            paragraphs=post_spec["paragraphs"],
            cafe_slug=cafe_cfg["slug"],
        )
        if isinstance(c_res, dict) and c_res.get("ok") and c_res.get("url"):
            art_url = str(c_res["url"])
            receipts.append({
                "ok": True,
                "cafe": cafe_cfg["slug"],
                "cafeSlug": cafe_cfg["slug"],
                "url": art_url,
                "postType": post_spec["postType"],
                "postTypeBadge": post_spec["postTypeBadge"],
            })
            published_articles.insert(0, {
                "id": f"{cafe_cfg['slug']}-{art_url.rstrip('/').split('/')[-1]}",
                "part": int(target_item["part"]),
                "cafeId": cafe_cfg["slug"],
                "cafeName": cafe_cfg["name"],
                "boardName": cafe_cfg["board"],
                "members": cafe_cfg["members"],
                "account": cafe_cfg["account"],
                "postType": post_spec["postType"],
                "postTypeBadge": post_spec["postTypeBadge"],
                "hasExternalLink": post_spec["hasExternalLink"],
                "title": post_spec["title"],
                "articleUrl": art_url,
                "bridgeDomain": post_spec["recordedBridgeDomain"],
                "bridgeUrl": post_spec["recordedBridgeUrl"],
                "publishedAt": now_kst_str()[:16] + " KST",
                "status": "published_verified",
                "statusLabel": f"🟢 실측 발행 영수증 검증 완료 (#{art_url.rstrip('/').split('/')[-1]})",
            })

    st["publishedArticles"] = published_articles
    save_cafe_status(st)
    final_st = sync_cafe_live_state()
    return {
        "ok": len(receipts) > 0,
        "part": int(target_item["part"]),
        "title": target_item["title"],
        "receipts": receipts,
        "status": final_st,
    }


def process_cafe_autonomy_once() -> dict[str, Any]:
    """24/7 Autonomous Naver Cafe Bridge Scheduler (09:40 & 16:40 KST, up to 2 parts/day across boutiqueinfo + dekilab)."""
    now_dt = datetime.now(KST)
    today_prefix = now_dt.date().isoformat()
    st = load_cafe_status()
    published_articles = list(st.get("publishedArticles") or [])
    today_articles = [a for a in published_articles if str(a.get("publishedAt") or "").startswith(today_prefix)]
    if len(today_articles) >= 4:
        return {"ok": True, "action": "daily_quota_complete", "todayCount": len(today_articles)}

    target_minutes = 9 * 60 + 40 if len(today_articles) == 0 else 16 * 60 + 40
    cur_minutes = now_dt.hour * 60 + now_dt.minute
    if cur_minutes < target_minutes:
        return {"ok": True, "action": "waiting_for_slot", "nextSlot": "09:40" if len(today_articles) == 0 else "16:40"}

    # Find next part not yet published on both boutiqueinfo and dekilab
    for part_no in range(1, 11):
        has_b = any(a.get("cafeId") == "boutiqueinfo" and int(a.get("part") or 0) == part_no for a in published_articles)
        has_d = any(a.get("cafeId") == "dekilab" and int(a.get("part") or 0) == part_no for a in published_articles)
        if not (has_b and has_d):
            return publish_cafe_bridge_part(part_no)
    return {"ok": True, "action": "all_parts_published"}


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    out = sync_cafe_live_state()
    print(json.dumps({"ok": out.get("ok"), "kpi": out.get("kpi"), "antiBanStrategy": out.get("antiBanStrategy")}, ensure_ascii=False, indent=2))
