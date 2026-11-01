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

# 1. 16 Cloudflare Blogs (Cash-Cow AdSense Conversion Hubs — Strictly Aligned with DOMAIN_KEYWORD_MATRIX)
CF_DOMAINS = {
    'must-pick.com': {'niche': '가전·IT기어·에너지환급 비교', 'desc': '로봇청소기, 식기세척기, 제습기, 노트북·태블릿 스펙 비교, 으뜸효율 가전 환급, A/S 수리비용 가이드'},
    'must-good.com': {'niche': '정부지원금·청년장년복지·민원·세금환급', 'desc': '정부지원금, 국민취업지원제도, 부모급여, 건강보험료 환급, 정부24 민원 발급, 연말정산·종합소득세'},
    'healthcox.com': {'niche': '관절통증·국가건강검진·만성질환·영양의학', 'desc': '관절·디스크 통증 케어, 국가건강검진·내시경, 혈압·혈당·콜레스테롤 관리, 영양제·수면 의학'},
    'must-joy.com': {'niche': '로컬맛집·웨이팅·카페·전시공연 리뷰', 'desc': '백반기행·생활의달인 맛집 웨이팅·주차, 감성 카페·베이커리, 전시·팝업·공연 예매, 제철 특산물'},
    'maxnote.kr': {'niche': 'AI툴·업무자동화·노션·엑셀·알뜰폰', 'desc': '챗GPT·클로드 프롬프트, 노션·엑셀 함수 자동화, 크리에이터 편집 도구, 알뜰폰 요금제·모바일신분증'},
    'baronote.kr': {'niche': '국민기초연금·대출금리·카드혜택·보험절세', 'desc': '국민·기초·퇴직연금 수령액, 주담대·전세대출 금리·DSR 비교, 신용카드 캐시백, 실손보험·절세 전략'},
    'topnote.kr': {'niche': '윈도우·맥 설정·스마트폰·오피스·계정복구', 'desc': '윈도우11·맥북 오류·프린터 설정, 아이폰·갤럭시·카톡 백업·알뜰폰 eSIM, 엑셀·PDF 팁, 2단계인증·계정복구'},
    'meganote.kr': {'niche': '자동차·전기차보조금·다이렉트보험·생활금융', 'desc': '전기차·하이브리드 보조금, 다이렉트 자동차보험 특약·경정비·과태료, 마트 휴무일·온누리상품권·공과금 절약'},
    'justinfo.co.kr': {'niche': '세무절세·실업급여노무·소비자환불·과태료', 'desc': '실업급여·퇴직금·주휴수당 노무, 양도세·증여세·종합소득세 절세, 소비자 위약금·환불 분쟁, 생활법률·과태료'},
    'smilenote.kr': {'niche': '연금·은퇴설계·시니어혜택·중장년건강·돌봄', 'desc': '국민·기초·주택연금 은퇴설계, 시니어 경로우대·할인 바우처, 중장년 관절·근력 운동, 장기요양·임플란트·돌봄'},
    'tripmarvel.com': {'niche': '해외여행·항공숙소예약팁·국내여행·패스', 'desc': '항공권·수하물·보조배터리 규정, 호텔 무료취소·보증금·리조트피 방어, 트래블로그·환전·eSIM, 국내여행·KTX'},
    'daynote.kr': {'niche': '생활살림·물가절약·주방리빙·분리수거', 'desc': '식재료 냉장·냉동 보관법, 과탄산소다 배수구·세탁기 청소, 분리수거 과태료 기준, 전기세·가스비·관리비 절약'},
    'woorinote.kr': {'niche': '청약분양·전월세 계약법률·주거대출·등기세법', 'desc': '청약 가점·특별공급 분양, 전월세 확정일자·보증금 반환·전입신고, 디딤돌·버팀목 대출, 취득세·재산세·셀프등기'},
    'nolplace.com': {'niche': '수목원·테마파크·아이와나들이·축제·주차꿀팁', 'desc': '수목원·자연휴양림·캠핑장 예약, 주말 아이와 가볼만한곳, 시즌 축제·전시·팝업 일정, 무료주차·오픈런 동선'},
    'soulnote.kr': {'niche': '내일배움카드·국비지원·국가자격증·이직커리어', 'desc': '국민내일배움카드 국비 신청, 유망 국가기술자격증 시험일정·기출 독학팁, 이직·취업·경조사 예절 가이드'},
    'joynote.kr': {'niche': '강아지고양이건강·펫보험·애견동반·반려식물', 'desc': '강아지·고양이 증상·사료·예방접종, 동물병원 진료비·펫보험 비교, 애견동반 카페·숙소·산책로, 반려식물 분갈이·물주기'},
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

# 4-B. Brunch Story (Kakao/Daum & Google High-DA Essay Column Bridge)
BRUNCH_ACCOUNT = {
    'account_key': 'baro76650',
    'email': 'baro76650@gmail.com',
    'profile_id': '31d1f5fb288c4fc',
    'pen_name': '머스트픽',
    'url': 'https://brunch.co.kr/@31d1f5fb288c4fc',
    'cdp_port': 9450,
    'status': 'writer_application_submitted',
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
    """Return today's verified published CF landing pages ranked by topic match & cash-cow priority."""
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
        for day_dir in sorted(cf_sched_root.iterdir(), reverse=True)[:2]:
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
    tokens = [t for t in re.split(r'[\s,·/()|\[\]-]+', str(topic_or_keyword or '').lower()) if len(t) >= 2]
    def _score(row):
        hay = f"{row['title']} {row['category']} {row['domain']} {CF_DOMAINS.get(row['domain'], {}).get('niche', '')}".lower()
        kw_hits = sum(3 for t in tokens if t in hay)
        cash_bonus = (10 - PRIORITY_CASHCOW_DOMAINS.index(row['domain'])) if row['domain'] in PRIORITY_CASHCOW_DOMAINS else 1
        return (kw_hits, cash_bonus)
    candidates.sort(key=_score, reverse=True)
    return candidates


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
    """Write or update a Brunch column on CDP 9450. Publishes live if writer is approved, otherwise saves to drawer."""
    from playwright.sync_api import sync_playwright

    safe_title = _fit_brunch_text(title, 28)
    safe_subtitle = _fit_brunch_text(subtitle, 38)

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
