---
updated: 2026-10-17
category: skill
---
# 부분 수선(In-Place Repair) (SKILL.md)

- **핵심 원칙**: 검수 단계에서 캡션 중복·`afterBlock` 인덱스 밀림·요약문 기호(`▲`) 혼입 등 구조적 결함 발생 시, 전체 원고를 처음부터 재작성(`rework-*` 무한 루프)하지 않고 해당 폴더 안에서 Python 정규화 및 최대 1회 보정으로 즉시 수선
- **효과**: 토큰 낭비 및 무한 재시도 루프 원천 차단, `handoff.json` 파일 지문(`sha256`) 자동 동기화

## 연결된 허브
- [[hubs/crew-patch]]
- [[hubs/crew-publi]]
- [[hubs/channel-naver-blog]]
- [[hubs/channel-cf-blog]]
