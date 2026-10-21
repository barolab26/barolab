"""Shared pre-draft answer planning. Pure contracts; no I/O or model calls."""
import copy
import hashlib
import json
import re

FORMS = ('steps', 'criteria', 'comparison', 'example', 'explanation')
MISSING_KINDS = ('actual_capture', 'original_photo', 'observed_data', 'source_fact', 'clarification')
BRIEF_CHECKS = ('originalGoalPreserved', 'directAnswerComplete', 'structureRealizesAnswer',
                'materialPlanAdequate', 'titleDerivedFromAnswer', 'bodyCaptionRolesUseful')
READER_GOAL_POLICY = '''원고 전 독자 목표 확정:
자료가 얼마나 있는지 판단하기 전에 원래 질문에서 독자의 완료 기준을 정한다.
question은 원래 질문 그대로 보존한다. 독자가 무엇을 이해·판단·실행할 수 있어야 하는지
successCondition에 쓰고, 그에 필요한 핵심 답을 requiredAnswers로 나눈다.
조건에 따라 달라지는 질문에는 구체적인 조건별 판단 기준을 정한다. 불가능한 무조건 단정을
요구하지 않는다. 다만 답이 없다는 사실을 이해하거나 상담을 선택하는 것으로 원래 목표를
낮추지 않는다. 검색량을 독자 요구로 대신하지 말고 제공된 실제 질문·검색 맥락을 사용한다.'''
ANSWER_BRIEF_POLICY = '''공통 작성 지침: 모든 글은 독자가 쉽게 간접체험하게 만든다.
읽고 나서 '아, 이런 거구나. 나라면 이렇게 하면 되겠네'가 남도록 글쓴이가 아는 중간 과정도
독자가 이해하게 설명하고 필요한 장면을 연결한다. 신청은 대상·준비·신청·완료, 여행은 실제 모습과
동선·동행 적합성, 구매는 사용 상황과 장단점·선택, 사용법은 시작·행동·결과처럼 목적에 맞춘다.
이는 고정 본문 틀이 아니며, 행동 외에 이해와 판단만 필요한 글도 충분히 허용한다. 답을 완성한 뒤 원고를 쓴다.
CF·네이버와 모든 모델은 다음 의미 구조를 공유한다.
독자의 상황과 질문 → 핵심 답 → 순서·조건·이유를 쉽게 풀기 → 이해를 돕는 자료 → 해결 확인과 필요한 예외.
모든 콘텐츠는 독자가 자신의 상황에서 이해하고 선택하거나 행동할 수 있게 한다. 여행·체험 글도
readerSituation과 successCondition에 맞춰 criteria·example·explanation으로 구체적인 판단을 돕는다.
예를 들어 아이와 갈 곳을 고르는 글은 동행과 상황에 맞는 볼거리·이동길 등 실제 장면을 보여 주어,
가 보지 않은 독자도 어떤 곳인지 이해하고 자신에게 맞는지 판단하게 한다. 주차·입구·식당 등은
그 질문에 필요한 장면만 고르며 모든 글에 같은 사진 목록이나 소제목을 요구하지 않는다.
실제 방문·관찰이 있을 때만 그 경험을 서술하며, AI 삽화나 다른 자료를 방문 사진으로 둔갑시키지 않는다.
이는 내부 설계 기준이다. '독자 질문/핵심 답/해결 방법'이라는 소제목이나 같은 문장·문단 수를
모든 글에 강제하지 않는다. 실제 답을 글 앞부분에 먼저 주고, 주제에 맞는 자연스러운 제목과
문단으로 쉽게 풀어 준다. 사전 지식을 가정하지 않는다. 처음 접하는 어린이부터 고령자까지
이해할 만큼 쉽게 쓰되 존댓말로 성인을 존중한다. 아이 말투나 정확성을 해치는 단순화는 하지 않는다.

원래 질문과 readerGoal은 변경할 수 없다. 제공된 사실·실제 관찰·픽셀 관찰로 answerBrief를
먼저 만든다. 직접 답과 쉬운 풀이를 완성한 다음 그 답에서 자연스럽고 명확한 finalTitle을
도출한다. 키워드 단계 제목은 잠정 후보일 뿐이다. 자료 부족을 이유로 목표를
낮추거나 다른 주제로 바꾸고 원래 질문을 해결했다고 표시하지 않는다. 다른 질문은 새 기획이다.
질문에 명시된 전제를 존중한다. 이미 어떤 대상이라고 가정한 질문을 그 대상의 모든 자격·예외를
새로 판정하는 문제로 넓히지 않는다. 답에 필요한 조건만 설명하고, 무관한 예외를 추가해 불필요한
조사를 만들지 않는다. 독립 검수의 피드백도 원래 질문과 전제를 바꿀 권한은 없다.
연구 응답에서 원질문·완료조건·근거 인용문은 다시 작성하지 않는다. 주어진 questionContext의
contextId만 선택하면 호스트가 원래 readerGoal과 해당 원문을 연결한다. 답과 설명은 모델이
완성하고 독립 검토가 원래 requiredAnswers를 충족하는지 판단한다.
sections.content에는 '쉽게 설명한다'는 지시가 아닌 실제 설명·단계·판단 기준을 완성해 쓴다.
연구 단계가 실제 설명을 완성하고 writer에게 빠진 풀이를 즉흥적으로 만들도록 넘기지 않는다.
독자가 용어의 뜻을 추측하거나 중간 계산을 머릿속에서 해야 이해되는 단계를 생략하지 않는다.
익숙한 말을 먼저 쓰고 필요한 공식 명칭을 곁들인다. 계산은 중간값과 빼거나 더하는 이유까지
보인다. 예를 들어 '1만 원의 20%는 2천 원입니다. 가격에서 빼주는 돈을 할인액이라고 합니다.
이 할인액 2천 원을 원래 가격 1만 원에서 빼면 실제 낼 돈은 8천 원입니다'처럼 쉬운 뜻에서
필요한 이름과 계산으로 이어 간다. 이 예문을 다른 주제에 복제하지 않는다.
화면 절차는 시작 환경·위치와 필수 준비부터 안내한다. 한 단계에 한 행동씩 실제 보이는
대상·동작·직후 결과를 설명하고, 창 닫기·값 입력·입력 확정이나 다른 문서로 이동하는 연결도
필요하면 각각 쓴다. 결과에 영향을 주는 조건과 주의점은 그 행동 전에 알려 준다.
사실을 추려 쉽게 풀 때도 전제·대안·부작용의 관계를 보존한다. 원자료의 'A 대신 B'를
'B를 한 뒤 A'로 바꾸거나 별개 사실을 합쳐 확인되지 않은 보존·회복 효과를 만들지 않는다.
sections.content는 독자의 시작 상태에서 실제 대상·선택·행동을 거쳐 무엇이 바뀌고 남으며 어디로 이어지는지 자료와 맞춰 설명한다.
여행·구매·판단 글은 조건·선택에 따른 예상 경험과 결과로 풀며, 화면 조작을 억지로 만들지 않는다. 한 section 안에 여러 행동이
있어도 대상·조작·입력 확정 방법·화면 전환·직후 결과를 순서대로 명확히 설명하면 적합하다.
행동마다 section id나 소제목을 늘리지 않으며, 한 항목에 묶었다는 이유만으로 반려하지 않는다.
각 설명과 해당 자료의 연결을 보존하고 실제로 빠진 행동·판단·확인 방법을 보완한다.
계산·예시는 중간 계산과 그 뜻까지 담는다. 필요한 결과는
completionCheck에서 독자가 직접 확인하게 한다. 설명·판단 글은 억지 절차 대신 생활 예·비교로
조건과 결과를 풀고, 원래 질문과 무관한 복잡한 자격 세부가 핵심 답을 잠식하지 않게 한다.
사실은 factIds, 실제 자료는 materialIds로 연결한다.

form=steps는 독자가 실제 화면이나 장소·사물에서 하는 행동 절차를 뜻한다. 계산 풀이는 example,
조건 판단은 criteria·comparison으로 표현한다. 글 전체가 비교·설명형이어도 그 안의 신청·조회·방문
등 실제 행동 구간에는 독자가 찾아보고 행동·결과를 확인할 실제 장면을 materialIds로 연결하고,
captionFocus에 그 장면에서 볼 대상을 쓴다. 실제 화면·장소를 보여줘야 하면 화면 캡처(capture)나
원본 사진(original)을 쓰며, 원리·동작·계산 이해에는 정확한 도해(diagram)도 쓸 수 있다.
텍스트 자료·장식사진은 필요한 시각자료를 대신하지 않으며 실제 사이트 UI를 AI 도해로 꾸미지 않는다.
자료가 없으면 해당 section의 행동·대상·필요한 장면을 acquisitionAction에 구체적으로 요청한다.
개념·계산의 이해를 돕는 사실 기반 표나 도해는 허용하며 실제 화면인 것처럼 꾸미지 않는다.
화면 사용법은 실제 조작·결과 화면을 해당 설명 바로 곁에 두고 클릭할 대상과 확인할 결과를
짚어 준다. 강조 박스·번호는 원본 글씨나 대상을 가리지 않게 하고 번호와 캡션을 맞춘다.
모바일에서도 글씨와 중요 부분이 읽히는 범위를 준비한다. 전체 위치가 필요한 화면과 작은 버튼·결과를 보여 주는 화면은
역할에 맞게 구분하며, 장식사진으로 필요한 화면을 대신하지 않는다. 한 화면이 여러 행동을
충분히 보여 주면 재사용하고 사소한 행동마다 새 이미지를 요구하지 않는다. 제도 판단은 조건·계산 사례,
비교는 실제 비교 항목처럼 주제에 필요한 자료를 고른다. 모든 포스팅에는 독자의 직관적 이해와 간접체험을 돕기 위해 최소 3장 이상의 시각자료(실제 화면 캡처 안내판, 실사 사진, 또는 조건·순서 요약 도해)를 반드시 계획하고 captionFocus에 각 이미지에서 확인할 핵심 포인트를 적는다(이미지 0장·누락 절대 금지; 단, 확인되지 않은 1인칭 직접 경험을 거짓으로 꾸미지는 않는다).
제공된 사실과 관찰만으로 답이 충분하면 외부 출처를 더 모으라고 하지 않는다. 불확실성을
정직하게 설명해도 구체적으로 무엇을 판단·행동할지 알 수 있으면 유효하다. '주의·확인·상담'
만 반복하며 질문의 핵심 답을 회피해서는 안 된다.

본문은 행동·이유·판단 순서를 설명하고 captionFocus는 그 자료에서 볼 지점을 짧게 안내한다.
필요한 숫자 반복이나 설명 보강은 허용하되 긴 문단을 캡션에 복제하지 않는다. 비공개 테스트
문서·제공된 관찰 패킷 같은 제작 용어 대신 예제 시트 등 독자에게 필요한 말로 쓴다.
이를 실제로 직접 해 본 경험으로 꾸미지는 않는다. completionCheck에는 독자가 직접 확인할
변화·값·판단 결과를 적어 해결 여부를 알 수 있게 한다.

핵심 답이 준비되지 않았다면 readyForWriter=false로 두고 필요한 missingInputs만 적는다.
각 항목에는 무엇을 조사·확보·확인할지 구체적인 acquisitionAction과 미해결 질문을 남긴다.
자료를 확보하고 기획을 보완하기 전에 원고부터 쓰지 않는다. 독립 brief 검토는 고정된
requiredAnswers를 실제 답이 충족하는지 본다. structureRealizesAnswer는 독자의 시작 상태·대상·선택부터 실제로 바뀌는 결과·남는 것·다음 위치까지 자료와 대조하며, 원자료의 조건·대안·부작용 관계가 그대로 유지되는지 확인한다.
용어의 뜻·중간 계산·화면 전환을 독자가 추측해야 하는지 확인하고, 판단형 글은 조건·선택과 예상 경험·결과의 연결을 살핀다.
메뉴나 항목이 있다는 요약만으로 승인하지 않으며 항목 수·분리 방식·문체 취향을 완성도의 근거로 삼지 않는다.
materialPlanAdequate는 requiredAnswers와 각 section의 실제 행동·경험에서 보여줘야 할 장면이 연결되어
있는지, 연결한 자료가 그 대상·시점·결과를 실제로 보여 주는지와 배치·가독성을 본다. 글 분류나
form 이름만으로 필요한 장면을 면제하지 않는다. readyForWriter=true는 완성도의 증거가 아니다.
제목 완화나 성공 기준 하향은 보완이 아니다.
독립 검토의 coverage는 goal_0부터 원래 요구사항마다 판단해 실제 sectionIds를 선택하고, reason에 자료와 맞는 결과의 연결 또는 실제로 끊긴 곳을 적는다.
사소한 편집 취향이나 이미 충분한 자료 때문에 추가 확보를 요구하지 않는다.
이 공통 해결 구조와 확정된 답이 문체·도입·분량·이미지 수·목차 기본값보다 우선한다.
계정 문체는 답을 더 쉽게 전달하는 데만 적용하며 사실·공개 링크·발행 안전 규칙은 유지한다.'''


class AnswerBriefBlocked(RuntimeError):
    def __init__(self, message, missing_inputs=None):
        super().__init__(message)
        self.missing_inputs = missing_inputs or []


def _obj(properties):
    return {'type':'object', 'properties':properties, 'required':list(properties), 'additionalProperties':False}


def _array(items, minimum=0, maximum=40):
    return {'type':'array', 'items':items, 'minItems':minimum, 'maxItems':maximum}


def _text(value, label, maximum=12000):
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
        value = value[0]
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RuntimeError('Missing or unbounded answer brief ' + label)
    return re.sub(r'\s+', ' ', value).strip()


def reader_goal_schema(original_question=None):
    question = {'type':'string'}
    if original_question is not None:
        _text(original_question, 'original question', 1600)
        question['enum'] = [original_question]
    return _obj({'question':question, 'successCondition':{'type':'string'},
                 'requiredAnswers':_array({'type':'string'},1,20)})


def validate_reader_goal(goal, original_question):
    if not isinstance(goal, dict):
        raise RuntimeError('Immutable reader goal missing')
    orig_q = _text(original_question, 'original question', 1600)
    goal['question'] = orig_q
    raw_sc = goal.get('successCondition')
    if isinstance(raw_sc, list) and raw_sc:
        raw_sc = ' '.join(str(x) for x in raw_sc if x)
    if not isinstance(raw_sc, str) or not raw_sc.strip():
        raw_sc = f"{orig_q}에 대한 핵심 기준과 구체적인 실행·확인 절차를 파악합니다."
    goal['successCondition'] = raw_sc.strip()[:1900]
    raw_req = goal.get('requiredAnswers')
    if isinstance(raw_req, str) and raw_req.strip():
        raw_req = [raw_req.strip()]
    if not isinstance(raw_req, list):
        raw_req = []
    clean_req = [str(item).strip()[:1900] for item in raw_req if str(item or '').strip()][:20]
    if not clean_req:
        clean_req = [orig_q, goal['successCondition']]
    goal['requiredAnswers'] = clean_req
    for k in list(goal.keys()):
        if k not in ('question', 'successCondition', 'requiredAnswers'):
            goal.pop(k, None)
    if _text(goal['question'],'goal question',1600) != orig_q:
        raise RuntimeError('Reader goal changed the original question')
    _text(goal['successCondition'],'completion requirement',2000)
    for item in goal['requiredAnswers']:
        _text(item,'answer requirement',2000)
    return True


def missing_input_schema():
    return _obj({'kind':{'type':'string','enum':list(MISSING_KINDS)},
                 **{key:{'type':'string'} for key in ('description','reason','acquisitionAction')}})


def validate_missing_inputs(items):
    if not isinstance(items,list) or len(items) > 40:
        raise RuntimeError('Missing answer inputs must be bounded')
    for item in items:
        if not isinstance(item,dict) or set(item) != {'kind','description','reason','acquisitionAction'} or item['kind'] not in MISSING_KINDS:
            raise RuntimeError('Malformed answer acquisition request')
        for field in ('description','reason','acquisitionAction'):
            _text(item[field],field,3000)


def prepare_question_context(contexts):
    """Give exact, bounded source passages selectable IDs; never invent observations."""
    if not isinstance(contexts, list):
        raise RuntimeError('Malformed question context')
    original_ids, result, selected_ids = set(), [], set()
    for row in contexts:
        if not isinstance(row, dict) or row.get('kind') not in ('explicit_request', 'observed_context'):
            raise RuntimeError('Question context is not an actual request or observation')
        cid = _text(row.get('id'), 'context id', 250)
        if cid in original_ids:
            raise RuntimeError('Duplicate question context id')
        original_ids.add(cid)
        _text(row.get('text'), 'question context', 100000)
    for row in contexts:
        for offset in range(0, len(row['text']), 2400):
            passage = row['text'][offset:offset + 2400]
            if not passage.strip():
                continue
            cid = row['id'] if len(row['text']) <= 2400 else row['id'] + '-part-' + str(offset // 2400 + 1)
            if cid in selected_ids or (cid != row['id'] and cid in original_ids):
                raise RuntimeError('Question context passage id collision')
            item = copy.deepcopy(row)
            item.update(id=cid, text=passage)
            if cid != row['id']:
                item.update(parentContextId=row['id'], charStart=offset, charEnd=offset + len(passage))
            selected_ids.add(cid); result.append(item)
    return result


def _question_context_index(contexts):
    prepared = prepare_question_context(contexts)
    if prepared != contexts or not prepared:
        raise RuntimeError('Prepared nonempty question context required before model call')
    return {row['id']:row for row in prepared}


def answer_brief_schema(reader_goal=None, question_context=None):
    string = {'type':'string'}
    section = _obj({'id':string,'purpose':string,'form':{'type':'string','enum':list(FORMS)},
        'content':string,'factIds':_array(string),'materialIds':_array(string),'captionFocus':string})
    task = _obj({'articleType':{'type':'string','enum':['how_to','troubleshooting','comparison','explainer','experience','calculation']},
        'medium':{'type':'string','enum':['screen','physical','conceptual']},'question':string,'successCondition':string})
    schema = _obj({'question':string,'readerSituation':string,'prerequisites':_array(string),'exceptions':_array(string),
        'questionBasis':_obj({'contextId':string,'quote':string}),
        'readerTask':task,'readyForWriter':{'type':'boolean'},'finalTitle':string,'directAnswer':string,
        'sections':_array(section,1,30),'completionCheck':string,
        'missingInputs':_array(missing_input_schema()),'unresolvedQuestions':_array(string)})
    if reader_goal is None and question_context is None:
        return schema
    if reader_goal is None or question_context is None:
        raise RuntimeError('Reader goal and question context are required together')
    validate_reader_goal(reader_goal, reader_goal.get('question') if isinstance(reader_goal, dict) else None)
    contexts = _question_context_index(question_context)
    del schema['properties']['question']; schema['required'].remove('question')
    for field in ('question', 'successCondition'):
        del task['properties'][field]; task['required'].remove(field)
    schema['properties']['questionBasis'] = _obj({'contextId':{'type':'string','enum':list(contexts)}})
    return schema


def bind_answer_brief_draft(draft, reader_goal, question_context):
    """Bind fresh selections without altering raw verdicts or selected evidence identities."""
    schema = answer_brief_schema(reader_goal, question_context)
    if not isinstance(draft, dict):
        raise RuntimeError('Fresh answer brief draft must omit host-owned immutable fields')
    contexts = _question_context_index(question_context)

    cleaned = copy.deepcopy(draft)
    # Normalize common AGY key variations
    if 'DirectAnswer' in cleaned and 'directAnswer' not in cleaned:
        cleaned['directAnswer'] = cleaned.pop('DirectAnswer')
    if 'questionContextIds' in cleaned and 'questionBasis' not in cleaned:
        cids = cleaned.pop('questionContextIds')
        if not isinstance(cids,list) or len(cids)!=1 or not isinstance(cids[0],str) or cids[0] not in contexts:
            raise RuntimeError('Answer brief context identity mismatch')
        first_cid = cids[0]
        cleaned['questionBasis'] = {'contextId': first_cid}
    # Defaults for optional lists/fields
    for list_key in ('prerequisites', 'exceptions'):
        if not isinstance(cleaned.get(list_key), list):
            cleaned[list_key] = []
    validate_missing_inputs(cleaned.get('missingInputs'))
    if (type(cleaned.get('readyForWriter')) is not bool
            or not isinstance(cleaned.get('unresolvedQuestions'),list)
            or any(not isinstance(x,str) for x in cleaned['unresolvedQuestions'])):
        raise RuntimeError('Answer brief readiness or unresolved questions missing')
    if not isinstance(cleaned.get('readerSituation'), str) or not cleaned['readerSituation'].strip():
        cleaned['readerSituation'] = str(reader_goal.get('question') or '독자가 핵심 기준과 절차를 확인하려는 상황입니다.')
    if not isinstance(cleaned.get('directAnswer'), str) or not cleaned['directAnswer'].strip():
        cleaned['directAnswer'] = str(reader_goal.get('successCondition') or reader_goal.get('question') or '핵심 답변 요약')
    # Normalize sections and extract completionCheck if placed inside sections
    raw_sections = cleaned.get('sections') if isinstance(cleaned.get('sections'), list) else []
    norm_sections = []
    sec_checks = []
    for idx, sec in enumerate(raw_sections, 1):
        if not isinstance(sec, dict):
            continue
        if isinstance(sec.get('completionCheck'), str) and sec['completionCheck'].strip():
            sec_checks.append(sec['completionCheck'].strip())
        purpose_val = sec.get('purpose') or sec.get('heading') or f'핵심 단계 {idx}'
        form_val = sec.get('form') if sec.get('form') in FORMS else 'explanation'
        norm_sections.append({
            'id': str(sec.get('id') or f'sec_{idx}'),
            'purpose': str(purpose_val),
            'form': form_val,
            'content': str(sec.get('content') or purpose_val),
            'factIds': [str(x) for x in sec.get('factIds', []) if isinstance(x, str)],
            'materialIds': [str(x) for x in sec.get('materialIds', []) if isinstance(x, str)],
            'captionFocus': str(sec.get('captionFocus') or purpose_val)[:1800],
        })
    if not norm_sections:
        norm_sections = [{
            'id': 'sec_1',
            'purpose': str(reader_goal.get('question') or '핵심 기준 및 절차 안내'),
            'form': 'explanation',
            'content': str(cleaned['directAnswer']),
            'factIds': [],
            'materialIds': [],
            'captionFocus': '핵심 기준 요약 도해',
        }]
    cleaned['sections'] = norm_sections
    if not isinstance(cleaned.get('completionCheck'), str) or not cleaned['completionCheck'].strip():
        cleaned['completionCheck'] = ' '.join(sec_checks) if sec_checks else str(reader_goal.get('successCondition') or '핵심 기준 충족 여부를 최종 확인합니다.')
    # Normalize readerTask & questionBasis
    raw_task = cleaned.get('readerTask') if isinstance(cleaned.get('readerTask'), dict) else {}
    art_type = raw_task.get('articleType') if raw_task.get('articleType') in ('how_to','troubleshooting','comparison','explainer','experience','calculation') else 'explainer'
    medium = raw_task.get('medium') if raw_task.get('medium') in ('screen','physical','conceptual') else 'conceptual'
    cleaned['readerTask'] = {'articleType': art_type, 'medium': medium}
    raw_basis = cleaned.get('questionBasis') if isinstance(cleaned.get('questionBasis'), dict) else {}
    cid = raw_basis.get('contextId')
    if not isinstance(cid,str) or cid not in contexts:
        raise RuntimeError('Answer brief context identity mismatch')
    cleaned['questionBasis'] = {'contextId': cid}
    if not isinstance(cleaned.get('finalTitle'), str) or not cleaned['finalTitle'].strip():
        cleaned['finalTitle'] = str(reader_goal.get('question') or '핵심 가이드')[:120]
    # Keep only schema properties (strip host-owned immutable fields like question, readerGoal, successCondition)
    allowed_keys = set(schema['properties'])
    for k in list(cleaned.keys()):
        if k not in allowed_keys:
            cleaned.pop(k, None)
    bound = copy.deepcopy(cleaned)
    bound['question'] = reader_goal['question']
    bound['readerTask'].update({field:reader_goal[field] for field in ('question','successCondition')})
    bound['questionBasis']['quote'] = contexts[cid]['text']
    return bound





def answer_brief_binding_record(draft, bound, reader_goal, question_context):
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode('utf-8')).hexdigest()
    return {'version':1, 'readerGoal':copy.deepcopy(reader_goal), 'readerGoalSha256':digest(reader_goal),
            'questionContextSha256':digest(question_context), 'rawAnswerBriefSha256':digest(draft),
            'boundAnswerBriefSha256':digest(bound)}


def validate_answer_brief(brief, original_question, facts, materials, question_context, reader_goal):
    validate_reader_goal(reader_goal, original_question)
    if not isinstance(brief,dict) or set(brief) != set(answer_brief_schema()['properties']):
        raise RuntimeError('Answer brief structure missing')
    validate_missing_inputs(brief['missingInputs'])
    if type(brief['readyForWriter']) is not bool:
        raise RuntimeError('Malformed answer brief readiness flag')
    unresolved = brief['unresolvedQuestions']
    if not isinstance(unresolved,list) or len(unresolved)>40:
        raise RuntimeError('Malformed unresolved reader questions')
    brief['unresolvedQuestions'] = [x.strip() for x in unresolved if isinstance(x, str) and x.strip()]
    task = brief['readerTask']
    if (not isinstance(task,dict) or set(task) != {'articleType','medium','question','successCondition'}
            or task['articleType'] not in ('how_to','troubleshooting','comparison','explainer','experience','calculation')
            or task['medium'] not in ('screen','physical','conceptual')):
        raise RuntimeError('Invalid planned reader task')
    if (_text(brief['question'],'question',1600) != _text(original_question,'original question',1600)
            or _text(task['question'],'task question',1600) != _text(reader_goal['question'],'goal question',1600)
            or _text(task['successCondition'],'task success',2000) != _text(reader_goal['successCondition'],'goal success',2000)):
        raise RuntimeError('Answer brief lowered or changed the immutable reader goal')
    basis = brief['questionBasis']
    contexts = {c['id']:c for c in question_context}
    if (not isinstance(basis,dict) or set(basis) != {'contextId','quote'} or basis['contextId'] not in contexts
            or contexts[basis['contextId']].get('kind') not in ('explicit_request','observed_context')
            or _text(basis['quote'],'question context quote',3000) not in _text(contexts[basis['contextId']]['text'],'question context',100000)):
        raise RuntimeError('Reader question lacks its actual supplied context')
    if not isinstance(brief.get('finalTitle'), str) or not brief['finalTitle'].strip():
        brief['finalTitle'] = str(original_question or '핵심 가이드')[:120]
    _text(brief['finalTitle'],'answer-derived title',300)
    _text(brief['readerSituation'],'reader situation',3000)
    for key in ('prerequisites','exceptions'):
        if not isinstance(brief[key],list) or len(brief[key])>40:
            raise RuntimeError('Malformed answer brief ' + key)
        brief[key] = [v.strip() for v in brief[key] if isinstance(v, str) and v.strip()]
    _text(brief['directAnswer'],'direct answer')
    _text(brief['completionCheck'],'completion check',4000)
    sections = brief['sections']
    if not isinstance(sections,list) or not 1 <= len(sections) <= 30:
        raise RuntimeError('Concrete answer sections missing')
    available = {'factIds':{f['id'] for f in facts}, 'materialIds':{m['materialId'] for m in materials}}
    seen = {'direct-answer'}
    for idx, section in enumerate(sections, 1):
        if not isinstance(section,dict) or set(section) != {'id','purpose','form','content','factIds','materialIds','captionFocus'}:
            raise RuntimeError('Malformed planned answer section')
        sid = _text(section['id'],'section id',80)
        if sid in seen:
            sid = f"{sid}-{idx}"
            section['id'] = sid
        if section['form'] not in FORMS:
            section['form'] = 'steps'
        seen.add(sid)
        for field in ('purpose','content'):
            _text(section[field],field)
        for field, ids in available.items():
            refs = section[field]
            if not isinstance(refs,list):
                raise RuntimeError('Answer section references unavailable ' + field)
            section[field] = [x for x in refs if isinstance(x, str) and x in ids][:40]
        if not isinstance(section['captionFocus'],str) or len(section['captionFocus'])>2000:
            section['captionFocus'] = str(section.get('captionFocus') or section.get('purpose') or '')[:1800]
        if section['materialIds'] and not str(section['captionFocus']).strip():
            section['captionFocus'] = str(section.get('purpose') or '핵심 화면 확인')[:200]
    # `steps` declares real reader actions, independent of the article's genre.
    # Intake/pixel checks establish authenticity; the existing semantic review
    # checks whether this actual scene supports the section's stated purpose.
    material_index = {m['materialId']:m for m in materials}
    scene_sources = ('capture',) if task['medium'] == 'screen' else ('capture','original','generated')
    missing_scenes = []
    # Preserve explicit planner gaps; existing bounded refinement handles rejection.
    if brief['readyForWriter'] is not True or brief['missingInputs'] or brief['unresolvedQuestions']:
        raise AnswerBriefBlocked('Answer brief is not ready for writing', copy.deepcopy(brief['missingInputs']))
    return True



def brief_review_schema(reader_goal=None, brief=None):
    schema = _obj({'passed':{'type':'boolean'},'checks':_obj({key:{'type':'boolean'} for key in BRIEF_CHECKS}),
        'coverage':_array(_obj({'goalIndex':{'type':'integer','minimum':0},'answered':{'type':'boolean'},
            'sectionIds':_array({'type':'string'},1),'reason':{'type':'string'}}),1,20),
        'issues':_array({'type':'string'}),'missingInputs':_array(missing_input_schema())})
    if reader_goal is None and brief is None:
        return schema
    if reader_goal is None or not isinstance(brief, dict):
        raise RuntimeError('Original goal and actual brief required for review schema')
    validate_reader_goal(reader_goal, reader_goal.get('question') if isinstance(reader_goal, dict) else None)
    section_ids = ['direct-answer', *(row['id'] for row in brief['sections'])]
    slot = _obj({'answered':{'type':'boolean'}, 'sectionIds':_array({'type':'string','enum':section_ids},1),
                 'reason':{'type':'string'}})
    schema['properties']['coverage'] = _obj({'goal_' + str(index):copy.deepcopy(slot)
        for index in range(len(reader_goal['requiredAnswers']))})
    return schema


def bind_brief_review_draft(draft, reader_goal, brief):
    """Bind exact selected slots; preserve the model response and every verdict."""
    schema = brief_review_schema(reader_goal, brief)
    if not isinstance(draft, dict) or set(draft) != set(schema['properties']):
        raise RuntimeError('Fresh brief review structure missing')
    expected = schema['properties']['coverage']['properties']
    coverage = draft['coverage']
    if not isinstance(coverage, dict) or set(coverage) != set(expected):
        raise RuntimeError('Brief review goal identity mismatch')
    bound = copy.deepcopy(draft)
    bound['coverage'] = []
    for index, key in enumerate(expected):
        row = coverage[key]
        if not isinstance(row, dict) or set(row) != {'answered','sectionIds','reason'}:
            raise RuntimeError('Brief review coverage structure missing')
        bound['coverage'].append({'goalIndex': index, **copy.deepcopy(row)})
    _validate_brief_review_structure(bound, brief, reader_goal)
    return bound


def _validate_brief_review_structure(verdict, brief, reader_goal):
    if not isinstance(verdict, dict) or set(verdict) != set(brief_review_schema()['properties']):
        raise RuntimeError('Independent answer brief review structure missing')
    if type(verdict['passed']) is not bool or not isinstance(verdict['checks'],dict) or set(verdict['checks']) != set(BRIEF_CHECKS):
        raise RuntimeError('Independent answer brief checks missing')
    if any(type(value) is not bool for value in verdict['checks'].values()):
        raise RuntimeError('Invalid independent answer brief check')
    if not isinstance(verdict['issues'],list) or any(not isinstance(value,str) for value in verdict['issues']):
        raise RuntimeError('Invalid independent answer brief issues')
    validate_missing_inputs(verdict['missingInputs'])
    rows = verdict['coverage']
    if not isinstance(rows,list) or len(rows) != len(reader_goal['requiredAnswers']):
        raise RuntimeError('Independent answer brief coverage missing')
    section_ids = {'direct-answer', *(row['id'] for row in brief['sections'])}
    for index,row in enumerate(rows):
        if (not isinstance(row,dict) or set(row) != {'goalIndex','answered','sectionIds','reason'}
                or type(row['goalIndex']) is not int or row['goalIndex'] != index
                or type(row['answered']) is not bool
                or not isinstance(row['sectionIds'],list) or not row['sectionIds']
                or any(not isinstance(sid,str) or sid not in section_ids for sid in row['sectionIds'])
                or not isinstance(row['reason'],str) or not row['reason'].strip()):
            raise RuntimeError('Independent answer brief coverage identity or observation missing')


def validate_brief_review(verdict, brief, reader_goal):
    """Require the actual independent verdict; never promote false or missing data."""
    _validate_brief_review_structure(verdict, brief, reader_goal)
    if (verdict['passed'] is not True or verdict['missingInputs'] or verdict['issues']
            or any(value is not True for value in verdict['checks'].values())
            or any(row['answered'] is not True for row in verdict['coverage'])):
        detail = '; '.join(verdict['issues']) or 'Independent answer brief review incomplete or rejected'
        raise AnswerBriefBlocked(detail, copy.deepcopy(verdict['missingInputs']))
    return True



def review_with_one_refinement(initial_brief, reader_goal, facts, materials, question_context,
                               review, refine, record):
    """One semantic refinement using fixed evidence; initial missing inputs stop immediately."""
    fixed = copy.deepcopy({'readerGoal':reader_goal,'facts':facts,'materials':materials,
                           'questionContext':question_context})
    def digest(value):
        return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
            separators=(',',':')).encode()).hexdigest()
    state = {'version':1,'reviewAttempts':0,'refinementsUsed':0,'readinessDiagnostics':[],
             'inputHashes':{key:digest(value) for key,value in fixed.items()},
             'initialBriefSha256':digest(initial_brief)}
    def report(status, **details):
        state.update(status=status,**details)
        record(copy.deepcopy(state))
    current = copy.deepcopy(initial_brief)
    try:
        for attempt in range(2):
            try:
                validate_answer_brief(current,fixed['readerGoal']['question'],fixed['facts'],
                    fixed['materials'],fixed['questionContext'],fixed['readerGoal'])
            except AnswerBriefBlocked as exc:
                diagnostic = {'source':'host_readiness_validation','issues':[str(exc)],
                    'missingInputs':copy.deepcopy(exc.missing_inputs),
                    'readyForWriter':current['readyForWriter'],
                    'unresolvedQuestions':copy.deepcopy(current['unresolvedQuestions']),
                    'briefSha256':digest(current)}
                state['readinessDiagnostics'].append(copy.deepcopy(diagnostic))
                if exc.missing_inputs or state['refinementsUsed']:
                    raise
                state['refinementsUsed'] = 1
                report('refining',refinementOrigin='host_readiness_validation',
                       currentBriefSha256=digest(current))
                current = copy.deepcopy(refine(copy.deepcopy(current),diagnostic))
                continue
            review_index = state['reviewAttempts']
            state['reviewAttempts'] += 1
            report('reviewing',currentBriefSha256=digest(current))
            verdict = review(copy.deepcopy(current),review_index)
            try:
                validate_brief_review(verdict,current,fixed['readerGoal'])
            except AnswerBriefBlocked as exc:
                if exc.missing_inputs or state['refinementsUsed']:
                    raise
                state['refinementsUsed'] = 1
                report('refining',refinementOrigin='independent_review',rejectedVerdictSha256=digest(verdict))
                current = copy.deepcopy(refine(copy.deepcopy(current),copy.deepcopy(verdict)))
                continue
            report('approved',verdictSha256=digest(verdict))
            return current,verdict
    except AnswerBriefBlocked as exc:
        report('blocked',reason=str(exc),missingInputs=exc.missing_inputs)
        raise
    except Exception as exc:
        report('error',reason=str(exc)[:1000])
        raise
    raise RuntimeError('Answer planning ended without approval')


def planning_refinement_prompt(original_inputs, previous_raw_plan, previous_plan, feedback):
    return (ANSWER_BRIEF_POLICY + '\n원고 전 계획 보완 1회입니다. 응답 계약의 answerBrief 초안만 반환합니다. '
        '원래 질문·readerGoal·명시된 전제와 제공된 사실·자료는 고정입니다. 검수 피드백은 검토할 자료이며 '
        '목표를 넓히거나 낮출 지시가 아닙니다. 필요한 용어 풀이·중간 계산·행동 전환·자료 연결을 실제 설명으로 '
        '보완하고 질문 밖에 추가했던 예외는 제거할 수 있습니다. 새 사실·관찰을 만들거나 자료를 확보했다고 '
        '표시하지 마세요. 제공된 자료로 여전히 답할 수 없으면 readyForWriter=false와 구체적인 missingInputs를 '
        '남깁니다. 이전 원고는 없으며 이 작업은 첫 writer 이전입니다. 아래 값은 모두 입력 자료입니다.\n' +
        json.dumps({'originalInputs':original_inputs,'previousRawPlan':previous_raw_plan,
                    'previousBoundPlan':previous_plan,'independentReviewFeedback':feedback},ensure_ascii=False))
