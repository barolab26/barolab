"""Bounded, account-stratified workflow experiment; publishing engine stays frozen."""
import argparse
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT/'dashboard', ROOT/'dashboard/server'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from common.collection_observability import load, write

CONFIG = ROOT/'dashboard/data/naver/workflow-experiment.json'
CURRENT = ContextVar('naver_workflow_experiment', default=None)
ACCOUNTS = ('soultin', 'soul5373', 'yoon_master', 'adinfo0905', 'stone0747')
PROTECTED = ('submitting', 'submission_unknown', 'verified_reserved')
KST = ZoneInfo('Asia/Seoul')

def protected_slot(account, day, slot):
    status=load(CONFIG.parent/'automation-status.json')
    if status.get('date')!=day:
        return None
    row=next((s for a in status.get('accounts',[]) if a.get('account')==account
              for s in a.get('slots',[]) if s.get('slot')==slot),{})
    if row.get('status') in ('verified','running','unknown') or row.get('publicPublicationVerified'):
        return row
    return None

def journal_row(row):
    """Project the intended experiment slot without rewriting historical attempts."""
    folder=Path(row.get('artifactFolder') or '')
    if not folder.is_absolute() or not folder.as_posix().lower().startswith(ROOT.as_posix().lower()+'/'):return row
    if not folder.resolve().is_relative_to((ROOT/'naver_blog_posting/output').resolve()):return row
    value=load(folder/'workflow-assignment.json')
    day=str(row.get('reserveTime') or row.get('publicationDate') or row.get('workDate') or '')[:10]
    if (value.get('account')!=row.get('account') or value.get('day')!=day
            or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value.get('slot',''))):return row
    if row.get('phase')=='verified':
        receipt=load(folder/'reservation-evidence.json')
        if (receipt.get('submissionStatus')!='verified_reserved' or receipt.get('account')!=row.get('account')
                or receipt.get('reserveTime')!=row.get('reserveTime')):return row
    return {**row,'scheduledSlot':value['slot'],'workflowSlotSource':str(folder/'workflow-assignment.json')}


def publication_identity(row, attempts=None):
    """Resolve a public result to one receipt-bound original slot, without editing history."""
    if attempts is None:attempts=load(CONFIG.parent/'automation-journal.json').get('attempts',[])
    matches=[]
    for attempt in attempts:
        if (attempt.get('phase')!='verified' or attempt.get('account')!=row.get('account')
                or (attempt.get('title') or attempt.get('topic'))!=row.get('title')
                or attempt.get('reserveTime')!=row.get('reserveTime')):continue
        folder=Path(attempt.get('artifactFolder') or '')
        if not folder.is_absolute() or not folder.resolve().is_relative_to((ROOT/'naver_blog_posting/output').resolve()):continue
        receipt=load(folder/'reservation-evidence.json')
        if (receipt.get('submissionStatus')!='verified_reserved' or receipt.get('account')!=row.get('account')
                or receipt.get('title')!=row.get('title') or receipt.get('reserveTime')!=row.get('reserveTime')):continue
        projected=journal_row(attempt)
        slot=projected.get('scheduledSlot')
        if re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',str(slot or '')):
            matches.append((slot,str(folder)))
    identities=set(matches)
    if len(identities)!=1:return row
    slot,folder=next(iter(identities))
    return {**row,'scheduledSlot':slot,'artifactFolder':folder,'slotIdentitySource':'verified reservation receipt and original attempt'}

def approved_request(kind, arguments):
    """A bounded standing user approval; never a general autonomous-work exception."""
    config=load(CONFIG)
    approval=config.get('approval') or {}
    if (kind!='parameters' or arguments.get('action')!='naver' or config.get('status')!='active'
            or approval.get('sourceType')!='direct_user_instruction' or not approval.get('instruction')
            or arguments.get('account') not in config.get('accounts',[]) or not arguments.get('date')
            or not config['startDate'] <= arguments['date'] <= config['enrollmentEnd']):return None
    plan=load(ROOT/'dashboard/data/daily_schedule.json').get('naver',{})
    if arguments.get('slot') not in plan.get(arguments['account'],{}).get('slots',[]):return None
    if arguments.get('slot') not in approval.get('slotsByAccount',{}).get(arguments['account'],[]):return None
    return {'id':config['id'],'approval':approval,'account':arguments['account'],
            'date':arguments['date'],'slot':arguments['slot'],'source':str(CONFIG)}

def arm_for(account, day, slot, slots, seed):
    """Randomize each account's starting arm; alternate by date/slot thereafter."""
    start = int(hashlib.sha256((seed+account).encode()).hexdigest()[:8], 16) % 2
    ordinal = (date.fromisoformat(day)-date(2026, 11, 6)).days * len(slots) + slots.index(slot)
    # Swap paired days too: two-slot accounts see both arms in each time window.
    ordinal += (date.fromisoformat(day)-date(2026, 11, 6)).days if len(slots) % 2 == 0 else 0
    return 'AB'[(start+ordinal) % 2]

def assignment(account, folder, day, slot, *, create=False):
    folder = Path(folder)
    saved = load(folder/'workflow-assignment.json')
    if saved:
        if saved.get('account') != account or saved.get('day') != day or saved.get('slot') != slot:
            raise ValueError('Experiment assignment identity changed')
        return saved
    config = load(CONFIG)
    if (not create or config.get('status') != 'active' or account not in config.get('accounts', [])
            or not config['startDate'] <= day <= config['enrollmentEnd']):
        return None
    if not folder.resolve().is_relative_to((ROOT/'naver_blog_posting/output').resolve()):
        raise ValueError('Experiment artifacts must stay inside the Naver output directory')
    receipt = load(folder/'reservation-evidence.json')
    if (receipt or any((folder/name).exists() for name in
                       ('writer.json','editor-content.json','publication-receipt.json'))):
        return None  # Never retroactively label or re-author an existing article.
    slots = load(ROOT/'dashboard/data/daily_schedule.json')['naver'][account]['slots']
    if slot not in slots:
        from common.operating_plan import allocations
        if any(r['slot']==slot for r in allocations('naver_blog',account,day)):
            return None  # Additional operating volume is outside the original A/B cohort.
        raise ValueError('Experiment may not create an unapproved slot')
    value = {'experimentId':config['id'], 'account':account, 'day':day, 'slot':slot,
             'arm':arm_for(account,day,slot,slots,config['seed']),
             'mode':'search', 'provider':config['provider'], 'model':config['model'],
             'protocolSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             'createdAt':datetime.now(KST).isoformat(),
             'fidelity':'A_company_reader_first' if arm_for(account,day,slot,slots,config['seed'])=='A'
                        else 'B_moneyhomepan_search_download_reconstructed',
             'workflowProtocol':'company-capture-v2' if arm_for(account,day,slot,slots,config['seed'])=='A' else 'moneyhomepan-search-download-v2',
             'sharedDeviations':['no external links, no unverified claims, review failure holds',
                                 'actual reservation/publication verification retained'],
             'minimumSample':{'publishedPostsPerArmPerAccount':6,'uniqueReadersPerPost':100},
             'metrics':{'searchVisits':None,'uniqueReaders':None,'attributedRevenue':None}}
    write(folder/'workflow-assignment.json',value)
    return value

@contextmanager
def scope(value, folder):
    if not value:
        yield
        return
    token = CURRENT.set({'assignment':value,'folder':Path(folder)})
    try:
        yield
    finally:
        CURRENT.reset(token)

def reserve_call(stage):
    """Charge every scoped provider call before it starts, including failures."""
    context = CURRENT.get()
    if not context:
        return None
    from common.collection_observability import locked
    with locked(CONFIG.parent/'workflow-experiment-budget'):
        config = load(CONFIG)
        if config.get('status') != 'active':
            raise ValueError('Workflow experiment stopped; preserve current work')
        counts = config.setdefault('callsByDate', {})
        day = datetime.now(KST).date().isoformat()
        if counts.get(day,0) >= config['maxModelCallsPerDay']:
            from common.llm_usage import UsageBudgetExceeded
            raise UsageBudgetExceeded('naver_workflow_experiment_daily_call_budget')
        local = load(context['folder']/'workflow-calls.json')
        calls = local.setdefault('calls',[])
        if len(calls) >= config['maxModelCallsPerArticle']:
            from common.llm_usage import UsageBudgetExceeded
            raise UsageBudgetExceeded('naver_workflow_experiment_article_call_budget')
        calls.append({'stage':stage,'at':datetime.now(KST).isoformat()})
        counts[day] = counts.get(day,0)+1
        write(context['folder']/'workflow-calls.json',local)
        write(CONFIG,config)
    return context['assignment']

def defer_preimage_review(folder):
    """Review the complete publication once; this is explicitly NOT an approval."""
    context=CURRENT.get()
    if not context or Path(folder).resolve()!=context['folder'].resolve():
        return False
    folder=Path(folder)
    return not (folder/'photo-plan.json').is_file() and not (folder/'editor-content.json').is_file()

def normalize_article_tags(article):
    """Native schema requires #tags; format existing words without inventing tags."""
    tags=[]
    for value in article.get('tags',[]):
        if not isinstance(value,str):raise ValueError('Invalid article tag')
        tag='#'+value.strip().lstrip('#')
        if not re.fullmatch(r'#[A-Za-z0-9_\uac00-\ud7a3]+',tag):
            raise ValueError('Invalid article tag characters')
        if tag not in tags:tags.append(tag)
    if not tags:raise ValueError('Article tags missing')
    return {**article,'tags':tags}

def normalize_saved_tags(folder):
    folder=Path(folder)
    if not folder.resolve().is_relative_to((ROOT/'naver_blog_posting/output').resolve()):return
    if (not load(folder/'workflow-assignment.json') or (folder/'editor-content.json').exists()
            or (folder/'reservation-evidence.json').exists()):return
    path=folder/'writer.json'
    if not path.exists():return
    original=load(path);updated=normalize_article_tags(original)
    if updated!=original:
        backup=folder/'writer-before-tag-format.json'
        if not backup.exists():write(backup,original)
        write(path,updated)

def writer_prompt(prompt, value):
    from common.naver_reader import POLICY
    context=CURRENT.get()
    if context:
        folder=context['folder'];research=load(folder/'research.json');brief=load(folder/'planning.json')
        actual=research.get('requestedKeyword') or research.get('keyword')
        if actual and brief.get('keyword')!=actual:
            from dashboard.agents.style_strategy import attach_search_benchmark, search_writing_context
            brief=attach_search_benchmark({**brief,'keyword':actual},folder)
            write(folder/'planning.json',brief)
            prompt+='\n[최종 선택 검색어의 실제 벤치마킹: 앞의 다른 검색어 관찰은 적용하지 않는다]\n'+json.dumps(search_writing_context(folder),ensure_ascii=False)
    if value['arm'] == 'A':
        rules = ('A: 독자의 검색 질문에 먼저 답한다. 분량·소제목·이미지 개수를 강제하지 않는다. '
                 '각 이미지 요구에는 소제목과 주변 문장에 필요한 구체적인 화면·대상·검색어를 적는다. '
                 '텍스트만으로 충분한 지점은 image_optional=true로 한다.')
    else:
        # Preserve safety policy but replace its editorial freedom clauses for this arm.
        prompt = prompt.replace(POLICY, '\n'.join(line for line in POLICY.splitlines()
                                  if not any(x in line for x in ('글자수,','이미지 수의 하한'))))
        rules = ('B: MoneyHomepan 검색형 제작 방식을 재현한다. 도입부 첫 1~2문장에 핵심 답과 적용 조건을 쓴다. '
                 '본문은 1600~1900자를 목표로 하며 자료가 부족하면 분량을 채우려고 사실을 만들지 않는다. '
                 '짧은 모바일 문단과 내용에 맞는 구체적인 소제목으로 구성하며 소제목 앞에 번호를 붙이지 않는다. '
                 '이미지 7~8개 자리는 본문 후처리에서 만들며 소제목 7개를 강제한다는 뜻이 아니다. '
                 '각 섹션의 imagePrompt에는 2~5개 구체어와 필요한 장면을, imageCaption에는 역할을 적는다. '
                 '공식 화면이 독자에게 도움이 되는 섹션만 image_optional=false로 한다. '
                 '뉴스 사진 다운로드 대신 실제 출처 캡처라는 공통 안전 기준을 쓴다. '
                 '이 차이 때문에 원본 이미지 방식의 완전 복제로 해석하지 않는다. '
                 '비교 조건이 3개 이상이고 표가 유용할 때만 표를 쓴다. 경험을 꾸미지 않는다.')
    common = ('본문과 맺음말에는 제공된 자료·입력 자료·직접 조작한 후기가 아님 같은 내부 제작 설명을 넣지 않는다. '
              '실제 경험을 주장하지 말고 기관명과 확인할 메뉴를 안내한다. '
              '자료에서 확인되지 않은 조건을 확정하지 않으며, 제목은 실제로 답할 수 있는 범위로 정한다. '
              '소제목 번호는 불필요한 사실 수치로 섞이지 않도록 쓰지 않는다.')
    common += ' tags는 각각 #으로 시작하고 공백이나 특수기호가 없는 고유한 해시태그로 반환한다.'
    return prompt+'\n[네이버 워크플로우 실험 — 원고에 이 표시는 노출하지 않는다]\n'+rules+'\n'+common

def polish_article(generate, draft, prompt, args, kwargs):
    context = CURRENT.get()
    if not context or context['assignment']['arm'] != 'B':
        return draft
    folder = context['folder']
    write(folder/'workflow-initial-draft.json',draft)
    review_kwargs = dict(kwargs)
    review_kwargs['audit_directory'] = folder/'workflow-polish-audit'
    reviewed = generate(prompt+'\n동일 모델 최종 교정 단계이다. 새 자료를 추정하지 말고 제공 근거와 초안을 대조한다. '
                        '잘못된 사실·관계·날짜·수치를 제거하고 소제목 및 이미지 요구의 의미를 유지한다. '
                        '완성 원고만 동일 JSON 스키마로 반환한다. 교정할 초안:\n'
                        +json.dumps(draft,ensure_ascii=False),*args,**review_kwargs)
    write(folder/'workflow-polished-draft.json',reviewed)
    # The independent publication/reader reviews still run after this call.
    return reviewed

def activate():
    if load(CONFIG):
        return load(CONFIG)
    start = date(2026,11,6)
    value = {'id':'naver-workflow-ab-20261106','status':'active','startDate':start.isoformat(),
             'enrollmentEnd':(start+timedelta(days=13)).isoformat(),'accounts':list(ACCOUNTS),
             'seed':'ceo-approved-20261106-workflow-crossover','provider':'codex','model':'gpt-6.1-sol',
             'maxModelCallsPerDay':160,'maxModelCallsPerArticle':32,'callsByDate':{},
             'authorization':'User requested immediate A/B execution across all Naver accounts, 2026-11-06',
             'approval':{'sourceType':'direct_user_instruction',
                         'instruction':'오케이. 진행시켜서 바로 구동해봐. 우리 지금 네이버 블로그 오늘 부터, 그리고 한계정만 하지 말고 모든 계정에 해보는게 좋을거 같은데?',
                         'slotsByAccount':{k:v['slots'] for k,v in load(ROOT/'dashboard/data/daily_schedule.json')['naver'].items()}},
             'primaryMetric':'post-scoped searchVisits','observationDays':[7,14,28],
             'minimumSample':{'publishedPostsPerArmPerAccount':6,'uniqueReadersPerPost':100},
             'baseline':None,'baselineStatus':'not_collected; never substitute account totals',
             'stopConditions':['factual error','image provenance failure','duplicate or uncertain submission',
                               'daily/article call budget exhausted','manual stop or ownership loss'],
             'inference':'account-stratified crossover exploration; no guaranteed causal or revenue conclusion',
             'fidelity':'B is safety-adapted; not an exact news-photo acquisition reproduction',
             'preservePublished':True,'preserveExistingReceipts':True,'increaseDailyVolume':False}
    write(CONFIG,value)
    return value

def experiment_folder(original, account, day, slot):
    """Keep old unsent drafts intact; give the approved replacement one stable home."""
    original = Path(original)
    config = load(CONFIG)
    if (config.get('status') != 'active' or account not in config.get('accounts', []) or
            not config['startDate'] <= day <= config['enrollmentEnd']):
        return original
    if load(original/'workflow-assignment.json'):
        return original
    receipt = load(original/'reservation-evidence.json')
    if receipt.get('submissionStatus') in PROTECTED or (original/'publication-receipt.json').exists():
        return original
    if any((original/n).exists() for n in ('writer.json','editor-content.json')):
        return original.parent/('workflow-ab-'+account+'-'+slot.replace(':',''))
    return original

def plan(account, topic, folder, day, slot):
    """Directly prepare an experiment brief from real search evidence, without crew dispatch."""
    from common.asset_map import collect_used_naver_topics, is_duplicate_naver_topic, query_naver_blog_doc_count
    from common.naver_reader import POLICY
    from dashboard.agents.style_strategy import attach_search_benchmark, planning_keyword_candidates
    folder=Path(folder)
    value=assignment(account,folder,day,slot,create=True)
    if not value:
        return None
    previous=load(folder/'planning.json')
    if previous.get('keyword'):
        return previous
    seeds={
        'soultin':['국민연금 수급계좌 변경 방법','국민연금 연금수급증명서 발급 방법','국민연금 수급자 주소 변경'],
        'soul5373':['건강기능식품 이상사례 신고 방법','의약품안전나라 허가사항 검색 방법','예방접종증명서 온라인 발급 방법'],
        'adinfo0905':['엑셀 중복값 표시 조건부 서식','엑셀 셀 안 줄바꿈 단축키','엑셀 인쇄 제목 행 반복 설정'],
        'stone0747':['소상공인 정책자금 대리대출 확인서','소상공인확인서 발급 방법','중소기업확인서 유효기간 조회'],
        'yoon_master':['로봇청소기 문턱 높이 확인','식기세척기 급수 배수 설치조건','삼성 건조기 필터 청소 방법','LG 세탁기 통살균 사용 방법']}
    used=collect_used_naver_topics(account,days=14,current_folder=folder)
    from common.source_discovery import research
    from common.content_improvement import primary_url
    pool=seeds[account]+[r['keyword'] for r in planning_keyword_candidates(account,'naver',used)]
    candidates=list(dict.fromkeys(q for q in pool if not is_duplicate_naver_topic(q,used)))
    considered=[];keyword=None
    for query in candidates[:3]:
        observed=research(query,folder,exact_query=True)
        primary=[s['url'] for s in observed if primary_url(s['url'])]
        considered.append({'keyword':query,'sourceCount':len(observed),'primarySourceUrls':primary})
        write(folder/'workflow-topic-evidence.json',{'candidates':considered})
        if primary:keyword=query;break
    if not keyword:raise ValueError('Research new reader question: no primary evidence in bounded topic selection; no draft generated')
    doc_count=query_naver_blog_doc_count(keyword)
    brief={'status':'direct_experiment_brief','identity':account,'account':account,'channel':'naver',
           'keyword':keyword,'writingGuide':POLICY,'bridgeTarget':None,
           'observedCompetingDocuments':doc_count,
           'selectionBasis':'distinct account-specific reader task; document count is observation, not a ranking rule',
           'planningId':value['experimentId']+':'+account+':'+day+':'+slot,
           'decisionSource':'direct implementation of CEO-approved workflow experiment; not a fabricated crew meeting'}
    brief=attach_search_benchmark(brief,folder)
    write(folder/'planning.json',brief)
    return brief

def locked_keyword(account, candidate, used):
    """Keep research and benchmark on the same task; never replace it with an unrelated low-count keyword."""
    context=CURRENT.get()
    if not context:return None
    value=context['assignment'];brief=load(context['folder']/'planning.json')
    if account!=value['account'] or candidate!=brief.get('keyword'):
        raise ValueError('Experiment keyword identity changed; preserve the planned reader task')
    from common.asset_map import is_duplicate_naver_topic
    if is_duplicate_naver_topic(candidate,used):
        raise ValueError('Experiment topic duplicates existing work; choose another distinct reader question')
    return candidate

def observed_research(keyword, folder):
    context=CURRENT.get()
    if not context or Path(folder).resolve()!=context['folder'].resolve():return None
    value=load(Path(folder)/'research.json')
    if value.get('requestedKeyword')!=keyword or not value.get('sources'):return None
    try:
        at=datetime.fromisoformat(value['collectedAt'])
        if not at.tzinfo or not timedelta(0)<=datetime.now(KST)-at<=timedelta(minutes=30):return None
    except (ValueError,KeyError,TypeError):return None
    if any(s.get('status')!=200 or hashlib.sha256(s.get('text','').encode()).hexdigest()!=s.get('textSha256')
           for s in value['sources']):return None
    return value['sources']

def install_image_slots(engine):
    """Separate B's paragraph slots from headings; retain capture/review/hash gates."""
    if getattr(engine,'_workflow_image_wiring',False):
        return
    original_sections=engine.naver_image_sections
    original_prepare=engine.prepare_document_images
    original_verify=engine.verify_document_images
    def sections(document):
        slots=document.get('workflowImageSlots')
        return [{k:v for k,v in row.items() if k!='parentSection'} for row in slots] if slots else original_sections(document)
    def verify(document,plan,folder):
        if plan.get('workflowProtocol')=='moneyhomepan-search-download-v2':
            from common.naver_download_workflow import verify as verify_download
            return verify_download(document,plan,folder,engine)
        slots=document.get('workflowImageSlots')
        if not slots:
            return original_verify(document,plan,folder)
        from common.flow_images import require_editorial_images, hold_editorial_images
        result=require_editorial_images(document['title'],sections(document),folder,channel='naver',
                                         existing=plan.get('editorialImages'))
        expected=[engine._naver_image_asset(a,i) for i,a in enumerate(result['assets'])]
        if plan.get('documentSha256')!=engine.document_fingerprint(document) or plan.get('assets')!=expected:
            hold_editorial_images(folder,'workflow_image_plan_changed')
        current=0;images=[]
        for i,block in enumerate(document['blocks']):
            if block['type']=='heading':current+=1
            if block['type']!='image':continue
            images.append(block)
            if len(images)>len(expected):raise ValueError('Unplanned workflow image')
            asset=expected[len(images)-1];slot=slots[asset['section_index']]
            previous=document['blocks'][i-1] if i else {}
            if (slot['parentSection']!=current or previous.get('type') not in ('text','quotation') or
                    asset['editorialAsset']['anchor_text'] not in previous.get('text','')):
                hold_editorial_images(folder,'workflow_exact_anchor_changed')
        if len(images)!=len(expected):raise ValueError('Missing workflow image')
        report=engine.validate_document(document,plan,Path(folder)/'images')
        if not report['ok']:raise ValueError('Workflow image document invalid: '+str(report['errors']))
        return result
    def prepare(document,folder,keyword,signoff=''):
        value=load(Path(folder)/'workflow-assignment.json')
        if value.get('arm')!='B':return original_prepare(document,folder,keyword,signoff)
        if not document.get('workflowImageSlots'):
            candidates=[];parent=0;heading=document['title']
            options=document.get('editorialSectionOptions') or {}
            intents=load(Path(folder)/'workflow-image-intents.json').get('intents',[])
            observed_urls={s['url'] for s in load(Path(folder)/'research.json').get('sources',[])}
            required_seen=set()
            for block in document['blocks']:
                if block['type']=='heading':parent+=1;heading=block['text']
                elif block['type']=='text':
                    for paragraph in block['text'].splitlines():
                        if len(paragraph.strip())<8:continue
                        required=options.get('section-'+str(parent),True) is False and parent not in required_seen
                        if required:required_seen.add(parent)
                        candidates.append({'heading':heading,'body':paragraph,'parentSection':parent,
                                           'purpose':'contextual source screenshot for this paragraph',
                                           'image_optional':not required})
            intended=[]
            for intent in intents:
                matches=[c for c in candidates if intent.get('anchor') and intent['anchor'] in c['body']]
                if len(matches)!=1 or intent.get('sourceUrl') not in observed_urls:
                    raise ValueError('Image intention must bind one exact paragraph to an observed source')
                matches[0]['purpose']=intent['sourceUrl']+' — '+str(intent.get('readerNeed',''))
                intended.append(candidates.index(matches[0]))
                if intent.get('required') is True:matches[0]['image_optional']=False
            mandatory=[i for i,c in enumerate(candidates) if not c['image_optional']]
            first=[];seen=set()
            for i,c in enumerate(candidates):
                if c['parentSection'] not in seen:first.append(i);seen.add(c['parentSection'])
            preferred=mandatory+[i for i in intended if i not in mandatory]
            preferred += [i for i in first if i not in preferred]
            preferred += [i for i in range(len(candidates)) if i not in preferred]
            chosen=sorted(preferred[:max(7,len(mandatory))])
            document['workflowImageSlots']=[{**candidates[i],'id':'workflow-slot-'+str(n),'index':n}
                                             for n,i in enumerate(chosen)]
        from common.flow_images import require_editorial_images
        result=require_editorial_images(document['title'],sections(document),folder,
                                         sources=load(Path(folder)/'research.json').get('sources',[]),channel='naver')
        assets=[engine._naver_image_asset(a,i) for i,a in enumerate(result['assets'])]
        blocks=list(document['blocks'])
        for asset in reversed(assets):
            raw=asset['editorialAsset'];anchor=raw['anchor_text']
            matches=[i for i,b in enumerate(blocks) if b['type'] in ('text','quotation') and anchor in b['text']]
            if len(matches)!=1:raise ValueError('Ambiguous workflow image anchor')
            i=matches[0];block=blocks[i];end=block['text'].find('\n',block['text'].index(anchor)+len(anchor))
            image={'type':'image','id':asset['id'],'file':asset['file'],
                   'alt':raw.get('alt') or asset['description'],'caption':asset['description']+'｜'+asset['credit']}
            replacement=[block,image] if end<0 else [{**block,'text':block['text'][:end]},image,
                                                       {**block,'text':block['text'][end+1:]}]
            blocks[i:i+1]=replacement
        document['blocks']=blocks
        plan={'version':1,'main_keyword':keyword,'signoff':signoff,'assets':assets,
              'representative_file':assets[0]['file'] if assets else '',
              'editorialImages':result,'documentSha256':engine.document_fingerprint(document)}
        verify(document,plan,folder)
        write(Path(folder)/'workflow-image-realization.json',{'targetSlots':[7,8],
              'actualSlots':len(document['workflowImageSlots']),'approvedImages':len(assets),
              'acquisition':'real_source_screenshot','exactOriginalReproduction':False})
        return plan
    engine.naver_image_sections=sections
    engine.prepare_document_images=prepare
    engine.verify_document_images=verify
    engine._workflow_image_wiring=True

def observe():
    config = load(CONFIG)
    records = []
    for path in (ROOT/'naver_blog_posting/output').rglob('workflow-assignment.json'):
        value = load(path)
        if value.get('experimentId') != config.get('id'):
            continue
        receipt = load(path.parent/'reservation-evidence.json')
        public = load(path.parent/'publication-receipt.json')
        inventory = load(CONFIG.parent/'public-verification.json').get('evidence',[])
        title = load(path.parent/'editor-content.json').get('title')
        matches = [r for r in inventory if r.get('account')==value['account'] and r.get('title')==title
                   and r.get('publicPublicationVerified') is True]
        if len(matches)==1:
            public = matches[0]
        publicly_verified=public.get('publicPublicationVerified') is True
        photo_plan=load(path.parent/'photo-plan.json')
        image_count=len(photo_plan.get('assets',[]))
        implementation=load(path.parent/'b-protocol-evidence.json').get('implementationSha256') or value.get('protocolSha256')
        cohort=(value['workflowProtocol']+':'+str(implementation)[:12]) if value.get('workflowProtocol') else 'legacy-safety-adapted-pilot'
        stamp = public.get('publishedAt') if publicly_verified else None
        try:
            published_at = datetime.fromisoformat(stamp).replace(tzinfo=KST) if stamp else None
        except (ValueError,TypeError):
            published_at = None
        records.append({**value,'cohort':cohort,'implementationSha256':implementation,
                        'eligibleForDownloadComparison':value.get('workflowProtocol') in ('company-capture-v2','moneyhomepan-search-download-v2'),
                        'actualImageCount':image_count,'imageAcquisitionRealized':image_count>0,
                        'imageComparisonStatus':'observed_images' if image_count else 'no_images_keep_in_assigned_cohort',
                        'folder':str(path.parent),'reservation':receipt,
                        'publicEvidence':public,'publishedVerified':publicly_verified,
                        'publicBodyMatched':public.get('publicBodyMatched'),
                        'reservationVerified':receipt.get('submissionStatus')=='verified_reserved',
                        'measurementStatus':'post_scoped_analytics_not_collected',
                        'windows':[{'day':day,'dueAt':(published_at+timedelta(days=day)).isoformat() if published_at else None,
                                    'status':'inconclusive','searchVisits':None,
                                    'attributedRevenue':None,'reason':'URL-scoped observation required'}
                                   for day in config.get('observationDays',[7,14,28])]})
    result = {'checkedAt':datetime.now(KST).isoformat(),'records':records,
              'assigned':len(records),'reserved':sum(r['reservationVerified'] for r in records),
              'publiclyVerified':sum(r['publishedVerified'] for r in records),
              'causalClaim':False,'cohortWarning':'Pilot revisions and assisted edits must be stratified; do not pool protocol versions or compare only surviving published articles.'}
    write(CONFIG.parent/'workflow-experiment-results.json',result)
    return result

def run_all(day):
    """One attempt per unsubmitted slot. Never replay an earlier experiment hold."""
    policy=load(ROOT/'dashboard/data/daily_schedule.json')['naver']
    batch_path=CONFIG.parent/('workflow-batch-'+day+'.json')
    batch=load(batch_path) or {'date':day,'startedAt':datetime.now(KST).isoformat(),'items':[]}
    for account in ACCOUNTS:
        for slot in policy[account]['slots']:
            if any(r['account']==account and r['slot']==slot for r in batch['items']):continue
            standard=ROOT/'naver_blog_posting/output/scheduled'/day/(account+'-'+slot.replace(':',''))
            folder=experiment_folder(standard,account,day,slot)
            # A prior completed/held/uncertain attempt needs an explicit scoped repair, not a rerun loop.
            if load(folder/'workflow-assignment.json') and load(folder/'workflow-calls.json').get('calls'):
                row={'account':account,'slot':slot,'status':'preserved_prior_experiment_attempt','folder':str(folder)}
                batch['items'].append(row);write(batch_path,batch);continue
            row={'account':account,'slot':slot,'status':'running','folder':str(folder),
                 'startedAt':datetime.now(KST).isoformat()}
            batch['items'].append(row);write(batch_path,batch)
            logs=CONFIG.parent/'workflow-logs';logs.mkdir(exist_ok=True)
            log_path=logs/(day+'-'+account+'-'+slot.replace(':','')+'.log')
            print(json.dumps(row,ensure_ascii=False),flush=True)
            with log_path.open('w',encoding='utf-8') as log:
                run=subprocess.run([sys.executable,'-u','-B','-X','utf8','-m','dashboard.common.naver_ab',
                                    'run','--date',day,'--account',account,'--slot',slot],cwd=ROOT,
                                   stdout=log,stderr=subprocess.STDOUT)
            text=log_path.read_text(encoding='utf-8')
            outcome={}
            for line in reversed(text.splitlines()):
                try:outcome=json.loads(line)
                except ValueError:continue
                if isinstance(outcome,dict):break
            receipt=load(folder/'reservation-evidence.json')
            state=receipt.get('submissionStatus') or outcome.get('status') or 'unverified_return'
            row.update(status=state if run.returncode==0 else 'held',exitCode=run.returncode,
                       finishedAt=datetime.now(KST).isoformat(),log=str(log_path),lastOutput=text[-1800:])
            write(batch_path,batch);observe()
            print(json.dumps(row,ensure_ascii=False),flush=True)
            if any(t in text for t in ('user_takeover','manual_stop','unassigned','user-owned',
                                        'daily_call_budget','EGO_EXEC_DISABLED')):
                batch['status']='stopped';write(batch_path,batch);return batch
    batch['status']='attempts_finished';write(batch_path,batch)
    return batch


def cycle(now=None):
    """Direct scheduled execution of the bounded, explicitly approved experiment.

    One slot per tick; a held article never consumes every subsequent tick.
    Content/auth/manual holds and uncertain effects are never automatically replayed.
    """
    import os
    from common.collection_observability import locked
    from common.channel_parameters import configure_naver, folder_for, monitor
    if load(ROOT/'dashboard/data/daily_schedule.json').get('operatingMode')=='adaptive':
        return None  # Operating allocations supply volume; original cohort receipts remain intact.
    config=load(CONFIG)
    if not config or config.get('status')!='active':return None
    now=now or datetime.now(KST);day=now.date().isoformat()
    if not config['startDate']<=day<=config['enrollmentEnd']:
        return {'status':'outside_approved_experiment_window','enrollmentEnd':config['enrollmentEnd'],
                'nextAction':'Review measured experiment results before extending enrollment'}
    if (Path.home()/'EGO_EXEC_DISABLED').exists():
        return {'status':'manual_stop_preserved','nextAction':'Explicitly restore execution before resuming'}
    from common import work_agenda as agendas
    if agendas.current():return None  # Never take over another owner's agenda.
    engine=configure_naver(day)
    if engine.pipeline_busy():return {'status':'busy','nextAction':'Next scheduled tick; no competing writer'}
    state_path=CONFIG.parent/'workflow-cycle.json'
    try:
        with locked(CONFIG.parent/'workflow-cycle-owner'):
            if engine.pipeline_busy():return {'status':'busy'}
            config=load(CONFIG)
            if config.get('callsByDate',{}).get(day,0)>=config['maxModelCallsPerDay']:
                return {'status':'daily_budget_hold','nextAction':'Resume under the next approved day budget; no repeated model calls'}
            monitor(now=now)  # Rebuild stale running flags from durable publication evidence.
            state=load(state_path) or {'jobs':{}}
            state.update(checkedAt=now.isoformat(),experimentId=config['id'],owner='direct_naver_workflow_timer')
            jobs=state.setdefault('jobs',{});candidates=[]
            schedule=load(ROOT/'dashboard/data/daily_schedule.json')['naver']
            for account in config['accounts']:
                for slot in schedule[account]['slots']:
                    args={'action':'naver','date':day,'account':account,'slot':slot}
                    if not approved_request('parameters',args):continue
                    due=datetime.strptime(day+' '+slot,'%Y-%m-%d %H:%M').replace(tzinfo=KST)
                    if due-now>timedelta(minutes=95):continue
                    key=day+'|'+account+'|'+slot
                    if protected_slot(account,day,slot):continue
                    job=jobs.get(key,{})
                    if job.get('status') in ('verified_reserved','held','unknown'):continue
                    if job.get('status')=='running':
                        job.update(status='unknown',blocker='previous_cycle_interrupted',
                                   nextAction='Reconcile receipts and browser state; do not resubmit')
                        continue
                    folder=experiment_folder(folder_for('naver_blog_posting',day,account+'-'+slot.replace(':','')),account,day,slot)
                    # Historical/manual attempts retain their own recovery authority.
                    receipt=load(folder/'reservation-evidence.json')
                    if receipt or load(folder/'workflow-calls.json').get('calls'):
                        jobs[key]={'status':'held','account':account,'slot':slot,'folder':str(folder),
                                   'blocker':'existing_attempt_requires_reconciliation',
                                   'nextAction':'Inspect saved attempt without replaying authoring/submission'}
                        continue
                    candidates.append((due,key,account,slot,folder))
            if not candidates:
                state['status']='waiting_or_preserved';write(state_path,state)
                return {'status':state['status'],'jobs':len(jobs)}
            due,key,account,slot,folder=min(candidates,key=lambda row:row[0])
            target=due
            if target<now+timedelta(minutes=55):
                target=(now+timedelta(minutes=65)).replace(second=0,microsecond=0)
                target+=timedelta(minutes=-target.minute%10)
            if target.date().isoformat()!=day:
                state['status']='same_day_window_closed';write(state_path,state)
                return {'status':state['status'],'nextAction':'Preserve missed slots; next approved day is independent'}
            job={'status':'running','account':account,'slot':slot,'folder':str(folder),
                 'startedAt':now.isoformat(),'owner':state['owner']}
            jobs[key]=job;state['status']='running';write(state_path,state)
            engine.RUN_OPTIONS.update(slot=slot,reserve_time=target.strftime('%Y-%m-%d %H:%M'),screen_folder=str(folder))
            try:
                value=assignment(account,folder,day,slot,create=True)
                if not value:raise ValueError('Experiment assignment unavailable; preserve prior assets')
                with scope(value,folder):
                    engine.run_basic_pipeline(account,folder=folder,reserve_time=target.strftime('%Y-%m-%d %H:%M'))
                receipt=load(folder/'reservation-evidence.json')
                if receipt.get('submissionStatus')!='verified_reserved':
                    raise ValueError('Pipeline returned without a verified reservation receipt')
                job.update(status='verified_reserved',reserveTime=receipt['reserveTime'],verifiedAt=receipt['verifiedAt'])
            except Exception as exc:
                receipt=load(folder/'reservation-evidence.json')
                uncertain=receipt.get('submissionStatus') in ('submitting','submission_unknown')
                job.update(status='unknown' if uncertain else 'held',blocker=str(exc)[:500],
                           errorType=type(exc).__name__,
                           nextAction='Verify existing external effect; never resubmit' if uncertain else
                                      'Resolve this article blocker; other approved slots continue on subsequent ticks')
            job['finishedAt']=datetime.now(KST).isoformat()
            state.update(status=job['status'],lastJob=key);write(state_path,state)
            monitor();return {**job,'job':key}
    except TimeoutError:
        return {'status':'busy','nextAction':'Cycle owner active; wait for next scheduled tick'}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=('activate','observe','run','run-all'))
    parser.add_argument('--date',default=datetime.now(KST).date().isoformat())
    parser.add_argument('--account',choices=ACCOUNTS)
    parser.add_argument('--slot')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--prepared-dir')
    args = parser.parse_args()
    if args.action == 'activate':
        result = activate()
    elif args.action == 'observe':
        result = observe()
    elif args.action == 'run-all':
        result = run_all(args.date)
    else:
        if not args.account or not args.slot:
            parser.error('run requires --account and --slot')
        from common.channel_parameters import configure_naver, folder_for
        engine = configure_naver(args.date)
        original = folder_for('naver_blog_posting',args.date,args.account+'-'+args.slot.replace(':',''))
        folder = experiment_folder(original,args.account,args.date,args.slot)
        if args.prepared_dir:
            requested=Path(args.prepared_dir).resolve()
            if not requested.is_relative_to((ROOT/'naver_blog_posting/output').resolve()):
                raise ValueError('Prepared directory must stay inside Naver channel output')
            folder=requested
        if protected_slot(args.account,args.date,args.slot):
            print(json.dumps({'status':'preserved_existing_slot','account':args.account,'slot':args.slot}))
            return
        when = datetime.strptime(args.date+' '+args.slot,'%Y-%m-%d %H:%M').replace(tzinfo=KST)
        prepared=(folder/'editor-content.json').is_file() and (folder/'photo-plan.json').is_file()
        lead=40 if prepared else 65  # frozen engine requires >=30 minutes after editor input
        if when < datetime.now(KST)+timedelta(minutes=lead):
            when = (datetime.now(KST)+timedelta(minutes=lead)).replace(second=0,microsecond=0)
            when += timedelta(minutes=-when.minute%10)
        if when.date().isoformat() != args.date:
            raise ValueError('No backdating or silent next-day experiment publication')
        engine.RUN_OPTIONS.update(slot=args.slot,reserve_time=when.strftime('%Y-%m-%d %H:%M'),screen_folder=str(folder))
        value=assignment(args.account,folder,args.date,args.slot,create=True)
        with scope(value,folder):
            result = engine.run_basic_pipeline(args.account,folder=folder,reserve_time=when.strftime('%Y-%m-%d %H:%M'),
                                               prepare_only=args.prepare_only)
    print(json.dumps(result,ensure_ascii=False,default=str),flush=True)

if __name__ == '__main__':
    # All adapters import common.naver_ab. Calling the canonical module keeps
    # its ContextVar shared through preparation AND submission/result display.
    from common.naver_ab import main as canonical_main
    canonical_main()
