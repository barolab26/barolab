# BaroLab 통합 운영 구조

- `agents/`: 6인 크루, 회의실, 발행 후 학습.
- `runtime/`: 8790 서버, 6단 콕핏, Ubuntu Chrome·LLM 연결, 공용 실행 잠금.
- `collectors/`: 수익·트래픽·색인·공개 발행 확인.
- `data/`: 운영 원장, Vault, 채널 상태. `secure/`와 DB는 Git 제외.
- `data/public/`: HTTP 공개를 허용한 7개 대시보드 요약 파일.
- `tests/`, `test_dashboard.py`: 보존한 회귀 테스트와 통합 운영 계약 테스트.

각 채널은 `posting.py` 한 곳에서 키워드 → 실제 리서치 → 원고·이미지 블록 → 형식 검증 → 발행/예약 → 실제 결과 확인을 수행한다. 별도 모델 검수 승인이나 경쟁글 순위 전량 수집을 기다리지 않는다. 불명확한 제출 결과는 재전송 전에 조회한다.

CF·네이버·Threads 자동 요청은 memory-review 디스패처 한 곳에서 제한된 작업 단위로 순환한다. 지식iN은 별도 cadence 타이머가 전담한다. CF 중복 타이머는 비활성화했다. 서비스 정의는 `runtime/services/`에 보존한다.

기존 명령과 원장 참조를 위해 루트 `server`, `common`, `apps`, `skills` 및 채널 `data`는 호환 심볼릭 링크로 유지한다. 실제 파일은 통합 위치 한 곳에만 둔다. Android 프로젝트·기존 원장·로그인 프로필은 삭제하지 않았다.

검증 명령:

```sh
python3 -B cf_posting/test_posting.py
python3 -B naver_blog_posting/test_posting.py
python3 -B naver_kin/test_posting.py
python3 -B threads_posting/test_posting.py
python3 -B dashboard/test_dashboard.py
python3 -B -m unittest discover -s dashboard/tests/runtime
python3 -B -m unittest discover -s dashboard/tests/common
```

API 통합 테스트에는 테스트 환경의 httpx2가 필요하다. JavaScript 회귀 테스트에는 Node가 필요하다. 운영 서버의 의존성은 늘리지 않았다.

현재 전환 검증(2026-10-23 KST): 통합 및 보존 회귀 테스트 454개 통과. CF 추가 공개 2건, 네이버 공개 1건과 다음 날짜 예약 2건을 확인했다.

- https://www.baronote.kr/basic-pension-application-spouse-financial-consent
- https://www.soulnote.kr/training-allowance-eligibility-payment
- https://blog.naver.com/mustpickinfo/224450625180

예약 2건은 공개 발행 수에 합산하지 않는다. 원고 작성·리서치·공개 검증 시간과 에디터 블록 입력 시간을 구분한다. 하루 전체 목표 완주는 이 검증 결과에 포함하지 않는다.
