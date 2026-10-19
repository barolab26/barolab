# -*- coding: utf-8 -*-
"""
16 Cloudflare (CF) Blog 8-Architecture Independent DOM Skeleton Engine (`cf_posting/domain_themes.py`).

Implements 8 Completely Distinct HTML/CSS DOM Layout Architectures (with 16 per-domain variations)
so that every site has a genuinely unique DOM footprint (Header, 1/2/3-Column Grid, Sidebar placement,
Top Byline/Profile/Scoreboard/Quick-Info/Fact-Check Widgets, H2 Point/Timeline/Step/Block-Card splitting,
Bottom FAQ Accordion / Tech Feedback / 3-Col Magazine Grid, 5 High-CPC AdSense Slots, and Specialized Footers)
while hiding 100% of legacy duplicate headers and exposed admin UI.

8 Independent Layout Architectures (`shellFamily`):
1. `arch1-wikitree` (`daynote.kr`, `must-good.com`):
   - Wikitree (`wikitree.co.kr`) Social News & Breaking Media Portal
   - `daynote.kr`: White header + Sans Bold logo + Left Floating Share (60px) + Center News (700px) + Right TOP 10 Ranking Sidebar (300px)
   - `must-good.com`: Dark Navy header + Heavy Serif logo + Left TOP 10 Ranking Sidebar (300px) + Center News (700px) + Right Floating Share (60px)
2. `arch2-albup` (`woorinote.kr`, `justinfo.co.kr`):
   - Albup (`albup.co.kr`) Lawyer / Tax Accountant / Expert Column & Q&A Advisory
   - `woorinote.kr`: Deep Blue legal/real-estate column + Horizontal Navy Advisory Profile Card
   - `justinfo.co.kr`: Burgundy/Charcoal finance/tax column + Double-Bordered Partner Certificate Profile Box
3. `arch3-toss` (`meganote.kr`, `smilenote.kr`):
   - Toss Feed / Fintech Left Sticky Scrollspy TOC (220px) + Split Independent White H2 Block Cards (`border-radius: 20px`) on `#f2f4f6` canvas + Floating Pill Glass Header
4. `arch4-mslearn` (`topnote.kr`, `maxnote.kr`):
   - MS Learn / Apple Docs 3-Column Technical Manual & Wiki (`Left Folder Tree + Center Step Manual with <kbd> keycaps + Right On-This-Page Minimap`) + Slate Dark Ctrl+K Header + Bottom `[👍 도움됨] [👎 추가 설명 필요]` Feedback Box
5. `arch5-lonelyplanet` (`tripmarvel.com`, `nolplace.com`):
   - Lonely Planet / Brunch Magazine Full-Wide Cover Overlay Hero (Serif Large Title) + Top 3-Col `Quick Info Grid` (`📍 핵심 포인트 | 🕒 소요시간/시기 | 🚗 주차·이동 팁`) + Vertical Dotted Timeline (`Course 1 ➔ Course 2`)
6. `arch6-webmd` (`healthcox.com`):
   - Asan Medical Center / WebMD Medical Journal & Symptom Checksheet + Teal/Mint Cross Header + Fixed Fact-Check Banner (`🩺 건강정보 에디토리얼 가이드라인 검수 완료 · 의학적 진단을 대신하지 않습니다`) + Clinical Chart Tables + Right Health Column Sidebar
7. `arch7-danawa` (`must-pick.com`, `baronote.kr`):
   - Danawa DPG / Consumer Reports 2-Tier Review Portal Header + Top Consumer Reports Scoreboard (`[추천지수 ★★★★★ | 핵심 혜택 요약 | 신청 난이도: 쉬움]`) + Pros/Cons Contrast Box + Zebra Spec Comparison Table
8. `arch8-todayhouse` (`must-joy.com`, `soulnote.kr`, `joynote.kr`):
   - Todayhouse / 29CM Lifestyle & Pet Curation Magazine + Top Color Ribbon Banner (`오늘의 에디터 추천 라이프 가이드`) + Rounded Pill Icon Category Bar + Speech-Bubble Editor Note + Cute H2 Icon Badges + Bottom 3-Column Magazine Photo Card Grid
"""

from __future__ import annotations

import csv
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
THEMES_DIR = BASE_DIR / "themes"
CARD_CSS = (THEMES_DIR / "tripmarvel.com.css").read_text(encoding="utf-8")
CARD_CSS = CARD_CSS[CARD_CSS.index("/* BAROLAB_VERTICAL_CARDS_V3: home and category lists only. */"):].strip()
SKILLS_UI_UX_DIR = BASE_DIR.parent / "skills" / "ui-ux-pro-max"
DESIGN_SYSTEM_DIR = BASE_DIR / "design-system"


def load_ui_ux_pro_max_reference() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "skillRoot": str(SKILLS_UI_UX_DIR),
        "skillExists": (SKILLS_UI_UX_DIR / "SKILL.md").is_file(),
        "stylesCount": 67,
        "persistedDesignSystems": [],
    }
    styles_csv = SKILLS_UI_UX_DIR / "data" / "styles.csv"
    if styles_csv.is_file():
        try:
            with styles_csv.open("r", encoding="utf-8", errors="replace") as f:
                info["stylesCount"] = len(list(csv.DictReader(f)))
        except Exception:
            pass
    return info


DOMAIN_IDENTITY_SPECS: Dict[str, Dict[str, Any]] = {
    # =========================================================================
    # ARCHITECTURE 1: 위키트리(wikitree.co.kr) 스타일 — 소셜 뉴스·속보 미디어 포털형
    # daynote.kr (화이트 헤더 / 고딕 워드마크 / 우측 랭킹 보드)
    # must-good.com (다크네이비 헤더 / 명조 워드마크 / 좌측 랭킹 보드)
    # =========================================================================
    "daynote.kr": {
        "id": 13,
        "domain": "daynote.kr",
        "workerName": "daynote",
        "name": "데이노트 뉴스",
        "slogan": "생활·경제·트렌드 실시간 소셜 뉴스 포털",
        "category": "생활·살림속보",
        "categories": ["생활·살림속보", "물가·절약이슈", "주방·리빙기획", "트렌드팩트체크"],
        "subTopic": "생활·살림속보·물가·절약이슈·주방·리빙기획·트렌드팩트체크",
        "targetAudience": "실생활 꿀팁, 장바구니 물가·절약 속보 및 트렌드 기획기사를 찾는 뉴스 독자",
        "shellFamily": "arch1-wikitree",
        "shellVariant": "wikitree-white-right",
        "archetype": "arch1-wikitree",
        "archetypeLabel": "[아키텍처 1] 위키트리형 소셜 뉴스 포털 (화이트 신문사 헤더 + 좌측 플로팅 공유바 60px + 중앙 기사 700px + 우측 실시간 TOP 10 랭킹 300px)",
        "headerAlign": "wikitree-white-header",
        "catTabStyle": "news-2tier-bar",
        "cardVariant": "news-list-right-rank",
        "thumbRatio": "16/10",
        "editorName": "박현우 라이프데스크",
        "pressRegNo": "서울 아54813",
        "publisherName": "김정훈",
        "youthOfficer": "이서연",
        "headlines": [
            "[속보] 장바구니 생활물가 절약 핵심 수칙… 주부 90%가 놓치는 보관·관리법 공개",
            "[이슈기획] 전기·수도·가스 공과금 아끼는 계절별 살림 체크리스트 집중 분석",
            "[화제] \"한 달 내내 싱싱하게\" 식재료 무름 방지 냉장·냉동 황금 공식",
        ],
        "top10Articles": [
            "식재료 신선도 3배 늘리는 냉장·냉동 소분 보관 핵심 공식",
            "세탁기 쉰내·배수구 악취 단번에 잡는 과탄산소다 활용법",
            "매달 빠져나가는 공과금·관리비 즉시 환급·할인받는 체크리스트",
            "욕실 물때·창틀 묵은 먼지 10분 만에 끝내는 호텔식 청소 루틴",
            "제철 채소·과일 무르지 않게 고르는 법과 1주일 식단 구성",
            "에어프라이어·전자레인지 기름때 손쉽게 제거하는 천연 세제 조합",
            "옷장 곰팡이·습기 완벽 차단하는 계절별 의류 수납 가이드",
            "주방 싱크대 수전 광택 살리는 치약·구연산 3단계 코팅 팁",
            "냉동실 성에 방지 및 전기요금 아끼는 적정 용량 배치 요령",
            "배달 용기·플라스틱 김치 국물 색배임 지우는 햇빛·베이킹소다 비법",
        ],
        "colors": {
            "primary": "#E11D48",
            "secondary": "#1E293B",
            "accent": "#2563EB",
            "background": "#F8FAFC",
            "surface": "#FFFFFF",
            "text": "#0F172A",
            "muted": "#475569",
            "border": "#E2E8F0",
            "tableHeaderBg": "#FFF1F2",
            "tableHeaderTxt": "#9F1239",
        },
        "typography": {
            "headingFont": "'Pretendard Variable', 'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "700px",
            "lineHeight": "1.84",
        },
        "cardStyle": {
            "radius": "8px",
            "shadow": "0 2px 10px rgba(15, 23, 42, 0.05)",
            "border": "1px solid #E2E8F0",
            "headerBorder": "2px solid #0F172A",
            "h2BorderLeft": "5px solid #E11D48",
            "h2Bg": "#FFF1F2",
            "h2Padding": "10px 16px",
        },
        "ctaText": "관련 생활·정책 공식 안내 원문 및 신청 기준 확인 →",
        "badgeLabel": "DAYNOTE BREAKING NEWS · 실시간 라이프·경제 소셜 뉴스",
    },
    "must-good.com": {
        "id": 1,
        "domain": "must-good.com",
        "workerName": "mustgood",
        "name": "머스트굿 정책뉴스",
        "slogan": "정부지원금·복지·민원·세제 특종 미디어",
        "category": "정부지원금속보",
        "categories": ["정부지원금속보", "청년·장년복지", "민원·행정기획", "세금·환급이슈"],
        "subTopic": "정부지원금·청년·장년복지·민원·서류발급·세금·환급",
        "targetAudience": "정부 보조금·복지 혜택·민원 서류 및 세금 환급 속보를 확인하려는 독자",
        "shellFamily": "arch1-wikitree",
        "shellVariant": "wikitree-navy-left",
        "archetype": "arch1-wikitree",
        "archetypeLabel": "[아키텍처 1] 위키트리형 정책 뉴스 포털 (다크네이비 명조 헤더 + 좌측 실시간 TOP 10 랭킹 300px + 중앙 기사 700px + 우측 플로팅 공유바 60px)",
        "headerAlign": "wikitree-navy-header",
        "catTabStyle": "news-2tier-navy",
        "cardVariant": "news-list-left-rank",
        "thumbRatio": "16/10",
        "editorName": "정민석 정책에디터",
        "pressRegNo": "서울 아54801",
        "publisherName": "한상우",
        "youthOfficer": "최윤정",
        "headlines": [
            "[정책속보] 2026 정부지원금·민생 바우처 신청 대상 확대… 미신청 시 소멸 주의",
            "[단독기획] 정부24·복지로 온라인 민원 증명서 수수료 0원 즉시 발급 가이드",
            "[세제브리핑] 국세청·건보공단 미수령 환급금 통합 조회 및 계좌 입금 일정",
        ],
        "top10Articles": [
            "2026년 정부24·복지로 맞춤형 보조금 자격 조회 및 신청 절차 총정리",
            "건강보험료 본인부담상한제 환급금 조회 및 온라인 지급 신청 방법",
            "주민등록등본·가족관계증명서 인터넷 무료 발급 및 PDF 저장 팁",
            "청년·중장년 구직촉진수당 및 국민취업지원제도 1·2유형 자격 비교",
            "국세청 홈택스 종합소득세·근로장려금 기한 후 신청 및 수령액 계산",
            "소상공인 정책자금 대환대출 및 이자 환급 지원 대상 확인 리스트",
            "에너지바우처·도시가스 요금 경감 대상자 온라인 신청 구비서류",
            "부모급여·아동수당·첫만남이용권 중복 수급 기준 및 신청 시기",
            "기초생활수급자·차상위계층 선정 기준 중위소득 인상분 상세 분석",
            "지방세 세목별 과세증명서·납세증명서 모바일 즉시 발급 가이드",
        ],
        "colors": {
            "primary": "#0B3B8C",
            "secondary": "#0F172A",
            "accent": "#DC2626",
            "background": "#F1F5F9",
            "surface": "#FFFFFF",
            "text": "#0F172A",
            "muted": "#475569",
            "border": "#CBD5E1",
            "tableHeaderBg": "#EFF6FF",
            "tableHeaderTxt": "#0B3B8C",
        },
        "typography": {
            "headingFont": "'Noto Serif KR', 'Pretendard', Georgia, serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "'JetBrains Mono', monospace",
            "cfFontFamily": "serif",
            "fontImportUrl": "https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@700;900&display=swap",
            "readingMaxWidth": "700px",
            "lineHeight": "1.84",
        },
        "cardStyle": {
            "radius": "6px",
            "shadow": "0 3px 12px rgba(15, 23, 42, 0.06)",
            "border": "1px solid #CBD5E1",
            "headerBorder": "3px solid #DC2626",
            "h2BorderLeft": "5px solid #0B3B8C",
            "h2Bg": "#EFF6FF",
            "h2Padding": "10px 16px",
        },
        "ctaText": "정부24·복지로 공식 신청 창구 바로가기 →",
        "badgeLabel": "MUSTGOOD POLICY NEWS · 정부지원금·복지·민원 전문 인터넷신문",
    },

    # =========================================================================
    # ARCHITECTURE 2: 알법(albup.co.kr) 스타일 — 변호사·세무사·전문가 칼럼 & Q&A 상담형
    # woorinote.kr (딥블루 테마 · 법률/부동산 자문 에디터 프로필 박스)
    # justinfo.co.kr (버건디/차콜 테마 · 금융/세무 파트너 인증 프로필 박스)
    # =========================================================================
    "woorinote.kr": {
        "id": 12,
        "domain": "woorinote.kr",
        "workerName": "woorinote",
        "name": "우리노트 법률·부동산칼럼",
        "slogan": "변호사·공인중개 실무 기준 청약·전월세·등기 자문 플랫폼",
        "category": "청약·분양자문",
        "categories": ["청약·분양자문", "전월세·계약법률", "주거복지·대출", "부동산등기·세법"],
        "subTopic": "청약·분양가이드·전월세·계약체크·주거복지·대출·부동산세금",
        "targetAudience": "청약 자격, 전월세 안전 계약 특약, 등기부등본 권리분석 및 부동산 세법 자문을 찾는 독자",
        "shellFamily": "arch2-albup",
        "shellVariant": "albup-deepblue-law",
        "archetype": "arch2-albup",
        "archetypeLabel": "[아키텍처 2] 알법(albup)형 법률·부동산 전문가 칼럼 (딥블루 테마 + 브레드크럼 + 법률 자문 프로필 카드 + 핵심 3줄 요약 + POINT 01 소제목 + 하단 Q&A 아코디언)",
        "headerAlign": "albup-expert-blue",
        "catTabStyle": "expert-breadcrumb-bar",
        "cardVariant": "albup-column-card",
        "thumbRatio": "16/10",
        "expertName": "김도윤 수석 법률·부동산 리서치 에디터",
        "expertRole": "부동산 공법·임대차보호법·청약제도 실무 자문위원",
        "expertBadge": "✓ 대법원 인터넷등기소·청약홈 법령 기준 검수필",
        "colors": {
            "primary": "#1E3A8A",
            "secondary": "#2563EB",
            "accent": "#0284C7",
            "background": "#F4F7FB",
            "surface": "#FFFFFF",
            "text": "#0F172A",
            "muted": "#475569",
            "border": "#BFDBFE",
            "tableHeaderBg": "#EFF6FF",
            "tableHeaderTxt": "#1E3A8A",
        },
        "typography": {
            "headingFont": "'Noto Serif KR', Georgia, serif",
            "bodyFont": "'Pretendard', 'Noto Sans KR', sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "serif",
            "fontImportUrl": "https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700;900&display=swap",
            "readingMaxWidth": "740px",
            "lineHeight": "1.85",
        },
        "cardStyle": {
            "radius": "10px",
            "shadow": "0 4px 16px rgba(30, 58, 138, 0.07)",
            "border": "1px solid #BFDBFE",
            "headerBorder": "3px solid #1E3A8A",
            "h2BorderLeft": "4px solid #1E3A8A",
            "h2Bg": "#EFF6FF",
            "h2Padding": "12px 16px",
        },
        "ctaText": "청약홈·인터넷등기소 공식 법령 및 공고문 확인 →",
        "badgeLabel": "WOORINOTE LEGAL & ESTATE COLUMN · 법률·부동산 전문가 칼럼",
    },
    "justinfo.co.kr": {
        "id": 3,
        "domain": "justinfo.co.kr",
        "workerName": "justinfo",
        "name": "저스트인포 금융·세무칼럼",
        "slogan": "세무·노무·소비자분쟁 실전 판례 & 행정절차 전문 칼럼",
        "category": "세무·절세칼럼",
        "categories": ["세무·절세칼럼", "근로·실업급여노무", "소비자환불·분쟁", "생활법률·과태료"],
        "subTopic": "생활법률·권리·소비자피해·환불·교통·과태료·근로·실업급여",
        "targetAudience": "세무 공제·환급, 노무·실업급여 요건, 소비자 분쟁 조정 및 과태료 감경 절차를 찾는 독자",
        "shellFamily": "arch2-albup",
        "shellVariant": "albup-burgundy-tax",
        "archetype": "arch2-albup",
        "archetypeLabel": "[아키텍처 2] 알법(albup)형 금융·세무 전문가 칼럼 (버건디/차콜 테마 + 더블보더 세무 인증 프로필 박스 + 핵심 3줄 요약 + POINT 01 소제목 + 하단 Q&A 아코디언)",
        "headerAlign": "albup-expert-burgundy",
        "catTabStyle": "expert-breadcrumb-bar",
        "cardVariant": "albup-column-card",
        "thumbRatio": "16/10",
        "expertName": "이승헌 수석 금융·세무 리서치 에디터",
        "expertRole": "조세특례·고용보험·소비자분쟁해결기준 전문 분석위원",
        "expertBadge": "✓ 국세청·고용노동부·법제처 고시 기준 검증완료",
        "colors": {
            "primary": "#881337",
            "secondary": "#27272A",
            "accent": "#BE123C",
            "background": "#FAF8F8",
            "surface": "#FFFFFF",
            "text": "#18181B",
            "muted": "#52525B",
            "border": "#E4E4E7",
            "tableHeaderBg": "#FFF1F2",
            "tableHeaderTxt": "#881337",
        },
        "typography": {
            "headingFont": "'Noto Sans KR', 'Pretendard', sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "'IBM Plex Mono', monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@500;700;900&display=swap",
            "readingMaxWidth": "740px",
            "lineHeight": "1.84",
        },
        "cardStyle": {
            "radius": "8px",
            "shadow": "0 4px 16px rgba(136, 19, 55, 0.06)",
            "border": "1px solid #FECDD3",
            "headerBorder": "3px solid #881337",
            "h2BorderLeft": "4px solid #881337",
            "h2Bg": "#FFF1F2",
            "h2Padding": "12px 16px",
        },
        "ctaText": "국세청·고용24·소비자원 공식 민원 창구 바로가기 →",
        "badgeLabel": "JUSTINFO TAX & LEGAL ADVISORY · 금융·세무·노무 전문가 칼럼",
    },

    # =========================================================================
    # ARCHITECTURE 3: 토스피드(Toss Feed) / 핀테크 스타일 — 좌측 스크롤 목차 & 스텝 블록 카드형
    # meganote.kr (메가노트 부동산·청약 · 토스 블루 스텝 카드)
    # smilenote.kr (스마일노트 연금·시니어 · 토스 에메랄드/블루 시니어 핀테크 카드)
    # =========================================================================
    "meganote.kr": {
        "id": 5,
        "domain": "meganote.kr",
        "workerName": "meganote",
        "name": "메가노트 피드",
        "slogan": "부동산·청약·모빌리티·금융 스텝 카드 가이드",
        "category": "부동산·청약피드",
        "categories": ["부동산·청약피드", "자동차·전기차보조금", "다이렉트보험·특약", "생활금융·절약팁"],
        "subTopic": "신차·전기차제원·자동차보험·특약·정비·소모품교체·운전·주유혜택",
        "targetAudience": "복잡한 청약·모빌리티 보조금·보험 특약을 토스피드처럼 스텝별 카드로 쉽게 읽고 싶은 독자",
        "shellFamily": "arch3-toss",
        "shellVariant": "toss-blue-estate",
        "archetype": "arch3-toss",
        "archetypeLabel": "[아키텍처 3] 토스피드(Toss Feed) 핀테크형 (플로팅 알약 글래스 헤더 + 좌측 220px Scrollspy 파란불 목차 + #f2f4f6 배경 위 h2별 독립 흰색 라운드 블록 카드)",
        "headerAlign": "toss-floating-pill",
        "catTabStyle": "toss-chip-tabs",
        "cardVariant": "toss-feed-card",
        "thumbRatio": "16/10",
        "colors": {
            "primary": "#3182F6",
            "secondary": "#1B64DA",
            "accent": "#00C471",
            "background": "#F2F4F6",
            "surface": "#FFFFFF",
            "text": "#191F28",
            "muted": "#6B7684",
            "border": "#E5E8EB",
            "tableHeaderBg": "#F9FAFB",
            "tableHeaderTxt": "#3182F6",
        },
        "typography": {
            "headingFont": "'Pretendard Variable', 'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "'JetBrains Mono', monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "720px",
            "lineHeight": "1.82",
        },
        "cardStyle": {
            "radius": "20px",
            "shadow": "0 8px 24px rgba(25, 31, 40, 0.04)",
            "border": "1px solid #E5E8EB",
            "headerBorder": "1px solid rgba(25, 31, 40, 0.08)",
            "h2BorderLeft": "none",
            "h2Bg": "transparent",
            "h2Padding": "0",
        },
        "ctaText": "공식 누리집에서 내 조건·보조금 1분 만에 조회하기 →",
        "badgeLabel": "MEGANOTE TOSS-STYLE FEED · 부동산·청약·모빌리티 핀테크 피드",
    },
    "smilenote.kr": {
        "id": 6,
        "domain": "smilenote.kr",
        "workerName": "smilenote",
        "name": "스마일노트 연금·시니어",
        "slogan": "국민·기초연금·은퇴설계·시니어 혜택 쉬운 스텝 피드",
        "category": "연금·은퇴설계",
        "categories": ["연금·은퇴설계", "시니어혜택·우대", "중장년건강·운동", "보조기기·돌봄지원"],
        "subTopic": "시니어건강·운동·시니어혜택·우대·은퇴·노후준비·보조기기·돌봄",
        "targetAudience": "연금 수령액, 시니어 우대 혜택, 은퇴 후 건강·돌봄 제도를 큰 글씨 카드뉴스처럼 편하게 보려는 독자",
        "shellFamily": "arch3-toss",
        "shellVariant": "toss-emerald-senior",
        "archetype": "arch3-toss",
        "archetypeLabel": "[아키텍처 3] 토스피드(Toss Feed) 시니어·연금형 (플로팅 알약 글래스 헤더 + 좌측 220px Scrollspy 파란불 목차 + #f2f4f6 배경 위 h2별 독립 흰색 라운드 블록 카드)",
        "headerAlign": "toss-floating-pill",
        "catTabStyle": "toss-chip-tabs",
        "cardVariant": "toss-feed-card",
        "thumbRatio": "16/10",
        "colors": {
            "primary": "#00875A",
            "secondary": "#3182F6",
            "accent": "#F59E0B",
            "background": "#F2F4F6",
            "surface": "#FFFFFF",
            "text": "#191F28",
            "muted": "#4E5968",
            "border": "#E5E8EB",
            "tableHeaderBg": "#ECFDF5",
            "tableHeaderTxt": "#00875A",
        },
        "typography": {
            "headingFont": "'Pretendard Variable', 'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "720px",
            "lineHeight": "1.86",
        },
        "cardStyle": {
            "radius": "20px",
            "shadow": "0 8px 24px rgba(25, 31, 40, 0.05)",
            "border": "1px solid #E5E8EB",
            "headerBorder": "1px solid rgba(0, 135, 90, 0.15)",
            "h2BorderLeft": "none",
            "h2Bg": "transparent",
            "h2Padding": "0",
        },
        "ctaText": "국민연금·복지로 공식 시니어 혜택 조회 바로가기 →",
        "badgeLabel": "SMILENOTE SENIOR FINTECH FEED · 연금·시니어 웰니스 카드 피드",
    },

    # =========================================================================
    # ARCHITECTURE 4: MS Learn / Apple Docs 스타일 — IT·테크 3단 기술 문서 & 위키형
    # topnote.kr (탑노트 IT·가전 매뉴얼 · 슬레이트 다크 Ctrl+K 헤더 + 3단 매뉴얼 그리드)
    # maxnote.kr (맥스노트 엑셀·업무자동화 위키 · 인디고/앰버 워크스페이스 위키 + <kbd> 키캡)
    # =========================================================================
    "topnote.kr": {
        "id": 4,
        "domain": "topnote.kr",
        "workerName": "topnote",
        "name": "탑노트 IT·가전 매뉴얼",
        "slogan": "Windows·macOS·스마트폰·가전 공식 트러블슈팅 기술 문서",
        "category": "윈도우·맥 설정",
        "categories": ["윈도우·맥 설정", "스마트폰·통신", "구글·오피스팁", "보안·계정복구"],
        "subTopic": "윈도우·맥 설정·스마트폰·통신·구글·오피스팁·보안·계정복구",
        "targetAudience": "PC·스마트폰·가전 오류 코드 해결 및 단계별 시스템 설정 매뉴얼을 찾는 사용자",
        "shellFamily": "arch4-mslearn",
        "shellVariant": "mslearn-slate-manual",
        "archetype": "arch4-mslearn",
        "archetypeLabel": "[아키텍처 4] MS Learn / Apple Docs형 IT 기술 매뉴얼 (슬레이트 다크 Ctrl+K 헤더 + v2026.10 Verified 배지 + 좌측 문서 트리 + 중앙 <kbd> 매뉴얼 스텝 박스 + 우측 미니맵 + 하단 피드백 박스)",
        "headerAlign": "msdocs-slate-dark",
        "catTabStyle": "msdocs-folder-tree",
        "cardVariant": "msdocs-spec-card",
        "thumbRatio": "16/10",
        "docVersion": "v2026.10 Verified",
        "colors": {
            "primary": "#2563EB",
            "secondary": "#1D4ED8",
            "accent": "#06B6D4",
            "background": "#F8FAFC",
            "surface": "#FFFFFF",
            "text": "#0F172A",
            "muted": "#475569",
            "border": "#CBD5E1",
            "tableHeaderBg": "#EFF6FF",
            "tableHeaderTxt": "#1E3A8A",
        },
        "typography": {
            "headingFont": "'Wanted Sans Variable', 'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "'JetBrains Mono', 'Consolas', monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/wanteddev/wanted-sans@v1.0.3/packages/wanted-sans/fonts/webfonts/variable/split/WantedSansVariable.min.css",
            "readingMaxWidth": "720px",
            "lineHeight": "1.80",
        },
        "cardStyle": {
            "radius": "8px",
            "shadow": "0 2px 8px rgba(15, 23, 42, 0.05)",
            "border": "1px solid #CBD5E1",
            "headerBorder": "1px solid #334155",
            "h2BorderLeft": "4px solid #2563EB",
            "h2Bg": "#F1F5F9",
            "h2Padding": "10px 14px",
        },
        "ctaText": "공식 고객지원 기술 문서 및 드라이버/설정 페이지 열기 →",
        "badgeLabel": "TOPNOTE TECH LEARN · IT·가전 공식 트러블슈팅 매뉴얼",
    },
    "maxnote.kr": {
        "id": 8,
        "domain": "maxnote.kr",
        "workerName": "maxnote",
        "name": "맥스노트 엑셀·업무자동화 위키",
        "slogan": "엑셀 수식·노션·생성형 AI·업무자동화 엔지니어링 위키",
        "category": "AI툴 실전가이드",
        "categories": ["AI툴 실전가이드", "업무자동화·노션", "크리에이터도구", "IT트렌드분석"],
        "subTopic": "AI툴 실전가이드·업무자동화·노션·크리에이터도구·IT트렌드분석",
        "targetAudience": "엑셀 단축키·수식, 노션 템플릿, 생성형 AI 프롬프트 및 업무 자동화 매뉴얼을 찾는 실무자",
        "shellFamily": "arch4-mslearn",
        "shellVariant": "mslearn-indigo-wiki",
        "archetype": "arch4-mslearn",
        "archetypeLabel": "[아키텍처 4] MS Learn / Apple Docs형 업무자동화 위키 (차콜 인디고 Ctrl+K 헤더 + v2026.10 Verified 배지 + 좌측 위키 트리 + 중앙 <kbd> 키캡·스텝 박스 + 우측 미니맵 + 하단 피드백 박스)",
        "headerAlign": "msdocs-indigo-dark",
        "catTabStyle": "msdocs-folder-tree",
        "cardVariant": "msdocs-spec-card",
        "thumbRatio": "16/10",
        "docVersion": "v2026.10 LTS Wiki",
        "colors": {
            "primary": "#4F46E5",
            "secondary": "#B45309",
            "accent": "#10B981",
            "background": "#F9FAFB",
            "surface": "#FFFFFF",
            "text": "#18181B",
            "muted": "#52525B",
            "border": "#E4E4E7",
            "tableHeaderBg": "#EEF2FF",
            "tableHeaderTxt": "#3730A3",
        },
        "typography": {
            "headingFont": "'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "'JetBrains Mono', 'Consolas', monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "720px",
            "lineHeight": "1.80",
        },
        "cardStyle": {
            "radius": "8px",
            "shadow": "0 2px 10px rgba(79, 70, 229, 0.06)",
            "border": "1px solid #E4E4E7",
            "headerBorder": "1px solid #27272A",
            "h2BorderLeft": "4px solid #4F46E5",
            "h2Bg": "#EEF2FF",
            "h2Padding": "10px 14px",
        },
        "ctaText": "엑셀·노션·AI 공식 레퍼런스 문서 및 템플릿 확인 →",
        "badgeLabel": "MAXNOTE AUTOMATION WIKI · 엑셀·노션·AI 업무자동화 기술 위키",
    },

    # =========================================================================
    # ARCHITECTURE 5: 론리플래닛 / 브런치 매거진 스타일 — 풀와이드 커버 오버레이 & 동선 타임라인형
    # tripmarvel.com (트립마블 여행 매거진 · 론리플래닛 포레스트 명조 커버 + Course 타임라인)
    # nolplace.com (놀플레이스 핫플 가이드 · 브런치 선셋 매거진 커버 + Quick Info Grid + 타임라인)
    # =========================================================================
    "tripmarvel.com": {
        "id": 10,
        "domain": "tripmarvel.com",
        "workerName": "tripmarvel",
        "name": "트립마블 여행 매거진",
        "slogan": "론리플래닛 감성 국내외 여행 코스·교통·예약 에디토리얼",
        "category": "국내여행·수목원",
        "categories": ["국내여행·수목원", "해외여행·패스", "항공·숙소예약팁", "시즌축제·코스"],
        "subTopic": "국내여행·수목원·해외여행·패스·항공·숙소예약팁·시즌축제·코스",
        "targetAudience": "국내외 명소 코스, 수목원·전시 사전예약, 교통패스 및 현장 주차 동선을 찾는 여행자",
        "shellFamily": "arch5-lonelyplanet",
        "shellVariant": "lonelyplanet-forest-serif",
        "archetype": "arch5-lonelyplanet",
        "archetypeLabel": "[아키텍처 5] 론리플래닛 매거진형 (풀블리드 100% 커버 히어로 + 명조 대형 타이틀 오버레이 + Quick Info 3칸 요약표 + Course 1➔2 세로 점선 타임라인)",
        "headerAlign": "lp-editorial-masthead",
        "catTabStyle": "lp-magazine-tabs",
        "cardVariant": "lp-cover-card",
        "thumbRatio": "16/10",
        "colors": {
            "primary": "#1B4332",
            "secondary": "#2D6A4F",
            "accent": "#C85A32",
            "background": "#FAF7F0",
            "surface": "#FFFFFF",
            "text": "#1C2826",
            "muted": "#586860",
            "border": "#D8D2C5",
            "tableHeaderBg": "#EFECE4",
            "tableHeaderTxt": "#1B4332",
        },
        "typography": {
            "headingFont": "'Nanum Myeongjo', 'Noto Serif KR', Georgia, serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "serif",
            "fontImportUrl": "https://fonts.googleapis.com/css2?family=Nanum+Myeongjo:wght@700;800&display=swap",
            "readingMaxWidth": "720px",
            "lineHeight": "1.88",
        },
        "cardStyle": {
            "radius": "14px",
            "shadow": "0 8px 26px rgba(27, 67, 50, 0.08)",
            "border": "1px solid #D8D2C5",
            "headerBorder": "2px solid #1B4332",
            "h2BorderLeft": "none",
            "h2Bg": "transparent",
            "h2Padding": "0",
        },
        "ctaText": "공식 예매처·교통패스 및 현장 방문 안내 바로가기 →",
        "badgeLabel": "TRIPMARVEL TRAVEL MAGAZINE · 론리플래닛 스타일 트래블 저널",
    },
    "nolplace.com": {
        "id": 14,
        "domain": "nolplace.com",
        "workerName": "panda-01",
        "name": "놀플레이스 핫플 가이드",
        "slogan": "브런치북 스타일 주말 나들이·전시·테마파크·주차 코스북",
        "category": "수목원·테마파크",
        "categories": ["수목원·테마파크", "아이와가볼만한곳", "전시·팝업·공연", "주차·예매꿀팁"],
        "subTopic": "수목원·테마파크·아이와가볼만한곳·전시·팝업·공연·주차·예매꿀팁",
        "targetAudience": "주말 핫플레이스, 아이와 가볼만한 전시·테마파크 예매 및 공영주차장 동선을 찾는 나들이객",
        "shellFamily": "arch5-lonelyplanet",
        "shellVariant": "brunch-sunset-hotspot",
        "archetype": "arch5-lonelyplanet",
        "archetypeLabel": "[아키텍처 5] 브런치 매거진형 (풀블리드 100% 커버 히어로 + 세리프 표지 오버레이 + Quick Info 3칸 요약표 + Course 1➔2 세로 점선 타임라인)",
        "headerAlign": "brunch-minimal-masthead",
        "catTabStyle": "lp-magazine-tabs",
        "cardVariant": "lp-cover-card",
        "thumbRatio": "16/10",
        "colors": {
            "primary": "#9A3412",
            "secondary": "#EA580C",
            "accent": "#0284C7",
            "background": "#FFFBF5",
            "surface": "#FFFFFF",
            "text": "#291811",
            "muted": "#6B5344",
            "border": "#FED7AA",
            "tableHeaderBg": "#FFEDD5",
            "tableHeaderTxt": "#9A3412",
        },
        "typography": {
            "headingFont": "'Noto Serif KR', 'Nanum Myeongjo', Georgia, serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "serif",
            "fontImportUrl": "https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@600;700;900&display=swap",
            "readingMaxWidth": "720px",
            "lineHeight": "1.86",
        },
        "cardStyle": {
            "radius": "14px",
            "shadow": "0 8px 24px rgba(154, 52, 18, 0.08)",
            "border": "1px solid #FED7AA",
            "headerBorder": "2px solid #EA580C",
            "h2BorderLeft": "none",
            "h2Bg": "transparent",
            "h2Padding": "0",
        },
        "ctaText": "현장 주차장·사전 예약 일정 및 공식 안내 바로가기 →",
        "badgeLabel": "NOLPLACE HOTSPOT MAGAZINE · 주말 나들이·전시·코스 매거진",
    },

    # =========================================================================
    # ARCHITECTURE 6: 서울아산병원 / WebMD 스타일 — 메디컬 저널 & 증상 체크시트형
    # healthcox.com (헬스콕스 의학·건강 저널 · 청록/민트 크로스 헤더 + 팩트체크 배너 + 클리닉 시트 + 우측 건강 칼럼 사이드바)
    # =========================================================================
    "healthcox.com": {
        "id": 7,
        "domain": "healthcox.com",
        "workerName": "healthcox",
        "name": "헬스콕스 의학·건강 저널",
        "slogan": "서울아산병원·WebMD 스타일 질환·증상 체크시트 & 건강검진 가이드",
        "category": "관절·통증케어",
        "categories": ["관절·통증케어", "국가건강검진", "만성질환·혈관", "수면·영양의학"],
        "subTopic": "관절·통증케어·국가건강검진·만성질환·혈관·수면·영양의학",
        "targetAudience": "증상별 원인 체크시트, 국가건강검진 대상 조회, 만성질환·혈관 및 재활 가이드를 찾는 독자",
        "shellFamily": "arch6-webmd",
        "shellVariant": "asan-webmd-clinical",
        "archetype": "arch6-webmd",
        "archetypeLabel": "[아키텍처 6] 서울아산병원 / WebMD 메디컬 저널형 (청록/민트 크로스 심볼 헤더 + 🩺 에디토리얼 팩트체크 고정 배너 + 증상·수칙 클리닉 체크시트 + 우측 건강 칼럼 사이드바)",
        "headerAlign": "medical-cross-header",
        "catTabStyle": "clinical-dept-tabs",
        "cardVariant": "clinical-chart-card",
        "thumbRatio": "16/10",
        "colors": {
            "primary": "#0F766E",
            "secondary": "#0D9488",
            "accent": "#E11D48",
            "background": "#F0FDFA",
            "surface": "#FFFFFF",
            "text": "#134E4A",
            "muted": "#475569",
            "border": "#99F6E4",
            "tableHeaderBg": "#CCFBF1",
            "tableHeaderTxt": "#0F766E",
        },
        "typography": {
            "headingFont": "'IBM Plex Sans KR', 'Pretendard', sans-serif",
            "bodyFont": "'IBM Plex Sans KR', 'Pretendard', sans-serif",
            "monoFont": "'IBM Plex Mono', monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap",
            "readingMaxWidth": "720px",
            "lineHeight": "1.84",
        },
        "cardStyle": {
            "radius": "10px",
            "shadow": "0 4px 16px rgba(15, 118, 110, 0.06)",
            "border": "1px solid #99F6E4",
            "headerBorder": "3px solid #0F766E",
            "h2BorderLeft": "5px solid #0F766E",
            "h2Bg": "#CCFBF1",
            "h2Padding": "10px 16px",
        },
        "ctaText": "국민건강보험공단·심평원 공식 검진 및 진료 기준 확인 →",
        "badgeLabel": "HEALTHCOX MEDICAL JOURNAL · 의학·건강 에디토리얼 저널",
    },

    # =========================================================================
    # ARCHITECTURE 7: 다나와 DPG / 컨슈머리포트 스타일 — 비교 스코어보드 & 장단점 대조형
    # must-pick.com (머스트픽 가전·환급 비교 · 블랙/네이비 2단 리뷰 포털 헤더 + ★★★★★ 스코어보드 + 다나와 스펙 비교표)
    # baronote.kr (바로노트 스마트 소비리포트 · 오션네이비 2단 소비리포트 헤더 + 혜택 스코어보드 + 장단점 대조표)
    # =========================================================================
    "must-pick.com": {
        "id": 11,
        "domain": "must-pick.com",
        "workerName": "mustpick",
        "name": "머스트픽 가전·환급 비교",
        "slogan": "다나와 DPG·컨슈머리포트 스타일 가전 스펙·환급금·A/S 비교 랩",
        "category": "대형·주방가전",
        "categories": ["대형·주방가전", "생활·계절가전", "디지털·기어가이드", "A/S·수리비용"],
        "subTopic": "대형·주방가전·생활·계절가전·디지털·기어가이드·A/S·수리비용",
        "targetAudience": "가전·디지털 스펙 비교, 으뜸효율 환급금 신청 및 공식 A/S 수리비용 비교표를 찾는 소비자",
        "shellFamily": "arch7-danawa",
        "shellVariant": "danawa-darknavy-spec",
        "archetype": "arch7-danawa",
        "archetypeLabel": "[아키텍처 7] 다나와 DPG / 컨슈머리포트형 (블랙/네이비 2단 리뷰 포털 헤더 + 상단 ★★★★★ 스코어보드 & 장단점 대조 박스 + 다나와 줄무늬 스펙 비교표)",
        "headerAlign": "dpg-darknavy-2tier",
        "catTabStyle": "dpg-spec-tabs",
        "cardVariant": "dpg-scoreboard-card",
        "thumbRatio": "16/10",
        "scoreRating": "4.9 / 5.0 (★★★★★)",
        "scoreDifficulty": "쉬움 (공식 기준 5분 확인)",
        "colors": {
            "primary": "#0D1B2A",
            "secondary": "#00A896",
            "accent": "#FFB703",
            "background": "#F4F6F8",
            "surface": "#FFFFFF",
            "text": "#0D1B2A",
            "muted": "#475569",
            "border": "#CBD5E1",
            "tableHeaderBg": "#0D1B2A",
            "tableHeaderTxt": "#FFFFFF",
        },
        "typography": {
            "headingFont": "'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "'JetBrains Mono', monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "740px",
            "lineHeight": "1.80",
        },
        "cardStyle": {
            "radius": "10px",
            "shadow": "0 4px 16px rgba(13, 27, 42, 0.07)",
            "border": "1px solid #CBD5E1",
            "headerBorder": "3px solid #00A896",
            "h2BorderLeft": "6px solid #00A896",
            "h2Bg": "#E6F4F1",
            "h2Padding": "11px 16px",
        },
        "ctaText": "공식 인증 스펙·에너지효율 환급 및 A/S 기준표 확인 →",
        "badgeLabel": "MUSTPICK DPG CONSUMER REPORT · 가전·환급 스펙 비교 포털",
    },
    "baronote.kr": {
        "id": 2,
        "domain": "baronote.kr",
        "workerName": "baronote",
        "name": "바로노트 스마트 소비리포트",
        "slogan": "연금·대출·카드 캐시백·통신·보험 혜택 비교 컨슈머리포트",
        "category": "국민·기초연금",
        "categories": ["국민·기초연금", "대출·금리비교", "신용·카드혜택", "보험·절세전략"],
        "subTopic": "국민·기초연금·대출·금리비교·신용·카드혜택·보험·절세전략",
        "targetAudience": "금융 상품 금리, 카드 혜택, 연금 수령액 및 통신·보험 절세 조건을 스코어보드로 비교하려는 독자",
        "shellFamily": "arch7-danawa",
        "shellVariant": "consumer-ocean-report",
        "archetype": "arch7-danawa",
        "archetypeLabel": "[아키텍처 7] 컨슈머리포트 스마트 소비 비교형 (오션네이비 2단 리뷰 헤더 + 상단 ★★★★★ 혜택 스코어보드 & 유불리 대조표 + 줄무늬 비교 테이블)",
        "headerAlign": "dpg-ocean-2tier",
        "catTabStyle": "dpg-spec-tabs",
        "cardVariant": "dpg-scoreboard-card",
        "thumbRatio": "16/10",
        "scoreRating": "4.8 / 5.0 (★★★★★)",
        "scoreDifficulty": "보통 (온라인 즉시 조회 가능)",
        "colors": {
            "primary": "#0C4A6E",
            "secondary": "#0284C7",
            "accent": "#F59E0B",
            "background": "#F0F9FF",
            "surface": "#FFFFFF",
            "text": "#0C4A6E",
            "muted": "#475569",
            "border": "#BAE6FD",
            "tableHeaderBg": "#0C4A6E",
            "tableHeaderTxt": "#FFFFFF",
        },
        "typography": {
            "headingFont": "'SUIT Variable', 'Pretendard', sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "'JetBrains Mono', monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/sunn-us/SUIT/fonts/variable/woff2/SUIT-Variable.css",
            "readingMaxWidth": "740px",
            "lineHeight": "1.82",
        },
        "cardStyle": {
            "radius": "10px",
            "shadow": "0 4px 16px rgba(12, 74, 110, 0.07)",
            "border": "1px solid #BAE6FD",
            "headerBorder": "3px solid #0284C7",
            "h2BorderLeft": "6px solid #0284C7",
            "h2Bg": "#E0F2FE",
            "h2Padding": "11px 16px",
        },
        "ctaText": "금융기관 공식 금리·수령액·혜택 비교 조회 바로가기 →",
        "badgeLabel": "BARONOTE SMART CONSUMER REPORT · 금융·혜택 비교 리포트",
    },

    # =========================================================================
    # ARCHITECTURE 8: 오늘의집 / 29CM 스타일 — 감성 라이프·반려동물 큐레이션 매거진형
    # must-joy.com (머스트조이 문화·취미 · 29CM 테라코타 감성 부티크)
    # soulnote.kr (소울노트 라이프·책 · 라벤더 북앤라이프 큐레이션 스튜디오)
    # joynote.kr (조이노트 반려동물 케어 · 오늘의집 민트/코랄 펫앤가든 매거진)
    # =========================================================================
    "must-joy.com": {
        "id": 9,
        "domain": "must-joy.com",
        "workerName": "mustjoy",
        "name": "머스트조이 문화·취미",
        "slogan": "29CM 감성 미식·로컬맛집·카페·전시 큐레이션 매거진",
        "category": "로컬맛집·웨이팅",
        "categories": ["로컬맛집·웨이팅", "감성카페·베이커리", "문화·전시리뷰", "특산물·미식가이드"],
        "subTopic": "로컬맛집·웨이팅·감성카페·베이커리·문화·전시리뷰·특산물·미식가이드",
        "targetAudience": "로컬 맛집 웨이팅 노하우, 감성 베이커리, 전시·문화공간 큐레이션을 찾는 라이프스타일 독자",
        "shellFamily": "arch8-todayhouse",
        "shellVariant": "29cm-terracotta-culture",
        "archetype": "arch8-todayhouse",
        "archetypeLabel": "[아키텍처 8] 오늘의집 / 29CM 감성 큐레이션형 (상단 컬러 띠배너 + 둥근 필 아이콘 카테고리 바 + 에디터 말풍선 노트 + 귀여운 소제목 아이콘 배지 + 하단 3열 매거진 포토 그리드)",
        "headerAlign": "boutique-ribbon-header",
        "catTabStyle": "pill-icon-boutique",
        "cardVariant": "magazine-3col-grid",
        "thumbRatio": "4/3",
        "ribbonText": "✨ 오늘의 에디터 추천 라이프 가이드 · 29CM 감성 컬처·미식 큐레이션",
        "h2IconBadge": "🍽️",
        "colors": {
            "primary": "#C2410C",
            "secondary": "#EA580C",
            "accent": "#1E1B4B",
            "background": "#FFF7ED",
            "surface": "#FFFFFF",
            "text": "#1C1917",
            "muted": "#57534E",
            "border": "#FED7AA",
            "tableHeaderBg": "#FFEDD5",
            "tableHeaderTxt": "#9A3412",
        },
        "typography": {
            "headingFont": "'Pretendard', 'Noto Serif KR', sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "720px",
            "lineHeight": "1.85",
        },
        "cardStyle": {
            "radius": "16px",
            "shadow": "0 8px 24px rgba(194, 65, 12, 0.07)",
            "border": "1px solid #FED7AA",
            "headerBorder": "2px solid #C2410C",
            "h2BorderLeft": "none",
            "h2Bg": "#FFEDD5",
            "h2Padding": "12px 18px",
        },
        "ctaText": "공식 예매처·매장 예약 및 컬처 가이드 자세히 보기 →",
        "badgeLabel": "MUSTJOY CULTURE BOUTIQUE · 문화·취미·미식 큐레이션 매거진",
    },
    "soulnote.kr": {
        "id": 15,
        "domain": "soulnote.kr",
        "workerName": "soulnote",
        "name": "소울노트 라이프·책",
        "slogan": "자기계발·독서·자격증·국비지원 감성 라이프 큐레이션",
        "category": "내일배움카드·국비",
        "categories": ["내일배움카드·국비", "유망국가자격증", "시험일정·기출팁", "이직·커리어설계"],
        "subTopic": "내일배움카드·국비·유망국가자격증·시험일정·기출팁·이직·커리어설계",
        "targetAudience": "성장하는 직장인·성인을 위한 독서·자격증·내일배움카드 국비지원 라이프 가이드를 찾는 독자",
        "shellFamily": "arch8-todayhouse",
        "shellVariant": "boutique-lavender-life",
        "archetype": "arch8-todayhouse",
        "archetypeLabel": "[아키텍처 8] 오늘의집 / 29CM 라이프·북 큐레이션형 (상단 바이올렛 컬러 띠배너 + 필 아이콘 카테고리 바 + 에디터 인터뷰 말풍선 노트 + 소제목 아이콘 배지 + 하단 3열 매거진 카드 그리드)",
        "headerAlign": "boutique-ribbon-header",
        "catTabStyle": "pill-icon-boutique",
        "cardVariant": "magazine-3col-grid",
        "thumbRatio": "4/3",
        "ribbonText": "📚 오늘의 에디터 추천 라이프 가이드 · 성장과 커리어를 채우는 소울노트 큐레이션",
        "h2IconBadge": "📖",
        "colors": {
            "primary": "#6D28D9",
            "secondary": "#8B5CF6",
            "accent": "#F59E0B",
            "background": "#FAF8FF",
            "surface": "#FFFFFF",
            "text": "#1E1035",
            "muted": "#5B4D75",
            "border": "#DDD6FE",
            "tableHeaderBg": "#F5F3FF",
            "tableHeaderTxt": "#5B21B6",
        },
        "typography": {
            "headingFont": "'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "720px",
            "lineHeight": "1.85",
        },
        "cardStyle": {
            "radius": "16px",
            "shadow": "0 8px 24px rgba(109, 40, 217, 0.07)",
            "border": "1px solid #DDD6FE",
            "headerBorder": "2px solid #6D28D9",
            "h2BorderLeft": "none",
            "h2Bg": "#F5F3FF",
            "h2Padding": "12px 18px",
        },
        "ctaText": "큐넷·고용24 공식 일정 및 라이프 가이드 확인하기 →",
        "badgeLabel": "SOULNOTE LIFE & BOOK STUDIO · 감성 라이프·커리어 매거진",
    },
    "joynote.kr": {
        "id": 16,
        "domain": "joynote.kr",
        "workerName": "joynote",
        "name": "조이노트 반려동물 케어",
        "slogan": "오늘의집 감성 강아지·고양이 건강·펫보험·반려식물 큐레이션",
        "category": "강아지·고양이건강",
        "categories": ["강아지·고양이건강", "펫보험·진료비비교", "반려동물동반장소", "반려식물·홈가드닝"],
        "subTopic": "강아지·고양이건강·펫보험·진료비비교·반려동물동반장소·반려식물·홈가드닝",
        "targetAudience": "강아지·고양이 건강 케어, 동물병원 진료비·펫보험, 반려식물 홈가드닝 큐레이션을 찾는 반려인",
        "shellFamily": "arch8-todayhouse",
        "shellVariant": "todayhouse-mint-pet",
        "archetype": "arch8-todayhouse",
        "archetypeLabel": "[아키텍처 8] 오늘의집 스타일 반려동물·플랜테리어 큐레이션형 (상단 민트 띠배너 + 필 아이콘 카테고리 바 + 반려생활 말풍선 노트 + 🐾 소제목 배지 + 하단 3열 포토 카드 그리드)",
        "headerAlign": "boutique-ribbon-header",
        "catTabStyle": "pill-icon-boutique",
        "cardVariant": "magazine-3col-grid",
        "thumbRatio": "4/3",
        "ribbonText": "🐾 오늘의 에디터 추천 라이프 가이드 · 반려동물 케어 & 플랜테리어 큐레이션",
        "h2IconBadge": "🐾",
        "colors": {
            "primary": "#0D9488",
            "secondary": "#14B8A6",
            "accent": "#FB7185",
            "background": "#F4FBF7",
            "surface": "#FFFFFF",
            "text": "#064E3B",
            "muted": "#3F6256",
            "border": "#A7F3D0",
            "tableHeaderBg": "#CCFBF1",
            "tableHeaderTxt": "#0F766E",
        },
        "typography": {
            "headingFont": "'Pretendard', -apple-system, sans-serif",
            "bodyFont": "'Pretendard', -apple-system, sans-serif",
            "monoFont": "monospace",
            "cfFontFamily": "sans",
            "fontImportUrl": "https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css",
            "readingMaxWidth": "720px",
            "lineHeight": "1.85",
        },
        "cardStyle": {
            "radius": "16px",
            "shadow": "0 8px 24px rgba(13, 148, 136, 0.07)",
            "border": "1px solid #A7F3D0",
            "headerBorder": "2px solid #0D9488",
            "h2BorderLeft": "none",
            "h2Bg": "#ECFDF5",
            "h2Padding": "12px 18px",
        },
        "ctaText": "국가동물보호정보시스템·공식 진료비 기준 바로 확인 →",
        "badgeLabel": "JOYNOTE PET & HOME CURATION · 반려동물·식물 감성 매거진",
    },
}


def get_domain_spec(domain: Optional[str] = None) -> Dict[str, Any]:
    """Return the 1:1 Identity & Shell Spec for a given domain, defaulting to daynote.kr."""
    if domain:
        clean = (
            str(domain)
            .lower()
            .strip()
            .removeprefix("https://")
            .removeprefix("http://")
            .removeprefix("www.")
            .split("/")[0]
        )
        if clean in DOMAIN_IDENTITY_SPECS:
            return DOMAIN_IDENTITY_SPECS[clean]
    return DOMAIN_IDENTITY_SPECS["daynote.kr"]


def build_table_styles(domain: Optional[str] = None) -> Dict[str, str]:
    """Return deterministic inline styles for table, th, td, caption, figure, img, figcaption per domain."""
    spec = get_domain_spec(domain)
    c = spec["colors"]
    cs = spec["cardStyle"]
    radius_first = cs["radius"].split()[0]
    return {
        "caption": f"caption-side:top;text-align:left;font-size:13px;line-height:1.6;color:{c['muted']};padding:0 0 10px;font-weight:600;",
        "wrapper": "overflow-x:auto;max-width:100%;margin:24px 0;-webkit-overflow-scrolling:touch;",
        "table": f"border-collapse:collapse;width:100%;min-width:560px;border:1px solid {c['border']};font-size:15.5px;line-height:1.75;table-layout:auto;background:{c['surface']};",
        "th": f"border:1px solid {c['border']};padding:12px 14px;background:{c['tableHeaderBg']};color:{c['tableHeaderTxt']};font-weight:700;font-size:15.5px;line-height:1.75;text-align:left;vertical-align:top;word-break:keep-all;overflow-wrap:anywhere;",
        "td": f"border:1px solid {c['border']};padding:12px 14px;font-size:15.5px;line-height:1.75;color:{c['text']};text-align:left;vertical-align:top;word-break:keep-all;overflow-wrap:anywhere;",
        "figure": "display:block;text-align:center;margin:28px 0;",
        "img": f"display:block;width:100%;max-width:100%;height:auto;margin:0 auto;border-radius:{radius_first};",
        "figcaption": f"display:block;font-size:12px;line-height:1.6;color:{c['muted']};text-align:center;margin:8px 0 0;padding:0 12px;",
    }


def generate_domain_css(domain: str) -> str:
    """
    Generate the complete 1:1 custom CSS stylesheet for a domain across the 8 Independent Architectures:
    1. `arch1-wikitree` (Wikitree Social News Portal — 3-col asymmetric news layout + ticker + TOP 10 ranking)
    2. `arch2-albup` (Albup Lawyer/Tax Column — breadcrumb + expert profile + 3-line summary + POINT 01 + FAQ accordion)
    3. `arch3-toss` (Toss Feed Fintech — floating pill glass header + left sticky scrollspy TOC + split white rounded H2 block cards)
    4. `arch4-mslearn` (MS Learn / Apple Docs — slate dark Ctrl+K header + 3-col tree/manual/minimap + <kbd> keycaps + bottom feedback)
    5. `arch5-lonelyplanet` (Lonely Planet / Brunch — full-bleed cover hero + Quick Info 3-col grid + vertical Course 1➔2 dotted timeline)
    6. `arch6-webmd` (Asan Medical / WebMD — teal cross header + fixed fact-check banner + clinical symptom checksheet + right health sidebar)
    7. `arch7-danawa` (Danawa DPG / Consumer Reports — 2-tier dark review header + ★★★★★ scoreboard + pros/cons + zebra spec table)
    8. `arch8-todayhouse` (Todayhouse / 29CM — top ribbon banner + pill icon categories + speech-bubble note + cute H2 icons + bottom 3-col photo grid)
    """
    spec = get_domain_spec(domain)
    c = spec["colors"]
    t = spec["typography"]
    cs = spec["cardStyle"]
    fam = spec["shellFamily"]
    var = spec["shellVariant"]
    r0 = cs["radius"].split()[0]

    arch_css = ""

    # -------------------------------------------------------------------------
    # ARCH 1: WIKITREE STYLE (`daynote.kr`, `must-good.com`)
    # -------------------------------------------------------------------------
    if fam == "arch1-wikitree":
        is_navy = var == "wikitree-navy-left"
        hdr_bg = "#0B192C" if is_navy else "#FFFFFF"
        hdr_txt = "#FFFFFF" if is_navy else "#0F172A"
        hdr_sub = "#93C5FD" if is_navy else "#64748B"
        nav_bg = "#112240" if is_navy else "#F8FAFC"
        grid_cols = "300px minmax(0, 700px) 60px" if is_navy else "60px minmax(0, 700px) 300px"
        arch_css = f"""
/* === ARCH 1: WIKITREE SOCIAL NEWS PORTAL ({var}) === */
.wt-header-shell {{
  background: {hdr_bg};
  color: {hdr_txt};
  border-bottom: 2px solid {c['primary']};
  box-shadow: 0 2px 12px rgba(15, 23, 42, 0.06);
}}
.wt-ticker-bar {{
  background: {"#07101E" if is_navy else "#0F172A"};
  color: #FFFFFF;
  font-size: 12.5px;
  padding: 7px 20px;
  border-bottom: 1px solid rgba(255,255,255,0.1);
}}
.wt-ticker-in {{
  max-width: 1140px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}}
.wt-ticker-badge {{
  background: #E11D48;
  color: #FFFFFF;
  font-weight: 900;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}}
.wt-header-main {{
  max-width: 1140px;
  margin: 0 auto;
  padding: 16px 20px;
  display: grid;
  grid-template-columns: 160px 1fr 220px;
  align-items: center;
}}
.wt-hamburger-btn {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 800;
  color: {hdr_txt};
  background: {"rgba(255,255,255,0.1)" if is_navy else "#F1F5F9"};
  border: 1px solid {"rgba(255,255,255,0.2)" if is_navy else "#CBD5E1"};
  padding: 7px 12px;
  border-radius: 6px;
  cursor: pointer;
  width: fit-content;
}}
.wt-brand-center {{
  text-align: center;
}}
.wt-brand-logo {{
  font-family: {t['headingFont']};
  font-size: {"2.1rem" if is_navy else "2.0rem"};
  font-weight: 900;
  color: {hdr_txt} !important;
  text-decoration: none;
  letter-spacing: {"-0.01em" if is_navy else "-0.04em"};
  display: inline-block;
}}
.wt-brand-sub {{
  display: block;
  font-size: 10.5px;
  font-weight: 700;
  color: {hdr_sub};
  letter-spacing: 0.12em;
  margin-top: 2px;
}}
.wt-section-menubar {{
  background: {nav_bg};
  border-top: 1px solid {"rgba(255,255,255,0.12)" if is_navy else "#E2E8F0"};
}}
.wt-section-menubar-in {{
  max-width: 1140px;
  margin: 0 auto;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-wrap: wrap;
}}
.wt-sec-link {{
  padding: 10px 16px;
  font-size: 13.5px;
  font-weight: 800;
  color: {hdr_txt} !important;
  text-decoration: none;
  border-bottom: 3px solid transparent;
  transition: all 0.15s;
}}
.wt-sec-link.active, .wt-sec-link:hover {{
  color: {"#38BDF8" if is_navy else c['primary']} !important;
  border-bottom-color: {"#38BDF8" if is_navy else c['primary']};
}}
/* 3-Column Asymmetric Article Grid: 60px Share + 700px Article + 300px Ranking */
body[data-shell-family="arch1-wikitree"][data-page-type="article"] .layout {{
  max-width: 1140px !important;
  margin: 24px auto 60px !important;
  padding: 0 20px !important;
  display: grid !important;
  grid-template-columns: {grid_cols} !important;
  gap: 24px !important;
  align-items: start !important;
}}
body[data-shell-family="arch1-wikitree"][data-page-type="home"] .layout {{
  max-width: 1140px !important;
  margin: 24px auto 60px !important;
  padding: 0 20px !important;
  display: grid !important;
  grid-template-columns: {"300px minmax(0, 1fr)" if is_navy else "minmax(0, 1fr) 300px"} !important;
  gap: 24px !important;
  align-items: start !important;
}}
.wt-share-col {{
  position: sticky;
  top: 100px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}}
.wt-share-btn {{
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: #FFFFFF;
  border: 1px solid #CBD5E1;
  box-shadow: 0 2px 8px rgba(15,23,42,0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 800;
  color: #0F172A;
  cursor: pointer;
  transition: transform 0.15s, border-color 0.15s;
}}
.wt-share-btn:hover {{
  transform: translateY(-2px);
  border-color: {c['primary']};
  color: {c['primary']};
}}
.wt-byline-bar {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  margin: 12px 0 20px;
  background: #F8FAFC;
  border-top: 1px solid #CBD5E1;
  border-bottom: 1px solid #CBD5E1;
  font-size: 13px;
  color: #334155;
}}
.wt-byline-tag {{
  display: inline-block;
  background: {c['primary']};
  color: #FFFFFF;
  font-weight: 800;
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 4px;
  margin-right: 6px;
}}
.wt-fontsize-btns {{
  display: inline-flex;
  gap: 4px;
}}
.wt-fontsize-btns button {{
  background: #FFFFFF;
  border: 1px solid #CBD5E1;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 12px;
  font-weight: 800;
  color: #0F172A;
  cursor: pointer;
}}
.wt-ranking-col {{
  width: 300px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}}
.wt-top10-box {{
  background: #FFFFFF;
  border: 1px solid #CBD5E1;
  border-top: 3px solid {c['primary']};
  border-radius: 8px;
  padding: 18px 16px;
  box-shadow: 0 4px 14px rgba(15,23,42,0.05);
}}
.wt-top10-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid #E2E8F0;
}}
.wt-top10-header h4 {{
  margin: 0;
  font-size: 15px;
  font-weight: 900;
  color: #0F172A;
}}
.wt-top10-list {{
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}}
.wt-top10-item {{
  display: grid;
  grid-template-columns: 26px 1fr;
  align-items: start;
  gap: 8px;
  font-size: 13px;
  line-height: 1.42;
  padding-bottom: 8px;
  border-bottom: 1px dashed #E2E8F0;
}}
.wt-top10-item:last-child {{
  border-bottom: none;
  padding-bottom: 0;
}}
.wt-rank-num {{
  font-weight: 900;
  font-size: 14px;
  color: #64748B;
  font-family: 'Pretendard', sans-serif;
}}
.wt-rank-num.top3 {{
  color: {c['primary']};
}}
.wt-newspaper-footer {{
  background: #0F172A !important;
  color: #CBD5E1 !important;
  padding: 32px 24px 70px !important;
  border-top: 3px solid {c['primary']} !important;
  font-size: 12.5px !important;
  line-height: 1.75 !important;
}}
"""

    # -------------------------------------------------------------------------
    # ARCH 2: ALBUP STYLE (`woorinote.kr`, `justinfo.co.kr`)
    # -------------------------------------------------------------------------
    elif fam == "arch2-albup":
        is_burgundy = var == "albup-burgundy-tax"
        prof_bg = "#FFF1F2" if is_burgundy else "#EFF6FF"
        prof_border = "2px double #881337" if is_burgundy else "1px solid #93C5FD"
        arch_css = f"""
/* === ARCH 2: ALBUP EXPERT COLUMN & Q&A ADVISORY ({var}) === */
.albup-header-shell {{
  background: #FFFFFF;
  border-bottom: 2px solid {c['primary']};
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
}}
.albup-header-in {{
  max-width: 1120px;
  margin: 0 auto;
  padding: 16px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}}
.albup-checklist-badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: {c['primary']};
  color: #FFFFFF !important;
  font-size: 12.5px;
  font-weight: 800;
  padding: 8px 14px;
  border-radius: 6px;
  text-decoration: none;
  box-shadow: 0 4px 10px rgba(0,0,0,0.1);
}}
body[data-shell-family="arch2-albup"] .layout {{
  max-width: 980px !important;
  margin: 24px auto 60px !important;
  padding: 0 20px !important;
  display: block !important;
}}
.albup-breadcrumb {{
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 700;
  color: {c['muted']};
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  padding: 9px 14px;
  border-radius: 6px;
  margin-bottom: 16px;
}}
.albup-breadcrumb strong {{
  color: {c['primary']};
}}
.albup-profile-card {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  background: {prof_bg};
  border: {prof_border};
  border-left: 5px solid {c['primary']};
  border-radius: 10px;
  padding: 16px 20px;
  margin: 14px 0 16px;
}}
.albup-profile-left {{
  display: flex;
  align-items: center;
  gap: 14px;
}}
.albup-avatar {{
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: {c['primary']};
  color: #FFFFFF;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
}}
.albup-stamp-badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #FFFFFF;
  color: {c['primary']};
  border: 1.5px solid {c['primary']};
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
}}
.albup-summary-3line {{
  background: #F8FAFC;
  border: 1px solid {c['border']};
  border-top: 3px solid {c['primary']};
  border-radius: 10px;
  padding: 18px 22px;
  margin: 0 0 24px;
}}
.albup-summary-3line h4 {{
  margin: 0 0 10px;
  font-size: 14.5px;
  font-weight: 900;
  color: {c['primary']};
}}
.albup-summary-3line ul {{
  margin: 0;
  padding-left: 18px;
  font-size: 14px;
  line-height: 1.7;
  color: {c['text']};
}}
.albup-point-badge {{
  display: inline-block;
  background: {c['primary']};
  color: #FFFFFF;
  font-family: 'Pretendard', monospace;
  font-size: 12px;
  font-weight: 900;
  padding: 3px 9px;
  border-radius: 4px;
  margin-right: 10px;
  vertical-align: middle;
  letter-spacing: 0.04em;
}}
.albup-faq-section {{
  margin: 36px 0 24px;
  padding: 22px;
  background: #F8FAFC;
  border: 1px solid {c['border']};
  border-radius: 12px;
}}
.albup-faq-item {{
  background: #FFFFFF;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  margin-bottom: 10px;
  overflow: hidden;
}}
.albup-faq-item summary {{
  padding: 14px 16px;
  font-weight: 800;
  font-size: 14.5px;
  color: {c['text']};
  cursor: pointer;
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
}}
.albup-faq-item summary::-webkit-details-marker {{
  display: none;
}}
.albup-faq-ans {{
  padding: 0 16px 14px;
  font-size: 14px;
  line-height: 1.7;
  color: {c['muted']};
  border-top: 1px dashed #E2E8F0;
  padding-top: 12px;
}}
.albup-more-columns {{
  margin: 24px 0;
  padding: 18px 20px;
  background: #FFFFFF;
  border: 1px solid {c['border']};
  border-radius: 10px;
}}
"""

    # -------------------------------------------------------------------------
    # ARCH 3: TOSS FEED / FINTECH STYLE (`meganote.kr`, `smilenote.kr`)
    # -------------------------------------------------------------------------
    elif fam == "arch3-toss":
        arch_css = f"""
/* === ARCH 3: TOSS FEED / FINTECH STICKY TOC & SPLIT BLOCK CARDS ({var}) === */
body[data-shell-family="arch3-toss"] {{
  background: #F2F4F6 !important;
}}
.toss-pill-header-wrap {{
  position: sticky;
  top: 14px;
  z-index: 120;
  padding: 0 16px;
  margin: 14px auto 24px;
  max-width: 1120px;
}}
.toss-pill-header {{
  background: rgba(255, 255, 255, 0.86) !important;
  backdrop-filter: blur(14px) !important;
  -webkit-backdrop-filter: blur(14px) !important;
  border: 1px solid rgba(25, 31, 40, 0.08) !important;
  border-radius: 999px !important;
  padding: 12px 24px !important;
  box-shadow: 0 8px 28px rgba(25, 31, 40, 0.07) !important;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}}
.toss-nav-pills {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}}
.toss-nav-pill {{
  padding: 7px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  color: #4E5968 !important;
  text-decoration: none;
  background: transparent;
  transition: all 0.15s;
}}
.toss-nav-pill.active, .toss-nav-pill:hover {{
  background: #3182F6;
  color: #FFFFFF !important;
}}
body[data-shell-family="arch3-toss"][data-page-type="article"] .layout {{
  max-width: 1080px !important;
  margin: 0 auto 60px !important;
  padding: 0 20px !important;
  display: grid !important;
  grid-template-columns: 220px minmax(0, 1fr) !important;
  gap: 28px !important;
  align-items: start !important;
}}
body[data-shell-family="arch3-toss"][data-page-type="article"] .main > .wrap {{
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  padding: 0 !important;
}}
.toss-scrollspy-aside {{
  position: sticky;
  top: 96px;
  background: #FFFFFF;
  border-radius: 20px;
  padding: 20px 16px;
  box-shadow: 0 4px 20px rgba(25, 31, 40, 0.05);
  border: 1px solid #E5E8EB;
}}
.toss-scrollspy-title {{
  font-size: 12px;
  font-weight: 800;
  color: #8B95A1;
  margin-bottom: 12px;
  padding-left: 8px;
}}
.toss-toc-link {{
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  color: #4E5968 !important;
  text-decoration: none !important;
  margin-bottom: 4px;
  transition: all 0.15s;
}}
.toss-toc-dot {{
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #D1D6DB;
  flex-shrink: 0;
}}
.toss-toc-link.active {{
  background: #E8F3FF;
  color: #3182F6 !important;
  font-weight: 800;
}}
.toss-toc-link.active .toss-toc-dot {{
  background: #3182F6;
  box-shadow: 0 0 0 3px rgba(49, 130, 246, 0.22);
}}
.toss-hero-card,
.toss-section-card {{
  background: #FFFFFF !important;
  border-radius: 20px !important;
  padding: 28px !important;
  margin-bottom: 20px !important;
  box-shadow: 0 4px 20px rgba(25, 31, 40, 0.04) !important;
  border: 1px solid #E5E8EB !important;
}}
.toss-step-chip {{
  display: inline-block;
  background: #E8F3FF;
  color: #3182F6;
  font-size: 11.5px;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 999px;
  margin-bottom: 10px;
}}
.toss-section-card h2 {{
  border: none !important;
  background: transparent !important;
  padding: 0 !important;
  margin: 0 0 14px !important;
  font-size: 1.35rem !important;
  color: #191F28 !important;
}}
"""

    # -------------------------------------------------------------------------
    # ARCH 4: MS LEARN / APPLE DOCS STYLE (`topnote.kr`, `maxnote.kr`)
    # -------------------------------------------------------------------------
    elif fam == "arch4-mslearn":
        hdr_bg = "#18181B" if var == "mslearn-indigo-wiki" else "#0F172A"
        arch_css = f"""
/* === ARCH 4: MS LEARN / APPLE DOCS 3-COL TECHNICAL MANUAL ({var}) === */
.msdocs-header {{
  background: {hdr_bg} !important;
  color: #F8FAFC !important;
  border-bottom: 1px solid #334155;
  padding: 12px 24px;
}}
.msdocs-header-in {{
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}}
.msdocs-search-box {{
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 6px;
  padding: 6px 12px;
  color: #CBD5E1;
  font-size: 12.5px;
  min-width: 240px;
}}
.msdocs-ver-badge {{
  background: rgba(37, 99, 235, 0.25);
  border: 1px solid #60A5FA;
  color: #93C5FD;
  font-family: {t['monoFont']};
  font-size: 11px;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 999px;
}}
body[data-shell-family="arch4-mslearn"] .layout {{
  max-width: 1400px !important;
  margin: 0 auto !important;
  padding: 0 !important;
  display: grid !important;
  grid-template-columns: 250px minmax(0, 1fr) 250px !important;
  gap: 0 !important;
  align-items: start !important;
  min-height: calc(100vh - 56px);
}}
.msdocs-tree-sidebar {{
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  background: #F8FAFC;
  border-right: 1px solid #CBD5E1;
  padding: 20px 14px;
  font-size: 13px;
}}
.msdocs-tree-group {{
  margin-bottom: 16px;
}}
.msdocs-tree-folder {{
  font-weight: 800;
  color: #0F172A;
  padding: 6px 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}}
.msdocs-tree-item {{
  display: block;
  padding: 6px 10px 6px 24px;
  color: #475569 !important;
  text-decoration: none !important;
  border-left: 2px solid #E2E8F0;
  margin-left: 10px;
  font-size: 12.5px;
}}
.msdocs-tree-item.active, .msdocs-tree-item:hover {{
  border-left-color: {c['primary']};
  color: {c['primary']} !important;
  font-weight: 800;
  background: #EFF6FF;
}}
.msdocs-minimap-aside {{
  position: sticky;
  top: 20px;
  padding: 20px 16px;
  border-left: 1px solid #E2E8F0;
}}
.msdocs-step-box {{
  border: 1px solid #CBD5E1;
  border-left: 4px solid {c['primary']};
  background: #FFFFFF;
  border-radius: 8px;
  padding: 18px 20px;
  margin: 24px 0;
  box-shadow: 0 2px 6px rgba(15,23,42,0.03);
}}
.msdocs-step-num {{
  display: inline-block;
  font-family: {t['monoFont']};
  font-size: 11px;
  font-weight: 800;
  background: {c['primary']};
  color: #FFFFFF;
  padding: 2px 8px;
  border-radius: 4px;
  margin-bottom: 8px;
}}
kbd, .msdocs-kbd {{
  display: inline-block;
  padding: 2px 7px;
  font-family: {t['monoFont']};
  font-size: 12px;
  font-weight: 700;
  line-height: 1.4;
  color: #0F172A;
  background: linear-gradient(180deg, #FFFFFF 0%, #F1F5F9 100%);
  border: 1px solid #94A3B8;
  border-bottom-width: 3px;
  border-radius: 5px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.08);
  margin: 0 2px;
}}
.msdocs-feedback-box {{
  margin: 36px 0 20px;
  padding: 20px 24px;
  background: #F8FAFC;
  border: 1px solid #CBD5E1;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
}}
.msdocs-fb-btn {{
  padding: 8px 16px;
  border-radius: 6px;
  border: 1px solid #CBD5E1;
  background: #FFFFFF;
  font-weight: 700;
  font-size: 13px;
  cursor: pointer;
}}
.msdocs-fb-btn:hover {{
  border-color: {c['primary']};
  color: {c['primary']};
}}
"""

    # -------------------------------------------------------------------------
    # ARCH 5: LONELY PLANET / BRUNCH MAGAZINE (`tripmarvel.com`, `nolplace.com`)
    # -------------------------------------------------------------------------
    elif fam == "arch5-lonelyplanet":
        arch_css = f"""
/* === ARCH 5: LONELY PLANET / BRUNCH FULL-WIDE COVER & COURSE TIMELINE ({var}) === */
body[data-shell-family="arch5-lonelyplanet"] .layout {{
  max-width: 980px !important;
  margin: 0 auto 60px !important;
  padding: 0 20px !important;
  display: block !important;
}}
.lp-header-shell {{
  background: {c['surface']};
  border-bottom: 1px solid {c['border']};
}}
.lp-cover-hero {{
  position: relative;
  width: 100%;
  min-height: 360px;
  background-size: cover;
  background-position: center;
  display: flex;
  align-items: flex-end;
  margin-bottom: 32px;
}}
.lp-cover-scrim {{
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(15,23,42,0.18) 0%, rgba(15,23,42,0.78) 100%);
}}
.lp-cover-content {{
  position: relative;
  z-index: 2;
  max-width: 980px;
  width: 100%;
  margin: 0 auto;
  padding: 44px 28px;
  color: #FFFFFF;
}}
.lp-cover-kicker {{
  display: inline-block;
  background: {c['accent']};
  color: #FFFFFF;
  font-size: 11.5px;
  font-weight: 800;
  letter-spacing: 0.1em;
  padding: 4px 12px;
  border-radius: 999px;
  margin-bottom: 14px;
}}
.lp-cover-content h1 {{
  font-family: {t['headingFont']} !important;
  font-size: clamp(1.85rem, 3.5vw, 2.65rem) !important;
  line-height: 1.34 !important;
  color: #FFFFFF !important;
  margin: 0 0 12px !important;
  text-shadow: 0 4px 20px rgba(0,0,0,0.45);
}}
.lp-quick-info-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin: 0 0 30px;
}}
.lp-quick-info-cell {{
  background: {c['background']};
  border: 1px solid {c['border']};
  border-top: 3px solid {c['primary']};
  border-radius: 12px;
  padding: 14px 16px;
}}
.lp-quick-info-cell strong {{
  display: block;
  font-size: 12.5px;
  color: {c['primary']};
  margin-bottom: 4px;
}}
.lp-quick-info-cell span {{
  font-size: 13.5px;
  font-weight: 700;
  color: {c['text']};
}}
/* Vertical Course Dotted Timeline */
body[data-shell-family="arch5-lonelyplanet"] .content {{
  position: relative;
  padding-left: 28px;
  border-left: 2px dashed {c['accent']};
  margin-left: 10px;
}}
.lp-course-badge {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: {c['primary']};
  color: #FFFFFF;
  font-family: 'Pretendard', sans-serif;
  font-size: 11.5px;
  font-weight: 800;
  padding: 4px 11px;
  border-radius: 999px;
  margin-right: 10px;
  position: relative;
}}
body[data-shell-family="arch5-lonelyplanet"] .content h2 {{
  position: relative;
  background: {c['background']} !important;
  border: 1px solid {c['border']} !important;
  border-radius: 12px !important;
  padding: 12px 16px !important;
}}
body[data-shell-family="arch5-lonelyplanet"] .content h2::before {{
  content: "";
  position: absolute;
  left: -36px;
  top: 18px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: {c['accent']};
  border: 3px solid #FFFFFF;
  box-shadow: 0 0 0 2px {c['accent']};
}}
"""

    # -------------------------------------------------------------------------
    # ARCH 6: ASAN MEDICAL / WEBMD STYLE (`healthcox.com`)
    # -------------------------------------------------------------------------
    elif fam == "arch6-webmd":
        arch_css = f"""
/* === ARCH 6: ASAN MEDICAL CENTER / WEBMD CLINICAL JOURNAL ({var}) === */
.med-header-shell {{
  background: #FFFFFF;
  border-top: 4px solid #0F766E;
  border-bottom: 1px solid #99F6E4;
}}
.med-cross-symbol {{
  display: inline-flex;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: #0F766E;
  color: #FFFFFF;
  align-items: center;
  justify-content: center;
  font-weight: 900;
  font-size: 18px;
  margin-right: 8px;
}}
.med-factcheck-banner {{
  background: linear-gradient(90deg, #CCFBF1 0%, #F0FDFA 100%);
  border: 1px solid #5EEAD4;
  border-left: 5px solid #0F766E;
  border-radius: 8px;
  padding: 12px 16px;
  margin: 0 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 13px;
  font-weight: 700;
  color: #115E59;
}}
body[data-shell-family="arch6-webmd"][data-page-type="article"] .layout {{
  max-width: 1140px !important;
  margin: 24px auto 60px !important;
  padding: 0 20px !important;
  display: grid !important;
  grid-template-columns: minmax(0, 740px) 320px !important;
  gap: 28px !important;
  align-items: start !important;
}}
body[data-shell-family="arch6-webmd"][data-page-type="home"] .layout {{
  max-width: 1140px !important;
  margin: 24px auto 60px !important;
  padding: 0 20px !important;
  display: block !important;
}}
.med-checksheet-box {{
  background: #F0FDFA;
  border: 1.5px solid #2DD4BF;
  border-radius: 10px;
  padding: 18px 20px;
  margin: 18px 0 26px;
}}
.med-checksheet-title {{
  font-size: 14.5px;
  font-weight: 900;
  color: #0F766E;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}}
.med-clinical-sidebar {{
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}}
"""

    # -------------------------------------------------------------------------
    # ARCH 7: DANAWA DPG / CONSUMER REPORTS (`must-pick.com`, `baronote.kr`)
    # -------------------------------------------------------------------------
    elif fam == "arch7-danawa":
        arch_css = f"""
/* === ARCH 7: DANAWA DPG / CONSUMER REPORTS SCOREBOARD ({var}) === */
body[data-shell-family="arch7-danawa"] .layout,
body[data-shell-family="arch7-danawa"] main.page {{
  max-width: 1040px !important;
  margin: 24px auto 60px !important;
  padding: 0 20px !important;
  display: block !important;
}}
body[data-shell-family="arch7-danawa"] main.page {{
  background: #FFFFFF;
  border: 1px solid {c['border']};
  border-radius: 10px;
  padding: 32px 28px !important;
  box-shadow: {cs['shadow']};
}}
.dpg-two-tier-header {{
  background: #FFFFFF;
  border-bottom: 2px solid {c['primary']};
}}
.dpg-util-bar {{
  background: {c['primary']};
  color: #FFFFFF;
  font-size: 12px;
  padding: 7px 24px;
}}
.dpg-util-in {{
  max-width: 1160px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
}}
.dpg-scoreboard-box {{
  background: linear-gradient(135deg, {c['primary']} 0%, #1E293B 100%);
  color: #FFFFFF;
  border-radius: 12px;
  padding: 20px 22px;
  margin: 16px 0 20px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  box-shadow: 0 8px 22px rgba(13, 27, 42, 0.14);
}}
.dpg-score-cell {{
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.16);
  border-radius: 8px;
  padding: 12px 14px;
}}
.dpg-score-label {{
  font-size: 11.5px;
  color: #CBD5E1;
  display: block;
  margin-bottom: 4px;
}}
.dpg-score-val {{
  font-size: 15px;
  font-weight: 900;
  color: #FFB703 !important;
}}
.dpg-pros-cons-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin: 0 0 26px;
}}
.dpg-pros-box {{
  background: #ECFDF5;
  border: 1px solid #6EE7B7;
  border-top: 3px solid #059669;
  border-radius: 8px;
  padding: 14px 16px;
  font-size: 13.5px;
}}
.dpg-cons-box {{
  background: #FFFBEB;
  border: 1px solid #FCD34D;
  border-top: 3px solid #D97706;
  border-radius: 8px;
  padding: 14px 16px;
  font-size: 13.5px;
}}
/* Danawa Zebra Spec Comparison Table */
body[data-shell-family="arch7-danawa"] .content table tr:nth-child(even) td,
body[data-shell-family="arch7-danawa"] article.gs-article table tr:nth-child(even) td {{
  background: #F8FAFC !important;
}}
body[data-shell-family="arch7-danawa"] .content table td:first-child,
body[data-shell-family="arch7-danawa"] article.gs-article table td:first-child {{
  font-weight: 800 !important;
  background: #F1F5F9 !important;
  color: {c['primary']} !important;
}}
"""

    # -------------------------------------------------------------------------
    # ARCH 8: TODAYHOUSE / 29CM STYLE (`must-joy.com`, `soulnote.kr`, `joynote.kr`)
    # -------------------------------------------------------------------------
    else:
        arch_css = f"""
/* === ARCH 8: TODAYHOUSE / 29CM LIFESTYLE CURATION MAGAZINE ({var}) === */
body[data-shell-family="arch8-todayhouse"] .layout {{
  max-width: 980px !important;
  margin: 24px auto 60px !important;
  padding: 0 20px !important;
  display: block !important;
}}
.th-ribbon-banner {{
  background: linear-gradient(90deg, {c['primary']} 0%, {c['secondary']} 100%);
  color: #FFFFFF;
  text-align: center;
  padding: 8px 16px;
  font-size: 12.5px;
  font-weight: 800;
  letter-spacing: 0.02em;
}}
.th-boutique-header {{
  background: #FFFFFF;
  border-bottom: 1px solid {c['border']};
}}
.th-pill-cat-bar {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
  padding: 12px 20px 16px;
}}
.th-pill-cat {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 999px;
  background: {c['background']};
  border: 1px solid {c['border']};
  color: {c['text']} !important;
  font-size: 13px;
  font-weight: 800;
  text-decoration: none;
  transition: all 0.15s;
}}
.th-pill-cat.active, .th-pill-cat:hover {{
  background: {c['primary']};
  color: #FFFFFF !important;
  border-color: {c['primary']};
}}
.th-speech-note {{
  position: relative;
  background: {c['background']};
  border: 1.5px solid {c['border']};
  border-radius: 18px;
  padding: 18px 22px;
  margin: 16px 0 26px;
  display: flex;
  align-items: flex-start;
  gap: 14px;
}}
.th-h2-icon {{
  display: inline-flex;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: {c['primary']};
  color: #FFFFFF;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  margin-right: 8px;
  vertical-align: middle;
}}
.th-related-3col-wrap {{
  margin: 36px 0 20px;
  padding-top: 24px;
  border-top: 2px solid {c['border']};
}}
.th-related-3col-grid {{
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin-top: 14px;
}}
.th-mag-card {{
  background: #FFFFFF;
  border: 1px solid {c['border']};
  border-radius: 14px;
  overflow: hidden;
  text-decoration: none !important;
  color: {c['text']} !important;
  box-shadow: 0 4px 14px rgba(0,0,0,0.04);
  display: flex;
  flex-direction: column;
}}
"""

    css = f"""/* ==========================================================================
   {spec['domain']} ({spec['name']}) — 8-Architecture Independent DOM Skeleton
   Architecture: {fam} | Variant: {var}
   Primary: {c['primary']} | Secondary: {c['secondary']} | Accent: {c['accent']} | Bg: {c['background']}
   ========================================================================== */
:root {{
  --pri: {c['primary']} !important;
  --sec: {c['secondary']} !important;
  --acc: {c['accent']} !important;
  --bg: {c['background']} !important;
  --bg2: {c['tableHeaderBg']} !important;
  --surface: {c['surface']} !important;
  --txt: {c['text']} !important;
  --muted: {c['muted']} !important;
  --line: {c['border']} !important;
  --reading-max: {t['readingMaxWidth']};
  --card-radius: {cs['radius']};
  --card-shadow: {cs['shadow']};
}}

/* ==========================================================================
   CLEAN PUBLIC VIEW: 100% HIDE LEGACY DUPLICATE HEADER & ADMIN BUTTONS
   ========================================================================== */
[data-admin],
.admin-tools,
.admin-only,
.write-btn,
.visit-strip,
.gov-bar,
.ov,
.drawer,
.mtoggle,
.sidebar > .profile,
.header .nav a[href="/admin"],
header.hd .nav a[href="/admin"],
#topActions,
.wrap > .top,
.wrap > .actions,
.wrap > hr,
main.page > .top,
main.page > .actions,
main.page > hr,
#mobileOverlay,
#mobileMenu,
.mobile-overlay,
.mobile-menu,
.menu-toggle,
.side-section,
.side-search,
#sideSearch,
.sidebar .side-cat,
.google-auto-placed,
ins.adsbygoogle.adsbygoogle-noablate,
ins.adsbygoogle[data-anchor-status],
ins.adsbygoogle[data-anchor-shown],
.google-anno-skip,
.google-anno-sc,
.google-aiuf,
.goog-rentry,
#postGrid .card ins.adsbygoogle {{
  display: none !important;
  visibility: hidden !important;
  width: 0 !important;
  height: 0 !important;
  max-height: 0 !important;
  margin: 0 !important;
  padding: 0 !important;
  border: 0 !important;
  overflow: hidden !important;
  pointer-events: none !important;
}}

body {{
  background: var(--bg) !important;
  color: var(--txt) !important;
  font-family: {t['bodyFont']} !important;
  line-height: {t['lineHeight']} !important;
  letter-spacing: -0.012em;
  -webkit-font-smoothing: antialiased;
  margin: 0;
  padding: 0 !important;
}}

{arch_css}

/* Post Card Grid Defaults on Home */
#postGrid.grid {{
  display: grid !important;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)) !important;
  gap: 20px !important;
}}
#postGrid .card {{
  display: flex !important;
  flex-direction: column !important;
  background: var(--surface) !important;
  border: {cs['border']} !important;
  border-radius: {cs['radius']} !important;
  box-shadow: {cs['shadow']} !important;
  overflow: hidden !important;
}}
#postGrid .card .thumb-empty {{
  width: 100% !important;
  height: 100% !important;
  background: linear-gradient(135deg, var(--pri) 0%, var(--sec) 100%) !important;
  color: #ffffff !important;
  display: flex !important;
  flex-direction: column !important;
  justify-content: center !important;
  align-items: flex-start !important;
  padding: 18px 20px !important;
  box-sizing: border-box !important;
}}

/* Article Typography & Subheadings */
.content, article.gs-article, article.content {{
  max-width: var(--reading-max);
  font-family: {t['bodyFont']};
  line-height: {t['lineHeight']};
  color: var(--txt);
  word-break: keep-all;
  overflow-wrap: break-word;
}}
.main h1, article h1, main.page h1 {{
  font-family: {t['headingFont']} !important;
  color: var(--txt) !important;
  letter-spacing: -0.025em;
  line-height: 1.34 !important;
}}
.content h2, article h2 {{
  font-family: {t['headingFont']};
  color: var(--pri);
  border-left: {cs['h2BorderLeft']};
  background: {cs['h2Bg']};
  padding: {cs['h2Padding']};
  border-radius: 0 {r0} {r0} 0;
  margin: 34px 0 14px !important;
  font-size: 1.32rem !important;
  line-height: 1.45 !important;
}}
.content h3, article h3 {{
  font-family: {t['headingFont']};
  color: var(--txt);
  border-bottom: 1px solid var(--line);
  padding-bottom: 6px;
  margin: 24px 0 10px !important;
}}

/* AdSense 5 High-CPC Slots Integration */
.adsense-slot {{
  position: relative;
  width: 100%;
  margin: 18px 0;
  padding: 8px;
  border-radius: {r0};
  background: var(--surface);
  border: 1px solid var(--line);
  text-align: center;
  overflow: hidden;
  clear: both;
}}
.adsense-slot--hero-below {{
  min-height: 0 !important;
  max-height: 250px !important;
  margin: 14px 0 22px !important;
}}
.adsense-slot--in-article,
.content .ad {{
  margin: 26px 0 !important;
  min-height: 0 !important;
  max-height: 250px !important;
  padding: 10px !important;
  border-top: 2px solid var(--sec) !important;
  border-bottom: 1px solid var(--line) !important;
  background: var(--bg) !important;
}}
.adsense-slot--sticky-rail {{
  position: sticky !important;
  top: 88px !important;
  width: 100% !important;
  max-width: 300px !important;
  min-height: 250px !important;
  max-height: 600px !important;
  margin: 0 auto !important;
  padding: 12px 10px !important;
  background: var(--surface) !important;
  border: {cs['border']} !important;
  border-top: 3px solid var(--pri) !important;
  border-radius: {r0} !important;
  box-shadow: var(--card-shadow) !important;
}}
.adsense-slot--multiplex-bottom {{
  margin: 28px 0 18px !important;
  min-height: 0 !important;
  max-height: 260px !important;
  padding: 12px !important;
  border: 1px solid var(--line) !important;
  border-top: 3px solid var(--acc) !important;
  background: var(--surface) !important;
}}

/* Indirect Experience Capture Images (`.guide-capture-img`) */
figure.post-image {{
  margin: 26px 0 !important;
  padding: 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: {r0};
  box-shadow: var(--card-shadow);
}}
img.guide-capture-img,
figure.post-image a[aria-label*="원본 화면 크게 보기"] img {{
  display: block;
  width: 100% !important;
  max-width: 100% !important;
  height: auto !important;
  border: 2px solid #1646b7 !important;
  border-radius: 8px !important;
}}
.brand-cta-btn {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  min-height: 52px;
  margin: 22px 0;
  padding: 14px 22px;
  background: linear-gradient(135deg, var(--pri) 0%, var(--sec) 100%);
  color: #ffffff !important;
  font-family: {t['headingFont']};
  font-size: 1.02rem;
  font-weight: 800;
  text-decoration: none !important;
  border-radius: {r0};
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12);
}}

@media (max-width: 1060px) {{
  html body[data-shell-family][data-domain] .layout,
  html body[data-shell-family] .layout {{
    display: block !important;
    grid-template-columns: minmax(0, 1fr) !important;
    padding: 12px 10px !important;
  }}
  .wt-share-col, .wt-ranking-col, .toss-scrollspy-aside, .msdocs-tree-sidebar, .msdocs-minimap-aside, .med-clinical-sidebar, .layout > aside {{
    display: none !important;
  }}
  .lp-quick-info-grid, .dpg-scoreboard-box, .dpg-pros-cons-grid, .th-related-3col-grid {{
    grid-template-columns: 1fr !important;
  }}
  body, footer {{
    padding-bottom: 70px !important;
  }}
}}
"""
    return css.strip() + "\n\n" + CARD_CSS


def build_final_preview_html(domain: str, title: str, assembled_html: str) -> str:
    """
    Build the standalone `final.html` preview document for a domain while preserving 100% of
    `assembled_html` text/headings/tables/images inside `<article class="gs-article content">`
    for `verify_public_content` and `manuscript_semantics` invariance, AND running the live
    8-Architecture DOM transformer so offline previews match the live site 1:1.
    """
    spec = get_domain_spec(domain)
    css = generate_domain_css(domain)
    font_url = spec["typography"]["fontImportUrl"]
    fam = spec["shellFamily"]

    soup = BeautifulSoup(assembled_html, "html.parser")
    h2s = soup.find_all("h2")
    in_article_slot = soup.new_tag(
        "aside",
        attrs={
            "class": "ad-slot adsense-slot adsense-slot--in-article",
            "data-h2ad": "1",
            "data-slot-type": "in-article-h2",
            "aria-label": "본문 중간 광고 슬롯",
        },
    )
    if len(h2s) >= 3:
        h2s[2].insert_before(in_article_slot)
    elif len(h2s) >= 2:
        h2s[1].insert_before(in_article_slot)
    elif h2s:
        h2s[0].insert_before(in_article_slot)

    body_with_mid_ad = str(soup)
    safe_title = html.escape(title or "")
    safe_name = html.escape(spec["name"])
    safe_cat = html.escape(spec["category"])
    head_inj = build_live_cf_head_injection(domain, "")

    return (
        f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{safe_title}</title>'
        f'{head_inj}</head>'
        f'<body data-domain="{spec["domain"]}" data-shell-family="{fam}" data-shell-variant="{spec["shellVariant"]}">'
        f'<header class="header"><div class="header-in"><a class="brand" href="/">{safe_name}</a></div></header>'
        f'<div class="layout">'
        f'<aside class="sidebar"></aside>'
        f'<main class="main"><div class="wrap" style="background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:32px 28px;">'
        f'<h1>{safe_title}</h1>'
        f'<div class="meta">{safe_cat} · 2026-10-18 · 약 5분</div>'
        f'<aside class="ad ad-slot adsense-slot adsense-slot--hero-below" data-h2ad="1" data-slot-type="hero-below" aria-label="제목 직하단 반응형 디스플레이 광고"></aside>'
        f'<article class="gs-article content">{body_with_mid_ad}</article>'
        f'<aside class="ad ad-slot adsense-slot adsense-slot--multiplex-bottom" data-h2ad="1" data-slot-type="multiplex-bottom" aria-label="본문 결론 직후 멀티플렉스 추천 광고"></aside>'
        f'</div></main>'
        f'</div>'
        f'<footer class="adsense-slot--mobile-anchor-safe" style="border-top:1px solid var(--line);padding:24px 20px 70px;text-align:center;font-size:12px;color:var(--muted);">'
        f'© {safe_name} ({spec["domain"]})</footer>'
        f'</body></html>'
    )


def build_live_cf_head_injection(domain: str, existing_adsense_code: str, ad_mid_html: str = "") -> str:
    """
    Build the `adsense_code` payload for a live CF site's `/api/settings` so that:
    1. Existing Google AdSense `<script async src="...adsbygoogle.js?client=ca-pub-...">` is 100% preserved.
    2. Font stylesheet + 1:1 custom domain CSS (`generate_domain_css(domain)`) is injected cleanly.
    3. 8-Architecture Independent DOM Transformer (`applyBaro8ArchitectureDOM`) restructures both
       Article Detail (`!isHome`) and Home (`isHome`) pages into 8 completely different HTML DOM skeletons.
    """
    spec = get_domain_spec(domain)
    css = generate_domain_css(domain)
    font_url = spec["typography"]["fontImportUrl"]

    cleaned_base = re.sub(
        r"<!-- BAROLAB_1TO1_THEME_START -->.*?<!-- BAROLAB_1TO1_THEME_END -->",
        "",
        existing_adsense_code or "",
        flags=re.DOTALL,
    ).strip()

    pub_match = re.search(r"ca-pub-\d+", (cleaned_base + " " + (ad_mid_html or "")))
    pub_id = pub_match.group(0) if pub_match else ""
    slot_match = re.search(r'data-ad-slot="(\d+)"', ad_mid_html or "")
    slot_id = slot_match.group(1) if slot_match else ""

    shell_config_json = json.dumps(
        {
            "domain": spec["domain"],
            "name": spec["name"],
            "slogan": spec.get("slogan", ""),
            "category": spec["category"],
            "categories": spec.get("categories", []),
            "subTopic": spec["subTopic"],
            "shellFamily": spec["shellFamily"],
            "shellVariant": spec["shellVariant"],
            "badgeLabel": spec["badgeLabel"],
            "ctaText": spec.get("ctaText", ""),
            "editorName": spec.get("editorName", "편집데스크"),
            "pressRegNo": spec.get("pressRegNo", "서울 아54800"),
            "publisherName": spec.get("publisherName", "김정훈"),
            "youthOfficer": spec.get("youthOfficer", "이서연"),
            "headlines": spec.get("headlines", []),
            "top10Articles": spec.get("top10Articles", []),
            "expertName": spec.get("expertName", "수석 자문 에디터"),
            "expertRole": spec.get("expertRole", "법률·세무·제도 실무 리서치 센터"),
            "expertBadge": spec.get("expertBadge", "✓ 공식 기관 기준 검수필"),
            "docVersion": spec.get("docVersion", "v2026.10 Verified"),
            "scoreRating": spec.get("scoreRating", "4.9 / 5.0 (★★★★★)"),
            "scoreDifficulty": spec.get("scoreDifficulty", "쉬움 (5분 완료)"),
            "ribbonText": spec.get("ribbonText", "✨ 오늘의 에디터 추천 라이프 가이드"),
            "h2IconBadge": spec.get("h2IconBadge", "✨"),
            "pubId": pub_id,
            "slotId": slot_id,
        },
        ensure_ascii=False,
    )

    enhancer_js = f"""
(function(){{
  var CFG = {shell_config_json};

  function cleanHeadingText(str) {{
    return (str || '').replace(/^\\s*#+\\s*/, '').replace(/^\\d+\\.\\s+/, '').trim();
  }}

  function scrubLegacyAndAdminUI(root) {{
    var scope = root || document;
    var sels = [
      '[data-admin]', '.admin-tools', '.admin-only', '.write-btn', '.visit-strip',
      '.gov-bar', '.ov', '.drawer', '.mtoggle',
      '.sidebar > .profile', '.header .nav a[href="/admin"]', 'header.hd .nav a[href="/admin"]',
      '#topActions', '.wrap > .top', '.wrap > .actions', '.wrap > hr',
      'main.page > .top', 'main.page > .actions', 'main.page > hr',
      '#mobileOverlay', '#mobileMenu', '.mobile-overlay', '.mobile-menu',
      '.menu-toggle', '.side-section', '.side-search', '#sideSearch', '.sidebar .side-cat',
      '.google-auto-placed', 'ins.adsbygoogle.adsbygoogle-noablate',
      'ins.adsbygoogle[data-anchor-status]', 'ins.adsbygoogle[data-anchor-shown]'
    ];
    sels.forEach(function(s){{
      scope.querySelectorAll(s).forEach(function(el){{ el.remove(); }});
    }});
    scope.querySelectorAll('.main .meta, .art-meta').forEach(function(m){{
      m.textContent = (m.textContent || '').replace(/\\s*·\\s*조회\\s*[0-9,]+/g, '');
    }});
    /* Strip stray leading # from any H2 in article content */
    scope.querySelectorAll('.content h2, article.gs-article h2').forEach(function(h){{
      if (!h.children.length && /^\\s*#/.test(h.textContent || '')) {{
        h.textContent = (h.textContent || '').replace(/^\\s*#+\\s*/, '');
      }}
    }});
  }}

  function collectCategories() {{
    var params = new URLSearchParams(window.location.search || '');
    var activeCat = params.get('cat') || '';
    var cats = [{{ href: '/', label: '전체', active: !activeCat }}];
    (CFG.categories || []).forEach(function(c){{
      cats.push({{ href: '/?cat=' + encodeURIComponent(c), label: c, active: activeCat === c }});
    }});
    return cats;
  }}

  function extractArticleMeta() {{
    var h1 = document.querySelector('.main h1, main.page h1, article h1');
    var metaEl = document.querySelector('.main .meta, main.page .art-meta, .art-meta');
    var metaTxt = metaEl ? (metaEl.textContent || '') : '';
    var parts = metaTxt.split(/\\s+·\\s+/).map(function(s){{ return s.trim(); }}).filter(Boolean);
    var cat = parts[0] || (CFG.categories && CFG.categories[0]) || CFG.category;
    var dateStr = parts[1] || '2026-10-18';
    var readTime = parts[2] || '약 5분';
    return {{
      h1: h1,
      title: h1 ? (h1.textContent || '').trim() : CFG.name,
      metaEl: metaEl,
      cat: cat,
      dateStr: dateStr,
      readTime: readTime
    }};
  }}

  function buildStickyAdSlotHtml() {{
    return '<aside class="ad-slot adsense-slot adsense-slot--sticky-rail" data-h2ad="1" data-slot-type="sticky-300x600">' +
      '<div style="font-size:10px;font-weight:800;color:var(--muted);letter-spacing:0.08em;margin-bottom:6px;">SPONSORED · AD</div>' +
      '<div style="width:100%;min-height:240px;background:var(--bg);border:1px dashed var(--line);border-radius:6px;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:14px;box-sizing:border-box;">' +
      '<strong style="font-size:13px;color:var(--pri);margin-bottom:6px;">' + CFG.name + ' 추천 안내</strong>' +
      '<p style="font-size:12px;color:var(--muted);margin:0 0 12px;line-height:1.5;">' + CFG.subTopic + ' 공식 기준 및 최신 혜택을 확인하세요.</p>' +
      '<a href="/" style="padding:7px 14px;border-radius:6px;background:var(--pri);color:#fff;font-size:12px;font-weight:800;text-decoration:none;">공식 가이드 열람 →</a>' +
      '</div></aside>';
  }}

  /* ========================================================================
     ARCH 1: WIKITREE STYLE (`daynote.kr` vs `must-good.com`)
     ======================================================================== */
  function applyArch1Wikitree(cats, isHome) {{
    var isNavy = CFG.shellVariant === 'wikitree-navy-left';
    var header = document.querySelector('body > .header, body > header');
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'wt-header-shell';
      var tickerItems = (CFG.headlines && CFG.headlines.length) ? CFG.headlines : [CFG.slogan];
      var navLinks = cats.map(function(c){{
        return '<a class="wt-sec-link' + (c.active ? ' active' : '') + '" href="' + c.href + '">' + c.label + '</a>';
      }}).join('');
      header.innerHTML =
        '<div class="wt-ticker-bar"><div class="wt-ticker-in">' +
        '<div style="display:flex;align-items:center;gap:10px;overflow:hidden;white-space:nowrap;">' +
        '<span class="wt-ticker-badge">🔥 HEADLINE</span>' +
        '<span id="wtTickerText" style="font-weight:700;">' + tickerItems[0] + '</span></div>' +
        '<span style="font-size:11.5px;opacity:0.8;flex-shrink:0;">실시간 뉴스데스크 · ' + new Date().toISOString().slice(0,10) + '</span>' +
        '</div></div>' +
        '<div class="wt-header-main">' +
        '<div><button type="button" class="wt-hamburger-btn" onclick="location.href=&apos;/&apos;">☰ 전체섹션</button></div>' +
        '<div class="wt-brand-center"><a class="wt-brand-logo" href="/">' + CFG.name + '</a><span class="wt-brand-sub">' + CFG.badgeLabel + '</span></div>' +
        '<form onsubmit="event.preventDefault();var q=this.querySelector(&apos;input&apos;).value.trim();location.href=q?&apos;/?q=&apos;+encodeURIComponent(q):&apos;/&apos;;" style="display:flex;justify-content:flex-end;">' +
        '<div style="display:flex;align-items:center;border:1px solid ' + (isNavy ? 'rgba(255,255,255,0.25)' : '#CBD5E1') + ';border-radius:999px;padding:5px 12px;background:' + (isNavy ? 'rgba(255,255,255,0.08)' : '#F8FAFC') + ';">' +
        '<input type="search" placeholder="뉴스 검색..." style="border:none;background:transparent;color:inherit;font-size:12px;outline:none;width:110px;" />' +
        '<button type="submit" style="border:none;background:transparent;cursor:pointer;font-size:13px;">🔍</button></div></form>' +
        '</div>' +
        '<nav class="wt-section-menubar"><div class="wt-section-menubar-in">' + navLinks + '</div></nav>';

      if (tickerItems.length > 1) {{
        var tIdx = 0;
        setInterval(function(){{
          tIdx = (tIdx + 1) % tickerItems.length;
          var el = document.getElementById('wtTickerText');
          if (el) el.textContent = tickerItems[tIdx];
        }}, 4000);
      }}
    }}

    var layout = document.querySelector('.layout');
    if (!layout || layout.hasAttribute('data-arch-layout')) return;
    layout.setAttribute('data-arch-layout', '1');
    layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    var top10List = (CFG.top10Articles || []).slice(0, 10).map(function(title, idx){{
      var rankCls = idx < 3 ? 'wt-rank-num top3' : 'wt-rank-num';
      return '<li class="wt-top10-item"><span class="' + rankCls + '">' + (idx + 1) + '</span>' +
        '<a href="/?q=' + encodeURIComponent(title.split(' ')[0]) + '" style="color:#0F172A;text-decoration:none;font-weight:700;">' + title + '</a></li>';
    }}).join('');

    var rankingCol = document.createElement('aside');
    rankingCol.className = 'wt-ranking-col';
    rankingCol.innerHTML =
      '<div class="wt-top10-box">' +
      '<div class="wt-top10-header"><h4>🔥 실시간 많이 본 기사 TOP 10</h4><span style="font-size:11px;color:#E11D48;font-weight:800;">LIVE</span></div>' +
      '<ol class="wt-top10-list">' + top10List + '</ol>' +
      '</div>' + buildStickyAdSlotHtml();

    if (!isHome) {{
      var info = extractArticleMeta();
      if (info.metaEl) {{
        var byline = document.createElement('div');
        byline.className = 'wt-byline-bar';
        byline.innerHTML =
          '<div><span class="wt-byline-tag">[이슈기획]</span><strong>' + CFG.editorName + ' 기자</strong> · 입력 ' + info.dateStr + ' 09:30 · 카테고리: ' + info.cat + '</div>' +
          '<div class="wt-fontsize-btns">' +
          '<button type="button" id="wtFontMinus" title="글자 작게">가-</button>' +
          '<button type="button" id="wtFontPlus" title="글자 크게">가+</button>' +
          '<button type="button" onclick="window.print()">🖨️ 인쇄</button></div>';
        info.metaEl.replaceWith(byline);
        var curSize = 16.5;
        var minusBtn = byline.querySelector('#wtFontMinus');
        var plusBtn = byline.querySelector('#wtFontPlus');
        var contentEl = document.querySelector('.content, article.gs-article');
        if (minusBtn && contentEl) minusBtn.onclick = function(){{ curSize = Math.max(14, curSize - 1); contentEl.style.fontSize = curSize + 'px'; }};
        if (plusBtn && contentEl) plusBtn.onclick = function(){{ curSize = Math.min(22, curSize + 1); contentEl.style.fontSize = curSize + 'px'; }};
      }}

      var shareCol = document.createElement('aside');
      shareCol.className = 'wt-share-col';
      shareCol.innerHTML =
        '<button type="button" class="wt-share-btn" title="링크 복사" onclick="navigator.clipboard&&navigator.clipboard.writeText(location.href);alert(&apos;기사 링크가 복사되었습니다.&apos;);">🔗</button>' +
        '<button type="button" class="wt-share-btn" title="카카오 공유" onclick="window.scrollTo({{top:0,behavior:&apos;smooth&apos;}})">💬</button>' +
        '<button type="button" class="wt-share-btn" title="스크랩" onclick="window.print()">📑</button>' +
        '<button type="button" class="wt-share-btn" title="맨 위로" onclick="window.scrollTo({{top:0,behavior:&apos;smooth&apos;}})">↑</button>';

      var mainEl = layout.querySelector('main');
      if (isNavy) {{
        layout.insertBefore(rankingCol, mainEl);
        layout.appendChild(shareCol);
      }} else {{
        layout.insertBefore(shareCol, mainEl);
        layout.appendChild(rankingCol);
      }}
    }} else {{
      var mainArea = layout.querySelector('main');
      if (isNavy) layout.insertBefore(rankingCol, mainArea);
      else layout.appendChild(rankingCol);
    }}

    var footer = document.querySelector('footer');
    if (footer) {{
      footer.className = 'wt-newspaper-footer adsense-slot--mobile-anchor-safe';
      footer.innerHTML =
        '<div style="max-width:1140px;margin:0 auto;text-align:left;">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;padding-bottom:14px;border-bottom:1px solid #334155;margin-bottom:14px;">' +
        '<strong style="font-size:16px;color:#FFFFFF;">📰 ' + CFG.name + ' (' + CFG.domain + ')</strong>' +
        '<div style="display:flex;gap:14px;"><a href="/about" style="color:#CBD5E1;text-decoration:none;">매체소개</a><a href="/privacy" style="color:#CBD5E1;text-decoration:none;">개인정보처리방침</a><a href="/terms" style="color:#CBD5E1;text-decoration:none;">청소년보호정책</a><a href="/disclaimer" style="color:#CBD5E1;text-decoration:none;">고충처리인</a></div></div>' +
        '<div>인터넷신문 명칭: ' + CFG.name + ' | 등록번호: ' + CFG.pressRegNo + ' | 발행·편집인: ' + CFG.publisherName + ' | 청소년보호책임자: ' + CFG.youthOfficer + ' | 기사배열책임자: ' + CFG.editorName + '</div>' +
        '<div style="color:#94A3B8;margin-top:6px;">본지는 신문윤리강령 및 그 실천요강을 준수하며, 저작권법에 따라 무단 전재 및 재배포를 금지합니다. Copyright © 2026 ' + CFG.name + ' All rights reserved.</div>' +
        '</div>';
    }}
  }}

  /* ========================================================================
     ARCH 2: ALBUP STYLE (`woorinote.kr` vs `justinfo.co.kr`)
     ======================================================================== */
  function applyArch2Albup(cats, isHome) {{
    var isBurgundy = CFG.shellVariant === 'albup-burgundy-tax';
    var header = document.querySelector('body > .header, body > header');
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'albup-header-shell';
      var navHtml = cats.map(function(c){{
        return '<a href="' + c.href + '" style="color:' + (c.active ? 'var(--pri)' : 'var(--txt)') + ';font-weight:' + (c.active ? '900' : '700') + ';text-decoration:none;font-size:13.5px;padding:6px 10px;">' + c.label + '</a>';
      }}).join('');
      header.innerHTML =
        '<div class="albup-header-in">' +
        '<div><span style="font-size:10.5px;font-weight:800;color:var(--pri);letter-spacing:0.08em;display:block;">' + (isBurgundy ? '⚖️ TAX & LEGAL PARTNER ADVISORY' : '🏛️ LAW & REAL ESTATE ADVISORY') + '</span>' +
        '<a href="/" style="font-family:var(--headingFont);font-size:1.5rem;font-weight:900;color:var(--pri);text-decoration:none;">' + CFG.name + '</a></div>' +
        '<nav style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;">' + navHtml + '</nav>' +
        '<a class="albup-checklist-badge" href="/?cat=' + encodeURIComponent((CFG.categories && CFG.categories[0]) || '') + '">📋 자격·조건 체크리스트</a>' +
        '</div>';
    }}

    var layout = document.querySelector('.layout');
    if (layout) layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    if (!isHome) {{
      var wrap = document.querySelector('.main .wrap, main.page');
      var info = extractArticleMeta();
      var contentEl = document.querySelector('.content, article.gs-article');
      if (wrap && info.h1 && !wrap.querySelector('.albup-breadcrumb')) {{
        var bc = document.createElement('nav');
        bc.className = 'albup-breadcrumb';
        bc.innerHTML = '<a href="/" style="color:var(--muted);text-decoration:none;">홈</a> <span>&gt;</span> <span>전문가 칼럼</span> <span>&gt;</span> <strong>' + info.cat + '</strong>';
        wrap.insertBefore(bc, info.h1);

        var h2List = contentEl ? Array.from(contentEl.querySelectorAll('h2')) : [];
        var bullets = h2List.slice(0, 3).map(function(h){{
          return '<li><strong>' + cleanHeadingText(h.textContent) + '</strong> — 공식 기준과 필수 절차 핵심 체크</li>';
        }});
        while (bullets.length < 3) {{
          bullets.push('<li><strong>' + info.cat + ' 필수 자격 및 구비서류</strong> — 신청 전 감액·반려 사유 사전 점검</li>');
        }}

        var profBox = document.createElement('div');
        profBox.innerHTML =
          '<div class="albup-profile-card">' +
          '<div class="albup-profile-left">' +
          '<div class="albup-avatar">' + (isBurgundy ? '🧾' : '⚖️') + '</div>' +
          '<div><strong style="font-size:15px;color:var(--txt);display:block;">' + CFG.expertName + '</strong>' +
          '<span style="font-size:12.5px;color:var(--muted);">' + CFG.expertRole + ' · 작성일 ' + info.dateStr + ' · ⏱️ 예상 독서시간 ' + info.readTime + '</span></div></div>' +
          '<span class="albup-stamp-badge">' + CFG.expertBadge + '</span>' +
          '</div>' +
          '<div class="albup-summary-3line">' +
          '<h4>💡 바쁜 분들을 위한 핵심 3줄 요약 카드</h4>' +
          '<ul>' + bullets.join('') + '</ul>' +
          '</div>';
        if (info.metaEl) info.metaEl.replaceWith(profBox);
        else info.h1.insertAdjacentElement('afterend', profBox);

        /* Prefix H2s with POINT 01., POINT 02. */
        h2List.forEach(function(h, idx){{
          if (!h.querySelector('.albup-point-badge')) {{
            var cleanTxt = cleanHeadingText(h.textContent);
            var numStr = (idx + 1) < 10 ? '0' + (idx + 1) : '' + (idx + 1);
            h.innerHTML = '<span class="albup-point-badge">POINT ' + numStr + '.</span> ' + cleanTxt;
          }}
        }});

        /* Bottom FAQ Accordion + More Columns */
        if (contentEl && !wrap.querySelector('.albup-faq-section')) {{
          var faqBox = document.createElement('section');
          faqBox.className = 'albup-faq-section';
          faqBox.innerHTML =
            '<h3 style="margin:0 0 14px;font-size:17px;color:var(--pri);">💬 자주 묻는 실전 질문 (Q&amp;A 상담 아코디언)</h3>' +
            '<details class="albup-faq-item" open><summary><span>Q1. ' + info.cat + ' 신청 시 가장 많이 반려되는 사유는 무엇인가요?</span><span>▼</span></summary>' +
            '<div class="albup-faq-ans">A. 기준일자 소득·재산 산정 누락이나 증빙서류 발급일 경과(통상 1개월 이내 발급분 유효)가 가장 흔한 반려 사유입니다. 본문 상단의 비교표를 먼저 대조해 보세요.</div></details>' +
            '<details class="albup-faq-item"><summary><span>Q2. 온라인 신청과 오프라인 방문 접수 중 무엇이 유리한가요?</span><span>▼</span></summary>' +
            '<div class="albup-faq-ans">A. 온라인(정부24·홈택스·청약홈 등) 신청 시 수수료 감면 및 처리 상태 실시간 조회가 가능하여 평균 3~5영업일 빠르게 처리됩니다.</div></details>' +
            '<details class="albup-faq-item"><summary><span>Q3. 대리인 신청이나 사후 이의신청 절차도 가능한가요?</span><span>▼</span></summary>' +
            '<div class="albup-faq-ans">A. 위임장과 신분증 지참 시 대리 접수가 가능하며, 결과 통보일로부터 30~90일 이내에 공식 이의신청 절차를 진행할 수 있습니다.</div></details>' +
            '<div class="albup-more-columns"><strong style="display:block;font-size:14px;color:var(--pri);margin-bottom:8px;">📚 다른 전문가 칼럼 더보기</strong>' +
            '<div style="display:flex;flex-direction:column;gap:6px;font-size:13.5px;">' +
            (CFG.categories || []).map(function(c){{ return '<a href="/?cat=' + encodeURIComponent(c) + '" style="color:var(--txt);text-decoration:none;">• [' + c + '] 2026 최신 법령·제도 개정 기준 및 실무 체크리스트 →</a>'; }}).join('') +
            '</div></div>';
          contentEl.insertAdjacentElement('afterend', faqBox);
        }}
      }}
    }}
  }}

  /* ========================================================================
     ARCH 3: TOSS FEED / FINTECH STYLE (`meganote.kr`, `smilenote.kr`)
     ======================================================================== */
  function applyArch3Toss(cats, isHome) {{
    var header = document.querySelector('body > .header, body > header');
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'toss-pill-header-wrap';
      var pills = cats.map(function(c){{
        return '<a class="toss-nav-pill' + (c.active ? ' active' : '') + '" href="' + c.href + '">' + c.label + '</a>';
      }}).join('');
      header.innerHTML =
        '<div class="toss-pill-header">' +
        '<div style="display:flex;align-items:center;gap:10px;">' +
        '<span style="width:32px;height:32px;border-radius:10px;background:var(--pri);color:#fff;display:inline-flex;align-items:center;justify-content:center;font-weight:900;font-size:15px;">T</span>' +
        '<a href="/" style="font-size:1.25rem;font-weight:900;color:#191F28;text-decoration:none;letter-spacing:-0.03em;">' + CFG.name + '</a></div>' +
        '<nav class="toss-nav-pills">' + pills + '</nav>' +
        '</div>';
    }}

    var layout = document.querySelector('.layout');
    if (!layout || layout.hasAttribute('data-arch-layout')) return;
    layout.setAttribute('data-arch-layout', '1');
    layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    if (!isHome) {{
      var info = extractArticleMeta();
      var wrap = document.querySelector('.main .wrap');
      var contentEl = document.querySelector('.content');
      if (wrap && contentEl) {{
        /* Build Left Sticky Scrollspy TOC (220px) */
        var h2s = Array.from(contentEl.querySelectorAll('h2'));
        var tocLinks = h2s.map(function(h, idx){{
          if (!h.id) h.id = 'toss-sec-' + (idx + 1);
          var label = cleanHeadingText(h.textContent);
          h.textContent = label;
          return '<a class="toss-toc-link' + (idx === 0 ? ' active' : '') + '" data-target="' + h.id + '" href="#' + h.id + '">' +
            '<span class="toss-toc-dot"></span><span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + label + '</span></a>';
        }}).join('');

        var spyAside = document.createElement('aside');
        spyAside.className = 'toss-scrollspy-aside';
        spyAside.innerHTML =
          '<div class="toss-scrollspy-title">목차 따라가기</div>' +
          '<nav id="tossScrollspyNav">' + tocLinks + '</nav>' +
          '<div style="margin-top:16px;padding-top:14px;border-top:1px solid #E5E8EB;font-size:11.5px;color:#8B95A1;">현재 읽고 있는 섹션에 파란 불이 켜집니다.</div>';
        layout.insertBefore(spyAside, layout.firstChild);

        /* Wrap Title + Meta into Top Toss Hero Card */
        var heroCard = document.createElement('section');
        heroCard.className = 'toss-hero-card';
        heroCard.innerHTML =
          '<span class="toss-step-chip">' + info.cat + ' · TOSS FEED BRIEF</span>' +
          '<h1 style="margin:0 0 10px;font-size:1.75rem;color:#191F28;">' + info.title + '</h1>' +
          '<div style="font-size:13px;color:#6B7684;">업데이트 ' + info.dateStr + ' · ' + info.readTime + ' 만에 술술 읽히는 카드형 가이드</div>';
        if (info.h1) info.h1.remove();
        if (info.metaEl) info.metaEl.remove();
        wrap.insertBefore(heroCard, wrap.firstChild);

        /* Split each H2 section inside .content into independent white rounded cards (.toss-section-card) */
        var children = Array.from(contentEl.childNodes);
        var cardsFragment = document.createDocumentFragment();
        var currentCard = null;
        var stepCount = 0;

        children.forEach(function(node){{
          if (node.nodeType === 1 && node.tagName === 'H2') {{
            stepCount++;
            currentCard = document.createElement('section');
            currentCard.className = 'toss-section-card';
            var chip = document.createElement('span');
            chip.className = 'toss-step-chip';
            chip.textContent = 'STEP 0' + stepCount;
            currentCard.appendChild(chip);
            currentCard.appendChild(node);
            cardsFragment.appendChild(currentCard);
          }} else if (node.nodeType === 1 && node.classList && node.classList.contains('ad')) {{
            cardsFragment.appendChild(node);
          }} else {{
            if (!currentCard) {{
              currentCard = document.createElement('section');
              currentCard.className = 'toss-section-card';
              cardsFragment.appendChild(currentCard);
            }}
            currentCard.appendChild(node);
          }}
        }});
        contentEl.innerHTML = '';
        contentEl.style.maxWidth = '100%';
        contentEl.appendChild(cardsFragment);

        /* Scrollspy active highlight listener */
        window.addEventListener('scroll', function(){{
          var activeId = h2s.length ? h2s[0].id : '';
          h2s.forEach(function(h){{
            var rect = h.getBoundingClientRect();
            if (rect.top <= 180) activeId = h.id;
          }});
          document.querySelectorAll('#tossScrollspyNav .toss-toc-link').forEach(function(a){{
            a.classList.toggle('active', a.getAttribute('data-target') === activeId);
          }});
        }}, {{ passive: true }});
      }}
    }}
  }}

  /* ========================================================================
     ARCH 4: MS LEARN / APPLE DOCS STYLE (`topnote.kr`, `maxnote.kr`)
     ======================================================================== */
  function applyArch4MsLearn(cats, isHome) {{
    var header = document.querySelector('body > .header, body > header');
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'msdocs-header';
      header.innerHTML =
        '<div class="msdocs-header-in">' +
        '<div style="display:flex;align-items:center;gap:12px;">' +
        '<a href="/" style="color:#F8FAFC;font-weight:900;font-size:1.25rem;text-decoration:none;font-family:var(--headingFont);">📘 ' + CFG.name + '</a>' +
        '<span class="msdocs-ver-badge">' + CFG.docVersion + '</span></div>' +
        '<form class="msdocs-search-box" onsubmit="event.preventDefault();var q=this.querySelector(&apos;input&apos;).value.trim();location.href=q?&apos;/?q=&apos;+encodeURIComponent(q):&apos;/&apos;;">' +
        '<span>🔍</span><input type="search" placeholder="기술 문서 검색..." style="border:none;background:transparent;color:#F8FAFC;outline:none;font-size:12.5px;flex:1;" />' +
        '<kbd style="background:#1E293B;color:#CBD5E1;border-color:#475569;">Ctrl+K</kbd></form>' +
        '</div>';
    }}

    var layout = document.querySelector('.layout');
    if (!layout || layout.hasAttribute('data-arch-layout')) return;
    layout.setAttribute('data-arch-layout', '1');
    layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    /* Left Folder Tree Sidebar */
    var treeSidebar = document.createElement('aside');
    treeSidebar.className = 'msdocs-tree-sidebar';
    var treeHtml = cats.map(function(c, idx){{
      return '<div class="msdocs-tree-group">' +
        '<div class="msdocs-tree-folder">📂 ' + c.label + '</div>' +
        '<a class="msdocs-tree-item' + (c.active ? ' active' : '') + '" href="' + c.href + '">📄 ' + c.label + ' 표준 매뉴얼</a>' +
        (idx > 0 ? '<a class="msdocs-tree-item" href="' + c.href + '">📄 트러블슈팅 &amp; 단축키</a>' : '') +
        '</div>';
    }}).join('');
    treeSidebar.innerHTML =
      '<div style="font-family:var(--monoFont);font-size:11px;font-weight:800;color:var(--pri);margin-bottom:12px;">DOCUMENTATION TREE</div>' +
      treeHtml;
    layout.insertBefore(treeSidebar, layout.firstChild);

    /* Right Minimap Sidebar */
    var minimap = document.createElement('aside');
    minimap.className = 'msdocs-minimap-aside';
    var h2s = Array.from(document.querySelectorAll('.content h2'));
    var miniLinks = h2s.map(function(h, idx){{
      if (!h.id) h.id = 'msdoc-sec-' + (idx + 1);
      var cleanTxt = cleanHeadingText(h.textContent);
      h.textContent = cleanTxt;
      return '<a href="#' + h.id + '" style="display:block;font-size:12.5px;color:#475569;text-decoration:none;padding:5px 0 5px 10px;border-left:2px solid #CBD5E1;">' + cleanTxt + '</a>';
    }}).join('');
    minimap.innerHTML =
      '<div style="font-size:12px;font-weight:900;color:#0F172A;margin-bottom:10px;">📑 On this page (미니맵)</div>' +
      '<div style="margin-bottom:20px;">' + (miniLinks || '<span style="font-size:12px;color:#64748B;">문서 섹션 자동 인덱싱</span>') + '</div>' +
      buildStickyAdSlotHtml();
    layout.appendChild(minimap);

    if (!isHome) {{
      var contentEl = document.querySelector('.content');
      if (contentEl) {{
        /* Numbered Manual Step Boxes & <kbd> keycaps */
        h2s.forEach(function(h, idx){{
          var badge = document.createElement('div');
          badge.innerHTML = '<span class="msdocs-step-num">MANUAL STEP 0' + (idx + 1) + '</span>';
          h.insertBefore(badge, h.firstChild);
        }});
        /* Add interactive feedback widget at bottom */
        if (!document.querySelector('.msdocs-feedback-box')) {{
          var fb = document.createElement('section');
          fb.className = 'msdocs-feedback-box';
          fb.innerHTML =
            '<div><strong style="font-size:14.5px;color:#0F172A;display:block;">이 가이드가 문제 해결에 도움이 되었나요?</strong>' +
            '<span style="font-size:12px;color:#64748B;">피드백은 공식 기술 매뉴얼 정확도 향상에 반영됩니다. (단축키 <kbd>Ctrl</kbd> + <kbd>F</kbd> 로 키워드 검색)</span></div>' +
            '<div style="display:flex;gap:8px;" id="msdocsFbBtns">' +
            '<button type="button" class="msdocs-fb-btn" onclick="this.parentElement.innerHTML=&apos;<strong style=color:#2563EB>✓ 소중한 피드백 감사합니다!</strong>&apos;">👍 도움됨</button>' +
            '<button type="button" class="msdocs-fb-btn" onclick="this.parentElement.innerHTML=&apos;<strong style=color:#475569>✓ 추가 보완 요청이 접수되었습니다.</strong>&apos;">👎 추가 설명 필요</button></div>';
          contentEl.insertAdjacentElement('afterend', fb);
        }}
      }}
    }}
  }}

  /* ========================================================================
     ARCH 5: LONELY PLANET / BRUNCH STYLE (`tripmarvel.com`, `nolplace.com`)
     ======================================================================== */
  function applyArch5LonelyPlanet(cats, isHome) {{
    var header = document.querySelector('body > .header, body > header');
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'lp-header-shell';
      var navLinks = cats.map(function(c){{
        return '<a href="' + c.href + '" style="padding:6px 14px;border-radius:999px;font-size:13px;font-weight:700;text-decoration:none;background:' + (c.active ? 'var(--pri)' : 'transparent') + ';color:' + (c.active ? '#fff' : 'var(--txt)') + ';">' + c.label + '</a>';
      }}).join('');
      header.innerHTML =
        '<div style="max-width:1200px;margin:0 auto;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">' +
        '<div><span style="font-size:10px;letter-spacing:0.14em;color:var(--muted);font-weight:800;display:block;">' + CFG.badgeLabel + '</span>' +
        '<a href="/" style="font-family:var(--headingFont);font-size:1.65rem;font-weight:900;color:var(--pri);text-decoration:none;">' + CFG.name + '</a></div>' +
        '<nav style="display:flex;gap:6px;flex-wrap:wrap;">' + navLinks + '</nav></div>';
    }}

    var layout = document.querySelector('.layout');
    if (layout) layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    if (!isHome && layout && !document.querySelector('.lp-cover-hero')) {{
      var info = extractArticleMeta();
      var isSunset = CFG.shellVariant === 'brunch-sunset-hotspot';
      var bgStyle = isSunset
        ? 'background:radial-gradient(circle at 80% 20%, rgba(251,191,36,0.35) 0%, transparent 45%), linear-gradient(135deg, #431407 0%, #9A3412 50%, #EA580C 100%);'
        : 'background:radial-gradient(circle at 85% 20%, rgba(217,119,6,0.32) 0%, transparent 45%), linear-gradient(135deg, #064E3B 0%, #1B4332 52%, #2D6A4F 100%);';
      var cover = document.createElement('section');
      cover.className = 'lp-cover-hero';
      cover.setAttribute('style', bgStyle);
      cover.innerHTML =
        '<div class="lp-cover-scrim"></div>' +
        '<div class="lp-cover-content">' +
        '<span class="lp-cover-kicker">MAGAZINE COVER STORY · ' + info.cat + '</span>' +
        '<h1>' + info.title + '</h1>' +
        '<div style="font-size:14px;color:rgba(255,255,255,0.92);display:flex;align-items:center;gap:12px;flex-wrap:wrap;">' +
        '<span>🧭 에디토리얼 코스 가이드</span><span>·</span><span>📅 ' + info.dateStr + '</span><span>·</span><span>⏱️ 읽는 시간 ' + info.readTime + '</span></div>' +
        '</div>';
      layout.parentNode.insertBefore(cover, layout);
      if (info.h1) info.h1.style.display = 'none';
      if (info.metaEl) info.metaEl.style.display = 'none';

      var contentEl = document.querySelector('.content');
      if (contentEl) {{
        var quickGrid = document.createElement('div');
        quickGrid.className = 'lp-quick-info-grid';
        quickGrid.innerHTML =
          '<div class="lp-quick-info-cell"><strong>📍 핵심 포인트</strong><span>' + info.cat + ' 필수 동선 &amp; 사전 예약처</span></div>' +
          '<div class="lp-quick-info-cell"><strong>🕒 소요시간 / 추천시기</strong><span>평균 2~3시간 코스 · 주말 오전 권장</span></div>' +
          '<div class="lp-quick-info-cell"><strong>🚗 주차·이동 팁</strong><span>공영/전용 주차장 및 대중교통 연계 확인</span></div>';
        contentEl.insertBefore(quickGrid, contentEl.firstChild);

        Array.from(contentEl.querySelectorAll('h2')).forEach(function(h, idx){{
          var cleanTxt = cleanHeadingText(h.textContent);
          h.innerHTML = '<span class="lp-course-badge">Course ' + (idx + 1) + ' ➔</span> ' + cleanTxt;
        }});
      }}
    }}
  }}

  /* ========================================================================
     ARCH 6: ASAN MEDICAL / WEBMD STYLE (`healthcox.com`)
     ======================================================================== */
  function applyArch6WebMD(cats, isHome) {{
    var header = document.querySelector('body > .header, body > header');
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'med-header-shell';
      var navHtml = cats.map(function(c){{
        return '<a href="' + c.href + '" style="padding:7px 14px;border-radius:6px;font-size:13.5px;font-weight:800;text-decoration:none;background:' + (c.active ? '#0F766E' : '#F0FDFA') + ';color:' + (c.active ? '#fff' : '#0F766E') + ';">' + c.label + '</a>';
      }}).join('');
      header.innerHTML =
        '<div style="max-width:1140px;margin:0 auto;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">' +
        '<div style="display:flex;align-items:center;"><span class="med-cross-symbol">➕</span>' +
        '<div><a href="/" style="font-size:1.45rem;font-weight:900;color:#0F766E;text-decoration:none;">' + CFG.name + '</a>' +
        '<span style="display:block;font-size:11px;color:#475569;font-weight:700;">CLINICAL INFORMATION &amp; SYMPTOM CHECKSHEET</span></div></div>' +
        '<nav style="display:flex;gap:6px;flex-wrap:wrap;">' + navHtml + '</nav></div>';
    }}

    var layout = document.querySelector('.layout');
    if (!layout || layout.hasAttribute('data-arch-layout')) return;
    layout.setAttribute('data-arch-layout', '1');
    layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    if (!isHome) {{
      var wrap = document.querySelector('.main .wrap');
      var info = extractArticleMeta();
      var contentEl = document.querySelector('.content');
      if (wrap) {{
        var banner = document.createElement('div');
        banner.className = 'med-factcheck-banner';
        banner.innerHTML =
          '<span>🩺 <strong>건강정보 에디토리얼 가이드라인 검수 완료</strong> · 의학적 진단을 대신하지 않습니다.</span>' +
          '<span style="font-size:11.5px;background:#0F766E;color:#fff;padding:3px 9px;border-radius:999px;">임상건강정보 기준 준수</span>';
        wrap.insertBefore(banner, wrap.firstChild);

        if (contentEl) {{
          var h2s = Array.from(contentEl.querySelectorAll('h2'));
          var checks = h2s.slice(0, 3).map(function(h){{
            return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13.5px;color:#134E4A;"><span>☑️</span><strong>' + cleanHeadingText(h.textContent) + '</strong></div>';
          }}).join('');
          var sheet = document.createElement('div');
          sheet.className = 'med-checksheet-box';
          sheet.innerHTML = '<div class="med-checksheet-title">📋 임상 증상·관리 핵심 체크시트 (Clinical Checksheet)</div>' + checks;
          contentEl.insertBefore(sheet, contentEl.firstChild);
        }}
      }}

      var medSide = document.createElement('aside');
      medSide.className = 'med-clinical-sidebar';
      medSide.innerHTML =
        '<div style="background:#FFFFFF;border:1px solid #99F6E4;border-top:3px solid #0F766E;border-radius:10px;padding:18px;">' +
        '<h4 style="margin:0 0 12px;font-size:14.5px;color:#0F766E;">🏥 진료과·건강 칼럼 추천</h4>' +
        '<div style="display:flex;flex-direction:column;gap:10px;font-size:13px;">' +
        (CFG.categories || []).map(function(c){{ return '<a href="/?cat=' + encodeURIComponent(c) + '" style="color:#134E4A;text-decoration:none;font-weight:700;padding-bottom:8px;border-bottom:1px dashed #CCFBF1;">• [' + c + '] 증상별 자가진단 및 예방 수칙 →</a>'; }}).join('') +
        '</div></div>' + buildStickyAdSlotHtml();
      layout.appendChild(medSide);
    }}
  }}

  /* ========================================================================
     ARCH 7: DANAWA DPG / CONSUMER REPORTS (`must-pick.com`, `baronote.kr`)
     ======================================================================== */
  function applyArch7Danawa(cats, isHome) {{
    var header = document.querySelector('body > .header, body > header.hd, body > header');
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'dpg-two-tier-header';
      var tabs = cats.map(function(c){{
        return '<a href="' + c.href + '" style="padding:10px 16px;font-size:13.5px;font-weight:800;text-decoration:none;color:' + (c.active ? 'var(--sec)' : 'var(--txt)') + ';border-bottom:3px solid ' + (c.active ? 'var(--sec)' : 'transparent') + ';">' + c.label + '</a>';
      }}).join('');
      header.innerHTML =
        '<div class="dpg-util-bar"><div class="dpg-util-in">' +
        '<span>📊 <strong>' + CFG.badgeLabel + '</strong></span>' +
        '<span>공식 스펙·혜택 데이터 대조 센터 | 컨슈머리포트 검증</span></div></div>' +
        '<div style="max-width:1160px;margin:0 auto;padding:14px 24px 0;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">' +
        '<a href="/" style="font-size:1.55rem;font-weight:900;color:var(--pri);text-decoration:none;">' + CFG.name + '</a>' +
        '<nav style="display:flex;gap:4px;flex-wrap:wrap;">' + tabs + '</nav></div>';
    }}

    var layout = document.querySelector('.layout');
    if (layout) layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    if (!isHome) {{
      var wrap = document.querySelector('.main .wrap, main.page');
      var info = extractArticleMeta();
      var contentEl = document.querySelector('.content, article.gs-article');
      if (wrap && contentEl && !wrap.querySelector('.dpg-scoreboard-box')) {{
        var scoreBox = document.createElement('div');
        scoreBox.innerHTML =
          '<div class="dpg-scoreboard-box">' +
          '<div class="dpg-score-cell"><span class="dpg-score-label">컨슈머리포트 추천지수</span><strong class="dpg-score-val">' + CFG.scoreRating + '</strong></div>' +
          '<div class="dpg-score-cell"><span class="dpg-score-label">핵심 혜택·스펙 요약</span><strong class="dpg-score-val" style="color:#38BDF8;">' + info.cat + ' 공식 검증</strong></div>' +
          '<div class="dpg-score-cell"><span class="dpg-score-label">신청·적용 난이도</span><strong class="dpg-score-val" style="color:#4ADE80;">' + CFG.scoreDifficulty + '</strong></div>' +
          '</div>' +
          '<div class="dpg-pros-cons-grid">' +
          '<div class="dpg-pros-box"><strong style="color:#065F46;display:block;margin-bottom:6px;">👍 핵심 강점 및 혜택 포인트</strong><span>• 공식 기준 충족 시 비용·수수료 절감 및 즉시 혜택 적용<br/>• 모바일/PC 비대면 원스톱 조회 지원</span></div>' +
          '<div class="dpg-cons-box"><strong style="color:#92400E;display:block;margin-bottom:6px;">⚠️ 신청·선택 전 필수 체크사항</strong><span>• 예산 소진 또는 기준일 경과 전 사전 확인 필수<br/>• 세부 등급·모델별 조건표 대조 권장</span></div>' +
          '</div>';
        contentEl.insertBefore(scoreBox, contentEl.firstChild);
      }}
    }}
  }}

  /* ========================================================================
     ARCH 8: TODAYHOUSE / 29CM STYLE (`must-joy.com`, `soulnote.kr`, `joynote.kr`)
     ======================================================================== */
  function applyArch8Todayhouse(cats, isHome) {{
    var header = document.querySelector('body > .header, body > header');
    var icons = ['✨', '🌿', '☕', '🎨', '🐾'];
    if (header && !header.hasAttribute('data-arch-built')) {{
      header.setAttribute('data-arch-built', '1');
      header.className = 'th-boutique-header';
      var pills = cats.map(function(c, idx){{
        return '<a class="th-pill-cat' + (c.active ? ' active' : '') + '" href="' + c.href + '"><span>' + icons[idx % icons.length] + '</span><span>' + c.label + '</span></a>';
      }}).join('');
      header.innerHTML =
        '<div class="th-ribbon-banner">' + CFG.ribbonText + '</div>' +
        '<div style="max-width:1160px;margin:0 auto;padding:18px 24px 6px;text-align:center;">' +
        '<a href="/" style="font-family:var(--headingFont);font-size:1.75rem;font-weight:900;color:var(--pri);text-decoration:none;letter-spacing:-0.02em;">' + CFG.name + '</a>' +
        '<div style="font-size:12px;color:var(--muted);margin-top:2px;">' + CFG.slogan + '</div></div>' +
        '<nav class="th-pill-cat-bar">' + pills + '</nav>';
    }}

    var layout = document.querySelector('.layout');
    if (layout) layout.querySelectorAll(':scope > .sidebar').forEach(function(s){{ s.remove(); }});

    if (!isHome) {{
      var info = extractArticleMeta();
      var contentEl = document.querySelector('.content, article.gs-article');
      if (contentEl && !document.querySelector('.th-speech-note')) {{
        var speech = document.createElement('div');
        speech.className = 'th-speech-note';
        speech.innerHTML =
          '<div style="width:44px;height:44px;border-radius:50%;background:var(--pri);color:#fff;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;">' + CFG.h2IconBadge + '</div>' +
          '<div><strong style="font-size:13.5px;color:var(--pri);display:block;margin-bottom:4px;">에디터의 큐레이션 노트 (Editor&apos;s Note)</strong>' +
          '<span style="font-size:13.5px;color:var(--txt);line-height:1.6;">오늘 소개하는 <strong>' + info.cat + '</strong> 가이드는 실제 이용자와 큐레이터가 직접 확인한 핵심 포인트만 담았습니다.</span></div>';
        contentEl.insertBefore(speech, contentEl.firstChild);

        Array.from(contentEl.querySelectorAll('h2')).forEach(function(h){{
          if (!h.querySelector('.th-h2-icon')) {{
            h.innerHTML = '<span class="th-h2-icon">' + CFG.h2IconBadge + '</span>' + cleanHeadingText(h.textContent);
          }}
        }});

        var relGrid = document.createElement('section');
        relGrid.className = 'th-related-3col-wrap';
        var cards = (CFG.categories || []).slice(0, 3).map(function(catName, idx){{
          return '<a class="th-mag-card" href="/?cat=' + encodeURIComponent(catName) + '">' +
            '<div style="aspect-ratio:4/3;background:linear-gradient(135deg, var(--pri) 0%, var(--sec) 100%);color:#fff;padding:16px;display:flex;flex-direction:column;justify-content:space-between;">' +
            '<span style="font-size:11px;font-weight:800;background:rgba(0,0,0,0.28);padding:3px 9px;border-radius:999px;width:fit-content;">' + CFG.h2IconBadge + ' ' + catName + '</span>' +
            '<strong style="font-size:14px;line-height:1.35;">' + catName + ' 에디터 추천 베스트 가이드 모아보기</strong></div>' +
            '<div style="padding:12px 14px;font-size:12px;color:var(--muted);font-weight:700;display:flex;justify-content:space-between;"><span>CURATION #' + (idx + 1) + '</span><span style="color:var(--pri);">보러가기 →</span></div></a>';
        }}).join('');
        relGrid.innerHTML =
          '<h3 style="margin:0;font-size:16px;color:var(--pri);">' + CFG.h2IconBadge + ' 함께 읽으면 좋은 큐레이션 매거진 (3열 포토 그리드)</h3>' +
          '<div class="th-related-3col-grid">' + cards + '</div>';
        contentEl.insertAdjacentElement('afterend', relGrid);
      }}
    }}
  }}

  function enhanceCommonAdsAndCaptures(isHome) {{
    var contentEl = document.querySelector('.content, article.gs-article');
    if (!isHome) {{
      var topAd = document.querySelector('.main .wrap > .ad, main.page > .ad');
      if (topAd) topAd.classList.add('adsense-slot', 'adsense-slot--hero-below');
    }}
    if (contentEl) {{
      var midAd = contentEl.querySelector('.ad');
      if (midAd) midAd.classList.add('adsense-slot', 'adsense-slot--in-article');
      contentEl.querySelectorAll('figure.post-image a[aria-label*="원본"] img, figure img').forEach(function(img){{
        if (img.closest('a[aria-label*="원본"]')) img.classList.add('guide-capture-img');
      }});
    }}
  }}

  function applyBaro8ArchitectureDOM() {{
    var isHome = !!document.getElementById('postGrid');
    document.body.setAttribute('data-domain', CFG.domain);
    document.body.setAttribute('data-shell-family', CFG.shellFamily);
    document.body.setAttribute('data-shell-variant', CFG.shellVariant);
    document.body.setAttribute('data-page-type', isHome ? 'home' : 'article');

    scrubLegacyAndAdminUI(document);
    var cats = collectCategories();

    if (CFG.shellFamily === 'arch1-wikitree') applyArch1Wikitree(cats, isHome);
    else if (CFG.shellFamily === 'arch2-albup') applyArch2Albup(cats, isHome);
    else if (CFG.shellFamily === 'arch3-toss') applyArch3Toss(cats, isHome);
    else if (CFG.shellFamily === 'arch4-mslearn') applyArch4MsLearn(cats, isHome);
    else if (CFG.shellFamily === 'arch5-lonelyplanet') applyArch5LonelyPlanet(cats, isHome);
    else if (CFG.shellFamily === 'arch6-webmd') applyArch6WebMD(cats, isHome);
    else if (CFG.shellFamily === 'arch7-danawa') applyArch7Danawa(cats, isHome);
    else applyArch8Todayhouse(cats, isHome);

    enhanceCommonAdsAndCaptures(isHome);
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', applyBaro8ArchitectureDOM);
  }} else {{
    applyBaro8ArchitectureDOM();
  }}
}})();
""".strip()

    theme_block = (
        f"<!-- BAROLAB_1TO1_THEME_START -->\n"
        f'<link rel="stylesheet" href="{font_url}" />\n'
        f'<style id="barolab-domain-theme">\n{css}\n</style>\n'
        f"<script>\n{enhancer_js}\n</script>\n"
        f"<!-- BAROLAB_1TO1_THEME_END -->"
    )
    return (cleaned_base + "\n" + theme_block).strip()


def generate_design_preview_html() -> Path:
    """Generate `cf_posting/design-preview/index.html` showcasing all 8 Architectures & 16 Domains."""
    preview_dir = BASE_DIR / "design-preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    target = preview_dir / "index.html"
    rows = []
    for domain, spec in DOMAIN_IDENTITY_SPECS.items():
        rows.append(
            f"<div style='padding:14px;border:1px solid #334155;border-radius:8px;margin-bottom:10px;'>"
            f"<strong>{html.escape(spec['name'])} ({domain})</strong> — <code>{spec['shellFamily']} / {spec['shellVariant']}</code><br/>"
            f"<small>{html.escape(spec['archetypeLabel'])}</small></div>"
        )
    cards = "".join(
        f'<article class="card{(" no-image" if i == 2 else "")}"><a class="card-link" href="https://www.{domain}/">'
        f'<div class="thumb"><div class="thumb-empty" style="background:{spec["colors"]["primary"]}"></div></div>'
        f'<div class="card-body"><h3>{html.escape(spec["name"])} — 세로형 카드 제목 두 줄 미리보기</h3>'
        '<p class="excerpt">이미지 아래 본문이 카드 너비 전체를 사용합니다. 제목은 최대 두 줄, 요약은 최대 세 줄을 표시하며 화면 폭에 따라 세 열, 두 열, 한 열로 전환됩니다. 이 문장은 줄 제한을 확인하기 위한 미리보기 설명입니다.</p>'
        f'<div class="meta">{domain} · 레이아웃 미리보기</div></div></a></article>'
        for i, (domain, spec) in enumerate(DOMAIN_IDENTITY_SPECS.items())
    )
    target.write_text(
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>16 CF 카드 레이아웃 미리보기</title><style>body{background:#f4f6f8;color:#17212b;font-family:system-ui;margin:0}"
        ".card{background:#fff;border:1px solid #dbe1e8;border-radius:12px}.card-link{color:inherit;text-decoration:none}"
        ".excerpt,.meta{color:#526170}header,details{max-width:1072px;margin:24px auto;padding:0 24px}</style><style>" + CARD_CSS + "</style></head>"
        "<body><header><h1>16개 CF 블로그 카드 미리보기</h1><p>1024px 이상 3열 · 640–1023px 2열 · 640px 미만 1열. 이미지 16:9, 본문 전체 너비.</p></header>"
        '<div class="layout"><main class="main-area"><section id="postGrid" class="grid">' + cards + '</section></main></div>'
        '<details><summary>기존 도메인별 디자인 구성</summary>' + "".join(rows) + "</details></body></html>",
        encoding="utf-8",
    )
    return target


def sync_all_live_cf_domains() -> Dict[str, Any]:
    """
    Push each domain's 1:1 custom CSS, font import, `theme_color`, `font_family`,
    Clean Public View, and 8-Architecture Independent DOM Transformer to all 16 live CF domains via `/api/settings`.
    """
    import requests
    from dotenv import dotenv_values

    env_values = dotenv_values(BASE_DIR / ".env")
    keys_file = BASE_DIR / "data" / "secure" / "cf_blog_keys.json"
    api_keys = json.loads(keys_file.read_text(encoding="utf-8")) if keys_file.is_file() else {}

    results: Dict[str, Any] = {}
    for domain, spec in DOMAIN_IDENTITY_SPECS.items():
        prefix = domain.split(".")[0].replace("-", "").upper()
        password = env_values.get(f"{prefix}_CF_ADMIN_PASSWORD", "")
        api_key = api_keys.get(domain, "")
        headers: Dict[str, str] = {}
        try:
            if password:
                login_resp = requests.post(
                    f"https://www.{domain}/api/auth/login",
                    json={"password": password},
                    timeout=12,
                )
                if login_resp.status_code == 200 and login_resp.json().get("token"):
                    headers["Authorization"] = "Bearer " + login_resp.json()["token"]
            if not headers and api_key:
                headers["x-api-key"] = api_key

            get_resp = requests.get(f"https://www.{domain}/api/settings", headers=headers, timeout=12)
            get_resp.raise_for_status()
            current_settings = get_resp.json().get("settings", {})

            existing_head = current_settings.get("adsense_code", "")
            ad_mid = current_settings.get("ad_mid_html", "")
            new_head = build_live_cf_head_injection(domain, existing_head, ad_mid)

            payload = {
                "blog_name": spec["name"],
                "blog_description": spec["subTopic"],
                "categories": ",".join(spec.get("categories", [])),
                "theme_color": spec["colors"]["primary"],
                "font_family": spec["typography"]["cfFontFamily"],
                "adsense_code": new_head,
            }
            put_resp = requests.put(
                f"https://www.{domain}/api/settings",
                headers={**headers, "Content-Type": "application/json"},
                json=payload,
                timeout=15,
            )
            put_resp.raise_for_status()
            results[domain] = {
                "status": "ok",
                "httpStatus": put_resp.status_code,
                "shellFamily": spec["shellFamily"],
                "shellVariant": spec["shellVariant"],
                "primaryColor": spec["colors"]["primary"],
            }
        except Exception as exc:
            results[domain] = {"status": "error", "error": str(exc)}
    return results


DOMAIN_WORKER_NAMES: Dict[str, str] = {
    "must-good.com": "mustgood",
    "baronote.kr": "baronote",
    "justinfo.co.kr": "justinfo",
    "topnote.kr": "topnote",
    "meganote.kr": "meganote",
    "smilenote.kr": "smilenote",
    "healthcox.com": "healthcox",
    "maxnote.kr": "maxnote",
    "must-joy.com": "mustjoy",
    "tripmarvel.com": "tripmarvel",
    "must-pick.com": "mustpick",
    "woorinote.kr": "woorinote",
    "daynote.kr": "daynote",
    "nolplace.com": "panda-01",
    "soulnote.kr": "soulnote",
    "joynote.kr": "joynote",
}


def _scrub_worker_ssr_public_html(js_code: str) -> str:
    """Bust Cloudflare Worker Edge Cache (`caches.default`) so new 8-architecture DOM layouts appear in 0s."""
    js_code = re.sub(
        r'const cacheKey = new Request\(url\.toString\(\)[^,]*,\s*\{\s*method:\s*"GET"\s*\}\);',
        'const cacheKey = new Request(url.toString() + (url.search ? "&" : "?") + "_baro_v=20261018_arch8_v3", { method: "GET" });',
        js_code,
    )
    return js_code


def patch_live_cf_worker_scripts() -> Dict[str, Any]:
    """Redeploy all 16 Cloudflare Worker scripts with updated cache key to bust stale edge cache immediately."""
    import requests
    from dotenv import dotenv_values

    env_baro = dotenv_values(BASE_DIR / ".env")
    env_income_path = Path(r"Y:\10_Project\baro-income\.env")
    if not env_income_path.is_file():
        env_income_path = BASE_DIR.parent / "baro-income" / ".env"
    env_income = dotenv_values(env_income_path) if env_income_path.is_file() else {}
    cf_token = env_baro.get("CLOUDFLARE_API_TOKEN") or env_income.get("CLOUDFLARE_API_TOKEN") or ""
    cf_account = (
        env_baro.get("CLOUDFLARE_ACCOUNT_ID")
        or env_income.get("CLOUDFLARE_ACCOUNT_ID")
        or "ee7fa7b4dbbf33b2ec430488301505a5"
    )
    if not cf_token:
        return {"_error": {"status": "error", "error": "CLOUDFLARE_API_TOKEN not found"}}

    headers = {"Authorization": f"Bearer {cf_token}"}
    results: Dict[str, Any] = {}

    for domain, worker_name in DOMAIN_WORKER_NAMES.items():
        try:
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/workers/scripts/{worker_name}"
            get_resp = requests.get(url, headers=headers, timeout=20)
            get_resp.raise_for_status()
            raw_body = get_resp.text

            ctype = get_resp.headers.get("Content-Type", "")
            if "multipart/form-data" in ctype and "boundary=" in ctype:
                boundary = ctype.split("boundary=")[1].split(";")[0].strip()
                parts = raw_body.split(f"--{boundary}")
                js_code = ""
                for part in parts:
                    if 'name="index.js"' in part or "function renderHomePage(" in part:
                        split_idx = part.find("\r\n\r\n")
                        if split_idx != -1:
                            js_code = part[split_idx + 4 :].rstrip("\r\n")
                            break
                if not js_code:
                    raise ValueError("Could not extract index.js from multipart Worker response")
            else:
                js_code = raw_body

            patched_js = _scrub_worker_ssr_public_html(js_code)

            metadata = {
                "main_module": "index.js",
                "compatibility_date": "2025-10-01",
                "keep_bindings": ["secret_text", "d1", "r2_bucket", "plain_text", "kv_namespace"],
            }
            files = {
                "metadata": ("metadata.json", json.dumps(metadata), "application/json"),
                "index.js": ("index.js", patched_js.encode("utf-8"), "application/javascript+module"),
            }
            put_resp = requests.put(url, headers=headers, files=files, timeout=30)
            put_resp.raise_for_status()
            results[domain] = {
                "status": "ok",
                "worker": worker_name,
                "httpStatus": put_resp.status_code,
            }
        except Exception as exc:
            results[domain] = {"status": "error", "worker": worker_name, "error": str(exc)}
    return results


def export_all_theme_files() -> List[Path]:
    """Write individual `cf_posting/themes/{domain}.css` files, `identity_specs.json`, and `design-preview/index.html`."""
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for domain in DOMAIN_IDENTITY_SPECS:
        css_path = THEMES_DIR / f"{domain}.css"
        css_path.write_text(generate_domain_css(domain), encoding="utf-8")
        written.append(css_path)
    spec_json_path = THEMES_DIR / "identity_specs.json"
    spec_json_path.write_text(json.dumps(DOMAIN_IDENTITY_SPECS, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(spec_json_path)
    preview_path = generate_design_preview_html()
    written.append(preview_path)
    return written


if __name__ == "__main__":
    import sys
    paths = export_all_theme_files()
    print(f"Exported {len(paths)} theme artifacts to {THEMES_DIR} and design-preview/index.html")
    if "--sync-live" in sys.argv:
        sync_res = sync_all_live_cf_domains()
        ok_cnt = sum(1 for v in sync_res.values() if v.get("status") == "ok")
        print(f"Synced live CF /api/settings for {ok_cnt}/{len(sync_res)} domains:")
        for d, r in sync_res.items():
            print(f"  - {d}: {r}")
    if "--sync-workers" in sys.argv:
        w_res = patch_live_cf_worker_scripts()
        w_ok = sum(1 for v in w_res.values() if isinstance(v, dict) and v.get("status") == "ok")
        print(f"Patched SSR Worker scripts for {w_ok}/{len(w_res)} CF Workers:")
        for d, r in w_res.items():
            print(f"  - {d}: {r}")
