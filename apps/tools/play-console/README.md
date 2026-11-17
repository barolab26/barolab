# Play Console 작업 도구 (2026-11-17)

EGO 브라우저의 soultin 창(Profile 3, 개발자 계정 YoonLab) 안 탭으로 Play Console을 조작한다. 모두 `ego-browser nodejs -e "await import('file:///C:/10_Project/BaroLab/apps/tools/play-console/<파일>')"` 로 실행한다.

- `release-cfg.cjs <greeting|magnifier|shopping|bible>` → `play-release.json`, `play-send.txt` 작성
- `play-release.mjs` → 비공개 테스트(Alpha) 트랙에 번들 업로드, 출시 노트 입력, 저장 (같은 버전 코드를 두 번 올리지 않는다)
- `listing-cfg.cjs <앱> <read|apply>` + `play-listing.mjs` → 기본 스토어 등록정보의 앱 이름·짧은 설명 변경 (두 단계: 다음 → 저장)
- `play-send.mjs` → 게시 개요에서 검토 요청. 같은 날 검토 중인 건이 있으면 "검토 다시 시작"으로 함께 보낸다
- `make-answers.cjs` + `play-apply.mjs` → 프로덕션 액세스 신청서 (2026-11-17 제출 완료, 답변은 `apps/qa/2026-11-17-production-access-application.json`)

주의: 사실이 아닌 내용을 신청서·출시 노트에 쓰지 않는다. 광고를 누르지 않는다.
