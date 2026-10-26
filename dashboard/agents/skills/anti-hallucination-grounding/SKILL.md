---
name: anti-hallucination-grounding
description: LLM 환각 방지 팩트체크 근거 앵커링 Chain of Verification CoVe 가드레일 전 크루 공통 검증 절차
---
# LLM 환각 방지 및 근거 앵커링(Grounding) 마스터 절차

GitHub 상위 환각 방지 프레임워크(Guardrails AI, NeMo Guardrails, RAGAS) 및 Meta CoVe(Chain of Verification) 연구에 근거한 BaroLab 크루 공통 환각 차단 절차다.
모든 크루(Jarvis, Publi, Radar, Doctor, Trace, Patch)는 외부 문서나 도구 출력을 다룰 때 사전 지식이나 과거 세션의 잔재를 배제하고 오직 현재 제공된 근거(Ground Truth)에만 앵커링한다.

---

## 1. 4단계 CoVe (Chain of Verification) 핵심 프로세스

모든 텍스트 생성 및 안건 판단 시 다음 4단계를 무의식적으로 수행한다:

1. **초안 작성 (Draft Generation)**:
   - 제공된 문서(`sources`, `evidence`, `context`)를 바탕으로 질문자의 의도에 맞는 답변 또는 작업 초안을 작성한다.
2. **검증 질문 추출 (Fact-Check Query Extraction)**:
   - 본문에 포함된 핵심 주장(수치, 제도, 자격 조건, 날짜, 기관명, 절차)에 대해 *"이 내용이 제공된 소스 문서에 명시되어 있는가?"*를 스스로 묻는 검증 질문을 추출한다.
3. **독립 소스 대조 (Source-Only Verification)**:
   - 외부 지식이나 모델 자체의 기억을 완전히 차단하고, **오직 제공된 문서 텍스트만** 대조하여 검증 질문에 답변한다.
   - 문서에 명시되지 않은 수치나 확정적 사실은 가설로 표기하거나 즉시 삭제한다.
4. **최종 교정 및 앵커링 (Final Grounded Output)**:
   - 독립 검증을 통과한 문장만으로 최종 결과물을 완성한다. 불확실하거나 모순된 내용은 단호히 제거한다.

---

## 2. 3대 절대 원칙 (Negative Guardrails)

1. **과거 세션 및 타 도메인 고정관념 격리 (Context Isolation)**:
   - 이전 작업에서 다루었던 특정 주제(예: 정책자금, 연말정산 등)나 타 도메인 규칙을 현재 작업에 임의로 투영하지 않는다.
   - 현재 턴에 주어진 입력(`inputs`, `questions`, `articles`) 자체의 연관성만 보고 판단한다.
2. **사소한 세부 불일치 핑계로 인한 작업 거부 금지**:
   - 제공된 자료의 핵심 내용이 질문자의 문제를 해결할 수 있다면, 불필요하게 엄격한 형식 잣대를 들이대며 거부(`no_good_match` 등)하지 않는다. 자료의 실질적 가치를 전달하는 해결자 관점을 유지한다.
3. **무근거 수치·출처 날조 원천 금지 (Zero Hallucination)**:
   - 소스 문서에 없는 금액, 퍼센트, 기한, 공식 기관 안내를 그럴듯하게 지어내지 않는다. 모르는 것은 모른다고 하거나 공식 채널(공단, 고객센터 등) 조회를 안내한다.

---

## 3. 채널별 실전 적용 가이드

* **지식iN (Naver Kin)**:
  - 질문자의 핵심 고민에 공감하고, 연결할 블로그 글(`baronote.kr`, `must-good.com` 등)과 공식 문서에서 검증된 핵심 요약 팁을 본문에 충실히 전달한다.
  - 소유 고지('제가 운영하는')와 함께 추가 정보를 확인할 수 있는 링크를 1회 자연스럽게 배치한다.
* **블로그 (CF / Naver Blog)**:
  - 공식 발표 공고, 제도 시행일, 법령 기준을 교차 검증하고, 확인되지 않은 일정은 '현재 기준/예정'임을 명시한다.
* **SNS / Threads**:
  - 피드 후킹용 수치는 반드시 원문 본문의 검증된 팩트만을 인용하며, 과장이나 허위 어그로를 금지한다.

---

## 4. 크루별 역할 정의

* **jarvis (총괄)**: 크루들이 편향이나 환각에 빠지지 않고 제공된 팩트에 기반해 안건을 전진시키는지 감시.
* **publi (제작)**: CoVe 4단계를 통해 문서에 근거한 신뢰성 높은 본문 및 답변 작성.
* **doctor (감사)**: 발행 직전 본문의 모든 수치·조건이 첨부된 소스 문서와 100% 일치하는지 팩트체크.
* **radar (스카우트)**: 수집된 원천 자료의 출처 신뢰도 및 최신성을 검증하고 가설과 사실을 분리.
* **trace (분석)**: 실측 데이터(클릭, 색인, 수익)만을 기록하고 추정치나 미확인 수치를 성과로 보고하지 않음.
* **patch (엔지니어)**: 툴 에러 및 브라우저 로그를 가공/은폐 없이 원본 그대로 크루에게 전달하여 판단 오염 방지.

---

관계: [[hubs/crew-jarvis]] [[hubs/crew-publi]] [[hubs/crew-doctor]] [[hubs/channel-naver-kin]] [[hubs/channel-cf-blog]] [[hubs/channel-naver-blog]] [[hubs/channel-threads]]

<!-- barolab-knowledge {"knowledge":{"kind":"verified_skill","provenance":"curated_procedure","executionVerified":true,"reusable":true,"lesson":"LLM 환각을 방지하기 위해 CoVe 4단계 검증과 Strict Grounding을 적용하고 이전 도메인 편향을 격리한다.","steps":["초안 작성","팩트체크 검증 질문 추출","소스 문서 1:1 대조","검증된 사실만 남긴 최종 출력"],"sourceRef":"https://github.com/guardrails-ai/guardrails","sourceAgent":"doctor","channel":"naver_kin","verification":{"passed":true,"evidence":"CoVe & Grounding guardrail procedure verified against GitHub industry standards"}}} -->
