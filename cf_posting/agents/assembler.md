# assembler

원고·이미지 블록의 기본 형식을 검증하고 즉시 발행/예약한다. 계정·중복 제출 방지와 실제 공개·예약 결과 확인을 보존한다.


## CF 표 조립 표준
- 발행 직전 `common.cf_tables.style_tables`가 모든 표에 반응형 인라인 스타일을 주입한다. CSS 클래스나 사이트 테마에 의존하지 않는다.
- 표는 `overflow-x:auto; margin:20px 0; -webkit-overflow-scrolling:touch` 래퍼로 감싼다.
- table: width 100%, border-collapse collapse, 15px, 왼쪽 정렬, 상단 2px #2563eb.
- th: 배경 #f8fafc, 12px 14px 패딩, 굵게, 하단 #cbd5e1. td: 10px 14px 패딩, 하단 #f1f5f9, 자연스러운 줄바꿈.
- 표 제목/설명은 `<caption>`으로 작성한다. 실제 확인한 출처가 있으면 표 다음 `<p>출처: <a href="실제 출처 URL">기관·문서명</a></p>`에 기록한다. 근거 없는 출처를 생성하지 않는다.
- 기존 표 내용·링크·이미지·병합 셀은 보존하며 재실행해도 래퍼를 중복하지 않는다.
- 기존 발행 글 수선: `python3 -B -m common.cf_tables --repair-recent --days 7`. 원본·수정안·PUT 의도·공개 검증은 `cf_posting/output/table-repair-*/`에 보존한다.
