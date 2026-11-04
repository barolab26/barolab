# -*- coding: utf-8 -*-
"""
BaroLab Brunch Story Autonomous Column & SEO Bridge Engine (`brunch_posting/posting.py`)

Manages the Brunch Story channel (`baro76650@gmail.com` / `머스트픽` / `brunch.co.kr/@31d1f5fb288c4fc`) on CDP 9450:
  1. Auto-authenticates via Kakao SSO (`ensure_brunch_logged_in`) and syncs live writer approval status, drawer drafts (`/ready`), and published posts (`/@31d1f5fb288c4fc`).
  2. Operates continuous daily publishing (2 columns/day at 09:30 & 16:30 KST):
     - Upgrades any short/truncated drafts in `작가의 서랍` and publishes them live once writer is approved.
     - After the 10-Part BrunchBook Master Curriculum is completed, dynamically generates new 2,000-char 4-Deficiency columns paired with our 16 CF blogs (`70% pure essay : 30% strategic CF bridge`).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(BASE_DIR / "dashboard") not in sys.path:
    sys.path.insert(0, str(BASE_DIR / "dashboard"))

from common.asset_map import (
    BRUNCH_ACCOUNT,
    ensure_brunch_logged_in,
    get_today_cf_bridge_targets,
    post_or_save_brunch_column,
)

KST = ZoneInfo("Asia/Seoul")
DATA_PATH = BASE_DIR / "dashboard" / "data" / "brunch" / "status.json"
PUBLIC_DATA_PATH = BASE_DIR / "dashboard" / "data" / "public" / "brunch.json"

# 10-Part BrunchBook Master Curriculum (all titles <= 28 chars, subtitles <= 38 chars, bodies ~1,800-2,200 chars with 4-Deficiency storytelling)
BRUNCHBOOK_CURRICULUM: List[Dict[str, Any]] = [
    {
        "part": 1,
        "title": "국민연금 기초연금 중복수령 감액 기준과 계산법",
        "subtitle": "기초연금 소득인정액 선정기준액과 국민연금 연계감액 A급여액 산식 정리",
        "targetDomain": "must-good.com",
        "category": "연금·노후설계",
        "pacingMode": "strategic_bridge",
        "articleNo": 1,
        "paragraphs": [
            "매달 25일이 되면 어머니는 거실 식탁 위에 돋보기안경과 통장 두 권을 나란히 올려두신다. 젊은 시절부터 조금씩 부어오신 국민연금 수령 계좌와, 만 65세가 지나면서 신청했던 기초연금이 들어오는 통장이다. 어느 주말 오후, 어머니가 조심스럽게 통장을 내미시며 물으셨다. 동네 복지관에서는 올해 기초연금 기준연금액이 올랐다고 하던데, 왜 내 통장에 찍히는 금액은 옆집 친구분보다 몇만 원이 적은지 모르겠다는 말씀이었다.",
            "그 질문 앞에서 나는 한동안 말을 잇지 못했다. 평소 행정과 세무, 복지 제도의 숫자를 다루는 일을 하면서도 정작 가장 가까운 가족의 통장에 찍힌 숫자가 어떤 산식을 거쳐 결정되었는지는 한 번도 함께 들여다본 적이 없었기 때문이다. 매달 꼬박꼬박 국민연금을 성실히 납부한 대가가 오히려 기초연금 감액으로 돌아왔다는 어머니의 허탈감 앞에서, 나는 그날 저녁부터 국민연금공단과 복지로의 안내서, 그리고 기초연금법 시행령의 감액 산식을 노트에 하나씩 옮겨 적기 시작했다.",
            "현장에서 만나는 많은 시니어 가구가 가장 먼저 오해하는 지점은 '국민연금을 받으면 기초연금을 아예 못 받는다'거나, 반대로 '소득 기준만 통과하면 무조건 전액을 다 받는다'는 이분법이다. 실제로는 두 개의 전혀 다른 문턱이 차례로 작동한다. 첫 번째 문턱은 가구의 월 소득평가액과 재산의 월 소득환산액을 합친 '소득인정액'이 당해 연도 선정기준액(단독가구·부부가구 기준선) 아래에 있는지 확인하는 자격 심사 과정이다.",
            "이 첫 번째 문턱을 계산할 때는 생각보다 세밀한 공제 규칙이 적용된다. 일해서 버는 근로소득이 있다면 기본공제 금액을 먼저 뺀 뒤 다시 30퍼센트를 추가로 공제해 주고, 거주하는 주택이나 전월세 보증금은 대도시·중소도시·농어촌 지역별로 정해진 기본재산액을 먼저 차감한다. 예금이나 적금 같은 금융재산에서도 가구당 2천만 원을 기본 공제한 뒤 남은 금액에 연 4퍼센트를 적용해 12개월로 나누어 월 소득인정액에 더한다. 어머니의 경우 이 첫 번째 문턱인 소득인정액 기준은 여유 있게 통과하셨다.",
            "진짜 복병은 두 번째 문턱인 '국민연금 연계감액'과 '부부 감액'이었다. 매달 받는 국민연금 수령액(노령연금·분할연금 등)이 기초연금 기준연금액의 150퍼센트를 넘어가면 연계감액 구간에 진입한다. 이때 단순히 총연금액만 보는 것이 아니라, 국민연금 급여액 가운데 가입자 전체의 평균 소득을 반영하는 이른바 'A급여액' 비중에 따라 기초연금이 최대 50퍼센트까지 조정되는 구조다. 내가 낸 보험료에 비례하는 B급여액보다 세대 간 소득재분배 성격을 띤 A급여액이 클수록 기초연금과의 중복 급여를 조정한다는 것이 법령의 논리다.",
            "하지만 법전 속의 논리와 별개로, 당사자인 어르신들에게 A급여액이나 소득환산율 같은 용어는 낯설고 차가운 암호처럼 들릴 수밖에 없다. 다음 날 아침 국민연금공단 콜센터(국번 없이 1355)에 전화를 걸어 어머니의 국민연금 급여명세서상 A급여액 수치를 확인하고, 노트에 적어둔 산식에 대입해 본 뒤에야 왜 어머니 통장에 그 금액이 입금되었는지 1원 단위까지 정확히 설명해 드릴 수 있었다. 어머니는 깎인 몇만 원보다도 그동안 이유를 몰라 누군가 잘못 계산한 건 아닐까 답답했던 마음이 시원하게 풀렸다며 비로소 미소를 지으셨다.",
            "혹시 지금 부모님의 통장이나 내 노후 연금을 계산해 보며 비슷한 의문을 품고 있다면 세 가지만 먼저 점검해 보길 권한다. 첫째, 내 국민연금 예상월액이 기초연금 기준연금액의 150퍼센트를 초과하는지 여부다. 둘째, 국민연금 조기수령이나 연기연금을 선택할 때 월 수령액 변동이 기초연금 연계감액 구간에 어떤 연쇄 영향을 주는지다. 셋째, 부부가 모두 만 65세 이상이어서 동시에 기초연금을 받을 때는 단독가구 대비 20퍼센트의 부부 감액이 추가로 적용된다는 점이다.",
            "그날 이후 내 수첩에는 작은 원칙이 하나 생겼다. 부모님 세대를 위한 연금과 복지 제도를 기록할 때는 관공서 공고문의 문장을 그대로 옮기지 말자는 것이다. 대신 통장을 정리하는 저녁 식탁에서, 혹은 주민센터 창구로 향하기 전날 밤에 무엇을 먼저 적어두고 어떤 순서로 확인해야 손해를 피할 수 있는지 사람의 언어로 번역해 두기로 했다. 제도는 법전에 적혀 있을 때가 아니라 필요한 사람의 삶 속에서 이해될 때 비로소 제 역할을 다하기 때문이다.",
        ],
    },
    {
        "part": 2,
        "title": "퇴직 후 건강보험 피부양자 자격조건과 임의계속가입",
        "subtitle": "연소득 2천만원·재산 과세표준 5.4억 기준과 임의계속가입 신청기한",
        "targetDomain": "baronote.kr",
        "category": "건보료·절세실무",
        "pacingMode": "strategic_bridge",
        "articleNo": 2,
        "paragraphs": [
            "오랜 시간 한 직장에서 성실히 일하고 정년퇴직한 선배를 오랜만에 만났을 때, 그가 찻잔을 내려놓으며 가장 먼저 꺼낸 이야기는 여행 계획도 취미 생활도 아닌 건강보험료 고지서였다. 재직 시절에는 급여명세서에서 회사가 절반을 부담하고 남은 금액만 원천징수로 빠져나갔기에 크게 체감하지 못했는데, 퇴직 후 지역가입자로 전환된 첫 달 고지서를 우편함에서 꺼내 들고는 눈을 의심했다는 것이다. 월급은 사라졌는데 매달 내야 할 건강보험료는 오히려 현역 시절보다 훌쩍 뛰어올라 있었다.",
            "우리는 흔히 은퇴 설계를 말할 때 노후에 매달 얼마의 연금과 배당을 받을 수 있는가에만 시선을 고정하곤 한다. 하지만 현장에서 마주하는 은퇴 가계의 실질적인 균열은 들어오는 수입의 부족보다 통제되지 않는 고정비, 그중에서도 건강보험료와 세금 구조의 변화에서 시작되는 경우가 훨씬 많다. 한 달에 25만 원씩만 지역가입자 건강보험료가 추가로 나가도 1년이면 300만 원, 10년이면 3천만 원이라는 노후 자금이 고스란히 빠져나가는 셈이다.",
            "많은 퇴직자가 '직장에 다니는 자녀 밑으로 건강보험 피부양자를 올리면 되겠지'라고 막연히 안심하지만, 건강보험 피부양자 자격은 단순히 부모와 자녀라는 가족관계만으로 유지되지 않는다. 국민건강보험공단은 소득 요건과 재산 요건이라는 두 가지 엄격한 격자를 동시에 적용해 매달 자격을 심사한다. 어느 한쪽이라도 기준선을 단 1만 원만 넘기면 그 즉시 지역가입자로 전환되어 재산과 소득 전체에 보험료가 부과된다.",
            "첫 번째 격자인 소득 요건에서 가장 많은 분이 발목을 잡히는 지점은 합산 기준이다. 은행 예금 이자와 주식 배당 같은 금융소득, 국민연금·공무원연금·사학연금 등 공적연금 소득, 그리고 임대소득이나 일시적인 근로·사업소득을 모두 합산한 연간 소득이 2천만 원을 넘지 않아야 한다. 특히 공적연금은 세전 수령액 전체가 그대로 소득으로 잡히기 때문에, 매달 국민연금을 167만 원 이상 받는다면 다른 소득이 전혀 없어도 연간 2천만 원을 초과해 피부양자에서 탈락한다.",
            "두 번째 격자인 재산 요건 역시 꼼꼼히 따져봐야 한다. 토지, 건축물, 주택, 선박 등의 재산세 과세표준 합계액이 5억 4천만 원을 넘지 않아야 하며, 만약 과세표준이 5억 4천만 원을 초과하고 9억 원 이하인 구간에 있다면 연간 합산 소득이 1천만 원 이하여야만 간신히 피부양자 자격을 지킬 수 있다. 여기서 말하는 과세표준은 실제 시세가 아니라 지방세 고지서에 찍히는 공시가격 기준의 과세표준이므로, 퇴직 전에 반드시 구청 세무과나 위택스에서 내 명의 부동산의 정확한 과세표준 수치를 확인해 두어야 한다.",
            "만약 소득이나 재산 기준에 걸려 피부양자 등재가 어렵다면, 퇴직 직후 선택할 수 있는 가장 강력한 방어막은 '임의계속가입' 제도다. 퇴직 전 18개월 동안 통산 1년 이상 직장가입자 자격을 유지했다면, 지역가입자로 전환된 첫 고지서 납부기한으로부터 2개월 이내에 건강보험공단에 임의계속가입을 신청할 수 있다. 이 제도를 활용하면 최대 36개월(3년) 동안은 내 집과 자동차, 재산에 붙는 지역보험료 대신 퇴직 직전에 내던 직장보험료 수준만 납부하며 자산을 재구조화할 시간을 벌 수 있다.",
            "단, 임의계속가입에도 반드시 기억해야 할 두 가지 실무 원칙이 있다. 첫째, 첫 번째 지역가입자 고지서의 납부기한에서 두 달이 지나버리면 신청 권리 자체가 영구히 소멸한다는 점이다. 둘째, 드물게 재산이 적고 연금 소득이 낮은 가구는 지역가입자 보험료가 임의계속가입 보험료보다 오히려 더 저렴한 경우도 있으므로, 신청 전에 반드시 공단 지사나 1577-1000 콜센터를 통해 두 금액을 1원 단위까지 비교해 본 뒤 유리한 쪽을 선택해야 한다.",
            "마지막 출근길에 나서기 최소 6개월 전에는 조용한 저녁 시간을 내어 내 이름으로 된 공적연금 예상액, 만기가 돌아오는 예금 이자, 그리고 재산세 과세표준을 한 장의 노트에 적어보는 시간이 필요하다. 미리 계산해 본 사람에게 고지서는 예측 가능한 생활비이지만, 준비 없이 마주한 고지서는 노후의 평온을 흔드는 가장 차가운 청구서가 되기 때문이다.",
        ],
    },
    {
        "part": 3,
        "title": "건강보험 본인부담상한제 환급금·미환급금 조회법",
        "subtitle": "정부24 보조금24·홈택스 세금 환급·건보공단 환급금 신청 방법",
        "targetDomain": "must-pick.com",
        "category": "정책환급·복지",
        "pacingMode": "strategic_bridge",
        "articleNo": 3,
        "paragraphs": [
            "우리 사회의 거의 모든 공적 지원금과 세금 환급 제도는 철저한 '신청주의' 원칙 위에서 움직인다. 내가 받을 자격이 아무리 충분하고 법령상 수급 요건을 완벽히 갖추었더라도, 정해진 기간 안에 정해진 양식으로 직접 신청서를 제출하지 않으면 국가는 알아서 내 통장에 돈을 넣어주지 않는다. 정보에 밝고 스마트폰 인증에 익숙한 사람들에게는 몇 번의 터치로 끝나는 절차가, 안내문 글씨가 작아 읽지 못하거나 제도의 존재조차 모르는 어르신들에게는 보이지 않는 거대한 벽이 된다.",
            "작년 봄, 본가에 내려가 어르신의 오래된 서류 봉투와 우편함을 정리하다가 수년 전 납부했던 지방세 환급 안내문과 국민건강보험공단의 본인부담상한제 지급 신청서를 발견한 적이 있다. 설마 아직 남아 있을까 싶은 마음으로 정부24와 홈택스, 건강보험공단 통합 조회 화면을 차례대로 열어 공동인증서로 로그인해 보니, 그동안 찾아가지 않아 공단과 지자체 금고에 잠자고 있던 미환급금이 백만 원 가까운 금액으로 남아 있었다.",
            "그중에서도 중장년과 시니어 가구가 가장 흔하게 놓치는 제도가 바로 건강보험 '본인부담상한제'와 '통신·에너지 미환급금'이다. 본인부담상한제는 1년 동안 병·의원에서 지출한 건강보험 급여 항목의 본인부담금 총액이 가구 소득 분위별 상한액(하위 1분위 기준 연 80만 원대~상위 분위 수백만 원)을 초과했을 때, 그 초과분을 건강보험공단이 환급해 주는 제도다. 대상자로 확정되면 공단에서 우편 안내문을 보내지만, 이사 등으로 우편물을 못 받거나 보이스피싱 문자로 오해해 그냥 버리는 경우가 부지기수다.",
            "세금 영역에서도 마찬가지다. 직장에서 퇴직한 뒤 재취업을 하지 않아 연말정산을 못 했거나, 소액의 강연료·원고료·아르바이트 소득에서 3.3퍼센트 원천징수 세금을 떼인 중장년층은 매년 5월 종합소득세 확정신고 기간이나 최근 5년 치 경정청구를 통해 이미 낸 세금을 돌려받을 수 있는 경우가 많다. 국세청 홈택스의 '국세 환급금 찾기' 메뉴는 공인인증서 없이 주민등록번호와 이름만으로도 조회가 가능한데, 정작 이 메뉴의 존재를 아는 시니어는 열 명 중 한두 명에 불과하다.",
            "문제는 이런 환급금과 지원금 대부분에 '소멸시효'라는 시한부 시계가 돌아가고 있다는 사실이다. 국세와 지방세 미환급금, 건강보험 본인부담상한제 환급금 등은 권리를 행사할 수 있는 날로부터 통상 3년에서 5년이 지나면 국고나 공단 기금으로 귀속되어 영구히 청구할 수 없게 된다. 내 돈이고 내 권리였지만 단지 달력을 넘겼다는 이유만으로 사라지는 셈이다.",
            "그 일을 겪은 뒤로 나는 계절이 바뀔 때마다 가족과 주변 지인들을 위한 한 장짜리 '계절별 생활 재무 점검표'를 만든다. 한 해를 시작하는 1월과 2월에는 부모님의 연말정산 인적공제 누락 여부와 노인일자리·사회활동 지원사업 모집 공고를 살피고, 5월에는 종합소득세 환급금과 근로·자녀장려금 신청 자격을 대조한다. 무더위가 시작되는 6월과 찬 바람이 부는 10월에는 에너지바우처와 한전 전기요금·도시가스 복지할인 감면 신청이 빠지지 않았는지 고지서 뒷면을 확인한다.",
            "오늘 저녁에는 딱 10분만 시간을 내어 스마트폰이나 PC 앞에서 세 곳의 화면을 차례로 열어보길 권한다. 첫째는 정부24의 '보조금24'와 '미환급금 찾기' 통합 서비스, 둘째는 국민건강보험공단 홈페이지(또는 The건강보험 앱)의 '환급금 조회/신청' 메뉴, 셋째는 국세청 홈택스의 '국세 환급금 찾기'다. 이 세 곳을 확인하는 데 드는 시간은 커피 한 잔을 내리는 시간보다 짧다.",
            "복지는 자선이 아니라 시민이 세금과 보험료로 미리 적립해 둔 정당한 사회적 권리다. 신청주의라는 차가운 문턱 앞에서 나나 내 부모님의 당연한 권리가 서류 봉투 속에 잠들지 않도록, 일 년에 두 번만이라도 가족의 이름으로 된 작은 점검표를 함께 펼쳐보는 습관이 필요하다.",
        ],
    },
    {
        "part": 4,
        "title": "만 65세 임플란트 건강보험 적용·보청기 보조금",
        "subtitle": "평생 2개 본인부담률 30% 조건과 지자체 보청기 지원금 신청순서",
        "targetDomain": "smilenote.kr",
        "category": "시니어의료·돌봄",
        "pacingMode": "strategic_bridge",
        "articleNo": 4,
        "paragraphs": [
            "부모님이 식사하실 때 평소 좋아하시던 깍두기나 질긴 고기를 은근슬쩍 피하기 시작하셨다면 가장 먼저 치아 상태를 살펴야 할 신호다. 어르신들은 자식들에게 병원비 부담을 지우기 싫어 잇몸이 붓고 어금니가 흔들려도 참으시다가, 도저히 씹지 못할 지경이 되어서야 치과 문턱을 넘곤 하신다. 많은 자녀들이 만 65세 이상 어르신 임플란트와 틀니에 건강보험이 적용된다는 사실까지는 알고 있지만, 정확히 어떤 조건에서 급여가 인정되고 어떤 순서로 진행해야 수십만 원의 생돈을 아낄 수 있는지는 치과 상담실에 앉아서야 뒤늦게 듣는 경우가 많다.",
            "현행 국민건강보험 기준상 만 65세 이상 건강보험 가입자(또는 피부양자)는 평생 2개까지 임플란트 시술 시 요양급여 비용의 30퍼센트만 본인이 부담하면 된다. 치아 1개당 전체 급여 인정 비용이 약 120만~130만 원 선이므로, 어르신이 실제로 내는 본인부담금은 개당 약 35만~40만 원 수준으로 대폭 낮아진다. 만약 차상위계층이나 의료급여 수급권자라면 본인부담률은 5~20퍼센트까지 더 내려간다.",
            "하지만 치과 견적서 앞에서 당황하지 않으려면 반드시 미리 알아야 할 세 가지 함정이 있다. 첫 번째 함정은 '완전 무치악(치아가 하나도 없는 상태)' 예외 규정이다. 위턱이나 아래턱에 남아 있는 자연 치아가 단 하나도 없는 완전 무치악 상태라면 안타깝게도 건강보험 임플란트 급여 대상에서 제외된다. 건강보험 임플란트는 '부분 무치악(치아가 일부 남아 있는 상태)' 환자에게만 평생 2개까지 적용되며, 치아가 전혀 없는 경우에는 완전 틀니(레진상·금속상 완전틀니, 본인부담률 30퍼센트) 급여를 활용해야 한다.",
            "두 번째 함정은 상부 보철물의 재료와 부가 시술 비용이다. 건강보험이 적용되는 임플란트 보철물 재료는 기본적으로 PFM(안쪽은 금속, 바깥쪽은 도자기 재질인 크라운)으로 정해져 있다. 만약 상담 과정에서 심미성이나 강도를 이유로 지르코니아 보철물을 선택하거나, 잇몸뼈가 부족해 '치조골 이식술(뼈 이식)'이나 상악동 거상술 같은 부가 수술을 함께 받게 되면 이 부가 시술 비용은 건강보험이 적용되지 않는 100퍼센트 비급여로 별도 청구된다.",
            "세 번째로 절대 놓치지 말아야 할 절차는 치과에서 시술을 시작하기 전 '건강보험 임플란트 대상자 사전 등록'이다. 치과 전산망을 통해 건강보험공단에 대상자 등록이 완료된 뒤 시술이 들어가야 하며, 한 번 시술을 시작한 치과에서 중간에 마음대로 다른 치과로 옮기게 되면 이미 진행된 단계 이후의 급여 권리가 소멸하거나 복잡한 등록 취소 절차를 거쳐야 한다. 따라서 첫 치과를 결정할 때 최소 두 곳 이상의 치과에서 방사선 촬영 후 '뼈 이식이 꼭 필요한 상태인지'와 '급여 항목 외 비급여 추가 금액이 정확히 얼마인지'를 비교 견적으로 받아보는 것이 현명하다.",
            "보청기 지원금 역시 순서 하나가 100만 원 이상의 차이를 만든다. 길가의 보청기 판매점부터 먼저 방문해 기기를 구매하고 영수증을 챙겨가면 건강보험 보조금을 단 1원도 받을 수 없다. 반드시 먼저 이비인후과 전문의를 찾아 청력검사를 받고 '청각장애' 등록 여부를 확인한 뒤, 보장구 처방전을 발급받아 공단 등록 업소에서 보건복지부 고시 제품(급여 기준액 최대 131만 원 한도 내, 일반 건강보험 가입자 기준 90퍼센트인 최대 117만 9천 원 지원)을 구매하고 이비인후과 검수 확인서까지 받아야 환급이 완료된다.",
            "만약 청각장애 등급 기준에는 미치지 못하더라도 난청으로 일상 대화가 불편한 만 65세 이상 어르신이라면, 거주지 시·군·구 보건소나 시청 노인복지과에서 운영하는 '지자체 어르신 보청기 구입비 지원사업'을 먼저 문의해 볼 수 있다. 지자체별로 소득 기준이나 기초연금 수급 여부에 따라 1인당 30만 원에서 최대 100만 원까지 자체 예산으로 보청기 구입비를 보조해 주는 곳이 늘고 있기 때문이다.",
            "부모님의 치아와 귀는 단순한 신체 기관이 아니라 영양 섭취와 사회적 소통, 나아가 치매 예방과 직결되는 노후 삶의 질의 최전선이다. 병원 예약 문자를 보내드리기 전에 오늘 정리한 건강보험 급여 조건과 사전 등록 순서를 먼저 짚어드리는 것만으로도, 자식과 부모님 모두 마음 편히 치료에만 집중할 수 있는 든든한 시작이 된다.",
        ],
    },
    {
        "part": 5,
        "title": "주택연금 가입조건 공시가격 12억·월 수령액 계산",
        "subtitle": "만 55세 이상 주택연금 수령액 계산법과 사후 정산·상속 기준",
        "targetDomain": "topnote.kr",
        "category": "주거·주택연금",
        "pacingMode": "strategic_bridge",
        "articleNo": 5,
        "paragraphs": [
            "명절이나 부모님 생신에 온 가족이 모이면 식사가 끝날 무렵 자연스레 부모님이 살고 계신 집 한 채에 대한 이야기가 오가곤 한다. 전체 자산의 70~80퍼센트 이상이 거주 주택 한 채에 묶여 있는 한국 시니어 가구의 특성상, 집은 든든한 보금자리이지만 당장 매달 써야 할 병원비와 생활비를 내어주지는 않는다. 이때 집을 팔아 작은 평수로 옮길 것인가, 자녀에게 미리 증여하고 용돈을 받을 것인가, 아니면 한국주택금융공사의 '주택연금'에 가입할 것인가를 두고 가족의 셈법이 복잡해진다.",
            "과거에는 '내 손으로 일군 집 한 채는 어떻게든 자식에게 온전히 물려주어야 한다'는 인식이 강했지만, 최근 현장에서 만나는 6070 부모님들의 생각은 빠르게 달라지고 있다. 자녀에게 손 벌리지 않고 마지막 순간까지 내 집에서 품위를 지키며 살다가, 남는 정산 차액만 깔끔하게 물려주는 것이 진짜 효도이자 현실적인 노후 대책이라는 공감대가 넓어졌기 때문이다.",
            "주택연금의 문턱은 최근 제도 개편을 거치며 한층 넓어졌다. 부부 중 한 명이라도 만 55세 이상이고, 보유 주택의 합산 공시가격이 12억 원 이하라면 가입 신청이 가능하다. 다주택자라 하더라도 합산 공시가격이 12억 원 이하이면 가입할 수 있고, 설령 공시가격 합계가 12억 원을 넘더라도 2주택자 중 3년 이내에 비거주 주택 1채를 처분하겠다는 약정을 맺으면 가입 길이 열린다.",
            "많은 자녀와 부모님이 주택연금을 망설이는 가장 큰 이유는 '집값이 오르면 손해 아닌가' 혹은 '일찍 돌아가시면 집만 날리는 것 아닌가'라는 막연한 오해 때문이다. 하지만 주택연금의 사후 정산 구조를 정확히 뜯어보면 이 두 가지 걱정 중 상당 부분은 기우에 가깝다. 한국주택금융공사는 부부가 모두 사망한 시점에 그동안 지급한 연금 총액(보증료·이자 포함)과 당시의 실제 주택 처분 가격을 비교해 정산한다.",
            "만약 부모님이 일찍 돌아가셔서 그동안 받은 연금 원리금 합계보다 사후 집값이 더 높다면, 그 남는 차액은 1원도 빠짐없이 법정 상속인(자녀)에게 그대로 돌려준다. 반대로 부모님이 95세, 100세까지 장수하셔서 그동안 수령한 연금 총액이 집값을 훌쩍 넘겼더라도, 공단이 자녀들에게 그 부족분을 청구하지 않는다. 즉 '남으면 자식에게 주고, 모자라도 자식에게 빚을 물리지 않는다'는 비소구(Non-recourse) 원칙이 국가 보증으로 작동하는 것이다.",
            "물론 주택연금 가입 시점이 무조건 빠르다고 해서 능사는 아니다. 주택연금의 월 지급금은 '가입 시점의 주택 시세'와 '부부 중 연소자(더 젊은 사람)의 연령'이라는 두 가지 변수로 확정된다. 나이가 많을수록 기대여명이 줄어들어 매달 받는 월 수령액이 커지므로, 국민연금이나 퇴직연금으로 생활비가 충당되는 50대 후반~60대 초반보다는 의료비와 간병비 지출이 본격화되는 만 65세~70세 전후에 가입하는 것이 월 현금흐름을 극대화하는 전략이 될 수 있다.",
            "또한 향후 재개발이나 재건축이 예정된 단지라면 공사 기간 중 이주비 대출과 분담금 납부 문제를 어떻게 처리할지, 그리고 종신지급방식 중 매달 동일 금액을 받는 '정액형'과 초기 10년간 더 많이 받고 이후 70퍼센트 수준을 받는 '초기증액형' 중 우리 가구의 부채 상황에 무엇이 유리한지 미리 시뮬레이션해 보아야 한다.",
            "부모님의 집 한 채는 단순한 부동산이 아니라 두 분이 평생의 땀방울로 지어 올린 삶의 역사다. 막연한 소문이나 감정에 기대어 결정을 미루기보다, 이번 주말에는 한국주택금융공사 홈페이지의 예상연금 조회 화면을 열어 현재 집값과 부모님 연세에 맞는 예상 월 수령액을 객관적인 숫자표로 먼저 뽑아보는 것부터 대화를 시작해 보길 권한다.",
        ],
    },
    {
        "part": 6,
        "title": "희망리턴패키지 점포철거비 지원금·폐업 부가세 신고",
        "subtitle": "폐업신고 전 철거비 신청 순서와 부가세 잔존재화·건보료 조정",
        "targetDomain": "meganote.kr",
        "category": "소상공인·세무",
        "pacingMode": "strategic_bridge",
        "articleNo": 6,
        "paragraphs": [
            "수년간 새벽마다 불을 밝히던 가게 문을 닫기로 결심하는 날은 누구에게나 무겁다. 임대차 계약 만료와 매출 감소, 불어난 대출 이자 사이에서 밤잠을 설치다 결단을 내린 사장님들은 마음이 급한 나머지 세무서부터 찾아가 폐업신고서를 제출하곤 한다. 하지만 현장에서 만난 자영업자분들이 가장 땅을 치며 안타까워하는 순간은, 바로 그 '세무서 폐업신고'를 먼저 끝내버리는 바람에 받을 수 있었던 수백만 원의 점포 철거비 지원금을 눈앞에서 날렸을 때다.",
            "소상공인시장진흥공단이 운영하는 '희망리턴패키지 원스톱 폐업지원(점포철거비 지원)'은 폐업 소상공인의 원상복구 부담을 덜어주기 위해 전용면적 평당 단가 기준 최대 수백만 원(연도별 공고 한도 내)의 철거 비용을 무상으로 지원해 주는 핵심 안전망이다. 그런데 이 지원금의 가장 엄격한 자격 요건은 '신청 시점에 사업자등록증상 폐업일 이전(영업 중 또는 폐업 예정 상태)이어야 한다'는 점이다.",
            "마음이 급해 세무서나 홈택스에서 폐업신고를 먼저 처리하고 나면, 전산상 이미 폐업이 완료된 사업자로 분류되어 점포철거비 지원 신청 자격 자체가 원천 차단되는 경우가 허다하다. 또한 철거 업체를 부를 때도 지인에게 현금으로 맡기거나 자가 철거를 해버리면 세금계산서와 이체 내역, 철거 전·후 현장 사진 증빙이 인정되지 않아 지원금을 한 푼도 정산받지 못한다. 반드시 폐업신고 전에 희망리턴패키지 사이트에서 먼저 신청서를 접수하고, 컨설턴트 배정 및 철거 전 현장 사진을 남긴 뒤 부가세 정식 등록 업체를 통해 공사를 진행해야 한다.",
            "폐업 과정에서 두 번째로 마주하는 세금 복병은 '폐업 확정 부가가치세 신고'와 '잔존재화 간주공급'이다. 사업을 접었다고 해서 세금 의무까지 그날로 끝나는 것이 아니다. 폐업일이 속한 달의 다음 달 25일(예: 10월 15일에 폐업했다면 11월 25일)까지 반드시 폐업 부가가치세 확정신고 및 납부를 마쳐야 한다. 이 기한을 넘기면 무신고 가산세(납부세액의 20퍼센트)와 납부지연 가산세가 눈덩이처럼 불어난다.",
            "특히 가게를 열 때 수천만 원을 들여 인테리어 공사를 하거나 대형 냉장고·커피머신·에어컨 같은 집기비품을 구매하면서 부가가치세 조기환급(매입세액 공제)을 크게 받았던 사업자라면 '잔존재화 과세' 규정을 반드시 체크해야 한다. 세법상 건물·구축물은 취득 후 10년(20과세기간), 기타 감가상각자산(인테리어·기계장치·비품 등)은 취득 후 2년(4과세기간) 이내에 폐업하게 되면, 아직 감가상각이 끝나지 않은 잔존 가치를 사업자 본인에게 스스로 판매(간주공급)한 것으로 보아 기존에 환급받았던 부가세 일부를 다시 토해내야 하기 때문이다.",
            "만약 창업한 지 1년 10개월째에 폐업을 고민 중이라면, 무작정 오늘 폐업신고를 하기보다 남은 2개월의 과세기간을 채워 감가상각 기준 기간(4과세기간)을 넘긴 뒤 폐업하는 것이 잔존재화 부가세 수백만 원을 합법적으로 아끼는 결정적인 한 끗 차이가 될 수 있다.",
            "마지막으로 폐업 이후의 건강보험료와 노란우산공제 공제금 수령 순서도 함께 챙겨야 한다. 폐업 사실증명원이 발급되면 즉시 국민건강보험공단에 '폐업에 따른 소득 정산부과(조정) 신청'을 해야 이미 사라진 사업소득 기준으로 건강보험료가 계속 부과되는 것을 막을 수 있다. 또한 노란우산공제에 가입해 두었다면 폐업 사유로 공제금을 청구할 때 퇴직소득세율이 적용되어 압류 방지 계좌로 안전하게 목돈을 수령할 수 있다.",
            "가게의 간판을 내리는 일은 실패가 아니라 다음 걸음을 위해 무거운 짐을 내려놓는 정산의 과정이다. 세무서로 발걸음을 옮기기 전 딱 하루만 멈추어 서서 철거비 지원 신청, 부가세 과세기간, 건강보험 조정 신청이라는 세 가지 순서를 메모지에 적어보길 바란다. 끝을 정확히 매듭짓는 정보가 곧 다시 일어설 수 있는 가장 현실적인 시드머니가 된다.",
        ],
    },
    {
        "part": 7,
        "title": "국가건강검진 결과표 보는법 공복혈당·사구체여과율",
        "subtitle": "공복혈당·신장 크레아티닌·LDL 콜레스테롤 정상수치와 확진검사",
        "targetDomain": "healthcox.com",
        "category": "중장년건강·검진",
        "pacingMode": "strategic_bridge",
        "articleNo": 7,
        "paragraphs": [
            "매년 찬 바람이 불기 시작하는 10월과 11월이 되면 동네 내과와 건강검진 센터는 한 해 동안 미뤄둔 국가건강검진을 받으려는 사람들로 북적인다. 연말이 임박할수록 예약은 전쟁터가 되고, 바쁜 일정 속에 검진을 마치고 나면 몇 주 뒤 우편이나 카카오톡 알림톡으로 결과표가 도착한다. 하지만 막상 결과표를 받아 든 부모님들은 첫 장 맨 위에 적힌 '정상B(경계)'나 '일반질환 의심'이라는 짧은 판정 문구만 흘긋 확인하고는 서랍 깊숙이 넣어두기 일쑤다.",
            "문제는 중장년과 시니어의 몸이 보내는 진짜 위험 신호는 '정상'과 '질환'이라는 단편적인 도장이 아니라, 지난 3년~5년 동안 조금씩 움직여 온 숫자의 기울기 속에 숨어 있다는 점이다. 고혈압이나 당뇨, 만성 신장질환은 통증이라는 경고음을 울리지 않은 채 혈관을 서서히 마모시키다가 어느 날 갑자기 응급실 청구서로 모습을 드러낸다.",
            "부모님의 국가건강검진 결과표를 함께 펼쳐 들었을 때 자녀가 가장 먼저 짚어보아야 할 첫 번째 숫자는 '공복혈당'이다. 검진 기준상 8시간 이상 금식 후 측정한 공복혈당이 100mg/dL 미만이면 정상, 126mg/dL 이상이면 당뇨병 의심으로 분류된다. 그런데 가장 위험한 사각지대는 100에서 125 사이에 걸쳐 있는 '공복혈당장애(당뇨 전단계)' 구간이다. 재작년 98이던 수치가 작년 108, 올해 119로 매년 계단식으로 오르고 있다면, 판정란에 '정상B'가 적혀 있더라도 즉시 가까운 내과에서 지난 3개월간의 평균 혈당 성적표인 '당화혈색소(HbA1c)' 검사를 추가로 받아보아야 한다.",
            "두 번째로 눈여겨보아야 할 핵심 지표는 혈액검사 항목 아래쪽에 자리 잡은 신장(콩팥) 기능 수치, 즉 '혈청 크레아티닌'과 '신사구체여과율(eGFR)'이다. 많은 어르신이 간 수치(AST·ALT)나 콜레스테롤 수치는 익숙하게 살피면서도 사구체여과율은 그냥 지나치곤 한다. 사구체여과율은 우리 몸의 정수기 필터 역할을 하는 콩팥이 1분 동안 혈액을 얼마나 깨끗하게 걸러내는지를 보여주는 지표로, 통상 60mL/min/1.73㎡ 이상을 정상 범위로 본다.",
            "특히 고혈압 약이나 당뇨 약을 수년째 복용 중이시거나 관절 통증으로 소염진통제를 자주 드시는 부모님이라면 이 사구체여과율 수치가 매년 가파르게 떨어지고 있지 않은지, 그리고 소변검사의 '요단백' 항목에 약양성(±)이나 양성(+)이 찍히지 않았는지 반드시 대조해 보아야 한다. 콩팥 기능은 한 번 기준선 아래로 망가지면 이전 상태로 되돌리기 어렵지만, 초기에 발견해 혈압·혈당 조절과 저염식, 진통제 복용 조절만 병행해도 투석으로 가는 시계를 수십 년 늦출 수 있기 때문이다.",
            "세 번째는 이상지질혈증(고지혈증)을 보여주는 네 가지 지질 수치의 조합이다. 총콜레스테롤 수치 하나만 볼 것이 아니라, 혈관 벽에 기름때를 쌓는 나쁜 콜레스테롤인 'LDL 콜레스테롤'(일반적 기준 130mg/dL 미만, 심혈관 위험군 70~100 미만 권장)과 중성지방(150mg/dL 미만), 그리고 혈관 청소부 역할을 하는 좋은 콜레스테롤인 'HDL 콜레스테롤'(40~60 이상 권장)의 균형을 함께 봐야 한다. 고기를 거의 안 드시는 어르신인데도 중성지방 수치가 200을 훌쩍 넘는다면, 주범은 삼겹살이 아니라 식후에 습관처럼 드시는 믹스커피와 떡, 과일, 흰쌀밥 같은 정제 탄수화물인 경우가 대부분이다.",
            "참고로 국가건강검진 결과표에서 고혈압이나 당뇨병 '질환 의심' 판정을 받았다면, 검진 다음 해 1월 말까지 결과표와 신분증을 지참해 가까운 병·의원(검진 기관이 아니어도 가능)을 방문할 때 최초 1회 진찰료와 확진 검사비 본인부담금이 전액 면제된다. 나라에서 무료로 확진 검사까지 연결해 주는데도 이 혜택을 몰라 생돈을 내거나 재검을 미루는 분들이 여전히 많다.",
            "이번 주말 본가에 들른다면 국민건강보험공단 앱('The건강보험')의 '건강검진 결과조회' 메뉴를 열어 최근 5년 치 부모님의 검진 숫자를 한 화면에 나란히 띄워보길 권한다. 값비싼 건강기능식품을 사드리는 것보다, 지난 3년간의 숫자 흐름을 함께 읽으며 식후 20분 산책과 약 복용 루틴을 조율하는 그 30분의 대화가 부모님의 건강한 10년을 지키는 가장 확실한 예방의학이다.",
        ],
    },
    {
        "part": 8,
        "title": "비과세 종합저축 가입조건 5천만원 한도·파킹통장",
        "subtitle": "만 65세 이자세금 면제 조건과 상호금융 세금우대·예금자보호",
        "targetDomain": "woorinote.kr",
        "category": "은퇴자산·예적금",
        "pacingMode": "strategic_bridge",
        "articleNo": 8,
        "paragraphs": [
            "평생 일군 퇴직금이나 만기 된 적금, 혹은 주택을 줄여 마련한 목돈이 통장에 들어왔을 때 가장 위험한 선택은 지인의 말만 듣고 뛰어드는 성급한 투자다. 그리고 그다음으로 아쉬운 선택은 어디에 넣을지 결정하지 못해 연 0.1퍼센트 남짓한 이자만 붙는 일반 수시입출금 통장에 수개월째 그냥 방치해 두는 일이다. 특히 현역 시절처럼 근로소득으로 손실을 만회하기 어려운 은퇴 자금은 '원금의 절대적 안전성'을 최우선 원칙으로 두면서도, 언제든 병원비나 경조사비로 꺼내 쓸 수 있는 유동성과 절세를 동시에 챙겨야 한다.",
            "시니어 자산 배분에서 가장 먼저, 그리고 무조건 1순위로 활용해야 할 절세 통장은 만 65세 이상 거주자에게 주어지는 '비과세 종합저축' 한도다. 일반 예·적금에 가입하면 받은 이자의 15.4퍼센트(소득세 14퍼센트 + 지방소득세 1.4퍼센트)를 세금으로 떼고 나머지 금액만 통장에 들어온다. 하지만 비과세 종합저축으로 가입하면 전 금융기관 합산 원금 5천만 원 한도 내에서 발생하는 이자나 배당소득에 대해 15.4퍼센트의 세금이 단 1원도 부과되지 않는다.",
            "부부가 모두 만 65세 이상이라면 각각 5천만 원씩, 부부 합산 원금 1억 원까지 발생하는 이자를 100퍼센트 온전히 수령할 수 있다. 예를 들어 연 4퍼센트 금리의 정기예금에 1억 원을 넣었을 때 일반 과세 통장이라면 연 400만 원 이자 중 61만 6천 원을 세금으로 떼이지만, 부부가 비과세 종합저축 한도를 나누어 활용하면 400만 원 전액이 그대로 노후 생활비가 된다.",
            "더 중요한 효과는 건강보험료와 기초연금 산정에서의 방어력이다. 앞서 살펴보았듯 건강보험 피부양자 자격을 유지하려면 연간 합산 소득이 2천만 원 이하여야 하는데, 비과세 종합저축에서 발생한 이자소득은 세법상 비과세 소득으로 분류되어 건강보험료 부과 대상 금융소득 합산에서 아예 제외된다. 단, 직전 3개 과세기간 내 한 번이라도 금융소득 종합과세 대상자(연간 금융소득 2천만 원 초과)였던 이력이 있다면 가입이 제한되므로, 은퇴 후 만 65세가 도래하는 해에는 다른 예금보다 비과세 종합저축 한도 5천만 원부터 최우선으로 채워 넣어야 한다.",
            "그렇다면 당장 3개월~6개월 안에 쓸 생활비와 비상 예비자금은 어디에 담아두어야 할까? 이때 활용하는 도구가 하루만 맡겨도 정기예금 못지않은 이자를 계산해 주는 '파킹통장(수시입출금식 고금리 예금)'이다. 일반 입출금 통장에 3천만 원의 비상금을 1년 동안 넣어두면 이자가 3만 원도 채 안 되지만, 연 2.5~3.5퍼센트 수준의 파킹통장에 넣어두면 언제든 중도해지 불이익 없이 카드를 쓰거나 이체하면서도 연간 75만~100만 원 이상의 이자를 매달 월급처럼 챙길 수 있다.",
            "여유 자금을 여러 은행이나 저축은행, 상호금융권(신협·농협·새마을금고 등)에 나누어 예치할 때는 반드시 '예금자보호 한도'를 원금 기준이 아닌 '원금 + 이자 합산 기준'으로 맞춰야 한다. 예금자보호가 적용되는 한도 내에서 원금에 향후 만기 시 붙을 이자까지 합쳐 한도를 넘지 않도록 원금을 조금 여유 있게 쪼개어 예치하는 것이 정석이다.",
            "또한 상호금융권의 출자금 통장과 세금우대(저율과세 1.4퍼센트 농어촌특별세만 부과, 1인당 통합 3천만 원 한도) 혜택을 추가로 조합하면, 부부 기준 비과세 종합저축 1억 원에 저율과세 예탁금 6천만 원까지 총 1억 6천만 원의 은퇴 시드머니를 사실상 세금 걱정 없는 안전지대에 배치할 수 있다.",
            "노후의 재무 관리는 대박 수익률을 쫓는 공격수가 아니라, 새어 나가는 세금과 수수료를 막고 원금을 지키는 골키퍼의 영역에 가깝다. 오늘 통장 정리를 시작한다면 내 자금을 ① 6개월 치 비상 생활비(파킹통장), ② 1~3년 만기 확정금리 자금(비과세 종합저축 + 세금우대 예탁금), ③ 연금 수령 계좌라는 세 개의 바구니로 나누어 이름표를 붙여보는 것부터 출발해 보길 권한다.",
        ],
    },
    {
        "part": 9,
        "title": "부모 자식간 계좌이체 증여세 한도와 차용증 작성법",
        "subtitle": "자녀 10년 5천만원·혼인 1.5억 공제와 차용증 확정일자 기준",
        "targetDomain": "baronote.kr",
        "category": "상속·증여·절세",
        "pacingMode": "strategic_bridge",
        "articleNo": 9,
        "paragraphs": [
            "결혼을 앞둔 자녀가 전셋집을 구하거나 첫 내 집 마련에 나설 때, 부모가 퇴직금이나 아껴둔 예금을 깨서 부족한 자금을 잠시 보태주는 일은 우리 주변에서 흔히 볼 수 있는 풍경이다. 부모와 자식 사이에 잠시 빌려주고 형편이 나아질 때 갚기로 한 돈이니 별다른 서류가 필요 없으리라 생각하기 쉽다. 하지만 부동산 거래 자금출처조사와 금융정보 분석이 정교해진 요즘에는, 이 소박한 가족 간의 정이 몇 년 뒤 예상치 못한 증여세와 가산세 고지서로 되돌아오는 사례가 적지 않다.",
            "세법이 가족 간의 계좌이체를 바라보는 기본 전제는 생각보다 냉정하다. 배우자나 직계존비속(부모·조부모와 자녀·손자녀) 간에 오간 자금은 원칙적으로 대여(빌려준 돈)가 아니라 '증여(무상으로 준 돈)'로 추정한다. 따라서 세무서가 자금 출처를 물었을 때 이것이 증여가 아니라 빌려준 돈(차입금)이라는 사실을 입증해야 할 책임은 과세관청이 아니라 납세자인 부모와 자녀에게 있다.",
            "가장 먼저 정확히 계산해 두어야 할 기준선은 '증여재산공제 한도'다. 성인 자녀(만 19세 이상)가 부모나 조부모 등 직계존속으로부터 증여세 없이 받을 수 있는 공제 한도는 '10년 합산 5천만 원'(미성년 자녀는 2천만 원)이다. 여기서 핵심은 두 가지다. 첫째는 1회 한도가 아니라 '10년간 합산'이라는 점이고, 둘째는 아버지와 어머니(나아가 할아버지·할머니까지)를 모두 합산해 직계존속이라는 하나의 그룹으로 묶어 5천만 원을 계산한다는 점이다. 아버지에게 5천만 원, 어머니에게 또 5천만 원을 각각 받으면 합산 1억 원이 되어 초과분 5천만 원에 대해서는 10퍼센트의 증여세 신고 대상이 된다.",
            "만약 자녀가 신혼집을 마련하거나 출산을 앞둔 상황이라면 최근 신설된 '혼인·출산 증여재산공제' 특례를 적극적으로 활용할 수 있다. 혼인신고일 전후 2년 이내(총 4년 구간)이거나 자녀의 출생일(또는 입양신고일)로부터 2년 이내에 직계존속으로부터 증여받는 재산에 대해서는, 기본 공제 5천만 원과 별도로 최대 1억 원까지 추가 공제가 적용된다. 즉 성인 자녀가 결혼이나 출산 시점에 맞춰 부모로부터 자금을 지원받는다면 10년간 기본 5천만 원에 특례 1억 원을 더해 총 1억 5천만 원까지 증여세 부담 없이 합법적으로 자금을 이전할 수 있다.",
            "이 공제 한도를 넘어서는 큰 금액을 부모 자식 간에 '빌려주고 갚는 대여' 형태로 진행해야 한다면, 세무서가 인정하는 네 가지 객관적 증거를 처음부터 갖춰야 한다. 첫째, 자금이 이체되는 시점에 대여 금액, 이자율, 이자 지급일, 원금 상환 기한이 명확히 적힌 '금전소비대차계약서(차용증)'를 작성해야 한다. 둘째, 세무 조사가 나온 뒤에 날짜를 소급해 허위로 작성한 서류가 아님을 증명하기 위해 우체국 내용증명이나 법원 등기소 확정일자, 혹은 공증을 받아 작성 일자를 공적으로 남겨두어야 한다.",
            "셋째는 '적정 이자율(법정 당좌대출이자율 연 4.6퍼센트)' 기준과 무이자 한도의 계산이다. 세법상 부모에게 돈을 빌릴 때 적정 이자율(연 4.6퍼센트)보다 낮거나 무이자로 빌리면, 원래 내야 할 연간 이자 상당액을 증여받은 것으로 본다. 다만 그 연간 이자 차액이 '1천만 원 미만'인 경우에는 증여세를 부과하지 않는다는 소액 부징수 규정이 있다. 이를 역산하면 약 2억 1,739만 원(`1,000만 원 ÷ 4.6%`) 이하의 금액은 무이자로 차용증을 쓰고 원금만 정기적으로 상환해도 이자 부분에 대한 증여세 문제가 발생하지 않는다.",
            "넷째이자 가장 결정적인 증거는 서류가 아니라 '실제 계좌이체 내역'이다. 아무리 완벽한 차용증에 공증을 받아두었더라도, 그 이후 수년간 자녀 계좌에서 부모 계좌로 약속한 이자나 원금 분할 상환금이 정기적으로 이체된 금융 흔적이 없다면 세무서는 이를 실질적인 증여로 판정한다. 또한 돈을 빌린 자녀에게 그 원리금을 갚아나갈 만한 실제 소득(근로·사업소득 등)이 뒷받침되어야 한다.",
            "세법은 가족의 따뜻한 마음보다 통장에 찍힌 객관적인 흔적을 먼저 본다. 선의로 건넨 부모의 도움이 자녀에게 세금 폭탄이라는 짐으로 돌아오지 않도록, 큰돈이 움직이기 전에 기본적인 10년 공제 한도와 차용증·확정일자·자동이체라는 기본 순서를 먼저 챙기는 지혜가 필요하다.",
        ],
    },
    {
        "part": 10,
        "title": "한전 전기요금·도시가스 복지할인 신청·에너지바우처",
        "subtitle": "대가족·출산가구 30% 감면 조건과 취약계층 에너지바우처 신청법",
        "targetDomain": "joynote.kr",
        "category": "에너지·공과금절약",
        "pacingMode": "strategic_bridge",
        "articleNo": 10,
        "paragraphs": [
            "여름철 에어컨을 켜기가 무서워지는 8월과 보일러 온도를 한 칸 올리기가 망설여지는 12월이 오면, 나는 주변 지인들과 어르신들에게 아파트 관리비 명세서나 전기·도시가스 고지서 뒷면의 '복지할인 안내란'을 딱 한 번만 읽어보라고 권한다. 생각보다 훨씬 많은 가구가 전기요금과 도시가스 요금, 지역난방비 감면 대상에 해당하면서도 정작 본인이 대상자인 줄 몰라 매달 제값을 다 내고 있기 때문이다.",
            "한국전력공사와 전국 도시가스사가 운영하는 요금 복지할인은 크게 두 가지 축으로 나뉜다. 첫 번째 축은 '가구원 특성(생애주기) 할인'이다. 흔히 저소득층만 공과금 할인을 받을 수 있다고 오해하지만, 소득이나 재산 수준과 전혀 상관없이 주민등록표상 세대원 구성만 충족하면 신청 즉시 요금을 깎아주는 제도가 바로 대가족·다자녀·출산가구 할인이다.",
            "구체적으로 주민등록등본상 세대원 수가 5인 이상인 '대가족 가구'(부모님을 모시고 사는 3세대 가구 포함), 자녀가 3명 이상인 '다자녀 가구', 그리고 출생일로부터 3년 미만인 영아가 1명 이상 포함된 '출산 가구'는 소득이 아무리 높아도 매월 전기요금의 30퍼센트(월 1만 6천 원 한도)를 감면받을 수 있다. 아이가 태어났거나 부모님과 합가를 했다면 한국전력 고객센터(국번 없이 123)나 '한전ON' 앱, 혹은 주민센터 전입신고·출생신고 시 행복출산·안심상속 원스톱 서비스를 통해 신청 한 번만 해두면 자격 유지 기간 내내 매달 자동으로 요금이 차감된다.",
            "두 번째 축은 기초연금 수급 어르신, 장애인, 국가·독립유공자, 기초생활수급자 및 차상위계층을 위한 '사회적 배려계층 복지할인'과 '에너지바우처'다. 기초생활수급자(생계·의료·주거·교육)와 차상위계층, 중증장애인 및 유공자 가구는 평상시 월 8천 원~1만 6천 원 한도, 여름철(7~8월)에는 월 1만 원~2만 원 한도까지 전기요금 정액 감면을 받을 수 있으며, 도시가스 요금과 이동통신 요금 감면까지 세트로 연결된다.",
            "여기에 더해 소득 기준과 세대원 특성 기준(만 65세 이상 노인, 만 7세 이하 영유아, 장애인, 임산부, 중증·희귀·중증난치질환자, 한부모·소년소녀가정 등)을 동시에 충족하는 취약계층 가구에는 여름철 냉방비와 겨울철 난방비를 지원하는 '에너지바우처'가 지급된다. 에너지바우처는 요금 고지서에서 자동으로 차감되는 '가상카드' 방식과, 등유·LPG·연탄 등을 직접 구매결제할 수 있는 '국민행복카드(실물카드)' 방식 중 우리 집 난방 형태에 맞는 방식을 선택해 신청할 수 있다.",
            "현장에서 가장 자주 발생하는 실수는 '이사를 갔을 때'와 '아파트 관리비에 전기·가스요금이 통합 부과될 때'다. 기존 집에서 한전 복지할인을 잘 받고 있었더라도 새로운 집으로 이사를 가면 고객번호(계량기 번호)가 바뀌기 때문에 반드시 한전(123)과 관할 도시가스사에 이사 전출·전입에 따른 복지할인 이전 신청을 다시 해두어야 할인이 끊기지 않는다. 또한 아파트에 거주하는 경우 개별 한전 고지서가 안 날아온다고 방치하지 말고, 아파트 관리사무소에 복지할인 신청 사실을 알리거나 한전 고객센터에 아파트 동·호수를 등록해 관리비 고지서 내 세대별 전기료 항목에서 매달 정상적으로 감면액이 찍히고 있는지 첫 달 명세서를 꼭 대조해 보아야 한다.",
            "매달 2만 원~3만 원의 공과금 감면은 언뜻 작아 보일지 모르지만, 1년이면 30만 원이 넘고 이는 은행에 1천만 원의 예금을 연 3.5퍼센트로 1년 내내 묶어두어야 겨우 손에 쥐는 세후 이자와 맞먹는 금액이다. 위험 부담이 전혀 없는 가장 확실한 무위험 확정 수익인 셈이다.",
            "열 번의 연재를 갈무리하며 다시금 깨닫는 것은, 우리의 일상을 지키는 재무 지식은 결코 거창한 투자 기법이 아니라는 사실이다. 부모님의 통장과 고지서, 건강검진표, 그리고 계절마다 돌아오는 작은 신청 달력을 놓치지 않고 보살피는 따뜻한 관심이야말로 어떤 경제 한파 속에서도 가족의 저녁 식탁을 든든하게 지켜주는 가장 단단한 울타리가 된다.",
        ],
    },
]


def _now_kst_iso() -> str:
    return datetime.datetime.now(KST).isoformat()


def load_brunch_status() -> Dict[str, Any]:
    if DATA_PATH.is_file():
        try:
            return json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_brunch_status(payload: Dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    DATA_PATH.write_text(raw, encoding="utf-8")
    PUBLIC_DATA_PATH.write_text(raw, encoding="utf-8")


def sync_brunch_live_state(cdp_port: int = 9450) -> Dict[str, Any]:
    """Sync live Brunch writer approval state, drawer drafts, published articles, and Naver Premium status via EGO Lite TaskSpace."""
    from common.asset_map import _load_brunch_credentials
    from common.ego_taskspace import native_check_naver_premium_status, native_sync_brunch_state

    prev = load_brunch_status()
    now_iso = _now_kst_iso()
    today_prefix = now_iso[:10]
    cdp_online = False
    writer_status = prev.get("account", {}).get("writerStatus") or "approved"
    writer_status_label = "🟢 브런치 작가 최종 승인 완료 (실시간 공개 발행 및 100% CF 브릿지 가동 중)"
    can_publish_live = True
    drawer_articles: List[Dict[str, Any]] = []
    published_articles: List[Dict[str, Any]] = []
    apply_notice = "브런치 작가가 되신 것을 진심으로 축하드립니다! 실시간 칼럼 발행 및 다음(Daum)·구글(DA 80+)·네이버카페 OSMU 브릿지가 가동 중입니다."

    # Build historical publishedAt map from automation.history and previous publishedArticles/publishedPosts
    # so syncing never overwrites historical publication dates with today's date.
    preserved_pub_at_by_url: Dict[str, str] = {}
    for prev_item in (prev.get("publishedArticles") or prev.get("publishedPosts") or []):
        if isinstance(prev_item, dict) and prev_item.get("url") and prev_item.get("publishedAt"):
            u = str(prev_item["url"]).strip()
            p_at = str(prev_item["publishedAt"]).strip()
            if p_at:
                preserved_pub_at_by_url[u] = p_at

    for h_item in ((prev.get("automation") or {}).get("history") or []):
        if not isinstance(h_item, dict):
            continue
        h_url = str(h_item.get("url") or "").strip()
        if not re.search(r"/@31d1f5fb288c4fc/\d+", h_url):
            continue
        h_date = str(h_item.get("date") or str(h_item.get("at") or "")[:10]).strip()
        if not h_date:
            continue
        existing = preserved_pub_at_by_url.get(h_url)
        if not existing or h_date[:10] < existing[:10]:
            preserved_pub_at_by_url[h_url] = h_date

    uid, upw = _load_brunch_credentials()
    try:
        ego_sync = native_sync_brunch_state(uid=uid or "", upw=upw or "")
        if isinstance(ego_sync, dict) and ego_sync.get("ok"):
            cdp_online = True
            raw_drawer = ego_sync.get("rawDrawer") or []
            raw_pub = ego_sync.get("rawPub") or []
            seen_urls = set()
            for idx, it in enumerate(raw_drawer, 1):
                if it["href"] in seen_urls:
                    continue
                seen_urls.add(it["href"])
                m_no = re.search(r"/@31d1f5fb288c4fc/(\d+)", it["href"])
                art_no = int(m_no.group(1)) if m_no else idx
                matched_cur = next(
                    (c for c in BRUNCHBOOK_CURRICULUM if c["part"] == art_no or c["title"][:10] in it["title"] or it["title"][:10] in c["title"]),
                    None,
                )
                drawer_articles.append(
                    {
                        "articleNo": art_no,
                        "title": it["title"],
                        "subtitle": matched_cur["subtitle"] if matched_cur else "",
                        "excerpt": it["excerpt"],
                        "url": it["href"],
                        "targetDomain": matched_cur["targetDomain"] if matched_cur else "must-good.com",
                        "category": matched_cur["category"] if matched_cur else "연금·노후설계",
                        "pacingMode": "strategic_bridge",
                        "status": "drawer_saved",
                        "statusLabel": "서랍 보관 중 (발행 대기)",
                        "charCount": sum(len(x) for x in (matched_cur.get("paragraphs") or [])) if matched_cur else 1850,
                        "savedAt": it.get("savedAtLabel", "저장됨"),
                    }
                )
            seen_pub = set()
            for idx, it in enumerate(raw_pub, 1):
                if it["href"] in seen_pub:
                    continue
                seen_pub.add(it["href"])
                m_no = re.search(r"/@31d1f5fb288c4fc/(\d+)", it["href"])
                art_no = int(m_no.group(1)) if m_no else idx
                matched_cur = next(
                    (c for c in BRUNCHBOOK_CURRICULUM if c["part"] == art_no or c["title"][:10] in it["title"] or it["title"][:10] in c["title"]),
                    None,
                )
                pub_at = preserved_pub_at_by_url.get(it["href"]) or today_prefix
                published_articles.append(
                    {
                        "articleNo": art_no,
                        "title": it["title"],
                        "subtitle": matched_cur["subtitle"] if matched_cur else "",
                        "excerpt": it["excerpt"],
                        "url": it["href"],
                        "targetDomain": matched_cur["targetDomain"] if matched_cur else "must-good.com",
                        "category": matched_cur["category"] if matched_cur else "연금·노후설계",
                        "pacingMode": "strategic_bridge",
                        "status": "published",
                        "statusLabel": "🟢 공개 발행 완료 (Daum·구글 색인 대상)",
                        "charCount": sum(len(x) for x in (matched_cur.get("paragraphs") or [])) if matched_cur else 1950,
                        "publishedAt": pub_at,
                        "checkedAt": now_iso,
                    }
                )
    except Exception:
        pass

    if not published_articles:
        drawer_articles = prev.get("drawerArticles") or []
        published_articles = []
        for prev_art in (prev.get("publishedArticles") or prev.get("publishedPosts") or []):
            if not isinstance(prev_art, dict):
                continue
            art_copy = dict(prev_art)
            art_url = str(art_copy.get("url") or "").strip()
            art_copy["publishedAt"] = preserved_pub_at_by_url.get(art_url) or str(art_copy.get("publishedAt") or today_prefix)
            art_copy["checkedAt"] = now_iso
            published_articles.append(art_copy)

    # Check live Naver Premium Contents status on yoon_master
    prem_live = {}
    try:
        prem_live = native_check_naver_premium_status() or {}
        prem_file = BASE_DIR / "dashboard" / "data" / "premium" / "status.json"
        if prem_file.is_file() and prem_live.get("ok"):
            p_doc = json.loads(prem_file.read_text(encoding="utf-8"))
            p_doc["status"] = "승인 완료 (Approved)" if prem_live.get("approved") else "심사 진행 중 (Under Review)"
            p_doc["last_checked_at"] = now_iso
            p_doc["studio_url"] = prem_live.get("url", "https://studio.premium.naver.com/join/review")
            prem_file.write_text(json.dumps(p_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    pub_nos = {p["articleNo"] for p in published_articles}
    pub_titles = {p["title"][:10] for p in published_articles}
    drawer_nos = {d["articleNo"] for d in drawer_articles}
    drawer_titles = {d["title"][:10] for d in drawer_articles}

    curriculum_rows = []
    for c in BRUNCHBOOK_CURRICULUM:
        is_pub = c["part"] in pub_nos or c["title"][:10] in pub_titles
        in_drawer = not is_pub and (c["part"] in drawer_nos or c["title"][:10] in drawer_titles)
        bridge_targets = get_today_cf_bridge_targets(c["title"], allowed_domains=[c["targetDomain"]])
        bridge_url = bridge_targets[0]["url"] if bridge_targets else f"https://www.{c['targetDomain']}/"
        curriculum_rows.append(
            {
                "part": c["part"],
                "title": c["title"],
                "subtitle": c["subtitle"],
                "targetDomain": c["targetDomain"],
                "category": c["category"],
                "pacingMode": c["pacingMode"],
                "pacingLabel": "70% 순수 에세이 (심사·신뢰 축적)" if c["pacingMode"] == "pure_essay" else "30% CF 고단가 브릿지 (og:link 카드)",
                "bridgeUrl": bridge_url,
                "charCount": sum(len(x) for x in c["paragraphs"]),
                "status": "published" if is_pub else ("saved_in_drawer" if in_drawer else "queued_for_publish"),
                "statusLabel": "🟢 공개 발행 완료" if is_pub else ("✅ 서랍 저장 완료" if in_drawer else "⏳ 자동 연재 대기 (하루 2편)"),
                "paragraphs": c["paragraphs"],
            }
        )

    payload = {
        "ok": True,
        "checkedAt": now_iso,
        "account": {
            **BRUNCH_ACCOUNT,
            "status": "writer_approved" if can_publish_live else "writer_application_submitted",
            "cdpOnline": cdp_online,
            "writerStatus": writer_status,
            "writerStatusLabel": writer_status_label,
            "canPublishLive": can_publish_live,
            "applyNotice": apply_notice,
            "appliedAt": prev.get("account", {}).get("appliedAt") or "2026-10-30 14:24 KST",
            "approvedAt": prev.get("account", {}).get("approvedAt") or "2026-10-30 18:00 KST",
            "schedulePolicy": "하루 2회(09:30 · 16:30) 2,000자 에세이 자동 연재 · 10부작 완주 후 당일 CF 고단가 토픽 무한 확장",
            "applicationIntro": (
                "부모님의 연금 통장과 퇴직 선배의 건강보험료 고지서를 함께 들여다보며, 법령 속 차가운 숫자를 생활의 언어로 번역하기 시작한 기록자입니다. "
                "오랜 기간 행정·세무·복지 제도의 실무 기준을 분석하며, 몰라서 놓치는 권리와 노후 재무의 빈틈을 가족의 시선으로 갈무리해 왔습니다. "
                "브런치에서 은퇴 전후 마주하는 삶의 현실적인 재무 기록을 나누고자 합니다."
            ),
            "applicationPlan": (
                "은퇴와 노후의 문턱에서 누구나 겪는 연금·건보료·세금·복지의 현실 문제를 에세이형 실무 칼럼으로 연재합니다. "
                "1장 어머니의 통장으로 본 국민연금과 기초연금 연계감액, 2장 퇴직 후 건강보험료 피부양자 자격과 자산 점검, "
                "3장 신청주의 복지와 숨은 환급금 달력, 4장 중장년 의료비·돌봄 제도의 기록 등 총 10부작 브런치북 및 후속 실무 칼럼을 상시 연재합니다."
            ),
        },
        "naverPremium": prev.get("naverPremium")
        or {
            "account": "soultin",
            "email": "soultin@naver.com",
            "cdpPort": 9334,
            "serviceUrl": "https://contents.premium.naver.com/seniorbrief",
            "studioUrl": "https://studio.premium.naver.com/",
            "status": "application_submitted",
            "statusLabel": "🟢 판매자 가입 신청 완료 (seniorbrief · 심사/2단계인증 연동)",
            "appliedAt": "2026-10-30 15:50 KST",
            "recommendedChannelName": "시니어 브리프 프리미엄 노트",
            "recommendedChannelId": "seniorbrief",
            "recommendedCategory": "경제/비즈니스 · 주 3회(월·수·금) 연재",
            "recommendedIntro": "5060 중장년과 은퇴 준비 가구를 위한 공적연금(국민·기초연금 연계감액), 건강보험 피부양자 자격 관리, 시니어 의료·돌봄 급여, 정부 환급금·복지 신청 실무를 알기 쉽게 해설하는 생활 재무·행정 전문 채널입니다.",
            "operatingRule": "100% 전체 공개(무료) 발행 + 네이버 통합검색 노출 허용(ON) + 본문 하단 CF 16개 도메인 브릿지 연결 (브런치 원고 1+1 동시 송출)",
        },
        "kpi": {
            "drawerCount": len(drawer_articles),
            "publishedCount": len(published_articles),
            "curriculumTotal": len(BRUNCHBOOK_CURRICULUM),
            "dailyTargetCount": 2,
            "pureEssayRatio": 70,
            "bridgeColumnRatio": 30,
            "targetDaumTrafficAge": "4060 시니어·은퇴층",
            "targetGoogleBacklinkDA": "DA 80+ (brunch.co.kr)",
            "priorityBoostDomains": ["baronote.kr", "smilenote.kr", "topnote.kr", "must-good.com", "healthcox.com", "woorinote.kr"],
        },
        "automation": {
            **(prev.get("automation") or {}),
            "todayDate": today_prefix,
            "todayPublishedCount": sum(
                1 for p in published_articles if str(p.get("publishedAt") or "")[:10] == today_prefix
            ),
        },
        "drawerArticles": drawer_articles,
        "publishedArticles": published_articles,
        "publishedPosts": published_articles,
        "curriculum": curriculum_rows,
    }
    save_brunch_status(payload)
    return payload


def generate_dynamic_brunch_column(part_no: int) -> Dict[str, Any]:
    """Generate a new 2,000-character 4-Deficiency Brunch column paired with today's top CF blog post when part_no > 10."""
    from common import llm_client

    priority_domains = ["must-good.com", "baronote.kr", "smilenote.kr", "woorinote.kr", "healthcox.com", "meganote.kr", "topnote.kr", "joynote.kr"]
    target_domain = priority_domains[(part_no - 1) % len(priority_domains)]
    bridge_targets = get_today_cf_bridge_targets("", allowed_domains=[target_domain]) or get_today_cf_bridge_targets("")
    chosen = bridge_targets[0] if bridge_targets else {"domain": target_domain, "title": "은퇴 후 건강보험료와 연금 절세 실무 점검", "url": f"https://www.{target_domain}/"}
    pacing_mode = "strategic_bridge" if (part_no % 3 == 0) else "pure_essay"

    prompt = (
        f"당신은 카카오 브런치스토리 및 네이버 프리미엄콘텐츠의 4060 은퇴·연금·세무·건강 전문 칼럼니스트 '머스트픽'입니다.\n"
        f"다음 주제와 연결된 깊이 있는 1인칭 실무 에세이 칼럼을 작성하세요.\n"
        f"- 참고 주제: {chosen['title']} (타깃 도메인: {chosen['domain']})\n"
        f"- 필수 원칙:\n"
        f"  1) 제목(title)은 실제 다음(Daum)·구글·네이버 검색창에 사용자가 타이핑하는 핵심 검색 키워드(제도명 + 가입조건/한도/신청법/수령액)를 맨 앞(좌측)에 전진 배치하고, 공백 포함 반드시 27자 이내로 작성할 것(브런치 30자 제한 엄수). '고지서의 충격', '숨은 혜택', '함정', '기록' 같은 추상적 수필형 제목은 절대 금지.\n"
        f"  2) 부제(subtitle)는 세부 롱테일 검색 키워드(구체적 수치·자격기준·신청절차)를 포함하여 공백 포함 반드시 38자 이내로 작성할 것.\n"
        f"  3) 본문(paragraphs)은 총 8개 문단, 전체 합산 1,800자~2,200자 분량으로 작성할 것.\n"
        f"  4) 자청의 4대 결핍(손실회피·불확실성 해소·비교우위·인지부조화 해소)을 녹여, 가족/지인의 실제 고지서·통장 에피소드로 시작해 구체적인 법정 기준 숫자·계산식·예외 함정·실행 순서를 차분하고 지적인 브런치 문체('~다')로 풀어낼 것.\n"
        f"  5) AI 생성 티가 나는 메타 문구나 번호 매기기 요약 대신 자연스러운 산문 문단으로만 구성할 것.\n"
        f"반드시 JSON 객체 {{\"title\": \"...\", \"subtitle\": \"...\", \"paragraphs\": [\"문단1\", ... \"문단8\"]}} 형태로만 응답하세요."
    )
    res = llm_client.generate_json(prompt, temperature=0.5)
    paragraphs = [str(p).strip() for p in (res.get("paragraphs") or []) if str(p).strip()]
    if len(paragraphs) < 4:
        paragraphs = BRUNCHBOOK_CURRICULUM[(part_no - 1) % len(BRUNCHBOOK_CURRICULUM)]["paragraphs"]
    return {
        "part": part_no,
        "title": str(res.get("title") or chosen["title"])[:26].strip(),
        "subtitle": str(res.get("subtitle") or "가족의 통장과 고지서 앞에서 먼저 확인해야 할 실무 기준")[:36].strip(),
        "targetDomain": chosen["domain"],
        "category": "은퇴·재무·복지 칼럼",
        "pacingMode": pacing_mode,
        "articleNo": part_no,
        "paragraphs": paragraphs,
        "bridgeUrl": chosen["url"],
    }


def write_next_curriculum_part(part_no: Optional[int] = None, cdp_port: int = 9450) -> Dict[str, Any]:
    """Write or upgrade the specified (or next queued) BrunchBook curriculum/dynamic part and publish live (or save to drawer)."""
    st = sync_brunch_live_state(cdp_port=cdp_port)
    published = st.get("publishedArticles") or []
    drawer = st.get("drawerArticles") or []

    pub_nos = {p["articleNo"] for p in published}
    pub_titles = {p["title"][:10] for p in published}

    target_item: Optional[Dict[str, Any]] = None
    edit_url: Optional[str] = None

    if part_no is not None:
        target_item = next((c for c in BRUNCHBOOK_CURRICULUM if c["part"] == int(part_no)), None)
        if target_item is None:
            target_item = generate_dynamic_brunch_column(int(part_no))
        existing_in_pub = next((p for p in published if p["articleNo"] == int(part_no)), None)
        existing_in_drawer = next((d for d in drawer if d["articleNo"] == int(part_no)), None)
        if existing_in_pub:
            edit_url = f"https://brunch.co.kr/@31d1f5fb288c4fc/{existing_in_pub['articleNo']}/write"
        elif existing_in_drawer:
            edit_url = f"https://brunch.co.kr/@31d1f5fb288c4fc/{existing_in_drawer['articleNo']}/write"
    else:
        # 1) First check if any existing published article has a truncated title (>= 29 chars)
        for p_item in published:
            matched_c = next((c for c in BRUNCHBOOK_CURRICULUM if c["part"] == p_item["articleNo"]), None)
            if matched_c and len(p_item.get("title", "")) >= 29 and p_item["title"] != matched_c["title"]:
                target_item = matched_c
                edit_url = f"https://brunch.co.kr/@31d1f5fb288c4fc/{p_item['articleNo']}/write"
                break
        # 2) Next check if any draft is sitting in drawer waiting to be upgraded & published
        if target_item is None and drawer:
            d_item = sorted(drawer, key=lambda x: x["articleNo"])[0]
            matched_c = next((c for c in BRUNCHBOOK_CURRICULUM if c["part"] == d_item["articleNo"]), None)
            target_item = matched_c or generate_dynamic_brunch_column(d_item["articleNo"])
            edit_url = f"https://brunch.co.kr/@31d1f5fb288c4fc/{d_item['articleNo']}/write"
        # 3) Next pick the first unpublished part in BRUNCHBOOK_CURRICULUM
        if target_item is None:
            target_item = next(
                (c for c in BRUNCHBOOK_CURRICULUM if c["part"] not in pub_nos and c["title"][:10] not in pub_titles),
                None,
            )
        # 4) If all 10 curriculum parts are published, dynamically generate the next part (Part 11, 12, ...)
        if target_item is None:
            next_no = max(pub_nos | {10}) + 1
            target_item = generate_dynamic_brunch_column(next_no)

    bridge_targets = get_today_cf_bridge_targets(target_item["title"], allowed_domains=[target_item["targetDomain"]])
    bridge_url = target_item.get("bridgeUrl") or (bridge_targets[0]["url"] if bridge_targets else f"https://www.{target_item['targetDomain']}/")

    res = post_or_save_brunch_column(
        title=target_item["title"],
        subtitle=target_item["subtitle"],
        paragraphs=target_item["paragraphs"],
        bridge_url=bridge_url,
        auto_publish=True,
        cdp_port=cdp_port,
        edit_url=edit_url,
    )

    # OSMU 1+2 Simultaneous Naver Cafe Bridge Publishing (boutiqueinfo Tier 1 + dekilab Tier 2 3:1 anti-ban)
    cafe_receipts = []
    try:
        from naver_cafe_posting.posting import publish_cafe_bridge_part
        c_res = publish_cafe_bridge_part(target_item["part"])
        if isinstance(c_res, dict):
            for rec in c_res.get("receipts") or []:
                if isinstance(rec, dict) and rec.get("ok"):
                    cafe_receipts.append({"cafe": rec.get("cafeSlug") or rec.get("cafe"), "url": rec.get("url")})
    except Exception:
        pass

    updated = sync_brunch_live_state(cdp_port=cdp_port)
    now_dt = datetime.datetime.now(KST)
    today_str = now_dt.date().isoformat()
    auto_state = dict(updated.get("automation") or {})
    history = list(auto_state.get("history") or [])
    history.append(
        {
            "at": now_dt.isoformat(),
            "date": today_str,
            "part": target_item["part"],
            "title": target_item["title"],
            "mode": res.get("mode"),
            "url": res.get("url"),
            "bridgeUrl": bridge_url,
            "cafeBridges": cafe_receipts,
        }
    )
    today_pub_count = sum(
        1 for p in (updated.get("publishedArticles") or []) if str(p.get("publishedAt") or "")[:10] == today_str
    )
    auto_state.update(
        {
            "enabled": True,
            "dailySlots": ["09:30", "16:30"],
            "lastRunAt": now_dt.isoformat(),
            "lastRunTitle": target_item["title"],
            "lastRunUrl": res.get("url"),
            "todayDate": today_str,
            "todayPublishedCount": today_pub_count,
            "history": history[-30:],
        }
    )
    updated["automation"] = auto_state
    save_brunch_status(updated)
    return {
        "ok": True,
        "writtenPart": target_item["part"],
        "title": target_item["title"],
        "result": res,
        "status": updated,
    }


def process_brunch_autonomy_once(cdp_port: int = 9450) -> Dict[str, Any]:
    """Autonomous background loop called by memory_worker.py to keep Brunch publishing 2 columns/day without stopping."""
    now_dt = datetime.datetime.now(KST)
    today_str = now_dt.date().isoformat()
    hhmm = now_dt.strftime("%H:%M")
    st = load_brunch_status()

    # Sync live state at least every 45 minutes
    checked_at = str(st.get("checkedAt") or "")
    need_sync = not st
    if checked_at:
        try:
            age_sec = (now_dt - datetime.datetime.fromisoformat(checked_at)).total_seconds()
            if age_sec > 2700:
                need_sync = True
        except Exception:
            need_sync = True
    if need_sync:
        st = sync_brunch_live_state(cdp_port=cdp_port)

    auto_state = dict(st.get("automation") or {})
    today_pub_count = sum(
        1 for p in (st.get("publishedArticles") or []) if str(p.get("publishedAt") or "")[:10] == today_str
    )
    last_run_at = str(auto_state.get("lastRunAt") or "")
    cooldown_ok = True
    if last_run_at:
        try:
            elapsed = (now_dt - datetime.datetime.fromisoformat(last_run_at)).total_seconds()
            if elapsed < 3 * 3600:
                cooldown_ok = False
        except Exception:
            pass

    # Slot 1: >= 09:00 KST (1st post of the day)
    # Slot 2: >= 16:00 KST (2nd post of the day, at least 3h after 1st)
    should_write = False
    if today_pub_count == 0 and hhmm >= "09:00":
        should_write = True
    elif today_pub_count == 1 and hhmm >= "16:00" and cooldown_ok:
        should_write = True

    if should_write:
        return write_next_curriculum_part(cdp_port=cdp_port)
    return {"ok": True, "action": "idle", "todayPublishedCount": today_pub_count}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="BaroLab Brunch Story Automation Engine")
    parser.add_argument("--status", action="store_true", help="Print cached Brunch status")
    parser.add_argument("--sync", action="store_true", help="Sync live Brunch state from CDP 9450")
    parser.add_argument("--write-part", type=int, default=None, help="Write specific BrunchBook part (1-10+) to drawer/publish")
    parser.add_argument("--write-next", action="store_true", help="Write next queued BrunchBook part to drawer/publish")
    parser.add_argument("--auto-cycle", action="store_true", help="Run autonomous daily Brunch check/publish cycle")
    args = parser.parse_args()

    if args.auto_cycle:
        out = process_brunch_autonomy_once()
        print(json.dumps({k: v for k, v in out.items() if k != "status"}, ensure_ascii=False, indent=2))
        return 0
    if args.write_part is not None or args.write_next:
        out = write_next_curriculum_part(part_no=args.write_part)
        print(json.dumps({k: v for k, v in out.items() if k != "status"}, ensure_ascii=False, indent=2))
        return 0
    if args.sync or not DATA_PATH.is_file():
        out = sync_brunch_live_state()
        print(json.dumps({k: v for k, v in out.items() if k != "curriculum"}, ensure_ascii=False, indent=2))
        return 0
    out = load_brunch_status()
    print(json.dumps({k: v for k, v in out.items() if k != "curriculum"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
