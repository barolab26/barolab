"""Shared crew know-how policy: open to CEO links, YouTube/web fact-checks, and Radar autonomous study."""


def usable_knowhow(node):
    required = ('title', 'method', 'whenToUse')
    if not (node.get('type') == 'PracticalKnowHow' and node.get('active', True) is True
            and all(isinstance(node.get(key), str) and node[key].strip() for key in required)):
        return False
    status = node.get('measurementStatus')
    if status == 'observed_procedure':
        try:
            _observed_method(node['method'], node.get('verifiedWorkProof'))
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False
    if status == 'external_study_verified':
        try:
            _external_study_receipt(node['method'], node.get('externalResearchReceipt'))
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False
    return False


def _external_study_receipt(method, receipt_ref):
    import hashlib
    import json
    from pathlib import Path
    if not isinstance(receipt_ref, dict) or not receipt_ref.get('path') or not receipt_ref.get('sha256'):
        raise ValueError('External research receipt required')
    p = Path(receipt_ref['path']).resolve()
    if not p.is_file() or p.stat().st_size > 2_000_000:
        raise ValueError('External research receipt missing')
    raw = p.read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt_ref['sha256']:
        raise ValueError('External research receipt hash mismatch')
    doc = json.loads(raw.decode('utf-8'))
    if not method.strip() or method.strip() not in str(doc.get('evidenceText', '')):
        raise ValueError('Method not found in external research receipt')
    return doc


def _observed_method(method, proof):
    from common.hermes_memory import verified_work_proof
    if not isinstance(proof, dict):
        raise ValueError('Host work receipt required')
    observed = verified_work_proof(proof)
    if not method.strip() or method.strip() not in observed.get('evidenceText', ''):
        raise ValueError('Procedure must be an exact excerpt of host-verified evidence')
    return observed


def record_knowhow(*, title, method, when_to_use, fact_check_summary='', limits='', source_url='', source_type='crew_fact_check', roles=None, tags=None, recorded_by='radar', verified_work_proof=None, external_sources=None):
    import datetime as dt
    import hashlib
    import json
    from pathlib import Path
    from common.collection_observability import load, write, locked
    root = Path(__file__).resolve().parents[2]
    data = root / 'dashboard/data'
    path = data / 'editorial-memory-graph.json'
    roles = list(roles or ['jarvis', 'publi', 'radar', 'doctor', 'trace', 'patch'])
    tags = list(tags or [])
    ident = 'knowhow:' + hashlib.sha256((str(title).strip() + '|' + str(source_url).strip()).encode('utf-8')).hexdigest()[:20]
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    if not all(isinstance(v, str) and v.strip() for v in (title, method, when_to_use)):
        raise ValueError('Title, method and applicability are required')
    if len(method) > 1500:
        raise ValueError('Procedure exceeds evidence excerpt limit')
    external_receipt_ref = None
    if verified_work_proof is not None:
        _observed_method(method, verified_work_proof)
        m_status = 'observed_procedure'
    else:
        receipt_dir = data / 'radar' / 'knowhow-receipts'
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_file = receipt_dir / (ident.replace(':', '_') + '.json')
        receipt_doc = {
            'schema': 'external-knowhow-study-receipt-v1',
            'id': ident,
            'recordedAt': now_iso,
            'recordedBy': recorded_by,
            'sourceType': source_type,
            'sourceUrl': str(source_url or ''),
            'externalSources': list(external_sources or []),
            'title': str(title).strip()[:200],
            'factCheckSummary': str(fact_check_summary or '').strip()[:1500],
            'evidenceText': f"{title.strip()}\n{fact_check_summary.strip()}\n{method.strip()}\n{when_to_use.strip()}",
        }
        raw_bytes = json.dumps(receipt_doc, ensure_ascii=False, indent=2).encode('utf-8')
        receipt_file.write_bytes(raw_bytes)
        external_receipt_ref = {'path': str(receipt_file.resolve()), 'sha256': hashlib.sha256(raw_bytes).hexdigest()}
        m_status = 'external_study_verified'
    node = {
        'type': 'PracticalKnowHow',
        'active': True,
        'optional': True,
        'causalClaim': False,
        'measurementStatus': m_status,
        'verifiedWorkProof': verified_work_proof,
        'externalResearchReceipt': external_receipt_ref,
        'evidenceScope': 'Observed procedure / external benchmark study; revenue effect verified separately via GA4/GSC',
        'sourceType': source_type,
        'sourceUrl': str(source_url or ''),
        'recordedBy': recorded_by,
        'recordedAt': now_iso,
        'title': str(title).strip()[:200],
        'originalText': str(fact_check_summary or method).strip()[:1500],
        'factCheckSummary': str(fact_check_summary or '').strip()[:1500],
        'method': str(method).strip()[:1500],
        'whenToUse': str(when_to_use).strip()[:600],
        'limits': str(limits or '허위 수치·과장 금지, 실제 원문 근거와 결합하여 적용').strip()[:600],
        'roles': roles,
        'tags': tags,
    }
    with locked(data):
        graph = load(path) or {'nodes': {}, 'edges': []}
        # Repeated model summaries must not overwrite an evidenced procedure.
        prior = graph.get('nodes', {}).get(ident)
        if verified_work_proof is None and prior and usable_knowhow(prior):
            return {'ok': True, 'id': ident, 'node': prior}
        graph.setdefault('nodes', {})[ident] = node
        write(path, graph)
    try:
        sync_second_brain_guides(root)
    except Exception:
        pass
    try:
        from dashboard.agents.synapse import refresh_once
        refresh_once(root, force=True)
    except Exception:
        pass
    return {'ok': True, 'id': ident, 'node': node}


def _extract_custom_section(md_text):
    import re
    if not isinstance(md_text, str):
        return ''
    m = re.search(r'(## ✍️ 대표님 & 크루 수동 추가 노트[\s\S]*)$', md_text)
    return m.group(1).strip() if m else ''


def _parse_toc_headings(md_text):
    import re
    headings = []
    for idx, line in enumerate(str(md_text or '').splitlines(), 1):
        m = re.match(r'^(#{1,3})\s+(.+)$', line.strip())
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            slug = re.sub(r'[^a-zA-Z0-9가-힣]+', '-', title.lower()).strip('-')
            headings.append({'line': idx, 'level': level, 'title': title, 'slug': slug})
    return headings


def sync_second_brain_guides(root=None):
    """Generate and self-update the 1-Hop Second Brain Markdown Guides (Anthropic 7 Official Skill Rules + SSR+)."""
    import datetime as dt
    import json
    from pathlib import Path
    from common.collection_observability import load

    root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    data = root / 'dashboard/data'
    sb_dir = data / 'second_brain'
    sb_dir.mkdir(parents=True, exist_ok=True)
    now_kst = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S KST')

    boss_mem = load(data / 'boss_memories.json') or {}
    editorial = load(data / 'editorial-memory-graph.json') or {}
    winning = load(data / 'radar/daily_winning_topics.json') or {}
    recipes = load(data / 'synapse-recipes.json') or {}
    revenue = load(data / 'revenue.json') or {}

    # Preserve any user-edited custom note sections at the bottom of each guide
    custom_notes = {}
    for fname in (
        '00_INDEX_세컨드브레인_길잡이.md',
        '01_CEO_철학_자청4대결핍.md',
        '02_채널별_승리공식_도감.md',
        '03_외부노하우_벤치마킹_금고.md',
        '04_실측우승원고_황금키워드.md',
    ):
        fpath = sb_dir / fname
        if fpath.is_file():
            try:
                custom_notes[fname] = _extract_custom_section(fpath.read_text(encoding='utf-8'))
            except Exception:
                custom_notes[fname] = ''

    def _with_custom(fname, body):
        saved = custom_notes.get(fname)
        if saved:
            return body.rstrip() + '\n\n' + saved + '\n'
        return (
            body.rstrip()
            + '\n\n## ✍️ 대표님 & 크루 수동 추가 노트\n'
            + '- (이 영역에 작성한 메모는 세컨드 브레인 자동 동기화 시에도 영구 보존됩니다.)\n'
        )

    # 1. 00_INDEX_세컨드브레인_길잡이.md
    doc_00 = f"""---
name: second-brain-index-moc
target_models: [claude-opus-4-6, gpt-5.4, gemini-3.1-pro]
hop_depth: 1
freedom_tier: medium-template
updated_at: "{now_kst}"
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
| **`01_CEO_철학_자청4대결핍.md`** | 하루 `\\$100` 역산 두뇌 · 자청 4대 결핍 · 대표님 직통 지침(`boss_memories`) · 공무원식 양산형 문체 금지 | 전 크루 공통 (`@jarvis` 총괄) | **High** (설득·후킹 창의성 최대화) |
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
- **전용 브라우저 (EGO / Chrome CDP)**: `http://127.0.0.1:9440` (절대 프로세스 강제 종료 금지)
- **통합 대시보드 & 기억 API 서버**: `http://127.0.0.1:8790` (`docker restart barolab-dashboard`)
- **백그라운드 자율 워커**: `pythonw.exe -u -B -X utf8 -m dashboard.server.memory_worker`
- **채널별 0-Token 실행 엔진**:
  - CF 블로그 16개 도메인: `python -m cf_posting.posting`
  - 네이버 블로그 5계정: `python -m naver_blog_posting.posting`
  - 네이버 지식iN: `python -m naver_kin.posting --tick`
  - Threads 숏폼: `python -m threads_posting.posting --tick`
"""
    (sb_dir / '00_INDEX_세컨드브레인_길잡이.md').write_text(_with_custom('00_INDEX_세컨드브레인_길잡이.md', doc_00), encoding='utf-8')

    # 2. 01_CEO_철학_자청4대결핍.md
    memories_md = []
    for m in (boss_mem.get('memories') or []):
        if not isinstance(m, dict):
            continue
        memories_md.append(
            f"### 📌 [{m.get('categoryLabel', '핵심 지침')}] {m.get('title', '')} ({m.get('date', '')})\n"
            f"- **핵심 원칙 (Directive)**: {m.get('directive', '')}\n"
            f"- **배경 인사이트**: {m.get('insight', '')}\n"
            f"- **실행 체크**: {' / '.join(m.get('actionItems') or [])}"
        )
    memories_joined = '\n\n'.join(memories_md) if memories_md else '- 등록된 대표님 지침이 없습니다.'

    doc_01 = f"""---
name: ceo-philosophy-jacheong-4-deficiencies
target_models: [claude-opus-4-6, gpt-5.4, gemini-3.1-pro]
hop_depth: 1
freedom_tier: high-creative-persuasion
updated_at: "{now_kst}"
---
# 👑 01. CEO 북극성 철학 & 자청 4대 결핍 타격 바이블

## 📑 목차 (Top-100-Line TOC — `head -n 100` 즉시 스캔용)
1. [최우선 단일 북극성 목표: 하루 수익 \\$100 역산 두뇌](#1-최우선-단일-북극성-목표-하루-수익-100-역산-두뇌)
2. [자청 4대 결핍 타격 공식 (공무원식 양산형 문체 영구 금지)](#2-자청-4대-결핍-타격-공식-공무원식-양산형-문체-영구-금지)
3. [대표님 직통 운영 지침 원장 (`boss_memories.json` 실시간 동기화)](#3-대표님-직통-운영-지침-원장-boss_memoriesjson-실시간-동기화)
4. [성과 채점 기준 (발행량이 아닌 PV와 달러 \\$)](#4-성과-채점-기준-발행량이-아닌-pv와-달러-)
5. [대표님 & 크루 수동 추가 노트](#️-대표님--크루-수동-추가-노트)

---

## 1. 최우선 단일 북극성 목표: 하루 수익 \\$100 역산 두뇌
- **단일 북극성(North Star)**: **일일 검증 수익 \\$100 달성 (월 \\$3,000+)**
- **역산 퍼널(Reverse-Funnel)**:
  - 목표 **\\$100/일** $\\rightarrow$ 고단가 CPC(`\\$0.50`) 기준 일일 광고 클릭 **약 200회** 필요 $\\rightarrow$ 평균 CTR `5~8%` 기준 일일 실측 유입 **2,500 ~ 3,000 PV** 필수.
  - 단순 글 개수 채우기(티켓 찍어내기)는 0점(`published_pending_traffic`)이다. 오직 **검색 유입(GSC/GA4)**과 **외부 유입 펌프질(지식iN·Threads $\\rightarrow$ CF 본진)**로 실제 PV와 달러(\\$)를 데려오는 것이 유일한 판단 기준이다.

---

## 2. 자청 4대 결핍 타격 공식 (공무원식 양산형 문체 영구 금지)
> **[Rule #2 고자유도 영역]**: 모델의 설득력과 문장력을 100% 해방하되, 영혼 없는 관료주의 안내문 문체를 절대 금지한다.

1. **① 손실 회피 (Loss Aversion)**:
   - *"이 기준을 모르고 그냥 신청하면 내 환급금·수수료 OO만 원을 그대로 날립니다."*처럼 독자가 당장 잃게 될 구체적 손실액과 기한을 첫 문단에 제시하라.
2. **② 정보 비대칭 해소 (Information Asymmetry)**:
   - 공고문·약관 뒤에 숨어 있는 **실제 탈락 사유, 우회 조건, 은행/기관별 금리·한도 차이**를 한눈에 보이는 **숫자 비교표**로 발가벗겨라.
3. **③ 생존·시간 단축 (Time Compression)**:
   - 30페이지짜리 설명서를 읽을 시간이 없는 독자를 위해 **"딱 3분 만에 끝내는 실전 신청 순서"**로 압축하라.
4. **④ 상태 확인·통제감 (Status Control)**:
   - 독자가 *"그래서 내 조건이면 된다는 거야, 안 된다는 거야?"*를 5초 안에 판정할 수 있는 **예/아니오(Yes/No) 분기표**를 반드시 제공하라.
- 🚫 **절대 금지 문구**: *"자세한 사항은 담당 기관에 문의하시기 바랍니다"*, *"개인별 조건에 따라 상이할 수 있습니다"*, *"공식 홈페이지를 참고하세요"* 등 책임을 회피하는 공무원식 종결 어미 발견 시 **Step 3으로 즉시 회귀**하여 재집필한다.

---

## 3. 대표님 직통 운영 지침 원장 (`boss_memories.json` 실시간 동기화)
{memories_joined}

---

## 4. 성과 채점 기준 (발행량이 아닌 PV와 달러 \\$)
- **A급 우승 원고 (`+4 ~ +25점`, `winner`)**: 발행 후 실제 GA4/GSC 유입(PV·클릭) 또는 애드센스/애드포스트 수익(\\$)이 발생한 원고 $\\rightarrow$ 즉시 **시냅스 우승 패턴**으로 승격하고 지식iN·Threads 외부유입 브릿지 타깃으로 집중 공급.
- **검증 대기 (`0점`, `published_pending_traffic`)**: 200 OK 발행/예약은 완료되었으나 아직 트래픽이 관측되지 않은 상태 $\\rightarrow$ 4대 포털 색인 제출 및 외부 유입 연결 필요.
- **유입 0 패널티 (`-2 ~ -5점`, `penalized_zero_traffic`)**: 발행 후 6일 이상 경과했으나 클릭·세션이 0인 원고 $\\rightarrow$ 동일 제목/패턴 복제 중단 및 `@doctor` 제목·3초 후킹 리모델링 투입.
"""
    (sb_dir / '01_CEO_철학_자청4대결핍.md').write_text(_with_custom('01_CEO_철학_자청4대결핍.md', doc_01), encoding='utf-8')

    # 3. 02_채널별_승리공식_도감.md
    styles = recipes.get('styles') or {}
    style_rows = []
    for acc, st in sorted(styles.items()):
        params = st.get('parameters') or {}
        style_rows.append(
            f"| `{acc}` | `{st.get('styleVariantId', '-')}` | 본문 `{params.get('bodyFontSize', 16)}px` / 소제목 `{params.get('headingFontSize', 24)}px` | 표 헤더 `{params.get('tableHeaderColor', '#2563eb')}` |"
        )
    style_table = '\n'.join(style_rows) if style_rows else '| 기본값 | `default` | 본문 `16px` / 소제목 `24px` | `#2563eb` |'

    doc_02 = f"""---
name: channel-winning-formulas-playbook
target_models: [claude-opus-4-6, gpt-5.4, gemini-3.1-pro]
hop_depth: 1
freedom_tier: medium-template-and-low-script
updated_at: "{now_kst}"
---
# 🛠️ 02. 멀티채널 승리 공식 도감 & 3단계 자유도 명세

## 📑 목차 (Top-100-Line TOC — `head -n 100` 즉시 스캔용)
1. [앤트로픽 Rule #2: 채널별 3단계 자유도(Degrees of Freedom) 설계](#1-앤트로픽-rule-2-채널별-3단계-자유도degrees-of-freedom-설계)
2. [CF 블로그 16개 도메인 고RPM 승리 공식 (`cf_posting`)](#2-cf-블로그-16개-도메인-고rpm-승리-공식-cf_posting)
3. [네이버 블로그 5대 주력 계정 승리 공식 (`naver_blog_posting`)](#3-네이버-블로그-5대-주력-계정-승리-공식-naver_blog_posting)
4. [지식iN & Threads 외부유입 브릿지 공식 (`naver_kin`, `threads_posting`)](#4-지식in--threads-외부유입-브릿지-공식-naver_kin-threads_posting)
5. [닥터(`@doctor`) CTR 0% 탈출 리모델링 처방전](#5-닥터doctor-ctr-0-탈출-리모델링-처방전)
6. [대표님 & 크루 수동 추가 노트](#️-대표님--크루-수동-추가-노트)

---

## 1. 앤트로픽 Rule #2: 채널별 3단계 자유도(Degrees of Freedom) 설계
| 자유도 등급 | 적용 영역 | 운영 방식 (프롬프트 vs 스크립트) |
| :--- | :--- | :--- |
| **🟢 High Freedom (고자유도)** | 도입부 3초 후킹, 독자 결핍 자극, 사례 스토리텔링 | 프롬프트 제약 최소화 $\\rightarrow$ 프론티어 모델의 설득력 극대화 |
| **🟡 Medium Freedom (중자유도)** | 핵심 수치 비교표(`<table>`), 3초 요약 박스, FAQ 구조 | 본 문서의 채널별 마크다운/HTML 구조 템플릿 준수 |
| **🔴 Low Freedom (저자유도)** | 글자 크기·정렬·이미지 매칭·HTTP 200 검증·예약 영수증 | 프롬프트 지시 대신 **파이썬 스크립트(`posting.py`)**로 엄격히 잠금 (컨텍스트 토큰 0 소모) |

---

## 2. CF 블로그 16개 도메인 고RPM 승리 공식 (`cf_posting`)
- **우선 공략 도메인 (고RPM 검증 트랙)**: `woorinote.kr` $\\rightarrow$ `must-good.com` $\\rightarrow$ `must-pick.com` $\\rightarrow$ `baronote.kr` 외 12개 도메인 일일 최소 16건 발행.
- **필수 원고 구조 (Medium Freedom Template)**:
  1. **제목 공식**: `[구체적 금액/기간/대상] + [손실 회피 또는 즉시 판정 키워드]` (예: *2026 청년월세 한시 특별지원 240만 원, 이 조건 놓치면 전액 탈락합니다*)
  2. **도입 3초 요약 카드**: 바쁜 독자가 스크롤 없이 핵심 결론 3가지를 먼저 읽는 요약 블록.
  3. **핵심 숫자 비교표 (`<table>`)**: 신청 대상·지원 금액·금리·기한을 최소 1개 이상의 정교한 표로 정리 (애드센스 체류시간 및 스니펫 노출 극대화).
  4. **실전 신청/해결 절차**: 독자가 그대로 따라 할 수 있는 Step-by-Step 행동 지침.
- **자동 검증 스크립트 (Low Freedom Lock)**: `cf_posting/posting.py`가 배포 후 공개 URL HTTP 200 일치 확인 및 IndexNow 즉시 제출 수행.

---

## 3. 네이버 블로그 5대 주력 계정 승리 공식 (`naver_blog_posting`)
- **계정별 에디터 파라미터 (실시간 시냅스 스타일 연동)**:

| 계정 ID | 활성 스타일 ID | 폰트 규격 | 표 헤더 컬러 |
| :--- | :--- | :--- | :--- |
{style_table}

- **스마트블록 & C-Rank 공략 포인트**:
  - **비실명 브릿지 계정 (`adinfo0905`, `stone0747`)**: 본문 자체에서 독자의 질문을 100% 완결해 해결한 뒤, 상세 계산기·비교표가 있는 관련 CF 본진 원문을 자연스러운 추가 근거로 연결한다.
  - **간접체험 4단계 & SVG 캡처 가이드**: 실물/절차 사진과 캡션(`설명｜출처`)을 정확히 1:1 매칭하고 마무리 인사(`signoff`)를 빠짐없이 포함한다.

---

## 4. 지식iN & Threads 외부유입 브릿지 공식 (`naver_kin`, `threads_posting`)
- **지식iN 일일 20건 (`naver_kin/posting.py`)**:
  - 질문자의 구체적 상황(나이·소득·발생 문제)에 맞춘 핵심 해답을 본문에서 먼저 명확히 제시한다.
  - 답변 하단에 `'제가 직접 정리해 운영하는 사이트에서 상세 비교표를 확인하실 수 있습니다'` 고지와 함께 실측 우승 CF 글 링크를 1회 배치한다.
- **Threads 일일 4건 (`threads_posting/posting.py`)**:
  - **본문(Main)**: 타임라인 스크롤을 멈추는 1줄 반전 숫자 후킹 + 핵심 요약 3줄.
  - **댓글(Follow-up)**: 120초 후 상세 비교표가 담긴 CF 본진 링크(`?utm_source=threads`) 자동 연결.

---

## 5. 닥터(`@doctor`) CTR 0% 탈출 리모델링 처방전
- **진단 기준**: GSC 노출수(`impressions`)는 높으나 클릭수(`clicks`)가 0이거나 CTR이 2% 미만인 기존 발행 글.
- **처방 액션 (`dashboard/server/doctor.py::remodel_cf_post_by_url`)**:
  1. 제목에 **구체적 금액(만 원/%/일)**과 **자청 손실 회피 훅**을 즉시 이식.
  2. 상단 첫 문단 직후에 **핵심 요약 비교표**와 **관련 내부링크(우승 원고)**를 보강하여 체류시간과 광고 클릭률(CTR)을 동시에 끌어올린다.
"""
    (sb_dir / '02_채널별_승리공식_도감.md').write_text(_with_custom('02_채널별_승리공식_도감.md', doc_02), encoding='utf-8')

    # 4. 03_외부노하우_벤치마킹_금고.md
    knowhow_items = []
    for nid, node in sorted((editorial.get('nodes') or {}).items(), key=lambda x: str(x[1].get('recordedAt', '')), reverse=True):
        if usable_knowhow(node):
            knowhow_items.append(
                f"### 💡 {node.get('title', '')}\n"
                f"- **식별자**: `{nid}` · **기록 크루**: `@{node.get('recordedBy', 'radar')}` · **검증 상태**: `{node.get('measurementStatus', '')}`\n"
                f"- **출처**: {node.get('sourceUrl') or node.get('sourceType') or '내부 검증'}\n"
                f"- **핵심 실행 공략법 (Method)**:\n  > {node.get('method', '')}\n"
                f"- **언제 사용하는가 (When to Use)**: {node.get('whenToUse', '')}\n"
                f"- **팩트체크 요약**: {node.get('factCheckSummary', '')}"
            )
    knowhow_section = '\n\n'.join(knowhow_items[:15]) if knowhow_items else '- 아직 적재된 외부 노하우가 없습니다.'

    doc_03 = f"""---
name: external-knowhow-benchmark-vault
target_models: [claude-opus-4-6, gpt-5.4, gemini-3.1-pro]
hop_depth: 1
freedom_tier: medium-verified-knowhow
updated_at: "{now_kst}"
---
# 🔭 03. 외부 노하우 & 실전 벤치마킹 금고 (`@radar` 자율 학습 원장)

## 📑 목차 (Top-100-Line TOC — `head -n 100` 즉시 스캔용)
1. [NotebookLM 핵심 이식 #1: AI 업무 시스템 4단계 구축법 (SSR+)](#1-notebooklm-핵심-이식-1-ai-업무-시스템-4단계-구축법-ssr)
2. [NotebookLM 핵심 이식 #2: 앤트로픽 피셜 클로드 스킬 7대 공식 규칙](#2-notebooklm-핵심-이식-2-앤트로픽-피셜-클로드-스킬-7대-공식-규칙)
3. [레이더(`@radar`) 실시간 검증 외부 노하우 (`PracticalKnowHow`)](#3-레이더radar-실시간-검증-외부-노하우-practicalknowhow)
4. [자가 진화 피드백 루프 규칙 (Anthropic Rule #6)](#4-자가-진화-피드백-루프-규칙-anthropic-rule-6)
5. [대표님 & 크루 수동 추가 노트](#️-대표님--크루-수동-추가-노트)

---

## 1. NotebookLM 핵심 이식 #1: AI 업무 시스템 4단계 구축법 (SSR+)
- **출처**: `https://notebook.google.com/notebook/54a7fa66-ef38-4762-ab06-950264ca9c35`
- **4대 기둥 (SSR+ 프레임워크)**:
  1. **Skill (스킬)**: 반복 업무 절차를 매번 프롬프트로 설명하지 않고 모듈화된 스킬(`SKILL.md`)로 캡슐화하여 일관된 고품질을 보장한다.
  2. **Second Brain (세컨드 브레인)**: 나무위키식 **상위 길잡이 문서(Map of Content)**와 **1-Hop 마크다운 지식창고**를 구축하여 에이전트가 작업 전 맥락을 즉시 파악하게 한다.
  3. **Routine (루틴)**: 사람이 매번 실행 버튼을 누르지 않아도 24시간 데몬(`memory_worker` + `radar_scout` + `posting.py`)이 정해진 슬롯에 자율 구동한다.
  4. **Extension (확장)**: 브라우저 제어(CDP 9440), 검색어/경쟁자 스카우팅, 4대 포털 색인 API를 결합해 외부 세계와 직접 상호작용한다.

---

## 2. NotebookLM 핵심 이식 #2: 앤트로픽 피셜 클로드 스킬 7대 공식 규칙
- **출처**: `https://notebook.google.com/notebook/1d906519-a358-46fd-ba3f-93988489e66f`
1. **상단 100줄 목차(TOC) 필수**: 클로드/에이전트는 레퍼런스 파일을 읽을 때 상단 100줄(`head -n 100`)을 먼저 스캔하므로 모든 길잡이 문서 상단에 목차를 둔다.
2. **자유도 3단계 분리**: 창의적 글쓰기는 고자유도(High)로 풀어주고, 구조는 템플릿(Medium)으로, 깨지기 쉬운 검증/발행은 파이썬 스크립트(Low, 0 토큰)로 잠근다.
3. **최신 모델 눈높이 조율**: 프론티어 모델에게 구시대적 마이크로 제약을 걸면 오히려 공무원식 양산형 글이 나오므로 핵심 목표와 결핍 타격 원칙만 명확히 준다.
4. **1-Hop 직통 참조만 허용**: `SKILL.md -> A.md -> B.md` 다단계 참조는 에이전트가 길을 잃게 만든다. 반드시 루트에서 1-Hop으로 직접 연결한다.
5. **5단계 역방향 회귀 체크리스트**: 마지막 5단계에 *"기준 미달 시 3단계로 돌아가 재작성하라"*는 명시적 회귀 조건을 넣어야 품질이 폭발적으로 상승한다.
6. **자가 개선 루프 (Self-Improving Skill)**: 작업 중 발견한 새로운 승리 패턴이나 대표님 피드백을 길잡이 문서에 즉시 역반영한다.
7. **실행 환경/의존성 명시**: 스크립트 실행에 필요한 포트·경로·명령어를 문서 내에 명시한다.

---

## 3. 레이더(`@radar`) 실시간 검증 외부 노하우 (`PracticalKnowHow`)
{knowhow_section}

---

## 4. 자가 진화 피드백 루프 규칙 (Anthropic Rule #6)
- `@radar`가 외부 트렌드·SERP·유튜브에서 검증한 노하우는 `record_knowhow()` 호출과 동시에 SHA-256 영수증(`dashboard/data/radar/knowhow-receipts/`)으로 검증되며, 본 `03_외부노하우_벤치마킹_금고.md`와 `synapse-recipes.json`에 즉시 자동 동기화되어 전 크루의 다음 턴 프롬프트에 주입된다.
"""
    (sb_dir / '03_외부노하우_벤치마킹_금고.md').write_text(_with_custom('03_외부노하우_벤치마킹_금고.md', doc_03), encoding='utf-8')

    # 5. 04_실측우승원고_황금키워드.md
    rev_leaders = winning.get('revenueLeaders') or []
    rev_lines = []
    if isinstance(rev_leaders, list):
        for r in rev_leaders:
            if not isinstance(r, dict):
                continue
            cur = r.get('currency') or 'USD'
            yest = r.get('yesterdayAmount') or 0
            cum = r.get('cumulativeAmount') or 0
            unit = f"\\${yest:,.2f} (누적 \\${cum:,.2f})" if cur == 'USD' else f"{int(yest):,}원 (누적 {int(cum):,}원)"
            rev_lines.append(f"- **{r.get('label', r.get('category', '채널'))}**: 어제 실측 **{unit}** · 최근 수집 `{r.get('lastCollectedAt') or '-'}`")
    rev_md = '\n'.join(rev_lines) if rev_lines else '- 집계된 수익 리더 데이터가 없습니다.'

    winners_rows = []
    for idx, w in enumerate((winning.get('provenTrafficWinners') or [])[:12], 1):
        title_str = str(w.get('title') or w.get('slugTopic') or w.get('url') or '').replace('|', '·')[:46]
        pv_val = w.get('pageViews') or 0
        sess_val = w.get('sessions') or 0
        clk_val = w.get('clicks') or 0
        imp_val = w.get('impressions') or 0
        traffic_desc = f"PV `{pv_val}` · 세션 `{sess_val}`" if pv_val else f"클릭 `{clk_val}` · 노출 `{imp_val}`"
        winners_rows.append(
            f"| {idx} | `{w.get('domain', '')}` | {title_str} | `{w.get('source', 'ga4')}` | {traffic_desc} | `{w.get('url', '')}` |"
        )
    winners_table = '\n'.join(winners_rows) if winners_rows else '| - | - | 관측된 우승 원고 없음 | - | - | - |'

    doctor_rows = []
    for idx, t in enumerate((winning.get('doctorCtrRemodelTargets') or [])[:8], 1):
        title_str = str(t.get('title') or t.get('slugTopic') or t.get('url') or '').replace('|', '·')[:44]
        action_str = str(t.get('prescribedFix') or t.get('doctorAction') or '자청 4대 결핍 제목 + 3초 요약표 보강')
        doctor_rows.append(
            f"| {idx} | `{t.get('domain', '')}` | {title_str} | 노출 `{t.get('impressions', 0)}` / 클릭 `{t.get('clicks', 0)}` (CTR `{t.get('ctrPct', 0)}%`) | {action_str} |"
        )
    doctor_table = '\n'.join(doctor_rows) if doctor_rows else '| - | - | 현재 CTR 긴급 수선 대상 없음 | - | - |'

    golden_rows = []
    for idx, g in enumerate((winning.get('goldenKeywords') or [])[:12], 1):
        golden_rows.append(
            f"| {idx} | **{g.get('keyword', '')}** | `{g.get('grade', 'A')}급` | 검색량 `{g.get('monthlySearch', 0):,}` / 문서수 `{g.get('blogTotal', 0):,}` (황금지수 `{g.get('saturation', 0)}`) | `{g.get('recommendedChannel', 'cf+naver')}` |"
        )
    golden_table = '\n'.join(golden_rows) if golden_rows else '| - | 발굴된 황금키워드 없음 | - | - | - |'

    doc_04 = f"""---
name: live-traffic-winners-and-golden-keywords
target_models: [claude-opus-4-6, gpt-5.4, gemini-3.1-pro]
hop_depth: 1
freedom_tier: low-data-grounded
updated_at: "{now_kst}"
---
# 📈 04. 실측 우승 원고 & 블로키 S/A급 황금키워드 뱅크

## 📑 목차 (Top-100-Line TOC — `head -n 100` 즉시 스캔용)
1. [실시간 수익 리더보드 (AdSense & AdPost 실측)](#1-실시간-수익-리더보드-adsense--adpost-실측)
2. [실측 유입·수익 우승 원고 Top 12 (확장·외부유입 브릿지 1순위)](#2-실측-유입수익-우승-원고-top-12-확장외부유입-브릿지-1순위)
3. [닥터(`@doctor`) CTR 0% 긴급 리모델링 타깃 리스트](#3-닥터doctor-ctr-0-긴급-리모델링-타깃-리스트)
4. [블로키(Blokey) 실측 S/A급 빈집 황금키워드 Top 12](#4-블로키blokey-실측-sa급-빈집-황금키워드-top-12)
5. [대표님 & 크루 수동 추가 노트](#️-대표님--크루-수동-추가-노트)

---

## 1. 실시간 수익 리더보드 (AdSense & AdPost 실측)
{rev_md}

---

## 2. 실측 유입·수익 우승 원고 Top 12 (확장·외부유입 브릿지 1순위)
> **활용 지침**: `@publi`와 `@jarvis`는 아래 우승 원고의 주제·표 구조·결핍 타격 각도를 인접 키워드로 수평 복제하고, `지식iN`·`Threads`의 최우선 착지 URL(Bridge Target)로 사용한다.

| 순위 | 도메인 | 우승 원고 주제/슬러그 | 측정 출처 | 실측 트래픽 (GA4/GSC) | 공개 URL |
| :---: | :--- | :--- | :---: | :--- | :--- |
{winners_table}

---

## 3. 닥터(`@doctor`) CTR 0% 긴급 리모델링 타깃 리스트
> **활용 지침**: 검색 노출(`Impressions`)은 이미 확보되었으나 제목/도입부 후킹 부족으로 클릭이 새고 있는 금맥이다. 제목 숫자 후킹 + 3초 요약표 수선 시 즉각적인 PV 상승이 발생한다.

| 순위 | 도메인 | 대상 원고 주제/슬러그 | 노출 / 클릭 (CTR) | 처방 액션 |
| :---: | :--- | :--- | :--- | :--- |
{doctor_table}

---

## 4. 블로키(Blokey) 실측 S/A급 빈집 황금키워드 Top 12
> **활용 지침**: 월간 검색량은 높고 블로그 문서수(경쟁도)는 낮은 실측 빈집 키워드다. CF 본진과 네이버 주력 계정에 동시 배정한다.

| 순위 | 황금 키워드 | 등급 | 월간 검색량 / 문서수 (황금지수) | 권장 배정 채널 |
| :---: | :--- | :---: | :--- | :--- |
{golden_table}
"""
    (sb_dir / '04_실측우승원고_황금키워드.md').write_text(_with_custom('04_실측우승원고_황금키워드.md', doc_04), encoding='utf-8')
    return {'ok': True, 'updatedAt': now_kst, 'directory': str(sb_dir)}


def seed_notebooklm_official_knowhow(root=None):
    """Ensure both NotebookLM sources (SSR+ Second Brain & Anthropic 7 Official Skill Rules) are cleanly recorded in UTF-8."""
    from pathlib import Path
    from common.collection_observability import load, write, locked
    root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    data = root / 'dashboard/data'
    path = data / 'editorial-memory-graph.json'
    with locked(data):
        graph = load(path) or {'nodes': {}, 'edges': []}
        bad_keys = [k for k, v in (graph.get('nodes') or {}).items() if '\ufffd' in str(v.get('title', '')) or '\ufffd' in str(v.get('method', ''))]
        for k in bad_keys:
            graph['nodes'].pop(k, None)
        write(path, graph)

    r1 = record_knowhow(
        title='[NotebookLM·SSR+] 나만의 AI 업무 시스템 4단계(Skill·Second Brain·Routine·Extension) 구축법',
        method='1) Skill: 반복 업무를 모듈화하여 프롬프트 재입력 제거. 2) Second Brain: 나무위키식 상위 길잡이 문서(Map of Content)와 1-Hop 마크다운 지식창고로 에이전트에게 문맥과 대표 철학을 즉시 주입. 3) Routine: 24/7 백그라운드 워커로 자율 실행. 4) Extension: 브라우저(CDP)·검색·발행 도구로 외부 세계와 연결.',
        when_to_use='전 크루가 자율 업무를 수행하거나 새로운 도메인/채널 지식을 구조화할 때 1-Hop 길잡이 문서를 최우선 참조',
        fact_check_summary='NotebookLM(54a7fa66-ef38-4762-ab06-950264ca9c35) 클로드 AI 업무 시스템 4단계(SSR+) 원본 분석 및 BaroLab 아키텍처 대조 검증 완료',
        source_url='https://notebook.google.com/notebook/54a7fa66-ef38-4762-ab06-950264ca9c35',
        source_type='ceo_notebooklm_verified',
        tags=['세컨드브레인', 'SSR+', '길잡이문서', '1-Hop'],
        recorded_by='jarvis',
    )
    r2 = record_knowhow(
        title='[Anthropic 공식] 클로드 스킬(SKILL.md) 설계 7대 최신 규칙 & 5단계 역방향 회귀 루프',
        method='1) 100줄 이상 레퍼런스 문서 최상단에 목차(TOC) 배치(head -n 100 스캔 대응). 2) 자유도 3단 분리: 설득/글쓰기는 고자유도(High), 비교표/요약박스는 중자유도(Medium), 발행/검증은 파이썬 스크립트(Low, 0토큰)로 잠금. 3) 루트에서 1-Hop 직통 참조만 허용. 4) 5단계 체크리스트의 마지막 5단계에 구체적 수치/비교표 누락 또는 공무원식 회피 문구 발견 시 즉시 3단계로 되돌아가 재작성(Go-Back Loop) 강제.',
        when_to_use='모든 채널 원고 집필(@publi), CTR 리모델링(@doctor), 지식iN/Threads 외부유입 브릿지 작성 및 SKILL.md 업데이트 시 필수 적용',
        fact_check_summary='NotebookLM(1d906519-a358-46fd-ba3f-93988489e66f) 앤트로픽 공식 스킬 제작 7대 규칙 원본 대조 및 검증 완료',
        source_url='https://notebook.google.com/notebook/1d906519-a358-46fd-ba3f-93988489e66f',
        source_type='ceo_notebooklm_verified',
        tags=['앤트로픽7규칙', 'TOC목차', '3단자유도', '5단계회귀체크리스트'],
        recorded_by='jarvis',
    )
    sync_second_brain_guides(root)
    return {'ok': True, 'r1': r1['id'], 'r2': r2['id']}


def get_second_brain_explorer_data(root=None, q=''):
    """Return the full 1-Hop Second Brain tree, TOC headings, and markdown bodies for the Explorer UI."""
    import datetime as dt
    import hashlib
    from pathlib import Path

    root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    sb_dir = root / 'dashboard/data/second_brain'
    if not sb_dir.is_dir() or not list(sb_dir.glob('*.md')):
        sync_second_brain_guides(root)

    files_meta = [
        ('00_INDEX_세컨드브레인_길잡이.md', '🧭 00. 세컨드 브레인 1-Hop 마스터 길잡이', 'index_moc', 'High/Medium/Low 통합', 'hubs/crew-jarvis'),
        ('01_CEO_철학_자청4대결핍.md', '👑 01. CEO 북극성 철학 & 자청 4대 결핍 바이블', 'ceo_philosophy', 'High (창의·설득 해방)', 'hubs/crew-jarvis'),
        ('02_채널별_승리공식_도감.md', '🛠️ 02. 멀티채널 승리 공식 & 3단 자유도 도감', 'channel_playbook', 'Medium (구조 템플릿)', 'hubs/crew-publi'),
        ('03_외부노하우_벤치마킹_금고.md', '🔭 03. 외부 노하우(SSR+·앤트로픽 7규칙) 금고', 'external_knowhow', 'Medium (검증 노하우)', 'hubs/crew-radar'),
        ('04_실측우승원고_황금키워드.md', '📈 04. 실측 우승 원고 & 황금키워드 뱅크', 'live_winners', 'Low (실측 데이터 앵커)', 'hubs/crew-trace'),
    ]

    skill_files = [
        (root / 'dashboard/agents/skills/anti-hallucination-grounding/SKILL.md', '🛡️ SKILL: 환각 방지 & CoVe 4단계 팩트체크', 'official_skill', 'Low (엄격 팩트 검증)', 'hubs/crew-doctor'),
        (root / 'dashboard/agents/skills/seo-marketing-master/SKILL.md', '🚀 SKILL: 4대 검색엔진 색인·마케팅 마스터', 'official_skill', 'Medium (채널 표준)', 'hubs/crew-trace'),
        (root / 'dashboard/data/knowledge/skills/channel-verification/SKILL.md', '✅ SKILL: 채널별 발행·예약·검증 영수증 표준', 'official_skill', 'Low (파이썬 스크립트 잠금)', 'hubs/crew-patch'),
        (root / 'dashboard/data/knowledge/skills/evidence-first-repair/SKILL.md', '🔧 SKILL: 증거 기반 최소 범위 수선(Repair)', 'official_skill', 'Low (무결성 수선)', 'hubs/crew-patch'),
    ]

    items = []
    q_low = str(q or '').strip().lower()

    for fname, label, group, freedom, owner_hub in files_meta:
        fpath = sb_dir / fname
        if not fpath.is_file():
            continue
        content = fpath.read_text(encoding='utf-8')
        if q_low and q_low not in content.lower() and q_low not in label.lower():
            continue
        toc = _parse_toc_headings(content)
        stat = fpath.stat()
        items.append({
            'id': f'second_brain/{fname}',
            'filename': fname,
            'title': label,
            'group': group,
            'groupLabel': '1-Hop 세컨드 브레인 길잡이',
            'freedomTier': freedom,
            'hopDepth': 1,
            'ownerHub': owner_hub,
            'editable': True,
            'updatedAt': dt.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            'sizeBytes': stat.st_size,
            'lineCount': len(content.splitlines()),
            'revision': hashlib.sha256(content.encode('utf-8')).hexdigest()[:16],
            'toc': toc,
            'top100Preview': '\n'.join(content.splitlines()[:100]),
            'content': content,
        })

    for spath, label, group, freedom, owner_hub in skill_files:
        if not spath.is_file():
            continue
        content = spath.read_text(encoding='utf-8')
        if q_low and q_low not in content.lower() and q_low not in label.lower():
            continue
        toc = _parse_toc_headings(content)
        stat = spath.stat()
        rel_id = f'skill/{spath.parent.name}'
        items.append({
            'id': rel_id,
            'filename': f'{spath.parent.name}/SKILL.md',
            'title': label,
            'group': group,
            'groupLabel': '앤트로픽 7규칙 공식 스킬 (SKILL.md)',
            'freedomTier': freedom,
            'hopDepth': 1,
            'ownerHub': owner_hub,
            'editable': True,
            'updatedAt': dt.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'),
            'sizeBytes': stat.st_size,
            'lineCount': len(content.splitlines()),
            'revision': hashlib.sha256(content.encode('utf-8')).hexdigest()[:16],
            'toc': toc,
            'top100Preview': '\n'.join(content.splitlines()[:100]),
            'content': content,
        })

    return {
        'ok': True,
        'architecture': 'SSR+ Second Brain & Anthropic 7-Rule 1-Hop Guides',
        'totalCount': len(items),
        'guides': items,
    }


def save_second_brain_document(doc_id, content, root=None):
    """Save edits to a 1-Hop Second Brain guide or official SKILL.md file."""
    import hashlib
    from pathlib import Path
    root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
    doc_id = str(doc_id or '').strip()
    content = str(content or '')
    if not content.strip() or len(content) > 200_000:
        raise ValueError('문서 본문이 비어 있거나 허용 크기를 초과했습니다.')

    allowed_sb = {
        'second_brain/00_INDEX_세컨드브레인_길잡이.md': root / 'dashboard/data/second_brain/00_INDEX_세컨드브레인_길잡이.md',
        'second_brain/01_CEO_철학_자청4대결핍.md': root / 'dashboard/data/second_brain/01_CEO_철학_자청4대결핍.md',
        'second_brain/02_채널별_승리공식_도감.md': root / 'dashboard/data/second_brain/02_채널별_승리공식_도감.md',
        'second_brain/03_외부노하우_벤치마킹_금고.md': root / 'dashboard/data/second_brain/03_외부노하우_벤치마킹_금고.md',
        'second_brain/04_실측우승원고_황금키워드.md': root / 'dashboard/data/second_brain/04_실측우승원고_황금키워드.md',
        'skill/anti-hallucination-grounding': root / 'dashboard/agents/skills/anti-hallucination-grounding/SKILL.md',
        'skill/seo-marketing-master': root / 'dashboard/agents/skills/seo-marketing-master/SKILL.md',
        'skill/channel-verification': root / 'dashboard/data/knowledge/skills/channel-verification/SKILL.md',
        'skill/evidence-first-repair': root / 'dashboard/data/knowledge/skills/evidence-first-repair/SKILL.md',
    }
    target = allowed_sb.get(doc_id)
    if target is None:
        raise ValueError('허용되지 않은 세컨드 브레인 문서 ID입니다.')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    return {
        'ok': True,
        'id': doc_id,
        'revision': hashlib.sha256(content.encode('utf-8')).hexdigest()[:16],
        'lineCount': len(content.splitlines()),
    }

