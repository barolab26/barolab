"""Unified corporate asset map and cross-channel synergy engine for BaroLab.

Integrates 16 Cloudflare blogs, 5 Naver blogs, KnowledgeIn, Threads,
multi-account Gemini/Codex compute, Flow image generation, and the 7:3 Account Longevity Rule.
"""

from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
ROOT = Path(__file__).resolve().parents[2]

# 1. 16 Cloudflare Blogs (Cash-Cow AdSense Conversion Hubs)
CF_DOMAINS = {
    'must-pick.com': {'niche': '정책·금융·생활지원금', 'desc': '정부 정책자금, 국민취업지원제도, 지원금 신청 공식 가이드'},
    'must-good.com': {'niche': '복지·연금·노후설계', 'desc': '국민연금, 조기노령연금, 기초연금, 노후 건강보험 가이드'},
    'healthcox.com': {'niche': '건강·질환·의료혜택', 'desc': '건강보험 산정특례, 실손보험 청구, 질환별 영양·치료 혜택'},
    'must-joy.com': {'niche': '생활·문화·여가소비', 'desc': '문화누리카드, 청년 문화예술 패스, 알뜰 여가 혜택'},
    'maxnote.kr': {'niche': 'IT·모바일·스마트라이프', 'desc': '통신비 할인, 알뜰폰 요금제, 디지털 정책·앱 활용법'},
    'baronote.kr': {'niche': '세금·절세·연말정산', 'desc': '종합소득세, 연말정산 공제, 상속·증여세 실무 팁'},
    'topnote.kr': {'niche': '부동산·청약·주거복지', 'desc': '버팀목 전세자금, 디딤돌 대출, 청약통장 활용법'},
    'meganote.kr': {'niche': '소상공인·자영업·창업', 'desc': '소상공인 대환대출, 희망리턴패키지, 세무 절세법'},
    'justinfo.co.kr': {'niche': '시사·경제·트렌드', 'desc': '금리 변동, 물가 정책, 실생활 경제 지표 해설'},
    'smilenote.kr': {'niche': '육아·교육·청년지원', 'desc': '부모급여, 아동수당, 청년도약계좌, 국가장학금'},
    'tripmarvel.com': {'niche': '여행·지역축제·교통', 'desc': 'K-패스, 기후동행카드, 국내 여행 지원 사업'},
    'daynote.kr': {'niche': '일상생활·민원·법률상식', 'desc': '정부24 민원 발급, 주민등록, 생활 법률 팁'},
    'woorinote.kr': {'niche': '재테크·적금·예금', 'desc': '고금리 파킹통장, 특판 적금, 청년 적금 비교'},
    'nolplace.com': {'niche': '지역명소·핫플·문화공간', 'desc': '전국 숨은 힐링 명소, 지자체 무료 개방 시설'},
    'soulnote.kr': {'niche': '심리·자기계발·상담지원', 'desc': '전국민 마음투자 지원사업, 심리상담 바우처'},
    'joynote.kr': {'niche': '생활 꿀팁·가전·에너지지원', 'desc': '에너지바우처, 한전 고효율 가전 환급, 난방비 지원'},
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
    'soul5373': {'status': 'active', 'role': '생활 복지/건강 답변자'},
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


def match_synergy_cluster(topic_or_keyword):
    """Find the best CF Blog destination and cluster angle for a given topic."""
    kw = (topic_or_keyword or '').lower()
    if any(k in kw for k in ('건강', '보험', '의료', '병원', '약', '질환', '특례', '암')):
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
    return {
        'targetDomain': domain,
        'niche': target['niche'],
        'desc': target['desc'],
        'synergyAngle': f'네이버/스레드에서 궁금증 유발 후 상세 모의계산 및 자격 조회는 {domain} 심화 분석 글로 연결'
    }


def get_account_pacing_strategy(account, date_str=None):
    """Apply the current experimental 7:3 allocation; longevity effects are unverified.

    70% Pure Informational Posts (No external link, C-Rank DIA build-up).
    30% Strategic Bridge Posts (Natural anchor link to target CF Blog).
    Rule: Never bridge in consecutive posts on the same account.
    """
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
        "5. 제휴마케팅 무기 (수익 2차 엔진):\n"
        "   - 리플알바 (CPA/CPC, ID: baro76650): 정책자금/대출/보험/렌탈 상담신청 · 실제 수수료는 해당 캠페인 조건 확인\n"
        "   - 트립닷컴 (CPS, AID: 7143081, SID: 263330208): tripmarvel.com/여행/축제/K-패스 글에 숙소·교통 예약 링크\n"
        "   - 쿠팡 파트너스 & 토스 쉐어링크: 생활/가전/금융 이벤트 직결 전환\n"
        "6. 컴퓨팅 인프라: 제미나이 2개 풀(baro76650, barolab26) + Codex(gpt-6.1-sol/luna) + Google Flow 이미지(CDP 9440)\n"
        "7. 운용 가설: 네이버 정보글 70%·CF 링크 30% 배분 및 애드센스·제휴 병행을 실험한다. 하루 $100는 목표이며 이 전략의 수익·계정 수명 효과는 미검증이다.\n"
        "=================================================="
    )
