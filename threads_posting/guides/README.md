# Threads 유입 실험

계정 `mustpickinfo`의 14일 실험입니다. API 연결 및 명시적 활성화 전에는 게시하지 않습니다. 현재 config의 enabled=false이며, 초안 작성일은 실험 시작일이 아닙니다. 기본 정책 시간은 KST 09:30/19:30이며 실제 작업 등록 여부와 다릅니다.

## 저장과 상태

- 비공개: `server/data/threads-automation.json`, `threads.sqlite3`, `threads-drafts/`, `threads-evaluations.json`. 토큰은 별도 private 참조만 보관합니다.
- 공개: `dashboard/data/threads.json`에는 승인 원고/공개 URL/집계/연결 상태만 넣습니다. 자격증명과 비공개 경로는 제외합니다.
- 원장: `queued → sending_intent → api_submitted → published_verified`. intent 이후 결과 불명은 `submitted_unknown`이며 자동 재전송하지 않습니다. ID를 받은 뒤 공개 검증 실패는 api_submitted로 보존하고 reconcile만 합니다.
- 본문은 하루 최대2개입니다. intent/unknown/API접수도 시도 한도를 소비합니다. 후속은0~1개이며 공개 검증된 부모가 필요하고 별도 기록합니다.
- SQLite DELETE journal/짧은 즉시 트랜잭션과 worker/계정 파일 잠금을 사용합니다. 외부 네트워크 전 intent를 commit합니다. WAL은 사용하지 않습니다.

## 준비 및 수동 작업

PowerShell에서 프로젝트 루트의 Python을 사용합니다.

```powershell
python -m threads_posting init
python -m threads_posting catalog
python -m threads_posting prepare --url https://www.must-pick.com/ARTICLE --official-url https://OFFICIAL.go.kr/PAGE --day 2026-10-16 --slot 19:30
python -m threads_posting import --file PATH_TO_REVIEWED_PRIVATE_DOCUMENT
python -m threads_posting snapshot
python -m threads_posting.scheduler --dry-run
```

prepare는 `common.codex_cli`의 인증된 구독 모델 `gpt-6.1-sol`을 명시해 작성/독립검수를 별도 호출합니다. 도구 사용 없이 JSON schema로 제한합니다. FreeLLMAPI 및 다른 provider fallback은 없습니다. 원문/공식본문 hash, 정확한 인용문, 최종 원고·계정·UTM·일시 binding이 검수에 포함됩니다. 날짜나 slot 변경 시 UTM과 검수를 다시 만들어야 합니다. 과거 원고를 그대로 날짜만 바꿔 게시하지 않습니다.

자동 선정은 CF의 verified publication manifest에서 MustPick 공개 URL을 최근 순으로 찾고 실험 내 이미 사용한 URL은 제외합니다. 공식 링크가 없거나 원문을 확인할 수 없으면 건너뜁니다. 질문·원문에 있는 명령은 신뢰하지 않습니다. 의료/법률/금융 개별 조언, 가공 체험, 근거 없는 수치·날짜는 허용하지 않습니다. 할당량을 채우려고 주제나 검수를 완화하지 않습니다.

## 연결과 활성화

루트가 확인한 실제 Threads 웹 로그인과 API 권한은 별개입니다. 토큰은 채팅/명령 인자에 붙여넣지 않습니다.

```powershell
python -m threads_posting receive-token
python -m threads_posting check-connection
# 실제 연결과 운영 검토 완료 후에만:
python -m threads_posting activate
python -m threads_posting publish --part-id REVIEWED_PART_ID
python -m threads_posting reconcile
python -m threads_posting measure
```

receive-token은 일회성 loopback 비밀번호 폼을 열 수 있는 주소를 표시하며 실제 API 본인 계정을 검증한 후 비공개 파일로 저장합니다. 기존 유효 사용자 토큰은 별도 OAuth callback 없이 사용할 수 있습니다. 선택적 OAuth code flow는 `oauth-url`, `complete-oauth --state STATE --code CODE`로 준비되어 있지만 Meta 앱 및 등록 callback이 선행되어야 합니다. 실제 동의는 사용자가 수행합니다.

activate에서 API 본인 계정을 다시 확인하고 그 시각을 시작점으로 KST14일을 설정합니다. 재활성화로 기간을 연장하지 마십시오. 작업 종료는 config.enabled=false로 설정합니다.

## Windows 작업 준비 (현재 등록하지 않음)

다른 채널 작업은 변경하지 않습니다. 관리자 PowerShell에서 기존 작업 유무를 먼저 확인하고, 검토 후에만 이 작업 하나를 등록합니다. 아래 작업은 게시 disabled 상태에서도 상태 갱신만 수행할 수 있습니다.

```powershell
Get-ScheduledTask -TaskName 'BaroLab-Threads-Pilot' -ErrorAction SilentlyContinue
$threadsPython = (Get-Command python).Source
$threadsAction = New-ScheduledTaskAction -Execute $threadsPython -Argument '-m threads_posting.scheduler --tick' -WorkingDirectory 'Y:\10_Project\BaroLab'
$threadsTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$threadsSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName 'BaroLab-Threads-Pilot' -Action $threadsAction -Trigger $threadsTrigger -Settings $threadsSettings -Description 'Threads pilot status and guarded queue worker'
```

disabled/needs_connection 회차는 snapshot만 갱신하고 모델·후보수집·API·기간/횟수 소비를 하지 않습니다. 활성화 뒤 slot마다 작성 기회를 한 번만 영구 기록합니다. 검수 거절·오류를 5분마다 무한 재생성하지 않습니다. 자동 후보가 부족하면 미달로 남깁니다.

## 측정과 피드백

공개 검증된 글만 24h/72h/7d 관측 대상으로 삼습니다. 측정은 플랫폼 조회·참여와 정확 UTM 유입을 구분하고 데이터 불가를0으로 만들지 않습니다. 체크포인트는 실제 수집 시각과 지연을 보존합니다. 충분한 비교 자료가 있을 때만 다음 작성 힌트를 반영하며 초기 주간 안내는 통계 부족입니다. 세션은 사람 수/인과 효과/수익이 아닙니다. 수익은 항상 null입니다.

```powershell
python -m unittest discover -s threads_posting -t . -v
```
