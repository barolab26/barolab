"""Unified corporate asset map and cross-channel synergy engine for BaroLab.

Integrates 16 Cloudflare blogs, 5 Naver blogs, KnowledgeIn, Threads,
multi-account Gemini/Codex compute, Flow image generation, and the 7:3 Account Longevity Rule.
"""

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
ROOT = Path(__file__).resolve().parents[2]

# 1. 16 Cloudflare Blogs (Cash-Cow AdSense Conversion Hubs — Strictly Aligned with DOMAIN_KEYWORD_MATRIX)
CF_DOMAINS = {
    'must-pick.com': {
        'niche': '가전·IT기어·에너지환급 비교',
        'desc': '로봇청소기, 식기세척기, 제습기, 노트북·태블릿 스펙 비교, 으뜸효율 가전 환급, A/S 수리비용 가이드',
        'persona': '가전·IT 실사용 스펙 비교 리뷰어',
        'titleStyle': '스펙·비용 비교형 (예: "[핵심 키워드] 실구매 체감 차이와 유지비·수리비 비교")',
        'writingTone': '실제 가전·기기를 써보고 스펙표의 함정과 A/S·유지비 차이를 짚어주는 스마트 컨슈머 리뷰 톤. 억지스러운 행정/탈락 용어 대신 체감 성능, 소비전력, 수리비, 호환성 기준으로 서술하라.',
        'theme': {'accent': '#0284c7', 'bg': '#f0f9ff', 'border': '#bae6fd', 'headerBg': '#e0f2fe', 'text': '#0c4a6e', 'widgetStyle': 'spec_card'},
    },
    'must-good.com': {
        'niche': '정부지원금·청년장년복지·민원·세금환급',
        'desc': '정부지원금, 국민취업지원제도, 부모급여, 건강보험료 환급, 정부24 민원 발급, 연말정산·종합소득세',
        'persona': '복지·민원 행정 실무 가이드',
        'titleStyle': '신청기한·자격 핵심형 (예: "[핵심 키워드] 신청 자격과 지급일·서류 체크포인트")',
        'writingTone': '주민센터·복지로 민원 창구에서 바로 써먹을 수 있도록 신청 기한, 소득·재산 산정 기준, 반려 사유를 명확히 짚어주는 친절한 행정 실무자 톤.',
        'theme': {'accent': '#2563eb', 'bg': '#eff6ff', 'border': '#bfdbfe', 'headerBg': '#dbeafe', 'text': '#1e3a8a', 'widgetStyle': 'checklist'},
    },
    'healthcox.com': {
        'niche': '관절통증·국가건강검진·만성질환·영양의학',
        'desc': '관절·디스크 통증 케어, 국가건강검진·내시경, 혈압·혈당·콜레스테롤 관리, 영양제·수면 의학',
        'persona': '건강검진·만성질환 메디컬 에디터',
        'titleStyle': '증상·검사 수치 가이드형 (예: "[핵심 키워드] 정상 수치 기준과 검사 전 주의사항")',
        'writingTone': '건강검진 결과표나 초기 증상을 보고 걱정하는 독자에게 수치 기준, 병원 진료과 선택, 식습관·복용 타이밍을 차분하고 신뢰감 있게 설명하는 헬스케어 칼럼 톤. 행정/심사 탈락 같은 어색한 표현은 절대 쓰지 마라.',
        'theme': {'accent': '#0d9488', 'bg': '#f0fdfa', 'border': '#99f6e4', 'headerBg': '#ccfbf1', 'text': '#134e4a', 'widgetStyle': 'medical_note'},
    },
    'must-joy.com': {
        'niche': '로컬맛집·웨이팅·카페·전시공연 리뷰',
        'desc': '백반기행·생활의달인 맛집 웨이팅·주차, 감성 카페·베이커리, 전시·팝업·공연 예매, 제철 특산물',
        'persona': '로컬 미식·문화 큐레이터',
        'titleStyle': '현장 웨이팅·주차·메뉴 꿀팁형 (예: "[핵심 키워드] 주말 웨이팅 시간대와 주차·대표메뉴 정리")',
        'writingTone': '직접 현장을 찾는 방문객을 위해 피크타임 대기 시간, 브레이크타임, 인근 공영주차장, 대표 메뉴 가격대와 주문 팁을 생생하게 전하는 매거진 에디터 톤. 심사·반려·판독기 같은 딱딱한 용어는 금지한다.',
        'theme': {'accent': '#ea580c', 'bg': '#fff7ed', 'border': '#fed7aa', 'headerBg': '#ffedd5', 'text': '#7c2d12', 'widgetStyle': 'field_tip'},
    },
    'maxnote.kr': {
        'niche': 'AI툴·업무자동화·노션·엑셀·알뜰폰',
        'desc': '챗GPT·클로드 프롬프트, 노션·엑셀 함수 자동화, 크리에이터 편집 도구, 알뜰폰 요금제·모바일신분증',
        'persona': '생산성 테크·통신비 최적화 에디터',
        'titleStyle': '실전 세팅·요금 비교형 (예: "[핵심 키워드] 요금제·옵션 비교와 5분 개통·설정법")',
        'writingTone': '복잡한 IT·통신·업무 툴 설정을 군더더기 없이 단계별(Step-by-step)로 풀어주고 숨은 요금 조건이나 단축키·옵션 차이를 콕 집어주는 테크 블로거 톤.',
        'theme': {'accent': '#4f46e5', 'bg': '#eef2ff', 'border': '#c7d2fe', 'headerBg': '#e0e7ff', 'text': '#312e81', 'widgetStyle': 'step_box'},
    },
    'baronote.kr': {
        'niche': '국민기초연금·대출금리·카드혜택·보험절세',
        'desc': '국민·기초·퇴직연금 수령액, 주담대·전세대출 금리·DSR 비교, 신용카드 캐시백, 실손보험·절세 전략',
        'persona': '가계 금융·연금 자산관리 플래너',
        'titleStyle': '수령액·이자 계산 비교형 (예: "[핵심 키워드] 조건별 예상 금액과 유불리 비교")',
        'writingTone': '은행·연금공단 창구 상담처럼 금리, 한도, 수령액 계산식과 중도상환·감액 조건을 숫자로 또렷하게 비교해주는 금융 플래너 톤.',
        'theme': {'accent': '#1e40af', 'bg': '#f8fafc', 'border': '#cbd5e1', 'headerBg': '#e2e8f0', 'text': '#0f172a', 'widgetStyle': 'finance_summary'},
    },
    'topnote.kr': {
        'niche': '윈도우·맥 설정·스마트폰·오피스·계정복구',
        'desc': '윈도우11·맥북 오류·프린터 설정, 아이폰·갤럭시·카톡 백업·알뜰폰 eSIM, 엑셀·PDF 팁, 2단계인증·계정복구',
        'persona': 'PC·모바일 트러블슈팅 엔지니어',
        'titleStyle': '오류 원인·해결 순서형 (예: "[핵심 키워드] 원인별 해결 순서와 초기화 방지 설정")',
        'writingTone': '갑작스러운 기기 오류나 계정 잠금으로 당황한 독자가 화면 메뉴 경로를 그대로 따라 누르며 즉시 해결할 수 있도록 안내하는 IT 헬프데스크 톤.',
        'theme': {'accent': '#334155', 'bg': '#f8fafc', 'border': '#cbd5e1', 'headerBg': '#f1f5f9', 'text': '#1e293b', 'widgetStyle': 'troubleshoot_faq'},
    },
    'meganote.kr': {
        'niche': '자동차·전기차보조금·다이렉트보험·생활금융',
        'desc': '전기차·하이브리드 보조금, 다이렉트 자동차보험 특약·경정비·과태료, 마트 휴무일·온누리상품권·공과금 절약',
        'persona': '자동차 유지비·생활경제 에디터',
        'titleStyle': '보조금·특약·할인 실속형 (예: "[핵심 키워드] 특약·보조금 조건과 유지비 아끼는 법")',
        'writingTone': '운전자와 주부·자영업자가 자동차 보험료, 경정비 비용, 과태료, 대형마트·전통시장 할인 혜택을 알뜰하게 챙길 수 있도록 돕는 실속 경제 가이드 톤.',
        'theme': {'accent': '#059669', 'bg': '#ecfdf5', 'border': '#a7f3d0', 'headerBg': '#d1fae5', 'text': '#064e3b', 'widgetStyle': 'saving_point'},
    },
    'justinfo.co.kr': {
        'niche': '세무절세·실업급여노무·소비자환불·과태료',
        'desc': '실업급여·퇴직금·주휴수당 노무, 양도세·증여세·종합소득세 절세, 소비자 위약금·환불 분쟁, 생활법률·과태료',
        'persona': '노무·세무·소비자분쟁 실무 해설가',
        'titleStyle': '가산세·위약금 방어 기준형 (예: "[핵심 키워드] 법정 기준과 불이익 피하는 증빙 서류")',
        'writingTone': '근로기준법·세법·소비자분쟁해결기준의 핵심 요건을 근거로 억울한 가산세나 위약금, 수급 불인정을 피하는 방법을 명쾌하게 정리하는 법률·세무 해설 톤.',
        'theme': {'accent': '#4338ca', 'bg': '#eef2ff', 'border': '#c7d2fe', 'headerBg': '#e0e7ff', 'text': '#1e1b4b', 'widgetStyle': 'legal_qa'},
    },
    'smilenote.kr': {
        'niche': '연금·은퇴설계·시니어혜택·중장년건강·돌봄',
        'desc': '국민·기초·주택연금 은퇴설계, 시니어 경로우대·할인 바우처, 중장년 관절·근력 운동, 장기요양·임플란트·돌봄',
        'persona': '5070 은퇴·시니어 라이프 컨설턴트',
        'titleStyle': '부모님·중장년 혜택 맞춤형 (예: "[핵심 키워드] 연령별 지원 기준과 본인부담금 줄이는 법")',
        'writingTone': '은퇴 전후 중장년층과 부모님 돌봄을 준비하는 자녀가 이해하기 쉽도록 편안하고 따뜻한 어조로 연령 기준과 신청 절차를 설명하는 시니어 라이프 가이드 톤.',
        'theme': {'accent': '#15803d', 'bg': '#f0fdf4', 'border': '#bbf7d0', 'headerBg': '#dcfce7', 'text': '#14532d', 'widgetStyle': 'senior_guide'},
    },
    'tripmarvel.com': {
        'niche': '해외여행·항공숙소예약팁·국내여행·패스',
        'desc': '항공권·수하물·보조배터리 규정, 호텔 무료취소·보증금·리조트피 방어, 트래블로그·환전·eSIM, 국내여행·KTX',
        'persona': '글로벌 트래블·항공숙소 에디터',
        'titleStyle': '출국·예약 전 체크형 (예: "[핵심 키워드] 항공사·호텔별 규정과 추가요금 피하는 팁")',
        'writingTone': '공항 카운터나 현지 호텔 체크인에서 당황하지 않도록 수하물 규격, 환전·결제 수수료, 교통 패스 동선을 실전 여행자 시각에서 짚어주는 트래블 가이드 톤.',
        'theme': {'accent': '#0369a1', 'bg': '#f0f9ff', 'border': '#bae6fd', 'headerBg': '#e0f2fe', 'text': '#0c4a6e', 'widgetStyle': 'travel_memo'},
    },
    'daynote.kr': {
        'niche': '생활살림·물가절약·주방리빙·분리수거',
        'desc': '식재료 냉장·냉동 보관법, 과탄산소다 배수구·세탁기 청소, 분리수거 과태료 기준, 전기세·가스비·관리비 절약',
        'persona': '살림·리빙 노하우 에디터',
        'titleStyle': '살림·보관·청소 실용형 (예: "[핵심 키워드] 실패 없는 비율·순서와 보관 기간 정리")',
        'writingTone': '주방·세탁실·거실에서 바로 따라 할 수 있도록 계량 비율, 세척 시간, 보관 온도, 분리배출 기준을 깔끔하고 실용적으로 정리해주는 리빙 매거진 톤.',
        'theme': {'accent': '#b45309', 'bg': '#fffbeb', 'border': '#fde68a', 'headerBg': '#fef3c7', 'text': '#78350f', 'widgetStyle': 'living_recipe'},
    },
    'woorinote.kr': {
        'niche': '청약분양·전월세 계약법률·주거대출·등기세법',
        'desc': '청약 가점·특별공급 분양, 전월세 확정일자·보증금 반환·전입신고, 디딤돌·버팀목 대출, 취득세·재산세·셀프등기',
        'persona': '부동산 청약·임대차 실무 가이드',
        'titleStyle': '계약·청약 체크리스트형 (예: "[핵심 키워드] 계약 전 필수 특약과 순위·한도 기준")',
        'writingTone': '전월세 계약서 작성부터 청약 가점 계산, 주택담보·정책 대출, 등기·취득세 신고까지 내 집 마련과 보증금 보호를 위한 실전 절차를 차근차근 짚어주는 주거 가이드 톤.',
        'theme': {'accent': '#0f766e', 'bg': '#f0fdfa', 'border': '#99f6e4', 'headerBg': '#ccfbf1', 'text': '#115e59', 'widgetStyle': 'housing_check'},
    },
    'nolplace.com': {
        'niche': '수목원·테마파크·아이와나들이·축제·주차꿀팁',
        'desc': '수목원·자연휴양림·캠핑장 예약, 주말 아이와 가볼만한곳, 시즌 축제·전시·팝업 일정, 무료주차·오픈런 동선',
        'persona': '주말 나들이·가족 여행 코스 플래너',
        'titleStyle': '예약·주차·관람 동선형 (예: "[핵심 키워드] 예약 오픈 시간과 주차장·관람 추천 코스")',
        'writingTone': '주말에 아이·가족·연인과 나들이를 떠나는 독자를 위해 매표·예약 팁, 유모차·그늘막 반입 여부, 가장 가까운 주차장과 추천 관람 코스를 경쾌하게 안내하는 나들이 가이드 톤.',
        'theme': {'accent': '#16a34a', 'bg': '#f0fdf4', 'border': '#bbf7d0', 'headerBg': '#dcfce7', 'text': '#14532d', 'widgetStyle': 'outing_route'},
    },
    'soulnote.kr': {
        'niche': '내일배움카드·국비지원·국가자격증·이직커리어',
        'desc': '국민내일배움카드 국비 신청, 유망 국가기술자격증 시험일정·기출 독학팁, 이직·취업·경조사 예절 가이드',
        'persona': '자격증·국비지원 커리어 코치',
        'titleStyle': '응시자격·국비훈련 전략형 (예: "[핵심 키워드] 응시 자격 확인과 국비 지원·합격 준비법")',
        'writingTone': '취업·이직·자격증 취득을 준비하는 독자에게 응시 자격 요건, 훈련장려금 수령 조건, 과목별 공부 순서와 실무 활용도를 명확히 잡아주는 커리어 멘토 톤.',
        'theme': {'accent': '#7c3aed', 'bg': '#f5f3ff', 'border': '#ddd6fe', 'headerBg': '#ede9fe', 'text': '#4c1d95', 'widgetStyle': 'career_step'},
    },
    'joynote.kr': {
        'niche': '강아지고양이건강·펫보험·애견동반·반려식물',
        'desc': '강아지·고양이 증상·사료·예방접종, 동물병원 진료비·펫보험 비교, 애견동반 카페·숙소·산책로, 반려식물 분갈이·물주기',
        'persona': '반려동물·반려식물 케어 에디터',
        'titleStyle': '증상 대처·케어 가이드형 (예: "[핵심 키워드] 주요 원인과 병원 방문 전 대처·관리법")',
        'writingTone': '강아지·고양이 보호자와 식집사가 일상에서 겪는 이상 증상, 사료·간식 급여량, 병원 진료비·펫보험 보장 기준, 분갈이·물주기 주기를 다정하고 세심하게 알려주는 펫·플랜트 케어 톤.',
        'theme': {'accent': '#d97706', 'bg': '#fffbeb', 'border': '#fde68a', 'headerBg': '#fef3c7', 'text': '#78350f', 'widgetStyle': 'pet_care'},
    },
}

# 2. Naver Blogs (Frontline Search SEO Bridges)
NAVER_ACCOUNTS = {
    'soultin': {'status': 'active', 'type': '비실명 성장형', 'focus': '금융·연금·경제 실무'},
    'adinfo0905': {'status': 'active', 'type': '비실명 안정형', 'focus': '정책자금·소상공인·지원금'},
    'soul5373': {'status': 'active', 'type': '비실명 안정형', 'focus': '복지·건강·생활 가이드'},
    'yoon_master': {'status': 'active', 'type': '비실명 성장형', 'focus': '재테크·부동산·주거지원'},
    'stone0747': {'status': 'active', 'type': '비실명 안정형', 'focus': '세무·민원·정부 혜택'},
}

# 3. Threads Channel (Viral Feed Hooking Bridge)
THREADS_ACCOUNT = {
    'account_key': 'mustpickinfo',
    'status': 'connected',
    'auth_mode': 'Meta Graph API (Verified) + Chrome CDP (Port 9450)',
    'strategy': '피드 후킹 숏테일 바이럴 → 첫 댓글 브릿지 링크로 CF 블로그 대량 유입 유도',
}

# 4. Naver KnowledgeIn (Kin)
KIN_ACCOUNTS = {
    'adinfo0905': {'status': 'active', 'role': '전문 정책/대출 답변자'},
    'stone0747': {'status': 'active', 'role': '세무/민원/정부 혜택 답변자'},
}

# 4-B. Brunch Story (Kakao/Daum & Google High-DA Essay Column Bridge)
BRUNCH_ACCOUNT = {
    'account_key': 'baro76650',
    'email': 'baro76650@gmail.com',
    'profile_id': '31d1f5fb288c4fc',
    'pen_name': '머스트픽',
    'url': 'https://brunch.co.kr/@31d1f5fb288c4fc',
    'cdp_port': 9450,
    'status': 'writer_approved',
    'strategy': '4060 은퇴·연금·건보료·세무 실무 에세이 칼럼 → 승인 즉시 다음(Daum)·구글(DA 80+) 색인 부스터 및 CF 16개 도메인 브릿지 가동',
}

# 5. Compute & Image Infrastructure
INFRASTRUCTURE = {
    'llm_pool': {
        'gemini_1': 'baro76650@gmail.com (Gemini 3.8 Flash High/Medium)',
        'gemini_2': 'barolab26@gmail.com (Gemini 3.8 Flash High/Medium)',
        'codex': 'gpt-6.1-sol / gpt-6-luna (Codex subscription)',
    },
    'image_generator': 'Google Flow / Flux via Chrome CDP (Port 9440)',
    'memory_vault': 'Synapse Vault & Hermes Memory Graph',
}


# 6. Affiliate Marketing Weapons (CPA / CPC / CPS Multi-Monetization)
AFFILIATE_PROGRAMS = {
    'replyalba': {
        'name': '리플알바 (ReplyAlba)',
        'credentials': {'id_set': True, 'url': 'https://replyalba.co.kr/'},
        'options': ['CPA (상담/신청 건당 고수익 DB)', 'CPC (클릭당 과금)'],
        'categories': ['정책지원금', '대출·금융', '렌탈', '취업·부업', '법률·세무', '건강·보험'],
        'target_channels': ['must-pick.com', 'baronote.kr', 'meganote.kr', 'woorinote.kr', 'healthcox.com', 'soultin', 'adinfo0905'],
        'strategy': '정부 정책, 소상공인 지원금, 대출 비교, 보험/렌탈 글에서 [무료 자격 조회 및 전문 상담 신청] CPA 링크/버튼을 본문 하단에 배치하여 건당 수천~수만원 추가 수익 창출',
    },
    'trip_com': {
        'name': '트립닷컴 (Trip.com 파트너스)',
        'credentials': {'aid': '7143081', 'sid': '263330208'},
        'options': ['CPS (호텔·숙박 예약)', '항공권·철도·액티비티'],
        'categories': ['여행·나들이', '숙소·호텔·리조트', '지역 축제', 'K-패스·교통'],
        'target_channels': ['tripmarvel.com', 'nolplace.com', 'must-joy.com', 'stone0747'],
        'deeplink_template': 'https://kr.trip.com/sale/w/4166/generalhotels.html?Allianceid=7143081&SID=263330208',
        'strategy': '국내외 여행지, 지역 힐링 명소, 축제, K-패스/교통 포스팅 시 [트립닷컴 특가 호텔/교통편 예약하기] 제휴 링크로 수수료 직결',
    },
    'coupang_partners': {
        'name': '쿠팡 파트너스',
        'options': ['CPS (상품 판매 수수료)'],
        'categories': ['가전·IT', '생활용품', '건강기능식품', '육아용품'],
        'target_channels': ['maxnote.kr', 'joynote.kr', 'smilenote.kr', 'soul5373'],
        'strategy': '생활 꿀팁, 고효율 가전 환급, 통신비 절약 등 실물 제품 추천 시 쿠팡 파트너스 링크 매칭',
    },
    'toss_sharelink': {
        'name': '토스 쉐어링크',
        'options': ['CPA/이벤트 공유'],
        'categories': ['토스 핀테크', '금융·지원금 알림'],
        'target_channels': ['woorinote.kr', 'must-pick.com'],
        'strategy': '파킹통장, 청년 적금, 지원금 찾기 등 토스 연계 이벤트 공유',
    }
}


def match_monetization_options(topic_or_keyword, channel='cf'):
    """Determine optimal affiliate and revenue options alongside AdSense."""
    kw = (topic_or_keyword or '').lower()
    options = []
    
    # 1. Trip.com matching for travel/transport/places
    if any(k in kw for k in ('여행', '숙소', '호텔', '축제', 'k패스', 'k-패스', '교통', '관광', '명소', '비행기', '항공권')):
        options.append({
            'program': 'trip_com',
            'type': 'CPS 제휴',
            'name': '트립닷컴 파트너스 (AID: 7143081, SID: 263330208)',
            'action': '포스팅 본문 하단에 [트립닷컴 공식 특가 숙소/교통 예약] 제휴 링크 삽입 권장',
            'link': 'https://kr.trip.com/sale/w/4166/generalhotels.html?Allianceid=7143081&SID=263330208'
        })
    
    # 2. ReplyAlba CPA matching for loans/policy funds/insurance/rental
    if any(k in kw for k in ('대출', '지원금', '정책', '소상공인', '보험', '렌탈', '상담', '환급', '취업', '알바', '창업', '세무', '법률')):
        options.append({
            'program': 'replyalba',
            'type': 'CPA/CPC 제휴 (고단가 DB)',
            'name': '리플알바 (ID: baro76650)',
            'action': '포스팅 본문 중/하단에 [전문 무료 상담 신청 및 자격조회] CPA 링크 삽입 권장 (건당 고단가 정산)',
            'portal': 'https://replyalba.co.kr/'
        })

    # 3. Coupang Partners for lifestyle/appliances/supplements
    if any(k in kw for k in ('가전', '에너지', '영양제', '육아', '폰', '스마트', '제품', '추천', '기기')):
        options.append({
            'program': 'coupang_partners',
            'type': 'CPS 제휴',
            'name': '쿠팡 파트너스',
            'action': '추천 상품 구매 연결 링크 삽입 권장'
        })

    return {
        'primaryEngine': 'Google AdSense (기본 캐시카우)',
        'affiliateOptions': options,
        'hasAffiliateAngle': len(options) > 0,
        'advice': '애드센스 기본 노출 위에 고단가 제휴(리플알바 CPA 또는 트립닷컴)를 결합하여 페이지당 RPM 극대화'
    }


def match_synergy_cluster(topic_or_keyword, identity=None):
    """Find the best CF Blog destination and cluster angle for a given topic."""
    kw = (topic_or_keyword or '').lower().strip()
    if identity and identity in CF_DOMAINS:
        domain = identity
    elif kw in CF_DOMAINS:
        domain = kw
    elif any(d in kw for d in CF_DOMAINS):
        domain = next(d for d in CF_DOMAINS if d in kw)
    elif any(k in kw for k in ('건강', '보험', '의료', '병원', '약', '질환', '특례', '암')):
        domain = 'healthcox.com'
    elif any(k in kw for k in ('연금', '노후', '기초', '노령', '퇴직', '실버')):
        domain = 'must-good.com'
    elif any(k in kw for k in ('세금', '연말정산', '절세', '소득세', '증여', '상속')):
        domain = 'baronote.kr'
    elif any(k in kw for k in ('부동산', '청약', '전세', '디딤돌', '버팀목', '주택')):
        domain = 'topnote.kr'
    elif any(k in kw for k in ('소상공인', '자영업', '대환', '사업자', '희망리턴')):
        domain = 'meganote.kr'
    elif any(k in kw for k in ('육아', '아동', '청년', '부모', '도약', '장학금')):
        domain = 'smilenote.kr'
    elif any(k in kw for k in ('교통', 'k패스', '여행', '기후', '지하철')):
        domain = 'tripmarvel.com'
    elif any(k in kw for k in ('적금', '예금', '통장', '파킹', '금리', '이자')):
        domain = 'woorinote.kr'
    elif any(k in kw for k in ('휴대폰', '알뜰폰', '통신비', '앱', '모바일')):
        domain = 'maxnote.kr'
    elif any(k in kw for k in ('전기세', '난방비', '에너지', '환급', '가전')):
        domain = 'joynote.kr'
    else:
        domain = 'must-pick.com'

    target = CF_DOMAINS.get(domain, CF_DOMAINS['must-pick.com'])
    live_targets = get_today_cf_bridge_targets(topic_or_keyword, allowed_domains=[domain]) or get_today_cf_bridge_targets(topic_or_keyword)
    return {
        'targetDomain': domain,
        'niche': target['niche'],
        'desc': target['desc'],
        'synergyAngle': f'네이버/스레드/지식iN에서 핵심 통증 후킹 후 3초 자가진단 체크리스트 및 세부 기준표는 {domain} 랜딩페이지로 일점사 연결',
        'todayLiveBridgeTargets': live_targets[:3],
    }


PRIORITY_CASHCOW_DOMAINS = (
    'must-pick.com',
    'baronote.kr',
    'must-good.com',
    'woorinote.kr',
    'justinfo.co.kr',
    'daynote.kr',
    'meganote.kr',
    'healthcox.com',
)


def get_today_cf_bridge_targets(topic_or_keyword='', allowed_domains=None):
    """Return verified published CF landing pages ranked by topic match & cash-cow priority (strictly requiring topic overlap when topic_or_keyword is given)."""
    import re
    allowed = {d.replace('www.', '').strip().lower() for d in (allowed_domains or []) if d}
    candidates = []
    seen_urls = set()
    sched_path = ROOT / 'dashboard/data/cf/daily_schedule.json'
    if sched_path.is_file():
        try:
            sched = json.loads(sched_path.read_text(encoding='utf-8'))
            for item in sched.get('items', []):
                dom = str(item.get('domain') or '').replace('www.', '').strip().lower()
                url = str(item.get('publicUrl') or '').strip()
                title = str(item.get('title') or '').strip()
                if dom and url and title and url not in seen_urls:
                    if allowed and dom not in allowed:
                        continue
                    seen_urls.add(url)
                    candidates.append({'domain': dom, 'url': url, 'title': title, 'category': str(item.get('category') or '')})
        except Exception:
            pass
    cf_sched_root = ROOT / 'cf_posting/output/scheduled'
    if cf_sched_root.is_dir():
        for day_dir in sorted(cf_sched_root.iterdir(), reverse=True)[:10]:
            if not day_dir.is_dir():
                continue
            for dom_dir in sorted(day_dir.iterdir()):
                rec_p = dom_dir / 'publication-receipt.json'
                if not rec_p.is_file():
                    continue
                try:
                    rec = json.loads(rec_p.read_text(encoding='utf-8'))
                    dom = str(rec.get('domain') or dom_dir.name).replace('www.', '').strip().lower()
                    url = str(rec.get('publicUrl') or '').strip()
                    title = str(rec.get('title') or '').strip()
                    if dom and url and title and url not in seen_urls:
                        if allowed and dom not in allowed:
                            continue
                        seen_urls.add(url)
                        candidates.append({'domain': dom, 'url': url, 'title': title, 'category': ''})
                except Exception:
                    pass
    topic_str = str(topic_or_keyword or '').strip()
    core_tokens = [
        t for t in extract_core_topic_nouns(topic_str)
        if t not in ('놓치기', '쉬운', '점검', '정리', '확인', '가이드', '방법', '기준', '조건', '서류', '신청', '계산')
    ]
    def _score(row):
        title_nouns = extract_core_topic_nouns(row['title'])
        hay_title = f"{row['title']} {row['url']}".lower()
        kw_hits = 0
        for t in core_tokens:
            if t in title_nouns or t in hay_title:
                kw_hits += 3
        cash_bonus = (10 - PRIORITY_CASHCOW_DOMAINS.index(row['domain'])) if row['domain'] in PRIORITY_CASHCOW_DOMAINS else 1
        return (kw_hits, cash_bonus)
    if core_tokens:
        candidates = [c for c in candidates if _score(c)[0] >= 3]
    candidates.sort(key=_score, reverse=True)
    return candidates


def get_account_pacing_strategy(account, date_str=None):
    """Apply the current experimental 7:3 allocation; longevity effects are unverified.

    70% Pure Informational Posts (No external link, C-Rank DIA build-up).
    30% Strategic Bridge Posts (Natural anchor link to target CF Blog).
    Rule: Never bridge in consecutive posts on the same account.
    Note: stone0747 is locked to pure_info_build (linkAllowed=False) for index recovery.
    """
    if account == 'stone0747':
        return {
            'mode': 'pure_info_build',
            'linkAllowed': False,
            'ratio': '지수 회복 집중 모드 (외부 링크 0개 · 순수 정보 완결형)',
            'instruction': 'stone0747 계정은 유사문서/색인 지수 회복을 위해 외부 링크를 절대 넣지 않고 본문 안에서 모든 질문과 수치·판독표를 100% 완결한다.'
        }
    day = date_str or datetime.now(KST).date().isoformat()
    journal_path = ROOT / 'dashboard/data/naver/automation-journal.json'
    recent_attempts = []
    if journal_path.exists():
        try:
            journal = json.loads(journal_path.read_text(encoding='utf-8'))
            recent_attempts = [
                a for a in journal.get('attempts', [])
                if a.get('account') == account and a.get('phase') in ('done', 'verified', 'published', 'reserved')
            ]
        except Exception:
            pass

    # Check last 3 attempts for this account
    bridge_count = 0
    consecutive_bridge = False
    if recent_attempts:
        last = recent_attempts[-1]
        # Check if the last post had an outbound bridge link
        topic = str(last.get('topic', ''))
        consecutive_bridge = '[브릿지]' in topic or '링크' in topic

        for att in recent_attempts[-3:]:
            if '[브릿지]' in str(att.get('topic', '')) or '링크' in str(att.get('topic', '')):
                bridge_count += 1

    # If the last post was a bridge, this one MUST be pure info (70% category) to protect C-Rank
    if consecutive_bridge or bridge_count >= 2:
        return {
            'mode': 'pure_info_build',
            'linkAllowed': False,
            'ratio': '70% 정보성 콘텐츠 배분 실험 · 순위·수명 효과 미검증',
            'instruction': '이번 글은 외부 링크 없이 질문을 해결하는 완결형 정보로 작성한다. 이 배분이 계정 지수·순위·수명을 개선한다고 주장하지 않는다.'
        }
    else:
        return {
            'mode': 'strategic_bridge',
            'linkAllowed': True,
            'ratio': '30% 전략적 브릿지 (수익형 트래픽 유입)',
            'instruction': '본문 85%는 충실한 정보로 체류시간 확보 후, 본문 하단에 자연스러운 앵커 텍스트로 연관 CF 블로그의 공식 모의계산/세부 서식 링크 1개 삽입.'
        }


# ── Naver Blog Top-Exposure SEO Guardrails (3-Stage Patch) ──
NAVER_NICHE_VERIFIED_POOLS = {
    'soultin': [
        '국민연금 유족연금 중복수급 감액률',
        '퇴직 후 건강보험 임의계속가입 해지',
        '기초연금 수급자격 자동차 시가표준액',
        '노령연금 연기연금 신청 손익분기점',
        '주택연금 우대형 가입조건 수령액 차이',
        '국민연금 추납 신청자격 반환일시금',
    ],
    'soul5373': [
        '당화혈색소 6.5 공복혈당 불일치 이유',
        '대상포진 사백신 싱그릭스 접종간격 실비',
        '무릎 연골주사 히알루론산 급여 주기',
        '백내장 단초점 다초점 실손보험 청구서류',
        '위내시경 조직검사 용종절제 실비보험 청구',
        '도수치료 실손보험 10회 초과 소견서',
        '고지혈증 스타틴 근육통 코엔자임Q10',
    ],
    'yoon_master': [
        '호텔 디파짓 해외결제 승인취소 소요기간',
        '로봇청소기 직배수 키트 타공 원상복구',
        '인버터 제습기 일일제습량 소비전력 계산',
        '가을 구스다운 세탁 중성세제 건조기 볼',
        '국제선 기내수하물 보조배터리 단락방지 포장',
        '친환경 콘덴싱보일러 보조금 세입자 신청',
        '빌트인 식기세척기 싱크대 리폼 설치조건',
        '한전 고효율 가전제품 환급 구매내역서 라벨',
    ],
    'adinfo0905': [
        '청년주택드림 청약통장 전환 일시납 한도',
        'IRP 중도인출 무주택 전세보증금 서류',
        '퇴직금 중간정산 무주택자 전세계약서 기간',
        '버팀목 전세자금대출 목적물변경 연장 조건',
        '중소기업 청년 소득세 감면 경정청구 서류',
        '연말정산 부모님 인적공제 양도소득 100만원',
    ],
    'stone0747': [
        '청년월세 특별지원 이체확인증 보증금 감액',
        '소상공인 대환대출 4.5% 보증서 발급절차',
        '노란우산공제 해지 일시금 퇴직소득세율',
        '근로장려금 반기신청 전세보증금 간주전세금',
        '소상공인 고용보험료 지원 신청 등급별 비율',
        '육아휴직급여 사후지급금 폐지 상한액 계산',
        '희망리턴패키지 원스톱 폐업지원 정산서류',
        '국민취업지원제도 1유형 조기취업성공수당 신청',
    ],
}

_STOPWORDS_KO = frozenset({
    '2025', '2026', '2026년', '신청', '조건', '방법', '기준', '확인', '확인법', '체크', '체크리스트',
    '정리', '총정리', '계산', '계산법', '점검', '이유', '차이', '순서', '서류', '기간', '일정',
    '대상', '조회', '할까', '될까', '있을까', '어떨까', '무엇', '언제', '어떻게', '왜',
    '냈는데', '썼는데', '골랐는데', '받는데', '사셨나요', '그대로', '먼저', '전후', '포기',
    '놓치기', '쉬운', '3분', '3초', '1분', '가지', '3가지', '4가지', '판독법', '판독기',
    '자격', '수급자격', '지원', '지원금', '환급', '환급금', '공제', '세액공제', '소득공제',
    '내가', '내겐', '부모님', '명의', '계약서', '계약자', '계약',
})


def _load_naver_openapi_keys():
    import os
    env_p = ROOT / '.env'
    if env_p.is_file():
        for line in env_p.read_text(encoding='utf-8', errors='replace').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    cid = os.environ.get('NAVER_CLIENT_ID') or os.environ.get('NAVER_SEARCH_CLIENT_ID') or ''
    csec = os.environ.get('NAVER_CLIENT_SECRET') or os.environ.get('NAVER_SEARCH_CLIENT_SECRET') or ''
    return cid, csec


def query_naver_blog_doc_count(keyword, timeout=3.5):
    """Return total Naver Blog document count via Naver Search OpenAPI, or None if unavailable."""
    import urllib.request
    import urllib.parse
    kw = str(keyword or '').strip()
    if not kw:
        return None
    cid, csec = _load_naver_openapi_keys()
    if not cid or not csec:
        return None
    try:
        url = f'https://openapi.naver.com/v1/search/blog.json?query={urllib.parse.quote(kw)}&display=5&sort=sim'
        req = urllib.request.Request(url, headers={
            'X-Naver-Client-Id': cid,
            'X-Naver-Client-Secret': csec,
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='ignore'))
            return int(data.get('total', 0))
    except Exception:
        return None


def extract_core_topic_nouns(text):
    """Extract normalized 2+ char domain nouns from a Korean title or keyword."""
    cleaned = re.sub(r'[^\w가-힣\s]', ' ', str(text or '')).lower()
    tokens = []
    for raw_tok in cleaned.split():
        # Strip common Korean trailing particles
        tok = re.sub(r'(은|는|이|가|을|를|의|에|에서|으로|로|과|와|도|만|부터|까지|라도|처럼|보다|할까|될까|일까)$', '', raw_tok)
        if len(tok) >= 2 and tok not in _STOPWORDS_KO and not tok.isdigit():
            tokens.append(tok)
    return set(tokens)


def is_duplicate_naver_topic(candidate_text, used_texts):
    """Return True if candidate_text duplicates any topic in used_texts (exact or >=2 core domain nouns overlap)."""
    cand_str = re.sub(r'\s+', '', str(candidate_text or '')).lower()
    if not cand_str:
        return True
    cand_nouns = extract_core_topic_nouns(candidate_text)
    for u in (used_texts or []):
        u_str = re.sub(r'\s+', '', str(u or '')).lower()
        if not u_str:
            continue
        if cand_str == u_str or (len(cand_str) >= 7 and cand_str[:7] in u_str) or (len(u_str) >= 7 and u_str[:7] in cand_str):
            return True
        u_nouns = extract_core_topic_nouns(u)
        overlap = cand_nouns & u_nouns
        if len(overlap) >= 2:
            return True
    return False


def collect_used_naver_topics(account=None, days=14, current_folder=None):
    """Collect all titles/keywords used by `account` in the last `days` days + all accounts today."""
    now_dt = datetime.now(KST)
    cutoff_date = (now_dt - timedelta(days=days)).date().isoformat()
    today_date = now_dt.date().isoformat()
    used = []

    def _add(val):
        s = str(val or '').strip()
        if s and s not in used:
            used.append(s)

    # 1. public-verification.json
    pv_path = ROOT / 'dashboard/data/naver/public-verification.json'
    if pv_path.is_file():
        try:
            pv = json.loads(pv_path.read_text(encoding='utf-8'))
            for ev in (pv.get('evidence') or []):
                pub_d = str(ev.get('publicationDate') or ev.get('reserveTime') or '')[:10]
                if not pub_d or pub_d < cutoff_date:
                    continue
                if account is None or ev.get('account') == account or pub_d == today_date:
                    _add(ev.get('title'))
        except Exception:
            pass

    # 2. automation-journal.json
    jr_path = ROOT / 'dashboard/data/naver/automation-journal.json'
    if jr_path.is_file():
        try:
            jr = json.loads(jr_path.read_text(encoding='utf-8'))
            for att in (jr.get('attempts') or []):
                w_d = str(att.get('publicationDate') or att.get('reserveTime') or att.get('workDate') or '')[:10]
                if not w_d or w_d < cutoff_date:
                    continue
                if account is None or att.get('account') == account or w_d == today_date:
                    _add(att.get('topic') or att.get('title'))
        except Exception:
            pass

    # 3. Scheduled output folders for recent days
    sched_root = ROOT / 'naver_blog_posting/output/scheduled'
    if sched_root.is_dir():
        for day_dir in sorted(sched_root.iterdir(), reverse=True)[:days + 2]:
            if not day_dir.is_dir() or day_dir.name < cutoff_date:
                continue
            for slot_dir in day_dir.iterdir():
                if not slot_dir.is_dir():
                    continue
                if current_folder and slot_dir.resolve() == Path(current_folder).resolve():
                    continue
                slot_acc = slot_dir.name.rsplit('-', 1)[0]
                if account is None or slot_acc == account or day_dir.name == today_date:
                    for fn, fk in (('planning.json', 'keyword'), ('writer.json', 'mainKeyword'), ('writer.json', 'title'), ('editor-content.json', 'title')):
                        fp = slot_dir / fn
                        if fp.is_file():
                            try:
                                _add(json.loads(fp.read_text(encoding='utf-8')).get(fk))
                            except Exception:
                                pass
    # 4. Also include today's CF scheduled topics to prevent same-day cross-channel cannibalization
    cf_sched_path = ROOT / 'dashboard/data/cf/daily_schedule.json'
    if cf_sched_path.is_file():
        try:
            cf_s = json.loads(cf_sched_path.read_text(encoding='utf-8'))
            if cf_s.get('date') == today_date:
                for it in (cf_s.get('items') or []):
                    _add(it.get('mainKeyword') or it.get('title'))
        except Exception:
            pass
    return used


CF_NICHE_VERIFIED_POOLS = {
    'must-pick.com': [
        '으뜸효율 가전제품 환급 세입자 신청서류',
        '식기세척기 빌트인 싱크대 걸레받이 절단 비용',
        '인버터 제습기 일일제습량 소비전력 전기세 계산',
        '로봇청소기 직배수 키트 타공 원상복구 비용',
        '올인원 세탁건조기 히트펌프 소비전력 누진세',
    ],
    'must-good.com': [
        '건강보험 임의계속가입 해지 신청기한 퇴직후',
        '청년내일저축계좌 중도해지 적립중지 신청사유',
        '부모급여 가정양육수당 전환 신청일 25일 기준',
        '본인부담상한제 사후환급금 지급신청서 입금기간',
        '근로장려금 반기신청 전세보증금 간주전세금 계산',
    ],
    'healthcox.com': [
        '당화혈색소 6.5 공복혈당 불일치 이유',
        '대상포진 사백신 싱그릭스 접종간격 실비',
        '무릎 연골주사 히알루론산 급여 주기 6개월',
        '대장내시경 용종절제술 수술비특약 질병수술비 청구',
        '국가건강검진 위내시경 조직검사 실비 청구서류',
    ],
    'must-joy.com': [
        '문화누리카드 세대원 잔액 합산 온라인 신청방법',
        '온누리상품권 카드형 충전할인 전통시장 소득공제율',
        '공연 관람료 소득공제 신용카드 문화비 한도',
        '국립박물관 어린이박물관 사전예약 취소표 시간',
        '고궁 야간개장 경복궁 특별관람 무료입장 대상',
    ],
    'maxnote.kr': [
        '알뜰폰 번호이동 중립기관 제한 90일 해제 신청',
        '모바일 주민등록증 발급 IC칩 재발급 수수료',
        '휴대폰 소액결제 한도 차단 통신사별 원천차단',
        '알뜰폰 eSIM 듀얼심 데이터 나눠쓰기 개통비용',
        '엠세이퍼 명의도용방지 가입제한 해제 비대면 방법',
    ],
    'baronote.kr': [
        'IRP 중도인출 무주택 전세보증금 필요서류',
        '퇴직연금 DC형 DB형 전환 신청시기 임금피크제',
        '신용카드 리볼빙 해지 일시결제 신용점수 복구',
        '예금담보대출 중도상환수수료 한도 가산금리 계산',
        '청년도약계좌 일시납입 전환 정부기여금 계산',
    ],
    'topnote.kr': [
        '윈도우11 네트워크 프린터 공유 오류 0x0000011b 해결',
        '카카오톡 대화내용 백업 복원 기한 14일 연장',
        '아이폰 eSIM 기기변경 QR코드 재발급 수수료',
        '엑셀 VLOOKUP N/A 오류 공백 문자 일괄제거',
        '구글 계정 2단계인증 백업코드 분실 복구절차',
    ],
    'meganote.kr': [
        '자동차보험 마일리지 특약 환급금 주행거리 사진',
        '전기차 충전구역 과태료 완속 14시간 예외기준',
        '자동차세 연납 후 폐차 매매 환급금 일할계산',
        '하이브리드 개별소비세 취등록세 감면 한도 연장',
        '운전자보험 교통사고처리지원금 중복가입 비례보상',
    ],
    'justinfo.co.kr': [
        '실업급여 조기재취업수당 자영업 프리랜서 서류',
        '주휴수당 지급조건 주 15시간 지각 조퇴 계산',
        '가족간 부동산 저가양도 증여세 3억 30% 기준',
        '퇴직금 중간정산 무주택자 전세계약서 신청기한',
        '소상공인 폐업 점포철거비 지원금 부가세 제외',
    ],
    'smilenote.kr': [
        '기초연금 수급자격 자동차 시가표준액 4천만원',
        '노령연금 연기연금 신청 가산율 7.2% 손익분기점',
        '주택연금 우대형 가입조건 공시가격 수령액 차이',
        '장기요양등급 가족요양비 복지용구 본인부담률',
        '만 65세 임플란트 건강보험 평생 2개 본인부담금',
    ],
    'tripmarvel.com': [
        '인천공항 긴급여권 발급 소요시간 필요서류 당일',
        '국제운전면허증 온라인 발급 영문운전면허증 국가',
        '기내 보조배터리 용량 Wh 계산 160Wh 반입규정',
        '호텔 디파짓 보증금 해외결제 가승인 취소 기간',
        'KTX 지연배상금 기준 시간별 환불율 신청방법',
    ],
    'daynote.kr': [
        '통돌이 세탁기 배수필터 청소 거름망 과탄산소다',
        '대형폐기물 인터넷신고 스티커 취소 환불 수수료',
        '도시가스 계량기 교체비용 자가검침 누락 요금정산',
        '아파트 관리비 장기수선충당금 세입자 퇴거 환급',
        '가을 겨울 구스다운 패딩 세탁 중성세제 건조기',
    ],
    'woorinote.kr': [
        '버팀목 전세자금대출 목적물변경 추가대출 조건',
        '전세보증금 반환보증 HUG HF 보증료율 가입기한',
        '주택청약 부적격 당첨 청약통장 부활 신청기한',
        '디딤돌대출 생애최초 무주택세대주 소득합산 예외',
        '전입신고 세대주 확인 온라인 확정일자 우선변제권',
    ],
    'nolplace.com': [
        '국립자연휴양림 숲나들e 우선예약 다자녀 대기예약',
        '서울대공원 캠핑장 예약 매너타임 주차요금 할인',
        '경복궁 야간관람 인터넷예매 현장발권 무료대상',
        '국립수목원 광릉숲 사전예약 차량등록 입장료 면제',
        '어린이대공원 주차장 만차시 주변 공영주차장 요금',
    ],
    'soulnote.kr': [
        '국민내일배움카드 훈련장려금 단위기간 출석률 80%',
        '산업안전기사 응시자격 관련학과 경력증명서 인정',
        '국가기술자격증 취득자격확인서 큐넷 온라인 발급',
        '청년일자리도약장려금 근속지원금 재직기간 계산',
        '이직 확인서 처리기간 고용보험 상실신고 지연',
    ],
    'joynote.kr': [
        '펫보험 슬개골탈구 면책기간 1년 자기부담금 비교',
        '강아지 광견병 무료접종 시군구 동물병원 지참물',
        '반려동물 등록 내장형 마이크로칩 외장형 과태료',
        '강아지 심장사상충약 넥스가드 스펙트라 체중별 용량',
        '몬스테라 분갈이 흙배합 마사토 펄라이트 물주기',
    ],
}


def collect_used_cf_topics(domain=None, days=14, current_folder=None):
    """Collect all titles/keywords used across CF domains in the last `days` days + Naver today."""
    now_dt = datetime.now(KST)
    cutoff_date = (now_dt - timedelta(days=days)).date().isoformat()
    today_date = now_dt.date().isoformat()
    used = []

    def _add(val):
        s = str(val or '').strip()
        if s and s not in used:
            used.append(s)

    sched_root = ROOT / 'cf_posting/output/scheduled'
    if sched_root.is_dir():
        for day_dir in sorted(sched_root.iterdir(), reverse=True)[:days + 2]:
            if not day_dir.is_dir() or day_dir.name < cutoff_date:
                continue
            for dom_dir in day_dir.iterdir():
                if not dom_dir.is_dir():
                    continue
                if current_folder and dom_dir.resolve() == Path(current_folder).resolve():
                    continue
                if domain is None or dom_dir.name == domain or day_dir.name == today_date:
                    for fn, fk in (('planning.json', 'keyword'), ('article.json', 'title'), ('article.json', 'mainKeyword')):
                        fp = dom_dir / fn
                        if fp.is_file():
                            try:
                                _add(json.loads(fp.read_text(encoding='utf-8')).get(fk))
                            except Exception:
                                pass
    return used


def select_verified_cf_keyword(domain, candidate_kw, verified_candidates=None, used_topics=None, max_docs=300):
    """Select a domain-consistent, non-duplicate CF search keyword verified to have <= max_docs competing posts."""
    used = list(used_topics or [])
    pool = []
    if candidate_kw and candidate_kw != domain and not candidate_kw.startswith(CF_DOMAINS.get(domain, {}).get('niche', '___')):
        pool.append(clean_naver_search_keyword(candidate_kw))
    for c in (verified_candidates or []):
        kw_c = clean_naver_search_keyword(c.get('keyword') if isinstance(c, dict) else c)
        if kw_c and kw_c not in pool:
            pool.append(kw_c)
    for fallback_kw in CF_NICHE_VERIFIED_POOLS.get(domain, []):
        if fallback_kw not in pool:
            pool.append(fallback_kw)

    best_fallback = None
    best_docs = 10**9
    for kw in pool:
        if not kw or is_duplicate_naver_topic(kw, used):
            continue
        doc_cnt = query_naver_blog_doc_count(kw)
        if doc_cnt is None:
            return kw
        if 1 <= doc_cnt <= max_docs:
            return kw
        if doc_cnt < best_docs:
            best_docs = doc_cnt
            best_fallback = kw
    return best_fallback or (CF_NICHE_VERIFIED_POOLS.get(domain, ['건강보험 임의계속가입 해지 신청기한'])[0])



def clean_naver_search_keyword(raw_keyword):
    """Normalize a topic/keyword into a clean 3~5 word search noun phrase that real Naver/Google users type."""
    s = str(raw_keyword or '').strip()
    if ',' in s and len(s.split(',')[0].strip()) >= 6:
        s = s.split(',')[0].strip()
    if '?' in s and len(s.split('?')[0].strip()) >= 6:
        s = s.split('?')[0].strip()
    s = re.sub(r'\b(3분|3초|1분)\s*(체크|확인|판독|점검|계산|정리)\w*', '', s)
    s = re.sub(r'\s+vs\s+', ' ', s, flags=re.IGNORECASE)
    s = re.sub(r'[^\w가-힣.%+\s·-]', ' ', s)
    words = [w for w in s.split() if w]
    words = words[:5]
    if words:
        words[-1] = re.sub(r'(와|과|은|는|이|가|을|를|에|에서)$', '', words[-1])
    return ' '.join(w for w in words if w).strip()


def select_verified_naver_keyword(account, candidate_kw, verified_candidates=None, used_topics=None, max_docs=500):
    """Select a non-duplicate Naver search keyword verified to have <= max_docs competing blog posts."""
    used = list(used_topics or [])
    pool = []
    if candidate_kw:
        pool.append(clean_naver_search_keyword(candidate_kw))
    for c in (verified_candidates or []):
        kw_c = clean_naver_search_keyword(c.get('keyword') if isinstance(c, dict) else c)
        if kw_c and kw_c not in pool:
            pool.append(kw_c)
    for fallback_kw in NAVER_NICHE_VERIFIED_POOLS.get(account, []):
        if fallback_kw not in pool:
            pool.append(fallback_kw)

    best_fallback = None
    best_docs = 10**9
    for kw in pool:
        if not kw or is_duplicate_naver_topic(kw, used):
            continue
        doc_cnt = query_naver_blog_doc_count(kw)
        if doc_cnt is None:
            return kw
        if 1 <= doc_cnt <= max_docs:
            return kw
        if doc_cnt < best_docs:
            best_docs = doc_cnt
            best_fallback = kw
    return best_fallback or (NAVER_NICHE_VERIFIED_POOLS.get(account, ['국민연금 추납 신청자격 반환일시금'])[0])


def enforce_naver_seo_title(raw_title, target_keyword, domain=None):
    """Ensure the search noun phrase appears naturally near the front without forcing an identical comma template across all domains."""
    clean_kw = clean_naver_search_keyword(target_keyword)
    title = re.sub(r'\s+', ' ', str(raw_title or '').strip())
    if not clean_kw:
        return title
    kw_tokens = [t for t in clean_kw.split() if len(t) >= 2][:3]
    front_window = title[:max(len(clean_kw) + 12, 26)]
    if kw_tokens and sum(1 for t in kw_tokens if t in front_window) >= max(1, len(kw_tokens) - 1):
        return title
    if ':' in title[:24] and '?' not in title.split(':', 1)[0]:
        pre_colon = title.split(':', 1)[0]
        if not re.search(r'(는데|했더니|했는데|할까|전\s*3초|전\s*3분)', pre_colon):
            return title

    hook = title
    for sep in (',', ':', ' - ', ' · '):
        if sep in title:
            parts = [p.strip() for p in title.split(sep, 1)]
            if len(parts[1]) >= 8 and not re.match(r'^\d', parts[1]):
                hook = parts[1]
                break
    if hook.startswith(clean_kw):
        hook = hook[len(clean_kw):].lstrip(' ,·:-')
    else:
        cand_hook = hook
        for tok in clean_kw.split():
            if cand_hook.startswith(tok + ' ') or cand_hook.startswith(tok + ','):
                cand_hook = cand_hook[len(tok):].lstrip(' ,·:-')
        if not re.match(r'^(했는데|내렸다는데|끝났는데|끝나면|받으면|깨면|있는데|된다는데|일찍\s*받으면)', cand_hook):
            hook = cand_hook
    if not hook or len(hook) < 6:
        hook = '핵심 기준과 실전 체크포인트 정리'
    separators = (' · ', ': ', ' - ', ', ')
    sep_idx = sum(ord(c) for c in str(domain or clean_kw)) % len(separators)
    combined = f'{clean_kw}{separators[sep_idx]}{hook}'
    return combined[:68].rstrip(' ,·:-')



def _load_brunch_credentials():
    import os
    env_p = ROOT / '.env'
    if env_p.is_file():
        for line in env_p.read_text(encoding='utf-8', errors='replace').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return os.environ.get('BRUNCH_ID_BARO76650', ''), os.environ.get('BRUNCH_PW_BARO76650', '')


def ensure_brunch_logged_in(page, target_url='https://brunch.co.kr/ready'):
    """Ensure Brunch session is authenticated on CDP 9450; auto-login via Kakao SSO if redirected to signin."""
    page.goto(target_url, wait_until='domcontentloaded', timeout=25000)
    page.wait_for_timeout(1500)
    if 'signin' in page.url or 'accounts.kakao.com' in page.url:
        uid, upw = _load_brunch_credentials()
        if not uid or not upw:
            return False
        page.goto('https://brunch.co.kr/auth/kakao?url=%2Fsignin%2Ffinish%3Furl%3D%252Fready', wait_until='domcontentloaded', timeout=25000)
        page.wait_for_timeout(2000)
        if 'accounts.kakao.com' in page.url:
            page.locator("input[name='loginId']").fill(uid)
            page.wait_for_timeout(250)
            page.locator("input[name='password']").fill(upw)
            page.wait_for_timeout(250)
            try:
                chk = page.locator("input[name='saveSignedIn']")
                if not chk.is_checked():
                    chk.check(force=True)
            except Exception:
                pass
            page.locator("button[type='submit']").first.click()
            page.wait_for_timeout(3500)
        if target_url and page.url != target_url:
            page.goto(target_url, wait_until='domcontentloaded', timeout=25000)
            page.wait_for_timeout(1500)
    return 'signin' not in page.url and 'accounts.kakao.com' not in page.url


def _fit_brunch_text(text, limit):
    s = str(text or '').strip()
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(' ', 1)[0]
    return cut if len(cut) >= limit - 7 else s[:limit].strip()


def post_or_save_brunch_column(title, subtitle, paragraphs, bridge_url=None, auto_publish=True, cdp_port=9450, edit_url=None):
    """Write or update a Brunch column via native EGO Lite TaskSpace (`barolab-soultin`, Profile 3) without spawning extra windows."""
    safe_title = _fit_brunch_text(title, 28)
    safe_subtitle = _fit_brunch_text(subtitle, 38)
    uid, upw = _load_brunch_credentials()

    try:
        from common.ego_taskspace import native_publish_brunch_column
        ego_res = native_publish_brunch_column(
            title=safe_title,
            subtitle=safe_subtitle,
            paragraphs=list(paragraphs or []),
            bridge_url=bridge_url,
            auto_publish=auto_publish,
            edit_url=edit_url,
            uid=uid or '',
            upw=upw or '',
        )
        if isinstance(ego_res, dict) and ego_res.get('ok'):
            return ego_res
    except Exception:
        pass

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(f'http://127.0.0.1:{cdp_port}')
        ctx = b.contexts[0]
        page = ctx.new_page()
        dialogs = []
        page.on('dialog', lambda d: (dialogs.append(d.message), d.accept()))
        try:
            target_write_url = edit_url or 'https://brunch.co.kr/write'
            ensure_brunch_logged_in(page, target_write_url)
            page.wait_for_timeout(1500)
            try:
                if page.locator('button.guide_close').is_visible(timeout=1200):
                    page.locator('button.guide_close').click()
                    page.wait_for_timeout(300)
            except Exception:
                pass

            title_el = page.locator('h1.cover_title')
            title_el.click()
            page.keyboard.press('Control+A')
            page.keyboard.press('Backspace')
            page.keyboard.insert_text(safe_title)
            page.wait_for_timeout(200)

            sub_el = page.locator('div.cover_sub_title')
            sub_el.click()
            page.keyboard.press('Control+A')
            page.keyboard.press('Backspace')
            page.keyboard.insert_text(safe_subtitle)
            page.wait_for_timeout(200)

            body_el = page.locator('div.wrap_body')
            body_el.click()
            page.keyboard.press('Control+A')
            page.keyboard.press('Backspace')
            page.wait_for_timeout(200)

            for idx, para in enumerate(paragraphs or []):
                page.keyboard.insert_text(str(para).strip())
                if idx < len(paragraphs) - 1:
                    page.keyboard.press('Enter')
                    page.keyboard.press('Enter')
                page.wait_for_timeout(120)

            # Check if writer approval is active ('button.be_header_button_publish' exists)
            can_publish = page.locator('button.be_header_button_publish').count() > 0 or page.locator('button:visible', has_text='발행').count() > 0
            if can_publish and bridge_url:
                page.keyboard.press('Enter')
                page.keyboard.press('Enter')
                page.keyboard.insert_text('▶ 관련 실무 기준표 및 3분 자가진단 원문 보기:')
                page.keyboard.press('Enter')
                page.keyboard.type(str(bridge_url).strip())
                page.keyboard.press('Enter')
                page.wait_for_timeout(1800)

            save_btn = page.locator('button.btn_article_save_draft, button.be_header_button_save').first
            if save_btn.count() > 0:
                save_btn.click()
                page.wait_for_timeout(2000)
            saved_url = page.url

            if can_publish and auto_publish:
                pub_btn = page.locator('button.be_header_button_publish').first
                pub_btn.click()
                page.wait_for_timeout(1500)
                selected = page.locator('button.keyword.selected').count()
                if selected < 3:
                    unselected = page.locator('button.keyword:not(.selected)')
                    for i in range(min(3 - selected, unselected.count())):
                        unselected.nth(i).click()
                        page.wait_for_timeout(200)
                confirm_pub = page.locator('button.save.button.mint').first
                if confirm_pub.count() > 0 and confirm_pub.is_visible():
                    confirm_pub.click()
                    page.wait_for_timeout(3500)
                return {'ok': True, 'mode': 'published', 'writerApproved': True, 'url': page.url, 'title': safe_title}

            return {'ok': True, 'mode': 'saved_to_drawer', 'writerApproved': can_publish, 'url': saved_url, 'title': safe_title}
        finally:
            page.close()
            if os.name == 'nt':
                try:
                    from common.ubuntu_naver_browser import close_account
                    close_account(cdp_port)
                except Exception:
                    pass


def get_asset_map_summary():
    """Generates an executive-level asset map summary for LLM context injection."""
    cf_summary = ', '.join([f'{d}({info["niche"]})' for d, info in list(CF_DOMAINS.items())[:6]]) + f' 외 {len(CF_DOMAINS)-6}개'
    naver_summary = ', '.join([f'{acc}({info["focus"]})' for acc, info in NAVER_ACCOUNTS.items()])
    kin_summary = ', '.join(KIN_ACCOUNTS.keys())
    return (
        "=== [BaroLab 전사 가용 자산 지도 (Asset Map)] ===\n"
        f"1. 캐시카우 (CF 블로그 16개): {cf_summary} (고단가 애드센스 수익화 종착지)\n"
        f"2. 검색 유입 브릿지 (네이버 블로그 5개): {naver_summary} (7:3 배분 실험 · 수명 효과 미검증)\n"
        f"3. 바이럴 숏테일 (스레드): @{THREADS_ACCOUNT['account_key']} (공식 Graph API + 크롬 9450)\n"
        f"4. 신뢰 솔루션 (지식iN): {kin_summary}\n"
        f"4-B. 고권위 칼럼 브릿지 (브런치): {BRUNCH_ACCOUNT['pen_name']} ({BRUNCH_ACCOUNT['url']} · CDP {BRUNCH_ACCOUNT['cdp_port']})\n"
        "5. 제휴마케팅 무기 (수익 2차 엔진):\n"
        "   - 리플알바 (CPA/CPC, ID: baro76650): 정책자금/대출/보험/렌탈 상담신청 · 실제 수수료는 해당 캠페인 조건 확인\n"
        "   - 트립닷컴 (CPS, AID: 7143081, SID: 263330208): tripmarvel.com/여행/축제/K-패스 글에 숙소·교통 예약 링크\n"
        "   - 쿠팡 파트너스 & 토스 쉐어링크: 생활/가전/금융 이벤트 직결 전환\n"
        "6. 컴퓨팅 인프라: 제미나이 2개 풀(baro76650, barolab26) + Codex(gpt-6.1-sol/luna) + Google Flow 이미지(CDP 9440)\n"
        "7. 운용 가설: 네이버 정보글 70%·CF 링크 30% 배분 및 애드센스·제휴 병행을 실험한다. 하루 $100는 목표이며 이 전략의 수익·계정 수명 효과는 미검증이다.\n"
        "=================================================="
    )
