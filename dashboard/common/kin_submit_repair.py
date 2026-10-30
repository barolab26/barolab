"""One exact, ledger-bound editor repair; uncertain submissions are verified only."""
import json
from contextlib import closing,contextmanager
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def click_existing(page, document, ownership, before_submit):
    from naver_kin import posting as kin
    qid=kin.question_id(document['question']['question_url'])
    if kin.question_id(page.url)!=qid:
        raise ValueError('Editor question mismatch')
    kin._naver_browser__check_service_state(page)
    soup=kin._naver_browser_BeautifulSoup(page.content(),'html.parser')
    title=soup.select_one('.endTitleSection')
    if title is None:raise ValueError('Current question title unavailable')
    for hidden in title.select('.blind,svg'):hidden.decompose()
    normal=kin._naver_browser__normalized
    if normal(title.get_text(' ',strip=True))!=normal(document['question']['title']) or normal(page.locator('.questionDetail').inner_text())!=normal(document['question']['body']):
        raise ValueError('Question changed; editor preserved')
    if not ownership.get('known') or not ownership.get('complete') or ownership.get('answer_ids'):
        raise ValueError('Existing answer or incomplete ownership; no click')
    kin._naver_browser_wait_for_editor_ready(page)
    from common.kin_screen import editor_paragraphs,visual_click,ScreenPage
    from common.kin_answer_view import semantic_paragraphs
    rendered='\n'.join(semantic_paragraphs(page,document['answer_text'],editor_paragraphs(page)))
    if kin._naver_browser__normalized(rendered)!=kin._naver_browser__normalized(document['answer_text']):
        raise ValueError('Editor differs from approved answer; preserved')
    links=ScreenPage(page,kin._naver_browser_ACCOUNTS[document['account']],ROOT,lambda:None,document['answer_text']).locator('.se-canvas a[href], .se-canvas .se-link[data-href]').evaluate_all('es=>es.map(e=>e.href || e.getAttribute("data-href"))')
    if document['attribution']['outboundUrl'] not in links:
        raise ValueError('Approved outbound link is not bound')
    button=page.locator('#answerRegisterButton')
    if button.count()!=1 or not button.is_visible() or not button.is_enabled():
        raise ValueError('Registration unavailable; no disabled-button bypass')
    result={};dialogs=[]
    def response_seen(response):
        if (response.url.split('?',1)[0]!='https://kin.naver.com/ajax/detail/registerAnswerForSmartEditorOne.naver'
                or response.request.method!='POST'):return
        from urllib.parse import parse_qs
        if parse_qs(response.request.post_data or '').get('docId')!=[qid]:return
        if response.status==200:
            try:
                value=response.json();answer=value.get('result',{}).get('result',{}).get('answerNo')
                if value.get('isSuccess') is True and str(answer).isdigit():result['answer_id']=str(answer)
            except (ValueError,TypeError,AttributeError):pass
    def dialog_seen(dialog):
        dialogs.append(str(dialog.message)[:300]);dialog.dismiss()
    page.on('response',response_seen);page.on('dialog',dialog_seen)
    try:
        import uuid
        folder=ROOT/'naver_kin/output/recovery'/qid/uuid.uuid4().hex
        visual_click(page,button,kin._naver_browser_ACCOUNTS[document['account']],folder,'이 승인 답변의 등록 버튼',before_click=before_submit)
        for _ in range(30):
            page.wait_for_timeout(500)
            if result or dialogs:break
        if result:
            return {**result,'answer_url':kin._naver_browser_exact_answer_url(page.url,result['answer_id']),
                    'reason':'EGO screen click observed; public verification pending','screenEvidence':str(folder)}
        for text in dialogs:kin._naver_browser__check_protection_message(text)
        return {'reason':'Submission uncertain after one click; verification only; no retry'}
    finally:
        page.remove_listener('response',response_seen);page.remove_listener('dialog',dialog_seen)


def public_evidence(account,row,document,initial=None):
    from naver_kin import posting as kin
    evidence=initial if initial is not None else kin._naver_browser_verify_public(account,row['answer_url'],document['answer_text'],document['attribution']['outboundUrl'],row['answer_id'])
    if not evidence.get('public'):
        import requests
        from common.kin_answer_view import public_card_evidence
        response=requests.get(row['answer_url'],timeout=20,allow_redirects=False,headers={'User-Agent':'Mozilla/5.0'})
        card=public_card_evidence(response,account,row['question_id'],row['answer_id'],document['answer_text'],document['attribution']['outboundUrl'])
        if card:evidence.update(card,answer_url=row['answer_url'])
    if evidence.get('verified'):
        evidence.setdefault('httpStatus',200)
        return evidence
    if not evidence.get('public'):return evidence
    # Read-only ownership fetch does not acquire the publisher's mutation lock.
    import requests,websocket
    from urllib.parse import urlsplit
    from common.ubuntu_naver_browser import account_paths,process_identity
    port={'adinfo0905':9231,'stone0747':9230}[account]
    _,profile,_=account_paths(port)
    if not process_identity(port,profile):return evidence
    try:
        tabs=requests.get(f'http://127.0.0.1:{port}/json/list',timeout=.3).json()
        tab=next((t for t in tabs if t.get('type')=='page' and urlsplit(t.get('url','')).hostname=='kin.naver.com'),None)
        if not tab:return evidence
        address=tab.get('webSocketDebuggerUrl','');parsed=urlsplit(address)
        if parsed.scheme!='ws' or parsed.hostname not in ('localhost','127.0.0.1') or parsed.port!=port:return evidence
        expression='(async()=>{const r=await fetch('+json.dumps(row['answer_url'])+',{credentials:"include",signal:AbortSignal.timeout(8000)});return {status:r.status,html:await r.text()};})()'
        with closing(websocket.create_connection(address,timeout=10,suppress_origin=True)) as ws:
            ws.send(json.dumps({'id':917,'method':'Runtime.evaluate','params':{'expression':expression,'awaitPromise':True,'returnByValue':True}}))
            for _ in range(20):
                response=json.loads(ws.recv())
                if response.get('id')==917:break
            else:return evidence
        value=response.get('result',{}).get('result',{}).get('value',{})
        if value.get('status')!=200:return evidence
        ownership=kin._naver_browser__parse_question_ownership(value.get('html',''),account,str(row['question_id']))
        if str(row['answer_id']) in ownership.get('verified_owned_answer_ids',[]):
            evidence.update(account=account,verified=True,ownership_evidence='read-only authenticated exact-question CDP fetch; _myAnswer and owner controls; no navigation or click',reason='Public body/link and exact authenticated owner matched',httpStatus=200)
    except (OSError,ValueError,RuntimeError,requests.RequestException,websocket.WebSocketException):pass
    return evidence


def remember(result,root=ROOT):
    if result.get('publicVerified') is not True:return
    import datetime,hashlib
    from common import runtime_locks as fcntl
    from common.runtime_locks import runtime_lock_path
    from common.collection_observability import write,locked,load
    from dashboard.agents.synapse import build_index
    data=Path(root)/'dashboard/data';path=data/'memory_graph.json'
    lock=runtime_lock_path(data/'synapse.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+b') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        graph=json.loads(path.read_text()) if path.exists() else {'nodes':{},'edges':[]}
        nodes=graph['nodes'];edges=graph['edges'];now=datetime.datetime.now(datetime.timezone.utc).isoformat()
        reported='problem:KIN_PREPARED_EDITOR_SUBMISSION';solution='solution:EGO_VERIFIED_SCREEN_CLICK'
        nodes.setdefault('memory:hub',{'type':'MemoryHub'})
        nodes.setdefault(reported,{'type':'ProblemPattern','pattern':'KIN_PREPARED_EDITOR_SUBMISSION','status':'observed_prepared_editor','causalClaim':False,'resolvedCount':0,'concreteExamples':[]})
        nodes.setdefault(solution,{'type':'SolutionPattern','pattern':'EGO_VERIFIED_SCREEN_CLICK','status':'guarded_implementation_tested','constraints':['exact approved editor','confirmed no owned answer','enabled button','durable before-submit intent','one click only','captcha never bypassed']})
        pattern=reported if result.get('clicked') else 'problem:KIN_ALERT_STALE_STATE'
        resolver=solution if result.get('clicked') else 'solution:EXACT_PUBLIC_ANSWER_RECONCILIATION'
        nodes.setdefault(pattern,{'type':'ProblemPattern','pattern':'KIN_ALERT_STALE_STATE','resolvedCount':0,'concreteExamples':[]})
        nodes.setdefault(resolver,{'type':'SolutionPattern','pattern':'EXACT_PUBLIC_ANSWER_RECONCILIATION'})
        outcome='outcome:kin-repair:'+hashlib.sha256(result['publicUrl'].encode()).hexdigest()[:24]
        created=outcome not in nodes
        if created:
            problem=nodes[pattern];problem['resolvedCount']=problem.get('resolvedCount',0)+1;problem['lastResolvedAt']=now
            problem.setdefault('concreteExamples',[]).append({'account':result['account'],'questionId':result['questionId'],'url':result['publicUrl'],'clicked':result.get('clicked',False)})
            nodes[outcome]={'type':'Outcome','publicUrl':result['publicUrl'],'verifiedAt':now,'publicVerified':True,'httpStatus':200,'clicked':result.get('clicked',False),'originalSendDay':result.get('originalSendDay'),'todayNewPublication':bool(result.get('clicked'))}
        for source,target,kind in [('memory:hub',reported,'contains'),(reported,solution,'candidate_resolution'),('memory:hub',pattern,'contains'),(pattern,resolver,'resolved_by'),(resolver,outcome,'verified_by')]:
            edge={'source':source,'target':target,'type':kind}
            if edge not in edges:edges.append(edge)
        write(path,graph);write(data/'synapse-recipes.json',build_index(graph))
    tickets=data/'ego-alerts/tickets.json'
    if tickets.exists():
        with locked(tickets.parent):
            state=load(tickets,{})
            for row in state.get('tickets',{}).values():
                if row.get('identity')==result['questionId'] and row.get('account')==result['account']:
                    row.update(status='resolved',publicUrl=result['publicUrl'],resolvedAt=now,clicked=result.get('clicked',False))
            write(tickets,state)
    return created


@contextmanager
def prepared_run(db,kin,account,question_id):
    """Resume the exact prepared editor through native cadence and quota checks."""
    with kin._naver_scheduler_file_lock(ROOT/'dashboard/data/kin-scheduler.lock') as ready:
        if not ready:raise ValueError('Scheduler owns the current run; preserve editor')
        original=db.execute('SELECT * FROM automation_slots WHERE question_id=? ORDER BY updated_at DESC LIMIT 1',(question_id,)).fetchone()
        cadence=db.execute('SELECT * FROM operating_cadence WHERE id=1').fetchone()
        question=db.execute('SELECT * FROM questions WHERE question_id=?',(question_id,)).fetchone()
        if not question or question['account']!=account or question['state']!='drafted' or any(question[k] for k in ('send_day','answer_id','answer_url','result')):
            raise ValueError('Exact unsubmitted draft required; verification only for uncertain submissions')
        if not original or original['account']!=account or original['state']!='blocked' or not cadence or cadence['active_run_id']:
            raise ValueError('Exact blocked scheduler run required; no uncertain resume')
        from common import work_agenda as agendas
        if agendas.enabled():
            current=agendas.require(project='naver_kin')
            if current['kind']=='conference':
                target=(current.get('workTarget') or current['source']).get('arguments',{})
                from common.collection_observability import load
                receipt=load(ROOT/'dashboard/data/publication-conferences'/(current['source']['conferenceId']+'.json'))
                bound=receipt.get('retryTarget') or next(iter(receipt.get('executionFailures',[])),{})
                if target.get('account')!=account or target.get('date')!=kin._naver_pipeline_today_kst() or bound.get('questionId')!=question_id:
                    raise ValueError('Prepared editor is outside the current agenda')
            else:
                agendas.bind_target({'kind':'kin-repair','arguments':{'account':account,'question_id':question_id,'date':kin._naver_pipeline_today_kst()}})
        config=json.loads(kin._naver_scheduler_CONFIG.read_text())
        kin._naver_scheduler_validate_config(config)
        if not config.get('enabled'):raise ValueError('Kin automation is disabled')
        status=kin._naver_scheduler_cadence_status(db,config,kin._naver_scheduler_now_kst())
        if status.get('nextAccount')!=account:raise ValueError('Native account cadence does not permit this editor')
        reservation=kin._naver_scheduler_reserve_run(db,config)
        if reservation.get('state')!='reserved':raise ValueError('Native cadence held: '+str(reservation.get('reason') or reservation.get('state')))
        run_id=reservation['runId']
        try:
            if reservation['account']!=account:raise ValueError('Native reservation account changed')
            with db:db.execute('UPDATE automation_slots SET question_id=? WHERE slot_id=?',(question_id,run_id))
            kin._naver_pipeline_preflight_send(db,question_id,account,run_id=run_id)
            yield run_id
        finally:
            row=db.execute('SELECT state FROM questions WHERE question_id=?',(question_id,)).fetchone()
            state=row['state'] if row else 'blocked'
            submitted=state in kin._naver_pipeline_TERMINAL_SEND
            with db:
                db.execute('UPDATE automation_slots SET state=?,reason=?,updated_at=? WHERE slot_id=?',
                           (state if submitted else 'blocked',None if submitted else 'prepared_editor_repair_held',kin._naver_pipeline_stamp(),run_id))
                if not submitted:
                    db.execute('UPDATE operating_cadence SET last_completed_at=?,last_account=?,active_run_id=NULL,active_account=NULL,active_started_at=NULL WHERE id=1 AND active_run_id=?',
                               (cadence['last_completed_at'],cadence['last_account'],run_id))
            if submitted:kin._naver_scheduler_complete_run(db,run_id)
            snapshot=json.loads(kin._naver_scheduler_STATE.read_text())
            snapshot.update(state='completed_cycle',checkedAt=kin._naver_pipeline_stamp(),runId=run_id,account=account,
                runs=[{'runId':run_id,'account':account,'state':state if submitted else 'blocked','reason':None if submitted else 'prepared_editor_repair_held'}],
                **kin._naver_scheduler_cadence_status(db,config,kin._naver_scheduler_now_kst()))
            kin._naver_scheduler_write(kin._naver_scheduler_STATE,snapshot)


def repair(account,question_id):
    if account not in ('adinfo0905','stone0747') or not isinstance(question_id,str) or not re.fullmatch(r'\d{1,24}',question_id):
        raise ValueError('Exact registered account/question required')
    from naver_kin import posting as kin
    from naver_blog_posting.posting import pipeline_lock
    from playwright.sync_api import sync_playwright
    db=kin.connect();clicked=False
    try:
        with kin.account_lock(account):
            row=db.execute('SELECT * FROM questions WHERE account=? AND question_id=?',(account,question_id)).fetchone()
            if not row:return {'ok':False,'status':'held','reason':'No approved ledger answer; existing tabs preserved'}
            document=json.loads(row['document'])
            if row['state']=='drafted':
                fresh=kin._naver_pipeline_article_snapshot(document['article']['url'],fallback_body=document['article'].get('body') if document['article'].get('scope')=='local_verified_publication' else None)
                if fresh['body_sha256']!=document['article']['body_sha256']:raise ValueError('Source changed; approved draft preserved')
                config=kin._naver_browser_account_config(account)
                with pipeline_lock(),kin._naver_browser_account_lock(account),sync_playwright() as playwright,kin._naver_browser_awake_browser(playwright,config) as browser:
                    pages=[p for c in browser.contexts for p in c.pages if 'kin.naver.com/qna/detail.naver' in p.url and kin.question_id(p.url)==question_id and p.locator('#answerRegisterButton').count()==1]
                    if len(pages)!=1:raise ValueError('Exactly one existing editor required; no new editor created')
                    page=pages[0]
                    ownership=current_ownership(page,kin,account,document['question']['question_url'],question_id)
                    def before_submit():
                        nonlocal clicked
                        kin.begin_send(db,question_id,account,run_id=run_id);clicked=True
                    with prepared_run(db,kin,account,question_id) as run_id:
                        try:result=click_existing(page,document,ownership,before_submit)
                        except Exception:
                            if clicked:kin.finish_send(db,question_id,{'reason':'Repair submission uncertain; never repeat click'})
                            raise
                        kin.finish_send(db,question_id,result)
            row=db.execute('SELECT * FROM questions WHERE question_id=?',(question_id,)).fetchone()
            if row['state']=='submitted_unverified' and not row['answer_id'] and not row['answer_url']:
                candidate=reconcile_owned_answer(kin,account,question_id,document)
                if candidate:
                    previous=json.loads(row['result'] or '{}');previous['reconciliation']=candidate
                    with db:
                        db.execute("UPDATE questions SET answer_id=?,answer_url=?,result=?,updated_at=? WHERE question_id=? AND account=? AND state='submitted_unverified' AND answer_id IS NULL AND answer_url IS NULL",
                                   (candidate['answerId'],candidate['answerUrl'],json.dumps(previous,ensure_ascii=False),kin._naver_pipeline_stamp(),question_id,account))
                    row=db.execute('SELECT * FROM questions WHERE question_id=?',(question_id,)).fetchone()
        if not row['answer_id'] or not row['answer_url']:
            return {'ok':False,'status':'held','reason':'Submission outcome unknown; no repeat click','clicked':clicked}
        evidence=public_evidence(account,row,document)
        if evidence.get('verified') is True and row['state']!='published_verified':kin.record_verification(db,question_id,evidence)
        kin.snapshot(db)
        result={'ok':evidence.get('verified') is True,'status':'observed' if evidence.get('verified') is True else 'held',
                'account':account,'questionId':question_id,'publicUrl':evidence.get('answer_url') if evidence.get('verified') is True else None,
                'publicVerified':evidence.get('verified') is True,'clicked':clicked,'originalSendDay':row['send_day'],
                'publicationVerified':evidence.get('verified') is True,'recoveryVerified':evidence.get('verified') is True,
                'httpStatus':evidence.get('httpStatus'),'linkPresentation':evidence.get('linkPresentation'),
                'reason':evidence.get('reason')}
        try:
            if remember(result):
                from common.crew_chat_bridge import emit_work_event
                emit_work_event(actor='patch',actor_label='패치',task_id='kin-repair:'+question_id,phase='completed',stage='recovery-verified',output_kind='지식iN 공개 답변·계정 확인 · '+('EGO 화면 단일 클릭 복구' if clicked else '기존 답변 확인, 재등록 없음'))
        except (OSError,ValueError,KeyError):result['learningStatus']='pending; publication evidence preserved'
        return result
    except (ValueError,RuntimeError,OSError) as exc:
        return {'ok':False,'status':'held','reason':type(exc).__name__+': '+str(exc)[:300],'clicked':clicked}
    finally:db.close()


def current_ownership(page,kin,account,url,question_id):
    response=page.context.request.get(url,timeout=15000)
    if response.status!=200:raise ValueError('Current question ownership unavailable')
    ownership=kin._naver_browser__parse_question_ownership(response.text(),account,question_id)
    if ownership.get('reason')=='question_answers_partially_loaded' and not ownership.get('answer_ids'):
        # The native complete inventory may navigate; never reload the prepared editor.
        probe=page.context.new_page()
        try:ownership=kin._naver_browser__question_ownership(probe,account,url)
        finally:probe.close()
    return ownership


def owned_answer_candidate(kin,html,account,question_id,document):
    import hashlib
    from types import SimpleNamespace
    from common.kin_answer_view import public_card_evidence
    ownership=kin._naver_browser__parse_question_ownership(html,account,question_id)
    soup=kin._naver_browser_BeautifulSoup(html,'html.parser');matches=[]
    for answer_id in ownership.get('verified_owned_answer_ids',[]):
        node=soup.select_one('#answer_'+answer_id)
        if node is None:continue
        raw=(kin._naver_browser__normalized(document['answer_text']) in kin._naver_browser__normalized(node.get_text('\n'))
             and document['attribution']['outboundUrl'] in {a.get('href') for a in node.select('a[href]')})
        card=public_card_evidence(SimpleNamespace(text=html,status_code=200),account,question_id,answer_id,document['answer_text'],document['attribution']['outboundUrl'])
        if raw or card:
            matches.append({'account':account,'questionId':question_id,'answerId':answer_id,
                'answerUrl':kin._naver_browser_exact_answer_url(document['question']['question_url'],answer_id),
                'source':'existing authenticated exact-question DOM; matching approved body + destination + native _myAnswer/owner controls',
                'sourceSha256':hashlib.sha256(html.encode()).hexdigest(),'resubmitted':False})
    return matches[0] if len(matches)==1 else None


def reconcile_owned_answer(kin,account,question_id,document):
    """Positive exact-account proof only; never click, navigate, or infer absence."""
    from playwright.sync_api import sync_playwright
    config=kin._naver_browser_account_config(account)
    with kin._naver_browser_account_lock(account),sync_playwright() as playwright,kin._naver_browser_awake_browser(playwright,config) as browser:
        candidates=[]
        for context in browser.contexts:
            for page in context.pages:
                if 'kin.naver.com/qna/detail.naver' not in page.url or kin.question_id(page.url)!=question_id:continue
                candidate=owned_answer_candidate(kin,page.content(),account,question_id,document)
                if candidate:candidates.append(candidate)
        unique={c['answerId']:c for c in candidates}
        return next(iter(unique.values())) if len(unique)==1 else None
