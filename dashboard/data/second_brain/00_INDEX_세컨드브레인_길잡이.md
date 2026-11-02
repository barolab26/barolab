---
name: second-brain-index-moc
target_models: [claude-opus-4-6, gpt-5.4, gemini-3.1-pro]
hop_depth: 1
freedom_tier: medium-template
updated_at: "2026-11-02 15:57:25 KST"
---
# 🧠 BaroLab 세컨드 브레인 1-Hop 마스터 길잡이 (Map of Content)

## 📑 목차 (Top-100-Line TOC — `head -n 100` 즉시 스캔용)
1. [1-Hop 직통 도메인 길잡이 인덱스 (Anthropic Rule #4)](#1-1-hop-직통-도메인-길잡이-인덱스-anthropic-rule-4)
2. [앤트로픽 공식 클로드 스킬 7대 규칙 표준](#2-앤트로픽-공식-클로드-스킬-7대-규칙-표준)
3. [전 크루 5단계 역방향 회귀 체크리스트 (Go-Back Loop)](#3-전-크루-5단계-역방향-회귀-체크리스트-go-back-loop)
4. [실행 환경·포트·스크립트 명세 (Anthropic Rule #7)](#4-실행-환경포트스크립트-명세-anthropic-rule-7)
5. [대표님 & 크루 수동 추가 노트](#️-대표님--크루-수동-추가-노트)

---

## 1. 1-Hop 직통 도메인 길잡이 인덱스 (Anthropic Rule #4)
> **중첩 참조 금지 원칙**: 모든 에이전트(`@jarvis`, `@radar`, `@publi`, `@doctor`, `@trace`, `@patch`)는 `A -> B -> C` 다단계 탐색 없이 아래 **1-Hop 길잡이 파일**을 직접 참조한다.

| 1-Hop 파일명 | 핵심 역할 및 수록 지식 | 담당/소비 크루 | 자유도 등급 (Rule #2) |
| :--- | :--- | :--- | :--- |
| **`01_CEO_철학_자청4대결핍.md`** | 하루 `\$100` 역산 두뇌 · 자청 4대 결핍 · 대표님 직통 지침(`boss_memories`) · 공무원식 양산형 문체 금지 | 전 크루 공통 (`@jarvis` 총괄) | **High** (설득·후킹 창의성 최대화) |
| **`02_채널별_승리공식_도감.md`** | CF 16개 도메인 · 네이버 5계정 · 지식iN · Threads · 브런치 매체별 문법 및 3단 자유도 분리 | `@publi`, `@doctor`, `@patch` | **Medium** (비교표·3초 요약 템플릿) |
| **`03_외부노하우_벤치마킹_금고.md`** | NotebookLM `SSR+` 아키텍처 · 앤트로픽 공식 스킬 7규칙 · `@radar` 외부 실전 노하우(`PracticalKnowHow`) | `@radar`, `@publi`, `@doctor` | **Medium** (검증된 외부 노하우 조합) |
| **`04_실측우승원고_황금키워드.md`** | 애드센스/애드포스트 수익 리더 · GA4/GSC 상위 15개 우승 글 · `@doctor` CTR 수선 타깃 · 블로키 S/A급 황금키워드 | `@radar`, `@trace`, `@publi`, `@doctor` | **Low/Data** (실측 데이터 100% 앵커링) |
| **`anti-hallucination-grounding/SKILL.md`** | CoVe 4단계 팩트체크 · 무근거 수치 날조 원천 차단 · 도메인 문맥 격리 | 전 크루 공통 (`@doctor` 감사) | **Low** (팩트 검증 엄격 적용) |
| **`seo-marketing-master/SKILL.md`** | Google·Naver·Bing·Daum 4대 포털 색인/수집 검증 및 일일 최소 기준선(Minimum Floor) 3대 병렬 작전 | `@trace`, `@radar`, `@jarvis` | **Medium** (채널별 마케팅 규격) |

---

## 2. 앤트로픽 공식 클로드 스킬 7대 규칙 표준
1. **[Rule #1] 상단 100줄 목차(TOC) 법칙**: 100줄 이상 모든 스킬·길잡이 문서는 최상단 20줄 이내에 목차(TOC)를 배치하여 `head -n 100` 프리뷰만으로 전체 섹션 위치를 파악하게 한다.
2. **[Rule #2] 3단계 자유도 분리 (스크립트로 잠그고 프롬프트는 풀어라)**:
   - **고자유도(High Freedom)**: 본문 스토리텔링, 자청 4대 결핍 타격, 독자 공감 후킹 (관료주의 제약 철폐)
   - **중자유도(Medium Freedom)**: 핵심 숫자 비교표, 3초 요약 박스, 예/아니오 판정 분기표
   - **저자유도(Low Freedom)**: 실제 발행·예약·색인·DB 원장 기록은 프롬프트 잔소리가 아니라 **0 토큰 파이썬 스크립트**(`posting.py`)로 100% 강제
3. **[Rule #3] 최신 프론티어 모델 눈높이 맞춤**: `Opus 4.6`/`GPT-5.4`/`Gemini 3.1 Pro`급 모델의 문맥 추론력을 신뢰하고 구형 모델용 과잉 금지 조항을 제거한다.
4. **[Rule #4] 1-Hop 직통 참조만 허용**: `AGENTS.md` 및 본 인덱스에서 모든 도메인 가이드로 1번에 점프한다.
5. **[Rule #5] 5단계 역방향 회귀 체크리스트**: 5단계에서 기준 미달 시 3단계로 즉시 되돌아가는 루프를 강제한다.
6. **[Rule #6] 자가 진화 피드백 루프 (Self-Updating Brain)**: `@radar` 노하우 입수, `@trace` 실측 성과 갱신 시 본 길잡이 문서들이 자동으로 최신화된다.
7. **[Rule #7] 실행 환경·포트·의존성 명시**: 모든 자동화 도구 옆에 정확한 포트와 실행 명령을 명시한다.

---

## 3. 전 크루 5단계 역방향 회귀 체크리스트 (Go-Back Loop)
모든 원고 집필(`@publi`), 리모델링(`@doctor`), 답변 생성(`kin`/`threads`) 시 아래 5단계를 순서대로 실행한다:
1. **[Step 1 · 길잡이 로드]**: 작업 채널에 맞는 1-Hop 길잡이(`01`~`04`)와 타깃 독자의 핵심 결핍을 확인한다.
2. **[Step 2 · 실측 데이터 매칭]**: `04_실측우승원고_황금키워드.md`의 우승 패턴 및 원천 근거 문서(`sources`)의 구체적 수치(금액·기한·조건)를 추출한다.
3. **[Step 3 · 고자유도 설득 집필]**: 도입부 3문장 안에 **자청 4대 결핍(손실 회피·정보 비대칭·시간 단축·즉시 판정)**을 타격하고, 본문에 **핵심 숫자 비교표**와 **예/아니오 판정 기준**을 배치한다.
4. **[Step 4 · CoVe 팩트 대조]**: 본문의 모든 숫자·자격·절차가 원천 근거 문서와 일치하는지 1:1 대조한다.
5. **[Step 5 · 역방향 회귀 검증 (Go-Back Gate)]**:
   - 핵심 주장에 구체적 숫자/비교표가 빠졌거나, *"담당 기관에 문의하세요"*, *"조건에 따라 다를 수 있습니다"* 같은 **공무원식 회피 문장**이 단 1문장이라도 발견되면 **즉시 Step 3으로 되돌아가(Go Back to Step 3) 본문을 재작성**한다.

---

## 4. 실행 환경·포트·스크립트 명세 (Anthropic Rule #7)
- **전용 브라우저 (EGO Lite v2.2.0 Native TaskSpace & CDP)**:
  - 네이티브 스페이스 엔진: `dashboard/common/ego_taskspace.py` (`ego-browser.exe nodejs` + `Profile 3`~`Profile 7` 직결)
  - 백그라운드 스페이스 작업 원칙: `SetForegroundWindow` 강제 화면 팝업 금지, 작업 완료 시 `await task.finish({ keep: [] })` 즉시 회수, 캡차·로그인 필요 시 `await task.handOff()`로 대표님께 인계
- **통합 대시보드 & 기억 API 서버**: `http://127.0.0.1:8790` (`docker restart barolab-dashboard`)
- **백그라운드 자율 워커**: `pythonw.exe -u -B -X utf8 -m dashboard.server.memory_worker`
- **채널별 0-Token 실행 엔진**:
  - CF 블로그 16개 도메인: `python -m cf_posting.posting`
  - 네이버 블로그 5계정: `python -m naver_blog_posting.posting`
  - 네이버 지식iN: `python -m naver_kin.posting --tick`
  - Threads 숏폼: `python -m threads_posting.posting --tick`

## ✍️ 대표님 & 크루 수동 추가 노트
- (이 영역에 작성한 메모는 세컨드 브레인 자동 동기화 시에도 영구 보존됩니다.)
