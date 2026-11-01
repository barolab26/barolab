---
name: anti-hallucination-grounding
description: LLM 환각 방지 팩트체크 근거 앵커링 Chain of Verification CoVe 가드레일 전 크루 공통 검증 절차
target_models: [claude-opus-4-6, gpt-5.4, gemini-3.1-pro]
hop_depth: 1
freedom_tier: low-strict-grounding
---
# LLM 환각 방지 및 근거 앵커링(Grounding) 마스터 절차

## 📑 목차 (Top-100-Line TOC — `head -n 100` 즉시 스캔용)
1. [5단계 CoVe + 역방향 회귀 검증 (Go-Back Loop — Anthropic Rule #5)](#1-5단계-cove--역방향-회귀-검증-go-back-loop--anthropic-rule-5)
2. [3대 절대 원칙 (Negative Guardrails)](#2-3대-절대-원칙-negative-guardrails)
3. [채널별 실전 적용 가이드 (3단계 자유도 분리)](#3-채널별-실전-적용-가이드-3단계-자유도-분리)
4. [크루별 역할 및 1-Hop 길잡이 연결](#4-크루별-역할-및-1-hop-길잡이-연결)

GitHub 상위 환각 방지 프레임워크(Guardrails AI, NeMo Guardrails, RAGAS), Meta CoVe(Chain of Verification) 연구 및 앤트로픽 공식 스킬 7대 규칙에 근거한 BaroLab 크루 공통 환각 차단 절차다.
모든 크루(Jarvis, Publi, Radar, Doctor, Trace, Patch)는 외부 문서나 도구 출력을 다룰 때 사전 지식이나 과거 세션의 잔재를 배제하고 오직 현재 제공된 근거(Ground Truth)에만 앵커링한다.

---

## 1. 5단계 CoVe + 역방향 회귀 검증 (Go-Back Loop — Anthropic Rule #5)

모든 텍스트 생성 및 안건 판단 시 다음 5단계를 수행하며, **5단계 미달 시 반드시 3단계로 되돌아간다**:

1. **의도 및 1-Hop 길잡이 확인**:
   - 제공된 문서(`sources`, `evidence`, `context`)와 `dashboard/data/second_brain/01_CEO_철학_자청4대결핍.md`의 핵심 결핍 타격 포인트를 파악한다.
2. **검증 질문 및 핵심 수치 추출 (Fact-Check Query Extraction)**:
   - 본문에 포함할 핵심 주장(금액, 퍼센트, 자격 조건, 날짜, 기관명, 절차)을 원천 문서에서 먼저 발췌한다.
3. **고자유도 설득 초안 집필 (High-Freedom Persuasive Draft)**:
   - 발췌한 팩트 수치를 바탕으로 독자의 손실 회피·정보 비대칭을 해소하는 본문과 비교표를 작성한다.
4. **독립 소스 1:1 대조 (Source-Only Verification)**:
   - 외부 지식이나 모델 자체의 기억을 차단하고, **오직 제공된 문서 텍스트만** 대조하여 미확인 수치를 제거한다.
5. **역방향 회귀 검증 (Go-Back Gate — 핵심)**:
   - *"본문의 모든 주장에 구체적 금액/수치/비교표가 포함되어 있는가? 공무원식 회피 문구('담당자에게 문의하세요', '기관별로 상이합니다')가 없는가?"*를 점검한다. **하나라도 미달이면 즉시 3단계로 되돌아가(Go Back to Step 3) 본문을 재작성한다.**

---

## 2. 3대 절대 원칙 (Negative Guardrails)

1. **과거 세션 및 타 도메인 고정관념 격리 (Context Isolation)**:
   - 이전 작업에서 다루었던 특정 주제(예: 정책자금, 연말정산 등)나 타 도메인 규칙을 현재 작업에 임의로 투영하지 않는다.
   - 현재 턴에 주어진 입력(`inputs`, `questions`, `articles`) 자체의 연관성만 보고 판단한다.
2. **사소한 세부 불일치 핑계로 인한 작업 거부 금지**:
   - 제공된 자료의 핵심 내용이 질문자의 문제를 해결할 수 있다면, 불필요하게 엄격한 형식 잣대를 들이대며 거부(`no_good_match` 등)하지 않는다. 자료의 실질적 가치를 전달하는 해결자 관점을 유지한다.
3. **무근거 수치·출처 날조 원천 금지 (Zero Hallucination)**:
   - 소스 문서에 없는 금액, 퍼센트, 기한, 공식 기관 안내를 그럴듯하게 지어내지 않는다.

---

## 3. 채널별 실전 적용 가이드 (3단계 자유도 분리)

* **지식iN (`naver_kin/posting.py` — порт: CDP 9440)**:
  - 질문자의 핵심 고민에 공감하고, 연결할 블로그 글(`baronote.kr`, `must-good.com` 등)과 공식 문서에서 검증된 핵심 요약 팁을 본문에 충실히 전달한다.
  - 소유 고지('제가 운영하는')와 함께 추가 정보를 확인할 수 있는 링크를 1회 자연스럽게 배치한다.
* **블로그 (`cf_posting/posting.py`, `naver_blog_posting/posting.py`)**:
  - 공식 발표 공고, 제도 시행일, 법령 기준을 교차 검증하고, 확인되지 않은 일정은 '현재 기준/예정'임을 명시한다.
* **SNS / Threads (`threads_posting/posting.py`)**:
  - 피드 후킹용 수치는 반드시 원문 본문의 검증된 팩트만을 인용하며, 과장이나 허위 어그로를 금지한다.

---

## 4. 크루별 역할 및 1-Hop 길잡이 연결

* **1-Hop 참조**: `dashboard/data/second_brain/00_INDEX_세컨드브레인_길잡이.md`
* **jarvis (총괄)**: 크루들이 편향이나 환각에 빠지지 않고 제공된 팩트에 기반해 안건을 전진시키는지 감시.
* **publi (제작)**: CoVe 5단계를 통해 문서에 근거한 신뢰성 높은 본문 및 답변 작성.
* **doctor (감사)**: 발행 직전 본문의 모든 수치·조건이 첨부된 소스 문서와 100% 일치하는지 팩트체크.
* **radar (스카우트)**: 수집된 원천 자료의 출처 신뢰도 및 최신성을 검증하고 가설과 사실을 분리.
* **trace (분석)**: 실측 데이터(클릭, 색인, 수익)만을 기록하고 추정치나 미확인 수치를 성과로 보고하지 않음.
* **patch (엔지니어)**: 툴 에러 및 브라우저 로그를 가공/은폐 없이 원본 그대로 크루에게 전달하여 판단 오염 방지.

---

관계: [[hubs/crew-jarvis]] [[hubs/crew-publi]] [[hubs/crew-doctor]] [[hubs/channel-naver-kin]] [[hubs/channel-cf-blog]] [[hubs/channel-naver-blog]] [[hubs/channel-threads]]

<!-- barolab-knowledge {"knowledge":{"kind":"verified_skill","provenance":"curated_procedure","executionVerified":true,"reusable":true,"lesson":"LLM 환각을 방지하기 위해 CoVe 4단계 검증과 Strict Grounding을 적용하고 이전 도메인 편향을 격리한다.","steps":["초안 작성","팩트체크 검증 질문 추출","소스 문서 1:1 대조","검증된 사실만 남긴 최종 출력"],"sourceRef":"https://github.com/guardrails-ai/guardrails","sourceAgent":"doctor","channel":"naver_kin","verification":{"passed":true,"evidence":"CoVe & Grounding guardrail procedure verified against GitHub industry standards"}}} -->
