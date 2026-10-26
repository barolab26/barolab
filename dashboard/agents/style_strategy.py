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
    """EGO sees the search tab and article; observations are not certified ranks."""
    from common.ego_executor import benchmark_blog_screen
    folder = Path(folder) if folder else ROOT / 'dashboard/data/knowledge/ego-benchmarks' / datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat() / hashlib.sha256(query.encode()).hexdigest()[:16]
    result = {'query':query,'checkedAt':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),'articles':[]}
    try:
        return benchmark_blog_screen(query, folder)
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
        system_instruction = (
            '당신은 자율 멀티채널 콘텐츠·마케팅 크루의 전문 운영진이다. '
            '우리 팀의 최우선 단일 목표는 [하루 수익 $100 달성]이다. '
            '어떻게 쓸지 정해진 고정 템플릿은 없다. 각자의 전문성으로 하루 $100 수익 달성에 가장 직결되는 고단가(CPC/RPM)·고유입·고전환 전략을 자유롭게 판단하고 자연스러운 대화체로 논의하라.\n'
            '[절대 금지(Guardrails): 허위 사실/수치 날조, AI/봇 티 내기("AI 생성", "참고사진"), 무책임한 면피 문구("공식 공고 참고", "자료 부족").]\n'
        )
        value = None
        try:
            value=generate_json(system_instruction + prompt, provider=brain['provider'], model_override=brain['model'],
                observer=observe,agent_slot=role,memory_read_only=True,reasoning_effort='medium',timeout_seconds=60,crew_actor=role,
                crew_actor_label={'radar':'레이더','jarvis':'팀장','publi':'퍼블리','trace':'트레이스','patch':'패치','doctor':'닥터'}[role],crew_task_id=task,crew_stage='post-style-planning',
                response_schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False},
                audit_directory=folder/'model-audit'/('strategy-'+role))
        except Exception:
            try:
                value=generate_json(system_instruction + prompt, provider='agy', model_override='gemini-2.5-pro',
                    observer=observe,agent_slot=role,memory_read_only=True,timeout_seconds=45,crew_actor=role,
                    crew_actor_label={'radar':'레이더','jarvis':'팀장','publi':'퍼블리','trace':'트레이스','patch':'패치','doctor':'닥터'}[role],crew_task_id=task,crew_stage='post-style-planning',
                    response_schema={'type':'object','properties':properties,'required':list(properties),'additionalProperties':False})
            except Exception:
                value = {'message': f'{role} 전략 수립: {topic} 핵심 정보와 수익화 동선 구성'}
                if 'keyword' in properties:
                    value['keyword'] = topic[:50] if len(topic) >= 2 else identity
                if 'writingGuide' in properties:
                    value['writingGuide'] = f'{topic}에 대한 명확한 핵심 안내와 단계별 설명, 관련 제휴·애드센스 유입 동선을 포함한다.'
                routes.append({'provider': 'host', 'model': 'fallback-strategy'})
        if not routes or not routes[-1].get('model'):routes.append({'provider':'host','model':'fallback-strategy'})
        transcript.append({'actor':role,'model':routes[-1]['model'],'result':value})
        progress.setdefault('calls',[]).append({'fingerprint':fingerprint,'transcript':transcript[-1]})
        progress['calls']=progress['calls'][-12:]
        write(folder/'planning-progress.json',progress)
        recipient='radar' if role=='jarvis' and value.get('benchmarkNeeded') is True else 'publi' if role in ('jarvis','radar') else 'jarvis'
        last_reply=emit_work_event(actor=role,actor_label=role,task_id=task,phase='completed',stage='post-style-planning',
            parent_request_id=last_reply,requested_to=recipient,model=routes[-1]['model'],message_kind='staff_reply',output_kind=value['message'])
        return value
    message={'type':'string','minLength':1,'maxLength':800}
    existing_draft=load(folder/'editor-content.json') or load(folder/'article.json') or parameters.get('existingDraft',{})
    channel_purposes = {
        'naver': '소모성 비실명 네이버 블로그: 본진 리스크를 방어하며 네이버 검색 트래픽을 CF 블로그(애드센스)로 넘기는 유입 브릿지. 계정 사리기보다 강력한 후킹, 외부 링크 유입 및 키워드 점유가 핵심 목적.',
        'cf': '핵심 캐시카우 (하루 $100 애드센스 수익 기지): 양질의 정보와 체류시간 확보, 고단가 광고 배치 최적화 및 외부 트래픽 흡수가 핵심 목적.',
        'threads': 'SNS 고속 유입 채널: 피드 후킹과 첫 댓글 브릿지를 통해 CF 블로그로 대량 트래픽을 넘기는 것이 핵심 목적.',
        'kin': '지식인 맞춤형 솔루션 제공 및 CF 블로그 신뢰 유입을 만드는 전초기지.',
    }
    purpose = channel_purposes.get(channel, '하루 $100 수익 창출 및 트래픽 유입 기여')
    from common.asset_map import get_asset_map_summary, match_synergy_cluster, get_account_pacing_strategy, match_monetization_options
    asset_summary = get_asset_map_summary()
    synergy = match_synergy_cluster(topic)
    pacing = get_account_pacing_strategy(identity) if channel == 'naver' else {'mode': 'standard', 'instruction': '채널 고유 유입 극대화'}
    monetization = match_monetization_options(topic, channel=channel)

    screen_directive = channel == 'naver' and any(d.get('id') == 'ceo-directive:ego-screen-execution' and d.get('active')
                                                 for d in index.get('operatingDirectives', []))
    if not screen_directive:
        fast_prompt = (
            '팀장으로서 전사 자산 시너지와 계정 수명 7:3 페이싱을 고려해 이번 안건의 핵심 타깃 키워드(keyword) 1개와 실행 방향(writingGuide)을 즉시 확정하라.\n'
            + asset_summary + '\n'
            f'[채널 비즈니스 목적(Why)] {purpose}\n'
            f'[삼각 편대 시너지 대상] 연계 CF 블로그: {synergy["targetDomain"]} ({synergy["niche"]})\n'
            f'[계정 7:3 수명 페이싱 룰] {pacing["instruction"]}\n'
            f'[수익화·제휴 옵션(CPA/CPC/CPS)] {json.dumps(monetization, ensure_ascii=False)}\n'
            + 'JSON message,keyword,writingGuide.\n'
            + json.dumps({'identity':identity,'topic':topic,'channel':channel,'businessPurpose':purpose,'synergy':synergy,'pacing':pacing,'monetization':monetization,'agenda':agenda,'existingDraftTitle':existing_draft.get('title')},ensure_ascii=False)
        )
        instructions = call('jarvis', fast_prompt, {
            'message': message,
            'keyword': {'type': 'string', 'minLength': 2, 'maxLength': 60},
            'writingGuide': {'type': 'string', 'minLength': 1, 'maxLength': 5000},
        })
        keyword = instructions['keyword']
        observed = {'query': keyword, 'checkedAt': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(), 'articles': [], 'status': 'fast_track'}
    else:
        publi_prompt = (
            '퍼블리로서 전사 자산 시너지와 계정 수명 페이싱을 고려해 이번 안건의 핵심 앵글과 타깃 키워드 1개를 제안하라.\n'
            + asset_summary + '\n'
            f'[채널 비즈니스 목적(Why)] {purpose}\n'
            f'[삼각 편대 시너지 대상] 연계 CF 블로그: {synergy["targetDomain"]} ({synergy["niche"]})\n'
            f'[계정 7:3 수명 페이싱 룰] {pacing["instruction"]}\n'
            f'[수익화·제휴 옵션(CPA/CPC/CPS)] {json.dumps(monetization, ensure_ascii=False)}\n'
            + 'JSON message,keyword.\n'
            + json.dumps({'identity':identity,'topic':topic,'channel':channel,'businessPurpose':purpose,'synergy':synergy,'pacing':pacing,'monetization':monetization,'agenda':agenda,'existingDraftTitle':existing_draft.get('title')},ensure_ascii=False)
        )
        request=call('publi', publi_prompt, {'message':message,'keyword':{'type':'string','minLength':2,'maxLength':60}})
        keyword=request['keyword']
        observed=benchmark(keyword,folder)
        jarvis_prompt = (
            '팀장으로서 전사 자산 시너지와 계정 수명 7:3 페이싱에 맞춰 이번 콘텐츠의 실행 방향(writingGuide)을 즉시 확정하라.\n'
            + asset_summary + '\n'
            f'[채널 비즈니스 목적(Why)] {purpose}\n'
            f'[삼각 편대 시너지 대상] 연계 CF 블로그: {synergy["targetDomain"]} ({synergy["niche"]})\n'
            f'[계정 7:3 수명 페이싱 룰] {pacing["instruction"]}\n'
            f'[수익화·제휴 옵션(CPA/CPC/CPS)] {json.dumps(monetization, ensure_ascii=False)}\n'
            + 'JSON message,writingGuide.\n'
            + json.dumps({'keyword':keyword,'businessPurpose':purpose,'synergy':synergy,'pacing':pacing,'monetization':monetization,'publiProposal':request,'priorDiscussion':transcript,'observedBenchmark':observed},ensure_ascii=False)
        )
        instructions=call('jarvis', jarvis_prompt,
            {'message':message,'writingGuide':{'type':'string','minLength':1,'maxLength':5000}})
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
        can_trial = decision['approveExperiment'] and value is not None and value != baseline_value
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
