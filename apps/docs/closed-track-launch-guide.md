# Google Groups 기반 원클릭 비공개 테스트(Closed Testing) 전환 가이드 & 반자동 스크립트

- **문서 경로**: `apps/docs/closed-track-launch-guide.md`
- **최종 갱신**: 2026-10-18 KST
- **전담 에이전트**: `@patch` (빌드·트랙 승격·랜딩 개편) · `@trace` (테스터 Opt-in · 14일 요건 실측)

---

## 1. 기존 방식 폐기 사유 및 진실성(Truth) 감사 결과

1. **치명적 착시 교정 (`내부 테스트` vs `비공개 테스트`)**:
   - 현재 4개 앱(`오늘의 성경말씀`, `오늘의 안부`, `큰글씨 돋보기`, `말로 장보기`)은 모두 **`internalTrack: "internal"` (내부 테스트, 등록 테스터 1명: `baro76650@gmail.com`)** 상태입니다.
   - Google Play 개인 개발자 계정의 프로덕션 출시 필수 요건인 **"비공개 테스트(Closed Testing) 12명 이상 Opt-in 후 14일 연속 유지"** 카운트다운은 **비공개 트랙 개설 및 12명 Opt-in이 완료되는 순간부터 시작**됩니다 (`내부 테스트` 배포일인 `2026-10-14` 기준 D+4일/D-10일 카운트다운은 전면 폐기).
2. **이메일 사전 신청(`mailto:baro76650@gmail.com`) 전면 폐기**:
   - 기존 `barolab-daily-apps.pages.dev/testers/` 랜딩페이지는 참여자에게 *"기기 모델과 기간을 적어 이메일을 보내면 추후 개별 등록 후 링크를 보내주겠다"*는 고마찰(High-Friction) 사전 신청 방식을 사용하여 **실제 비공개 테스트 Opt-in 전환율이 0건**이었습니다.
   - 이를 전면 폐기하고, 글로벌·국내 품앗이 표준인 **[Step 1: Google 그룹스 1초 가입] → [Step 2: 앱 4종 원클릭 Opt-in & 설치]** 구조로 전환합니다.

---

## 2. 앱 4종 Play Console & 번들 명세표 (승격 대상)

이미 내부 테스트 트랙에 업로드·검증 완료된 서명 번들(AAB)을 재빌드 없이 그대로 **비공개 테스트(Alpha)** 트랙으로 승격(Promote)합니다.

| 앱 이름 | 패키지명 (`applicationId`) | Play App ID | 검증된 AAB 버전 | Play Console 비공개 트랙 직행 URL | 웹 Opt-in URL (비공개 트랙 승인 후 활성) |
|---|---|---|---|---|---|
| **오늘의 안부** | `com.barolab.morningcard` | `4973731498485355571` | `v2` (`0.2.0-internal-preview`) | [비공개 테스트 관리](https://play.google.com/console/u/0/developers/7752283694845461925/app/4973731498485355571/tracks/closed-testing) | `https://play.google.com/apps/testing/com.barolab.morningcard` |
| **큰글씨 돋보기** | `com.barolab.biglens` | `4972819523776643880` | `v2` (`0.2.0-internal-preview`) | [비공개 테스트 관리](https://play.google.com/console/u/0/developers/7752283694845461925/app/4972819523776643880/tracks/closed-testing) | `https://play.google.com/apps/testing/com.barolab.biglens` |
| **말로 장보기** | `com.barolab.voicebasket` | `4972748430542309887` | `v2` (`0.2.0-internal-preview`) | [비공개 테스트 관리](https://play.google.com/console/u/0/developers/7752283694845461925/app/4972748430542309887/tracks/closed-testing) | `https://play.google.com/apps/testing/com.barolab.voicebasket` |
| **오늘의 성경말씀** | `com.barolab.harubible` | `4975007773224005878` | `v4` (`0.4.0-internal-preview`) | [비공개 테스트 관리](https://play.google.com/console/u/0/developers/7752283694845461925/app/4975007773224005878/tracks/closed-testing) | `https://play.google.com/apps/testing/com.barolab.harubible` |

---

## 3. 단계별 체크리스트 (Play Console & Google Groups 5분 컷)

### Step A. Google Groups 통합 테스터 그룹 개설 (최초 1회)
- [ ] [Google Groups 생성 페이지](https://groups.google.com/my-groups) 접속 (`baro76650@gmail.com` 또는 운영 계정)
- [ ] **그룹 이름**: `BaroLab Android Testers`
- [ ] **그룹 이메일**: `barolab-testers@googlegroups.com` (`https://groups.google.com/g/barolab-testers`)
- [ ] **개인정보 보호 설정 (필수)**:
  - 그룹을 볼 수 있는 사용자: `웹의 모든 사용자`
  - **그룹에 가입할 수 있는 사용자**: **`웹의 모든 사용자 (Anyone on the web can join)`** ← *승인 대기 없이 1초 즉시 가입되도록 설정*
  - 대화 열람/게시: `그룹 관리자만` (테스터 이메일 노출 방지)

### Step B. Play Console 4개 앱 비공개 테스트(Alpha) 그룹 연동
4개 앱 각각의 **테스트 > 비공개 테스트 > Alpha 트랙 관리 > [테스터] 탭**에서:
- [ ] 테스터 방식: **`Google 그룹스(Google Groups)`** 라디오 버튼 선택
- [ ] 이메일 주소 입력란에 **`barolab-testers@googlegroups.com`** 입력 후 `[변경사항 저장]` 클릭
- [ ] **국가/지역 탭**: `대한민국` (및 글로벌 품앗이 병행 시 `전체 국가`) 추가 후 저장

### Step C. 내부 테스트(Internal) AAB → 비공개 테스트(Closed - Alpha) 원클릭 승격(Promote)
4개 앱 각각의 **테스트 > 내부 테스트 > [버전(Releases)] 탭**에서:
- [ ] 현재 게시된 버전(`v2 0.2.0-internal-preview` 또는 성경앱 `v4 0.4.0-internal-preview`) 우측의 **`[버전 승격 (Promote release)] → [비공개 테스트 - Alpha]`** 클릭
- [ ] 출시 노트에 한국어 테스트 안내 문구 확인 후 **`[다음] → [저장] → [게시 개요로 이동] → [변경사항을 검토용으로 전송]`** 클릭

---

## 4. 반자동 상태 검증 및 트랙 승격 반영 스크립트

비공개 트랙 승격 및 테스터 Opt-in 인원 변화를 로컬 원장(`apps/deployment.json`, `apps/bible/deployment.json`, `apps/*/project.json`)과 대시보드에 즉시 반영하는 반자동 CLI 명령어입니다.

```powershell
# 1. 현재 4개 앱의 내부/비공개 트랙 상태 및 14일 카운트다운 진실성(Truth) 즉시 감사
python -c "from server import projects; import json; print(json.dumps(projects.sync_manifests_to_disk(force_verify=True), ensure_ascii=False, indent=2))"

# 2. Cloudflare Pages (barolab-daily-apps.pages.dev/testers/) 원클릭 랜딩페이지 배포
npx wrangler pages deploy apps/web --project-name barolab-daily-apps --branch main
```

### 비공개 트랙 개설 및 Opt-in 수 갱신 표준 규칙 (`server/projects.py` 연동)
- `internalTrack == "internal"` 이거나 `closedTestOptIns < 12` 인 동안에는:
  - **현재 트랙**: `내부 테스트 (테스터 1명) — ⚠️ 14일 카운트다운 미시작`
  - **비공개 테스트 현황**: `비공개 트랙 미개설 · 참여 테스터 0 / 12명 (12명 Opt-in 완료 시 14일 카운트 시작)`
- Play Console에서 비공개 트랙 개설 완료 및 `optedInTesters >= 12` 도달이 확인되면, `apps/deployment.json`의 `closedTesting.trackOpened = true`, `closedTesting.optedInTesters = 12`, `closedTesting.startedAt = "<ISO8601>"` 및 `internalTrack = "closed"`로 갱신되어 그 시점부터 정확한 14일 카운트다운(`D+1일째 · 14일 요건 D-13일`)이 작동합니다.
