"""Platform-independent editorial policy: Indirect Experience and Reader Problem Solving."""

import hashlib
READER_GOAL_POLICY = '독자 질문에 확인된 사실로 답하고 가정과 실제 사실을 구분한다.'
ANSWER_BRIEF_POLICY = '기본 문서 형식을 검증한 뒤 발행하며 별도 승인 절차를 요구하지 않는다.'


CONTENT_QUALITY_POLICY = """콘텐츠 공통 기준 — 독자에게 생생한 간접체험을 제공하고 궁금증을 완벽히 해결하는 글

1. [핵심 가치: 최고의 글은 생생한 간접체험이다]
- 모든 글의 목적은 독자가 안 가봤어도 가본 것처럼, 안 해봤어도 직접 해본 것처럼 쉽게 이해하고 판단할 수 있게 해주는 것이다.
- 독자가 항상 궁금해하거나 새롭게 생겨나는 궁금증을 두괄식으로 시원하게 해결해준다.

2. [간접체험형 4단계 글 구조]
① 상황 정의 (어떤 상황에서?):
   - 누구와 함께(아이, 연인, 부모님, 반려동물 등) 또는 어떤 문제 상황에서 필요한지 시작부터 타겟의 상황에 깊이 공감한다.
② 핵심 안내 (어디를/무엇을?):
   - 독자가 궁금해하는 장소, 신청 대상, 구매 품목, 해결 방법을 명쾌하게 제시한다.
③ 생생한 여정과 비주얼 (가면/해보면 무엇이 있는가?):
   - 독자가 현장에 있거나 직접 화면을 보는 것처럼 순서대로 안내한다.
   - 여행/방문: 입구 전경, 주차장/교통편, 메인 볼거리와 코스, 주변 식당과 편의시설
   - 신청/정보/해결: 준비물, 1단계 시작 화면, 핵심 처리 과정, 주의할 점, 완료 확인
   - 사진과 캡처는 독자가 "아! 이렇게 생겼구나! 가고 싶다/해볼 만하다"를 직관적으로 판단할 수 있게 핵심 지점마다 배치한다.
④ 솔직한 후기와 추천 (가보니까/해보니까 이렇더라):
   - "직접 경험해보니 이 점은 좋았고, 이 점은 주의해야 하더라"는 실전 꿀팁과 함께 "이런 분들에게 특히 추천한다"로 만족스럽게 마무리한다.

3. [자연스러운 사용자 경험(UX) 중심 서술]
- 딱딱한 공공문서나 출처 나열형 글을 지양하고, '내가 직접 겪고 해결한 노하우'를 전수하듯 친절하고 몰입감 있게 작성한다.
- 구글, 빙 등 검색 포털에서 독자가 읽었을 때 다른 글을 다시 찾아볼 필요가 없을 만큼 궁금증을 완벽히 종결짓는다.
"""

READER_QUALITY_CHECKS = (
    'readerTaskComplete', 'actionableSteps', 'successVerification',
    'troubleshootingUseful', 'experienceHonest', 'visualsServeTask',
)


def content_quality_sha256():
    """Fingerprint the shared editorial criteria used by an accepted handoff."""
    value = CONTENT_QUALITY_POLICY + '\n' + '\n'.join(READER_QUALITY_CHECKS) + '\n' + READER_GOAL_POLICY + '\n' + ANSWER_BRIEF_POLICY
    return hashlib.sha256(value.encode('utf-8')).hexdigest()
