"""Daily evidence-led crew discussion; only memory parameters evolve, never engines."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {'bodyFontSize':(16,19), 'headingFontSize':(19,24,28),
          'summaryFontSize':(19,24), 'summaryBold':(True,False), 'textAlign':('left','center'),
          'leadStyle':('summary-first','question-first','context-first'), 'tone':('polite','concise','friendly'),
          'headingRhythm':('short-question','action-step'), 'summaryStructure':('three-lines','comparison-table')}


def comparable(posts, now):
    """Missing reports are unknown, never zero or a losing variant."""
    eligible = []
    for post in posts:
        try:
            age = (now - datetime.fromisoformat(post['publishedAt'].replace('Z','+00:00'))).days
        except (KeyError, TypeError, ValueError):
            continue
        metrics = post.get('measurements', {})
        search = metrics.get('gsc', {})
        try:
            days = (datetime.fromisoformat(search['end']) - datetime.fromisoformat(search['start'])).days
        except (KeyError, TypeError, ValueError):
            continue
        if age >= 7 and days >= 6 and search.get('impressions', 0) >= 100 and post.get('styleVariantId'):
            eligible.append(post)
    return eligible



def benchmark(query, folder=None):
    """Observed search order is not a claimed organic rank; unavailable articles never block publishing."""
    from playwright.sync_api import sync_playwright
    from common.browser_session import PageScope, connect_sync
    from common.ubuntu_naver_browser import account_paths
    from urllib.parse import quote
    import re
    result = {'query':query,'checkedAt':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),'articles':[]}
    try:
        binary, profile, _ = account_paths(9440)
        with sync_playwright() as playwright, PageScope() as pages:
            browser = connect_sync(playwright,'http://127.0.0.1:9440',binary,profile)
            page = pages.acquire(browser.contexts[0], lambda p: False)
            page.bring_to_front()
            response = page.goto('https://search.naver.com/search.naver?where=blog&query='+quote(query),wait_until='domcontentloaded',timeout=10000)
            if not response or response.status != 200:
                return result
            candidates = page.locator('a[href*="blog.naver.com"]').evaluate_all('(xs)=>xs.filter(x=>x.checkVisibility()).map(x=>({url:x.href,title:x.innerText}))')
            unique = []
            for item in candidates:
                match = re.match(r'https://(?:m\.)?blog.naver.com/([A-Za-z0-9_-]+)/(\d+)',item['url'])
                if match:
                    address = 'https://m.blog.naver.com/'+match[1]+'/'+match[2]
                    if address not in [x['url'] for x in unique]:
                        unique.append({'url':address,'searchTitle':item['title'][:160],'observedOrder':len(unique)+1,'organicRank':None})
            for item in unique[:3]:
                try:
                    response = page.goto(item['url'],wait_until='domcontentloaded',timeout=8000)
                    if not response or response.status != 200:
                        continue
                    content = page.locator('.se-main-container, #postViewArea').first
                    content.wait_for(state='visible',timeout=3000)
                    text = content.inner_text()
                    if len(text)<200:
                        continue
                    paragraphs = [x.strip() for x in text.split('\n') if x.strip()]
                    item.update(bodyExcerpt=text[:1000],bodySha256=hashlib.sha256(text.encode()).hexdigest(),
                                paragraphCount=len(paragraphs),averageParagraphLength=round(sum(map(len,paragraphs))/len(paragraphs)),
                                images=content.locator('img').count(),tables=content.locator('table').count(),httpStatus=200,
                                layoutBlocks=content.locator('.se-component').evaluate_all('(xs)=>xs.slice(0,30).map(x=>({type:x.classList.contains("se-image")?"image":x.classList.contains("se-table")?"table":"text",preview:(x.innerText||"").slice(0,100)}))'))
                    if folder:
                        page.screenshot(path=str(Path(folder)/('benchmark-'+str(item['observedOrder'])+'.png')))
                    result['articles'].append(item)
                except Exception:
                    continue
    except Exception as exc:
        result['errorType'] = type(exc).__name__
    return result



def plan_post(identity, topic, folder, parameters, channel='naver'):
    """Select this post's keyword, inspect its real search results, then agree its presentation."""
    from common.collection_observability import load, write
    from common.llm_settings import get_agent_brain
    from common.llm_client import generate_json
    from common.crew_chat_bridge import emit_work_event, work_task_id
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'planning.json'
    previous=load(path)
    if previous.get('keyword') and previous.get('status')=='agreed':
        previous.setdefault('planningId','planning:'+hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:24])
        write(path,previous)
        return previous
    from dashboard.agents.synapse import cached_index
    index=cached_index(ROOT)
    profile=index.get('accountProfiles',{}).get(identity,{})
    agenda={'channel':channel,'account':identity,'brand':profile.get('brand',identity),'target':profile.get('target',''),'publicationDate':folder.parent.name,'slot':folder.name.rsplit('-',1)[-1]}
    agenda.update(parameters.get('agenda',{}))
    meeting_policy=index.get('meetingPolicy',{})
    transcript=[];task=work_task_id(folder)
    last_reply=''
    def call(role, prompt, properties):
        nonlocal last_reply
        brain=get_agent_brain(role);routes=[]
        fingerprint=hashlib.sha256((role+prompt+json.dumps(properties,sort_keys=True)).encode()).hexdigest()
        progress=load(folder/'planning-progress.json')
        cached=next((row for row in progress.get('calls',[]) if row.get('fingerprint')==fingerprint),None)
        if cached:
            transcript.append(cached['transcript'])
            return cached['transcript']['result']
        def observe(provider, requested_model, state, **metadata):
            if state=='returned':routes.append({'provider':provider,'model':metadata.get('actual_model')})
        value=generate_json('회의실 message는 한국어 1~2문장, 110자 이내로 완결하고 마침표로 끝내라. 과장·더미 진행 보고는 금지한다.\n'+prompt,provider=brain['provider'],model_override=brain['model'],
            observer=observe,agent_slot=role,memory_read_only=True,timeout_seconds=120,crew_actor=role,
            crew_actor_label={'radar':'레이더','jarvis':'팀장','publi':'퍼블리','trace':'트레이스','patch':'패치','doctor':'닥터'}[role],crew_task_id=task,crew_stage='post-style-planning',
            response_schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False},
            audit_directory=folder/'model-audit'/('strategy-'+role))
        if not routes or not routes[-1].get('model'):raise ValueError('Actual planning model not observed')
        transcript.append({'actor':role,'model':routes[-1]['model'],'result':value})
        progress.setdefault('calls',[]).append({'fingerprint':fingerprint,'transcript':transcript[-1]})
        progress['calls']=progress['calls'][-12:]
        write(folder/'planning-progress.json',progress)
        recipient='radar' if role=='jarvis' and value.get('benchmarkNeeded') is True else 'publi' if role in ('jarvis','radar') else 'jarvis'
        last_reply=emit_work_event(actor=role,actor_label=role,task_id=task,phase='completed',stage='post-style-planning',
            parent_request_id=last_reply,requested_to=recipient,model=routes[-1]['model'],message_kind='staff_reply',output_kind=value['message'])
        return value
    message={'type':'string','minLength':1,'maxLength':150}
    opener=meeting_policy.get('openingRole','jarvis')
    if opener in ('jarvis','publi','radar','trace','patch','doctor'):
        call(opener,'지식그래프에 정한 개회 규칙으로 이번 발행 안건의 회의를 열어라. 실제 계정 브랜드와 발행일·슬롯을 밝히고 어떤 키워드를 공략할지 논의를 시작하라. 아직 조사·발행·수익이 완료된 것처럼 말하지 마라. JSON message.\n'+json.dumps({'agenda':agenda,'openingInstruction':meeting_policy.get('openingInstruction',''),'profile':profile},ensure_ascii=False),{'message':message})
    existing_draft=load(folder/'editor-content.json') or load(folder/'article.json') or parameters.get('existingDraft',{})
    request=call('publi','이번 계정과 주제를 발행하려는 퍼블리다. 기존 원고가 있으면 그 주제를 유지한 실행안을 제안하고, 없으면 정확한 키워드 하나를 제안하고, 어떤 독자·구성·서식으로 쓸지 팀장에게 짧게 질문하라. 기발행·검색 성과를 꾸미지 마라. JSON message,keyword.\n'+json.dumps({'identity':identity,'topic':topic,'memoryStyle':parameters,'channel':channel,'agenda':agenda,'existingDraftTitle':existing_draft.get('title'),'priorDiscussion':transcript},ensure_ascii=False), {'message':message,'keyword':{'type':'string','minLength':2,'maxLength':60}})
    keyword=request['keyword']
    direction=call('jarvis','퍼블리의 보고와 지식그래프를 읽고 이번 원고의 방향을 정하라. 성과가 나쁘다고 단정하지 말고 실측 여부를 구분하라. 경쟁글 확인이 필요하면 레이더에게 이 정확한 키워드로 2~3개를 조사하도록 지시하라. 필요한 경우에만 트레이스·닥터·패치 최대 2명을 자문 요청하라. JSON message,researchTask,benchmarkNeeded,consultAgents.\n'+json.dumps({'publiRequest':request,'memoryStyle':parameters,'agenda':agenda,'priorDiscussion':transcript},ensure_ascii=False), {'message':message,'researchTask':{'type':'string','minLength':1,'maxLength':600},'benchmarkNeeded':{'type':'boolean'},'consultAgents':{'type':'array','maxItems':2,'items':{'type':'string','enum':['trace','doctor','patch']}}})
    observed=benchmark(keyword,folder) if direction['benchmarkNeeded'] is True else {'query':keyword,'checkedAt':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),'articles':[],'status':'not_requested_by_jarvis'}
    if direction['benchmarkNeeded']:
        call('radar','팀장의 지시를 수행한 레이더다. 실제 검색 결과 본문·배치 관측만 근거로 퍼블리에게 어떤 형식을 참고할지 제안하라. 못 읽었다면 그대로 보고하고 다른 방식의 제안을 하라. 미관측 순위와 성과는 만들지 마라. JSON message.\n'+json.dumps({'jarvisDirective':direction,'keyword':keyword,'observedBenchmark':observed},ensure_ascii=False), {'message':message})
    for role in [r for r in dict.fromkeys(direction['consultAgents']) if r in ('trace','doctor','patch')][:2]:
        call(role,'팀장가 요청한 역할별 자문을 하라. 트레이스는 실측 성과, 닥터는 기존 글의 개선 경험, 패치는 도구로 구현 가능한 서식을 살핀다. 주어진 지식과 관측에 없는 성공·수치는 꾸미지 말고 의견을 한국어로 제시하라. JSON message.\n'+json.dumps({'keyword':keyword,'jarvisDirective':direction,'priorDiscussion':transcript,'memoryStyle':parameters,'observedBenchmark':observed},ensure_ascii=False), {'message':message})
    instructions=call('jarvis','퍼블리의 업무 보고, 실제 조사 결과와 직원 의견을 읽고 최종 실행 방향을 정하라. 이번 원고의 정확한 키워드와 실제 검색 결과 본문을 보고, 우리 독자에 맞춰 참고할 제목·첫문단·소제목·사진·표 배치 방식을 한국어로 정하라. 본문 복제·가짜 체험·미관측 순위는 금지한다. 벤치마킹이 비어 있으면 지식그래프의 기존 스타일 또는 다른 접근을 택하고, 발행을 반려하지 마라. 이번 글의 스타일 실험은 성과 검증 전 가설이다. JSON message,writingGuide.\n'+json.dumps({'keyword':keyword,'priorDiscussion':transcript,'observedBenchmark':observed,'memoryStyle':parameters},ensure_ascii=False),
        {'message':message,'writingGuide':{'type':'string','minLength':1,'maxLength':1200}})
    result={'status':'agreed','agenda':agenda,'keyword':keyword,'identity':identity,'channel':channel,'parameters':parameters,
        'writingGuide':instructions['writingGuide'],'benchmark':observed,'transcript':transcript,
        'createdAt':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),'outcome':'awaiting_url_measurements','causalClaim':False}
    result['planningId']='planning:'+hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:24]
    write(path,result)
    return result


def review_once(force=False):
    from common import work_agenda as agendas
    if agendas.enabled() and not agendas.current():
        day=datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
        return {'status':'queued','businessAgendaId':agendas.propose('style',day,title='기존 글 실측에 따른 스타일 전략 검토 · '+day,
            project='legacy_remodel',source={'date':day},completion='실측·미수집을 구분한 전략 결정과 적용 여부 기록',priority=30)}
    import fcntl
    from common.collection_observability import load, write
    from common.runtime_locks import runtime_lock_path
    from common.channel_parameters import policy, styles
    from common.llm_settings import get_agent_brain
    from common.llm_client import generate_json
    from common.crew_chat_bridge import emit_work_event
    from dashboard.agents.synapse import edge, build_index

    data = ROOT / 'dashboard/data'
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    day = now.date().isoformat()
    state_path = data / 'style-strategy-review.json'
    lock_path = runtime_lock_path(data / 'style-strategy-review.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+b') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'busy'}
        previous = load(state_path)
        if not force and previous.get('date') == day:
            return {'status':'already_reviewed'}
        write(state_path, {'date':day,'status':'discussing','startedAt':now.isoformat()})
        graph = load(data / 'memory_graph.json')
        plan = policy()
        posts = [{**node,'id':identity} for identity,node in graph.get('nodes',{}).items() if node.get('type')=='Post']
        evidence = {account:comparable([p for p in posts if p.get('domain')=='blog.naver.com/'+row['blogId']], now)[-10:] for account,row in plan['naver'].items()}
        account_for_benchmark = list(plan['naver'])[now.toordinal() % len(plan['naver'])]
        benchmark_result = benchmark(plan['naver'][account_for_benchmark]['target'])
        write(data / 'style-benchmark.json', benchmark_result)
        task = 'style-strategy:'+day
        transcript = []

        def discuss(role, instruction, schema):
            brain = get_agent_brain(role)
            observed = []
            def observer(provider, requested_model, state, **metadata):
                if state == 'returned':
                    observed.append({'provider':provider,'actualModel':metadata.get('actual_model')})
            result = generate_json('회의실 message는 한국어 1~2문장, 110자 이내로 완결하고 마침표로 끝내라.\n'+instruction+'\n'+json.dumps({'effectiveDate':plan['effectiveDate'],'evidence':evidence,'benchmark':benchmark_result,'priorDiscussion':transcript},ensure_ascii=False),
                provider=brain['provider'], model_override=brain['model'], response_schema=schema,
                observer=observer, agent_slot=role, timeout_seconds=45, memory_read_only=True, crew_actor=role,
                crew_actor_label={'trace':'트레이스','radar':'레이더','jarvis':'팀장'}[role],
                crew_task_id=task, crew_stage='style-strategy-discussion')
            if not observed or not observed[-1].get('actualModel'):
                raise ValueError('Actual strategy model not observed')
            transcript.append({'actor':role,'model':observed[-1]['actualModel'],'result':result})
            emit_work_event(actor=role,actor_label=role,task_id=task,phase='completed',stage='style-strategy-discussion',
                model=observed[-1]['actualModel'],message_kind='staff_reply',output_kind=result['message'])
            return result

        message = {'type':'string','minLength':1,'maxLength':150}
        schema = lambda props: {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
        try:
            discuss('jarvis','총괄 팀장로서 기존 글별 성과·실패와 벤치마킹 자료를 보고 이번 회의의 개선 가설과 직원 조사 과제를 정하라. 미수집 데이터는 모른다고 명시하라. JSON message.',schema({'message':message}))
            discuss('trace','URL별 실제 성과와 보고기간만 확인해 회의실에 한국어로 보고하라. 데이터가 없으면 측정 대기라고 말하라. 수익·체류시간을 만들거나 사이트 수익을 글에 배분하지 마라. JSON message.',schema({'message':message}))
            proposal = discuss('radar','트레이스 발언과 실제 벤치마킹 본문 특징을 읽고 다음 스타일 실험을 하나 제안하라. 시간표는 바꾸지 말고 단 하나의 서식 파라미터만 선택하라. 근거가 없으면 초기 페르소나 기준선을 유지하자고 제안하라. message는 한국어.',schema({'message':message,'account':{'type':'string','enum':list(plan['naver'])},'field':{'type':'string','enum':list(FIELDS)},'value':{'type':'string'}}))
            decision = discuss('jarvis','트레이스와 레이더의 실제 발언에 응답하라. 초기 기준선은 7일 유지하라. 그 후 보고가 부족해도 탐색적 실험을 제안할 수 있으나 측정 없이는 개선이라고 판정하지 마라. 예약·발행 완료를 꾸며 말하지 마라. 한국어 message와 approveExperiment를 반환하라.',schema({'message':message,'approveExperiment':{'type':'boolean'}}))
        except Exception as exc:
            write(state_path, {'date':day,'status':'model_unavailable','errorType':type(exc).__name__,'transcript':transcript})
            return {'status':'model_unavailable'}
        account, field = proposal['account'], proposal['field']
        choices = {str(v).lower():v for v in FIELDS[field]}
        value = choices.get(proposal['value'].lower())
        measured = evidence[account]
        # A bounded single-variable trial is a hypothesis, never proof of causal uplift.
        active = next((n for n in graph.get('nodes',{}).values() if n.get('type')=='StyleVariant' and n.get('account')==account and n.get('active')), {})
        try:
            mature = (now.date() - datetime.fromisoformat(active['effectiveDate']).date()).days >= 7
        except (KeyError, ValueError):
            mature = False
        baseline_value = active.get('parameters', {}).get(field)
        can_trial = decision['approveExperiment'] and mature and value is not None and value != baseline_value
        graph_lock = runtime_lock_path(data / 'synapse.lock')
        with graph_lock.open('a+b') as writer:
            fcntl.flock(writer, fcntl.LOCK_EX)
            graph = load(data / 'memory_graph.json')
            graph['nodes'].setdefault('memory:hub', {'type':'MemoryHub'})
            mid = 'strategy:meeting:'+day
            graph['nodes'][mid] = {'type':'StrategyMeeting','createdAt':now.isoformat(),'transcript':transcript,
                'benchmark':benchmark_result,'decision':('single_variable_trial' if measured else 'exploratory_trial_measurement_missing') if can_trial else 'preserve_baseline_measure_first','causalClaim':False}
            edge(graph,'memory:hub',mid,'contains')
            for key,row in plan['naver'].items():
                sid = 'style:naver:'+key+':baseline'
                graph['nodes'].setdefault(sid, {'type':'StyleVariant','account':key,'domain':'blog.naver.com/'+row['blogId'],
                    'parameters':styles(key),'active':True,'effectiveDate':plan['effectiveDate'],'createdAt':now.isoformat(),
                    'basis':'CEO persona baseline; performance not established','synapseWeight':0})
                edge(graph,mid,sid,'reviews_style')
                for post in evidence[key]:
                    edge(graph,mid,post['id'],'reviews_measured_outcome')
            if benchmark_result['articles']:
                bid = 'benchmark:'+day
                graph['nodes'][bid] = {'type':'ObservedBenchmark',**benchmark_result}
                edge(graph,mid,bid,'references_observed_articles')
            if can_trial:
                baseline = next(n for n in graph['nodes'].values() if n.get('type')=='StyleVariant' and n.get('account')==account and n.get('active'))
                params = {**baseline['parameters'],field:value}
                identity = 'style:naver:'+account+':'+hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()[:12]
                for node in graph['nodes'].values():
                    if node.get('type')=='StyleVariant' and node.get('account')==account:
                        node['active'] = False
                graph['nodes'][identity] = {'type':'StyleVariant','account':account,'parameters':params,'active':True,
                    'effectiveDate':(now+timedelta(days=1)).date().isoformat(),'createdAt':now.isoformat(),
                    'changedField':field,'baselinePostIds':[p['id'] for p in measured],'synapseWeight':0,'causalClaim':False}
                edge(graph,mid,identity,'proposes_trial')
            write(data / 'memory_graph.json',graph)
            write(data / 'synapse-recipes.json',build_index(graph))
        result = {'date':day,'status':'completed','meetingId':mid,'decision':graph['nodes'][mid]['decision'],'transcript':transcript}
        write(state_path,result)
        return result
