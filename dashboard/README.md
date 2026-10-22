# BaroLab 통합 운영 구조

- `agents/`: 6인 크루, 회의실, 발행 후 학습.
- `server/`: 8790 서버와 6단 콕핏.
- `common/`: Ubuntu Chrome·LLM 연결과 공용 실행 잠금.
- `collectors/`: 수익·트래픽·색인·공개 발행 확인.
- `data/`: 운영 원장, Vault, 채널 상태. `secure/`와 DB는 Git 제외.
- `data/public/`: HTTP 공개를 허용한 7개 대시보드 요약 파일.
- `tests/`, `test_dashboard.py`: 보존한 회귀 테스트와 통합 운영 계약 테스트.

각 채널은 `posting.py` 한 곳에서 키워드 → 실제 리서치 → 원고·이미지 블록 → 형식 검증 → 발행/예약 → 실제 결과 확인을 수행한다. 별도 모델 검수 승인이나 경쟁글 순위 전량 수집을 기다리지 않는다. 불명확한 제출 결과는 재전송 전에 조회한다.

CF·네이버·Threads 자동 요청은 memory-review 디스패처 한 곳에서 제한된 작업 단위로 순환한다. 지식iN은 별도 cadence 타이머가 전담한다. CF 중복 타이머는 비활성화했다. 서비스 정의는 `server/services/`에 보존한다.

루트 호환 링크는 두지 않는다. Python 가상환경 site-packages의 `barolab_root.pth`와 `barolab_dashboard.pth`에 저장소 루트와 `dashboard/`를 각각 등록한다. `apps/`의 Android 4개 프로젝트는 루트에 실체로 보존한다.

8790 서버의 단일 Collector가 `data/live_snapshot.json`을 1초마다 원자적으로 교체한다. 웹 `/api/mission-control`, `/api/live-snapshot`, `/api/status`와 EGO SnapshotReader가 동일 revision을 사용한다. 모니터는 브라우저·크레딧 조회를 별도로 실행하지 않는다. 네이버 공개 확인은 화면의 자동 polling에서 실행하지 않는다.

`memory.html` 기본 그래프와 `/api/memory/summary`는 `data/memory_graph.json`의 노드·관계를 표시한다. 기존 문서 기반 기억의 편집 기능은 “문서 기억 편집 보기”에 보존한다.


검증 명령:

```sh
python3 -B cf_posting/test_posting.py
python3 -B naver_blog_posting/test_posting.py
python3 -B naver_kin/test_posting.py
python3 -B threads_posting/test_posting.py
python3 -B dashboard/test_dashboard.py
python3 -B -m unittest discover -s dashboard/tests/runtime
python3 -B -m unittest discover -s dashboard/tests/common
python3 -B -m pytest -c dashboard/pytest.ini --rootdir=. -q
```

API 통합 테스트에는 테스트 환경의 httpx2가 필요하다. JavaScript 회귀 테스트에는 Node가 필요하다. 운영 서버의 의존성은 늘리지 않았다.

현재 전환 검증(2026-10-23 KST): 통합 및 보존 회귀 테스트 454개 통과. CF 추가 공개 2건, 네이버 공개 1건과 다음 날짜 예약 2건을 확인했다.

- https://www.baronote.kr/basic-pension-application-spouse-financial-consent
- https://www.soulnote.kr/training-allowance-eligibility-payment
- https://blog.naver.com/mustpickinfo/224450625180

예약 2건은 공개 발행 수에 합산하지 않는다. 원고 작성·리서치·공개 검증 시간과 에디터 블록 입력 시간을 구분한다. 하루 전체 목표 완주는 이 검증 결과에 포함하지 않는다.

## Frozen Engine & Evolving Memory

네 채널 `posting.py`는 `76ca310` 버전의 해시를 유지한다. 직원의 자동 코드 수정 요청은 이 실행 파일을 변경할 수 없다. 엔진의 인증·형식·중복 제출·실제 결과 확인은 그대로 보존한다.

`agents/synapse.py`가 기존 워커의 관측 주기에서 5분 간격으로 원장을 읽어 `data/memory_graph.json`을 갱신하고 작은 `data/synapse-recipes.json` 조회 캐시를 만든다. 별도 상주 프로세스나 LLM 심사 호출을 추가하지 않는다. 기존 Vault의 문제·해결 노드는 원장 출처를 보존해 중앙 그래프에 연결한다. 원본 자료는 삭제하지 않는다.

공용 LLM 경계에서 해당 도메인의 상위 3개 패턴과 관련 질문·본문 요약·실제 예약 제목을 최대 10줄로 주입한다. 장애 시 마지막 캐시를 사용하거나 기본 생성으로 진행한다. 모델 산출물 폴더의 `model-audit/synapse-card.json`에 실제 주입문과 해시를 보존한다. 조회 시간은 모델·검색·발행 시간이 아니다.

URL별 공개 HTTP 200은 기본 1점, 24시간 내 확인된 색인은 3점, 실제 클릭은 2점을 준다. URL별 USD 수익이 확인되면 강화하며, 색인·클릭까지 함께 확인된 경우 10점을 준다. 완전한 발행 이후 7일 관측에서 명시적 유입 0일 때만 5점을 낮춘다. 미수집·사이트 전체 수익·예약은 공개 성과나 0점으로 바꾸지 않는다. 동일 관측의 반복 수집은 추가 가산하지 않는다. 가중치는 관측 상관관계이며 인과 효과나 수익 보장이 아니다.

발행 3~7일 된 글 중 최근 실측 유입·노출이 있는 상위 10%만 닥터의 새 부분 보완 후보로 선택한다. 기존 수정 한도·사실 보존·공개 검증은 유지한다. 수정 전 기준값과 동일 길이의 수정 후 별도 기간이 확보되어야 변화량을 기록한다. 유망 글 증거가 없으면 후보는 0개다.

지식iN 질문은 docId를 보존해 연결하고, CF 본문 요약·소제목을 후속 채널의 참고 데이터로 제공한다. 계정별 실패 검색어를 실제 성공한 쿼리로 연결하는 QueryRecipe와 형식 실패 교훈도 그래프 데이터로 저장한다. 관련 없는 계정·주제를 강제로 바꾸지 않는다.

조회 API: `/api/memory/synapses`. 기존 대시보드 비공개 원장 차단 규칙을 유지한다.

실증(2026-10-23): adinfo0905의 빈 signoff·리서치 0건 실패를 엔진 수정 없이 해결했다. 기억의 검색어 치환으로 국세청 본문 3건을 수집하고, 실제 모델 호출의 synapseCardSha256을 확인했다. `output/adinfo0905/synapse-5ddb559f9b`에서 11:00 예약과 서버 저장 문서·예약 목록 재확인을 완료했다. 에디터 입력 0.744초이며 전체 원고 생성·예약 시간과 구분한다. 해결 에피소드 1건과 제출 전 실패 대체 기록을 누적했다. URL별 수익은 아직 확인되지 않았고 발행일이 확정된 3~7일 유망 글 후보는 0건이며, 테스트의 합성 수치를 운영 수익으로 보고하지 않는다.

이전 회귀 검증: 채널 31개 + 통합 운영·시냅스 58개 + 보존 회귀 381개, 총 470개 통과.

최종 운영 스냅샷: 공개 본문·해시 근거가 있는 33개 글과 실측 연결 29개 글을 포함해 232개 노드·384개 연결, 고립 노드 0개. 이는 신규 발행 33건을 뜻하지 않는다. 실제 이번 요청의 추가 성과는 adinfo0905 예약 1건이다.

2026-10-23 관제 일원화 검증: 전체 pytest 499개와 JavaScript 41개 통과. 실제 PTY 70행에서 상속된 LINES=24를 무시하는 회귀를 포함한다. 웹과 EGO의 수익·호출·크레딧·6개 크롬·4채널·6인 크루·Vault/타임라인은 동일 revision으로 비교한다.

채널의 완료·준비·진행·대기·실패와 재시도/차단 연산 수는 구분한다. 지식iN·Threads 연산 원장은 DB/WAL 변경 시에만 읽기 전용으로 집계하고, KST 날짜 경계와 쓰기 잠금에서는 당일 캐시만 유지한다. 인증 파일 참조 4곳도 `data/secure/` 및 `data/`의 실제 파일로 갱신했다.
